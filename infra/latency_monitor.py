"""
Latency monitoring and optimization framework for MERID.

Implements:
- End-to-end latency tracking
- Market data and execution latency
- RPC and infrastructure latency
- AI/model inference latency
- Real-time alerting and optimization
"""

import logging
import time
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal
import statistics

logger = logging.getLogger(__name__)


class LatencyMetricType(Enum):
    """Latency metric type."""
    END_TO_END_USER = "end_to_end_user"
    MARKET_DATA = "market_data"
    EXECUTION = "execution"
    RPC_CALL = "rpc_call"
    AI_INFERENCE = "ai_inference"
    DATABASE_QUERY = "database_query"
    NETWORK_ROUND_TRIP = "network_round_trip"


class LatencyThreshold(Enum):
    """Latency threshold levels."""
    EXCELLENT = 50  # < 50ms
    GOOD = 100  # < 100ms
    ACCEPTABLE = 500  # < 500ms
    POOR = 1000  # < 1000ms
    CRITICAL = 5000  # < 5000ms


@dataclass
class LatencyMeasurement:
    """Latency measurement."""
    measurement_id: str
    metric_type: LatencyMetricType
    
    # Timing
    start_time: float
    end_time: float
    latency_ms: float
    
    # Context
    component: str
    operation: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Breakdown (for end-to-end)
    breakdown: Dict[str, float] = field(default_factory=dict)
    
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class LatencyAlert:
    """Latency alert."""
    alert_id: str
    metric_type: LatencyMetricType
    
    # Threshold
    threshold_ms: float
    actual_ms: float
    
    # Context
    component: str
    operation: str
    
    # Severity
    severity: str = "warning"  # warning, critical
    
    # Status
    acknowledged: bool = False
    resolved: bool = False
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class LatencyBudget:
    """Latency budget for operations."""
    budget_id: str
    operation: str
    
    # Budget
    target_p50_ms: float
    target_p95_ms: float
    target_p99_ms: float
    
    # Current performance
    actual_p50_ms: float = 0.0
    actual_p95_ms: float = 0.0
    actual_p99_ms: float = 0.0
    
    # Status
    within_budget: bool = True
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class OptimizationRecommendation:
    """Optimization recommendation."""
    recommendation_id: str
    
    # Target
    metric_type: LatencyMetricType
    component: str
    
    # Issue
    issue_description: str
    current_latency_ms: float
    target_latency_ms: float
    
    # Recommendation
    recommendation: str
    estimated_improvement_ms: float
    
    # Priority
    priority: str = "medium"  # low, medium, high
    
    # Status
    implemented: bool = False
    
    created_at: datetime = field(default_factory=datetime.utcnow)


class LatencyMonitor:
    """
    Latency monitoring and optimization framework.
    
    Features:
    - Multi-layer latency tracking
    - Real-time alerting
    - Latency budgets
    - Optimization recommendations
    - Performance analytics
    """
    
    def __init__(self):
        self._measurements: List[LatencyMeasurement] = []
        self._alerts: List[LatencyAlert] = []
        self._budgets: Dict[str, LatencyBudget] = {}
        self._recommendations: List[OptimizationRecommendation] = []
        
        # Configuration
        self._alert_thresholds = {
            LatencyMetricType.END_TO_END_USER: 1000.0,  # 1s
            LatencyMetricType.MARKET_DATA: 100.0,  # 100ms
            LatencyMetricType.EXECUTION: 500.0,  # 500ms
            LatencyMetricType.RPC_CALL: 200.0,  # 200ms
            LatencyMetricType.AI_INFERENCE: 1000.0,  # 1s
            LatencyMetricType.DATABASE_QUERY: 100.0,  # 100ms
            LatencyMetricType.NETWORK_ROUND_TRIP: 50.0,  # 50ms
        }
        
        self._initialize_budgets()
    
    def _initialize_budgets(self) -> None:
        """Initialize latency budgets."""
        
        # User action latency budget
        self.set_latency_budget(
            operation="user_trade_submission",
            target_p50_ms=500.0,
            target_p95_ms=1000.0,
            target_p99_ms=2000.0,
        )
        
        # Market data latency budget
        self.set_latency_budget(
            operation="market_data_update",
            target_p50_ms=50.0,
            target_p95_ms=100.0,
            target_p99_ms=200.0,
        )
        
        # Strategy execution latency budget
        self.set_latency_budget(
            operation="strategy_execution",
            target_p50_ms=200.0,
            target_p95_ms=500.0,
            target_p99_ms=1000.0,
        )
        
        # Liquidation latency budget
        self.set_latency_budget(
            operation="liquidation_execution",
            target_p50_ms=100.0,
            target_p95_ms=200.0,
            target_p99_ms=500.0,
        )
        
        logger.info(f"Initialized {len(self._budgets)} latency budgets")
    
    def measure_latency(
        self,
        metric_type: LatencyMetricType,
        component: str,
        operation: str,
        start_time: float,
        end_time: Optional[float] = None,
        breakdown: Optional[Dict[str, float]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> LatencyMeasurement:
        """Measure and record latency."""
        if end_time is None:
            end_time = time.time()
        
        latency_ms = (end_time - start_time) * 1000
        
        measurement_id = f"lat_{int(time.time() * 1000)}"
        
        measurement = LatencyMeasurement(
            measurement_id=measurement_id,
            metric_type=metric_type,
            start_time=start_time,
            end_time=end_time,
            latency_ms=latency_ms,
            component=component,
            operation=operation,
            breakdown=breakdown or {},
            metadata=metadata or {},
        )
        
        self._measurements.append(measurement)
        
        # Check threshold
        threshold = self._alert_thresholds.get(metric_type)
        if threshold and latency_ms > threshold:
            self._create_alert(measurement, threshold)
        
        # Update budget if applicable
        self._update_budget(operation, latency_ms)
        
        logger.debug(
            f"Measured latency: {component}/{operation} - {latency_ms:.2f}ms"
        )
        
        return measurement
    
    def _create_alert(
        self,
        measurement: LatencyMeasurement,
        threshold_ms: float,
    ) -> LatencyAlert:
        """Create latency alert."""
        alert_id = f"alert_{int(time.time() * 1000)}"
        
        severity = "critical" if measurement.latency_ms > threshold_ms * 2 else "warning"
        
        alert = LatencyAlert(
            alert_id=alert_id,
            metric_type=measurement.metric_type,
            threshold_ms=threshold_ms,
            actual_ms=measurement.latency_ms,
            component=measurement.component,
            operation=measurement.operation,
            severity=severity,
        )
        
        self._alerts.append(alert)
        
        logger.warning(
            f"Latency alert [{severity}]: {measurement.component}/{measurement.operation} - "
            f"{measurement.latency_ms:.2f}ms (threshold: {threshold_ms:.2f}ms)"
        )
        
        return alert
    
    def set_latency_budget(
        self,
        operation: str,
        target_p50_ms: float,
        target_p95_ms: float,
        target_p99_ms: float,
    ) -> LatencyBudget:
        """Set latency budget for operation."""
        budget_id = f"budget_{operation}"
        
        budget = LatencyBudget(
            budget_id=budget_id,
            operation=operation,
            target_p50_ms=target_p50_ms,
            target_p95_ms=target_p95_ms,
            target_p99_ms=target_p99_ms,
        )
        
        self._budgets[budget_id] = budget
        
        logger.info(
            f"Set latency budget for '{operation}': "
            f"p50={target_p50_ms}ms, p95={target_p95_ms}ms, p99={target_p99_ms}ms"
        )
        
        return budget
    
    def _update_budget(self, operation: str, latency_ms: float) -> None:
        """Update latency budget with new measurement."""
        budget_id = f"budget_{operation}"
        budget = self._budgets.get(budget_id)
        
        if not budget:
            return
        
        # Get recent measurements for this operation
        recent_measurements = [
            m.latency_ms for m in self._measurements
            if m.operation == operation
            and m.timestamp >= datetime.utcnow() - timedelta(hours=1)
        ]
        
        if len(recent_measurements) < 10:
            return
        
        # Calculate percentiles
        recent_measurements.sort()
        n = len(recent_measurements)
        
        budget.actual_p50_ms = recent_measurements[int(n * 0.50)]
        budget.actual_p95_ms = recent_measurements[int(n * 0.95)]
        budget.actual_p99_ms = recent_measurements[int(n * 0.99)]
        
        # Check if within budget
        budget.within_budget = (
            budget.actual_p50_ms <= budget.target_p50_ms and
            budget.actual_p95_ms <= budget.target_p95_ms and
            budget.actual_p99_ms <= budget.target_p99_ms
        )
        
        if not budget.within_budget:
            logger.warning(
                f"Latency budget exceeded for '{operation}': "
                f"p50={budget.actual_p50_ms:.2f}ms (target: {budget.target_p50_ms}ms)"
            )
    
    def add_optimization_recommendation(
        self,
        metric_type: LatencyMetricType,
        component: str,
        issue_description: str,
        current_latency_ms: float,
        target_latency_ms: float,
        recommendation: str,
        estimated_improvement_ms: float,
        priority: str = "medium",
    ) -> OptimizationRecommendation:
        """Add optimization recommendation."""
        recommendation_id = f"opt_{int(time.time() * 1000)}"
        
        opt = OptimizationRecommendation(
            recommendation_id=recommendation_id,
            metric_type=metric_type,
            component=component,
            issue_description=issue_description,
            current_latency_ms=current_latency_ms,
            target_latency_ms=target_latency_ms,
            recommendation=recommendation,
            estimated_improvement_ms=estimated_improvement_ms,
            priority=priority,
        )
        
        self._recommendations.append(opt)
        
        logger.info(
            f"Added optimization recommendation [{priority}]: {component} - "
            f"{recommendation} (estimated improvement: {estimated_improvement_ms:.2f}ms)"
        )
        
        return opt
    
    def get_latency_stats(
        self,
        metric_type: Optional[LatencyMetricType] = None,
        time_window_hours: int = 1,
    ) -> Dict[str, Any]:
        """Get latency statistics."""
        cutoff = datetime.utcnow() - timedelta(hours=time_window_hours)
        
        measurements = [
            m for m in self._measurements
            if m.timestamp >= cutoff
        ]
        
        if metric_type:
            measurements = [m for m in measurements if m.metric_type == metric_type]
        
        if not measurements:
            return {
                "count": 0,
                "avg_ms": 0.0,
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "max_ms": 0.0,
            }
        
        latencies = [m.latency_ms for m in measurements]
        latencies.sort()
        n = len(latencies)
        
        return {
            "count": n,
            "avg_ms": statistics.mean(latencies),
            "p50_ms": latencies[int(n * 0.50)],
            "p95_ms": latencies[int(n * 0.95)],
            "p99_ms": latencies[int(n * 0.99)],
            "max_ms": max(latencies),
        }
    
    def get_critical_path_analysis(
        self,
        operation: str,
    ) -> Dict[str, Any]:
        """Analyze critical path for operation."""
        # Get recent measurements with breakdown
        recent = [
            m for m in self._measurements
            if m.operation == operation
            and m.breakdown
            and m.timestamp >= datetime.utcnow() - timedelta(hours=1)
        ]
        
        if not recent:
            return {"operation": operation, "stages": []}
        
        # Aggregate breakdown by stage
        stage_latencies: Dict[str, List[float]] = {}
        
        for measurement in recent:
            for stage, latency in measurement.breakdown.items():
                if stage not in stage_latencies:
                    stage_latencies[stage] = []
                stage_latencies[stage].append(latency)
        
        # Calculate stats per stage
        stages = []
        for stage, latencies in stage_latencies.items():
            stages.append({
                "stage": stage,
                "avg_ms": statistics.mean(latencies),
                "p95_ms": sorted(latencies)[int(len(latencies) * 0.95)],
                "contribution_pct": statistics.mean(latencies) / sum(
                    statistics.mean(lats) for lats in stage_latencies.values()
                ) * 100,
            })
        
        # Sort by contribution
        stages.sort(key=lambda s: s["contribution_pct"], reverse=True)
        
        return {
            "operation": operation,
            "total_measurements": len(recent),
            "stages": stages,
        }
    
    def get_latency_dashboard(self) -> Dict[str, Any]:
        """Get latency monitoring dashboard."""
        # Overall stats
        overall_stats = self.get_latency_stats(time_window_hours=1)
        
        # Stats by metric type
        by_type = {
            metric_type.value: self.get_latency_stats(
                metric_type=metric_type,
                time_window_hours=1,
            )
            for metric_type in LatencyMetricType
        }
        
        # Active alerts
        active_alerts = [a for a in self._alerts if not a.resolved]
        
        # Budget status
        budgets_within = sum(1 for b in self._budgets.values() if b.within_budget)
        
        return {
            "overall": overall_stats,
            "by_type": by_type,
            "alerts": {
                "total": len(self._alerts),
                "active": len(active_alerts),
                "critical": sum(1 for a in active_alerts if a.severity == "critical"),
                "warning": sum(1 for a in active_alerts if a.severity == "warning"),
            },
            "budgets": {
                "total": len(self._budgets),
                "within_budget": budgets_within,
                "exceeded": len(self._budgets) - budgets_within,
            },
            "optimizations": {
                "total_recommendations": len(self._recommendations),
                "implemented": sum(1 for r in self._recommendations if r.implemented),
                "pending_high_priority": sum(
                    1 for r in self._recommendations
                    if not r.implemented and r.priority == "high"
                ),
            },
        }


_latency_monitor: Optional[LatencyMonitor] = None


def get_latency_monitor() -> LatencyMonitor:
    """Get global LatencyMonitor instance."""
    global _latency_monitor
    if _latency_monitor is None:
        _latency_monitor = LatencyMonitor()
    return _latency_monitor
