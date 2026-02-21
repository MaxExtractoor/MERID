"""
Walk-forward analysis for Kalshi strategies.

Slides a train/test window across the full price/probability series,
optimises strategy parameters on each training segment, then evaluates
on the immediately following out-of-sample test segment.

The concatenated out-of-sample returns form a realistic equity curve
that is free from look-ahead bias — use this as the input to
validate_before_lift() and monte_carlo_equity() instead of a single
in-sample backtest.

Usage (pure-Python, no pandas required at import time):
    from merid.backtesting.walk_forward import walk_forward_analysis

    result = walk_forward_analysis(
        bars=candles,           # list of {"close": float, ...}
        param_grid=[{"fast": 5, "slow": 20}, {"fast": 10, "slow": 30}],
        train_bars=500,
        test_bars=100,
        strategy_fn=my_strategy,
    )
    if result:
        report = result["backtest_report"]   # BacktestReport ready for validate_before_lift
"""

from __future__ import annotations

import logging
import math
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core WFA engine (pure Python)
# ---------------------------------------------------------------------------

def walk_forward_analysis(
    bars: List[Dict[str, Any]],
    param_grid: List[Dict[str, Any]],
    train_bars: int,
    test_bars: int,
    strategy_fn: Callable[[List[Dict[str, Any]], Dict[str, Any]], List[float]],
    min_windows: int = 3,
) -> Optional[Dict]:
    """
    Sliding-window walk-forward analysis.

    Args:
        bars:        List of OHLCV-style dicts (must have at least "close").
        param_grid:  List of parameter dicts to optimise over.
        train_bars:  Number of bars in each training window.
        test_bars:   Number of bars in each test (out-of-sample) window.
        strategy_fn: fn(bars_slice, params) -> List[float] of per-bar returns.
        min_windows: Minimum number of complete windows required.

    Returns:
        {
            "windows":          list of per-window results,
            "oos_returns":      concatenated out-of-sample returns,
            "equity_curve":     cumulative equity (starting at 1.0),
            "sharpe":           annualised Sharpe of OOS returns,
            "max_drawdown":     peak-to-trough drawdown of OOS equity,
            "backtest_report":  BacktestReport ready for validate_before_lift(),
        }
        or None if insufficient data / windows.
    """
    n = len(bars)
    if n < train_bars + test_bars:
        logger.warning(
            "walk_forward_analysis: only %d bars, need %d+%d — skipping",
            n, train_bars, test_bars,
        )
        return None

    windows: List[Dict] = []
    oos_returns: List[float] = []
    i = 0

    while i + train_bars + test_bars <= n:
        train = bars[i: i + train_bars]
        test  = bars[i + train_bars: i + train_bars + test_bars]

        # --- Optimise on training window ---
        best_params: Optional[Dict] = None
        best_sharpe = float("-inf")

        for params in param_grid:
            try:
                rets = strategy_fn(train, params)
            except Exception as exc:
                logger.debug("WFA strategy_fn error (train, params=%s): %s", params, exc)
                continue

            if not rets or len(rets) < 2:
                continue

            mean = sum(rets) / len(rets)
            variance = sum((r - mean) ** 2 for r in rets) / len(rets)
            std = math.sqrt(variance) if variance > 0 else 0.0
            if std == 0:
                continue

            sharpe = (mean / std) * math.sqrt(252)
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_params = params

        if best_params is None:
            logger.debug("WFA window %d: no valid params found — skipping", i)
            i += test_bars
            continue

        # --- Evaluate best params on test window ---
        try:
            test_rets = strategy_fn(test, best_params)
        except Exception as exc:
            logger.debug("WFA strategy_fn error (test): %s", exc)
            i += test_bars
            continue

        if not test_rets:
            i += test_bars
            continue

        # Compute test-window metrics
        test_mean = sum(test_rets) / len(test_rets)
        test_var  = sum((r - test_mean) ** 2 for r in test_rets) / len(test_rets)
        test_std  = math.sqrt(test_var) if test_var > 0 else 1e-9
        test_sharpe = (test_mean / test_std) * math.sqrt(252)

        windows.append({
            "window_start": i,
            "train_end": i + train_bars,
            "test_end": i + train_bars + test_bars,
            "best_params": best_params,
            "train_sharpe": best_sharpe,
            "test_sharpe": test_sharpe,
            "test_returns": test_rets,
        })
        oos_returns.extend(test_rets)
        i += test_bars

    if len(windows) < min_windows:
        logger.warning(
            "walk_forward_analysis: only %d complete windows (need %d)",
            len(windows), min_windows,
        )
        return None

    # --- Build OOS equity curve ---
    equity = 1.0
    equity_curve: List[float] = []
    for r in oos_returns:
        equity *= (1.0 + r)
        equity_curve.append(equity)

    # --- OOS metrics ---
    n_oos = len(oos_returns)
    oos_mean = sum(oos_returns) / n_oos if n_oos else 0.0
    oos_var  = sum((r - oos_mean) ** 2 for r in oos_returns) / n_oos if n_oos > 1 else 0.0
    oos_std  = math.sqrt(oos_var) if oos_var > 0 else 1e-9
    oos_sharpe = (oos_mean / oos_std) * math.sqrt(252)

    peak = equity_curve[0] if equity_curve else 1.0
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / max(peak, 1e-9)
        if dd > max_dd:
            max_dd = dd

    trades = sum(1 for r in oos_returns if r != 0.0)
    years  = n_oos / 252.0  # approximate

    # --- Build BacktestReport ---
    from merid.risk.btc_promotion_config import BacktestReport
    report = BacktestReport(
        equity_curve=equity_curve,
        returns=oos_returns,
        max_drawdown=max_dd,
        sharpe=oos_sharpe,
        trades=trades,
        years=years,
    )

    logger.info(
        "walk_forward_analysis: %d windows | OOS sharpe=%.2f dd=%.1f%% trades=%d years=%.1f",
        len(windows), oos_sharpe, max_dd * 100, trades, years,
    )

    return {
        "windows": windows,
        "oos_returns": oos_returns,
        "equity_curve": equity_curve,
        "sharpe": oos_sharpe,
        "max_drawdown": max_dd,
        "backtest_report": report,
    }


# ---------------------------------------------------------------------------
# Convenience: WFA → validate
# ---------------------------------------------------------------------------

def wfa_and_validate(
    bars: List[Dict[str, Any]],
    param_grid: List[Dict[str, Any]],
    train_bars: int,
    test_bars: int,
    strategy_fn: Callable,
) -> Dict:
    """
    Run WFA and immediately validate the OOS BacktestReport.

    Returns {"wfa": result_or_None, "validation": {"ok": bool, "reason": str}}.
    """
    from merid.risk.btc_promotion_config import validate_before_lift

    result = walk_forward_analysis(bars, param_grid, train_bars, test_bars, strategy_fn)
    if result is None:
        return {
            "wfa": None,
            "validation": {"ok": False, "reason": "insufficient_wfa_windows"},
        }

    validation = validate_before_lift(result["backtest_report"])
    return {"wfa": result, "validation": validation}
