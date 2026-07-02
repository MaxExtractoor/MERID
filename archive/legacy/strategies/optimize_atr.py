"""
ATR Optimization - Optimize ATR Multiplier/Period for Crypto Volatility

Grid search over ATR period and multiplier for volatility-aware sizing.
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed

from .atr_sizing import compute_atr
from .backtest_15m_meanrev import backtest_meanrev_15m
from .max_drawdown_metric import max_drawdown

logger = logging.getLogger(__name__)

def backtest_with_atr_sizing(df: pd.DataFrame, atr_period: int, atr_mult: float,
                           z_entry: float = 1.0, z_exit: float = 0.1, hurst_max: float = 0.5) -> Dict[str, Any]:
    """
    Backtest with ATR-based sizing evaluation.
    
    Args:
        df: OHLCV DataFrame
        atr_period: ATR calculation period
        atr_mult: ATR multiplier for sizing
        z_entry: Z-score entry threshold
        z_exit: Z-score exit threshold
        hurst_max: Hurst exponent threshold
        
    Returns:
        Dictionary with backtest results and ATR metrics
    """
    try:
        # Calculate ATR
        atr = compute_atr(df, period=atr_period)
        
        # Add ATR to DataFrame for potential use in backtest
        df_bt = df.copy()
        df_bt["atr"] = atr
        
        # Run backtest
        res = backtest_meanrev_15m(df_bt, z_entry=z_entry, z_exit=z_exit, hurst_max=hurst_max)
        
        # Calculate metrics
        eq = res.equity_curve
        dd = max_drawdown(eq)
        total_pnl = float(eq.iloc[-1])
        
        # ATR statistics
        atr_stats = {
            "current_atr": atr.iloc[-1],
            "avg_atr": atr.mean(),
            "atr_std": atr.std(),
            "atr_pct_of_price": atr.iloc[-1] / df['close'].iloc[-1] if df['close'].iloc[-1] > 0 else 0.0
        }
        
        # Risk-adjusted return
        risk_adjusted_return = total_pnl / abs(dd) if dd != 0 else total_pnl
        
        return {
            "atr_period": atr_period,
            "atr_mult": atr_mult,
            "equity_curve": eq,
            "max_drawdown": dd,
            "pnl": total_pnl,
            "win_rate": res.win_rate,
            "total_trades": len(res.trades),
            "sharpe_ratio": res.sharpe_ratio,
            "atr_stats": atr_stats,
            "risk_adjusted_return": risk_adjusted_return,
            "profit_factor": res.total_pnl / abs(min([t.pnl for t in res.trades], default=1)) if res.trades else 0.0
        }
        
    except Exception as e:
        logger.error(f"Error in ATR backtest for period={atr_period}, mult={atr_mult}: {e}")
        return {
            "atr_period": atr_period,
            "atr_mult": atr_mult,
            "error": str(e),
            "pnl": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "total_trades": 0,
            "sharpe_ratio": 0.0
        }

def optimize_atr_params(df: pd.DataFrame,
                        atr_periods: Optional[List[int]] = None,
                        atr_multipliers: Optional[List[float]] = None,
                        z_entry: float = 1.0,
                        z_exit: float = 0.1,
                        hurst_max: float = 0.5,
                        parallel: bool = True,
                        max_workers: int = 4) -> List[Dict[str, Any]]:
    """
    Optimize ATR parameters using grid search.
    
    Args:
        df: OHLCV DataFrame
        atr_periods: List of ATR periods to test
        atr_multipliers: List of ATR multipliers to test
        z_entry: Z-score entry threshold
        z_exit: Z-score exit threshold
        hurst_max: Hurst exponent threshold
        parallel: Whether to use parallel processing
        max_workers: Number of parallel workers
        
    Returns:
        List of results sorted by risk-adjusted return
    """
    # Default parameter grids
    if atr_periods is None:
        atr_periods = [7, 14, 21, 28]  # Weekly to monthly ranges
    
    if atr_multipliers is None:
        atr_multipliers = [1.0, 1.5, 2.0, 3.0]  # Conservative to aggressive
    
    # Generate parameter combinations
    combinations = []
    for period in atr_periods:
        for mult in atr_multipliers:
            combinations.append((period, mult))
    
    total_combinations = len(combinations)
    logger.info(f"ATR optimization: {total_combinations} combinations "
                f"({len(atr_periods)} periods × {len(atr_multipliers)} multipliers)")
    
    if parallel and total_combinations > 4:
        results = _parallel_atr_optimization(df, combinations, z_entry, z_exit, hurst_max, max_workers)
    else:
        results = _sequential_atr_optimization(df, combinations, z_entry, z_exit, hurst_max)
    
    # Sort by risk-adjusted return (PnL / |max_drawdown|)
    valid_results = [r for r in results if 'error' not in r]
    results_sorted = sorted(
        valid_results,
        key=lambda r: r["risk_adjusted_return"],
        reverse=True
    )
    
    logger.info(f"ATR optimization completed: {len(results_sorted)} valid results")
    
    return results_sorted

def _parallel_atr_optimization(df: pd.DataFrame, combinations: List[Tuple[int, float]],
                               z_entry: float, z_exit: float, hurst_max: float,
                               max_workers: int) -> List[Dict[str, Any]]:
    """Execute ATR optimization in parallel."""
    results = []
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_params = {
            executor.submit(backtest_with_atr_sizing, df, period, mult, z_entry, z_exit, hurst_max): (period, mult)
            for period, mult in combinations
        }
        
        # Collect results
        completed = 0
        for future in as_completed(future_to_params):
            try:
                result = future.result()
                results.append(result)
                completed += 1
                
                if completed % 5 == 0:
                    logger.info(f"Completed {completed}/{len(combinations)} ATR combinations")
                    
            except Exception as e:
                period, mult = future_to_params[future]
                logger.error(f"Error in ATR combination {period, mult}: {e}")
    
    return results

def _sequential_atr_optimization(df: pd.DataFrame, combinations: List[Tuple[int, float]],
                                 z_entry: float, z_exit: float, hurst_max: float) -> List[Dict[str, Any]]:
    """Execute ATR optimization sequentially."""
    results = []
    
    for i, (period, mult) in enumerate(combinations):
        try:
            result = backtest_with_atr_sizing(df, period, mult, z_entry, z_exit, hurst_max)
            results.append(result)
            
            if (i + 1) % 5 == 0:
                logger.info(f"Completed {i + 1}/{len(combinations)} ATR combinations")
                
        except Exception as e:
            logger.error(f"Error in ATR combination {period, mult}: {e}")
    
    return results

def analyze_atr_optimization_results(results: List[Dict[str, Any]], top_n: int = 10) -> Dict[str, Any]:
    """
    Analyze ATR optimization results and provide insights.
    
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
    periods = [r["atr_period"] for r in results]
    multipliers = [r["atr_mult"] for r in results]
    
    # Performance statistics
    pnls = [r["pnl"] for r in results]
    drawdowns = [r["max_drawdown"] for r in results]
    sharpe_ratios = [r["sharpe_ratio"] for r in results]
    risk_adj_returns = [r["risk_adjusted_return"] for r in results]
    
    analysis = {
        "total_combinations": len(results),
        "top_results": top_results,
        "parameter_insights": {
            "period_range": (min(periods), max(periods)),
            "mult_range": (min(multipliers), max(multipliers)),
            "avg_period": np.mean(periods),
            "avg_mult": np.mean(multipliers),
            "period_std": np.std(periods),
            "mult_std": np.std(multipliers)
        },
        "performance_insights": {
            "best_pnl": max(pnls),
            "worst_pnl": min(pnls),
            "avg_pnl": np.mean(pnls),
            "best_sharpe": max(sharpe_ratios),
            "avg_sharpe": np.mean(sharpe_ratios),
            "best_risk_adj_return": max(risk_adj_returns),
            "avg_risk_adj_return": np.mean(risk_adj_returns)
        },
        "top_parameters": {
            "avg_period": np.mean([r["atr_period"] for r in top_results]),
            "avg_mult": np.mean([r["atr_mult"] for r in top_results]),
            "period_frequency": _calculate_parameter_frequency(top_results, "atr_period"),
            "mult_frequency": _calculate_parameter_frequency(top_results, "atr_mult")
        },
        "stability_analysis": {
            "parameter_stability": _calculate_atr_stability(top_results),
            "performance_consistency": _calculate_performance_consistency(top_results)
        }
    }
    
    return analysis

def _calculate_parameter_frequency(results: List[Dict[str, Any]], param_name: str) -> Dict[int, int]:
    """Calculate frequency of parameter values in top results."""
    values = [r[param_name] for r in results]
    frequency = {}
    for value in values:
        frequency[value] = frequency.get(value, 0) + 1
    return frequency

def _calculate_atr_stability(results: List[Dict[str, Any]]) -> Dict[str, float]:
    """Calculate stability of ATR parameters in top results."""
    if len(results) < 2:
        return {"period_cv": 0.0, "mult_cv": 0.0}
    
    periods = [r["atr_period"] for r in results]
    multipliers = [r["atr_mult"] for r in results]
    
    # Coefficient of variation (lower = more stable)
    period_cv = np.std(periods) / np.mean(periods) if np.mean(periods) > 0 else float('inf')
    mult_cv = np.std(multipliers) / np.mean(multipliers) if np.mean(multipliers) > 0 else float('inf')
    
    return {
        "period_cv": period_cv,
        "mult_cv": mult_cv
    }

def _calculate_performance_consistency(results: List[Dict[str, Any]]) -> Dict[str, float]:
    """Calculate consistency of performance in top results."""
    if len(results) < 2:
        return {"pnl_cv": 0.0, "sharpe_cv": 0.0}
    
    pnls = [r["pnl"] for r in results]
    sharpe_ratios = [r["sharpe_ratio"] for r in results]
    
    # Coefficient of variation for performance metrics
    pnl_cv = np.std(pnls) / np.mean(np.abs(pnls)) if len(pnls) > 0 else float('inf')
    sharpe_cv = np.std(sharpe_ratios) / np.mean(np.abs(sharpe_ratios)) if len(sharpe_ratios) > 0 else float('inf')
    
    return {
        "pnl_cv": pnl_cv,
        "sharpe_cv": sharpe_cv
    }

def save_atr_optimization_results(results: List[Dict[str, Any]], filename: str = None) -> str:
    """
    Save ATR optimization results to CSV.
    
    Args:
        results: Optimization results
        filename: Output filename
        
    Returns:
        Filename of saved file
    """
    from datetime import datetime
    
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"atr_optimization_{timestamp}.csv"
    
    # Convert to DataFrame
    data = []
    for result in results:
        if 'error' not in result:
            data.append({
                'atr_period': result['atr_period'],
                'atr_mult': result['atr_mult'],
                'pnl': result['pnl'],
                'max_drawdown': result['max_drawdown'],
                'win_rate': result['win_rate'],
                'total_trades': result['total_trades'],
                'sharpe_ratio': result['sharpe_ratio'],
                'risk_adjusted_return': result['risk_adjusted_return'],
                'profit_factor': result['profit_factor'],
                'current_atr': result.get('atr_stats', {}).get('current_atr', 0.0),
                'atr_pct_of_price': result.get('atr_stats', {}).get('atr_pct_of_price', 0.0)
            })
    
    if data:
        df = pd.DataFrame(data)
        df.to_csv(filename, index=False)
        logger.info(f"Saved {len(data)} ATR optimization results to {filename}")
    else:
        logger.warning("No valid results to save")
    
    return filename

def print_atr_optimization_summary(results: List[Dict[str, Any]], top_n: int = 10):
    """
    Print formatted ATR optimization summary.
    
    Args:
        results: Optimization results
        top_n: Number of top results to display
    """
    if not results:
        print("No ATR optimization results to display")
        return
    
    print("\n" + "="*80)
    print("ATR OPTIMIZATION SUMMARY")
    print("="*80)
    
    # Top results table
    print(f"\nTop {top_n} Results:")
    print("-" * 80)
    print(f"{'Rank':<4} {'Period':<8} {'Mult':<6} {'PnL':<10} {'DD':<8} {'Sharpe':<8} {'Trades':<8} {'RiskAdj':<10}")
    print("-" * 80)
    
    for i, result in enumerate(results[:top_n]):
        print(f"{i+1:<4} {result['atr_period']:<8} {result['atr_mult']:<6.1f} "
              f"${result['pnl']:<9.0f} {result['max_drawdown']:<8.2%} "
              f"{result['sharpe_ratio']:<8.2f} {result['total_trades']:<8} "
              f"{result['risk_adjusted_return']:<10.1f}")
    
    # Analysis
    analysis = analyze_atr_optimization_results(results, top_n)
    
    print(f"\nParameter Insights:")
    print(f"  Period Range: {analysis['parameter_insights']['period_range'][0]} - "
          f"{analysis['parameter_insights']['period_range'][1]}")
    print(f"  Multiplier Range: {analysis['parameter_insights']['mult_range'][0]:.1f} - "
          f"{analysis['parameter_insights']['mult_range'][1]:.1f}")
    print(f"  Average Period: {analysis['parameter_insights']['avg_period']:.1f}")
    print(f"  Average Multiplier: {analysis['parameter_insights']['avg_mult']:.2f}")
    
    print(f"\nPerformance Insights:")
    print(f"  Best PnL: ${analysis['performance_insights']['best_pnl']:,.0f}")
    print(f"  Best Sharpe: {analysis['performance_insights']['best_sharpe']:.2f}")
    print(f"  Best Risk-Adjusted Return: {analysis['performance_insights']['best_risk_adj_return']:.1f}")
    print(f"  Average PnL: ${analysis['performance_insights']['avg_pnl']:,.0f}")
    
    print(f"\nTop Parameters (Average):")
    print(f"  Period: {analysis['top_parameters']['avg_period']:.1f}")
    print(f"  Multiplier: {analysis['top_parameters']['avg_mult']:.2f}")
    
    # Parameter frequency
    period_freq = analysis['top_parameters']['period_frequency']
    mult_freq = analysis['top_parameters']['mult_frequency']
    
    print(f"\nParameter Frequency (Top {top_n}):")
    print(f"  Periods: {dict(list(period_freq.items())[:3])}")  # Top 3
    print(f"  Multipliers: {dict(list(mult_freq.items())[:3])}")  # Top 3
    
    # Stability analysis
    stability = analysis['stability_analysis']['parameter_stability']
    print(f"\nParameter Stability:")
    print(f"  Period CV: {stability['period_cv']:.3f}")
    print(f"  Multiplier CV: {stability['mult_cv']:.3f}")
    
    print("="*80)

# Example usage:
"""
import pandas as pd
import numpy as np

# Generate sample data
np.random.seed(42)
dates = pd.date_range(start='2024-01-01', periods=1000, freq='15min')
base_price = 50000
price_changes = np.random.randn(1000) * 100
prices = base_price + np.cumsum(price_changes)

df = pd.DataFrame({
    'open': prices,
    'high': prices * (1 + np.abs(np.random.randn(1000) * 0.001)),
    'low': prices * (1 - np.abs(np.random.randn(1000) * 0.001)),
    'close': prices,
    'volume': np.random.randint(1000, 10000, 1000)
}, index=dates)

# Optimize ATR parameters
results = optimize_atr_params(df, parallel=True)

# Print summary
print_atr_optimization_summary(results, top_n=10)

# Save results
filename = save_atr_optimization_results(results)
print(f"Results saved to: {filename}")
"""
