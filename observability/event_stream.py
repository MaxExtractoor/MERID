"""Async event stream for spectator/backtest telemetry."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set


@dataclass
class EventRecord:
    event_type: str
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)


class EventStream:
    """In-memory async pub/sub bus."""

    def __init__(self, max_queue: int = 500) -> None:
        self._listeners: Set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
        self._max_queue = max_queue

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        async with self._lock:
            self._listeners.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        async with self._lock:
            self._listeners.discard(queue)

    async def publish(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        record = EventRecord(event_type=event_type, payload=payload or {})
        async with self._lock:
            stale: Set[asyncio.Queue] = set()
            for queue in list(self._listeners):
                try:
                    if queue.full():
                        try:
                            queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    queue.put_nowait(record)
                except Exception:
                    stale.add(queue)
            for queue in stale:
                self._listeners.discard(queue)


_stream: EventStream | None = None


def get_event_stream() -> EventStream:
    global _stream
    if _stream is None:
        _stream = EventStream()
    return _stream


async def publish_event_async(event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    await get_event_stream().publish(event_type, payload)


def publish_event(event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    stream = get_event_stream()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(stream.publish(event_type, payload))
        return
    loop.create_task(stream.publish(event_type, payload))


event_stream = get_event_stream()
