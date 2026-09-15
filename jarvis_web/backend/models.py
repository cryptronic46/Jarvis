from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class HealthResponse(BaseModel):
    status: str


class StatusResponse(BaseModel):
    state: str
    adapter: str
    local_only: bool = True


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=32000)
    session_id: str | None = Field(default=None, max_length=128)


class ChatResponse(BaseModel):
    message_id: str
    session_id: str
    answer: str
    provider: str
    status: str = "completed"

    @classmethod
    def build(
        cls,
        *,
        session_id: str,
        answer: str,
        provider: str,
    ) -> "ChatResponse":
        return cls(
            message_id=str(uuid4()),
            session_id=session_id,
            answer=answer,
            provider=provider,
        )


class JarvisEvent(BaseModel):
    type: str
    timestamp: str = Field(default_factory=utc_now_iso)
    session_id: str | None = None
    data: dict = Field(default_factory=dict)


class SessionMessage(BaseModel):
    id: str
    role: str
    content: str
    created_at: str


class SessionSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int


class SessionDetail(SessionSummary):
    messages: list[SessionMessage] = Field(default_factory=list)


class HistorySearchHit(BaseModel):
    session_id: str
    session_title: str
    message_id: str | None = None
    role: str | None = None
    snippet: str
    score: int
    updated_at: str


class HistorySearchResponse(BaseModel):
    query: str
    hits: list[HistorySearchHit] = Field(default_factory=list)


class SessionRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)
