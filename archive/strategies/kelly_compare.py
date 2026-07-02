"""
Kelly Compare - Fractional vs Full Kelly Comparison

Minimal, focused code patterns for Kelly level comparison.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import List
import logging

from .kelly import KellyStats, kelly_fraction

logger = logging.getLogger(__name__)

@dataclass
class KellyRunResult:
    """Result of Kelly run with equity and drawdown."""
    fraction: float
    equity: pd.Series
    max_drawdown: float
    final_capital: float
    sharpe_ratio: float
    sortino_ratio: float

def equity_with_kelly(trade_pnls: List[float], kelly_fraction_used: float) -> pd.Series:
    """
    Generate equity curve using Kelly fraction.
    
    Args:
        trade_pnls: List of per-trade PnLs
        kelly_fraction_used: Kelly fraction to apply
        
    Returns:
        Equity curve Series
    """
    capital = 1.0
    eq = []
    
    for pnl in trade_pnls:
        # Log-optimal compounding
        capital *= (1 + kelly_fraction_used * pnl)
        eq.append(capital)
    
    return pd.Series(eq)

def max_drawdown(equity: pd.Series) -> float:
    """
    Calculate maximum drawdown from equity curve.
    
    Args:
        equity: Equity curve Series
        
    Returns:
        Maximum drawdown as negative fraction
    """
    if equity.empty:
        return 0.0
    
    peak = equity.cummax()
    dd = (equity - peak) / peak.replace(0, np.nan)
    return float(dd.min())

def calculate_sharpe_sortino(equity: pd.Series) -> tuple[float, float]:
    """
    Calculate Sharpe and Sortino ratios for equity curve.
    
    Args:
        equity: Equity curve Series
        
    Returns:
        Tuple of (sharpe_ratio, sortino_ratio)
    """
    if len(equity) < 2:
        return 0.0, 0.0
    
    # Calculate returns
    returns = equity.pct_change().dropna()
    
    if len(returns) == 0 or returns.std() == 0:
        return 0.0, 0.0
    
    # Sharpe ratio (annualized for 15m bars)
    periods_per_year = 365 * 24 * 4
    sharpe = returns.mean() / returns.std() * np.sqrt(periods_per_year)
    
    # Sortino ratio (downside deviation only)
    downside_returns = returns[returns < 0]
    if len(downside_returns) == 0 or downside_returns.std() == 0:
        sortino = 0.0
    else:
        sortino = returns.mean() / downside_returns.std() * np.sqrt(periods_per_year)
    
    return float(sharpe), float(sortino)

def compare_kelly_levels(trade_pnls: List[float], 
                        fractions: List[float] = None) -> List[KellyRunResult]:
    """
    Compare different Kelly levels on trade PnLs.
    
    Args:
        trade_pnls: List of per-trade PnLs
        fractions: List of Kelly fractions to test (default: full, half, quarter)
        
    Returns:
        List of KellyRunResult objects
    """
    if not trade_pnls:
        logger.warning("No trade PnLs provided")
        return []
    
    # Calculate Kelly statistics from trades
    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p < 0]
    
    win_rate = len(wins) / len(trade_pnls)
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = -np.mean(losses) if losses else 0.0
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
    
    # Calculate full Kelly fraction
    ks = KellyStats(win_rate=win_rate, win_loss_ratio=win_loss_ratio)
    f_full = kelly_fraction(ks)
    
    # Default fractions: full, half, quarter Kelly
    if fractions is None:
        fractions = [f_full, 0.5 * f_full, 0.25 * f_full]
    
    results = []
    
    for f in fractions:
        try:
            # Generate equity curve
            eq = equity_with_kelly(trade_pnls, f)
            
            # Calculate metrics
            dd = max_drawdown(eq)
            final_capital = eq.iloc[-1]
            sharpe, sortino = calculate_sharpe_sortino(eq)
            
            result = KellyRunResult(
                fraction=f,
                equity=eq,
                max_drawdown=dd,
                final_capital=final_capital,
                sharpe_ratio=sharpe,
                sortino_ratio=sortino
            )
            
            results.append(result)
            
        except Exception as e:
            logger.error(f"Error calculating Kelly result for fraction {f}: {e}")
            continue
    
    return results

def analyze_kelly_comparison(results: List[KellyRunResult]) -> dict:
    """
    Analyze Kelly comparison results.
    
    Args:
        results: List of KellyRunResult objects
        
    Returns:
        Analysis dictionary
    """
    if not results:
        return {"error": "No results to analyze"}
    
    # Find best performers
    best_sharpe = max(results, key=lambda r: r.sharpe_ratio)
    best_sortino = max(results, key=lambda r: r.sortino_ratio)
    best_return = max(results, key=lambda r: r.final_capital)
    best_drawdown = min(results, key=lambda r: r.max_drawdown)
    
    # Calculate risk-adjusted returns
    risk_adj_returns = {}
    for result in results:
        risk_adj = result.final_capital / abs(result.max_drawdown) if result.max_drawdown != 0 else result.final_capital
        risk_adj_returns[result.fraction] = risk_adj
    
    best_risk_adj = max(risk_adj_returns.items(), key=lambda x: x[1])
    
    return {
        "total_results": len(results),
        "best_sharpe": {
            "fraction": best_sharpe.fraction,
            "sharpe": best_sharpe.sharpe_ratio,
            "final_capital": best_sharpe.final_capital,
            "max_drawdown": best_sharpe.max_drawdown
        },
        "best_sortino": {
            "fraction": best_sortino.fraction,
            "sortino": best_sortino.sortino_ratio,
            "final_capital": best_sortino.final_capital,
            "max_drawdown": best_sortino.max_drawdown
        },
        "best_return": {
            "fraction": best_return.fraction,
            "final_capital": best_return.final_capital,
            "sharpe": best_return.sharpe_ratio,
            "max_drawdown": best_return.max_drawdown
        },
        "best_drawdown": {
            "fraction": best_drawdown.fraction,
            "max_drawdown": best_drawdown.max_drawdown,
            "final_capital": best_drawdown.final_capital,
            "sharpe": best_drawdown.sharpe_ratio
        },
        "best_risk_adjusted": {
            "fraction": best_risk_adj[0],
            "risk_adj_return": best_risk_adj[1]
        },
        "risk_adjusted_returns": risk_adj_returns,
        "recommendation": _generate_recommendation(results)
    }

def _generate_recommendation(results: List[KellyRunResult]) -> str:
    """Generate recommendation based on results."""
    if not results:
        return "No data for recommendation"
    
    # Find half Kelly result
    full_kelly = None
    half_kelly = None
    
    for result in results:
        if abs(result.fraction - 1.0) < 0.01:  # Full Kelly
            full_kelly = result
        elif abs(result.fraction - 0.5) < 0.01:  # Half Kelly
            half_kelly = result
    
    if half_kelly and full_kelly:
        # Compare risk-adjusted performance
        full_risk_adj = full_kelly.final_capital / abs(full_kelly.max_drawdown) if full_kelly.max_drawdown != 0 else full_kelly.final_capital
        half_risk_adj = half_kelly.final_capital / abs(half_kelly.max_drawdown) if half_kelly.max_drawdown != 0 else half_kelly.final_capital
        
        if half_risk_adj > full_risk_adj * 0.8:  # Half Kelly within 80% of full Kelly risk-adjusted return
            return f"Half Kelly (f={half_kelly.fraction:.3f}) recommended: better risk-adjusted returns with lower drawdowns"
        else:
            return f"Full Kelly (f={full_kelly.fraction:.3f}) shows superior performance, but consider fractional Kelly for lower risk"
    
    # Default recommendation
    best_result = max(results, key=lambda r: r.sharpe_ratio)
    return f"Consider {best_result.fraction:.3f} Kelly fraction (Sharpe: {best_result.sharpe_ratio:.2f})"

def print_kelly_comparison_summary(results: List[KellyRunResult]):
    """
    Print formatted summary of Kelly comparison.
    
    Args:
        results: List of KellyRunResult objects
    """
    if not results:
        print("No Kelly comparison results to display")
        return
    
    print("\n" + "="*70)
    print("KELLY COMPARISON SUMMARY")
    print("="*70)
    
    print(f"\n{'Fraction':<12} {'Final Cap':<12} {'Sharpe':<8} {'Sortino':<8} {'Max DD':<8} {'Risk Adj':<10}")
    print("-" * 70)
    
    for result in results:
        risk_adj = result.final_capital / abs(result.max_drawdown) if result.max_drawdown != 0 else result.final_capital
        print(f"{result.fraction:<12.3f} {result.final_capital:<12.2f} "
              f"{result.sharpe_ratio:<8.2f} {result.sortino_ratio:<8.2f} "
              f"{result.max_drawdown:<8.2%} {risk_adj:<10.2f}")
    
    # Analysis
    analysis = analyze_kelly_comparison(results)
    
    print(f"\nBest Performance:")
    print(f"  Highest Sharpe: {analysis['best_sharpe']['fraction']:.3f} ({analysis['best_sharpe']['sharpe']:.2f})")
    print(f"  Highest Return: {analysis['best_return']['fraction']:.3f} ({analysis['best_return']['final_capital']:.2f})")
    print(f"  Lowest Drawdown: {analysis['best_drawdown']['fraction']:.3f} ({analysis['best_drawdown']['max_drawdown']:.2%})")
    print(f"  Best Risk-Adjusted: {analysis['best_risk_adjusted']['fraction']:.3f} ({analysis['best_risk_adjusted']['risk_adj_return']:.2f})")
    
    print(f"\nRecommendation: {analysis['recommendation']}")
    
    print("="*70)

# Example usage:
"""
import numpy as np

# Generate sample trade PnLs
np.random.seed(42)
trade_pnls = np.random.choice([100, -50, 75, -25, 150, -75], size=100)

# Compare Kelly levels
results = compare_kelly_levels(trade_pnls.tolist())

# Print summary
print_kelly_comparison_summary(results)

# Analyze results
analysis = analyze_kelly_comparison(results)
print(f"Analysis: {analysis}")
"""
