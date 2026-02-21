"""
Technical indicators for Kalshi sentiment trading.

RSI and SMA calculations for combining with sentiment signals.
"""

import numpy as np
import pandas as pd
from typing import List, Union, Optional
import logging

logger = logging.getLogger(__name__)


def rsi(series: Union[pd.Series, np.ndarray, List[float]], period: int = 14) -> np.ndarray:
    """
    Calculate Relative Strength Index (RSI).
    
    Standard RSI calculation with exponential smoothing.
    
    Args:
        series: Price series
        period: RSI period (default 14)
    
    Returns:
        Array of RSI values (0-100)
    """
    if isinstance(series, list):
        series = pd.Series(series)
    elif isinstance(series, np.ndarray):
        series = pd.Series(series)
    
    delta = series.diff()
    
    # Separate gains and losses
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    # Use exponential moving average for smoother RSI
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    
    # Calculate RS and RSI
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_val = 100 - (100 / (1 + rs))
    
    return rsi_val.fillna(50).values


def sma(series: Union[pd.Series, np.ndarray, List[float]], period: int = 20) -> np.ndarray:
    """
    Calculate Simple Moving Average.
    
    Args:
        series: Price series
        period: SMA period (default 20)
    
    Returns:
        Array of SMA values
    """
    if isinstance(series, list):
        series = pd.Series(series)
    elif isinstance(series, np.ndarray):
        series = pd.Series(series)
    
    return series.rolling(window=period, min_periods=1).mean().values


def ema(series: Union[pd.Series, np.ndarray, List[float]], period: int = 20) -> np.ndarray:
    """
    Calculate Exponential Moving Average.
    
    Args:
        series: Price series
        period: EMA period (default 20)
    
    Returns:
        Array of EMA values
    """
    if isinstance(series, list):
        series = pd.Series(series)
    elif isinstance(series, np.ndarray):
        series = pd.Series(series)
    
    return series.ewm(span=period, min_periods=1).mean().values


def add_technical_indicators(
    df: pd.DataFrame,
    price_col: str = "price",
    rsi_period: int = 14,
    sma_period: int = 20,
) -> pd.DataFrame:
    """
    Add RSI and SMA to a DataFrame.
    
    Args:
        df: DataFrame with price data
        price_col: Column name for price
        rsi_period: RSI calculation period
        sma_period: SMA calculation period
    
    Returns:
        DataFrame with added 'rsi_14' and 'sma_20' columns
    """
    result = df.copy()
    
    # RSI
    result["rsi_14"] = rsi(result[price_col], rsi_period)
    
    # SMA
    result["sma_20"] = sma(result[price_col], sma_period)
    
    # Above/below SMA flag
    result["above_sma"] = (result[price_col] > result["sma_20"]).astype(int)
    
    # Distance from SMA (as percentage)
    result["sma_dist_pct"] = ((result[price_col] - result["sma_20"]) / result["sma_20"]) * 100
    
    return result


def get_tech_signal(
    rsi_val: float,
    above_sma: bool,
    rsi_low: float = 30,
    rsi_high: float = 70,
) -> str:
    """
    Get technical signal based on RSI and SMA.
    
    Args:
        rsi_val: Current RSI value
        above_sma: Whether price is above SMA
        rsi_low: Oversold threshold
        rsi_high: Overbought threshold
    
    Returns:
        Signal string: 'bullish', 'bearish', or 'neutral'
    """
    # Bullish: above SMA with RSI not overbought
    if above_sma and rsi_val < rsi_high:
        return "bullish"
    
    # Bearish: below SMA with RSI not oversold
    if not above_sma and rsi_val > rsi_low:
        return "bearish"
    
    # Neutral: mixed signals
    return "neutral"


# ── Convenience functions ──────────────────────────────────────────

def quick_rsi(prices: List[float], period: int = 14) -> float:
    """Quick RSI calculation for last value."""
    if len(prices) < period:
        return 50.0
    return float(rsi(prices, period)[-1])


def quick_sma(prices: List[float], period: int = 20) -> float:
    """Quick SMA calculation."""
    if len(prices) < period:
        return sum(prices) / len(prices) if prices else 0.0
    return float(sma(prices, period)[-1])
