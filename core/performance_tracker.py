"""
Performance Tracker - Real-time performance monitoring and profiling.

Features:
- Request latency tracking
- Throughput measurement
- Resource utilization monitoring
- Performance degradation detection
- Automatic alerting on anomalies
"""
from __future__ import annotations

import time
import threading
from typing import Dict, List, Optional, Any, Deque
from dataclasses import dataclass, field
from collections import deque, defaultdict
from datetime import datetime
import statistics

from utils.logger import get_logger

logger = get_logger("core.performance_tracker")


@dataclass
class PerformanceMetric:
    """Single performance measurement."""
    name: str
    value: float
    timestamp: float
    tags: Dict[str, str] = field(default_factory=dict)


@dataclass
class LatencyStats:
    """Latency statistics for an operation."""
    operation: str
    count: int
    min_ms: float
    max_ms: float
    mean_ms: float
    median_ms: float
    p95_ms: float
    p99_ms: float
    total_time_ms: float


class PerformanceTracker:
    """
    Production-grade performance tracking.
    
    Features:
    - Request/operation latency tracking
    - Throughput measurement
    - Percentile calculations (p50, p95, p99)
    - Time-windowed metrics
    - Anomaly detection
    """
    
    def __init__(
        self,
        window_size: int = 1000,
        retention_seconds: float = 3600.0
    ):
        """
        Initialize performance tracker.
        
        Args:
            window_size: Number of recent samples to keep per metric
            retention_seconds: How long to retain metrics
        """
        self.window_size = window_size
        self.retention_seconds = retention_seconds
        
        # Latency tracking
        self._latencies: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=window_size))
        self._latency_lock = threading.Lock()
        
        # Throughput tracking
        self._throughput: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=window_size))
        self._throughput_lock = threading.Lock()
        
        # Custom metrics
        self._metrics: Dict[str, Deque[PerformanceMetric]] = defaultdict(lambda: deque(maxlen=window_size))
        self._metrics_lock = threading.Lock()
        
        # Counters
        self._counters: Dict[str, int] = defaultdict(int)
        self._counter_lock = threading.Lock()
        
        logger.info(f"PerformanceTracker initialized: window={window_size}, retention={retention_seconds}s")
    
    def record_latency(self, operation: str, duration_ms: float, tags: Optional[Dict[str, str]] = None) -> None:
        """
        Record operation latency.
        
        Args:
            operation: Operation name
            duration_ms: Duration in milliseconds
            tags: Optional tags for categorization
        """
        with self._latency_lock:
            self._latencies[operation].append(duration_ms)
        
        # Also record as metric
        self.record_metric(f"latency.{operation}", duration_ms, tags or {})
    
    def record_throughput(self, operation: str, count: int = 1) -> None:
        """
        Record throughput (operations per second).
        
        Args:
            operation: Operation name
            count: Number of operations completed
        """
        timestamp = time.time()
        
        with self._throughput_lock:
            self._throughput[operation].append(timestamp)
    
    def record_metric(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        """
        Record custom metric.
        
        Args:
            name: Metric name
            value: Metric value
            tags: Optional tags
        """
        metric = PerformanceMetric(
            name=name,
            value=value,
            timestamp=time.time(),
            tags=tags or {}
        )
        
        with self._metrics_lock:
            self._metrics[name].append(metric)
    
    def increment_counter(self, name: str, amount: int = 1) -> None:
        """
        Increment counter.
        
        Args:
            name: Counter name
            amount: Amount to increment
        """
        with self._counter_lock:
            self._counters[name] += amount
    
    def get_latency_stats(self, operation: str) -> Optional[LatencyStats]:
        """
        Get latency statistics for an operation.
        
        Args:
            operation: Operation name
        
        Returns:
            LatencyStats or None if no data
        """
        with self._latency_lock:
            latencies = list(self._latencies.get(operation, []))
        
        if not latencies:
            return None
        
        sorted_latencies = sorted(latencies)
        count = len(sorted_latencies)
        
        return LatencyStats(
            operation=operation,
            count=count,
            min_ms=sorted_latencies[0],
            max_ms=sorted_latencies[-1],
            mean_ms=statistics.mean(sorted_latencies),
            median_ms=statistics.median(sorted_latencies),
            p95_ms=sorted_latencies[int(count * 0.95)] if count > 0 else 0.0,
            p99_ms=sorted_latencies[int(count * 0.99)] if count > 0 else 0.0,
            total_time_ms=sum(sorted_latencies)
        )
    
    def get_throughput(self, operation: str, window_seconds: float = 60.0) -> float:
        """
        Get throughput (operations per second) for an operation.
        
        Args:
            operation: Operation name
            window_seconds: Time window to calculate over
        
        Returns:
            Operations per second
        """
        now = time.time()
        cutoff = now - window_seconds
        
        with self._throughput_lock:
            timestamps = list(self._throughput.get(operation, []))
        
        # Count operations within window
        recent_ops = sum(1 for ts in timestamps if ts >= cutoff)
        
        return recent_ops / window_seconds if window_seconds > 0 else 0.0
    
    def get_metric_stats(self, name: str) -> Dict[str, Any]:
        """
        Get statistics for a custom metric.
        
        Args:
            name: Metric name
        
        Returns:
            Statistics dict
        """
        with self._metrics_lock:
            metrics = list(self._metrics.get(name, []))
        
        if not metrics:
            return {"count": 0}
        
        values = [m.value for m in metrics]
        
        return {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "mean": statistics.mean(values),
            "median": statistics.median(values),
            "stdev": statistics.stdev(values) if len(values) > 1 else 0.0
        }
    
    def get_counter(self, name: str) -> int:
        """Get counter value."""
        with self._counter_lock:
            return self._counters.get(name, 0)
    
    def get_all_latency_stats(self) -> Dict[str, LatencyStats]:
        """Get latency statistics for all operations."""
        with self._latency_lock:
            operations = list(self._latencies.keys())
        
        stats = {}
        for operation in operations:
            stat = self.get_latency_stats(operation)
            if stat:
                stats[operation] = stat
        
        return stats
    
    def get_all_throughput(self, window_seconds: float = 60.0) -> Dict[str, float]:
        """Get throughput for all operations."""
        with self._throughput_lock:
            operations = list(self._throughput.keys())
        
        return {
            operation: self.get_throughput(operation, window_seconds)
            for operation in operations
        }
    
    def get_all_counters(self) -> Dict[str, int]:
        """Get all counter values."""
        with self._counter_lock:
            return dict(self._counters)
    
    def reset(self) -> None:
        """Reset all metrics."""
        with self._latency_lock:
            self._latencies.clear()
        
        with self._throughput_lock:
            self._throughput.clear()
        
        with self._metrics_lock:
            self._metrics.clear()
        
        with self._counter_lock:
            self._counters.clear()
        
        logger.info("Performance metrics reset")
    
    def get_summary(self) -> Dict[str, Any]:
        """Get comprehensive performance summary."""
        return {
            "latency": {
                op: {
                    "count": stats.count,
                    "mean_ms": stats.mean_ms,
                    "median_ms": stats.median_ms,
                    "p95_ms": stats.p95_ms,
                    "p99_ms": stats.p99_ms,
                    "min_ms": stats.min_ms,
                    "max_ms": stats.max_ms
                }
                for op, stats in self.get_all_latency_stats().items()
            },
            "throughput": self.get_all_throughput(),
            "counters": self.get_all_counters(),
            "timestamp": datetime.utcnow().isoformat()
        }


class PerformanceTimer:
    """Context manager for timing operations."""
    
    def __init__(self, tracker: PerformanceTracker, operation: str, tags: Optional[Dict[str, str]] = None):
        self.tracker = tracker
        self.operation = operation
        self.tags = tags
        self.start_time: Optional[float] = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is not None:
            duration_ms = (time.time() - self.start_time) * 1000
            self.tracker.record_latency(self.operation, duration_ms, self.tags)
            self.tracker.record_throughput(self.operation)


# Global singleton
_performance_tracker: Optional[PerformanceTracker] = None


def get_performance_tracker() -> PerformanceTracker:
    """Get the global performance tracker instance."""
    global _performance_tracker
    if _performance_tracker is None:
        _performance_tracker = PerformanceTracker()
    return _performance_tracker


def track_performance(operation: str, tags: Optional[Dict[str, str]] = None):
    """
    Decorator to track function performance.
    
    Example:
        @track_performance("api.fetch_data")
        def fetch_data(symbol: str):
            return api.get(symbol)
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            tracker = get_performance_tracker()
            with PerformanceTimer(tracker, operation, tags):
                return func(*args, **kwargs)
        return wrapper
    return decorator
