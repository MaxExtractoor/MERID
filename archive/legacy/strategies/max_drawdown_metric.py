"""
Max Drawdown Metric - Standard Peak-to-Trough Calculation

Standard peak-to-trough over peak definition for risk analysis.
"""

import pandas as pd
import numpy as np
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

def max_drawdown(equity: pd.Series) -> float:
    """
    Calculate maximum drawdown from equity curve.
    
    Args:
        equity: Series of cumulative PnL or equity
        
    Returns:
        Maximum drawdown as a negative fraction of peak (e.g., -0.2 for -20%)
    """
    if equity.empty:
        logger.warning("Empty equity series for drawdown calculation")
        return 0.0
    
    # Calculate running peak
    peak = equity.cummax()
    
    # Calculate drawdown
    dd = (equity - peak) / peak.replace(0, np.nan)
    
    # Return maximum drawdown
    max_dd = dd.min()
    
    return float(max_dd) if not np.isnan(max_dd) else 0.0

def max_drawdown_duration(equity: pd.Series) -> Tuple[int, pd.Timestamp, pd.Timestamp]:
    """
    Calculate maximum drawdown duration.
    
    Args:
        equity: Equity curve
        
    Returns:
        Tuple of (duration in periods, start_time, end_time)
    """
    if equity.empty:
        return 0, None, None
    
    # Calculate running peak
    peak = equity.cummax()
    
    # Find drawdown periods
    in_drawdown = equity < peak
    
    if not in_drawdown.any():
        return 0, None, None
    
    # Find drawdown periods
    drawdown_periods = []
    start = None
    
    for i, (timestamp, is_dd) in enumerate(in_drawdown.items()):
        if is_dd and start is None:
            start = timestamp
        elif not is_dd and start is not None:
            drawdown_periods.append((start, equity.index[i-1]))
            start = None
    
    # Handle ongoing drawdown
    if start is not None:
        drawdown_periods.append((start, equity.index[-1]))
    
    if not drawdown_periods:
        return 0, None, None
    
    # Find longest drawdown period
    max_duration = 0
    max_start, max_end = None, None
    
    for start, end in drawdown_periods:
        duration = len(equity.loc[start:end])
        if duration > max_duration:
            max_duration = duration
            max_start, max_end = start, end
    
    return max_duration, max_start, max_end

def drawdown_statistics(equity: pd.Series) -> dict:
    """
    Calculate comprehensive drawdown statistics.
    
    Args:
        equity: Equity curve
        
    Returns:
        Dictionary with drawdown statistics
    """
    if equity.empty:
        return {
            "max_drawdown": 0.0,
            "max_dd_duration": 0,
            "avg_drawdown": 0.0,
            "drawdown_frequency": 0.0,
            "recovery_time_avg": 0.0
        }
    
    # Calculate running peak
    peak = equity.cummax()
    
    # Calculate drawdown series
    dd_series = (equity - peak) / peak.replace(0, np.nan)
    
    # Basic statistics
    max_dd = dd_series.min()
    avg_dd = dd_series[dd_series < 0].mean() if (dd_series < 0).any() else 0.0
    
    # Drawdown frequency
    in_drawdown = dd_series < 0
    drawdown_frequency = in_drawdown.sum() / len(equity)
    
    # Recovery times
    recovery_times = []
    in_dd_period = False
    dd_start = None
    
    for i, (timestamp, is_dd) in enumerate(in_drawdown.items()):
        if is_dd and not in_dd_period:
            # Start of drawdown
            in_dd_period = True
            dd_start = timestamp
        elif not is_dd and in_dd_period:
            # End of drawdown - recovery
            recovery_time = i - equity.index.get_loc(dd_start)
            recovery_times.append(recovery_time)
            in_dd_period = False
    
    avg_recovery_time = np.mean(recovery_times) if recovery_times else 0.0
    
    # Max drawdown duration
    max_dd_duration, dd_start_time, dd_end_time = max_drawdown_duration(equity)
    
    return {
        "max_drawdown": float(max_dd),
        "max_dd_duration": max_dd_duration,
        "avg_drawdown": float(avg_dd),
        "drawdown_frequency": float(drawdown_frequency),
        "recovery_time_avg": float(avg_recovery_time),
        "max_dd_start": dd_start_time,
        "max_dd_end": dd_end_time,
        "total_drawdowns": len([dd for dd in dd_series if dd < 0])
    }

def underwater_periods(equity: pd.Series, threshold: float = 0.0) -> pd.DataFrame:
    """
    Identify underwater periods (periods when equity is below threshold).
    
    Args:
        equity: Equity curve
        threshold: Threshold for underwater (default 0.0 = peak)
        
    Returns:
        DataFrame with underwater periods
    """
    if equity.empty:
        return pd.DataFrame()
    
    # Calculate running peak
    peak = equity.cummax()
    
    # Determine underwater status
    if threshold == 0.0:
        underwater = equity < peak
    else:
        underwater = equity < threshold
    
    # Find underwater periods
    periods = []
    start = None
    
    for i, (timestamp, is_underwater) in enumerate(underwater.items()):
        if is_underwater and start is None:
            start = timestamp
        elif not is_underwater and start is not None:
            periods.append({
                "start": start,
                "end": equity.index[i-1],
                "duration": len(equity.loc[start:equity.index[i-1]]),
                "depth": (equity.loc[start:equity.index[i-1]] - peak.loc[start:equity.index[i-1]]).min()
            })
            start = None
    
    # Handle ongoing underwater period
    if start is not None:
        periods.append({
            "start": start,
            "end": equity.index[-1],
            "duration": len(equity.loc[start:]),
            "depth": (equity.loc[start:] - peak.loc[start:]).min()
        })
    
    return pd.DataFrame(periods)

def calculate_drawdown_peaks(equity: pd.Series) -> pd.DataFrame:
    """
    Calculate drawdown peaks and valleys.
    
    Args:
        equity: Equity curve
        
    Returns:
        DataFrame with peak and valley information
    """
    if equity.empty:
        return pd.DataFrame()
    
    # Calculate running peak
    peak = equity.cummax()
    
    # Find new peaks
    new_peaks = equity.diff() > 0
    new_peaks.iloc[0] = True  # First point is a peak
    
    # Find valleys (local minima after peaks)
    valleys = pd.Series(False, index=equity.index)
    
    for i in range(1, len(equity)-1):
        if (equity.iloc[i] < equity.iloc[i-1] and 
            equity.iloc[i] < equity.iloc[i+1] and
            equity.iloc[i] < peak.iloc[i]):
            valleys.iloc[i] = True
    
    # Create results
    results = []
    
    for i, (timestamp, is_peak) in enumerate(new_peaks.items()):
        if is_peak:
            peak_value = equity.iloc[i]
            peak_dd = 0.0
            
            # Find next valley
            future_valleys = valleys.loc[timestamp:]
            if not future_valleys.empty:
                next_valley_time = future_valleys.idxmax()
                next_valley_value = equity.loc[next_valley_time]
                peak_dd = (next_valley_value - peak_value) / peak_value
                
                results.append({
                    "peak_time": timestamp,
                    "peak_value": peak_value,
                    "valley_time": next_valley_time,
                    "valley_value": next_valley_value,
                    "drawdown": peak_dd,
                    "recovery_time": len(equity.loc[timestamp:next_valley_time]) if next_valley_time in equity.index else None
                })
    
    return pd.DataFrame(results)

def validate_drawdown_calculation(equity: pd.Series) -> dict:
    """
    Validate drawdown calculation and provide diagnostics.
    
    Args:
        equity: Equity curve
        
    Returns:
        Validation results
    """
    validation = {
        "valid": True,
        "warnings": [],
        "recommendations": [],
        "diagnostics": {}
    }
    
    if equity.empty:
        validation["valid"] = False
        validation["warnings"].append("Empty equity series")
        return validation
    
    # Basic statistics
    max_dd = max_drawdown(equity)
    stats = drawdown_statistics(equity)
    
    validation["diagnostics"] = {
        "data_points": len(equity),
        "date_range": f"{equity.index[0]} to {equity.index[-1]}",
        "max_drawdown": max_dd,
        "drawdown_frequency": stats["drawdown_frequency"],
        "avg_recovery_time": stats["recovery_time_avg"]
    }
    
    # Check for issues
    if max_dd == 0.0:
        validation["warnings"].append("No drawdown detected - may indicate flat equity curve")
        validation["recommendations"].append("Verify strategy is generating realistic returns")
    
    if stats["drawdown_frequency"] > 0.5:
        validation["warnings"].append(f"High drawdown frequency: {stats['drawdown_frequency']:.1%}")
        validation["recommendations"].append("Consider reducing position size or improving entry criteria")
    
    if stats["recovery_time_avg"] > len(equity) * 0.3:
        validation["warnings"].append(f"Long average recovery time: {stats['recovery_time_avg']:.0f} periods")
        validation["recommendations"].append("Strategy may be slow to recover from losses")
    
    if max_dd < -0.5:
        validation["warnings"].append(f"Very high drawdown: {max_dd:.1%}")
        validation["recommendations"].append("Implement stronger risk controls")
    
    # Check for data quality issues
    if equity.isnull().any():
        validation["warnings"].append(f"Missing data points: {equity.isnull().sum()}")
        validation["recommendations"].append("Handle missing data before analysis")
    
    if (equity.diff() == 0).sum() > len(equity) * 0.1:
        validation["warnings"].append("Many flat periods detected")
        validation["recommendations"].append("Check for data quality issues")
    
    return validation

# Example usage:
"""
import pandas as pd
import numpy as np

# Generate sample equity curve
np.random.seed(42)
returns = np.random.randn(200) * 0.01
equity = (1 + returns).cumprod() * 100000

# Calculate max drawdown
max_dd = max_drawdown(equity)
print(f"Max Drawdown: {max_dd:.2%}")

# Drawdown statistics
stats = drawdown_statistics(equity)
print(f"Drawdown Stats: {stats}")

# Underwater periods
underwater = underwater_periods(equity)
print(f"Underwater periods: {len(underwater)}")

# Drawdown peaks and valleys
peaks_valleys = calculate_drawdown_peaks(equity)
print(f"Peaks and valleys: {len(peaks_valleys)}")

# Validation
validation = validate_drawdown_calculation(equity)
print(f"Validation: {validation}")
"""
