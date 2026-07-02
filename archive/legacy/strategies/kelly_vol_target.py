"""
Kelly Volatility Targeting for Kalshi Events

Volatility targeting with Kelly on Kalshi events for MERID.
"""

import numpy as np
import pandas as pd
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)

def realized_vol(returns: pd.Series, periods_per_year: int) -> float:
    """
    Calculate realized volatility from returns series.
    
    Args:
        returns: Series of per-trade returns
        periods_per_year: Number of periods per year for annualization
        
    Returns:
        Realized volatility (annualized)
    """
    if returns.empty:
        return 0.0
    
    sigma = returns.std()
    return float(sigma * np.sqrt(periods_per_year))

def vol_targeted_fraction(
    base_fraction: float,
    per_trade_returns: pd.Series,
    target_vol: float = 0.20,
    periods_per_year: int = 365 * 24 * 4,  # ~15m periods
) -> float:
    """
    Scale base_fraction to match target volatility.
    
    Args:
        base_fraction: Base Kelly fraction (e.g., half Kelly)
        per_trade_returns: Series of per-trade returns from Kalshi fills
        target_vol: Target annual volatility (default 20%)
        periods_per_year: Number of periods per year
        
    Returns:
        Volatility-targeted Kelly fraction
    """
    if per_trade_returns.empty:
        return base_fraction
    
    cur_vol = realized_vol(per_trade_returns, periods_per_year)
    
    if cur_vol <= 0 or np.isnan(cur_vol):
        return base_fraction
    
    # Scale factor to match target volatility
    scale = target_vol / cur_vol
    
    # Cap to avoid crazy jumps (max 2x base fraction)
    capped_scale = min(scale, 2.0)
    
    adjusted_fraction = base_fraction * capped_scale
    
    logger.debug(f"Vol targeting: base={base_fraction:.3f}, cur_vol={cur_vol:.2%}, "
                f"target={target_vol:.2%}, scale={scale:.2f}, capped={capped_scale:.2f}, "
                f"adjusted={adjusted_fraction:.3f}")
    
    return adjusted_fraction

def update_live_kelly_fraction(
    base_kelly_fraction: float,
    recent_trade_returns: List[float],
    target_vol: float = 0.20,
    lookback: int = 200
) -> float:
    """
    Update live Kelly fraction based on recent trade returns.
    
    Args:
        base_kelly_fraction: Base Kelly fraction from backtest
        recent_trade_returns: List of recent per-trade returns
        target_vol: Target volatility
        lookback: Number of recent trades to consider
        
    Returns:
        Updated Kelly fraction
    """
    if not recent_trade_returns:
        return base_kelly_fraction
    
    # Use last N trades for volatility calculation
    returns_series = pd.Series(recent_trade_returns[-lookback:])
    
    return vol_targeted_fraction(base_kelly_fraction, returns_series, target_vol)

def calculate_kelly_volatility_adjustment(
    base_fraction: float,
    trade_returns: List[float],
    target_vol: float = 0.20,
    min_periods: int = 20
) -> dict:
    """
    Calculate comprehensive volatility adjustment metrics.
    
    Args:
        base_fraction: Base Kelly fraction
        trade_returns: List of per-trade returns
        target_vol: Target volatility
        min_periods: Minimum periods for calculation
        
    Returns:
        Volatility adjustment analysis
    """
    if len(trade_returns) < min_periods:
        return {
            "base_fraction": base_fraction,
            "adjusted_fraction": base_fraction,
            "current_vol": 0.0,
            "target_vol": target_vol,
            "scale_factor": 1.0,
            "status": "insufficient_data"
        }
    
    returns_series = pd.Series(trade_returns)
    
    # Calculate current volatility
    periods_per_year = 365 * 24 * 4  # ~15m periods
    current_vol = realized_vol(returns_series, periods_per_year)
    
    # Calculate adjusted fraction
    adjusted_fraction = vol_targeted_fraction(base_fraction, returns_series, target_vol, periods_per_year)
    
    # Calculate scale factor
    scale_factor = adjusted_fraction / base_fraction if base_fraction > 0 else 1.0
    
    # Determine status
    if current_vol <= 0 or np.isnan(current_vol):
        status = "invalid_vol"
    elif scale_factor > 1.5:
        status = "high_adjustment"
    elif scale_factor < 0.5:
        status = "low_adjustment"
    else:
        status = "normal"
    
    return {
        "base_fraction": base_fraction,
        "adjusted_fraction": adjusted_fraction,
        "current_vol": current_vol,
        "target_vol": target_vol,
        "scale_factor": scale_factor,
        "status": status,
        "volatility_ratio": current_vol / target_vol if target_vol > 0 else 0.0
    }

def adaptive_volatility_targeting(
    base_fraction: float,
    trade_returns: List[float],
    target_vol: float = 0.20,
    window_sizes: List[int] = None,
    min_periods: int = 20
) -> dict:
    """
    Adaptive volatility targeting with multiple window sizes.
    
    Args:
        base_fraction: Base Kelly fraction
        trade_returns: List of per-trade returns
        target_vol: Target volatility
        window_sizes: List of window sizes to test
        min_periods: Minimum periods for calculation
        
    Returns:
        Adaptive volatility targeting results
    """
    if window_sizes is None:
        window_sizes = [50, 100, 200, 400]  # Different lookback periods
    
    if len(trade_returns) < min_periods:
        return {
            "base_fraction": base_fraction,
            "adjusted_fraction": base_fraction,
            "recommendations": ["insufficient_data"],
            "window_results": {}
        }
    
    returns_series = pd.Series(trade_returns)
    window_results = {}
    
    for window in window_sizes:
        if len(trade_returns) >= window:
            window_returns_data = trade_returns[-window:]
            adjustment = calculate_kelly_volatility_adjustment(
                base_fraction, window_returns_data, target_vol, min_periods
            )
            window_results[window] = adjustment
    
    if not window_results:
        return {
            "base_fraction": base_fraction,
            "adjusted_fraction": base_fraction,
            "recommendations": ["no_valid_windows"],
            "window_results": {}
        }
    
    # Find consensus adjustment
    valid_adjustments = [r for r in window_results.values() if r["status"] == "normal"]
    
    if valid_adjustments:
        # Use median of valid adjustments
        adjusted_fractions = [r["adjusted_fraction"] for r in valid_adjustments]
        consensus_fraction = np.median(adjusted_fractions)
        
        # Generate recommendations
        recommendations = []
        if consensus_fraction > base_fraction * 1.2:
            recommendations.append("consider_increasing_base_fraction")
        elif consensus_fraction < base_fraction * 0.8:
            recommendations.append("consider_decreasing_base_fraction")
        else:
            recommendations.append("current_base_fraction_appropriate")
        
        if len(valid_adjustments) < len(window_results):
            recommendations.append("some_windows_show_extreme_volatility")
        
    else:
        # Use most recent window if no normal adjustments
        recent_window = min(window_sizes.keys())
        consensus_fraction = window_results[recent_window]["adjusted_fraction"]
        recommendations = ["high_volatility_detected"]
    
    return {
        "base_fraction": base_fraction,
        "adjusted_fraction": consensus_fraction,
        "recommendations": recommendations,
        "window_results": window_results
    }

def validate_volatility_targeting(
    base_fraction: float,
    target_vol: float,
    current_vol: float,
    adjusted_fraction: float
) -> dict:
    """
    Validate volatility targeting parameters and provide recommendations.
    
    Args:
        base_fraction: Base Kelly fraction
        target_vol: Target volatility
        current_vol: Current realized volatility
        adjusted_fraction: Adjusted fraction
        
    Returns:
        Validation results
    """
    validation = {
        "valid": True,
        "warnings": [],
        "recommendations": []
    }
    
    # Validate base fraction
    if not (0.0 < base_fraction <= 1.0):
        validation["warnings"].append(f"Invalid base fraction: {base_fraction}")
        validation["recommendations"].append("Base fraction should be between 0 and 1")
        validation["valid"] = False
    
    # Validate target volatility
    if not (0.05 <= target_vol <= 1.0):
        validation["warnings"].append(f"Unusual target volatility: {target_vol:.1%}")
        validation["recommendations"].append("Target volatility typically 5-100% annually")
    
    # Validate current volatility
    if current_vol <= 0 or np.isnan(current_vol):
        validation["warnings"].append(f"Invalid current volatility: {current_vol}")
        validation["recommendations"].append("Check trade returns data quality")
        validation["valid"] = False
    
    # Check adjustment magnitude
    if base_fraction > 0:
        adjustment_ratio = adjusted_fraction / base_fraction
        if adjustment_ratio > 2.0:
            validation["warnings"].append(f"Very large adjustment: {adjustment_ratio:.1f}x")
            validation["recommendations"].append("Consider reducing target volatility")
        elif adjustment_ratio < 0.1:
            validation["warnings"].append(f"Very small adjustment: {adjustment_ratio:.1f}x")
            validation["recommendations"].append("Consider increasing target volatility")
    
    # Volatility regime assessment
    if current_vol > target_vol * 2:
        validation["warnings"].append(f"Current volatility {current_vol:.1%} much higher than target {target_vol:.1%}")
        validation["recommendations"].append("Market in high volatility regime - reduce exposure")
    elif current_vol < target_vol * 0.5:
        validation["warnings"].append(f"Current volatility {current_vol:.1%} much lower than target {target_vol:.1%}")
        validation["recommendations"].append("Market in low volatility regime - consider increasing exposure")
    
    return validation

# Example usage for Kalshi events:
"""
# In Kalshi event subscriber that tracks trades
class KalshiTradeSubscriber:
    def __init__(self):
        self.trade_returns = []
        self.base_kelly_fraction = 0.15  # Half Kelly from backtest
        self.target_volatility = 0.20
        self.current_kelly_fraction = self.base_kelly_fraction
    
    def on_trade_filled(self, trade_event):
        # Calculate per-trade return
        trade_return = (trade_event.exit_price - trade_event.entry_price) / trade_event.entry_price
        kelly_return = self.current_kelly_fraction * trade_return
        
        # Add to returns list
        self.trade_returns.append(kelly_return)
        
        # Update Kelly fraction periodically (e.g., every 50 trades)
        if len(self.trade_returns) % 50 == 0:
            self.current_kelly_fraction = update_live_kelly_fraction(
                self.base_kelly_fraction, 
                self.trade_returns, 
                self.target_volatility
            )
            
            logger.info(f"Updated Kelly fraction: {self.current_kelly_fraction:.3f}")
    
    def get_position_size(self, base_position_size):
        # Scale position size by current Kelly fraction
        kelly_adjustment = self.current_kelly_fraction / self.base_kelly_fraction
        return base_position_size * kelly_adjustment

# Usage:
subscriber = KalshiTradeSubscriber()
# On each trade fill:
# subscriber.on_trade_filled(trade_event)
# position_size = subscriber.get_position_size(base_size)
"""
