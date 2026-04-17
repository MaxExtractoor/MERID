"""
Handle Kalshi API Rate Limits in Multivariate Fetching

Rate-limited client for Kalshi API to stay within documented per-second caps.
"""

import time
import threading
import requests
from collections import deque
from typing import Dict, Any, Optional, List
import logging
from functools import wraps
import backoff
import os

logger = logging.getLogger(__name__)

# Kalshi API configuration - read from env to support demo/live modes
BASE = os.getenv("KALSHI_API_BASE_URL", "https://demo-api.kalshi.co/trade-api/v2")

# Rate limiting configuration
# Basic tier: 20 requests per second reads
# We use conservative values to stay within limits
READ_LIMIT_PER_SEC = 18  # Conservative under Basic 20/s limit
BURST_LIMIT = 5  # Allow small bursts
TIME_WINDOW = 1.0  # 1 second window

class KalshiRateLimiter:
    """
    Thread-safe rate limiter for Kalshi API requests.
    
    Implements token bucket algorithm with configurable rate limits.
    """
    
    def __init__(self, requests_per_second: float = READ_LIMIT_PER_SEC, burst_limit: int = BURST_LIMIT):
        self.requests_per_second = requests_per_second
        self.burst_limit = burst_limit
        self.tokens = burst_limit
        self.last_update = time.time()
        self.lock = threading.Lock()
        
        logger.info(f"Kalshi rate limiter initialized: {requests_per_second} rps, burst: {burst_limit}")
    
    def _add_tokens(self) -> None:
        """Add tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_update
        
        if elapsed > 0:
            tokens_to_add = elapsed * self.requests_per_second
            self.tokens = min(self.burst_limit, self.tokens + tokens_to_add)
            self.last_update = now
    
    def acquire_token(self, block: bool = True, timeout: Optional[float] = None) -> bool:
        """
        Acquire a token for API request.
        
        Args:
            block: Whether to block until token is available
            timeout: Maximum time to wait for token
            
        Returns:
            True if token acquired, False if timeout
        """
        with self.lock:
            self._add_tokens()
            
            if self.tokens >= 1:
                self.tokens -= 1
                return True
            
            if not block:
                return False
            
            # Calculate wait time
            deficit = 1.0 - self.tokens
            wait_time = deficit / self.requests_per_second
            
            if timeout is not None and wait_time > timeout:
                return False
        
        # Sleep outside the lock to avoid blocking other threads
        time.sleep(wait_time)
        
        with self.lock:
            self._add_tokens()
            
            if self.tokens >= 1:
                self.tokens -= 1
                return True
            
            return False

# Global rate limiter instance
_rate_limiter = KalshiRateLimiter()

def rate_limit_decorator(max_retries: int = 3, backoff_factor: float = 1.0):
    """
    Decorator for rate-limited API calls with retry logic.
    
    Args:
        max_retries: Maximum number of retries
        backoff_factor: Backoff multiplier for retries
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    # Acquire rate limit token
                    if not _rate_limiter.acquire_token(block=True, timeout=10.0):
                        raise requests.exceptions.Timeout("Rate limit timeout")
                    
                    # Make the API call
                    return func(*args, **kwargs)
                    
                except requests.exceptions.HTTPError as e:
                    last_exception = e
                    
                    # Don't retry on client errors (4xx)
                    if 400 <= e.response.status_code < 500:
                        raise
                    
                    # Retry on server errors (5xx) with backoff
                    if attempt < max_retries:
                        wait_time = backoff_factor * (2 ** attempt)
                        logger.warning(f"API error (attempt {attempt + 1}/{max_retries + 1}): {e}. Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    
                except requests.exceptions.RequestException as e:
                    last_exception = e
                    
                    # Retry on network errors with backoff
                    if attempt < max_retries:
                        wait_time = backoff_factor * (2 ** attempt)
                        logger.warning(f"Network error (attempt {attempt + 1}/{max_retries + 1}): {e}. Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        continue
            
            # All retries exhausted
            raise last_exception
        
        return wrapper
    return decorator

class KalshiRateLimitedClient:
    """
    Rate-limited Kalshi API client with automatic retry and error handling.
    """
    
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = requests.Session()
        
        # Configure session
        self.session.headers.update({
            'User-Agent': 'MERID-Kalshi-Client/1.0',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })
        
        # Add authentication if provided
        if api_key:
            self.session.headers['Authorization'] = f'Bearer {api_key}'
        
        logger.info("Kalshi rate-limited client initialized")
    
    @rate_limit_decorator(max_retries=3, backoff_factor=1.0)
    def get(self, path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 10) -> requests.Response:
        """
        Make rate-limited GET request to Kalshi API.
        
        Args:
            path: API endpoint path
            params: Query parameters
            timeout: Request timeout
            
        Returns:
            Response object
        """
        url = f"{BASE}{path}"
        
        logger.debug(f"Making GET request to {url}")
        
        response = self.session.get(url, params=params or {}, timeout=timeout)
        response.raise_for_status()
        
        return response
    
    @rate_limit_decorator(max_retries=3, backoff_factor=1.0)
    def post(self, path: str, data: Optional[Dict[str, Any]] = None, timeout: int = 10) -> requests.Response:
        """
        Make rate-limited POST request to Kalshi API.
        
        Args:
            path: API endpoint path
            data: Request data
            timeout: Request timeout
            
        Returns:
            Response object
        """
        url = f"{BASE}{path}"
        
        logger.debug(f"Making POST request to {url}")
        
        response = self.session.post(url, json=data or {}, timeout=timeout)
        response.raise_for_status()
        
        return response
    
    def fetch_markets_batch(self, market_ids: List[str], batch_size: int = 10) -> List[Dict[str, Any]]:
        """
        Fetch multiple markets in batches to respect rate limits.
        
        Args:
            market_ids: List of market IDs to fetch
            batch_size: Number of markets per batch
            
        Returns:
            List of market data
        """
        all_markets = []
        
        for i in range(0, len(market_ids), batch_size):
            batch_ids = market_ids[i:i + batch_size]
            
            try:
                # Fetch batch
                response = self.get("/markets", params={"ids": ",".join(batch_ids)})
                markets_data = response.json().get("markets", [])
                all_markets.extend(markets_data)
                
                logger.info(f"Fetched batch {i//batch_size + 1}: {len(markets_data)} markets")
                
                # Small delay between batches to avoid hitting limits
                if i + batch_size < len(market_ids):
                    time.sleep(0.1)
                    
            except Exception as e:
                logger.error(f"Error fetching batch {i//batch_size + 1}: {e}")
                continue
        
        return all_markets
    
    def fetch_ohlc_series(self, ticker: str, limit: int = 1000) -> Dict[str, Any]:
        """
        Fetch OHLC data for a specific ticker.
        
        Args:
            ticker: Market ticker
            limit: Maximum number of data points
            
        Returns:
            OHLC data
        """
        try:
            response = self.get(f"/markets/{ticker}/history", params={"limit": limit})
            return response.json()
            
        except Exception as e:
            logger.error(f"Error fetching OHLC data for {ticker}: {e}")
            raise
    
    def get_rate_limit_status(self) -> Dict[str, Any]:
        """
        Get current rate limiter status.
        
        Returns:
            Rate limiter status
        """
        with _rate_limiter.lock:
            _rate_limiter._add_tokens()
            
            return {
                "available_tokens": _rate_limiter.tokens,
                "max_tokens": _rate_limiter.burst_limit,
                "requests_per_second": _rate_limiter.requests_per_second,
                "last_update": _rate_limiter.last_update
            }

# Global client instance
_client: Optional[KalshiRateLimitedClient] = None

def get_kalshi_client(api_key: Optional[str] = None, api_secret: Optional[str] = None) -> KalshiRateLimitedClient:
    """
    Get or create global Kalshi rate-limited client.
    
    Args:
        api_key: Kalshi API key
        api_secret: Kalshi API secret
        
    Returns:
        KalshiRateLimitedClient instance
    """
    global _client
    
    if _client is None:
        _client = KalshiRateLimitedClient(api_key, api_secret)
    
    return _client

def get(path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 10) -> requests.Response:
    """
    Convenience function for rate-limited GET requests.
    
    Args:
        path: API endpoint path
        params: Query parameters
        timeout: Request timeout
        
    Returns:
        Response object
    """
    client = get_kalshi_client()
    return client.get(path, params, timeout)

def post(path: str, data: Optional[Dict[str, Any]] = None, timeout: int = 10) -> requests.Response:
    """
    Convenience function for rate-limited POST requests.
    
    Args:
        path: API endpoint path
        data: Request data
        timeout: Request timeout
        
    Returns:
        Response object
    """
    client = get_kalshi_client()
    return client.post(path, data, timeout)

def configure_rate_limiting(requests_per_second: float = READ_LIMIT_PER_SEC, burst_limit: int = BURST_LIMIT):
    """
    Configure global rate limiting parameters.
    
    Args:
        requests_per_second: Maximum requests per second
        burst_limit: Maximum burst size
    """
    global _rate_limiter
    _rate_limiter = KalshiRateLimiter(requests_per_second, burst_limit)
    
    logger.info(f"Rate limiting configured: {requests_per_second} rps, burst: {burst_limit}")

# Example usage:
"""
# Initialize client
client = get_kalshi_client(api_key="your_key", api_secret="your_secret")

# Fetch markets (rate-limited)
markets = client.fetch_markets_batch(market_ids, batch_size=10)

# Fetch OHLC data (rate-limited)
ohlc = client.fetch_ohlc_series("KXBTC15M-EXAMPLE", limit=500)

# Check rate limiter status
status = client.get_rate_limit_status()
print(f"Available tokens: {status['available_tokens']}/{status['max_tokens']}")

# Use convenience functions
response = get("/markets", params={"category": "crypto"})
data = response.json()

# Configure custom rate limits
configure_rate_limiting(requests_per_second=15, burst_limit=8)
"""

# =============================================================================
# MULTIVARIATE FETCHING WITH RATE LIMITING
# =============================================================================

def fetch_crypto_markets_rate_limited(category: str = "crypto", limit: int = 1000) -> List[Dict[str, Any]]:
    """
    Fetch crypto markets with rate limiting.
    
    Args:
        category: Market category filter
        limit: Maximum number of markets to fetch
        
    Returns:
        List of market data
    """
    client = get_kalshi_client()
    
    try:
        response = client.get("/markets", params={"category": category, "limit": limit})
        markets_data = response.json().get("markets", [])
        
        logger.info(f"Fetched {len(markets_data)} crypto markets")
        return markets_data
        
    except Exception as e:
        logger.error(f"Error fetching crypto markets: {e}")
        return []

def build_returns_matrix_rate_limited(market_tickers: List[str], 
                                     limit_per_market: int = 1000,
                                     batch_delay: float = 0.1) -> "pd.DataFrame":
    """
    Build returns matrix with rate limiting for multiple markets.
    
    Args:
        market_tickers: List of market tickers
        limit_per_market: Data points per market
        batch_delay: Delay between market requests
        
    Returns:
        DataFrame with returns matrix
    """
    import pandas as pd
    import numpy as np
    
    client = get_kalshi_client()
    series = {}
    
    logger.info(f"Building returns matrix for {len(market_tickers)} markets with rate limiting")
    
    for i, ticker in enumerate(market_tickers):
        try:
            # Fetch market history with rate limiting
            ohlc_data = client.fetch_ohlc_series(ticker, limit=limit_per_market)
            
            if not ohlc_data or "history" not in ohlc_data:
                logger.warning(f"No history data for {ticker}")
                continue
            
            # Convert to DataFrame
            df = pd.DataFrame(ohlc_data["history"])
            
            if "ts" in df.columns:
                df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
                df = df.set_index("ts").sort_index()
            
            # Calculate returns from close prices
            if "close" in df.columns:
                close_prices = pd.to_numeric(df["close"], errors='coerce') / 100.0  # Convert from cents
                returns = close_prices.pct_change().dropna()
                
                if len(returns) > 0:
                    series[ticker] = returns
                    logger.info(f"Added {ticker}: {len(returns)} returns")
                else:
                    logger.warning(f"No returns calculated for {ticker}")
            
            # Rate limiting delay between markets
            if i < len(market_tickers) - 1:
                time.sleep(batch_delay)
                
        except Exception as e:
            logger.error(f"Error processing {ticker}: {e}")
            continue
    
    if not series:
        raise ValueError("No valid return series generated")
    
    # Combine into DataFrame
    returns_df = pd.DataFrame(series).dropna()
    
    logger.info(f"Built returns matrix: {returns_df.shape}, columns: {list(returns_df.columns)}")
    
    return returns_df

# =============================================================================
# MONITORING AND METRICS
# =============================================================================

class RateLimitMonitor:
    """
    Monitor rate limiting usage and performance.
    """
    
    def __init__(self):
        self.request_count = 0
        self.error_count = 0
        self.start_time = time.time()
        self.lock = threading.Lock()
    
    def record_request(self, success: bool = True):
        """Record a request attempt."""
        with self.lock:
            self.request_count += 1
            if not success:
                self.error_count += 1
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get rate limiting metrics."""
        with self.lock:
            elapsed = time.time() - self.start_time
            rps = self.request_count / elapsed if elapsed > 0 else 0
            error_rate = self.error_count / self.request_count if self.request_count > 0 else 0
            
            return {
                "total_requests": self.request_count,
                "error_count": self.error_count,
                "requests_per_second": rps,
                "error_rate": error_rate,
                "uptime_seconds": elapsed
            }

# Global monitor
_monitor = RateLimitMonitor()

def get_rate_limit_metrics() -> Dict[str, Any]:
    """Get comprehensive rate limiting metrics."""
    client_metrics = get_kalshi_client().get_rate_limit_status()
    monitor_metrics = _monitor.get_metrics()
    
    return {
        "rate_limiter": client_metrics,
        "usage": monitor_metrics,
        "limits": {
            "max_rps": READ_LIMIT_PER_SEC,
            "burst_limit": BURST_LIMIT
        }
    }
