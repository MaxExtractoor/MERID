"""
MVRK vs Kelly Risk of Ruin Comparison

Compare risk of ruin between full Kelly and MVRK on crypto events using Monte Carlo.
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Any
import logging

from .mvrk_strategy import compute_kelly_mvrk_weights
from .mvrk_risk_of_ruin import mc_mvrk_risk_of_ruin

logger = logging.getLogger(__name__)

def compare_kelly_mvrk_ruin(btc_pnls: List[float], eth_pnls: List[float],
                            theta: float = 1.0,
                            ruin_level: float = 0.5,
                            n_paths: int = 5000,
                            seed: int = None) -> Dict[str, Any]:
    """
    Compare risk of ruin between Kelly and MVRK on crypto event strategies.
    
    Args:
        btc_pnls: List of BTC strategy PnLs
        eth_pnls: List of ETH strategy PnLs
        theta: MVRK theta parameter
        ruin_level: Capital threshold for ruin (0.5 = 50%)
        n_paths: Number of Monte Carlo paths
        seed: Random seed for reproducibility
        
    Returns:
        Comparison results with risk metrics
    """
    if not btc_pnls or not eth_pnls:
        raise ValueError("Empty PnL data provided")
    
    # Build multivariate returns DataFrame
    from .mvrk_strategy import build_multivariate_returns
    df = build_multivariate_returns(btc_pnls, eth_pnls)
    
    logger.info(f"Comparing Kelly vs MVRK risk of ruin: {len(df)} periods, theta={theta}")
    
    # Compute Kelly and MVRK weights
    try:
        w_kelly, w_mvrk = compute_kelly_mvrk_weights(df, theta=theta)
        logger.info(f"Weights computed: Kelly sum={np.sum(np.abs(w_kelly)):.3f}, MVRK sum={np.sum(np.abs(w_mvrk)):.3f}")
    except Exception as e:
        logger.error(f"Error computing weights: {e}")
        raise
    
    # Calculate risk of ruin for both strategies
    try:
        ruin_kelly = mc_mvrk_risk_of_ruin(df, w_kelly, ruin_level=ruin_level, n_paths=n_paths, seed=seed)
        ruin_mvrk = mc_mvrk_risk_of_ruin(df, w_mvrk, ruin_level=ruin_level, n_paths=n_paths, seed=seed)
        
        logger.info(f"Risk of ruin completed: Kelly={ruin_kelly:.2%}, MVRK={ruin_mvrk:.2%}")
        
    except Exception as e:
        logger.error(f"Error in Monte Carlo simulation: {e}")
        raise
    
    # Calculate additional risk metrics
    kelly_metrics = calculate_portfolio_risk_metrics(df, w_kelly)
    mvrk_metrics = calculate_portfolio_risk_metrics(df, w_mvrk)
    
    # Calculate improvement metrics
    risk_improvement = (ruin_kelly - ruin_mvrk) / ruin_kelly if ruin_kelly > 0 else 0.0
    
    results = {
        "btc_pnls_count": len(btc_pnls),
        "eth_pnls_count": len(eth_pnls),
        "periods": len(df),
        "theta": theta,
        "ruin_level": ruin_level,
        "n_paths": n_paths,
        "weights": {
            "kelly": w_kelly.tolist(),
            "mvrk": w_mvrk.tolist(),
            "kelly_abs_sum": float(np.sum(np.abs(w_kelly))),
            "mvrk_abs_sum": float(np.sum(np.abs(w_mvrk)))
        },
        "risk_of_ruin": {
            "kelly": ruin_kelly,
            "mvrk": ruin_mvrk,
            "improvement": risk_improvement,
            "reduction_bps": (ruin_kelly - ruin_mvrk) * 10000  # Basis points
        },
        "portfolio_metrics": {
            "kelly": kelly_metrics,
            "mvrk": mvrk_metrics
        },
        "recommendation": generate_risk_recommendation(ruin_kelly, ruin_mvrk, kelly_metrics, mvrk_metrics)
    }
    
    return results

def calculate_portfolio_risk_metrics(returns_df: pd.DataFrame, weights: np.ndarray) -> Dict[str, float]:
    """
    Calculate portfolio risk metrics for given weights.
    
    Args:
        returns_df: DataFrame with asset returns
        weights: Portfolio weights
        
    Returns:
        Risk metrics dictionary
    """
    # Calculate portfolio returns
    port_rets = returns_df.values @ weights
    
    # Portfolio volatility (annualized for 15m bars)
    periods_per_year = 365 * 24 * 4
    portfolio_vol = port_rets.std() * np.sqrt(periods_per_year)
    
    # Portfolio expected return (annualized)
    portfolio_return = port_rets.mean() * periods_per_year
    
    # Sharpe ratio
    sharpe_ratio = portfolio_return / portfolio_vol if portfolio_vol > 0 else 0.0
    
    # Maximum drawdown (simplified)
    equity = (1 + port_rets).cumprod()
    peak = equity.cummax()
    drawdown = (equity - peak) / peak.replace(0, np.nan)
    max_drawdown = drawdown.min()
    
    # Value at Risk (5%)
    var_5 = np.percentile(port_rets, 5)
    
    # Expected shortfall (5%)
    shortfall_5 = port_rets[port_rets <= np.percentile(port_rets, 5)].mean()
    
    return {
        "portfolio_volatility": portfolio_vol,
        "portfolio_return": portfolio_return,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown": max_drawdown,
        "var_5": var_5,
        "expected_shortfall_5": shortfall_5,
        "weight_concentration": np.max(np.abs(weights)) / np.sum(np.abs(weights)) if np.sum(np.abs(weights)) > 0 else 0.0
    }

def generate_risk_recommendation(ruin_kelly: float, ruin_mvrk: float,
                                kelly_metrics: Dict[str, float],
                                mvrk_metrics: Dict[str, float]) -> str:
    """
    Generate recommendation based on risk comparison.
    
    Args:
        ruin_kelly: Kelly risk of ruin
        ruin_mvrk: MVRK risk of ruin
        kelly_metrics: Kelly portfolio metrics
        mvrk_metrics: MVRK portfolio metrics
        
    Returns:
        Recommendation string
    """
    if ruin_mvrk < ruin_kelly * 0.8:
        return "STRONGLY_RECOMMEND_MVRK"
    elif ruin_mvrk < ruin_kelly * 0.95:
        return "RECOMMEND_MVRK"
    elif ruin_mvrk > ruin_kelly * 1.05:
        return "RECOMMEND_KELLY"
    else:
        return "NEUTRAL"

def compare_multiple_theta_values(btc_pnls: List[float], eth_pnls: List[float],
                                 theta_values: List[float] = None,
                                 ruin_level: float = 0.5,
                                 n_paths: int = 5000) -> Dict[str, Any]:
    """
    Compare risk of ruin across multiple theta values.
    
    Args:
        btc_pnls: List of BTC strategy PnLs
        eth_pnls: List of ETH strategy PnLs
        theta_values: List of theta values to test
        ruin_level: Capital threshold for ruin
        n_paths: Number of Monte Carlo paths
        
    Returns:
        Multi-theta comparison results
    """
    if theta_values is None:
        theta_values = [0.0, 0.5, 1.0, 2.0, 5.0]
    
    results = {}
    
    for theta in theta_values:
        try:
            result = compare_kelly_mvrk_ruin(
                btc_pnls, eth_pnls, theta, ruin_level, n_paths
            )
            results[f"theta_{theta}"] = result
        except Exception as e:
            logger.error(f"Error in theta {theta} comparison: {e}")
            continue
    
    # Find best theta
    best_theta = None
    best_mvrk_risk = float('inf')
    
    for theta_key, result in results.items():
        mvrk_risk = result["risk_of_ruin"]["mvrk"]
        if mvrk_risk < best_mvrk_risk:
            best_mvrk_risk = mvrk_risk
            best_theta = theta_key
    
    summary = {
        "best_theta": best_theta,
        "best_mvrk_risk": best_mvrk_risk,
        "theta_results": results,
        "theta_comparison": {
            theta_key: {
                "kelly_risk": result["risk_of_ruin"]["kelly"],
                "mvrk_risk": result["risk_of_ruin"]["mvrk"],
                "improvement": result["risk_of_ruin"]["improvement"]
            }
            for theta_key, result in results.items()
        }
    }
    
    return summary

def print_risk_comparison_results(results: Dict[str, Any], title: str = "Kelly vs MVRK Risk of Ruin Comparison"):
    """
    Print formatted risk comparison results.
    
    Args:
        results: Results from compare_kelly_mvrk_ruin
        title: Results title
    """
    if not results:
        print("No results to display")
        return
    
    print(f"\n{title}")
    print("=" * 80)
    
    # Basic info
    print(f"\nMonte Carlo Settings:")
    print("-" * 40)
    print(f"  Periods: {results['periods']}")
    print(f"  Theta: {results['theta']}")
    print(f"  Ruin Level: {results['ruin_level']:.1%}")
    print(f"  Paths: {results['n_paths']:,}")
    
    # Risk of ruin results
    risk_data = results["risk_of_ruin"]
    print(f"\nRisk of Ruin Results:")
    print("-" * 50)
    print(f"  Kelly: {risk_data['kelly']:.2%}")
    print(f"  MVRK: {risk_data['mvrk']:.2%}")
    print(f"  Improvement: {risk_data['improvement']:.1%}")
    print(f"  Reduction: {risk_data['reduction_bps']:.0f} bps")
    
    # Weight analysis
    weights = results["weights"]
    print(f"\nWeight Analysis:")
    print("-" * 50)
    print(f"  Kelly weights: {weights['kelly']}")
    print(f"  MVRK weights: {weights['mvrk']}")
    print(f"  Kelly abs sum: {weights['kelly_abs_sum']:.3f}")
    print(f"  MVRK abs sum: {weights['mvrk_abs_sum']:.3f}")
    
    # Portfolio metrics
    kelly_metrics = results["portfolio_metrics"]["kelly"]
    mvrk_metrics = results["portfolio_metrics"]["mvrk"]
    
    print(f"\nPortfolio Metrics:")
    print("-" * 50)
    print(f"  Kelly Sharpe: {kelly_metrics['sharpe_ratio']:.2f}")
    print(f"  MVRK Sharpe: {mvrk_metrics['sharpe_ratio']:.2f}")
    print(f"  Kelly Vol: {kelly_metrics['portfolio_volatility']:.2%}")
    print(f"  MVRK Vol: {mvrk_metrics['portfolio_volatility']:.2%}")
    print(f"  Kelly Max DD: {kelly_metrics['max_drawdown']:.2%}")
    print(f"  MVRK Max DD: {mvrk_metrics['max_drawdown']:.2%}")
    
    # Recommendation
    print(f"\nRecommendation: {results['recommendation']}")
    
    print("=" * 80)

def print_multi_theta_results(results: Dict[str, Any]):
    """
    Print formatted multi-theta comparison results.
    
    Args:
        results: Results from compare_multiple_theta_values
    """
    if not results or "theta_comparison" not in results:
        print("No multi-theta results to display")
        return
    
    print("\n" + "="*80)
    print("MULTI-THETA RISK OF RUIN COMPARISON")
    print("="*80)
    
    theta_comp = results["theta_comparison"]
    
    print(f"\nRisk of Ruin by Theta Value:")
    print("-" * 60)
    print(f"{'Theta':<12} {'Kelly Risk':<12} {'MVRK Risk':<12} {'Improvement':<12}")
    print("-" * 60)
    
    for theta_key, comp in theta_comp.items():
        theta_val = theta_key.replace("theta_", "")
        print(f"{theta_val:<12} {comp['kelly_risk']:<12.2%} "
              f"{comp['mvrk_risk']:<12.2%} {comp['improvement']:<12.1%}")
    
    # Best theta
    best_theta = results["best_theta"]
    best_risk = results["best_mvrk_risk"]
    
    print(f"\nBest Theta: {best_theta}")
    print(f"  Lowest MVRK Risk: {best_risk:.2%}")
    
    print("=" * 80)

# Example usage:
"""
# Assume we have PnL data from BTC and ETH Kalshi strategies
import numpy as np

# Generate sample data (replace with actual Kalshi strategy PnLs)
np.random.seed(42)
n_periods = 200

btc_pnls = np.random.normal(0.001, 0.02, n_periods).tolist()
eth_pnls = np.random.normal(0.0015, 0.025, n_periods).tolist()

# Single theta comparison
results = compare_kelly_mvrk_ruin(btc_pnls, eth_pnls, theta=1.0, n_paths=2000)
print_risk_comparison_results(results)

# Multi-theta comparison
multi_results = compare_multiple_theta_values(btc_pnls, eth_pnls, theta_values=[0.0, 0.5, 1.0, 2.0], n_paths=1000)
print_multi_theta_results(multi_results)

# Generate recommendations based on results
if results['recommendation'] == 'STRONGLY_RECOMMEND_MVRK':
    print("Strongly recommend using MVRK for significantly lower risk of ruin")
elif results['recommendation'] == 'RECOMMEND_MVRK':
    print("Recommend using MVRK for lower risk of ruin")
elif results['recommendation'] == 'RECOMMEND_KELLY':
    print("Kelly performs better than MVRK for this dataset")
else:
    print("Both strategies perform similarly - consider other factors")
"""
