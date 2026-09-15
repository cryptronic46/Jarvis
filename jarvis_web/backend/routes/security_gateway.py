from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from jarvis_web.backend.auth import SESSION_COOKIE_NAME

router = APIRouter(prefix="/api/security", tags=["security"])


def _current_session(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    return request.app.state.auth.get_session(token)


def _require_scope(request: Request, scope: str):
    session = _current_session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not session.has_scope(scope):
        raise HTTPException(status_code=403, detail="Insufficient scope")
    return session


@router.get("/me")
async def security_me(request: Request):
    session = _require_scope(request, "security.read")
    return {
        "session_id": session.session_id,
        "device_id": session.device_id,
        "device_label": session.device_label,
        "trust_level": session.trust_level,
        "scopes": sorted(session.scopes),
        # Important contract: Home capabilities do not imply raw Core control.
        "core_control_authorized": False,
        "home_read_authorized": session.has_scope("home.read"),
        "home_control_authorized": session.has_scope("home.control"),
        "home_critical_authorized": False,
        "remote_access_enabled": False,
    }


@router.get("/sessions")
async def list_security_sessions(request: Request):
    session = _require_scope(request, "security.manage_local")

    # Only trusted local-desktop sessions may enumerate/revoke sessions.
    if session.trust_level != "local_desktop":
        raise HTTPException(status_code=403, detail="Local desktop required")

    return {
        "sessions": request.app.state.auth.list_sessions(),
    }


@router.post("/revoke/{session_id}")
async def revoke_security_session(session_id: str, request: Request):
    session = _require_scope(request, "security.manage_local")
    if session.trust_level != "local_desktop":
        raise HTTPException(status_code=403, detail="Local desktop required")

    revoked = request.app.state.auth.revoke_session_id(session_id)

    request.app.state.security_audit.write(
        "security.session_revoke",
        actor_session_id=session.session_id,
        target_session_id=session_id,
        result="revoked" if revoked else "not_found",
    )

    if not revoked:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"revoked": True}


@router.post("/revoke-all")
async def revoke_all_security_sessions(request: Request):
    session = _require_scope(request, "security.manage_local")
    if session.trust_level != "local_desktop":
        raise HTTPException(status_code=403, detail="Local desktop required")

    actor_session_id = session.session_id
    count = request.app.state.auth.revoke_all()

    request.app.state.security_audit.write(
        "security.revoke_all",
        actor_session_id=actor_session_id,
        revoked_count=count,
    )

    return {
        "revoked": count,
        "current_session_revoked": True,
    }


@router.get("/remote-status")
async def remote_status(request: Request):
    _require_scope(request, "security.read")
    return {
        "enabled": False,
        "reason": (
            "Remote/VPN access remains disabled until passkey/WebAuthn "
            "device enrollment and remote transport policy are implemented."
        ),
    }



@router.get("/storage-status")
async def storage_status(request: Request):
    session = _require_scope(request, "security.manage_local")
    if session.trust_level != "local_desktop":
        raise HTTPException(status_code=403, detail="Local desktop required")

    return request.app.state.session_store.security_status()


@router.get("/home-policy")
async def home_policy(request: Request):
    session = _require_scope(request, "security.read")
    manifest = request.app.state.home_capability_broker.manifest()
    return {
        **manifest,
        "session_can_read": session.has_scope("home.read"),
        "session_can_control_normal": session.has_scope("home.control"),
        "session_can_control_critical": False,
    }
