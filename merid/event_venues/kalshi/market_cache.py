"""Market data cache for Kalshi API.

Provides TTL-based caching for semi-static market data to reduce API calls
and improve latency. Cache entries expire after a configurable TTL.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TypeVar

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.market_cache")

T = TypeVar("T")


@dataclass
class CacheEntry:
    """A single cache entry with TTL."""
    value: Any
    timestamp: float = field(default_factory=time.monotonic)
    hits: int = 0


class KalshiMarketCache:
    """TTL-based cache for Kalshi market data.

    Caches market definitions, orderbooks, and other semi-static data
    to reduce API calls. Each entry has an independent TTL.

    Features:
    - Per-entry TTL with automatic expiration
    - Background cleanup task
    - Hit/miss statistics
    - Thread-safe async operations
    """

    def __init__(
        self,
        default_ttl_seconds: float = 60.0,
        max_size: int = 10000,
        cleanup_interval_seconds: float = 300.0,
    ):
        self._cache: Dict[str, CacheEntry] = {}
        self._default_ttl = default_ttl_seconds
        self._max_size = max_size
        self._cleanup_interval = cleanup_interval_seconds
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "expirations": 0,
        }

    async def start(self) -> None:
        """Start the background cleanup task."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(
                self._cleanup_loop(),
                name="kalshi-cache-cleanup",
            )
            logger.info("KalshiMarketCache cleanup task started")

    async def stop(self) -> None:
        """Stop the background cleanup task."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            logger.info("KalshiMarketCache cleanup task stopped")

    async def get(
        self,
        key: str,
        ttl_seconds: Optional[float] = None,
    ) -> Optional[Any]:
        """Get a value from cache if it exists and hasn't expired.

        Args:
            key: Cache key
            ttl_seconds: Optional override for this entry's TTL

        Returns:
            Cached value or None if expired/missing
        """
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._stats["misses"] += 1
                return None

            ttl = ttl_seconds or self._default_ttl
            age = time.monotonic() - entry.timestamp

            if age > ttl:
                # Expired
                del self._cache[key]
                self._stats["expirations"] += 1
                self._stats["misses"] += 1
                return None

            entry.hits += 1
            self._stats["hits"] += 1
            return entry.value

    async def set(
        self,
        key: str,
        value: Any,
    ) -> None:
        """Store a value in the cache.

        Args:
            key: Cache key
            value: Value to cache
        """
        async with self._lock:
            # Evict oldest entries if at capacity
            if len(self._cache) >= self._max_size:
                await self._evict_oldest()

            self._cache[key] = CacheEntry(value=value)

    async def delete(self, key: str) -> bool:
        """Delete a cache entry.

        Returns:
            True if entry was deleted, False if not found
        """
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    async def clear(self) -> None:
        """Clear all cache entries."""
        async with self._lock:
            self._stats["evictions"] += len(self._cache)
            self._cache.clear()

    async def get_or_fetch(
        self,
        key: str,
        fetch_func,
        ttl_seconds: Optional[float] = None,
    ) -> Any:
        """Get from cache or fetch and store if missing.

        Args:
            key: Cache key
            fetch_func: Async function to fetch the value
            ttl_seconds: Optional override for this entry's TTL

        Returns:
            Cached or fetched value
        """
        cached = await self.get(key, ttl_seconds)
        if cached is not None:
            return cached

        try:
            value = await fetch_func()
            await self.set(key, value)
            return value
        except Exception as e:
            logger.warning(f"Fetch failed for {key}: {e}")
            raise

    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        async with self._lock:
            total_requests = self._stats["hits"] + self._stats["misses"]
            hit_rate = (
                self._stats["hits"] / total_requests
                if total_requests > 0
                else 0.0
            )
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._stats["hits"],
                "misses": self._stats["misses"],
                "hit_rate": round(hit_rate, 4),
                "evictions": self._stats["evictions"],
                "expirations": self._stats["expirations"],
                "default_ttl_seconds": self._default_ttl,
            }

    async def _evict_oldest(self, count: int = 1) -> None:
        """Evict the oldest entries from cache."""
        if not self._cache:
            return

        # Sort by timestamp (oldest first)
        sorted_keys = sorted(
            self._cache.keys(),
            key=lambda k: self._cache[k].timestamp,
        )

        for key in sorted_keys[:count]:
            del self._cache[key]
            self._stats["evictions"] += 1

    async def _cleanup_loop(self) -> None:
        """Background task to clean up expired entries."""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cache cleanup error: {e}")

    async def _cleanup_expired(self) -> None:
        """Remove all expired entries."""
        now = time.monotonic()
        expired_keys = []

        async with self._lock:
            for key, entry in self._cache.items():
                age = now - entry.timestamp
                if age > self._default_ttl:
                    expired_keys.append(key)

            for key in expired_keys:
                del self._cache[key]

        if expired_keys:
            self._stats["expirations"] += len(expired_keys)
            logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")


# ── Singleton ────────────────────────────────────────────────────────────

_cache: Optional[KalshiMarketCache] = None


def get_market_cache(
    default_ttl_seconds: float = 60.0,
    max_size: int = 10000,
) -> KalshiMarketCache:
    """Get or create the singleton market cache.

    Args:
        default_ttl_seconds: Default TTL for cache entries
        max_size: Maximum number of entries in cache

    Returns:
        KalshiMarketCache singleton instance
    """
    global _cache
    if _cache is None:
        _cache = KalshiMarketCache(
            default_ttl_seconds=default_ttl_seconds,
            max_size=max_size,
        )
    return _cache
