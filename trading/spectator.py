"""Spectator log capturing trading intents/results for UI/backtests."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import asdict, is_dataclass
from typing import Any, Deque, Dict, List


class SpectatorLog:
    def __init__(self, max_events: int = 500) -> None:
        self._events: Deque[Dict[str, Any]] = deque(maxlen=max_events)
        self._lock = threading.Lock()

    def ingest_event(self, event_type: str, payload: Any) -> None:
        entry = {
            "event_type": event_type,
            "payload": self._serialize(payload),
            "ts": time.time(),
        }
        with self._lock:
            self._events.appendleft(entry)

    def get_recent(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            return list(list(self._events)[:limit])

    def dump_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._events)

    @staticmethod
    def _serialize(payload: Any) -> Any:
        if payload is None:
            return None
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, (str, int, float, bool)):
            return payload
        if isinstance(payload, list):
            return payload
        if is_dataclass(payload):
            try:
                return asdict(payload)
            except Exception:
                return repr(payload)
        if hasattr(payload, "dict"):
            try:
                return payload.dict()
            except Exception:
                return repr(payload)
        return repr(payload)


def get_spectator_log() -> SpectatorLog:
    global _spectator_log
    if _spectator_log is None:
        _spectator_log = SpectatorLog()
    return _spectator_log


_spectator_log: SpectatorLog | None = None
