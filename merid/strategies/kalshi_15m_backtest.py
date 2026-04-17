"""
Kalshi 15m Crypto Up/Down Backtest
===================================
Backtest scaffold for EMA(50) + RSI + MACD + ATR indicator stack
on Kalshi BTC/ETH/SOL 15-minute Up/Down markets.

Consumes:
  - ``df_price``: 1m or 5m OHLCV spot data (BTC, ETH, etc.)
  - ``df_kalshi``: 15m Kalshi market records with settlement outcomes

Produces:
  - Per-trade log with indicators, fees, PnL
  - Aggregate stats: hit rate, net PnL, fee drag %, Sharpe, drawdown

Usage::

    from merid.strategies.kalshi_15m_backtest import backtest_kalshi_15m

    results, summary = backtest_kalshi_15m(df_price, df_kalshi, contracts=10)
    print(summary)
"""

import math
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

import numpy as np
import pandas as pd

from merid.signals.crypto_15m_indicators import (
    Crypto15mIndicatorStack,
    IndicatorConfig,
    IndicatorSnapshot,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class TradeRecord:
    """Single backtest trade with full indicator context."""

    market_id: str
    entry_time: Any                # pd.Timestamp or str
    close_time: Any
    side: str                      # "UP" or "DOWN"
    entry_price: float             # Kalshi price 0-1 (or 0-100 cents)
    outcome: int                   # 1 = Up wins, 0 = Down wins
    pnl_cents: float               # net PnL in cents after fees
    fee_cents: float               # Kalshi fee in cents
    contracts: int

    # Indicator snapshot at entry
    ema_trend: float = 0.0
    price_above_trend_ema: bool = False
    ema_fast: float = 0.0
    ema_slow: float = 0.0
    ema_cross: str = "neutral"
    rsi: float = 50.0
    macd_histogram: float = 0.0
    macd_cross: str = "neutral"
    atr: float = 0.0
    vol_band: str = "mid"
    chop_detected: bool = False
    bias: str = "neutral"
    bias_confidence: float = 0.0
    spot_price: float = 0.0
    
    # Spot metadata for observability and policy enforcement
    spot_source: str = ""  # 'coinbase', 'binanceus', 'coingecko', 'coinbase_cache', etc.
    spot_is_stale: bool = False
    spot_age_seconds: float = 0.0


@dataclass
class BacktestSummary:
    """Aggregate backtest performance metrics."""

    total_trades: int = 0
    up_trades: int = 0
    down_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_pnl_cents: float = 0.0
    avg_pnl_per_trade: float = 0.0
    total_fees_cents: float = 0.0
    fee_drag_pct: float = 0.0      # fees / (gross PnL + fees)
    max_drawdown_cents: float = 0.0
    sharpe_ratio: float = 0.0
    avg_entry_price: float = 0.0
    skipped_no_signal: int = 0
    skipped_gate_blocked: int = 0


# ═══════════════════════════════════════════════════════════════════════════
# Fee helpers
# ═══════════════════════════════════════════════════════════════════════════


def kalshi_fee_cents(price_cents: float, contracts: int = 1) -> float:
    """Kalshi taker fee: ceil(0.07 * contracts * P * (1-P))."""
    p = price_cents / 100.0
    return math.ceil(0.07 * contracts * p * (1.0 - p))


def trade_pnl_cents(
    side: str,
    entry_price_cents: float,
    outcome: int,
    contracts: int,
) -> tuple:
    """Compute (gross_pnl, fee, net_pnl) in cents for a binary trade.

    Args:
        side: "UP" or "DOWN".
        entry_price_cents: Kalshi price in cents (0-100).
        outcome: 1 if Up wins, 0 if Down wins.
        contracts: Number of contracts.

    Returns:
        (gross_pnl_cents, fee_cents, net_pnl_cents)
    """
    fee = kalshi_fee_cents(entry_price_cents, contracts)

    if side == "UP":
        if outcome == 1:
            gross = (100.0 - entry_price_cents) * contracts
        else:
            gross = -entry_price_cents * contracts
    else:  # DOWN
        down_price = 100.0 - entry_price_cents
        if outcome == 0:
            gross = (100.0 - down_price) * contracts
        else:
            gross = -down_price * contracts

    net = gross - fee
    return gross, fee, net


# ═══════════════════════════════════════════════════════════════════════════
# Core backtest engine
# ═══════════════════════════════════════════════════════════════════════════


def backtest_kalshi_15m(
    df_price: pd.DataFrame,
    df_kalshi: pd.DataFrame,
    contracts: int = 10,
    config: Optional[IndicatorConfig] = None,
    require_trend_aligned: bool = True,
    require_trade_allowed: bool = True,
) -> tuple:
    """Run a backtest of the EMA(50)+RSI+MACD+ATR indicator stack on Kalshi 15m markets.

    Args:
        df_price: Spot price DataFrame with DatetimeIndex and 'close' column (1m or 5m).
        df_kalshi: Kalshi markets DataFrame with columns:
            - market_id: str
            - open_time: datetime — market open (or entry time)
            - close_time: datetime — market settlement time
            - settle: int — 1 if Up wins, 0 if Down wins
            - entry_price: float — Kalshi YES price in cents (0-100) at entry
        contracts: Number of contracts per trade.
        config: Optional IndicatorConfig override.
        require_trend_aligned: Skip trades where trend_aligned is False.
        require_trade_allowed: Skip trades where trade_allowed is False.

    Returns:
        (trades: List[TradeRecord], summary: BacktestSummary)
    """
    stack = Crypto15mIndicatorStack(config)
    trades: List[TradeRecord] = []
    skipped_no_signal = 0
    skipped_gate_blocked = 0

    # Sort Kalshi markets by open time
    df_kalshi = df_kalshi.sort_values("open_time").reset_index(drop=True)

    # Ensure price data is sorted
    df_price = df_price.sort_index()

    logger.info(
        f"Backtest: {len(df_kalshi)} Kalshi markets, "
        f"{len(df_price)} price bars, contracts={contracts}"
    )

    for _, mkt in df_kalshi.iterrows():
        t_entry = pd.Timestamp(mkt["open_time"])
        t_close = pd.Timestamp(mkt["close_time"])
        entry_price_cents = float(mkt["entry_price"])
        outcome = int(mkt["settle"])
        market_id = str(mkt["market_id"])

        # ── Feed price bars up to entry time into indicator stack ─────
        price_slice = df_price.loc[:t_entry]
        if price_slice.empty:
            skipped_no_signal += 1
            continue

        # Reset stack for each market (walk-forward would keep state)
        stack = Crypto15mIndicatorStack(config)
        for _, row in price_slice.tail(stack.cfg.max_bars).iterrows():
            stack.update(float(row["close"]))

        snap = stack.snapshot()

        # ── Apply gates ───────────────────────────────────────────────
        if require_trade_allowed and not snap.trade_allowed:
            skipped_gate_blocked += 1
            continue

        if require_trend_aligned and not snap.trend_aligned:
            skipped_gate_blocked += 1
            continue

        # ── Generate signal from bias ─────────────────────────────────
        side = None
        if snap.bias == "up":
            side = "UP"
        elif snap.bias == "down":
            side = "DOWN"
        else:
            skipped_no_signal += 1
            continue

        # ── Compute PnL ──────────────────────────────────────────────
        gross, fee, net = trade_pnl_cents(side, entry_price_cents, outcome, contracts)

        trade = TradeRecord(
            market_id=market_id,
            entry_time=t_entry,
            close_time=t_close,
            side=side,
            entry_price=entry_price_cents,
            outcome=outcome,
            pnl_cents=net,
            fee_cents=fee,
            contracts=contracts,
            ema_trend=snap.ema_trend,
            price_above_trend_ema=snap.price_above_trend_ema,
            ema_fast=snap.ema_fast,
            ema_slow=snap.ema_slow,
            ema_cross=snap.ema_cross,
            rsi=snap.rsi,
            macd_histogram=snap.macd_histogram,
            macd_cross=snap.macd_cross,
            atr=snap.atr,
            vol_band=snap.vol_band,
            chop_detected=snap.chop_detected,
            bias=snap.bias,
            bias_confidence=snap.bias_confidence,
            spot_price=snap.price,
        )
        trades.append(trade)

    # ── Compute summary ──────────────────────────────────────────────
    summary = _compute_summary(trades, skipped_no_signal, skipped_gate_blocked)

    logger.info(
        f"Backtest complete: {summary.total_trades} trades, "
        f"PnL={summary.total_pnl_cents:.0f}c, "
        f"WR={summary.win_rate:.1%}, "
        f"fee_drag={summary.fee_drag_pct:.1%}"
    )

    return trades, summary


def _compute_summary(
    trades: List[TradeRecord],
    skipped_no_signal: int,
    skipped_gate_blocked: int,
) -> BacktestSummary:
    """Aggregate trade records into performance metrics."""
    s = BacktestSummary()
    s.skipped_no_signal = skipped_no_signal
    s.skipped_gate_blocked = skipped_gate_blocked

    if not trades:
        return s

    s.total_trades = len(trades)
    s.up_trades = sum(1 for t in trades if t.side == "UP")
    s.down_trades = sum(1 for t in trades if t.side == "DOWN")

    pnls = [t.pnl_cents for t in trades]
    fees = [t.fee_cents for t in trades]

    s.wins = sum(1 for p in pnls if p > 0)
    s.losses = sum(1 for p in pnls if p <= 0)
    s.win_rate = s.wins / s.total_trades if s.total_trades > 0 else 0.0

    s.total_pnl_cents = sum(pnls)
    s.avg_pnl_per_trade = s.total_pnl_cents / s.total_trades
    s.total_fees_cents = sum(fees)

    gross_plus_fees = s.total_pnl_cents + s.total_fees_cents
    s.fee_drag_pct = (
        s.total_fees_cents / gross_plus_fees
        if gross_plus_fees > 0
        else float("nan")
    )

    s.avg_entry_price = np.mean([t.entry_price for t in trades])

    # Drawdown
    equity = np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    drawdown = peak - equity
    s.max_drawdown_cents = float(np.max(drawdown)) if len(drawdown) > 0 else 0.0

    # Sharpe (annualized assuming ~96 15m periods per day, 365 days)
    if len(pnls) > 1:
        pnl_arr = np.array(pnls)
        mean_pnl = np.mean(pnl_arr)
        std_pnl = np.std(pnl_arr, ddof=1)
        if std_pnl > 0:
            daily_trades = 96  # 15m markets per day
            s.sharpe_ratio = (mean_pnl / std_pnl) * np.sqrt(daily_trades * 365)
        else:
            s.sharpe_ratio = 0.0

    return s


# ═══════════════════════════════════════════════════════════════════════════
# Grid search / parameter sweep
# ═══════════════════════════════════════════════════════════════════════════


def grid_search_params(
    df_price: pd.DataFrame,
    df_kalshi: pd.DataFrame,
    contracts: int = 10,
    ema_trend_periods: List[int] = None,
    rsi_periods: List[int] = None,
    macd_configs: List[tuple] = None,
) -> pd.DataFrame:
    """Run grid search over indicator parameters.

    Args:
        df_price: Spot price data.
        df_kalshi: Kalshi market data.
        contracts: Contracts per trade.
        ema_trend_periods: List of EMA trend periods to test (default: [30, 50, 75]).
        rsi_periods: List of RSI periods (default: [7, 8, 10, 14]).
        macd_configs: List of (fast, slow, signal) tuples (default: [(8,21,5), (12,26,9)]).

    Returns:
        DataFrame with one row per parameter combo and summary stats.
    """
    if ema_trend_periods is None:
        ema_trend_periods = [30, 50, 75]
    if rsi_periods is None:
        rsi_periods = [7, 8, 10, 14]
    if macd_configs is None:
        macd_configs = [(8, 21, 5), (12, 26, 9)]

    results = []

    total_combos = len(ema_trend_periods) * len(rsi_periods) * len(macd_configs)
    logger.info(f"Grid search: {total_combos} parameter combinations")

    for ema_p in ema_trend_periods:
        for rsi_p in rsi_periods:
            for macd_f, macd_s, macd_sig in macd_configs:
                cfg = IndicatorConfig(
                    ema_trend_period=ema_p,
                    rsi_period=rsi_p,
                    macd_fast=macd_f,
                    macd_slow=macd_s,
                    macd_signal=macd_sig,
                    min_bars_required=max(52, ema_p + 2),
                )
                _, summary = backtest_kalshi_15m(
                    df_price, df_kalshi, contracts=contracts, config=cfg
                )
                results.append({
                    "ema_trend": ema_p,
                    "rsi_period": rsi_p,
                    "macd": f"{macd_f}-{macd_s}-{macd_sig}",
                    "trades": summary.total_trades,
                    "win_rate": summary.win_rate,
                    "total_pnl": summary.total_pnl_cents,
                    "avg_pnl": summary.avg_pnl_per_trade,
                    "fee_drag": summary.fee_drag_pct,
                    "max_dd": summary.max_drawdown_cents,
                    "sharpe": summary.sharpe_ratio,
                    "skipped_gate": summary.skipped_gate_blocked,
                    "skipped_signal": summary.skipped_no_signal,
                })

    df_results = pd.DataFrame(results)
    if not df_results.empty:
        df_results = df_results.sort_values("total_pnl", ascending=False)

    return df_results


# ═══════════════════════════════════════════════════════════════════════════
# Trade log export
# ═══════════════════════════════════════════════════════════════════════════


def trades_to_dataframe(trades: List[TradeRecord]) -> pd.DataFrame:
    """Convert trade records to a DataFrame for analysis/export."""
    if not trades:
        return pd.DataFrame()

    rows = []
    for t in trades:
        rows.append({
            "market_id": t.market_id,
            "entry_time": t.entry_time,
            "close_time": t.close_time,
            "side": t.side,
            "entry_price": t.entry_price,
            "outcome": t.outcome,
            "pnl_cents": t.pnl_cents,
            "fee_cents": t.fee_cents,
            "contracts": t.contracts,
            "ema_trend": round(t.ema_trend, 2),
            "price_above_trend": t.price_above_trend_ema,
            "ema_cross": t.ema_cross,
            "rsi": round(t.rsi, 2),
            "macd_histogram": round(t.macd_histogram, 4),
            "macd_cross": t.macd_cross,
            "atr": round(t.atr, 2),
            "vol_band": t.vol_band,
            "chop_detected": t.chop_detected,
            "bias": t.bias,
            "bias_confidence": round(t.bias_confidence, 3),
            "spot_price": round(t.spot_price, 2),
            "spot_source": t.spot_source,
            "spot_is_stale": t.spot_is_stale,
            "spot_age_seconds": round(t.spot_age_seconds, 1),
        })
    return pd.DataFrame(rows)
