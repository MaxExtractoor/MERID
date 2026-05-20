"""
Sizing Validation Metrics

Emits Prometheus metrics for sizing validation job.
Follows Prometheus naming and labeling best practices.
"""

from typing import Dict, Optional
from prometheus_client import Counter, Gauge, Histogram, Summary
from prometheus_client.registry import CollectorRegistry

# Metric names follow Prometheus best practices:
# - Use snake_case
# - Use unit suffixes (e.g., _total, _seconds, _bytes)
# - Use labels for dimensions (asset, strategy, etc.)
# Source: https://betterstack.com/community/guides/monitoring/prometheus-best-practices/

# Create a custom registry for sizing metrics
sizing_registry = CollectorRegistry()

# Counters
sizing_validation_total = Counter(
    'merid_sizing_validation_total',
    'Total number of sizing validations performed',
    ['asset', 'strategy', 'status'],  # status: passed, failed, skipped
    registry=sizing_registry
)

sizing_mismatch_total = Counter(
    'merid_sizing_mismatch_total',
    'Total number of sizing mismatches detected',
    ['asset', 'strategy', 'mismatch_type'],  # mismatch_type: intended_size, intended_notional, actual_size, actual_notional
    registry=sizing_registry
)

# Gauges
sizing_validation_pass_rate = Gauge(
    'merid_sizing_validation_pass_rate',
    'Pass rate of sizing validations (0-1)',
    ['asset', 'strategy'],
    registry=sizing_registry
)

sizing_intended_size_diff = Gauge(
    'merid_sizing_intended_size_diff',
    'Average difference between stored and recomputed intended size (contracts)',
    ['asset', 'strategy'],
    registry=sizing_registry
)

sizing_intended_notional_diff = Gauge(
    'merid_sizing_intended_notional_diff',
    'Average difference between stored and recomputed intended notional (USD)',
    ['asset', 'strategy'],
    registry=sizing_registry
)

# Histograms
sizing_validation_duration = Histogram(
    'merid_sizing_validation_duration_seconds',
    'Time taken to perform sizing validation',
    ['asset', 'strategy'],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
    registry=sizing_registry
)

sizing_intended_size = Histogram(
    'merid_sizing_intended_size',
    'Distribution of intended sizes (contracts)',
    ['asset', 'strategy'],
    buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000],
    registry=sizing_registry
)

sizing_intended_notional = Histogram(
    'merid_sizing_intended_notional',
    'Distribution of intended notional (USD)',
    ['asset', 'strategy'],
    buckets=[10, 50, 100, 500, 1000, 5000, 10000, 50000, 100000],
    registry=sizing_registry
)


class SizingMetricsEmitter:
    """Emits Prometheus metrics for sizing validation."""
    
    def __init__(self, registry: Optional[CollectorRegistry] = None):
        """
        Initialize metrics emitter.
        
        Args:
            registry: Custom Prometheus registry (uses sizing_registry if None)
        """
        self.registry = registry or sizing_registry
    
    def emit_validation_result(
        self,
        asset: str,
        strategy: str,
        passed: bool,
        intended_size: int,
        intended_notional: float,
        duration_seconds: float,
    ):
        """
        Emit metrics for a single validation result.
        
        Args:
            asset: Asset symbol
            strategy: Strategy name
            passed: Whether validation passed
            intended_size: Intended size in contracts
            intended_notional: Intended notional in USD
            duration_seconds: Validation duration in seconds
        """
        status = "passed" if passed else "failed"
        
        sizing_validation_total.labels(
            asset=asset,
            strategy=strategy,
            status=status
        ).inc()
        
        sizing_intended_size.labels(
            asset=asset,
            strategy=strategy
        ).observe(intended_size)
        
        sizing_intended_notional.labels(
            asset=asset,
            strategy=strategy
        ).observe(intended_notional)
        
        sizing_validation_duration.labels(
            asset=asset,
            strategy=strategy
        ).observe(duration_seconds)
    
    def emit_mismatch(
        self,
        asset: str,
        strategy: str,
        mismatch_type: str,
    ):
        """
        Emit metric for a sizing mismatch.
        
        Args:
            asset: Asset symbol
            strategy: Strategy name
            mismatch_type: Type of mismatch (intended_size, intended_notional, actual_size, actual_notional)
        """
        sizing_mismatch_total.labels(
            asset=asset,
            strategy=strategy,
            mismatch_type=mismatch_type
        ).inc()
    
    def emit_summary(
        self,
        asset: str,
        strategy: str,
        pass_rate: float,
        avg_intended_size_diff: float,
        avg_intended_notional_diff: float,
    ):
        """
        Emit summary metrics for a validation batch.
        
        Args:
            asset: Asset symbol
            strategy: Strategy name
            pass_rate: Pass rate (0-1)
            avg_intended_size_diff: Average intended size difference
            avg_intended_notional_diff: Average intended notional difference
        """
        sizing_validation_pass_rate.labels(
            asset=asset,
            strategy=strategy
        ).set(pass_rate)
        
        sizing_intended_size_diff.labels(
            asset=asset,
            strategy=strategy
        ).set(avg_intended_size_diff)
        
        sizing_intended_notional_diff.labels(
            asset=asset,
            strategy=strategy
        ).set(avg_intended_notional_diff)
    
    def get_metrics(self) -> str:
        """
        Get metrics in Prometheus text format.
        
        Returns:
            Prometheus metrics as text
        """
        from prometheus_client import exposition
        return exposition.generate_latest(self.registry)


# Singleton instance
_metrics_emitter: Optional[SizingMetricsEmitter] = None


def get_sizing_metrics_emitter() -> SizingMetricsEmitter:
    """
    Get the singleton sizing metrics emitter.
    
    Returns:
        SizingMetricsEmitter instance
    """
    global _metrics_emitter
    if _metrics_emitter is None:
        _metrics_emitter = SizingMetricsEmitter()
    return _metrics_emitter
