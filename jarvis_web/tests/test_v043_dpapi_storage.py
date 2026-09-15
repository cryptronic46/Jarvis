import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jarvis_web.backend.app import create_app
from jarvis_web.backend.session_store import SessionStorageError, SessionStore
from jarvis_web.backend.storage_protection import NoOpAclHardener, TestOnlyProtector
from jarvis_web.tests.auth_helpers import make_authenticated_client


def _store(path: Path, *, legacy_path: Path | None = None) -> SessionStore:
    return SessionStore(
        path,
        protector=TestOnlyProtector(),
        acl_hardener=NoOpAclHardener(),
        legacy_path=legacy_path,
    )


def test_encrypted_store_does_not_contain_plaintext_title_or_message(tmp_path: Path) -> None:
    path = tmp_path / "sessions.dpapi"
    store = _store(path)

    session = asyncio.run(store.create(title="Projeto Ultra Secreto"))
    asyncio.run(
        store.append_message(
            session["id"],
            "user",
            "Mensagem confidencial que não deve aparecer no disco em claro",
        )
    )

    raw = path.read_bytes()
    assert raw.startswith(SessionStore.ENVELOPE_MAGIC)
    assert b"Projeto Ultra Secreto" not in raw
    assert b"Mensagem confidencial" not in raw


def test_encrypted_store_survives_reload(tmp_path: Path) -> None:
    path = tmp_path / "sessions.dpapi"
    store = _store(path)
    session = asyncio.run(store.create(title="Nome Persistente Encriptado"))

    reloaded = _store(path)
    fetched = asyncio.run(reloaded.get(session["id"]))
    assert fetched["title"] == "Nome Persistente Encriptado"


def test_legacy_plaintext_migrates_and_is_removed_only_after_verification(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "sessions.json"
    encrypted = tmp_path / "sessions.dpapi"

    legacy_payload = {
        "session-1": {
            "id": "session-1",
            "title": "Chat Antigo Preservado",
            "created_at": "2026-09-04T10:00:00+00:00",
            "updated_at": "2026-09-04T10:00:00+00:00",
            "messages": [],
        }
    }
    legacy.write_text(
        json.dumps(legacy_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    store = _store(encrypted, legacy_path=legacy)

    assert encrypted.exists()
    assert not legacy.exists()
    assert b"Chat Antigo Preservado" not in encrypted.read_bytes()
    assert asyncio.run(store.get("session-1"))["title"] == "Chat Antigo Preservado"

    reloaded = _store(encrypted, legacy_path=legacy)
    assert asyncio.run(reloaded.get("session-1"))["title"] == "Chat Antigo Preservado"


def test_corrupt_encrypted_history_fails_closed_without_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "sessions.dpapi"
    path.write_bytes(SessionStore.ENVELOPE_MAGIC + b"corrupt")
    original = path.read_bytes()

    with pytest.raises(SessionStorageError):
        _store(path)

    assert path.read_bytes() == original


def test_invalid_legacy_plaintext_is_not_deleted(tmp_path: Path) -> None:
    legacy = tmp_path / "sessions.json"
    encrypted = tmp_path / "sessions.dpapi"
    legacy.write_text("{not-json", encoding="utf-8")

    with pytest.raises(SessionStorageError):
        _store(encrypted, legacy_path=legacy)

    assert legacy.exists()
    assert not encrypted.exists()


def test_authenticated_storage_status_exposes_protection_state(tmp_path: Path) -> None:
    app, client = make_authenticated_client()
    try:
        store = _store(tmp_path / "sessions.dpapi")
        app.state.session_store = store

        response = client.get("/api/security/storage-status")
        assert response.status_code == 200
        payload = response.json()
        assert payload["encrypted_at_rest"] is True
        assert payload["acl_hardened"] is True
        assert payload["legacy_plaintext_present"] is False
    finally:
        client.__exit__(None, None, None)
