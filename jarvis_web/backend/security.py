from __future__ import annotations

from collections.abc import Awaitable, Callable
from urllib.parse import unquote

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse

from jarvis_web.backend.config import settings


class SuspiciousPathGuardMiddleware:
    """Reject malformed/path-traversal requests before routing/static fallback.

    The production server is Windows-based, so this guard also rejects NTFS
    alternate-data-stream syntax (':') in request paths.
    """

    MAX_RAW_PATH_LENGTH = 4096

    def __init__(self, app) -> None:
        self.app = app

    @staticmethod
    def _fully_decode(value: str) -> tuple[str, bool]:
        """Decode a bounded number of layers.

        Returns (decoded, over_encoded). If another decoding pass would still
        change the value after the bound, the request is rejected instead of
        allowing arbitrarily nested encodings to slip past the guard.
        """
        decoded = value
        for _ in range(6):
            next_value = unquote(decoded)
            if next_value == decoded:
                return decoded, False
            decoded = next_value

        return decoded, unquote(decoded) != decoded

    @classmethod
    def _is_suspicious(cls, value: str) -> bool:
        if len(value) > cls.MAX_RAW_PATH_LENGTH:
            return True

        decoded, over_encoded = cls._fully_decode(value)

        if over_encoded:
            return True

        if len(decoded) > cls.MAX_RAW_PATH_LENGTH:
            return True

        if "\x00" in decoded:
            return True

        normalized = decoded.replace("\\", "/")

        # Windows NTFS ADS syntax is not needed by the Web UI and creates
        # unnecessary filesystem ambiguity (for example file.txt:stream).
        if ":" in normalized:
            return True

        segments = normalized.split("/")
        return any(segment == ".." for segment in segments)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw_path = scope.get("raw_path", b"")
        if isinstance(raw_path, bytes):
            raw_value = raw_path.decode("latin-1", errors="ignore")
        else:
            raw_value = str(raw_path)

        decoded_path = str(scope.get("path", ""))

        if self._is_suspicious(raw_value) or self._is_suspicious(decoded_path):
            response = PlainTextResponse(
                "Malformed path",
                status_code=400,
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


class LocalOriginGuardMiddleware:
    """Reject browser requests to /api from untrusted Origins.

    CORS controls whether a browser may read a response; it does not prevent
    every cross-origin request from reaching the server. This guard makes the
    server itself reject untrusted browser origins.
    """

    def __init__(self, app, *, allowed_origins: tuple[str, ...]) -> None:
        self.app = app
        self.allowed = set(allowed_origins)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith("/api"):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if origin and origin not in self.allowed:
            response = PlainTextResponse("Forbidden origin", status_code=403)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


class _RequestBodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    """Bound API request bodies before JSON parsing.

    Enforces both declared Content-Length and the bytes actually received, so
    chunked/streamed requests cannot bypass the 256 KiB API limit.
    """

    MAX_API_BODY_BYTES = 256 * 1024

    def __init__(self, app) -> None:
        self.app = app

    @staticmethod
    async def _reject(scope, receive, send, *, status_code: int, message: str) -> None:
        response = PlainTextResponse(
            message,
            status_code=status_code,
            headers={"Cache-Control": "no-store"},
        )
        await response(scope, receive, send)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith("/api"):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        content_length = headers.get("content-length")

        if content_length:
            try:
                declared = int(content_length)
            except ValueError:
                await self._reject(
                    scope, receive, send,
                    status_code=400,
                    message="Invalid Content-Length",
                )
                return

            if declared < 0:
                await self._reject(
                    scope, receive, send,
                    status_code=400,
                    message="Invalid Content-Length",
                )
                return

            if declared > self.MAX_API_BODY_BYTES:
                await self._reject(
                    scope, receive, send,
                    status_code=413,
                    message="Request body too large",
                )
                return

        received = 0

        async def receive_limited():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"")
                received += len(body)
                if received > self.MAX_API_BODY_BYTES:
                    raise _RequestBodyTooLarge
            return message

        try:
            await self.app(scope, receive_limited, send)
        except _RequestBodyTooLarge:
            await self._reject(
                scope, receive, send,
                status_code=413,
                message="Request body too large",
            )


class SecurityHeadersMiddleware:
    """Add browser hardening headers without duplicating response headers."""

    def __init__(self, app) -> None:
        self.app = app

    @staticmethod
    def _set_header(headers: list[tuple[bytes, bytes]], name: bytes, value: bytes) -> None:
        lowered = name.lower()
        headers[:] = [(k, v) for (k, v) in headers if k.lower() != lowered]
        headers.append((name, value))

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_hardened(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))

                self._set_header(headers, b"x-content-type-options", b"nosniff")
                self._set_header(headers, b"x-frame-options", b"DENY")
                self._set_header(headers, b"referrer-policy", b"no-referrer")
                self._set_header(headers, b"cross-origin-resource-policy", b"same-origin")
                self._set_header(headers, b"x-permitted-cross-domain-policies", b"none")
                self._set_header(
                    headers,
                    b"permissions-policy",
                    b"camera=(), microphone=(), geolocation=()",
                )
                self._set_header(
                    headers,
                    b"content-security-policy",
                    (
                        b"default-src 'self'; "
                        b"base-uri 'none'; "
                        b"frame-ancestors 'none'; "
                        b"form-action 'self'; "
                        b"object-src 'none'; "
                        b"script-src 'self'; "
                        b"style-src 'self'; "
                        b"font-src 'self'; "
                        b"manifest-src 'self'; "
                        b"worker-src 'none'; "
                        b"img-src 'self' data:; "
                        b"connect-src 'self' ws://127.0.0.1:8766 ws://localhost:8766"
                    ),
                )

                if scope.get("path", "").startswith("/api"):
                    self._set_header(headers, b"cache-control", b"no-store")

                message["headers"] = headers

            await send(message)

        await self.app(scope, receive, send_hardened)



class LocalSessionAuthMiddleware:
    """Require authentication and minimal route-specific scopes."""

    PUBLIC_API_PATHS = {
        "/api/health",
        "/api/auth/status",
    }

    def __init__(self, app) -> None:
        self.app = app

    @staticmethod
    def _required_scope(scope) -> str | None:
        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()

        if path.startswith("/api/chat"):
            return "chat.write"

        if path.startswith("/api/history"):
            return "history.read"

        if path.startswith("/api/sessions"):
            if method in {"POST", "PATCH", "DELETE"}:
                return "history.write"
            return "history.read"

        if path.startswith("/api/security"):
            return "security.read"

        if path == "/api/status":
            return "chat.read"

        return None

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith("/api") or path in self.PUBLIC_API_PATHS:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        cookies = {}
        cookie_header = headers.get("cookie", "")
        for item in cookie_header.split(";"):
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            cookies[key.strip()] = value.strip()

        from jarvis_web.backend.auth import SESSION_COOKIE_NAME

        token = cookies.get(SESSION_COOKIE_NAME)
        auth = scope["app"].state.auth
        session = auth.get_session(token)

        if session is None:
            response = PlainTextResponse(
                "Authentication required",
                status_code=401,
                headers={
                    "Cache-Control": "no-store",
                    "WWW-Authenticate": "JarvisLocal",
                },
            )
            await response(scope, receive, send)
            return

        required = self._required_scope(scope)
        if required and not session.has_scope(required):
            response = PlainTextResponse(
                "Insufficient scope",
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return

        scope["jarvis.session"] = session
        await self.app(scope, receive, send)
