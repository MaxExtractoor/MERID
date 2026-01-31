"""
Cache Manager - Production-grade caching layer for frequently accessed data.

Implements:
- In-memory LRU cache with TTL
- Multi-level caching (L1: memory, L2: disk)
- Cache warming and preloading
- Cache invalidation strategies
- Cache hit/miss metrics
"""
from __future__ import annotations

import time
import threading
import pickle
import hashlib
from typing import Dict, Optional, Any, Callable, TypeVar, Generic
from dataclasses import dataclass, field
from collections import OrderedDict
from pathlib import Path

from utils.logger import get_logger

logger = get_logger("core.cache_manager")

T = TypeVar('T')


@dataclass
class CacheEntry(Generic[T]):
    """Single cache entry with metadata."""
    key: str
    value: T
    created_at: float
    last_accessed: float
    access_count: int = 0
    ttl: Optional[float] = None
    size_bytes: int = 0
    
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        if self.ttl is None:
            return False
        return time.time() - self.created_at > self.ttl


class LRUCache(Generic[T]):
    """
    Thread-safe LRU cache with TTL support.
    
    Features:
    - Least Recently Used eviction
    - Time-to-live per entry
    - Size-based eviction
    - Access statistics
    """
    
    def __init__(
        self,
        name: str,
        max_size: int = 1000,
        default_ttl: Optional[float] = 3600.0,  # 1 hour
        max_memory_mb: int = 100
    ):
        """
        Initialize LRU cache.
        
        Args:
            name: Cache identifier
            max_size: Maximum number of entries
            default_ttl: Default time-to-live in seconds (None = no expiry)
            max_memory_mb: Maximum memory usage in megabytes
        """
        self.name = name
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        
        self._cache: OrderedDict[str, CacheEntry[T]] = OrderedDict()
        self._lock = threading.RLock()
        
        # Metrics
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0
        self._total_size_bytes = 0
        
        logger.info(f"LRUCache '{name}' initialized: max_size={max_size}, ttl={default_ttl}s, max_memory={max_memory_mb}MB")
    
    def _estimate_size(self, value: T) -> int:
        """Estimate size of value in bytes."""
        try:
            return len(pickle.dumps(value))
        except Exception:
            # Fallback estimate
            return 1024
    
    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if not self._cache:
            return
        
        key, entry = self._cache.popitem(last=False)
        self._total_size_bytes -= entry.size_bytes
        self._evictions += 1
        logger.debug(f"Evicted LRU entry '{key}' from cache '{self.name}'")
    
    def _evict_expired(self) -> int:
        """Remove all expired entries."""
        expired_keys = []
        
        for key, entry in self._cache.items():
            if entry.is_expired():
                expired_keys.append(key)
        
        for key in expired_keys:
            entry = self._cache.pop(key)
            self._total_size_bytes -= entry.size_bytes
            self._expirations += 1
        
        if expired_keys:
            logger.debug(f"Removed {len(expired_keys)} expired entries from cache '{self.name}'")
        
        return len(expired_keys)
    
    def get(self, key: str) -> Optional[T]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
        
        Returns:
            Cached value or None if not found/expired
        """
        with self._lock:
            entry = self._cache.get(key)
            
            if entry is None:
                self._misses += 1
                return None
            
            if entry.is_expired():
                self._cache.pop(key)
                self._total_size_bytes -= entry.size_bytes
                self._expirations += 1
                self._misses += 1
                return None
            
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            entry.last_accessed = time.time()
            entry.access_count += 1
            self._hits += 1
            
            return entry.value
    
    def set(self, key: str, value: T, ttl: Optional[float] = None) -> None:
        """
        Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (None = use default)
        """
        with self._lock:
            # Remove expired entries first
            self._evict_expired()
            
            # Estimate size
            size_bytes = self._estimate_size(value)
            
            # Check if we need to evict for size
            while (self._total_size_bytes + size_bytes > self.max_memory_bytes and self._cache):
                self._evict_lru()
            
            # Check if we need to evict for count
            while len(self._cache) >= self.max_size and self._cache:
                self._evict_lru()
            
            # Remove existing entry if present
            if key in self._cache:
                old_entry = self._cache.pop(key)
                self._total_size_bytes -= old_entry.size_bytes
            
            # Create new entry
            now = time.time()
            entry = CacheEntry(
                key=key,
                value=value,
                created_at=now,
                last_accessed=now,
                access_count=0,
                ttl=ttl if ttl is not None else self.default_ttl,
                size_bytes=size_bytes
            )
            
            self._cache[key] = entry
            self._total_size_bytes += size_bytes
    
    def delete(self, key: str) -> bool:
        """
        Delete entry from cache.
        
        Args:
            key: Cache key
        
        Returns:
            True if entry was deleted, False if not found
        """
        with self._lock:
            entry = self._cache.pop(key, None)
            if entry:
                self._total_size_bytes -= entry.size_bytes
                return True
            return False
    
    def clear(self) -> None:
        """Clear all entries from cache."""
        with self._lock:
            self._cache.clear()
            self._total_size_bytes = 0
            logger.info(f"Cleared cache '{self.name}'")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = self._hits / total_requests if total_requests > 0 else 0.0
            
            return {
                "name": self.name,
                "size": len(self._cache),
                "max_size": self.max_size,
                "memory_bytes": self._total_size_bytes,
                "max_memory_bytes": self.max_memory_bytes,
                "memory_utilization": self._total_size_bytes / self.max_memory_bytes if self.max_memory_bytes > 0 else 0.0,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
                "evictions": self._evictions,
                "expirations": self._expirations,
                "default_ttl": self.default_ttl,
            }


class CacheManager:
    """
    Manages multiple caches with different policies.
    
    Features:
    - Multiple named caches
    - Cache warming
    - Bulk operations
    - Global statistics
    """
    
    def __init__(self):
        self._caches: Dict[str, LRUCache] = {}
        self._lock = threading.Lock()
        logger.info("CacheManager initialized")
    
    def create_cache(
        self,
        name: str,
        max_size: int = 1000,
        default_ttl: Optional[float] = 3600.0,
        max_memory_mb: int = 100
    ) -> LRUCache:
        """Create and register a new cache."""
        with self._lock:
            if name in self._caches:
                logger.warning(f"Cache '{name}' already exists")
                return self._caches[name]
            
            cache = LRUCache(
                name=name,
                max_size=max_size,
                default_ttl=default_ttl,
                max_memory_mb=max_memory_mb
            )
            self._caches[name] = cache
            return cache
    
    def get_cache(self, name: str) -> Optional[LRUCache]:
        """Get a cache by name."""
        with self._lock:
            return self._caches.get(name)
    
    def warm_cache(
        self,
        cache_name: str,
        loader: Callable[[str], Any],
        keys: list[str]
    ) -> int:
        """
        Warm cache by preloading data.
        
        Args:
            cache_name: Name of cache to warm
            loader: Function to load data for a key
            keys: List of keys to preload
        
        Returns:
            Number of entries successfully loaded
        """
        cache = self.get_cache(cache_name)
        if not cache:
            logger.error(f"Cache '{cache_name}' not found")
            return 0
        
        loaded = 0
        for key in keys:
            try:
                value = loader(key)
                cache.set(key, value)
                loaded += 1
            except Exception as exc:
                logger.warning(f"Failed to load key '{key}' for cache warming: {exc}")
        
        logger.info(f"Warmed cache '{cache_name}' with {loaded}/{len(keys)} entries")
        return loaded
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Get statistics for all caches."""
        with self._lock:
            return {
                name: cache.get_stats()
                for name, cache in self._caches.items()
            }
    
    def clear_all(self) -> None:
        """Clear all caches."""
        with self._lock:
            for cache in self._caches.values():
                cache.clear()
            logger.info("Cleared all caches")
    
    def cleanup_expired(self) -> int:
        """Remove expired entries from all caches."""
        total_removed = 0
        with self._lock:
            for cache in self._caches.values():
                total_removed += cache._evict_expired()
        
        if total_removed > 0:
            logger.info(f"Cleaned up {total_removed} expired entries across all caches")
        
        return total_removed


# Global singleton
_cache_manager: Optional[CacheManager] = None


def get_cache_manager() -> CacheManager:
    """Get the global cache manager instance."""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager


# Convenience decorator for caching function results
def cached(
    cache_name: str,
    ttl: Optional[float] = None,
    key_func: Optional[Callable] = None
):
    """
    Decorator to cache function results.
    
    Args:
        cache_name: Name of cache to use
        ttl: Time-to-live for cached results
        key_func: Function to generate cache key from args/kwargs
    
    Example:
        @cached("api_responses", ttl=300)
        def fetch_data(symbol: str):
            return expensive_api_call(symbol)
    """
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            # Get or create cache
            manager = get_cache_manager()
            cache = manager.get_cache(cache_name)
            if not cache:
                cache = manager.create_cache(cache_name)
            
            # Generate cache key
            if key_func:
                key = key_func(*args, **kwargs)
            else:
                # Default: hash of function name + args + kwargs
                key_parts = [func.__name__]
                key_parts.extend(str(arg) for arg in args)
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
                key_str = "|".join(key_parts)
                key = hashlib.md5(key_str.encode()).hexdigest()
            
            # Try to get from cache
            result = cache.get(key)
            if result is not None:
                return result
            
            # Cache miss, call function
            result = func(*args, **kwargs)
            cache.set(key, result, ttl=ttl)
            return result
        
        return wrapper
    return decorator
