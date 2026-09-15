from pathlib import Path

from fastapi.testclient import TestClient

from jarvis_web.backend.adapters.mock import MockJarvisCoreAdapter
from jarvis_web.backend.app import create_app
from jarvis_web.backend.session_store import SessionStore
from jarvis_web.tests.auth_helpers import make_authenticated_client


def test_create_app_accepts_explicit_core_adapter() -> None:
    adapter = MockJarvisCoreAdapter()

    app = create_app(
        core_adapter=adapter,
    )

    with TestClient(app):
        assert app.state.core_adapter is adapter


def test_health() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_status_is_local_only() -> None:
    app, client = make_authenticated_client()
    try:
        response = client.get("/api/status")
        assert response.status_code == 200
        payload = response.json()
        assert payload["adapter"] == "mock"
        assert payload["local_only"] is True
    finally:
        client.__exit__(None, None, None)


def test_chat_uses_mock_adapter(tmp_path: Path) -> None:
    app, client = make_authenticated_client()
    try:
        app.state.session_store = SessionStore(tmp_path / "sessions.json")
        response = client.post(
            "/api/chat",
            json={"message": "Olá Jarvis", "session_id": "test-session"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["session_id"] == "test-session"
        assert payload["provider"] == "mock"
        assert "Olá Jarvis" in payload["answer"]
    finally:
        client.__exit__(None, None, None)


def test_chat_rejects_empty_message() -> None:
    app, client = make_authenticated_client()
    try:
        response = client.post("/api/chat", json={"message": ""})
        assert response.status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_websocket_ready_event() -> None:
    app, client = make_authenticated_client()
    try:
        with client.websocket_connect(
            "/api/events",
            headers={"Origin": "http://127.0.0.1:8766"},
        ) as websocket:
            payload = websocket.receive_json()
            assert payload["type"] == "jarvis.ready"
    finally:
        client.__exit__(None, None, None)
