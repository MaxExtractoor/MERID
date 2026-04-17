"""
Fibonacci Retracements for Kalshi Backtests

Compute Fibonacci levels on underlying assets (e.g., BTC spot) and use them
as features for Kalshi BTC markets. Useful for identifying support/resistance
and entry/exit timing.
"""

import pandas as pd
import numpy as np
from typing import Any, Dict, List, Tuple, Optional
from dataclasses import dataclass
from utils.logger import get_logger

logger = get_logger(__name__)

# Standard Fibonacci retracement levels
FIB_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.786]


@dataclass
class FibLevels:
    """Fibonacci retracement levels for a price range."""
    high: float
    low: float
    levels: Dict[float, float]  # level -> price
    
    def get_level(self, level: float) -> float:
        """Get price at a specific Fibonacci level."""
        return self.levels.get(level, 0.0)
    
    def is_near_level(
        self,
        price: float,
        level: float,
        tolerance_pct: float = 0.005,
    ) -> bool:
        """Check if price is near a specific Fib level."""
        level_price = self.get_level(level)
        diff_pct = abs(price - level_price) / price
        return diff_pct < tolerance_pct


def fib_retracements(high: float, low: float) -> Dict[float, float]:
    """
    Compute Fibonacci retracement levels for a price range.
    
    Args:
        high: High price
        low: Low price
    
    Returns:
        Dict mapping Fib level to price
    """
    diff = high - low
    return {lvl: high - lvl * diff for lvl in FIB_LEVELS}


def add_fib_to_df(
    price_df: pd.DataFrame,
    window: int = 100,
    price_col: str = "underlying_price",
) -> pd.DataFrame:
    """
    Add Fibonacci retracement levels to price DataFrame.
    
    Args:
        price_df: DataFrame with price column
        window: Rolling window for high/low calculation
        price_col: Column name for price data
    
    Returns:
        DataFrame with added Fib columns and proximity flags
    """
    df = price_df.copy()
    
    # Compute rolling highs and lows
    highs = df[price_col].rolling(window=window, min_periods=window//2).max()
    lows = df[price_col].rolling(window=window, min_periods=window//2).min()
    
    # Add Fib levels
    for lvl in FIB_LEVELS:
        col_name = f"fib_{int(lvl*1000)}"  # e.g., fib_618
        df[col_name] = highs - lvl * (highs - lows)
    
    # Add proximity flags (within 0.5% of level)
    tolerance = 0.005
    
    # Key levels: 0.382, 0.5, 0.618
    key_levels = [0.382, 0.5, 0.618]
    for lvl in key_levels:
        col_name = f"fib_{int(lvl*1000)}"
        flag_name = f"near_{int(lvl*1000)}"
        df[flag_name] = (
            (df[price_col] - df[col_name]).abs() / df[price_col]
        ) < tolerance
    
    # Combined flag: near any key level
    df["near_fib"] = df[[f"near_{int(lvl*1000)}" for lvl in key_levels]].any(axis=1)
    
    # Add current Fib context
    df["fib_618_dist"] = (df[price_col] - df["fib_618"]) / (highs - lows)
    df["fib_position"] = (highs - df[price_col]) / (highs - lows)  # 0=high, 1=low
    
    return df


def get_fib_signal(
    price: float,
    high: float,
    low: float,
    sentiment: float,
    tolerance: float = 0.005,
) -> Dict[str, Any]:
    """
    Generate trading signal based on Fib levels and sentiment.
    
    Logic:
    - Near 0.618 retracement + bullish sentiment = potential bounce (long)
    - Near 0.382 retracement + bearish sentiment = potential rejection (short)
    - Near 0.5 = neutral/wait
    
    Args:
        price: Current price
        high: Recent high
        low: Recent low
        sentiment: Combined sentiment -1 to 1
        tolerance: Proximity tolerance
    
    Returns:
        Signal dict with recommendation
    """
    fibs = fib_retracements(high, low)
    
    # Find nearest level
    nearest_level = None
    nearest_dist = float('inf')
    
    for lvl, lvl_price in fibs.items():
        dist = abs(price - lvl_price) / price
        if dist < nearest_dist:
            nearest_dist = dist
            nearest_level = lvl
    
    # Check if near enough
    if nearest_dist > tolerance:
        return {
            "signal": "neutral",
            "nearest_fib": nearest_level,
            "distance": nearest_dist,
            "reason": "Not near any Fib level",
        }
    
    # Generate signal based on level and sentiment
    lvl_price = fibs[nearest_level]
    
    # 0.618 (deep retracement) - often support in uptrend
    if nearest_level == 0.618 and sentiment > 0.2:
        return {
            "signal": "long",
            "strength": sentiment,
            "nearest_fib": 0.618,
            "distance": nearest_dist,
            "reason": "Near 0.618 retracement + bullish sentiment",
        }
    
    # 0.382 (shallow retracement) - often resistance
    if nearest_level == 0.382 and sentiment < -0.2:
        return {
            "signal": "short",
            "strength": abs(sentiment),
            "nearest_fib": 0.382,
            "distance": nearest_dist,
            "reason": "Near 0.382 retracement + bearish sentiment",
        }
    
    # 0.5 - neutral, wait for break
    if nearest_level == 0.5:
        return {
            "signal": "neutral",
            "nearest_fib": 0.5,
            "distance": nearest_dist,
            "reason": "At 0.5 Fibonacci - wait for direction",
        }
    
    # Default
    return {
        "signal": "neutral",
        "nearest_fib": nearest_level,
        "distance": nearest_dist,
        "reason": f"Near {nearest_level} Fib but no clear signal",
    }


class FibSentimentStrategy:
    """
    Trading strategy combining Fibonacci levels with sentiment.
    
    Usage:
        strategy = FibSentimentStrategy()
        
        # Check entry conditions
        signal = strategy.check_entry(
            price=55000,
            high=60000,
            low=50000,
            sentiment=0.4,
        )
    """
    
    def __init__(
        self,
        fib_window: int = 100,
        tolerance: float = 0.005,
        min_sentiment: float = 0.2,
    ):
        self.fib_window = fib_window
        self.tolerance = tolerance
        self.min_sentiment = min_sentiment
    
    def check_entry(
        self,
        price: float,
        high: float,
        low: float,
        sentiment: float,
    ) -> Dict[str, Any]:
        """
        Check if entry conditions are met.
        
        Returns:
            Entry signal dict
        """
        fib_signal = get_fib_signal(
            price, high, low, sentiment, self.tolerance
        )
        
        # Require sentiment confirmation
        if fib_signal["signal"] == "long" and sentiment < self.min_sentiment:
            return {
                "action": "none",
                "reason": f"Fib long signal but sentiment {sentiment:+.2f} < {self.min_sentiment}",
            }
        
        if fib_signal["signal"] == "short" and sentiment > -self.min_sentiment:
            return {
                "action": "none",
                "reason": f"Fib short signal but sentiment {sentiment:+.2f} > -{self.min_sentiment}",
            }
        
        return {
            "action": fib_signal["signal"],
            "strength": fib_signal.get("strength", 0.0),
            "nearest_fib": fib_signal["nearest_fib"],
            "reason": fib_signal["reason"],
        }
    
    def check_exit(
        self,
        entry_price: float,
        current_price: float,
        high: float,
        low: float,
        sentiment: float,
        position_side: str,
    ) -> Dict[str, Any]:
        """
        Check if exit conditions are met.
        
        Args:
            entry_price: Entry price
            current_price: Current price
            high: Recent high
            low: Recent low
            sentiment: Current sentiment
            position_side: 'long' or 'short'
        
        Returns:
            Exit signal dict
        """
        fibs = fib_retracements(high, low)
        
        # For longs: take profit at 0.382, stop at 0.786
        if position_side == "long":
            if current_price >= fibs[0.382]:
                return {
                    "action": "take_profit",
                    "reason": f"Reached 0.382 Fib ({fibs[0.382]:.2f})",
                }
            
            if current_price <= fibs[0.786]:
                return {
                    "action": "stop_loss",
                    "reason": f"Broke 0.786 Fib ({fibs[0.786]:.2f})",
                }
            
            # Sentiment flip
            if sentiment < -0.3:
                return {
                    "action": "exit",
                    "reason": f"Sentiment turned bearish ({sentiment:+.2f})",
                }
        
        # For shorts: take profit at 0.618, stop at 0.0 (new high)
        if position_side == "short":
            if current_price <= fibs[0.618]:
                return {
                    "action": "take_profit",
                    "reason": f"Reached 0.618 Fib ({fibs[0.618]:.2f})",
                }
            
            if current_price >= high:
                return {
                    "action": "stop_loss",
                    "reason": "Broke to new high",
                }
            
            # Sentiment flip
            if sentiment > 0.3:
                return {
                    "action": "exit",
                    "reason": f"Sentiment turned bullish ({sentiment:+.2f})",
                }
        
        return {
            "action": "hold",
            "reason": "No exit condition met",
        }


# ── Convenience functions ──────────────────────────────────────────

def quick_fib_levels(high: float, low: float) -> List[Tuple[float, float]]:
    """
    Quick one-liner to get Fibonacci levels.
    
    Returns:
        List of (level, price) tuples
    """
    fibs = fib_retracements(high, low)
    return [(lvl, price) for lvl, price in fibs.items()]


def quick_fib_signal(
    price: float,
    high: float,
    low: float,
    sentiment: float,
) -> str:
    """
    Quick one-liner to get Fib + sentiment signal.
    
    Returns:
        Signal string: 'long', 'short', or 'neutral'
    """
    result = get_fib_signal(price, high, low, sentiment)
    return result["signal"]
