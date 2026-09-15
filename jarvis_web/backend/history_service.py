from __future__ import annotations

from dataclasses import dataclass
import re

from jarvis_web.backend.session_store import SessionStore


@dataclass(slots=True)
class HistoryHit:
    session_id: str
    session_title: str
    message_id: str | None
    role: str | None
    snippet: str
    score: int
    updated_at: str


class HistoryService:
    """Local retrieval layer for Web conversation history.

    v0.3 deliberately uses dependency-free lexical retrieval. CODEX may later
    add semantic/vector retrieval behind this service boundary.
    """

    def __init__(self, store: SessionStore) -> None:
        self.store = store

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [
            token
            for token in re.findall(r"[\wÀ-ÿ-]+", text.lower(), flags=re.UNICODE)
            if len(token) >= 2
        ]

    @staticmethod
    def _snippet(text: str, query_tokens: list[str], limit: int = 180) -> str:
        compact = " ".join(text.split())
        if len(compact) <= limit:
            return compact

        lower = compact.lower()
        positions = [lower.find(t) for t in query_tokens if lower.find(t) >= 0]
        center = min(positions) if positions else 0
        start = max(0, center - 50)
        end = min(len(compact), start + limit)
        return (
            ("…" if start > 0 else "")
            + compact[start:end]
            + ("…" if end < len(compact) else "")
        )

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        tokens = self._tokens(query)
        if not tokens:
            return []

        summaries = await self.store.list()
        hits: list[HistoryHit] = []

        for summary in summaries:
            session = await self.store.get(summary["id"])
            title_lower = session["title"].lower()
            title_score = sum(4 for token in tokens if token in title_lower)

            if title_score:
                hits.append(
                    HistoryHit(
                        session_id=session["id"],
                        session_title=session["title"],
                        message_id=None,
                        role=None,
                        snippet=session["title"],
                        score=title_score,
                        updated_at=session["updated_at"],
                    )
                )

            for message in session.get("messages", []):
                content = message.get("content", "")
                lower = content.lower()
                score = sum(2 for token in tokens if token in lower)
                if not score:
                    continue

                if query.strip().lower() in lower:
                    score += 5

                hits.append(
                    HistoryHit(
                        session_id=session["id"],
                        session_title=session["title"],
                        message_id=message.get("id"),
                        role=message.get("role"),
                        snippet=self._snippet(content, tokens),
                        score=score,
                        updated_at=session["updated_at"],
                    )
                )

        hits.sort(key=lambda hit: (hit.score, hit.updated_at), reverse=True)

        selected: list[HistoryHit] = []
        per_session: dict[str, int] = {}
        for hit in hits:
            count = per_session.get(hit.session_id, 0)
            if count >= 3:
                continue
            selected.append(hit)
            per_session[hit.session_id] = count + 1
            if len(selected) >= max(1, min(limit, 25)):
                break

        return [
            {
                "session_id": hit.session_id,
                "session_title": hit.session_title,
                "message_id": hit.message_id,
                "role": hit.role,
                "snippet": hit.snippet,
                "score": hit.score,
                "updated_at": hit.updated_at,
            }
            for hit in selected
        ]

    async def current_context(
        self,
        session_id: str,
        *,
        max_messages: int = 24,
        store: SessionStore | None = None,
    ) -> list[dict]:
        active_store = store or self.store
        session = await active_store.get(session_id)
        messages = session.get("messages", [])
        return messages[-max(1, min(max_messages, 100)) :]
