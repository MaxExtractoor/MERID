"""
Multivariate Event Fetching from Kalshi API

Fetch multiple crypto event markets and build return matrix for MVRK analysis.
"""

import requests
import pandas as pd
from typing import List, Dict, Any, Optional
import logging
import os
from datetime import datetime, timedelta
import time

logger = logging.getLogger(__name__)

# Kalshi API configuration - read from env to support demo/live modes
BASE = os.getenv("KALSHI_API_BASE_URL", "https://demo-api.kalshi.co/trade-api/v2")

# Common crypto market patterns
CRYPTO_SERIES_PATTERNS = [
    "KXBTC",    # Bitcoin markets
    "KXETH",    # Ethereum markets
    "KXLTC",    # Litecoin markets
    "KXADA",    # Cardano markets
    "KXSOL",    # Solana markets
]

TIMEFRAMES = {
    "15M": "15min",
    "1H": "1hour", 
    "4H": "4hour",
    "1D": "1day"
}

def fetch_crypto_markets(category: str = "crypto", 
                        status: str = "open",
                        limit: int = 1000) -> pd.DataFrame:
    """
    Fetch crypto markets from Kalshi API.
    
    Args:
        category: Market category filter
        status: Market status filter
        limit: Maximum number of markets to fetch
        
    Returns:
        DataFrame with market information
    """
    url = f"{BASE}/markets"
    params = {
        "category": category,
        "status": status,
        "limit": limit
    }
    
    try:
        logger.info(f"Fetching crypto markets: category={category}, status={status}")
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        
        data = r.json().get("markets", [])
        
        if not data:
            logger.warning(f"No crypto markets found for category={category}, status={status}")
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
        
        # Filter for crypto markets
        crypto_patterns = [pattern for pattern in CRYPTO_SERIES_PATTERNS]
        crypto_mask = df['series_ticker'].str.contains('|'.join(crypto_patterns), na=False)
        df = df[crypto_mask]
        
        logger.info(f"Fetched {len(df)} crypto markets")
        
        return df
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch crypto markets: {e}")
        raise
    except Exception as e:
        logger.error(f"Error processing crypto markets data: {e}")
        raise

def fetch_market_history(market_ticker: str, 
                         limit: int = 1000,
                         timeframe: str = "15M") -> pd.DataFrame:
    """
    Fetch historical price data for a specific market.
    
    Args:
        market_ticker: Market ticker identifier
        limit: Maximum number of price points to fetch
        timeframe: Timeframe for data (15M, 1H, 4H, 1D)
        
    Returns:
        DataFrame with price history
    """
    url = f"{BASE}/markets/{market_ticker}/price_history"
    params = {"limit": limit}
    
    try:
        logger.info(f"Fetching market history: {market_ticker}, limit={limit}")
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        
        history_data = r.json().get("history", [])
        
        if not history_data:
            logger.warning(f"No price history found: {market_ticker}")
            return pd.DataFrame()
        
        df = pd.DataFrame(history_data)
        
        # Convert timestamp
        if 'ts' in df.columns:
            df['timestamp'] = pd.to_datetime(df['ts'], unit="s", utc=True)
            df = df.set_index('timestamp').sort_index()
        
        # Convert numeric columns
        numeric_cols = ['yes_price', 'no_price']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Calculate price in dollars (cents to dollars)
        if 'yes_price' in df.columns:
            df['price'] = df['yes_price'] / 100.0
        
        # Add timeframe information
        df['timeframe'] = timeframe
        
        logger.info(f"Fetched {len(df)} price points for {market_ticker}")
        
        return df
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch market history {market_ticker}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error processing market history: {e}")
        raise

def build_returns_matrix(market_tickers: List[str],
                        timeframe: str = "15M",
                        limit: int = 1000,
                        min_periods: int = 10) -> pd.DataFrame:
    """
    Build multivariate returns matrix from multiple Kalshi markets.
    
    Args:
        market_tickers: List of market tickers
        timeframe: Timeframe for data
        limit: Maximum price points per market
        min_periods: Minimum periods required for returns calculation
        
    Returns:
        DataFrame with returns matrix (columns = markets, rows = time)
    """
    if not market_tickers:
        raise ValueError("No market tickers provided")
    
    logger.info(f"Building returns matrix for {len(market_tickers)} markets")
    
    series = {}
    
    for i, ticker in enumerate(market_tickers):
        try:
            # Fetch market history
            df = fetch_market_history(ticker, limit=limit, timeframe=timeframe)
            
            if df.empty or 'price' not in df.columns:
                logger.warning(f"No price data for {ticker}")
                continue
            
            # Calculate returns
            price_series = df['price'].dropna()
            if len(price_series) < min_periods:
                logger.warning(f"Insufficient data for {ticker}: {len(price_series)} < {min_periods}")
                continue
            
            returns = price_series.pct_change().dropna()
            
            if len(returns) > 0:
                series[ticker] = returns
                logger.info(f"Added {ticker}: {len(returns)} returns")
            else:
                logger.warning(f"No returns calculated for {ticker}")
                
        except Exception as e:
            logger.error(f"Error processing {ticker}: {e}")
            continue
    
    if not series:
        raise ValueError("No valid return series generated")
    
    # Combine into DataFrame
    returns_df = pd.DataFrame(series).dropna()
    
    logger.info(f"Built returns matrix: {returns_df.shape}, columns: {list(returns_df.columns)}")
    
    return returns_df

def get_crypto_market_tickers(timeframe: str = "15M") -> List[str]:
    """
    Get list of available crypto market tickers for a specific timeframe.
    
    Args:
        timeframe: Timeframe for markets
        
    Returns:
        List of market tickers
    """
    try:
        # Fetch crypto markets
        markets_df = fetch_crypto_markets()
        
        if markets_df.empty:
            return []
        
        # Filter for active markets with volume
        active_markets = markets_df[
            (markets_df['volume'] > 0) & 
            (markets_df['yes_price'] > 0) & 
            (markets_df['yes_price'] < 100)
        ]
        
        # Filter by timeframe if possible (check ticker patterns)
        timeframe_suffix = timeframe.replace("M", "min").replace("H", "hour").replace("D", "day")
        
        # Try to match timeframe in ticker
        timeframe_mask = active_markets['ticker'].str.contains(timeframe_suffix, na=False, case=False)
        timeframe_markets = active_markets[timeframe_mask]
        
        if timeframe_markets.empty:
            # Fallback to all active markets
            timeframe_markets = active_markets
        
        # Get unique tickers
        tickers = timeframe_markets['ticker'].unique().tolist()
        
        logger.info(f"Found {len(tickers)} crypto markets for {timeframe} timeframe")
        
        return tickers[:20]  # Limit to top 20 markets
        
    except Exception as e:
        logger.error(f"Error getting crypto market tickers: {e}")
        return []

def build_portfolio_returns(num_assets: int = 2,
                           timeframe: str = "15M",
                           limit: int = 500) -> pd.DataFrame:
    """
    Build portfolio returns matrix for a specified number of crypto assets.
    
    Args:
        num_assets: Number of assets to include
        timeframe: Timeframe for data
        limit: Price history limit
        
    Returns:
        DataFrame with portfolio returns
    """
    # Get available crypto tickers
    tickers = get_crypto_market_tickers(timeframe)
    
    if len(tickers) < num_assets:
        logger.warning(f"Only {len(tickers)} tickers available, requested {num_assets}")
        num_assets = len(tickers)
    
    # Select top tickers
    selected_tickers = tickers[:num_assets]
    
    # Build returns matrix
    returns_df = build_returns_matrix(selected_tickers, timeframe=timeframe, limit=limit)
    
    return returns_df

def validate_returns_matrix(returns_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Validate and analyze returns matrix quality.
    
    Args:
        returns_df: Returns matrix DataFrame
        
    Returns:
        Validation results
    """
    if returns_df.empty:
        return {"valid": False, "error": "Empty returns matrix"}
    
    validation = {
        "valid": True,
        "warnings": [],
        "info": {}
    }
    
    # Basic info
    validation["info"]["shape"] = returns_df.shape
    validation["info"]["assets"] = list(returns_df.columns)
    validation["info"]["date_range"] = {
        "start": returns_df.index[0],
        "end": returns_df.index[-1],
        "periods": len(returns_df)
    }
    
    # Check for missing data
    missing_data = returns_df.isnull().sum()
    if missing_data.any():
        validation["warnings"].append(f"Missing data detected: {missing_data[missing_data > 0].to_dict()}")
    
    # Check for zero variance
    zero_var = returns_df.var() == 0
    if zero_var.any():
        validation["warnings"].append(f"Zero variance assets: {zero_var[zero_var].index.tolist()}")
    
    # Correlation analysis
    corr_matrix = returns_df.corr()
    high_corr_pairs = []
    
    for i in range(len(corr_matrix.columns)):
        for j in range(i+1, len(corr_matrix.columns)):
            corr_val = corr_matrix.iloc[i, j]
            if abs(corr_val) > 0.9:
                high_corr_pairs.append((corr_matrix.columns[i], corr_matrix.columns[j], corr_val))
    
    if high_corr_pairs:
        validation["warnings"].append(f"High correlation pairs: {high_corr_pairs}")
    
    # Basic statistics
    validation["info"]["mean_returns"] = returns_df.mean().to_dict()
    validation["info"]["volatility"] = returns_df.std().to_dict()
    validation["info"]["avg_correlation"] = corr_matrix.values[np.triu_indices_from(corr_matrix.shape, k=1)].mean()
    
    # Check for extreme values
    extreme_threshold = 5  # 5 standard deviations
    z_scores = (returns_df - returns_df.mean()) / returns_df.std()
    extreme_values = (np.abs(z_scores) > extreme_threshold).sum().sum()
    
    if extreme_values > 0:
        validation["warnings"].append(f"Extreme values detected: {extreme_values} observations")
    
    return validation

def sample_portfolio_data(num_assets: int = 2,
                         num_periods: int = 200,
                         seed: int = 42) -> pd.DataFrame:
    """
    Generate sample portfolio data for testing.
    
    Args:
        num_assets: Number of assets
        num_periods: Number of time periods
        seed: Random seed
        
    Returns:
        Sample returns DataFrame
    """
    import numpy as np
    
    np.random.seed(seed)
    
    # Generate correlated returns
    mean_returns = np.array([0.001, 0.0015])[:num_assets]
    
    # Create correlation matrix
    corr = np.array([[1.0, 0.3], [0.3, 1.0]])[:num_assets, :num_assets]
    
    # Create covariance matrix
    vol = np.array([0.02, 0.025])[:num_assets]
    cov = np.outer(vol, vol) * corr
    
    # Generate returns
    returns = np.random.multivariate_normal(mean_returns, cov, num_periods)
    
    # Create DataFrame
    asset_names = [f"Asset_{i+1}" for i in range(num_assets)]
    dates = pd.date_range("2023-01-01", periods=num_periods, freq="15min")
    
    df = pd.DataFrame(returns, index=dates, columns=asset_names)
    
    logger.info(f"Generated sample data: {df.shape}")
    
    return df

# Example usage:
"""
# Get available crypto markets
markets_df = fetch_crypto_markets()
print(f"Found {len(markets_df)} crypto markets")

# Get specific market tickers
tickers = get_crypto_market_tickers("15M")
print(f"Available 15M tickers: {tickers[:5]}")

# Build returns matrix for top 2 assets
returns_df = build_portfolio_returns(num_assets=2, timeframe="15M", limit=500)
print(f"Returns matrix shape: {returns_df.shape}")

# Validate returns matrix
validation = validate_returns_matrix(returns_df)
print(f"Validation: {'✅ Valid' if validation['valid'] else '⚠️ Issues found'}")

# Generate sample data for testing
sample_df = sample_portfolio_data(num_assets=2, num_periods=100)
print(f"Sample data: {sample_df.shape}")
"""
