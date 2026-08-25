"""
Dynamic FLB Thresholds Based on Market Conditions

This module implements dynamic threshold adjustment for FLB (Favorite-Longshot Bias)
parameters based on real-time market conditions.

Dynamic factors:
- Volatility regime (high volatility = wider FLB zones)
- Liquidity availability (low liquidity = stricter FLB zones)
- Time of day (certain hours have different risk profiles)
- Market regime (trend vs range)
- Recent performance (adaptive thresholds based on recent results)

Based on research from prediction market microstructure and risk management.
"""

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from datetime import datetime, timezone
import math

logger = logging.getLogger("merid.risk.dynamic_flb_thresholds")


@dataclass
class FLBThresholds:
    """Dynamic FLB thresholds."""
    yes_min_safe: int = 10  # Minimum YES price to avoid FLB
    yes_max_safe: int = 85  # Maximum YES price to avoid fee drag
    no_min_safe: int = 25   # Minimum NO price
    no_max_safe: int = 95   # Maximum NO price
    no_edge_min: int = 88   # NO edge band start
    no_edge_max: int = 95   # NO edge band end

    # Position sizing multipliers
    high_risk_multiplier: float = 0.5
    fee_drag_multiplier: float = 0.7
    edge_band_multiplier: float = 1.2
    normal_multiplier: float = 1.0


class DynamicFLBThresholdManager:
    """Manage dynamic FLB thresholds based on market conditions."""

    def __init__(self):
        self.base_thresholds = FLBThresholds()
        self.current_thresholds = FLBThresholds()
        self.last_adjustment_time: Optional[datetime] = None
        self.adjustment_count = 0

    def calculate_dynamic_thresholds(
        self,
        volatility: float,
        liquidity_score: float,
        market_regime: str,
        hour_of_day: int,
        recent_performance: Optional[Dict[str, float]] = None
    ) -> FLBThresholds:
        """Calculate dynamic FLB thresholds based on market conditions.

        Args:
            volatility: Current market volatility (annualized)
            liquidity_score: Liquidity availability score (0-100)
            market_regime: Market regime ("trend", "range", "extreme")
            hour_of_day: Hour of day (0-23)
            recent_performance: Recent performance metrics (optional)

        Returns:
            Dynamic FLB thresholds adjusted for current conditions
        """
        # Start with base thresholds
        thresholds = FLBThresholds()

        # Volatility adjustment: High volatility = wider FLB zones
        vol_multiplier = self._calculate_volatility_multiplier(volatility)
        thresholds.yes_min_safe = max(5, int(self.base_thresholds.yes_min_safe * vol_multiplier))
        thresholds.yes_max_safe = min(90, int(self.base_thresholds.yes_max_safe * (2.0 - vol_multiplier)))
        thresholds.no_min_safe = max(20, int(self.base_thresholds.no_min_safe * vol_multiplier))
        thresholds.no_max_safe = min(98, int(self.base_thresholds.no_max_safe * (2.0 - vol_multiplier)))

        # Liquidity adjustment: Low liquidity = stricter FLB zones
        liq_multiplier = self._calculate_liquidity_multiplier(liquidity_score)
        thresholds.yes_min_safe = max(5, int(thresholds.yes_min_safe * liq_multiplier))
        thresholds.yes_max_safe = min(90, int(thresholds.yes_max_safe / liq_multiplier))
        thresholds.no_min_safe = max(20, int(thresholds.no_min_safe * liq_multiplier))
        thresholds.no_max_safe = min(98, int(thresholds.no_max_safe / liq_multiplier))

        # Time-of-day adjustment: Certain hours have different risk profiles
        tod_multiplier = self._calculate_tod_multiplier(hour_of_day)
        thresholds.high_risk_multiplier = self.base_thresholds.high_risk_multiplier * tod_multiplier
        thresholds.fee_drag_multiplier = self.base_thresholds.fee_drag_multiplier * tod_multiplier
        thresholds.edge_band_multiplier = self.base_thresholds.edge_band_multiplier * tod_multiplier

        # Market regime adjustment
        regime_multiplier = self._calculate_regime_multiplier(market_regime)
        thresholds.normal_multiplier = self.base_thresholds.normal_multiplier * regime_multiplier

        # Performance-based adjustment (if recent performance available)
        if recent_performance:
            perf_multiplier = self._calculate_performance_multiplier(recent_performance)
            thresholds.edge_band_multiplier *= perf_multiplier

        # Update current thresholds
        self.current_thresholds = thresholds
        self.last_adjustment_time = datetime.now(timezone.utc)
        self.adjustment_count += 1

        logger.info(
            "[DYNAMIC-FLB-THRESHOLDS] vol=%.3f liq=%.1f regime=%s hour=%d -> "
            "yes_min=%dc yes_max=%dc no_min=%dc no_max=%dc "
            "mult_risk=%.2f mult_fee=%.2f mult_edge=%.2f mult_norm=%.2f",
            volatility, liquidity_score, market_regime, hour_of_day,
            thresholds.yes_min_safe, thresholds.yes_max_safe,
            thresholds.no_min_safe, thresholds.no_max_safe,
            thresholds.high_risk_multiplier, thresholds.fee_drag_multiplier,
            thresholds.edge_band_multiplier, thresholds.normal_multiplier
        )

        return thresholds

    def _calculate_volatility_multiplier(self, volatility: float) -> float:
        """Calculate volatility adjustment multiplier.

        High volatility = wider FLB zones (more permissive)
        Low volatility = narrower FLB zones (more restrictive)
        """
        # Normalize volatility: 0.15 = low, 1.20 = high (from research)
        vol_normalized = max(0.15, min(1.20, volatility))
        vol_pct = (vol_normalized - 0.15) / (1.20 - 0.15)  # 0.0-1.0

        # High volatility = wider zones (multiplier > 1.0)
        # Low volatility = narrower zones (multiplier < 1.0)
        return 0.8 + (vol_pct * 0.4)  # Range: 0.8-1.2

    def _calculate_liquidity_multiplier(self, liquidity_score: float) -> float:
        """Calculate liquidity adjustment multiplier.

        High liquidity = more permissive FLB zones
        Low liquidity = stricter FLB zones
        """
        # Normalize liquidity: 0 = illiquid, 100 = very liquid
        liq_normalized = max(0.0, min(100.0, liquidity_score))
        liq_pct = liq_normalized / 100.0  # 0.0-1.0

        # High liquidity = more permissive (multiplier < 1.0 for min, > 1.0 for max)
        # Low liquidity = more restrictive (multiplier > 1.0 for min, < 1.0 for max)
        return 1.2 - (liq_pct * 0.4)  # Range: 0.8-1.2

    def _calculate_tod_multiplier(self, hour_of_day: int) -> float:
        """Calculate time-of-day adjustment multiplier.

        Certain hours have different risk profiles based on market activity.
        """
        # Risk profile by hour (UTC):
        # 0-6: Low activity (Asian session) - more conservative
        # 6-12: Medium activity (European session) - moderate
        # 12-18: High activity (US session overlap) - more aggressive
        # 18-24: Medium activity (US session) - moderate

        if 0 <= hour_of_day < 6:
            # Asian session - more conservative
            return 0.8
        elif 6 <= hour_of_day < 12:
            # European session - moderate
            return 0.9
        elif 12 <= hour_of_day < 18:
            # US session overlap - more aggressive
            return 1.1
        else:  # 18-24
            # US session - moderate
            return 1.0

    def _calculate_regime_multiplier(self, market_regime: str) -> float:
        """Calculate market regime adjustment multiplier.

        Different regimes have different risk profiles.
        """
        if market_regime == "extreme":
            # Extreme regime - more conservative position sizing
            return 0.8
        elif market_regime == "trend":
            # Trend regime - more aggressive
            return 1.1
        else:  # range or neutral
            # Range regime - normal
            return 1.0

    def _calculate_performance_multiplier(self, recent_performance: Dict[str, float]) -> float:
        """Calculate performance-based adjustment multiplier.

        Adjust edge band multiplier based on recent FLB edge band performance.
        """
        # Get recent edge band performance
        edge_band_roi = recent_performance.get("edge_band_roi", 0.0)
        edge_band_win_rate = recent_performance.get("edge_band_win_rate", 0.5)

        # If edge band is performing well, increase multiplier
        # If edge band is performing poorly, decrease multiplier
        if edge_band_roi > 0.05 and edge_band_win_rate > 0.6:
            return 1.3  # Boost multiplier for good performance
        elif edge_band_roi < 0.0 or edge_band_win_rate < 0.4:
            return 0.9  # Reduce multiplier for poor performance
        else:
            return 1.0  # Normal multiplier

    def get_current_thresholds(self) -> FLBThresholds:
        """Get current dynamic thresholds."""
        return self.current_thresholds

    def should_recalculate(self, minutes_since_last: int = 15) -> bool:
        """Check if thresholds should be recalculated.

        Args:
            minutes_since_last: Minutes since last recalculation

        Returns:
            True if thresholds should be recalculated
        """
        if self.last_adjustment_time is None:
            return True

        time_since = (datetime.now(timezone.utc) - self.last_adjustment_time).total_seconds() / 60
        return time_since >= minutes_since_last


# Global dynamic FLB threshold manager instance
_dynamic_flb_manager: Optional[DynamicFLBThresholdManager] = None


def get_dynamic_flb_manager() -> DynamicFLBThresholdManager:
    """Get the global dynamic FLB threshold manager instance."""
    global _dynamic_flb_manager
    if _dynamic_flb_manager is None:
        _dynamic_flb_manager = DynamicFLBThresholdManager()
    return _dynamic_flb_manager


def calculate_dynamic_flb_thresholds(
    volatility: float,
    liquidity_score: float,
    market_regime: str,
    hour_of_day: int,
    recent_performance: Optional[Dict[str, float]] = None
) -> FLBThresholds:
    """Calculate dynamic FLB thresholds (convenience function)."""
    manager = get_dynamic_flb_manager()
    return manager.calculate_dynamic_thresholds(
        volatility, liquidity_score, market_regime, hour_of_day, recent_performance
    )


def get_current_flb_thresholds() -> FLBThresholds:
    """Get current dynamic FLB thresholds (convenience function)."""
    manager = get_dynamic_flb_manager()
    return manager.get_current_thresholds()
