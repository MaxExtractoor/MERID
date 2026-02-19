"""Backtest Visualization — Equity curves, PnL distributions, regime analysis.

Generates data structures (and optional matplotlib plots) for visualizing
backtest and paper session results.  All functions return plain dicts/lists
so they work headless (CI, API) and can optionally render with matplotlib.

Usage::

    from merid.event_venues.kalshi.backtest_viz import (
        equity_curve_data, pnl_distribution_data, regime_metrics,
        BacktestViz,
    )

    viz = BacktestViz(trade_log, initial_equity_usd=100.0)
    curve = viz.equity_curve()
    dist = viz.pnl_distribution(bins=50)
    regimes = viz.regime_breakdown(vol_threshold=2.0)
    viz.render_to_file("btc_hourly_backtest.png")  # optional matplotlib
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.backtest_viz")


# ── Data structures ──────────────────────────────────────────────────────

@dataclass
class TradeRecord:
    """Normalized trade record for visualization."""
    ts: float
    pnl_cents: float
    price_cents: int = 50
    side: str = ""
    ticker: str = ""
    fee_cents: float = 0.0


# ── Equity curve ─────────────────────────────────────────────────────────

def equity_curve_data(
    trades: List[TradeRecord],
    initial_equity_cents: float = 0.0,
) -> Dict[str, Any]:
    """Compute equity curve from a trade log.

    Returns:
        Dict with "timestamps", "equity_cents", "equity_usd",
        "high_water_mark_cents", "drawdown_cents", "drawdown_pct".
    """
    timestamps: List[float] = []
    equity_cents: List[float] = []
    hwm_cents: List[float] = []
    dd_cents: List[float] = []
    dd_pct: List[float] = []

    current = initial_equity_cents
    hwm = initial_equity_cents

    for trade in sorted(trades, key=lambda t: t.ts):
        current += trade.pnl_cents
        if current > hwm:
            hwm = current
        dd = hwm - current
        pct = (dd / hwm * 100) if hwm > 0 else 0.0

        timestamps.append(trade.ts)
        equity_cents.append(current)
        hwm_cents.append(hwm)
        dd_cents.append(dd)
        dd_pct.append(pct)

    return {
        "timestamps": timestamps,
        "equity_cents": equity_cents,
        "equity_usd": [c / 100.0 for c in equity_cents],
        "high_water_mark_cents": hwm_cents,
        "drawdown_cents": dd_cents,
        "drawdown_pct": dd_pct,
        "final_equity_cents": current,
        "max_drawdown_cents": max(dd_cents) if dd_cents else 0.0,
        "trade_count": len(trades),
    }


# ── PnL distribution ────────────────────────────────────────────────────

def pnl_distribution_data(
    trades: List[TradeRecord],
    bins: int = 30,
) -> Dict[str, Any]:
    """Compute PnL distribution histogram data.

    Returns:
        Dict with "bin_edges", "counts", "mean", "median", "std",
        "skew", "min", "max", "positive_pct", "negative_pct".
    """
    if not trades:
        return {
            "bin_edges": [], "counts": [], "mean": 0, "median": 0,
            "std": 0, "skew": 0, "min": 0, "max": 0,
            "positive_pct": 0, "negative_pct": 0, "trade_count": 0,
        }

    pnls = [t.pnl_cents for t in trades]
    n = len(pnls)

    mean = statistics.mean(pnls)
    median = statistics.median(pnls)
    std = statistics.stdev(pnls) if n > 1 else 0.0

    # Skewness (Fisher)
    if std > 0 and n > 2:
        skew = sum(((x - mean) / std) ** 3 for x in pnls) * n / ((n - 1) * (n - 2))
    else:
        skew = 0.0

    pnl_min = min(pnls)
    pnl_max = max(pnls)
    positive = sum(1 for p in pnls if p > 0)
    negative = sum(1 for p in pnls if p < 0)

    # Simple histogram binning
    if pnl_max == pnl_min:
        bin_edges = [pnl_min, pnl_max + 1]
        counts = [n]
    else:
        step = (pnl_max - pnl_min) / bins
        bin_edges = [pnl_min + i * step for i in range(bins + 1)]
        counts = [0] * bins
        for p in pnls:
            idx = min(int((p - pnl_min) / step), bins - 1)
            counts[idx] += 1

    return {
        "bin_edges": [round(e, 2) for e in bin_edges],
        "counts": counts,
        "mean": round(mean, 2),
        "median": round(median, 2),
        "std": round(std, 2),
        "skew": round(skew, 3),
        "min": round(pnl_min, 2),
        "max": round(pnl_max, 2),
        "positive_pct": round(positive / n * 100, 1),
        "negative_pct": round(negative / n * 100, 1),
        "trade_count": n,
    }


# ── Regime breakdown ─────────────────────────────────────────────────────

def regime_metrics(
    trades: List[TradeRecord],
    vol_threshold_cents: float = 200.0,
    window_size: int = 20,
) -> Dict[str, Any]:
    """Break down PF and expectancy by volatility regime.

    Classifies each trade's local environment as "calm" or "volatile"
    based on rolling PnL standard deviation.

    Args:
        trades: Trade records sorted by timestamp.
        vol_threshold_cents: Std dev threshold to classify as volatile.
        window_size: Rolling window for vol estimation.

    Returns:
        Dict with "calm" and "volatile" sub-dicts containing PF,
        expectancy, win_rate, trade_count.
    """
    sorted_trades = sorted(trades, key=lambda t: t.ts)

    calm_trades: List[TradeRecord] = []
    vol_trades: List[TradeRecord] = []

    pnl_window: List[float] = []

    for trade in sorted_trades:
        pnl_window.append(trade.pnl_cents)
        if len(pnl_window) > window_size:
            pnl_window.pop(0)

        if len(pnl_window) >= 2:
            local_vol = statistics.stdev(pnl_window)
        else:
            local_vol = 0.0

        if local_vol >= vol_threshold_cents:
            vol_trades.append(trade)
        else:
            calm_trades.append(trade)

    def _compute(group: List[TradeRecord], label: str) -> Dict[str, Any]:
        if not group:
            return {
                "label": label, "trade_count": 0, "win_rate_pct": 0,
                "profit_factor": 0, "expectancy_cents": 0, "net_pnl_cents": 0,
            }
        wins = [t for t in group if t.pnl_cents > 0]
        losses = [t for t in group if t.pnl_cents < 0]
        gross_wins = sum(t.pnl_cents for t in wins)
        gross_losses = abs(sum(t.pnl_cents for t in losses))
        total = len(wins) + len(losses)
        wr = len(wins) / total * 100 if total > 0 else 0
        pf = gross_wins / gross_losses if gross_losses > 0 else (float("inf") if gross_wins > 0 else 0)
        avg_win = gross_wins / len(wins) if wins else 0
        avg_loss = gross_losses / len(losses) if losses else 0
        exp = (len(wins) / total * avg_win - len(losses) / total * avg_loss) if total > 0 else 0

        return {
            "label": label,
            "trade_count": len(group),
            "win_rate_pct": round(wr, 1),
            "profit_factor": round(pf, 2) if pf != float("inf") else "inf",
            "expectancy_cents": round(exp, 2),
            "net_pnl_cents": round(sum(t.pnl_cents for t in group), 2),
        }

    return {
        "calm": _compute(calm_trades, "calm"),
        "volatile": _compute(vol_trades, "volatile"),
        "vol_threshold_cents": vol_threshold_cents,
        "window_size": window_size,
    }


# ── BacktestViz class ───────────────────────────────────────────────────

class BacktestViz:
    """Convenience wrapper for generating all visualization data."""

    def __init__(
        self,
        trades: List[TradeRecord],
        initial_equity_cents: float = 0.0,
    ) -> None:
        self._trades = sorted(trades, key=lambda t: t.ts)
        self._initial = initial_equity_cents

    def equity_curve(self) -> Dict[str, Any]:
        return equity_curve_data(self._trades, self._initial)

    def pnl_distribution(self, bins: int = 30) -> Dict[str, Any]:
        return pnl_distribution_data(self._trades, bins)

    def regime_breakdown(
        self, vol_threshold_cents: float = 200.0, window_size: int = 20,
    ) -> Dict[str, Any]:
        return regime_metrics(self._trades, vol_threshold_cents, window_size)

    def full_report(self, bins: int = 30) -> Dict[str, Any]:
        """Generate all visualization data in one call."""
        return {
            "equity_curve": self.equity_curve(),
            "pnl_distribution": self.pnl_distribution(bins),
            "regime_breakdown": self.regime_breakdown(),
        }

    def render_to_file(self, path: str, bins: int = 30) -> bool:
        """Render equity curve + PnL histogram to a PNG file.

        Requires matplotlib. Returns False if matplotlib is unavailable.
        """
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            logger.warning("matplotlib not available — skipping render")
            return False

        curve = self.equity_curve()
        dist = self.pnl_distribution(bins)

        fig, axes = plt.subplots(2, 1, figsize=(10, 8))

        # Equity curve
        axes[0].plot(curve["timestamps"], curve["equity_usd"])
        axes[0].set_title("Equity Curve")
        axes[0].set_ylabel("Equity (USD)")
        axes[0].grid(True, alpha=0.3)

        # PnL histogram
        if dist["bin_edges"] and dist["counts"]:
            edges = dist["bin_edges"]
            widths = [edges[i + 1] - edges[i] for i in range(len(edges) - 1)]
            axes[1].bar(edges[:-1], dist["counts"], width=widths, align="edge", alpha=0.7)
        axes[1].set_title(f"Trade PnL Distribution (n={dist['trade_count']})")
        axes[1].set_xlabel("PnL (cents)")
        axes[1].set_ylabel("Count")
        axes[1].grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(path, dpi=100)
        plt.close(fig)
        logger.info(f"Backtest visualization saved to {path}")
        return True
