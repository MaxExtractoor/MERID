"""
Z-Score Threshold Optimization - Grid Search for Mean Reversion Strategy

Grid search Z-entry and Z-exit per asset using backtest function.
"""

import numpy as np
import pandas as pd
import logging
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

from .backtest_15m_meanrev import backtest_meanrev_15m, BacktestResult
from .kelly import KellyStats, kelly_fraction

logger = logging.getLogger(__name__)

@dataclass
class OptimizationResult:
    """Result of optimization run."""
    z_entry: float
    z_exit: float
    hurst_max: float
    total_pnl: float
    max_drawdown: float
    score: float
    win_rate_btc: float
    win_rate_eth: float
    sharpe_ratio: float
    total_trades: int
    profit_factor: float

def optimize_z_thresholds(
    df_btc: pd.DataFrame,
    df_eth: pd.DataFrame,
    z_entry_range: Tuple[float, float] = (0.5, 2.0),
    z_exit_range: List[float] = None,
    hurst_range: Tuple[float, float] = (0.4, 0.6),
    z_entry_steps: int = 8,
    enable_hurst_filter: bool = True
) -> List[OptimizationResult]:
    """
    Optimize Z-score thresholds for mean reversion strategy.
    
    Args:
        df_btc: BTC 15m OHLCV DataFrame
        df_eth: ETH 15m OHLCV DataFrame
        z_entry_range: Tuple of (min, max) for Z-entry threshold
        z_exit_range: List of Z-exit thresholds to test
        hurst_range: Tuple of (min, max) for Hurst threshold
        z_entry_steps: Number of steps for Z-entry grid
        enable_hurst_filter: Whether to enable Hurst filter in backtest
        
    Returns:
        List of optimization results sorted by score
    """
    if z_exit_range is None:
        z_exit_range = [0.05, 0.1, 0.2]
    
    # Generate parameter grids
    z_entries = np.linspace(z_entry_range[0], z_entry_range[1], z_entry_steps)
    z_exits = z_exit_range
    hurst_values = np.linspace(hurst_range[0], hurst_range[1], 5) if enable_hurst_filter else [0.5]
    
    logger.info(f"Optimization: {len(z_entries)} z_entries, {len(z_exits)} z_exits, "
                f"{len(hurst_values)} hurst_values = {len(z_entries) * len(z_exits) * len(hurst_values)} combinations")
    
    results = []
    total_combinations = len(z_entries) * len(z_exits) * len(hurst_values)
    
    for i, z_entry in enumerate(z_entries):
        for z_exit in z_exits:
            for hurst_max in hurst_values:
                try:
                    # Run backtest for BTC
                    logger.debug(f"Testing BTC: z_entry={z_entry:.2f}, z_exit={z_exit:.2f}, hurst_max={hurst_max:.2f}")
                    res_btc = backtest_meanrev_15m(
                        df_btc,
                        z_entry=z_entry,
                        z_exit=z_exit,
                        hurst_max=hurst_max,
                        enable_hurst_filter=enable_hurst_filter
                    )
                    
                    # Run backtest for ETH
                    logger.debug(f"Testing ETH: z_entry={z_entry:.2f}, z_exit={z_exit:.2f}, hurst_max={hurst_max:.2f}")
                    res_eth = backtest_meanrev_15m(
                        df_eth,
                        z_entry=z_entry,
                        z_exit=z_exit,
                        hurst_max=hurst_max,
                        enable_hurst_filter=enable_hurst_filter
                    )
                    
                    # Calculate combined metrics
                    total_pnl = res_btc.total_pnl + res_eth.total_pnl
                    max_dd = min(res_btc.max_drawdown, res_eth.max_drawdown)
                    
                    # Performance score: return / |max_dd| with Sharpe adjustment
                    dd_penalty = abs(max_dd) if max_dd != 0 else 1.0
                    base_score = total_pnl / dd_penalty
                    
                    # Sharpe adjustment (weighted)
                    sharpe_weight = 0.3
                    avg_sharpe = (res_btc.sharpe_ratio + res_eth.sharpe_ratio) / 2
                    sharpe_bonus = avg_sharpe * sharpe_weight * 1000  # Scale to similar magnitude
                    
                    score = base_score + sharpe_bonus
                    
                    # Calculate profit factor
                    all_trades = res_btc.trades + res_eth.trades
                    if all_trades:
                        pnls = [t.pnl for t in all_trades]
                        wins = [p for p in pnls if p > 0]
                        losses = [p for p in pnls if p <= 0]
                        profit_factor = sum(wins) / abs(sum(losses)) if losses else float('inf')
                    else:
                        profit_factor = 0.0
                    
                    result = OptimizationResult(
                        z_entry=z_entry,
                        z_exit=z_exit,
                        hurst_max=hurst_max,
                        total_pnl=total_pnl,
                        max_drawdown=max_dd,
                        score=score,
                        win_rate_btc=res_btc.win_rate,
                        win_rate_eth=res_eth.win_rate,
                        sharpe_ratio=avg_sharpe,
                        total_trades=len(all_trades),
                        profit_factor=profit_factor
                    )
                    
                    results.append(result)
                    
                    # Progress logging
                    progress = (i * len(z_exits) * len(hurst_values) + 
                              z_exits.index(z_exit) * len(hurst_values) + 
                              hurst_values.index(hurst_max) + 1)
                    
                    if progress % 10 == 0:
                        logger.info(f"Progress: {progress}/{total_combinations} ({progress/total_combinations:.1%})")
                
                except Exception as e:
                    logger.error(f"Error in optimization for z_entry={z_entry}, z_exit={z_exit}, hurst_max={hurst_max}: {e}")
                    continue
    
    # Sort by score descending
    results_sorted = sorted(results, key=lambda r: r.score, reverse=True)
    
    logger.info(f"Optimization completed: {len(results)} results")
    
    return results_sorted

def analyze_optimization_results(results: List[OptimizationResult], top_n: int = 10) -> Dict:
    """
    Analyze optimization results and provide insights.
    
    Args:
        results: List of optimization results
        top_n: Number of top results to analyze
        
    Returns:
        Analysis dictionary
    """
    if not results:
        return {"error": "No results to analyze"}
    
    # Top results
    top_results = results[:top_n]
    
    # Parameter ranges
    z_entries = [r.z_entry for r in results]
    z_exits = [r.z_exit for r in results]
    hurst_values = [r.hurst_max for r in results]
    
    # Performance metrics
    pnls = [r.total_pnl for r in results]
    scores = [r.score for r in results]
    win_rates = [(r.win_rate_btc + r.win_rate_eth) / 2 for r in results]
    
    analysis = {
        "total_combinations": len(results),
        "top_results": top_results,
        "parameter_insights": {
            "z_entry_range": (min(z_entries), max(z_entries)),
            "z_exit_range": (min(z_exits), max(z_exits)),
            "hurst_range": (min(hurst_values), max(hurst_values))
        },
        "performance_insights": {
            "best_pnl": max(pnls),
            "worst_pnl": min(pnls),
            "avg_pnl": np.mean(pnls),
            "best_score": max(scores),
            "avg_score": np.mean(scores),
            "best_win_rate": max(win_rates),
            "avg_win_rate": np.mean(win_rates)
        },
        "top_parameters": {
            "avg_z_entry": np.mean([r.z_entry for r in top_results]),
            "avg_z_exit": np.mean([r.z_exit for r in top_results]),
            "avg_hurst_max": np.mean([r.hurst_max for r in top_results])
        },
        "stability_analysis": {
            "z_entry_std": np.std([r.z_entry for r in top_results]),
            "z_exit_std": np.std([r.z_exit for r in top_results]),
            "hurst_std": np.std([r.hurst_max for r in top_results])
        }
    }
    
    return analysis

def calculate_optimal_kelly_from_results(results: List[OptimizationResult], top_n: int = 5) -> Dict[str, KellyStats]:
    """
    Calculate optimal Kelly statistics from top backtest results.
    
    Args:
        results: Optimization results
        top_n: Number of top results to use
        
    Returns:
        Dictionary of Kelly stats per asset
    """
    if not results:
        return {}
    
    # Get best result
    best_result = results[0]
    
    # Note: In a real implementation, you'd extract actual trade PnLs from the backtest
    # For now, we'll estimate from summary statistics
    kelly_stats = {}
    
    # Estimate win rates from results
    btc_win_rate = best_result.win_rate_btc
    eth_win_rate = best_result.win_rate_eth
    
    # Estimate win/loss ratios (crude approximation)
    # In practice, you'd calculate this from actual trade PnLs
    estimated_win_loss_ratio = 1.5  # Conservative assumption
    
    kelly_stats["BTC"] = KellyStats(
        win_rate=btc_win_rate,
        win_loss_ratio=estimated_win_loss_ratio
    )
    
    kelly_stats["ETH"] = KellyStats(
        win_rate=eth_win_rate,
        win_loss_ratio=estimated_win_loss_ratio
    )
    
    logger.info(f"Kelly stats estimated - BTC: win_rate={btc_win_rate:.2f}, "
                f"ETH: win_rate={eth_win_rate:.2f}")
    
    return kelly_stats

def print_optimization_summary(results: List[OptimizationResult], top_n: int = 10):
    """
    Print formatted optimization summary.
    
    Args:
        results: Optimization results
        top_n: Number of top results to display
    """
    if not results:
        print("No optimization results to display")
        return
    
    print("\n" + "="*80)
    print("OPTIMIZATION SUMMARY")
    print("="*80)
    
    # Top results table
    print(f"\nTop {top_n} Results:")
    print("-" * 80)
    print(f"{'Rank':<4} {'Z-Entry':<8} {'Z-Exit':<8} {'Hurst':<6} {'PnL':<8} {'DD':<8} {'Score':<8} {'Win%':<8} {'Trades':<8}")
    print("-" * 80)
    
    for i, result in enumerate(results[:top_n]):
        avg_win_rate = (result.win_rate_btc + result.win_rate_eth) / 2
        print(f"{i+1:<4} {result.z_entry:<8.2f} {result.z_exit:<8.2f} {result.hurst_max:<6.2f} "
              f"{result.total_pnl:<8.0f} {result.max_drawdown:<8.2%} {result.score:<8.1f} "
              f"{avg_win_rate:<8.2%} {result.total_trades:<8}")
    
    # Analysis
    analysis = analyze_optimization_results(results, top_n)
    
    print(f"\nParameter Insights:")
    print(f"  Z-Entry range: {analysis['parameter_insights']['z_entry_range'][0]:.2f} - "
          f"{analysis['parameter_insights']['z_entry_range'][1]:.2f}")
    print(f"  Z-Exit range: {analysis['parameter_insights']['z_exit_range'][0]:.2f} - "
          f"{analysis['parameter_insights']['z_exit_range'][1]:.2f}")
    print(f"  Hurst range: {analysis['parameter_insights']['hurst_range'][0]:.2f} - "
          f"{analysis['parameter_insights']['hurst_range'][1]:.2f}")
    
    print(f"\nPerformance Insights:")
    print(f"  Best PnL: ${analysis['performance_insights']['best_pnl']:,.0f}")
    print(f"  Average PnL: ${analysis['performance_insights']['avg_pnl']:,.0f}")
    print(f"  Best Score: {analysis['performance_insights']['best_score']:.1f}")
    print(f"  Best Win Rate: {analysis['performance_insights']['best_win_rate']:.2%}")
    
    print(f"\nTop Parameters (Average):")
    print(f"  Z-Entry: {analysis['top_parameters']['avg_z_entry']:.2f}")
    print(f"  Z-Exit: {analysis['top_parameters']['avg_z_exit']:.2f}")
    print(f"  Hurst Max: {analysis['top_parameters']['avg_hurst_max']:.2f}")
    
    # Kelly stats
    kelly_stats = calculate_optimal_kelly_from_results(results)
    if kelly_stats:
        print(f"\nKelly Statistics (Estimated):")
        for asset, stats in kelly_stats.items():
            kelly_frac = kelly_fraction(stats)
            print(f"  {asset}: win_rate={stats.win_rate:.2f}, "
                  f"win_loss_ratio={stats.win_loss_ratio:.2f}, kelly={kelly_frac:.3f}")
    
    print("="*80)

def save_optimization_results(results: List[OptimizationResult], filename: str = "optimization_results.csv"):
    """
    Save optimization results to CSV.
    
    Args:
        results: Optimization results
        filename: Output filename
    """
    if not results:
        logger.warning("No results to save")
        return
    
    # Convert to DataFrame
    data = []
    for result in results:
        data.append({
            'z_entry': result.z_entry,
            'z_exit': result.z_exit,
            'hurst_max': result.hurst_max,
            'total_pnl': result.total_pnl,
            'max_drawdown': result.max_drawdown,
            'score': result.score,
            'win_rate_btc': result.win_rate_btc,
            'win_rate_eth': result.win_rate_eth,
            'sharpe_ratio': result.sharpe_ratio,
            'total_trades': result.total_trades,
            'profit_factor': result.profit_factor
        })
    
    df = pd.DataFrame(data)
    df.to_csv(filename, index=False)
    
    logger.info(f"Saved {len(results)} optimization results to {filename}")

# Example usage:
"""
import pandas as pd
import numpy as np

# Generate sample data
np.random.seed(42)
dates = pd.date_range(start='2024-01-01', periods=2000, freq='15min')

# BTC data
btc_prices = 50000 + np.cumsum(np.random.randn(2000) * 100)
df_btc = pd.DataFrame({
    'timestamp': dates,
    'open': btc_prices,
    'high': btc_prices * (1 + np.abs(np.random.randn(2000) * 0.001)),
    'low': btc_prices * (1 - np.abs(np.random.randn(2000) * 0.001)),
    'close': btc_prices,
    'volume': np.random.randint(1000, 10000, 2000)
})

# ETH data
eth_prices = 3000 + np.cumsum(np.random.randn(2000) * 50)
df_eth = pd.DataFrame({
    'timestamp': dates,
    'open': eth_prices,
    'high': eth_prices * (1 + np.abs(np.random.randn(2000) * 0.001)),
    'low': eth_prices * (1 - np.abs(np.random.randn(2000) * 0.001)),
    'close': eth_prices,
    'volume': np.random.randint(500, 5000, 2000)
})

# Run optimization
results = optimize_z_thresholds(df_btc, df_eth)

# Print summary
print_optimization_summary(results, top_n=10)

# Save results
save_optimization_results(results)

# Get Kelly stats
kelly_stats = calculate_optimal_kelly_from_results(results)
print(f"Kelly stats: {kelly_stats}")
"""
