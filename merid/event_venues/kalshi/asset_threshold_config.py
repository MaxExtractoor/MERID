"""Asset-specific threshold configuration for dynamic edge gating.

Provides asset metadata and threshold ranking for BTC, ETH, SOL, XRP, DOGE.
Threshold ranking: DOGE (highest) > XRP (high) > SOL (medium-high) > ETH (medium) > BTC (lowest).
"""

from dataclasses import dataclass
from typing import Dict, Optional
from enum import Enum


class ThresholdStrictness(Enum):
    """Asset threshold strictness ranking."""
    HIGHEST = 5    # DOGE
    HIGH = 4       # XRP
    MEDIUM_HIGH = 3 # SOL
    MEDIUM = 2     # ETH
    LOWEST = 1     # BTC


@dataclass
class AssetThresholdConfig:
    """Per-asset threshold configuration."""
    asset: str
    strictness: ThresholdStrictness
    base_spread_multiplier: float  # α: spread multiplier
    base_vol_multiplier: float     # β: volatility multiplier
    base_fee_multiplier: float     # γ: fee multiplier
    base_slippage_multiplier: float # δ: slippage multiplier
    base_alpha_hurdle: float       # ε: base alpha hurdle (cents)
    
    def get_dynamic_multiplier(self) -> float:
        """Get overall dynamic multiplier based on strictness."""
        strictness_value = self.strictness.value
        # Higher strictness = higher multiplier
        return 1.0 + (strictness_value - 1) * 0.2  # 1.0 to 1.8 range


# Default asset configurations
DEFAULT_ASSET_CONFIGS: Dict[str, AssetThresholdConfig] = {
    "BTC": AssetThresholdConfig(
        asset="BTC",
        strictness=ThresholdStrictness.LOWEST,
        base_spread_multiplier=0.5,
        base_vol_multiplier=0.3,
        base_fee_multiplier=1.0,
        base_slippage_multiplier=0.5,
        base_alpha_hurdle=1.0  # 1 cent base hurdle
    ),
    "ETH": AssetThresholdConfig(
        asset="ETH",
        strictness=ThresholdStrictness.MEDIUM,
        base_spread_multiplier=0.7,
        base_vol_multiplier=0.5,
        base_fee_multiplier=1.0,
        base_slippage_multiplier=0.7,
        base_alpha_hurdle=1.5  # 1.5 cents base hurdle
    ),
    "SOL": AssetThresholdConfig(
        asset="SOL",
        strictness=ThresholdStrictness.MEDIUM_HIGH,
        base_spread_multiplier=0.9,
        base_vol_multiplier=0.7,
        base_fee_multiplier=1.0,
        base_slippage_multiplier=0.9,
        base_alpha_hurdle=2.0  # 2 cents base hurdle
    ),
    "XRP": AssetThresholdConfig(
        asset="XRP",
        strictness=ThresholdStrictness.HIGH,
        base_spread_multiplier=1.1,
        base_vol_multiplier=0.9,
        base_fee_multiplier=1.0,
        base_slippage_multiplier=1.1,
        base_alpha_hurdle=2.5  # 2.5 cents base hurdle
    ),
    "DOGE": AssetThresholdConfig(
        asset="DOGE",
        strictness=ThresholdStrictness.HIGHEST,
        base_spread_multiplier=1.3,
        base_vol_multiplier=1.1,
        base_fee_multiplier=1.0,
        base_slippage_multiplier=1.3,
        base_alpha_hurdle=3.0  # 3 cents base hurdle
    ),
}


def get_asset_config(asset: str) -> Optional[AssetThresholdConfig]:
    """Get threshold configuration for an asset."""
    return DEFAULT_ASSET_CONFIGS.get(asset.upper())


def get_all_asset_configs() -> Dict[str, AssetThresholdConfig]:
    """Get all asset configurations."""
    return DEFAULT_ASSET_CONFIGS.copy()
