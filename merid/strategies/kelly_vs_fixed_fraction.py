"""
Kelly vs Fixed Fraction Comparison - Sharpe Analysis

Compare Kelly sizing vs fixed fraction sizing using risk metrics.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from typing import List, Dict, Any
import logging

from .ratios import sharpe_ratio, sortino_ratio
from .kelly_compare import equity_with_kelly
from .binance_us_15m_btc import fetch_btcusdt_15m
from .backtest_15m_meanrev import backtest_meanrev_15m
from .kelly import KellyStats, kelly_fraction

logger = logging.getLogger(__name__)

def equity_fixed_fraction(trade_pnls: List[float], frac: float) -> pd.Series:
    """
    Generate equity curve using fixed fraction sizing.
    
    Args:
        trade_pnls: List of per-trade PnLs
        frac: Fixed fraction of capital to risk
        
    Returns:
        Equity curve Series
    """
    capital = 1.0
    eq = []
    
    for pnl in trade_pnls:
        # Apply fixed fraction
        capital *= (1 + frac * pnl)
        eq.append(capital)
    
    return pd.Series(eq)

def calculate_kelly_stats_from_pnls(trade_pnls: List[float]) -> Dict[str, float]:
    """
    Calculate Kelly statistics from trade PnLs.
    
    Args:
        trade_pnls: List of per-trade PnLs
        
    Returns:
        Dictionary with Kelly statistics
    """
    if not trade_pnls:
        return {"win_rate": 0.0, "win_loss_ratio": 0.0, "kelly_fraction": 0.0}
    
    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p < 0]
    
    win_rate = len(wins) / len(trade_pnls)
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = -np.mean(losses) if losses else 0.0
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
    
    ks = KellyStats(win_rate=win_rate, win_loss_ratio=win_loss_ratio)
    f_kelly = kelly_fraction(ks)
    
    return {
        "win_rate": win_rate,
        "win_loss_ratio": win_loss_ratio,
        "kelly_fraction": f_kelly,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "total_trades": len(trade_pnls)
    }

def compare_kelly_vs_fixed(trade_pnls: List[float], 
                          fixed_fractions: List[float] = None,
                          kelly_multipliers: List[float] = None) -> Dict[str, Any]:
    """
    Compare Kelly vs fixed fraction sizing.
    
    Args:
        trade_pnls: List of per-trade PnLs
        fixed_fractions: List of fixed fractions to test
        kelly_multipliers: List of Kelly multipliers to test
        
    Returns:
        Comparison results
    """
    if not trade_pnls:
        return {"error": "No trade PnLs provided"}
    
    # Calculate Kelly statistics
    kelly_stats = calculate_kelly_stats_from_pnls(trade_pnls)
    f_kelly = kelly_stats["kelly_fraction"]
    
    # Default fractions
    if fixed_fractions is None:
        fixed_fractions = [0.01, 0.02, 0.05, 0.10]  # 1%, 2%, 5%, 10%
    
    if kelly_multipliers is None:
        kelly_multipliers = [0.25, 0.5, 0.75, 1.0]  # Quarter, half, three-quarters, full
    
    results = {}
    
    # Test Kelly fractions
    for mult in kelly_multipliers:
        kelly_frac = f_kelly * mult
        eq = equity_with_kelly(trade_pnls, kelly_frac)
        returns = eq.pct_change().fillna(0.0)
        
        results[f"Kelly {mult:.1f}x"] = {
            "fraction": kelly_frac,
            "equity": eq,
            "final_capital": eq.iloc[-1],
            "sharpe": sharpe_ratio(returns),
            "sortino": sortino_ratio(returns),
            "max_drawdown": (eq - eq.cummax()).min() / eq.cummax().max(),
            "type": "kelly",
            "multiplier": mult
        }
    
    # Test fixed fractions
    for frac in fixed_fractions:
        eq = equity_fixed_fraction(trade_pnls, frac)
        returns = eq.pct_change().fillna(0.0)
        
        results[f"Fixed {frac:.1%}"] = {
            "fraction": frac,
            "equity": eq,
            "final_capital": eq.iloc[-1],
            "sharpe": sharpe_ratio(returns),
            "sortino": sortino_ratio(returns),
            "max_drawdown": (eq - eq.cummax()).min() / eq.cummax().max(),
            "type": "fixed",
            "fixed_fraction": frac
        }
    
    return {
        "results": results,
        "kelly_stats": kelly_stats,
        "best_sharpe": max(results.items(), key=lambda x: x[1]["sharpe"]),
        "best_return": max(results.items(), key=lambda x: x[1]["final_capital"]),
        "best_sortino": max(results.items(), key=lambda x: x[1]["sortino"]),
        "lowest_drawdown": min(results.items(), key=lambda x: x[1]["max_drawdown"])
    }

def print_comparison_results(comparison_results: Dict[str, Any]):
    """
    Print formatted comparison results.
    
    Args:
        comparison_results: Results from compare_kelly_vs_fixed
    """
    if "error" in comparison_results:
        print(f"Error: {comparison_results['error']}")
        return
    
    results = comparison_results["results"]
    kelly_stats = comparison_results["kelly_stats"]
    
    print("\n" + "="*70)
    print("KELLY VS FIXED FRACTION COMPARISON")
    print("="*70)
    
    print(f"\nStrategy Statistics:")
    print(f"  Total Trades: {kelly_stats['total_trades']}")
    print(f"  Win Rate: {kelly_stats['win_rate']:.1%}")
    print(f"  Win/Loss Ratio: {kelly_stats['win_loss_ratio']:.2f}")
    print(f"  Full Kelly Fraction: {kelly_stats['kelly_fraction']:.3f}")
    
    print(f"\nComparison Results:")
    print("-" * 70)
    print(f"{'Strategy':<15} {'Fraction':<10} {'Final Cap':<12} {'Sharpe':<8} {'Sortino':<8} {'Max DD':<8}")
    print("-" * 70)
    
    for name, result in results.items():
        print(f"{name:<15} {result['fraction']:<10.3f} {result['final_capital']:<12.2f} "
              f"{result['sharpe']:<8.2f} {result['sortino']:<8.2f} {result['max_drawdown']:<8.2%}")
    
    print(f"\nBest Performers:")
    print(f"  Highest Sharpe: {comparison_results['best_sharpe'][0]} ({comparison_results['best_sharpe'][1]['sharpe']:.2f})")
    print(f"  Highest Return: {comparison_results['best_return'][0]} ({comparison_results['best_return'][1]['final_capital']:.2f})")
    print(f"  Highest Sortino: {comparison_results['best_sortino'][0]} ({comparison_results['best_sortino'][1]['sortino']:.2f})")
    print(f"  Lowest Drawdown: {comparison_results['lowest_drawdown'][0]} ({comparison_results['lowest_drawdown'][1]['max_drawdown']:.2%})")
    
    print("="*70)

def plot_comparison_results(comparison_results: Dict[str, Any], title: str = None):
    """
    Plot comparison results.
    
    Args:
        comparison_results: Results from compare_kelly_vs_fixed
        title: Plot title
    """
    if "error" in comparison_results:
        print(f"Cannot plot: {comparison_results['error']}")
        return
    
    results = comparison_results["results"]
    kelly_stats = comparison_results["kelly_stats"]
    
    plt.figure(figsize=(12, 8))
    
    # Plot equity curves
    for name, result in results.items():
        eq = result["equity"]
        plt.plot(eq.values, label=name, linewidth=2)
    
    # Formatting
    if title is None:
        title = f"Kelly vs Fixed Fraction Comparison\n"
        title += f"Full Kelly: {kelly_stats['kelly_fraction']:.3f} "
        title += f"(Win Rate: {kelly_stats['win_rate']:.1%}, W/L: {kelly_stats['win_loss_ratio']:.2f})"
    
    plt.title(title, fontsize=14, fontweight='bold')
    plt.xlabel("Trade Number")
    plt.ylabel("Capital (normalized)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()

def analyze_risk_adjusted_performance(comparison_results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze risk-adjusted performance of different strategies.
    
    Args:
        comparison_results: Results from compare_kelly_vs_fixed
        
    Returns:
        Risk-adjusted analysis
    """
    if "error" in comparison_results:
        return {"error": comparison_results["error"]}
    
    results = comparison_results["results"]
    
    # Calculate risk-adjusted returns
    risk_adj_returns = {}
    for name, result in results.items():
        risk_adj = result["final_capital"] / abs(result["max_drawdown"]) if result["max_drawdown"] != 0 else result["final_capital"]
        risk_adj_returns[name] = risk_adj
    
    # Find best risk-adjusted performer
    best_risk_adj = max(risk_adj_returns.items(), key=lambda x: x[1])
    
    # Categorize strategies
    kelly_strategies = {name: result for name, result in results.items() if result["type"] == "kelly"}
    fixed_strategies = {name: result for name, result in results.items() if result["type"] == "fixed"}
    
    # Calculate averages
    avg_kelly_sharpe = np.mean([r["sharpe"] for r in kelly_strategies.values()])
    avg_fixed_sharpe = np.mean([r["sharpe"] for r in fixed_strategies.values()])
    
    avg_kelly_return = np.mean([r["final_capital"] for r in kelly_strategies.values()])
    avg_fixed_return = np.mean([r["final_capital"] for r in fixed_strategies.values()])
    
    return {
        "best_risk_adjusted": {
            "strategy": best_risk_adj[0],
            "risk_adj_return": best_risk_adj[1],
            "sharpe": results[best_risk_adj[0]]["sharpe"],
            "final_capital": results[best_risk_adj[0]]["final_capital"]
        },
        "kelly_vs_fixed": {
            "kelly_avg_sharpe": avg_kelly_sharpe,
            "fixed_avg_sharpe": avg_fixed_sharpe,
            "kelly_avg_return": avg_kelly_return,
            "fixed_avg_return": avg_fixed_return,
            "kelly_advantage": avg_kelly_sharpe - avg_fixed_sharpe
        },
        "risk_adjusted_returns": risk_adj_returns,
        "recommendation": _generate_sizing_recommendation(comparison_results)
    }

def _generate_sizing_recommendation(comparison_results: Dict[str, Any]) -> str:
    """Generate sizing recommendation based on comparison."""
    if "error" in comparison_results:
        return "No data for recommendation"
    
    results = comparison_results["results"]
    kelly_stats = comparison_results["kelly_stats"]
    
    # Find best Kelly strategy (typically half Kelly)
    kelly_strategies = {name: result for name, result in results.items() if result["type"] == "kelly"}
    
    if not kelly_strategies:
        return "No Kelly strategies to evaluate"
    
    # Find half Kelly
    half_kelly = None
    for name, result in kelly_strategies.items():
        if abs(result["multiplier"] - 0.5) < 0.1:  # Half Kelly
            half_kelly = (name, result)
            break
    
    # Find best fixed strategy
    best_fixed = None
    best_fixed_sharpe = -np.inf
    for name, result in results.items():
        if result["type"] == "fixed" and result["sharpe"] > best_fixed_sharpe:
            best_fixed_sharpe = result["sharpe"]
            best_fixed = (name, result)
    
    # Generate recommendation
    if half_kelly and best_fixed:
        if half_kelly[1]["sharpe"] > best_fixed[1]["sharpe"] * 0.9:  # Within 90% of best fixed
            return f"Half Kelly ({half_kelly[1]['fraction']:.3f}) recommended: competitive Sharpe with optimal sizing"
        else:
            return f"Fixed {best_fixed[1]['fraction']:.1%} recommended: better risk-adjusted performance"
    elif half_kelly:
        return f"Half Kelly ({half_kelly[1]['fraction']:.3f}) available but no fixed strategies for comparison"
    else:
        return f"Consider conservative Kelly sizing (25-50% of full Kelly) for better risk management"

def run_btc_comparison(limit: int = 2000):
    """
    Run complete BTC comparison with real data.
    
    Args:
        limit: Number of bars to fetch
        
    Returns:
        Comparison results
    """
    try:
        # Fetch data
        print(f"Fetching BTCUSDT 15m data (limit={limit})...")
        df = fetch_btcusdt_15m(limit=limit)
        
        if df.empty:
            return {"error": "No data fetched"}
        
        # Run backtest
        print("Running backtest...")
        res = backtest_meanrev_15m(df)
        
        if not res.trades:
            return {"error": "No trades generated"}
        
        pnls = [t.pnl for t in res.trades]
        
        # Compare strategies
        print("Comparing Kelly vs fixed fractions...")
        comparison = compare_kelly_vs_fixed(pnls)
        
        # Print results
        print_comparison_results(comparison)
        
        # Analyze risk-adjusted performance
        analysis = analyze_risk_adjusted_performance(comparison)
        print(f"\nRisk-Adjusted Analysis:")
        print(f"  Best Risk-Adjusted: {analysis['best_risk_adjusted']['strategy']}")
        print(f"  Kelly vs Fixed Sharpe: {analysis['kelly_vs_fixed']['kelly_advantage']:.2f}")
        print(f"  Recommendation: {analysis['recommendation']}")
        
        # Plot results
        plot_comparison_results(comparison)
        
        return comparison
        
    except Exception as e:
        logger.error(f"Error in BTC comparison: {e}")
        return {"error": str(e)}

# Example usage:
"""
# Run with real BTC data
results = run_btc_comparison(limit=2000)

# Or use custom trade PnLs
import numpy as np
np.random.seed(42)
trade_pnls = np.random.choice([100, -50, 75, -25, 150, -75], size=100)

comparison = compare_kelly_vs_fixed(trade_pnls.tolist())
print_comparison_results(comparison)

# Risk-adjusted analysis
analysis = analyze_risk_adjusted_performance(comparison)
print(f"Recommendation: {analysis['recommendation']}")
"""
