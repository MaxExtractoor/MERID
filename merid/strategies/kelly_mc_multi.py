"""
Kelly Monte Carlo Extension for Fractional Kelly Backtest

Monte Carlo for multiple fractions with distribution comparison.
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List
import logging

from .quarter_half_kelly import kelly_equity

logger = logging.getLogger(__name__)

def mc_for_fraction(trade_pnls: np.ndarray, f: float, n_paths: int = 2000, seed: int = None) -> Dict[str, Any]:
    """
    Run Monte Carlo simulation for a specific Kelly fraction.
    
    Args:
        trade_pnls: Array of trade PnLs
        f: Kelly fraction to test
        n_paths: Number of Monte Carlo paths
        seed: Random seed for reproducibility
        
    Returns:
        Monte Carlo results for this fraction
    """
    if seed is not None:
        np.random.seed(seed)
    
    finals = []
    max_dds = []
    min_caps = []
    
    for i in range(n_paths):
        # Random permutation of trades
        perm = np.random.permutation(trade_pnls)
        
        # Generate equity curve
        eq = kelly_equity(perm.tolist(), f)
        
        # Calculate metrics
        peak = eq.cummax()
        dd = (eq - peak) / peak.replace(0, np.nan)
        
        finals.append(eq.iloc[-1])
        max_dds.append(dd.min())
        min_caps.append(eq.min())
        
        # Progress logging
        if (i + 1) % 500 == 0:
            logger.debug(f"Completed {i + 1}/{n_paths} paths for fraction {f:.3f}")
    
    # Convert to arrays
    finals = np.array(finals)
    max_dds = np.array(max_dds)
    min_caps = np.array(min_caps)
    
    # Calculate statistics
    results = {
        "fraction": f,
        "n_paths": n_paths,
        "final_capital_mean": float(finals.mean()),
        "final_capital_std": float(finals.std()),
        "final_capital_median": float(np.median(finals)),
        "final_capital_p05": float(np.percentile(finals, 5)),
        "final_capital_p25": float(np.percentile(finals, 25)),
        "final_capital_p75": float(np.percentile(finals, 75)),
        "final_capital_p95": float(np.percentile(finals, 95)),
        "dd_mean": float(max_dds.mean()),
        "dd_std": float(max_dds.std()),
        "dd_median": float(np.median(max_dds)),
        "dd_p05": float(np.percentile(max_dds, 5)),
        "dd_p25": float(np.percentile(max_dds, 25)),
        "dd_p75": float(np.percentile(max_dds, 75)),
        "dd_p95": float(np.percentile(max_dds, 95)),
        "min_capital_mean": float(min_caps.mean()),
        "min_capital_p05": float(np.percentile(min_caps, 5)),
        "ruin_probability": float(np.mean(min_caps < 0.5)),  # Capital < 50%
        "profit_probability": float(np.mean(finals > 1.0)),  # Capital > 100%
        "risk_adjusted_return": float(finals.mean() / abs(max_dds.mean())) if max_dds.mean() != 0 else float(finals.mean())
    }
    
    return results

def mc_fractional_kelly_summary(trade_pnls: List[float], f_full: float, n_paths: int = 2000) -> List[Dict[str, Any]]:
    """
    Run Monte Carlo for multiple fractional Kelly levels.
    
    Args:
        trade_pnls: List of per-trade PnLs
        f_full: Full Kelly fraction
        n_paths: Number of Monte Carlo paths per fraction
        
    Returns:
        List of Monte Carlo results for each fraction
    """
    if not trade_pnls:
        logger.warning("No trade PnLs provided for Monte Carlo")
        return []
    
    pnls = np.array(trade_pnls)
    fractions = [f_full, 0.5 * f_full, 0.25 * f_full]  # Full, half, quarter Kelly
    
    results = []
    
    for f in fractions:
        logger.info(f"Running Monte Carlo for fraction {f:.3f}")
        
        try:
            result = mc_for_fraction(pnls, f, n_paths)
            results.append(result)
        except Exception as e:
            logger.error(f"Error in Monte Carlo for fraction {f:.3f}: {e}")
            continue
    
    logger.info(f"Monte Carlo completed for {len(results)} fractions")
    
    return results

def compare_mc_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compare Monte Carlo results across fractions.
    
    Args:
        results: List of Monte Carlo results
        
    Returns:
        Comparison analysis
    """
    if not results:
        return {"error": "No results to compare"}
    
    # Find best performers
    best_return = max(results, key=lambda r: r["final_capital_mean"])
    best_sharpe = max(results, key=lambda r: r["risk_adjusted_return"])
    lowest_dd = min(results, key=lambda r: r["dd_mean"])
    lowest_ruin = min(results, key=lambda r: r["ruin_probability"])
    
    # Calculate improvement metrics
    full_kelly = next((r for r in results if abs(r["fraction"] - max(r["fraction"] for r in results)) < 0.01), None)
    half_kelly = next((r for r in results if abs(r["fraction"] - (max(r["fraction"] for r in results) * 0.5)) < 0.01), None)
    quarter_kelly = next((r for r in results if abs(r["fraction"] - (max(r["fraction"] for r in results) * 0.25)) < 0.01), None)
    
    comparison = {
        "best_return": {
            "fraction": best_return["fraction"],
            "mean_final": best_return["final_capital_mean"],
            "sharpe": best_return["risk_adjusted_return"]
        },
        "best_sharpe": {
            "fraction": best_sharpe["fraction"],
            "sharpe": best_sharpe["risk_adjusted_return"],
            "mean_final": best_sharpe["final_capital_mean"]
        },
        "lowest_drawdown": {
            "fraction": lowest_dd["fraction"],
            "mean_dd": lowest_dd["dd_mean"],
            "ruin_prob": lowest_dd["ruin_probability"]
        },
        "lowest_ruin": {
            "fraction": lowest_ruin["fraction"],
            "ruin_prob": lowest_ruin["ruin_probability"],
            "mean_dd": lowest_ruin["dd_mean"]
        }
    }
    
    # Add fractional Kelly comparisons if available
    if full_kelly and half_kelly:
        comparison["half_vs_full"] = {
            "return_ratio": half_kelly["final_capital_mean"] / full_kelly["final_capital_mean"],
            "dd_improvement": (half_kelly["dd_mean"] - full_kelly["dd_mean"]) / abs(full_kelly["dd_mean"]) if full_kelly["dd_mean"] != 0 else 0,
            "ruin_reduction": full_kelly["ruin_probability"] - half_kelly["ruin_probability"]
        }
    
    if full_kelly and quarter_kelly:
        comparison["quarter_vs_full"] = {
            "return_ratio": quarter_kelly["final_capital_mean"] / full_kelly["final_capital_mean"],
            "dd_improvement": (quarter_kelly["dd_mean"] - full_kelly["dd_mean"]) / abs(full_kelly["dd_mean"]) if full_kelly["dd_mean"] != 0 else 0,
            "ruin_reduction": full_kelly["ruin_probability"] - quarter_kelly["ruin_probability"]
        }
    
    return comparison

def print_mc_summary(results: List[Dict[str, Any]], title: str = "Monte Carlo Fractional Kelly Summary"):
    """
    Print formatted Monte Carlo summary.
    
    Args:
        results: List of Monte Carlo results
        title: Summary title
    """
    if not results:
        print("No Monte Carlo results to display")
        return
    
    print(f"\n{title}")
    print("=" * 80)
    
    print(f"\nMonte Carlo Results Summary:")
    print("-" * 80)
    print(f"{'Fraction':<12} {'Final Cap':<12} {'Std':<8} {'5th':<8} {'95th':<8} {'DD Mean':<10} {'DD 95th':<10} {'Ruin':<8}")
    print("-" * 80)
    
    for result in results:
        print(f"{result['fraction']:<12.3f} {result['final_capital_mean']:<12.3f} "
              f"{result['final_capital_std']:<8.3f} {result['final_capital_p05']:<8.3f} "
              f"{result['final_capital_p95']:<8.3f} {result['dd_mean']:<10.2%} "
              f"{result['dd_p95']:<10.2%} {result['ruin_probability']:<8.2%}")
    
    # Comparison analysis
    comparison = compare_mc_results(results)
    
    print(f"\nBest Performers:")
    print(f"  Highest Return: {comparison['best_return']['fraction']:.3f} (mean: {comparison['best_return']['mean_final']:.3f})")
    print(f"  Best Sharpe: {comparison['best_sharpe']['fraction']:.3f} (sharpe: {comparison['best_sharpe']['sharpe']:.2f})")
    print(f"  Lowest Drawdown: {comparison['lowest_drawdown']['fraction']:.3f} (dd: {comparison['lowest_drawdown']['mean_dd']:.2%})")
    print(f"  Lowest Ruin: {comparison['lowest_ruin']['fraction']:.3f} (ruin: {comparison['lowest_ruin']['ruin_prob']:.2%})")
    
    # Fractional Kelly benefits
    if "half_vs_full" in comparison:
        half_vs_full = comparison["half_vs_full"]
        print(f"\nHalf Kelly vs Full Kelly:")
        print(f"  Return Retention: {half_vs_full['return_ratio']:.1%}")
        print(f"  Drawdown Improvement: {half_vs_full['dd_improvement']:.1%}")
        print(f"  Ruin Reduction: {half_vs_full['ruin_reduction']:.1%}")
    
    if "quarter_vs_full" in comparison:
        quarter_vs_full = comparison["quarter_vs_full"]
        print(f"\nQuarter Kelly vs Full Kelly:")
        print(f"  Return Retention: {quarter_vs_full['return_ratio']:.1%}")
        print(f"  Drawdown Improvement: {quarter_vs_full['dd_improvement']:.1%}")
        print(f"  Ruin Reduction: {quarter_vs_full['ruin_reduction']:.1%}")
    
    print("=" * 80)

def analyze_mc_robustness(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze robustness of Kelly fractions using Monte Carlo results.
    
    Args:
        results: List of Monte Carlo results
        
    Returns:
        Robustness analysis
    """
    if not results:
        return {"error": "No results to analyze"}
    
    robustness_scores = {}
    
    for result in results:
        # Calculate robustness score based on multiple factors
        factors = {
            "mean_return": result["final_capital_mean"],
            "return_stability": 1.0 / (1.0 + result["final_capital_std"]),  # Lower variance = higher stability
            "drawdown_control": 1.0 / (1.0 + abs(result["dd_mean"])),  # Lower drawdown = higher score
            "ruin_avoidance": 1.0 - result["ruin_probability"],  # Lower ruin probability = higher score
            "profit_probability": result["profit_probability"]
        }
        
        # Weighted score (adjust weights as needed)
        robustness_score = (
            0.3 * factors["mean_return"] +
            0.2 * factors["return_stability"] +
            0.2 * factors["drawdown_control"] +
            0.2 * factors["ruin_avoidance"] +
            0.1 * factors["profit_probability"]
        )
        
        robustness_scores[result["fraction"]] = {
            "score": robustness_score,
            "factors": factors
        }
    
    # Find most robust fraction
    most_robust = max(robustness_scores.items(), key=lambda x: x[1]["score"])
    
    return {
        "robustness_scores": robustness_scores,
        "most_robust_fraction": most_robust[0],
        "most_robust_score": most_robust[1]["score"],
        "most_robust_factors": most_robust[1]["factors"]
    }

def generate_mc_recommendations(results: List[Dict[str, Any]]) -> List[str]:
    """
    Generate recommendations based on Monte Carlo results.
    
    Args:
        results: List of Monte Carlo results
        
    Returns:
        List of recommendations
    """
    if not results:
        return ["No Monte Carlo results available for recommendations"]
    
    recommendations = []
    
    # Analyze results
    comparison = compare_mc_results(results)
    robustness = analyze_mc_robustness(results)
    
    # Risk assessment
    highest_ruin = max(results, key=lambda r: r["ruin_probability"])
    if highest_ruin["ruin_probability"] > 0.20:
        recommendations.append(f"⚠️ High ruin probability ({highest_ruin['ruin_probability']:.1%}) for {highest_ruin['fraction']:.3f} Kelly - consider fractional Kelly")
    
    # Drawdown assessment
    worst_dd = min(results, key=lambda r: r["dd_mean"])
    if worst_dd["dd_mean"] < -0.30:
        recommendations.append(f"📉 Severe drawdown ({worst_dd['dd_mean']:.1%}) for {worst_dd['fraction']:.3f} Kelly - implement stronger risk controls")
    
    # Performance assessment
    best_sharpe = comparison["best_sharpe"]
    if best_sharpe["sharpe"] < 1.0:
        recommendations.append(f"📊 Low risk-adjusted returns ({best_sharpe['sharpe']:.2f}) - consider improving strategy edge")
    
    # Robustness recommendation
    most_robust = robustness["most_robust_fraction"]
    if most_robust in [0.25 * max(r["fraction"] for r in results), 0.5 * max(r["fraction"] for r in results)]:
        recommendations.append(f"✅ Most robust fraction is {most_robust:.3f} Kelly - recommended for live trading")
    
    # General recommendations
    full_kelly = next((r for r in results if abs(r["fraction"] - max(r["fraction"] for r in results)) < 0.01), None)
    if full_kelly and full_kelly["ruin_probability"] > 0.10:
        recommendations.append("🛡️ Full Kelly shows high ruin risk - fractional Kelly (25-50%) recommended")
    
    if len(recommendations) == 0:
        recommendations.append("✅ Monte Carlo results look favorable - current Kelly fractions appear robust")
    
    return recommendations

# Example usage:
"""
import numpy as np

# Generate sample trade PnLs
np.random.seed(42)
trade_pnls = np.random.choice([0.01, -0.005, 0.015, -0.01, 0.02, -0.015], size=100)

# Calculate full Kelly (simplified)
wins = [p for p in trade_pnls if p > 0]
losses = [p for p in trade_pnls if p <= 0]
win_rate = len(wins) / len(trade_pnls)
avg_win = np.mean(wins) if wins else 0.0
avg_loss = -np.mean(losses) if losses else 0.0
win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0

from merid.strategies.kelly import KellyStats, kelly_fraction
ks = KellyStats(win_rate=win_rate, win_loss_ratio=win_loss_ratio)
f_full = kelly_fraction(ks)

# Run Monte Carlo for multiple fractions
results = mc_fractional_kelly_summary(trade_pnls.tolist(), f_full, n_paths=2000)

# Print summary
print_mc_summary(results)

# Generate recommendations
recommendations = generate_mc_recommendations(results)
print("Recommendations:")
for rec in recommendations:
    print(f"  {rec}")
"""
