"""
Multivariate Volatility Regulated Kelly (MVRK) Skeleton

Multivariate Kelly with volatility regulation for multiple assets.
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)

def classical_kelly_weights(mu: np.ndarray, cov: np.ndarray) -> np.ndarray:
    """
    Classical Kelly weights for multiple assets: w ~ cov^{-1} * mu.
    
    Args:
        mu: Expected return vector (n_assets,)
        cov: Covariance matrix (n_assets, n_assets)
        
    Returns:
        Kelly weights vector (n_assets,)
    """
    try:
        inv_cov = np.linalg.inv(cov)
        w = inv_cov @ mu
        return w
    except np.linalg.LinAlgError:
        logger.error("Singular covariance matrix - using zero weights")
        return np.zeros_like(mu)

def mvrk_weights(mu: np.ndarray, cov: np.ndarray, theta: float = 1.0) -> np.ndarray:
    """
    Multivariate Volatility Regulated Kelly (MVRK).
    
    Penalizes portfolio variance with theta parameter.
    Approximation: shrink weights toward zero based on portfolio variance.
    
    Args:
        mu: Expected return vector (n_assets,)
        cov: Covariance matrix (n_assets, n_assets)
        theta: Volatility regulation parameter (higher = more conservative)
        
    Returns:
        MVRK weights vector (n_assets,)
    """
    # Calculate classical Kelly weights
    w_kelly = classical_kelly_weights(mu, cov)
    
    # Calculate portfolio variance under Kelly weights
    var_kelly = float(w_kelly.T @ cov @ w_kelly)
    
    if var_kelly <= 0:
        logger.warning("Non-positive portfolio variance - using zero weights")
        return np.zeros_like(w_kelly)
    
    # Shrink weights toward zero based on variance and theta
    # shrink = 1.0 / (1.0 + theta * var_kelly)
    # As theta increases, shrink factor decreases (more conservative)
    shrink_factor = 1.0 / (1.0 + theta * var_kelly)
    
    w_mvrk = w_kelly * shrink_factor
    
    logger.debug(f"MVRK: var_kelly={var_kelly:.6f}, theta={theta:.2f}, "
                f"shrink_factor={shrink_factor:.4f}")
    
    return w_mvrk

def normalize_kelly_weights(weights: np.ndarray, max_leverage: float = 1.0) -> np.ndarray:
    """
    Normalize Kelly weights to respect maximum leverage constraint.
    
    Args:
        weights: Raw Kelly weights
        max_leverage: Maximum allowed leverage sum of absolute weights
        
    Returns:
        Normalized weights
    """
    abs_sum = np.sum(np.abs(weights))
    
    if abs_sum <= max_leverage:
        return weights
    
    # Scale down to respect leverage constraint
    scale_factor = max_leverage / abs_sum
    return weights * scale_factor

def calculate_portfolio_metrics(weights: np.ndarray, mu: np.ndarray, cov: np.ndarray) -> Dict[str, float]:
    """
    Calculate portfolio metrics for given weights.
    
    Args:
        weights: Portfolio weights
        mu: Expected returns
        cov: Covariance matrix
        
    Returns:
        Portfolio metrics dictionary
    """
    # Expected portfolio return
    portfolio_return = float(weights @ mu)
    
    # Portfolio variance
    portfolio_variance = float(weights.T @ cov @ weights)
    portfolio_volatility = np.sqrt(portfolio_variance)
    
    # Sharpe ratio (assuming risk-free rate = 0)
    sharpe_ratio = portfolio_return / portfolio_volatility if portfolio_volatility > 0 else 0.0
    
    # Leverage (sum of absolute weights)
    leverage = np.sum(np.abs(weights))
    
    return {
        "portfolio_return": portfolio_return,
        "portfolio_variance": portfolio_variance,
        "portfolio_volatility": portfolio_volatility,
        "sharpe_ratio": sharpe_ratio,
        "leverage": leverage
    }

def compare_kelly_methods(mu: np.ndarray, cov: np.ndarray, 
                           theta_values: List[float] = None,
                           max_leverage: float = 1.0) -> Dict[str, Any]:
    """
    Compare classical Kelly vs MVRK across different theta values.
    
    Args:
        mu: Expected return vector
        cov: Covariance matrix
        theta_values: List of theta values to test
        max_leverage: Maximum leverage constraint
        
    Returns:
        Comparison results
    """
    if theta_values is None:
        theta_values = [0.0, 0.5, 1.0, 2.0, 5.0]  # From no regulation to very conservative
    
    results = {}
    
    # Classical Kelly
    w_classical = classical_kelly_weights(mu, cov)
    w_classical_norm = normalize_kelly_weights(w_classical, max_leverage)
    classical_metrics = calculate_portfolio_metrics(w_classical_norm, mu, cov)
    
    results["classical"] = {
        "weights": w_classical_norm,
        "theta": 0.0,
        "metrics": classical_metrics
    }
    
    # MVRK with different theta values
    for theta in theta_values:
        w_mvrk = mvrk_weights(mu, cov, theta)
        w_mvrk_norm = normalize_kelly_weights(w_mvrk, max_leverage)
        mvrk_metrics = calculate_portfolio_metrics(w_mvrk_norm, mu, cov)
        
        results[f"theta_{theta}"] = {
            "weights": w_mvrk_norm,
            "theta": theta,
            "metrics": mvrk_metrics
        }
    
    return results

def print_mvrk_comparison(results: Dict[str, Any], asset_names: List[str] = None):
    """
    Print formatted MVRK comparison results.
    
    Args:
        results: Results from compare_kelly_methods
        asset_names: Names of assets for display
    """
    if not results:
        print("No MVRK results to display")
        return
    
    print("\n" + "="*80)
    print("MULTIVARIATE VOLATILITY REGULATED KELLY (MVRK) COMPARISON")
    print("="*80)
    
    print(f"\nPortfolio Metrics Comparison:")
    print("-" * 80)
    print(f"{'Method':<12} {'Return':<10} {'Vol':<10} {'Sharpe':<10} {'Leverage':<10} {'Theta':<8}")
    print("-" * 80)
    
    for method_name, result in results.items():
        metrics = result["metrics"]
        theta = result["theta"]
        
        print(f"{method_name:<12} {metrics['portfolio_return']:<10.3f} "
              f"{metrics['portfolio_volatility']:<10.3f} "
              f"{metrics['sharpe_ratio']:<10.3f} "
              f"{metrics['leverage']:<10.3f} "
              f"{theta:<8.2f}")
    
    # Show weight allocation if asset names provided
    if asset_names and len(asset_names) == len(results["classical"]["weights"]):
        print(f"\nWeight Allocation (Normalized):")
        print("-" * 50)
        
        for method_name, result in results.items():
            weights = result["weights"]
            print(f"\n{method_name}:")
            for i, (asset, weight) in enumerate(zip(asset_names, weights)):
                if abs(weight) > 0.01:  # Only show significant weights
                    print(f"  {asset}: {weight:.3f}")
    
    # Find best method by Sharpe ratio
    best_method = max(results.items(), key=lambda x: x[1]["metrics"]["sharpe_ratio"])
    
    print(f"\nBest Method by Sharpe Ratio:")
    print(f"  Method: {best_method[0]}")
    print(f"  Sharpe: {best_method[1]['metrics']['sharpe_ratio']:.3f}")
    print(f"  Return: {best_method[1]['metrics']['portfolio_return']:.3f}")
    print(f"  Volatility: {best_method[1]['metrics']['portfolio_volatility']:.3f}")
    
    print("="*80)

def estimate_parameters_from_returns(returns: pd.DataFrame, 
                                   window: int = 100) -> Dict[str, np.ndarray]:
    """
    Estimate mu and covariance from returns data.
    
    Args:
        returns: DataFrame of returns (time x assets)
        window: Window size for estimation
        
    Returns:
        Dictionary with mu and cov arrays
    """
    if returns.empty:
        return {"mu": np.array([]), "cov": np.array([[]])}
    
    # Use rolling window for estimation
    recent_returns = returns.tail(window)
    
    # Expected returns (annualized)
    mu = recent_returns.mean().values * (365 * 24 * 4)  # Annualized for 15m bars
    
    # Covariance matrix (annualized)
    cov = recent_returns.cov().values * (365 * 24 * 4)
    
    return {"mu": mu, "cov": cov}

def analyze_mvrk_effectiveness(returns: pd.DataFrame, 
                              theta_values: List[float] = None,
                              max_leverage: float = 1.0) -> Dict[str, Any]:
    """
    Analyze MVRK effectiveness on historical returns.
    
    Args:
        returns: DataFrame of historical returns
        theta_values: Theta values to test
        max_leverage: Maximum leverage constraint
        
    Returns:
        Effectiveness analysis
    """
    # Estimate parameters
    params = estimate_parameters_from_returns(returns)
    mu = params["mu"]
    cov = params["cov"]
    
    if len(mu) == 0:
        return {"error": "No data for estimation"}
    
    # Compare methods
    results = compare_kelly_methods(mu, cov, theta_values, max_leverage)
    
    # Analyze effectiveness
    classical_sharpe = results["classical"]["metrics"]["sharpe_ratio"]
    
    best_sharpe = 0.0
    best_theta = 0.0
    improvement = {}
    
    for method_name, result in results.items():
        if method_name != "classical":
            sharpe = result["metrics"]["sharpe_ratio"]
            improvement[method_name] = sharpe - classical_sharpe
            
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_theta = result["theta"]
    
    # Determine effectiveness
    avg_improvement = np.mean(list(improvement.values())) if improvement else 0.0
    
    effectiveness = {
        "best_theta": best_theta,
        "best_sharpe": best_sharpe,
        "classical_sharpe": classical_sharpe,
        "avg_improvement": avg_improvement,
        "improvements": improvement,
        "max_sharpe_improvement": max(improvement.values()) if improvement else 0.0,
        "results": results
    }
    
    return effectiveness

def generate_mvrk_recommendations(effectiveness: Dict[str, Any]) -> List[str]:
    """
    Generate recommendations based on MVRK analysis.
    
    Args:
        effectiveness: Results from analyze_mvrk_effectiveness
        
    Returns:
        List of recommendations
    """
    recommendations = []
    
    if "error" in effectiveness:
        return ["No data available for recommendations"]
    
    avg_improvement = effectiveness["avg_improvement"]
    best_theta = effectiveness["best_theta"]
    max_improvement = effectiveness["max_sharpe_improvement"]
    
    # Overall effectiveness assessment
    if avg_improvement > 0.1:
        recommendations.append("✅ MVRK significantly improves risk-adjusted returns")
    elif avg_improvement > 0.05:
        recommendations.append("📈 MVRK modestly improves risk-adjusted returns")
    elif avg_improvement > 0.01:
        recommendations.append("📊 MVRK slightly improves risk-adjusted returns")
    else:
        recommendations.append("⚠️ MVRK does not improve risk-adjusted returns")
    
    # Theta recommendation
    if best_theta == 0.0:
        recommendations.append("📊 Classical Kelly performs best - no volatility regulation needed")
    elif best_theta < 1.0:
        recommendations.append(f"🎯 Low theta ({best_theta:.1f}) optimal - mild volatility regulation")
    elif best_theta < 2.0:
        recommendations.append(f"🛡️ Moderate theta ({best_theta:.1f}) optimal - balanced volatility regulation")
    else:
        recommendations.append(f"⚠️ High theta ({best_theta:.1f}) optimal - strong volatility regulation")
    
    # Maximum improvement guidance
    if max_improvement > 0.2:
        recommendations.append(f"🚀 Maximum Sharpe improvement: {max_improvement:.2f} - highly recommended")
    elif max_improvement > 0.1:
        recommendations.append(f"📈 Good Sharpe improvement: {max_improvement:.2f} - recommended")
    elif max_improvement > 0.05:
        recommendations.append(f"📊 Modest Sharpe improvement: {max_improvement:.2f} - consider")
    else:
        recommendations.append("⚠️ Limited Sharpe improvement - evaluate necessity")
    
    # General recommendations
    recommendations.append("💡 Consider market volatility regime when choosing theta")
    recommendations.append("🔄 Re-estimate parameters periodically for adaptive performance")
    recommendations.append("⚖️ Use leverage constraints to control risk exposure")
    
    return recommendations

# Example usage for BTC/ETH Kalshi trading:
"""
# For BTC/ETH 15m strategy returns
import pandas as pd

# Assume we have historical returns for BTC and ETH
# returns = pd.DataFrame({
#     'BTC': btc_returns,  # 15m returns
#     'ETH': eth_returns   # 15m returns
# })

# Estimate parameters
# params = estimate_parameters_from_returns(returns.tail(100))
# mu = params["mu"]  # Expected returns
# cov = params["cov"]  # Covariance matrix

# Compare methods
# results = compare_kelly_methods(mu, cov, theta_values=[0.0, 0.5, 1.0, 2.0])

# Print comparison
# print_mvrk_comparison(results, asset_names=['BTC', 'ETH'])

# Analyze effectiveness
# effectiveness = analyze_mvrk_effectiveness(returns)
# recommendations = generate_mvrk_recommendations(effectiveness)

# Use best method for live trading
# best_method_name = max(results.keys(), key=lambda k: results[k]['metrics']['sharpe_ratio'])
# best_weights = results[best_method_name]['weights']

# For live trading, use weights as relative allocation
# total_allocation = 1.0  # Total Kelly allocation
# btc_allocation = total_allocation * best_weights[0]  # BTC portion
# eth_allocation = total_allocation * best_weights[1]  # ETH portion
"""
