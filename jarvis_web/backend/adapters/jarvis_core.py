from __future__ import annotations

import asyncio
from functools import partial

from .base import JarvisCoreAdapter


class RealJarvisCoreAdapter(JarvisCoreAdapter):
    """Thin Web transport adapter over one existing JarvisApplication."""

    name = "jarvis-core"

    def __init__(self, application):
        if application is None:
            raise ValueError(
                "RealJarvisCoreAdapter requires an existing JarvisApplication"
            )

        self._application = application

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

        call = partial(
            self._application.process_request,
            message,
            source="web",
        )

        result = await asyncio.to_thread(call)

        answer = getattr(
            result,
            "answer",
            None,
        )

        if not isinstance(answer, str):
            raise RuntimeError(
                "JarvisApplication returned an invalid ProcessRequestResult"
            )

        return answer
