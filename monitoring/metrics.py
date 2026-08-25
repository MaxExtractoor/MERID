"""
Metrics - Prometheus-compatible metrics with latency tracking and business metrics.

This module implements the observability layer for MERID:
- Prometheus-compatible metric collection
- Agent health metrics
- Consensus metrics
- Stream metrics
- Execution metrics
- Latency tracking with P50, P95, P99 percentiles
- Business metrics (orders, P&L, slippage, fill rate)
- System resource monitoring

Version: 2.0.0
Reference: MASTER_SPEC.md Section 7.1 (Scalability Layer)
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional
import statistics

from utils.logger import get_logger
from config.monitoring_config import get_monitoring_config, MetricsConfig

logger = get_logger("monitoring.metrics")


class MetricType(Enum):
    """Types of metrics."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


@dataclass
class MetricLabel:
    """Label for a metric."""
    name: str
    value: str


@dataclass
class MetricValue:
    """A single metric value with labels."""
    name: str
    metric_type: MetricType
    value: float
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    help_text: str = ""


@dataclass
class HistogramBucket:
    """Histogram bucket definition."""
    le: float
    count: int = 0


class Counter:
    """
    Prometheus-style counter metric.
    
    Counters only go up (or reset to zero on restart).
    """
    
    def __init__(self, name: str, help_text: str = "", labels: Optional[List[str]] = None) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = labels or []
        self._values: Dict[tuple, float] = defaultdict(float)
    
    def inc(self, value: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        """Increment counter."""
        if value < 0:
            raise ValueError("Counter can only be incremented")
        label_key = self._make_label_key(labels)
        self._values[label_key] += value
    
    def get(self, labels: Optional[Dict[str, str]] = None) -> float:
        """Get current counter value."""
        label_key = self._make_label_key(labels)
        return self._values[label_key]
    
    def collect(self) -> List[MetricValue]:
        """Collect all metric values."""
        results = []
        for label_key, value in self._values.items():
            labels = dict(zip(self.label_names, label_key)) if label_key else {}
            results.append(MetricValue(
                name=self.name,
                metric_type=MetricType.COUNTER,
                value=value,
                labels=labels,
                help_text=self.help_text,
            ))
        return results
    
    def _make_label_key(self, labels: Optional[Dict[str, str]]) -> tuple:
        if not labels:
            return ()
        return tuple(labels.get(name, "") for name in self.label_names)


class Gauge:
    """
    Prometheus-style gauge metric.
    
    Gauges can go up and down.
    """
    
    def __init__(self, name: str, help_text: str = "", labels: Optional[List[str]] = None) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = labels or []
        self._values: Dict[tuple, float] = defaultdict(float)
    
    def set(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Set gauge value."""
        label_key = self._make_label_key(labels)
        self._values[label_key] = value
    
    def inc(self, value: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        """Increment gauge."""
        label_key = self._make_label_key(labels)
        self._values[label_key] += value
    
    def dec(self, value: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        """Decrement gauge."""
        label_key = self._make_label_key(labels)
        self._values[label_key] -= value
    
    def get(self, labels: Optional[Dict[str, str]] = None) -> float:
        """Get current gauge value."""
        label_key = self._make_label_key(labels)
        return self._values[label_key]
    
    def collect(self) -> List[MetricValue]:
        """Collect all metric values."""
        results = []
        for label_key, value in self._values.items():
            labels = dict(zip(self.label_names, label_key)) if label_key else {}
            results.append(MetricValue(
                name=self.name,
                metric_type=MetricType.GAUGE,
                value=value,
                labels=labels,
                help_text=self.help_text,
            ))
        return results
    
    def _make_label_key(self, labels: Optional[Dict[str, str]]) -> tuple:
        if not labels:
            return ()
        return tuple(labels.get(name, "") for name in self.label_names)


class Histogram:
    """
    Prometheus-style histogram metric.
    
    Tracks value distributions in configurable buckets.
    """
    
    DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
    
    def __init__(
        self,
        name: str,
        help_text: str = "",
        labels: Optional[List[str]] = None,
        buckets: Optional[tuple] = None,
    ) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = labels or []
        self.buckets = buckets or self.DEFAULT_BUCKETS
        
        self._bucket_counts: Dict[tuple, Dict[float, int]] = defaultdict(
            lambda: {b: 0 for b in self.buckets}
        )
        self._sums: Dict[tuple, float] = defaultdict(float)
        self._counts: Dict[tuple, int] = defaultdict(int)
    
    def observe(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Observe a value."""
        label_key = self._make_label_key(labels)
        
        self._sums[label_key] += value
        self._counts[label_key] += 1
        
        for bucket in self.buckets:
            if value <= bucket:
                self._bucket_counts[label_key][bucket] += 1
    
    def collect(self) -> List[MetricValue]:
        """Collect all metric values."""
        results = []
        
        for label_key in self._counts.keys():
            labels = dict(zip(self.label_names, label_key)) if label_key else {}
            
            for bucket, count in self._bucket_counts[label_key].items():
                bucket_labels = {**labels, "le": str(bucket)}
                results.append(MetricValue(
                    name=f"{self.name}_bucket",
                    metric_type=MetricType.HISTOGRAM,
                    value=count,
                    labels=bucket_labels,
                    help_text=self.help_text,
                ))
            
            results.append(MetricValue(
                name=f"{self.name}_sum",
                metric_type=MetricType.HISTOGRAM,
                value=self._sums[label_key],
                labels=labels,
                help_text=self.help_text,
            ))
            
            results.append(MetricValue(
                name=f"{self.name}_count",
                metric_type=MetricType.HISTOGRAM,
                value=self._counts[label_key],
                labels=labels,
                help_text=self.help_text,
            ))
        
        return results
    
    def _make_label_key(self, labels: Optional[Dict[str, str]]) -> tuple:
        if not labels:
            return ()
        return tuple(labels.get(name, "") for name in self.label_names)


class Summary:
    """
    Prometheus-style summary metric with percentile tracking.
    
    Tracks value distributions and calculates P50, P95, P99 percentiles.
    Used for latency tracking and SLA monitoring.
    """
    
    def __init__(
        self,
        name: str,
        help_text: str = "",
        labels: Optional[List[str]] = None,
        percentiles: Optional[List[float]] = None,
        max_age_seconds: float = 600.0,  # 10 minutes
        age_buckets: int = 5,
    ) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = labels or []
        self.percentiles = percentiles or [0.5, 0.95, 0.99]
        self.max_age_seconds = max_age_seconds
        self.age_buckets = age_buckets
        
        # Store samples per label key with timestamps
        self._samples: Dict[tuple, List[tuple[float, float]]] = defaultdict(list)  # (value, timestamp)
        self._sums: Dict[tuple, float] = defaultdict(float)
        self._counts: Dict[tuple, int] = defaultdict(int)
    
    def observe(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Observe a value."""
        label_key = self._make_label_key(labels)
        now = time.time()
        
        self._samples[label_key].append((value, now))
        self._sums[label_key] += value
        self._counts[label_key] += 1
        
        # Clean old samples
        self._cleanup_old_samples(label_key, now)
    
    def _cleanup_old_samples(self, label_key: tuple, now: float) -> None:
        """Remove samples older than max_age_seconds."""
        cutoff = now - self.max_age_seconds
        self._samples[label_key] = [
            (v, t) for v, t in self._samples[label_key] if t > cutoff
        ]
    
    def _calculate_percentiles(self, label_key: tuple) -> Dict[float, float]:
        """Calculate percentiles for a label key."""
        samples = [v for v, t in self._samples[label_key]]
        if not samples:
            return {p: 0.0 for p in self.percentiles}
        
        sorted_samples = sorted(samples)
        n = len(sorted_samples)
        
        percentiles = {}
        for p in self.percentiles:
            index = int(n * p)
            if index >= n:
                index = n - 1
            percentiles[p] = sorted_samples[index]
        
        return percentiles
    
    def collect(self) -> List[MetricValue]:
        """Collect all metric values."""
        results = []
        now = time.time()
        
        for label_key in self._counts.keys():
            labels = dict(zip(self.label_names, label_key)) if label_key else {}
            
            # Clean old samples before collecting
            self._cleanup_old_samples(label_key, now)
            
            # Calculate percentiles
            percentiles = self._calculate_percentiles(label_key)
            
            # Emit percentile metrics
            for p, value in percentiles.items():
                percentile_labels = {**labels, "quantile": str(p)}
                results.append(MetricValue(
                    name=f"{self.name}",
                    metric_type=MetricType.SUMMARY,
                    value=value,
                    labels=percentile_labels,
                    help_text=self.help_text,
                ))
            
            # Emit sum and count
            results.append(MetricValue(
                name=f"{self.name}_sum",
                metric_type=MetricType.SUMMARY,
                value=self._sums[label_key],
                labels=labels,
                help_text=self.help_text,
            ))
            
            results.append(MetricValue(
                name=f"{self.name}_count",
                metric_type=MetricType.SUMMARY,
                value=self._counts[label_key],
                labels=labels,
                help_text=self.help_text,
            ))
        
        return results
    
    def _make_label_key(self, labels: Optional[Dict[str, str]]) -> tuple:
        if not labels:
            return ()
        return tuple(labels.get(name, "") for name in self.label_names)


class MetricsRegistry:
    """
    Central registry for all metrics with business metrics and system monitoring.
    
    Provides Prometheus-compatible metric collection and export with:
    - Standard Prometheus metrics (counter, gauge, histogram, summary)
    - Business metrics (orders, P&L, slippage, fill rate)
    - System resource monitoring (CPU, memory, disk, network)
    - Latency tracking with percentiles
    """
    
    def __init__(self, config: Optional[MetricsConfig] = None) -> None:
        self._config = config or get_monitoring_config().metrics
        self._metrics: Dict[str, object] = {}
        self._collectors: List[Callable[[], List[MetricValue]]] = []
        self._logger = get_logger("monitoring.metrics.registry")
        
        # Initialize business metrics
        self._init_business_metrics()
        
        # Initialize system resource metrics
        self._init_system_metrics()
    
    def _init_business_metrics(self) -> None:
        """Initialize business metrics for trading operations."""
        if self._config.track_orders:
            self.counter(
                "trading_orders_total",
                "Total number of trading orders",
                labels=["venue", "side", "status"]
            )
            self.counter(
                "trading_orders_submitted",
                "Number of orders submitted",
                labels=["venue", "side"]
            )
            self.counter(
                "trading_orders_filled",
                "Number of orders filled",
                labels=["venue", "side"]
            )
            self.counter(
                "trading_orders_rejected",
                "Number of orders rejected",
                labels=["venue", "reason"]
            )
        
        if self._config.track_pnl:
            self.gauge(
                "trading_pnl_total",
                "Total profit and loss",
                labels=["venue", "asset"]
            )
            self.gauge(
                "trading_pnl_daily",
                "Daily profit and loss",
                labels=["venue", "asset"]
            )
        
        if self._config.track_slippage:
            self.summary(
                "trading_slippage_bps",
                "Trading slippage in basis points",
                labels=["venue", "side"],
                percentiles=self._config.percentiles
            )
        
        if self._config.track_fill_rate:
            self.gauge(
                "trading_fill_rate",
                "Order fill rate (0-1)",
                labels=["venue"]
            )
        
        # Latency metrics for trading operations
        self.summary(
            "trading_order_latency_seconds",
            "Order submission latency in seconds",
            labels=["venue"],
            percentiles=self._config.percentiles
        )
        
        self.summary(
            "trading_fill_latency_seconds",
            "Order fill latency in seconds",
            labels=["venue"],
            percentiles=self._config.percentiles
        )
    
    def _init_system_metrics(self) -> None:
        """Initialize system resource monitoring metrics."""
        if self._config.track_cpu:
            self.gauge(
                "system_cpu_percent",
                "CPU usage percentage",
                labels=["core"]
            )
        
        if self._config.track_memory:
            self.gauge(
                "system_memory_bytes",
                "Memory usage in bytes",
                labels=["type"]  # type: used, available, total
            )
            self.gauge(
                "system_memory_percent",
                "Memory usage percentage",
            )
        
        if self._config.track_disk:
            self.gauge(
                "system_disk_bytes",
                "Disk usage in bytes",
                labels=["mount", "type"]  # type: used, free, total
            )
        
        if self._config.track_network:
            self.counter(
                "system_network_bytes",
                "Network traffic in bytes",
                labels=["direction", "interface"]  # direction: sent, received
            )
    
    def counter(
        self,
        name: str,
        help_text: str = "",
        labels: Optional[List[str]] = None,
    ) -> Counter:
        """Create or get a counter metric."""
        if name in self._metrics:
            return self._metrics[name]  # type: ignore
        
        counter = Counter(name, help_text, labels)
        self._metrics[name] = counter
        return counter
    
    def gauge(
        self,
        name: str,
        help_text: str = "",
        labels: Optional[List[str]] = None,
    ) -> Gauge:
        """Create or get a gauge metric."""
        if name in self._metrics:
            return self._metrics[name]  # type: ignore
        
        gauge = Gauge(name, help_text, labels)
        self._metrics[name] = gauge
        return gauge
    
    def histogram(
        self,
        name: str,
        help_text: str = "",
        labels: Optional[List[str]] = None,
        buckets: Optional[tuple] = None,
    ) -> Histogram:
        """Create or get a histogram metric."""
        if name in self._metrics:
            return self._metrics[name]  # type: ignore
        
        histogram = Histogram(name, help_text, labels, buckets)
        self._metrics[name] = histogram
        return histogram
    
    def summary(
        self,
        name: str,
        help_text: str = "",
        labels: Optional[List[str]] = None,
        percentiles: Optional[List[float]] = None,
    ) -> Summary:
        """Create or get a summary metric with percentile tracking."""
        if name in self._metrics:
            return self._metrics[name]  # type: ignore
        
        summary = Summary(name, help_text, labels, percentiles)
        self._metrics[name] = summary
        return summary
    
    def register_collector(
        self,
        collector: Callable[[], List[MetricValue]],
    ) -> None:
        """Register a custom collector function."""
        self._collectors.append(collector)
    
    def collect_all(self) -> List[MetricValue]:
        """Collect all metrics from all sources."""
        results: List[MetricValue] = []
        
        for metric in self._metrics.values():
            if hasattr(metric, "collect"):
                results.extend(metric.collect())
        
        for collector in self._collectors:
            try:
                results.extend(collector())
            except Exception as e:
                self._logger.error("Collector error: %s", e)
        
        return results
    
    def export_prometheus(self) -> str:
        """Export metrics in Prometheus text format."""
        lines: List[str] = []
        metrics = self.collect_all()
        
        metrics_by_name: Dict[str, List[MetricValue]] = defaultdict(list)
        for metric in metrics:
            metrics_by_name[metric.name].append(metric)
        
        for name, values in sorted(metrics_by_name.items()):
            if values and values[0].help_text:
                lines.append(f"# HELP {name} {values[0].help_text}")
            if values:
                lines.append(f"# TYPE {name} {values[0].metric_type.value}")
            
            for value in values:
                if value.labels:
                    label_str = ",".join(
                        f'{k}="{v}"' for k, v in sorted(value.labels.items())
                    )
                    lines.append(f"{name}{{{label_str}}} {value.value}")
                else:
                    lines.append(f"{name} {value.value}")
        
        return "\n".join(lines)


_metrics_registry: Optional[MetricsRegistry] = None
_metrics_registry_lock = threading.Lock()


def get_metrics_registry(config: Optional[MetricsConfig] = None) -> MetricsRegistry:
    """Get or create global metrics registry with optional config."""
    global _metrics_registry
    if _metrics_registry is None:
        with _metrics_registry_lock:
            if _metrics_registry is None:
                _metrics_registry = MetricsRegistry(config)
                _initialize_default_metrics(_metrics_registry)
    return _metrics_registry


def _initialize_default_metrics(registry: MetricsRegistry) -> None:
    """Initialize default MERID metrics."""
    
    registry.counter(
        "merid_agent_observations_total",
        "Total agent observations",
        ["agent_id"],
    )
    
    registry.counter(
        "merid_agent_votes_total",
        "Total agent votes",
        ["agent_id", "decision"],
    )


class SystemMetricsCollector:
    """
    Collects system resource metrics (CPU, memory, disk, network).
    
    Updates metrics at regular intervals with minimal performance impact.
    """
    
    def __init__(self, registry: MetricsRegistry, config: Optional[MetricsConfig] = None):
        self._registry = registry
        self._config = config or get_monitoring_config().metrics
        self._logger = get_logger("monitoring.metrics.system")
        self._running = False
        self._task = None
    
    async def start(self) -> None:
        """Start system metrics collection."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._collect_loop())
        self._logger.info("System metrics collector started")
    
    async def stop(self) -> None:
        """Stop system metrics collection."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._logger.info("System metrics collector stopped")
    
    async def _collect_loop(self) -> None:
        """Main collection loop."""
        import psutil
        
        while self._running:
            try:
                self._collect_system_metrics(psutil)
                await asyncio.sleep(self._config.system_metrics_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"System metrics collection error: {e}")
                await asyncio.sleep(self._config.system_metrics_interval)
    
    def _collect_system_metrics(self, psutil) -> None:
        """Collect system resource metrics."""
        try:
            # CPU metrics
            if self._config.track_cpu:
                cpu_percent = psutil.cpu_percent(interval=0.1)
                self._registry.gauge("system_cpu_percent").set(cpu_percent, labels={"core": "all"})
                
                # Per-core CPU
                for i, percent in enumerate(psutil.cpu_percent(interval=0.1, percpu=True)):
                    self._registry.gauge("system_cpu_percent").set(percent, labels={"core": str(i)})
            
            # Memory metrics
            if self._config.track_memory:
                mem = psutil.virtual_memory()
                self._registry.gauge("system_memory_bytes").set(mem.total, labels={"type": "total"})
                self._registry.gauge("system_memory_bytes").set(mem.available, labels={"type": "available"})
                self._registry.gauge("system_memory_bytes").set(mem.used, labels={"type": "used"})
                self._registry.gauge("system_memory_percent").set(mem.percent)
            
            # Disk metrics
            if self._config.track_disk:
                for partition in psutil.disk_partitions():
                    try:
                        usage = psutil.disk_usage(partition.mountpoint)
                        mount = partition.mountpoint.replace("\\", "").replace("/", "")
                        self._registry.gauge("system_disk_bytes").set(usage.total, labels={"mount": mount, "type": "total"})
                        self._registry.gauge("system_disk_bytes").set(usage.free, labels={"mount": mount, "type": "free"})
                        self._registry.gauge("system_disk_bytes").set(usage.used, labels={"mount": mount, "type": "used"})
                    except Exception as e:
                        self._logger.warning(f"Failed to collect disk metrics for {partition.mountpoint}: {e}")
            
            # Network metrics
            if self._config.track_network:
                net_io = psutil.net_io_counters()
                self._registry.counter("system_network_bytes").inc(net_io.bytes_sent, labels={"direction": "sent", "interface": "all"})
                self._registry.counter("system_network_bytes").inc(net_io.bytes_recv, labels={"direction": "received", "interface": "all"})
        
        except Exception as e:
            self._logger.error(f"Failed to collect system metrics: {e}")


def _initialize_default_metrics(registry: MetricsRegistry) -> None:
    """Initialize default MERID metrics."""
    
    registry.counter(
        "merid_agent_observations_total",
        "Total agent observations",
        ["agent_id"],
    )
    
    registry.counter(
        "merid_agent_votes_total",
        "Total agent votes",
        ["agent_id", "decision"],
    )
    
    registry.histogram(
        "merid_agent_processing_seconds",
        "Agent processing time",
        ["agent_id"],
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    )
    
    registry.gauge(
        "merid_agent_trust_score",
        "Agent trust score",
        ["agent_id"],
    )
    
    registry.counter(
        "merid_consensus_rounds_total",
        "Total consensus rounds",
        ["state"],
    )
    
    registry.histogram(
        "merid_consensus_duration_seconds",
        "Consensus round duration",
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    )
    
    registry.gauge(
        "merid_consensus_approval_ratio",
        "Last consensus approval ratio",
    )
    
    registry.counter(
        "merid_stream_events_total",
        "Total stream events",
        ["stream_id", "event_type"],
    )
    
    registry.gauge(
        "merid_stream_buffer_size",
        "Stream buffer size",
        ["stream_id"],
    )
    
    registry.counter(
        "merid_stream_errors_total",
        "Total stream errors",
        ["stream_id"],
    )
    
    registry.counter(
        "merid_orders_total",
        "Total orders",
        ["side", "status"],
    )
    
    registry.gauge(
        "merid_positions_count",
        "Open positions count",
    )
    
    registry.gauge(
        "merid_portfolio_equity",
        "Portfolio equity",
    )
    
    registry.gauge(
        "merid_portfolio_unrealized_pnl",
        "Unrealized P&L",
    )
    
    registry.counter(
        "merid_oracle_requests_total",
        "Total oracle requests",
        ["oracle_id"],
    )
    
    registry.gauge(
        "merid_oracle_status",
        "Oracle status (1=connected, 0=disconnected)",
        ["oracle_id"],
    )
    
    registry.histogram(
        "merid_oracle_latency_seconds",
        "Oracle request latency",
        ["oracle_id"],
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0),
    )

    # P0-001: Spot price staleness metrics for PM crypto
    registry.counter(
        "merid_pm_spot_staleness_violations_total",
        "Total spot price staleness violations (age > max_spot_age_seconds)",
        ["asset", "market_id"],
    )

    registry.gauge(
        "merid_pm_spot_age_seconds",
        "Current spot price age in seconds",
        ["asset"],
    )

    # 50¢ order guardrail metrics (production audit)
    registry.counter(
        "kalshi_price_50_rejected_total",
        "Total orders rejected in 48-52c band",
        ["ticker", "reason"],
    )

    registry.counter(
        "kalshi_fallback_averted_total",
        "Total times 0.50 fallback was prevented",
        ["location"],
    )

    registry.counter(
        "kalshi_signal_validation_failed_total",
        "Total orders failing signal validation",
        ["reason"],
    )

    registry.counter(
        "kalshi_invalid_price_rejected_total",
        "Total orders rejected due to invalid price",
        ["price_cents"],
    )

    # Catalog enrichment metrics
    registry.counter(
        "catalog_enrich_skipped_markets",
        "Total markets skipped during catalog enrichment due to invalid data",
        ["reason", "asset"],
    )

    # Entry window metrics
    registry.counter(
        "entry_window_rejections",
        "Total markets rejected due to entry window filter",
        ["agent_id", "reason"],
    )


def record_agent_observation(agent_id: str) -> None:
    """Record an agent observation."""
    registry = get_metrics_registry()
    counter = registry._metrics.get("merid_agent_observations_total")
    if counter:
        counter.inc(labels={"agent_id": agent_id})


def record_entry_window_rejection(agent_id: str, reason: str) -> None:
    """Record an entry window rejection."""
    registry = get_metrics_registry()
    counter = registry._metrics.get("entry_window_rejections")
    if counter:
        counter.inc(labels={"agent_id": agent_id, "reason": reason})


def record_agent_vote(agent_id: str, decision: str) -> None:
    """Record an agent vote."""
    registry = get_metrics_registry()
    counter = registry._metrics.get("merid_agent_votes_total")
    if counter:
        counter.inc(labels={"agent_id": agent_id, "decision": decision})


def record_agent_processing_time(agent_id: str, duration_seconds: float) -> None:
    """Record agent processing time."""
    registry = get_metrics_registry()
    histogram = registry._metrics.get("merid_agent_processing_seconds")
    if histogram:
        histogram.observe(duration_seconds, labels={"agent_id": agent_id})


def update_agent_trust(agent_id: str, trust_score: float) -> None:
    """Update agent trust score metric."""
    registry = get_metrics_registry()
    gauge = registry._metrics.get("merid_agent_trust_score")
    if gauge:
        gauge.set(trust_score, labels={"agent_id": agent_id})


def record_consensus_round(state: str, duration_seconds: float) -> None:
    """Record a consensus round."""
    registry = get_metrics_registry()
    
    counter = registry._metrics.get("merid_consensus_rounds_total")
    if counter:
        counter.inc(labels={"state": state})
    
    histogram = registry._metrics.get("merid_consensus_duration_seconds")
    if histogram:
        histogram.observe(duration_seconds)


def record_stream_event(stream_id: str, event_type: str) -> None:
    """Record a stream event."""
    registry = get_metrics_registry()
    counter = registry._metrics.get("merid_stream_events_total")
    if counter:
        counter.inc(labels={"stream_id": stream_id, "event_type": event_type})


def record_order(side: str, status: str) -> None:
    """Record an order."""
    registry = get_metrics_registry()
    counter = registry._metrics.get("merid_orders_total")
    if counter:
        counter.inc(labels={"side": side, "status": status})


def update_portfolio_metrics(
    equity: float,
    unrealized_pnl: float,
    positions_count: int,
) -> None:
    """Update portfolio metrics."""
    registry = get_metrics_registry()
    
    equity_gauge = registry._metrics.get("merid_portfolio_equity")
    if equity_gauge:
        equity_gauge.set(equity)
    
    pnl_gauge = registry._metrics.get("merid_portfolio_unrealized_pnl")
    if pnl_gauge:
        pnl_gauge.set(unrealized_pnl)
    
    positions_gauge = registry._metrics.get("merid_positions_count")
    if positions_gauge:
        positions_gauge.set(positions_count)


# P0-001: Spot price staleness metric helpers
def record_pm_spot_staleness_violation(asset: str, market_id: str = "") -> None:
    """Record a spot price staleness violation.

    Called when spot price age exceeds max_spot_age_seconds().
    """
    registry = get_metrics_registry()
    counter = registry._metrics.get("merid_pm_spot_staleness_violations_total")
    if counter:
        counter.inc(labels={"asset": asset, "market_id": market_id or "unknown"})


def update_pm_spot_age(asset: str, age_seconds: float) -> None:
    """Update the current spot price age metric.

    Should be called whenever spot price is fetched to track freshness.
    """
    registry = get_metrics_registry()
    gauge = registry._metrics.get("merid_pm_spot_age_seconds")
    if gauge:
        gauge.set(age_seconds, labels={"asset": asset})


# ============================================================================
# ASGI Fatal Error and Shutdown Metrics (Incident Response)
# ============================================================================

# Shutdown metrics (defined at module level for import from asgi_guard)
MERID_SHUTDOWN_TOTAL = Counter(
    "merid_shutdowns_total",
    "Total system shutdowns by reason",
    labels=["reason", "sub_reason"],
)

MERID_ASGI_FATAL_ERRORS_TOTAL = Counter(
    "merid_asgi_fatal_errors_total",
    "ASGI-level fatal errors by type",
    labels=["error_type", "source"],
)

MERID_VENUE_RESTART_COUNT = Counter(
    "merid_venue_restart_count",
    "Venue client restarts",
    labels=["venue", "reason"],
)

MERID_AGENT_EXECUTION_ERRORS_TOTAL = Counter(
    "merid_agent_execution_errors_total",
    "Agent signal execution errors",
    labels=["agent", "exception", "market"],
)

# Shutdown reason tracking
CURRENT_SHUTDOWN_REASON = Gauge(
    "merid_current_shutdown_reason",
    "Current shutdown reason code (0=none, 1=user, 2=asgi_fatal, 3=loop_lag, 4=killswitch)",
)


def record_shutdown(reason: str, sub_reason: str = "none") -> None:
    """Record a system shutdown event."""
    MERID_SHUTDOWN_TOTAL.inc(labels={"reason": reason, "sub_reason": sub_reason})


def record_asgi_fatal(error_type: str, source: str = "asgi") -> None:
    """Record an ASGI fatal error."""
    MERID_ASGI_FATAL_ERRORS_TOTAL.inc(labels={"error_type": error_type, "source": source})


def record_venue_restart(venue: str, reason: str) -> None:
    """Record a venue client restart."""
    MERID_VENUE_RESTART_COUNT.inc(labels={"venue": venue, "reason": reason})


def record_agent_execution_error(agent: str, exception: str, market: str = "unknown") -> None:
    """Record an agent execution error."""
    MERID_AGENT_EXECUTION_ERRORS_TOTAL.inc(
        labels={"agent": agent, "exception": exception, "market": market}
    )
