"""
Risk of Ruin Monte Carlo for Correlated Kalshi Events

Monte Carlo simulation for risk-of-ruin analysis with correlated portfolio returns.
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

def mc_ror_correlated(returns_df: pd.DataFrame,
                     weights: np.ndarray,
                     ruin_level: float = 0.5,
                     n_paths: int = 5000,
                     seed: Optional[int] = None) -> float:
    """
    Monte Carlo risk of ruin for correlated Kalshi events.
    
    Maintains the cross-sectional correlation structure but shuffles time order,
    which is a common approach when stress-testing correlated portfolios.
    
    Args:
        returns_df: T x N matrix of asset returns (Kalshi events)
        weights: N-dimensional portfolio weights
        ruin_level: Capital threshold (e.g., 0.5 = 50% of starting capital)
        n_paths: Number of Monte Carlo paths to simulate
        seed: Random seed for reproducibility
        
    Returns:
        Risk of ruin probability (0.0 to 1.0)
    """
    if returns_df.empty:
        logger.warning("Empty returns DataFrame")
        return 0.0
    
    if len(weights) != returns_df.shape[1]:
        raise ValueError(f"Weight dimension {len(weights)} doesn't match assets {returns_df.shape[1]}")
    
    if seed is not None:
        np.random.seed(seed)
    
    rets = returns_df.values
    T, N = rets.shape
    
    logger.info(f"Running MC risk of ruin: {T} periods, {N} assets, {n_paths} paths")
    
    ruin_hits = 0
    
    for path_idx in range(n_paths):
        # Random permutation of time periods (maintains correlation structure)
        idx = np.random.permutation(T)
        rets_perm = rets[idx, :]
        
        # Calculate portfolio returns
        port_rets = rets_perm @ weights
        
        # Generate equity curve
        eq = (1 + port_rets).cumprod()
        
        # Check for ruin
        if eq.min() <= ruin_level:
            ruin_hits += 1
        
        # Progress logging
        if (path_idx + 1) % 1000 == 0:
            logger.debug(f"Completed {path_idx + 1}/{n_paths} paths")
    
    risk_of_ruin = ruin_hits / n_paths
    
    logger.info(f"Risk of ruin completed: {ruin_hits}/{n_paths} paths hit ruin ({risk_of_ruin:.2%})")
    
    return risk_of_ruin

def mc_ror_correlated_detailed(returns_df: pd.DataFrame,
                               weights: np.ndarray,
                               ruin_levels: List[float] = None,
                               n_paths: int = 5000,
                               seed: Optional[int] = None) -> Dict[str, Any]:
    """
    Detailed Monte Carlo risk of ruin analysis for multiple ruin levels.
    
    Args:
        returns_df: T x N matrix of asset returns
        weights: N-dimensional portfolio weights
        ruin_levels: List of ruin thresholds to test
        n_paths: Number of Monte Carlo paths
        seed: Random seed for reproducibility
        
    Returns:
        Detailed risk analysis results
    """
    if ruin_levels is None:
        ruin_levels = [0.8, 0.6, 0.4, 0.2]
    
    results = {
        "weights": weights.tolist(),
        "n_assets": len(weights),
        "n_periods": len(returns_df),
        "n_paths": n_paths,
        "ruin_levels": ruin_levels,
        "risk_of_ruin": {},
        "path_statistics": {},
        "recommendations": []
    }
    
    # Calculate risk of ruin for each level
    for ruin_level in ruin_levels:
        risk = mc_ror_correlated(returns_df, weights, ruin_level, n_paths, seed)
        results["risk_of_ruin"][str(ruin_level)] = risk
    
    # Calculate additional statistics
    rets = returns_df.values
    port_rets = rets @ weights
    
    # Portfolio statistics
    results["portfolio_stats"] = {
        "mean_return": float(port_rets.mean()),
        "volatility": float(port_rets.std()),
        "sharpe_ratio": float(port_rets.mean() / port_rets.std() * np.sqrt(365 * 24 * 4)) if port_rets.std() > 0 else 0.0,
        "skewness": float(pd.Series(port_rets).skew()),
        "kurtosis": float(pd.Series(port_rets).kurtosis())
    }
    
    # Path statistics
    if seed is not None:
        np.random.seed(seed)
    
    path_equities = []
    path_max_drawdowns = []
    path_final_returns = []
    
    for _ in range(min(1000, n_paths)):  # Sample subset for detailed stats
        idx = np.random.permutation(len(returns_df))
        rets_perm = rets[idx, :]
        port_rets_perm = rets_perm @ weights
        eq = (1 + port_rets_perm).cumprod()
        
        path_equities.append(eq[-1])
        
        # Calculate max drawdown
        peak = np.maximum.accumulate(eq)
        drawdown = (eq - peak) / peak
        path_max_drawdowns.append(drawdown.min())
        
        path_final_returns.append(eq[-1] - 1)
    
    results["path_statistics"] = {
        "avg_final_equity": float(np.mean(path_equities)),
        "avg_max_drawdown": float(np.mean(path_max_drawdowns)),
        "worst_final_equity": float(np.min(path_equities)),
        "worst_max_drawdown": float(np.min(path_max_drawdowns)),
        "equity_std": float(np.std(path_equities))
    }
    
    # Generate recommendations
    results["recommendations"] = generate_risk_recommendations(results)
    
    return results

def generate_risk_recommendations(results: Dict[str, Any]) -> List[str]:
    """
    Generate risk management recommendations based on MC analysis.
    
    Args:
        results: Risk analysis results
        
    Returns:
        List of recommendations
    """
    recommendations = []
    
    risk_data = results.get("risk_of_ruin", {})
    portfolio_stats = results.get("portfolio_stats", {})
    path_stats = results.get("path_statistics", {})
    
    # Risk level assessment
    if "0.5" in risk_data:
        risk_50 = risk_data["0.5"]
        if risk_50 < 0.01:
            recommendations.append("✅ Very low risk of ruin - strategy appears very safe")
        elif risk_50 < 0.05:
            recommendations.append("🟢 Low risk of ruin - acceptable risk level")
        elif risk_50 < 0.15:
            recommendations.append("🟡 Moderate risk of ruin - monitor closely")
        else:
            recommendations.append("🔴 High risk of ruin - consider reducing position size")
    
    # Portfolio performance assessment
    sharpe = portfolio_stats.get("sharpe_ratio", 0)
    if sharpe > 1.5:
        recommendations.append("🚀 Excellent risk-adjusted returns")
    elif sharpe > 1.0:
        recommendations.append("📈 Good risk-adjusted returns")
    elif sharpe > 0.5:
        recommendations.append("📊 Moderate risk-adjusted returns")
    else:
        recommendations.append("⚠️ Low risk-adjusted returns - improve strategy")
    
    # Drawdown assessment
    worst_dd = path_stats.get("worst_max_drawdown", 0)
    if worst_dd > -0.1:
        recommendations.append("✅ Low maximum drawdown risk")
    elif worst_dd > -0.2:
        recommendations.append("🟡 Moderate drawdown risk")
    else:
        recommendations.append("🔴 High drawdown risk - implement risk controls")
    
    # Consistency assessment
    equity_std = path_stats.get("equity_std", 0)
    avg_equity = path_stats.get("avg_final_equity", 1.0)
    if avg_equity > 0:
        cv = equity_std / avg_equity  # Coefficient of variation
        if cv < 0.2:
            recommendations.append("✅ Consistent performance across paths")
        elif cv < 0.5:
            recommendations.append("📊 Moderate performance variability")
        else:
            recommendations.append("⚠️ High performance variability - improve consistency")
    
    # General recommendations
    recommendations.append("💡 Consider combining with other risk controls like drawdown limits")
    recommendations.append("🔄 Re-run analysis periodically with updated data")
    recommendations.append("📊 Monitor correlation changes between assets")
    recommendations.append("⚖️ Use fractional Kelly (25-50%) for better risk management")
    
    return recommendations

def compare_portfolio_risk(returns_df: pd.DataFrame,
                           weight_sets: Dict[str, np.ndarray],
                           ruin_level: float = 0.5,
                           n_paths: int = 5000) -> Dict[str, Any]:
    """
    Compare risk of ruin across multiple portfolio weight sets.
    
    Args:
        returns_df: Asset returns DataFrame
        weight_sets: Dictionary of weight sets by name
        ruin_level: Ruin threshold for comparison
        n_paths: Number of Monte Carlo paths
        
    Returns:
        Comparison results
    """
    comparison = {
        "weight_sets": {},
        "risk_comparison": {},
        "best_strategy": None,
        "recommendations": []
    }
    
    # Calculate risk for each weight set
    for name, weights in weight_sets.items():
        try:
            risk = mc_ror_correlated(returns_df, weights, ruin_level, n_paths)
            
            # Calculate portfolio metrics
            port_rets = returns_df.values @ weights
            sharpe = port_rets.mean() / port_rets.std() * np.sqrt(365 * 24 * 4) if port_rets.std() > 0 else 0.0
            leverage = np.sum(np.abs(weights))
            
            comparison["weight_sets"][name] = {
                "weights": weights.tolist(),
                "risk_of_ruin": risk,
                "sharpe_ratio": sharpe,
                "leverage": leverage
            }
            
        except Exception as e:
            logger.error(f"Error calculating risk for {name}: {e}")
            continue
    
    # Find best strategy (lowest risk with reasonable Sharpe)
    best_strategy = None
    best_score = -float('inf')
    
    for name, metrics in comparison["weight_sets"].items():
        # Composite score: risk penalty + Sharpe reward
        risk_penalty = metrics["risk_of_ruin"] * 100
        sharpe_reward = metrics["sharpe_ratio"]
        score = risk_penalty - sharpe_reward
        
        if score < best_score:
            best_score = score
            best_strategy = name
    
    comparison["best_strategy"] = best_strategy
    
    # Generate recommendations
    if best_strategy:
        best_metrics = comparison["weight_sets"][best_strategy]
        comparison["recommendations"].append(f"🏆 Best strategy: {best_strategy}")
        comparison["recommendations"].append(f"Risk of ruin: {best_metrics['risk_of_ruin']:.1%}")
        comparison["recommendations"].append(f"Sharpe ratio: {best_metrics['sharpe_ratio']:.2f}")
        
        # Compare to others
        for name, metrics in comparison["weight_sets"].items():
            if name != best_strategy:
                risk_diff = metrics["risk_of_ruin"] - best_metrics["risk_of_ruin"]
                sharpe_diff = metrics["sharpe_ratio"] - best_metrics["sharpe_ratio"]
                
                if risk_diff > 0.03:  # 3% higher risk (optimized 2026-05-07)
                    comparison["recommendations"].append(
                        f"⚠️ {name} has {risk_diff:.1%} higher risk of ruin"
                    )
                elif sharpe_diff < -0.2:  # 0.2 lower Sharpe
                    comparison["recommendations"].append(
                        f"📉 {name} has {abs(sharpe_diff):.2f} lower Sharpe ratio"
                    )
    
    return comparison

def print_risk_analysis(results: Dict[str, Any], title: str = "Risk of Ruin Analysis"):
    """
    Print formatted risk analysis results.
    
    Args:
        results: Risk analysis results
        title: Analysis title
    """
    if not results:
        print("No results to display")
        return
    
    print(f"\n{title}")
    print("=" * 60)
    
    # Basic info
    print(f"\nSimulation Parameters:")
    print("-" * 40)
    print(f"  Assets: {results['n_assets']}")
    print(f"  Periods: {results['n_periods']}")
    print(f"  Paths: {results['n_paths']}")
    print(f"  Ruin Levels: {results['ruin_levels']}")
    
    # Risk of ruin results
    print(f"\nRisk of Ruin Results:")
    print("-" * 50)
    print(f"{'Ruin Level':<15} {'Risk':<10} {'Assessment':<20}")
    print("-" * 50)
    
    for level, risk in results["risk_of_ruin"].items():
        if float(level) == 0.5:
            assessment = "Primary metric"
        elif float(level) > 0.5:
            assessment = "High threshold"
        else:
            assessment = "Low threshold"
        
        print(f"{float(level):<15.0%} {risk:<10.1%} {assessment:<20}")
    
    # Portfolio statistics
    if "portfolio_stats" in results:
        stats = results["portfolio_stats"]
        print(f"\nPortfolio Statistics:")
        print("-" * 40)
        print(f"  Mean Return: {stats['mean_return']:.4f}")
        print(f"  Volatility: {stats['volatility']:.4f}")
        print(f"  Sharpe Ratio: {stats['sharpe_ratio']:.2f}")
        print(f"  Skewness: {stats['skewness']:.3f}")
        print(f"  Kurtosis: {stats['kurtosis']:.3f}")
    
    # Path statistics
    if "path_statistics" in results:
        path_stats = results["path_statistics"]
        print(f"\nPath Statistics (Sample):")
        print("-" * 40)
        print(f"  Avg Final Equity: {path_stats['avg_final_equity']:.3f}")
        print(f"  Avg Max Drawdown: {path_stats['avg_max_drawdown']:.2%}")
        print(f"  Worst Final Equity: {path_stats['worst_final_equity']:.3f}")
        print(f"  Worst Max Drawdown: {path_stats['worst_max_drawdown']:.2%}")
        print(f"  Equity Std Dev: {path_stats['equity_std']:.3f}")
    
    # Recommendations
    if "recommendations" in results:
        print(f"\nRecommendations:")
        print("-" * 40)
        for rec in results["recommendations"]:
            print(f"  {rec}")
    
    print("=" * 60)

# Example usage:
"""
import pandas as pd
import numpy as np

# Generate sample correlated returns
np.random.seed(42)
n_periods = 200
n_assets = 2

# Create correlation matrix
corr = np.array([[1.0, 0.3], [0.3, 1.0]])
vol = np.array([0.02, 0.025])
cov = np.outer(vol, vol) * corr

mean_returns = np.array([0.001, 0.0015])
returns = np.random.multivariate_normal(mean_returns, cov, n_periods)

returns_df = pd.DataFrame(returns, columns=['BTC', 'ETH'])

# Portfolio weights
weights = np.array([0.6, 0.4])

# Basic risk of ruin
risk = mc_ror_correlated(returns_df, weights, ruin_level=0.5, n_paths=2000)
print(f"Risk of ruin: {risk:.2%}")

# Detailed analysis
detailed_results = mc_ror_correlated_detailed(returns_df, weights, n_paths=2000)
print_risk_analysis(detailed_results)

# Compare multiple strategies
weight_sets = {
    'equal': np.array([0.5, 0.5]),
    'kelly': np.array([0.7, 0.3]),
    'conservative': np.array([0.3, 0.2])
}

comparison = compare_portfolio_risk(returns_df, weight_sets)
print(f"Best strategy: {comparison['best_strategy']}")
"""
