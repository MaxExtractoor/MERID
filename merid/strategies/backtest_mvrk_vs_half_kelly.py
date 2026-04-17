"""
Backtest MVRK vs Fractional Kelly on Crypto Events

Comprehensive backtest comparison between MVRK and fractional Kelly strategies.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)

@dataclass
class MvrkVsKellyResult:
    """Results of MVRK vs fractional Kelly backtest comparison."""
    eq_half_kelly: pd.Series
    eq_mvrk: pd.Series
    ruin_half: float
    ruin_mvrk: float
    half_kelly_metrics: Dict[str, float]
    mvrk_metrics: Dict[str, float]
    performance_comparison: Dict[str, float]
    risk_comparison: Dict[str, float]
    recommendations: List[str]

def backtest_mvrk_vs_half_kelly(returns_df: pd.DataFrame,
                               theta: float = 1.0,
                               ruin_level: float = 0.5,
                               n_paths: int = 5000) -> MvrkVsKellyResult:
    """
    Backtest MVRK vs half Kelly on crypto events.
    
    Args:
        returns_df: DataFrame with per-trade returns (columns = assets)
        theta: MVRK theta parameter
        ruin_level: Risk of ruin threshold
        n_paths: Number of Monte Carlo paths for risk analysis
        
    Returns:
        MvrkVsKellyResult with comprehensive comparison
    """
    if returns_df.empty:
        raise ValueError("Empty returns DataFrame")
    
    logger.info(f"Backtesting MVRK vs half Kelly: {len(returns_df)} periods, {len(returns_df.columns)} assets")
    
    # Import required modules
    try:
        from .mvrk_kalshi import run_mvrk_on_kalshi
        from .kalshi_half_kelly_portfolio import build_half_kelly_portfolio
        from .kalshi_multivariate_ror import mc_ror_correlated
    except ImportError as e:
        logger.error(f"Import error: {e}")
        raise
    
    # Half Kelly portfolio
    half_port = build_half_kelly_portfolio(returns_df)
    
    # MVRK portfolio
    mvrk_res = run_mvrk_on_kalshi(returns_df, theta=theta)
    
    # Calculate performance metrics
    half_metrics = calculate_portfolio_metrics(half_port.equity, returns_df, half_port.weights)
    mvrk_metrics = calculate_portfolio_metrics(mvrk_res.eq_mvrk, returns_df, mvrk_res.w_mvrk)
    
    # Risk of ruin estimates
    ruin_half = mc_ror_correlated(returns_df, half_port.weights, ruin_level=ruin_level, n_paths=n_paths)
    ruin_mvrk = mc_ror_correlated(returns_df, mvrk_res.w_mvrk, ruin_level=ruin_level, n_paths=n_paths)
    
    # Performance comparison
    performance_comparison = compare_performance_metrics(half_metrics, mvrk_metrics)
    
    # Risk comparison
    risk_comparison = compare_risk_metrics(ruin_half, ruin_mvrk, half_metrics, mvrk_metrics)
    
    # Generate recommendations
    recommendations = generate_backtest_recommendations(
        half_metrics, mvrk_metrics, ruin_half, ruin_mvrk, performance_comparison, risk_comparison
    )
    
    logger.info(f"Backtest completed: Half Kelly return={half_metrics['total_return']:.2%}, "
                f"MVRK return={mvrk_metrics['total_return']:.2%}")
    
    return MvrkVsKellyResult(
        eq_half_kelly=half_port.equity,
        eq_mvrk=mvrk_res.eq_mvrk,
        ruin_half=ruin_half,
        ruin_mvrk=ruin_mvrk,
        half_kelly_metrics=half_metrics,
        mvrk_metrics=mvrk_metrics,
        performance_comparison=performance_comparison,
        risk_comparison=risk_comparison,
        recommendations=recommendations
    )

def calculate_portfolio_metrics(equity: pd.Series, 
                              returns_df: pd.DataFrame,
                              weights: np.ndarray) -> Dict[str, float]:
    """
    Calculate comprehensive portfolio performance metrics.
    
    Args:
        equity: Portfolio equity curve
        returns_df: Asset returns DataFrame
        weights: Portfolio weights
        
    Returns:
        Performance metrics dictionary
    """
    if equity.empty:
        return {}
    
    # Basic return metrics
    total_return = (equity.iloc[-1] / equity.iloc[0]) - 1
    
    # Calculate portfolio returns
    port_rets = equity.pct_change().dropna()
    
    # Annualization factor (assuming 15m bars)
    periods_per_year = 365 * 24 * 4
    
    # Sharpe ratio
    if len(port_rets) > 1 and port_rets.std() > 0:
        sharpe_ratio = port_rets.mean() / port_rets.std() * np.sqrt(periods_per_year)
    else:
        sharpe_ratio = 0.0
    
    # Sortino ratio
    downside_rets = port_rets[port_rets < 0]
    if len(downside_rets) > 0 and downside_rets.std() > 0:
        sortino_ratio = port_rets.mean() / downside_rets.std() * np.sqrt(periods_per_year)
    else:
        sortino_ratio = 0.0
    
    # Max drawdown
    peak = equity.cummax()
    drawdown = (equity - peak) / peak.replace(0, np.nan)
    max_drawdown = drawdown.min()
    
    # Win rate
    win_rate = (port_rets > 0).sum() / len(port_rets)
    
    # Portfolio volatility
    portfolio_vol = port_rets.std() * np.sqrt(periods_per_year)
    
    # Leverage
    leverage = np.sum(np.abs(weights))
    
    # Calmar ratio
    if max_drawdown != 0:
        calmar_ratio = total_return / abs(max_drawdown)
    else:
        calmar_ratio = 0.0
    
    return {
        "total_return": total_return,
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "max_drawdown": max_drawdown,
        "win_rate": win_rate,
        "portfolio_volatility": portfolio_vol,
        "leverage": leverage,
        "calmar_ratio": calmar_ratio,
        "final_capital": equity.iloc[-1]
    }

def compare_performance_metrics(half_metrics: Dict[str, float],
                               mvrk_metrics: Dict[str, float]) -> Dict[str, float]:
    """
    Compare performance metrics between half Kelly and MVRK.
    
    Args:
        half_metrics: Half Kelly portfolio metrics
        mvrk_metrics: MVRK portfolio metrics
        
    Returns:
        Performance comparison dictionary
    """
    comparison = {}
    
    # Key performance metrics
    metrics_to_compare = [
        "total_return", "sharpe_ratio", "sortino_ratio", "max_drawdown", 
        "win_rate", "portfolio_volatility", "calmar_ratio"
    ]
    
    for metric in metrics_to_compare:
        half_val = half_metrics.get(metric, 0)
        mvrk_val = mvrk_metrics.get(metric, 0)
        
        if metric == "max_drawdown":
            # For drawdown, improvement is less negative
            if half_val != 0:
                improvement = (mvrk_val - half_val) / abs(half_val)
            else:
                improvement = 0.0
        elif half_val != 0:
            improvement = (mvrk_val - half_val) / abs(half_val)
        else:
            improvement = 0.0
        
        comparison[f"{metric}_improvement"] = improvement
        comparison[f"{metric}_difference"] = mvrk_val - half_val
    
    return comparison

def compare_risk_metrics(ruin_half: float,
                         ruin_mvrk: float,
                         half_metrics: Dict[str, float],
                         mvrk_metrics: Dict[str, float]) -> Dict[str, float]:
    """
    Compare risk metrics between half Kelly and MVRK.
    
    Args:
        ruin_half: Half Kelly risk of ruin
        ruin_mvrk: MVRK risk of ruin
        half_metrics: Half Kelly portfolio metrics
        mvrk_metrics: MVRK portfolio metrics
        
    Returns:
        Risk comparison dictionary
    """
    comparison = {}
    
    # Risk of ruin comparison
    if ruin_half > 0:
        ruin_improvement = (ruin_half - ruin_mvrk) / ruin_half
    else:
        ruin_improvement = 0.0
    
    comparison["ruin_improvement"] = ruin_improvement
    comparison["ruin_reduction_bps"] = (ruin_half - ruin_mvrk) * 10000
    comparison["ruin_difference"] = ruin_half - ruin_mvrk
    
    # Drawdown comparison
    half_dd = half_metrics.get("max_drawdown", 0)
    mvrk_dd = mvrk_metrics.get("max_drawdown", 0)
    
    if half_dd != 0:
        dd_improvement = (mvrk_dd - half_dd) / abs(half_dd)
    else:
        dd_improvement = 0.0
    
    comparison["drawdown_improvement"] = dd_improvement
    comparison["drawdown_difference"] = mvrk_dd - half_dd
    
    # Volatility comparison
    half_vol = half_metrics.get("portfolio_volatility", 0)
    mvrk_vol = mvrk_metrics.get("portfolio_volatility", 0)
    
    if half_vol != 0:
        vol_improvement = (mvrk_vol - half_vol) / half_vol
    else:
        vol_improvement = 0.0
    
    comparison["volatility_improvement"] = vol_improvement
    comparison["volatility_difference"] = mvrk_vol - half_vol
    
    return comparison

def generate_backtest_recommendations(half_metrics: Dict[str, float],
                                      mvrk_metrics: Dict[str, float],
                                      ruin_half: float,
                                      ruin_mvrk: float,
                                      performance_comparison: Dict[str, float],
                                      risk_comparison: Dict[str, float]) -> List[str]:
    """
    Generate recommendations based on backtest comparison.
    
    Args:
        half_metrics: Half Kelly portfolio metrics
        mvrk_metrics: MVRK portfolio metrics
        ruin_half: Half Kelly risk of ruin
        ruin_mvrk: MVRK risk of ruin
        performance_comparison: Performance comparison results
        risk_comparison: Risk comparison results
        
    Returns:
        List of recommendations
    """
    recommendations = []
    
    # Overall recommendation
    mvrk_better = (performance_comparison.get("sharpe_ratio_improvement", 0) > 0 and 
                   risk_comparison.get("ruin_improvement", 0) > 0)
    
    if mvrk_better:
        recommendations.append("🏆 **MVRK Strategy Recommended** - Better risk-adjusted returns")
    elif performance_comparison.get("sharpe_ratio_improvement", 0) > 0:
        recommendations.append("📈 **MVRK Strategy Recommended** - Higher returns")
    elif risk_comparison.get("ruin_improvement", 0) > 0:
        recommendations.append("🛡️ **MVRK Strategy Recommended** - Lower risk")
    else:
        recommendations.append("⚖️ **Half Kelly Strategy Recommended** - Better overall performance")
    
    # Performance recommendations
    sharpe_imp = performance_comparison.get("sharpe_ratio_improvement", 0)
    if sharpe_imp > 0.1:
        recommendations.append(f"✅ MVRK improves Sharpe ratio by {sharpe_imp:.2f}")
    elif sharpe_imp < -0.1:
        recommendations.append(f"⚠️ MVRK reduces Sharpe ratio by {abs(sharpe_imp):.2f}")
    
    return_imp = performance_comparison.get("total_return_improvement", 0)
    if return_imp > 0.05:
        recommendations.append(f"🚀 MVRK improves total return by {return_imp:.1%}")
    elif return_imp < -0.05:
        recommendations.append(f"📉 MVRK reduces total return by {abs(return_imp):.1%}")
    
    # Risk recommendations
    ruin_imp = risk_comparison.get("ruin_improvement", 0)
    if ruin_imp > 0.1:
        recommendations.append(f"🛡️ MVRK reduces risk of ruin by {ruin_imp:.1%}")
    elif ruin_imp < -0.1:
        recommendations.append(f"⚠️ MVRK increases risk of ruin by {abs(ruin_imp):.1%}")
    
    dd_imp = risk_comparison.get("drawdown_improvement", 0)
    if dd_imp > 0.05:
        recommendations.append(f"📈 MVRK improves max drawdown by {dd_imp:.1%}")
    elif dd_imp < -0.05:
        recommendations.append(f"📉 MVRK worsens max drawdown by {abs(dd_imp):.1%}")
    
    # Risk level assessment
    if ruin_mvrk < 0.05:
        recommendations.append("✅ MVRK strategy has acceptable risk levels")
    elif ruin_mvrk < 0.15:
        recommendations.append("🟡 MVRK strategy has moderate risk - monitor closely")
    else:
        recommendations.append("🔴 MVRK strategy has high risk - consider reducing position size")
    
    # General recommendations
    if mvrk_metrics.get("sharpe_ratio", 0) > 1.5:
        recommendations.append("🚀 Excellent risk-adjusted returns - consider increasing position size")
    elif mvrk_metrics.get("sharpe_ratio", 0) < 0.5:
        recommendations.append("⚠️ Low risk-adjusted returns - improve strategy signals")
    
    recommendations.append("💡 Consider combining MVRK with other risk controls like drawdown limits")
    recommendations.append("🔄 Re-run backtest periodically with updated market data")
    recommendations.append("📊 Monitor correlation changes between crypto assets")
    
    return recommendations

def print_backtest_results(result: MvrkVsKellyResult, title: str = "MVRK vs Half Kelly Backtest Results"):
    """
    Print formatted backtest comparison results.
    
    Args:
        result: MVRKVsKellyResult to display
        title: Results title
    """
    print(f"\n{title}")
    print("=" * 80)
    
    # Basic info
    print(f"\nStrategy Comparison:")
    print("-" * 60)
    print(f"{'Metric':<20} {'Half Kelly':<15} {'MVRK':<15} {'Improvement':<15}")
    print("-" * 60)
    
    # Performance metrics
    metrics = ["total_return", "sharpe_ratio", "max_drawdown", "win_rate", "calmar_ratio"]
    metric_names = ["Total Return", "Sharpe Ratio", "Max Drawdown", "Win Rate", "Calmar Ratio"]
    
    for metric, name in zip(metrics, metric_names):
        half_val = result.half_kelly_metrics.get(metric, 0)
        mvrk_val = result.mvrk_metrics.get(metric, 0)
        improvement = result.performance_comparison.get(f"{metric}_improvement", 0)
        
        if metric == "max_drawdown":
            imp_str = f"{improvement:.1%}" if improvement != 0 else "0.0%"
        else:
            imp_str = f"{improvement:.1%}" if improvement != 0 else "0.0%"
        
        if metric in ["total_return", "win_rate"]:
            print(f"{name:<20} {half_val:<15.2%} {mvrk_val:<15.2%} {imp_str:<15}")
        else:
            print(f"{name:<20} {half_val:<15.3f} {mvrk_val:<15.3f} {imp_str:<15}")
    
    # Risk metrics
    print(f"\nRisk Analysis:")
    print("-" * 50)
    print(f"Risk of Ruin (50%):")
    print(f"  Half Kelly: {result.ruin_half:.2%}")
    print(f"  MVRK: {result.ruin_mvrk:.2%}")
    print(f"  Improvement: {result.risk_comparison.get('ruin_improvement', 0):.1%}")
    
    # Recommendations
    print(f"\nRecommendations:")
    print("-" * 50)
    for rec in result.recommendations:
        print(f"  {rec}")
    
    print("=" * 80)

def run_multiple_theta_backtests(returns_df: pd.DataFrame,
                               theta_values: List[float] = None,
                               ruin_level: float = 0.5,
                               n_paths: int = 5000) -> Dict[str, MvrkVsKellyResult]:
    """
    Run backtests for multiple theta values.
    
    Args:
        returns_df: Asset returns DataFrame
        theta_values: List of theta values to test
        ruin_level: Risk of ruin threshold
        n_paths: Number of Monte Carlo paths
        
    Returns:
        Dictionary of results by theta value
    """
    if theta_values is None:
        theta_values = [0.0, 0.5, 1.0, 2.0]
    
    results = {}
    
    for theta in theta_values:
        try:
            result = backtest_mvrk_vs_half_kelly(returns_df, theta, ruin_level, n_paths)
            results[f"theta_{theta}"] = result
        except Exception as e:
            logger.error(f"Error in theta {theta} backtest: {e}")
            continue
    
    return results

# Example usage:
"""
import pandas as pd
import numpy as np

# Generate sample crypto returns
np.random.seed(42)
n_periods = 200

returns_df = pd.DataFrame({
    'BTC15M': np.random.normal(0.001, 0.02, n_periods),
    'ETH15M': np.random.normal(0.0015, 0.025, n_periods),
})

# Run backtest
result = backtest_mvrk_vs_half_kelly(returns_df, theta=1.0)
print_backtest_results(result)

# Multiple theta comparison
theta_results = run_multiple_theta_backtests(returns_df, theta_values=[0.0, 0.5, 1.0, 2.0])

# Find best theta
best_theta = None
best_score = -float('inf')

for theta_key, result in theta_results.items():
    # Composite score: Sharpe improvement + risk improvement
    score = (result.performance_comparison.get('sharpe_ratio_improvement', 0) + 
             result.risk_comparison.get('ruin_improvement', 0))
    
    if score > best_score:
        best_score = score
        best_theta = theta_key

print(f"Best theta: {best_theta} (score: {best_score:.3f})")
"""
