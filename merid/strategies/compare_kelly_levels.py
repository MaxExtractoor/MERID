"""
Compare Full vs Half Kelly on BTCUSDT 15m

Run backtest with different risk scaling and overlay the curves.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from typing import List, Dict, Tuple
import logging

from .binance_us_data import fetch_klines
from .backtest_15m_meanrev import backtest_meanrev_15m
from .kelly import KellyStats, kelly_fraction
from .ratios import calculate_all_ratios
from .max_drawdown_metric import max_drawdown

logger = logging.getLogger(__name__)

def equity_with_kelly_scaling(trade_pnls: List[float], kelly_fraction_used: float, 
                           initial_capital: float = 1.0) -> pd.Series:
    """
    Simple model: scale each trade PnL by kelly_fraction_used (as fraction of capital).
    For more realism, you'd update capital each trade and size in dollars, but this
    shows relative effect of full vs half Kelly.
    
    Args:
        trade_pnls: List of trade PnLs
        kelly_fraction_used: Kelly fraction to use (0-1)
        initial_capital: Starting capital
        
    Returns:
        Equity curve Series
    """
    capital = initial_capital
    equity_values = [capital]
    
    for pnl in trade_pnls:
        # Scale PnL by Kelly fraction
        capital_change = kelly_fraction_used * pnl
        capital += capital_change
        equity_values.append(capital)
    
    return pd.Series(equity_values)

def calculate_kelly_from_trades(trade_pnls: List[float]) -> Tuple[float, KellyStats]:
    """
    Calculate Kelly statistics from trade PnLs.
    
    Args:
        trade_pnls: List of trade PnLs
        
    Returns:
        Tuple of (kelly_fraction, kelly_stats)
    """
    if not trade_pnls:
        return 0.0, KellyStats(win_rate=0.0, win_loss_ratio=0.0)
    
    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p < 0]
    
    win_rate = len(wins) / len(trade_pnls) if trade_pnls else 0.0
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = -np.mean(losses) if losses else 0.0
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
    
    ks = KellyStats(win_rate=win_rate, win_loss_ratio=win_loss_ratio)
    f_full = kelly_fraction(ks)
    
    return f_full, ks

def compare_kelly_levels(df: pd.DataFrame, kelly_fractions: List[float] = None,
                        title: str = "BTCUSDT 15m: Kelly Strategy Comparison") -> Dict[str, any]:
    """
    Compare different Kelly levels on the same backtest.
    
    Args:
        df: OHLCV DataFrame
        kelly_fractions: List of Kelly fractions to test
        title: Plot title
        
    Returns:
        Comparison results
    """
    if df.empty:
        return {"error": "Empty DataFrame"}
    
    # Default Kelly fractions
    if kelly_fractions is None:
        kelly_fractions = [0.25, 0.5, 0.75, 1.0]  # Quarter, half, three-quarters, full Kelly
    
    # Run backtest
    res = backtest_meanrev_15m(df)
    trade_pnls = [t.pnl for t in res.trades]
    
    if not trade_pnls:
        return {"error": "No trades generated"}
    
    # Calculate Kelly statistics
    f_full, ks = calculate_kelly_from_trades(trade_pnls)
    
    # Generate equity curves for different Kelly levels
    equity_curves = {}
    performance_metrics = {}
    
    for kelly_mult in kelly_fractions:
        kelly_used = kelly_mult * f_full
        equity_curve = equity_with_kelly_scaling(trade_pnls, kelly_used)
        
        # Calculate performance metrics
        returns = equity_curve.pct_change().dropna()
        metrics = calculate_all_ratios(returns)
        
        # Add Kelly-specific metrics
        metrics.update({
            "kelly_fraction_used": kelly_used,
            "kelly_multiplier": kelly_mult,
            "final_capital": equity_curve.iloc[-1],
            "total_return": (equity_curve.iloc[-1] / equity_curve.iloc[0]) - 1,
            "max_drawdown": max_drawdown(equity_curve),
            "volatility": returns.std(),
            "sharpe_ratio": metrics.get("sharpe_ratio", 0.0),
            "sortino_ratio": metrics.get("sortino_ratio", 0.0)
        })
        
        equity_curves[f"{kelly_mult:.1f}x Kelly"] = equity_curve
        performance_metrics[f"{kelly_mult:.1f}x Kelly"] = metrics
    
    return {
        "equity_curves": equity_curves,
        "performance_metrics": performance_metrics,
        "kelly_stats": {
            "full_kelly_fraction": f_full,
            "win_rate": ks.win_rate,
            "win_loss_ratio": ks.win_loss_ratio
        },
        "backtest_summary": {
            "total_trades": len(trade_pnls),
            "avg_pnl": np.mean(trade_pnls),
            "pnl_std": np.std(trade_pnls)
        }
    }

def plot_kelly_comparison(comparison_results: Dict[str, any], title: str = None):
    """
    Plot Kelly comparison results.
    
    Args:
        comparison_results: Results from compare_kelly_levels
        title: Plot title
    """
    if "equity_curves" not in comparison_results:
        print("No equity curves to plot")
        return
    
    equity_curves = comparison_results["equity_curves"]
    performance_metrics = comparison_results["performance_metrics"]
    
    # Create figure
    plt.figure(figsize=(12, 8))
    
    # Plot equity curves
    for label, equity in equity_curves.items():
        plt.plot(equity.index, equity.values, label=label, linewidth=2)
    
    # Formatting
    if title is None:
        title = f"BTCUSDT 15m: Kelly Strategy Comparison\n"
        title += f"Full Kelly: {comparison_results['kelly_stats']['full_kelly_fraction']:.3f} "
        title += f"(Win Rate: {comparison_results['kelly_stats']['win_rate']:.1%}, "
        title += f"W/L Ratio: {comparison_results['kelly_stats']['win_loss_ratio']:.2f})"
    
    plt.title(title, fontsize=14, fontweight='bold')
    plt.xlabel("Trade Number")
    plt.ylabel("Capital (normalized)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()

def print_kelly_comparison_summary(comparison_results: Dict[str, any]):
    """
    Print formatted summary of Kelly comparison.
    
    Args:
        comparison_results: Results from compare_kelly_levels
    """
    if "performance_metrics" not in comparison_results:
        print("No performance metrics to display")
        return
    
    performance_metrics = comparison_results["performance_metrics"]
    kelly_stats = comparison_results["kelly_stats"]
    backtest_summary = comparison_results["backtest_summary"]
    
    print("\n" + "="*80)
    print("KELLY STRATEGY COMPARISON SUMMARY")
    print("="*80)
    
    print(f"\nBacktest Statistics:")
    print(f"  Total Trades: {backtest_summary['total_trades']}")
    print(f"  Average PnL: ${backtest_summary['avg_pnl']:.2f}")
    print(f"  PnL Std Dev: ${backtest_summary['pnl_std']:.2f}")
    
    print(f"\nKelly Statistics:")
    print(f"  Full Kelly Fraction: {kelly_stats['full_kelly_fraction']:.3f}")
    print(f"  Win Rate: {kelly_stats['win_rate']:.1%}")
    print(f"  Win/Loss Ratio: {kelly_stats['win_loss_ratio']:.2f}")
    
    print(f"\nPerformance by Kelly Level:")
    print("-" * 80)
    print(f"{'Level':<12} {'Final Cap':<12} {'Return':<10} {'Sharpe':<8} {'DD':<8} {'Vol':<8}")
    print("-" * 80)
    
    for level, metrics in performance_metrics.items():
        print(f"{level:<12} ${metrics['final_capital']:<11.2f} "
              f"{metrics['total_return']:<9.1%} {metrics['sharpe_ratio']:<7.2f} "
              f"{metrics['max_drawdown']:<7.1%} {metrics['volatility']:<7.1%}")
    
    # Find best performance
    best_sharpe = max(performance_metrics.items(), key=lambda x: x[1]['sharpe_ratio'])
    best_return = max(performance_metrics.items(), key=lambda x: x[1]['total_return'])
    best_dd = max(performance_metrics.items(), key=lambda x: x[1]['max_drawdown'])
    
    print(f"\nBest Performance:")
    print(f"  Highest Sharpe: {best_sharpe[0]} ({best_sharpe[1]['sharpe_ratio']:.2f})")
    print(f"  Highest Return: {best_return[0]} ({best_return[1]['total_return']:.1%})")
    print(f"  Lowest Drawdown: {best_dd[0]} ({best_dd[1]['max_drawdown']:.1%})")
    
    # Risk-adjusted analysis
    print(f"\nRisk-Adjusted Analysis:")
    for level, metrics in performance_metrics.items():
        risk_adj_return = metrics['total_return'] / abs(metrics['max_drawdown']) if metrics['max_drawdown'] != 0 else 0
        print(f"  {level}: {risk_adj_return:.2f}")
    
    print("="*80)

def analyze_kelly_optimal_fraction(comparison_results: Dict[str, any]) -> Dict[str, any]:
    """
    Analyze optimal Kelly fraction based on risk-adjusted performance.
    
    Args:
        comparison_results: Results from compare_kelly_levels
        
    Returns:
        Analysis results
    """
    performance_metrics = comparison_results["performance_metrics"]
    kelly_stats = comparison_results["kelly_stats"]
    
    # Calculate risk-adjusted returns
    risk_adj_returns = {}
    for level, metrics in performance_metrics.items():
        risk_adj_return = metrics['total_return'] / abs(metrics['max_drawdown']) if metrics['max_drawdown'] != 0 else 0
        risk_adj_returns[level] = risk_adj_return
    
    # Find optimal fraction
    optimal_level = max(risk_adj_returns.items(), key=lambda x: x[1])
    optimal_kelly_mult = float(optimal_level[0].replace('x Kelly', ''))
    
    # Calculate recommended safe Kelly fraction (typically 0.25-0.5 of full Kelly)
    safe_kelly_mult = 0.3  # Conservative recommendation
    safe_kelly_fraction = safe_kelly_mult * kelly_stats['full_kelly_fraction']
    
    return {
        "optimal_level": optimal_level[0],
        "optimal_kelly_mult": optimal_kelly_mult,
        "optimal_kelly_fraction": optimal_kelly_mult * kelly_stats['full_kelly_fraction'],
        "optimal_risk_adj_return": optimal_level[1],
        "recommended_safe_mult": safe_kelly_mult,
        "recommended_safe_fraction": safe_kelly_fraction,
        "risk_adjusted_returns": risk_adj_returns,
        "full_kelly_fraction": kelly_stats['full_kelly_fraction']
    }

def compare_full_vs_half_kelly(limit: int = 2000):
    """
    Compare full vs half Kelly on BTCUSDT 15m data.
    
    Args:
        limit: Number of bars to fetch
    """
    try:
        # Fetch data
        print(f"Fetching BTCUSDT 15m data (limit={limit})...")
        df = fetch_klines("BTCUSDT", "15m", limit=limit)
        
        if df.empty:
            print("No data fetched")
            return
        
        print(f"Data fetched: {len(df)} bars from {df.index[0]} to {df.index[-1]}")
        
        # Compare Kelly levels
        print("Running Kelly comparison...")
        results = compare_kelly_levels(df, kelly_fractions=[0.5, 1.0])  # Half vs Full
        
        # Print summary
        print_kelly_comparison_summary(results)
        
        # Analyze optimal fraction
        analysis = analyze_kelly_optimal_fraction(results)
        print(f"\nOptimal Kelly Analysis:")
        print(f"  Optimal Level: {analysis['optimal_level']}")
        print(f"  Optimal Multiplier: {analysis['optimal_kelly_mult']:.1f}x")
        print(f"  Optimal Fraction: {analysis['optimal_kelly_fraction']:.3f}")
        print(f"  Recommended Safe: {analysis['recommended_safe_mult']:.1f}x ({analysis['recommended_safe_fraction']:.3f})")
        
        # Plot comparison
        title = f"BTCUSDT 15m: Full vs Half Kelly\n"
        title += f"Full Kelly: {results['kelly_stats']['full_kelly_fraction']:.3f} "
        title += f"(Win Rate: {results['kelly_stats']['win_rate']:.1%}, "
        title += f"W/L Ratio: {results['kelly_stats']['win_loss_ratio']:.2f})"
        
        plot_kelly_comparison(results, title)
        
        return results
        
    except Exception as e:
        logger.error(f"Error in Kelly comparison: {e}")
        return {"error": str(e)}

def comprehensive_kelly_analysis(limit: int = 2000, kelly_fractions: List[float] = None):
    """
    Comprehensive Kelly analysis with multiple levels.
    
    Args:
        limit: Number of bars to fetch
        kelly_fractions: List of Kelly multipliers to test
    """
    if kelly_fractions is None:
        kelly_fractions = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5]
    
    try:
        # Fetch data
        print(f"Fetching BTCUSDT 15m data (limit={limit})...")
        df = fetch_klines("BTCUSDT", "15m", limit=limit)
        
        if df.empty:
            print("No data fetched")
            return
        
        # Run comprehensive analysis
        print("Running comprehensive Kelly analysis...")
        results = compare_kelly_levels(df, kelly_fractions=kelly_fractions)
        
        # Print summary
        print_kelly_comparison_summary(results)
        
        # Analyze optimal fraction
        analysis = analyze_kelly_optimal_fraction(results)
        print(f"\nOptimal Kelly Analysis:")
        print(f"  Optimal Level: {analysis['optimal_level']}")
        print(f"  Optimal Multiplier: {analysis['optimal_kelly_mult']:.1f}x")
        print(f"  Recommended Safe: {analysis['recommended_safe_mult']:.1f}x")
        
        # Plot comparison
        title = f"BTCUSDT 15m: Comprehensive Kelly Analysis\n"
        title += f"Full Kelly: {results['kelly_stats']['full_kelly_fraction']:.3f} "
        title += f"(Win Rate: {results['kelly_stats']['win_rate']:.1%}, "
        title += f"W/L Ratio: {results['kelly_stats']['win_loss_ratio']:.2f})"
        
        plot_kelly_comparison(results, title)
        
        return results
        
    except Exception as e:
        logger.error(f"Error in comprehensive Kelly analysis: {e}")
        return {"error": str(e)}

# Example usage:
"""
# Simple half vs full Kelly comparison
results = compare_full_vs_half_kelly(limit=2000)

# Comprehensive analysis with multiple levels
results = comprehensive_kelly_analysis(limit=2000, kelly_fractions=[0.25, 0.5, 0.75, 1.0])

# Custom analysis
from merid.strategies.binance_us_data import fetch_klines
df = fetch_klines("BTCUSDT", "15m", limit=1000)
results = compare_kelly_levels(df, kelly_fractions=[0.3, 0.5, 0.7])
print_kelly_comparison_summary(results)
plot_kelly_comparison(results)
"""
