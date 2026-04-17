#!/usr/bin/env python3
"""
BTC 15m Backtest vs Shadow Reconciliation

Compares BTC 15m backtest summary with shadow performance metrics.
Validates that shadow stats fall within acceptable bands from backtest.
"""

import json
from typing import Dict, Any
from dataclasses import dataclass
from pathlib import Path

from utils.logger import get_logger

logger = get_logger("btc_15m_reconciliation")

@dataclass
class BacktestSummary:
    """Backtest metrics summary."""
    total_trades: int
    win_rate: float
    avg_edge: float
    max_drawdown: float
    sharpe_ratio: float
    regimes: Dict[str, Dict[str, Any]]  # regime -> metrics

@dataclass
class ShadowMetrics:
    """Shadow performance metrics."""
    total_trades: int
    win_rate: float
    avg_edge: float
    max_drawdown: float
    sharpe_ratio: float
    regimes: Dict[str, Dict[str, Any]]

def load_backtest_summary() -> BacktestSummary:
    """Load BTC 15m backtest summary from file."""
    # TODO: Load from actual backtest output file
    # For now, return example data
    return BacktestSummary(
        total_trades=1000,
        win_rate=0.55,
        avg_edge=0.02,
        max_drawdown=-0.08,
        sharpe_ratio=1.2,
        regimes={
            "trend_up": {"trades": 400, "win_rate": 0.60, "avg_edge": 0.025},
            "trend_down": {"trades": 300, "win_rate": 0.50, "avg_edge": 0.015},
            "chop": {"trades": 300, "win_rate": 0.52, "avg_edge": 0.018},
        }
    )

def load_shadow_metrics() -> ShadowMetrics:
    """Load BTC 15m shadow metrics from performance tracker."""
    from merid.prediction.agent_performance_tracker import get_agent_performance_tracker

    tracker = get_agent_performance_tracker()
    summary = tracker.get_agent_summary(agent_id="btc_15m_regime")

    # TODO: Load regime breakdown from tracker or logs
    regimes = {
        "trend_up": {"trades": 0, "win_rate": 0, "avg_edge": 0},  # placeholder
        "trend_down": {"trades": 0, "win_rate": 0, "avg_edge": 0},
        "chop": {"trades": 0, "win_rate": 0, "avg_edge": 0},
    }

    return ShadowMetrics(
        total_trades=summary.total_closes,
        win_rate=summary.win_rate,
        avg_edge=getattr(summary, 'avg_edge', 0),
        max_drawdown=summary.max_drawdown,
        sharpe_ratio=getattr(summary, 'sharpe_ratio', 0),
        regimes=regimes,
    )

def reconcile_metrics(backtest: BacktestSummary, shadow: ShadowMetrics) -> Dict[str, Any]:
    """Reconcile backtest vs shadow metrics."""
    results = {
        "overall": {},
        "regimes": {},
        "recommendations": [],
    }

    # Overall metrics
    for metric in ['win_rate', 'avg_edge', 'max_drawdown', 'sharpe_ratio']:
        bt_val = getattr(backtest, metric)
        sh_val = getattr(shadow, metric)
        diff = sh_val - bt_val
        pct_diff = (diff / bt_val) * 100 if bt_val != 0 else 0

        # Acceptable bands: ±20% for win_rate/edge, ±50% for DD/Sharpe
        if metric in ['win_rate', 'avg_edge']:
            acceptable = abs(pct_diff) <= 20
        else:
            acceptable = abs(pct_diff) <= 50

        results["overall"][metric] = {
            "backtest": bt_val,
            "shadow": sh_val,
            "diff": diff,
            "pct_diff": pct_diff,
            "acceptable": acceptable,
        }

        if not acceptable:
            results["recommendations"].append(
                f"{metric}: shadow {sh_val:.3f} vs backtest {bt_val:.3f} ({pct_diff:+.1f}%) - investigate"
            )

    # Regime metrics
    for regime in backtest.regimes:
        if regime in shadow.regimes:
            bt_reg = backtest.regimes[regime]
            sh_reg = shadow.regimes[regime]
            results["regimes"][regime] = {
                "backtest": bt_reg,
                "shadow": sh_reg,
                "trade_diff": sh_reg.get("trades", 0) - bt_reg.get("trades", 0),
            }

    # Trade frequency check
    trade_diff_pct = ((shadow.total_trades - backtest.total_trades) / backtest.total_trades) * 100
    if abs(trade_diff_pct) > 30:
        results["recommendations"].append(
            f"Trade frequency: shadow {shadow.total_trades} vs backtest {backtest.total_trades} ({trade_diff_pct:+.1f}%) - adjust filters"
        )

    return results

def generate_config_updates(results: Dict[str, Any]) -> Dict[str, Any]:
    """Generate config updates based on reconciliation."""
    updates = {}

    # If shadow win rate is significantly lower, increase min_edge_threshold
    win_rate = results["overall"]["win_rate"]
    if not win_rate["acceptable"] and win_rate["shadow"] < win_rate["backtest"] * 0.8:
        updates["min_edge_threshold"] = "+0.005"  # increase threshold

    # If shadow DD is higher, adjust max_vol_ratio or time windows
    dd = results["overall"]["max_drawdown"]
    if not dd["acceptable"] and dd["shadow"] > dd["backtest"] * 1.5:
        updates["max_vol_ratio"] = "-0.5"  # more restrictive
        updates["max_exposure_pct"] = "-0.01"  # lower exposure

    return updates

def main():
    """Run BTC 15m backtest vs shadow reconciliation."""
    logger.info("Starting BTC 15m backtest vs shadow reconciliation")

    backtest = load_backtest_summary()
    shadow = load_shadow_metrics()

    results = reconcile_metrics(backtest, shadow)
    config_updates = generate_config_updates(results)

    # Log results
    logger.info(f"Reconciliation results: {json.dumps(results, indent=2)}")
    logger.info(f"Config updates: {json.dumps(config_updates, indent=2)}")

    # TODO: Save results to file or database
    output_path = Path("btc_15m_reconciliation.json")
    with open(output_path, 'w') as f:
        json.dump({
            "backtest": backtest.__dict__,
            "shadow": shadow.__dict__,
            "results": results,
            "config_updates": config_updates,
        }, f, indent=2)

    logger.info(f"Reconciliation complete, results saved to {output_path}")

    return results, config_updates

if __name__ == "__main__":
    main()
