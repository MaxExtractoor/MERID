"""
Drift Detection Metrics - Runtime alarms for configuration and guard mismatches.

These metrics catch mismatches that only appear over time, acting as runtime alarms
if any future change introduces drift or duplication.
"""

import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DriftMetric:
    """A single drift detection metric."""
    name: str
    value: float
    threshold: float
    description: str
    is_violation: bool
    
    def __str__(self) -> str:
        status = "VIOLATION" if self.is_violation else "OK"
        return f"{self.name}: {self.value:.4f} (threshold: {self.threshold:.4f}) - {status}"


class DriftMetricsCollector:
    """
    Collects drift detection metrics across all domains.
    
    Metrics:
    - risk_envelope_vs_positions_violation: Realized exposure exceeds envelope caps
    - profile_limit_mismatch: KalshiRiskManager cap differs from envelope-derived cap
    - data_freshness_violation: Health check says fresh but router says stale
    - scheduler_vs_catalog_window_mismatch: Scheduler believes tradable but catalog says not
    """
    
    def __init__(self):
        self._metrics: Dict[str, DriftMetric] = {}
    
    def collect_risk_envelope_drift(
        self,
        envelope_max_notional_usd: float,
        realized_exposure_usd: float,
        pending_orders_notional_usd: float,
        epsilon: float = 0.01  # 1% tolerance
    ) -> DriftMetric:
        """
        Check if realized exposure or open orders exceed envelope caps.
        
        Args:
            envelope_max_notional_usd: Max notional from risk envelope
            realized_exposure_usd: Current realized exposure
            pending_orders_notional_usd: Pending orders notional
            epsilon: Tolerance for floating-point comparison
            
        Returns:
            DriftMetric for risk envelope vs positions
        """
        total_exposure = realized_exposure_usd + pending_orders_notional_usd
        violation_pct = (total_exposure - envelope_max_notional_usd) / envelope_max_notional_usd
        
        is_violation = violation_pct > epsilon
        
        metric = DriftMetric(
            name="risk_envelope_vs_positions_violation",
            value=violation_pct,
            threshold=epsilon,
            description=f"Realized exposure (${total_exposure:.2f}) vs envelope cap (${envelope_max_notional_usd:.2f})",
            is_violation=is_violation
        )
        
        self._metrics[metric.name] = metric
        
        if is_violation:
            logger.warning(
                f"[DRIFT-METRIC] {metric.name}: {metric.description} - "
                f"exceeds envelope by {violation_pct*100:.2f}%"
            )
        
        return metric
    
    def collect_profile_limit_mismatch(
        self,
        envelope_per_market_contracts: int,
        kalshi_risk_manager_contracts: int,
        epsilon: float = 0.0  # Exact match required
    ) -> DriftMetric:
        """
        Check if KalshiRiskManager cap differs from envelope-derived cap.
        
        Args:
            envelope_per_market_contracts: Per-market cap from envelope
            kalshi_risk_manager_contracts: Per-market cap from KalshiRiskManager
            epsilon: Tolerance for comparison
            
        Returns:
            DriftMetric for profile limit mismatch
        """
        diff = abs(envelope_per_market_contracts - kalshi_risk_manager_contracts)
        is_violation = diff > epsilon
        
        metric = DriftMetric(
            name="profile_limit_mismatch",
            value=diff,
            threshold=epsilon,
            description=f"Envelope per-market cap ({envelope_per_market_contracts}) vs KalshiRiskManager ({kalshi_risk_manager_contracts})",
            is_violation=is_violation
        )
        
        self._metrics[metric.name] = metric
        
        if is_violation:
            logger.warning(
                f"[DRIFT-METRIC] {metric.name}: {metric.description} - "
                f"mismatch of {diff} contracts"
            )
        
        return metric
    
    def collect_data_freshness_violation(
        self,
        health_check_fresh: bool,
        router_fresh: bool,
        market_id: str
    ) -> Optional[DriftMetric]:
        """
        Check if health check says fresh but router says stale (or vice versa).
        
        Args:
            health_check_fresh: True if health check considers market fresh
            router_fresh: True if router considers market fresh
            market_id: Market identifier for logging
            
        Returns:
            DriftMetric if mismatch detected, None otherwise
        """
        if health_check_fresh == router_fresh:
            return None  # No mismatch
        
        is_violation = True  # Any mismatch is a violation
        
        metric = DriftMetric(
            name="data_freshness_violation",
            value=1.0 if is_violation else 0.0,
            threshold=0.0,
            description=f"Market {market_id}: health_check_fresh={health_check_fresh}, router_fresh={router_fresh}",
            is_violation=is_violation
        )
        
        self._metrics[metric.name] = metric
        
        logger.warning(
            f"[DRIFT-METRIC] {metric.name}: {metric.description} - "
            f"freshness mismatch detected"
        )
        
        return metric
    
    def collect_scheduler_catalog_mismatch(
        self,
        scheduler_tradable: bool,
        catalog_tradable: bool,
        market_id: str
    ) -> Optional[DriftMetric]:
        """
        Check if scheduler believes market is tradable but catalog says not.
        
        Args:
            scheduler_tradable: True if scheduler considers market tradable
            catalog_tradable: True if catalog considers market tradable
            market_id: Market identifier for logging
            
        Returns:
            DriftMetric if mismatch detected, None otherwise
        """
        if scheduler_tradable == catalog_tradable:
            return None  # No mismatch
        
        is_violation = True  # Any mismatch is a violation
        
        metric = DriftMetric(
            name="scheduler_vs_catalog_window_mismatch",
            value=1.0 if is_violation else 0.0,
            threshold=0.0,
            description=f"Market {market_id}: scheduler_tradable={scheduler_tradable}, catalog_tradable={catalog_tradable}",
            is_violation=is_violation
        )
        
        self._metrics[metric.name] = metric
        
        logger.warning(
            f"[DRIFT-METRIC] {metric.name}: {metric.description} - "
            f"tradability mismatch detected"
        )
        
        return metric
    
    def get_all_metrics(self) -> Dict[str, DriftMetric]:
        """Get all collected drift metrics."""
        return self._metrics.copy()
    
    def get_violations(self) -> Dict[str, DriftMetric]:
        """Get only metrics that are in violation state."""
        return {k: v for k, v in self._metrics.items() if v.is_violation}
    
    def has_violations(self) -> bool:
        """Check if any metrics are in violation state."""
        return any(m.is_violation for m in self._metrics.values())
    
    def reset(self) -> None:
        """Reset all metrics (for testing or periodic reset)."""
        self._metrics.clear()
        logger.info("[DRIFT-METRICS] All metrics reset")


# Global singleton
_drift_collector: Optional[DriftMetricsCollector] = None


def get_drift_metrics_collector() -> DriftMetricsCollector:
    """Get the global drift metrics collector singleton."""
    global _drift_collector
    if _drift_collector is None:
        _drift_collector = DriftMetricsCollector()
    return _drift_collector
