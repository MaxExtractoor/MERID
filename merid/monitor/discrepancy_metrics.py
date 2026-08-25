"""
Discrepancy Metrics for Production Observability

This module provides metrics collection and aggregation for order discrepancy
events, enabling production monitoring and alerting on exposure, liquidity role,
and fee mismatches.

CRITICAL FIX (2026-07-19): Tracks discrepancy types as first-class metrics for
the maker/taker contract, providing visibility into contract violations in live
trading.

Metrics:
- Counters: exposure_mismatch_count, liquidity_role_mismatch_count, fee_mismatch_count
- Ratios: mismatches per 1,000 orders per asset
- Thresholds: Alert when mismatches exceed production limits
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional, List
from collections import defaultdict
import threading

from utils.logger import get_logger

logger = get_logger("merid.monitor.discrepancy_metrics")


class DiscrepancyType(str, Enum):
    """Types of discrepancy events."""
    EXPOSURE_MISMATCH = "exposure_mismatch"
    LIQUIDITY_ROLE_MISMATCH = "liquidity_role_mismatch"
    FEE_MISMATCH = "fee_mismatch"
    ORDER_CONTRACT_VIOLATION = "order_contract_violation"  # Co-occurring exposure + liquidity


@dataclass
class DiscrepancyMetric:
    """Single metric data point."""
    
    discrepancy_type: DiscrepancyType
    asset: str
    timestamp: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    severity: str = ""
    order_count: int = 0  # Total orders in this window for ratio calculation
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "discrepancy_type": self.discrepancy_type.value,
            "asset": self.asset,
            "timestamp": self.timestamp,
            "severity": self.severity,
            "order_count": self.order_count,
        }


@dataclass
class DiscrepancyWindowStats:
    """Aggregated statistics for a time window."""
    
    window_start: float
    window_end: float
    asset: str
    
    # Counters
    exposure_mismatch_count: int = 0
    liquidity_role_mismatch_count: int = 0
    fee_mismatch_count: int = 0
    order_contract_violation_count: int = 0
    
    # Total orders for ratio calculation
    total_orders: int = 0
    
    # Severity breakdown
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "asset": self.asset,
            "exposure_mismatch_count": self.exposure_mismatch_count,
            "liquidity_role_mismatch_count": self.liquidity_role_mismatch_count,
            "fee_mismatch_count": self.fee_mismatch_count,
            "order_contract_violation_count": self.order_contract_violation_count,
            "total_orders": self.total_orders,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "medium_count": self.medium_count,
            "low_count": self.low_count,
            # Ratios (per 1,000 orders)
            "exposure_mismatch_per_1k": self._per_1k(self.exposure_mismatch_count),
            "liquidity_role_mismatch_per_1k": self._per_1k(self.liquidity_role_mismatch_count),
            "fee_mismatch_per_1k": self._per_1k(self.fee_mismatch_count),
            "order_contract_violation_per_1k": self._per_1k(self.order_contract_violation_count),
        }
    
    def _per_1k(self, count: int) -> float:
        """Calculate ratio per 1,000 orders."""
        if self.total_orders == 0:
            return 0.0
        return (count / self.total_orders) * 1000.0


class DiscrepancyMetricsCollector:
    """Collects and aggregates discrepancy metrics for production observability.
    
    This is a thread-safe singleton that tracks discrepancy events across all
    assets and provides aggregated statistics for monitoring and alerting.
    """
    
    _instance: Optional[DiscrepancyMetricsCollector] = None
    _lock: threading.Lock = threading.Lock()
    
    def __new__(cls) -> DiscrepancyMetricsCollector:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self._lock = threading.Lock()
        
        # Per-asset counters
        self._asset_counters: Dict[str, Dict[DiscrepancyType, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        
        # Per-asset order counts (for ratio calculation)
        self._asset_order_counts: Dict[str, int] = defaultdict(int)
        
        # Per-asset severity counters
        self._asset_severity: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        
        # Historical metrics (last N events per asset)
        self._history: Dict[str, List[DiscrepancyMetric]] = defaultdict(list)
        self._max_history_per_asset = 1000
        
        # Window-based statistics (15-minute windows)
        self._window_stats: Dict[str, List[DiscrepancyWindowStats]] = defaultdict(list)
        self._max_windows_per_asset = 100
        
        # Alert thresholds
        self._alert_thresholds = {
            "critical_per_window": 1,  # Alert on any critical mismatch in 15m window
            "high_per_window": 5,  # Alert on 5+ high mismatches in 15m window
            "medium_per_window": 10,  # Alert on 10+ medium mismatches in 15m window
            "mismatch_ratio_per_1k": 5.0,  # Alert if >5 mismatches per 1,000 orders
        }
        
        logger.info("[DISCREPANCY-METRICS] Initialized metrics collector")
    
    def record_discrepancy(
        self,
        discrepancy_type: DiscrepancyType,
        asset: str,
        severity: str,
        order_count: int = 0,
    ) -> None:
        """Record a discrepancy event.
        
        Args:
            discrepancy_type: Type of discrepancy
            asset: Asset symbol
            severity: Severity level (critical, high, medium, low)
            order_count: Total orders in this window (for ratio calculation)
        """
        with self._lock:
            # Update counters
            self._asset_counters[asset][discrepancy_type] += 1
            self._asset_severity[asset][severity] += 1
            self._asset_order_counts[asset] += order_count
            
            # Add to history
            metric = DiscrepancyMetric(
                discrepancy_type=discrepancy_type,
                asset=asset,
                severity=severity,
                order_count=order_count,
            )
            self._history[asset].append(metric)
            
            # Trim history
            if len(self._history[asset]) > self._max_history_per_asset:
                self._history[asset].pop(0)
            
            # Check alert thresholds
            self._check_alerts(asset, discrepancy_type, severity)
            
            logger.debug(
                f"[DISCREPANCY-METRICS] Recorded: {discrepancy_type.value} | "
                f"asset={asset} | severity={severity}"
            )
    
    def _check_alerts(
        self,
        asset: str,
        discrepancy_type: DiscrepancyType,
        severity: str,
    ) -> None:
        """Check if discrepancy triggers alert thresholds."""
        # Critical severity always alerts
        if severity == "critical":
            logger.error(
                f"[DISCREPANCY-ALERT] CRITICAL mismatch detected | "
                f"asset={asset} | type={discrepancy_type.value} | "
                f"severity={severity}"
            )
            return
        
        # Check high severity threshold
        if severity == "high":
            high_count = self._asset_severity[asset]["high"]
            if high_count >= self._alert_thresholds["high_per_window"]:
                logger.warning(
                    f"[DISCREPANCY-ALERT] High severity threshold exceeded | "
                    f"asset={asset} | count={high_count} | threshold={self._alert_thresholds['high_per_window']}"
                )
        
        # Check medium severity threshold
        if severity == "medium":
            medium_count = self._asset_severity[asset]["medium"]
            if medium_count >= self._alert_thresholds["medium_per_window"]:
                logger.warning(
                    f"[DISCREPANCY-ALERT] Medium severity threshold exceeded | "
                    f"asset={asset} | count={medium_count} | threshold={self._alert_thresholds['medium_per_window']}"
                )
    
    def get_asset_stats(self, asset: str) -> Dict:
        """Get current statistics for a specific asset.
        
        Args:
            asset: Asset symbol
            
        Returns:
            Dictionary with current counters and ratios
        """
        with self._lock:
            total_orders = self._asset_order_counts[asset]
            counters = self._asset_counters[asset]
            severity = self._asset_severity[asset]
            
            return {
                "asset": asset,
                "total_orders": total_orders,
                "exposure_mismatch_count": counters[DiscrepancyType.EXPOSURE_MISMATCH],
                "liquidity_role_mismatch_count": counters[DiscrepancyType.LIQUIDITY_ROLE_MISMATCH],
                "fee_mismatch_count": counters[DiscrepancyType.FEE_MISMATCH],
                "order_contract_violation_count": counters[DiscrepancyType.ORDER_CONTRACT_VIOLATION],
                "critical_count": severity["critical"],
                "high_count": severity["high"],
                "medium_count": severity["medium"],
                "low_count": severity["low"],
                # Ratios (per 1,000 orders)
                "exposure_mismatch_per_1k": self._per_1k(counters[DiscrepancyType.EXPOSURE_MISMATCH], total_orders),
                "liquidity_role_mismatch_per_1k": self._per_1k(counters[DiscrepancyType.LIQUIDITY_ROLE_MISMATCH], total_orders),
                "fee_mismatch_per_1k": self._per_1k(counters[DiscrepancyType.FEE_MISMATCH], total_orders),
                "order_contract_violation_per_1k": self._per_1k(counters[DiscrepancyType.ORDER_CONTRACT_VIOLATION], total_orders),
            }
    
    def get_all_stats(self) -> Dict[str, Dict]:
        """Get statistics for all assets.
        
        Returns:
            Dictionary mapping asset symbols to their statistics
        """
        with self._lock:
            return {
                asset: self.get_asset_stats(asset)
                for asset in self._asset_counters.keys()
            }
    
    def _per_1k(self, count: int, total: int) -> float:
        """Calculate ratio per 1,000 orders."""
        if total == 0:
            return 0.0
        return (count / total) * 1000.0
    
    def reset_asset(self, asset: str) -> None:
        """Reset counters for a specific asset.
        
        Args:
            asset: Asset symbol
        """
        with self._lock:
            self._asset_counters[asset].clear()
            self._asset_severity[asset].clear()
            self._asset_order_counts[asset] = 0
            self._history[asset].clear()
            
            logger.info(f"[DISCREPANCY-METRICS] Reset metrics for asset={asset}")
    
    def reset_all(self) -> None:
        """Reset all counters and history."""
        with self._lock:
            self._asset_counters.clear()
            self._asset_severity.clear()
            self._asset_order_counts.clear()
            self._history.clear()
            self._window_stats.clear()
            
            logger.info("[DISCREPANCY-METRICS] Reset all metrics")
    
    def set_alert_threshold(self, key: str, value: int) -> None:
        """Update an alert threshold.
        
        Args:
            key: Threshold key (e.g., "critical_per_window", "high_per_window")
            value: New threshold value
        """
        with self._lock:
            if key in self._alert_thresholds:
                self._alert_thresholds[key] = value
                logger.info(f"[DISCREPANCY-METRICS] Updated threshold: {key}={value}")
            else:
                logger.warning(f"[DISCREPANCY-METRICS] Unknown threshold key: {key}")


def get_discrepancy_metrics_collector() -> DiscrepancyMetricsCollector:
    """Get the singleton discrepancy metrics collector instance."""
    return DiscrepancyMetricsCollector()
