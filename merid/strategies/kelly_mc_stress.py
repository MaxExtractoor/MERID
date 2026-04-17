"""
Monte Carlo Stress Testing for Kalshi Kelly Backtests

Monte Carlo stress testing with summary statistics for Kelly validation.
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List
import logging

from .quarter_half_kelly import kelly_equity

logger = logging.getLogger(__name__)

def mc_stress_summary(
    trade_pnls: List[float],
    fraction: float,
    n_paths: int = 5000,
    ruin_level: float = 0.5,
    seed: int = None
) -> Dict[str, Any]:
    """
    Monte Carlo stress testing summary for Kelly fraction.
    
    Args:
        trade_pnls: List of per-trade PnLs
        fraction: Kelly fraction to test
        n_paths: Number of Monte Carlo paths
        ruin_level: Capital level that constitutes ruin
        seed: Random seed for reproducibility
        
    Returns:
        Stress testing summary statistics
    """
    if not trade_pnls:
        logger.warning("No trade PnLs provided for stress testing")
        return {}
    
    if seed is not None:
        np.random.seed(seed)
    
    pnls = np.array(trade_pnls)
    
    finals = []
    max_dds = []
    ruin_hits = 0
    min_caps = []
    
    logger.info(f"Running MC stress test: fraction={fraction:.3f}, n_paths={n_paths}")
    
    for i in range(n_paths):
        # Random permutation of trades
        perm = np.random.permutation(pnls)
        
        # Generate equity curve
        eq = kelly_equity(perm.tolist(), fraction)
        
        # Calculate metrics
        peak = eq.cummax()
        dd = (eq - peak) / peak.replace(0, np.nan)
        min_cap = eq.min()
        
        finals.append(eq.iloc[-1])
        max_dds.append(dd.min())
        min_caps.append(min_cap)
        
        # Check for ruin
        if min_cap <= ruin_level:
            ruin_hits += 1
        
        # Progress logging
        if (i + 1) % 1000 == 0:
            logger.debug(f"Completed {i + 1}/{n_paths} stress paths")
    
    # Convert to arrays
    finals = np.array(finals)
    max_dds = np.array(max_dds)
    min_caps = np.array(min_caps)
    
    # Calculate statistics
    results = {
        "fraction": fraction,
        "n_paths": n_paths,
        "final_mean": float(finals.mean()),
        "final_std": float(finals.std()),
        "final_p05": float(np.percentile(finals, 5)),
        "final_p25": float(np.percentile(finals, 25)),
        "final_p75": float(np.percentile(finals, 75)),
        "final_p95": float(np.percentile(finals, 95)),
        "dd_mean": float(max_dds.mean()),
        "dd_std": float(max_dds.std()),
        "dd_p05": float(np.percentile(max_dds, 5)),
        "dd_p25": float(np.percentile(max_dds, 25)),
        "dd_p75": float(np.percentile(max_dds, 75)),
        "dd_p95": float(np.percentile(max_dds, 95)),
        "min_cap_mean": float(min_caps.mean()),
        "min_cap_p05": float(np.percentile(min_caps, 5)),
        "risk_of_ruin": ruin_hits / n_paths,  # probability equity < ruin_level at any time
        "ruin_hits": ruin_hits,
        "profit_probability": float(np.mean(finals > 1.0)),  # probability of profit
        "loss_probability": float(np.mean(finals < 1.0)),  # probability of loss
        "severe_loss_probability": float(np.mean(finals < 0.8)),  # probability of >20% loss
        "risk_adjusted_return": float(finals.mean() / abs(max_dds.mean())) if max_dds.mean() != 0 else float(finals.mean())
    }
    
    logger.info(f"Stress test completed: mean_final={results['final_mean']:.3f}, "
                f"ruin_prob={results['risk_of_ruin']:.2%}, dd_mean={results['dd_mean']:.2%}")
    
    return results

def compare_stress_fractions(trade_pnls: List[float], 
                           fractions: List[float],
                           n_paths: int = 5000,
                           ruin_level: float = 0.5) -> Dict[str, Any]:
    """
    Compare stress testing results across multiple Kelly fractions.
    
    Args:
        trade_pnls: List of per-trade PnLs
        fractions: List of Kelly fractions to test
        n_paths: Number of Monte Carlo paths per fraction
        ruin_level: Capital level that constitutes ruin
        
    Returns:
        Comparison results
    """
    if not trade_pnls:
        return {"error": "No trade PnLs provided"}
    
    results = {}
    
    for fraction in fractions:
        logger.info(f"Stress testing fraction: {fraction:.3f}")
        
        try:
            stress_result = mc_stress_summary(trade_pnls, fraction, n_paths, ruin_level)
            results[f"fraction_{fraction:.3f}"] = stress_result
        except Exception as e:
            logger.error(f"Error in stress test for fraction {fraction:.3f}: {e}")
            continue
    
    if not results:
        return {"error": "No valid stress test results"}
    
    # Find best performers
    best_return = max(results.items(), key=lambda x: x[1]["final_mean"])
    best_sharpe = max(results.items(), key=lambda x: x[1]["risk_adjusted_return"])
    lowest_risk = min(results.items(), key=lambda x: x[1]["risk_of_ruin"])
    lowest_dd = min(results.items(), key=lambda x: x[1]["dd_mean"])
    
    comparison = {
        "best_return": {
            "fraction": best_return[0],
            "final_mean": best_return[1]["final_mean"],
            "risk_of_ruin": best_return[1]["risk_of_ruin"]
        },
        "best_sharpe": {
            "fraction": best_sharpe[0],
            "risk_adj_return": best_sharpe[1]["risk_adjusted_return"],
            "dd_mean": best_sharpe[1]["dd_mean"]
        },
        "lowest_risk": {
            "fraction": lowest_risk[0],
            "risk_of_ruin": lowest_risk[1]["risk_of_ruin"],
            "final_mean": lowest_risk[1]["final_mean"]
        },
        "lowest_drawdown": {
            "fraction": lowest_dd[0],
            "dd_mean": lowest_dd[1]["dd_mean"],
            "dd_p95": lowest_dd[1]["dd_p95"]
        }
    }
    
    return {
        "results": results,
        "comparison": comparison,
        "fractions_tested": fractions,
        "n_paths": n_paths,
        "ruin_level": ruin_level
    }

def print_stress_summary(results: Dict[str, Any], title: str = "Monte Carlo Stress Testing Summary"):
    """
    Print formatted stress testing summary.
    
    Args:
        results: Stress testing results
        title: Summary title
    """
    if not results or "fraction" not in results:
        print("No stress testing results to display")
        return
    
    print(f"\n{title}")
    print("=" * 80)
    
    print(f"\nStress Test Results for Kelly Fraction: {results['fraction']:.3f}")
    print(f"Paths Simulated: {results['n_paths']:,}")
    print(f"Ruin Level: {results.get('ruin_level', 0.5):.1%}")
    
    print(f"\nFinal Capital Distribution:")
    print("-" * 50)
    print(f"  Mean: {results['final_mean']:.3f}")
    print(f"  Std:  {results['final_std']:.3f}")
    print(f"  5th percentile: {results['final_p05']:.3f}")
    print(f"  25th percentile: {results['final_p25']:.3f}")
    print(f"  75th percentile: {results['final_p75']:.3f}")
    print(f"  95th percentile: {results['final_p95']:.3f}")
    
    print(f"\nDrawdown Distribution:")
    print("-" * 50)
    print(f"  Mean: {results['dd_mean']:.2%}")
    print(f"  Std:  {results['dd_std']:.2%}")
    print(f"  5th percentile: {results['dd_p05']:.2%}")
    print(f"  95th percentile: {results['dd_p95']:.2%}")
    
    print(f"\nRisk Metrics:")
    print("-" * 50)
    print(f"  Risk of Ruin: {results['risk_of_ruin']:.2%}")
    print(f"  Profit Probability: {results['profit_probability']:.2%}")
    print(f"  Loss Probability: {results['loss_probability']:.2%}")
    print(f"  Severe Loss Prob: {results['severe_loss_probability']:.2%}")
    print(f"  Risk-Adjusted Return: {results['risk_adjusted_return']:.3f}")
    
    # Risk assessment
    if results['risk_of_ruin'] < 0.01:
        risk_level = "Very Low"
    elif results['risk_of_ruin'] < 0.05:
        risk_level = "Low"
    elif results['risk_of_ruin'] < 0.15:
        risk_level = "Moderate"
    elif results['risk_of_ruin'] < 0.30:
        risk_level = "High"
    else:
        risk_level = "Very High"
    
    print(f"\nRisk Assessment: {risk_level}")
    
    print("=" * 80)

def print_stress_comparison(comparison: Dict[str, Any]):
    """
    Print formatted stress testing comparison.
    
    Args:
        comparison: Comparison results from compare_stress_fractions
    """
    if "results" not in comparison:
        print("No comparison results to display")
        return
    
    results = comparison["results"]
    comp = comparison["comparison"]
    
    print(f"\nMonte Carlo Stress Testing Comparison")
    print("=" * 80)
    
    print(f"\nSummary by Fraction:")
    print("-" * 80)
    print(f"{'Fraction':<12} {'Final Mean':<12} {'Risk Adj':<10} {'Ruin':<8} {'DD Mean':<10} {'DD 95th':<10}")
    print("-" * 80)
    
    for result_name, result_data in results.items():
        fraction = result_data["fraction"]
        final_mean = result_data["final_mean"]
        risk_adj = result_data["risk_adjusted_return"]
        ruin_prob = result_data["risk_of_ruin"]
        dd_mean = result_data["dd_mean"]
        dd_p95 = result_data["dd_p95"]
        
        print(f"{fraction:<12.3f} {final_mean:<12.3f} {risk_adj:<10.3f} "
              f"{ruin_prob:<8.2%} {dd_mean:<10.2%} {dd_p95:<10.2%}")
    
    print(f"\nBest Performers:")
    print("-" * 50)
    print(f"  Highest Return: {comp['best_return']['fraction']} "
          f"(mean: {comp['best_return']['final_mean']:.3f}, ruin: {comp['best_return']['risk_of_ruin']:.2%})")
    print(f"  Best Risk-Adjusted: {comp['best_sharpe']['fraction']} "
          f"(risk adj: {comp['best_sharpe']['risk_adj_return']:.3f}, dd: {comp['best_sharpe']['dd_mean']:.2%})")
    print(f"  Lowest Risk of Ruin: {comp['lowest_risk']['fraction']} "
          f"(ruin: {comp['lowest_risk']['risk_of_ruin']:.2%}, mean: {comp['lowest_risk']['final_mean']:.3f})")
    print(f"  Lowest Drawdown: {comp['lowest_drawdown']['fraction']} "
          f"(dd mean: {comp['lowest_drawdown']['dd_mean']:.2%}, dd 95th: {comp['lowest_drawdown']['dd_p95']:.2%})")
    
    print("=" * 80)

def generate_stress_recommendations(comparison: Dict[str, Any]) -> List[str]:
    """
    Generate recommendations based on stress testing comparison.
    
    Args:
        comparison: Comparison results from compare_stress_fractions
        
    Returns:
        List of recommendations
    """
    if "results" not in comparison:
        return ["No stress testing results available for recommendations"]
    
    results = comparison["results"]
    comp = comparison["comparison"]
    
    recommendations = []
    
    # Analyze risk levels
    max_risk = max(result["risk_of_ruin"] for result in results.values())
    min_risk = min(result["risk_of_ruin"] for result in results.values())
    
    if max_risk > 0.20:
        recommendations.append(f"⚠️ High risk of ruin detected ({max_risk:.1%}) - consider more conservative sizing")
    elif max_risk > 0.10:
        recommendations.append(f"📊 Moderate risk of ruin ({max_risk:.1%}) - monitor risk carefully")
    elif max_risk < 0.05:
        recommendations.append(f"✅ Low risk of ruin ({max_risk:.1%}) - current sizing appears safe")
    
    # Analyze best performers
    best_risk_adj = comp["best_sharpe"]
    best_return = comp["best_return"]
    lowest_risk_frac = comp["lowest_risk"]
    
    # Check if best return has acceptable risk
    if best_return["risk_of_ruin"] < 0.10:
        recommendations.append(f"🚀 {best_return['fraction']} offers best returns with acceptable risk")
    else:
        recommendations.append(f"⚠️ {best_return['fraction']} has best returns but high risk ({best_return['risk_of_ruin']:.1%})")
    
    # Check risk-adjusted performance
    if best_risk_adj["risk_adj_return"] > 2.0:
        recommendations.append(f"✅ {best_risk_adj['fraction']} provides excellent risk-adjusted returns")
    elif best_risk_adj["risk_adj_return"] > 1.0:
        recommendations.append(f"📈 {best_risk_adj['fraction']} provides good risk-adjusted returns")
    else:
        recommendations.append(f"⚠️ Risk-adjusted returns are low across all fractions")
    
    # Check drawdown levels
    worst_dd = min(result["dd_mean"] for result in results.values())
    if worst_dd < -0.30:
        recommendations.append(f"📉 Severe drawdowns possible ({worst_dd:.1%}) - implement strong risk controls")
    elif worst_dd < -0.20:
        recommendations.append(f"📊 Moderate drawdowns expected ({worst_dd:.1%}) - monitor carefully")
    
    # Specific recommendations
    if lowest_risk_frac["risk_of_ruin"] < 0.05:
        recommendations.append(f"🛡️ {lowest_risk_frac['fraction']} has lowest risk - recommended for conservative trading")
    
    # General recommendations
    recommendations.append("💡 Consider combining Kelly sizing with drawdown limits")
    recommendations.append("🔄 Re-run stress testing periodically with updated trade data")
    recommendations.append("⚖️ Use fractional Kelly (25-50%) for better risk management")
    
    return recommendations

# Example usage for Kalshi Kelly validation:
"""
import numpy as np

# Generate sample trade PnLs from Kalshi strategy
np.random.seed(42)
trade_pnls = np.random.choice([0.015, -0.008, 0.020, -0.012, 0.025, -0.018], size=100)

# Test different Kelly fractions
fractions = [0.25, 0.5, 0.75, 1.0]  # Quarter, half, three-quarters, full Kelly

# Run stress testing comparison
comparison = compare_stress_fractions(trade_pnls.tolist(), fractions, n_paths=2000)

# Print comparison
print_stress_comparison(comparison)

# Generate recommendations
recommendations = generate_stress_recommendations(comparison)
print("Recommendations:")
for rec in recommendations:
    print(f"  {rec}")

# Individual fraction analysis
for fraction in fractions:
    result = mc_stress_summary(trade_pnls.tolist(), fraction, n_paths=1000)
    print_stress_summary(result, f"Stress Test for {fraction:.1f} Kelly")
"""
