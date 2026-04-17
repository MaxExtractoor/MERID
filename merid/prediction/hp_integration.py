"""High-Performance Integration — Wires HP config into Kalshi trading systems.

This module provides seamless integration between high-performance calibration
and existing trading infrastructure:
- Overrides StrategyConfig with HP edge thresholds
- Wires HP take-profit configs into TakeProfitManager
- Wires HP stop-loss configs into StopLossManager
- Integrates sentiment/consensus weighting into sizing

Usage::

    from merid.prediction.hp_integration import enable_high_performance_mode
    
    # Enable HP mode globally
    enable_high_performance_mode(win_rate_target=0.85)
    
    # Or per-agent
    from merid.prediction.hp_integration import apply_hp_to_agent
    apply_hp_to_agent(agent, "BTC", "15m")
"""

from __future__ import annotations

import os
from typing import Optional, TYPE_CHECKING
from decimal import Decimal

from utils.logger import get_logger

if TYPE_CHECKING:
    from merid.event_venues.kalshi.take_profit import TakeProfitManager, TakeProfitConfig
    from merid.event_venues.kalshi.stop_loss import StopLossManager
    from merid.prediction.strategy import StrategyConfig

logger = get_logger("merid.prediction.hp_integration")


# Global HP mode flag
_hp_mode_enabled = False
_hp_win_rate_target = 0.85


def enable_high_performance_mode(
    win_rate_target: float = 0.85,
    aggressive_sizing: bool = True,
    strict_round_trip_limits: bool = True,
) -> None:
    """Enable high-performance mode globally.
    
    Args:
        win_rate_target: Target win rate (0.75-0.90)
        aggressive_sizing: Use 30% Kelly instead of 25%
        strict_round_trip_limits: Enforce max 1 round trip per contract
    """
    global _hp_mode_enabled, _hp_win_rate_target
    
    _hp_mode_enabled = True
    _hp_win_rate_target = win_rate_target
    
    # Set environment variables for downstream systems
    os.environ["MERID_HP_WIN_RATE_TARGET"] = str(int(win_rate_target * 100))
    
    if aggressive_sizing:
        os.environ["MERID_KELLY_FRACTION"] = "0.30"
    
    if strict_round_trip_limits:
        os.environ["MERID_STRICT_ROUND_TRIPS"] = "1"
    
    logger.info(
        f"🚀 HIGH-PERFORMANCE MODE ENABLED: Target win rate {win_rate_target:.0%}, "
        f"Kelly {0.30 if aggressive_sizing else 0.25}, "
        f"Strict round-trip limits: {strict_round_trip_limits}"
    )


def is_hp_mode_enabled() -> bool:
    """Check if high-performance mode is enabled."""
    return _hp_mode_enabled or os.getenv("MERID_HP_MODE", "false").lower() == "true"


def apply_hp_to_strategy_config(
    config: StrategyConfig,
    asset: str,
    timeframe: str,
) -> StrategyConfig:
    """Apply HP calibration to a StrategyConfig.
    
    Returns a new StrategyConfig with HP-optimized thresholds.
    """
    from merid.prediction.high_performance_calibration import get_hp_config
    
    hp_config = get_hp_config(asset, timeframe)
    
    # Create new config with HP values
    new_config = StrategyConfig(
        min_edge_early=hp_config.edge.min_edge_entry,
        min_edge_mid=hp_config.edge.expiry_hour_4,
        min_edge_late=hp_config.edge.expiry_hour_1,
        min_edge_terminal=hp_config.edge.expiry_hour_1,
        max_contracts_per_order=int(config.max_contracts_per_order * 1.2),  # 20% boost
        kelly_fraction=hp_config.sizing.kelly_fraction,
        profit_target_pct=Decimal(str(int(hp_config.take_profit.hard_tp_pct))),
        stop_loss_pct=Decimal(str(int(hp_config.stop_loss.initial_stop_pct * 100))),
    )
    
    logger.debug(
        f"Applied HP config to {asset}/{timeframe}: "
        f"edge={hp_config.edge.min_edge_entry}, "
        f"win_rate_target={hp_config.win_rate_target:.0%}"
    )
    
    return new_config


def apply_hp_to_take_profit_config(
    agent_name: str,
    asset: str,
    timeframe: str,
) -> TakeProfitConfig:
    """Get HP-optimized take-profit config for an agent.
    
    Returns a TakeProfitConfig with aggressive profit targets.
    """
    from merid.prediction.high_performance_calibration import get_hp_config
    from merid.event_venues.kalshi.take_profit import TakeProfitConfig
    
    hp_config = get_hp_config(asset, timeframe)
    tp = hp_config.take_profit
    
    # Build HP TP config
    hp_tp = TakeProfitConfig(
        tp_enabled=True,
        tp_r_multiple_primary=tp.r_multiple_primary,
        tp_pct_of_max_gain_primary=0.0,  # Use R-multiple only
        tp_min_cents=max(3, tp.trailing_giveback_cents // 2),  # Tighter min cents
        tp_scale_out_fraction=tp.scale_out_fraction,
        tp_trailing_enabled=True,
        tp_trailing_activation_r_multiple=tp.trailing_activation_r,
        tp_trailing_giveback_cents=tp.trailing_giveback_cents,
        tp_min_edge_after_fees_cents=1.5,  # Lower fee floor for more trades
        tp_min_unrealized_pct_hard_close=tp.hard_tp_pct,
        tp_min_unrealized_pct_partial=tp.partial_tp_pct,
        trailing_giveback_pct_after_unrealized=15.0,  # Tighter % giveback
        trailing_pct_activation_unrealized=50.0,
        tp_max_round_trips_per_contract=tp.max_round_trips,
        tp_min_price_move_for_reentry=tp.min_price_move_reentry,
        tp_round_trips_reset_daily=True,
    )
    
    logger.debug(
        f"HP TP config for {agent_name}: "
        f"R_primary={tp.r_multiple_primary}, "
        f"scale_out={tp.scale_out_fraction}, "
        f"hard_tp={tp.hard_tp_pct}%"
    )
    
    return hp_tp


def calculate_hp_position_size(
    asset: str,
    timeframe: str,
    base_size: int,
    sentiment_score: float,
    consensus_confidence: float,
    vol_scalar: float,
    win_streak: int = 0,
    lose_streak: int = 0,
) -> int:
    """Calculate HP-optimized position size with sentiment/consensus weighting.
    
    Args:
        asset: Asset symbol
        timeframe: Timeframe
        base_size: Base Kelly-calculated size
        sentiment_score: Fear/greed score (0-100)
        consensus_confidence: Consensus confidence (0-1)
        vol_scalar: Volatility scalar (0-1, lower = higher vol)
        win_streak: Current consecutive win count
        lose_streak: Current consecutive loss count
        
    Returns:
        Adjusted position size
    """
    from merid.prediction.high_performance_calibration import get_hp_config
    
    hp_config = get_hp_config(asset, timeframe)
    sizing = hp_config.sizing
    
    # Start with base size
    size = float(base_size)
    
    # Apply sentiment weighting
    # In extreme fear (score < 20), increase size (contrarian opportunity)
    # In extreme greed (score > 80), reduce size (avoid FOMO)
    if sentiment_score < 20:
        sentiment_mult = 1.20  # Boost 20% in extreme fear (buy dips)
    elif sentiment_score > 80:
        sentiment_mult = 0.85  # Reduce 15% in extreme greed (avoid FOMO)
    else:
        # Linear interpolation: neutral (50) = 1.0
        if sentiment_score <= 50:
            sentiment_mult = 1.0 + (50 - sentiment_score) / 50 * 0.20  # 1.0 to 1.2
        else:
            sentiment_mult = 1.0 - (sentiment_score - 50) / 50 * 0.15  # 1.0 to 0.85
    
    size *= (1 + (sentiment_mult - 1) * sizing.sentiment_weight)
    
    # Apply consensus confidence weighting
    # Size proportional to confidence above floor
    conf_floor = hp_config.sentiment_consensus.confidence_floor
    if consensus_confidence > conf_floor:
        conf_boost = (consensus_confidence - conf_floor) / (1 - conf_floor)
        size *= (1 + conf_boost * sizing.consensus_weight)
    else:
        size *= 0.5  # Halve size if below confidence floor
    
    # Apply volatility scalar weighting
    # Lower scalar = higher vol = reduce size
    vol_mult = 0.5 + vol_scalar * 0.5  # 0.5 to 1.0 range
    size *= (1 + (vol_mult - 1) * sizing.vol_scalar_weight)
    
    # Apply win/lose streak adjustment
    if sizing.compound_win_streak and win_streak >= sizing.streak_length_threshold:
        # Increase size on win streaks (up to 50% boost)
        streak_boost = min((win_streak - sizing.streak_length_threshold + 1) * 0.1, 0.5)
        size *= (1 + streak_boost)
        logger.debug(f"Win streak boost: +{streak_boost:.0%} (streak={win_streak})")
    
    if sizing.reduce_lose_streak and lose_streak >= sizing.streak_length_threshold:
        # Decrease size on lose streaks (down to 50% reduction)
        streak_penalty = min((lose_streak - sizing.streak_length_threshold + 1) * 0.15, 0.5)
        size *= (1 - streak_penalty)
        logger.debug(f"Lose streak penalty: -{streak_penalty:.0%} (streak={lose_streak})")
    
    # Apply max position limit
    max_position = float(sizing.max_position_pct_bankroll) * 100000  # Assume $100k bankroll
    size = min(size, max_position)
    
    return max(1, int(size))


def get_hp_edge_threshold(
    asset: str,
    timeframe: str,
    hours_to_expiry: float,
    sentiment_regime: str = "neutral",
    vol_regime: str = "normal",
) -> Decimal:
    """Get dynamic edge threshold for entry decision.
    
    This is the main entry point for edge calculation in HP mode.
    """
    from merid.prediction.high_performance_calibration import calculate_dynamic_edge
    
    # Base edge (will be overridden by HP config)
    base_edge = Decimal("0.05")
    
    return calculate_dynamic_edge(
        asset=asset,
        timeframe=timeframe,
        base_edge=base_edge,
        sentiment_regime=sentiment_regime,
        vol_regime=vol_regime,
        hours_to_expiry=hours_to_expiry,
    )


def validate_hp_setup() -> list[str]:
    """Validate that HP mode is properly configured.
    
    Returns list of issues (empty if all good).
    """
    issues = []
    
    if not is_hp_mode_enabled():
        issues.append("HP mode not enabled")
    
    # Check that all crypto assets have configs
    assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    timeframes = ["15m", "1h", "daily"]
    
    try:
        from merid.prediction.high_performance_calibration import get_hp_config
        
        for asset in assets:
            for tf in timeframes:
                try:
                    config = get_hp_config(asset, tf)
                    if config.expected_win_rate < 0.80:
                        issues.append(f"{asset}/{tf} win_rate {config.expected_win_rate:.0%} below 80%")
                except Exception as e:
                    issues.append(f"{asset}/{tf} config error: {e}")
    except Exception as e:
        issues.append(f"HP config loading failed: {e}")
    
    return issues


def get_hp_performance_summary() -> dict:
    """Get summary of expected performance across all asset/timeframe combinations."""
    from merid.prediction.high_performance_calibration import get_hp_config
    
    assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    timeframes = ["15m", "1h", "daily"]
    
    summary = {
        "hp_mode_enabled": is_hp_mode_enabled(),
        "win_rate_target": _hp_win_rate_target,
        "combinations": {},
        "average_win_rate": 0.0,
        "average_profit_factor": 0.0,
        "average_sharpe": 0.0,
    }
    
    total_wr = 0.0
    total_pf = 0.0
    total_sr = 0.0
    count = 0
    
    for asset in assets:
        for tf in timeframes:
            try:
                config = get_hp_config(asset, tf)
                key = f"{asset}_{tf}"
                summary["combinations"][key] = {
                    "edge_threshold": str(config.edge.min_edge_entry),
                    "win_rate": round(config.expected_win_rate, 3),
                    "profit_factor": round(config.expected_profit_factor, 2),
                    "sharpe": round(config.expected_sharpe, 2),
                    "tp_r_multiple": config.take_profit.r_multiple_full,
                    "sl_cents": config.stop_loss.initial_stop_cents,
                }
                total_wr += config.expected_win_rate
                total_pf += config.expected_profit_factor
                total_sr += config.expected_sharpe
                count += 1
            except Exception:
                pass
    
    if count > 0:
        summary["average_win_rate"] = round(total_wr / count, 3)
        summary["average_profit_factor"] = round(total_pf / count, 2)
        summary["average_sharpe"] = round(total_sr / count, 2)
    
    return summary
