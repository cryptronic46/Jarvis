from fastapi import APIRouter, HTTPException, Request, status

from jarvis_web.backend.models import SessionDetail, SessionRenameRequest, SessionSummary
from jarvis_web.backend.session_store import SessionNotFoundError

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionSummary])
async def list_sessions(request: Request) -> list[SessionSummary]:
    items = await request.app.state.session_store.list()
    return [SessionSummary(**item) for item in items]


@router.post("", response_model=SessionDetail, status_code=status.HTTP_201_CREATED)
async def create_session(request: Request) -> SessionDetail:
    session = await request.app.state.session_store.create()
    return SessionDetail(
        **session,
        message_count=len(session["messages"]),
    )


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str, request: Request) -> SessionDetail:
    try:
        session = await request.app.state.session_store.get(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionDetail(
        **session,
        message_count=len(session["messages"]),
    )


@router.patch("/{session_id}", response_model=SessionDetail)
async def rename_session(
    session_id: str,
    payload: SessionRenameRequest,
    request: Request,
) -> SessionDetail:
    try:
        session = await request.app.state.session_store.rename(
            session_id,
            payload.title,
        )
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid session title")

    return SessionDetail(
        **session,
        message_count=len(session["messages"]),
    )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str, request: Request) -> None:
    try:
        await request.app.state.session_store.delete(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
