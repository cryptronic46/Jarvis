from pathlib import Path

from jarvis_web.backend.history_service import HistoryService
from jarvis_web.backend.session_store import SessionStore
from jarvis_web.tests.auth_helpers import make_authenticated_client


def test_slash_command_is_blocked_in_web_chat(tmp_path: Path) -> None:
    app, client = make_authenticated_client()
    try:
        store = SessionStore(tmp_path / "sessions.json")
        app.state.session_store = store
        app.state.history_service = HistoryService(store)

        session = client.post("/api/sessions").json()
        session_id = session["id"]

        response = client.post(
            "/api/chat",
            json={
                "message": "/mind status",
                "session_id": session_id,
            },
        )

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "core_command_blocked"

        detail = client.get(f"/api/sessions/{session_id}").json()
        assert detail["message_count"] == 0
    finally:
        client.__exit__(None, None, None)


def test_slash_command_is_blocked_in_stream_chat(tmp_path: Path) -> None:
    app, client = make_authenticated_client()
    try:
        store = SessionStore(tmp_path / "sessions.json")
        app.state.session_store = store
        app.state.history_service = HistoryService(store)

        session = client.post("/api/sessions").json()
        response = client.post(
            "/api/chat/stream",
            json={
                "message": "   /mind status",
                "session_id": session["id"],
            },
        )
        assert response.status_code == 403
    finally:
        client.__exit__(None, None, None)


def test_normal_conversation_about_commands_is_allowed(tmp_path: Path) -> None:
    app, client = make_authenticated_client()
    try:
        store = SessionStore(tmp_path / "sessions.json")
        app.state.session_store = store
        app.state.history_service = HistoryService(store)

        session = client.post("/api/sessions").json()
        response = client.post(
            "/api/chat",
            json={
                "message": "O que significa o comando /mind status?",
                "session_id": session["id"],
            },
        )
        assert response.status_code == 200
    finally:
        client.__exit__(None, None, None)
