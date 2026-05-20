"""
Band Strategy Production Corridors
==================================

Defines and enforces production parameter corridors for the 15m Bollinger Band
strategy per asset. These corridors are derived from backtest results and walk-forward
validation to prevent over-fitting and ensure robust performance.

Production corridors are tighter than the search ranges used during optimization:
- BTC/ETH: SD 2.0-2.2 (narrower than search 2.0-2.5)
- SOL/XRP: SD 2.2-2.4 (narrower than search 2.0-2.5)
- DOGE: SD 2.3-2.5 (narrower than search 2.0-2.5)

Reference:
- Walk-forward validation should select parameters within these corridors
- Parameters outside corridors are considered over-fit even if backtests look good
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, Tuple, List
import logging

from utils.logger import get_logger

logger = get_logger("merid.strategies.band_production_corridors")


@dataclass
class AssetProductionCorridor:
    """Production parameter corridor for a single asset."""
    
    asset: str
    
    # Bollinger Bands corridor
    bb_period_min: int = 18
    bb_period_max: int = 22
    bb_sd_min: float = 2.0
    bb_sd_max: float = 2.5
    
    # Keltner Channels corridor
    kc_ema_period_min: int = 18
    kc_ema_period_max: int = 22
    kc_atr_period_min: int = 10
    kc_atr_period_max: int = 20
    kc_atr_multiplier_min: float = 1.8
    kc_atr_multiplier_max: float = 2.2
    
    # Stop Loss corridor
    sl_atr_multiplier_min: float = 1.5
    sl_atr_multiplier_max: float = 2.0
    
    # Entry filters
    rsi_oversold_min: float = 25.0
    rsi_oversold_max: float = 35.0
    rsi_overbought_min: float = 65.0
    rsi_overbought_max: float = 75.0
    
    # Regime filters
    adx_trend_threshold_min: float = 18.0
    adx_trend_threshold_max: float = 22.0
    atr_spike_multiplier_min: float = 1.8
    atr_spike_multiplier_max: float = 2.2
    
    def validate_config(
        self,
        bb_period: int,
        bb_sd: float,
        sl_atr: float,
    ) -> Tuple[bool, List[str]]:
        """Validate a configuration against production corridor.
        
        Args:
            bb_period: Bollinger Bands period.
            bb_sd: Bollinger Bands SD multiplier.
            sl_atr: Stop loss ATR multiplier.
        
        Returns:
            (is_valid, list of violation messages)
        """
        violations = []
        
        if not (self.bb_period_min <= bb_period <= self.bb_period_max):
            violations.append(
                f"BB period {bb_period} outside corridor [{self.bb_period_min}, {self.bb_period_max}]"
            )
        
        if not (self.bb_sd_min <= bb_sd <= self.bb_sd_max):
            violations.append(
                f"BB SD {bb_sd} outside corridor [{self.bb_sd_min}, {self.bb_sd_max}]"
            )
        
        if not (self.sl_atr_multiplier_min <= sl_atr <= self.sl_atr_multiplier_max):
            violations.append(
                f"SL ATR {sl_atr} outside corridor [{self.sl_atr_multiplier_min}, {self.sl_atr_multiplier_max}]"
            )
        
        return len(violations) == 0, violations
    
    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "bb_period": {"min": self.bb_period_min, "max": self.bb_period_max},
            "bb_sd": {"min": self.bb_sd_min, "max": self.bb_sd_max},
            "kc_ema_period": {"min": self.kc_ema_period_min, "max": self.kc_ema_period_max},
            "kc_atr_period": {"min": self.kc_atr_period_min, "max": self.kc_atr_period_max},
            "kc_atr_multiplier": {"min": self.kc_atr_multiplier_min, "max": self.kc_atr_multiplier_max},
            "sl_atr_multiplier": {"min": self.sl_atr_multiplier_min, "max": self.sl_atr_multiplier_max},
            "rsi_oversold": {"min": self.rsi_oversold_min, "max": self.rsi_oversold_max},
            "rsi_overbought": {"min": self.rsi_overbought_min, "max": self.rsi_overbought_max},
            "adx_trend_threshold": {"min": self.adx_trend_threshold_min, "max": self.adx_trend_threshold_max},
            "atr_spike_multiplier": {"min": self.atr_spike_multiplier_min, "max": self.atr_spike_multiplier_max},
        }


# Default production corridors per asset (to be refined after backtesting)
DEFAULT_PRODUCTION_CORRIDORS: Dict[str, AssetProductionCorridor] = {
    "BTC": AssetProductionCorridor(
        asset="BTC",
        bb_sd_min=2.0,
        bb_sd_max=2.2,  # Tighter for smoother asset
        sl_atr_multiplier_min=1.5,
        sl_atr_multiplier_max=1.7,
    ),
    "ETH": AssetProductionCorridor(
        asset="ETH",
        bb_sd_min=2.0,
        bb_sd_max=2.2,  # Similar to BTC
        sl_atr_multiplier_min=1.5,
        sl_atr_multiplier_max=1.7,
    ),
    "SOL": AssetProductionCorridor(
        asset="SOL",
        bb_sd_min=2.2,
        bb_sd_max=2.4,  # Wider for higher beta
        sl_atr_multiplier_min=1.7,
        sl_atr_multiplier_max=1.9,
    ),
    "XRP": AssetProductionCorridor(
        asset="XRP",
        bb_sd_min=2.2,
        bb_sd_max=2.4,  # Wider for squeezes
        sl_atr_multiplier_min=1.7,
        sl_atr_multiplier_max=1.9,
    ),
    "DOGE": AssetProductionCorridor(
        asset="DOGE",
        bb_sd_min=2.3,
        bb_sd_max=2.5,  # Widest for noise
        sl_atr_multiplier_min=1.8,
        sl_atr_multiplier_max=2.0,
    ),
}


def get_production_corridor(asset: str) -> AssetProductionCorridor:
    """Get production corridor for a specific asset.
    
    Args:
        asset: Asset symbol.
    
    Returns:
        AssetProductionCorridor for the asset.
    """
    asset = asset.upper()
    return DEFAULT_PRODUCTION_CORRIDORS.get(asset, AssetProductionCorridor(asset=asset))


def validate_production_config(
    asset: str,
    bb_period: int,
    bb_sd: float,
    sl_atr: float,
) -> Tuple[bool, List[str]]:
    """Validate a configuration against production corridor.
    
    Args:
        asset: Asset symbol.
        bb_period: Bollinger Bands period.
        bb_sd: Bollinger Bands SD multiplier.
        sl_atr: Stop loss ATR multiplier.
    
    Returns:
        (is_valid, list of violation messages)
    """
    corridor = get_production_corridor(asset)
    return corridor.validate_config(bb_period, bb_sd, sl_atr)


def update_production_corridor(
    asset: str,
    bb_sd_min: Optional[float] = None,
    bb_sd_max: Optional[float] = None,
    sl_atr_min: Optional[float] = None,
    sl_atr_max: Optional[float] = None,
) -> None:
    """Update production corridor for an asset based on backtest results.
    
    This should be called after walk-forward validation to lock in validated
    parameter ranges.
    
    Args:
        asset: Asset symbol.
        bb_sd_min: Minimum BB SD multiplier.
        bb_sd_max: Maximum BB SD multiplier.
        sl_atr_min: Minimum SL ATR multiplier.
        sl_atr_max: Maximum SL ATR multiplier.
    """
    asset = asset.upper()
    
    if asset not in DEFAULT_PRODUCTION_CORRIDORS:
        logger.warning(f"No default corridor for {asset}, creating new")
        DEFAULT_PRODUCTION_CORRIDORS[asset] = AssetProductionCorridor(asset=asset)
    
    corridor = DEFAULT_PRODUCTION_CORRIDORS[asset]
    
    if bb_sd_min is not None:
        corridor.bb_sd_min = bb_sd_min
    if bb_sd_max is not None:
        corridor.bb_sd_max = bb_sd_max
    if sl_atr_min is not None:
        corridor.sl_atr_multiplier_min = sl_atr_min
    if sl_atr_max is not None:
        corridor.sl_atr_multiplier_max = sl_atr_max
    
    logger.info(f"Updated production corridor for {asset}: "
                f"BB SD [{corridor.bb_sd_min}, {corridor.bb_sd_max}], "
                f"SL ATR [{corridor.sl_atr_multiplier_min}, {corridor.sl_atr_multiplier_max}]")


def get_all_corridors() -> Dict[str, Dict[str, Any]]:
    """Get all production corridors.
    
    Returns:
        Dict mapping asset to corridor dict.
    """
    return {asset: corridor.to_dict() for asset, corridor in DEFAULT_PRODUCTION_CORRIDORS.items()}


def check_backtest_parameter_stability(
    asset: str,
    bb_sd_values: List[float],
    sl_atr_values: List[float],
) -> Dict[str, Any]:
    """Check parameter stability across walk-forward windows.
    
    Args:
        asset: Asset symbol.
        bb_sd_values: List of BB SD values from WFO windows.
        sl_atr_values: List of SL ATR values from WFO windows.
    
    Returns:
        Dict with stability metrics and assessment.
    """
    corridor = get_production_corridor(asset)
    
    # Check how many parameters fall within corridor
    bb_sd_in_corridor = sum(1 for v in bb_sd_values if corridor.bb_sd_min <= v <= corridor.bb_sd_max)
    sl_atr_in_corridor = sum(1 for v in sl_atr_values if corridor.sl_atr_multiplier_min <= v <= corridor.sl_atr_multiplier_max)
    
    # Calculate variance
    import statistics
    bb_sd_std = statistics.stdev(bb_sd_values) if len(bb_sd_values) > 1 else 0.0
    sl_atr_std = statistics.stdev(sl_atr_values) if len(sl_atr_values) > 1 else 0.0
    
    # Stability assessment
    is_stable = (
        bb_sd_in_corridor / len(bb_sd_values) >= 0.7 and
        sl_atr_in_corridor / len(sl_atr_values) >= 0.7 and
        bb_sd_std < 0.15 and
        sl_atr_std < 0.15
    )
    
    return {
        "asset": asset,
        "bb_sd_in_corridor_pct": bb_sd_in_corridor / len(bb_sd_values) if bb_sd_values else 0.0,
        "sl_atr_in_corridor_pct": sl_atr_in_corridor / len(sl_atr_values) if sl_atr_values else 0.0,
        "bb_sd_std": round(bb_sd_std, 4),
        "sl_atr_std": round(sl_atr_std, 4),
        "is_stable": is_stable,
        "corridor_bb_sd": f"[{corridor.bb_sd_min}, {corridor.bb_sd_max}]",
        "corridor_sl_atr": f"[{corridor.sl_atr_multiplier_min}, {corridor.sl_atr_multiplier_max}]",
    }
