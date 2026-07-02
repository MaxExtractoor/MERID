"""
Monte Carlo Risk of Ruin for Kelly

Estimate probability of hitting ruin threshold across many random trade sequences.
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Any
import logging

from .quarter_half_kelly import kelly_equity

logger = logging.getLogger(__name__)

def risk_of_ruin_monte_carlo(
    trade_pnls: List[float],
    kelly_fraction_used: float,
    ruin_level: float = 0.5,  # ruin when capital < 50% of start
    n_paths: int = 5000,
    seed: int = None
) -> float:
    """
    Estimate probability of hitting ruin level using Monte Carlo simulation.
    
    Args:
        trade_pnls: List of per-trade PnLs
        kelly_fraction_used: Kelly fraction to apply
        ruin_level: Capital level that constitutes ruin (fraction of starting capital)
        n_paths: Number of Monte Carlo paths to simulate
        seed: Random seed for reproducibility
        
    Returns:
        Estimated probability of ruin (0.0 to 1.0)
    """
    if not trade_pnls:
        logger.warning("No trade PnLs provided for ruin simulation")
        return 0.0
    
    if ruin_level <= 0 or ruin_level >= 1.0:
        logger.warning(f"Invalid ruin level: {ruin_level}")
        return 0.0
    
    # Set seed for reproducibility
    if seed is not None:
        np.random.seed(seed)
    
    pnls = np.array(trade_pnls)
    ruin_count = 0
    
    logger.info(f"Running ruin simulation: {n_paths} paths, ruin_level={ruin_level:.1%}")
    
    for i in range(n_paths):
        # Random permutation of trades
        perm = np.random.permutation(pnls)
        
        # Generate equity curve
        eq = kelly_equity(perm.tolist(), kelly_fraction_used)
        
        # Check if ruin level was hit at any point
        min_cap = eq.min()
        if min_cap <= ruin_level:
            ruin_count += 1
        
        # Progress logging
        if (i + 1) % 1000 == 0:
            logger.debug(f"Completed {i + 1}/{n_paths} ruin paths")
    
    ruin_probability = ruin_count / n_paths
    
    logger.info(f"Ruin simulation completed: {ruin_count}/{n_paths} paths hit ruin ({ruin_probability:.2%})")
    
    return ruin_probability

def compare_ruin_across_fractions(
    trade_pnls: List[float],
    kelly_fractions: List[float],
    ruin_level: float = 0.5,
    n_paths: int = 5000
) -> Dict[str, float]:
    """
    Compare risk of ruin across different Kelly fractions.
    
    Args:
        trade_pnls: List of per-trade PnLs
        kelly_fractions: List of Kelly fractions to test
        ruin_level: Capital level that constitutes ruin
        n_paths: Number of Monte Carlo paths per fraction
        
    Returns:
        Dictionary mapping fraction labels to ruin probabilities
    """
    if not trade_pnls:
        return {"error": "No trade PnLs provided"}
    
    results = {}
    
    for fraction in kelly_fractions:
        logger.info(f"Calculating ruin probability for Kelly fraction: {fraction:.3f}")
        
        ruin_prob = risk_of_ruin_monte_carlo(
            trade_pnls, fraction, ruin_level, n_paths
        )
        
        label = f"{fraction:.3f}"
        results[label] = ruin_prob
    
    return results

def detailed_ruin_analysis(
    trade_pnls: List[float],
    kelly_fraction_used: float,
    ruin_levels: List[float] = None,
    n_paths: int = 5000
) -> Dict[str, Any]:
    """
    Perform detailed ruin analysis across multiple ruin levels.
    
    Args:
        trade_pnls: List of per-trade PnLs
        kelly_fraction_used: Kelly fraction to test
        ruin_levels: List of ruin levels to test
        n_paths: Number of Monte Carlo paths
        
    Returns:
        Detailed ruin analysis
    """
    if ruin_levels is None:
        ruin_levels = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]  # 20% to 80% ruin levels
    
    results = {}
    
    for ruin_level in ruin_levels:
        ruin_prob = risk_of_ruin_monte_carlo(
            trade_pnls, kelly_fraction_used, ruin_level, n_paths
        )
        
        results[f"ruin_{ruin_level:.1f}"] = {
            "ruin_level": ruin_level,
            "ruin_probability": ruin_prob,
            "survival_probability": 1.0 - ruin_prob
        }
    
    # Calculate summary statistics
    ruin_probabilities = [result["ruin_probability"] for result in results.values()]
    
    summary = {
        "kelly_fraction": kelly_fraction_used,
        "n_paths": n_paths,
        "ruin_levels_tested": ruin_levels,
        "avg_ruin_probability": np.mean(ruin_probabilities),
        "worst_ruin_probability": max(ruin_probabilities),
        "best_ruin_probability": min(ruin_probabilities),
        "detailed_results": results
    }
    
    return summary

def simulate_equity_paths(
    trade_pnls: List[float],
    kelly_fraction_used: float,
    n_paths: int = 100,
    max_paths_to_store: int = 10
) -> Dict[str, Any]:
    """
    Simulate equity paths for visualization and analysis.
    
    Args:
        trade_pnls: List of per-trade PnLs
        kelly_fraction_used: Kelly fraction to apply
        n_paths: Number of paths to simulate
        max_paths_to_store: Maximum number of paths to store in memory
        
    Returns:
        Simulation results with sample paths
    """
    if not trade_pnls:
        return {"error": "No trade PnLs provided"}
    
    pnls = np.array(trade_pnls)
    paths = []
    final_capitals = []
    min_capitals = []
    max_drawdowns = []
    
    for i in range(n_paths):
        # Random permutation
        perm = np.random.permutation(pnls)
        
        # Generate equity curve
        eq = kelly_equity(perm.tolist(), kelly_fraction_used)
        
        # Calculate metrics
        final_capital = eq.iloc[-1]
        min_capital = eq.min()
        
        # Calculate max drawdown
        peak = eq.cummax()
        drawdown = (eq - peak) / peak.replace(0, np.nan)
        max_dd = drawdown.min()
        
        final_capitals.append(final_capital)
        min_capitals.append(min_capital)
        max_drawdowns.append(max_dd)
        
        # Store sample paths for visualization
        if i < max_paths_to_store:
            paths.append(eq)
    
    return {
        "kelly_fraction": kelly_fraction_used,
        "n_paths": n_paths,
        "sample_paths": paths,
        "final_capitals": final_capitals,
        "min_capitals": min_capitals,
        "max_drawdowns": max_drawdowns,
        "avg_final_capital": np.mean(final_capitals),
        "avg_min_capital": np.mean(min_capitals),
        "avg_max_drawdown": np.mean(max_drawdowns),
        "capital_below_50": np.mean([c < 0.5 for c in min_capitals]),
        "capital_below_30": np.mean([c < 0.3 for c in min_capitals]),
        "capital_below_10": np.mean([c < 0.1 for c in min_capitals])
    }

def analyze_ruin_factors(
    trade_pnls: List[float],
    kelly_fraction_used: float,
    n_paths: int = 5000
) -> Dict[str, Any]:
    """
    Analyze factors contributing to ruin probability.
    
    Args:
        trade_pnls: List of per-trade PnLs
        kelly_fraction_used: Kelly fraction to test
        n_paths: Number of Monte Carlo paths
        
    Returns:
        Factor analysis
    """
    if not trade_pnls:
        return {"error": "No trade PnLs provided"}
    
    # Basic trade statistics
    pnls = np.array(trade_pnls)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    
    win_rate = len(wins) / len(pnls)
    avg_win = np.mean(wins) if len(wins) > 0 else 0.0
    avg_loss = -np.mean(losses) if len(losses) > 0 else 0.0
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
    
    # Volatility and skewness
    volatility = np.std(pnls)
    skewness = float(pd.Series(pnls).skew())
    kurtosis = float(pd.Series(pnls).kurtosis())
    
    # Maximum loss streak
    max_loss_streak = 0
    current_streak = 0
    for pnl in pnls:
        if pnl <= 0:
            current_streak += 1
            max_loss_streak = max(max_loss_streak, current_streak)
        else:
            current_streak = 0
    
    # Run ruin simulation
    ruin_prob = risk_of_ruin_monte_carlo(trade_pnls, kelly_fraction_used, 0.5, n_paths)
    
    # Risk categorization
    if ruin_prob < 0.01:
        risk_category = "very_low"
    elif ruin_prob < 0.05:
        risk_category = "low"
    elif ruin_prob < 0.15:
        risk_category = "moderate"
    elif ruin_prob < 0.30:
        risk_category = "high"
    else:
        risk_category = "very_high"
    
    return {
        "kelly_fraction": kelly_fraction_used,
        "ruin_probability": ruin_prob,
        "risk_category": risk_category,
        "trade_statistics": {
            "total_trades": len(pnls),
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "win_loss_ratio": win_loss_ratio,
            "volatility": volatility,
            "skewness": skewness,
            "kurtosis": kurtosis,
            "max_loss_streak": max_loss_streak
        },
        "risk_factors": {
            "high_volatility": volatility > 0.1,
            "negative_skew": skewness < -0.5,
            "high_kurtosis": kurtosis > 2.0,
            "low_win_rate": win_rate < 0.4,
            "poor_win_loss_ratio": win_loss_ratio < 1.0,
            "long_loss_streaks": max_loss_streak > 5
        }
    }

def print_ruin_comparison(trade_pnls: List[float], f_full: float):
    """
    Print formatted ruin comparison across Kelly fractions.
    
    Args:
        trade_pnls: List of per-trade PnLs
        f_full: Full Kelly fraction
    """
    if not trade_pnls:
        print("No trade PnLs for ruin comparison")
        return
    
    # Test different fractions
    fractions = [
        ("Full", f_full),
        ("Half", 0.5 * f_full),
        ("Quarter", 0.25 * f_full),
        ("Eighth", 0.125 * f_full)
    ]
    
    print("\n" + "="*70)
    print("KELLY RUIN PROBABILITY COMPARISON")
    print("="*70)
    
    print(f"\nTrade Statistics:")
    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p <= 0]
    win_rate = len(wins) / len(trade_pnls)
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = -np.mean(losses) if losses else 0.0
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
    
    print(f"  Total Trades: {len(trade_pnls)}")
    print(f"  Win Rate: {win_rate:.1%}")
    print(f"  Win/Loss Ratio: {win_loss_ratio:.2f}")
    print(f"  Full Kelly: {f_full:.3f}")
    
    print(f"\nRuin Probability (Capital < 50%):")
    print("-" * 50)
    
    for label, f in fractions:
        prob = risk_of_ruin_monte_carlo(trade_pnls, f, ruin_level=0.5, n_paths=2000)
        print(f"  {label:<10} Kelly: {prob:.2%}")
    
    # Detailed analysis for main fractions
    print(f"\nDetailed Risk Analysis:")
    print("-" * 50)
    
    main_fractions = [f_full, 0.5 * f_full, 0.25 * f_full]
    main_labels = ["Full", "Half", "Quarter"]
    
    for label, f in zip(main_labels, main_fractions):
        analysis = analyze_ruin_factors(trade_pnls, f, n_paths=2000)
        
        print(f"\n{label} Kelly ({f:.3f}):")
        print(f"  Ruin Probability: {analysis['ruin_probability']:.2%}")
        print(f"  Risk Category: {analysis['risk_category']}")
        
        # Show key risk factors
        risk_factors = analysis["risk_factors"]
        active_factors = [factor for factor, present in risk_factors.items() if present]
        
        if active_factors:
            print(f"  Risk Factors: {', '.join(active_factors)}")
        else:
            print(f"  Risk Factors: None significant")
    
    print("="*70)

def generate_ruin_recommendations(
    trade_pnls: List[float],
    kelly_fraction: float
) -> List[str]:
    """
    Generate recommendations based on ruin analysis.
    
    Args:
        trade_pnls: List of per-trade PnLs
        kelly_fraction: Kelly fraction to analyze
        
    Returns:
        List of recommendations
    """
    analysis = analyze_ruin_factors(trade_pnls, kelly_fraction)
    recommendations = []
    
    ruin_prob = analysis["ruin_probability"]
    risk_factors = analysis["risk_factors"]
    trade_stats = analysis["trade_statistics"]
    
    # High ruin probability recommendations
    if ruin_prob > 0.20:
        recommendations.append("⚠️ High ruin probability detected - consider reducing Kelly fraction to 25% or less")
    elif ruin_prob > 0.10:
        recommendations.append("⚠️ Moderate ruin probability - consider reducing Kelly fraction to 50% or less")
    elif ruin_prob > 0.05:
        recommendations.append("ℹ️ Low ruin probability - fractional Kelly recommended for safety")
    
    # Risk factor specific recommendations
    if risk_factors["high_volatility"]:
        recommendations.append("📊 High volatility detected - consider smaller position sizes")
    
    if risk_factors["negative_skew"]:
        recommendations.append("📉 Negative skew detected - consider defensive sizing")
    
    if risk_factors["low_win_rate"]:
        recommendations.append("🎯 Low win rate detected - improve entry signals or reduce size")
    
    if risk_factors["poor_win_loss_ratio"]:
        recommendations.append("⚖️ Poor win/loss ratio detected - improve exit signals")
    
    if risk_factors["long_loss_streaks"]:
        recommendations.append("📉 Long loss streaks detected - implement stronger risk controls")
    
    # General recommendations
    if ruin_prob < 0.01:
        recommendations.append("✅ Very low ruin probability - current sizing appears safe")
    
    # Safety recommendations
    if kelly_fraction > 0.15:
        recommendations.append("🛡️ Consider fractional Kelly (25-50%) for better risk management")
    
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

# Print ruin comparison
print_ruin_comparison(trade_pnls.tolist(), f_full)

# Generate recommendations
recommendations = generate_ruin_recommendations(trade_pnls.tolist(), 0.5 * f_full)
print("Recommendations:")
for rec in recommendations:
    print(f"  {rec}")
"""
