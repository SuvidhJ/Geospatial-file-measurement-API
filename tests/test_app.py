from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
