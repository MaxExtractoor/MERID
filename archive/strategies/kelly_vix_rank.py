"""
VIX-Rank Dynamic Kelly Scaling on Kalshi

Scale base Kelly fraction by volatility rank for dynamic position sizing.
"""

import numpy as np
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

def vix_rank_scale(vol_rank: float, min_scale: float = 0.25, max_scale: float = 1.0) -> float:
    """
    Scale Kelly fraction based on volatility rank.
    
    Args:
        vol_rank: Volatility rank in [0,1] (0 = calm, 1 = extreme)
        min_scale: Minimum scale factor (high volatility)
        max_scale: Maximum scale factor (low volatility)
        
    Returns:
        Scale factor for Kelly fraction
    """
    # Ensure vol_rank is in valid range
    vol_rank = max(0.0, min(1.0, vol_rank))
    
    # Linear mapping: max_scale at vol_rank=0, min_scale at vol_rank=1
    scale = max_scale - (max_scale - min_scale) * vol_rank
    
    logger.debug(f"VIX-Rank scaling: vol_rank={vol_rank:.2f}, scale={scale:.3f}")
    
    return scale

def kelly_with_vix_rank(base_kelly_fraction: float, vol_rank: float, 
                        min_scale: float = 0.25, max_scale: float = 1.0) -> float:
    """
    Dynamic Kelly fraction based on VIX-Rank volatility scaling.
    
    Args:
        base_kelly_fraction: Base Kelly fraction (e.g., half Kelly)
        vol_rank: Volatility rank (0-1)
        min_scale: Minimum scale factor
        max_scale: Maximum scale factor
        
    Returns:
        Dynamic Kelly fraction
    """
    scale = vix_rank_scale(vol_rank, min_scale, max_scale)
    dynamic_fraction = base_kelly_fraction * scale
    
    logger.debug(f"Dynamic Kelly: base={base_kelly_fraction:.3f}, "
                f"vol_rank={vol_rank:.2f}, scale={scale:.3f}, result={dynamic_fraction:.3f}")
    
    return dynamic_fraction

def calculate_vol_rank(historical_volatilities: np.ndarray, current_vol: float) -> float:
    """
    Calculate volatility rank from historical volatility distribution.
    
    Args:
        historical_volatilities: Array of historical volatility values
        current_vol: Current volatility value
        
    Returns:
        Volatility rank (0-1)
    """
    if len(historical_volatilities) == 0:
        return 0.5  # Default to middle rank
    
    # Calculate percentile rank
    rank = np.searchsorted(np.sort(historical_volatilities), current_vol) / len(historical_volatilities)
    
    # Ensure in [0,1] range
    rank = max(0.0, min(1.0, rank))
    
    return rank

def vix_rank_kelly_position_size(base_position_size: float, base_kelly_fraction: float,
                                vol_rank: float, atr_multiplier: float = 1.0,
                                min_scale: float = 0.25, max_scale: float = 1.0) -> float:
    """
    Calculate position size using VIX-Rank scaled Kelly.
    
    Args:
        base_position_size: Base position size (e.g., from ATR)
        base_kelly_fraction: Base Kelly fraction
        vol_rank: Volatility rank (0-1)
        atr_multiplier: ATR multiplier for position sizing
        min_scale: Minimum scale factor
        max_scale: Maximum scale factor
        
    Returns:
        Adjusted position size
    """
    # Get dynamic Kelly fraction
    dynamic_kelly = kelly_with_vix_rank(base_kelly_fraction, vol_rank, min_scale, max_scale)
    
    # Apply to position size
    adjusted_size = base_position_size * atr_multiplier * dynamic_kelly
    
    logger.debug(f"VIX-Rank position sizing: base_size={base_position_size:.2f}, "
                f"dynamic_kelly={dynamic_kelly:.3f}, adjusted_size={adjusted_size:.2f}")
    
    return adjusted_size

def analyze_vix_rank_effectiveness(base_kelly_fraction: float, 
                                   trade_pnls: list[float],
                                   vol_ranks: list[float]) -> Dict[str, Any]:
    """
    Analyze effectiveness of VIX-Rank scaling.
    
    Args:
        base_kelly_fraction: Base Kelly fraction
        trade_pnls: List of per-trade PnLs
        vol_ranks: List of volatility ranks (same length as trade_pnls)
        
    Returns:
        Analysis results
    """
    if len(trade_pnls) != len(vol_ranks):
        return {"error": "Trade PnLs and vol ranks must have same length"}
    
    if not trade_pnls:
        return {"error": "No trade data"}
    
    # Calculate equity with fixed Kelly
    from .quarter_half_kelly import kelly_equity
    fixed_equity = kelly_equity(trade_pnls, base_kelly_fraction)
    
    # Calculate equity with VIX-Rank scaling
    dynamic_equity_values = []
    capital = 1.0
    
    for i, (pnl, vol_rank) in enumerate(zip(trade_pnls, vol_ranks)):
        dynamic_kelly = kelly_with_vix_rank(base_kelly_fraction, vol_rank)
        capital *= (1 + dynamic_kelly * pnl)
        dynamic_equity_values.append(capital)
    
    dynamic_equity = pd.Series(dynamic_equity_values)
    
    # Calculate performance metrics
    def calculate_metrics(equity, label):
        if equity.empty:
            return {}
        
        final_capital = equity.iloc[-1]
        total_return = (final_capital / equity.iloc[0]) - 1
        
        # Sharpe ratio
        returns = equity.pct_change().dropna()
        if len(returns) > 1 and returns.std() > 0:
            periods_per_year = 365 * 24 * 4  # 15m bars
            sharpe = returns.mean() / returns.std() * np.sqrt(periods_per_year)
        else:
            sharpe = 0.0
        
        # Max drawdown
        peak = equity.cummax()
        dd = (equity - peak) / peak.replace(0, np.nan)
        max_dd = dd.min()
        
        return {
            "final_capital": final_capital,
            "total_return": total_return,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_dd
        }
    
    fixed_metrics = calculate_metrics(fixed_equity, "fixed")
    dynamic_metrics = calculate_metrics(dynamic_equity, "dynamic")
    
    # Calculate improvement
    improvement = {}
    if fixed_metrics and dynamic_metrics:
        improvement = {
            "return_improvement": (dynamic_metrics["total_return"] - fixed_metrics["total_return"]) / abs(fixed_metrics["total_return"]) if fixed_metrics["total_return"] != 0 else 0.0,
            "sharpe_improvement": dynamic_metrics["sharpe_ratio"] - fixed_metrics["sharpe_ratio"],
            "drawdown_improvement": (dynamic_metrics["max_drawdown"] - fixed_metrics["max_drawdown"]) / abs(fixed_metrics["max_drawdown"]) if fixed_metrics["max_drawdown"] != 0 else 0.0
        }
    
    # Calculate volatility correlation
    vol_rank_array = np.array(vol_ranks)
    returns_array = np.array(trade_pnls)
    correlation = np.corrcoef(vol_rank_array, returns_array)[0, 1] if len(vol_rank_array) > 1 else 0.0
    
    return {
        "base_kelly_fraction": base_kelly_fraction,
        "fixed_metrics": fixed_metrics,
        "dynamic_metrics": dynamic_metrics,
        "improvement": improvement,
        "volatility_correlation": correlation,
        "avg_vol_rank": np.mean(vol_ranks),
        "vol_rank_range": [min(vol_ranks), max(vol_ranks)]
    }

def print_vix_rank_analysis(analysis: Dict[str, Any]):
    """
    Print formatted VIX-Rank analysis.
    
    Args:
        analysis: Analysis results from analyze_vix_rank_effectiveness
    """
    if "error" in analysis:
        print(f"Error: {analysis['error']}")
        return
    
    print("\n" + "="*70)
    print("VIX-RANK KELLY SCALING ANALYSIS")
    print("="*70)
    
    print(f"\nBase Kelly Fraction: {analysis['base_kelly_fraction']:.3f}")
    print(f"Volatility Rank Range: {analysis['vol_rank_range'][0]:.2f} - {analysis['vol_rank_range'][1]:.2f}")
    print(f"Average Vol Rank: {analysis['avg_vol_rank']:.2f}")
    print(f"Volatility-Return Correlation: {analysis['volatility_correlation']:.3f}")
    
    fixed = analysis.get("fixed_metrics", {})
    dynamic = analysis.get("dynamic_metrics", {})
    improvement = analysis.get("improvement", {})
    
    print(f"\nPerformance Comparison:")
    print("-" * 50)
    print(f"{'Metric':<12} {'Fixed':<12} {'Dynamic':<12} {'Improvement':<12}")
    print("-" * 50)
    
    for metric in ["total_return", "sharpe_ratio", "max_drawdown"]:
        fixed_val = fixed.get(metric, 0.0)
        dynamic_val = dynamic.get(metric, 0.0)
        
        if metric == "max_drawdown":
            # Drawdown improvement is positive when less negative
            imp = improvement.get("drawdown_improvement", 0.0)
            imp_str = f"{imp:.1%}"
        else:
            imp = improvement.get(f"{metric}_improvement", 0.0)
            imp_str = f"{imp:.1%}"
        
        print(f"{metric:<12} {fixed_val:<12.3f} {dynamic_val:<12.3f} {imp_str:<12}")
    
    print(f"\nRecommendations:")
    if improvement.get("return_improvement", 0) > 0.05:
        print("✅ VIX-Rank scaling significantly improves returns")
    elif improvement.get("return_improvement", 0) > 0.01:
        print("📈 VIX-Rank scaling modestly improves returns")
    else:
        print("⚠️ VIX-Rank scaling does not improve returns")
    
    if improvement.get("sharpe_improvement", 0) > 0.1:
        print("✅ VIX-Rank scaling improves risk-adjusted returns")
    elif improvement.get("sharpe_improvement", 0) > 0.05:
        print("📊 VIX-Rank scaling modestly improves risk-adjusted returns")
    else:
        print("⚠️ VIX-Rank scaling does not improve risk-adjusted returns")
    
    if improvement.get("drawdown_improvement", 0) > 0.1:
        print("✅ VIX-Rank scaling significantly reduces drawdowns")
    elif improvement.get("drawdown_improvement", 0) > 0.05:
        print("📉 VIX-Rank scaling modestly reduces drawdowns")
    else:
        print("⚠️ VIX-Rank scaling does not reduce drawdowns")
    
    print("="*70)

# Example usage for Kalshi integration:
"""
class KalshiVIXRankStrategy:
    def __init__(self, base_kelly_fraction=0.15, min_scale=0.25, max_scale=1.0):
        self.base_kelly_fraction = base_kelly_fraction
        self.min_scale = min_scale
        self.max_scale = max_scale
        self.historical_vols = []
        
    def update_volatility_history(self, realized_vol):
        # Update historical volatility for rank calculation
        self.historical_vols.append(realized_vol)
        
        # Keep only recent history (e.g., last 100 periods)
        if len(self.historical_vols) > 100:
            self.historical_vols = self.historical_vols[-100:]
    
    def calculate_current_vol_rank(self, current_vol):
        if not self.historical_vols:
            return 0.5  # Default to middle rank
        
        return calculate_vol_rank(np.array(self.historical_vols), current_vol)
    
    def get_dynamic_kelly_fraction(self, current_vol):
        vol_rank = self.calculate_current_vol_rank(current_vol)
        return kelly_with_vix_rank(
            self.base_kelly_fraction, vol_rank, 
            self.min_scale, self.max_scale
        )
    
    def calculate_position_size(self, base_position_size, current_vol, atr_multiplier=1.0):
        vol_rank = self.calculate_current_vol_rank(current_vol)
        return vix_rank_kelly_position_size(
            base_position_size, self.base_kelly_fraction, vol_rank,
            atr_multiplier, self.min_scale, self.max_scale
        )

# Usage:
# strategy = KalshiVIXRankStrategy(base_kelly_fraction=0.15)
# 
# On each trade opportunity:
# current_vol = calculate_realized_volatility()
# strategy.update_volatility_history(current_vol)
# dynamic_kelly = strategy.get_dynamic_kelly_fraction(current_vol)
# position_size = strategy.calculate_position_size(base_size, current_vol)
"""
