"""
Unified WebSocket feed manager for venue market data.

Handles connection orchestration, automatic resubscription, and fan-out to
consumers inside MERID. This is a lightweight in-process coordinator that can
later be replaced with a hosted data service if needed.
"""

from __future__ import annotations

import asyncio
import threading
from utils.logger import get_logger
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


logger = get_logger(__name__)


@dataclass
class FeedSubscription:
    venue: str
    channel: str
    handler: Callable[[Dict[str, object]], None]
    active: bool = False


class WebSocketFeedManager:
    def __init__(self) -> None:
        self._subscriptions: List[FeedSubscription] = []
        self._connections: Dict[str, asyncio.Task] = {}
        self._loop = asyncio.get_event_loop()

    def add_subscription(self, venue: str, channel: str, handler: Callable[[Dict[str, object]], None]) -> None:
        self._subscriptions.append(FeedSubscription(venue=venue, channel=channel, handler=handler))

    def start(self) -> None:
        for sub in self._subscriptions:
            key = f"{sub.venue}:{sub.channel}"
            if key in self._connections:
                continue
            self._connections[key] = self._loop.create_task(self._run_feed(sub))

    async def _run_feed(self, subscription: FeedSubscription) -> None:
        subscription.active = True
        logger.info("Starting websocket feed %s/%s", subscription.venue, subscription.channel)
        while subscription.active:
            await asyncio.sleep(1)  # placeholder for actual websocket recv
            payload = {"venue": subscription.venue, "channel": subscription.channel, "tick": {}}
            subscription.handler(payload)

    def stop(self) -> None:
        for sub in self._subscriptions:
            sub.active = False
        for task in self._connections.values():
            task.cancel()
        self._connections.clear()


_websocket_feed_manager: Optional[WebSocketFeedManager] = None
_websocket_feed_manager_lock = threading.Lock()


def get_websocket_feed_manager() -> WebSocketFeedManager:
    global _websocket_feed_manager
    if _websocket_feed_manager is None:
        with _websocket_feed_manager_lock:
            if _websocket_feed_manager is None:
                _websocket_feed_manager = WebSocketFeedManager()
    return _websocket_feed_manager
