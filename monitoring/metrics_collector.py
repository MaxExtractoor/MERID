"""
Metrics Collector.

Collects and stores system metrics with time-series support.

Version: 1.0.0
"""

from __future__ import annotations

import threading
import time
import statistics
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from collections import deque

from utils.logger import get_logger

logger = get_logger("monitoring.metrics")


class MetricType(Enum):
    """Types of metrics."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"


@dataclass
class MetricValue:
    """A single metric value."""
    value: float
    timestamp: float = field(default_factory=time.time)
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class Metric:
    """A metric definition."""
    name: str
    metric_type: MetricType
    description: str = ""
    unit: str = ""
    
    # Values (time-series)
    values: deque = field(default_factory=lambda: deque(maxlen=10000))
    
    # Current value (for gauges)
    current_value: float = 0.0
    
    # Histogram buckets
    buckets: List[float] = field(default_factory=lambda: [0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0])
    bucket_counts: Dict[float, int] = field(default_factory=dict)
    
    # Statistics
    total_count: int = 0
    total_sum: float = 0.0
    min_value: float = float("inf")
    max_value: float = float("-inf")
    
    def record(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Record a metric value."""
        mv = MetricValue(value=value, labels=labels or {})
        self.values.append(mv)
        
        self.total_count += 1
        self.total_sum += value
        self.min_value = min(self.min_value, value)
        self.max_value = max(self.max_value, value)
        
        if self.metric_type == MetricType.GAUGE:
            self.current_value = value
        elif self.metric_type == MetricType.COUNTER:
            self.current_value += value
        elif self.metric_type == MetricType.HISTOGRAM:
            for bucket in self.buckets:
                if value <= bucket:
                    self.bucket_counts[bucket] = self.bucket_counts.get(bucket, 0) + 1
    
    def get_percentile(self, p: float) -> float:
        """Get percentile value."""
        if not self.values:
            return 0.0
        sorted_values = sorted(v.value for v in self.values)
        idx = int(len(sorted_values) * p / 100)
        return sorted_values[min(idx, len(sorted_values) - 1)]
    
    def get_average(self) -> float:
        """Get average value."""
        if self.total_count == 0:
            return 0.0
        return self.total_sum / self.total_count
    
    def get_recent_average(self, seconds: float = 60.0) -> float:
        """Get average of recent values."""
        cutoff = time.time() - seconds
        recent = [v.value for v in self.values if v.timestamp >= cutoff]
        if not recent:
            return 0.0
        return sum(recent) / len(recent)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.metric_type.value,
            "description": self.description,
            "unit": self.unit,
            "current_value": self.current_value,
            "total_count": self.total_count,
            "total_sum": self.total_sum,
            "min_value": self.min_value if self.min_value != float("inf") else 0,
            "max_value": self.max_value if self.max_value != float("-inf") else 0,
            "average": self.get_average(),
            "p50": self.get_percentile(50),
            "p95": self.get_percentile(95),
            "p99": self.get_percentile(99),
        }


class MetricsCollector:
    """
    Collects and manages system metrics.
    
    Features:
    - Multiple metric types (counter, gauge, histogram, timer)
    - Time-series storage
    - Percentile calculations
    - Label support
    """
    
    def __init__(self, retention_hours: int = 24):
        self.logger = get_logger("monitoring.metrics")
        self._metrics: Dict[str, Metric] = {}
        self._retention_hours = retention_hours
        
        # Initialize core metrics
        self._init_core_metrics()
    
    def _init_core_metrics(self) -> None:
        """Initialize core system metrics."""
        # Request metrics
        self.register("http_requests_total", MetricType.COUNTER, "Total HTTP requests", "requests")
        self.register("http_request_duration", MetricType.HISTOGRAM, "HTTP request duration", "seconds")
        self.register("http_errors_total", MetricType.COUNTER, "Total HTTP errors", "errors")
        
        # Trading metrics
        self.register("trades_total", MetricType.COUNTER, "Total trades executed", "trades")
        self.register("trade_volume_usd", MetricType.COUNTER, "Total trade volume", "USD")
        self.register("trade_latency", MetricType.HISTOGRAM, "Trade execution latency", "ms")
        
        # Agent metrics
        self.register("agent_decisions", MetricType.COUNTER, "Agent decisions made", "decisions")
        self.register("agent_cycle_time", MetricType.HISTOGRAM, "Agent cycle duration", "seconds")
        
        # System metrics
        self.register("cpu_usage", MetricType.GAUGE, "CPU usage percentage", "percent")
        self.register("memory_usage", MetricType.GAUGE, "Memory usage percentage", "percent")
        self.register("disk_usage", MetricType.GAUGE, "Disk usage percentage", "percent")
        
        # WebSocket metrics
        self.register("ws_connections", MetricType.GAUGE, "Active WebSocket connections", "connections")
        self.register("ws_messages_sent", MetricType.COUNTER, "WebSocket messages sent", "messages")
        
        # Price feed metrics
        self.register("price_updates", MetricType.COUNTER, "Price updates received", "updates")
        self.register("price_feed_latency", MetricType.HISTOGRAM, "Price feed latency", "ms")
    
    def register(
        self,
        name: str,
        metric_type: MetricType,
        description: str = "",
        unit: str = "",
    ) -> Metric:
        """Register a new metric."""
        if name in self._metrics:
            return self._metrics[name]
        
        metric = Metric(
            name=name,
            metric_type=metric_type,
            description=description,
            unit=unit,
        )
        
        self._metrics[name] = metric
        return metric
    
    def record(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        """Record a metric value."""
        metric = self._metrics.get(name)
        if not metric:
            # Auto-register as gauge
            metric = self.register(name, MetricType.GAUGE)
        
        metric.record(value, labels)
    
    def increment(self, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        """Increment a counter metric."""
        metric = self._metrics.get(name)
        if not metric:
            metric = self.register(name, MetricType.COUNTER)
        
        metric.record(value, labels)
    
    def gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Set a gauge metric."""
        metric = self._metrics.get(name)
        if not metric:
            metric = self.register(name, MetricType.GAUGE)
        
        metric.record(value, labels)
    
    def timer(self, name: str) -> "MetricTimer":
        """Create a timer context manager."""
        return MetricTimer(self, name)
    
    def get_metric(self, name: str) -> Optional[Metric]:
        """Get a metric by name."""
        return self._metrics.get(name)
    
    def get_value(self, name: str) -> float:
        """Get current value of a metric."""
        metric = self._metrics.get(name)
        if not metric:
            return 0.0
        return metric.current_value
    
    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get all metrics."""
        return {name: m.to_dict() for name, m in self._metrics.items()}
    
    def get_metrics_by_prefix(self, prefix: str) -> Dict[str, Dict[str, Any]]:
        """Get metrics matching a prefix."""
        return {
            name: m.to_dict()
            for name, m in self._metrics.items()
            if name.startswith(prefix)
        }
    
    def cleanup_old_values(self) -> int:
        """Remove values older than retention period."""
        cutoff = time.time() - (self._retention_hours * 3600)
        removed = 0
        
        for metric in self._metrics.values():
            original_len = len(metric.values)
            metric.values = deque(
                (v for v in metric.values if v.timestamp >= cutoff),
                maxlen=10000
            )
            removed += original_len - len(metric.values)
        
        return removed
    
    def export_prometheus(self) -> str:
        """Export metrics in Prometheus format."""
        lines = []
        
        for name, metric in self._metrics.items():
            # Add help and type
            lines.append(f"# HELP {name} {metric.description}")
            lines.append(f"# TYPE {name} {metric.metric_type.value}")
            
            if metric.metric_type == MetricType.HISTOGRAM:
                # Export histogram buckets
                for bucket, count in sorted(metric.bucket_counts.items()):
                    lines.append(f'{name}_bucket{{le="{bucket}"}} {count}')
                lines.append(f'{name}_bucket{{le="+Inf"}} {metric.total_count}')
                lines.append(f"{name}_sum {metric.total_sum}")
                lines.append(f"{name}_count {metric.total_count}")
            else:
                lines.append(f"{name} {metric.current_value}")
        
        return "\n".join(lines)
    
    def get_status(self) -> Dict[str, Any]:
        """Get collector status."""
        return {
            "total_metrics": len(self._metrics),
            "retention_hours": self._retention_hours,
            "metrics": self.get_all_metrics(),
        }


class MetricTimer:
    """Context manager for timing operations."""
    
    def __init__(self, collector: MetricsCollector, name: str):
        self.collector = collector
        self.name = name
        self.start_time: float = 0.0
    
    def __enter__(self) -> "MetricTimer":
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        duration = time.time() - self.start_time
        self.collector.record(self.name, duration)


# Singleton
_metrics_collector: Optional[MetricsCollector] = None
_metrics_collector_lock = threading.Lock()


def get_metrics_collector() -> MetricsCollector:
    """Get or create the Metrics Collector singleton."""
    global _metrics_collector
    if _metrics_collector is None:
        with _metrics_collector_lock:
            if _metrics_collector is None:
                _metrics_collector = MetricsCollector()
    return _metrics_collector
