"""
MERID SLO (Service Level Objective) Monitor
Implements SLO tracking, alerting, and compliance reporting for critical services.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.slo_monitor")


class SLOStatus(Enum):
    """SLO compliance status."""
    COMPLIANT = "compliant"
    WARNING = "warning"
    VIOLATING = "violating"
    UNKNOWN = "unknown"


@dataclass
class SLOMetric:
    """Individual SLO metric definition."""
    name: str
    description: str
    target_percent: float  # Target success rate (e.g., 99.9)
    window_minutes: int    # Time window for evaluation
    current_percent: float = 0.0
    status: SLOStatus = SLOStatus.UNKNOWN
    last_updated: float = field(default_factory=time.time)


@dataclass
class SLOResult:
    """Result of an SLO evaluation."""
    slo_name: str
    status: SLOStatus
    success_count: int
    total_count: int
    success_rate: float
    window_start: datetime
    window_end: datetime
    violations: List[Dict[str, Any]] = field(default_factory=list)


class SLOMonitor:
    """
    SLO monitoring and compliance tracking.
    
    Tracks service level objectives across critical MERID components:
    - API availability and latency
    - Order execution success rates
    - Data freshness and completeness
    - System health and responsiveness
    """
    
    def __init__(self):
        self.slos: Dict[str, SLOMetric] = {
            # API SLOs
            "api_availability": SLOMetric(
                name="api_availability",
                description="API endpoint availability",
                target_percent=99.9,
                window_minutes=30
            ),
            "api_latency_p99": SLOMetric(
                name="api_latency_p99", 
                description="99th percentile API latency < 500ms",
                target_percent=95.0,
                window_minutes=15
            ),
            
            # Trading SLOs
            "order_success_rate": SLOMetric(
                name="order_success_rate",
                description="Order execution success rate",
                target_percent=99.5,
                window_minutes=60
            ),
            "order_latency_p95": SLOMetric(
                name="order_latency_p95",
                description="95th percentile order latency < 2s",
                target_percent=90.0,
                window_minutes=30
            ),
            
            # Data SLOs
            "market_data_freshness": SLOMetric(
                name="market_data_freshness",
                description="Market data freshness < 5s",
                target_percent=98.0,
                window_minutes=10
            ),
            "portfolio_sync": SLOMetric(
                name="portfolio_sync",
                description="Portfolio position sync completeness",
                target_percent=99.0,
                window_minutes=5
            ),
            
            # System SLOs
            "system_health": SLOMetric(
                name="system_health",
                description="Overall system health score",
                target_percent=95.0,
                window_minutes=5
            ),
            
            # Loop SLOs
            "loop_features_success": SLOMetric(
                name="loop_features_success",
                description="Loop feature refresh success rate",
                target_percent=98.0,
                window_minutes=15
            ),
            "loop_consensus_success": SLOMetric(
                name="loop_consensus_success",
                description="Loop consensus aggregation success rate",
                target_percent=99.0,
                window_minutes=15
            ),
            "loop_arb_scan_success": SLOMetric(
                name="loop_arb_scan_success",
                description="Loop arbitrage scan success rate",
                target_percent=95.0,
                window_minutes=15
            ),
            "loop_execution_success": SLOMetric(
                name="loop_execution_success",
                description="Loop execution step success rate",
                target_percent=99.5,
                window_minutes=15
            ),
            "background_task_completed": SLOMetric(
                name="background_task_completed",
                description="Background task completion success rate",
                target_percent=95.0,
                window_minutes=15
            )
        }
        
        # Metrics storage for SLO calculations
        self.metrics_buffer: Dict[str, List[Dict[str, Any]]] = {}
        self.violation_log: List[Dict[str, Any]] = []
        
    @classmethod
    def get_instance(cls) -> "SLOMonitor":
        """Return the process-wide SLO monitor singleton."""
        return slo_monitor

    def track_slo(
        self,
        metric_name: str,
        success: bool,
        total: int = 1,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a single SLO data point (dynamic metric names accepted)."""
        timestamp = time.time()
        if metric_name not in self.metrics_buffer:
            self.metrics_buffer[metric_name] = []
        self.metrics_buffer[metric_name].append(
            {"timestamp": timestamp, "success": success, "metadata": metadata or {}}
        )
        if len(self.metrics_buffer[metric_name]) > 1000:
            self.metrics_buffer[metric_name] = self.metrics_buffer[metric_name][-1000:]

    def record_metric(self, slo_name: str, success: bool,
                      latency_ms: Optional[float] = None,
                      metadata: Optional[Dict[str, Any]] = None):
        """Record a metric for SLO tracking."""
        if slo_name not in self.slos:
            logger.warning(f"Unknown SLO: {slo_name}")
            return
            
        timestamp = time.time()
        metric_entry = {
            "timestamp": timestamp,
            "success": success,
            "latency_ms": latency_ms,
            "metadata": metadata or {}
        }
        
        if slo_name not in self.metrics_buffer:
            self.metrics_buffer[slo_name] = []
            
        self.metrics_buffer[slo_name].append(metric_entry)
        
        # Keep buffer size manageable (keep last 1000 entries per SLO)
        if len(self.metrics_buffer[slo_name]) > 1000:
            self.metrics_buffer[slo_name] = self.metrics_buffer[slo_name][-1000:]
            
    def evaluate_slo(self, slo_name: str) -> SLOResult:
        """Evaluate SLO compliance for a specific metric."""
        if slo_name not in self.slos:
            raise ValueError(f"Unknown SLO: {slo_name}")
            
        slo = self.slos[slo_name]
        now = time.time()
        window_start = now - (slo.window_minutes * 60)
        
        # Get metrics in the evaluation window
        if slo_name not in self.metrics_buffer:
            return SLOResult(
                slo_name=slo_name,
                status=SLOStatus.UNKNOWN,
                success_count=0,
                total_count=0,
                success_rate=0.0,
                window_start=datetime.fromtimestamp(window_start, tz=timezone.utc),
                window_end=datetime.fromtimestamp(now, tz=timezone.utc)
            )
            
        window_metrics = [
            m for m in self.metrics_buffer[slo_name] 
            if m["timestamp"] >= window_start
        ]
        
        if not window_metrics:
            return SLOResult(
                slo_name=slo_name,
                status=SLOStatus.UNKNOWN,
                success_count=0,
                total_count=0,
                success_rate=0.0,
                window_start=datetime.fromtimestamp(window_start, tz=timezone.utc),
                window_end=datetime.fromtimestamp(now, tz=timezone.utc)
            )
            
        # Calculate success rate
        total_count = len(window_metrics)
        success_count = sum(1 for m in window_metrics if m["success"])
        success_rate = (success_count / total_count) * 100.0
        
        # Determine status
        if success_rate >= slo.target_percent:
            status = SLOStatus.COMPLIANT
        elif success_rate >= slo.target_percent * 0.9:  # 90% of target
            status = SLOStatus.WARNING
        else:
            status = SLOStatus.VIOLATING
            
        # Find violations (failed metrics in window)
        violations = [
            m for m in window_metrics 
            if not m["success"]
        ]
        
        # Update SLO metric
        slo.current_percent = success_rate
        slo.status = status
        slo.last_updated = now
        
        # Log violations
        if status == SLOStatus.VIOLATING:
            for violation in violations:
                self.violation_log.append({
                    "slo_name": slo_name,
                    "timestamp": violation["timestamp"],
                    "metadata": violation["metadata"]
                })
                
        return SLOResult(
            slo_name=slo_name,
            status=status,
            success_count=success_count,
            total_count=total_count,
            success_rate=success_rate,
            window_start=datetime.fromtimestamp(window_start, tz=timezone.utc),
            window_end=datetime.fromtimestamp(now, tz=timezone.utc),
            violations=violations
        )
        
    def evaluate_all_slos(self) -> Dict[str, SLOResult]:
        """Evaluate all configured SLOs."""
        results = {}
        for slo_name in self.slos:
            results[slo_name] = self.evaluate_slo(slo_name)
        return results
        
    def get_overall_status(self) -> SLOStatus:
        """Get overall SLO status across all metrics."""
        results = self.evaluate_all_slos()
        
        if not results:
            return SLOStatus.UNKNOWN
            
        statuses = [r.status for r in results.values()]
        
        if all(s == SLOStatus.COMPLIANT for s in statuses):
            return SLOStatus.COMPLIANT
        elif any(s == SLOStatus.VIOLATING for s in statuses):
            return SLOStatus.VIOLATING
        else:
            return SLOStatus.WARNING
            
    def get_slo_summary(self) -> Dict[str, Any]:
        """Get comprehensive SLO summary for monitoring."""
        results = self.evaluate_all_slos()
        overall_status = self.get_overall_status()
        
        return {
            "overall_status": overall_status.value,
            "evaluation_time": datetime.now(timezone.utc).isoformat(),
            "slos": {
                name: {
                    "status": result.status.value,
                    "success_rate": result.success_rate,
                    "target": self.slos[name].target_percent,
                    "window_minutes": self.slos[name].window_minutes,
                    "success_count": result.success_count,
                    "total_count": result.total_count,
                    "violations": len(result.violations)
                }
                for name, result in results.items()
            },
            "recent_violations": [
                v for v in self.violation_log 
                if time.time() - v["timestamp"] <= 3600  # Last hour
            ]
        }


# Global SLO monitor instance
slo_monitor = SLOMonitor()


def get_slo_monitor() -> SLOMonitor:
    """Get the global SLO monitor instance."""
    return slo_monitor


# Decorator for automatic SLO tracking
def track_slo(slo_name: str, success_threshold: bool = True):
    """Decorator to automatically track SLO metrics."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            success = False
            metadata = {"function": func.__name__}
            
            try:
                result = func(*args, **kwargs)
                success = True
                return result
            except Exception as e:
                metadata["error"] = str(e)
                raise
            finally:
                latency_ms = (time.time() - start_time) * 1000
                slo_monitor.record_metric(slo_name, success, latency_ms, metadata)
                
        return wrapper
    return decorator
