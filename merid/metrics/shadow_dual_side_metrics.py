"""
Shadow Dual-Side Metrics Module

Tracks and analyzes missed opportunities from expected_side gating in the 15m Kalshi
crypto trading system. This module quantifies the structural bias introduced by
single-side evaluation based on velocity prior.

Metrics tracked:
- Missed edge distribution (how much edge is lost to gating)
- Frequency of wrong-side lockout (when opposite side has better edge)
- Hypothetical PnL delta if unconstrained
- Per-asset and per-regime breakdowns
- Velocity strength vs missed opportunity correlation

Usage:
    from merid.metrics.shadow_dual_side_metrics import get_shadow_dual_side_monitor
    
    monitor = get_shadow_dual_side_monitor()
    monitor.log_shadow_evaluation(
        asset="BTC",
        velocity=0.01,
        strategy_mode="trend_following",
        expected_side="yes",
        expected_edge=0.08,
        opposite_side="no",
        opposite_edge=0.12,
        hypothetical_best_side="no",
        hypothetical_best_edge=0.12,
        yes_in_range=True,
        no_in_range=True
    )
    
    # Get analysis
    analysis = monitor.get_analysis()
    print(f"Missed opportunity rate: {analysis['missed_opportunity_rate']:.2%}")
    print(f"Average missed edge: {analysis['avg_missed_edge']:.4f}")
"""

import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta


@dataclass
class ShadowEvaluationRecord:
    """Record of a shadow dual-side evaluation."""
    timestamp: float
    asset: str
    velocity: float
    strategy_mode: str
    expected_side: str
    expected_edge: float
    opposite_side: str
    opposite_edge: float
    hypothetical_best_side: str
    hypothetical_best_edge: float
    yes_in_range: bool
    no_in_range: bool
    chosen_side: Optional[str] = None  # Will be set after actual selection


@dataclass
class ShadowAnalysis:
    """Analysis results from shadow dual-side metrics."""
    total_evaluations: int
    missed_opportunities: int
    missed_opportunity_rate: float
    avg_missed_edge: float
    max_missed_edge: float
    total_missed_edge: float
    per_asset_breakdown: Dict[str, Dict]
    per_regime_breakdown: Dict[str, Dict]
    velocity_correlation: Dict[str, float]
    time_window: Tuple[datetime, datetime]


class ShadowDualSideMonitor:
    """
    Singleton monitor for shadow dual-side evaluation metrics.
    
    Tracks the opportunity cost of expected_side gating by logging both
    the expected side's edge and the opposite side's edge on every evaluation.
    This allows quantification of how much edge is being left on the table
    due to single-side evaluation.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._records: List[ShadowEvaluationRecord] = []
        self._max_records = 100000  # Keep last 100k records to manage memory
        self._lock = threading.Lock()
        self._initialized = True
        
        # Per-asset metrics
        self._asset_metrics: Dict[str, Dict] = defaultdict(lambda: {
            "total_evaluations": 0,
            "missed_opportunities": 0,
            "total_missed_edge": 0.0,
            "max_missed_edge": 0.0
        })
        
        # Per-regime metrics (based on velocity strength)
        self._regime_metrics: Dict[str, Dict] = defaultdict(lambda: {
            "total_evaluations": 0,
            "missed_opportunities": 0,
            "total_missed_edge": 0.0,
            "max_missed_edge": 0.0
        })
    
    def log_shadow_evaluation(
        self,
        asset: str,
        velocity: float,
        strategy_mode: str,
        expected_side: str,
        expected_edge: float,
        opposite_side: str,
        opposite_edge: float,
        hypothetical_best_side: str,
        hypothetical_best_edge: float,
        yes_in_range: bool,
        no_in_range: bool,
        chosen_side: Optional[str] = None
    ) -> None:
        """
        Log a shadow dual-side evaluation.
        
        Args:
            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
            velocity: Velocity value
            strategy_mode: Strategy mode (trend_following, mean_reversion)
            expected_side: Expected side from velocity
            expected_edge: Edge of expected side
            opposite_side: Opposite side
            opposite_edge: Edge of opposite side
            hypothetical_best_side: Best side if unconstrained
            hypothetical_best_edge: Best edge if unconstrained
            yes_in_range: Whether YES price is in 10-75c range
            no_in_range: Whether NO price is in 10-75c range
            chosen_side: Actually chosen side (if known)
        """
        record = ShadowEvaluationRecord(
            timestamp=time.time(),
            asset=asset,
            velocity=velocity,
            strategy_mode=strategy_mode,
            expected_side=expected_side,
            expected_edge=expected_edge,
            opposite_side=opposite_side,
            opposite_edge=opposite_edge,
            hypothetical_best_side=hypothetical_best_side,
            hypothetical_best_edge=hypothetical_best_edge,
            yes_in_range=yes_in_range,
            no_in_range=no_in_range,
            chosen_side=chosen_side
        )
        
        with self._lock:
            self._records.append(record)
            
            # Trim records if exceeding max
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
            
            # Update per-asset metrics
            self._update_asset_metrics(record)
            
            # Update per-regime metrics
            self._update_regime_metrics(record)
    
    def _update_asset_metrics(self, record: ShadowEvaluationRecord) -> None:
        """Update per-asset metrics from a record."""
        asset = record.asset
        metrics = self._asset_metrics[asset]
        
        metrics["total_evaluations"] += 1
        
        # Check if this was a missed opportunity
        if record.hypothetical_best_side != record.expected_side:
            metrics["missed_opportunities"] += 1
            missed_edge = record.hypothetical_best_edge - record.expected_edge
            metrics["total_missed_edge"] += missed_edge
            metrics["max_missed_edge"] = max(metrics["max_missed_edge"], missed_edge)
    
    def _update_regime_metrics(self, record: ShadowEvaluationRecord) -> None:
        """Update per-regime metrics from a record."""
        # Classify regime based on velocity strength
        velocity_abs = abs(record.velocity)
        if velocity_abs < 0.005:
            regime = "low_velocity"
        elif velocity_abs < 0.015:
            regime = "medium_velocity"
        else:
            regime = "high_velocity"
        
        metrics = self._regime_metrics[regime]
        
        metrics["total_evaluations"] += 1
        
        # Check if this was a missed opportunity
        if record.hypothetical_best_side != record.expected_side:
            metrics["missed_opportunities"] += 1
            missed_edge = record.hypothetical_best_edge - record.expected_edge
            metrics["total_missed_edge"] += missed_edge
            metrics["max_missed_edge"] = max(metrics["max_missed_edge"], missed_edge)
    
    def get_analysis(
        self,
        time_window_hours: Optional[float] = None
    ) -> ShadowAnalysis:
        """
        Get analysis of shadow dual-side metrics.
        
        Args:
            time_window_hours: If specified, only analyze records within this time window
        
        Returns:
            ShadowAnalysis with comprehensive metrics
        """
        with self._lock:
            # Filter by time window if specified
            if time_window_hours:
                cutoff_time = time.time() - (time_window_hours * 3600)
                records = [r for r in self._records if r.timestamp >= cutoff_time]
            else:
                records = self._records
            
            if not records:
                return ShadowAnalysis(
                    total_evaluations=0,
                    missed_opportunities=0,
                    missed_opportunity_rate=0.0,
                    avg_missed_edge=0.0,
                    max_missed_edge=0.0,
                    total_missed_edge=0.0,
                    per_asset_breakdown={},
                    per_regime_breakdown={},
                    velocity_correlation={},
                    time_window=(datetime.min, datetime.max)
                )
            
            # Calculate overall metrics
            total_evaluations = len(records)
            missed_opportunities = sum(
                1 for r in records
                if r.hypothetical_best_side != r.expected_side
            )
            missed_opportunity_rate = missed_opportunities / total_evaluations if total_evaluations > 0 else 0.0
            
            missed_edges = [
                r.hypothetical_best_edge - r.expected_edge
                for r in records
                if r.hypothetical_best_side != r.expected_side
            ]
            
            avg_missed_edge = sum(missed_edges) / len(missed_edges) if missed_edges else 0.0
            max_missed_edge = max(missed_edges) if missed_edges else 0.0
            total_missed_edge = sum(missed_edges)
            
            # Calculate velocity correlation
            velocity_correlation = self._calculate_velocity_correlation(records)
            
            # Time window
            timestamps = [r.timestamp for r in records]
            time_window_dt = (
                datetime.fromtimestamp(min(timestamps)),
                datetime.fromtimestamp(max(timestamps))
            )
            
            return ShadowAnalysis(
                total_evaluations=total_evaluations,
                missed_opportunities=missed_opportunities,
                missed_opportunity_rate=missed_opportunity_rate,
                avg_missed_edge=avg_missed_edge,
                max_missed_edge=max_missed_edge,
                total_missed_edge=total_missed_edge,
                per_asset_breakdown=dict(self._asset_metrics),
                per_regime_breakdown=dict(self._regime_metrics),
                velocity_correlation=velocity_correlation,
                time_window=time_window_dt
            )
    
    def _calculate_velocity_correlation(self, records: List[ShadowEvaluationRecord]) -> Dict[str, float]:
        """Calculate correlation between velocity strength and missed opportunity rate."""
        # Group by velocity strength
        low_vel = [r for r in records if abs(r.velocity) < 0.005]
        med_vel = [r for r in records if 0.005 <= abs(r.velocity) < 0.015]
        high_vel = [r for r in records if abs(r.velocity) >= 0.015]
        
        def calc_missed_rate(recs):
            if not recs:
                return 0.0
            missed = sum(1 for r in recs if r.hypothetical_best_side != r.expected_side)
            return missed / len(recs)
        
        return {
            "low_velocity_missed_rate": calc_missed_rate(low_vel),
            "medium_velocity_missed_rate": calc_missed_rate(med_vel),
            "high_velocity_missed_rate": calc_missed_rate(high_vel),
            "low_velocity_count": len(low_vel),
            "medium_velocity_count": len(med_vel),
            "high_velocity_count": len(high_vel)
        }
    
    def get_missed_edge_distribution(self, bins: int = 20) -> List[Tuple[float, float, int]]:
        """
        Get distribution of missed edge magnitudes.
        
        Args:
            bins: Number of bins for histogram
        
        Returns:
            List of (bin_start, bin_end, count) tuples
        """
        with self._lock:
            missed_edges = [
                r.hypothetical_best_edge - r.expected_edge
                for r in self._records
                if r.hypothetical_best_side != r.expected_side
            ]
        
        if not missed_edges:
            return []
        
        max_edge = max(missed_edges)
        min_edge = min(missed_edges)
        bin_width = (max_edge - min_edge) / bins
        
        distribution = []
        for i in range(bins):
            bin_start = min_edge + i * bin_width
            bin_end = bin_start + bin_width
            count = sum(1 for e in missed_edges if bin_start <= e < bin_end)
            distribution.append((bin_start, bin_end, count))
        
        return distribution
    
    def reset(self) -> None:
        """Reset all metrics (useful for testing or fresh start)."""
        with self._lock:
            self._records.clear()
            self._asset_metrics.clear()
            self._regime_metrics.clear()


def get_shadow_dual_side_monitor() -> ShadowDualSideMonitor:
    """Get the singleton ShadowDualSideMonitor instance."""
    return ShadowDualSideMonitor()
