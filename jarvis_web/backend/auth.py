from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import os
import secrets
import time
from uuid import uuid4


SESSION_COOKIE_NAME = "jarvis_local_session"
BOOTSTRAP_ENV_NAME = "JARVIS_BOOTSTRAP_TOKEN"

# Current Web/API scopes. Deliberately excludes any Core-control authority.
LOCAL_DESKTOP_SCOPES = frozenset(
    {
        "chat.read",
        "chat.write",
        "history.read",
        "history.write",
        "security.read",
        "security.manage_local",
        "home.read",
        "home.control",
    }
)


@dataclass(slots=True)
class SessionRecord:
    session_id: str
    device_id: str
    device_label: str
    trust_level: str
    scopes: frozenset[str]
    created_at: float
    expires_at: float
    last_seen_at: float
    step_up_until: float = 0.0

    def is_expired(self, now: float) -> bool:
        return now > self.expires_at

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


class LocalAuthManager:
    """Ephemeral authenticated browser sessions with explicit scopes.

    Security properties:
    - bootstrap token is one-time and short-lived;
    - browser token is random, HttpOnly and stored server-side only;
    - sessions are memory-only, so a service restart revokes all sessions;
    - session tokens never authorize raw Core-control operations;
    - normal Home capabilities are separate from Core/shell authority;
    - future remote/passkey sessions must be created by a separate flow.
    """

    def __init__(
        self,
        *,
        bootstrap_token: str | None = None,
        bootstrap_ttl_seconds: int = 60,
        session_ttl_seconds: int = 12 * 60 * 60,
    ) -> None:
        if bootstrap_token is not None:
            token = bootstrap_token
        else:
            token = os.environ.pop(
                BOOTSTRAP_ENV_NAME,
                None,
            )

        self._bootstrap_hash = self._digest(token) if token else None
        self._bootstrap_expires_at = (
            time.monotonic() + bootstrap_ttl_seconds if token else 0.0
        )
        self._session_ttl_seconds = session_ttl_seconds
        self._sessions: dict[str, SessionRecord] = {}

    @staticmethod
    def _digest(value: str) -> bytes:
        return hashlib.sha256(value.encode("utf-8")).digest()

    def consume_bootstrap(
        self,
        candidate: str,
        *,
        device_label: str = "Local Windows browser",
    ) -> tuple[str, SessionRecord] | None:
        if not candidate or self._bootstrap_hash is None:
            return None

        now = time.monotonic()
        if now > self._bootstrap_expires_at:
            self._bootstrap_hash = None
            return None

        if not hmac.compare_digest(
            self._digest(candidate),
            self._bootstrap_hash,
        ):
            return None

        # One-time bootstrap: invalidate before issuing the authenticated session.
        self._bootstrap_hash = None

        session_token = secrets.token_urlsafe(32)
        record = SessionRecord(
            session_id=str(uuid4()),
            device_id=str(uuid4()),
            device_label=device_label[:80] or "Local Windows browser",
            trust_level="local_desktop",
            scopes=LOCAL_DESKTOP_SCOPES,
            created_at=now,
            expires_at=now + self._session_ttl_seconds,
            last_seen_at=now,
        )
        self._sessions[session_token] = record
        return session_token, record

    def get_session(self, session_token: str | None) -> SessionRecord | None:
        if not session_token:
            return None

        record = self._sessions.get(session_token)
        if record is None:
            return None

        now = time.monotonic()
        if record.is_expired(now):
            self._sessions.pop(session_token, None)
            return None

        record.last_seen_at = now
        return record

    def validate_session(self, session_token: str | None) -> bool:
        return self.get_session(session_token) is not None

    def revoke_session(self, session_token: str | None) -> None:
        if session_token:
            self._sessions.pop(session_token, None)

    def revoke_session_id(self, session_id: str) -> bool:
        for token, record in list(self._sessions.items()):
            if record.session_id == session_id:
                self._sessions.pop(token, None)
                return True
        return False

    def revoke_all(self) -> int:
        count = len(self._sessions)
        self._sessions.clear()
        return count

    def list_sessions(self) -> list[dict]:
        now = time.monotonic()
        result: list[dict] = []

        for token, record in list(self._sessions.items()):
            if record.is_expired(now):
                self._sessions.pop(token, None)
                continue

            result.append(
                {
                    "session_id": record.session_id,
                    "device_id": record.device_id,
                    "device_label": record.device_label,
                    "trust_level": record.trust_level,
                    "scopes": sorted(record.scopes),
                    "expires_in_seconds": max(0, int(record.expires_at - now)),
                    "last_seen_seconds_ago": max(0, int(now - record.last_seen_at)),
                }
            )

        return result
