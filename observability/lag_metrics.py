"""
End-to-end lag metrics for MERID data quality observability.

Tracks latency across all pipeline stages (ingestion, processing, execution) to
identify bottlenecks and ensure time-sensitive operations meet SLA requirements.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class LagMeasurement:
    stage: str
    operation: str
    lag_ms: float
    measured_at: datetime
    metadata: Dict[str, object]


@dataclass
class LagAlert:
    alert_id: str
    stage: str
    operation: str
    lag_ms: float
    threshold_ms: float
    severity: str
    detected_at: datetime


class LagMetricsCollector:
    """
    Collects and analyzes end-to-end lag metrics.
    
    Features:
    - Per-stage latency tracking
    - Per-venue lag monitoring
    - SLA violation detection
    - Historical lag analysis
    """
    
    def __init__(self):
        self._measurements: List[LagMeasurement] = []
        self._alerts: List[LagAlert] = []
        self._stage_thresholds: Dict[str, float] = {
            "market_data_ingestion": 100.0,
            "market_data_processing": 50.0,
            "signal_generation": 200.0,
            "execution_submission": 500.0,
            "execution_fill": 1000.0,
            "end_to_end": 2000.0,
        }
    
    def record_lag(
        self,
        stage: str,
        operation: str,
        start_time: float,
        end_time: Optional[float] = None,
        metadata: Optional[Dict[str, object]] = None,
    ) -> LagMeasurement:
        """Record lag measurement for a pipeline stage."""
        end_ts = end_time or time.time()
        lag_interval = max(0.0, end_ts - start_time)
        lag_us = int(round(lag_interval * 1_000_000))
        lag_ms = lag_us / 1000.0  # Convert using integer microseconds to avoid float drift
        
        measurement = LagMeasurement(
            stage=stage,
            operation=operation,
            lag_ms=lag_ms,
            measured_at=datetime.utcnow(),
            metadata=metadata or {},
        )
        
        self._measurements.append(measurement)
        
        threshold = self._stage_thresholds.get(stage)
        if threshold is not None:
            threshold_us = int(round(threshold * 1000.0))
            if lag_us >= threshold_us:
                self._emit_alert(stage, operation, lag_ms, threshold)
        
        if len(self._measurements) > 10000:
            self._measurements = self._measurements[-5000:]
        
        return measurement
    
    def _emit_alert(
        self,
        stage: str,
        operation: str,
        lag_ms: float,
        threshold_ms: float,
    ) -> None:
        """Emit lag alert when threshold exceeded."""
        severity = (
            "critical" if lag_ms > threshold_ms * 3
            else "high" if lag_ms > threshold_ms * 2
            else "medium"
        )
        
        alert = LagAlert(
            alert_id=f"lag_{stage}_{int(time.time())}",
            stage=stage,
            operation=operation,
            lag_ms=lag_ms,
            threshold_ms=threshold_ms,
            severity=severity,
            detected_at=datetime.utcnow(),
        )
        
        self._alerts.append(alert)
        logger.warning(
            f"Lag alert: {stage}/{operation} lag={lag_ms:.2f}ms "
            f"(threshold={threshold_ms}ms)"
        )
        
        if len(self._alerts) > 1000:
            self._alerts = self._alerts[-500:]
    
    def get_stage_stats(self, stage: str, window_minutes: int = 5) -> Dict[str, float]:
        """Get statistics for a specific stage."""
        cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
        recent = [
            m for m in self._measurements
            if m.stage == stage and m.measured_at > cutoff
        ]
        
        if not recent:
            return {
                "count": 0,
                "avg_ms": 0.0,
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "max_ms": 0.0,
            }
        
        lags = sorted(m.lag_ms for m in recent)
        count = len(lags)
        
        return {
            "count": count,
            "avg_ms": sum(lags) / count,
            "p50_ms": lags[int(count * 0.5)],
            "p95_ms": lags[int(count * 0.95)] if count > 20 else lags[-1],
            "p99_ms": lags[int(count * 0.99)] if count > 100 else lags[-1],
            "max_ms": max(lags),
        }
    
    def get_recent_alerts(self, limit: int = 20) -> List[LagAlert]:
        """Get recent lag alerts."""
        return self._alerts[-limit:]
    
    def set_threshold(self, stage: str, threshold_ms: float) -> None:
        """Set lag threshold for a stage."""
        self._stage_thresholds[stage] = threshold_ms
        logger.info(f"Set lag threshold for {stage}: {threshold_ms}ms")
    
    def get_lag_summary(self) -> Dict[str, object]:
        """Get overall lag summary."""
        recent_alerts = [
            a for a in self._alerts
            if a.detected_at > datetime.utcnow() - timedelta(hours=1)
        ]
        
        stage_stats = {}
        for stage in self._stage_thresholds.keys():
            stage_stats[stage] = self.get_stage_stats(stage)
        
        return {
            "total_measurements": len(self._measurements),
            "recent_alerts_1h": len(recent_alerts),
            "total_alerts": len(self._alerts),
            "stage_thresholds": self._stage_thresholds.copy(),
            "stage_stats": stage_stats,
        }


class LatencyTracker:
    """Tracks execution latency with percentile calculations.

    Implements E-003: P99 latency tracking and SLA alerting.

    Maintains a rolling window of recent latency measurements and computes
    percentiles for monitoring and alerting.
    """

    def __init__(self, window_size: int = 1000, alert_threshold_ms: float = 2000.0):
        """Initialize latency tracker.

        Args:
            window_size: Number of measurements to keep in rolling window
            alert_threshold_ms: P99 threshold for alerting (default 2000ms)
        """
        self._latencies: List[float] = []
        self._window_size = window_size
        self._alert_threshold_ms = alert_threshold_ms
        self._total_recorded = 0

    def record(self, latency_ms: float) -> None:
        """Record a latency measurement.

        Args:
            latency_ms: Latency in milliseconds
        """
        self._latencies.append(latency_ms)
        self._total_recorded += 1

        # Trim to window size
        if len(self._latencies) > self._window_size:
            self._latencies = self._latencies[-self._window_size:]

    def p99(self) -> float:
        """Get P99 latency.

        Returns:
            P99 latency in milliseconds, or 0.0 if no data
        """
        if not self._latencies:
            return 0.0

        sorted_lats = sorted(self._latencies)
        idx = int(len(sorted_lats) * 0.99)
        return sorted_lats[min(idx, len(sorted_lats) - 1)]

    def p95(self) -> float:
        """Get P95 latency.

        Returns:
            P95 latency in milliseconds, or 0.0 if no data
        """
        if not self._latencies:
            return 0.0

        sorted_lats = sorted(self._latencies)
        idx = int(len(sorted_lats) * 0.95)
        return sorted_lats[min(idx, len(sorted_lats) - 1)]

    def p50(self) -> float:
        """Get P50 (median) latency.

        Returns:
            P50 latency in milliseconds, or 0.0 if no data
        """
        if not self._latencies:
            return 0.0

        sorted_lats = sorted(self._latencies)
        idx = int(len(sorted_lats) * 0.50)
        return sorted_lats[min(idx, len(sorted_lats) - 1)]

    def avg(self) -> float:
        """Get average latency.

        Returns:
            Average latency in milliseconds, or 0.0 if no data
        """
        if not self._latencies:
            return 0.0
        return sum(self._latencies) / len(self._latencies)

    def max(self) -> float:
        """Get maximum latency.

        Returns:
            Maximum latency in milliseconds, or 0.0 if no data
        """
        return max(self._latencies) if self._latencies else 0.0

    def summary(self) -> Dict[str, float]:
        """Get latency summary statistics.

        Returns:
            Dictionary with count, avg, p50, p95, p99, max
        """
        return {
            "count": len(self._latencies),
            "total_recorded": self._total_recorded,
            "avg_ms": self.avg(),
            "p50_ms": self.p50(),
            "p95_ms": self.p95(),
            "p99_ms": self.p99(),
            "max_ms": self.max(),
        }

    def check_sla(self) -> bool:
        """Check if P99 exceeds alert threshold.

        Implements E-003: SLA violation detection.

        Returns:
            True if P99 exceeds threshold, False otherwise
        """
        if len(self._latencies) < 100:
            # Need sufficient samples for reliable P99
            return False

        return self.p99() > self._alert_threshold_ms


_lag_metrics_collector: Optional[LagMetricsCollector] = None


def get_lag_metrics_collector() -> LagMetricsCollector:
    """Get global LagMetricsCollector instance."""
    global _lag_metrics_collector
    if _lag_metrics_collector is None:
        _lag_metrics_collector = LagMetricsCollector()
    return _lag_metrics_collector
