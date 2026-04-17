"""
Fibonacci-weighted sentiment smoothing for Kalshi markets.

Applies Fibonacci weighting to recent sentiment values, giving more
weight to recent data while maintaining a smoothed signal.
"""

import numpy as np
from typing import List, Union
from utils.logger import get_logger

logger = get_logger(__name__)

# Fibonacci weights for 7-point window
FIB_WEIGHTS = np.array([1, 1, 2, 3, 5, 8, 13], dtype=float)
FIB_WEIGHTS = FIB_WEIGHTS / FIB_WEIGHTS.sum()


def fib_blend(values: List[float]) -> float:
    """
    Blend values using Fibonacci weights.
    
    Shorter series uses last n Fibonacci weights normalized.
    
    Args:
        values: List of values to blend
    
    Returns:
        Weighted average using Fibonacci weights
    """
    n = len(values)
    if n == 0:
        return 0.0
    
    # Use last n Fibonacci weights
    w = FIB_WEIGHTS[-n:]
    v = np.array(values, dtype=float)
    
    # Normalize weights
    w = w / w.sum()
    
    return float((v * w).sum())


def fib_smooth_series(
    series: np.ndarray,
    window: int = 7,
) -> np.ndarray:
    """
    Apply Fibonacci smoothing to a numpy array.
    
    Args:
        series: Input array of sentiment values
        window: Smoothing window size (default 7)
    
    Returns:
        Smoothed array
    """
    if len(series) < window:
        # For short series, use simple mean
        return np.array([series.mean()] * len(series))
    
    result = np.zeros_like(series)
    
    for i in range(len(series)):
        if i < window - 1:
            # Not enough data, use available values
            values = series[:i+1].tolist()
            result[i] = fib_blend(values)
        else:
            # Full window
            values = series[i-window+1:i+1].tolist()
            result[i] = fib_blend(values)
    
    return result


def fib_smooth_sentiment_data(
    data: List[float],
    window: int = 7,
) -> List[float]:
    """
    Apply Fibonacci smoothing to sentiment data.
    
    Args:
        data: List of sentiment values (-1 to 1)
        window: Smoothing window
    
    Returns:
        Smoothed values
    """
    series = np.array(data)
    smoothed = fib_smooth_series(series, window)
    return smoothed.tolist()


# ── Convenience function ─────────────────────────────────────────────

def quick_fib_smooth(values: List[float]) -> float:
    """Quick one-liner to get Fibonacci-smoothed value."""
    return fib_blend(values)
