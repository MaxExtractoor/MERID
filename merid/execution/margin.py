"""Margin calculation utilities - stub module to prevent import errors.

This module was previously deleted but restored as a stub to prevent
errors from stale running processes. The actual functionality has been
moved elsewhere.
"""

from functools import lru_cache
from typing import Callable, Any
from utils.logger import get_logger

logger = get_logger("merid.execution.margin")


def margin_cache(size: int = 50):
    """Decorator that provides LRU caching for margin calculations."""
    def decorator(fn: Callable) -> Callable:
        return lru_cache(maxsize=size)(fn)
    return decorator


def get_available_margin(*args, **kwargs) -> float:
    """Get available margin - stub implementation returns 0.0."""
    logger.debug("margin.get_available_margin called (stub implementation)")
    return 0.0


def sweep_to(*args, **kwargs) -> bool:
    """Sweep funds to margin account - stub implementation returns False."""
    logger.debug("margin.sweep_to called (stub implementation)")
    return False
