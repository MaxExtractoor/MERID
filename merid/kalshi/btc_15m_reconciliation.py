# merid/kalshi/btc_15m_reconciliation.py
"""BTC 15m backtest vs shadow reconciliation job."""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any

from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
from utils.logger import get_logger

logger = get_logger("merid.kalshi.btc_15m_reconciliation")


def load_backtest_summary() -> Dict[str, Any]:
    """Load BTC 15m backtest summary from file or return mock data."""
    # TODO: Replace with actual backtest data loading
    return {
        "hit_rate": 0.58,
        "expected_edge": 0.024,
        "max_drawdown": 0.087,
        "trade_rate_by_regime": {
            "trending": 0.12,
            "choppy": 0.05,
            "volatile": 0.09,
        },
        "avg_confidence": 0.72,
        "sharpe": 1.34,
    }


def get_shadow_metrics() -> Dict[str, Any]:
    """Pull BTC 15m shadow metrics from performance tracker."""
    tracker = get_agent_performance_tracker()
    metrics = tracker.get_agent_metrics("btc_15m_regime")
    
    if not metrics:
        return {}
    
    return {
        "hit_rate": metrics.win_rate,
        "realized_edge": metrics.avg_realized_edge,
        "max_drawdown": getattr(metrics, "max_drawdown", 0.0),
        "trade_rate": getattr(metrics, "trades_per_day", 0.0),
        "avg_confidence": metrics.avg_confidence,
        "sharpe": metrics.sharpe_ratio,
        "total_trades": metrics.total_closes,
    }


def compute_deltas(backtest: Dict[str, Any], shadow: Dict[str, Any]) -> Dict[str, Any]:
    """Compute deltas between backtest and shadow metrics."""
    deltas = {}
    
    # Hit rate delta
    if "hit_rate" in backtest and "hit_rate" in shadow:
        deltas["hit_rate_delta"] = shadow["hit_rate"] - backtest["hit_rate"]
    
    # Edge delta
    if "expected_edge" in backtest and "realized_edge" in shadow:
        deltas["edge_delta"] = shadow["realized_edge"] - backtest["expected_edge"]
    
    # Drawdown delta
    if "max_drawdown" in backtest and "max_drawdown" in shadow:
        deltas["drawdown_delta"] = shadow["max_drawdown"] - backtest["max_drawdown"]
    
    # Trade rate deltas by regime (shadow only has aggregate)
    if "trade_rate_by_regime" in backtest and "trade_rate" in shadow:
        shadow_rate = shadow["trade_rate"]
        regime_rates = backtest["trade_rate_by_regime"]
        deltas["trade_rate_regime_deltas"] = {
            regime: shadow_rate - rate
            for regime, rate in regime_rates.items()
        }
    
    return deltas


def suggest_config_adjustments(deltas: Dict[str, Any]) -> Dict[str, str]:
    """Suggest config adjustments based on deltas."""
    suggestions = {}
    
    # Hit rate too low
    hit_rate_delta = deltas.get("hit_rate_delta", 0)
    if hit_rate_delta < -0.05:
        suggestions["min_edge_threshold"] = "Increase by 0.005 to improve selectivity"
    elif hit_rate_delta > 0.05:
        suggestions["min_edge_threshold"] = "Consider decreasing to capture more opportunities"
    
    # Edge underperformance
    edge_delta = deltas.get("edge_delta", 0)
    if edge_delta < -0.01:
        suggestions["max_vol_ratio"] = "Reduce to avoid high-volatility periods"
        suggestions["time_to_expiry_min"] = "Increase to avoid last-minute noise"
    
    # Drawdown too high
    drawdown_delta = deltas.get("drawdown_delta", 0)
    if drawdown_delta > 0.02:
        suggestions["max_exposure_pct"] = "Reduce by 20% to limit drawdowns"
        suggestions["dd_guard_threshold"] = "Lower to trigger earlier protection"
    
    # Trade rate deviations
    regime_deltas = deltas.get("trade_rate_regime_deltas", {})
    for regime, delta in regime_deltas.items():
        if delta < -0.03:
            suggestions[f"regime_{regime}_multiplier"] = "Increase to capture more trades"
        elif delta > 0.03:
            suggestions[f"regime_{regime}_multiplier"] = "Decrease to avoid overtrading"
    
    return suggestions


def run_reconciliation() -> Dict[str, Any]:
    """Run full reconciliation and return report."""
    logger.info("Starting BTC 15m backtest vs shadow reconciliation")
    
    # Load data
    backtest = load_backtest_summary()
    shadow = get_shadow_metrics()
    
    if not shadow:
        logger.warning("No shadow metrics available for btc_15m_regime")
        return {"error": "No shadow data available"}
    
    # Compute deltas
    deltas = compute_deltas(backtest, shadow)
    
    # Generate suggestions
    suggestions = suggest_config_adjustments(deltas)
    
    # Build report
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": "btc_15m_regime",
        "backtest": backtest,
        "shadow": shadow,
        "deltas": deltas,
        "config_suggestions": suggestions,
    }
    
    # Log summary
    logger.info(f"Reconciliation complete: hit_rate_delta={deltas.get('hit_rate_delta', 0):.3f}, "
                f"edge_delta={deltas.get('edge_delta', 0):.4f}, "
                f"drawdown_delta={deltas.get('drawdown_delta', 0):.3f}")
    
    if suggestions:
        logger.info(f"Config suggestions: {json.dumps(suggestions, indent=2)}")
    
    return report


if __name__ == "__main__":
    # Run reconciliation and output report
    report = run_reconciliation()
    print(json.dumps(report, indent=2))
