"""
Kalshi Market Data Fetch - Public API for Yes/No Markets

Fetch Kalshi market data without authentication for backtesting.
"""

import logging
import os
import pandas as pd
import requests
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Kalshi public API base URL - read from env to support demo/live modes
BASE = os.getenv("KALSHI_API_BASE_URL", "https://demo-api.kalshi.co/trade-api/v2")

def fetch_markets(series_ticker: str = None, status: str = "open", 
                  event_ticker: str = None, limit: int = 1000) -> pd.DataFrame:
    """
    Fetch Kalshi markets data using public API.
    
    Args:
        series_ticker: Filter by series ticker (e.g., "KXBTC", "KXETH")
        status: Market status filter ("open", "closed", "settled")
        event_ticker: Filter by event ticker
        limit: Maximum number of markets to fetch
        
    Returns:
        DataFrame with market data including ticker, yes_price, volume, etc.
    """
    url = f"{BASE}/markets"
    
    params = {
        "limit": limit,
        "status": status
    }
    
    if series_ticker:
        params["series_ticker"] = series_ticker
    
    if event_ticker:
        params["event_ticker"] = event_ticker
    
    try:
        logger.info(f"Fetching Kalshi markets: series={series_ticker}, status={status}")
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        
        data = r.json().get("markets", [])
        
        if not data:
            logger.warning(f"No markets found for series={series_ticker}, status={status}")
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        
        # Convert timestamps
        if 'closing_time' in df.columns:
            df['closing_time'] = pd.to_datetime(df['closing_time'])
        
        # Convert numeric columns
        numeric_cols = ['yes_price', 'no_price', 'volume', 'open_interest']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        logger.info(f"Fetched {len(df)} markets from Kalshi")
        
        return df
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch Kalshi markets: {e}")
        raise
    except Exception as e:
        logger.error(f"Error processing Kalshi markets data: {e}")
        raise

def fetch_event(event_ticker: str) -> Dict:
    """
    Fetch detailed event information.
    
    Args:
        event_ticker: Event ticker identifier
        
    Returns:
        Event information dictionary
    """
    url = f"{BASE}/events/{event_ticker}"
    
    try:
        logger.info(f"Fetching Kalshi event: {event_ticker}")
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        
        event_data = r.json().get("event", {})
        
        if not event_data:
            raise ValueError(f"Event not found: {event_ticker}")
        
        # Convert timestamps
        if 'event_start' in event_data:
            event_data['event_start'] = pd.to_datetime(event_data['event_start'])
        if 'event_end' in event_data:
            event_data['event_end'] = pd.to_datetime(event_data['event_end'])
        
        return event_data
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch Kalshi event {event_ticker}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error processing Kalshi event data: {e}")
        raise

def fetch_orderbook(market_ticker: str) -> Dict:
    """
    Fetch orderbook for a specific market.
    
    Args:
        market_ticker: Market ticker identifier
        
    Returns:
        Orderbook dictionary with yes/no bid ladders
    """
    url = f"{BASE}/markets/{market_ticker}/orderbook"
    
    try:
        logger.info(f"Fetching Kalshi orderbook: {market_ticker}")
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        
        orderbook_data = r.json().get("orderbook", {})
        
        if not orderbook_data:
            raise ValueError(f"Orderbook not found: {market_ticker}")
        
        # Process bid ladders
        if 'yes' in orderbook_data:
            yes_bids = orderbook_data['yes'].get('bids', [])
            orderbook_data['yes']['bids'] = [
                {'price': float(bid['price']), 'quantity': int(bid['quantity'])}
                for bid in yes_bids
            ]
        
        if 'no' in orderbook_data:
            no_bids = orderbook_data['no'].get('bids', [])
            orderbook_data['no']['bids'] = [
                {'price': float(bid['price']), 'quantity': int(bid['quantity'])}
                for bid in no_bids
            ]
        
        return orderbook_data
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch Kalshi orderbook {market_ticker}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error processing Kalshi orderbook data: {e}")
        raise

def fetch_market_history(market_ticker: str, limit: int = 1000) -> pd.DataFrame:
    """
    Fetch historical price data for a specific market.
    
    Args:
        market_ticker: Market ticker identifier
        limit: Maximum number of price points to fetch
        
    Returns:
        DataFrame with price history
    """
    url = f"{BASE}/markets/{market_ticker}/price_history"
    
    params = {"limit": limit}
    
    try:
        logger.info(f"Fetching Kalshi market history: {market_ticker}")
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        
        history_data = r.json().get("history", [])
        
        if not history_data:
            logger.warning(f"No price history found: {market_ticker}")
            return pd.DataFrame()
        
        df = pd.DataFrame(history_data)
        
        # Convert timestamp
        if 'ts' in df.columns:
            df['ts'] = pd.to_datetime(df['ts'])
            df = df.set_index('ts')
        
        # Convert numeric columns
        numeric_cols = ['yes_price', 'no_price']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        logger.info(f"Fetched {len(df)} price points for {market_ticker}")
        
        return df
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch Kalshi market history {market_ticker}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error processing Kalshi market history: {e}")
        raise

def get_crypto_markets(crypto_ticker: str = "BTC", status: str = "open") -> pd.DataFrame:
    """
    Convenience function to get crypto-related Kalshi markets.
    
    Args:
        crypto_ticker: Crypto ticker ("BTC", "ETH")
        status: Market status filter
        
    Returns:
        DataFrame with crypto markets
    """
    # Common Kalshi crypto series tickers
    series_mapping = {
        "BTC": "KXBTC",
        "ETH": "KXETH",
        "BTCUSD": "KXBTCUSD",
        "ETHUSD": "KXETHUSD"
    }
    
    series_ticker = series_mapping.get(crypto_ticker.upper(), crypto_ticker)
    
    return fetch_markets(series_ticker=series_ticker, status=status)

def get_market_summary(market_ticker: str) -> Dict:
    """
    Get comprehensive market summary including orderbook and recent history.
    
    Args:
        market_ticker: Market ticker identifier
        
    Returns:
        Market summary dictionary
    """
    try:
        # Fetch market info
        markets_df = fetch_markets(event_ticker=market_ticker, limit=1)
        
        if markets_df.empty:
            raise ValueError(f"Market not found: {market_ticker}")
        
        market_info = markets_df.iloc[0].to_dict()
        
        # Fetch orderbook
        orderbook = fetch_orderbook(market_ticker)
        
        # Fetch recent price history
        price_history = fetch_market_history(market_ticker, limit=100)
        
        # Calculate recent price stats
        price_stats = {}
        if not price_history.empty and 'yes_price' in price_history.columns:
            recent_prices = price_history['yes_price'].tail(20)
            price_stats = {
                "current_price": recent_prices.iloc[-1],
                "price_change": recent_prices.iloc[-1] - recent_prices.iloc[0],
                "price_change_pct": (recent_prices.iloc[-1] - recent_prices.iloc[0]) / recent_prices.iloc[0] * 100,
                "volatility": recent_prices.std(),
                "trend": "up" if recent_prices.iloc[-1] > recent_prices.iloc[0] else "down"
            }
        
        summary = {
            "market_info": market_info,
            "orderbook": orderbook,
            "price_history": price_history.to_dict() if not price_history.empty else {},
            "price_stats": price_stats,
            "fetched_at": datetime.now().isoformat()
        }
        
        return summary
        
    except Exception as e:
        logger.error(f"Error getting market summary for {market_ticker}: {e}")
        raise

def validate_market_data(markets_df: pd.DataFrame) -> Dict:
    """
    Validate market data quality and provide diagnostics.
    
    Args:
        markets_df: DataFrame of market data
        
    Returns:
        Validation results
    """
    if markets_df.empty:
        return {"valid": False, "error": "Empty markets DataFrame"}
    
    validation = {
        "valid": True,
        "warnings": [],
        "info": {}
    }
    
    # Basic info
    validation["info"]["total_markets"] = len(markets_df)
    validation["info"]["unique_events"] = markets_df["event_ticker"].nunique()
    validation["info"]["unique_series"] = markets_df["series_ticker"].nunique()
    
    # Check for missing data
    missing_cols = []
    required_cols = ["ticker", "yes_price", "no_price", "volume"]
    
    for col in required_cols:
        if col not in markets_df.columns:
            missing_cols.append(col)
        elif markets_df[col].isnull().sum() > 0:
            validation["warnings"].append(f"Missing values in {col}")
    
    if missing_cols:
        validation["valid"] = False
        validation["error"] = f"Missing required columns: {missing_cols}"
        return validation
    
    # Price validation
    yes_prices = markets_df["yes_price"]
    no_prices = markets_df["no_price"]
    
    # Check price ranges (should be 0-100 cents)
    if yes_prices.min() < 0 or yes_prices.max() > 100:
        validation["warnings"].append("Yes prices outside 0-100 range")
    
    if no_prices.min() < 0 or no_prices.max() > 100:
        validation["warnings"].append("No prices outside 0-100 range")
    
    # Check price sum (yes + no should be close to 100)
    price_sums = yes_prices + no_prices
    if (price_sums.abs() - 100).max() > 5:
        validation["warnings"].append("Price sums deviate significantly from 100")
    
    # Volume validation
    volumes = markets_df["volume"]
    if volumes.min() < 0:
        validation["warnings"].append("Negative volumes detected")
    
    validation["info"]["avg_yes_price"] = yes_prices.mean()
    validation["info"]["avg_no_price"] = no_prices.mean()
    validation["info"]["total_volume"] = volumes.sum()
    validation["info"]["avg_volume"] = volumes.mean()
    
    return validation

# Example usage:
"""
# Fetch all open BTC markets
btc_markets = get_crypto_markets("BTC", status="open")
print(f"Found {len(btc_markets)} BTC markets")

# Get market summary
if not btc_markets.empty:
    market_ticker = btc_markets.iloc[0]["ticker"]
    summary = get_market_summary(market_ticker)
    print(f"Market summary for {market_ticker}:")
    print(f"  Current price: {summary['price_stats']['current_price']:.2f}")
    print(f"  Price change: {summary['price_stats']['price_change_pct']:.2f}%")

# Validate market data
validation = validate_market_data(btc_markets)
print(f"Data validation: {'✅ Valid' if validation['valid'] else '⚠️ Issues found'}")
"""
