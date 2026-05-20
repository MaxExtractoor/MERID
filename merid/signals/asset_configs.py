"""Asset-Specific Indicator Configurations — Optimized parameters per crypto asset.

Replaces the uniform parameter approach with asset-specific tuning based on:
- Volatility characteristics (BTC stable, SOL/DOGE volatile)
- Beta to BTC (DOGE 1.30x, SOL 1.40x)
- Mean-reversion vs momentum tendencies
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.signals.asset_configs")


@dataclass(frozen=True)
class AssetIndicatorConfig:
    """Indicator parameters optimized for a specific asset."""
    
    # Trend detection
    ema_trend_period: int = 50      # EMA for primary trend filter
    ema_fast_period: int = 5        # Fast EMA for crossover
    ema_slow_period: int = 20       # Slow EMA for crossover
    
    # Momentum
    rsi_period: int = 8             # RSI lookback
    rsi_oversold: int = 30          # RSI oversold threshold
    rsi_overbought: int = 70        # RSI overbought threshold
    
    macd_fast: int = 8              # MACD fast EMA
    macd_slow: int = 21             # MACD slow EMA
    macd_signal: int = 5            # MACD signal line
    macd_persistence_bars: int = 3  # Bars MACD must hold signal
    macd_histogram_min_pct: float = 0.0001  # Min histogram as % of price
    
    # Volatility / Chop filters
    atr_period: int = 14            # ATR lookback
    atr_min_move_pct: float = 0.0003  # Min ATR as % of price (chop filter)
    atr_stop_mult: float = 1.5      # ATR multiplier for stop distance
    
    # Edge requirements
    min_edge_threshold: float = 0.050  # CONSERVATIVE: 5.0% minimum edge
    
    # Beta (for cross-asset sizing)
    beta_15m: float = 1.0           # Beta to BTC on 15m timeframe
    
    # Position sizing adjustment (1.0 = baseline)
    # Higher for volatile assets to compensate for wider stops
    vol_size_adjustment: float = 1.0


# ═══════════════════════════════════════════════════════════════════════════
# Asset-Specific Configurations (from audit recommendations)
# ═══════════════════════════════════════════════════════════════════════════

ASSET_CONFIGS: Dict[str, AssetIndicatorConfig] = {
    "BTC": AssetIndicatorConfig(
        # Conservative - slower, more established trends
        ema_trend_period=50,
        ema_fast_period=5,
        ema_slow_period=20,
        rsi_period=8,
        rsi_oversold=30,
        rsi_overbought=70,
        macd_fast=8,
        macd_slow=21,
        macd_signal=5,
        atr_period=14,
        atr_min_move_pct=0.0003,   # 0.03%
        atr_stop_mult=1.5,          # 1.5x ATR for stops
        min_edge_threshold=0.050,   # CONSERVATIVE: 5.0%
        beta_15m=1.0,
        vol_size_adjustment=1.0,
    ),
    
    "ETH": AssetIndicatorConfig(
        # Similar to BTC, slightly more aggressive
        ema_trend_period=45,
        ema_fast_period=5,
        ema_slow_period=18,
        rsi_period=8,
        rsi_oversold=30,
        rsi_overbought=70,
        macd_fast=8,
        macd_slow=20,
        macd_signal=5,
        atr_period=14,
        atr_min_move_pct=0.00035,   # 0.035%
        atr_stop_mult=1.6,
        min_edge_threshold=0.052,   # CONSERVATIVE: 5.2%
        beta_15m=1.15,
        vol_size_adjustment=1.0,
    ),
    
    "SOL": AssetIndicatorConfig(
        # Faster, higher volatility - shorter lookbacks
        ema_trend_period=35,        # Faster trend detection
        ema_fast_period=4,
        ema_slow_period=15,
        rsi_period=6,               # More responsive
        rsi_oversold=25,            # Wider bands for vol
        rsi_overbought=75,
        macd_fast=6,
        macd_slow=16,
        macd_signal=4,
        macd_persistence_bars=2,    # Faster signal
        atr_period=14,
        atr_min_move_pct=0.0005,    # 0.05% - higher chop threshold
        atr_stop_mult=2.0,          # Wider stops for vol
        min_edge_threshold=0.055,   # CONSERVATIVE: 5.5%
        beta_15m=1.40,
        vol_size_adjustment=0.85,   # Smaller positions due to vol
    ),
    
    "XRP": AssetIndicatorConfig(
        # Medium speed, news-driven
        ema_trend_period=40,
        ema_fast_period=5,
        ema_slow_period=16,
        rsi_period=7,
        rsi_oversold=28,
        rsi_overbought=72,
        macd_fast=7,
        macd_slow=17,
        macd_signal=4,
        atr_period=14,
        atr_min_move_pct=0.0004,    # 0.04%
        atr_stop_mult=1.8,
        min_edge_threshold=0.057,   # CONSERVATIVE: 5.7% (matches kalshi_distance.yaml)
        beta_15m=1.10,
        vol_size_adjustment=0.95,
    ),
    
    "DOGE": AssetIndicatorConfig(
        # Fastest, meme-driven, most noise
        ema_trend_period=30,        # Very fast
        ema_fast_period=3,
        ema_slow_period=12,
        rsi_period=5,               # Very responsive
        rsi_oversold=20,            # Extreme bands
        rsi_overbought=80,
        macd_fast=5,
        macd_slow=12,
        macd_signal=3,
        macd_persistence_bars=2,
        atr_period=14,
        atr_min_move_pct=0.0006,    # 0.06% - most chop filtering
        atr_stop_mult=2.5,          # Widest stops
        min_edge_threshold=0.060,   # CONSERVATIVE: 6.0% (matches kalshi_distance.yaml)
        beta_15m=1.30,
        vol_size_adjustment=0.80,   # Smallest positions
    ),
}


def get_asset_config(asset: str) -> AssetIndicatorConfig:
    """Get indicator configuration for an asset.
    
    Args:
        asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
        
    Returns:
        AssetIndicatorConfig for the asset, or BTC config as default
    """
    asset_upper = asset.upper()
    if asset_upper in ASSET_CONFIGS:
        return ASSET_CONFIGS[asset_upper]
    
    logger.warning(f"No config found for asset {asset}, using BTC defaults")
    return ASSET_CONFIGS["BTC"]


def get_all_configs() -> Dict[str, AssetIndicatorConfig]:
    """Get all asset configurations."""
    return ASSET_CONFIGS.copy()


def validate_configs() -> list:
    """Validate all asset configurations.
    
    Returns list of validation errors (empty if all valid).
    """
    errors = []
    
    for asset, config in ASSET_CONFIGS.items():
        # Validate EMA ordering
        if config.ema_fast_period >= config.ema_slow_period:
            errors.append(f"{asset}: ema_fast ({config.ema_fast_period}) >= ema_slow ({config.ema_slow_period})")
        
        if config.ema_fast_period >= config.ema_trend_period:
            errors.append(f"{asset}: ema_fast ({config.ema_fast_period}) >= ema_trend ({config.ema_trend_period})")
        
        # Validate RSI bounds
        if config.rsi_oversold >= config.rsi_overbought:
            errors.append(f"{asset}: rsi_oversold ({config.rsi_oversold}) >= rsi_overbought ({config.rsi_overbought})")
        
        # Validate MACD ordering
        if config.macd_fast >= config.macd_slow:
            errors.append(f"{asset}: macd_fast ({config.macd_fast}) >= macd_slow ({config.macd_slow})")
        
        # Validate positive values
        for attr in ["atr_period", "rsi_period", "macd_fast", "macd_slow"]:
            val = getattr(config, attr)
            if val <= 0:
                errors.append(f"{asset}: {attr} must be positive, got {val}")
        
        # Validate beta
        if config.beta_15m < 0.5 or config.beta_15m > 3.0:
            errors.append(f"{asset}: beta_15m ({config.beta_15m}) outside reasonable range [0.5, 3.0]")
    
    return errors


# Run validation on import
_validation_errors = validate_configs()
if _validation_errors:
    for err in _validation_errors:
        logger.error(f"[asset-config-validation] {err}")
    raise ValueError(f"Asset config validation failed: {_validation_errors}")
else:
    logger.info("[asset-configs] All %d asset configurations validated", len(ASSET_CONFIGS))
