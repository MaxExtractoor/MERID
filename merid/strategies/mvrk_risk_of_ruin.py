"""
MVRK Risk of Ruin - Monte Carlo Analysis for MVRK Strategies

Risk of ruin analysis for multivariate volatility regulated Kelly strategies.
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

def mc_mvrk_risk_of_ruin(
    returns_df: pd.DataFrame,
    weights: np.ndarray,
    ruin_level: float = 0.5,
    n_paths: int = 5000,
    seed: int = None
) -> float:
    """
    Monte Carlo risk of ruin calculation for MVRK portfolio.
    
    Args:
        returns_df: Asset returns DataFrame (periods x assets)
        weights: Portfolio weights (MVRK or Kelly)
        ruin_level: Capital threshold (0.5 = 50% of starting capital)
        n_paths: Number of Monte Carlo paths
        seed: Random seed for reproducibility
        
    Returns:
        Risk of ruin probability
    """
    if returns_df.empty:
        logger.warning("Empty returns DataFrame")
        return 0.0
    
    if len(weights) != len(returns_df.columns):
        raise ValueError("Weight dimension mismatch with returns columns")
    
    if seed is not None:
        np.random.seed(seed)
    
    rets = returns_df.values
    T, N = rets.shape
    ruin_hits = 0
    
    logger.info(f"Running MVRK risk of ruin: {n_paths} paths, {T} periods, {N} assets")
    
    for i in range(n_paths):
        # Shuffle periods to get new sequence (Monte Carlo)
        idx = np.random.permutation(T)
        rets_perm = rets[idx, :]
        
        # Calculate portfolio returns
        port_rets = rets_perm @ weights
        
        # Generate equity curve
        equity = (1 + port_rets).cumprod()
        
        # Check for ruin
        if equity.min() <= ruin_level:
            ruin_hits += 1
        
        # Progress logging
        if (i + 1) % 1000 == 0:
            logger.debug(f"Completed {i + 1}/{n_paths} MVRK ruin paths")
    
    ruin_probability = ruin_hits / n_paths
    
    logger.info(f"MVRK risk of ruin completed: {ruin_hits}/{n_paths} paths hit ruin ({ruin_probability:.2%})")
    
    return ruin_probability

def compare_mvrk_kelly_risk_of_ruin(
    returns_df: pd.DataFrame,
    theta_values: List[float] = None,
    ruin_levels: List[float] = None,
    n_paths: int = 5000
) -> Dict[str, Any]:
    """
    Compare risk of ruin between MVRK and Kelly strategies.
    
    Args:
        returns_df: Asset returns DataFrame
        theta_values: List of theta values for MVRK
        ruin_levels: List of ruin levels to test
        n_paths: Number of Monte Carlo paths per test
        
    Returns:
        Comparison results
    """
    if returns_df.empty:
        return {"error": "Empty returns DataFrame"}
    
    if theta_values is None:
        theta_values = [0.0, 0.5, 1.0, 2.0]  # Classical Kelly and MVRK variants
    
    if ruin_levels is None:
        ruin_levels = [0.8, 0.6, 0.4, 0.2]  # Different ruin thresholds
    
    # Estimate parameters
    from .mvrk import classical_kelly_weights, mvrk_weights
    from .mvrk_backtest import estimate_mu_cov
    
    mu, cov = estimate_mu_cov(returns_df)
    
    # Calculate weights
    w_kelly = classical_kelly_weights(mu, cov)
    w_mvrk = {}
    
    for theta in theta_values:
        w_mvrk[theta] = mvrk_weights(mu, cov, theta)
    
    # Normalize weights to same gross exposure
    from .mvrk_backtest import normalize_weights
    w_kelly_norm = normalize_weights(w_kelly, method="sum_abs")
    w_mvrk_norm = {}
    
    for theta, weights in w_mvrk.items():
        w_mvrk_norm[theta] = normalize_weights(weights, method="sum_abs")
    
    results = {}
    
    # Test classical Kelly variants
    kelly_variants = {
        "full_kelly": w_kelly_norm,
        "half_kelly": 0.5 * w_kelly_norm,
        "quarter_kelly": 0.25 * w_kelly_norm
    }
    
    for variant_name, weights in kelly_variants.items():
        variant_results = {}
        
        for ruin_level in ruin_levels:
            try:
                ruin_prob = mc_mvrk_risk_of_ruin(returns_df, weights, ruin_level, n_paths)
                variant_results[f"ruin_{ruin_level}"] = ruin_prob
            except Exception as e:
                logger.error(f"Error in {variant_name} ruin level {ruin_level}: {e}")
                continue
        
        results[variant_name] = variant_results
    
    # Test MVRK variants
    for theta, weights in w_mvrk_norm.items():
        mvrk_name = f"mvrk_theta_{theta}"
        mvrk_results = {}
        
        for ruin_level in ruin_levels:
            try:
                ruin_prob = mc_mvrk_risk_of_ruin(returns_df, weights, ruin_level, n_paths)
                mvrk_results[f"ruin_{ruin_level}"] = ruin_prob
            except Exception as e:
                logger.error(f"Error in {mvrk_name} ruin level {ruin_level}: {e}")
                continue
        
        results[mvrk_name] = mvrk_results
    
    return {
        "results": results,
        "theta_values": theta_values,
        "ruin_levels": ruin_levels,
        "n_paths": n_paths,
        "assets": list(returns_df.columns)
    }

def analyze_mvrk_risk_comparison(comparison: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze MVRK vs Kelly risk of ruin comparison.
    
    Args:
        comparison: Results from compare_mvrk_kelly_risk_of_ruin
        
    Returns:
        Analysis results
    """
    if "results" not in comparison:
        return {"error": "No comparison results"}
    
    results = comparison["results"]
    ruin_levels = comparison["ruin_levels"]
    
    # Separate Kelly and MVRK results
    kelly_results = {k: v for k, v in results.items() if "kelly" in k}
    mvrk_results = {k: v for k, v in results.items() if "mvrk" in k}
    
    # Calculate summary statistics
    summary = {}
    
    # Kelly summary
    if kelly_results:
        kelly_max_risks = {}
        kelly_avg_risks = {}
        
        for ruin_level in ruin_levels:
            risks = [result[f"ruin_{ruin_level}"] for result in kelly_results.values() if f"ruin_{ruin_level}" in result]
            if risks:
                kelly_max_risks[ruin_level] = max(risks)
                kelly_avg_risks[ruin_level] = np.mean(risks)
        
        summary["kelly"] = {
            "max_risks": kelly_max_risks,
            "avg_risks": kelly_avg_risks,
            "strategies": list(kelly_results.keys())
        }
    
    # MVRK summary
    if mvrk_results:
        mvrk_max_risks = {}
        mvrk_avg_risks = {}
        
        for ruin_level in ruin_levels:
            risks = [result[f"ruin_{ruin_level}"] for result in mvrk_results.values() if f"ruin_{ruin_level}" in result]
            if risks:
                mvrk_max_risks[ruin_level] = min(risks)  # Best (lowest) risk
                mvrk_avg_risks[ruin_level] = np.mean(risks)
        
        summary["mvrk"] = {
            "max_risks": mvrk_max_risks,
            "avg_risks": mvrk_avg_risks,
            "strategies": list(mvrk_results.keys())
        }
    
    # Compare best performers
    best_performers = {}
    
    for ruin_level in ruin_levels:
        best_kelly = min(kelly_results.items(), key=lambda x: x[1].get(f"ruin_{ruin_level}", 1.0)) if kelly_results else None
        best_mvrk = min(mvrk_results.items(), key=lambda x: x[1].get(f"ruin_{ruin_level}", 1.0)) if mvrk_results else None
        
        if best_kelly and best_mvrk:
            kelly_risk = best_kelly[1].get(f"ruin_{ruin_level}", 1.0)
            mvrk_risk = best_mvrk[1].get(f"ruin_{ruin_level}", 1.0)
            
            best_performers[ruin_level] = {
                "best_kelly": {"strategy": best_kelly[0], "risk": kelly_risk},
                "best_mvrk": {"strategy": best_mvrk[0], "risk": mvrk_risk},
                "mvrk_better": mvrk_risk < kelly_risk,
                "risk_improvement": (kelly_risk - mvrk_risk) / kelly_risk if kelly_risk > 0 else 0.0
            }
    
    summary["best_performers"] = best_performers
    
    # Overall assessment
    mvrk_wins = sum(1 for perf in best_performers.values() if perf["mvrk_better"])
    total_levels = len(best_performers)
    
    summary["overall"] = {
        "mvrk_win_rate": mvrk_wins / total_levels if total_levels > 0 else 0.0,
        "total_levels": total_levels,
        "mvrk_dominant": mvrk_wins > total_levels / 2
    }
    
    return summary

def print_mvrk_risk_comparison(comparison: Dict[str, Any]):
    """
    Print formatted MVRK risk of ruin comparison.
    
    Args:
        comparison: Results from compare_mvrk_kelly_risk_of_ruin
    """
    if "results" not in comparison:
        print("No comparison results to display")
        return
    
    results = comparison["results"]
    ruin_levels = comparison["ruin_levels"]
    
    print("\n" + "="*80)
    print("MVRK VS KELLY RISK OF RUIN COMPARISON")
    print("="*80)
    
    print(f"\nMonte Carlo Settings:")
    print(f"  Paths per test: {comparison['n_paths']:,}")
    print(f"  Assets: {', '.join(comparison['assets'])}")
    print(f"  Ruin levels: {ruin_levels}")
    
    # Group by strategy type
    kelly_strategies = {k: v for k, v in results.items() if "kelly" in k}
    mvrk_strategies = {k: v for k, v in results.items() if "mvrk" in k}
    
    print(f"\nRisk of Ruin by Strategy and Ruin Level:")
    print("-" * 80)
    print(f"{'Strategy':<20} {'80%':<8} {'60%':<8} {'40%':<8} {'20%':<8}")
    print("-" * 80)
    
    # Kelly strategies
    for strategy_name, strategy_results in kelly_strategies.items():
        risks = []
        for level in ruin_levels:
            risk = strategy_results.get(f"ruin_{level}", 0.0)
            risks.append(f"{risk:.2%}")
        print(f"{strategy_name:<20} {' '.join(risks)}")
    
    # MVRK strategies
    for strategy_name, strategy_results in mvrk_strategies.items():
        risks = []
        for level in ruin_levels:
            risk = strategy_results.get(f"ruin_{level}", 0.0)
            risks.append(f"{risk:.2%}")
        print(f"{strategy_name:<20} {' '.join(risks)}")
    
    # Analysis
    analysis = analyze_mvrk_risk_comparison(comparison)
    
    if "best_performers" in analysis:
        print(f"\nBest Performers by Ruin Level:")
        print("-" * 60)
        
        for level, perf in analysis["best_performers"].items():
            kelly_best = perf["best_kelly"]
            mvrk_best = perf["best_mvrk"]
            
            print(f"  {level:.0%} ruin:")
            print(f"    Best Kelly: {kelly_best['strategy']} ({kelly_best['risk']:.2%})")
            print(f"    Best MVRK: {mvrk_best['strategy']} ({mvrk_best['risk']:.2%})")
            print(f"    MVRK Better: {'Yes' if perf['mvrk_better'] else 'No'}")
            print(f"    Improvement: {perf['risk_improvement']:.1%}")
    
    # Overall assessment
    if "overall" in analysis:
        overall = analysis["overall"]
        print(f"\nOverall Assessment:")
        print("-" * 40)
        print(f"  MVRK Win Rate: {overall['mvrk_win_rate']:.1%}")
        print(f"  MVRK Dominant: {'Yes' if overall['mvrk_dominant'] else 'No'}")
    
    print("="*80)

def find_safest_mvrk_strategy(comparison: Dict[str, Any], 
                            max_risk_tolerance: float = 0.05,
                            ruin_level: float = 0.5) -> Dict[str, Any]:
    """
    Find safest MVRK strategy based on risk tolerance.
    
    Args:
        comparison: Results from compare_mvrk_kelly_risk_of_ruin
        max_risk_tolerance: Maximum acceptable risk of ruin
        ruin_level: Ruin level to evaluate (default 0.5 = 50%)
        
    Returns:
        Safest strategy information
    """
    if "results" not in comparison:
        return {"error": "No comparison results"}
    
    results = comparison["results"]
    
    # Find MVRK strategies
    mvrk_strategies = {k: v for k, v in results.items() if "mvrk" in k}
    
    if not mvrk_strategies:
        return {"error": "No MVRK strategies found"}
    
    safe_strategies = []
    
    for strategy_name, strategy_results in mvrk_strategies.items():
        risk = strategy_results.get(f"ruin_{ruin_level}", 1.0)
        
        if risk <= max_risk_tolerance:
            # Calculate additional metrics
            all_risks = [v for k, v in strategy_results.items() if k.startswith("ruin_")]
            avg_risk = np.mean(all_risks) if all_risks else risk
            
            safe_strategies.append({
                "strategy": strategy_name,
                "target_risk": risk,
                "avg_risk": avg_risk,
                "max_risk": max(all_risks) if all_risks else risk,
                "risk_score": risk + (1.0 - avg_risk)  # Lower is better
            })
    
    if not safe_strategies:
        return {"error": f"No MVRK strategies meet risk tolerance {max_risk_tolerance:.1%}"}
    
    # Sort by risk score (lowest first)
    safe_strategies.sort(key=lambda x: x["risk_score"])
    
    safest = safe_strategies[0]
    
    return {
        "safest_strategy": safest["strategy"],
        "safest_risk": safest["target_risk"],
        "safest_avg_risk": safest["avg_risk"],
        "safest_max_risk": safest["max_risk"],
        "risk_score": safest["risk_score"],
        "total_safe_strategies": len(safe_strategies),
        "all_safe_strategies": safe_strategies
    }

def generate_mvrk_risk_recommendations(comparison: Dict[str, Any]) -> List[str]:
    """
    Generate recommendations based on MVRK risk of ruin analysis.
    
    Args:
        comparison: Results from compare_mvrk_kelly_risk_of_ruin
        
    Returns:
        List of recommendations
    """
    if "results" not in comparison:
        return ["No risk analysis data available for recommendations"]
    
    analysis = analyze_mvrk_risk_comparison(comparison)
    
    recommendations = []
    
    # Overall assessment
    if "overall" in analysis:
        overall = analysis["overall"]
        
        if overall["mvrk_dominant"]:
            recommendations.append("✅ MVRK consistently outperforms Kelly across ruin levels")
            recommendations.append("🚀 MVRK recommended for live trading")
        elif overall["mvrk_win_rate"] > 0.5:
            recommendations.append("📈 MVRK outperforms Kelly in majority of scenarios")
            recommendations.append("📊 Consider MVRK for improved risk management")
        else:
            recommendations.append("⚠️ Kelly outperforms MVRK in most scenarios")
            recommendations.append("📊 Consider sticking with fractional Kelly")
    
    # Risk level analysis
    if "best_performers" in analysis:
        best_performers = analysis["best_performers"]
        
        high_risk_levels = [level for level, perf in best_performers.items() 
                             if perf["best_kelly"]["risk"] > 0.20 or perf["best_mvrk"]["risk"] > 0.20]
        
        if high_risk_levels:
            recommendations.append(f"⚠️ High risk levels detected: {high_risk_levels}")
            recommendations.append("📉 Use conservative position sizing for high volatility periods")
        
        # Check MVRK effectiveness
        mvrk_improvements = [perf["risk_improvement"] for perf in best_performers.values() if perf["risk_improvement"] > 0]
        
        if mvrk_improvements:
            avg_improvement = np.mean(mvrk_improvements)
            if avg_improvement > 0.2:
                recommendations.append(f"✅ MVRK significantly reduces risk (avg: {avg_improvement:.1%})")
            elif avg_improvement > 0.1:
                recommendations.append(f"📈 MVRK moderately reduces risk (avg: {avg_improvement:.1%})")
            else:
                recommendations.append(f"📊 MVRK slightly reduces risk (avg: {avg_improvement:.1%})")
    
    # Find safest strategy
    safest = find_safest_mvrk_strategy(comparison, max_risk_tolerance=0.05)
    
    if "error" not in safest:
        recommendations.append(f"🛡️ Safest MVRK strategy: {safest['safest_strategy']} "
                           f"(risk: {safest['safest_risk']:.1%})")
        
        if safest["total_safe_strategies"] > 1:
            recommendations.append(f"📊 {safest['total_safe_strategies']} MVRK strategies meet 5% risk tolerance")
    else:
        recommendations.append("⚠️ No MVRK strategies meet 5% risk tolerance - consider very conservative sizing")
    
    # General recommendations
    recommendations.append("💡 Use risk-of-ruin analysis to set maximum position sizes")
    recommendations.append("🔄 Re-run analysis periodically with updated returns data")
    recommendations.append("⚖️ Combine MVRK with other risk controls like drawdown limits")
    recommendations.append("📊 Consider using quarter Kelly for maximum safety in high volatility")
    
    return recommendations

# Example usage for Kalshi multi-asset strategy:
"""
# Assume we have returns data for BTC and ETH from Kalshi events
import pandas as pd
import numpy as np

# Generate sample data (replace with actual Kalshi returns)
np.random.seed(42)
n_periods = 200
btc_returns = np.random.normal(0.001, 0.02, n_periods)
eth_returns = np.random.normal(0.0015, 0.025, n_periods)

returns_df = pd.DataFrame({
    'BTC': btc_returns,
    'ETH': eth_returns
})

# Compare risk of ruin
comparison = compare_mvrk_kelly_risk_of_ruin(returns_df, theta_values=[0.0, 0.5, 1.0, 2.0])

# Print comparison
print_mvrk_risk_comparison(comparison)

# Find safest strategy
safest = find_safest_mvrk_strategy(comparison, max_risk_tolerance=0.05)
print(f"Safest MVRK strategy: {safest}")

# Generate recommendations
recommendations = generate_mvrk_risk_recommendations(comparison)
print("Recommendations:")
for rec in recommendations:
    print(f"  {rec}")
"""
