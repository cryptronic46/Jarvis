from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from jarvis_web.backend.auth import SESSION_COOKIE_NAME

router = APIRouter(tags=["auth"])


@router.get("/auth/bootstrap", include_in_schema=False)
async def bootstrap(
    request: Request,
    token: str = Query(min_length=20, max_length=512),
):
    result = request.app.state.auth.consume_bootstrap(
        token,
        device_label="Local Windows browser",
    )
    if result is None:
        return JSONResponse(
            {"detail": "Invalid or expired bootstrap token"},
            status_code=401,
            headers={"Cache-Control": "no-store"},
        )

    session_token, session = result

    request.app.state.security_audit.write(
        "security.local_bootstrap_success",
        session_id=session.session_id,
        device_id=session.device_id,
        trust_level=session.trust_level,
    )

    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_token,
        httponly=True,
        secure=False,  # Local HTTP only. Do not expose remotely.
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/api/auth/status")
async def auth_status(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    return {
        "authenticated": request.app.state.auth.validate_session(token),
    }


@router.post("/api/auth/logout")
async def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    request.app.state.auth.revoke_session(token)

    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.headers["Cache-Control"] = "no-store"
    return response
