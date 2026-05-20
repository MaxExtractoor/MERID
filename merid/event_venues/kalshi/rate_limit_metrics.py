"""Rate-limit and backoff metrics for Kalshi API.

Emits metrics for rate limit utilization and backoff events (429 errors, retry delays).
Integrates with rate_limit_coordinator and api_metrics for comprehensive monitoring.
"""

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.rate_limit_metrics")


@dataclass
class BackoffEvent:
    """Record of a backoff event (rate limit hit)."""
    timestamp: float
    endpoint: str
    status_code: int
    retry_delay_seconds: float
    reason: str


class RateLimitMetrics:
    """Collects and emits rate-limit and backoff metrics.

    Features:
    - Tracks rate limit utilization from coordinator
    - Records backoff events (429 errors, retry delays)
    - Emits alerts for high rate limit usage
    - Provides metrics summary for monitoring
    """

    def __init__(self, window_seconds: float = 300.0, max_history: int = 1000):
        self._window_seconds = window_seconds
        self._max_history = max_history
        self._backoff_history: deque = deque(maxlen=max_history)
        self._backoff_counts: Dict[int, int] = defaultdict(int)  # status_code -> count
        self._start_time = time.monotonic()

    def record_backoff(
        self,
        endpoint: str,
        status_code: int,
        retry_delay_seconds: float,
        reason: str = "rate_limit",
    ) -> None:
        """Record a backoff event.

        Args:
            endpoint: API endpoint that triggered backoff
            status_code: HTTP status code (usually 429)
            retry_delay_seconds: Delay before retry
            reason: Reason for backoff (rate_limit, server_error, etc.)
        """
        event = BackoffEvent(
            timestamp=time.monotonic(),
            endpoint=endpoint,
            status_code=status_code,
            retry_delay_seconds=retry_delay_seconds,
            reason=reason,
        )
        self._backoff_history.append(event)
        self._backoff_counts[status_code] += 1

        logger.warning(
            f"[RATE-LIMIT] Backoff event: endpoint={endpoint}, status={status_code}, "
            f"delay={retry_delay_seconds:.2f}s, reason={reason}"
        )

        # Emit alert if high rate of backoffs
        self._check_backoff_alert()

    def get_metrics(self) -> Dict[str, Any]:
        """Get rate-limit and backoff metrics summary.

        Returns:
            Dict with rate limit metrics
        """
        # Get utilization from coordinator
        try:
            from merid.event_venues.kalshi.rate_limit_coordinator import (
                get_rate_limit_coordinator,
            )
            coordinator = get_rate_limit_coordinator()
            utilization = coordinator.get_utilization()
        except Exception as e:
            logger.debug(f"Failed to get rate limit coordinator: {e}")
            utilization = {}

        # Get backoff stats from window
        now = time.monotonic()
        window_start = now - self._window_seconds
        recent_backoffs = [
            b for b in self._backoff_history if b.timestamp >= window_start
        ]

        backoff_by_status = defaultdict(int)
        total_retry_delay = 0.0
        for b in recent_backoffs:
            backoff_by_status[b.status_code] += 1
            total_retry_delay += b.retry_delay_seconds

        return {
            "rate_limit_utilization": utilization,
            "backoff_events": {
                "total": len(recent_backoffs),
                "rate_per_minute": round(len(recent_backoffs) / (self._window_seconds / 60), 2),
                "by_status_code": dict(backoff_by_status),
                "total_retry_delay_seconds": round(total_retry_delay, 2),
                "avg_retry_delay_seconds": round(
                    total_retry_delay / len(recent_backoffs), 2
                ) if recent_backoffs else 0.0,
            },
            "uptime_seconds": round(now - self._start_time, 1),
            "window_seconds": self._window_seconds,
        }

    def _check_backoff_alert(self) -> None:
        """Check if backoff rate is high and emit alert.

        Alert threshold: >10 backoffs per minute
        """
        now = time.monotonic()
        window_start = now - 60.0  # 1 minute window
        recent_backoffs = [
            b for b in self._backoff_history if b.timestamp >= window_start
        ]

        if len(recent_backoffs) > 10:
            logger.error(
                f"[RATE-LIMIT ALERT] High backoff rate: {len(recent_backoffs)} backoffs in last minute. "
                f"This may indicate rate limit pressure or API issues."
            )

    def get_backoff_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent backoff events.

        Args:
            limit: Max number of events to return

        Returns:
            List of backoff event dicts
        """
        recent = list(self._backoff_history)[-limit:]
        return [
            {
                "timestamp": b.timestamp,
                "endpoint": b.endpoint,
                "status_code": b.status_code,
                "retry_delay_seconds": b.retry_delay_seconds,
                "reason": b.reason,
            }
            for b in recent
        ]


# ── Singleton ───────────────────────────────────────────────────────────────

_metrics: Optional[RateLimitMetrics] = None


def get_rate_limit_metrics(
    window_seconds: float = 300.0,
    max_history: int = 1000,
) -> RateLimitMetrics:
    """Get or create the singleton rate limit metrics instance.

    Args:
        window_seconds: Sliding window for metrics aggregation
        max_history: Max number of backoff events to keep

    Returns:
        RateLimitMetrics singleton instance
    """
    global _metrics
    if _metrics is None:
        _metrics = RateLimitMetrics(
            window_seconds=window_seconds,
            max_history=max_history,
        )
    return _metrics


# ── Helper functions for easy metric emission ─────────────────────────────────

def emit_backoff_event(
    endpoint: str,
    status_code: int,
    retry_delay_seconds: float,
    reason: str = "rate_limit",
) -> None:
    """Emit a backoff event metric.

    Args:
        endpoint: API endpoint that triggered backoff
        status_code: HTTP status code (usually 429)
        retry_delay_seconds: Delay before retry
        reason: Reason for backoff
    """
    metrics = get_rate_limit_metrics()
    metrics.record_backoff(
        endpoint=endpoint,
        status_code=status_code,
        retry_delay_seconds=retry_delay_seconds,
        reason=reason,
    )


def emit_rate_limit_summary() -> Dict[str, Any]:
    """Emit current rate limit metrics summary.

    Returns:
        Dict with rate limit metrics
    """
    metrics = get_rate_limit_metrics()
    return metrics.get_metrics()
