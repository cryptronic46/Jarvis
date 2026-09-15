from fastapi.testclient import TestClient
import pytest

from jarvis_web.backend.app import create_app


def test_rejects_untrusted_host() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/health", headers={"Host": "evil.example"})
        assert response.status_code == 400


def test_rejects_untrusted_origin_even_for_simple_post() -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/sessions",
            headers={
                "Origin": "https://evil.example",
                "Content-Type": "text/plain",
            },
        )
        assert response.status_code == 403


def test_websocket_rejects_untrusted_origin() -> None:
    with TestClient(create_app()) as client:
        with pytest.raises(Exception):
            with client.websocket_connect(
                "/api/events",
                headers={"Origin": "https://evil.example"},
            ):
                pass


def test_security_headers_present() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/health")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_docs_disabled_in_normal_runtime() -> None:
    with TestClient(create_app()) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404



def test_env_cannot_enable_production_docs(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_DEV_MODE", "true")
    with TestClient(create_app()) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404



def test_reserved_server_paths_do_not_fall_through_to_spa() -> None:
    with TestClient(create_app()) as client:
        for path in ("/docs", "/openapi.json", "/redoc"):
            response = client.get(path)
            assert response.status_code == 404
            assert "text/html" not in response.headers.get("content-type", "")
