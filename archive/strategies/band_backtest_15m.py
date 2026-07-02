"""
15-Minute Band Strategy Backtest Engine
=======================================

Backtest scaffold for Bollinger Band "top edge" mean-reversion strategy
on 15m crypto majors (BTC, ETH, SOL, XRP, DOGE).

Features:
- Walk-forward validation with rolling windows
- Per-asset parameter optimization
- Regime-aware metrics (trend vs range)
- Win rate targeting (80%+ goal)
- Fee-aware PnL calculation for Kalshi

Usage::

    from merid.strategies.band_backtest_15m import backtest_band_strategy, walk_forward_validation
    
    # Simple backtest
    trades, summary = backtest_band_strategy(df_ohlc, asset="BTC")
    
    # Walk-forward validation
    results = walk_forward_validation(df_ohlc, asset="BTC", opt_window=90, fwd_window=30)
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import numpy as np
import pandas as pd

from merid.strategies.band_strategy_15m import (
    BandStrategyEngine,
    BandStrategyConfig,
    BandSnapshot,
    TradeSetup,
    get_band_strategy_config,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class BandTradeRecord:
    """Single backtest trade with full context."""
    
    asset: str
    entry_time: datetime
    exit_time: datetime
    side: str  # "long" or "short"
    entry_price: float
    exit_price: float
    tp_price: float
    sl_price: float
    pnl_pct: float  # % return
    r_multiple: float
    
    # Context at entry
    regime: str  # "trend" or "range"
    bb_position: float
    rsi: float
    adx: float
    atr: float
    bb_sd_multiplier: float
    
    # Trade metadata
    bars_held: int = 0
    exit_reason: str = ""  # "tp", "sl", "timeout", "manual"
    signal_strength: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat(),
            "side": self.side,
            "entry_price": round(self.entry_price, 2),
            "exit_price": round(self.exit_price, 2),
            "tp_price": round(self.tp_price, 2),
            "sl_price": round(self.sl_price, 2),
            "pnl_pct": round(self.pnl_pct, 4),
            "r_multiple": round(self.r_multiple, 2),
            "regime": self.regime,
            "bb_position": round(self.bb_position, 4),
            "rsi": round(self.rsi, 2),
            "adx": round(self.adx, 2),
            "atr": round(self.atr, 2),
            "bb_sd_multiplier": self.bb_sd_multiplier,
            "bars_held": self.bars_held,
            "exit_reason": self.exit_reason,
            "signal_strength": round(self.signal_strength, 3),
        }


@dataclass
class BandBacktestSummary:
    """Aggregate backtest performance metrics."""
    
    asset: str = ""
    total_trades: int = 0
    long_trades: int = 0
    short_trades: int = 0
    
    # Performance
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    total_pnl_pct: float = 0.0
    
    # Regime-aware metrics
    range_trades: int = 0
    range_wins: int = 0
    range_win_rate: float = 0.0
    trend_trades: int = 0
    trend_wins: int = 0
    trend_win_rate: float = 0.0
    
    # Risk metrics
    max_drawdown_pct: float = 0.0
    avg_r_multiple: float = 0.0
    avg_bars_held: float = 0.0
    
    # Exit breakdown
    tp_exits: int = 0
    sl_exits: int = 0
    timeout_exits: int = 0
    
    # Config used
    bb_sd_multiplier: float = 2.0
    sl_atr_multiplier: float = 1.5
    
    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "total_trades": self.total_trades,
            "long_trades": self.long_trades,
            "short_trades": self.short_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 4),
            "avg_win_pct": round(self.avg_win_pct, 4),
            "avg_loss_pct": round(self.avg_loss_pct, 4),
            "total_pnl_pct": round(self.total_pnl_pct, 4),
            "range_trades": self.range_trades,
            "range_wins": self.range_wins,
            "range_win_rate": round(self.range_win_rate, 4),
            "trend_trades": self.trend_trades,
            "trend_wins": self.trend_wins,
            "trend_win_rate": round(self.trend_win_rate, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "avg_r_multiple": round(self.avg_r_multiple, 2),
            "avg_bars_held": round(self.avg_bars_held, 1),
            "tp_exits": self.tp_exits,
            "sl_exits": self.sl_exits,
            "timeout_exits": self.timeout_exits,
            "bb_sd_multiplier": self.bb_sd_multiplier,
            "sl_atr_multiplier": self.sl_atr_multiplier,
        }


@dataclass
class WalkForwardResult:
    """Results from walk-forward validation."""
    
    asset: str
    opt_window_days: int
    fwd_window_days: int
    windows: List[Dict[str, Any]] = field(default_factory=list)
    
    # Aggregate across all windows
    total_trades: int = 0
    aggregate_win_rate: float = 0.0
    aggregate_range_win_rate: float = 0.0
    avg_window_win_rate: float = 0.0
    consistency_score: float = 0.0  # % of windows with >65% win rate
    
    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "opt_window_days": self.opt_window_days,
            "fwd_window_days": self.fwd_window_days,
            "windows": self.windows,
            "total_trades": self.total_trades,
            "aggregate_win_rate": round(self.aggregate_win_rate, 4),
            "aggregate_range_win_rate": round(self.aggregate_range_win_rate, 4),
            "avg_window_win_rate": round(self.avg_window_win_rate, 4),
            "consistency_score": round(self.consistency_score, 4),
        }


# ═══════════════════════════════════════════════════════════════════════════
# Core Backtest Engine
# ═══════════════════════════════════════════════════════════════════════════

def backtest_band_strategy(
    df_ohlc: pd.DataFrame,
    asset: str = "BTC",
    config: Optional[BandStrategyConfig] = None,
    max_bars_held: int = 96,  # 24 hours on 15m
    timeout_hours: float = 24.0,
) -> Tuple[List[BandTradeRecord], BandBacktestSummary]:
    """Run backtest of band strategy on OHLCV data.
    
    Args:
        df_ohlc: DataFrame with DatetimeIndex and 'high', 'low', 'close' columns (15m).
        asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE).
        config: Optional BandStrategyConfig override.
        max_bars_held: Maximum bars to hold position before timeout.
        timeout_hours: Hours before forced exit if TP/SL not hit.
    
    Returns:
        (trades: List[BandTradeRecord], summary: BandBacktestSummary)
    """
    cfg = config or get_band_strategy_config(asset)
    engine = BandStrategyEngine(cfg)
    
    trades: List[BandTradeRecord] = []
    open_position: Optional[BandTradeRecord] = None
    bar_count = 0
    
    logger.info(
        f"Backtest {asset}: {len(df_ohlc)} bars, "
        f"BB SD={cfg.bb_sd_multiplier}, SL ATR={cfg.sl_atr_multiplier}"
    )
    
    for idx, row in df_ohlc.iterrows():
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        timestamp = idx if isinstance(idx, datetime) else pd.Timestamp(idx)
        bar_count += 1
        
        # Update engine
        engine.update(high, low, close)
        
        # Log progress every 100 bars
        if bar_count % 100 == 0:
            logger.info(f"{asset} processing bar {bar_count}/{len(df_ohlc)}")
        
        # Check exit if position open
        if open_position is not None:
            exit_triggered = False
            exit_reason = ""
            exit_price = close
            
            # Check TP
            if open_position.side == "long" and high >= open_position.tp_price:
                exit_price = open_position.tp_price
                exit_triggered = True
                exit_reason = "tp"
            elif open_position.side == "short" and low <= open_position.tp_price:
                exit_price = open_position.tp_price
                exit_triggered = True
                exit_reason = "tp"
            
            # Check SL
            elif open_position.side == "long" and low <= open_position.sl_price:
                exit_price = open_position.sl_price
                exit_triggered = True
                exit_reason = "sl"
            elif open_position.side == "short" and high >= open_position.sl_price:
                exit_price = open_position.sl_price
                exit_triggered = True
                exit_reason = "sl"
            
            # Check timeout
            elif (timestamp - open_position.entry_time).total_seconds() / 3600 >= timeout_hours:
                exit_triggered = True
                exit_reason = "timeout"
            
            if exit_triggered:
                # Close position
                if open_position.side == "long":
                    pnl_pct = (exit_price - open_position.entry_price) / open_position.entry_price
                else:
                    pnl_pct = (open_position.entry_price - exit_price) / open_position.entry_price
                
                open_position.exit_time = timestamp
                open_position.exit_price = exit_price
                open_position.pnl_pct = pnl_pct
                open_position.bars_held = len(trades) + 1  # Approximate
                open_position.exit_reason = exit_reason
                
                trades.append(open_position)
                open_position = None
                logger.debug(f"Exit {exit_reason}: {asset} {pnl_pct:.2%}")
        
        # Check for new entry if no position
        if open_position is None:
            snap = engine.snapshot()
            setup = engine._generate_signal(snap)
            
            # Log signal generation for debugging (sample every 50 bars and on signals)
            if bar_count % 50 == 0 or setup.side in ["long", "short"]:
                logger.info(
                    f"{asset} bar {bar_count}/{len(df_ohlc)}: signal={setup.side}, "
                    f"regime={setup.regime}, reason={setup.reason}, "
                    f"bb_pos={snap.bb_position:.3f}, rsi={snap.rsi:.1f}, "
                    f"touched_upper={snap.touched_upper}, touched_lower={snap.touched_lower}"
                )
            
            if setup.side in ["long", "short"]:
                # Create new position
                trade = BandTradeRecord(
                    asset=asset,
                    entry_time=timestamp,
                    exit_time=timestamp,  # Will update on exit
                    side=setup.side,
                    entry_price=setup.entry_price,
                    exit_price=0.0,  # Will update on exit
                    tp_price=setup.tp_price,
                    sl_price=setup.sl_price,
                    pnl_pct=0.0,  # Will update on exit
                    r_multiple=setup.r_multiple,
                    regime=setup.regime,
                    bb_position=setup.bb_position,
                    rsi=setup.rsi,
                    adx=setup.adx,
                    atr=snap.atr,
                    bb_sd_multiplier=cfg.bb_sd_multiplier,
                    signal_strength=setup.signal_strength,
                )
                open_position = trade
                logger.debug(f"Entry {asset} {setup.side} @ {setup.entry_price:.2f}")
    
    # Close any remaining position
    if open_position is not None:
        last_close = df_ohlc.iloc[-1]["close"]
        if open_position.side == "long":
            pnl_pct = (last_close - open_position.entry_price) / open_position.entry_price
        else:
            pnl_pct = (open_position.entry_price - last_close) / open_position.entry_price
        
        open_position.exit_time = df_ohlc.index[-1]
        open_position.exit_price = last_close
        open_position.pnl_pct = pnl_pct
        open_position.exit_reason = "timeout"
        trades.append(open_position)
    
    # Compute summary
    summary = _compute_summary(trades, cfg)
    
    logger.info(
        f"Backtest complete: {summary.total_trades} trades, "
        f"WR={summary.win_rate:.1%}, "
        f"Range WR={summary.range_win_rate:.1%}, "
        f"PnL={summary.total_pnl_pct:.2%}"
    )
    
    return trades, summary


def _compute_summary(
    trades: List[BandTradeRecord],
    config: BandStrategyConfig,
) -> BandBacktestSummary:
    """Aggregate trade records into performance metrics."""
    s = BandBacktestSummary()
    
    if not trades:
        return s
    
    s.asset = trades[0].asset
    s.total_trades = len(trades)
    s.long_trades = sum(1 for t in trades if t.side == "long")
    s.short_trades = sum(1 for t in trades if t.side == "short")
    
    # Basic metrics
    pnls = [t.pnl_pct for t in trades]
    s.wins = sum(1 for p in pnls if p > 0)
    s.losses = sum(1 for p in pnls if p <= 0)
    s.win_rate = s.wins / s.total_trades if s.total_trades > 0 else 0.0
    
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    s.avg_win_pct = np.mean(wins) if wins else 0.0
    s.avg_loss_pct = np.mean(losses) if losses else 0.0
    s.total_pnl_pct = sum(pnls)
    
    # Regime-aware metrics
    range_trades = [t for t in trades if t.regime == "range"]
    trend_trades = [t for t in trades if t.regime == "trend"]
    
    s.range_trades = len(range_trades)
    s.range_wins = sum(1 for t in range_trades if t.pnl_pct > 0)
    s.range_win_rate = s.range_wins / s.range_trades if s.range_trades > 0 else 0.0
    
    s.trend_trades = len(trend_trades)
    s.trend_wins = sum(1 for t in trend_trades if t.pnl_pct > 0)
    s.trend_win_rate = s.trend_wins / s.trend_trades if s.trend_trades > 0 else 0.0
    
    # Risk metrics
    equity = np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    drawdown = peak - equity
    s.max_drawdown_pct = float(np.max(drawdown)) if len(drawdown) > 0 else 0.0
    
    s.avg_r_multiple = np.mean([t.r_multiple for t in trades if t.r_multiple > 0])
    s.avg_bars_held = np.mean([t.bars_held for t in trades]) if trades else 0.0
    
    # Exit breakdown
    s.tp_exits = sum(1 for t in trades if t.exit_reason == "tp")
    s.sl_exits = sum(1 for t in trades if t.exit_reason == "sl")
    s.timeout_exits = sum(1 for t in trades if t.exit_reason == "timeout")
    
    # Config
    s.bb_sd_multiplier = config.bb_sd_multiplier
    s.sl_atr_multiplier = config.sl_atr_multiplier
    
    return s


# ═══════════════════════════════════════════════════════════════════════════
# Walk-Forward Validation
# ═══════════════════════════════════════════════════════════════════════════

def walk_forward_validation(
    df_ohlc: pd.DataFrame,
    asset: str = "BTC",
    opt_window_days: int = 90,
    fwd_window_days: int = 30,
    sd_range: Tuple[float, float] = (2.0, 2.5),
    sd_step: float = 0.1,
    sl_atr_range: Tuple[float, float] = (1.5, 2.0),
    sl_atr_step: float = 0.1,
) -> WalkForwardResult:
    """Run walk-forward validation with parameter optimization.
    
    Args:
        df_ohlc: OHLCV DataFrame with DatetimeIndex.
        asset: Asset symbol.
        opt_window_days: Days for optimization window.
        fwd_window_days: Days for forward test window.
        sd_range: Range of BB SD multipliers to test.
        sd_step: Step size for SD optimization.
        sl_atr_range: Range of SL ATR multipliers to test.
        sl_atr_step: Step size for SL ATR optimization.
    
    Returns:
        WalkForwardResult with per-window and aggregate metrics.
    """
    result = WalkForwardResult(
        asset=asset,
        opt_window_days=opt_window_days,
        fwd_window_days=fwd_window_days,
    )
    
    # Generate parameter grid
    sd_values = np.arange(sd_range[0], sd_range[1] + sd_step, sd_step)
    sl_atr_values = np.arange(sl_atr_range[0], sl_atr_range[1] + sl_atr_step, sl_atr_step)
    
    param_grid = [(sd, sl) for sd in sd_values for sl in sl_atr_values]
    
    logger.info(
        f"Walk-forward {asset}: {len(param_grid)} param combos, "
        f"opt={opt_window_days}d, fwd={fwd_window_days}d"
    )
    
    # Calculate window boundaries
    start_date = df_ohlc.index[0]
    end_date = df_ohlc.index[-1]
    total_days = (end_date - start_date).days
    
    opt_start = start_date
    window_idx = 0
    
    while True:
        opt_end = opt_start + timedelta(days=opt_window_days)
        fwd_start = opt_end
        fwd_end = fwd_start + timedelta(days=fwd_window_days)
        
        if fwd_end > end_date:
            break
        
        # Optimization window
        opt_data = df_ohlc.loc[opt_start:opt_end]
        fwd_data = df_ohlc.loc[fwd_start:fwd_end]
        
        if len(opt_data) < 200 or len(fwd_data) < 100:
            logger.warning(f"Window {window_idx}: insufficient data, skipping")
            opt_start = fwd_start
            window_idx += 1
            continue
        
        # Optimize parameters on opt window
        best_params = None
        best_range_wr = 0.0
        
        for sd, sl_atr in param_grid:
            cfg = BandStrategyConfig(asset=asset, bb_sd_multiplier=sd, sl_atr_multiplier=sl_atr)
            _, summary = backtest_band_strategy(opt_data, asset, cfg)
            
            # Optimize for range win rate (target 80%+)
            if summary.range_trades >= 10 and summary.range_win_rate > best_range_wr:
                best_range_wr = summary.range_win_rate
                best_params = (sd, sl_atr)
        
        if best_params is None:
            logger.warning(f"Window {window_idx}: no valid params found, using defaults")
            best_params = (2.1, 1.5)
        
        # Test on forward window with best params
        best_sd, best_sl_atr = best_params
        test_cfg = BandStrategyConfig(asset=asset, bb_sd_multiplier=best_sd, sl_atr_multiplier=best_sl_atr)
        test_trades, test_summary = backtest_band_strategy(fwd_data, asset, test_cfg)
        
        # Record window results
        window_result = {
            "window_idx": window_idx,
            "opt_start": opt_start.isoformat(),
            "opt_end": opt_end.isoformat(),
            "fwd_start": fwd_start.isoformat(),
            "fwd_end": fwd_end.isoformat(),
            "best_sd": best_sd,
            "best_sl_atr": best_sl_atr,
            "fwd_trades": test_summary.total_trades,
            "fwd_win_rate": test_summary.win_rate,
            "fwd_range_win_rate": test_summary.range_win_rate,
            "fwd_pnl_pct": test_summary.total_pnl_pct,
        }
        result.windows.append(window_result)
        
        logger.info(
            f"Window {window_idx}: SD={best_sd:.1f}, SL={best_sl_atr:.1f}, "
            f"FWD WR={test_summary.win_rate:.1%}, Range WR={test_summary.range_win_rate:.1%}"
        )
        
        # Move to next window
        opt_start = fwd_start
        window_idx += 1
    
    # Compute aggregate metrics
    if result.windows:
        result.total_trades = sum(w["fwd_trades"] for w in result.windows)
        
        total_wins = sum(w["fwd_trades"] * w["fwd_win_rate"] for w in result.windows)
        result.aggregate_win_rate = total_wins / result.total_trades if result.total_trades > 0 else 0.0
        
        # Range-weighted aggregate
        range_trades_total = sum(
            w["fwd_trades"] for w in result.windows if w["fwd_range_win_rate"] > 0
        )
        range_wins_total = sum(
            w["fwd_trades"] * w["fwd_range_win_rate"] for w in result.windows
        )
        result.aggregate_range_win_rate = range_wins_total / range_trades_total if range_trades_total > 0 else 0.0
        
        # Average window win rate
        result.avg_window_win_rate = np.mean([w["fwd_win_rate"] for w in result.windows])
        
        # Consistency: % of windows with >65% win rate
        good_windows = sum(1 for w in result.windows if w["fwd_win_rate"] >= 0.65)
        result.consistency_score = good_windows / len(result.windows) if result.windows else 0.0
    
    logger.info(
        f"Walk-forward complete: {len(result.windows)} windows, "
        f"Aggregate WR={result.aggregate_win_rate:.1%}, "
        f"Range WR={result.aggregate_range_win_rate:.1%}, "
        f"Consistency={result.consistency_score:.1%}"
    )
    
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Parameter Grid Search
# ═══════════════════════════════════════════════════════════════════════════

def grid_search_band_params(
    df_ohlc: pd.DataFrame,
    asset: str = "BTC",
    sd_range: Tuple[float, float] = (2.0, 2.5),
    sd_step: float = 0.1,
    sl_atr_range: Tuple[float, float] = (1.5, 2.0),
    sl_atr_step: float = 0.1,
) -> pd.DataFrame:
    """Grid search over BB SD and SL ATR parameters.
    
    Args:
        df_ohlc: OHLCV DataFrame.
        asset: Asset symbol.
        sd_range: Range of BB SD multipliers.
        sd_step: Step size for SD.
        sl_atr_range: Range of SL ATR multipliers.
        sl_atr_step: Step size for SL ATR.
    
    Returns:
        DataFrame with one row per parameter combo and summary stats.
    """
    sd_values = np.arange(sd_range[0], sd_range[1] + sd_step, sd_step)
    sl_atr_values = np.arange(sl_atr_range[0], sl_atr_range[1] + sl_atr_step, sl_atr_step)
    
    results = []
    total_combos = len(sd_values) * len(sl_atr_values)
    
    logger.info(f"Grid search {asset}: {total_combos} parameter combinations")
    
    for sd in sd_values:
        for sl_atr in sl_atr_values:
            cfg = BandStrategyConfig(asset=asset, bb_sd_multiplier=sd, sl_atr_multiplier=sl_atr)
            _, summary = backtest_band_strategy(df_ohlc, asset, cfg)
            
            results.append({
                "asset": asset,
                "bb_sd": sd,
                "sl_atr": sl_atr,
                "total_trades": summary.total_trades,
                "win_rate": summary.win_rate,
                "range_win_rate": summary.range_win_rate,
                "total_pnl_pct": summary.total_pnl_pct,
                "max_drawdown_pct": summary.max_drawdown_pct,
                "avg_r_multiple": summary.avg_r_multiple,
                "tp_exits": summary.tp_exits,
                "sl_exits": summary.sl_exits,
            })
    
    df_results = pd.DataFrame(results)
    if not df_results.empty:
        # Sort by range win rate (primary) then total PnL (secondary)
        df_results = df_results.sort_values(["range_win_rate", "total_pnl_pct"], ascending=[False, False])
    
    return df_results


# ═══════════════════════════════════════════════════════════════════════════
# Trade Log Export
# ═══════════════════════════════════════════════════════════════════════════

def trades_to_dataframe(trades: List[BandTradeRecord]) -> pd.DataFrame:
    """Convert trade records to DataFrame for analysis/export."""
    if not trades:
        return pd.DataFrame()
    
    rows = [t.to_dict() for t in trades]
    return pd.DataFrame(rows)


def windows_to_dataframe(result: WalkForwardResult) -> pd.DataFrame:
    """Convert walk-forward windows to DataFrame."""
    if not result.windows:
        return pd.DataFrame()
    
    return pd.DataFrame(result.windows)
