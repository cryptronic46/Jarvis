from fastapi import APIRouter, WebSocket, WebSocketDisconnect, WebSocketException, status

from jarvis_web.backend.auth import SESSION_COOKIE_NAME
from jarvis_web.backend.models import JarvisEvent

router = APIRouter(tags=["events"])


@router.websocket("/api/events")
async def events(websocket: WebSocket) -> None:
    # Browser WebSockets are not protected by CORS. Validate Origin explicitly.
    origin = websocket.headers.get("origin")
    allowed_origins = set(
        getattr(websocket.app.state, "allowed_origins", ())
    )
    if not origin or origin not in allowed_origins:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    session_token = websocket.cookies.get(SESSION_COOKIE_NAME)
    if not websocket.app.state.auth.validate_session(session_token):
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    await websocket.accept()
    broker = websocket.app.state.event_broker
    queue = await broker.subscribe()

    try:
        await websocket.send_json(JarvisEvent(type="jarvis.ready").model_dump())
        while True:
            event = await queue.get()
            await websocket.send_json(event.model_dump())
    except WebSocketDisconnect:
        pass
    finally:
        await broker.unsubscribe(queue)
