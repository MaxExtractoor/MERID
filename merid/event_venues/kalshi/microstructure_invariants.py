"""
Per-Asset Microstructure Invariants

Defines asset-specific microstructure thresholds and validation invariants.
Different assets (BTC, ETH, SOL, XRP, DOGE) have different liquidity profiles,
so they should have different spread, depth, and volatility thresholds.
"""
from dataclasses import dataclass
from typing import Dict, Optional
from enum import Enum

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.microstructure_invariants")


class AssetClass(Enum):
    """Asset liquidity classification."""
    HIGH_LIQUIDITY = "high_liquidity"  # BTC, ETH
    MEDIUM_LIQUIDITY = "medium_liquidity"  # SOL
    LOW_LIQUIDITY = "low_liquidity"  # XRP, DOGE


@dataclass
class MicrostructureThresholds:
    """Microstructure thresholds for a specific asset."""
    asset: str
    asset_class: AssetClass
    
    # Spread thresholds (cents)
    max_spread_tight: int  # Maximum spread for "tight" regime
    max_spread_normal: int  # Maximum spread for "normal" regime
    max_spread_wide: int  # Maximum spread for "wide" regime (block trading)
    
    # Depth thresholds (contracts at best price)
    min_depth_yes: int  # Minimum YES depth at best bid/ask
    min_depth_no: int  # Minimum NO depth at best bid/ask
    
    # Volatility thresholds
    max_realized_vol_15m: float  # Maximum 15m realized volatility (decimal)
    max_price_range_15m: float  # Maximum 15m price range percentage
    
    # Time to expiry adjustments
    min_tte_for_entry_min: float  # Minimum TTE for entry (minutes)
    min_tte_for_entry_normal: float  # Normal TTE for entry (minutes)
    
    # Slippage tolerance
    max_slippage_cents: int  # Maximum acceptable slippage in cents


# Per-asset threshold definitions
ASSET_THRESHOLDS: Dict[str, MicrostructureThresholds] = {
    "BTC": MicrostructureThresholds(
        asset="BTC",
        asset_class=AssetClass.HIGH_LIQUIDITY,
        max_spread_tight=2,
        max_spread_normal=5,
        max_spread_wide=10,
        min_depth_yes=30,  # From kalshi_crypto_15m.yaml (single source of truth)
        min_depth_no=30,  # From kalshi_crypto_15m.yaml (single source of truth)
        max_realized_vol_15m=0.08,  # 8%
        max_price_range_15m=0.05,  # 5%
        min_tte_for_entry_min=1.5,
        min_tte_for_entry_normal=2.5,
        max_slippage_cents=3,
    ),
    "ETH": MicrostructureThresholds(
        asset="ETH",
        asset_class=AssetClass.HIGH_LIQUIDITY,
        max_spread_tight=2,
        max_spread_normal=5,
        max_spread_wide=10,
        min_depth_yes=30,  # From kalshi_crypto_15m.yaml (single source of truth)
        min_depth_no=30,  # From kalshi_crypto_15m.yaml (single source of truth)
        max_realized_vol_15m=0.10,  # 10%
        max_price_range_15m=0.06,  # 6%
        min_tte_for_entry_min=1.5,
        min_tte_for_entry_normal=2.5,
        max_slippage_cents=3,
    ),
    "SOL": MicrostructureThresholds(
        asset="SOL",
        asset_class=AssetClass.MEDIUM_LIQUIDITY,
        max_spread_tight=3,
        max_spread_normal=8,
        max_spread_wide=15,
        min_depth_yes=20,  # From kalshi_crypto_15m.yaml (single source of truth)
        min_depth_no=20,  # From kalshi_crypto_15m.yaml (single source of truth)
        max_realized_vol_15m=0.12,  # 12%
        max_price_range_15m=0.08,  # 8%
        min_tte_for_entry_min=2.0,
        min_tte_for_entry_normal=3.0,
        max_slippage_cents=4,
    ),
    "XRP": MicrostructureThresholds(
        asset="XRP",
        asset_class=AssetClass.LOW_LIQUIDITY,
        max_spread_tight=4,
        max_spread_normal=10,
        max_spread_wide=20,
        min_depth_yes=10,  # From kalshi_crypto_15m.yaml (single source of truth)
        min_depth_no=10,  # From kalshi_crypto_15m.yaml (single source of truth)
        max_realized_vol_15m=0.15,  # 15%
        max_price_range_15m=0.10,  # 10%
        min_tte_for_entry_min=2.5,
        min_tte_for_entry_normal=3.5,
        max_slippage_cents=5,
    ),
    "DOGE": MicrostructureThresholds(
        asset="DOGE",
        asset_class=AssetClass.LOW_LIQUIDITY,
        max_spread_tight=4,
        max_spread_normal=10,
        max_spread_wide=20,
        min_depth_yes=5,  # From kalshi_crypto_15m.yaml (single source of truth)
        min_depth_no=5,  # From kalshi_crypto_15m.yaml (single source of truth)
        max_realized_vol_15m=0.15,  # 15%
        max_price_range_15m=0.10,  # 10%
        min_tte_for_entry_min=2.5,
        min_tte_for_entry_normal=3.5,
        max_slippage_cents=5,
    ),
}


@dataclass
class InvariantViolation:
    """Result of an invariant check."""
    violated: bool
    asset: str
    invariant_name: str
    actual_value: float
    threshold_value: float
    severity: str  # "warning", "error", "critical"
    message: str


class MicrostructureInvariantChecker:
    """Checker for per-asset microstructure invariants."""
    
    def __init__(self):
        self.thresholds = ASSET_THRESHOLDS
    
    def get_thresholds(self, asset: str) -> Optional[MicrostructureThresholds]:
        """Get thresholds for a specific asset."""
        return self.thresholds.get(asset.upper())
    
    def check_spread_invariant(
        self,
        asset: str,
        spread_cents: int,
        regime: str = "normal",
    ) -> InvariantViolation:
        """Check if spread is within asset-specific threshold.
        
        Args:
            asset: Asset symbol
            spread_cents: Current spread in cents
            regime: Trading regime ("tight", "normal", "wide")
        
        Returns:
            InvariantViolation result
        """
        thresholds = self.get_thresholds(asset)
        if not thresholds:
            return InvariantViolation(
                violated=False,
                asset=asset,
                invariant_name="spread",
                actual_value=spread_cents,
                threshold_value=0,
                severity="info",
                message=f"No thresholds defined for asset {asset}",
            )
        
        # Get appropriate threshold based on regime
        if regime == "tight":
            max_spread = thresholds.max_spread_tight
        elif regime == "wide":
            max_spread = thresholds.max_spread_wide
        else:
            max_spread = thresholds.max_spread_normal
        
        if spread_cents > max_spread:
            severity = "critical" if spread_cents > max_spread * 2 else "error"
            return InvariantViolation(
                violated=True,
                asset=asset,
                invariant_name="spread",
                actual_value=spread_cents,
                threshold_value=max_spread,
                severity=severity,
                message=f"Spread {spread_cents}c exceeds {regime} threshold {max_spread}c for {asset}",
            )
        
        return InvariantViolation(
            violated=False,
            asset=asset,
            invariant_name="spread",
            actual_value=spread_cents,
            threshold_value=max_spread,
            severity="info",
            message=f"Spread {spread_cents}c within {regime} threshold {max_spread}c for {asset}",
        )
    
    def check_depth_invariant(
        self,
        asset: str,
        depth_yes: int,
        depth_no: int,
    ) -> InvariantViolation:
        """Check if depth meets asset-specific minimums.
        
        Args:
            asset: Asset symbol
            depth_yes: YES depth at best price
            depth_no: NO depth at best price
        
        Returns:
            InvariantViolation result
        """
        thresholds = self.get_thresholds(asset)
        if not thresholds:
            return InvariantViolation(
                violated=False,
                asset=asset,
                invariant_name="depth",
                actual_value=min(depth_yes, depth_no),
                threshold_value=0,
                severity="info",
                message=f"No thresholds defined for asset {asset}",
            )
        
        # Check both YES and NO depth
        if depth_yes < thresholds.min_depth_yes or depth_no < thresholds.min_depth_no:
            severity = "error"
            return InvariantViolation(
                violated=True,
                asset=asset,
                invariant_name="depth",
                actual_value=min(depth_yes, depth_no),
                threshold_value=min(thresholds.min_depth_yes, thresholds.min_depth_no),
                severity=severity,
                message=f"Depth YES={depth_yes} NO={depth_no} below minimums YES={thresholds.min_depth_yes} NO={thresholds.min_depth_no} for {asset}",
            )
        
        return InvariantViolation(
            violated=False,
            asset=asset,
            invariant_name="depth",
            actual_value=min(depth_yes, depth_no),
            threshold_value=min(thresholds.min_depth_yes, thresholds.min_depth_no),
            severity="info",
            message=f"Depth YES={depth_yes} NO={depth_no} meets minimums for {asset}",
        )
    
    def check_volatility_invariant(
        self,
        asset: str,
        realized_vol_15m: float,
        price_range_15m: float,
    ) -> InvariantViolation:
        """Check if volatility is within asset-specific thresholds.
        
        Args:
            asset: Asset symbol
            realized_vol_15m: 15m realized volatility (decimal)
            price_range_15m: 15m price range percentage (decimal)
        
        Returns:
            InvariantViolation result
        """
        thresholds = self.get_thresholds(asset)
        if not thresholds:
            return InvariantViolation(
                violated=False,
                asset=asset,
                invariant_name="volatility",
                actual_value=realized_vol_15m,
                threshold_value=0,
                severity="info",
                message=f"No thresholds defined for asset {asset}",
            )
        
        violations = []
        if realized_vol_15m > thresholds.max_realized_vol_15m:
            violations.append(f"realized_vol {realized_vol_15m:.2%} > {thresholds.max_realized_vol_15m:.2%}")
        
        if price_range_15m > thresholds.max_price_range_15m:
            violations.append(f"price_range {price_range_15m:.2%} > {thresholds.max_price_range_15m:.2%}")
        
        if violations:
            severity = "critical" if len(violations) == 2 else "error"
            return InvariantViolation(
                violated=True,
                asset=asset,
                invariant_name="volatility",
                actual_value=max(realized_vol_15m, price_range_15m),
                threshold_value=max(thresholds.max_realized_vol_15m, thresholds.max_price_range_15m),
                severity=severity,
                message=f"Volatility violations for {asset}: {', '.join(violations)}",
            )
        
        return InvariantViolation(
            violated=False,
            asset=asset,
            invariant_name="volatility",
            actual_value=max(realized_vol_15m, price_range_15m),
            threshold_value=max(thresholds.max_realized_vol_15m, thresholds.max_price_range_15m),
            severity="info",
            message=f"Volatility within thresholds for {asset}",
        )
    
    def check_all_invariants(
        self,
        asset: str,
        spread_cents: int,
        depth_yes: int,
        depth_no: int,
        realized_vol_15m: float = 0.0,
        price_range_15m: float = 0.0,
        regime: str = "normal",
    ) -> list[InvariantViolation]:
        """Check all microstructure invariants for an asset.
        
        Args:
            asset: Asset symbol
            spread_cents: Current spread in cents
            depth_yes: YES depth at best price
            depth_no: NO depth at best price
            realized_vol_15m: 15m realized volatility (decimal)
            price_range_15m: 15m price range percentage (decimal)
            regime: Trading regime ("tight", "normal", "wide")
        
        Returns:
            List of InvariantViolation results
        """
        violations = []
        
        violations.append(self.check_spread_invariant(asset, spread_cents, regime))
        violations.append(self.check_depth_invariant(asset, depth_yes, depth_no))
        
        if realized_vol_15m > 0 or price_range_15m > 0:
            violations.append(self.check_volatility_invariant(asset, realized_vol_15m, price_range_15m))
        
        return violations


def get_microstructure_checker() -> MicrostructureInvariantChecker:
    """Get the microstructure invariant checker singleton."""
    global _checker
    if _checker is None:
        _checker = MicrostructureInvariantChecker()
    return _checker


_checker: Optional[MicrostructureInvariantChecker] = None
