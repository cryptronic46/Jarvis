from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from .base import JarvisCoreAdapter


class MockJarvisCoreAdapter(JarvisCoreAdapter):
    """Development adapter. Never touches G:\\JARVIS."""

    name = "mock"

    async def health(self) -> str:
        return "ready"

    async def status(self) -> dict:
        return {
            "state": "ready",
            "adapter": self.name,
            "local_only": True,
        }

    async def chat(
        self,
        message: str,
        *,
        session_id: str | None = None,
        history: list[dict] | None = None,
    ) -> str:
        _ = (
            session_id,
            history,
        )

        await asyncio.sleep(0.08)

        return (
            "Liga??o Web/API operacional. "
            "Continuo em modo isolado e o c?rebro real em G:\\JARVIS "
            "n?o foi alterado. "
            f"Recebi: {message}"
        )

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
            await asyncio.sleep(0.025)
            yield word if index == len(words) - 1 else word + " "
