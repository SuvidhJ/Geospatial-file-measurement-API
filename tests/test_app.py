from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "queue": "in-process"}


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert set(response.json()["error"]) == {"code", "message", "details"}


def test_viewer_is_served(client: TestClient) -> None:
    response = client.get("/viewer/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "/api/files/" in response.text


def test_root_redirects_to_viewer(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/viewer/"


def test_response_carries_a_generated_request_id(client: TestClient) -> None:
    request_id = client.get("/health").headers["x-request-id"]

    assert len(request_id) == 32


def test_safe_client_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "survey-42.retry_1"})

    assert response.headers["x-request-id"] == "survey-42.retry_1"


def test_unsafe_client_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "x\tforged log line"})

    assert response.headers["x-request-id"] != "x\tforged log line"
    assert len(response.headers["x-request-id"]) == 32
