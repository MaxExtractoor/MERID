"""Resilient Redis client with retry, fallback, and graceful degradation.

This module provides a Redis wrapper that:
- Retries operations with exponential backoff
- Falls back to in-memory or no-op on failure
- Tracks health status via background checker
- Never blocks the main loop on Redis failures
"""

from __future__ import annotations

import random
import threading
import time
from contextlib import contextmanager
from typing import Any, Optional

from utils.logger import get_logger

logger = get_logger("merid.infra.redis_resilient")


class ResilientRedis:
    """Redis client with automatic retry, health checking, and graceful degradation.
    
    Usage:
        redis = ResilientRedis("redis://localhost:6379")
        value = redis.get("key")  # Returns None on failure (no exception)
        redis.set("key", b"value", ex=60)  # Fire-and-forget with retry
        
        # Lock with local fallback
        with redis.lock("my_lock", timeout=10):
            do_work()
    """
    
    def __init__(
        self,
        url: str,
        healthy_timeout: float = 30.0,
        max_retries: int = 3,
        connect_timeout: float = 2.0,
        socket_timeout: float = 2.0,
    ):
        self._url = url
        self._max_retries = max_retries
        self._healthy_timeout = healthy_timeout
        
        self._client: Optional[Any] = None
        self._healthy = False
        self._last_healthy_check = 0.0
        self._health_lock = threading.Lock()
        self._degraded_ops_count = 0
        
        # In-memory fallback cache (for reads when Redis is down)
        self._fallback_cache: dict[str, tuple[bytes, Optional[float]]] = {}
        self._fallback_lock = threading.Lock()
        
        try:
            import redis as redis_lib
            self._client = redis_lib.from_url(
                url,
                socket_connect_timeout=connect_timeout,
                socket_timeout=socket_timeout,
                decode_responses=False,  # Keep bytes
            )
            # Initial health check
            self._check_health_once()
            # Start background health checker
            self._start_health_checker(healthy_timeout)
            logger.info(f"ResilientRedis initialized: {url}")
        except Exception as exc:
            logger.warning(f"Redis initialization failed (degraded mode): {exc}")
            self._healthy = False
    
    def _check_health_once(self) -> bool:
        """Single health check. Returns True if Redis is responsive."""
        if self._client is None:
            return False
        try:
            self._client.ping()
            with self._health_lock:
                self._healthy = True
                self._last_healthy_check = time.time()
            return True
        except Exception:
            with self._health_lock:
                self._healthy = False
            return False
    
    def _start_health_checker(self, interval: float) -> None:
        """Start background thread to monitor Redis health."""
        def check_loop():
            while True:
                try:
                    if self._client:
                        try:
                            self._client.ping()
                            with self._health_lock:
                                if not self._healthy:
                                    logger.info("Redis health restored")
                                self._healthy = True
                                self._last_healthy_check = time.time()
                        except Exception:
                            with self._health_lock:
                                if self._healthy:
                                    logger.warning("Redis health check failed - entering degraded mode")
                                self._healthy = False
                except Exception as exc:
                    logger.debug(f"Health checker error: {exc}")
                
                time.sleep(interval)
        
        thread = threading.Thread(target=check_loop, daemon=True, name="redis-health-check")
        thread.start()
        logger.debug(f"Redis health checker started (interval={interval}s)")
    
    def _retry_on_fail(
        self,
        func,
        *args,
        fallback_return: Optional[Any] = None,
        **kwargs
    ) -> Optional[Any]:
        """Execute Redis operation with retry and fallback.
        
        Returns fallback_return on total failure (no exception raised).
        """
        # Fast-fail if we know Redis is unhealthy
        with self._health_lock:
            is_healthy = self._healthy
        
        if not is_healthy and self._max_retries <= 1:
            # Already known unhealthy, fast return fallback
            self._degraded_ops_count += 1
            return fallback_return
        
        for attempt in range(self._max_retries):
            try:
                if self._client is None:
                    raise RuntimeError("Redis client not initialized")
                return func(*args, **kwargs)
            except Exception as e:
                if attempt == 0:
                    # First failure - mark unhealthy immediately
                    with self._health_lock:
                        self._healthy = False
                
                if attempt == self._max_retries - 1:
                    # Final attempt failed
                    self._degraded_ops_count += 1
                    logger.debug(f"Redis operation failed after {self._max_retries} attempts: {e}")
                    return fallback_return
                
                # Exponential backoff with jitter
                delay = min(0.1 * (2 ** attempt), 2.0) * (0.5 + random.random())
                time.sleep(delay)
        
        return fallback_return  # Should never reach here
    
    # ── Core Redis Operations ─────────────────────────────────────────
    
    def get(self, key: str) -> Optional[bytes]:
        """Get value from Redis with fallback to local cache."""
        # Try Redis first
        result = self._retry_on_fail(
            self._client.get if self._client else lambda k: None,
            key,
            fallback_return=None
        )
        
        if result is not None:
            # Update local fallback cache
            with self._fallback_lock:
                self._fallback_cache[key] = (result, None)  # No expiry in fallback
            return result
        
        # Redis miss or failure - check fallback cache
        with self._fallback_lock:
            if key in self._fallback_cache:
                value, expiry = self._fallback_cache[key]
                if expiry is None or time.time() < expiry:
                    logger.debug(f"Redis fallback cache hit: {key}")
                    return value
                else:
                    # Expired, remove from cache
                    del self._fallback_cache[key]
        
        return None
    
    def set(
        self,
        key: str,
        value: bytes,
        ex: Optional[int] = None,
        nx: bool = False,
        xx: bool = False
    ) -> bool:
        """Set value in Redis with retry. Returns True if successful.
        
        Also updates local fallback cache for reads during degradation.
        """
        # Update fallback cache first (optimistic)
        expiry_time = time.time() + ex if ex else None
        with self._fallback_lock:
            self._fallback_cache[key] = (value, expiry_time)
        
        # Try Redis
        success = self._retry_on_fail(
            self._client.set if self._client else lambda *a, **k: False,
            key,
            value,
            ex=ex,
            nx=nx,
            xx=xx,
            fallback_return=False
        ) is not None
        
        return success
    
    def delete(self, *keys: str) -> int:
        """Delete keys from Redis. Returns number of keys deleted."""
        # Remove from fallback cache
        with self._fallback_lock:
            for key in keys:
                self._fallback_cache.pop(key, None)
        
        if not keys:
            return 0
        
        return self._retry_on_fail(
            self._client.delete if self._client else lambda *k: 0,
            *keys,
            fallback_return=0
        ) or 0
    
    def exists(self, *keys: str) -> int:
        """Check if keys exist. Returns count of existing keys."""
        return self._retry_on_fail(
            self._client.exists if self._client else lambda *k: 0,
            *keys,
            fallback_return=0
        ) or 0
    
    def expire(self, key: str, seconds: int) -> bool:
        """Set expiry on key. Returns True if successful."""
        return self._retry_on_fail(
            self._client.expire if self._client else lambda k, s: False,
            key,
            seconds,
            fallback_return=False
        ) or False
    
    def ttl(self, key: str) -> int:
        """Get remaining TTL for key. Returns -2 if key doesn't exist, -1 if no expiry."""
        return self._retry_on_fail(
            self._client.ttl if self._client else lambda k: -2,
            key,
            fallback_return=-2
        ) or -2
    
    def incr(self, key: str, amount: int = 1) -> Optional[int]:
        """Increment key by amount. Returns new value or None on failure."""
        return self._retry_on_fail(
            self._client.incrby if self._client else lambda k, a: None,
            key,
            amount,
            fallback_return=None
        )
    
    def decr(self, key: str, amount: int = 1) -> Optional[int]:
        """Decrement key by amount. Returns new value or None on failure."""
        return self._retry_on_fail(
            self._client.decrby if self._client else lambda k, a: None,
            key,
            amount,
            fallback_return=None
        )
    
    def hget(self, key: str, field: str) -> Optional[bytes]:
        """Get hash field value."""
        return self._retry_on_fail(
            self._client.hget if self._client else lambda k, f: None,
            key,
            field,
            fallback_return=None
        )
    
    def hset(self, key: str, field: str, value: bytes) -> int:
        """Set hash field value. Returns 1 if new field, 0 if updated."""
        return self._retry_on_fail(
            self._client.hset if self._client else lambda k, f, v: 0,
            key,
            field,
            value,
            fallback_return=0
        ) or 0
    
    def hgetall(self, key: str) -> dict:
        """Get all hash fields and values. Returns empty dict on failure."""
        result = self._retry_on_fail(
            self._client.hgetall if self._client else lambda k: {},
            key,
            fallback_return={}
        )
        return result or {}
    
    def lpush(self, key: str, *values: bytes) -> int:
        """Push values to list head. Returns list length or 0 on failure."""
        return self._retry_on_fail(
            self._client.lpush if self._client else lambda k, *v: 0,
            key,
            *values,
            fallback_return=0
        ) or 0
    
    def rpop(self, key: str) -> Optional[bytes]:
        """Pop value from list tail."""
        return self._retry_on_fail(
            self._client.rpop if self._client else lambda k: None,
            key,
            fallback_return=None
        )
    
    def llen(self, key: str) -> int:
        """Get list length."""
        return self._retry_on_fail(
            self._client.llen if self._client else lambda k: 0,
            key,
            fallback_return=0
        ) or 0
    
    # ── Lock Management ────────────────────────────────────────────────
    
    @contextmanager
    def lock(self, key: str, timeout: int = 10, blocking_timeout: float = 0):
        """Acquire distributed lock with local fallback.
        
        In degraded mode, falls back to thread-local locking (warns on collision risk).
        
        Usage:
            with redis.lock("trade_lock", timeout=30):
                execute_trade()
        """
        lock_acquired = False
        local_lock = None
        redis_lock = None
        
        try:
            # Try Redis lock first
            if self._client and self._healthy:
                try:
                    import redis as redis_lib
                    redis_lock = redis_lib.lock.Lock(self._client, key, timeout=timeout)
                    lock_acquired = redis_lock.acquire(blocking_timeout=blocking_timeout)
                except Exception as exc:
                    logger.debug(f"Redis lock acquire failed: {exc}")
            
            # Fallback to local lock if Redis unavailable or lock failed
            if not lock_acquired:
                local_lock = threading.Lock()
                lock_acquired = local_lock.acquire(blocking=False)
                if lock_acquired:
                    logger.warning(
                        f"Using local fallback lock for {key} "
                        "(Redis unavailable - collision risk between instances)"
                    )
                else:
                    raise RuntimeError(f"Could not acquire lock for {key}")
            
            yield lock_acquired
            
        finally:
            if redis_lock and lock_acquired:
                try:
                    redis_lock.release()
                except Exception as exc:
                    logger.debug(f"Redis lock release failed: {exc}")
            elif local_lock and lock_acquired:
                local_lock.release()
    
    # ── Health & Monitoring ──────────────────────────────────────────
    
    @property
    def is_healthy(self) -> bool:
        """Current Redis health status."""
        with self._health_lock:
            return self._healthy
    
    @property
    def degraded_ops_total(self) -> int:
        """Count of operations that fell back to degraded mode."""
        return self._degraded_ops_count
    
    def health_check(self) -> dict:
        """Detailed health status for monitoring."""
        with self._health_lock:
            healthy = self._healthy
            last_check = self._last_healthy_check
        
        return {
            "healthy": healthy,
            "last_check": last_check,
            "seconds_since_check": time.time() - last_check if last_check else None,
            "degraded_ops_count": self._degraded_ops_count,
            "fallback_cache_size": len(self._fallback_cache),
            "client_initialized": self._client is not None,
        }
    
    def clear_fallback_cache(self) -> int:
        """Clear the local fallback cache. Returns number of entries cleared."""
        with self._fallback_lock:
            count = len(self._fallback_cache)
            self._fallback_cache.clear()
            return count


# ── Global Instance ─────────────────────────────────────────────────────

_redis_instance: Optional[ResilientRedis] = None
_redis_lock = threading.Lock()


def get_resilient_redis(url: Optional[str] = None) -> Optional[ResilientRedis]:
    """Get or create global ResilientRedis instance.
    
    Args:
        url: Redis URL. If None, tries to get from settings or env.
        
    Returns:
        ResilientRedis instance or None if Redis is disabled.
    """
    global _redis_instance
    
    # Check if Redis is enabled
    import os
    if os.environ.get("MERID_REDIS_ENABLED", "1").strip() == "0":
        return None
    
    if _redis_instance is not None:
        return _redis_instance
    
    with _redis_lock:
        if _redis_instance is not None:
            return _redis_instance
        
        # Get URL from settings or env
        if url is None:
            try:
                from merid.settings import settings
                url = getattr(settings, "REDIS_URL", None)
            except Exception:
                url = None
            
            if url is None:
                url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        
        try:
            _redis_instance = ResilientRedis(url)
            return _redis_instance
        except Exception as exc:
            logger.debug(f"Redis not available (degraded mode): {exc}")
            return None


def reset_resilient_redis() -> None:
    """Reset the global Redis instance (for testing)."""
    global _redis_instance
    with _redis_lock:
        _redis_instance = None


# ── Convenience Functions ─────────────────────────────────────────────

def redis_get(key: str, default: Optional[bytes] = None) -> Optional[bytes]:
    """Convenience: get value from Redis or return default."""
    redis = get_resilient_redis()
    if redis is None:
        return default
    result = redis.get(key)
    return result if result is not None else default


def redis_set(key: str, value: bytes, ex: Optional[int] = None) -> bool:
    """Convenience: set value in Redis. Returns True on success."""
    redis = get_resilient_redis()
    if redis is None:
        return False
    return redis.set(key, value, ex=ex)


def redis_health() -> dict:
    """Get Redis health status for monitoring endpoints."""
    redis = get_resilient_redis()
    if redis is None:
        return {
            "enabled": False,
            "healthy": False,
            "reason": "Redis disabled (MERID_REDIS_ENABLED=0)"
        }
    return {"enabled": True, **redis.health_check()}
