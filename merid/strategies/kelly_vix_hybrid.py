"""
Kelly-VIX Hybrid Sizing - Per Trade

Hybrid Kelly sizing with VIX-based scaling factor for dynamic position sizing.
"""

import pandas as pd
import numpy as np
from typing import Optional
import logging

from .vix_data import fetch_vix_with_fallback, calculate_vix_rank

logger = logging.getLogger(__name__)

def vix_rank(vix_series: pd.Series, lookback: int = 252) -> float:
    """
    Return last value's percentile rank over lookback window.
    
    Args:
        vix_series: VIX price series indexed by date
        lookback: Number of days for rank calculation
        
    Returns:
        VIX rank (0-1, where 0 = lowest volatility, 1 = highest)
    """
    if vix_series.empty or len(vix_series) < lookback:
        logger.warning(f"Insufficient VIX data for rank calculation: {len(vix_series)} < {lookback}")
        return 0.5  # Default to middle rank
    
    # Get lookback window
    window = vix_series.iloc[-lookback:]
    
    if window.empty:
        return 0.5
    
    current = window.iloc[-1]
    
    # Calculate percentile rank
    rank = (window <= current).mean()
    
    # Ensure in [0,1] range
    rank = max(0.0, min(1.0, float(rank)))
    
    logger.debug(f"VIX rank: {rank:.3f} (current: {current:.2f}, lookback: {lookback} days)")
    
    return rank

def vix_hybrid_scale(vix_rank_value: float, 
                    low_vol_boost: float = 1.2, 
                    high_vol_cut: float = 0.5) -> float:
    """
    Calculate VIX hybrid scaling factor based on VIX rank.
    
    Args:
        vix_rank_value: VIX rank (0-1)
        low_vol_boost: Scaling factor when volatility is low (rank near 0)
        high_vol_cut: Scaling factor when volatility is high (rank near 1)
        
    Returns:
        Hybrid scaling factor
    """
    # Clamp rank to [0,1]
    v = max(0.0, min(1.0, vix_rank_value))
    
    # Linear interpolation between boost at 0 and cut at 1
    scale = low_vol_boost - (low_vol_boost - high_vol_cut) * v
    
    # Ensure non-negative
    scale = max(0.0, scale)
    
    logger.debug(f"VIX hybrid scale: rank={v:.3f}, scale={scale:.3f} "
                f"(boost={low_vol_boost:.2f}, cut={high_vol_cut:.2f})")
    
    return scale

def hybrid_kelly_fraction(base_kelly_fraction: float, 
                          vix_series: pd.Series,
                          lookback: int = 252,
                          low_vol_boost: float = 1.2,
                          high_vol_cut: float = 0.5,
                          max_fraction: float = None) -> float:
    """
    Calculate Kelly-VIX hybrid fraction for position sizing.
    
    Args:
        base_kelly_fraction: Base Kelly fraction (e.g., half Kelly)
        vix_series: VIX price series
        lookback: Lookback period for VIX rank calculation
        low_vol_boost: Scaling factor in low volatility
        high_vol_cut: Scaling factor in high volatility
        max_fraction: Maximum allowed fraction (safety cap)
        
    Returns:
        Hybrid Kelly fraction
    """
    # Calculate VIX rank
    vr = vix_rank(vix_series, lookback)
    
    # Calculate hybrid scale
    s = vix_hybrid_scale(vr, low_vol_boost, high_vol_cut)
    
    # Apply to base Kelly fraction
    hybrid_fraction = base_kelly_fraction * s
    
    # Apply maximum fraction cap if specified
    if max_fraction is not None:
        hybrid_fraction = min(hybrid_fraction, max_fraction)
    
    logger.debug(f"Hybrid Kelly: base={base_kelly_fraction:.3f}, rank={vr:.3f}, "
                f"scale={s:.3f}, hybrid={hybrid_fraction:.3f}")
    
    return hybrid_fraction

def adaptive_vix_hybrid_scale(vix_rank_value: float,
                             volatility_regime: str = None) -> float:
    """
    Adaptive VIX hybrid scaling based on volatility regime.
    
    Args:
        vix_rank_value: VIX rank (0-1)
        volatility_regime: Current volatility regime ('low', 'normal', 'high', 'extreme')
        
    Returns:
        Adaptive scaling factor
    """
    if volatility_regime is None:
        # Use default linear scaling
        return vix_hybrid_scale(vix_rank_value)
    
    # Adjust parameters based on regime
    if volatility_regime == "low":
        # More aggressive in low volatility
        return vix_hybrid_scale(vix_rank_value, low_vol_boost=1.5, high_vol_cut=0.6)
    elif volatility_regime == "normal":
        # Standard parameters
        return vix_hybrid_scale(vix_rank_value, low_vol_boost=1.2, high_vol_cut=0.5)
    elif volatility_regime == "high":
        # More conservative in high volatility
        return vix_hybrid_scale(vix_rank_value, low_vol_boost=1.0, high_vol_cut=0.4)
    elif volatility_regime == "extreme":
        # Very conservative in extreme volatility
        return vix_hybrid_scale(vix_rank_value, low_vol_boost=0.8, high_vol_cut=0.3)
    else:
        return vix_hybrid_scale(vix_rank_value)

def calculate_hybrid_kelly_series(base_kelly_fraction: float,
                                   vix_series: pd.Series,
                                   lookback: int = 252,
                                   low_vol_boost: float = 1.2,
                                   high_vol_cut: float = 0.5) -> pd.Series:
    """
    Calculate time series of hybrid Kelly fractions.
    
    Args:
        base_kelly_fraction: Base Kelly fraction
        vix_series: VIX price series
        lookback: Lookback period for VIX rank
        low_vol_boost: Low volatility boost factor
        high_vol_cut: High volatility cut factor
        
    Returns:
        Time series of hybrid Kelly fractions
    """
    if vix_series.empty or len(vix_series) < lookback:
        return pd.Series([base_kelly_fraction] * len(vix_series), index=vix_series.index, name="Hybrid Kelly")
    
    hybrid_fractions = []
    
    for i in range(len(vix_series)):
        # Use available data up to current point
        current_vix = vix_series.iloc[:i+1]
        
        if len(current_vix) < lookback:
            # Not enough data, use base fraction
            hybrid_fractions.append(base_kelly_fraction)
        else:
            # Calculate hybrid fraction
            hybrid_frac = hybrid_kelly_fraction(
                base_kelly_fraction, current_vix, lookback, low_vol_boost, high_vol_cut
            )
            hybrid_fractions.append(hybrid_frac)
    
    return pd.Series(hybrid_fractions, index=vix_series.index, name="Hybrid Kelly")

def analyze_vix_hybrid_effectiveness(base_kelly_fraction: float,
                                     vix_series: pd.Series,
                                     trade_returns: pd.Series,
                                     lookback: int = 252) -> dict:
    """
    Analyze effectiveness of VIX hybrid scaling.
    
    Args:
        base_kelly_fraction: Base Kelly fraction
        vix_series: VIX price series
        trade_returns: Trade returns series (aligned with VIX dates)
        lookback: Lookback period for VIX rank
        
    Returns:
        Analysis results
    """
    if vix_series.empty or trade_returns.empty:
        return {"error": "Empty VIX or returns data"}
    
    # Align data
    common_index = vix_series.index.intersection(trade_returns.index)
    if len(common_index) == 0:
        return {"error": "No overlapping dates between VIX and returns"}
    
    vix_aligned = vix_series.loc[common_index]
    returns_aligned = trade_returns.loc[common_index]
    
    # Calculate hybrid Kelly series
    hybrid_fractions = calculate_hybrid_kelly_series(
        base_kelly_fraction, vix_aligned, lookback
    )
    
    # Calculate performance with base Kelly
    base_equity = (1 + base_kelly_fraction * returns_aligned).cumprod()
    
    # Calculate performance with hybrid Kelly
    hybrid_equity = (1 + hybrid_fractions * returns_aligned).cumprod()
    
    # Calculate metrics
    def calculate_metrics(equity, label):
        if equity.empty:
            return {}
        
        total_return = (equity.iloc[-1] / equity.iloc[0]) - 1
        returns = equity.pct_change().dropna()
        
        # Sharpe ratio (annualized for daily data)
        if len(returns) > 1 and returns.std() > 0:
            sharpe = returns.mean() / returns.std() * np.sqrt(365)
        else:
            sharpe = 0.0
        
        # Max drawdown
        peak = equity.cummax()
        dd = (equity - peak) / peak.replace(0, np.nan)
        max_dd = dd.min()
        
        return {
            "total_return": total_return,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_dd,
            "final_capital": equity.iloc[-1]
        }
    
    base_metrics = calculate_metrics(base_equity, "base")
    hybrid_metrics = calculate_metrics(hybrid_equity, "hybrid")
    
    # Calculate improvement
    improvement = {}
    if base_metrics and hybrid_metrics:
        improvement = {
            "return_improvement": (hybrid_metrics["total_return"] - base_metrics["total_return"]) / abs(base_metrics["total_return"]) if base_metrics["total_return"] != 0 else 0.0,
            "sharpe_improvement": hybrid_metrics["sharpe_ratio"] - base_metrics["sharpe_ratio"],
            "drawdown_improvement": (hybrid_metrics["max_drawdown"] - base_metrics["max_drawdown"]) / abs(base_metrics["max_drawdown"]) if base_metrics["max_drawdown"] != 0 else 0.0
        }
    
    # Calculate correlation between VIX rank and performance
    vix_ranks = []
    for i in range(len(vix_aligned)):
        if i >= lookback - 1:
            window_vix = vix_aligned.iloc[:i+1]
            rank = (window_vix <= window_vix.iloc[-1]).mean()
            vix_ranks.append(rank)
    
    if len(vix_ranks) > 1:
        correlation = np.corrcoef(vix_ranks, returns_aligned.iloc[len(vix_ranks):].values)[0, 1]
    else:
        correlation = 0.0
    
    return {
        "base_metrics": base_metrics,
        "hybrid_metrics": hybrid_metrics,
        "improvement": improvement,
        "vix_correlation": correlation,
        "avg_hybrid_fraction": hybrid_fractions.mean(),
        "hybrid_fraction_range": [hybrid_fractions.min(), hybrid_fractions.max()],
        "data_points": len(common_index)
    }

def print_vix_hybrid_analysis(analysis: dict):
    """
    Print formatted VIX hybrid analysis.
    
    Args:
        analysis: Analysis results from analyze_vix_hybrid_effectiveness
    """
    if "error" in analysis:
        print(f"Error: {analysis['error']}")
        return
    
    print("\n" + "="*70)
    print("KELLY-VIX HYBRID SIZING ANALYSIS")
    print("="*70)
    
    base = analysis["base_metrics"]
    hybrid = analysis["hybrid_metrics"]
    improvement = analysis["improvement"]
    
    print(f"\nPerformance Comparison:")
    print("-" * 50)
    print(f"{'Metric':<15} {'Base Kelly':<12} {'Hybrid':<12} {'Improvement':<12}")
    print("-" * 50)
    
    for metric in ["total_return", "sharpe_ratio", "max_drawdown"]:
        base_val = base.get(metric, 0.0)
        hybrid_val = hybrid.get(metric, 0.0)
        
        if metric == "max_drawdown":
            # Drawdown improvement is positive when less negative
            imp = improvement.get("drawdown_improvement", 0.0)
            imp_str = f"{imp:.1%}"
        else:
            imp = improvement.get(f"{metric}_improvement", 0.0)
            imp_str = f"{imp:.1%}"
        
        print(f"{metric:<15} {base_val:<12.3f} {hybrid_val:<12.3f} {imp_str:<12}")
    
    print(f"\nHybrid Scaling Analysis:")
    print("-" * 50)
    print(f"  Average Hybrid Fraction: {analysis['avg_hybrid_fraction']:.3f}")
    print(f"  Hybrid Fraction Range: {analysis['hybrid_fraction_range'][0]:.3f} - {analysis['hybrid_fraction_range'][1]:.3f}")
    print(f"  VIX-Return Correlation: {analysis['vix_correlation']:.3f}")
    print(f"  Data Points: {analysis['data_points']}")
    
    print(f"\nRecommendations:")
    if improvement.get("return_improvement", 0) > 0.05:
        print("✅ VIX hybrid scaling significantly improves returns")
    elif improvement.get("return_improvement", 0) > 0.01:
        print("📈 VIX hybrid scaling modestly improves returns")
    else:
        print("⚠️ VIX hybrid scaling does not improve returns")
    
    if improvement.get("sharpe_improvement", 0) > 0.1:
        print("✅ VIX hybrid scaling improves risk-adjusted returns")
    elif improvement.get("sharpe_improvement", 0) > 0.05:
        print("📊 VIX hybrid scaling modestly improves risk-adjusted returns")
    else:
        print("⚠️ VIX hybrid scaling does not improve risk-adjusted returns")
    
    if improvement.get("drawdown_improvement", 0) > 0.1:
        print("✅ VIX hybrid scaling significantly reduces drawdowns")
    elif improvement.get("drawdown_improvement", 0) > 0.05:
        print("📉 VIX hybrid scaling modestly reduces drawdowns")
    else:
        print("⚠️ VIX hybrid scaling does not reduce drawdowns")
    
    print("="*70)

# Example usage for Kalshi integration:
"""
class KalshiVIXHybridStrategy:
    def __init__(self, base_kelly_fraction=0.15, lookback=252):
        self.base_kelly_fraction = base_kelly_fraction
        self.lookback = lookback
        self.vix_data = None
        self.last_vix_fetch = None
        
    def update_vix_data(self):
        # Fetch VIX data (with caching)
        import time
        now = time.time()
        
        # Cache for 1 hour
        if self.vix_data is None or (self.last_vix_fetch and now - self.last_vix_fetch > 3600):
            try:
                from .vix_data import fetch_vix_with_fallback
                self.vix_data = fetch_vix_with_fallback()
                self.last_vix_fetch = now
                print("VIX data updated")
            except Exception as e:
                print(f"Failed to update VIX data: {e}")
    
    def get_hybrid_kelly_fraction(self, trade_date=None):
        if self.vix_data is None:
            return self.base_kelly_fraction
        
        if trade_date is not None and trade_date in self.vix_data.index:
            # Use specific date
            vix_slice = self.vix_data.loc[:trade_date]
        else:
            # Use latest available data
            vix_slice = self.vix_data
        
        return hybrid_kelly_fraction(
            self.base_kelly_fraction, vix_slice, self.lookback
        )
    
    def analyze_historical_performance(self, trade_returns):
        if self.vix_data is None or trade_returns.empty:
            return {"error": "No VIX or returns data available"}
        
        analysis = analyze_vix_hybrid_effectiveness(
            self.base_kelly_fraction, self.vix_data, trade_returns, self.lookback
        )
        
        return analysis

# Usage:
# strategy = KalshiVIXHybridStrategy(base_kelly_fraction=0.15)
# 
# On each trade opportunity:
# strategy.update_vix_data()
# hybrid_kelly = strategy.get_hybrid_kelly_fraction()
# position_size = base_position_size * hybrid_kelly
# 
# Periodically analyze performance:
# analysis = strategy.analyze_historical_performance(trade_returns)
# print_vix_hybrid_analysis(analysis)
"""
