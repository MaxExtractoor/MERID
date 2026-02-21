"""Operation result type for explicit success/failure handling.

Replaces silent None/[] returns with explicit result containers.

Usage:
    result = await fetch_with_result(market_id)
    if result.success:
        process(result.data)
    else:
        handle_error(result.error)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Optional, TypeVar

import logging
logger = logging.getLogger("result")

T = TypeVar("T")


@dataclass
class OperationResult(Generic[T]):
    """
    Container for operation results with explicit success/failure.
    
    Replaces patterns like:
        try:
            data = await fetch()
            return data
        except Exception:
            return None  # Caller can't tell if None is valid or error
    
    With:
        try:
            data = await fetch()
            return OperationResult.ok(data)
        except Exception as e:
            return OperationResult.fail(e)
    
    Attributes:
        success: Whether operation succeeded
        data: Result data (if success)
        error: Error details (if failure)
        retries: Number of retries attempted
        latency_ms: Operation latency in milliseconds
        metadata: Additional context
    """
    
    success: bool
    data: Optional[T] = None
    error: Optional[Exception] = None
    error_message: Optional[str] = None
    retries: int = 0
    latency_ms: float = 0.0
    metadata: dict = field(default_factory=dict)
    
    @classmethod
    def ok(
        cls,
        data: T,
        latency_ms: float = 0.0,
        retries: int = 0,
        **metadata,
    ) -> "OperationResult[T]":
        """Create a successful result."""
        return cls(
            success=True,
            data=data,
            latency_ms=latency_ms,
            retries=retries,
            metadata=metadata,
        )
    
    @classmethod
    def fail(
        cls,
        error: Exception,
        latency_ms: float = 0.0,
        retries: int = 0,
        **metadata,
    ) -> "OperationResult[T]":
        """Create a failed result."""
        return cls(
            success=False,
            error=error,
            error_message=str(error),
            latency_ms=latency_ms,
            retries=retries,
            metadata=metadata,
        )
    
    @classmethod
    def empty(cls, reason: str = "No data") -> "OperationResult[T]":
        """Create an empty but successful result (e.g., no positions found)."""
        return cls(
            success=True,
            data=None,
            metadata={"reason": reason},
        )
    
    def map(self, func: Callable[[T], Any]) -> "OperationResult":
        """Transform successful data, pass through failures."""
        if self.success and self.data is not None:
            try:
                return OperationResult.ok(
                    func(self.data),
                    latency_ms=self.latency_ms,
                    retries=self.retries,
                )
            except Exception as e:
                return OperationResult.fail(e)
        return self
    
    def unwrap(self) -> T:
        """Get data or raise error."""
        if self.success:
            return self.data
        if self.error:
            raise self.error
        raise ValueError(self.error_message or "Operation failed")
    
    def unwrap_or(self, default: T) -> T:
        """Get data or return default on failure."""
        if self.success and self.data is not None:
            return self.data
        return default
    
    def unwrap_or_else(self, func: Callable[[], T]) -> T:
        """Get data or call function on failure."""
        if self.success and self.data is not None:
            return self.data
        return func()
    
    def __bool__(self) -> bool:
        """Allow `if result:` pattern."""
        return self.success


def timed_result(func: Callable[..., T]) -> Callable[..., "OperationResult[T]"]:
    """
    Decorator to wrap function result in OperationResult with timing.
    
    Usage:
        @timed_result
        async def fetch_market(market_id: str) -> Market:
            return await client.get_market(market_id)
        
        result = await fetch_market("BTC-YES")
        logger.info(f"Took {result.latency_ms}ms, success={result.success}")
    """
    import functools
    import asyncio
    
    @functools.wraps(func)
    async def wrapper(*args, **kwargs) -> OperationResult[T]:
        start = time.perf_counter()
        try:
            if asyncio.iscoroutinefunction(func):
                data = await func(*args, **kwargs)
            else:
                data = func(*args, **kwargs)
            latency_ms = (time.perf_counter() - start) * 1000
            return OperationResult.ok(data, latency_ms=latency_ms)
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            return OperationResult.fail(e, latency_ms=latency_ms)
    
    return wrapper
