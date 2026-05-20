"""
BinanceUS Authentication and Rate Limits

Authentication pattern for BinanceUS API with rate limit handling.
"""

import os
import hmac
import hashlib
import time
import urllib.parse
import requests
import logging
from typing import Dict, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

BINANCE_US_BASE = "https://api.binance.us"
API_KEY = os.getenv("BINANCE_US_API_KEY")
API_SECRET = os.getenv("BINANCE_US_API_SECRET", "").encode()

@dataclass
class RateLimitInfo:
    """Rate limit information."""
    endpoint: str
    weight: int
    limit_type: str
    interval: str
    limit: int

class BinanceAuthClient:
    """BinanceUS authenticated client with rate limit handling."""
    
    def __init__(self, api_key: str = None, api_secret: str = None):
        """
        Initialize BinanceUS client.
        
        Args:
            api_key: API key (defaults to environment variable)
            api_secret: API secret (defaults to environment variable)
        """
        self.api_key = api_key or API_KEY
        self.api_secret = (api_secret or API_SECRET).encode()
        
        if not self.api_key or not self.api_secret:
            logger.warning("API credentials not found - public endpoints only")
        
        # Rate limiting
        self.rate_limits = {}
        self.last_request_time = {}
        self.request_weights = {}
        
        # Session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'MERID-Strategy/1.0',
            'Content-Type': 'application/x-www-form-urlencoded'
        })
    
    def close(self) -> None:
        """Close the requests session to free resources. Call on shutdown."""
        if self.session is not None:
            try:
                self.session.close()
                logger.debug("BinanceAuth: requests session closed")
            except Exception as e:
                logger.warning("BinanceAuth: error closing session: %s", e)
    
    def __del__(self) -> None:
        """Cleanup on garbage collection (fallback if close() not called)."""
        self.close()
    
    def sign_params(self, params: Dict) -> str:
        """
        Sign parameters with HMAC SHA256.
        
        Args:
            params: Parameters to sign
            
        Returns:
            Query string with signature
        """
        if not self.api_secret:
            raise ValueError("API secret required for signing")
        
        # Add timestamp
        params["timestamp"] = int(time.time() * 1000)
        
        # Create query string
        query = urllib.parse.urlencode(sorted(params.items()))
        
        # Generate signature
        signature = hmac.new(
            self.api_secret,
            query.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return f"{query}&signature={signature}"
    
    def auth_get(self, path: str, params: Optional[Dict] = None) -> requests.Response:
        """
        Make authenticated GET request.
        
        Args:
            path: API endpoint path
            params: Query parameters
            
        Returns:
            Response object
        """
        if not self.api_key or not self.api_secret:
            raise ValueError("API credentials required for authenticated requests")
        
        params = params or {}
        
        # Check rate limits
        self._check_rate_limits(path, 'GET')
        
        # Sign parameters
        query_string = self.sign_params(params)
        url = f"{BINANCE_US_BASE}{path}?{query_string}"
        
        headers = {"X-MBX-APIKEY": self.api_key}
        
        try:
            response = self.session.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            logger.error(f"Authenticated GET request failed: {e}")
            raise
    
    def auth_post(self, path: str, params: Optional[Dict] = None, data: Optional[Dict] = None) -> requests.Response:
        """
        Make authenticated POST request.
        
        Args:
            path: API endpoint path
            params: Query parameters
            data: POST data
            
        Returns:
            Response object
        """
        if not self.api_key or not self.api_secret:
            raise ValueError("API credentials required for authenticated requests")
        
        params = params or {}
        
        # Check rate limits
        self._check_rate_limits(path, 'POST')
        
        # Sign parameters
        query_string = self.sign_params(params)
        url = f"{BINANCE_US_BASE}{path}?{query_string}"
        
        headers = {"X-MBX-APIKEY": self.api_key}
        
        try:
            response = self.session.post(url, headers=headers, json=data, timeout=10)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            logger.error(f"Authenticated POST request failed: {e}")
            raise
    
    def _check_rate_limits(self, path: str, method: str):
        """
        Check and enforce rate limits.
        
        Args:
            path: API endpoint path
            method: HTTP method
        """
        # Get rate limit info for endpoint
        rate_info = self._get_rate_limit_info(path, method)
        
        if not rate_info:
            return
        
        # Simple rate limiting (per second)
        current_time = time.time()
        last_time = self.last_request_time.get(path, 0)
        
        # Minimum time between requests based on weight
        min_interval = rate_info.weight / 10.0  # 10 requests per second per weight unit
        
        if current_time - last_time < min_interval:
            sleep_time = min_interval - (current_time - last_time)
            logger.info(f"Rate limiting {path}: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)
        
        self.last_request_time[path] = current_time
    
    def _get_rate_limit_info(self, path: str, method: str) -> Optional[RateLimitInfo]:
        """
        Get rate limit information for endpoint.
        
        Args:
            path: API endpoint path
            method: HTTP method
            
        Returns:
            RateLimitInfo or None
        """
        # Common rate limits (simplified)
        rate_limits = {
            '/api/v3/account': RateLimitInfo('/api/v3/account', 10, 'REQUEST_WEIGHT', 'PER_SECOND', 1200),
            '/api/v3/myTrades': RateLimitInfo('/api/v3/myTrades', 10, 'REQUEST_WEIGHT', 'PER_SECOND', 1200),
            '/api/v3/order': RateLimitInfo('/api/v3/order', 1, 'ORDERS', 'PER_SECOND', 10),
            '/api/v3/klines': RateLimitInfo('/api/v3/klines', 1, 'REQUEST_WEIGHT', 'PER_SECOND', 1200),
            '/api/v3/ticker/24hr': RateLimitInfo('/api/v3/ticker/24hr', 1, 'REQUEST_WEIGHT', 'PER_SECOND', 1200),
        }
        
        return rate_limits.get(path)
    
    def get_account_info(self) -> Dict:
        """
        Get account information.
        
        Returns:
        """
        try:
            response = self.auth_get('/api/v3/account')
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get account info: {e}")
            return {}
    
    def get_exchange_info(self) -> Dict:
        """
        Get exchange information including rate limits.
        
        Returns:
        """
        try:
            # Public endpoint, no auth needed
            response = requests.get(f"{BINANCE_US_BASE}/api/v3/exchangeInfo", timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get exchange info: {e}")
            return {}
    
    def get_trades(self, symbol: str = None, limit: int = 500) -> List[Dict]:
        """
        Get recent trades.
        
        Args:
            symbol: Trading symbol (optional)
            limit: Number of trades (max 1000)
            
        Returns:
        """
        try:
            params = {'limit': limit}
            if symbol:
                params['symbol'] = symbol
            
            response = self.auth_get('/api/v3/myTrades', params)
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get trades: {e}")
            return []
    
    def place_order(self, symbol: str, side: str, type: str, quantity: float, 
                   price: float = None, timeInForce: str = "GTC") -> Dict:
        """
        Place a new order.
        
        Args:
            symbol: Trading symbol
            side: Order side (BUY/SELL)
            type: Order type (MARKET/LIMIT)
            quantity: Order quantity
            price: Order price (for LIMIT orders)
            timeInForce: Time in force
            
        Returns:
        """
        try:
            params = {
                'symbol': symbol,
                'side': side,
                'type': type,
                'quantity': str(quantity),
                'timeInForce': timeInForce
            }
            
            if price is not None and type.upper() == 'LIMIT':
                params['price'] = str(price)
            
            response = self.auth_post('/api/v3/order', params=params)
            return response.json()
        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            return {}
    
    def get_ticker(self, symbol: str) -> Dict:
        """
        Get 24hr ticker price change statistics.
        
        Args:
            symbol: Trading symbol
            
        Returns:
        """
        try:
            # Public endpoint
            response = requests.get(f"{BINANCE_US_BASE}/api/v3/ticker/24hr", 
                                  params={'symbol': symbol}, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get ticker for {symbol}: {e}")
            return {}
    
    def get_order_status(self, symbol: str, orderId: str) -> Dict:
        """
        Check order status.
        
        Args:
            symbol: Trading symbol
            orderId: Order ID
            
        Returns:
        """
        try:
            params = {'symbol': symbol, 'orderId': orderId}
            response = self.auth_get('/api/v3/order', params)
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get order status: {e}")
            return {}
    
    def cancel_order(self, symbol: str, orderId: str) -> Dict:
        """
        Cancel an order.
        
        Args:
            symbol: Trading symbol
            orderId: Order ID
            
        Returns:
        """
        try:
            params = {'symbol': symbol, 'orderId': orderId}
            response = self.auth_delete('/api/v3/order', params)
            return response.json()
        except Exception as e:
            logger.error(f"Failed to cancel order: {e}")
            return {}
    
    def auth_delete(self, path: str, params: Optional[Dict] = None) -> requests.Response:
        """
        Make authenticated DELETE request.
        
        Args:
            path: API endpoint path
            params: Query parameters
            
        Returns:
            Response object
        """
        if not self.api_key or not self.api_secret:
            raise ValueError("API credentials required for authenticated requests")
        
        params = params or {}
        
        # Check rate limits
        self._check_rate_limits(path, 'DELETE')
        
        # Sign parameters
        query_string = self.sign_params(params)
        url = f"{BINANCE_US_BASE}{path}?{query_string}"
        
        headers = {"X-MBX-APIKEY": self.api_key}
        
        try:
            response = self.session.delete(url, headers=headers, timeout=10)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            logger.error(f"Authenticated DELETE request failed: {e}")
            raise
    
    def validate_credentials(self) -> bool:
        """
        Validate API credentials by making a test request.
        
        Returns:
            True if credentials are valid
        """
        try:
            account_info = self.get_account_info()
            return bool(account_info and 'canTrade' in account_info)
        except Exception as e:
            logger.error(f"Credential validation failed: {e}")
            return False

# Example usage:
"""
# Initialize client
client = BinanceAuthClient()

# Validate credentials
if client.validate_credentials():
    print("Credentials valid")
    
    # Get account info
    account = client.get_account_info()
    print(f"Account: {account}")
    
    # Get ticker
    ticker = client.get_ticker('BTCUSDT')
    print(f"BTC ticker: {ticker}")
    
    # Place order (example)
    order = client.place_order(
        symbol='BTCUSDT',
        side='BUY',
        type='MARKET',
        quantity=0.001
    )
    print(f"Order: {order}")
else:
    print("Invalid credentials - using public endpoints only")

# Get exchange info (public)
exchange_info = client.get_exchange_info()
print(f"Exchange info: {len(exchange_info.get('symbols', []))} symbols")
"""
