"""Tests for core/cache_manager.py - Batch B."""
import pytest
import time
import threading
from unittest.mock import MagicMock, patch

from core.cache_manager import (
    CacheEntry, LRUCache, CacheManager,
    get_cache_manager, cached, _cache_manager
)


class TestCacheEntry:
    """Test CacheEntry dataclass."""
    
    def test_cache_entry_creation(self):
        """Test creating a cache entry."""
        entry = CacheEntry(
            key="test_key",
            value="test_value",
            created_at=time.time(),
            last_accessed=time.time(),
            access_count=0,
            ttl=3600,
            size_bytes=100
        )
        assert entry.key == "test_key"
        assert entry.value == "test_value"
        assert entry.ttl == 3600
        assert entry.size_bytes == 100
    
    def test_cache_entry_not_expired(self):
        """Test entry with TTL not expired."""
        entry = CacheEntry(
            key="test",
            value="value",
            created_at=time.time(),
            last_accessed=time.time(),
            ttl=3600
        )
        assert entry.is_expired() is False
    
    def test_cache_entry_expired(self):
        """Test entry that has expired."""
        entry = CacheEntry(
            key="test",
            value="value",
            created_at=time.time() - 4000,  # Created 4000 seconds ago
            last_accessed=time.time() - 4000,
            ttl=3600  # TTL of 1 hour
        )
        assert entry.is_expired() is True
    
    def test_cache_entry_no_ttl_never_expires(self):
        """Test entry without TTL never expires."""
        entry = CacheEntry(
            key="test",
            value="value",
            created_at=time.time() - 100000,
            last_accessed=time.time() - 100000,
            ttl=None
        )
        assert entry.is_expired() is False


class TestLRUCache:
    """Test LRUCache implementation."""
    
    def test_cache_initialization(self):
        """Test cache initialization."""
        cache = LRUCache("test_cache", max_size=100, default_ttl=1800, max_memory_mb=50)
        assert cache.name == "test_cache"
        assert cache.max_size == 100
        assert cache.default_ttl == 1800
        assert cache.max_memory_bytes == 50 * 1024 * 1024
    
    def test_cache_set_and_get(self):
        """Test basic set and get operations."""
        cache = LRUCache("test")
        cache.set("key1", "value1")
        
        result = cache.get("key1")
        assert result == "value1"
    
    def test_cache_miss_returns_none(self):
        """Test cache miss returns None."""
        cache = LRUCache("test")
        result = cache.get("nonexistent_key")
        assert result is None
    
    def test_cache_delete(self):
        """Test deleting a cache entry."""
        cache = LRUCache("test")
        cache.set("key1", "value1")
        
        deleted = cache.delete("key1")
        assert deleted is True
        assert cache.get("key1") is None
    
    def test_cache_delete_nonexistent(self):
        """Test deleting non-existent key returns False."""
        cache = LRUCache("test")
        deleted = cache.delete("nonexistent")
        assert deleted is False
    
    def test_cache_clear(self):
        """Test clearing all entries."""
        cache = LRUCache("test")
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        
        cache.clear()
        
        assert cache.get("key1") is None
        assert cache.get("key2") is None
        assert len(cache._cache) == 0
    
    def test_cache_ttl_expiration(self):
        """Test TTL expiration."""
        cache = LRUCache("test", default_ttl=0.1)  # 100ms TTL
        cache.set("key1", "value1")
        
        # Should be available immediately
        assert cache.get("key1") == "value1"
        
        # Wait for expiration
        time.sleep(0.15)
        
        # Should be expired now
        assert cache.get("key1") is None
    
    def test_cache_custom_ttl(self):
        """Test setting custom TTL."""
        cache = LRUCache("test", default_ttl=3600)
        cache.set("key1", "value1", ttl=0.1)  # Short TTL
        
        time.sleep(0.15)
        assert cache.get("key1") is None
    
    def test_cache_lru_eviction(self):
        """Test LRU eviction when max_size reached."""
        cache = LRUCache("test", max_size=2)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")  # Should evict key1
        
        assert cache.get("key1") is None  # Evicted
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"
    
    def test_cache_access_updates_lru_order(self):
        """Test accessing item updates LRU order."""
        cache = LRUCache("test", max_size=2)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        
        # Access key1 to make it most recently used
        cache.get("key1")
        
        # Add new key, should evict key2 (least recently used)
        cache.set("key3", "value3")
        
        assert cache.get("key1") == "value1"  # Still there
        assert cache.get("key2") is None  # Evicted
        assert cache.get("key3") == "value3"
    
    def test_cache_stats(self):
        """Test cache statistics."""
        cache = LRUCache("test")
        cache.set("key1", "value1")
        cache.get("key1")  # Hit
        cache.get("key2")  # Miss
        
        stats = cache.get_stats()
        
        assert stats["name"] == "test"
        assert stats["size"] == 1
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5
    
    def test_cache_evict_expired(self):
        """Test manual eviction of expired entries."""
        cache = LRUCache("test", default_ttl=0.1)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        
        time.sleep(0.15)
        
        removed = cache._evict_expired()
        assert removed == 2
        assert len(cache._cache) == 0
    
    def test_cache_thread_safety(self):
        """Test thread-safe operations."""
        cache = LRUCache("test", max_size=100)
        errors = []
        
        def worker(worker_id):
            try:
                for i in range(50):
                    cache.set(f"key_{worker_id}_{i}", f"value_{i}")
                    cache.get(f"key_{worker_id}_{i}")
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0


class TestCacheManager:
    """Test CacheManager."""
    
    def test_create_cache(self):
        """Test creating a cache."""
        manager = CacheManager()
        cache = manager.create_cache("my_cache", max_size=50)
        
        assert cache.name == "my_cache"
        assert cache.max_size == 50
    
    def test_create_duplicate_cache_returns_existing(self):
        """Test creating duplicate cache returns existing."""
        manager = CacheManager()
        cache1 = manager.create_cache("test_cache")
        cache2 = manager.create_cache("test_cache")
        
        assert cache1 is cache2
    
    def test_get_cache(self):
        """Test getting a cache by name."""
        manager = CacheManager()
        manager.create_cache("test_cache")
        
        cache = manager.get_cache("test_cache")
        assert cache is not None
        assert cache.name == "test_cache"
    
    def test_get_nonexistent_cache(self):
        """Test getting non-existent cache returns None."""
        manager = CacheManager()
        cache = manager.get_cache("nonexistent")
        assert cache is None
    
    def test_warm_cache(self):
        """Test cache warming."""
        manager = CacheManager()
        manager.create_cache("test_cache")
        
        def loader(key):
            return f"loaded_{key}"
        
        loaded = manager.warm_cache("test_cache", loader, ["key1", "key2", "key3"])
        assert loaded == 3
        
        cache = manager.get_cache("test_cache")
        assert cache.get("key1") == "loaded_key1"
        assert cache.get("key2") == "loaded_key2"
    
    def test_warm_cache_not_found(self):
        """Test warming non-existent cache returns 0."""
        manager = CacheManager()
        
        loaded = manager.warm_cache("nonexistent", lambda k: k, ["key1"])
        assert loaded == 0
    
    def test_warm_cache_with_errors(self):
        """Test warming handles loader errors."""
        manager = CacheManager()
        manager.create_cache("test_cache")
        
        def failing_loader(key):
            if key == "key2":
                raise ValueError("Failed")
            return f"loaded_{key}"
        
        loaded = manager.warm_cache("test_cache", failing_loader, ["key1", "key2", "key3"])
        assert loaded == 2  # key2 failed
    
    def test_get_all_stats(self):
        """Test getting stats for all caches."""
        manager = CacheManager()
        cache1 = manager.create_cache("cache1")
        cache2 = manager.create_cache("cache2")
        
        cache1.set("key", "value")
        cache2.set("key", "value")
        
        stats = manager.get_all_stats()
        
        assert "cache1" in stats
        assert "cache2" in stats
        assert stats["cache1"]["size"] == 1
    
    def test_clear_all(self):
        """Test clearing all caches."""
        manager = CacheManager()
        cache1 = manager.create_cache("cache1")
        cache2 = manager.create_cache("cache2")
        
        cache1.set("key1", "value1")
        cache2.set("key2", "value2")
        
        manager.clear_all()
        
        assert cache1.get("key1") is None
        assert cache2.get("key2") is None
    
    def test_cleanup_expired(self):
        """Test cleanup of expired entries across all caches."""
        manager = CacheManager()
        cache1 = manager.create_cache("cache1", default_ttl=0.1)
        cache2 = manager.create_cache("cache2", default_ttl=0.1)
        
        cache1.set("key1", "value1")
        cache2.set("key2", "value2")
        
        time.sleep(0.15)
        
        removed = manager.cleanup_expired()
        assert removed == 2


class TestGetCacheManager:
    """Test singleton getter."""
    
    def test_get_cache_manager_singleton(self):
        """Test singleton returns same instance."""
        global _cache_manager
        _cache_manager = None  # Reset
        
        manager1 = get_cache_manager()
        manager2 = get_cache_manager()
        
        assert manager1 is manager2


class TestCachedDecorator:
    """Test @cached decorator."""
    
    def test_cached_decorator_caches_result(self):
        """Test decorator caches function result."""
        call_count = 0
        
        @cached("test_cache", ttl=3600)
        def expensive_function(x):
            nonlocal call_count
            call_count += 1
            return x * 2
        
        # First call
        result1 = expensive_function(5)
        assert result1 == 10
        assert call_count == 1
        
        # Second call with same arg - should use cache
        result2 = expensive_function(5)
        assert result2 == 10
        assert call_count == 1  # Not called again
    
    def test_cached_decorator_different_args(self):
        """Test decorator with different arguments."""
        # Reset cache manager to ensure isolation
        import core.cache_manager as cm
        cm._cache_manager = None
        
        call_count = 0
        
        @cached("test_cache_diff")
        def expensive_function(x):
            nonlocal call_count
            call_count += 1
            return x * 2
        
        expensive_function(5)
        expensive_function(10)
        
        assert call_count == 2  # Different args = different cache keys
    
    def test_cached_decorator_creates_cache_if_not_exists(self):
        """Test decorator creates cache if not exists."""
        global _cache_manager
        _cache_manager = None  # Reset
        
        @cached("auto_created_cache")
        def my_function():
            return "result"
        
        my_function()
        
        manager = get_cache_manager()
        cache = manager.get_cache("auto_created_cache")
        assert cache is not None
    
    def test_cached_decorator_with_custom_key_func(self):
        """Test decorator with custom key function."""
        call_count = 0
        
        def key_func(x, y):
            return f"{x}_{y}"
        
        @cached("test_cache", key_func=key_func)
        def expensive_function(x, y):
            nonlocal call_count
            call_count += 1
            return x + y
        
        expensive_function(1, 2)
        expensive_function(1, 2)
        
        assert call_count == 1
