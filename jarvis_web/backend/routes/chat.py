from __future__ import annotations

import json
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from jarvis_web.backend.models import ChatRequest, ChatResponse, JarvisEvent
from jarvis_web.backend.session_store import SessionNotFoundError
from jarvis_web.backend.web_chat_policy import evaluate_web_chat_message

router = APIRouter(prefix="/api", tags=["chat"])


def _enforce_web_chat_policy(message: str) -> None:
    decision = evaluate_web_chat_message(message)
    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "code": decision.code,
                "message": decision.reason,
            },
        )


async def _resolve_session(request: Request, session_id: str | None) -> str:
    store = request.app.state.session_store
    if session_id is None:
        session = await store.create()
        return session["id"]

    try:
        await store.get(session_id)
    except SessionNotFoundError:
        # Backward compatibility with the v0.1 API contract: callers that
        # already provide their own session ID continue to work.
        await store.create(session_id=session_id)
    return session_id


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    _enforce_web_chat_policy(payload.message)
    adapter = request.app.state.core_adapter
    broker = request.app.state.event_broker
    store = request.app.state.session_store
    session_id = await _resolve_session(request, payload.session_id)

    prior_history = await request.app.state.history_service.current_context(
        session_id,
        max_messages=24,
        store=store,
    )
    await store.append_message(session_id, "user", payload.message)
    await broker.publish(
        JarvisEvent(
            type="jarvis.thinking",
            session_id=session_id,
            data={},
        )
    )

    try:
        answer = await adapter.chat(
            payload.message,
            session_id=session_id,
            history=prior_history,
        )
    except Exception:
        await broker.publish(
            JarvisEvent(
                type="jarvis.error",
                session_id=session_id,
                data={"message": "The JARVIS Core request failed."},
            )
        )
        raise

    await store.append_message(session_id, "assistant", answer)

    response = ChatResponse.build(
        session_id=session_id,
        answer=answer,
        provider=adapter.name,
    )

    await broker.publish(
        JarvisEvent(
            type="jarvis.completed",
            session_id=session_id,
            data={"message_id": response.message_id},
        )
    )
    return response


@router.post("/chat/stream")
async def stream_chat(payload: ChatRequest, request: Request) -> StreamingResponse:
    _enforce_web_chat_policy(payload.message)
    adapter = request.app.state.core_adapter
    broker = request.app.state.event_broker
    store = request.app.state.session_store
    session_id = await _resolve_session(request, payload.session_id)

    prior_history = await request.app.state.history_service.current_context(
        session_id,
        max_messages=24,
        store=store,
    )
    await store.append_message(session_id, "user", payload.message)

    async def generate():
        message_id = str(uuid4())
        chunks: list[str] = []

        await broker.publish(
            JarvisEvent(
                type="jarvis.thinking",
                session_id=session_id,
                data={},
            )
        )

        yield json.dumps(
            {
                "type": "meta",
                "session_id": session_id,
                "provider": adapter.name,
            }
        ) + "\n"

        try:
            async for delta in adapter.stream_chat(
                payload.message,
                session_id=session_id,
                history=prior_history,
            ):
                chunks.append(delta)
                yield json.dumps(
                    {"type": "delta", "delta": delta},
                    ensure_ascii=False,
                ) + "\n"

            answer = "".join(chunks)
            await store.append_message(session_id, "assistant", answer)

            await broker.publish(
                JarvisEvent(
                    type="jarvis.completed",
                    session_id=session_id,
                    data={"message_id": message_id},
                )
            )

            yield json.dumps(
                {
                    "type": "done",
                    "message_id": message_id,
                    "session_id": session_id,
                }
            ) + "\n"
        except Exception:
            await broker.publish(
                JarvisEvent(
                    type="jarvis.error",
                    session_id=session_id,
                    data={"message": "The JARVIS Core request failed."},
                )
            )
            yield json.dumps(
                {
                    "type": "error",
                    "message": "A JARVIS não conseguiu concluir a resposta.",
                },
                ensure_ascii=False,
            ) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store"},
    )
