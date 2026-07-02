"""Unified Spot Service - Single authoritative source for all spot price data.

Consolidates LivePriceFeed, CryptoSpotService, and SpotComposite into one service.
All spot price consumers (PM model, execution, filters, basis tracker) use this service.

Architecture (REFACTORED for production):
1. Simple HTTP fetching: Coinbase public API (no auth required)
2. On-demand caching with TTL: Fetch when stale, not continuous streaming
3. FastAPI integration: Runs as FastAPI background task, not separate thread
4. Graceful shutdown: Properly handles FastAPI lifespan events

Clean interface:
    spot = unified_spot.get(asset)
    
    spot = {
        price: float,
        timestamp: ms,
        source: "coinbase",
    }

Hard rules:
- PM model uses ONLY UnifiedSpotService
- Execution uses ONLY UnifiedSpotService
- Filters use ONLY UnifiedSpotService
- Basis tracker uses ONLY UnifiedSpotService

Production usage:
- Spot prices are used as reference for Kalshi contract strikes
- Freshness requirement: < 60s for 15m crypto strategy
- Simple periodic fetch is sufficient (no streaming needed)
"""

from __future__ import annotations

import asyncio
import threading
import time
import requests
import hmac
import base64
from typing import Optional, Dict, Any, Union
from dataclasses import dataclass

from utils.logger import get_logger
from data.spot_sla_config import get_spot_max_age

logger = get_logger("data.unified_spot_service")

# =============================================================================
# Coinbase Exchange API Authentication Helpers
# =============================================================================

def _get_coinbase_credentials() -> tuple[Optional[str], Optional[str]]:
    """Get Coinbase Exchange API credentials from environment.
    
    Returns:
        Tuple of (api_key, api_secret) or (None, None) if not available
    """
    try:
        from merid.coinbase_env import coinbase_api_key, coinbase_api_secret
        api_key = coinbase_api_key()
        api_secret = coinbase_api_secret()
        return api_key, api_secret
    except Exception as e:
        logger.warning(f"[UNIFIED-SPOT] Failed to get Coinbase credentials: {e}")
        return None, None

def _generate_coinbase_signature(
    timestamp: str,
    method: str,
    request_path: str,
    body: str,
    api_secret: str
) -> str:
    """Generate Coinbase Exchange API HMAC signature.
    
    Args:
        timestamp: Unix timestamp in seconds
        method: HTTP method (e.g., "GET")
        request_path: API endpoint path (e.g., "/products/BTC-USD/candles")
        body: Request body (empty string for GET requests)
        api_secret: Coinbase API secret key
    
    Returns:
        Base64-encoded HMAC signature
    """
    # Create prehash string: timestamp + method + requestPath + body
    message = timestamp + method + request_path + body
    
    # Decode base64 secret
    secret_bytes = base64.b64decode(api_secret)
    
    # Create HMAC-SHA256 signature
    signature = hmac.new(
        secret_bytes,
        message.encode('utf-8'),
        digestmod='sha256'
    ).digest()
    
    # Base64 encode the signature
    return base64.b64encode(signature).decode('utf-8')

# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class SpotPrice:
    """Spot price data."""
    price: float
    timestamp: int  # milliseconds since epoch
    source: str
    confidence: float = 1.0  # Data quality confidence score (default 1.0 for high quality)
    # OHLC data for ADX/ATR calculations
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    # Volume data for volume confirmation filter (2026 best practice)
    volume: Optional[float] = None

@dataclass
class SpotError:
    """Error when spot price is unavailable or degraded."""
    reason: str  # "no_data", "stale", "degraded"
    asset: str
    age_s: Optional[float] = None  # Age in seconds if reason is "stale"
    message: str = ""  # Human-readable error message


# =============================================================================
# Unified Spot Service
# =============================================================================

class UnifiedSpotService:
    """Unified spot price service using Coinbase Public API (no auth required)
    
    Simplified for production: On-demand fetching with caching, no separate threads.
    Runs on FastAPI event loop as a background task.
    """
    
    SUPPORTED_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    
    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_lock = threading.Lock()  # Thread-safe cache access
        self._running = False
        self._refresh_task: Optional[asyncio.Task] = None
        self._refresh_interval_s = 5.0  # Refresh every 5 seconds (was 30s - too slow for velocity calc)
        # Price history for volatility regime detection (2026 best practice)
        self._price_history: Dict[str, list] = {}  # asset -> list of (timestamp, price) tuples
        self._max_history_length = 3600  # Keep 1 hour of history (5s interval * 720 points)
        logger.info("[UNIFIED-SPOT] UnifiedSpotService initialized (simplified production version)")

    def is_ready(self) -> bool:
        """Check if spot service has completed initial fetch and is ready for use."""
        return len(self._cache) > 0

    async def start_refresh_loop(self):
        """Start the refresh loop as a FastAPI background task.
        
        This performs an initial fetch then continues periodic refreshes.
        Runs on the FastAPI event loop, not a separate thread.
        """
        logger.info("[UNIFIED-SPOT] Starting refresh loop on FastAPI event loop")
        
        if self._running:
            logger.warning("[UNIFIED-SPOT] Refresh loop already running")
            return
        
        self._running = True
        
        # Initial fetch
        await self._refresh_all()
        
        # Start periodic refresh
        self._refresh_task = asyncio.create_task(self._refresh_loop())
        logger.info("[UNIFIED-SPOT] Refresh loop started")
    
    async def stop_refresh_loop(self):
        """Stop the refresh loop gracefully."""
        logger.info("[UNIFIED-SPOT] Stopping refresh loop")
        self._running = False
        
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
        
        logger.info("[UNIFIED-SPOT] Refresh loop stopped")
    
    async def _refresh_loop(self):
        """Periodic refresh loop running on FastAPI event loop."""
        while self._running:
            try:
                await asyncio.sleep(self._refresh_interval_s)
                if not self._running:
                    break
                await self._refresh_all()
            except asyncio.CancelledError:
                logger.info("[UNIFIED-SPOT] Refresh loop cancelled")
                break
            except Exception as e:
                logger.error(f"[UNIFIED-SPOT] Refresh loop error: {e}", exc_info=True)
                await asyncio.sleep(5)
    
    async def _refresh_all(self):
        """Refresh all assets from Coinbase API."""
        logger.info("[UNIFIED-SPOT] Refreshing all assets")
        
        tasks = []
        for asset in self.SUPPORTED_ASSETS:
            tasks.append(self._fetch_asset(asset))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = 0
        for asset, result in zip(self.SUPPORTED_ASSETS, results):
            if isinstance(result, Exception):
                logger.warning(f"[UNIFIED-SPOT] Failed to fetch {asset}: {result}")
            elif result:
                success_count += 1
        
        logger.info(f"[UNIFIED-SPOT] Refresh complete: {success_count}/{len(self.SUPPORTED_ASSETS)} successful")
    
    async def _fetch_asset(self, asset: str) -> bool:
        """Fetch single asset data from Coinbase Exchange API.
        
        Priority order:
        1. Coinbase Exchange API (authenticated) - true OHLC data for ATR/ADX
        2. Coinbase Public Ticker API - real-time price for velocity calculation
        3. Coinbase Public Spot API - fallback with OHLC proxy
        
        CRITICAL FIX: Use ticker endpoint for real-time price updates (every 5s) for velocity calculation.
        Use OHLC candles for ATR/ADX calculation.
        """
        pair_map = {
            "BTC": "BTC-USD",
            "ETH": "ETH-USD",
            "SOL": "SOL-USD",
            "XRP": "XRP-USD",
            "DOGE": "DOGE-USD"
        }
        
        pair = pair_map.get(asset)
        if not pair:
            logger.error(f"[UNIFIED-SPOT] Unsupported asset: {asset}")
            return False
        
        # Try authenticated Exchange API first (true OHLC data for ATR/ADX)
        api_key, api_secret = _get_coinbase_credentials()
        ohlc_data = None
        if api_key and api_secret:
            try:
                ohlc_data = await self._fetch_ohlc_authenticated(pair, api_key, api_secret)
                if ohlc_data:
                    volume = ohlc_data.get('volume', 0)
                    logger.info(f"[UNIFIED-SPOT] Fetched {asset} OHLC: O={ohlc_data['open']:.8f} H={ohlc_data['high']:.8f} L={ohlc_data['low']:.8f} C={ohlc_data['close']:.8f} V={volume:.2f}")
            except Exception as e:
                logger.warning(f"[UNIFIED-SPOT] Authenticated OHLC fetch failed for {asset}, falling back to ticker: {e}")
        
        # Always try ticker endpoint for real-time price (more frequent than candles)
        ticker_data = None
        try:
            ticker_data = await self._fetch_ticker_public(pair)
            if ticker_data:
                logger.info(f"[UNIFIED-SPOT] Fetched {asset} ticker: ${ticker_data['price']:.8f}")
        except Exception as e:
            logger.warning(f"[UNIFIED-SPOT] Ticker fetch failed for {asset}: {e}")
        
        # Combine data: use ticker price for velocity, OHLC for ATR/ADX
        if ticker_data:
            # Use ticker price as close, use OHLC for open/high/low if available
            final_data = {
                'open': ohlc_data['open'] if ohlc_data else ticker_data['price'],
                'high': ohlc_data['high'] if ohlc_data else ticker_data['price'],
                'low': ohlc_data['low'] if ohlc_data else ticker_data['price'],
                'close': ticker_data['price']  # Use ticker price for velocity calculation
            }
            source = 'coinbase_ticker_hybrid' if ohlc_data else 'coinbase_ticker'
            self._update_cache(asset, final_data, source=source)
            return True
        
        # Fallback to OHLC-only if ticker failed
        if ohlc_data:
            self._update_cache(asset, ohlc_data, source='coinbase_exchange_authenticated')
            return True
        
        # Final fallback to public spot price endpoint (OHLC proxy)
        try:
            ohlc_data = await self._fetch_spot_price_fallback_async(pair)
            if ohlc_data:
                self._update_cache(asset, ohlc_data, source='coinbase_public')
                logger.info(f"[UNIFIED-SPOT] Fetched {asset}: ${ohlc_data['close']:.8f} (OHLC proxy: O=H=L=C)")
                return True
        except Exception as e:
            logger.error(f"[UNIFIED-SPOT] Failed to fetch {asset}: {e}")
            return False
        
        return False
    
    async def _fetch_ohlc_authenticated(self, pair: str, api_key: str, api_secret: str) -> Optional[dict]:
        """Fetch OHLC data from Coinbase Exchange API (authenticated).
        
        Args:
            pair: Trading pair (e.g., "BTC-USD")
            api_key: Coinbase API key
            api_secret: Coinbase API secret
        
        Returns:
            Dict with 'open', 'high', 'low', 'close' or None on failure
        """
        # Coinbase Exchange API endpoint for candles
        url = f"https://api.exchange.coinbase.com/products/{pair}/candles"
        
        # Request parameters for 60-second candles (more frequent price updates for velocity calculation)
        params = {
            'granularity': '60',  # 60 seconds in seconds (1 minute)
            'limit': 1  # Only need the most recent candle
        }
        
        # Generate timestamp and signature
        timestamp = str(int(time.time()))
        request_path = f"/products/{pair}/candles?granularity=60&limit=1"
        signature = _generate_coinbase_signature(timestamp, "GET", request_path, "", api_secret)
        
        # Headers for authenticated request
        headers = {
            'CB-ACCESS-KEY': api_key,
            'CB-ACCESS-SIGN': signature,
            'CB-ACCESS-TIMESTAMP': timestamp,
            'Content-Type': 'application/json'
        }
        
        # Use requests in thread pool to avoid blocking
        loop = asyncio.get_running_loop()
        
        def fetch_sync():
            response = requests.get(url, params=params, headers=headers, timeout=5.0)
            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}: {response.text}")
            data = response.json()
            if not data or not isinstance(data, list) or len(data) == 0:
                raise Exception("No candles data returned")
            
            # Candle format: [timestamp, low, high, open, close, volume]
            candle = data[0]
            return {
                'open': float(candle[3]),
                'high': float(candle[2]),
                'low': float(candle[1]),
                'close': float(candle[4]),
                'volume': float(candle[5]) if len(candle) > 5 else None  # Volume for volume confirmation filter
            }
        
        return await loop.run_in_executor(None, fetch_sync)
    
    async def _fetch_ticker_public(self, pair: str) -> Optional[dict]:
        """Fetch ticker data from Coinbase public API (real-time price).
        
        Args:
            pair: Trading pair (e.g., "BTC-USD")
        
        Returns:
            Dict with 'price' or None on failure
        """
        # Use Coinbase Exchange API ticker endpoint (public, no auth required)
        ticker_url = f"https://api.exchange.coinbase.com/products/{pair}/ticker"
        
        loop = asyncio.get_running_loop()
        
        def fetch_sync():
            response = requests.get(ticker_url, timeout=5.0)
            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}: {response.text}")
            data = response.json()
            price = float(data['price'])
            return {'price': price}
        
        return await loop.run_in_executor(None, fetch_sync)
    
    async def _fetch_spot_price_fallback_async(self, pair: str) -> Optional[dict]:
        """Fetch spot price from public API as fallback (async wrapper).
        
        Args:
            pair: Trading pair (e.g., "BTC-USD")
        
        Returns:
            Dict with 'open', 'high', 'low', 'close' (all same as close) or None on failure
        """
        url = f"https://api.coinbase.com/v2/prices/{pair}/spot"
        
        loop = asyncio.get_running_loop()
        
        def fetch_sync():
            response = requests.get(url, timeout=5.0)
            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}")
            data = response.json()
            close_price = float(data['data']['amount'])
            return {
                'open': close_price,
                'high': close_price,
                'low': close_price,
                'close': close_price
            }
        
        return await loop.run_in_executor(None, fetch_sync)
    
    def _update_cache(self, asset: str, ohlc_data: dict, source: str):
        """Update cache with OHLC data.
        
        Args:
            asset: Asset symbol (e.g., "BTC")
            ohlc_data: Dict with 'open', 'high', 'low', 'close', 'volume'
            source: Data source identifier
        """
        with self._cache_lock:
            self._cache[asset] = {
                'price': ohlc_data['close'],
                'timestamp': int(time.time() * 1000),
                'source': source,
                'open': ohlc_data['open'],
                'high': ohlc_data['high'],
                'low': ohlc_data['low'],
                'volume': ohlc_data.get('volume')  # Volume for volume confirmation filter
            }
            # Add to price history for volatility regime detection
            if asset not in self._price_history:
                self._price_history[asset] = []
            self._price_history[asset].append((int(time.time() * 1000), ohlc_data['close']))
            # Trim history to max length
            if len(self._price_history[asset]) > self._max_history_length:
                self._price_history[asset] = self._price_history[asset][-self._max_history_length:]

    def get(self, asset: str) -> Union[SpotPrice, SpotError]:
        """Get cached spot price for asset with freshness check.
        
        Returns:
            SpotPrice if data is fresh and within SLA
            SpotError if data is stale, missing, or asset is degraded
        """
        # Thread-safe cache access
        with self._cache_lock:
            data = self._cache.get(asset)
        
        if not data:
            logger.info(f"[UNIFIED-SPOT] No spot price available for {asset}")
            return SpotError(reason="no_data", asset=asset, message="No cached data available")
        
        # Get single hard threshold from centralized config (60s for all assets)
        max_age_s = get_spot_max_age()
        
        # Calculate age in seconds
        age_ms = int(time.time() * 1000) - data['timestamp']
        age_s = age_ms / 1000.0
        
        # Check staleness against single hard threshold
        if age_s > max_age_s:
            logger.warning(f"[UNIFIED-SPOT] Stale spot price for {asset} (age={age_s:.1f}s > {max_age_s}s threshold)")
            return SpotError(reason="stale", asset=asset, age_s=age_s, 
                           message=f"Spot data age {age_s:.1f}s exceeds threshold {max_age_s}s")

        logger.info(f"[UNIFIED-SPOT] Returning spot price for {asset}: price={data['price']}, age={age_s:.1f}s")
        return SpotPrice(
            price=data['price'],
            timestamp=data['timestamp'],
            source=data['source'],
            confidence=1.0,  # High confidence for fresh data
            open=data.get('open'),
            high=data.get('high'),
            low=data.get('low'),
            volume=data.get('volume')  # Volume for volume confirmation filter
        )

    async def get_spot(self, asset: str) -> Optional[Any]:
        """Get cached spot price for asset in legacy agent format (compatibility method).
        
        Returns object with price_usd, staleness_ms, source attributes for legacy agents.
        Returns None if spot is unavailable or degraded (SpotError case).
        """
        result = self.get(asset)
        if isinstance(result, SpotError):
            return None
        
        # Convert SpotPrice to legacy format expected by agents
        now_ms = int(time.time() * 1000)
        staleness_ms = now_ms - result.timestamp
        
        # Create legacy-style spot snapshot object
        class SpotSnapshot:
            def __init__(self, price_usd: float, staleness_ms: int, source: str):
                self.price_usd = price_usd
                self.staleness_ms = staleness_ms
                self.source = source
        
        return SpotSnapshot(
            price_usd=result.price,
            staleness_ms=staleness_ms,
            source=result.source
        )
    
    def get_spot_history(self, asset: str, window_s: int = 300) -> list:
        """Get price history for volatility regime detection.
        
        Args:
            asset: Asset symbol (e.g., "BTC")
            window_s: Time window in seconds (default 300s = 5 minutes)
        
        Returns:
            List of dicts with 'price' and 'timestamp' keys
        """
        with self._cache_lock:
            history = self._price_history.get(asset, [])
        
        if not history:
            return []
        
        # Filter by time window
        now_ms = int(time.time() * 1000)
        window_ms = window_s * 1000
        cutoff_ms = now_ms - window_ms
        
        filtered = [
            {"price": price, "timestamp": ts}
            for ts, price in history
            if ts >= cutoff_ms
        ]
        
        return filtered

    async def get_spot_price(self, asset: str) -> Optional[float]:
        """Get cached spot price for asset as a float (compatibility method for agents).
        
        Returns None if spot is unavailable or degraded (SpotError case).
        """
        result = self.get(asset)
        if isinstance(result, SpotError):
            return None
        return result.price

    def get_all(self) -> Dict[str, SpotPrice]:
        """Get all cached spot prices (excludes degraded/errored assets)"""
        result = {}
        for asset in self.SUPPORTED_ASSETS:
            spot_result = self.get(asset)
            if isinstance(spot_result, SpotPrice):
                result[asset] = spot_result
        return result

    def health_check(self) -> Dict[str, Any]:
        """Health check for startup validation compatibility."""
        with self._cache_lock:
            cached_count = len(self._cache)
            cache_status = {}
            for asset in self.SUPPORTED_ASSETS:
                cache_status[asset] = {
                    "cached": asset in self._cache,
                    "stale": False  # Simplified version doesn't track staleness
                }
        
        return {
            "status": "healthy" if cached_count == len(self.SUPPORTED_ASSETS) else "degraded",
            "cached_count": cached_count,
            "cached_assets": cached_count,
            "total_assets": len(self.SUPPORTED_ASSETS),
            "supported_assets": self.SUPPORTED_ASSETS,
            "running": self._running,
            "stale_count": 0,  # Simplified version doesn't track staleness separately
            "degraded_count": 0,  # Simplified version doesn't track degradation separately
            "cache_status": cache_status
        }


# =============================================================================
# Singleton Instance
# =============================================================================

_unified_spot_instance: Optional[UnifiedSpotService] = None
_instance_lock = threading.Lock()

def get_unified_spot_service() -> UnifiedSpotService:
    """Get the singleton instance of UnifiedSpotService."""
    global _unified_spot_instance
    
    if _unified_spot_instance is None:
        with _instance_lock:
            if _unified_spot_instance is None:
                _unified_spot_instance = UnifiedSpotService()
                logger.info("[UNIFIED-SPOT] Singleton instance created")
    
    return _unified_spot_instance

def reset_unified_spot_service():
    """Reset the singleton instance (for clean startup)."""
    global _unified_spot_instance
    
    with _instance_lock:
        if _unified_spot_instance is not None:
            logger.info("[UNIFIED-SPOT] Resetting singleton instance")
            _unified_spot_instance = None
