"""
Compare Volatility-Targeted vs Fixed-Fraction Kelly

Compare volatility-targeted Kelly with fixed fraction sizing.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from typing import List, Dict, Any
import logging

from .quarter_half_kelly import kelly_equity
from .kelly_vol_target import vol_targeted_fraction, realized_vol

logger = logging.getLogger(__name__)

def compare_vol_target_vs_fixed(trade_pnls: List[float], f_full: float, 
                                target_vol: float = 0.20, 
                                show_plot: bool = True) -> Dict[str, Any]:
    """
    Compare volatility-targeted Kelly vs fixed fraction sizing.
    
    Args:
        trade_pnls: List of per-trade PnLs
        f_full: Full Kelly fraction
        target_vol: Target volatility for vol-targeted approach
        show_plot: Whether to display comparison plot
        
    Returns:
        Comparison results
    """
    if not trade_pnls:
        return {"error": "No trade PnLs provided"}
    
    pnls = pd.Series(trade_pnls)
    
    # Fixed fractional: half Kelly
    f_fixed = 0.5 * f_full
    eq_fixed = kelly_equity(pnls.tolist(), f_fixed)
    ret_fixed = eq_fixed.pct_change().fillna(0.0)
    
    # Vol-targeted: start with half Kelly then rescale to hit target vol
    base_returns = (pnls * f_fixed)
    f_vol = vol_targeted_fraction(f_fixed, base_returns, target_vol=target_vol)
    eq_vol = kelly_equity(pnls.tolist(), f_vol)
    ret_vol = eq_vol.pct_change().fillna(0.0)
    
    # Calculate volatilities
    periods_per_year = 365 * 24 * 4  # ~15m periods
    vol_fixed = realized_vol(ret_fixed, periods_per_year)
    vol_vol = realized_vol(ret_vol, periods_per_year)
    
    # Calculate performance metrics
    def calculate_metrics(equity, returns, label):
        final_capital = equity.iloc[-1]
        total_return = (final_capital / equity.iloc[0]) - 1
        
        # Sharpe ratio
        if returns.std() > 0:
            sharpe = returns.mean() / returns.std() * np.sqrt(periods_per_year)
        else:
            sharpe = 0.0
        
        # Max drawdown
        peak = equity.cummax()
        dd = (equity - peak) / peak.replace(0, np.nan)
        max_dd = dd.min()
        
        # Win rate
        win_rate = (returns > 0).sum() / len(returns) if len(returns) > 0 else 0.0
        
        return {
            "final_capital": final_capital,
            "total_return": total_return,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_dd,
            "win_rate": win_rate,
            "volatility": realized_vol(returns, periods_per_year)
        }
    
    metrics_fixed = calculate_metrics(eq_fixed, ret_fixed, "Fixed")
    metrics_vol = calculate_metrics(eq_vol, ret_vol, "Vol-Targeted")
    
    # Comparison analysis
    comparison = {
        "fixed_fraction": f_fixed,
        "vol_targeted_fraction": f_vol,
        "target_volatility": target_vol,
        "fixed_metrics": metrics_fixed,
        "vol_targeted_metrics": metrics_vol,
        "volatility_improvement": abs(vol_vol - target_vol) / abs(vol_fixed - target_vol) if vol_fixed != target_vol else 1.0,
        "performance_comparison": {
            "return_improvement": (metrics_vol["total_return"] - metrics_fixed["total_return"]) / abs(metrics_fixed["total_return"]) if metrics_fixed["total_return"] != 0 else 0.0,
            "sharpe_improvement": metrics_vol["sharpe_ratio"] - metrics_fixed["sharpe_ratio"],
            "drawdown_improvement": (metrics_vol["max_drawdown"] - metrics_fixed["max_drawdown"]) / abs(metrics_fixed["max_drawdown"]) if metrics_fixed["max_drawdown"] != 0 else 0.0
        }
    }
    
    # Print results
    print(f"Fixed fraction f={f_fixed:.3f}, realized vol≈{vol_fixed:.2%}")
    print(f"Vol-target f={f_vol:.3f}, realized vol≈{vol_vol:.2%}")
    print(f"Target volatility: {target_vol:.2%}")
    
    print(f"\nPerformance Comparison:")
    print(f"  Fixed Kelly - Return: {metrics_fixed['total_return']:.1%}, Sharpe: {metrics_fixed['sharpe_ratio']:.2f}, DD: {metrics_fixed['max_drawdown']:.2%}")
    print(f"  Vol-Target - Return: {metrics_vol['total_return']:.1%}, Sharpe: {metrics_vol['sharpe_ratio']:.2f}, DD: {metrics_vol['max_drawdown']:.2%}")
    
    # Show plot if requested
    if show_plot:
        plt.figure(figsize=(12, 6))
        
        # Equity curves
        plt.subplot(2, 1, 1)
        plt.plot(eq_fixed.values, label=f"Fixed Half Kelly (f={f_fixed:.3f})", linewidth=2)
        plt.plot(eq_vol.values, label=f"Vol-targeted (f={f_vol:.3f})", linewidth=2)
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.title("Kelly: Fixed Fraction vs Volatility Targeting")
        plt.ylabel("Capital")
        
        # Drawdowns
        plt.subplot(2, 1, 2)
        
        # Calculate drawdowns
        peak_fixed = eq_fixed.cummax()
        dd_fixed = (eq_fixed - peak_fixed) / peak_fixed.replace(0, np.nan)
        
        peak_vol = eq_vol.cummax()
        dd_vol = (eq_vol - peak_vol) / peak_vol.replace(0, np.nan)
        
        plt.fill_between(range(len(dd_fixed)), dd_fixed.values, 0, alpha=0.3, label="Fixed DD")
        plt.fill_between(range(len(dd_vol)), dd_vol.values, 0, alpha=0.3, label="Vol-Target DD")
        plt.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.ylabel("Drawdown")
        plt.xlabel("Trade Number")
        
        plt.tight_layout()
        plt.show()
    
    return comparison

def analyze_volatility_targeting_effectiveness(trade_pnls: List[float], f_full: float,
                                              target_vols: List[float] = None) -> Dict[str, Any]:
    """
    Analyze effectiveness of volatility targeting across different targets.
    
    Args:
        trade_pnls: List of per-trade PnLs
        f_full: Full Kelly fraction
        target_vols: List of target volatilities to test
        
    Returns:
        Effectiveness analysis
    """
    if not trade_pnls:
        return {"error": "No trade PnLs provided"}
    
    if target_vols is None:
        target_vols = [0.10, 0.15, 0.20, 0.25, 0.30]
    
    results = {}
    
    # Fixed Kelly baseline
    f_fixed = 0.5 * f_full
    eq_fixed = kelly_equity(trade_pnls, f_fixed)
    ret_fixed = eq_fixed.pct_change().fillna(0.0)
    
    baseline_metrics = {
        "final_capital": eq_fixed.iloc[-1],
        "total_return": (eq_fixed.iloc[-1] / eq_fixed.iloc[0]) - 1,
        "volatility": realized_vol(ret_fixed, 365 * 24 * 4),
        "sharpe_ratio": ret_fixed.mean() / ret_fixed.std() * np.sqrt(365 * 24 * 4) if ret_fixed.std() > 0 else 0.0
    }
    
    for target_vol in target_vols:
        try:
            comparison = compare_vol_target_vs_fixed(trade_pnls, f_full, target_vol, show_plot=False)
            
            if "error" not in comparison:
                results[target_vol] = {
                    "target_vol": target_vol,
                    "vol_targeted_fraction": comparison["vol_targeted_fraction"],
                    "realized_vol": comparison["vol_targeted_metrics"]["volatility"],
                    "vol_error": abs(comparison["vol_targeted_metrics"]["volatility"] - target_vol),
                    "vol_error_pct": abs(comparison["vol_targeted_metrics"]["volatility"] - target_vol) / target_vol,
                    "total_return": comparison["vol_targeted_metrics"]["total_return"],
                    "sharpe_ratio": comparison["vol_targeted_metrics"]["sharpe_ratio"],
                    "max_drawdown": comparison["vol_targeted_metrics"]["max_drawdown"],
                    "return_vs_baseline": comparison["vol_targeted_metrics"]["total_return"] - baseline_metrics["total_return"],
                    "sharpe_vs_baseline": comparison["vol_targeted_metrics"]["sharpe_ratio"] - baseline_metrics["sharpe_ratio"]
                }
        except Exception as e:
            logger.error(f"Error analyzing target vol {target_vol}: {e}")
            continue
    
    if not results:
        return {"error": "No valid results"}
    
    # Find best target volatility
    best_target = max(results.items(), key=lambda x: x[1]["sharpe_ratio"])
    
    return {
        "baseline_fixed": baseline_metrics,
        "target_vol_results": results,
        "best_target_vol": best_target[0],
        "best_target_metrics": best_target[1],
        "effectiveness_summary": {
            "vol_targeting_works": any(r["vol_error_pct"] < 0.20 for r in results.values()),
            "avg_vol_error": np.mean([r["vol_error_pct"] for r in results.values()]),
            "best_sharpe_improvement": best_target[1]["sharpe_vs_baseline"]
        }
    }

def print_volatility_analysis(trade_pnls: List[float], f_full: float):
    """
    Print comprehensive volatility targeting analysis.
    
    Args:
        trade_pnls: List of per-trade PnLs
        f_full: Full Kelly fraction
    """
    if not trade_pnls:
        print("No trade PnLs for analysis")
        return
    
    print("\n" + "="*80)
    print("VOLATILITY TARGETING ANALYSIS")
    print("="*80)
    
    # Basic comparison
    comparison = compare_vol_target_vs_fixed(trade_pnls, f_full, show_plot=False)
    
    print(f"\nBasic Comparison (Target Vol: 20%):")
    print(f"  Fixed Kelly: f={comparison['fixed_fraction']:.3f}, vol={comparison['fixed_metrics']['volatility']:.2%}")
    print(f"  Vol-Target: f={comparison['vol_targeted_fraction']:.3f}, vol={comparison['vol_targeted_metrics']['volatility']:.2%}")
    print(f"  Return Improvement: {comparison['performance_comparison']['return_improvement']:.1%}")
    print(f"  Sharpe Improvement: {comparison['performance_comparison']['sharpe_improvement']:.2f}")
    
    # Multi-target analysis
    effectiveness = analyze_volatility_targeting_effectiveness(trade_pnls, f_full)
    
    if "error" not in effectiveness:
        print(f"\nMulti-Target Analysis:")
        print(f"  Baseline Fixed Kelly: Return={effectiveness['baseline_fixed']['total_return']:.1%}, Sharpe={effectiveness['baseline_fixed']['sharpe_ratio']:.2f}")
        print(f"  Best Target Vol: {effectiveness['best_target_vol']:.1%}")
        print(f"  Best Sharpe: {effectiveness['best_target_metrics']['sharpe_ratio']:.2f}")
        print(f"  Best Improvement: {effectiveness['best_target_metrics']['sharpe_vs_baseline']:.2f}")
        print(f"  Avg Vol Error: {effectiveness['effectiveness_summary']['avg_vol_error']:.1%}")
        print(f"  Vol Targeting Effective: {'Yes' if effectiveness['effectiveness_summary']['vol_targeting_works'] else 'No'}")
        
        print(f"\nTarget Volatility Results:")
        print("-" * 80)
        print(f"{'Target':<8} {'Actual':<8} {'Error':<8} {'Sharpe':<8} {'Return':<8} {'Improvement':<12}")
        print("-" * 80)
        
        for target, metrics in effectiveness["target_vol_results"].items():
            print(f"{target:<8.1%} {metrics['realized_vol']:<8.2%} {metrics['vol_error_pct']:<8.1%} "
                  f"{metrics['sharpe_ratio']:<8.2f} {metrics['total_return']:<8.1%} {metrics['sharpe_vs_baseline']:<12.2f}")
    
    print("="*80)

def generate_volatility_recommendations(trade_pnls: List[float], f_full: float) -> List[str]:
    """
    Generate recommendations for volatility targeting.
    
    Args:
        trade_pnls: List of per-trade PnLs
        f_full: Full Kelly fraction
        
    Returns:
        List of recommendations
    """
    if not trade_pnls:
        return ["No trade data available for recommendations"]
    
    recommendations = []
    
    # Analyze effectiveness
    effectiveness = analyze_volatility_targeting_effectiveness(trade_pnls, f_full)
    
    if "error" in effectiveness:
        return ["Error in volatility analysis - cannot generate recommendations"]
    
    # Check if volatility targeting works
    if effectiveness["effectiveness_summary"]["vol_targeting_works"]:
        recommendations.append("✅ Volatility targeting appears effective for this strategy")
        best_target = effectiveness["best_target_vol"]
        recommendations.append(f"🎯 Consider using target volatility of {best_target:.1%} for optimal performance")
    else:
        recommendations.append("⚠️ Volatility targeting may not be effective for this strategy")
        recommendations.append("📊 Consider using fixed fractional Kelly instead")
    
    # Check volatility levels
    baseline_vol = effectiveness["baseline_fixed"]["volatility"]
    if baseline_vol > 0.30:
        recommendations.append("📈 High baseline volatility detected - volatility targeting could help smooth returns")
    elif baseline_vol < 0.10:
        recommendations.append("📉 Low baseline volatility - volatility targeting may have limited benefit")
    
    # Check improvement potential
    best_improvement = effectiveness["effectiveness_summary"]["best_sharpe_improvement"]
    if best_improvement > 0.5:
        recommendations.append(f"🚀 Significant Sharpe improvement possible (+{best_improvement:.2f})")
    elif best_improvement > 0.1:
        recommendations.append(f"📈 Moderate Sharpe improvement possible (+{best_improvement:.2f})")
    else:
        recommendations.append("📊 Limited improvement expected from volatility targeting")
    
    # General recommendations
    recommendations.append("💡 Monitor realized volatility regularly and adjust target as needed")
    recommendations.append("⚖️ Consider combining volatility targeting with drawdown limits for risk management")
    
    return recommendations

# Example usage:
"""
import numpy as np

# Generate sample trade PnLs
np.random.seed(42)
trade_pnls = np.random.choice([0.01, -0.005, 0.015, -0.01, 0.02, -0.015], size=200)

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

# Compare volatility targeting vs fixed
comparison = compare_vol_target_vs_fixed(trade_pnls.tolist(), f_full)

# Print comprehensive analysis
print_volatility_analysis(trade_pnls.tolist(), f_full)

# Generate recommendations
recommendations = generate_volatility_recommendations(trade_pnls.tolist(), f_full)
print("Recommendations:")
for rec in recommendations:
    print(f"  {rec}")
"""
