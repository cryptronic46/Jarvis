from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
from uuid import uuid4

from jarvis_web.backend.models import utc_now_iso
from jarvis_web.backend.storage_protection import (
    DataProtector,
    DirectoryAclHardener,
    StorageProtectionError,
    build_default_acl_hardener,
    build_default_protector,
)


class SessionNotFoundError(KeyError):
    pass


class SessionStorageError(StorageProtectionError):
    pass


class SessionStore:
    """Encrypted local conversation-history store.

    This remains Conversation History, not the official JARVIS Memory system.

    Production Windows storage:
    - DPAPI CURRENT USER encryption;
    - JARVIS-specific optional entropy;
    - private data-directory ACL;
    - atomic encrypted writes;
    - fail-closed on corrupt/unreadable encrypted history;
    - one-time migration from legacy plaintext data/sessions.json.
    """

    ENVELOPE_MAGIC = b"JARVIS-WEB-DPAPI-HISTORY-V1\n"

    def __init__(
        self,
        path: Path | None = None,
        *,
        protector: DataProtector | None = None,
        acl_hardener: DirectoryAclHardener | None = None,
        legacy_path: Path | None = None,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        default_path = root / "data" / "sessions.dpapi"
        default_legacy_path = root / "data" / "sessions.json"

        configured = os.getenv("JARVIS_WEB_SESSION_FILE")

        # Tests must never silently attach to the user's real conversation
        # history. Every pytest invocation must either inject an explicit path
        # or receive the per-test temporary path from tests/conftest.py.
        if (
            "PYTEST_CURRENT_TEST" in os.environ
            and path is None
            and not configured
        ):
            raise SessionStorageError(
                "Refusing to use production conversation storage during pytest"
            )

        self.path = path or Path(configured) if configured else (path or default_path)

        # Automatic legacy migration is used for the standard production path.
        self.legacy_path = (
            legacy_path
            if legacy_path is not None
            else (default_legacy_path if path is None and configured is None else None)
        )

        self._protector = protector or build_default_protector()
        self._acl_hardener = acl_hardener or build_default_acl_hardener()
        self._lock = asyncio.Lock()
        self._sessions: dict[str, dict] = {}

        self._acl_hardener.harden(self.path.parent)
        self._load_or_migrate()

    @property
    def protection_name(self) -> str:
        return self._protector.name

    @property
    def acl_name(self) -> str:
        return self._acl_hardener.name

    def security_status(self) -> dict[str, object]:
        return {
            "encrypted_at_rest": True,
            "protector": self.protection_name,
            "acl_hardened": True,
            "acl_policy": self.acl_name,
            "legacy_plaintext_present": bool(
                self.legacy_path and self.legacy_path.exists()
            ),
            "storage_filename": self.path.name,
        }

    def _decode_encrypted_file(self, raw: bytes) -> dict[str, dict]:
        if not raw.startswith(self.ENVELOPE_MAGIC):
            raise SessionStorageError(
                "Encrypted JARVIS history has an invalid storage envelope"
            )

        encrypted = raw[len(self.ENVELOPE_MAGIC):]
        if not encrypted:
            raise SessionStorageError("Encrypted JARVIS history is empty")

        try:
            plaintext = self._protector.unprotect(encrypted)
            payload = json.loads(plaintext.decode("utf-8"))
        except (StorageProtectionError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SessionStorageError(
                "JARVIS conversation history could not be decrypted/decoded; "
                "storage was left untouched"
            ) from exc

        if not isinstance(payload, dict):
            raise SessionStorageError("Invalid JARVIS conversation-history payload")

        return payload

    def _read_legacy_plaintext(self, path: Path) -> dict[str, dict]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SessionStorageError(
                "Legacy plaintext conversation history is unreadable; "
                "migration was aborted and the source file was left untouched"
            ) from exc

        if not isinstance(payload, dict):
            raise SessionStorageError(
                "Legacy plaintext conversation history has an invalid payload"
            )
        return payload

    def _load_or_migrate(self) -> None:
        if self.path.exists():
            try:
                self._sessions = self._decode_encrypted_file(self.path.read_bytes())
            except OSError as exc:
                raise SessionStorageError(
                    "Encrypted JARVIS history could not be read"
                ) from exc
            return

        if self.legacy_path is None or not self.legacy_path.exists():
            return

        # One-time migration: read legacy JSON, create + verify encrypted target,
        # and only then remove the plaintext source.
        migrated = self._read_legacy_plaintext(self.legacy_path)
        self._sessions = migrated
        self._save_unlocked()

        # Verify a fresh read/decrypt before deleting the plaintext source.
        verified = self._decode_encrypted_file(self.path.read_bytes())
        if verified != migrated:
            raise SessionStorageError(
                "Encrypted-history migration verification failed; "
                "legacy plaintext was left untouched"
            )

        try:
            self.legacy_path.unlink()
        except OSError as exc:
            # Fail closed: do not silently continue while plaintext history remains.
            raise SessionStorageError(
                "Encrypted migration succeeded, but legacy plaintext could not "
                "be removed. JARVIS Web will not continue with duplicate plaintext."
            ) from exc

    def _serialize(self) -> bytes:
        return json.dumps(
            self._sessions,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

    def _save_unlocked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._acl_hardener.harden(self.path.parent)

        try:
            encrypted = self._protector.protect(self._serialize())
        except StorageProtectionError as exc:
            raise SessionStorageError("Could not encrypt JARVIS history") from exc

        target = self.ENVELOPE_MAGIC + encrypted
        temp = self.path.with_name(self.path.name + ".tmp")

        try:
            with temp.open("wb") as handle:
                handle.write(target)
                handle.flush()
                os.fsync(handle.fileno())

            # Verify the complete temporary file before atomically replacing the
            # current encrypted history.
            verified = self._decode_encrypted_file(temp.read_bytes())
            if verified != self._sessions:
                raise SessionStorageError(
                    "Encrypted temporary history failed verification"
                )

            os.replace(temp, self.path)
        except Exception:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _save_transactional_unlocked(self, before: dict[str, dict]) -> None:
        """Persist the current in-memory state or roll it back completely.

        A storage failure must never leave memory ahead of disk. Without this,
        a failed rename/append/delete could be reported as failed to the caller
        but then be persisted accidentally by a later successful operation.
        """
        try:
            self._save_unlocked()
        except Exception:
            self._sessions = before
            raise

    @staticmethod
    def _summary(session: dict) -> dict:
        return {
            "id": session["id"],
            "title": session["title"],
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
            "message_count": len(session.get("messages", [])),
        }

    async def create(
        self,
        title: str = "Nova conversa",
        session_id: str | None = None,
    ) -> dict:
        async with self._lock:
            before = deepcopy(self._sessions)
            now = utc_now_iso()
            session_id = session_id or str(uuid4())
            session = {
                "id": session_id,
                "title": title[:80] or "Nova conversa",
                "created_at": now,
                "updated_at": now,
                "messages": [],
            }
            self._sessions[session_id] = session
            self._save_transactional_unlocked(before)
            return deepcopy(session)

    async def list(self) -> list[dict]:
        async with self._lock:
            items = [self._summary(s) for s in self._sessions.values()]
            items.sort(key=lambda item: item["updated_at"], reverse=True)
            return deepcopy(items)

    async def get(self, session_id: str) -> dict:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            return deepcopy(session)

    async def append_message(self, session_id: str, role: str, content: str) -> dict:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)

            before = deepcopy(self._sessions)
            now = utc_now_iso()
            message = {
                "id": str(uuid4()),
                "role": role,
                "content": content,
                "created_at": now,
            }
            session.setdefault("messages", []).append(message)
            session["updated_at"] = now

            if role == "user" and session["title"] == "Nova conversa":
                compact = " ".join(content.split())
                session["title"] = (
                    (compact[:55] + "…") if len(compact) > 56 else compact
                )
                if not session["title"]:
                    session["title"] = "Nova conversa"

            self._save_transactional_unlocked(before)
            return deepcopy(message)

    async def rename(self, session_id: str, title: str) -> dict:
        clean = " ".join(title.split()).strip()
        if not clean:
            raise ValueError("Session title cannot be empty")

        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)

            before = deepcopy(self._sessions)
            session["title"] = clean[:80]
            session["updated_at"] = utc_now_iso()
            self._save_transactional_unlocked(before)
            return deepcopy(session)

    async def delete(self, session_id: str) -> None:
        async with self._lock:
            if session_id not in self._sessions:
                raise SessionNotFoundError(session_id)
            before = deepcopy(self._sessions)
            del self._sessions[session_id]
            self._save_transactional_unlocked(before)
