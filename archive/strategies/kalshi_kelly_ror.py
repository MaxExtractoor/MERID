"""
Risk of Ruin Monte Carlo for Half Kelly on Kalshi

Monte Carlo risk-of-ruin calculation for half Kelly sizing on Kalshi trades.
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

def risk_of_ruin_half_kelly(trade_pnls: List[float], 
                           f_full: float,
                           ruin_level: float = 0.5,
                           n_paths: int = 5000,
                           seed: Optional[int] = None) -> float:
    """
    Calculate risk of ruin for half Kelly sizing using Monte Carlo simulation.
    
    Args:
        trade_pnls: List of per-trade PnLs (normalized returns)
        f_full: Full Kelly fraction
        ruin_level: Capital threshold for ruin (0.5 = 50% of starting capital)
        n_paths: Number of Monte Carlo paths to simulate
        seed: Random seed for reproducibility
        
    Returns:
        Risk of ruin probability (0.0 to 1.0)
    """
    if not trade_pnls:
        logger.warning("No trade PnLs provided for risk of ruin calculation")
        return 0.0
    
    if seed is not None:
        np.random.seed(seed)
    
    f_half = 0.5 * f_full
    pnls = np.array(trade_pnls)
    
    if len(pnls) == 0:
        return 0.0
    
    ruin_hits = 0
    
    logger.info(f"Running risk of ruin simulation: f_half={f_half:.3f}, n_paths={n_paths}")
    
    for i in range(n_paths):
        # Random permutation of trades (Monte Carlo path)
        perm = np.random.permutation(pnls)
        
        # Generate equity curve using Kelly equity function
        try:
            from .quarter_half_kelly import kelly_equity
            eq = kelly_equity(perm.tolist(), f_half)
        except ImportError:
            # Fallback equity calculation if kelly_equity not available
            eq = np.cumprod(1 + f_half * perm)
        
        # Check for ruin
        if eq.min() <= ruin_level:
            ruin_hits += 1
        
        # Progress logging
        if (i + 1) % 1000 == 0:
            logger.debug(f"Completed {i + 1}/{n_paths} risk of ruin paths")
    
    risk_of_ruin = ruin_hits / n_paths
    
    logger.info(f"Risk of ruin completed: {ruin_hits}/{n_paths} paths hit ruin ({risk_of_ruin:.2%})")
    
    return risk_of_ruin

def risk_of_ruin_table(trade_pnls: List[float],
                       f_full: float,
                       ruin_levels: List[float] = None,
                       fractions: List[float] = None,
                       n_paths: int = 5000) -> List[Dict[str, Any]]:
    """
    Generate risk of ruin table for multiple fractions and ruin levels.
    
    Args:
        trade_pnls: List of per-trade PnLs
        f_full: Full Kelly fraction
        ruin_levels: List of ruin thresholds (e.g., [0.75, 0.5, 0.25])
        fractions: List of fractions to test (e.g., [0.25, 0.5, 0.75, 1.0])
        n_paths: Number of Monte Carlo paths per simulation
        
    Returns:
        List of risk of ruin results
    """
    if not trade_pnls:
        return []
    
    if ruin_levels is None:
        ruin_levels = [0.8, 0.6, 0.4, 0.2]
    
    if fractions is None:
        fractions = [0.125, 0.25, 0.5, 0.75, 1.0]  # Eighth, quarter, half, three-quarters, full
    
    results = []
    
    for fraction in fractions:
        for ruin_level in ruin_levels:
            try:
                risk = risk_of_ruin_half_kelly(
                    trade_pnls, 
                    f_full * fraction, 
                    ruin_level, 
                    n_paths
                )
                
                results.append({
                    "fraction": fraction,
                    "ruin_level": ruin_level,
                    "risk_of_ruin": risk,
                    "kelly_fraction": f_full * fraction
                })
                
            except Exception as e:
                logger.error(f"Error in risk calculation for f={fraction:.3f}, rl={ruin_level:.2f}: {e}")
                continue
    
    return results

def calculate_optimal_fraction(trade_pnls: List[float],
                              f_full: float,
                              max_risk_tolerance: float = 0.05,
                              ruin_levels: List[float] = None) -> Dict[str, Any]:
    """
    Find optimal Kelly fraction based on risk tolerance.
    
    Args:
        trade_pnls: List of per-trade PnLs
        f_full: Full Kelly fraction
        max_risk_tolerance: Maximum acceptable risk of ruin
        ruin_levels: List of ruin levels to consider
        
    Returns:
        Optimal fraction analysis
    """
    if not trade_pnls:
        return {"error": "No trade PnLs provided"}
    
    if ruin_levels is None:
        ruin_levels = [0.5]  # Default to 50% ruin level
    
    # Test different fractions
    fractions = np.linspace(0.1, 1.0, 19)  # 10% to 100% in 5% increments
    
    safe_fractions = []
    
    for fraction in fractions:
        max_risk = 0.0
        
        for ruin_level in ruin_levels:
            risk = risk_of_ruin_half_kelly(trade_pnls, f_full * fraction, ruin_level, n_paths=1000)
            max_risk = max(max_risk, risk)
        
        if max_risk <= max_risk_tolerance:
            safe_fractions.append({
                "fraction": fraction,
                "max_risk": max_risk,
                "kelly_fraction": f_full * fraction
            })
    
    if not safe_fractions:
        # No fractions meet risk tolerance
        best_option = min(fractions, key=lambda f: max(
            risk_of_ruin_half_kelly(trade_pnls, f_full * f, rl, n_paths=1000) 
            for rl in ruin_levels
        ))
        
        return {
            "optimal_fraction": best_option,
            "kelly_fraction": f_full * best_option,
            "max_risk": max(
                risk_of_ruin_half_kelly(trade_pnls, f_full * best_option, rl, n_paths=1000) 
                for rl in ruin_levels
            ),
            "meets_tolerance": False,
            "safe_options": []
        }
    
    # Choose highest fraction that meets tolerance
    optimal = max(safe_fractions, key=lambda x: x["fraction"])
    
    return {
        "optimal_fraction": optimal["fraction"],
        "kelly_fraction": optimal["kelly_fraction"],
        "max_risk": optimal["max_risk"],
        "meets_tolerance": True,
        "safe_options": safe_fractions
    }

def analyze_kelly_risk_profile(trade_pnls: List[float],
                              f_full: float,
                              n_paths: int = 5000) -> Dict[str, Any]:
    """
    Comprehensive Kelly risk profile analysis.
    
    Args:
        trade_pnls: List of per-trade PnLs
        f_full: Full Kelly fraction
        n_paths: Number of Monte Carlo paths
        
    Returns:
        Risk profile analysis
    """
    if not trade_pnls:
        return {"error": "No trade PnLs provided"}
    
    # Calculate basic statistics
    pnls = np.array(trade_pnls)
    win_rate = (pnls > 0).mean()
    avg_win = pnls[pnls > 0].mean() if (pnls > 0).any() else 0.0
    avg_loss = -pnls[pnls < 0].mean() if (pnls < 0).any() else 0.0
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
    
    # Risk of ruin for different fractions
    fractions = [0.125, 0.25, 0.5, 0.75, 1.0]
    ruin_levels = [0.8, 0.6, 0.4, 0.2]
    
    risk_table = risk_of_ruin_table(trade_pnls, f_full, ruin_levels, fractions, n_paths)
    
    # Find optimal fraction
    optimal = calculate_optimal_fraction(trade_pnls, f_full, max_risk_tolerance=0.05)
    
    # Risk assessment
    half_kelly_risk = risk_of_ruin_half_kelly(trade_pnls, f_full * 0.5, 0.5, n_paths)
    quarter_kelly_risk = risk_of_ruin_half_kelly(trade_pnls, f_full * 0.25, 0.5, n_paths)
    
    return {
        "trade_statistics": {
            "total_trades": len(trade_pnls),
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "win_loss_ratio": win_loss_ratio,
            "full_kelly": f_full
        },
        "risk_table": risk_table,
        "optimal_fraction": optimal,
        "key_risks": {
            "half_kelly_risk": half_kelly_risk,
            "quarter_kelly_risk": quarter_kelly_risk,
            "full_kelly_risk": risk_of_ruin_half_kelly(trade_pnls, f_full, 0.5, n_paths)
        },
        "recommendations": generate_risk_recommendations(optimal, half_kelly_risk, quarter_kelly_risk)
    }

def generate_risk_recommendations(optimal: Dict[str, Any],
                                  half_kelly_risk: float,
                                  quarter_kelly_risk: float) -> List[str]:
    """
    Generate risk management recommendations based on analysis.
    
    Args:
        optimal: Optimal fraction analysis
        half_kelly_risk: Risk of ruin for half Kelly
        quarter_kelly_risk: Risk of ruin for quarter Kelly
        
    Returns:
        List of recommendations
    """
    recommendations = []
    
    # Optimal fraction recommendation
    if optimal.get("meets_tolerance", False):
        recommendations.append(f"✅ Optimal fraction: {optimal['optimal_fraction']:.1%} of Kelly "
                           f"({optimal['kelly_fraction']:.3f}) meets risk tolerance")
    else:
        recommendations.append(f"⚠️ No fraction meets 5% risk tolerance - best option: {optimal['optimal_fraction']:.1%} of Kelly")
    
    # Risk level assessment
    if quarter_kelly_risk < 0.01:
        recommendations.append("✅ Quarter Kelly has very low risk of ruin - safe for conservative trading")
    elif quarter_kelly_risk < 0.05:
        recommendations.append("📊 Quarter Kelly has acceptable risk of ruin - good for risk management")
    else:
        recommendations.append("⚠️ Even quarter Kelly has high risk of ruin - improve strategy or reduce exposure")
    
    # Half Kelly assessment
    if half_kelly_risk < 0.05:
        recommendations.append("✅ Half Kelly maintains acceptable risk levels")
    elif half_kelly_risk < 0.10:
        recommendations.append("📊 Half Kelly has moderate risk - monitor closely")
    else:
        recommendations.append("⚠️ Half Kelly has high risk of ruin - consider quarter Kelly")
    
    # General recommendations
    recommendations.append("💡 Always use fractional Kelly (25-50%) for better risk management")
    recommendations.append("🔄 Re-run risk analysis periodically with updated trade data")
    recommendations.append("📊 Consider combining Kelly sizing with other risk controls like drawdown limits")
    
    return recommendations

def print_risk_analysis(analysis: Dict[str, Any]):
    """
    Print formatted risk analysis results.
    
    Args:
        analysis: Risk analysis results
    """
    if "error" in analysis:
        print(f"Error: {analysis['error']}")
        return
    
    print("\n" + "="*80)
    print("KELLY RISK OF RUIN ANALYSIS")
    print("="*80)
    
    # Trade statistics
    stats = analysis["trade_statistics"]
    print(f"\nTrade Statistics:")
    print("-" * 40)
    print(f"  Total Trades: {stats['total_trades']}")
    print(f"  Win Rate: {stats['win_rate']:.1%}")
    print(f"  Average Win: {stats['avg_win']:.3f}")
    print(f"  Average Loss: {stats['avg_loss']:.3f}")
    print(f"  Win/Loss Ratio: {stats['win_loss_ratio']:.2f}")
    print(f"  Full Kelly: {stats['full_kelly']:.3f}")
    
    # Key risks
    risks = analysis["key_risks"]
    print(f"\nKey Risk Metrics (50% ruin level):")
    print("-" * 50)
    print(f"  Quarter Kelly Risk: {risks['quarter_kelly_risk']:.2%}")
    print(f"  Half Kelly Risk: {risks['half_kelly_risk']:.2%}")
    print(f"  Full Kelly Risk: {risks['full_kelly_risk']:.2%}")
    
    # Optimal fraction
    optimal = analysis["optimal_fraction"]
    print(f"\nOptimal Fraction Analysis:")
    print("-" * 50)
    print(f"  Optimal Fraction: {optimal['optimal_fraction']:.1%} of Kelly")
    print(f"  Kelly Fraction: {optimal['kelly_fraction']:.3f}")
    print(f"  Max Risk: {optimal['max_risk']:.2%}")
    print(f"  Meets 5% Tolerance: {'Yes' if optimal['meets_tolerance'] else 'No'}")
    
    # Recommendations
    print(f"\nRecommendations:")
    print("-" * 50)
    for rec in analysis["recommendations"]:
        print(f"  {rec}")
    
    print("="*80)

# Example usage:
"""
import numpy as np

# Generate sample trade PnLs from Kalshi strategy
np.random.seed(42)
trade_pnls = np.random.choice([0.015, -0.008, 0.020, -0.012, 0.025, -0.018], size=100).tolist()

# Full Kelly fraction (calculated from strategy)
full_kelly = 0.15

# Calculate risk of ruin for half Kelly
half_kelly_risk = risk_of_ruin_half_kelly(trade_pnls, full_kelly, ruin_level=0.5, n_paths=2000)
print(f"Half Kelly risk of ruin: {half_kelly_risk:.2%}")

# Generate risk table
risk_table = risk_of_ruin_table(trade_pnls, full_kelly, ruin_levels=[0.8, 0.6, 0.4, 0.2])
print(f"Risk table: {len(risk_table)} entries")

# Comprehensive analysis
analysis = analyze_kelly_risk_profile(trade_pnls, full_kelly)
print_risk_analysis(analysis)

# Find optimal fraction
optimal = calculate_optimal_fraction(trade_pnls, full_kelly, max_risk_tolerance=0.05)
print(f"Optimal fraction: {optimal['optimal_fraction']:.1%} of Kelly")
"""
