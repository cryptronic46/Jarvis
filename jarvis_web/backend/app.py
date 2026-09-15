from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from jarvis_web.backend.adapters import JarvisCoreAdapter, MockJarvisCoreAdapter
from jarvis_web.backend.audit_log import SecurityAuditLog
from jarvis_web.backend.permission_broker import PermissionBroker
from jarvis_web.backend.auth import LocalAuthManager
from jarvis_web.backend.config import settings
from jarvis_web.backend.events import EventBroker
from jarvis_web.backend.history_service import HistoryService
from jarvis_web.backend.home_capability_broker import HomeCapabilityBroker
from jarvis_web.backend.routes.auth import router as auth_router
from jarvis_web.backend.routes.chat import router as chat_router
from jarvis_web.backend.routes.events import router as events_router
from jarvis_web.backend.routes.health import router as health_router
from jarvis_web.backend.routes.history import router as history_router
from jarvis_web.backend.routes.sessions import router as sessions_router
from jarvis_web.backend.routes.security_gateway import router as security_gateway_router
from jarvis_web.backend.routes.status import router as status_router
from jarvis_web.backend.security import (
    LocalOriginGuardMiddleware,
    LocalSessionAuthMiddleware,
    RequestBodyLimitMiddleware,
    SecurityHeadersMiddleware,
    SuspiciousPathGuardMiddleware,
)
from jarvis_web.backend.session_store import SessionStore
from jarvis_web.backend.storage_protection import build_default_acl_hardener

ROOT = Path(__file__).resolve().parents[1]
WEB_DIST = ROOT / "web" / "dist"
WEB_DIST_RESOLVED = WEB_DIST.resolve()
RESERVED_SERVER_PATHS = {"docs", "openapi.json", "redoc"}

# These paths belong to source/runtime state and must never be satisfied by the
# SPA fallback. Returning a real 404 reduces ambiguity and prevents accidental
# disclosure if the static layout changes later.
SENSITIVE_WEB_PREFIXES = (
    ".env",
    ".git",
    ".venv",
    "backend",
    "data",
    "logs",
    "run",
    "tests",
    "web/src",
    "web/node_modules",
    "web/dist",
)


def _is_reserved_web_path(path: str) -> bool:
    normalized = path.strip("/").replace("\\", "/").lower()

    if (
        normalized in RESERVED_SERVER_PATHS
        or normalized.startswith("api/")
        or normalized == "api"
    ):
        return True

    first_segment = normalized.split("/", 1)[0] if normalized else ""
    if first_segment.startswith("."):
        return True

    for prefix in SENSITIVE_WEB_PREFIXES:
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return True

    return False


def _make_lifespan(
    bootstrap_token: str | None,
    core_adapter: JarvisCoreAdapter | None,
):
    # Keep the bootstrap credential only until lifespan startup.
    # The mutable cell is cleared before the rest of the Web runtime
    # is initialized so the plaintext token is not retained by the
    # lifespan closure for the lifetime of the application.
    bootstrap_token_box = [bootstrap_token]

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        token = bootstrap_token_box[0]
        bootstrap_token_box[0] = None

        try:
            auth = LocalAuthManager(
                bootstrap_token=token,
            )
        finally:
            token = None

        app.state.core_adapter = (
            core_adapter
            if core_adapter is not None
            else MockJarvisCoreAdapter()
        )
        app.state.event_broker = EventBroker()
        app.state.session_store = SessionStore()
        app.state.history_service = HistoryService(app.state.session_store)
        app.state.auth = auth
        app.state.permission_broker = PermissionBroker()
        app.state.home_capability_broker = HomeCapabilityBroker()

        # Security audit has no chat content/secrets, but its metadata is still
        # private local state, so protect the logs directory with the same ACL.
        #
        # Pytest is forced onto a per-test temporary audit path. If a test
        # somehow starts the app without that fixture, fail closed rather than
        # writing into the user's real JARVIS logs.
        test_audit = os.getenv("JARVIS_WEB_TEST_AUDIT_FILE")
        if "PYTEST_CURRENT_TEST" in os.environ:
            if not test_audit:
                raise RuntimeError(
                    "Refusing to use production security audit log during pytest"
                )
            audit_path = Path(test_audit)
        else:
            audit_path = ROOT / "logs" / "security-audit.jsonl"

        logs_dir = audit_path.parent
        build_default_acl_hardener().harden(logs_dir)
        app.state.security_audit = SecurityAuditLog(audit_path)
        yield

    return lifespan


def _safe_web_candidate(path: str) -> Path | None:
    candidate = (WEB_DIST / path).resolve()
    try:
        candidate.relative_to(WEB_DIST_RESOLVED)
    except ValueError:
        return None
    return candidate


def create_app(
    *,
    dev_mode: bool = False,
    bootstrap_token: str | None = None,
    core_adapter: JarvisCoreAdapter | None = None,
) -> FastAPI:
    app = FastAPI(
        title="JARVIS Local API",
        version="0.5.2-concept-d-earth-photo",
        lifespan=_make_lifespan(
            bootstrap_token,
            core_adapter,
        ),
        docs_url="/docs" if dev_mode else None,
        openapi_url="/openapi.json" if dev_mode else None,
        redoc_url=None,
    )

    accepted_origins = (
        settings.runtime_origins + settings.dev_origins
        if dev_mode
        else settings.runtime_origins
    )
    app.state.allowed_origins = accepted_origins

    # Reject traversal/encoded-traversal probes before they can reach API
    # routing or the SPA/static fallback.
    app.add_middleware(SuspiciousPathGuardMiddleware)

    # Protected API routes require the local authenticated browser session.
    # This middleware is intentionally inner to Host/Origin validation.
    app.add_middleware(LocalSessionAuthMiddleware)

    # Reject oversized API bodies before authentication/JSON parsing.
    app.add_middleware(RequestBodyLimitMiddleware)

    # DNS-rebinding / arbitrary Host protection.
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(settings.trusted_hosts),
    )

    # Reject hostile browser Origins at the application boundary. Production
    # trusts only the runtime Web origin; Vite origins exist only in dev_mode.
    app.add_middleware(
        LocalOriginGuardMiddleware,
        allowed_origins=accepted_origins,
    )

    # Browser hardening headers for the same-origin local Web UI.
    app.add_middleware(SecurityHeadersMiddleware)

    # Production is same-origin and does not need CORS at all. Enable the
    # narrowly-scoped Vite development CORS policy only in dev_mode.
    if dev_mode:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.dev_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Content-Type"],
        )

    app.include_router(auth_router)
    app.include_router(health_router)
    app.include_router(status_router)
    app.include_router(chat_router)
    app.include_router(sessions_router)
    app.include_router(security_gateway_router)
    app.include_router(history_router)
    app.include_router(events_router)

    # Unknown API paths must fail closed as nonexistent.
    # This also prevents the SPA GET fallback from turning
    # forbidden/undefined POST endpoints into 405 responses.
    @app.api_route(
        "/api/{path:path}",
        methods=[
            "GET",
            "HEAD",
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
            "OPTIONS",
        ],
        include_in_schema=False,
    )
    async def unknown_api_route(path: str):
        raise HTTPException(
            status_code=404,
            detail="Not found",
        )

    if WEB_DIST.exists():
        assets = WEB_DIST / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="web-assets")

        @app.get("/", include_in_schema=False)
        async def web_index():
            return FileResponse(WEB_DIST / "index.html")

        @app.get("/{path:path}", include_in_schema=False)
        async def web_fallback(path: str):
            if _is_reserved_web_path(path):
                raise HTTPException(status_code=404, detail="Not found")

            candidate = _safe_web_candidate(path)
            if candidate is not None and candidate.is_file():
                return FileResponse(candidate)

            return FileResponse(WEB_DIST / "index.html")

    return app


app = create_app(dev_mode=False)
