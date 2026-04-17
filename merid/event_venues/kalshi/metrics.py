"""Metrics collector for Kalshi API operations.

Tracks QPS, latency percentiles, error rates, and request counts per endpoint.
Designed for production monitoring and alerting.
"""

from __future__ import annotations

import threading
import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.metrics")


@dataclass
class LatencyHistogram:
    """Latency histogram for detailed distribution tracking."""
    buckets: List[float] = field(default_factory=lambda: [10, 25, 50, 100, 250, 500, 1000, 2500, 5000])
    counts: List[int] = field(default_factory=list)
    total_count: int = 0
    sum_ms: float = 0.0
    min_ms: float = float('inf')
    max_ms: float = 0.0
    
    def __post_init__(self):
        if not self.counts:
            self.counts = [0] * (len(self.buckets) + 1)  # +1 for overflow bucket
    
    def record(self, latency_ms: float) -> None:
        """Record a latency sample."""
        self.total_count += 1
        self.sum_ms += latency_ms
        self.min_ms = min(self.min_ms, latency_ms)
        self.max_ms = max(self.max_ms, latency_ms)
        
        # Find bucket
        for i, bucket in enumerate(self.buckets):
            if latency_ms <= bucket:
                self.counts[i] += 1
                return
        self.counts[-1] += 1  # Overflow bucket
    
    def get_percentile(self, p: float) -> float:
        """Get latency at given percentile."""
        if self.total_count == 0:
            return 0.0
        
        target = int(self.total_count * p / 100)
        cumulative = 0
        
        for i, count in enumerate(self.counts):
            cumulative += count
            if cumulative >= target:
                if i < len(self.buckets):
                    return float(self.buckets[i])
                return float(self.buckets[-1] * 2)  # Estimate overflow
        
        return self.max_ms
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize histogram to dict."""
        return {
            "buckets": self.buckets + [">max"],
            "counts": self.counts,
            "total": self.total_count,
            "avg_ms": round(self.sum_ms / self.total_count, 2) if self.total_count > 0 else 0.0,
            "min_ms": round(self.min_ms, 2) if self.min_ms != float('inf') else 0.0,
            "max_ms": round(self.max_ms, 2),
            "p50_ms": round(self.get_percentile(50), 2),
            "p95_ms": round(self.get_percentile(95), 2),
            "p99_ms": round(self.get_percentile(99), 2),
        }
@dataclass
class RequestMetrics:
    """Metrics for a single request."""
    timestamp: float
    latency_ms: float
    success: bool
    status_code: Optional[int] = None
    error_type: Optional[str] = None


class KalshiMetricsCollector:
    """Collects and aggregates metrics for Kalshi API operations.

    Features:
    - Per-endpoint request counts and latency percentiles
    - Error rate tracking by type
    - QPS calculation over configurable windows
    - Automatic metric expiration (sliding window)
    - Thread-safe async operations
    """

    def __init__(
        self,
        window_seconds: float = 300.0,  # 5 minute default window
        max_history: int = 10000,
    ):
        self._window_seconds = window_seconds
        self._max_history = max_history
        # Lazy-init lock to avoid event loop binding issues
        self._lock: Optional[asyncio.Lock] = None
        self._lock_init_lock = threading.Lock()

        # Per-endpoint metrics history
        self._requests: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_history))

        # Aggregated counters (since start)
        self._total_requests: Dict[str, int] = defaultdict(int)
        self._total_errors: Dict[str, int] = defaultdict(int)
        self._total_latency: Dict[str, float] = defaultdict(float)

        # Error type breakdown
        self._error_types: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

        # Start time for uptime calculation
        self._start_time = time.monotonic()

    def _ensure_lock(self) -> asyncio.Lock:
        """Lazy-initialize the asyncio.Lock in the current event loop."""
        if self._lock is None:
            with self._lock_init_lock:
                if self._lock is None:
                    self._lock = asyncio.Lock()
        return self._lock

    def record_request(
        self,
        endpoint: str,
        latency_ms: float,
        success: bool,
        status_code: Optional[int] = None,
        error_type: Optional[str] = None,
    ) -> None:
        """Record a single request metric.

        Args:
            endpoint: API endpoint name (e.g., "get_market", "place_order")
            latency_ms: Request latency in milliseconds
            success: Whether the request succeeded
            status_code: HTTP status code (if applicable)
            error_type: Type of error (if failed)
        """
        now = time.monotonic()
        metric = RequestMetrics(
            timestamp=now,
            latency_ms=latency_ms,
            success=success,
            status_code=status_code,
            error_type=error_type,
        )

        # Update in-memory structures (not async - assumed called from async context)
        self._requests[endpoint].append(metric)
        self._total_requests[endpoint] += 1
        self._total_latency[endpoint] += latency_ms

        if not success:
            self._total_errors[endpoint] += 1
            if error_type:
                self._error_types[endpoint][error_type] += 1

    async def get_summary(self) -> Dict[str, Any]:
        """Get metrics summary for all endpoints.

        Returns:
            Dict with per-endpoint and aggregate metrics
        """
        lock = self._ensure_lock()
        async with lock:
            now = time.monotonic()
            window_start = now - self._window_seconds

            endpoint_stats = {}
            for endpoint, history in self._requests.items():
                # Filter to window
                recent = [m for m in history if m.timestamp >= window_start]

                if not recent:
                    continue

                latencies = [m.latency_ms for m in recent]
                successes = sum(1 for m in recent if m.success)
                errors = len(recent) - successes

                endpoint_stats[endpoint] = {
                    "requests": len(recent),
                    "successes": successes,
                    "errors": errors,
                    "error_rate": round(errors / len(recent), 4) if recent else 0.0,
                    "qps": round(len(recent) / self._window_seconds, 2),
                    "latency_ms": {
                        "avg": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
                        "p50": round(self._percentile(latencies, 50), 2) if latencies else 0.0,
                        "p95": round(self._percentile(latencies, 95), 2) if latencies else 0.0,
                        "p99": round(self._percentile(latencies, 99), 2) if latencies else 0.0,
                        "max": round(max(latencies), 2) if latencies else 0.0,
                    },
                    "error_breakdown": dict(self._error_types[endpoint]),
                }

            # Aggregate across all endpoints
            all_recent = [
                m for history in self._requests.values()
                for m in history if m.timestamp >= window_start
            ]

            total_requests = sum(self._total_requests.values())
            total_errors = sum(self._total_errors.values())

            return {
                "uptime_seconds": round(now - self._start_time, 1),
                "window_seconds": self._window_seconds,
                "endpoints": endpoint_stats,
                "aggregate": {
                    "total_requests": len(all_recent),
                    "qps": round(len(all_recent) / self._window_seconds, 2),
                    "error_rate": round(
                        (len(all_recent) - sum(1 for m in all_recent if m.success)) / len(all_recent), 4
                    ) if all_recent else 0.0,
                    "latency_ms": {
                        "avg": round(
                            sum(m.latency_ms for m in all_recent) / len(all_recent), 2
                        ) if all_recent else 0.0,
                        "p95": round(
                            self._percentile([m.latency_ms for m in all_recent], 95), 2
                        ) if all_recent else 0.0,
                    },
                },
                "totals": {
                    "requests": total_requests,
                    "errors": total_errors,
                    "error_rate": round(total_errors / total_requests, 4) if total_requests else 0.0,
                },
            }

    async def get_endpoint_metrics(self, endpoint: str) -> Optional[Dict[str, Any]]:
        """Get metrics for a specific endpoint.

        Args:
            endpoint: Endpoint name

        Returns:
            Metrics dict or None if no data
        """
        lock = self._ensure_lock()
        async with lock:
            now = time.monotonic()
            window_start = now - self._window_seconds
            history = self._requests.get(endpoint, [])
            recent = [m for m in history if m.timestamp >= window_start]

            if not recent:
                return None

            latencies = [m.latency_ms for m in recent]
            successes = sum(1 for m in recent if m.success)
            errors = len(recent) - successes

            return {
                "endpoint": endpoint,
                "requests": len(recent),
                "successes": successes,
                "errors": errors,
                "error_rate": round(errors / len(recent), 4),
                "qps": round(len(recent) / self._window_seconds, 2),
                "latency_ms": {
                    "avg": round(sum(latencies) / len(latencies), 2),
                    "p50": round(self._percentile(latencies, 50), 2),
                    "p95": round(self._percentile(latencies, 95), 2),
                    "p99": round(self._percentile(latencies, 99), 2),
                    "max": round(max(latencies), 2),
                },
                "error_breakdown": dict(self._error_types[endpoint]),
            }

    async def reset(self) -> None:
        """Reset all metrics (use with caution)."""
        lock = self._ensure_lock()
        async with lock:
            self._requests.clear()
            self._total_requests.clear()
            self._total_errors.clear()
            self._error_types.clear()
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

_collector: Optional[KalshiMetricsCollector] = None
_collector_lock = threading.Lock()


def get_metrics_collector(
    window_seconds: float = 300.0,
    max_history: int = 10000,
) -> KalshiMetricsCollector:
    """Get or create the singleton metrics collector.

    Args:
        window_seconds: Sliding window for metrics aggregation
        max_history: Max number of requests to keep per endpoint

    Returns:
        KalshiMetricsCollector singleton instance
    """
    global _collector
    if _collector is None:
        with _collector_lock:
            if _collector is None:
                _collector = KalshiMetricsCollector(
                window_seconds=window_seconds,
                max_history=max_history,
            )
    return _collector


# ── Decorator for automatic metrics collection ───────────────────────────

def record_metrics(endpoint_name: str):
    """Decorator to automatically record metrics for a function.

    Usage:
        @record_metrics("get_market")
        async def get_market(self, ticker: str):
            ...
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            collector = get_metrics_collector()
            start = time.monotonic()
            error_type = None
            success = True
            status_code = None

            try:
                result = await func(*args, **kwargs)
                # Try to extract status from OperationResult
                if hasattr(result, "success"):
                    success = result.success
                if hasattr(result, "status_code"):
                    status_code = result.status_code
                return result
            except Exception as e:
                success = False
                error_type = type(e).__name__
                status_code = getattr(e, "status_code", None)
                raise
            finally:
                latency_ms = (time.monotonic() - start) * 1000
                collector.record_request(
                    endpoint=endpoint_name,
                    latency_ms=latency_ms,
                    success=success,
                    status_code=status_code,
                    error_type=error_type,
                )
        return wrapper
    return decorator
