"""
Risk-of-Ruin Analysis in Kelly Monte Carlo

Extend Monte Carlo to support risk-of-ruin analysis at various levels.
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Any
import logging

from .kelly_mc_stress import mc_stress_summary

logger = logging.getLogger(__name__)

def risk_of_ruin_table(
    trade_pnls: List[float],
    fractions: List[float],
    ruin_levels: List[float] = [0.75, 0.5, 0.25],
    n_paths: int = 5000,
    seed: int = None
) -> List[Dict[str, Any]]:
    """
    Generate risk-of-ruin table for multiple fractions and ruin levels.
    
    Args:
        trade_pnls: List of per-trade PnLs
        fractions: List of Kelly fractions to test
        ruin_levels: List of capital thresholds (e.g., 0.5 = 50% of start)
        n_paths: Number of Monte Carlo paths per simulation
        seed: Random seed for reproducibility
        
    Returns:
        List of dictionaries with risk-of-ruin data
    """
    if not trade_pnls:
        logger.warning("No trade PnLs provided for risk-of-ruin analysis")
        return []
    
    if not fractions:
        logger.warning("No fractions provided for risk-of-ruin analysis")
        return []
    
    table = []
    
    logger.info(f"Generating risk-of-ruin table: {len(fractions)} fractions x {len(ruin_levels)} ruin levels")
    
    for f in fractions:
        for rl in ruin_levels:
            try:
                # Run stress test with specific ruin level
                res = mc_stress_summary(trade_pnls, f, n_paths=n_paths, ruin_level=rl, seed=seed)
                
                if not res:
                    continue
                
                table.append({
                    "fraction": f,
                    "ruin_level": rl,
                    "risk_of_ruin": res["risk_of_ruin"],
                    "final_p05": res["final_p05"],
                    "dd_p95": res["dd_p95"],
                    "final_mean": res["final_mean"],
                    "final_std": res["final_std"],
                    "profit_probability": res["profit_probability"],
                    "severe_loss_probability": res["severe_loss_probability"],
                    "risk_adjusted_return": res["risk_adjusted_return"]
                })
                
            except Exception as e:
                logger.error(f"Error in risk-of-ruin analysis for f={f:.3f}, rl={rl:.2f}: {e}")
                continue
    
    logger.info(f"Risk-of-ruin table completed: {len(table)} entries")
    
    return table

def analyze_risk_of_ruin_by_fraction(ror_table: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze risk-of-ruin data by Kelly fraction.
    
    Args:
        ror_table: Risk-of-ruin table from risk_of_ruin_table
        
    Returns:
        Analysis by fraction
    """
    if not ror_table:
        return {"error": "Empty risk-of-ruin table"}
    
    # Group by fraction
    fractions = {}
    for entry in ror_table:
        f = entry["fraction"]
        if f not in fractions:
            fractions[f] = []
        fractions[f].append(entry)
    
    analysis = {}
    
    for f, entries in fractions.items():
        # Calculate metrics across all ruin levels
        max_risk = max(entry["risk_of_ruin"] for entry in entries)
        avg_risk = np.mean([entry["risk_of_ruin"] for entry in entries])
        
        # Find worst case (highest ruin level)
        worst_entry = max(entries, key=lambda x: x["risk_of_ruin"])
        best_entry = min(entries, key=lambda x: x["risk_of_ruin"])
        
        # Calculate consistency (how similar risks are across levels)
        risks = [entry["risk_of_ruin"] for entry in entries]
        risk_std = np.std(risks)
        risk_consistency = 1.0 / (1.0 + risk_std)  # Higher = more consistent
        
        analysis[f] = {
            "fraction": f,
            "max_risk_of_ruin": max_risk,
            "avg_risk_of_ruin": avg_risk,
            "risk_std": risk_std,
            "risk_consistency": risk_consistency,
            "worst_case": {
                "ruin_level": worst_entry["ruin_level"],
                "risk_of_ruin": worst_entry["risk_of_ruin"],
                "final_p05": worst_entry["final_p05"]
            },
            "best_case": {
                "ruin_level": best_entry["ruin_level"],
                "risk_of_ruin": best_entry["risk_of_ruin"],
                "final_p05": best_entry["final_p05"]
            },
            "entries": entries
        }
    
    return analysis

def analyze_risk_of_ruin_by_level(ror_table: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze risk-of-ruin data by ruin level.
    
    Args:
        ror_table: Risk-of-ruin table from risk_of_ruin_table
        
    Returns:
        Analysis by ruin level
    """
    if not ror_table:
        return {"error": "Empty risk-of-ruin table"}
    
    # Group by ruin level
    levels = {}
    for entry in ror_table:
        rl = entry["ruin_level"]
        if rl not in levels:
            levels[rl] = []
        levels[rl].append(entry)
    
    analysis = {}
    
    for rl, entries in levels.items():
        # Calculate metrics across all fractions
        max_risk = max(entry["risk_of_ruin"] for entry in entries)
        min_risk = min(entry["risk_of_ruin"] for entry in entries)
        avg_risk = np.mean([entry["risk_of_ruin"] for entry in entries])
        
        # Find safest and riskiest fractions
        safest_entry = min(entries, key=lambda x: x["risk_of_ruin"])
        riskiest_entry = max(entries, key=lambda x: x["risk_of_ruin"])
        
        analysis[rl] = {
            "ruin_level": rl,
            "max_risk_of_ruin": max_risk,
            "min_risk_of_ruin": min_risk,
            "avg_risk_of_ruin": avg_risk,
            "risk_range": max_risk - min_risk,
            "safest_fraction": safest_entry["fraction"],
            "safest_risk": safest_entry["risk_of_ruin"],
            "riskiest_fraction": riskiest_entry["fraction"],
            "riskiest_risk": riskiest_entry["risk_of_ruin"],
            "entries": entries
        }
    
    return analysis

def print_risk_of_ruin_table(ror_table: List[Dict[str, Any]], 
                            title: str = "Risk-of-Ruin Analysis"):
    """
    Print formatted risk-of-ruin table.
    
    Args:
        ror_table: Risk-of-ruin table from risk_of_ruin_table
        title: Table title
    """
    if not ror_table:
        print("No risk-of-ruin data to display")
        return
    
    print(f"\n{title}")
    print("=" * 80)
    
    # Group by fraction for display
    fractions = {}
    for entry in ror_table:
        f = entry["fraction"]
        if f not in fractions:
            fractions[f] = {}
        fractions[f][entry["ruin_level"]] = entry
    
    print(f"\nRisk-of-Ruin by Fraction and Ruin Level:")
    print("-" * 80)
    print(f"{'Fraction':<10} {'Ruin Level':<12} {'Risk of Ruin':<12} {'5th Pct':<10} {'DD 95th':<10}")
    print("-" * 80)
    
    for f in sorted(fractions.keys()):
        for rl in sorted(fractions[f].keys()):
            entry = fractions[f][rl]
            print(f"{f:<10.3f} {rl:<12.1%} {entry['risk_of_ruin']:<12.2%} "
                  f"{entry['final_p05']:<10.3f} {entry['dd_p95']:<10.2%}")
    
    # Analysis by fraction
    fraction_analysis = analyze_risk_of_ruin_by_fraction(ror_table)
    
    print(f"\nSummary by Fraction:")
    print("-" * 60)
    print(f"{'Fraction':<10} {'Max Risk':<10} {'Avg Risk':<10} {'Consistency':<12}")
    print("-" * 60)
    
    for f, analysis in fraction_analysis.items():
        print(f"{f:<10.3f} {analysis['max_risk_of_ruin']:<10.2%} "
              f"{analysis['avg_risk_of_ruin']:<10.2%} {analysis['risk_consistency']:<12.3f}")
    
    # Analysis by ruin level
    level_analysis = analyze_risk_of_ruin_by_level(ror_table)
    
    print(f"\nSummary by Ruin Level:")
    print("-" * 60)
    print(f"{'Ruin Level':<12} {'Safest F':<10} {'Riskiest F':<11} {'Risk Range':<12}")
    print("-" * 60)
    
    for rl, analysis in level_analysis.items():
        print(f"{rl:<12.1%} {analysis['safest_fraction']:<10.3f} "
              f"{analysis['riskiest_fraction']:<11.3f} {analysis['risk_range']:<12.2%}")
    
    print("=" * 80)

def find_safe_kelly_fractions(ror_table: List[Dict[str, Any]], 
                             max_risk_tolerance: float = 0.05,
                             min_profit_probability: float = 0.60) -> List[Dict[str, Any]]:
    """
    Find Kelly fractions that meet safety criteria.
    
    Args:
        ror_table: Risk-of-ruin table
        max_risk_tolerance: Maximum acceptable risk of ruin
        min_profit_probability: Minimum acceptable profit probability
        
    Returns:
        List of safe fractions with their metrics
    """
    if not ror_table:
        return []
    
    safe_fractions = []
    
    # Group by fraction
    fractions = {}
    for entry in ror_table:
        f = entry["fraction"]
        if f not in fractions:
            fractions[f] = []
        fractions[f].append(entry)
    
    for f, entries in fractions.items():
        # Check if all entries meet risk tolerance
        max_risk = max(entry["risk_of_ruin"] for entry in entries)
        avg_profit_prob = np.mean([entry["profit_probability"] for entry in entries])
        
        if max_risk <= max_risk_tolerance and avg_profit_prob >= min_profit_probability:
            # Find worst case metrics
            worst_entry = max(entries, key=lambda x: x["risk_of_ruin"])
            
            safe_fractions.append({
                "fraction": f,
                "max_risk_of_ruin": max_risk,
                "avg_profit_probability": avg_profit_prob,
                "worst_ruin_level": worst_entry["ruin_level"],
                "worst_final_p05": worst_entry["final_p05"],
                "risk_score": max_risk + (1.0 - avg_profit_prob)  # Lower is better
            })
    
    # Sort by risk score (lowest first)
    safe_fractions.sort(key=lambda x: x["risk_score"])
    
    return safe_fractions

def generate_risk_of_ruin_recommendations(ror_table: List[Dict[str, Any]]) -> List[str]:
    """
    Generate recommendations based on risk-of-ruin analysis.
    
    Args:
        ror_table: Risk-of-ruin table
        
    Returns:
        List of recommendations
    """
    if not ror_table:
        return ["No risk-of-ruin data available for recommendations"]
    
    recommendations = []
    
    # Find safe fractions
    safe_fractions = find_safe_kelly_fractions(ror_table, max_risk_tolerance=0.05)
    
    # Analyze overall risk levels
    fraction_analysis = analyze_risk_of_ruin_by_fraction(ror_table)
    level_analysis = analyze_risk_of_ruin_by_level(ror_table)
    
    # Overall risk assessment
    max_risk_all = max(entry["risk_of_ruin"] for entry in ror_table)
    avg_risk_all = np.mean([entry["risk_of_ruin"] for entry in ror_table])
    
    if max_risk_all > 0.30:
        recommendations.append("⚠️ Very high risk of ruin detected - use fractional Kelly (25% or less)")
    elif max_risk_all > 0.15:
        recommendations.append("📊 High risk of ruin detected - consider half Kelly or less")
    elif max_risk_all > 0.10:
        recommendations.append("📈 Moderate risk of ruin - fractional Kelly recommended")
    else:
        recommendations.append("✅ Low risk of ruin across all fractions")
    
    # Safe fractions recommendations
    if safe_fractions:
        best_safe = safe_fractions[0]
        recommendations.append(f"🛡️ Safest fraction: {best_safe['fraction']:.3f} "
                           f"(max risk: {best_safe['max_risk_of_ruin']:.1%})")
        
        if len(safe_fractions) > 1:
            recommendations.append(f"📊 Multiple safe options available "
                               f"({len(safe_fractions)} fractions meet criteria)")
    else:
        recommendations.append("⚠️ No fractions meet safety criteria - consider reducing position size")
    
    # Consistency recommendations
    consistent_fractions = [f for f, analysis in fraction_analysis.items() 
                          if analysis["risk_consistency"] > 0.8]
    
    if consistent_fractions:
        recommendations.append(f"✅ Consistent risk profiles: {len(consistent_fractions)} fractions")
    else:
        recommendations.append("⚠️ Inconsistent risk profiles - monitor volatility closely")
    
    # Ruin level analysis
    high_risk_levels = [rl for rl, analysis in level_analysis.items() 
                       if analysis["avg_risk_of_ruin"] > 0.20]
    
    if high_risk_levels:
        recommendations.append(f"📉 High risk at ruin levels: {high_risk_levels}")
    
    # General recommendations
    recommendations.append("💡 Use risk-of-ruin analysis to set maximum position sizes")
    recommendations.append("🔄 Re-run analysis periodically with updated trade data")
    recommendations.append("⚖️ Combine risk-of-ruin limits with drawdown controls")
    recommendations.append("📊 Consider using quarter Kelly for maximum safety")
    
    return recommendations

# Example usage for Kelly validation:
"""
import numpy as np

# Generate sample trade PnLs
np.random.seed(42)
trade_pnls = np.random.choice([0.015, -0.008, 0.020, -0.012, 0.025, -0.018], size=100)

# Test different Kelly fractions
fractions = [0.125, 0.25, 0.5, 1.0]  # Eighth, quarter, half, full Kelly

# Test different ruin levels
ruin_levels = [0.8, 0.6, 0.4, 0.2]  # 80%, 60%, 40%, 20% capital levels

# Generate risk-of-ruin table
ror_table = risk_of_ruin_table(trade_pnls.tolist(), fractions, ruin_levels, n_paths=2000)

# Print table
print_risk_of_ruin_table(ror_table)

# Find safe fractions
safe_fractions = find_safe_kelly_fractions(ror_table, max_risk_tolerance=0.05)
print(f"\nSafe fractions: {len(safe_fractions)}")
for safe in safe_fractions:
    print(f"  {safe['fraction']:.3f}: risk={safe['max_risk_of_ruin']:.1%}, score={safe['risk_score']:.3f}")

# Generate recommendations
recommendations = generate_risk_of_ruin_recommendations(ror_table)
print("\nRecommendations:")
for rec in recommendations:
    print(f"  {rec}")
"""
