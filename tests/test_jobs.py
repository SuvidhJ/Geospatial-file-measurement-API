"""Redis/RQ dispatch, run synchronously against an in-memory Redis."""

from pathlib import Path

import pytest
from fakeredis import FakeRedis
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from rq import Queue

from app.config import Settings
from app.main import create_app
from app.services import jobs
from tests.factories import kml_document, kml_point, placemark

KML = kml_document({"Points": [placemark("GCP-1", kml_point(77.59, 12.97))]}).encode()


@pytest.fixture
def redis_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    data_dir = tmp_path / "data"
    # The worker builds its own Settings from the environment, as it would in production.
    monkeypatch.setenv("GEOAPI_DATA_DIR", str(data_dir))
    return Settings(data_dir=data_dir, redis_url="redis://queue.test:6379/0")


def test_queued_upload_is_processed_by_the_worker_job(
    redis_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = FakeRedis()
    monkeypatch.setattr(
        jobs,
        "get_queue",
        lambda _url: Queue(jobs.QUEUE_NAME, connection=connection, is_async=False),
    )
    with TestClient(create_app(redis_settings)) as client:
        response = client.post(
            "/api/files/", params={"wait": "false"}, files={"file": ("gcp.kml", KML)}
        )
        record = client.get(f"/api/files/{response.json()['id']}/").json()
        health = client.get("/health").json()

    assert response.status_code == 202
    assert record["status"] == "COMPLETED"
    assert record["feature_count"] == 1
    assert health["queue"] == "redis"


def test_unreachable_queue_returns_503_and_marks_file_failed(
    redis_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreachable(_url: str) -> Queue:
        raise RedisConnectionError("connection refused")

    monkeypatch.setattr(jobs, "get_queue", unreachable)
    with TestClient(create_app(redis_settings)) as client:
        response = client.post(
            "/api/files/", params={"wait": "false"}, files={"file": ("gcp.kml", KML)}
        )
        file_id = response.json()["error"]["details"]["file_id"]
        record = client.get(f"/api/files/{file_id}/").json()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "QUEUE_UNAVAILABLE"
    assert record["status"] == "FAILED"
    assert record["error_detail"] == "The processing queue was unavailable."


def test_synchronous_uploads_do_not_touch_the_queue(
    redis_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_if_called(_url: str) -> Queue:
        raise AssertionError("queue used for a synchronous upload")

    monkeypatch.setattr(jobs, "get_queue", fail_if_called)
    with TestClient(create_app(redis_settings)) as client:
        response = client.post("/api/files/", files={"file": ("gcp.kml", KML)})

    assert response.status_code == 201
