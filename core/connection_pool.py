"""
Connection Pool Manager - Production-grade connection pooling for external APIs.

Manages persistent connections to external services with:
- Automatic connection reuse
- Health checking and auto-recovery
- Configurable pool sizes
- Connection lifecycle management
"""
from __future__ import annotations

import asyncio
import time
import threading
from typing import Dict, Optional, Any, Callable, Generic, TypeVar
from dataclasses import dataclass, field
from collections import deque
from contextlib import asynccontextmanager, contextmanager

from utils.logger import get_logger

logger = get_logger("core.connection_pool")

T = TypeVar('T')


@dataclass
class PooledConnection(Generic[T]):
    """Wrapper for a pooled connection."""
    connection: T
    created_at: float
    last_used: float
    use_count: int = 0
    is_healthy: bool = True


class ConnectionPool(Generic[T]):
    """
    Generic connection pool for any resource type.
    
    Features:
    - Min/max pool size enforcement
    - Idle connection cleanup
    - Health checking
    - Connection lifecycle hooks
    - Thread-safe operations
    """
    
    def __init__(
        self,
        name: str,
        create_connection: Callable[[], T],
        close_connection: Callable[[T], None],
        validate_connection: Optional[Callable[[T], bool]] = None,
        min_size: int = 1,
        max_size: int = 10,
        max_idle_time: float = 300.0,  # 5 minutes
        max_lifetime: float = 3600.0,  # 1 hour
        max_uses: int = 1000,
    ):
        """
        Initialize connection pool.
        
        Args:
            name: Pool identifier
            create_connection: Factory function to create new connections
            close_connection: Function to close connections
            validate_connection: Function to validate connection health
            min_size: Minimum number of connections to maintain
            max_size: Maximum number of connections allowed
            max_idle_time: Max time connection can be idle before cleanup
            max_lifetime: Max lifetime of a connection before recreation
            max_uses: Max number of uses before connection recreation
        """
        self.name = name
        self._create_connection = create_connection
        self._close_connection = close_connection
        self._validate_connection = validate_connection or (lambda _: True)
        
        self.min_size = min_size
        self.max_size = max_size
        self.max_idle_time = max_idle_time
        self.max_lifetime = max_lifetime
        self.max_uses = max_uses
        
        self._available: deque[PooledConnection[T]] = deque()
        self._in_use: Dict[int, PooledConnection[T]] = {}
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        
        self._total_created = 0
        self._total_closed = 0
        self._total_acquired = 0
        self._total_released = 0
        self._total_validation_failures = 0
        
        self._shutdown = False
        
        # Initialize minimum connections
        self._initialize_pool()
        
        logger.info(
            f"ConnectionPool '{name}' initialized: min={min_size}, max={max_size}, "
            f"max_idle={max_idle_time}s, max_lifetime={max_lifetime}s"
        )
    
    def _initialize_pool(self) -> None:
        """Create minimum number of connections."""
        with self._lock:
            for _ in range(self.min_size):
                try:
                    conn = self._create_new_connection()
                    self._available.append(conn)
                except Exception as exc:
                    logger.error(f"Failed to create initial connection for pool '{self.name}': {exc}")
    
    def _create_new_connection(self) -> PooledConnection[T]:
        """Create a new pooled connection."""
        try:
            connection = self._create_connection()
            self._total_created += 1
            
            pooled = PooledConnection(
                connection=connection,
                created_at=time.time(),
                last_used=time.time(),
                use_count=0,
                is_healthy=True
            )
            
            logger.debug(f"Created new connection for pool '{self.name}' (total: {self._total_created})")
            return pooled
        except Exception as exc:
            logger.error(f"Failed to create connection for pool '{self.name}': {exc}")
            raise
    
    def _close_connection_internal(self, pooled: PooledConnection[T]) -> None:
        """Close a pooled connection."""
        try:
            self._close_connection(pooled.connection)
            self._total_closed += 1
            logger.debug(f"Closed connection for pool '{self.name}' (total: {self._total_closed})")
        except Exception as exc:
            logger.error(f"Error closing connection for pool '{self.name}': {exc}")
    
    def _validate_pooled_connection(self, pooled: PooledConnection[T]) -> bool:
        """Check if pooled connection is still valid."""
        now = time.time()
        
        # Check age
        if now - pooled.created_at > self.max_lifetime:
            logger.debug(f"Connection exceeded max lifetime ({self.max_lifetime}s)")
            return False
        
        # Check use count
        if pooled.use_count >= self.max_uses:
            logger.debug(f"Connection exceeded max uses ({self.max_uses})")
            return False
        
        # Check idle time
        if now - pooled.last_used > self.max_idle_time:
            logger.debug(f"Connection exceeded max idle time ({self.max_idle_time}s)")
            return False
        
        # Check health
        try:
            if not self._validate_connection(pooled.connection):
                logger.debug("Connection failed health check")
                self._total_validation_failures += 1
                return False
        except Exception as exc:
            logger.warning(f"Connection validation error: {exc}")
            self._total_validation_failures += 1
            return False
        
        return True
    
    @contextmanager
    def acquire(self, timeout: Optional[float] = 30.0):
        """
        Acquire a connection from the pool (blocking).
        
        Args:
            timeout: Max time to wait for connection (None = wait forever)
        
        Yields:
            Connection object
        
        Raises:
            TimeoutError: If connection not available within timeout
            RuntimeError: If pool is shutdown
        """
        conn = self._acquire_connection(timeout)
        try:
            yield conn.connection
        finally:
            self._release_connection(conn)
    
    def _acquire_connection(self, timeout: Optional[float]) -> PooledConnection[T]:
        """Internal method to acquire a connection."""
        start_time = time.time()
        
        with self._condition:
            while True:
                if self._shutdown:
                    raise RuntimeError(f"Pool '{self.name}' is shutdown")
                
                # Try to get available connection
                while self._available:
                    pooled = self._available.popleft()
                    
                    # Validate connection
                    if self._validate_pooled_connection(pooled):
                        pooled.last_used = time.time()
                        pooled.use_count += 1
                        self._in_use[id(pooled)] = pooled
                        self._total_acquired += 1
                        return pooled
                    else:
                        # Connection invalid, close it
                        self._close_connection_internal(pooled)
                
                # No available connections, try to create new one
                total_connections = len(self._available) + len(self._in_use)
                if total_connections < self.max_size:
                    try:
                        pooled = self._create_new_connection()
                        pooled.last_used = time.time()
                        pooled.use_count += 1
                        self._in_use[id(pooled)] = pooled
                        self._total_acquired += 1
                        return pooled
                    except Exception as exc:
                        logger.error(f"Failed to create connection: {exc}")
                        # Fall through to wait
                
                # Pool exhausted, wait for connection to be released
                if timeout is not None:
                    elapsed = time.time() - start_time
                    remaining = timeout - elapsed
                    if remaining <= 0:
                        raise TimeoutError(f"Timeout acquiring connection from pool '{self.name}'")
                    self._condition.wait(remaining)
                else:
                    self._condition.wait()
    
    def _release_connection(self, pooled: PooledConnection[T]) -> None:
        """Internal method to release a connection back to pool."""
        with self._condition:
            if id(pooled) not in self._in_use:
                logger.warning(f"Attempted to release connection not in use")
                return
            
            del self._in_use[id(pooled)]
            self._total_released += 1
            
            # Check if connection should be kept
            if self._validate_pooled_connection(pooled):
                self._available.append(pooled)
            else:
                # Connection no longer valid, close it
                self._close_connection_internal(pooled)
                
                # Maintain minimum pool size
                total_connections = len(self._available) + len(self._in_use)
                if total_connections < self.min_size:
                    try:
                        new_conn = self._create_new_connection()
                        self._available.append(new_conn)
                    except Exception as exc:
                        logger.error(f"Failed to maintain minimum pool size: {exc}")
            
            # Notify waiting threads
            self._condition.notify()
    
    def cleanup_idle_connections(self) -> int:
        """
        Remove idle connections exceeding max_idle_time.
        
        Returns:
            Number of connections closed
        """
        closed_count = 0
        
        with self._lock:
            # Don't cleanup below minimum size
            target_size = max(self.min_size, len(self._in_use))
            
            while len(self._available) > target_size:
                pooled = self._available.popleft()
                
                if not self._validate_pooled_connection(pooled):
                    self._close_connection_internal(pooled)
                    closed_count += 1
                else:
                    # Still valid, put it back
                    self._available.append(pooled)
                    break
        
        if closed_count > 0:
            logger.info(f"Cleaned up {closed_count} idle connections from pool '{self.name}'")
        
        return closed_count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get pool statistics."""
        with self._lock:
            return {
                "name": self.name,
                "available": len(self._available),
                "in_use": len(self._in_use),
                "total": len(self._available) + len(self._in_use),
                "min_size": self.min_size,
                "max_size": self.max_size,
                "utilization": len(self._in_use) / self.max_size if self.max_size > 0 else 0.0,
                "total_created": self._total_created,
                "total_closed": self._total_closed,
                "total_acquired": self._total_acquired,
                "total_released": self._total_released,
                "total_validation_failures": self._total_validation_failures,
            }
    
    def shutdown(self, wait: bool = True) -> None:
        """
        Shutdown the pool and close all connections.
        
        Args:
            wait: If True, wait for all in-use connections to be released
        """
        logger.info(f"Shutting down connection pool '{self.name}'...")
        
        with self._condition:
            self._shutdown = True
            
            if wait:
                # Wait for all connections to be released
                while self._in_use:
                    logger.info(f"Waiting for {len(self._in_use)} connections to be released...")
                    self._condition.wait(timeout=1.0)
            
            # Close all available connections
            while self._available:
                pooled = self._available.popleft()
                self._close_connection_internal(pooled)
            
            # Force close any remaining in-use connections
            for pooled in list(self._in_use.values()):
                self._close_connection_internal(pooled)
            self._in_use.clear()
        
        logger.info(f"Connection pool '{self.name}' shutdown complete")


class ConnectionPoolManager:
    """Manages multiple connection pools."""
    
    def __init__(self):
        self._pools: Dict[str, ConnectionPool] = {}
        self._lock = threading.Lock()
        logger.info("ConnectionPoolManager initialized")
    
    def create_pool(
        self,
        name: str,
        create_connection: Callable,
        close_connection: Callable,
        validate_connection: Optional[Callable] = None,
        **kwargs
    ) -> ConnectionPool:
        """Create and register a new connection pool."""
        with self._lock:
            if name in self._pools:
                logger.warning(f"Pool '{name}' already exists")
                return self._pools[name]
            
            pool = ConnectionPool(
                name=name,
                create_connection=create_connection,
                close_connection=close_connection,
                validate_connection=validate_connection,
                **kwargs
            )
            self._pools[name] = pool
            return pool
    
    def get_pool(self, name: str) -> Optional[ConnectionPool]:
        """Get a pool by name."""
        with self._lock:
            return self._pools.get(name)
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Get statistics for all pools."""
        with self._lock:
            return {
                name: pool.get_stats()
                for name, pool in self._pools.items()
            }
    
    def cleanup_all_idle(self) -> int:
        """Cleanup idle connections in all pools."""
        total_closed = 0
        with self._lock:
            for pool in self._pools.values():
                total_closed += pool.cleanup_idle_connections()
        return total_closed
    
    def shutdown_all(self, wait: bool = True) -> None:
        """Shutdown all pools."""
        logger.info("Shutting down all connection pools...")
        with self._lock:
            for pool in self._pools.values():
                pool.shutdown(wait=wait)
            self._pools.clear()
        logger.info("All connection pools shutdown complete")


# Global singleton
_pool_manager: Optional[ConnectionPoolManager] = None


def get_pool_manager() -> ConnectionPoolManager:
    """Get the global connection pool manager."""
    global _pool_manager
    if _pool_manager is None:
        _pool_manager = ConnectionPoolManager()
    return _pool_manager
