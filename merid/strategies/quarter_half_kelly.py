"""
Quarter Kelly vs Half Kelly Backtest

Compact building block for Kelly level comparison.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import List
import logging

from .kelly import KellyStats, kelly_fraction

logger = logging.getLogger(__name__)

@dataclass
class KellyPath:
    """Kelly path with label, fraction, and equity curve."""
    label: str
    fraction: float
    equity: pd.Series

def kelly_equity(trade_pnls: List[float], f: float) -> pd.Series:
    """
    Generate equity curve using Kelly fraction.
    
    Args:
        trade_pnls: List of per-trade PnLs
        f: Kelly fraction to apply
        
    Returns:
        Equity curve Series
    """
    capital = 1.0
    eq = []
    
    for pnl in trade_pnls:
        capital *= (1 + f * pnl)
        eq.append(capital)
    
    return pd.Series(eq, name=f"f={f:.3f}")

def build_kelly_paths(trade_pnls: List[float]) -> List[KellyPath]:
    """
    Build Kelly paths for different fraction levels.
    
    Args:
        trade_pnls: List of per-trade PnLs from strategy backtest
        
    Returns:
        List of KellyPath objects
    """
    if not trade_pnls:
        logger.warning("No trade PnLs provided")
        return []
    
    # Calculate Kelly statistics
    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p < 0]
    
    win_rate = len(wins) / len(trade_pnls)
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = -np.mean(losses) if losses else 0.0
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
    
    # Calculate full Kelly fraction
    ks = KellyStats(win_rate=win_rate, win_loss_ratio=win_loss_ratio)
    f_full = kelly_fraction(ks)
    
    # Fractional Kelly levels
    f_half = 0.5 * f_full
    f_quarter = 0.25 * f_full
    
    # Build paths
    paths = []
    for label, f in [("Full Kelly", f_full), ("Half Kelly", f_half), ("Quarter Kelly", f_quarter)]:
        try:
            eq = kelly_equity(trade_pnls, f)
            paths.append(KellyPath(label=label, fraction=f, equity=eq))
        except Exception as e:
            logger.error(f"Error building {label} path: {e}")
            continue
    
    logger.info(f"Built {len(paths)} Kelly paths: full={f_full:.3f}, half={f_half:.3f}, quarter={f_quarter:.3f}")
    
    return paths

def compare_kelly_paths(paths: List[KellyPath]) -> dict:
    """
    Compare Kelly paths and return performance metrics.
    
    Args:
        paths: List of KellyPath objects
        
    Returns:
        Comparison dictionary
    """
    if not paths:
        return {"error": "No paths to compare"}
    
    comparison = {}
    
    for path in paths:
        if path.equity.empty:
            continue
        
        # Calculate metrics
        final_capital = path.equity.iloc[-1]
        total_return = (final_capital / path.equity.iloc[0]) - 1
        
        # Calculate returns
        returns = path.equity.pct_change().dropna()
        
        # Sharpe ratio (annualized for 15m bars)
        periods_per_year = 365 * 24 * 4
        sharpe = returns.mean() / returns.std() * np.sqrt(periods_per_year) if returns.std() > 0 else 0.0
        
        # Max drawdown
        peak = path.equity.cummax()
        dd = (path.equity - peak) / peak.replace(0, np.nan)
        max_dd = dd.min()
        
        comparison[path.label] = {
            "fraction": path.fraction,
            "final_capital": final_capital,
            "total_return": total_return,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_dd,
            "volatility": returns.std(),
            "equity_curve": path.equity
        }
    
    return comparison

def print_kelly_paths_summary(paths: List[KellyPath]):
    """
    Print formatted summary of Kelly paths.
    
    Args:
        paths: List of KellyPath objects
    """
    if not paths:
        print("No Kelly paths to display")
        return
    
    comparison = compare_kelly_paths(paths)
    
    print("\n" + "="*70)
    print("KELLY PATHS SUMMARY")
    print("="*70)
    
    print(f"\n{'Path':<15} {'Fraction':<10} {'Final Cap':<12} {'Return':<10} {'Sharpe':<8} {'Max DD':<8}")
    print("-" * 70)
    
    for label, metrics in comparison.items():
        print(f"{label:<15} {metrics['fraction']:<10.3f} {metrics['final_capital']:<12.2f} "
              f"{metrics['total_return']:<10.1%} {metrics['sharpe_ratio']:<8.2f} "
              f"{metrics['max_drawdown']:<8.2%}")
    
    # Find best performers
    best_sharpe = max(comparison.items(), key=lambda x: x[1]["sharpe_ratio"])
    best_return = max(comparison.items(), key=lambda x: x[1]["total_return"])
    best_drawdown = min(comparison.items(), key=lambda x: x[1]["max_drawdown"])
    
    print(f"\nBest Performance:")
    print(f"  Highest Sharpe: {best_sharpe[0]} ({best_sharpe[1]['sharpe_ratio']:.2f})")
    print(f"  Highest Return: {best_return[0]} ({best_return[1]['total_return']:.1%})")
    print(f"  Lowest Drawdown: {best_drawdown[0]} ({best_drawdown[1]['max_drawdown']:.2%})")
    
    # Risk-adjusted analysis
    risk_adj_returns = {}
    for label, metrics in comparison.items():
        risk_adj = metrics["total_return"] / abs(metrics["max_drawdown"]) if metrics["max_drawdown"] != 0 else metrics["total_return"]
        risk_adj_returns[label] = risk_adj
    
    best_risk_adj = max(risk_adj_returns.items(), key=lambda x: x[1])
    print(f"  Best Risk-Adjusted: {best_risk_adj[0]} ({best_risk_adj[1]:.2f})")
    
    print("="*70)

def recommend_kelly_fraction(paths: List[KellyPath]) -> str:
    """
    Recommend optimal Kelly fraction based on paths.
    
    Args:
        paths: List of KellyPath objects
        
    Returns:
        Recommendation string
    """
    if not paths:
        return "No data for recommendation"
    
    comparison = compare_kelly_paths(paths)
    
    # Find half Kelly path
    half_kelly = None
    for label, metrics in comparison.items():
        if "Half" in label:
            half_kelly = (label, metrics)
            break
    
    if not half_kelly:
        return "Half Kelly path not found"
    
    # Compare with full Kelly
    full_kelly = None
    for label, metrics in comparison.items():
        if "Full" in label:
            full_kelly = (label, metrics)
            break
    
    if full_kelly:
        # Risk-adjusted comparison
        half_risk_adj = half_kelly[1]["total_return"] / abs(half_kelly[1]["max_drawdown"]) if half_kelly[1]["max_drawdown"] != 0 else half_kelly[1]["total_return"]
        full_risk_adj = full_kelly[1]["total_return"] / abs(full_kelly[1]["max_drawdown"]) if full_kelly[1]["max_drawdown"] != 0 else full_kelly[1]["total_return"]
        
        if half_risk_adj >= full_risk_adj * 0.8:  # Within 80% of full Kelly risk-adjusted return
            return f"Half Kelly ({half_kelly[1]['fraction']:.3f}) recommended: competitive risk-adjusted returns with much lower drawdown risk"
        else:
            return f"Full Kelly ({full_kelly[1]['fraction']:.3f}) shows superior performance, but fractional Kelly is recommended for risk management"
    
    return f"Half Kelly ({half_kelly[1]['fraction']:.3f}) recommended for balanced risk and return"

# Example usage:
"""
import numpy as np

# Generate sample trade PnLs
np.random.seed(42)
trade_pnls = np.random.choice([100, -50, 75, -25, 150, -75], size=50)

# Build Kelly paths
paths = build_kelly_paths(trade_pnls.tolist())

# Print summary
print_kelly_paths_summary(paths)

# Get recommendation
recommendation = recommend_kelly_fraction(paths)
print(f"Recommendation: {recommendation}")
"""
