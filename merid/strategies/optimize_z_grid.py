"""
Z-Score Grid Search Optimization - Generic Parameter Optimization

Generic grid search for Z-score thresholds using existing backtest function.
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Tuple, Optional
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
import time

from .backtest_15m_meanrev import backtest_meanrev_15m, BacktestResult
from .risk_metrics import calculate_all_metrics

logger = logging.getLogger(__name__)

def optimize_z_grid(
    btc_df: pd.DataFrame,
    eth_df: pd.DataFrame,
    z_entry_values: Optional[List[float]] = None,
    z_exit_values: Optional[List[float]] = None,
    hurst_max_values: Optional[List[float]] = None,
    max_bars_in_trade: int = 16,
    enable_hurst_filter: bool = True,
    parallel: bool = True,
    max_workers: int = 4
) -> List[Dict[str, Any]]:
    """
    Generic grid search for Z-score threshold optimization.
    
    Returns sorted list of parameter configs with metrics.
    
    Args:
        btc_df: BTC 15m OHLCV DataFrame
        eth_df: ETH 15m OHLCV DataFrame
        z_entry_values: List of Z-entry values to test
        z_exit_values: List of Z-exit values to test
        hurst_max_values: List of Hurst max values to test
        max_bars_in_trade: Maximum bars to hold in trade
        enable_hurst_filter: Whether to enable Hurst filter
        parallel: Whether to use parallel processing
        max_workers: Number of parallel workers
        
    Returns:
        List of parameter configurations with metrics, sorted by performance
    """
    # Default parameter grids
    if z_entry_values is None:
        z_entry_values = np.linspace(0.5, 2.0, 7)  # 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0
    
    if z_exit_values is None:
        z_exit_values = [0.05, 0.1, 0.2]
    
    if hurst_max_values is None:
        hurst_max_values = [0.45, 0.5, 0.55]
    
    # Generate parameter combinations
    param_combinations = []
    for z_entry in z_entry_values:
        for z_exit in z_exit_values:
            for hurst_max in hurst_max_values:
                param_combinations.append({
                    'z_entry': float(z_entry),
                    'z_exit': float(z_exit),
                    'hurst_max': float(hurst_max)
                })
    
    total_combinations = len(param_combinations)
    logger.info(f"Grid search: {total_combinations} combinations "
                f"({len(z_entry_values)} z_entries × {len(z_exit_values)} z_exits × {len(hurst_max_values)} hurst_values)")
    
    if parallel and total_combinations > 4:
        results = _parallel_grid_search(param_combinations, btc_df, eth_df, 
                                       max_bars_in_trade, enable_hurst_filter, max_workers)
    else:
        results = _sequential_grid_search(param_combinations, btc_df, eth_df,
                                         max_bars_in_trade, enable_hurst_filter)
    
    # Sort results by composite score
    results_sorted = sorted(results, key=lambda r: r['composite_score'], reverse=True)
    
    logger.info(f"Grid search completed: {len(results)} results")
    
    return results_sorted

def _parallel_grid_search(param_combinations: List[Dict], btc_df: pd.DataFrame, 
                         eth_df: pd.DataFrame, max_bars_in_trade: int, 
                         enable_hurst_filter: bool, max_workers: int) -> List[Dict]:
    """Execute grid search in parallel."""
    results = []
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_params = {
            executor.submit(_evaluate_combination, params, btc_df, eth_df, 
                          max_bars_in_trade, enable_hurst_filter): params
            for params in param_combinations
        }
        
        # Collect results
        completed = 0
        for future in as_completed(future_to_params):
            try:
                result = future.result()
                results.append(result)
                completed += 1
                
                if completed % 10 == 0:
                    logger.info(f"Completed {completed}/{len(param_combinations)} combinations")
                    
            except Exception as e:
                params = future_to_params[future]
                logger.error(f"Error in combination {params}: {e}")
    
    return results

def _sequential_grid_search(param_combinations: List[Dict], btc_df: pd.DataFrame,
                           eth_df: pd.DataFrame, max_bars_in_trade: int,
                           enable_hurst_filter: bool) -> List[Dict]:
    """Execute grid search sequentially."""
    results = []
    
    for i, params in enumerate(param_combinations):
        try:
            result = _evaluate_combination(params, btc_df, eth_df, 
                                         max_bars_in_trade, enable_hurst_filter)
            results.append(result)
            
            if (i + 1) % 10 == 0:
                logger.info(f"Completed {i + 1}/{len(param_combinations)} combinations")
                
        except Exception as e:
            logger.error(f"Error in combination {params}: {e}")
    
    return results

def _evaluate_combination(params: Dict, btc_df: pd.DataFrame, eth_df: pd.DataFrame,
                         max_bars_in_trade: int, enable_hurst_filter: bool) -> Dict[str, Any]:
    """
    Evaluate a single parameter combination.
    
    Args:
        params: Parameter combination dictionary
        btc_df: BTC DataFrame
        eth_df: ETH DataFrame
        max_bars_in_trade: Maximum bars in trade
        enable_hurst_filter: Whether to enable Hurst filter
        
    Returns:
        Dictionary with results and metrics
    """
    # Run backtest for BTC
    btc_result = backtest_meanrev_15m(
        btc_df,
        z_entry=params['z_entry'],
        z_exit=params['z_exit'],
        hurst_max=params['hurst_max'],
        max_bars_in_trade=max_bars_in_trade,
        enable_hurst_filter=enable_hurst_filter
    )
    
    # Run backtest for ETH
    eth_result = backtest_meanrev_15m(
        eth_df,
        z_entry=params['z_entry'],
        z_exit=params['z_exit'],
        hurst_max=params['hurst_max'],
        max_bars_in_trade=max_bars_in_trade,
        enable_hurst_filter=enable_hurst_filter
    )
    
    # Combine results
    combined_result = _combine_backtest_results(btc_result, eth_result)
    
    # Calculate composite score
    composite_score = _calculate_composite_score(combined_result)
    
    # Create result dictionary
    result = {
        'z_entry': params['z_entry'],
        'z_exit': params['z_exit'],
        'hurst_max': params['hurst_max'],
        'composite_score': composite_score,
        'sharpe_ratio': combined_result['sharpe_ratio'],
        'max_drawdown': combined_result['max_drawdown'],
        'final_pnl': combined_result['final_pnl'],
        'win_rate_btc': btc_result.win_rate,
        'win_rate_eth': eth_result.win_rate,
        'total_trades': combined_result['total_trades'],
        'profit_factor': combined_result['profit_factor'],
        'calmar_ratio': combined_result['calmar_ratio'],
        'btc_trades': len(btc_result.trades),
        'eth_trades': len(eth_result.trades),
        'btc_pnl': btc_result.total_pnl,
        'eth_pnl': eth_result.total_pnl,
        'btc_sharpe': btc_result.sharpe_ratio,
        'eth_sharpe': eth_result.sharpe_ratio,
        'btc_dd': btc_result.max_drawdown,
        'eth_dd': eth_result.max_drawdown
    }
    
    return result

def _combine_backtest_results(btc_result: BacktestResult, eth_result: BacktestResult) -> Dict[str, Any]:
    """Combine backtest results from multiple assets."""
    # Combine equity curves
    if len(btc_result.equity_curve) > len(eth_result.equity_curve):
        combined_equity = btc_result.equity_curve.copy()
        combined_equity += eth_result.equity_curve.reindex(combined_equity.index, method='ffill').fillna(0)
    else:
        combined_equity = eth_result.equity_curve.copy()
        combined_equity += btc_result.equity_curve.reindex(combined_equity.index, method='ffill').fillna(0)
    
    # Combine trades
    all_trades = btc_result.trades + eth_result.trades
    all_pnls = [t.pnl for t in all_trades]
    
    # Calculate combined metrics
    total_pnl = sum(all_pnls)
    total_trades = len(all_trades)
    
    # Win rates
    wins = [p for p in all_pnls if p > 0]
    losses = [p for p in all_pnls if p <= 0]
    win_rate = len(wins) / total_trades if total_trades > 0 else 0.0
    
    # Profit factor
    profit_factor = sum(wins) / abs(sum(losses)) if losses else float('inf')
    
    # Risk metrics
    returns = combined_equity.pct_change().dropna()
    sharpe_ratio = returns.mean() / returns.std() * np.sqrt(252 * 24 * 4) if returns.std() > 0 else 0.0
    max_drawdown = (combined_equity - combined_equity.cummax()).min() / combined_equity.cummax().max()
    calmar_ratio = (combined_equity.iloc[-1] / combined_equity.iloc[0] - 1) / abs(max_drawdown) if max_drawdown != 0 else 0.0
    
    return {
        'equity_curve': combined_equity,
        'final_pnl': total_pnl,
        'total_trades': total_trades,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'sharpe_ratio': sharpe_ratio,
        'max_drawdown': max_drawdown,
        'calmar_ratio': calmar_ratio,
        'returns': returns
    }

def _calculate_composite_score(combined_result: Dict[str, Any]) -> float:
    """
    Calculate composite score for ranking parameter combinations.
    
    Ranking criteria: Sharpe, then PnL, then drawdown penalty.
    """
    sharpe = combined_result['sharpe_ratio']
    pnl = combined_result['final_pnl']
    max_dd = combined_result['max_drawdown']
    
    # Base score from Sharpe
    base_score = sharpe * 100  # Scale Sharpe for visibility
    
    # PnL bonus (scaled)
    pnl_bonus = np.sign(pnl) * np.log10(abs(pnl) + 1) * 10  # Log scale for PnL
    
    # Drawdown penalty
    dd_penalty = abs(max_dd) * 50  # Penalize large drawdowns
    
    # Win rate bonus
    win_rate_bonus = combined_result['win_rate'] * 20
    
    # Composite score
    composite_score = base_score + pnl_bonus + win_rate_bonus - dd_penalty
    
    return composite_score

def analyze_optimization_results(results: List[Dict[str, Any]], top_n: int = 10) -> Dict[str, Any]:
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
    
    # Parameter statistics
    z_entries = [r['z_entry'] for r in results]
    z_exits = [r['z_exit'] for r in results]
    hurst_values = [r['hurst_max'] for r in results]
    
    # Performance statistics
    sharpes = [r['sharpe_ratio'] for r in results]
    pnls = [r['final_pnl'] for r in results]
    drawdowns = [r['max_drawdown'] for r in results]
    
    analysis = {
        'total_combinations': len(results),
        'top_results': top_results,
        'parameter_insights': {
            'z_entry_range': (min(z_entries), max(z_entries)),
            'z_exit_range': (min(z_exits), max(z_exits)),
            'hurst_range': (min(hurst_values), max(hurst_values)),
            'z_entry_std': np.std(z_entries),
            'z_exit_std': np.std(z_exits),
            'hurst_std': np.std(hurst_values)
        },
        'performance_insights': {
            'best_sharpe': max(sharpes),
            'worst_sharpe': min(sharpes),
            'avg_sharpe': np.mean(sharpes),
            'best_pnl': max(pnls),
            'worst_pnl': min(pnls),
            'avg_pnl': np.mean(pnls),
            'best_dd': min(drawdowns),  # Least negative
            'worst_dd': max(drawdowns),  # Most negative
            'avg_dd': np.mean(drawdowns)
        },
        'top_parameters': {
            'avg_z_entry': np.mean([r['z_entry'] for r in top_results]),
            'avg_z_exit': np.mean([r['z_exit'] for r in top_results]),
            'avg_hurst_max': np.mean([r['hurst_max'] for r in top_results])
        },
        'stability_analysis': {
            'parameter_stability': _calculate_parameter_stability(top_results),
            'performance_consistency': _calculate_performance_consistency(top_results)
        }
    }
    
    return analysis

def _calculate_parameter_stability(top_results: List[Dict[str, Any]]) -> Dict[str, float]:
    """Calculate stability of parameters in top results."""
    if len(top_results) < 2:
        return {"z_entry_cv": 0.0, "z_exit_cv": 0.0, "hurst_cv": 0.0}
    
    z_entries = [r['z_entry'] for r in top_results]
    z_exits = [r['z_exit'] for r in top_results]
    hurst_values = [r['hurst_max'] for r in top_results]
    
    # Coefficient of variation (lower = more stable)
    z_entry_cv = np.std(z_entries) / np.mean(z_entries) if np.mean(z_entries) > 0 else float('inf')
    z_exit_cv = np.std(z_exits) / np.mean(z_exits) if np.mean(z_exits) > 0 else float('inf')
    hurst_cv = np.std(hurst_values) / np.mean(hurst_values) if np.mean(hurst_values) > 0 else float('inf')
    
    return {
        "z_entry_cv": z_entry_cv,
        "z_exit_cv": z_exit_cv,
        "hurst_cv": hurst_cv
    }

def _calculate_performance_consistency(top_results: List[Dict[str, Any]]) -> Dict[str, float]:
    """Calculate consistency of performance in top results."""
    if len(top_results) < 2:
        return {"sharpe_cv": 0.0, "pnl_cv": 0.0, "dd_cv": 0.0}
    
    sharpes = [r['sharpe_ratio'] for r in top_results]
    pnls = [r['final_pnl'] for r in top_results]
    drawdowns = [r['max_drawdown'] for r in top_results]
    
    # Coefficient of variation for performance metrics
    sharpe_cv = np.std(sharpes) / np.mean(sharpes) if np.mean(sharpes) > 0 else float('inf')
    pnl_cv = np.std(pnls) / np.mean(np.abs(pnls)) if len(pnls) > 0 else float('inf')
    dd_cv = np.std(drawdowns) / np.mean(np.abs(drawdowns)) if len(drawdowns) > 0 else float('inf')
    
    return {
        "sharpe_cv": sharpe_cv,
        "pnl_cv": pnl_cv,
        "dd_cv": dd_cv
    }

def save_optimization_results(results: List[Dict[str, Any]], filename: str = None) -> str:
    """
    Save optimization results to CSV.
    
    Args:
        results: Optimization results
        filename: Output filename
        
    Returns:
        Filename of saved file
    """
    from datetime import datetime
    
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"z_optimization_{timestamp}.csv"
    
    # Convert to DataFrame
    df = pd.DataFrame(results)
    
    # Reorder columns for readability
    column_order = ['z_entry', 'z_exit', 'hurst_max', 'composite_score', 'sharpe_ratio',
                    'max_drawdown', 'final_pnl', 'win_rate_btc', 'win_rate_eth',
                    'total_trades', 'profit_factor', 'calmar_ratio']
    
    # Ensure all columns exist
    for col in column_order:
        if col not in df.columns:
            df[col] = None
    
    # Reorder and save
    df = df[column_order + [col for col in df.columns if col not in column_order]]
    df.to_csv(filename, index=False)
    
    logger.info(f"Saved {len(results)} optimization results to {filename}")
    
    return filename

def print_optimization_summary(results: List[Dict[str, Any]], top_n: int = 10):
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
    print("Z-SCORE OPTIMIZATION SUMMARY")
    print("="*80)
    
    # Top results table
    print(f"\nTop {top_n} Results:")
    print("-" * 80)
    print(f"{'Rank':<4} {'Z-Entry':<8} {'Z-Exit':<8} {'Hurst':<6} {'Sharpe':<8} {'PnL':<10} {'DD':<8} {'Score':<8} {'Trades':<8}")
    print("-" * 80)
    
    for i, result in enumerate(results[:top_n]):
        print(f"{i+1:<4} {result['z_entry']:<8.2f} {result['z_exit']:<8.2f} "
              f"{result['hurst_max']:<6.2f} {result['sharpe_ratio']:<8.2f} "
              f"${result['final_pnl']:<9.0f} {result['max_drawdown']:<8.2%} "
              f"{result['composite_score']:<8.1f} {result['total_trades']:<8}")
    
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
    print(f"  Best Sharpe: {analysis['performance_insights']['best_sharpe']:.2f}")
    print(f"  Best PnL: ${analysis['performance_insights']['best_pnl']:,.0f}")
    print(f"  Best Drawdown: {analysis['performance_insights']['best_dd']:.2%}")
    print(f"  Average Sharpe: {analysis['performance_insights']['avg_sharpe']:.2f}")
    
    print(f"\nTop Parameters (Average):")
    print(f"  Z-Entry: {analysis['top_parameters']['avg_z_entry']:.2f}")
    print(f"  Z-Exit: {analysis['top_parameters']['avg_z_exit']:.2f}")
    print(f"  Hurst Max: {analysis['top_parameters']['avg_hurst_max']:.2f}")
    
    # Stability analysis
    stability = analysis['stability_analysis']['parameter_stability']
    print(f"\nParameter Stability:")
    print(f"  Z-Entry CV: {stability['z_entry_cv']:.3f}")
    print(f"  Z-Exit CV: {stability['z_exit_cv']:.3f}")
    print(f"  Hurst CV: {stability['hurst_cv']:.3f}")
    
    print("="*80)

# Example usage:
"""
import pandas as pd
import numpy as np

# Generate sample data
np.random.seed(42)
dates = pd.date_range(start='2024-01-01', periods=1000, freq='15min')

# BTC data
btc_prices = 50000 + np.cumsum(np.random.randn(1000) * 100)
df_btc = pd.DataFrame({
    'open': btc_prices,
    'high': btc_prices * (1 + np.abs(np.random.randn(1000) * 0.001)),
    'low': btc_prices * (1 - np.abs(np.random.randn(1000) * 0.001)),
    'close': btc_prices,
    'volume': np.random.randint(1000, 10000, 1000)
}, index=dates)

# ETH data
eth_prices = 3000 + np.cumsum(np.random.randn(1000) * 50)
df_eth = pd.DataFrame({
    'open': eth_prices,
    'high': eth_prices * (1 + np.abs(np.random.randn(1000) * 0.001)),
    'low': eth_prices * (1 - np.abs(np.random.randn(1000) * 0.001)),
    'close': eth_prices,
    'volume': np.random.randint(500, 5000, 1000)
}, index=dates)

# Run optimization
results = optimize_z_grid(df_btc, df_eth, parallel=True)

# Print summary
print_optimization_summary(results, top_n=10)

# Save results
filename = save_optimization_results(results)
print(f"Results saved to: {filename}")
"""
