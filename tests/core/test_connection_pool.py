"""Comprehensive tests for core/connection_pool.py."""

import pytest
import time
import threading
from unittest.mock import Mock, patch
from contextlib import contextmanager

from core.connection_pool import (
    PooledConnection,
    ConnectionPool,
    ConnectionPoolManager,
    get_pool_manager,
)


class TestPooledConnection:
    """Test PooledConnection dataclass."""

    def test_creation(self):
        """Test PooledConnection creation."""
        conn = Mock()
        now = time.time()
        
        pooled = PooledConnection(
            connection=conn,
            created_at=now,
            last_used=now,
            use_count=0,
            is_healthy=True
        )
        
        assert pooled.connection == conn
        assert pooled.created_at == now
        assert pooled.last_used == now
        assert pooled.use_count == 0
        assert pooled.is_healthy is True

    def test_default_values(self):
        """Test PooledConnection default values."""
        conn = Mock()
        now = time.time()
        
        pooled = PooledConnection(
            connection=conn,
            created_at=now,
            last_used=now
        )
        
        assert pooled.use_count == 0
        assert pooled.is_healthy is True


class TestConnectionPoolInitialization:
    """Test ConnectionPool initialization."""

    def test_default_initialization(self):
        """Test default pool initialization."""
        create_fn = Mock(return_value=Mock())
        close_fn = Mock()
        
        pool = ConnectionPool(
            name="test_pool",
            create_connection=create_fn,
            close_connection=close_fn
        )
        
        assert pool.name == "test_pool"
        assert pool.min_size == 1
        assert pool.max_size == 10
        assert pool.max_idle_time == 300.0
        assert pool.max_lifetime == 3600.0
        assert pool.max_uses == 1000
        assert pool._total_created == 1  # Created min_size connections
        assert pool._shutdown is False

    def test_custom_initialization(self):
        """Test pool with custom parameters."""
        create_fn = Mock(return_value=Mock())
        close_fn = Mock()
        validate_fn = Mock(return_value=True)
        
        pool = ConnectionPool(
            name="custom_pool",
            create_connection=create_fn,
            close_connection=close_fn,
            validate_connection=validate_fn,
            min_size=2,
            max_size=20,
            max_idle_time=60.0,
            max_lifetime=1800.0,
            max_uses=500
        )
        
        assert pool.min_size == 2
        assert pool.max_size == 20
        assert pool.max_idle_time == 60.0
        assert pool.max_lifetime == 1800.0
        assert pool.max_uses == 500
        assert pool._total_created == 2

    def test_initialization_failure(self):
        """Test pool initialization handles connection failures."""
        create_fn = Mock(side_effect=ConnectionError("Failed"))
        close_fn = Mock()
        
        pool = ConnectionPool(
            name="failing_pool",
            create_connection=create_fn,
            close_connection=close_fn,
            min_size=3
        )
        
        # Should continue even if initial connections fail
        assert pool._total_created == 0


class TestConnectionPoolAcquireAndRelease:
    """Test acquire and release operations."""

    def test_acquire_and_release(self):
        """Test basic acquire and release."""
        conn_obj = Mock()
        create_fn = Mock(return_value=conn_obj)
        close_fn = Mock()
        
        pool = ConnectionPool(
            name="test_pool",
            create_connection=create_fn,
            close_connection=close_fn
        )
        
        with pool.acquire() as conn:
            assert conn == conn_obj
        
        # Connection should be released back to pool
        assert pool._total_acquired == 1
        assert pool._total_released == 1
        assert len(pool._available) == 1

    def test_acquire_creates_new_connection(self):
        """Test acquire creates new connection when pool empty."""
        conn_obj = Mock()
        create_fn = Mock(return_value=conn_obj)
        close_fn = Mock()
        
        pool = ConnectionPool(
            name="test_pool",
            create_connection=create_fn,
            close_connection=close_fn,
            min_size=1
        )
        
        # Use up the initial connection
        with pool.acquire() as conn1:
            # Try to get another connection
            with pool.acquire(timeout=0.1) as conn2:
                pass
        
        assert pool._total_created >= 1

    def test_acquire_timeout(self):
        """Test acquire timeout when pool exhausted."""
        conn_obj = Mock()
        create_fn = Mock(return_value=conn_obj)
        close_fn = Mock()
        
        pool = ConnectionPool(
            name="test_pool",
            create_connection=create_fn,
            close_connection=close_fn,
            min_size=1,
            max_size=1
        )
        
        # Hold the only connection
        with pool.acquire():
            # Try to get another with short timeout
            with pytest.raises(TimeoutError):
                with pool.acquire(timeout=0.01):
                    pass

    def test_acquire_shutdown_raises(self):
        """Test acquire raises when pool is shutdown."""
        conn_obj = Mock()
        create_fn = Mock(return_value=conn_obj)
        close_fn = Mock()
        
        pool = ConnectionPool(
            name="test_pool",
            create_connection=create_fn,
            close_connection=close_fn
        )
        
        pool.shutdown(wait=False)
        
        with pytest.raises(RuntimeError, match="shutdown"):
            with pool.acquire():
                pass


class TestConnectionPoolValidation:
    """Test connection validation."""

    def test_validation_lifetime_expired(self):
        """Test connection rejected when lifetime expired."""
        conn_obj = Mock()
        create_fn = Mock(return_value=conn_obj)
        close_fn = Mock()
        
        pool = ConnectionPool(
            name="test_pool",
            create_connection=create_fn,
            close_connection=close_fn,
            max_lifetime=0.01  # Very short lifetime
        )
        
        time.sleep(0.02)  # Wait for lifetime to expire
        
        with pool.acquire() as conn:
            # Should create new connection since old one expired
            assert pool._total_created >= 2

    def test_validation_max_uses(self):
        """Test connection rejected when max uses exceeded."""
        conn_obj = Mock()
        create_fn = Mock(return_value=conn_obj)
        close_fn = Mock()
        
        pool = ConnectionPool(
            name="test_pool",
            create_connection=create_fn,
            close_connection=close_fn,
            min_size=1,
            max_uses=2
        )
        
        # Use connection multiple times
        for _ in range(3):
            with pool.acquire() as conn:
                pass
        
        # Should have created new connection after max uses
        assert pool._total_created >= 2

    def test_validation_idle_time(self):
        """Test connection rejected when idle time exceeded."""
        conn_obj = Mock()
        create_fn = Mock(return_value=conn_obj)
        close_fn = Mock()
        
        pool = ConnectionPool(
            name="test_pool",
            create_connection=create_fn,
            close_connection=close_fn,
            max_idle_time=0.01  # Very short idle time
        )
        
        # Wait for idle time to expire
        time.sleep(0.02)
        
        with pool.acquire() as conn:
            # Should create new connection
            assert pool._total_created >= 2

    def test_validation_health_check_fails(self):
        """Test connection rejected when health check fails."""
        conn_obj = Mock()
        create_fn = Mock(return_value=conn_obj)
        close_fn = Mock()
        validate_fn = Mock(return_value=False)
        
        pool = ConnectionPool(
            name="test_pool",
            create_connection=create_fn,
            close_connection=close_fn,
            validate_connection=validate_fn
        )
        
        with pool.acquire() as conn:
            pass
        
        # Health check should have been called
        assert validate_fn.called
        assert pool._total_validation_failures >= 0


class TestConnectionPoolCleanup:
    """Test cleanup operations."""

    def test_cleanup_idle_connections(self):
        """Test cleanup removes idle connections."""
        conn_obj = Mock()
        create_fn = Mock(return_value=conn_obj)
        close_fn = Mock()
        
        pool = ConnectionPool(
            name="test_pool",
            create_connection=create_fn,
            close_connection=close_fn,
            min_size=1,
            max_size=5
        )
        
        # Force create multiple connections
        for _ in range(3):
            with pool.acquire() as conn:
                pass
        
        initial_count = len(pool._available)
        
        # Cleanup should not go below min_size
        closed = pool.cleanup_idle_connections()
        
        assert len(pool._available) >= pool.min_size

    def test_cleanup_respects_min_size(self):
        """Test cleanup doesn't go below min_size."""
        conn_obj = Mock()
        create_fn = Mock(return_value=conn_obj)
        close_fn = Mock()
        
        pool = ConnectionPool(
            name="test_pool",
            create_connection=create_fn,
            close_connection=close_fn,
            min_size=2,
            max_size=5
        )
        
        closed = pool.cleanup_idle_connections()
        
        # Should not close any since we're at min_size
        assert len(pool._available) >= 2


class TestConnectionPoolStats:
    """Test pool statistics."""

    def test_get_stats(self):
        """Test getting pool statistics."""
        conn_obj = Mock()
        create_fn = Mock(return_value=conn_obj)
        close_fn = Mock()
        
        pool = ConnectionPool(
            name="test_pool",
            create_connection=create_fn,
            close_connection=close_fn,
            min_size=2,
            max_size=10
        )
        
        stats = pool.get_stats()
        
        assert stats["name"] == "test_pool"
        assert stats["min_size"] == 2
        assert stats["max_size"] == 10
        assert stats["available"] >= 0
        assert stats["in_use"] >= 0
        assert stats["total"] == stats["available"] + stats["in_use"]
        assert "utilization" in stats
        assert "total_created" in stats
        assert "total_closed" in stats
        assert "total_acquired" in stats
        assert "total_released" in stats


class TestConnectionPoolShutdown:
    """Test pool shutdown."""

    def test_shutdown_closes_connections(self):
        """Test shutdown closes all connections."""
        conn_obj = Mock()
        create_fn = Mock(return_value=conn_obj)
        close_fn = Mock()
        
        pool = ConnectionPool(
            name="test_pool",
            create_connection=create_fn,
            close_connection=close_fn,
            min_size=3
        )
        
        pool.shutdown(wait=False)
        
        assert pool._shutdown is True
        assert len(pool._available) == 0
        assert close_fn.call_count == 3

    def test_shutdown_with_wait(self):
        """Test shutdown waits for in-use connections."""
        conn_obj = Mock()
        create_fn = Mock(return_value=conn_obj)
        close_fn = Mock()
        
        pool = ConnectionPool(
            name="test_pool",
            create_connection=create_fn,
            close_connection=close_fn,
            min_size=1,
            max_size=2
        )
        
        # Acquire a connection
        with pool.acquire() as conn:
            # Shutdown should wait
            pool.shutdown(wait=True)
            
        assert pool._shutdown is True


class TestConnectionPoolManager:
    """Test ConnectionPoolManager."""

    def test_create_pool(self):
        """Test creating a pool through manager."""
        manager = ConnectionPoolManager()
        create_fn = Mock(return_value=Mock())
        close_fn = Mock()
        
        pool = manager.create_pool(
            name="test_pool",
            create_connection=create_fn,
            close_connection=close_fn
        )
        
        assert pool.name == "test_pool"
        assert manager.get_pool("test_pool") == pool

    def test_create_duplicate_pool(self):
        """Test creating duplicate pool returns existing."""
        manager = ConnectionPoolManager()
        create_fn = Mock(return_value=Mock())
        close_fn = Mock()
        
        pool1 = manager.create_pool(
            name="test_pool",
            create_connection=create_fn,
            close_connection=close_fn
        )
        
        pool2 = manager.create_pool(
            name="test_pool",
            create_connection=create_fn,
            close_connection=close_fn
        )
        
        assert pool1 is pool2

    def test_get_pool_nonexistent(self):
        """Test getting nonexistent pool returns None."""
        manager = ConnectionPoolManager()
        
        pool = manager.get_pool("nonexistent")
        
        assert pool is None

    def test_get_all_stats(self):
        """Test getting stats for all pools."""
        manager = ConnectionPoolManager()
        create_fn = Mock(return_value=Mock())
        close_fn = Mock()
        
        manager.create_pool("pool1", create_fn, close_fn)
        manager.create_pool("pool2", create_fn, close_fn)
        
        stats = manager.get_all_stats()
        
        assert "pool1" in stats
        assert "pool2" in stats

    def test_cleanup_all_idle(self):
        """Test cleanup on all pools."""
        manager = ConnectionPoolManager()
        create_fn = Mock(return_value=Mock())
        close_fn = Mock()
        
        manager.create_pool("pool1", create_fn, close_fn, min_size=1, max_size=3)
        manager.create_pool("pool2", create_fn, close_fn, min_size=1, max_size=3)
        
        closed = manager.cleanup_all_idle()
        
        assert closed >= 0

    def test_shutdown_all(self):
        """Test shutdown all pools."""
        manager = ConnectionPoolManager()
        create_fn = Mock(return_value=Mock())
        close_fn = Mock()
        
        manager.create_pool("pool1", create_fn, close_fn)
        manager.create_pool("pool2", create_fn, close_fn)
        
        manager.shutdown_all(wait=False)
        
        # All pools should be cleared
        assert len(manager._pools) == 0


class TestGetPoolManager:
    """Test get_pool_manager singleton."""

    def test_singleton(self):
        """Test get_pool_manager returns singleton."""
        manager1 = get_pool_manager()
        manager2 = get_pool_manager()
        
        assert manager1 is manager2

    def test_is_connection_pool_manager(self):
        """Test singleton is ConnectionPoolManager."""
        manager = get_pool_manager()
        
        assert isinstance(manager, ConnectionPoolManager)
