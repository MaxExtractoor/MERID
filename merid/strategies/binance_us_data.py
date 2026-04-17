"""
BinanceUS Data Fetcher - 15m BTC/ETH Historical Data

Use public GET /api/v3/klines on https://api.binance.us for historical data.
"""

import requests
import pandas as pd
from typing import Literal, Dict
import logging
import time

logger = logging.getLogger(__name__)

BINANCE_US_BASE = "https://api.binance.us"
Interval = Literal["15m"]

def fetch_klines(
    symbol: str = "BTCUSDT",
    interval: Interval = "15m",
    limit: int = 1000,
    timeout: int = 10
) -> pd.DataFrame:
    """
    Fetch recent klines from BinanceUS. Public, no auth needed.
    
    Args:
        symbol: Trading symbol (e.g., "BTCUSDT")
        interval: Kline interval ("15m")
        limit: Number of klines to fetch (max 1000)
        timeout: Request timeout in seconds
        
    Returns:
        DataFrame with OHLCV data indexed by close_time
    """
    url = f"{BINANCE_US_BASE}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        
        if not data:
            logger.warning(f"No data returned for {symbol}")
            return pd.DataFrame()
        
        cols = [
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore",
        ]
        
        df = pd.DataFrame(data, columns=cols)
        
        # Convert timestamps
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
        
        # Convert numeric columns
        numeric_cols = ["open", "high", "low", "close", "volume"]
        df[numeric_cols] = df[numeric_cols].astype(float)
        
        # Set index and clean
        df = df.set_index("close_time").sort_index()
        
        logger.info(f"Fetched {len(df)} klines for {symbol} ({interval})")
        
        return df
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch klines for {symbol}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error processing klines data for {symbol}: {e}")
        raise

def fetch_btc_eth_15m(limit: int = 1000, timeout: int = 10) -> Dict[str, pd.DataFrame]:
    """
    Fetch 15-minute BTC and ETH data from BinanceUS.
    
    Args:
        limit: Number of klines to fetch per symbol
        timeout: Request timeout in seconds
        
    Returns:
        Dictionary with "BTC" and "ETH" DataFrames
    """
    logger.info(f"Fetching BTC/ETH 15m data (limit={limit})")
    
    try:
        # Fetch both symbols
        btc_df = fetch_klines("BTCUSDT", "15m", limit, timeout)
        eth_df = fetch_klines("ETHUSDT", "15m", limit, timeout)
        
        # Add small delay to be respectful to API
        time.sleep(0.1)
        
        result = {
            "BTC": btc_df,
            "ETH": eth_df
        }
        
        logger.info(f"Successfully fetched data: BTC={len(btc_df)} bars, ETH={len(eth_df)} bars")
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to fetch BTC/ETH data: {e}")
        raise

def validate_data_quality(df: pd.DataFrame, symbol: str) -> Dict[str, any]:
    """
    Validate fetched data quality.
    
    Args:
        df: DataFrame with OHLCV data
        symbol: Symbol name for logging
        
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
    
    # Check for missing values
    missing_values = df.isnull().sum()
    if missing_values.any():
        validation["warnings"].append(f"Missing values: {missing_values.to_dict()}")
    
    # Check for duplicate timestamps
    duplicates = df.index.duplicated().sum()
    if duplicates > 0:
        validation["warnings"].append(f"Duplicate timestamps: {duplicates}")
    
    # Check price consistency
    price_issues = 0
    for idx, row in df.iterrows():
        if not (row["low"] <= row["open"] <= row["high"] and 
                row["low"] <= row["close"] <= row["high"]):
            price_issues += 1
    
    if price_issues > 0:
        validation["warnings"].append(f"Price consistency issues: {price_issues}")
    
    # Basic statistics
    validation["stats"] = {
        "bars": len(df),
        "date_range": f"{df.index[0]} to {df.index[-1]}",
        "price_range": f"{df['low'].min():.2f} - {df['high'].max():.2f}",
        "avg_volume": f"{df['volume'].mean():.0f}",
        "duplicate_timestamps": duplicates,
        "missing_values": missing_values.sum()
    }
    
    if validation["warnings"]:
        validation["valid"] = False
    
    return validation

def save_data_to_csv(data: Dict[str, pd.DataFrame], prefix: str = "") -> Dict[str, str]:
    """
    Save fetched data to CSV files.
    
    Args:
        data: Dictionary with symbol -> DataFrame mapping
        prefix: Prefix for filenames
        
    Returns:
        Dictionary with filenames
    """
    from datetime import datetime
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filenames = {}
    
    for symbol, df in data.items():
        filename = f"{prefix}{symbol.lower()}_15m_{timestamp}.csv"
        df.to_csv(filename)
        filenames[symbol] = filename
        logger.info(f"Saved {symbol} data to {filename}")
    
    return filenames

def load_data_from_csv(filenames: Dict[str, str]) -> Dict[str, pd.DataFrame]:
    """
    Load data from CSV files.
    
    Args:
        filenames: Dictionary with symbol -> filename mapping
        
    Returns:
        Dictionary with symbol -> DataFrame mapping
    """
    data = {}
    
    for symbol, filename in filenames.items():
        try:
            df = pd.read_csv(filename, index_col=0, parse_dates=True)
            data[symbol] = df
            logger.info(f"Loaded {symbol} data from {filename}")
        except Exception as e:
            logger.error(f"Failed to load {symbol} data from {filename}: {e}")
    
    return data

# Example usage:
"""
# Fetch latest data
data = fetch_btc_eth_15m(limit=500)

# Validate data
for symbol, df in data.items():
    validation = validate_data_quality(df, symbol)
    print(f"{symbol} validation: {validation}")

# Save to CSV
filenames = save_data_to_csv(data, prefix="binance_")
print(f"Saved data: {filenames}")

# Load from CSV
loaded_data = load_data_from_csv(filenames)
print(f"Loaded data: {list(loaded_data.keys())}")

# Get latest prices
latest_prices = {symbol: df['close'].iloc[-1] for symbol, df in data.items()}
print(f"Latest prices: {latest_prices}")
"""
