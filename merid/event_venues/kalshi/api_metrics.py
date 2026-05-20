"""
Kalshi API performance metrics for production monitoring.

Tracks per-endpoint request counts, error rates, and latency distributions
for monitoring API performance and rate limit pressure.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.api_metrics")


@dataclass
class APICallMetrics:
    """Metrics for a single API call."""
    timestamp: float
    endpoint: str
    method: str
    duration_seconds: float
    status_code: int
    success: bool


@dataclass
class EndpointSummary:
    """Summary metrics for an endpoint."""
    endpoint: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_duration_seconds: float = 0.0
    status_codes: Dict[int, int] = field(default_factory=dict)


class KalshiAPIMetricsCollector:
    """Collects Kalshi API performance metrics for monitoring.

    Features:
    - Per-endpoint request counting
    - Error rate tracking by status code
    - Latency distribution tracking
    - Thread-safe operations
    - Sliding window aggregation
    """

    def __init__(
        self,
        window_seconds: float = 300.0,  # 5 minute default window
        max_history: int = 10000,
    ):
        self._window_seconds = window_seconds
        self._max_history = max_history
        self._lock = threading.Lock()

        # Per-endpoint call history
        self._call_history: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=max_history)
        )

        # Endpoint summaries
        self._summaries: Dict[str, EndpointSummary] = {}

        # Start time
        self._start_time = time.monotonic()

    def record_api_call(
        self,
        endpoint: str,
        method: str,
        duration_seconds: float,
        status_code: int,
        success: bool,
    ) -> None:
        """Record an API call.

        Args:
            endpoint: API endpoint (e.g., "/markets", "/fills")
            method: HTTP method (GET, POST, etc.)
            duration_seconds: Request duration
            status_code: HTTP status code
            success: Whether the call succeeded
        """
        with self._lock:
            now = time.monotonic()
            metrics = APICallMetrics(
                timestamp=now,
                endpoint=endpoint,
                method=method,
                duration_seconds=duration_seconds,
                status_code=status_code,
                success=success,
            )
            self._call_history[endpoint].append(metrics)

            # Update summary
            if endpoint not in self._summaries:
                self._summaries[endpoint] = EndpointSummary(endpoint=endpoint)

            summary = self._summaries[endpoint]
            summary.total_requests += 1
            if success:
                summary.successful_requests += 1
            else:
                summary.failed_requests += 1
            summary.total_duration_seconds += duration_seconds
            summary.status_codes[status_code] = summary.status_codes.get(status_code, 0) + 1

    def get_summary(self) -> Dict[str, Any]:
        """Get metrics summary for all endpoints.

        Returns:
            Dict with API performance metrics
        """
        with self._lock:
            now = time.monotonic()
            window_start = now - self._window_seconds

            endpoint_stats = {}

            for endpoint, history in self._call_history.items():
                recent = [c for c in history if c.timestamp >= window_start]
                if not recent:
                    continue

                durations = [c.duration_seconds for c in recent]
                successful = [c for c in recent if c.success]
                failed = [c for c in recent if not c.success]

                # Count status codes
                status_counts = defaultdict(int)
                for c in recent:
                    status_counts[c.status_code] += 1

                endpoint_stats[endpoint] = {
                    "requests": {
                        "total": len(recent),
                        "successful": len(successful),
                        "failed": len(failed),
                        "rate_per_minute": round(len(recent) / (self._window_seconds / 60), 2),
                    },
                    "latency_seconds": {
                        "avg": round(sum(durations) / len(durations), 3) if durations else 0.0,
                        "p50": round(self._percentile(durations, 50), 3) if durations else 0.0,
                        "p95": round(self._percentile(durations, 95), 3) if durations else 0.0,
                        "p99": round(self._percentile(durations, 99), 3) if durations else 0.0,
                        "max": round(max(durations), 3) if durations else 0.0,
                    },
                    "errors": {
                        "total": len(failed),
                        "rate": round(len(failed) / len(recent), 4) if recent else 0.0,
                        "by_status_code": dict(status_counts),
                    },
                }

            return {
                "uptime_seconds": round(now - self._start_time, 1),
                "window_seconds": self._window_seconds,
                "endpoints": endpoint_stats,
            }

    def get_endpoint_metrics(self, endpoint: str) -> Optional[Dict[str, Any]]:
        """Get metrics for a specific endpoint.

        Args:
            endpoint: API endpoint

        Returns:
            Metrics dict or None if no data
        """
        with self._lock:
            now = time.monotonic()
            window_start = now - self._window_seconds

            history = self._call_history.get(endpoint, [])
            recent = [c for c in history if c.timestamp >= window_start]

            if not recent:
                return None

            durations = [c.duration_seconds for c in recent]
            successful = [c for c in recent if c.success]
            failed = [c for c in recent if not c.success]

            status_counts = defaultdict(int)
            for c in recent:
                status_counts[c.status_code] += 1

            return {
                "endpoint": endpoint,
                "requests": {
                    "total": len(recent),
                    "successful": len(successful),
                    "failed": len(failed),
                    "rate_per_minute": round(len(recent) / (self._window_seconds / 60), 2),
                },
                "latency_seconds": {
                    "avg": round(sum(durations) / len(durations), 3) if durations else 0.0,
                    "p50": round(self._percentile(durations, 50), 3) if durations else 0.0,
                    "p95": round(self._percentile(durations, 95), 3) if durations else 0.0,
                    "p99": round(self._percentile(durations, 99), 3) if durations else 0.0,
                    "max": round(max(durations), 3) if durations else 0.0,
                },
                "errors": {
                    "total": len(failed),
                    "rate": round(len(failed) / len(recent), 4) if recent else 0.0,
                    "by_status_code": dict(status_counts),
                },
            }

    async def reset(self) -> None:
        """Reset all metrics (use with caution)."""
        with self._lock:
            self._call_history.clear()
            self._summaries.clear()
            self._start_time = time.monotonic()

    @staticmethod
    def _percentile(data: List[float], percentile: float) -> float:
        """Calculate percentile from sorted data."""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        k = (len(sorted_data) - 1) * (percentile / 100.0)
        f = int(k)
        c = f + 1 if f + 1 < len(sorted_data) else f
        return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


# ── Singleton ────────────────────────────────────────────────────────────

_collector: Optional[KalshiAPIMetricsCollector] = None
_collector_lock = threading.Lock()


def get_api_metrics_collector(
    window_seconds: float = 300.0,
    max_history: int = 10000,
) -> KalshiAPIMetricsCollector:
    """Get or create the singleton API metrics collector.

    Args:
        window_seconds: Sliding window for metrics aggregation
        max_history: Max number of records to keep

    Returns:
        KalshiAPIMetricsCollector singleton instance
    """
    global _collector
    if _collector is None:
        with _collector_lock:
            if _collector is None:
                _collector = KalshiAPIMetricsCollector(
                    window_seconds=window_seconds,
                    max_history=max_history,
                )
    return _collector


# ── Helper functions for easy metric emission ─────────────────────────────

def emit_api_metrics(
    endpoint: str,
    method: str,
    duration_seconds: float,
    status_code: int,
    success: bool,
) -> None:
    """Emit API metrics from a completed call.

    Args:
        endpoint: API endpoint (e.g., "/markets", "/fills")
        method: HTTP method (GET, POST, etc.)
        duration_seconds: Request duration
        status_code: HTTP status code
        success: Whether the call succeeded
    """
    collector = get_api_metrics_collector()
    collector.record_api_call(
        endpoint=endpoint,
        method=method,
        duration_seconds=duration_seconds,
        status_code=status_code,
        success=success,
    )
