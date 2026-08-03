from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, Optional

from utils.logger import get_logger


class CacheAdapter:
    """In-memory cache for MERID.
    
    Redis dependency removed - using in-memory cache exclusively.
    """

    def __init__(self) -> None:
        self.logger = get_logger("core.cache")
        self._local_store: Dict[str, Any] = {}
        self._local_expiry: Dict[str, float] = {}
        self._lock = threading.RLock()
        self.logger.info("CacheAdapter initialized with in-memory cache (Redis dependency removed)")

    def _now(self) -> float:
        return time.time()

    # ------------------------- Public API -------------------------
    def get_json(self, key: str) -> Optional[Any]:
        raw = self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def set_json(self, key: str, value: Any, ttl: int = 60) -> None:
        self.set(key, json.dumps(value), ttl=ttl)

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            expires = self._local_expiry.get(key)
            if expires and expires < self._now():
                self._local_store.pop(key, None)
                self._local_expiry.pop(key, None)
                return None
            return self._local_store.get(key)

    def set(self, key: str, value: str, ttl: int = 60) -> None:
        with self._lock:
            self._local_store[key] = value
            self._local_expiry[key] = self._now() + ttl

    def delete(self, key: str) -> None:
        with self._lock:
            self._local_store.pop(key, None)
            self._local_expiry.pop(key, None)


cache = CacheAdapter()

__all__ = ["cache", "CacheAdapter"]
