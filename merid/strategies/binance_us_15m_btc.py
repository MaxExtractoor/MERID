"""
BinanceUS 15m BTC Data Fetcher

Minimal, focused code pattern for fetching BTCUSDT 15m data.
"""

import requests
import pandas as pd
import logging
from typing import Optional

logger = logging.getLogger(__name__)

BASE = "https://api.binance.us"

def fetch_btcusdt_15m(limit: int = 1500, timeout: int = 10) -> pd.DataFrame:
    """
    Fetch BTCUSDT 15m klines from BinanceUS.
    
    Args:
        limit: Number of klines to fetch (max 1500)
        timeout: Request timeout in seconds
        
    Returns:
        DataFrame with OHLCV data indexed by close_time
    """
    url = f"{BASE}/api/v3/klines"
    params = {
        "symbol": "BTCUSDT",
        "interval": "15m",
        "limit": limit
    }
    
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        
        if not data:
            logger.warning("No data returned from BinanceUS")
            return pd.DataFrame()
        
        cols = [
            "open_time","open","high","low","close","volume",
            "close_time","quote_asset_volume","number_of_trades",
            "taker_buy_base","taker_buy_quote","ignore",
        ]
        
        df = pd.DataFrame(data, columns=cols)
        
        # Convert timestamps
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
        
        # Convert numeric columns
        for c in ["open","high","low","close","volume"]:
            df[c] = df[c].astype(float)
        
        # Set index and sort
        df = df.set_index("close_time").sort_index()
        
        logger.info(f"Fetched {len(df)} BTCUSDT 15m klines")
        
        return df
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch BTCUSDT data: {e}")
        raise
    except Exception as e:
        logger.error(f"Error processing BTCUSDT data: {e}")
        raise

def fetch_ethusdt_15m(limit: int = 1500, timeout: int = 10) -> pd.DataFrame:
    """
    Fetch ETHUSDT 15m klines from BinanceUS.
    
    Args:
        limit: Number of klines to fetch (max 1500)
        timeout: Request timeout in seconds
        
    Returns:
        DataFrame with OHLCV data indexed by close_time
    """
    url = f"{BASE}/api/v3/klines"
    params = {
        "symbol": "ETHUSDT",
        "interval": "15m",
        "limit": limit
    }
    
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        
        if not data:
            logger.warning("No data returned from BinanceUS")
            return pd.DataFrame()
        
        cols = [
            "open_time","open","high","low","close","volume",
            "close_time","quote_asset_volume","number_of_trades",
            "taker_buy_base","taker_buy_quote","ignore",
        ]
        
        df = pd.DataFrame(data, columns=cols)
        
        # Convert timestamps
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
        
        # Convert numeric columns
        for c in ["open","high","low","close","volume"]:
            df[c] = df[c].astype(float)
        
        # Set index and sort
        df = df.set_index("close_time").sort_index()
        
        logger.info(f"Fetched {len(df)} ETHUSDT 15m klines")
        
        return df
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch ETHUSDT data: {e}")
        raise
    except Exception as e:
        logger.error(f"Error processing ETHUSDT data: {e}")
        raise

def fetch_btc_eth_15m(limit: int = 1500, timeout: int = 10) -> dict[str, pd.DataFrame]:
    """
    Fetch both BTC and ETH 15m data.
    
    Args:
        limit: Number of klines to fetch per symbol
        timeout: Request timeout in seconds
        
    Returns:
        Dictionary with "BTC" and "ETH" DataFrames
    """
    try:
        btc_df = fetch_btcusdt_15m(limit, timeout)
        eth_df = fetch_ethusdt_15m(limit, timeout)
        
        return {
            "BTC": btc_df,
            "ETH": eth_df
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch BTC/ETH data: {e}")
        raise

def validate_klines_data(df: pd.DataFrame, symbol: str = "BTCUSDT") -> dict:
    """
    Validate klines data and return quality metrics.
    
    Args:
        df: DataFrame with klines data
        symbol: Symbol name for logging
        
    Returns:
        Validation results
    """
    if df.empty:
        return {"valid": False, "error": "Empty DataFrame"}
    
    validation = {
        "valid": True,
        "symbol": symbol,
        "bars": len(df),
        "date_range": f"{df.index[0]} to {df.index[-1]}",
        "price_range": f"{df['low'].min():.2f} - {df['high'].max():.2f}",
        "avg_volume": f"{df['volume'].mean():.0f}",
        "issues": []
    }
    
    # Check for missing values
    missing = df.isnull().sum().sum()
    if missing > 0:
        validation["issues"].append(f"Missing values: {missing}")
    
    # Check for price consistency
    price_issues = 0
    for idx, row in df.iterrows():
        if not (row["low"] <= row["open"] <= row["high"] and 
                row["low"] <= row["close"] <= row["high"]):
            price_issues += 1
    
    if price_issues > 0:
        validation["issues"].append(f"Price consistency issues: {price_issues}")
    
    # Check for duplicate timestamps
    duplicates = df.index.duplicated().sum()
    if duplicates > 0:
        validation["issues"].append(f"Duplicate timestamps: {duplicates}")
    
    # Check for zero volume
    zero_volume = (df["volume"] == 0).sum()
    if zero_volume > 0:
        validation["issues"].append(f"Zero volume bars: {zero_volume}")
    
    if validation["issues"]:
        validation["valid"] = False
    
    return validation

def get_latest_price(symbol: str = "BTCUSDT") -> Optional[float]:
    """
    Get latest price for a symbol.
    
    Args:
        symbol: Trading symbol
        
    Returns:
        Latest price or None if error
    """
    try:
        url = f"{BASE}/api/v3/ticker/price"
        params = {"symbol": symbol}
        
        r = requests.get(url, params=params, timeout=5)
        r.raise_for_status()
        data = r.json()
        
        return float(data["price"])
        
    except Exception as e:
        logger.error(f"Failed to get latest price for {symbol}: {e}")
        return None

# Example usage:
"""
# Fetch BTC data
btc_df = fetch_btcusdt_15m(limit=1000)
print(f"BTC data: {len(btc_df)} bars")
print(f"Latest price: ${btc_df['close'].iloc[-1]:,.0f}")

# Validate data
validation = validate_klines_data(btc_df, "BTCUSDT")
print(f"Data validation: {validation}")

# Fetch both BTC and ETH
data = fetch_btc_eth_15m(limit=500)
print(f"BTC: {len(data['BTC'])} bars, ETH: {len(data['ETH'])} bars")

# Get latest prices
btc_price = get_latest_price("BTCUSDT")
eth_price = get_latest_price("ETHUSDT")
print(f"Latest prices: BTC=${btc_price:,.0f}, ETH=${eth_price:,.0f}")
"""
