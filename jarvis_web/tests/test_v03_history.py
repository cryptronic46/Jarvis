from pathlib import Path

from fastapi.testclient import TestClient

from jarvis_web.backend.app import create_app
from jarvis_web.backend.history_service import HistoryService
from jarvis_web.backend.session_store import SessionStore
from jarvis_web.tests.auth_helpers import make_authenticated_client


def test_history_search_finds_old_message(tmp_path: Path) -> None:
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
                "message": "Falámos sobre Home Assistant e sensores de humidade",
                "session_id": session_id,
            },
        )
        assert response.status_code == 200

        search = client.get("/api/history/search", params={"q": "humidade"})
        assert search.status_code == 200
        payload = search.json()
        assert payload["hits"]
        assert payload["hits"][0]["session_id"] == session_id
        assert "humidade" in payload["hits"][0]["snippet"].lower()
    finally:
        client.__exit__(None, None, None)


def test_history_search_rejects_too_short_query() -> None:
    app, client = make_authenticated_client()
    try:
        response = client.get("/api/history/search", params={"q": "a"})
        assert response.status_code == 422
    finally:
        client.__exit__(None, None, None)
