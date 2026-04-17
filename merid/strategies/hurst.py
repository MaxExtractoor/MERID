"""
Hurst Exponent Filter - Mean Reversion Regime Detection

Use Hurst to decide if the series is currently in a mean-reverting regime (H < 0.5).
"""

import numpy as np
import pandas as pd
import logging
from typing import Union

logger = logging.getLogger(__name__)

def hurst_exponent(series: np.ndarray, min_lag: int = 2, max_lag: int = 50) -> float:
    """
    Simple R/S-based Hurst exponent estimator.
    
    The Hurst exponent H characterizes the long-term memory of a time series:
    - H < 0.5: Mean-reverting (anti-persistent)
    - H = 0.5: Random walk (Brownian motion)
    - H > 0.5: Trending (persistent)
    
    Args:
        series: Price series as numpy array
        min_lag: Minimum lag for R/S calculation
        max_lag: Maximum lag for R/S calculation
        
    Returns:
        Hurst exponent H
    """
    if len(series) < max_lag + 1:
        logger.warning(f"Series too short for Hurst calculation: {len(series)} < {max_lag + 1}")
        return 0.5  # Return neutral value
    
    # Calculate range over standard deviation for different lags
    lags = range(min_lag, max_lag)
    tau = []
    
    for lag in lags:
        # Calculate range (max - min) for given lag
        diff = np.subtract(series[lag:], series[:-lag])
        range_val = np.max(diff) - np.min(diff)
        
        # Calculate standard deviation
        std_dev = np.std(diff)
        
        # R/S ratio
        if std_dev > 0:
            tau.append(range_val / std_dev)
        else:
            tau.append(0.0)
    
    tau = np.array(tau)
    
    # Filter out zero values to avoid log(0)
    valid_indices = tau > 0
    if not np.any(valid_indices):
        logger.warning("All tau values are zero, returning H=0.5")
        return 0.5
    
    lags_valid = np.array(lags)[valid_indices]
    tau_valid = tau[valid_indices]
    
    # Log-log regression to estimate Hurst exponent
    try:
        # Fit line: log(tau) = H * log(lags) + C
        poly = np.polyfit(np.log(lags_valid), np.log(tau_valid), 1)
        H = poly[0]
        
        # Clip to reasonable bounds
        H = max(0.0, min(1.0, H))
        
        logger.debug(f"Hurst exponent: {H:.3f} (lags: {min_lag}-{max_lag})")
        
        return float(H)
        
    except Exception as e:
        logger.error(f"Error in Hurst calculation: {e}")
        return 0.5

def is_mean_reverting(
    prices: Union[np.ndarray, pd.Series], 
    min_lag: int = 10, 
    max_lag: int = 80, 
    hurst_thresh: float = 0.5
) -> bool:
    """
    Determine if series is in mean-reverting regime using Hurst exponent.
    
    Args:
        prices: Price series (numpy array or pandas Series)
        min_lag: Minimum lag for Hurst calculation
        max_lag: Maximum lag for Hurst calculation
        hurst_thresh: Threshold for mean reversion (H < thresh)
        
    Returns:
        True if mean-reverting, False otherwise
    """
    if isinstance(prices, pd.Series):
        prices = prices.values
    
    H = hurst_exponent(prices, min_lag=min_lag, max_lag=max_lag)
    mean_reverting = H < hurst_thresh
    
    logger.debug(f"Mean-reverting check: H={H:.3f}, threshold={hurst_thresh}, result={mean_reverting}")
    
    return mean_reverting

def calculate_hurst_rolling(
    prices: Union[np.ndarray, pd.Series],
    window: int = 200,
    min_lag: int = 10,
    max_lag: int = 50
) -> pd.Series:
    """
    Calculate rolling Hurst exponent for regime detection.
    
    Args:
        prices: Price series
        window: Rolling window size
        min_lag: Minimum lag for each Hurst calculation
        max_lag: Maximum lag for each Hurst calculation
        
    Returns:
        Pandas Series of rolling Hurst exponents
    """
    if isinstance(prices, np.ndarray):
        prices = pd.Series(prices)
    
    hurst_values = []
    
    for i in range(window, len(prices)):
        window_prices = prices.iloc[i-window:i].values
        H = hurst_exponent(window_prices, min_lag=min_lag, max_lag=max_lag)
        hurst_values.append(H)
    
    # Create series with proper index
    index = prices.index[window:]
    hurst_series = pd.Series(hurst_values, index=index)
    
    return hurst_series

def analyze_regime_changes(
    prices: Union[np.ndarray, pd.Series],
    window: int = 200,
    hurst_thresh: float = 0.5,
    min_regime_duration: int = 20
) -> dict:
    """
    Analyze regime changes based on rolling Hurst exponent.
    
    Args:
        prices: Price series
        window: Rolling window for Hurst calculation
        hurst_thresh: Threshold for regime classification
        min_regime_duration: Minimum periods for regime change
        
    Returns:
        Dictionary with regime analysis results
    """
    if isinstance(prices, np.ndarray):
        prices = pd.Series(prices)
    
    # Calculate rolling Hurst
    hurst_series = calculate_hurst_rolling(prices, window=window)
    
    # Classify regimes
    regimes = (hurst_series < hurst_thresh).astype(int)  # 1 for mean-reverting, 0 for trending
    
    # Find regime changes
    regime_changes = regimes.diff().fillna(0)
    change_points = regime_changes[regime_changes != 0].index
    
    # Calculate regime durations
    regime_durations = []
    current_regime = regimes.iloc[0]
    regime_start = regimes.index[0]
    
    for i, (timestamp, regime) in enumerate(regimes.items()):
        if regime != current_regime:
            duration = i - (regimes.index.get_loc(regime_start) if regime_start in regimes.index else 0)
            regime_durations.append({
                'start': regime_start,
                'end': timestamp,
                'regime': 'mean_reverting' if current_regime == 1 else 'trending',
                'duration': duration
            })
            current_regime = regime
            regime_start = timestamp
    
    # Add final regime
    final_duration = len(regimes) - (regimes.index.get_loc(regime_start) if regime_start in regimes.index else 0)
    regime_durations.append({
        'start': regime_start,
        'end': regimes.index[-1],
        'regime': 'mean_reverting' if current_regime == 1 else 'trending',
        'duration': final_duration
    })
    
    # Filter short regimes
    significant_regimes = [r for r in regime_durations if r['duration'] >= min_regime_duration]
    
    return {
        'current_hurst': hurst_series.iloc[-1] if not hurst_series.empty else 0.5,
        'current_regime': 'mean_reverting' if (hurst_series.iloc[-1] if not hurst_series.empty else 0.5) < hurst_thresh else 'trending',
        'regime_changes': len(change_points),
        'significant_regimes': significant_regimes,
        'avg_mean_reverting_duration': np.mean([r['duration'] for r in significant_regimes if r['regime'] == 'mean_reverting']) if significant_regimes else 0,
        'avg_trending_duration': np.mean([r['duration'] for r in significant_regimes if r['regime'] == 'trending']) if significant_regimes else 0
    }

def validate_hurst_calculation(prices: Union[np.ndarray, pd.Series]) -> dict:
    """
    Validate Hurst calculation and provide diagnostics.
    
    Args:
        prices: Price series to validate
        
    Returns:
        Dictionary with validation results
    """
    if isinstance(prices, pd.Series):
        prices = prices.values
    
    validation = {
        'valid': True,
        'warnings': [],
        'recommendations': [],
        'hurst_values': {}
    }
    
    # Check data length
    if len(prices) < 100:
        validation['warnings'].append(f"Short series: {len(prices)} points")
        validation['recommendations'].append("Use at least 100 data points for reliable Hurst")
    
    # Check for constant values
    if np.std(prices) == 0:
        validation['warnings'].append("Constant price series")
        validation['recommendations'].append("Price series has no variance")
        validation['valid'] = False
        return validation
    
    # Calculate Hurst with different parameters
    for min_lag, max_lag in [(2, 20), (5, 50), (10, 80)]:
        if len(prices) > max_lag:
            H = hurst_exponent(prices, min_lag=min_lag, max_lag=max_lag)
            validation['hurst_values'][f'{min_lag}-{max_lag}'] = H
    
    # Check consistency
    hurst_vals = list(validation['hurst_values'].values())
    if len(hurst_vals) > 1:
        h_std = np.std(hurst_vals)
        if h_std > 0.1:
            validation['warnings'].append(f"Inconsistent Hurst values: std={h_std:.3f}")
            validation['recommendations'].append("Hurst estimates vary significantly with parameters")
    
    return validation

# Example usage:
"""
import numpy as np

# Generate random walk (should have H ≈ 0.5)
np.random.seed(42)
random_walk = np.cumsum(np.random.randn(1000))
H_rw = hurst_exponent(random_walk)
print(f"Random walk Hurst: {H_rw:.3f}")

# Generate mean-reverting series (should have H < 0.5)
mean_reverting = np.sin(np.linspace(0, 50*np.pi, 1000)) + np.random.randn(1000) * 0.1
H_mr = hurst_exponent(mean_reverting)
print(f"Mean-reverting Hurst: {H_mr:.3f}")

# Check if mean-reverting
is_mr = is_mean_reverting(mean_reverting)
print(f"Is mean-reverting: {is_mr}")

# Analyze regime changes
regime_analysis = analyze_regime_changes(mean_reverting)
print(f"Regime analysis: {regime_analysis}")
"""
