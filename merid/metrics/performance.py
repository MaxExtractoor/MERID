"""Performance metrics for MERID trading sessions.

Computes win rate, profit factor, R:R ratio, expectancy, Sharpe, and
max drawdown from a list of closed trade records.  Designed to be called
from any layer (paper session, fills ledger, backtests) without pulling in
heavy trading-stack dependencies.

Usage::

    from merid.metrics.performance import compute_performance_metrics, TradeRecord

    records = [TradeRecord(...), ...]
    summary = compute_performance_metrics(records)
    print(summary.win_rate_pct, summary.profit_factor)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TradeRecord:
    """Minimal representation of a closed trade for metrics calculation.

    Units: pnl_cents is the net PnL in cents (positive = win, negative = loss).
    risk_cents is the maximum possible loss on the trade (entry cost for YES;
    100 - entry for NO on a binary).  0 means the risk is unknown.
    """
    trade_id: str
    pnl_cents: float          # net realised PnL after fees (cents)
    risk_cents: float = 0.0   # max risk on the trade (cents); 0 = unknown
    fees_cents: float = 0.0   # fees charged both legs (cents)


@dataclass
class PerformanceSummary:
    """Aggregated performance statistics for a set of closed trades."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0

    win_rate_pct: float = 0.0         # fraction with PnL > 0, as percentage 0–100
    profit_factor: float = 0.0        # gross_wins / gross_losses (inf if no losses)
    avg_pnl_cents: float = 0.0        # simple average PnL per trade (expectancy)
    avg_win_cents: float = 0.0        # average winning trade PnL
    avg_loss_cents: float = 0.0       # average losing trade PnL (positive value = loss)
    avg_rr_ratio: float = 0.0         # average win/loss ratio (payoff ratio)

    sharpe_ratio: float = 0.0         # Sharpe on per-trade returns (no annualisation)
    max_drawdown_pct: float = 0.0     # peak-to-trough drawdown as % of peak equity
    total_pnl_cents: float = 0.0
    total_fees_cents: float = 0.0

    meets_75pct_winrate: bool = False  # quick flag: win_rate_pct >= 75
    meets_promotion_floor: bool = False  # win_rate>=55 AND PF>=1.3 AND avg_pnl>5


def compute_performance_metrics(trades: List[TradeRecord]) -> PerformanceSummary:
    """Compute all performance statistics from a list of closed trade records.

    Args:
        trades: Closed trades (wins and losses mixed).

    Returns:
        PerformanceSummary with all metrics populated.  Returns a zeroed
        summary (safe to display) when the list is empty.
    """
    if not trades:
        return PerformanceSummary()

    pnls = [t.pnl_cents for t in trades]
    fees = [t.fees_cents for t in trades]

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]  # zero PnL counts as a loss

    total = len(pnls)
    n_wins = len(wins)
    win_rate = (n_wins / total * 100) if total else 0.0

    gross_wins = sum(wins)
    gross_losses = sum(abs(p) for p in losses)
    profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else float("inf")

    avg_pnl = sum(pnls) / total if total else 0.0
    avg_win = (sum(wins) / n_wins) if wins else 0.0
    avg_loss_abs = (sum(abs(p) for p in losses) / len(losses)) if losses else 0.0
    avg_rr = (avg_win / avg_loss_abs) if avg_loss_abs > 0 else float("inf")

    # Sharpe on per-trade returns (no annualisation factor — sample-level only)
    sharpe = 0.0
    if total >= 5:
        mean_r = avg_pnl
        variance = sum((p - mean_r) ** 2 for p in pnls) / (total - 1)
        std_r = math.sqrt(variance) if variance > 0 else 0.0
        sharpe = mean_r / std_r if std_r > 0 else 0.0

    # Max drawdown: simulate running equity curve from peak
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        equity += p
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    total_pnl = sum(pnls)
    total_fees = sum(fees)

    return PerformanceSummary(
        total_trades=total,
        winning_trades=n_wins,
        losing_trades=total - n_wins,
        win_rate_pct=round(win_rate, 2),
        profit_factor=round(profit_factor, 4) if math.isfinite(profit_factor) else profit_factor,
        avg_pnl_cents=round(avg_pnl, 4),
        avg_win_cents=round(avg_win, 4),
        avg_loss_cents=round(avg_loss_abs, 4),
        avg_rr_ratio=round(avg_rr, 4) if math.isfinite(avg_rr) else avg_rr,
        sharpe_ratio=round(sharpe, 4),
        max_drawdown_pct=round(max_dd, 4),
        total_pnl_cents=round(total_pnl, 4),
        total_fees_cents=round(total_fees, 4),
        meets_75pct_winrate=(win_rate >= 75.0),
        meets_promotion_floor=(win_rate >= 55.0 and profit_factor >= 1.3 and avg_pnl >= 5.0),
    )
