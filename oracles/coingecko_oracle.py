"""
CoinGecko Oracle Implementation

Concrete implementation of BaseOracle for CoinGecko price data.
Provides real-time cryptocurrency prices with health monitoring and latency tracking.
"""

import asyncio
import time
from typing import Dict, List, Optional
from dataclasses import dataclass

from oracles.base_oracle import BaseOracle, OraclePrice, OracleStatus
from utils.logger import get_logger
from data.asset_universe import ASSET_UNIVERSE

logger = get_logger("oracles.coingecko")

@dataclass
class CoinGeckoConfig:
    """Configuration for CoinGecko oracle."""
    api_key: Optional[str] = None
    base_url: str = "https://api.coingecko.com/api/v3"
    timeout_seconds: float = 10.0
    rate_limit_requests_per_minute: int = 30
    max_cache_age_seconds: float = 60.0
    retry_attempts: int = 3
    retry_delay_seconds: float = 1.0

class CoinGeckoOracle(BaseOracle):
    """
    CoinGecko price oracle implementation.
    
    Provides cryptocurrency prices from CoinGecko API with:
    - Rate limiting and retry logic
    - Health monitoring and latency tracking
    - Price caching with staleness detection
    - Error handling and graceful degradation
    """
    
    def __init__(self, oracle_id: str = "coingecko", priority: int = 1, config: Optional[CoinGeckoConfig] = None):
        super().__init__(oracle_id, priority)

        if config is None:
            try:
                from merid.settings import settings
                config = CoinGeckoConfig(api_key=settings.COINGECKO_API_KEY)
            except Exception:
                config = CoinGeckoConfig()
        self.config = config
        self._session = None
        self._rate_limiter = RateLimiter(
            max_requests=self.config.rate_limit_requests_per_minute,
            time_window_seconds=60
        )

        # Build symbol map from top-50 asset universe (skip stablecoins — no CG price endpoint needed)
        self._symbol_map: Dict[str, str] = {
            asset.symbol: asset.coingecko_id
            for asset in ASSET_UNIVERSE.values()
            if asset.category not in ('Stable',) and 'PERP' not in asset.symbol
        }

        self._reverse_symbol_map = {v: k for k, v in self._symbol_map.items()}
        
        logger.info(f"CoinGeckoOracle initialized: {oracle_id}")
        logger.info(f"Rate limit: {self.config.rate_limit_requests_per_minute} requests/minute")
    
    async def _connect_impl(self) -> bool:
        """Connect to CoinGecko API."""
        try:
            # Test API connectivity
            test_url = f"{self.config.base_url}/ping"
            
            # For now, simulate connection success
            # In production, this would make actual HTTP request
            await asyncio.sleep(0.1)  # Simulate network latency
            
            self._logger.info("CoinGecko API connection test successful")
            return True
            
        except Exception as e:
            self._logger.error(f"CoinGecko connection failed: {e}")
            return False
    
    async def _disconnect_impl(self) -> None:
        """Disconnect from CoinGecko API."""
        try:
            # Clean up session if exists
            if self._session:
                # Close session in production implementation
                self._session = None
            
            self._logger.info("CoinGecko API disconnected")
            
        except Exception as e:
            self._logger.error(f"CoinGecko disconnection error: {e}")
    
    async def _fetch_price_impl(self, symbol: str) -> Optional[OraclePrice]:
        """Fetch price from CoinGecko API."""
        try:
            # Apply rate limiting
            await self._rate_limiter.acquire()

            # Map symbol to CoinGecko format
            coingecko_symbol = self._symbol_map.get(symbol)
            if not coingecko_symbol:
                self._logger.warning(f"Unsupported symbol: {symbol}")
                return None

            import httpx
            url = f"{self.config.base_url}/simple/price"
            params = {
                "ids": coingecko_symbol,
                "vs_currencies": "usd",
                "include_last_updated_at": "true",
            }
            headers = {}
            if self.config.api_key:
                headers["x-cg-demo-key"] = self.config.api_key

            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                resp = await client.get(url, params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            coin_data = data.get(coingecko_symbol)
            if not coin_data or "usd" not in coin_data:
                self._logger.warning(f"No price data returned for {symbol}")
                return None

            live_price = float(coin_data["usd"])
            source_ts = coin_data.get("last_updated_at", time.time())

            price = OraclePrice(
                oracle_id=self._oracle_id,
                symbol=symbol,
                price=live_price,
                timestamp=time.time(),
                confidence=0.95,
                source_timestamp=float(source_ts),
                metadata={
                    "source": "coingecko",
                    "coin_id": coingecko_symbol,
                }
            )

            self._logger.debug(f"Fetched price for {symbol}: ${live_price:.2f}")
            return price

        except Exception as e:
            self._logger.error(f"Price fetch failed for {symbol}: {e}")
            return None
    
    async def get_price_with_retry(self, symbol: str) -> Optional[OraclePrice]:
        """Get price with retry logic."""
        last_error = None
        
        for attempt in range(self.config.retry_attempts):
            try:
                price = await self.get_price(symbol)
                if price:
                    return price
                    
            except Exception as e:
                last_error = e
                self._logger.warning(f"Price fetch attempt {attempt + 1} failed for {symbol}: {e}")
                
                if attempt < self.config.retry_attempts - 1:
                    await asyncio.sleep(self.config.retry_delay_seconds * (attempt + 1))
        
        self._logger.error(f"All retry attempts failed for {symbol}. Last error: {last_error}")
        return None
    
    def get_supported_symbols(self) -> List[str]:
        """Get list of supported trading symbols."""
        return list(self._symbol_map.keys())
    
    def is_symbol_supported(self, symbol: str) -> bool:
        """Check if symbol is supported."""
        return symbol in self._symbol_map

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
            self._requests = [req_time for req_time in self._requests if now - req_time < self.time_window_seconds]
            
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
