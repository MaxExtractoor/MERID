from __future__ import annotations

import asyncio
from typing import Any, Dict, Set


class LiveEventStream:
    """In-memory pub/sub for agent activity streaming to the UI."""

    def __init__(self) -> None:
        self._listeners: Set[asyncio.Queue] = set()
        self._lock: asyncio.Lock | None = None
        self._max_queue = 200

    def _get_lock(self) -> asyncio.Lock:
        """Lazily create the lock in the current event loop to avoid cross-loop deadlocks."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        async with self._get_lock():
            self._listeners.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        async with self._get_lock():
            self._listeners.discard(queue)

    async def publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        event = {"type": event_type, "payload": payload}
        stale: Set[asyncio.Queue] = set()
        async with self._get_lock():
            for listener in list(self._listeners):
                if listener.full():
                    stale.add(listener)
                    continue
                listener.put_nowait(event)
            for listener in stale:
                self._listeners.discard(listener)

    def listener_count(self) -> int:
        return len(self._listeners)


event_stream = LiveEventStream()


def get_event_bus() -> LiveEventStream:
    """Return the module-level event stream singleton."""
    return event_stream
