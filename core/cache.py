from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, Optional

try:
    import redis  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    redis = None

from utils.logger import get_logger
from core.settings import REDIS_URL


class CacheAdapter:
    """Best-effort Redis cache with in-memory fallback."""

    def __init__(self) -> None:
        self.logger = get_logger("core.cache")
        self._local_store: Dict[str, Any] = {}
        self._local_expiry: Dict[str, float] = {}
        self._lock = threading.RLock()
        self._client = self._init_client()

    def _init_client(self):
        if redis is None:
            self.logger.warning("redis library not installed, falling back to in-memory cache.")
            return None
        try:
            client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
            client.ping()
            self.logger.info("Connected to Redis cache at %s", REDIS_URL)
            return client
        except (ConnectionError, TimeoutError, redis.RedisError) as exc:  # pragma: no cover - depends on environment
            self.logger.warning("Redis unavailable (%s). Using in-memory cache.", exc)
            return None

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
        if self._client:
            try:
                return self._client.get(key)
            except (ConnectionError, TimeoutError, redis.RedisError) as exc:
                self.logger.warning("Redis get failed (%s). Falling back to memory.", exc)
        with self._lock:
            expires = self._local_expiry.get(key)
            if expires and expires < self._now():
                self._local_store.pop(key, None)
                self._local_expiry.pop(key, None)
                return None
            return self._local_store.get(key)

    def set(self, key: str, value: str, ttl: int = 60) -> None:
        if self._client:
            try:
                self._client.set(key, value, ex=ttl)
                return
            except (ConnectionError, TimeoutError, redis.RedisError) as exc:
                self.logger.warning("Redis set failed (%s). Falling back to memory.", exc)
        with self._lock:
            self._local_store[key] = value
            self._local_expiry[key] = self._now() + ttl

    def delete(self, key: str) -> None:
        if self._client:
            try:
                self._client.delete(key)
            except (ConnectionError, TimeoutError, redis.RedisError):
                pass
        with self._lock:
            self._local_store.pop(key, None)
            self._local_expiry.pop(key, None)


cache = CacheAdapter()

__all__ = ["cache", "CacheAdapter"]
