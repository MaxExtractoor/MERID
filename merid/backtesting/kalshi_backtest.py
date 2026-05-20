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

from utils.logger import get_logger
import math
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

from merid.risk.btc_promotion_config import BacktestReport

logger = get_logger(__name__)


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
# C1 — Naive baseline strategies
# ---------------------------------------------------------------------------

def naive_50_50_strategy(candles: List[Dict]) -> List[float]:
    """Always bet YES at the open price each bar (50-50 baseline).

    Simulates buying YES at the open for every candle, assuming the
    contract settles YES with the closing probability as payout:
      return = close / open - 1  (no position if open == 0)
    """
    returns: List[float] = []
    for c in candles:
        o = float(c.get("o") or c.get("open") or 0)
        cl = float(c.get("c") or c.get("close") or 0)
        if o > 0:
            returns.append(cl / o - 1.0)
        else:
            returns.append(0.0)
    return returns


def naive_momentum_strategy(candles: List[Dict], lookback: int = 3) -> List[float]:
    """Buy YES when price trended up over the last `lookback` bars; else flat.

    Momentum signal:  close[t-1] > close[t-lookback-1]
    Exit:             sell at next bar's close.
    """
    returns: List[float] = []
    closes = [float(c.get("c") or c.get("close") or 0) for c in candles]
    for i, c in enumerate(candles):
        if i < lookback:
            returns.append(0.0)
            continue
        if closes[i - 1] > closes[i - lookback - 1] if i > lookback else False:
            o = float(c.get("o") or c.get("open") or closes[i - 1])
            cl = closes[i]
            returns.append(cl / o - 1.0 if o > 0 else 0.0)
        else:
            returns.append(0.0)
    return returns


async def run_baseline_comparison(
    ticker: str,
    years: int = 2,
) -> Dict:
    """Run all three strategies (50-50, momentum, custom placeholder) on the same data.

    Returns a dict of name → BacktestReport for direct comparison.
    """
    candles = await fetch_kalshi_history(ticker, years=years)
    if len(candles) < 10:
        logger.warning("run_baseline_comparison: insufficient data for %s", ticker)
        return {}

    results: Dict[str, "BacktestReport"] = {}
    for name, strategy_fn in [
        ("naive_50_50", naive_50_50_strategy),
        ("naive_momentum", naive_momentum_strategy),
    ]:
        returns = strategy_fn(candles)
        returns = (returns + [0.0] * len(candles))[: len(candles)]
        equity = 1.0
        equity_curve: List[float] = []
        for r in returns:
            equity *= (1.0 + r)
            equity_curve.append(equity)
        metrics = _compute_metrics(returns, equity_curve)
        trades = sum(1 for r in returns if r != 0.0)
        results[name] = BacktestReport(
            equity_curve=equity_curve,
            returns=returns,
            max_drawdown=metrics["max_drawdown"],
            sharpe=metrics["sharpe"],
            trades=trades,
            years=float(years),
        )
        logger.info(
            "baseline [%s] %s: sharpe=%.2f max_dd=%.1f%% total_ret=%.1f%%",
            name, ticker, metrics["sharpe"],
            metrics["max_drawdown"] * 100,
            (equity_curve[-1] - 1.0) * 100 if equity_curve else 0.0,
        )

    return results


# ---------------------------------------------------------------------------
# Convenience: validate immediately after running
# ---------------------------------------------------------------------------

async def run_multi_category_backtest(
    strategy_fn: Callable[[List[Dict]], List[float]],
    tickers: Optional[List[str]] = None,
    years: int = 2,
    include_baselines: bool = True,
) -> Dict:
    """C2: Batch backtest across multiple categories with baseline comparison.

    Default ticker set covers crypto hourly, crypto 15m, and macro daily.
    Returns a comparison dict: { ticker → { strategy: BacktestReport, baselines: {...} } }
    """
    if tickers is None:
        tickers = [
            "KXBTC-24DEC31-B90000",   # crypto (BTC) — hourly
            "KXETH-24DEC31-B2500",     # crypto (ETH) — hourly
        ]

    results: Dict[str, Any] = {}
    for ticker in tickers:
        entry: Dict[str, Any] = {}
        try:
            strategy_report = await run_backtest_2y(ticker, strategy_fn, years=years)
            entry["strategy"] = {
                "sharpe": strategy_report.sharpe,
                "max_drawdown": strategy_report.max_drawdown,
                "trades": strategy_report.trades,
                "total_return": (strategy_report.equity_curve[-1] - 1.0)
                    if strategy_report.equity_curve else 0.0,
                "years": strategy_report.years,
            }
        except Exception as exc:
            logger.warning("multi_category_backtest: %s strategy failed: %s", ticker, exc)
            entry["strategy"] = {"error": str(exc)}

        if include_baselines:
            try:
                baselines = await run_baseline_comparison(ticker, years=years)
                entry["baselines"] = {
                    name: {
                        "sharpe": r.sharpe,
                        "max_drawdown": r.max_drawdown,
                        "trades": r.trades,
                        "total_return": (r.equity_curve[-1] - 1.0) if r.equity_curve else 0.0,
                    }
                    for name, r in baselines.items()
                }
            except Exception as exc:
                logger.warning("multi_category_backtest: %s baselines failed: %s", ticker, exc)
                entry["baselines"] = {}

        results[ticker] = entry

    # Summary row
    strategy_sharpes = [
        r["strategy"]["sharpe"]
        for r in results.values()
        if "sharpe" in r.get("strategy", {})
    ]
    results["__summary__"] = {
        "tickers_tested": len(tickers),
        "avg_strategy_sharpe": (sum(strategy_sharpes) / len(strategy_sharpes)) if strategy_sharpes else None,
    }

    return results


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
    from merid.startup_validations import validate_profile_backtest_eligibility
    
    # Validate profile backtest eligibility before running
    validate_profile_backtest_eligibility()
    
    report = await run_backtest_2y(ticker, strategy_fn, years=years)
    validation = validate_before_lift(report)
    return {"report": report, "validation": validation}


# ---------------------------------------------------------------------------
# Persisted report store  (BUG-7 support)
# ---------------------------------------------------------------------------

import json as _json
import os as _os
from pathlib import Path as _Path

_REPORT_STORE = _Path(_os.environ.get(
    "MERID_BACKTEST_REPORTS",
    _Path(__file__).parent.parent.parent / "data" / "backtest_reports.json",
))


def save_backtest_report(agent_id: str, report: BacktestReport) -> None:
    """Persist a BacktestReport for *agent_id* to the report store.

    Overwrites any previous report for the same agent_id.  Callers should
    invoke this after every successful run_backtest_2y() so that
    get_latest_backtest_report() can retrieve a fresh report for promotion
    gating.
    """
    try:
        _REPORT_STORE.parent.mkdir(parents=True, exist_ok=True)
        existing: dict = {}
        if _REPORT_STORE.exists():
            try:
                existing = _json.loads(_REPORT_STORE.read_text())
            except Exception:
                existing = {}
        existing[agent_id] = {
            "equity_curve": report.equity_curve,
            "returns": report.returns,
            "max_drawdown": report.max_drawdown,
            "sharpe": report.sharpe,
            "trades": report.trades,
            "years": report.years,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        _REPORT_STORE.write_text(_json.dumps(existing, indent=2))
    except Exception as exc:
        logger.warning("save_backtest_report: failed for %s: %s", agent_id, exc)


def get_latest_backtest_report(agent_id: str) -> Optional[BacktestReport]:
    """Return the most recently saved BacktestReport for *agent_id*, or None.

    Used by DeploymentController._check_backtest_lift_gate() (BUG-7 fix) to
    verify a valid backtest exists before LIVE promotion.
    """
    if not _REPORT_STORE.exists():
        return None
    try:
        data = _json.loads(_REPORT_STORE.read_text())
        d = data.get(agent_id)
        if d is None:
            return None
        return BacktestReport(
            equity_curve=d.get("equity_curve", [1.0]),
            returns=d.get("returns", []),
            max_drawdown=d.get("max_drawdown", 1.0),
            sharpe=d.get("sharpe", 0.0),
            trades=d.get("trades", 0),
            years=d.get("years", 0.0),
        )
    except Exception as exc:
        logger.warning("get_latest_backtest_report: failed for %s: %s", agent_id, exc)
        return None
