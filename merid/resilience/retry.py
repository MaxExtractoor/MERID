"""Retry decorator with configurable backoff for MERID.

Provides a flexible retry mechanism for async operations.

Usage:
    @retry_with_backoff(max_retries=3, backoff_base=2.0)
    async def fetch_market(market_id: str):
        return await client.get(f"/markets/{market_id}")
"""

from __future__ import annotations

import asyncio
import functools
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Set, Tuple, Type, TypeVar, Union

from utils.logger import get_logger

logger = get_logger("merid.resilience.retry")

T = TypeVar("T")


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    
    max_retries: int = 3
    backoff_base: float = 2.0  # Exponential backoff base
    backoff_max: float = 60.0  # Max wait between retries
    backoff_jitter: float = 0.1  # Random jitter factor (0-1)
    
    # Exception types to retry on
    retry_on: Tuple[Type[Exception], ...] = (
        ConnectionError,
        TimeoutError,
        asyncio.TimeoutError,
    )
    
    # Exception types to never retry
    no_retry_on: Tuple[Type[Exception], ...] = ()
    
    # HTTP status codes to retry (if applicable)
    retry_statuses: Set[int] = None
    
    def __post_init__(self):
        if self.retry_statuses is None:
            self.retry_statuses = {429, 500, 502, 503, 504}


def _calculate_backoff(attempt: int, config: RetryConfig) -> float:
    """Calculate backoff time with jitter."""
    import random
    
    base_wait = config.backoff_base ** attempt
    jitter = base_wait * config.backoff_jitter * random.random()
    wait = min(base_wait + jitter, config.backoff_max)
    return wait


def retry_with_backoff(
    max_retries: int = 3,
    backoff_base: float = 2.0,
    backoff_max: float = 60.0,
    retry_on: Tuple[Type[Exception], ...] = (ConnectionError, TimeoutError),
    no_retry_on: Tuple[Type[Exception], ...] = (),
    on_retry: Optional[Callable[[int, Exception], None]] = None,
) -> Callable:
    """
    Decorator for retrying async functions with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        backoff_base: Base for exponential backoff (2.0 = 2, 4, 8, 16...)
        backoff_max: Maximum wait time between retries
        retry_on: Exception types to retry
        no_retry_on: Exception types to never retry
        on_retry: Optional callback(attempt, exception) on each retry
        
    Returns:
        Decorated function with retry behavior
        
    Example:
        @retry_with_backoff(max_retries=3, backoff_base=2.0)
        async def fetch_data():
            async with httpx.AsyncClient() as client:
                return await client.get(url)
    """
    config = RetryConfig(
        max_retries=max_retries,
        backoff_base=backoff_base,
        backoff_max=backoff_max,
        retry_on=retry_on,
        no_retry_on=no_retry_on,
    )
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception: Optional[Exception] = None
            
            for attempt in range(config.max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                    
                except config.no_retry_on as e:
                    # Never retry these
                    logger.debug(f"Non-retryable error in {func.__name__}: {e}")
                    raise
                    
                except config.retry_on as e:
                    last_exception = e
                    
                    if attempt >= config.max_retries:
                        logger.warning(
                            f"Max retries ({config.max_retries}) exceeded for "
                            f"{func.__name__}: {e}"
                        )
                        raise
                    
                    wait_time = _calculate_backoff(attempt, config)
                    logger.info(
                        f"Retry {attempt + 1}/{config.max_retries} for "
                        f"{func.__name__} after {wait_time:.1f}s: {e}"
                    )
                    
                    if on_retry:
                        try:
                            on_retry(attempt + 1, e)
                        except Exception:
                            pass  # Don't let callback errors break retry
                    
                    await asyncio.sleep(wait_time)
                    
                except Exception as e:
                    # Unexpected exception - don't retry
                    logger.error(f"Unexpected error in {func.__name__}: {e}")
                    raise
            
            # Should not reach here, but just in case
            if last_exception:
                raise last_exception
            raise RuntimeError(f"Retry loop exited unexpectedly for {func.__name__}")
        
        return wrapper
    return decorator


class RetryContext:
    """
    Context manager for retry logic (alternative to decorator).
    
    Usage:
        async with RetryContext(max_retries=3) as ctx:
            while ctx.should_retry():
                try:
                    result = await risky_operation()
                    ctx.success()
                    break
                except ConnectionError as e:
                    await ctx.handle_error(e)
    """
    
    def __init__(
        self,
        max_retries: int = 3,
        backoff_base: float = 2.0,
        backoff_max: float = 60.0,
        operation_name: str = "operation",
    ):
        self.config = RetryConfig(
            max_retries=max_retries,
            backoff_base=backoff_base,
            backoff_max=backoff_max,
        )
        self.operation_name = operation_name
        self._attempt = 0
        self._succeeded = False
        self._last_error: Optional[Exception] = None
    
    @property
    def attempt(self) -> int:
        """Current attempt number (0-indexed)."""
        return self._attempt
    
    @property
    def retries_remaining(self) -> int:
        """Number of retries remaining."""
        return max(0, self.config.max_retries - self._attempt)
    
    def should_retry(self) -> bool:
        """Check if another retry should be attempted."""
        return not self._succeeded and self._attempt <= self.config.max_retries
    
    def success(self) -> None:
        """Mark operation as successful."""
        self._succeeded = True
    
    async def handle_error(self, error: Exception) -> None:
        """Handle an error and wait before next retry."""
        self._last_error = error
        self._attempt += 1
        
        if self._attempt > self.config.max_retries:
            raise error
        
        wait_time = _calculate_backoff(self._attempt - 1, self.config)
        logger.info(
            f"Retry {self._attempt}/{self.config.max_retries} for "
            f"{self.operation_name} after {wait_time:.1f}s: {error}"
        )
        await asyncio.sleep(wait_time)
    
    async def __aenter__(self) -> "RetryContext":
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        return False  # Don't suppress exceptions
