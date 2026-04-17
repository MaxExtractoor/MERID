"""
Kelly Monte Carlo Simulation - Robustness Testing

Monte Carlo simulation for Kelly strategy robustness assessment.
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List
import logging

from .kelly_compare import equity_with_kelly, max_drawdown

logger = logging.getLogger(__name__)

def kelly_monte_carlo(
    trade_pnls: List[float],
    kelly_fraction_used: float,
    n_paths: int = 1000,
    seed: int = None
) -> Dict[str, Any]:
    """
    Monte Carlo shuffle of trades to assess distribution of outcomes.
    
    Args:
        trade_pnls: List of per-trade PnLs
        kelly_fraction_used: Kelly fraction to apply
        n_paths: Number of Monte Carlo paths
        seed: Random seed for reproducibility
        
    Returns:
        Dictionary with Monte Carlo results
    """
    if not trade_pnls:
        logger.warning("No trade PnLs provided for Monte Carlo")
        return {"final_capital": [], "max_drawdowns": [], "error": "No trade PnLs"}
    
    # Set seed for reproducibility
    if seed is not None:
        np.random.seed(seed)
    
    pnls = np.array(trade_pnls)
    final_caps = []
    max_dds = []
    
    logger.info(f"Running Monte Carlo simulation: {n_paths} paths, {len(pnls)} trades")
    
    for i in range(n_paths):
        # Shuffle trade order
        perm = np.random.permutation(pnls)
        
        # Generate equity curve
        eq = equity_with_kelly(perm.tolist(), kelly_fraction_used)
        
        # Calculate metrics
        final_caps.append(eq.iloc[-1])
        max_dds.append(max_drawdown(eq))
        
        # Progress logging
        if (i + 1) % 100 == 0:
            logger.debug(f"Completed {i + 1}/{n_paths} paths")
    
    # Convert to arrays
    final_caps = np.array(final_caps)
    max_dds = np.array(max_dds)
    
    # Calculate statistics
    results = {
        "final_capital": final_caps,
        "max_drawdowns": max_dds,
        "final_capital_mean": float(np.mean(final_caps)),
        "final_capital_std": float(np.std(final_caps)),
        "final_capital_median": float(np.median(final_caps)),
        "final_capital_p05": float(np.percentile(final_caps, 5)),
        "final_capital_p25": float(np.percentile(final_caps, 25)),
        "final_capital_p75": float(np.percentile(final_caps, 75)),
        "final_capital_p95": float(np.percentile(final_caps, 95)),
        "dd_mean": float(np.mean(max_dds)),
        "dd_std": float(np.std(max_dds)),
        "dd_median": float(np.median(max_dds)),
        "dd_p05": float(np.percentile(max_dds, 5)),
        "dd_p25": float(np.percentile(max_dds, 25)),
        "dd_p75": float(np.percentile(max_dds, 75)),
        "dd_p95": float(np.percentile(max_dds, 95)),
        "probability_profit": float(np.mean(final_caps > 1.0)),
        "probability_loss": float(np.mean(final_caps < 1.0)),
        "probability_large_loss": float(np.mean(final_caps < 0.8)),  # >20% loss
        "probability_ruin": float(np.mean(final_caps < 0.5)),  # >50% loss
        "n_paths": n_paths,
        "kelly_fraction": kelly_fraction_used,
        "n_trades": len(trade_pnls)
    }
    
    logger.info(f"Monte Carlo completed: mean final capital={results['final_capital_mean']:.3f}, "
                f"mean max DD={results['dd_mean']:.2%}")
    
    return results

def compare_kelly_fractions_monte_carlo(
    trade_pnls: List[float],
    kelly_fractions: List[float],
    n_paths: int = 1000,
    seed: int = None
) -> Dict[str, Any]:
    """
    Compare multiple Kelly fractions using Monte Carlo.
    
    Args:
        trade_pnls: List of per-trade PnLs
        kelly_fractions: List of Kelly fractions to test
        n_paths: Number of Monte Carlo paths per fraction
        seed: Random seed for reproducibility
        
    Returns:
        Dictionary with comparison results
    """
    if not trade_pnls:
        return {"error": "No trade PnLs provided"}
    
    if not kelly_fractions:
        return {"error": "No Kelly fractions provided"}
    
    results = {}
    
    for kelly_fraction in kelly_fractions:
        logger.info(f"Monte Carlo for Kelly fraction: {kelly_fraction:.3f}")
        
        mc_results = kelly_monte_carlo(
            trade_pnls, kelly_fraction, n_paths, seed
        )
        
        results[kelly_fraction] = mc_results
    
    # Find best performer
    best_fraction = None
    best_score = -np.inf
    
    for kelly_fraction, mc_results in results.items():
        # Score based on mean final capital and drawdown penalty
        score = mc_results["final_capital_mean"] - abs(mc_results["dd_mean"]) * 2
        
        if score > best_score:
            best_score = score
            best_fraction = kelly_fraction
    
    return {
        "results": results,
        "best_fraction": best_fraction,
        "best_score": best_score,
        "comparison_summary": _generate_monte_carlo_summary(results)
    }

def _generate_monte_carlo_summary(results: Dict[float, Dict]) -> Dict[str, Any]:
    """Generate summary of Monte Carlo comparison."""
    summary = {
        "fractions_tested": list(results.keys()),
        "risk_adjusted_scores": {},
        "profit_probabilities": {},
        "ruin_probabilities": {},
        "drawdown_risks": {}
    }
    
    for kelly_fraction, mc_results in results.items():
        # Risk-adjusted score
        risk_adj_score = mc_results["final_capital_mean"] - abs(mc_results["dd_mean"]) * 2
        summary["risk_adjusted_scores"][kelly_fraction] = risk_adj_score
        
        # Probability metrics
        summary["profit_probabilities"][kelly_fraction] = mc_results["probability_profit"]
        summary["ruin_probabilities"][kelly_fraction] = mc_results["probability_ruin"]
        
        # Drawdown risk
        summary["drawdown_risks"][kelly_fraction] = {
            "mean": mc_results["dd_mean"],
            "p95": mc_results["dd_p95"],
            "severe_dd_prob": mc_results["probability_large_loss"]
        }
    
    return summary

def analyze_monte_carlo_results(mc_results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze Monte Carlo results and provide insights.
    
    Args:
        mc_results: Monte Carlo results dictionary
        
    Returns:
        Analysis insights
    """
    if "error" in mc_results:
        return {"error": mc_results["error"]}
    
    # Risk assessment
    risk_assessment = {
        "low_risk": mc_results["probability_ruin"] < 0.01 and mc_results["dd_p95"] > -0.20,
        "moderate_risk": 0.01 <= mc_results["probability_ruin"] < 0.05 and -0.30 <= mc_results["dd_p95"] <= -0.20,
        "high_risk": mc_results["probability_ruin"] >= 0.05 or mc_results["dd_p95"] < -0.30
    }
    
    # Performance assessment
    performance_assessment = {
        "excellent": mc_results["final_capital_mean"] > 2.0 and mc_results["probability_profit"] > 0.8,
        "good": 1.2 <= mc_results["final_capital_mean"] <= 2.0 and 0.6 <= mc_results["probability_profit"] <= 0.8,
        "poor": mc_results["final_capital_mean"] < 1.2 or mc_results["probability_profit"] < 0.6
    }
    
    # Recommendations
    recommendations = []
    
    if risk_assessment["high_risk"]:
        recommendations.append("Consider reducing Kelly fraction due to high risk of ruin")
    
    if performance_assessment["poor"]:
        recommendations.append("Strategy performance may be insufficient - consider improving edge")
    
    if mc_results["probability_large_loss"] > 0.2:
        recommendations.append("High probability of large losses - implement stronger risk controls")
    
    if mc_results["final_capital_std"] / mc_results["final_capital_mean"] > 0.5:
        recommendations.append("High variance in outcomes - consider more conservative approach")
    
    return {
        "risk_assessment": risk_assessment,
        "performance_assessment": performance_assessment,
        "recommendations": recommendations,
        "key_metrics": {
            "expected_return": mc_results["final_capital_mean"],
            "volatility": mc_results["final_capital_std"],
            "downside_risk": mc_results["dd_p95"],
            "ruin_probability": mc_results["probability_ruin"]
        }
    }

def print_monte_carlo_summary(mc_results: Dict[str, Any], title: str = "Monte Carlo Results"):
    """
    Print formatted Monte Carlo summary.
    
    Args:
        mc_results: Monte Carlo results
        title: Summary title
    """
    if "error" in mc_results:
        print(f"Error: {mc_results['error']}")
        return
    
    print(f"\n{title}")
    print("=" * 60)
    
    print(f"\nConfiguration:")
    print(f"  Kelly Fraction: {mc_results['kelly_fraction']:.3f}")
    print(f"  Number of Trades: {mc_results['n_trades']}")
    print(f"  Monte Carlo Paths: {mc_results['n_paths']}")
    
    print(f"\nFinal Capital Distribution:")
    print(f"  Mean: {mc_results['final_capital_mean']:.3f}")
    print(f"  Std:  {mc_results['final_capital_std']:.3f}")
    print(f"  Median: {mc_results['final_capital_median']:.3f}")
    print(f"  5th percentile: {mc_results['final_capital_p05']:.3f}")
    print(f"  95th percentile: {mc_results['final_capital_p95']:.3f}")
    
    print(f"\nDrawdown Distribution:")
    print(f"  Mean: {mc_results['dd_mean']:.2%}")
    print(f"  Median: {mc_results['dd_median']:.2%}")
    print(f"  5th percentile: {mc_results['dd_p05']:.2%}")
    print(f"  95th percentile: {mc_results['dd_p95']:.2%}")
    
    print(f"\nRisk Metrics:")
    print(f"  Probability of Profit: {mc_results['probability_profit']:.1%}")
    print(f"  Probability of Loss: {mc_results['probability_loss']:.1%}")
    print(f"  Probability of >20% Loss: {mc_results['probability_large_loss']:.1%}")
    print(f"  Probability of Ruin (>50% Loss): {mc_results['probability_ruin']:.1%}")
    
    # Analysis
    analysis = analyze_monte_carlo_results(mc_results)
    
    print(f"\nRisk Assessment: {list(analysis['risk_assessment'].keys())[0] if any(analysis['risk_assessment'].values()) else 'Unknown'}")
    print(f"Performance Assessment: {list(analysis['performance_assessment'].keys())[0] if any(analysis['performance_assessment'].values()) else 'Unknown'}")
    
    if analysis['recommendations']:
        print(f"\nRecommendations:")
        for rec in analysis['recommendations']:
            print(f"  - {rec}")
    
    print("=" * 60)

def monte_carlo_stress_test(trade_pnls: List[float], 
                           kelly_fraction: float,
                           stress_scenarios: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Stress test Kelly strategy with different scenarios.
    
    Args:
        trade_pnls: List of per-trade PnLs
        kelly_fraction: Kelly fraction to test
        stress_scenarios: Dictionary of stress scenarios
        
    Returns:
        Stress test results
    """
    if stress_scenarios is None:
        stress_scenarios = {
            "worst_case": {"pnl_multiplier": 0.5},  # Halve all PnLs
            "high_volatility": {"vol_multiplier": 1.5},  # Increase volatility
            "correlated_losses": {"loss_correlation": 0.3},  # Correlated losses
            "extended_drawdown": {"dd_multiplier": 1.5}  # Longer drawdowns
        }
    
    results = {}
    
    for scenario_name, scenario_params in stress_scenarios.items():
        logger.info(f"Stress test: {scenario_name}")
        
        # Apply stress scenario
        stressed_pnls = _apply_stress_scenario(trade_pnls, scenario_params)
        
        # Run Monte Carlo
        mc_results = kelly_monte_carlo(stressed_pnls, kelly_fraction, n_paths=500)
        
        results[scenario_name] = {
            "scenario_params": scenario_params,
            "monte_carlo_results": mc_results
        }
    
    return results

def _apply_stress_scenario(trade_pnls: List[float], scenario_params: Dict[str, Any]) -> List[float]:
    """Apply stress scenario to trade PnLs."""
    stressed_pnls = trade_pnls.copy()
    
    # PnL multiplier
    if "pnl_multiplier" in scenario_params:
        stressed_pnls = [p * scenario_params["pnl_multiplier"] for p in stressed_pnls]
    
    # Volatility multiplier
    if "vol_multiplier" in scenario_params:
        vol_mult = scenario_params["vol_multiplier"]
        stressed_pnls = [p * vol_mult for p in stressed_pnls]
    
    # Loss correlation (make losses more likely to cluster)
    if "loss_correlation" in scenario_params:
        corr = scenario_params["loss_correlation"]
        # Simple implementation: make consecutive losses more likely
        for i in range(1, len(stressed_pnls)):
            if stressed_pnls[i-1] < 0 and np.random.random() < corr:
                stressed_pnls[i] *= -1  # Ensure loss
    
    return stressed_pnls

# Example usage:
"""
import numpy as np

# Generate sample trade PnLs
np.random.seed(42)
trade_pnls = np.random.choice([100, -50, 75, -25, 150, -75], size=100)

# Run Monte Carlo
mc_results = kelly_monte_carlo(trade_pnls.tolist(), kelly_fraction_used=0.3, n_paths=1000)

# Print summary
print_monte_carlo_summary(mc_results)

# Compare multiple Kelly fractions
fractions = [0.25, 0.5, 0.75, 1.0]
comparison = compare_kelly_fractions_monte_carlo(trade_pnls.tolist(), fractions)
print(f"Best Kelly fraction: {comparison['best_fraction']:.3f}")

# Stress test
stress_results = monte_carlo_stress_test(trade_pnls.tolist(), 0.3)
print(f"Stress test scenarios: {list(stress_results.keys())}")
"""
