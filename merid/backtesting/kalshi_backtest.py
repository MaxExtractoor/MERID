"""
Kalshi 2-year backtest runner.

Fetches historical candlestick data from the Kalshi API, applies a
strategy function, and returns a BacktestReport that can be passed
directly into validate_before_lift() to gate phase promotions and
live-execution unlocks.

Usage:
    from merid.backtesting.kalshi_backtest import run_backtest_2y
    from merid.risk.btc_promotion_config import validate_before_lift

    report = await run_backtest_2y("KXBTC-24DEC31-B90000", my_strategy)
    result = validate_before_lift(report)
    if result["ok"]:
        lane.set_backtest_report(report)
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

from merid.risk.btc_promotion_config import BacktestReport

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# History fetch
# ---------------------------------------------------------------------------

async def fetch_kalshi_history(
    ticker: str,
    years: int = 2,
    resolution: str = "1h",
) -> List[Dict]:
    """
    Fetch OHLCV candles from the Kalshi candlesticks endpoint.

    Returns a list of dicts with keys: t (timestamp), o, h, l, c, v.
    Returns [] on any error so the backtest can fail gracefully.
    """
    try:
        from merid.event_venues.kalshi.client import get_kalshi_client
        client = get_kalshi_client()

        end_ts = datetime.now(timezone.utc)
        start_ts = end_ts - timedelta(days=365 * years)

        candles = await client.get_candles(
            market_ticker=ticker,
            start=start_ts,
            end=end_ts,
            resolution=resolution,
        )
        logger.info(
            "fetch_kalshi_history: %d candles for %s (%dy %s)",
            len(candles), ticker, years, resolution,
        )
        return candles or []
    except Exception as exc:
        logger.error("fetch_kalshi_history failed for %s: %s", ticker, exc)
        return []


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

def _compute_metrics(returns: List[float], equity_curve: List[float]) -> Dict:
    """Compute max drawdown and annualised Sharpe from return series."""
    # Max drawdown
    peak = equity_curve[0] if equity_curve else 1.0
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / max(peak, 1e-9)
        if dd > max_dd:
            max_dd = dd

    # Sharpe (annualised, assuming hourly bars → 8760 bars/year)
    n = len(returns)
    if n < 2:
        sharpe = 0.0
    else:
        mean = sum(returns) / n
        variance = sum((r - mean) ** 2 for r in returns) / n
        std = math.sqrt(variance) if variance > 0 else 1e-9
        sharpe = (mean / std) * math.sqrt(8760)

    return {"max_drawdown": max_dd, "sharpe": sharpe}


async def run_backtest_2y(
    ticker: str,
    strategy_fn: Callable[[List[Dict]], List[float]],
    years: int = 2,
    resolution: str = "1h",
) -> BacktestReport:
    """
    Run a 2-year backtest for `ticker` using `strategy_fn`.

    strategy_fn(candles) -> List[float]
        Receives the raw candle list and returns a per-bar return series
        (same length as candles; use 0.0 for bars with no position).

    Returns a BacktestReport ready for validate_before_lift().
    """
    candles = await fetch_kalshi_history(ticker, years=years, resolution=resolution)

    if len(candles) < 10:
        logger.warning(
            "run_backtest_2y: insufficient data for %s (%d candles) — returning empty report",
            ticker, len(candles),
        )
        return BacktestReport(
            equity_curve=[1.0],
            returns=[],
            max_drawdown=1.0,
            sharpe=0.0,
            trades=0,
            years=0.0,
        )

    # Apply strategy
    try:
        returns = strategy_fn(candles)
    except Exception as exc:
        logger.error("run_backtest_2y: strategy_fn raised %s", exc)
        returns = [0.0] * len(candles)

    # Ensure same length
    returns = list(returns)
    if len(returns) != len(candles):
        logger.warning(
            "run_backtest_2y: strategy_fn returned %d returns for %d candles — padding",
            len(returns), len(candles),
        )
        returns = (returns + [0.0] * len(candles))[: len(candles)]

    # Build equity curve (starting at 1.0)
    equity = 1.0
    equity_curve: List[float] = []
    for r in returns:
        equity *= (1.0 + r)
        equity_curve.append(equity)

    # Metrics
    metrics = _compute_metrics(returns, equity_curve)
    trades = sum(1 for r in returns if r != 0.0)

    # Years from candle timestamps
    try:
        t_first = candles[0].get("t") or candles[0].get("timestamp")
        t_last  = candles[-1].get("t") or candles[-1].get("timestamp")
        if isinstance(t_first, str):
            try:
                from dateutil.parser import parse as _parse
                t_first = _parse(t_first)
                t_last  = _parse(t_last)
            except ImportError:
                # stdlib fallback: strip trailing Z and parse ISO 8601
                t_first = datetime.fromisoformat(t_first.rstrip("Z").replace("Z", "+00:00"))
                t_last  = datetime.fromisoformat(t_last.rstrip("Z").replace("Z", "+00:00"))
        actual_years = (t_last - t_first).days / 365.0
    except Exception as _de:
        logger.debug("backtest actual_years parse failed, using nominal: %s", _de)
        actual_years = float(years)

    report = BacktestReport(
        equity_curve=equity_curve,
        returns=returns,
        max_drawdown=metrics["max_drawdown"],
        sharpe=metrics["sharpe"],
        trades=trades,
        years=actual_years,
    )

    logger.info(
        "run_backtest_2y: %s | years=%.1f trades=%d sharpe=%.2f max_dd=%.1f%% total_ret=%.1f%%",
        ticker,
        actual_years,
        trades,
        metrics["sharpe"],
        metrics["max_drawdown"] * 100,
        (equity_curve[-1] - 1.0) * 100 if equity_curve else 0.0,
    )
    return report


# ---------------------------------------------------------------------------
# Convenience: validate immediately after running
# ---------------------------------------------------------------------------

async def run_and_validate(
    ticker: str,
    strategy_fn: Callable[[List[Dict]], List[float]],
    years: int = 2,
) -> Dict:
    """
    Run backtest and validate in one call.

    Returns {"report": BacktestReport, "validation": {"ok": bool, "reason": str}}.
    """
    from merid.risk.btc_promotion_config import validate_before_lift
    report = await run_backtest_2y(ticker, strategy_fn, years=years)
    validation = validate_before_lift(report)
    return {"report": report, "validation": validation}
