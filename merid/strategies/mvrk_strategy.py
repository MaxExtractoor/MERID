"""
MVRK Strategy Implementation - Multivariate Volatility Regulated Kelly

Implementation for two Kalshi strategies (BTC & ETH contracts) with multivariate Kelly and MVRK weights.
"""

import numpy as np
import pandas as pd
from typing import Tuple, Dict, Any
import logging

from .mvrk import classical_kelly_weights, mvrk_weights
from .mvrk_backtest import normalize_weights

logger = logging.getLogger(__name__)

def build_multivariate_returns(btc_pnls: list[float], eth_pnls: list[float], 
                              timestamps: list = None) -> pd.DataFrame:
    """
    Build multivariate returns DataFrame from BTC and ETH PnLs.
    
    Args:
        btc_pnls: List of BTC strategy PnLs
        eth_pnls: List of ETH strategy PnLs
        timestamps: Optional timestamps for each return
        
    Returns:
        DataFrame with BTC and ETH returns
    """
    n = min(len(btc_pnls), len(eth_pnls))
    
    if n == 0:
        raise ValueError("No PnL data provided")
    
    df = pd.DataFrame({
        "BTC": btc_pnls[:n],
        "ETH": eth_pnls[:n],
    })
    
    if timestamps and len(timestamps) >= n:
        df.index = pd.to_datetime(timestamps[:n])
    else:
        df.index = pd.date_range("2023-01-01", periods=n, freq="15min")
    
    logger.info(f"Built multivariate returns: {n} periods, {df.columns.tolist()}")
    
    return df

def compute_kelly_mvrk_weights(returns_df: pd.DataFrame, 
                               theta: float = 1.0,
                               normalization_method: str = "sum_abs") -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute classical Kelly and MVRK weights for multivariate returns.
    
    Args:
        returns_df: DataFrame with asset returns (columns = assets)
        theta: MVRK theta parameter for volatility regulation
        normalization_method: Weight normalization method
        
    Returns:
        Tuple of (kelly_weights, mvrk_weights)
    """
    if returns_df.empty:
        raise ValueError("Empty returns DataFrame")
    
    # Calculate expected returns and covariance matrix
    mu = returns_df.mean().values
    cov = returns_df.cov().values
    
    logger.debug(f"Computed mu and cov: {mu.shape}, {cov.shape}")
    
    # Calculate classical Kelly weights
    w_kelly = classical_kelly_weights(mu, cov)
    
    # Calculate MVRK weights
    w_mvrk = mvrk_weights(mu, cov, theta=theta)
    
    # Normalize weights to control gross exposure
    w_kelly_norm = normalize_weights(w_kelly, method=normalization_method)
    w_mvrk_norm = normalize_weights(w_mvrk, method=normalization_method)
    
    logger.info(f"Computed weights: Kelly sum={np.sum(np.abs(w_kelly_norm)):.3f}, "
                f"MVRK sum={np.sum(np.abs(w_mvrk_norm)):.3f}, theta={theta:.2f}")
    
    return w_kelly_norm, w_mvrk_norm

def analyze_weight_allocation(kelly_weights: np.ndarray, mvrk_weights: np.ndarray,
                             asset_names: list[str] = None) -> Dict[str, Any]:
    """
    Analyze and compare Kelly vs MVRK weight allocations.
    
    Args:
        kelly_weights: Classical Kelly weights
        mvrk_weights: MVRK weights
        asset_names: Names of assets
        
    Returns:
        Analysis results
    """
    if asset_names is None:
        asset_names = [f"Asset_{i}" for i in range(len(kelly_weights))]
    
    analysis = {
        "assets": asset_names,
        "kelly_weights": kelly_weights.tolist(),
        "mvrk_weights": mvrk_weights.tolist(),
        "weight_differences": (mvrk_weights - kelly_weights).tolist(),
        "kelly_allocation": {},
        "mvrk_allocation": {},
        "allocation_shift": {}
    }
    
    # Calculate allocation percentages
    kelly_abs = np.abs(kelly_weights)
    mvrk_abs = np.abs(mvrk_weights)
    
    kelly_total = kelly_abs.sum()
    mvrk_total = mvrk_abs.sum()
    
    for i, asset in enumerate(asset_names):
        analysis["kelly_allocation"][asset] = {
            "weight": kelly_weights[i],
            "abs_weight": kelly_abs[i],
            "allocation_pct": (kelly_abs[i] / kelly_total * 100) if kelly_total > 0 else 0.0,
            "direction": "long" if kelly_weights[i] > 0 else "short"
        }
        
        analysis["mvrk_allocation"][asset] = {
            "weight": mvrk_weights[i],
            "abs_weight": mvrk_abs[i],
            "allocation_pct": (mvrk_abs[i] / mvrk_total * 100) if mvrk_total > 0 else 0.0,
            "direction": "long" if mvrk_weights[i] > 0 else "short"
        }
        
        analysis["allocation_shift"][asset] = {
            "weight_change": mvrk_weights[i] - kelly_weights[i],
            "allocation_change_pct": (mvrk_abs[i] / mvrk_total - kelly_abs[i] / kelly_total) * 100 if kelly_total > 0 and mvrk_total > 0 else 0.0
        }
    
    # Overall statistics
    analysis["summary"] = {
        "kelly_gross_exposure": kelly_total,
        "mvrk_gross_exposure": mvrk_total,
        "weight_correlation": np.corrcoef(kelly_weights, mvrk_weights)[0, 1] if len(kelly_weights) > 1 else 1.0,
        "max_weight_change": np.max(np.abs(mvrk_weights - kelly_weights)),
        "allocation_consistency": 1.0 - np.std(np.abs(mvrk_weights - kelly_weights))
    }
    
    return analysis

def apply_multivariate_sizing(base_position_size: float,
                             weights: np.ndarray,
                             asset_names: list[str] = None) -> Dict[str, float]:
    """
    Apply multivariate weights to position sizing.
    
    Args:
        base_position_size: Base position size (e.g., total risk budget)
        weights: Portfolio weights
        asset_names: Names of assets
        
    Returns:
        Dictionary with position sizes per asset
    """
    if asset_names is None:
        asset_names = [f"Asset_{i}" for i in range(len(weights))]
    
    if len(asset_names) != len(weights):
        raise ValueError("Asset names and weights length mismatch")
    
    position_sizes = {}
    
    for asset, weight in zip(asset_names, weights):
        position_sizes[asset] = base_position_size * abs(weight)
    
    return position_sizes

def backtest_multivariate_strategies(returns_df: pd.DataFrame,
                                    theta_values: list[float] = None,
                                    base_fraction: float = 1.0) -> Dict[str, Any]:
    """
    Backtest multivariate Kelly and MVRK strategies.
    
    Args:
        returns_df: DataFrame with asset returns
        theta_values: List of theta values to test
        base_fraction: Base fraction for position sizing
        
    Returns:
        Backtest results
    """
    if theta_values is None:
        theta_values = [0.0, 0.5, 1.0, 2.0]
    
    results = {}
    
    # Calculate weights for each theta
    for theta in theta_values:
        try:
            w_kelly, w_mvrk = compute_kelly_mvrk_weights(returns_df, theta)
            
            # Generate equity curves
            from .mvrk_backtest import equity_from_weights
            
            equity_kelly = equity_from_weights(returns_df, w_kelly * base_fraction)
            equity_mvrk = equity_from_weights(returns_df, w_mvrk * base_fraction)
            
            # Calculate performance metrics
            from .mvrk_backtest import calculate_portfolio_metrics
            
            kelly_metrics = calculate_portfolio_metrics(equity_kelly, returns_df, w_kelly)
            mvrk_metrics = calculate_portfolio_metrics(equity_mvrk, returns_df, w_mvrk)
            
            results[f"theta_{theta}"] = {
                "theta": theta,
                "kelly_weights": w_kelly.tolist(),
                "mvrk_weights": w_mvrk.tolist(),
                "kelly_equity": equity_kelly,
                "mvrk_equity": equity_mvrk,
                "kelly_metrics": kelly_metrics,
                "mvrk_metrics": mvrk_metrics,
                "performance_improvement": {
                    "return_improvement": (mvrk_metrics["total_return"] - kelly_metrics["total_return"]) / abs(kelly_metrics["total_return"]) if kelly_metrics["total_return"] != 0 else 0.0,
                    "sharpe_improvement": mvrk_metrics["sharpe_ratio"] - kelly_metrics["sharpe_ratio"],
                    "drawdown_improvement": (mvrk_metrics["max_drawdown"] - kelly_metrics["max_drawdown"]) / abs(kelly_metrics["max_drawdown"]) if kelly_metrics["max_drawdown"] != 0 else 0.0
                }
            }
            
        except Exception as e:
            logger.error(f"Error in multivariate backtest for theta {theta}: {e}")
            continue
    
    return results

def print_mvrk_strategy_results(results: Dict[str, Any], asset_names: list[str] = None):
    """
    Print formatted MVRK strategy results.
    
    Args:
        results: Results from backtest_multivariate_strategies
        asset_names: Names of assets
    """
    if not results:
        print("No results to display")
        return
    
    print("\n" + "="*80)
    print("MULTIVARIATE KELLY/MVRK STRATEGY RESULTS")
    print("="*80)
    
    print(f"\nStrategy Performance Summary:")
    print("-" * 80)
    print(f"{'Theta':<8} {'Kelly Return':<12} {'MVRK Return':<12} {'Kelly Sharpe':<12} {'MVRK Sharpe':<12} {'Improvement':<12}")
    print("-" * 80)
    
    for theta_key, result in results.items():
        theta = result["theta"]
        kelly_metrics = result["kelly_metrics"]
        mvrk_metrics = result["mvrk_metrics"]
        improvement = result["performance_improvement"]
        
        print(f"{theta:<8.1f} {kelly_metrics['total_return']:<12.2%} "
              f"{mvrk_metrics['total_return']:<12.2%} {kelly_metrics['sharpe_ratio']:<12.2f} "
              f"{mvrk_metrics['sharpe_ratio']:<12.2f} {improvement['sharpe_improvement']:<12.3f}")
    
    # Find best theta
    best_theta = max(results.items(), key=lambda x: x[1]["mvrk_metrics"]["sharpe_ratio"])
    
    print(f"\nBest MVRK Performance:")
    print("-" * 50)
    print(f"  Theta: {best_theta[1]['theta']:.1f}")
    print(f"  Sharpe: {best_theta[1]['mvrk_metrics']['sharpe_ratio']:.2f}")
    print(f"  Return: {best_theta[1]['mvrk_metrics']['total_return']:.2%}")
    print(f"  Max DD: {best_theta[1]['mvrk_metrics']['max_drawdown']:.2%}")
    
    # Weight analysis for best theta
    if asset_names:
        best_weights = best_theta[1]["mvrk_weights"]
        
        print(f"\nOptimal Weight Allocation (Theta={best_theta[1]['theta']:.1f}):")
        print("-" * 50)
        
        for asset, weight in zip(asset_names, best_weights):
            direction = "Long" if weight > 0 else "Short"
            print(f"  {asset}: {weight:.3f} ({direction})")
    
    print("="*80)

def generate_mvrk_strategy_recommendations(results: Dict[str, Any]) -> list[str]:
    """
    Generate recommendations based on MVRK strategy results.
    
    Args:
        results: Results from backtest_multivariate_strategies
        
    Returns:
        List of recommendations
    """
    if not results:
        return ["No results available for recommendations"]
    
    recommendations = []
    
    # Find best performing theta
    best_theta = max(results.items(), key=lambda x: x[1]["mvrk_metrics"]["sharpe_ratio"])
    best_result = best_theta[1]
    
    # Compare MVRK vs Kelly
    mvrk_sharpe = best_result["mvrk_metrics"]["sharpe_ratio"]
    kelly_sharpe = best_result["kelly_metrics"]["sharpe_ratio"]
    
    if mvrk_sharpe > kelly_sharpe + 0.2:
        recommendations.append(f"✅ MVRK significantly outperforms Kelly (+{mvrk_sharpe - kelly_sharpe:.2f} Sharpe)")
    elif mvrk_sharpe > kelly_sharpe + 0.1:
        recommendations.append(f"📈 MVRK moderately outperforms Kelly (+{mvrk_sharpe - kelly_sharpe:.2f} Sharpe)")
    elif mvrk_sharpe > kelly_sharpe:
        recommendations.append(f"📊 MVRK slightly outperforms Kelly (+{mvrk_sharpe - kelly_sharpe:.2f} Sharpe)")
    else:
        recommendations.append(f"⚠️ Kelly outperforms MVRK ({kelly_sharpe - mvrk_sharpe:.2f} Sharpe)")
    
    # Theta recommendation
    optimal_theta = best_result["theta"]
    if optimal_theta == 0.0:
        recommendations.append(f"📊 Classical Kelly (theta=0) performs best - volatility regulation not needed")
    elif optimal_theta < 0.5:
        recommendations.append(f"🎯 Low theta ({optimal_theta:.1f}) optimal - mild volatility regulation")
    elif optimal_theta < 1.5:
        recommendations.append(f"🛡️ Moderate theta ({optimal_theta:.1f}) optimal - balanced volatility regulation")
    else:
        recommendations.append(f"⚠️ High theta ({optimal_theta:.1f}) optimal - strong volatility regulation")
    
    # Risk assessment
    max_dd = best_result["mvrk_metrics"]["max_drawdown"]
    if max_dd < -0.20:
        recommendations.append(f"📉 High drawdown risk ({max_dd:.1%}) - consider reducing position size")
    elif max_dd < -0.10:
        recommendations.append(f"📊 Moderate drawdown risk ({max_dd:.1%}) - monitor carefully")
    else:
        recommendations.append(f"✅ Low drawdown risk ({max_dd:.1%}) - current sizing appears safe")
    
    # Performance assessment
    if mvrk_sharpe > 1.5:
        recommendations.append(f"🚀 Excellent risk-adjusted returns (Sharpe: {mvrk_sharpe:.2f})")
    elif mvrk_sharpe > 1.0:
        recommendations.append(f"📈 Good risk-adjusted returns (Sharpe: {mvrk_sharpe:.2f})")
    elif mvrk_sharpe > 0.5:
        recommendations.append(f"📊 Moderate risk-adjusted returns (Sharpe: {mvrk_sharpe:.2f})")
    else:
        recommendations.append(f"⚠️ Low risk-adjusted returns (Sharpe: {mvrk_sharpe:.2f}) - improve strategy")
    
    # General recommendations
    recommendations.append("💡 Use optimal theta value for live trading")
    recommendations.append("🔄 Re-estimate parameters periodically with updated returns")
    recommendations.append("⚖️ Combine MVRK with other risk controls like drawdown limits")
    recommendations.append("📊 Monitor correlation between assets and adjust weights accordingly")
    
    return recommendations

# Example usage for Kalshi BTC/ETH strategies:
"""
# Assume we have PnL data from BTC and ETH Kalshi strategies
import numpy as np
import pandas as pd

# Generate sample data (replace with actual Kalshi strategy PnLs)
np.random.seed(42)
n_periods = 200

btc_pnls = np.random.normal(0.001, 0.02, n_periods)  # BTC strategy PnLs
eth_pnls = np.random.normal(0.0015, 0.025, n_periods)  # ETH strategy PnLs

# Build multivariate returns
returns_df = build_multivariate_returns(btc_pnls.tolist(), eth_pnls.tolist())

# Compute weights
w_kelly, w_mvrk = compute_kelly_mvrk_weights(returns_df, theta=1.0)

# Analyze allocation
analysis = analyze_weight_allocation(w_kelly, w_mvrk, ["BTC", "ETH"])
print("Weight Allocation Analysis:")
for asset, alloc in analysis["kelly_allocation"].items():
    print(f"  {asset}: {alloc['weight']:.3f} ({alloc['direction']}, {alloc['allocation_pct']:.1%})")

# Apply position sizing
base_size = 100000  # $100k risk budget
position_sizes = apply_multivariate_sizing(base_size, w_mvrk, ["BTC", "ETH"])
print(f"Position Sizes: {position_sizes}")

# Backtest strategies
results = backtest_multivariate_strategies(returns_df, theta_values=[0.0, 0.5, 1.0, 2.0])

# Print results
print_mvrk_strategy_results(results, ["BTC", "ETH"])

# Generate recommendations
recommendations = generate_mvrk_strategy_recommendations(results)
print("Recommendations:")
for rec in recommendations:
    print(f"  {rec}")
"""
