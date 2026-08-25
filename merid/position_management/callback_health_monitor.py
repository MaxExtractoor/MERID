"""
Callback Health Monitor

Monitors exit intent callback health with circuit breaker functionality.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Dict, Any

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CallbackFailure:
    """Record of a callback failure."""
    timestamp: float
    error: str
    error_type: str


class CallbackHealthMonitor:
    """Monitors exit intent callback health."""
    
    def __init__(self, failure_threshold: int = 5, window_seconds: int = 300):
        """
        Initialize callback health monitor.
        
        Args:
            failure_threshold: Number of failures to trigger unhealthy state
            window_seconds: Time window for failure counting (default 5 minutes)
        """
        self._failure_threshold = failure_threshold
        self._window_seconds = window_seconds
        self._failures: List[CallbackFailure] = []
        self._success_count = 0
        self._total_count = 0
        logger.info(
            "[CALLBACK-HEALTH-MONITOR] Initialized with failure_threshold=%d window_seconds=%d",
            failure_threshold,
            window_seconds
        )
    
    def record_success(self) -> None:
        """Record successful callback execution."""
        self._success_count += 1
        self._total_count += 1
        self._clean_old_failures()
        logger.debug("[CALLBACK-HEALTH-MONITOR] Recorded success (total=%d)", self._total_count)
    
    def record_failure(self, error: Exception) -> None:
        """Record callback failure."""
        self._total_count += 1
        self._failures.append(CallbackFailure(
            timestamp=time.time(),
            error=str(error),
            error_type=type(error).__name__
        ))
        self._clean_old_failures()
        
        logger.warning(
            "[CALLBACK-HEALTH-MONITOR] Recorded failure: %s (total=%d failures=%d)",
            type(error).__name__,
            self._total_count,
            len(self._failures)
        )
    
    def is_healthy(self) -> bool:
        """Check if callback is healthy (failure rate below threshold)."""
        self._clean_old_failures()
        return len(self._failures) < self._failure_threshold
    
    def get_failure_count(self) -> int:
        """Get current failure count within window."""
        self._clean_old_failures()
        return len(self._failures)
    
    def get_success_rate(self) -> float:
        """Get success rate (0.0-1.0)."""
        if self._total_count == 0:
            return 1.0
        return self._success_count / self._total_count
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current health metrics."""
        self._clean_old_failures()
        return {
            "total_count": self._total_count,
            "success_count": self._success_count,
            "failure_count": len(self._failures),
            "success_rate": self.get_success_rate(),
            "is_healthy": self.is_healthy(),
            "failure_threshold": self._failure_threshold,
            "window_seconds": self._window_seconds,
        }
    
    def _clean_old_failures(self) -> None:
        """Remove failures outside the time window."""
        cutoff = time.time() - self._window_seconds
        self._failures = [f for f in self._failures if f.timestamp > cutoff]
    
    def reset(self) -> None:
        """Reset monitor state."""
        self._failures = []
        self._success_count = 0
        self._total_count = 0
        logger.info("[CALLBACK-HEALTH-MONITOR] Reset monitor state")
