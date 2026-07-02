"""
Kelly with Volatility-of-Volatility Uncertainty

Adjust Kelly fraction based on volatility uncertainty (vol-of-vol).
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

def realized_vol_series(returns: pd.Series, window: int, periods_per_year: int) -> pd.Series:
    """
    Calculate rolling annualized volatility series.
    
    Args:
        returns: Series of returns
        window: Rolling window size
        periods_per_year: Number of periods per year for annualization
        
    Returns:
        Rolling annualized volatility series
    """
    if returns.empty or window <= 0:
        return pd.Series()
    
    rolling_sigma = returns.rolling(window=window, min_periods=1).std()
    return rolling_sigma * np.sqrt(periods_per_year)

def adjust_for_vol_of_vol(
    base_fraction: float,
    realized_vol_series: pd.Series,
    damp_factor: float = 1.0,
) -> float:
    """
    Adjust Kelly fraction based on volatility-of-volatility uncertainty.
    
    Args:
        base_fraction: Base Kelly fraction
        realized_vol_series: Rolling volatility estimates (annualized)
        damp_factor: Dampening factor for vol-of-vol adjustment
        
    Returns:
        Adjusted Kelly fraction
    """
    if realized_vol_series.empty:
        logger.warning("Empty volatility series - returning base fraction")
        return base_fraction
    
    # Calculate vol-of-vol (standard deviation of volatility estimates)
    vol_vol = realized_vol_series.dropna().std()
    
    if np.isnan(vol_vol) or vol_vol == 0:
        logger.debug(f"Zero or NaN vol-of-vol ({vol_vol}) - returning base fraction")
        return base_fraction
    
    # Simple shrinkage: f_adj = f / (1 + damp_factor * vol_vol)
    # Higher vol-of-vol -> more conservative (smaller fraction)
    adjustment_denominator = 1.0 + damp_factor * vol_vol
    adjusted_fraction = base_fraction / adjustment_denominator
    
    logger.debug(f"Vol-of-vol adjustment: base={base_fraction:.3f}, "
                f"vol_vol={vol_vol:.4f}, damp_factor={damp_factor:.2f}, "
                f"adjusted={adjusted_fraction:.3f}")
    
    return adjusted_fraction

def calculate_volatility_metrics(returns: pd.Series, 
                                vol_window: int = 30,
                                periods_per_year: int = 365 * 24 * 4) -> Dict[str, Any]:
    """
    Calculate comprehensive volatility metrics for uncertainty analysis.
    
    Args:
        returns: Series of returns
        vol_window: Window for rolling volatility
        periods_per_year: Periods per year for annualization
        
    Returns:
        Volatility metrics dictionary
    """
    if returns.empty:
        return {"error": "Empty returns series"}
    
    # Calculate rolling volatility
    vol_series = realized_vol_series(returns, vol_window, periods_per_year)
    
    if vol_series.empty:
        return {"error": "Could not calculate volatility series"}
    
    # Calculate vol-of-vol metrics
    vol_vol = vol_series.dropna().std()
    vol_mean = vol_series.mean()
    vol_median = vol_series.median()
    vol_range = vol_series.max() - vol_series.min()
    
    # Calculate volatility stability metrics
    vol_cv = vol_vol / vol_mean if vol_mean > 0 else float('inf')  # Coefficient of variation
    vol_trend = (vol_series.iloc[-1] - vol_series.iloc[0]) / vol_series.iloc[0] if vol_series.iloc[0] > 0 else 0.0
    
    # Calculate percentiles
    vol_p05 = vol_series.quantile(0.05)
    vol_p25 = vol_series.quantile(0.25)
    vol_p75 = vol_series.quantile(0.75)
    vol_p95 = vol_series.quantile(0.95)
    
    # Classify volatility regime
    if vol_mean < 0.10:
        vol_regime = "low"
    elif vol_mean < 0.25:
        vol_regime = "normal"
    elif vol_mean < 0.50:
        vol_regime = "high"
    else:
        vol_regime = "extreme"
    
    # Classify volatility stability
    if vol_cv < 0.2:
        stability = "very_stable"
    elif vol_cv < 0.5:
        stability = "stable"
    elif vol_cv < 1.0:
        stability = "unstable"
    else:
        stability = "very_unstable"
    
    return {
        "vol_mean": vol_mean,
        "vol_median": vol_median,
        "vol_std": vol_vol,
        "vol_range": vol_range,
        "vol_cv": vol_cv,
        "vol_trend": vol_trend,
        "vol_p05": vol_p05,
        "vol_p25": vol_p25,
        "vol_p75": vol_p75,
        "vol_p95": vol_p95,
        "vol_regime": vol_regime,
        "vol_stability": stability,
        "sample_size": len(vol_series.dropna()),
        "window_used": vol_window
    }

def adaptive_vol_of_vol_adjustment(base_fraction: float,
                                   returns: pd.Series,
                                   vol_windows: List[int] = None,
                                   damp_factors: List[float] = None,
                                   periods_per_year: int = 365 * 24 * 4) -> Dict[str, Any]:
    """
    Adaptive vol-of-vol adjustment across multiple windows and dampening factors.
    
    Args:
        base_fraction: Base Kelly fraction
        returns: Series of returns
        vol_windows: List of volatility windows to test
        damp_factors: List of dampening factors to test
        periods_per_year: Periods per year
        
    Returns:
        Adaptive adjustment results
    """
    if vol_windows is None:
        vol_windows = [20, 30, 50, 100]  # Different lookback periods
    
    if damp_factors is None:
        damp_factors = [0.5, 1.0, 2.0, 5.0]  # Different dampening levels
    
    results = {}
    
    for window in vol_windows:
        for damp_factor in damp_factors:
            # Calculate volatility series
            vol_series = realized_vol_series(returns, window, periods_per_year)
            
            if vol_series.empty:
                continue
            
            # Calculate adjustment
            adjusted_fraction = adjust_for_vol_of_vol(base_fraction, vol_series, damp_factor)
            
            # Calculate metrics
            vol_metrics = calculate_volatility_metrics(returns, window, periods_per_year)
            
            key = f"window_{window}_damp_{damp_factor}"
            results[key] = {
                "window": window,
                "damp_factor": damp_factor,
                "base_fraction": base_fraction,
                "adjusted_fraction": adjusted_fraction,
                "adjustment_ratio": adjusted_fraction / base_fraction if base_fraction > 0 else 1.0,
                "vol_metrics": vol_metrics
            }
    
    if not results:
        return {"error": "No valid adjustment results"}
    
    # Find best adjustment (highest adjusted fraction with reasonable vol-of-vol)
    best_result = None
    best_score = -np.inf
    
    for result in results.values():
        vol_metrics = result["vol_metrics"]
        
        # Score based on adjusted fraction and volatility stability
        # Prefer higher adjusted fraction but penalize high vol-of-vol
        vol_cv = vol_metrics.get("vol_cv", float('inf'))
        
        if vol_cv < float('inf'):
            # Higher score for higher adjusted fraction, lower for higher vol-of-vol
            score = result["adjusted_fraction"] - 0.1 * vol_cv
            
            if score > best_score:
                best_score = score
                best_result = result
    
    return {
        "results": results,
        "best_adjustment": best_result,
        "best_score": best_score,
        "total_combinations": len(results)
    }

def print_vol_of_vol_analysis(returns: pd.Series, base_fraction: float = 0.15):
    """
    Print comprehensive vol-of-vol analysis.
    
    Args:
        returns: Series of returns
        base_fraction: Base Kelly fraction
    """
    if returns.empty:
        print("No returns data for vol-of-vol analysis")
        return
    
    print("\n" + "="*80)
    print("KELLY VOLATILITY-OF-VOLATILITY UNCERTAINTY ANALYSIS")
    print("="*80)
    
    # Basic volatility metrics
    vol_metrics = calculate_volatility_metrics(returns)
    
    if "error" in vol_metrics:
        print(f"Error: {vol_metrics['error']}")
        return
    
    print(f"\nVolatility Metrics:")
    print(f"  Mean Volatility: {vol_metrics['vol_mean']:.2%}")
    print(f"  Volatility Std: {vol_metrics['vol_std']:.2%}")
    print(f"  Volatility Range: {vol_metrics['vol_range']:.2%}")
    print(f"  Volatility CV: {vol_metrics['vol_cv']:.3f}")
    print(f"  Volatility Regime: {vol_metrics['vol_regime']}")
    print(f"  Volatility Stability: {vol_metrics['vol_stability']}")
    
    # Simple adjustment
    vol_series = realized_vol_series(returns, 30, 365 * 24 * 4)
    adjusted_fraction = adjust_for_vol_of_vol(base_fraction, vol_series, damp_factor=1.0)
    
    print(f"\nSimple Vol-of-Vol Adjustment:")
    print(f"  Base Fraction: {base_fraction:.3f}")
    print(f"  Adjusted Fraction: {adjusted_fraction:.3f}")
    print(f"  Adjustment Ratio: {adjusted_fraction/base_fraction:.3f}")
    
    # Adaptive analysis
    adaptive_results = adaptive_vol_of_vol_adjustment(base_fraction, returns)
    
    if "error" not in adaptive_results:
        best = adaptive_results["best_adjustment"]
        
        print(f"\nAdaptive Analysis Results:")
        print(f"  Best Window: {best['window']}")
        print(f"  Best Damp Factor: {best['damp_factor']}")
        print(f"  Best Adjusted Fraction: {best['adjusted_fraction']:.3f}")
        print(f"  Best Adjustment Ratio: {best['adjustment_ratio']:.3f}")
        print(f"  Vol CV (best): {best['vol_metrics']['vol_cv']:.3f}")
        
        print(f"\nRecommendations:")
        if vol_metrics['vol_cv'] > 1.0:
            print("  ⚠️ High volatility uncertainty - use conservative Kelly sizing")
        elif vol_metrics['vol_cv'] > 0.5:
            print("  📊 Moderate volatility uncertainty - consider fractional Kelly")
        else:
            print("  ✅ Low volatility uncertainty - Kelly sizing should be reliable")
        
        if best['adjustment_ratio'] < 0.8:
            print(f"  🛡️ Recommended Kelly fraction: {best['adjusted_fraction']:.3f} (conservative)")
        elif best['adjustment_ratio'] < 0.95:
            print(f"  📊 Recommended Kelly fraction: {best['adjusted_fraction']:.3f} (moderate)")
        else:
            print(f"  🚀 Recommended Kelly fraction: {best['adjusted_fraction']:.3f} (aggressive)")
    
    print("="*80)

def generate_vol_of_vol_recommendations(vol_metrics: Dict[str, Any], 
                                     adjustment_ratio: float) -> List[str]:
    """
    Generate recommendations based on vol-of-vol analysis.
    
    Args:
        vol_metrics: Volatility metrics from calculate_volatility_metrics
        adjustment_ratio: Ratio of adjusted to base fraction
        
    Returns:
        List of recommendations
    """
    recommendations = []
    
    if "error" in vol_metrics:
        return ["No volatility data available for recommendations"]
    
    vol_cv = vol_metrics.get("vol_cv", 0.0)
    vol_regime = vol_metrics.get("vol_regime", "normal")
    vol_stability = vol_metrics.get("vol_stability", "stable")
    
    # Volatility uncertainty recommendations
    if vol_cv > 1.0:
        recommendations.append("⚠️ Very high volatility uncertainty - use quarter Kelly or less")
    elif vol_cv > 0.5:
        recommendations.append("📊 High volatility uncertainty - consider half Kelly")
    elif vol_cv > 0.2:
        recommendations.append("📈 Moderate volatility uncertainty - fractional Kelly recommended")
    else:
        recommendations.append("✅ Low volatility uncertainty - Kelly sizing should be reliable")
    
    # Volatility regime recommendations
    if vol_regime == "extreme":
        recommendations.append("🔴 Extreme volatility regime - reduce position size significantly")
    elif vol_regime == "high":
        recommendations.append("🟡 High volatility regime - use conservative sizing")
    elif vol_regime == "low":
        recommendations.append("🟢 Low volatility regime - can consider increasing position size")
    
    # Stability recommendations
    if vol_stability == "very_unstable":
        recommendations.append("📉 Very unstable volatility - implement strong risk controls")
    elif vol_stability == "unstable":
        recommendations.append("📊 Unstable volatility - monitor risk metrics closely")
    elif vol_stability == "very_stable":
        recommendations.append("✅ Very stable volatility - Kelly sizing should be consistent")
    
    # Adjustment ratio recommendations
    if adjustment_ratio < 0.5:
        recommendations.append(f"🛡️ Strong adjustment recommended ({adjustment_ratio:.1%} of base fraction)")
    elif adjustment_ratio < 0.8:
        recommendations.append(f"📊 Moderate adjustment recommended ({adjustment_ratio:.1%} of base fraction)")
    elif adjustment_ratio < 0.95:
        recommendations.append(f"📈 Light adjustment recommended ({adjustment_ratio:.1%} of base fraction)")
    else:
        recommendations.append(f"🚀 Minimal adjustment needed ({adjustment_ratio:.1%} of base fraction)")
    
    # General recommendations
    recommendations.append("💡 Monitor volatility changes and adjust Kelly fraction dynamically")
    recommendations.append("🔄 Re-calculate vol-of-vol metrics periodically with new data")
    recommendations.append("⚖️ Combine vol-of-vol adjustment with other risk controls")
    
    return recommendations

# Example usage for Kalshi strategy:
"""
class KalshiVolOfVolStrategy:
    def __init__(self, base_kelly_fraction=0.15, vol_window=30, damp_factor=1.0):
        self.base_kelly_fraction = base_kelly_fraction
        self.vol_window = vol_window
        self.damp_factor = damp_factor
        self.returns_history = []
        
    def add_trade_return(self, trade_return):
        # Add new trade return to history
        self.returns_history.append(trade_return)
        
        # Keep reasonable history size
        if len(self.returns_history) > 500:
            self.returns_history = self.returns_history[-500:]
    
    def get_adjusted_kelly_fraction(self):
        if len(self.returns_history) < self.vol_window:
            return self.base_kelly_fraction
        
        returns_series = pd.Series(self.returns_history)
        vol_series = realized_vol_series(returns_series, self.vol_window, 365 * 24 * 4)
        
        return adjust_for_vol_of_vol(
            self.base_kelly_fraction, vol_series, self.damp_factor
        )
    
    def get_volatility_metrics(self):
        if len(self.returns_history) < self.vol_window:
            return {}
        
        returns_series = pd.Series(self.returns_history)
        return calculate_volatility_metrics(returns_series, self.vol_window)
    
    def analyze_and_recommend(self):
        vol_metrics = self.get_volatility_metrics()
        adjusted_fraction = self.get_adjusted_kelly_fraction()
        adjustment_ratio = adjusted_fraction / self.base_kelly_fraction
        
        recommendations = generate_vol_of_vol_recommendations(vol_metrics, adjustment_ratio)
        
        return {
            "base_fraction": self.base_kelly_fraction,
            "adjusted_fraction": adjusted_fraction,
            "adjustment_ratio": adjustment_ratio,
            "vol_metrics": vol_metrics,
            "recommendations": recommendations
        }

# Usage:
# strategy = KalshiVolOfVolStrategy(base_kelly_fraction=0.15)
# 
# On each trade completion:
# strategy.add_trade_return(trade_return)
# adjusted_kelly = strategy.get_adjusted_kelly_fraction()
# 
# Periodically analyze:
# analysis = strategy.analyze_and_recommend()
# print("Vol-of-Vol Analysis:")
# for rec in analysis["recommendations"]:
#     print(f"  {rec}")
"""
