"""Bulkhead pattern implementation for MERID.

The bulkhead pattern isolates different operations into separate pools,
preventing failures in one area from exhausting resources for others.

Example:
    # Create bulkheads for different venues
    kalshi_bulkhead = Bulkhead("kalshi", max_concurrent=10, max_queued=50)
    polymarket_bulkhead = Bulkhead("polymarket", max_concurrent=10, max_queued=50)
    
    # Use bulkhead to limit concurrent operations
    async with kalshi_bulkhead:
        result = await kalshi_client.get_market(market_id)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

from utils.logger import get_logger

logger = get_logger("merid.resilience.bulkhead")


class BulkheadFullError(Exception):
    """Raised when bulkhead is at capacity and cannot accept more work."""
    
    def __init__(self, name: str, queued: int, max_queued: int):
        self.name = name
        self.queued = queued
        self.max_queued = max_queued
        super().__init__(
            f"Bulkhead '{name}' is full: {queued}/{max_queued} queued"
        )


@dataclass
class BulkheadStats:
    """Statistics for a bulkhead."""
    name: str
    max_concurrent: int
    max_queued: int
    active_count: int
    queued_count: int
    total_accepted: int
    total_rejected: int
    total_completed: int
    total_failed: int
    avg_wait_ms: float
    avg_execution_ms: float


@dataclass
class Bulkhead:
    """
    Bulkhead for isolating concurrent operations.
    
    Limits the number of concurrent operations and queued requests
    to prevent resource exhaustion.
    
    Attributes:
        name: Identifier for this bulkhead (e.g., venue name)
        max_concurrent: Maximum concurrent operations allowed
        max_queued: Maximum requests that can wait in queue
        timeout: Maximum time to wait in queue (seconds)
    """
    
    name: str
    max_concurrent: int = 10
    max_queued: int = 50
    timeout: float = 30.0
    
    # Internal state
    _semaphore: asyncio.Semaphore = field(init=False)
    _active_count: int = field(default=0, init=False)
    _queued_count: int = field(default=0, init=False)
    _total_accepted: int = field(default=0, init=False)
    _total_rejected: int = field(default=0, init=False)
    _total_completed: int = field(default=0, init=False)
    _total_failed: int = field(default=0, init=False)
    _total_wait_ms: float = field(default=0.0, init=False)
    _total_exec_ms: float = field(default=0.0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    
    def __post_init__(self):
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
    
    @property
    def active_count(self) -> int:
        """Number of currently active operations."""
        return self._active_count
    
    @property
    def queued_count(self) -> int:
        """Number of operations waiting in queue."""
        return self._queued_count
    
    @property
    def available_slots(self) -> int:
        """Number of available concurrent slots."""
        return max(0, self.max_concurrent - self._active_count)
    
    @property
    def available_queue(self) -> int:
        """Number of available queue slots."""
        return max(0, self.max_queued - self._queued_count)
    
    def is_full(self) -> bool:
        """Check if bulkhead is at capacity."""
        return self._queued_count >= self.max_queued
    
    async def acquire(self) -> float:
        """
        Acquire a slot in the bulkhead.
        
        Returns:
            Wait time in milliseconds
            
        Raises:
            BulkheadFullError: If queue is full
            asyncio.TimeoutError: If timeout waiting for slot
        """
        async with self._lock:
            if self._queued_count >= self.max_queued:
                self._total_rejected += 1
                raise BulkheadFullError(
                    self.name, self._queued_count, self.max_queued
                )
            self._queued_count += 1
            self._total_accepted += 1
        
        start_wait = time.time()
        
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self.timeout
            )
        except asyncio.TimeoutError:
            async with self._lock:
                self._queued_count -= 1
                self._total_rejected += 1
            raise
        
        wait_ms = (time.time() - start_wait) * 1000
        
        async with self._lock:
            self._queued_count -= 1
            self._active_count += 1
            self._total_wait_ms += wait_ms
        
        return wait_ms
    
    async def release(self, success: bool = True, exec_ms: float = 0.0) -> None:
        """
        Release a slot back to the bulkhead.
        
        Args:
            success: Whether the operation succeeded
            exec_ms: Execution time in milliseconds
        """
        self._semaphore.release()
        
        async with self._lock:
            self._active_count -= 1
            self._total_exec_ms += exec_ms
            if success:
                self._total_completed += 1
            else:
                self._total_failed += 1
    
    async def __aenter__(self) -> "Bulkhead":
        """Async context manager entry."""
        self._entry_time = time.time()
        await self.acquire()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Async context manager exit."""
        exec_ms = (time.time() - self._entry_time) * 1000
        success = exc_type is None
        await self.release(success=success, exec_ms=exec_ms)
        return False  # Don't suppress exceptions
    
    def get_stats(self) -> BulkheadStats:
        """Get bulkhead statistics."""
        total_ops = self._total_completed + self._total_failed
        avg_wait = self._total_wait_ms / max(1, self._total_accepted)
        avg_exec = self._total_exec_ms / max(1, total_ops)
        
        return BulkheadStats(
            name=self.name,
            max_concurrent=self.max_concurrent,
            max_queued=self.max_queued,
            active_count=self._active_count,
            queued_count=self._queued_count,
            total_accepted=self._total_accepted,
            total_rejected=self._total_rejected,
            total_completed=self._total_completed,
            total_failed=self._total_failed,
            avg_wait_ms=avg_wait,
            avg_execution_ms=avg_exec,
        )
    
    def reset_stats(self) -> None:
        """Reset statistics (for testing)."""
        self._total_accepted = 0
        self._total_rejected = 0
        self._total_completed = 0
        self._total_failed = 0
        self._total_wait_ms = 0.0
        self._total_exec_ms = 0.0


# Global registry of bulkheads
_bulkheads: dict[str, Bulkhead] = {}


def get_bulkhead(
    name: str,
    max_concurrent: int = 10,
    max_queued: int = 50,
    timeout: float = 30.0,
) -> Bulkhead:
    """
    Get or create a bulkhead by name.
    
    Args:
        name: Unique identifier (e.g., "kalshi", "polymarket")
        max_concurrent: Maximum concurrent operations
        max_queued: Maximum queued requests
        timeout: Queue timeout in seconds
        
    Returns:
        Bulkhead instance (cached by name)
    """
    if name not in _bulkheads:
        _bulkheads[name] = Bulkhead(
            name=name,
            max_concurrent=max_concurrent,
            max_queued=max_queued,
            timeout=timeout,
        )
        logger.info(
            f"Created bulkhead '{name}': "
            f"max_concurrent={max_concurrent}, max_queued={max_queued}"
        )
    return _bulkheads[name]


def get_all_bulkheads() -> dict[str, Bulkhead]:
    """Get all registered bulkheads."""
    return _bulkheads.copy()


def reset_all_bulkheads() -> None:
    """Reset all bulkhead statistics (for testing)."""
    for bulkhead in _bulkheads.values():
        bulkhead.reset_stats()
