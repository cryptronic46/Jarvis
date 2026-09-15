from __future__ import annotations

import asyncio

from jarvis_web.backend.models import JarvisEvent


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[JarvisEvent]] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[JarvisEvent]:
        queue: asyncio.Queue[JarvisEvent] = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[JarvisEvent]) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    async def publish(self, event: JarvisEvent) -> None:
        async with self._lock:
            subscribers = tuple(self._subscribers)

        for queue in subscribers:
            if queue.full():
                # Drop oldest state event rather than blocking the Core.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)
