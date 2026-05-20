"""
Kraken USD Data Fetcher - 15m Crypto Majors Historical Data

Use Kraken public API for historical OHLCV data.
Uses USD pairs (XBTUSD, ETHUSD, SOLUSD, XRPUSD, DOGEUSD) to match Kalshi USD settlement.
Supports BTC, ETH, SOL, XRP, DOGE for 15m band strategy backtesting.
"""

import requests
import pandas as pd
from typing import Literal, Dict, Optional
import logging
import time

logger = logging.getLogger(__name__)

KRAKEN_BASE = "https://api.kraken.com"
Interval = Literal["15m"]

# Supported assets for band strategy
BAND_STRATEGY_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]

# Symbol mapping to Kraken USD pairs
# Kraken uses XBT for Bitcoin, not BTC
KRAKEN_SYMBOL_MAP = {
    "BTC": "XBTUSD",  # Kraken uses XBT for Bitcoin
    "ETH": "ETHUSD",
    "SOL": "SOLUSD",
    "XRP": "XRPUSD",
    "DOGE": "DOGEUSD",
}

def fetch_candles(
    pair: str = "XBTUSD",
    interval: int = 15,  # 15m = 15 (Kraken uses minutes for interval)
    limit: int = 1000,
    since: Optional[int] = None,
    timeout: int = 10
) -> pd.DataFrame:
    """
    Fetch OHLCV candles from Kraken public API. No auth needed.
    
    Args:
        pair: Kraken trading pair (e.g., "XBTUSD", "ETHUSD")
        interval: Candle interval in minutes (15 for 15m, 60 for 1h, 1440 for 1d)
        limit: Number of candles to fetch per request (max 1000)
        since: Optional Unix timestamp to fetch data since (for historical data)
        timeout: Request timeout in seconds
        
    Returns:
        DataFrame with OHLCV data indexed by timestamp
    """
    # Kraken public API for OHLC data
    url = f"{KRAKEN_BASE}/0/public/OHLC"
    
    params = {
        "pair": pair,
        "interval": interval,
    }
    
    if since:
        params["since"] = since
    
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        
        if data.get("error"):
            logger.error(f"Kraken API error for {pair}: {data['error']}")
            return pd.DataFrame()
        
        result = data.get("result", {})
        if not result:
            logger.warning(f"No data returned for {pair}")
            return pd.DataFrame()
        
        # Kraken returns data as {pair: [[time, open, high, low, close, vwap, volume, count], ...]}
        # Get the first (and only) key which is the pair name
        pair_key = list(result.keys())[0]
        candles = result[pair_key]
        
        # Kraken returns: [time, open, high, low, close, vwap, volume, count]
        # We need: timestamp, open, high, low, close, volume
        df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "vwap", "volume", "count"])
        
        # Convert timestamp from Unix timestamp to datetime
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        
        # Convert numeric columns
        numeric_cols = ["open", "high", "low", "close", "volume"]
        df[numeric_cols] = df[numeric_cols].astype(float)
        
        # Select only the columns we need
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        
        # Set index and sort
        df = df.set_index("timestamp").sort_index()
        
        logger.info(f"Fetched {len(df)} candles for {pair}")
        
        return df
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch candles for {pair}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error processing candles data for {pair}: {e}")
        raise

def fetch_historical_candles(
    pair: str = "XBTUSD",
    interval: int = 15,
    total_bars: int = 10000,
    timeout: int = 10
) -> pd.DataFrame:
    """
    Fetch historical OHLCV candles by making multiple requests with pagination.
    
    Args:
        pair: Kraken trading pair (e.g., "XBTUSD", "ETHUSD")
        interval: Candle interval in minutes
        total_bars: Total number of bars to fetch
        timeout: Request timeout in seconds
        
    Returns:
        DataFrame with OHLCV data indexed by timestamp
    """
    all_candles = []
    since = None
    bars_fetched = 0
    
    while bars_fetched < total_bars:
        # Fetch up to 1000 candles per request
        limit = min(1000, total_bars - bars_fetched)
        
        params = {"pair": pair, "interval": interval}
        if since:
            params["since"] = since
        
        url = f"{KRAKEN_BASE}/0/public/OHLC"
        
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            
            if data.get("error"):
                logger.error(f"Kraken API error for {pair}: {data['error']}")
                break
            
            result = data.get("result", {})
            if not result:
                logger.warning(f"No more data for {pair}")
                break
            
            pair_key = list(result.keys())[0]
            candles = result[pair_key]
            
            if not candles:
                logger.warning(f"Empty candles array for {pair}")
                break
            
            all_candles.extend(candles)
            bars_fetched += len(candles)
            
            # Get the oldest timestamp for next request (candles are returned newest first)
            since = candles[-1][0]  # Last (oldest) timestamp
            
            logger.info(f"Fetched {len(candles)} candles for {pair} (total: {bars_fetched}/{total_bars})")
            
            # Rate limiting
            time.sleep(0.1)
            
        except Exception as e:
            logger.error(f"Error fetching candles for {pair}: {e}")
            break
    
    # Convert to DataFrame
    if not all_candles:
        return pd.DataFrame()
    
    df = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "vwap", "volume", "count"])
    
    # Convert timestamp from Unix timestamp to datetime
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    
    # Convert numeric columns
    numeric_cols = ["open", "high", "low", "close", "volume"]
    df[numeric_cols] = df[numeric_cols].astype(float)
    
    # Select only the columns we need
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    
    # Set index and sort
    df = df.set_index("timestamp").sort_index()
    
    # Limit to requested number of bars
    df = df.tail(total_bars)
    
    logger.info(f"Total fetched {len(df)} candles for {pair} (range: {df.index[0]} to {df.index[-1]})")
    
    return df

def fetch_crypto_majors_15m(limit: int = 1000, timeout: int = 10, historical: bool = False, total_bars: int = 10000) -> Dict[str, pd.DataFrame]:
    """
    Fetch 15-minute data for all crypto majors from Kraken USD pairs.
    
    Args:
        limit: Number of candles to fetch per symbol (for single request)
        timeout: Request timeout in seconds
        historical: If True, fetch multi-year historical data via pagination
        total_bars: Total number of bars to fetch when historical=True
        
    Returns:
        Dictionary with asset -> DataFrame mapping
    """
    logger.info(f"Fetching crypto majors 15m data from Kraken (historical={historical}, total_bars={total_bars})")
    
    try:
        result = {}
        
        for asset, pair in KRAKEN_SYMBOL_MAP.items():
            if historical:
                df = fetch_historical_candles(pair, interval=15, total_bars=total_bars, timeout=timeout)
            else:
                df = fetch_candles(pair, interval=15, limit=limit, timeout=timeout)
            result[asset] = df
            
            # Add delay to be respectful to API
            time.sleep(0.2)
        
        bars = {asset: len(df) for asset, df in result.items()}
        logger.info(f"Successfully fetched data: {bars}")
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to fetch crypto majors data: {e}")
        raise

def validate_data_quality(df: pd.DataFrame, asset: str) -> Dict[str, any]:
    """
    Validate fetched data quality.
    
    Args:
        df: DataFrame with OHLCV data
        asset: Asset name for logging
        
    Returns:
        Dictionary with validation results
    """
    validation = {
        "valid": True,
        "warnings": [],
        "stats": {}
    }
    
    if df.empty:
        validation["valid"] = False
        validation["warnings"].append("Empty DataFrame")
        return validation
    
    # Remove duplicate timestamps (keep last occurrence)
    before_dedup = len(df)
    df = df[~df.index.duplicated(keep='last')]
    after_dedup = len(df)
    duplicates_removed = before_dedup - after_dedup
    
    if duplicates_removed > 0:
        logger.info(f"Removed {duplicates_removed} duplicate timestamps for {asset}")
    
    # Check for missing values
    missing_values = df.isnull().sum()
    if missing_values.any():
        validation["warnings"].append(f"Missing values: {missing_values.to_dict()}")
    
    # Check price consistency
    price_issues = 0
    for idx, row in df.iterrows():
        if not (row["low"] <= row["open"] <= row["high"] and 
                row["low"] <= row["close"] <= row["high"]):
            price_issues += 1
    
    if price_issues > 0:
        validation["warnings"].append(f"Price consistency issues: {price_issues}")
    
    # Check for time gaps (15m candles should be 15 minutes apart)
    if len(df) > 1:
        time_diffs = df.index.to_series().diff().dropna()
        expected_diff = pd.Timedelta(minutes=15)
        gaps = (time_diffs > expected_diff * 1.5).sum()
        if gaps > 0:
            validation["warnings"].append(f"Time gaps detected: {gaps}")
    
    # Basic statistics
    validation["stats"] = {
        "bars": len(df),
        "date_range": f"{df.index[0]} to {df.index[-1]}",
        "price_range": f"{df['low'].min():.2f} - {df['high'].max():.2f}",
        "avg_volume": f"{df['volume'].mean():.0f}",
        "duplicate_timestamps": duplicates_removed,
        "missing_values": missing_values.sum(),
    }
    
    if validation["warnings"]:
        validation["valid"] = False
    
    return validation

def save_data_to_csv(data: Dict[str, pd.DataFrame], prefix: str = "") -> Dict[str, str]:
    """
    Save fetched data to CSV files.
    
    Args:
        data: Dictionary with asset -> DataFrame mapping
        prefix: Prefix for filenames
        
    Returns:
        Dictionary with filenames
    """
    from datetime import datetime
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filenames = {}
    
    for asset, df in data.items():
        filename = f"{prefix}{asset.lower()}_15m_{timestamp}.csv"
        df.to_csv(filename)
        filenames[asset] = filename
        logger.info(f"Saved {asset} data to {filename}")
    
    return filenames

def load_data_from_csv(filenames: Dict[str, str]) -> Dict[str, pd.DataFrame]:
    """
    Load data from CSV files.
    
    Args:
        filenames: Dictionary with asset -> filename mapping
        
    Returns:
        Dictionary with asset -> DataFrame mapping
    """
    data = {}
    
    for asset, filename in filenames.items():
        try:
            df = pd.read_csv(filename, index_col=0, parse_dates=True)
            data[asset] = df
            logger.info(f"Loaded {asset} data from {filename}")
        except Exception as e:
            logger.error(f"Failed to load {asset} data from {filename}: {e}")
    
    return data

# Example usage:
"""
# Fetch latest data for all majors
data = fetch_crypto_majors_15m(limit=300)

# Validate data
for asset, df in data.items():
    validation = validate_data_quality(df, asset)
    print(f"{asset} validation: {validation}")

# Save to CSV
filenames = save_data_to_csv(data, prefix="coinbase_")
print(f"Saved data: {filenames}")

# Load from CSV
loaded_data = load_data_from_csv(filenames)
print(f"Loaded data: {list(loaded_data.keys())}")

# Get latest prices
latest_prices = {asset: df['close'].iloc[-1] for asset, df in data.items()}
print(f"Latest prices: {latest_prices}")
"""
