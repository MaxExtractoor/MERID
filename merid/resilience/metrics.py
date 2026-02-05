"""Prometheus metrics for MERID resilience layer.

Exposes metrics for monitoring circuit breakers, bulkheads, and risk controls.

Usage:
    from merid.resilience.metrics import get_metrics_text, MetricsCollector
    
    # Get Prometheus-formatted metrics
    text = get_metrics_text()
    
    # Or use collector for custom integration
    collector = MetricsCollector()
    metrics = collector.collect()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.resilience.metrics")


@dataclass
class MetricSample:
    """A single metric sample."""
    name: str
    value: float
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: Optional[float] = None
    
    def to_prometheus(self) -> str:
        """Format as Prometheus text."""
        if self.labels:
            label_str = ",".join(f'{k}="{v}"' for k, v in self.labels.items())
            return f"{self.name}{{{label_str}}} {self.value}"
        return f"{self.name} {self.value}"


@dataclass
class MetricFamily:
    """A family of related metrics."""
    name: str
    help_text: str
    metric_type: str  # counter, gauge, histogram, summary
    samples: List[MetricSample] = field(default_factory=list)
    
    def to_prometheus(self) -> str:
        """Format as Prometheus text with HELP and TYPE."""
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} {self.metric_type}",
        ]
        for sample in self.samples:
            lines.append(sample.to_prometheus())
        return "\n".join(lines)


class MetricsCollector:
    """
    Collects metrics from MERID resilience components.
    
    Provides Prometheus-compatible metrics for:
    - Circuit breaker state and failure counts
    - Bulkhead utilization and queue depth
    - Risk controller state and P&L
    - Operation latencies and error rates
    """
    
    def collect(self) -> List[MetricFamily]:
        """Collect all metrics."""
        families = []
        families.extend(self._collect_circuit_breaker_metrics())
        families.extend(self._collect_bulkhead_metrics())
        families.extend(self._collect_risk_metrics())
        return families
    
    def _collect_circuit_breaker_metrics(self) -> List[MetricFamily]:
        """Collect circuit breaker metrics."""
        try:
            from merid.resilience.circuit_breaker import get_all_breakers
        except ImportError:
            return []
        
        breakers = get_all_breakers()
        if not breakers:
            return []
        
        # Circuit state (0=closed, 1=half-open, 2=open)
        state_family = MetricFamily(
            name="merid_circuit_breaker_state",
            help_text="Circuit breaker state (0=closed, 1=half_open, 2=open)",
            metric_type="gauge",
        )
        
        # Failure count
        failure_family = MetricFamily(
            name="merid_circuit_breaker_failures_total",
            help_text="Total circuit breaker failures",
            metric_type="counter",
        )
        
        # Time until retry
        retry_family = MetricFamily(
            name="merid_circuit_breaker_retry_seconds",
            help_text="Seconds until circuit breaker retry",
            metric_type="gauge",
        )
        
        state_map = {"closed": 0, "half_open": 1, "open": 2}
        
        for name, breaker in breakers.items():
            stats = breaker.get_stats()
            
            state_family.samples.append(MetricSample(
                name="merid_circuit_breaker_state",
                value=state_map.get(stats["state"], 0),
                labels={"venue": name},
            ))
            
            failure_family.samples.append(MetricSample(
                name="merid_circuit_breaker_failures_total",
                value=stats["failure_count"],
                labels={"venue": name},
            ))
            
            retry_family.samples.append(MetricSample(
                name="merid_circuit_breaker_retry_seconds",
                value=stats["time_until_retry"],
                labels={"venue": name},
            ))
        
        return [state_family, failure_family, retry_family]
    
    def _collect_bulkhead_metrics(self) -> List[MetricFamily]:
        """Collect bulkhead metrics."""
        try:
            from merid.resilience.bulkhead import get_all_bulkheads
        except ImportError:
            return []
        
        bulkheads = get_all_bulkheads()
        if not bulkheads:
            return []
        
        # Active count
        active_family = MetricFamily(
            name="merid_bulkhead_active",
            help_text="Number of active operations in bulkhead",
            metric_type="gauge",
        )
        
        # Queued count
        queued_family = MetricFamily(
            name="merid_bulkhead_queued",
            help_text="Number of queued operations in bulkhead",
            metric_type="gauge",
        )
        
        # Total accepted
        accepted_family = MetricFamily(
            name="merid_bulkhead_accepted_total",
            help_text="Total operations accepted by bulkhead",
            metric_type="counter",
        )
        
        # Total rejected
        rejected_family = MetricFamily(
            name="merid_bulkhead_rejected_total",
            help_text="Total operations rejected by bulkhead",
            metric_type="counter",
        )
        
        # Average wait time
        wait_family = MetricFamily(
            name="merid_bulkhead_wait_ms",
            help_text="Average wait time in milliseconds",
            metric_type="gauge",
        )
        
        for name, bulkhead in bulkheads.items():
            stats = bulkhead.get_stats()
            
            active_family.samples.append(MetricSample(
                name="merid_bulkhead_active",
                value=stats.active_count,
                labels={"bulkhead": name},
            ))
            
            queued_family.samples.append(MetricSample(
                name="merid_bulkhead_queued",
                value=stats.queued_count,
                labels={"bulkhead": name},
            ))
            
            accepted_family.samples.append(MetricSample(
                name="merid_bulkhead_accepted_total",
                value=stats.total_accepted,
                labels={"bulkhead": name},
            ))
            
            rejected_family.samples.append(MetricSample(
                name="merid_bulkhead_rejected_total",
                value=stats.total_rejected,
                labels={"bulkhead": name},
            ))
            
            wait_family.samples.append(MetricSample(
                name="merid_bulkhead_wait_ms",
                value=stats.avg_wait_ms,
                labels={"bulkhead": name},
            ))
        
        return [active_family, queued_family, accepted_family, rejected_family, wait_family]
    
    def _collect_risk_metrics(self) -> List[MetricFamily]:
        """Collect risk controller metrics."""
        try:
            from merid.risk import get_risk_status
        except ImportError:
            return []
        
        try:
            status = get_risk_status()
        except Exception:
            return []
        
        families = []
        
        # Kill switch state (0=active, 1=triggered)
        state_family = MetricFamily(
            name="merid_risk_kill_switch_state",
            help_text="Kill switch state (0=active/trading, 1=triggered/halted)",
            metric_type="gauge",
        )
        state_family.samples.append(MetricSample(
            name="merid_risk_kill_switch_state",
            value=0 if status.get("can_trade", True) else 1,
        ))
        families.append(state_family)
        
        # Daily P&L
        pnl_family = MetricFamily(
            name="merid_risk_daily_pnl_usd",
            help_text="Daily realized P&L in USD",
            metric_type="gauge",
        )
        pnl_family.samples.append(MetricSample(
            name="merid_risk_daily_pnl_usd",
            value=status.get("daily_pnl", 0.0),
        ))
        families.append(pnl_family)
        
        # Daily P&L percentage of limit
        pnl_pct_family = MetricFamily(
            name="merid_risk_daily_pnl_pct",
            help_text="Daily P&L as percentage of loss limit",
            metric_type="gauge",
        )
        pnl_pct_family.samples.append(MetricSample(
            name="merid_risk_daily_pnl_pct",
            value=status.get("daily_loss_pct", 0.0),
        ))
        families.append(pnl_pct_family)
        
        # Position value
        position_family = MetricFamily(
            name="merid_risk_position_value_usd",
            help_text="Current total position value in USD",
            metric_type="gauge",
        )
        position_family.samples.append(MetricSample(
            name="merid_risk_position_value_usd",
            value=status.get("position_value", 0.0),
        ))
        families.append(position_family)
        
        # Error count
        error_family = MetricFamily(
            name="merid_risk_error_count",
            help_text="Error count in current window",
            metric_type="gauge",
        )
        error_family.samples.append(MetricSample(
            name="merid_risk_error_count",
            value=status.get("error_count", 0),
        ))
        families.append(error_family)
        
        return families


# Singleton collector
_collector: Optional[MetricsCollector] = None


def get_collector() -> MetricsCollector:
    """Get or create the metrics collector."""
    global _collector
    if _collector is None:
        _collector = MetricsCollector()
    return _collector


def get_metrics_text() -> str:
    """
    Get all metrics in Prometheus text format.
    
    Returns:
        Prometheus-formatted metrics string
        
    Example:
        >>> text = get_metrics_text()
        >>> print(text)
        # HELP merid_circuit_breaker_state Circuit breaker state
        # TYPE merid_circuit_breaker_state gauge
        merid_circuit_breaker_state{venue="kalshi"} 0
        ...
    """
    collector = get_collector()
    families = collector.collect()
    
    lines = []
    for family in families:
        lines.append(family.to_prometheus())
        lines.append("")  # Blank line between families
    
    return "\n".join(lines)


def get_metrics_json() -> Dict:
    """
    Get all metrics as JSON-serializable dict.
    
    Returns:
        Dictionary with metric families and values
    """
    collector = get_collector()
    families = collector.collect()
    
    result = {}
    for family in families:
        result[family.name] = {
            "help": family.help_text,
            "type": family.metric_type,
            "samples": [
                {
                    "labels": s.labels,
                    "value": s.value,
                }
                for s in family.samples
            ],
        }
    
    return result
