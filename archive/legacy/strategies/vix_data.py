"""
VIX Data Fetcher for Kalshi Integration

Fetch VIX data for volatility ranking and Kelly scaling.
"""

import pandas as pd
import requests
from io import StringIO
from typing import Optional, List
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# CBOE VIX data URL
VIX_CSV_URL = "http://www.cboe.com/publish/scheduledtask/mktdata/datahouse/vixcurrent.csv"

# Alternative sources for robustness
VIX_ALTERNATIVE_URLS = [
    "https://raw.githubusercontent.com/datasets/finance-vix/main/data/vix-daily.csv",
    "https://stooq.com/q/?s=%5Evix&d1=20200101&dl=1"
]

def fetch_vix_history(url: str = VIX_CSV_URL, timeout: int = 10) -> pd.Series:
    """
    Fetch daily VIX closes as a pandas Series indexed by date.
    
    Args:
        url: URL to fetch VIX data from
        timeout: Request timeout in seconds
        
    Returns:
        VIX close prices Series indexed by date
    """
    try:
        logger.info(f"Fetching VIX data from: {url}")
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        
        # Parse CSV content
        csv_data = r.text.splitlines()
        
        # Skip header rows; CBOE file typically has header + blank lines
        content_lines = []
        for line in csv_data:
            line = line.strip()
            # Skip empty lines and lines starting with quotes or comments
            if line and not line.startswith(('"', '#', 'Date')):
                content_lines.append(line)
        
        if not content_lines:
            raise ValueError("No valid data lines found in CSV")
        
        content = "\n".join(content_lines)
        
        # Try different parsing approaches
        try:
            # First attempt: standard CSV parse
            df = pd.read_csv(StringIO(content))
        except Exception:
            # Second attempt: handle different column names
            df = pd.read_csv(StringIO(content), header=None)
            df.columns = ['Date', 'VIX Close'] if len(df.columns) == 2 else ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
        
        # Find the VIX close column
        vix_col = None
        for col in df.columns:
            if 'vix' in col.lower() and 'close' in col.lower():
                vix_col = col
                break
            elif col.lower() == 'vix' or col.lower() == 'close':
                vix_col = col
                break
        
        if vix_col is None:
            # Use the second column as fallback
            vix_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]
        
        # Convert date column
        date_col = df.columns[0]
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
        
        # Clean VIX data
        df[vix_col] = pd.to_numeric(df[vix_col], errors='coerce')
        
        # Remove invalid data
        df = df.dropna(subset=[date_col, vix_col])
        
        # Set index and sort
        df = df.set_index(date_col).sort_index()
        
        # Create Series
        vix = df[vix_col]
        vix.name = "VIX"
        
        logger.info(f"Successfully fetched {len(vix)} VIX data points from {vix.index[0]} to {vix.index[-1]}")
        
        return vix
        
    except Exception as e:
        logger.error(f"Failed to fetch VIX data from {url}: {e}")
        raise

def fetch_vix_with_fallback(timeout: int = 10) -> pd.Series:
    """
    Fetch VIX data with fallback URLs for robustness.
    
    Args:
        timeout: Request timeout in seconds
        
    Returns:
        VIX close prices Series indexed by date
    """
    urls_to_try = [VIX_CSV_URL] + VIX_ALTERNATIVE_URLS
    
    for url in urls_to_try:
        try:
            return fetch_vix_history(url, timeout)
        except Exception as e:
            logger.warning(f"Failed to fetch from {url}: {e}")
            continue
    
    raise RuntimeError("Failed to fetch VIX data from all sources")

def calculate_vix_rank(vix_series: pd.Series, lookback: int = 252) -> float:
    """
    Calculate VIX rank (percentile) over lookback window.
    
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

def get_vix_percentile(vix_series: pd.Series, current_date: Optional[datetime] = None) -> float:
    """
    Get VIX percentile for a specific date.
    
    Args:
        vix_series: VIX price series indexed by date
        current_date: Date to calculate percentile for (uses latest if None)
        
    Returns:
        VIX percentile (0-1)
    """
    if vix_series.empty:
        return 0.5
    
    if current_date is None:
        current_date = vix_series.index[-1]
    elif current_date not in vix_series.index:
        # Find closest date
        closest_idx = vix_series.index.get_indexer([current_date], method='nearest')[0]
        current_date = vix_series.index[closest_idx]
    
    current_vix = vix_series.loc[current_date]
    
    # Calculate percentile against all historical data
    percentile = (vix_series <= current_vix).mean()
    
    return float(percentile)

def validate_vix_data(vix_series: pd.Series) -> dict:
    """
    Validate VIX data quality and provide diagnostics.
    
    Args:
        vix_series: VIX price series
        
    Returns:
        Validation results
    """
    if vix_series.empty:
        return {"valid": False, "error": "Empty VIX series"}
    
    validation = {
        "valid": True,
        "warnings": [],
        "info": {}
    }
    
    # Basic stats
    validation["info"]["data_points"] = len(vix_series)
    validation["info"]["date_range"] = f"{vix_series.index[0]} to {vix_series.index[-1]}"
    validation["info"]["min_vix"] = vix_series.min()
    validation["info"]["max_vix"] = vix_series.max()
    validation["info"]["mean_vix"] = vix_series.mean()
    validation["info"]["latest_vix"] = vix_series.iloc[-1]
    
    # Check for gaps
    date_range = vix_series.index[-1] - vix_series.index[0]
    expected_days = date_range.days
    actual_days = len(vix_series)
    
    if expected_days > 0:
        coverage = actual_days / expected_days
        validation["info"]["data_coverage"] = coverage
        
        if coverage < 0.9:
            validation["warnings"].append(f"Low data coverage: {coverage:.1%}")
    
    # Check for outliers
    vix_mean = vix_series.mean()
    vix_std = vix_series.std()
    
    outliers = vix_series[(vix_series < vix_mean - 3 * vix_std) | (vix_series > vix_mean + 3 * vix_std)]
    
    if len(outliers) > 0:
        validation["warnings"].append(f"Found {len(outliers)} outliers in VIX data")
    
    # Check for stale data
    latest_date = vix_series.index[-1]
    days_old = (datetime.now() - latest_date).days
    
    validation["info"]["days_stale"] = days_old
    
    if days_old > 7:
        validation["warnings"].append(f"VIX data is {days_old} days old")
    
    # VIX level assessment
    latest_vix = vix_series.iloc[-1]
    
    if latest_vix < 15:
        validation["info"]["volatility_regime"] = "low"
    elif latest_vix < 25:
        validation["info"]["volatility_regime"] = "normal"
    elif latest_vix < 40:
        validation["info"]["volatility_regime"] = "high"
    else:
        validation["info"]["volatility_regime"] = "extreme"
    
    if validation["warnings"]:
        validation["valid"] = False
    
    return validation

def get_vix_summary(vix_series: pd.Series) -> dict:
    """
    Get comprehensive VIX summary for dashboard display.
    
    Args:
        vix_series: VIX price series
        
    Returns:
        Summary dictionary
    """
    if vix_series.empty:
        return {"error": "No VIX data available"}
    
    # Calculate various metrics
    current_vix = vix_series.iloc[-1]
    vix_rank_252 = calculate_vix_rank(vix_series, lookback=252)
    vix_rank_90 = calculate_vix_rank(vix_series, lookback=90)
    vix_rank_30 = calculate_vix_rank(vix_series, lookback=30)
    
    # Recent trends
    recent_change = (current_vix - vix_series.iloc[-5]) / vix_series.iloc[-5] if len(vix_series) >= 5 else 0.0
    monthly_change = (current_vix - vix_series.iloc[-22]) / vix_series.iloc[-22] if len(vix_series) >= 22 else 0.0
    
    # Percentiles
    percentiles = {
        "p10": vix_series.quantile(0.10),
        "p25": vix_series.quantile(0.25),
        "p50": vix_series.quantile(0.50),
        "p75": vix_series.quantile(0.75),
        "p90": vix_series.quantile(0.90)
    }
    
    return {
        "current_vix": current_vix,
        "vix_rank_252": vix_rank_252,
        "vix_rank_90": vix_rank_90,
        "vix_rank_30": vix_rank_30,
        "recent_change_5d": recent_change,
        "monthly_change_22d": monthly_change,
        "percentiles": percentiles,
        "data_points": len(vix_series),
        "latest_date": vix_series.index[-1],
        "volatility_regime": validate_vix_data(vix_series)["info"]["volatility_regime"]
    }

# Example usage:
"""
# Fetch VIX data
try:
    vix_data = fetch_vix_with_fallback()
    
    # Validate data
    validation = validate_vix_data(vix_data)
    print(f"VIX data validation: {'✅ Valid' if validation['valid'] else '⚠️ Issues found'}")
    
    # Calculate rank
    vix_rank = calculate_vix_rank(vix_data, lookback=252)
    print(f"Current VIX rank: {vix_rank:.3f}")
    
    # Get summary
    summary = get_vix_summary(vix_data)
    print(f"VIX summary: {summary}")
    
except Exception as e:
    print(f"Error fetching VIX data: {e}")
    # Fallback to default values
    vix_rank = 0.5
"""
