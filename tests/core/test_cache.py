"""Comprehensive tests for core/cache.py."""

import pytest
import json
import time
from unittest.mock import Mock, patch, MagicMock

from core.cache import CacheAdapter, cache


class TestCacheAdapterInitialization:
    """Test CacheAdapter initialization."""

    def test_default_initialization(self):
        """CacheAdapter should initialize with Redis if available, or fall back to memory."""
        from core.cache import CacheAdapter
        adapter = CacheAdapter()
        # Adapter should always initialize successfully
        assert adapter is not None
        assert adapter._local_store == {}
        assert adapter._local_expiry == {}
        # Redis may or may not be available depending on environment
        # If available, client will be set; if not, client will be None

    @patch("core.cache.redis")
    def test_initialization_with_redis(self, mock_redis):
        """Test initialization with Redis available."""
        mock_client = Mock()
        mock_client.ping.return_value = True
        mock_redis.Redis.from_url.return_value = mock_client
        
        adapter = CacheAdapter()
        
        assert adapter._client == mock_client

    @patch("core.cache.redis")
    def test_initialization_redis_connection_error(self, mock_redis):
        """Test initialization falls back to memory on Redis error."""
        mock_redis.Redis.from_url.side_effect = ConnectionError("Redis unavailable")
        
        adapter = CacheAdapter()
        
        assert adapter._client is None

    @patch("core.cache.redis", None)
    def test_initialization_redis_not_installed(self):
        """Test initialization when redis library not installed."""
        adapter = CacheAdapter()
        
        assert adapter._client is None


class TestCacheAdapterNow:
    """Test _now method."""

    def test_now_returns_float(self):
        """Test _now returns current time as float."""
        adapter = CacheAdapter()
        
        now = adapter._now()
        
        assert isinstance(now, float)
        assert now > 0

    def test_now_increases_over_time(self):
        """Test _now increases over time."""
        adapter = CacheAdapter()
        
        before = adapter._now()
        time.sleep(0.01)
        after = adapter._now()
        
        assert after > before


class TestCacheAdapterSetAndGet:
    """Test set and get methods."""

    def test_set_and_get_memory(self):
        """Test setting and getting from memory."""
        adapter = CacheAdapter()
        
        adapter.set("key1", "value1", ttl=60)
        result = adapter.get("key1")
        
        assert result == "value1"

    def test_get_nonexistent_key(self):
        """Test getting nonexistent key returns None."""
        adapter = CacheAdapter()
        
        result = adapter.get("nonexistent")
        
        assert result is None

    def test_set_overwrites_existing(self):
        """Test setting overwrites existing value."""
        adapter = CacheAdapter()
        
        adapter.set("key1", "value1", ttl=60)
        adapter.set("key1", "value2", ttl=60)
        result = adapter.get("key1")
        
        assert result == "value2"

    def test_ttl_expires_value(self):
        """Test value expires after TTL."""
        adapter = CacheAdapter()
        
        adapter.set("key1", "value1", ttl=1)
        assert adapter.get("key1") == "value1"
        
        time.sleep(1.1)
        result = adapter.get("key1")
        
        assert result is None

    def test_ttl_extends_expiry(self):
        """Test setting with new TTL extends expiry."""
        adapter = CacheAdapter()
        
        adapter.set("key1", "value1", ttl=1)
        time.sleep(0.5)
        
        # Reset with longer TTL
        adapter.set("key1", "value2", ttl=5)
        time.sleep(0.7)
        
        # Should still exist
        result = adapter.get("key1")
        assert result == "value2"

    @patch("core.cache.redis")
    def test_set_with_redis(self, mock_redis):
        """Test setting with Redis client."""
        mock_client = Mock()
        mock_redis.Redis.from_url.return_value = mock_client
        
        adapter = CacheAdapter()
        adapter.set("key1", "value1", ttl=60)
        
        mock_client.set.assert_called_once_with("key1", "value1", ex=60)

    @patch("core.cache.redis")
    def test_get_with_redis(self, mock_redis):
        """Test getting with Redis client."""
        mock_client = Mock()
        mock_client.get.return_value = "redis_value"
        mock_redis.Redis.from_url.return_value = mock_client
        
        adapter = CacheAdapter()
        result = adapter.get("key1")
        
        assert result == "redis_value"
        mock_client.get.assert_called_once_with("key1")

    @patch("core.cache.redis")
    def test_redis_get_fallback_to_memory(self, mock_redis):
        """Test fallback to memory on Redis get error."""
        mock_client = Mock()
        mock_client.get.side_effect = ConnectionError("Redis down")
        mock_client.set.side_effect = ConnectionError("Redis down")  # Also fail set to force memory fallback
        mock_redis.Redis.from_url.return_value = mock_client
        
        adapter = CacheAdapter()
        # Set will fall back to memory (Redis set fails)
        adapter.set("key1", "memory_value", ttl=60)
        # Get should fall back to memory when Redis fails
        result = adapter.get("key1")
        
        assert result == "memory_value"

    @patch("core.cache.redis")
    def test_redis_set_fallback_to_memory(self, mock_redis):
        """Test fallback to memory on Redis set error."""
        mock_client = Mock()
        mock_client.set.side_effect = ConnectionError("Redis down")
        mock_client.get.side_effect = ConnectionError("Redis down")  # Also fail get for fallback test
        mock_redis.Redis.from_url.return_value = mock_client
        
        adapter = CacheAdapter()
        adapter.set("key1", "value1", ttl=60)
        # Get should also fall back to memory
        result = adapter.get("key1")
        
        assert result == "value1"


class TestCacheAdapterSetJsonAndGetJson:
    """Test set_json and get_json methods."""

    def test_set_and_get_json_dict(self):
        """Test setting and getting JSON dict."""
        adapter = CacheAdapter()
        data = {"name": "test", "value": 123}
        
        adapter.set_json("key1", data, ttl=60)
        result = adapter.get_json("key1")
        
        assert result == data

    def test_set_and_get_json_list(self):
        """Test setting and getting JSON list."""
        adapter = CacheAdapter()
        data = [1, 2, 3, {"nested": "dict"}]
        
        adapter.set_json("key1", data, ttl=60)
        result = adapter.get_json("key1")
        
        assert result == data

    def test_get_json_nonexistent(self):
        """Test get_json returns None for nonexistent key."""
        adapter = CacheAdapter()
        
        result = adapter.get_json("nonexistent")
        
        assert result is None

    def test_get_json_invalid_json(self):
        """Test get_json returns None for invalid JSON."""
        adapter = CacheAdapter()
        
        adapter.set("key1", "not valid json", ttl=60)
        result = adapter.get_json("key1")
        
        assert result is None

    def test_set_json_complex_object(self):
        """Test set_json with complex nested object."""
        adapter = CacheAdapter()
        data = {
            "users": [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"}
            ],
            "count": 2,
            "active": True
        }
        
        adapter.set_json("users", data, ttl=60)
        result = adapter.get_json("users")
        
        assert result == data


class TestCacheAdapterDelete:
    """Test delete method."""

    def test_delete_existing_key(self):
        """Test deleting existing key."""
        adapter = CacheAdapter()
        adapter.set("key1", "value1", ttl=60)
        
        adapter.delete("key1")
        result = adapter.get("key1")
        
        assert result is None

    def test_delete_nonexistent_key(self):
        """Test deleting nonexistent key doesn't error."""
        adapter = CacheAdapter()
        
        adapter.delete("nonexistent")  # Should not raise

    def test_delete_removes_expiry(self):
        """Test delete removes expiry entry."""
        adapter = CacheAdapter()
        adapter.set("key1", "value1", ttl=60)
        
        adapter.delete("key1")
        
        assert "key1" not in adapter._local_expiry
        assert "key1" not in adapter._local_store

    @patch("core.cache.redis")
    def test_delete_with_redis(self, mock_redis):
        """Test delete with Redis client."""
        mock_client = Mock()
        mock_redis.Redis.from_url.return_value = mock_client
        
        adapter = CacheAdapter()
        adapter.delete("key1")
        
        mock_client.delete.assert_called_once_with("key1")

    @patch("core.cache.redis")
    def test_delete_redis_error_continues(self, mock_redis):
        """Test delete continues even if Redis error."""
        mock_client = Mock()
        mock_client.delete.side_effect = ConnectionError("Redis down")
        mock_client.get.side_effect = ConnectionError("Redis down")  # Also fail get for fallback test
        mock_redis.Redis.from_url.return_value = mock_client
        
        adapter = CacheAdapter()
        adapter.set("key1", "value1", ttl=60)
        adapter.delete("key1")  # Should not raise
        # Get should fall back to memory and return None after delete
        result = adapter.get("key1")
        
        assert result is None
        # Local cache should still be cleared
        assert adapter.get("key1") is None


class TestCacheAdapterConcurrency:
    """Test thread safety with locks."""

    def test_concurrent_set_and_get(self):
        """Test concurrent set and get operations."""
        import threading
        
        adapter = CacheAdapter()
        results = []
        
        def setter():
            for i in range(10):
                adapter.set(f"key{i}", f"value{i}", ttl=60)
        
        def getter():
            for i in range(10):
                val = adapter.get(f"key{i}")
                results.append(val)
        
        threads = [
            threading.Thread(target=setter),
            threading.Thread(target=getter)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Should complete without errors
        assert len(results) == 10


class TestGlobalCache:
    """Test global cache instance."""

    def test_global_cache_exists(self):
        """Test global cache instance exists."""
        assert cache is not None
        assert isinstance(cache, CacheAdapter)

    def test_global_cache_operations(self):
        """Test operations on global cache."""
        cache.set("test_key", "test_value", ttl=60)
        result = cache.get("test_key")
        
        assert result == "test_value"
        
        # Cleanup
        cache.delete("test_key")
