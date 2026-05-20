"""Tiered Profit-Taking Configuration — 40%/40%/20% Ladder Strategy.

This module provides the canonical configuration for the three-tier profit-taking
strategy across all supported crypto assets (BTC, ETH, SOL, XRP, DOGE).

The configuration is declarative (YAML/env-driven) and maps directly to the
existing TakeProfitManager and DynamicTakeProfitEngine infrastructure.

Tier Structure:
- Tier 1 (40%): Exit at 0.7R, capturing initial profit while leaving runway
- Tier 2 (40%): Exit at 1.0R via trailing stop activation
- Tier 3 (20%): Exit at 1.5R via hard TP or wide trailing stop

Reference: trademetria.com/blog/what-are-r-multiples-the-key-metric-every-trader-should-know/
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.prediction.tiered_profit_config")


@dataclass
class TieredProfitLevel:
    """Single tier configuration within the ladder.
    
    Attributes:
        tier_number: 1, 2, or 3 (for logging/metrics)
        position_fraction: Fraction of remaining position to exit (0.0-1.0)
        target_r_multiple: R-multiple at which this tier triggers
        use_trailing: Whether to use trailing stop (vs hard TP) for this tier
        trailing_giveback_cents: Cents of giveback allowed from peak (trailing only)
        min_unrealized_pct: Alternative: trigger via PnL % (overrides R-multiple if set)
    """
    tier_number: int
    position_fraction: float  # e.g., 0.40 for 40%
    target_r_multiple: float  # e.g., 0.7 for Tier 1
    use_trailing: bool = False
    trailing_giveback_cents: int = 5
    min_unrealized_pct: Optional[float] = None  # Alternative trigger (e.g., 150.0 for 1.5R)
    
    def __post_init__(self) -> None:
        # Validation
        if not 0 < self.position_fraction <= 1.0:
            raise ValueError(f"position_fraction must be in (0, 1], got {self.position_fraction}")
        if self.target_r_multiple <= 0:
            raise ValueError(f"target_r_multiple must be positive, got {self.target_r_multiple}")


@dataclass
class TieredProfitConfig:
    """Complete 40%/40%/20% ladder configuration.
    
    This dataclass centralizes all parameters for the tiered profit-taking strategy
    and provides factory methods for per-asset configuration.
    
    The configuration maps directly to TakeProfitManager parameters:
    - Tier 1 → tp_r_multiple_primary + tp_scale_out_fraction
    - Tier 2 → trailing_activation_r_multiple (captures ~40% of remainder)
    - Tier 3 → min_unrealized_pct_hard_close (captures final 20%)
    
    Example:
        >>> config = TieredProfitConfig.for_asset("BTC", timeframe="15m")
        >>> config.to_take_profit_config()
        TakeProfitConfig(...)
    """
    
    # ═══════════════════════════════════════════════════════════════════════════
    # TIER DEFINITIONS (40% / 40% / 20% ladder)
    # ═══════════════════════════════════════════════════════════════════════════
    
    tier1: TieredProfitLevel = field(default_factory=lambda: TieredProfitLevel(
        tier_number=1,
        position_fraction=0.40,
        target_r_multiple=0.70,  # ~5% profit on typical contract after fees
        use_trailing=False,  # Hard exit at 0.7R
        trailing_giveback_cents=0,
    ))
    
    tier2: TieredProfitLevel = field(default_factory=lambda: TieredProfitLevel(
        tier_number=2,
        position_fraction=0.40,  # 40% of remaining 60% = 24% of original
        target_r_multiple=1.00,  # Breakeven on risk, profit on first tier
        use_trailing=True,
        trailing_giveback_cents=5,  # ~50% of captured 10c profit
    ))
    
    tier3: TieredProfitLevel = field(default_factory=lambda: TieredProfitLevel(
        tier_number=3,
        position_fraction=1.00,  # Remaining 20% (of original)
        target_r_multiple=1.50,  # 1.5R = substantial profit
        use_trailing=True,
        trailing_giveback_cents=8,  # Wider trail for final run
        min_unrealized_pct=150.0,  # Hard TP at 150% unrealized
    ))
    
    # ═══════════════════════════════════════════════════════════════════════════
    # RE-ENTRY GATING (Anti-churn / Anti-round-trip)
    # ═══════════════════════════════════════════════════════════════════════════
    
    max_round_trips_per_contract: int = 2  # Max cycles per contract
    min_price_move_for_reentry_cents: int = 5  # Require 5¢ move before re-entry
    round_trips_reset_daily: bool = True
    
    # ═══════════════════════════════════════════════════════════════════════════
    # FEE-AWARE EDGE FLOOR
    # ═══════════════════════════════════════════════════════════════════════════
    
    min_edge_after_fees_cents: float = 2.0  # Minimum 2c net profit per contract
    
    # ═══════════════════════════════════════════════════════════════════════════
    # OBSERVABILITY
    # ═══════════════════════════════════════════════════════════════════════════
    
    emit_metrics: bool = True
    log_level: str = "info"  # debug, info, warning
    
    # ═══════════════════════════════════════════════════════════════════════════
    # ASSET-SPECIFIC OVERRIDES (populated by factory methods)
    # ═══════════════════════════════════════════════════════════════════════════
    
    asset: str = "BTC"
    timeframe: str = "15m"
    
    @classmethod
    def for_asset(cls, asset: str, timeframe: str = "15m") -> "TieredProfitConfig":
        """Create tiered config optimized for specific asset and timeframe.
        
        Assets:
            - BTC, ETH: Tighter trails (more liquid, less volatile)
            - SOL, XRP, DOGE: Wider trails (higher volatility)
        
        Timeframes:
            - 15m: Aggressive, tighter targets
            - 1h: Moderate
            - daily/weekly: Wider targets, fewer round trips
        """
        asset_upper = asset.upper()
        tf_lower = timeframe.lower()
        
        # Base configuration
        config = cls()
        config.asset = asset_upper
        config.timeframe = tf_lower
        
        # ═══════════════════════════════════════════════════════════════════════
        # VOLATILITY-BASED TRAIL WIDTH ADJUSTMENTS
        # ═══════════════════════════════════════════════════════════════════════
        
        if asset_upper in ("SOL", "XRP", "DOGE"):
            # Higher volatility assets: wider trails to avoid noise
            config.tier2.trailing_giveback_cents = 7
            config.tier3.trailing_giveback_cents = 12
            config.min_price_move_for_reentry_cents = 6
            logger.debug("[TIERED-CONFIG] %s %s: high-vol adjustments applied", asset_upper, tf_lower)
            
        elif asset_upper in ("BTC", "ETH"):
            # Major assets: tighter trails, more precise exits
            config.tier2.trailing_giveback_cents = 4
            config.tier3.trailing_giveback_cents = 6
            config.min_price_move_for_reentry_cents = 4
            
        # ═══════════════════════════════════════════════════════════════════════
        # TIMEFRAME-BASED ADJUSTMENTS
        # ═══════════════════════════════════════════════════════════════════════
        
        if tf_lower in ("daily", "weekly"):
            # Longer timeframes: wider targets, fewer round trips
            config.tier1.target_r_multiple = 0.80
            config.tier2.target_r_multiple = 1.20
            config.tier3.target_r_multiple = 2.00
            config.tier3.min_unrealized_pct = 200.0
            config.max_round_trips_per_contract = 1
            config.tier2.trailing_giveback_cents += 2
            config.tier3.trailing_giveback_cents += 3
            
        elif tf_lower == "1h":
            # Hourly: moderate
            config.tier1.target_r_multiple = 0.75
            config.tier2.target_r_multiple = 1.10
            config.tier3.target_r_multiple = 1.75
            
        # 15m uses defaults (most aggressive)
        
        # ═══════════════════════════════════════════════════════════════════════
        # ENVIRONMENT OVERRIDES
        # ═══════════════════════════════════════════════════════════════════════
        
        # Allow env vars to override any numeric parameter
        config._apply_env_overrides()
        
        return config
    
    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides for production tuning."""
        prefix = f"MERID_TP_{self.asset}_{self.timeframe.upper()}_"
        
        # Tier 1 overrides
        if val := os.getenv(f"{prefix}TIER1_R"):
            self.tier1.target_r_multiple = float(val)
        if val := os.getenv(f"{prefix}TIER1_FRAC"):
            self.tier1.position_fraction = float(val)
            
        # Tier 2 overrides
        if val := os.getenv(f"{prefix}TIER2_R"):
            self.tier2.target_r_multiple = float(val)
        if val := os.getenv(f"{prefix}TIER2_GIVEBACK"):
            self.tier2.trailing_giveback_cents = int(val)
            
        # Tier 3 overrides
        if val := os.getenv(f"{prefix}TIER3_R"):
            self.tier3.target_r_multiple = float(val)
        if val := os.getenv(f"{prefix}TIER3_HARD_PCT"):
            self.tier3.min_unrealized_pct = float(val)
            
        # Global overrides
        if val := os.getenv(f"MERID_TP_MAX_ROUNDTrips_{self.asset}"):
            self.max_round_trips_per_contract = int(val)
    
    def to_take_profit_config(self) -> "TakeProfitConfig":
        """Convert tiered config to existing TakeProfitManager configuration.
        
        This maps the 40/40/20 ladder onto the existing TP infrastructure:
        - Tier 1 → primary TP with scale_out_fraction
        - Tier 2 → trailing activation at 1.0R (captures ~40% of remainder)
        - Tier 3 → hard TP at 150% unrealized (or trailing with wide giveback)
        """
        from merid.event_venues.kalshi.take_profit import TakeProfitConfig
        
        return TakeProfitConfig(
            tp_enabled=True,
            # Tier 1: Primary exit at 0.7R, scale out 40%
            tp_r_multiple_primary=self.tier1.target_r_multiple,
            tp_scale_out_fraction=self.tier1.position_fraction,
            # Tier 2 & 3: Trailing configuration
            tp_trailing_enabled=True,
            tp_trailing_activation_r_multiple=self.tier2.target_r_multiple,
            tp_trailing_giveback_cents=self.tier2.trailing_giveback_cents,
            # Tier 3 hard TP fallback
            tp_min_unrealized_pct_hard_close=self.tier3.min_unrealized_pct or 150.0,
            tp_min_unrealized_pct_partial=50.0,  # 50% for mid-ladder partial
            # Fee and re-entry gating
            tp_min_edge_after_fees_cents=self.min_edge_after_fees_cents,
            tp_max_round_trips_per_contract=self.max_round_trips_per_contract,
            tp_min_price_move_for_reentry=self.min_price_move_for_reentry_cents,
            tp_round_trips_reset_daily=self.round_trips_reset_daily,
            # Minimum profit floor (prevents micro-gain exits)
            tp_min_cents=5,
        )
    
    def to_dict(self) -> dict:
        """Serialize configuration for logging and metrics."""
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "tier1": {
                "fraction": self.tier1.position_fraction,
                "r_multiple": self.tier1.target_r_multiple,
                "exit_type": "hard" if not self.tier1.use_trailing else "trailing",
            },
            "tier2": {
                "fraction_of_remainder": self.tier2.position_fraction,
                "r_multiple": self.tier2.target_r_multiple,
                "giveback_cents": self.tier2.trailing_giveback_cents,
                "exit_type": "trailing" if self.tier2.use_trailing else "hard",
            },
            "tier3": {
                "fraction_of_original": 0.20,  # Always 20% of original
                "r_multiple": self.tier3.target_r_multiple,
                "hard_tp_pct": self.tier3.min_unrealized_pct,
                "giveback_cents": self.tier3.trailing_giveback_cents,
            },
            "reentry": {
                "max_round_trips": self.max_round_trips_per_contract,
                "min_price_move_cents": self.min_price_move_for_reentry_cents,
                "reset_daily": self.round_trips_reset_daily,
            },
            "min_edge_cents": self.min_edge_after_fees_cents,
        }


# ═══════════════════════════════════════════════════════════════════════════
# SINGLETON REGISTRY (per-asset configs)
# ═══════════════════════════════════════════════════════════════════════════

_tiered_configs: Dict[str, TieredProfitConfig] = {}


def get_tiered_config(asset: str, timeframe: str = "15m") -> TieredProfitConfig:
    """Get cached tiered config for asset/timeframe pair."""
    key = f"{asset.upper()}:{timeframe.lower()}"
    if key not in _tiered_configs:
        _tiered_configs[key] = TieredProfitConfig.for_asset(asset, timeframe)
    return _tiered_configs[key]


def clear_tiered_config_cache() -> None:
    """Clear config cache (for testing/config reload)."""
    global _tiered_configs
    _tiered_configs = {}
