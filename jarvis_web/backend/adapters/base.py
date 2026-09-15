from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class JarvisCoreAdapter(ABC):
    """Stable boundary between network-facing code and the JARVIS Core."""

    name = "base"

    @abstractmethod
    async def health(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def status(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def chat(
        self,
        message: str,
        *,
        session_id: str | None = None,
        history: list[dict] | None = None,
    ) -> str:
        raise NotImplementedError

    async def stream_chat(
        self,
        message: str,
        *,
        session_id: str | None = None,
        history: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        answer = await self.chat(
            message,
            session_id=session_id,
            history=history,
        )

        words = answer.split(" ")

        for index, word in enumerate(words):
            yield word if index == len(words) - 1 else word + " "
