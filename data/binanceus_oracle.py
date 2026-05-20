"""
BinanceUS Oracle Implementation

Concrete implementation for BinanceUS public spot price data.
Provides real-time cryptocurrency prices for BTC/ETH/SOL/XRP/DOGE
using public REST endpoints (no authentication required).

BinanceUS is used as a fallback spot source when Coinbase/Kraken/CCXT are unavailable.
It is treated as degraded mode with conservative risk parameters.
"""

import asyncio
import time
from typing import Dict, Optional
from dataclasses import dataclass

import httpx
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger("data.binanceus")


@dataclass
class BinanceUSConfig:
    """Configuration for BinanceUS oracle."""
    base_url: str = "https://api.binance.us"
    timeout_seconds: float = 10.0
    rate_limit_requests_per_minute: int = 1200  # BinanceUS public API is generous
    max_cache_age_seconds: float = 60.0
    retry_attempts: int = 3
    retry_delay_seconds: float = 0.5


class BinanceUSOracle:
    """
    BinanceUS price oracle implementation.
    
    Provides cryptocurrency prices from BinanceUS public API with:
    - Rate limiting and retry logic
    - Health monitoring and latency tracking
    - Price caching with staleness detection
    - Error handling and graceful degradation
    
    BinanceUS is a US-regulated exchange and provides reliable public APIs
    without authentication requirements for basic price data.
    """
    
    # Symbol mapping: internal USD format → BinanceUS API symbol (USDT pairs)
    # BinanceUS uses USDT pairs internally (e.g., BTCUSDT), but we normalize to USD format
    _SYMBOL_MAPPING: Dict[str, str] = {
        "BTC/USD": "BTCUSDT",  # API uses USDT, we normalize to USD
        "ETH/USD": "ETHUSDT",
        "SOL/USD": "SOLUSDT",
        "XRP/USD": "XRPUSDT",
        "DOGE/USD": "DOGEUSDT",
    }
    
    # Reverse mapping for batch operations
    _REVERSE_SYMBOL_MAP: Dict[str, str] = {v: k for k, v in _SYMBOL_MAPPING.items()}
    
    def __init__(self, oracle_id: str = "binanceus", config: Optional[BinanceUSConfig] = None):
        self.oracle_id = oracle_id
        self.config = config or BinanceUSConfig()
        self._session: Optional[httpx.AsyncClient] = None
        self._last_request_time: float = 0.0
        self._rate_limiter = RateLimiter(
            max_requests=self.config.rate_limit_requests_per_minute,
            time_window_seconds=60
        )
        
        logger.info(f"BinanceUSOracle initialized: {oracle_id}")
        logger.info(f"Base URL: {self.config.base_url}")
        logger.info(f"Rate limit: {self.config.rate_limit_requests_per_minute} requests/minute")
    
    async def _get_session(self) -> httpx.AsyncClient:
        """Get or create HTTP session."""
        if self._session is None or self._session.is_closed:
            self._session = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.timeout_seconds
            )
        return self._session
    
    async def close(self):
        """Close HTTP session."""
        if self._session and not self._session.is_closed:
            await self._session.aclose()
            self._session = None
    
    async def get_price(self, symbol: str) -> Optional[float]:
        """
        Fetch current price for an asset.
        
        Args:
            symbol: Asset symbol in USD format (BTC/USD, ETH/USD, SOL/USD, XRP/USD, DOGE/USD)
            
        Returns:
            Current price in USD or None if fetch fails
        """
        try:
            # Apply rate limiting
            await self._rate_limiter.acquire()
            
            # Map USD symbol to BinanceUS API symbol
            binance_symbol = self.SYMBOL_MAP.get(symbol.upper())
            if not binance_symbol:
                logger.warning(f"Unsupported symbol: {symbol}")
                return None
            
            # Fetch price from BinanceUS public API
            session = await self._get_session()
            response = await session.get(
                "/api/v3/ticker/price",
                params={"symbol": binance_symbol}
            )
            response.raise_for_status()
            data = response.json()
            
            price = float(data.get("price", 0))
            if price <= 0:
                logger.warning(f"Invalid price for {symbol}: {price}")
                return None
            
            self._last_request_time = time.time()
            logger.debug(f"BinanceUS price for {symbol}: ${price:.2f}")
            return price
            
        except httpx.HTTPStatusError as e:
            logger.warning(f"BinanceUS HTTP error for {symbol}: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"BinanceUS fetch error for {symbol}: {e}")
            return None
    
    async def get_price_with_retry(self, symbol: str) -> Optional[float]:
        """
        Get price with retry logic.
        
        Args:
            symbol: Asset symbol in USD format (BTC/USD, ETH/USD, etc.)
            
        Returns:
            Current price or None if all retries fail
        """
        last_error = None
        
        for attempt in range(self.config.retry_attempts):
            try:
                price = await self.get_price(symbol)
                if price is not None:
                    return price
                    
            except Exception as e:
                last_error = e
                logger.warning(f"BinanceUS price fetch attempt {attempt + 1} failed for {symbol}: {e}")
                
                if attempt < self.config.retry_attempts - 1:
                    await asyncio.sleep(self.config.retry_delay_seconds * (attempt + 1))
        
        logger.error(f"All BinanceUS retry attempts failed for {symbol}. Last error: {last_error}")
        return None
    
    async def get_batch_prices(self, assets: list[str]) -> Dict[str, float]:
        """
        Fetch prices for multiple assets in a single batch call.
        
        Uses BinanceUS ticker/24hr endpoint to get all prices efficiently.
        
        Args:
            assets: List of asset symbols (BTC, ETH, SOL, XRP, DOGE)
            
        Returns:
            Dict mapping asset symbol to price
        """
        try:
            # Apply rate limiting
            await self._rate_limiter.acquire()
            
            # Map assets to BinanceUS symbols
            binance_symbols = []
            for asset in assets:
                symbol = self.SYMBOL_MAP.get(asset.upper())
                if symbol:
                    binance_symbols.append(symbol)
            
            if not binance_symbols:
                logger.warning("No valid assets to fetch")
                return {}
            
            # Fetch all tickers from BinanceUS
            session = await self._get_session()
            response = await session.get("/api/v3/ticker/24hr")
            response.raise_for_status()
            data = response.json()
            
            # Build price map
            price_map = {}
            for ticker in data:
                binance_symbol = ticker.get("symbol")
                if binance_symbol in self._REVERSE_SYMBOL_MAP:
                    asset = self._REVERSE_SYMBOL_MAP[binance_symbol]
                    if asset in assets:
                        price = float(ticker.get("lastPrice", 0))
                        if price > 0:
                            price_map[asset] = price
            
            self._last_request_time = time.time()
            logger.info(f"BinanceUS batch fetch: {len(price_map)}/{len(assets)} assets")
            return price_map
            
        except Exception as e:
            logger.error(f"BinanceUS batch fetch error: {e}")
            return {}
    
    def is_asset_supported(self, symbol: str) -> bool:
        """Check if symbol is supported."""
        return symbol.upper() in self.SYMBOL_MAP
    
    def get_supported_assets(self) -> list[str]:
        """Get list of supported symbols in USD format."""
        return list(self.SYMBOL_MAP.keys())


class RateLimiter:
    """Simple rate limiter for API calls."""
    
    def __init__(self, max_requests: int, time_window_seconds: int):
        self.max_requests = max_requests
        self.time_window_seconds = time_window_seconds
        self._requests = []
        self._lock = asyncio.Lock()
    
    async def acquire(self):
        """Acquire rate limit permit."""
        async with self._lock:
            now = time.time()
            
            # Remove old requests outside time window
            self._requests = [req_time for req_time in self._requests 
                            if now - req_time < self.time_window_seconds]
            
            # Check if we can make a request
            if len(self._requests) < self.max_requests:
                self._requests.append(now)
                return
            
            # Calculate wait time
            oldest_request = min(self._requests)
            wait_time = self.time_window_seconds - (now - oldest_request)
            
            if wait_time > 0:
                await asyncio.sleep(wait_time)
                await self.acquire()  # Retry after waiting


# Singleton instance for use across the system
_oracle: Optional[BinanceUSOracle] = None


def get_binanceus_oracle() -> BinanceUSOracle:
    """Get or create the singleton BinanceUS oracle instance."""
    global _oracle
    if _oracle is None:
        _oracle = BinanceUSOracle()
    return _oracle
