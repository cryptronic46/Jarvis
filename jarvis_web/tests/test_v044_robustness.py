from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from jarvis_web.backend.security import RequestBodyLimitMiddleware, SuspiciousPathGuardMiddleware
from jarvis_web.backend.session_store import SessionStore
from jarvis_web.backend.storage_protection import (
    NoOpAclHardener,
    StorageProtectionError,
    TestOnlyProtector,
)
from jarvis_web.tests.auth_helpers import make_authenticated_client


def _store(path: Path) -> SessionStore:
    return SessionStore(
        path,
        protector=TestOnlyProtector(),
        acl_hardener=NoOpAclHardener(),
        legacy_path=None,
    )


@pytest.mark.parametrize(
    "value",
    [
        "/%252525252525252e%252525252525252e/Windows/win.ini",
        "/%255c%255c..%255cWindows",
        "/..%255c..%255cWindows",
        "/%00",
        "/file.txt%3Asecret",
        "/" + "a" * 5000,
    ],
)
def test_path_fuzz_is_rejected(value: str) -> None:
    assert SuspiciousPathGuardMiddleware._is_suspicious(value)


def test_normal_unicode_path_is_not_falsely_rejected() -> None:
    assert not SuspiciousPathGuardMiddleware._is_suspicious(
        "/conversa/Olá-ação-日本語"
    )


@pytest.mark.parametrize(
    "body,content_type",
    [
        (b"{", "application/json"),
        (b'{"message":', "application/json"),
        (b"\xff\xfe\xfa", "application/json"),
        (b"null", "application/json"),
        (b"[]", "application/json"),
        (b'{"message":""}', "application/json"),
        (b'{"message":1}', "application/json"),
    ],
)
def test_malformed_chat_payloads_never_return_500(body: bytes, content_type: str) -> None:
    app, client = make_authenticated_client()
    try:
        response = client.post(
            "/api/chat",
            content=body,
            headers={"Content-Type": content_type},
        )
        assert response.status_code in {400, 403, 415, 422}
    finally:
        client.__exit__(None, None, None)


@pytest.mark.parametrize(
    "message",
    [
        "Olá 👩🏽‍💻🚀",
        "texto com RTL \u202eABC\u202c controlado",
        "combining e\u0301 e\u0308",
        "日本語 العربية кириллица",
        "<script>alert('x')</script>",
        "${jndi:ldap://127.0.0.1/x}",
    ],
)
def test_unicode_and_markup_chat_inputs_do_not_crash(message: str) -> None:
    app, client = make_authenticated_client()
    try:
        response = client.post("/api/chat", json={"message": message})
        assert response.status_code in {200, 403, 422}
        assert response.status_code != 500
    finally:
        client.__exit__(None, None, None)


def test_title_boundaries_and_whitespace() -> None:
    app, client = make_authenticated_client()
    try:
        created = client.post("/api/sessions").json()
        sid = created["id"]

        ok = client.patch(f"/api/sessions/{sid}", json={"title": "A" * 80})
        assert ok.status_code == 200

        too_long = client.patch(f"/api/sessions/{sid}", json={"title": "B" * 81})
        assert too_long.status_code == 422

        whitespace = client.patch(f"/api/sessions/{sid}", json={"title": "   "})
        assert whitespace.status_code == 422
    finally:
        client.__exit__(None, None, None)


def test_concurrent_appends_preserve_all_messages(tmp_path: Path) -> None:
    async def scenario():
        store = _store(tmp_path / "sessions.dpapi")
        session = await store.create(title="Concurrent")

        total = 160
        await asyncio.gather(
            *[
                store.append_message(session["id"], "user", f"message-{i}")
                for i in range(total)
            ]
        )

        current = await store.get(session["id"])
        contents = [m["content"] for m in current["messages"]]
        assert len(contents) == total
        assert set(contents) == {f"message-{i}" for i in range(total)}

        reloaded = _store(tmp_path / "sessions.dpapi")
        again = await reloaded.get(session["id"])
        assert len(again["messages"]) == total

    asyncio.run(scenario())


def test_concurrent_create_ids_are_unique_and_reloadable(tmp_path: Path) -> None:
    async def scenario():
        store = _store(tmp_path / "sessions.dpapi")
        created = await asyncio.gather(
            *[store.create(title=f"session-{i}") for i in range(80)]
        )
        ids = {item["id"] for item in created}
        assert len(ids) == 80

        reloaded = _store(tmp_path / "sessions.dpapi")
        summaries = await reloaded.list()
        assert len(summaries) == 80

    asyncio.run(scenario())


def test_mixed_rename_append_race_remains_consistent(tmp_path: Path) -> None:
    async def scenario():
        store = _store(tmp_path / "sessions.dpapi")
        session = await store.create(title="Start")
        titles = [f"Rename-{i}" for i in range(40)]

        tasks = [
            *(store.rename(session["id"], title) for title in titles),
            *(
                store.append_message(session["id"], "user", f"msg-{i}")
                for i in range(100)
            ),
        ]
        await asyncio.gather(*tasks)

        current = await store.get(session["id"])
        assert current["title"] in titles
        assert len(current["messages"]) == 100

        reloaded = _store(tmp_path / "sessions.dpapi")
        persisted = await reloaded.get(session["id"])
        assert persisted["title"] == current["title"]
        assert len(persisted["messages"]) == 100

    asyncio.run(scenario())


def test_replace_failure_rolls_memory_and_disk_back(tmp_path: Path) -> None:
    async def scenario():
        path = tmp_path / "sessions.dpapi"
        store = _store(path)
        session = await store.create(title="Before")
        original_bytes = path.read_bytes()

        with patch("jarvis_web.backend.session_store.os.replace", side_effect=OSError("simulated replace failure")):
            with pytest.raises(OSError):
                await store.rename(session["id"], "Must Not Leak")

        assert path.read_bytes() == original_bytes
        assert (await store.get(session["id"]))["title"] == "Before"
        assert not path.with_name(path.name + ".tmp").exists()

    asyncio.run(scenario())


def test_fsync_failure_rolls_memory_and_disk_back(tmp_path: Path) -> None:
    async def scenario():
        path = tmp_path / "sessions.dpapi"
        store = _store(path)
        session = await store.create(title="Stable")
        original_bytes = path.read_bytes()

        with patch("jarvis_web.backend.session_store.os.fsync", side_effect=OSError("simulated disk full/fsync failure")):
            with pytest.raises(OSError):
                await store.append_message(session["id"], "user", "must rollback")

        assert path.read_bytes() == original_bytes
        assert (await store.get(session["id"]))["messages"] == []
        assert not path.with_name(path.name + ".tmp").exists()

    asyncio.run(scenario())


class _FailingProtector:
    name = "intentional-failure"

    def protect(self, plaintext: bytes) -> bytes:
        raise StorageProtectionError("simulated DPAPI failure")

    def unprotect(self, ciphertext: bytes) -> bytes:
        raise StorageProtectionError("simulated DPAPI failure")


def test_encryption_failure_does_not_create_partial_history(tmp_path: Path) -> None:
    async def scenario():
        path = tmp_path / "sessions.dpapi"
        store = SessionStore(
            path,
            protector=_FailingProtector(),
            acl_hardener=NoOpAclHardener(),
            legacy_path=None,
        )

        with pytest.raises(StorageProtectionError):
            await store.create(title="Never committed")

        assert not path.exists()
        assert await store.list() == []

    asyncio.run(scenario())


def test_delete_failure_rolls_back_in_memory(tmp_path: Path) -> None:
    async def scenario():
        path = tmp_path / "sessions.dpapi"
        store = _store(path)
        session = await store.create(title="Keep me")

        with patch("jarvis_web.backend.session_store.os.replace", side_effect=OSError("simulated replace failure")):
            with pytest.raises(OSError):
                await store.delete(session["id"])

        assert (await store.get(session["id"]))["title"] == "Keep me"

    asyncio.run(scenario())


def test_actual_chunked_body_over_limit_is_rejected_without_content_length() -> None:
    async def scenario():
        called = False

        async def downstream(scope, receive, send):
            nonlocal called
            called = True
            # Read until middleware rejects.
            while True:
                message = await receive()
                if not message.get("more_body", False):
                    break

        middleware = RequestBodyLimitMiddleware(downstream)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/chat",
            "headers": [(b"content-type", b"application/json")],
        }

        chunks = [
            {
                "type": "http.request",
                "body": b"A" * (RequestBodyLimitMiddleware.MAX_API_BODY_BYTES // 2),
                "more_body": True,
            },
            {
                "type": "http.request",
                "body": b"B" * (RequestBodyLimitMiddleware.MAX_API_BODY_BYTES // 2 + 1),
                "more_body": False,
            },
        ]

        async def receive():
            return chunks.pop(0)

        sent = []

        async def send(message):
            sent.append(message)

        await middleware(scope, receive, send)

        assert called is True
        starts = [m for m in sent if m["type"] == "http.response.start"]
        assert len(starts) == 1
        assert starts[0]["status"] == 413

    asyncio.run(scenario())


def test_chunked_body_at_limit_is_allowed() -> None:
    async def scenario():
        downstream_completed = False

        async def downstream(scope, receive, send):
            nonlocal downstream_completed
            total = 0
            while True:
                message = await receive()
                total += len(message.get("body", b""))
                if not message.get("more_body", False):
                    break
            assert total == RequestBodyLimitMiddleware.MAX_API_BODY_BYTES
            downstream_completed = True

        middleware = RequestBodyLimitMiddleware(downstream)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/chat",
            "headers": [],
        }
        chunks = [
            {
                "type": "http.request",
                "body": b"A" * 1000,
                "more_body": True,
            },
            {
                "type": "http.request",
                "body": b"B" * (RequestBodyLimitMiddleware.MAX_API_BODY_BYTES - 1000),
                "more_body": False,
            },
        ]

        async def receive():
            return chunks.pop(0)

        async def send(message):
            pass

        await middleware(scope, receive, send)
        assert downstream_completed

    asyncio.run(scenario())
