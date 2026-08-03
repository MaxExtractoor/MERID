"""Spot-strike distance selector for Kalshi markets.

Provides canonical distance computation and configurable acceptance criteria
based on asset, timeframe, volatility, tenor, and equity regime.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# Config-driven maxallowedpct per asset/timeframe
# Format: {asset: {timeframe: max_distance_pct}}
DEFAULT_SPOT_STRIKE_DISTANCE_PCT: Dict[str, Dict[str, float]] = {
    "BTC": {
        "15m": 0.03,
        "1h": 0.05,
        "daily": 0.08,
        "weekly": 0.12,
        "annual": 0.20,
    },
    "ETH": {
        "15m": 0.04,
        "1h": 0.06,
        "daily": 0.10,
        "weekly": 0.15,
        "annual": 0.25,
    },
    "SOL": {
        "15m": 0.05,
        "1h": 0.07,
        "daily": 0.12,
        "weekly": 0.18,
        "annual": 0.28,
    },
    "XRP": {
        "15m": 0.05,
        "1h": 0.07,
        "daily": 0.12,
        "weekly": 0.18,
        "annual": 0.30,
    },
    "DOGE": {
        "15m": 0.06,
        "1h": 0.08,
        "daily": 0.15,
        "weekly": 0.22,
        "annual": 0.35,
    },
}

# Hard caps per asset (absolute maximum regardless of dynamic scaling)
HARD_SPOT_STRIKE_DISTANCE_CAP: Dict[str, float] = {
    "BTC": 0.25,
    "ETH": 0.30,
    "SOL": 0.32,
    "XRP": 0.35,
    "DOGE": 0.40,
}

# Volatility multipliers
VOL_MULTIPLIERS = {
    "low": 0.7,
    "medium": 1.0,
    "high": 1.3,
}

# Tenor (time-to-expiry) multipliers
TENOR_MULTIPLIERS = {
    "<6h": 0.5,
    "6h-2d": 0.75,
    "2-14d": 1.0,
    ">14d": 1.3,
}

# Equity regime multipliers
REGIME_MULTIPLIERS = {
    "DEEP_UNDERWATER": 0.5,
    "UNDERWATER": 0.7,
    "BASELINE": 1.0,
    "LOCK_IN_GAINS": 0.8,
}


@dataclass
class DistanceCheckResult:
    """Result of a spot-strike distance check."""
    accepted: bool
    distance_pct: float
    max_allowed_pct: float
    base_pct: float
    vol_mult: float
    tenor_mult: float
    regime_mult: float
    rejection_reason: Optional[str] = None


class StrikeSelector:
    """Selects Kalshi strikes based on spot-strike distance criteria."""

    def __init__(
        self,
        distance_config: Optional[Dict[str, Dict[str, float]]] = None,
        global_warn_pct: float = 0.85,
    ):
        """Initialize the strike selector.

        Args:
            distance_config: Config for max distance per asset/timeframe
            global_warn_pct: Hard global guard - reject strikes beyond this
        """
        self._distance_config = distance_config or DEFAULT_SPOT_STRIKE_DISTANCE_PCT
        self._global_warn_pct = global_warn_pct

    def compute_distance_pct(self, spot: float, strike: float) -> float:
        """Compute symmetric relative distance between spot and strike.

        Formula: distance_pct = |strike - spot| / spot

        Args:
            spot: Current spot price
            strike: Strike price of the contract

        Returns:
            Distance as a percentage (e.g., 0.10 for 10%)
        """
        if spot <= 0:
            return float("inf")
        return abs(strike - spot) / spot

    def get_max_allowed_pct(
        self,
        asset: str,
        timeframe: str,
        vol_bucket: str = "medium",
        tenor_bucket: str = "2-14d",
        regime: str = "BASELINE",
        dynamic_enabled: bool = False,
    ) -> float:
        """Get max allowed distance percentage with optional dynamic scaling.

        Args:
            asset: Underlying asset (BTC, ETH, SOL, XRP, DOGE)
            timeframe: Timeframe (15m, 1h, daily, weekly, annual)
            vol_bucket: Volatility bucket (low, medium, high)
            tenor_bucket: Time-to-expiry bucket (<6h, 6h-2d, 2-14d, >14d)
            regime: Equity regime (DEEP_UNDERWATER, UNDERWATER, BASELINE, LOCK_IN_GAINS)
            dynamic_enabled: Whether to apply dynamic scaling

        Returns:
            Max allowed distance percentage
        """
        asset_upper = asset.upper()
        timeframe_lower = timeframe.lower()

        # Get base config value
        base_pct = self._distance_config.get(asset_upper, {}).get(
            timeframe_lower, 0.05  # Default 5% for intraday
        )

        if not dynamic_enabled:
            return base_pct

        # Apply dynamic scaling
        vol_mult = VOL_MULTIPLIERS.get(vol_bucket, 1.0)
        tenor_mult = TENOR_MULTIPLIERS.get(tenor_bucket, 1.0)
        regime_mult = REGIME_MULTIPLIERS.get(regime, 1.0)

        dynamic_pct = base_pct * vol_mult * tenor_mult * regime_mult

        # Apply hard cap for this asset
        hard_cap = HARD_SPOT_STRIKE_DISTANCE_CAP.get(asset_upper, 0.30)
        return min(dynamic_pct, hard_cap)

    def check_strike(
        self,
        spot: float,
        strike: float,
        asset: str,
        timeframe: str,
        vol_bucket: str = "medium",
        tenor_bucket: str = "2-14d",
        regime: str = "BASELINE",
        dynamic_enabled: bool = False,
    ) -> DistanceCheckResult:
        """Check if a strike is acceptable based on spot-strike distance.

        Args:
            spot: Current spot price
            strike: Strike price of the contract
            asset: Underlying asset (BTC, ETH, SOL, XRP, DOGE)
            timeframe: Timeframe (15m, 1h, daily, weekly, annual)
            vol_bucket: Volatility bucket (low, medium, high)
            tenor_bucket: Time-to-expiry bucket (<6h, 6h-2d, 2-14d, >14d)
            regime: Equity regime (DEEP_UNDERWATER, UNDERWATER, BASELINE, LOCK_IN_GAINS)
            dynamic_enabled: Whether to apply dynamic scaling

        Returns:
            DistanceCheckResult with acceptance status and details
        """
        distance_pct = self.compute_distance_pct(spot, strike)

        # Hard global guard - reject obviously absurd distances
        if distance_pct > self._global_warn_pct:
            logger.warning(
                "kalshistrikeselector SPOT-OUT-OF-RANGE "
                "asset=%s spot=%.4f strike=%.4f distancepct=%.4f warn=%.4f",
                asset, spot, strike, distance_pct, self._global_warn_pct
            )
            return DistanceCheckResult(
                accepted=False,
                distance_pct=distance_pct,
                max_allowed_pct=self._global_warn_pct,
                base_pct=0.0,
                vol_mult=1.0,
                tenor_mult=1.0,
                regime_mult=1.0,
                rejection_reason="spot_out_of_range",
            )

        # Get max allowed with optional dynamic scaling
        max_allowed_pct = self.get_max_allowed_pct(
            asset, timeframe, vol_bucket, tenor_bucket, regime, dynamic_enabled
        )

        # Compute individual multipliers for logging
        base_pct = self._distance_config.get(asset.upper(), {}).get(timeframe.lower(), 0.05)
        vol_mult = VOL_MULTIPLIERS.get(vol_bucket, 1.0) if dynamic_enabled else 1.0
        tenor_mult = TENOR_MULTIPLIERS.get(tenor_bucket, 1.0) if dynamic_enabled else 1.0
        regime_mult = REGIME_MULTIPLIERS.get(regime, 1.0) if dynamic_enabled else 1.0

        accepted = distance_pct <= max_allowed_pct

        # Log the decision
        logger.info(
            "kalshistrikeselector DISTANCE "
            "asset=%s timeframe=%s spot=%.4f strike=%.4f "
            "distancepct=%.6f base=%.4f volmult=%.2f tenormult=%.2f regimemult=%.2f "
            "maxallowedpct=%.4f accepted=%s",
            asset,
            timeframe,
            spot,
            strike,
            distance_pct,
            base_pct,
            vol_mult,
            tenor_mult,
            regime_mult,
            max_allowed_pct,
            accepted,
        )

        rejection_reason = None
        if not accepted:
            rejection_reason = "exceeds_max_distance"

        return DistanceCheckResult(
            accepted=accepted,
            distance_pct=distance_pct,
            max_allowed_pct=max_allowed_pct,
            base_pct=base_pct,
            vol_mult=vol_mult,
            tenor_mult=tenor_mult,
            regime_mult=regime_mult,
            rejection_reason=rejection_reason,
        )

    def infer_timeframe_from_expiry(
        self, expiry: datetime, now: Optional[datetime] = None
    ) -> str:
        """Infer tenor bucket from expiry time.

        Args:
            expiry: Contract expiry datetime
            now: Current datetime (defaults to UTC now)

        Returns:
            Tenor bucket (<6h, 6h-2d, 2-14d, >14d)
        """
        if now is None:
            now = datetime.now(timezone.utc)

        time_to_expiry = expiry - now
        hours = time_to_expiry.total_seconds() / 3600
        days = hours / 24

        if hours < 6:
            return "<6h"
        elif days < 2:
            return "6h-2d"
        elif days < 14:
            return "2-14d"
        else:
            return ">14d"

    def infer_vol_bucket_from_regime(self, vol_regime: str) -> str:
        """Infer volatility bucket from volatility regime.

        Args:
            vol_regime: Volatility regime string

        Returns:
            Volatility bucket (low, medium, high)
        """
        vol_lower = vol_regime.lower()
        if "low" in vol_lower or "quiet" in vol_lower:
            return "low"
        elif "high" in vol_lower or "breakout" in vol_lower or "elevated" in vol_lower:
            return "high"
        return "medium"


# Singleton instance
_strike_selector: Optional[StrikeSelector] = None


def get_strike_selector() -> StrikeSelector:
    """Get the global StrikeSelector instance."""
    global _strike_selector
    if _strike_selector is None:
        try:
            from merid.settings import settings
            global_warn_pct = getattr(settings, "KALSHI_SPOT_STRIKE_GLOBAL_WARN_PCT", 0.85)
        except Exception:
            global_warn_pct = 0.85
        _strike_selector = StrikeSelector(global_warn_pct=global_warn_pct)
    return _strike_selector


def reset_strike_selector() -> None:
    """Reset the global StrikeSelector instance (for testing)."""
    global _strike_selector
    _strike_selector = None
