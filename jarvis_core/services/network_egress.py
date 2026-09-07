from __future__ import annotations

import ipaddress
import socket
from secrets import token_hex
from threading import RLock
from time import monotonic
from typing import Any
from urllib.parse import urlparse


class NetworkEgressError(RuntimeError):
    pass


def _resolved_ips(host: str) -> set[ipaddress._BaseAddress]:
    raw = str(host or "").strip().lower()
    if not raw:
        raise NetworkEgressError("NETWORK_HOST_REQUIRED")

    if raw == "localhost":
        return {
            ipaddress.ip_address("127.0.0.1"),
            ipaddress.ip_address("::1"),
        }

    try:
        return {ipaddress.ip_address(raw.split("%", 1)[0])}
    except ValueError:
        pass

    try:
        rows = socket.getaddrinfo(raw, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise NetworkEgressError("NETWORK_HOST_RESOLUTION_FAILED") from exc

    values = set()
    for row in rows:
        try:
            values.add(
                ipaddress.ip_address(
                    str(row[4][0]).split("%", 1)[0]
                )
            )
        except (ValueError, IndexError):
            continue

    if not values:
        raise NetworkEgressError("NETWORK_HOST_RESOLUTION_FAILED")

    return values


def require_loopback_url(url: str) -> str:
    value = str(url or "").strip()
    parsed = urlparse(value)

    if parsed.scheme not in {"http", "https"}:
        raise NetworkEgressError("LOOPBACK_HTTP_REQUIRED")

    if not parsed.hostname:
        raise NetworkEgressError("NETWORK_HOST_REQUIRED")

    addresses = _resolved_ips(parsed.hostname)

    if not addresses or not all(ip.is_loopback for ip in addresses):
        raise NetworkEgressError("NON_LOOPBACK_TARGET_BLOCKED")

    return value


def _public_target(url: str) -> tuple[str, set[ipaddress._BaseAddress]]:
    value = str(url or "").strip()
    parsed = urlparse(value)

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise NetworkEgressError("INVALID_PUBLIC_WEB_URL")

    addresses = _resolved_ips(parsed.hostname)

    if any(
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
        for ip in addresses
    ):
        raise NetworkEgressError("PUBLIC_WEB_TARGET_NOT_PUBLIC")

    return parsed.hostname.lower(), addresses


class NetworkEgressGate:
    def __init__(self, guardian: Any = None) -> None:
        self.guardian = guardian
        self._lock = RLock()
        self._sessions: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _mode(purpose: str) -> str:
        return (
            "learning"
            if str(purpose or "").strip().lower() == "learning"
            else "research"
        )

    def _standing_allowed(self, purpose: str) -> bool:
        guardian = self.guardian
        if guardian is None:
            return False

        try:
            if self._mode(purpose) == "learning":
                return bool(
                    guardian.has_standing_public_web_learning()
                )
            return bool(
                guardian.has_standing_public_web_research()
            )
        except Exception:
            return False

    def open_public_web_session(
        self,
        *,
        purpose: str,
        capability: str,
        payload: dict[str, Any],
        execution_token: str = "",
    ) -> dict[str, Any]:
        mode = self._mode(purpose)
        expected_capability = (
            "external_learning"
            if mode == "learning"
            else "web_research"
        )

        if str(capability or "").strip() != expected_capability:
            return {
                "ok": False,
                "allowed": False,
                "error": "PUBLIC_WEB_CAPABILITY_MISMATCH",
            }

        guardian = self.guardian
        if guardian is None:
            return {
                "ok": False,
                "allowed": False,
                "error": "OWNER_AUTHORITY_UNAVAILABLE",
            }

        authority = ""

        if str(execution_token or "").strip():
            try:
                consumed = guardian.consume_direct_authorization(
                    execution_token=execution_token,
                    capability=expected_capability,
                    payload=dict(payload or {}),
                )
            except Exception:
                return {
                    "ok": False,
                    "allowed": False,
                    "error": "OWNER_AUTHORITY_CHECK_FAILED",
                }

            if not isinstance(consumed, dict) or not consumed.get("allowed"):
                return {
                    "ok": False,
                    "allowed": False,
                    "error": (
                        consumed.get("error")
                        if isinstance(consumed, dict)
                        else "OWNER_WEB_AUTHORIZATION_REQUIRED"
                    ),
                }

            authority = "exact_owner_authorization"

        elif self._standing_allowed(mode):
            authority = "standing_owner_permission"

        else:
            return {
                "ok": False,
                "allowed": False,
                "error": "OWNER_WEB_AUTHORIZATION_REQUIRED",
            }

        session_token = token_hex(24).upper()

        with self._lock:
            now = monotonic()
            self._sessions = {
                token: row
                for token, row in self._sessions.items()
                if float(row.get("expires_at") or 0.0) > now
            }
            self._sessions[session_token] = {
                "purpose": mode,
                "capability": expected_capability,
                "authority": authority,
                "expires_at": now + 600.0,
            }

        return {
            "ok": True,
            "allowed": True,
            "session_token": session_token,
            "scope": "PUBLIC_WEB_READ_ONLY",
            "purpose": mode,
            "authority": authority,
        }

    def close_public_web_session(self, session_token: str) -> None:
        token = str(session_token or "").strip().upper()
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)

    def allow_public_web(
        self,
        url: str,
        *,
        purpose: str = "research",
        session_token: str = "",
    ) -> dict[str, Any]:
        try:
            host, _ = _public_target(url)
        except NetworkEgressError as exc:
            return {
                "ok": False,
                "allowed": False,
                "error": str(exc),
            }

        mode = self._mode(purpose)
        token = str(session_token or "").strip().upper()

        if token:
            with self._lock:
                row = self._sessions.get(token)

                if row is None:
                    return {
                        "ok": False,
                        "allowed": False,
                        "error": "PUBLIC_WEB_SESSION_INVALID",
                    }

                if float(row.get("expires_at") or 0.0) <= monotonic():
                    self._sessions.pop(token, None)
                    return {
                        "ok": False,
                        "allowed": False,
                        "error": "PUBLIC_WEB_SESSION_EXPIRED",
                    }

                if row.get("purpose") != mode:
                    return {
                        "ok": False,
                        "allowed": False,
                        "error": "PUBLIC_WEB_SESSION_SCOPE_MISMATCH",
                    }

                return {
                    "ok": True,
                    "allowed": True,
                    "scope": "PUBLIC_WEB_READ_ONLY",
                    "purpose": mode,
                    "host": host,
                    "authority": row.get("authority"),
                }

        if not self._standing_allowed(mode):
            return {
                "ok": False,
                "allowed": False,
                "error": "OWNER_WEB_AUTHORIZATION_REQUIRED",
            }

        return {
            "ok": True,
            "allowed": True,
            "scope": "PUBLIC_WEB_READ_ONLY",
            "purpose": mode,
            "host": host,
            "authority": "standing_owner_permission",
        }
