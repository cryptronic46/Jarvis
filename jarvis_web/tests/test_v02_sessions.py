from pathlib import Path

from jarvis_web.backend.history_service import HistoryService
from jarvis_web.backend.session_store import SessionStore
from jarvis_web.tests.auth_helpers import make_authenticated_client


def _client_with_temp_store(tmp_path: Path):
    app, client = make_authenticated_client()
    store = SessionStore(tmp_path / "sessions.json")
    app.state.session_store = store
    app.state.history_service = HistoryService(store)
    return app, client


def test_session_create_list_get_delete(tmp_path: Path) -> None:
    _, client = _client_with_temp_store(tmp_path)
    try:
        created = client.post("/api/sessions")
        assert created.status_code == 201
        session = created.json()
        session_id = session["id"]
        assert session["title"] == "Nova conversa"

        listed = client.get("/api/sessions")
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == session_id

        fetched = client.get(f"/api/sessions/{session_id}")
        assert fetched.status_code == 200
        assert fetched.json()["messages"] == []

        deleted = client.delete(f"/api/sessions/{session_id}")
        assert deleted.status_code == 204

        missing = client.get(f"/api/sessions/{session_id}")
        assert missing.status_code == 404
    finally:
        client.__exit__(None, None, None)


def test_chat_persists_messages_and_titles_session(tmp_path: Path) -> None:
    _, client = _client_with_temp_store(tmp_path)
    try:
        created = client.post("/api/sessions").json()
        session_id = created["id"]

        response = client.post(
            "/api/chat",
            json={
                "message": "Explica o estado da nova interface",
                "session_id": session_id,
            },
        )
        assert response.status_code == 200

        detail = client.get(f"/api/sessions/{session_id}").json()
        assert detail["message_count"] == 2
        assert detail["messages"][0]["role"] == "user"
        assert detail["messages"][1]["role"] == "assistant"
        assert detail["title"].startswith("Explica o estado")
    finally:
        client.__exit__(None, None, None)


def test_stream_chat_returns_meta_deltas_and_done(tmp_path: Path) -> None:
    _, client = _client_with_temp_store(tmp_path)
    try:
        created = client.post("/api/sessions").json()
        session_id = created["id"]

        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"message": "Olá streaming", "session_id": session_id},
        ) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

        assert '"type": "meta"' in body
        assert '"type": "delta"' in body
        assert '"type": "done"' in body
        assert session_id in body
    finally:
        client.__exit__(None, None, None)



def test_session_can_be_renamed(tmp_path: Path) -> None:
    _, client = _client_with_temp_store(tmp_path)
    try:
        created = client.post("/api/sessions").json()
        session_id = created["id"]

        renamed = client.patch(
            f"/api/sessions/{session_id}",
            json={"title": "Projeto Home Assistant"},
        )
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "Projeto Home Assistant"

        fetched = client.get(f"/api/sessions/{session_id}")
        assert fetched.json()["title"] == "Projeto Home Assistant"
    finally:
        client.__exit__(None, None, None)



def test_session_rename_survives_store_reload(tmp_path: Path) -> None:
    import asyncio

    app, client = make_authenticated_client()
    session_file = tmp_path / "sessions.json"

    try:
        store = SessionStore(session_file)
        app.state.session_store = store
        app.state.history_service = HistoryService(store)

        created = client.post("/api/sessions").json()
        session_id = created["id"]

        renamed = client.patch(
            f"/api/sessions/{session_id}",
            json={"title": "Nome Persistente"},
        )
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "Nome Persistente"

        # Simulate a full service restart by loading a fresh store from disk.
        reloaded = SessionStore(session_file)
        persisted = asyncio.run(reloaded.get(session_id))
        assert persisted["title"] == "Nome Persistente"
    finally:
        client.__exit__(None, None, None)
