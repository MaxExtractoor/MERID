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
import os
import threading
import time
import requests
import hmac
import base64
from typing import Optional, Dict, Any, Union, Literal, Tuple
from dataclasses import dataclass
from enum import Enum
import random

from utils.logger import get_logger
from data.spot_sla_config import get_spot_max_age

logger = get_logger("data.unified_spot_service")

# =============================================================================
# Retry Helper with Exponential Backoff
# =============================================================================

async def _retry_with_backoff(
    func,
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 5.0,
    retryable_errors: tuple = (502, 503, 504, 429, 500, 503)
) -> Any:
    """Execute function with exponential backoff retry logic.
    
    Args:
        func: Async function to execute
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds before first retry
        max_delay: Maximum delay between retries
        retryable_errors: HTTP status codes that trigger retry
    
    Returns:
        Function result or raises last exception
    
    Raises:
        Exception: Last exception if all retries exhausted
    """
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            return await func()
        except Exception as e:
            last_exception = e
            
            # Check if error is retryable
            error_str = str(e)
            is_retryable = False
            for code in retryable_errors:
                if f"HTTP {code}" in error_str:
                    is_retryable = True
                    break
            
            if not is_retryable or attempt == max_retries:
                # Not retryable or exhausted retries
                raise
            
            # Calculate exponential backoff with jitter
            delay = min(base_delay * (2 ** attempt) + random.uniform(0, 0.5), max_delay)
            logger.warning(f"[UNIFIED-SPOT] Retry attempt {attempt + 1}/{max_retries} after {delay:.2f}s delay: {e}")
            await asyncio.sleep(delay)
    
    raise last_exception

# =============================================================================
# Price Formatting Helper
# =============================================================================

def format_price(asset: str, price: float) -> str:
    """Format price with appropriate decimal places based on asset."""
    asset_precision = {
        "BTC": 2,
        "ETH": 2,
        "SOL": 4,
        "XRP": 4,
        "DOGE": 7
    }
    precision = asset_precision.get(asset.upper(), 4)
    return f"{price:.{precision}f}"

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

class DataState(Enum):
    """Market data recovery states based on 2026 best practices.
    
    States follow the LIVE -> DEGRADED -> STALE -> FALLBACK -> RECOVERING -> LIVE cycle.
    Each state has clear application behavior and trading implications.
    """
    LIVE = "live"  # WebSocket updates are fresh - normal trading
    DEGRADED = "degraded"  # Latest update is getting old but usable - monitor closely
    STALE = "stale"  # Latest update too old to trust - request fallback
    FALLBACK = "fallback"  # REST snapshot being used - label as degraded
    RECOVERING = "recovering"  # WebSocket resumed but not confirmed - wait for stability
    DEAD = "dead"  # No reliable data - block trading
    MARKET_CLOSED = "market_closed"  # Session closed - show with label


@dataclass
class ComponentScore:
    """Individual component score for Signal Quality Score (SQS)."""
    name: str
    score: float  # 0-100
    weight: float  # 0-1
    reason: str = ""


@dataclass
class SignalQualityScore:
    """Signal Quality Score (SQS) - composite 0-100 data quality metric.
    
    Based on 2026 research: data freshness (30%), regime deviation (35%),
    spread quality (20%), signal agreement (15%). Below threshold -> no new positions.
    """
    composite: float  # 0-100 weighted composite
    components: Dict[str, ComponentScore]
    timestamp: int
    trade_permitted: bool
    threshold: float
    degradation_level: Literal["normal", "yellow", "orange", "red"]


@dataclass
class SpotPrice:
    """Spot price data with recovery state and quality scoring."""
    price: float
    timestamp: int  # milliseconds since epoch
    source: str
    state: DataState = DataState.LIVE
    confidence: float = 1.0  # Data quality confidence score (default 1.0 for high quality)
    sqs: Optional[SignalQualityScore] = None  # Signal Quality Score
    # OHLC data for ADX/ATR calculations
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    # Volume data for volume confirmation filter (2026 best practice)
    volume: Optional[float] = None
    # Metadata for source labeling (2026 best practice)
    exchange_timestamp: Optional[int] = None  # When the market event happened
    received_timestamp: Optional[int] = None  # When the app received it
    age_seconds: Optional[float] = None  # Calculated age

@dataclass
class SpotError:
    """Error when spot price is unavailable or degraded."""
    reason: str  # "no_data", "stale", "degraded", "dead"
    asset: str
    state: DataState = DataState.DEAD
    age_s: Optional[float] = None  # Age in seconds if reason is "stale"
    message: str = ""  # Human-readable error message
    sqs: Optional[SignalQualityScore] = None  # Signal Quality Score even in error state


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
        self._cache_lock = threading.RLock()  # Reentrant lock for nested lock acquisition (health_check -> _compute_sqs)
        self._running = False
        self._refresh_task: Optional[asyncio.Task] = None
        self._refresh_interval_s = 1.0  # CRITICAL FIX: Reduced from 3s to 1s for faster price updates. Prediction markets move fast and stale data is costly. 1s polling is within rate limits while providing fresher data.

        # Per-asset last successful fetch timestamp (legacy tests/health compatibility)
        self._asset_success_ts: Dict[str, float] = {}

        logger.info("[UNIFIED-SPOT] UnifiedSpotService initialized with SQS and recovery states (2026 best practices)")

        logger.info("[UNIFIED-SPOT] UnifiedSpotService initialized with WebSocket streaming support")
        # Price history for volatility regime detection (2026 best practice)
        self._price_history: Dict[str, list] = {}  # asset -> list of (timestamp, price) tuples
        self._max_history_length = 3600  # Keep 1 hour of history (3s interval * 1200 points)
        
        # 2026 BEST PRACTICE: Recovery state tracking per asset
        self._data_states: Dict[str, DataState] = {}  # asset -> current recovery state
        self._consecutive_fresh_ticks: Dict[str, int] = {}  # asset -> consecutive fresh tick count for RECOVERING->LIVE transition
        
        # 2026 BEST PRACTICE: Signal Quality Score (SQS) thresholds per asset
        self._sqs_thresholds = {
            "BTC": 65.0,  # Conservative - most sensitive to data quality
            "ETH": 65.0,
            "SOL": 50.0,  # More robust to equity vol regime shifts
            "XRP": 50.0,
            "DOGE": 45.0,  # Crypto is inherently chaotic, lower bar
        }
        
        # 2026 BEST PRACTICE: Freshness thresholds for state transitions
        self._freshness_thresholds = {
            "live_s": 3.0,      # 3 seconds or less -> LIVE
            "degraded_s": 10.0,  # 3-10 seconds -> DEGRADED
            "stale_s": 30.0,     # >10 seconds -> STALE
        }
        
        # 2026 BEST PRACTICE: Fallback activation tracking for metrics
        self._fallback_activations: Dict[str, int] = {}  # asset -> fallback activation count
        self._state_transitions: Dict[str, list] = {}  # asset -> list of (timestamp, from_state, to_state)
        
        logger.info("[UNIFIED-SPOT] UnifiedSpotService initialized with SQS and recovery states (2026 best practices)")

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
        1. Coinbase Public Ticker API - real-time price for velocity calculation (FASTEST)
        2. Coinbase Public Candles API - public OHLC data (no auth required)
        3. Coinbase Exchange API (authenticated) - true OHLC data for ATR/ADX
        4. Coinbase Public Spot API - fallback with OHLC proxy
        
        CRITICAL FIX (2026-07-08): Prioritize ticker endpoint for real-time price updates.
        Ticker is fastest and most reliable for spot price. OHLC is secondary for ATR/ADX.
        This fixes XRP/DOGE NoneType issues by ensuring ticker fetch is attempted first.
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
        
        # CRITICAL FIX: Try ticker FIRST for real-time price (most reliable, no auth needed)
        ticker_data = None
        try:
            ticker_data = await self._fetch_ticker_public(pair)
            if ticker_data:
                logger.info(f"[UNIFIED-SPOT] Fetched {asset} ticker: ${format_price(asset, ticker_data['price'])}")
        except Exception as e:
            logger.warning(f"[UNIFIED-SPOT] Ticker fetch failed for {asset}: {e}")
        
        # Try public candles endpoint (no auth required) for OHLC data
        ohlc_data = None
        try:
            ohlc_data = await self._fetch_ohlc_public(pair)
            if ohlc_data:
                volume = ohlc_data.get('volume', 0)
                logger.info(f"[UNIFIED-SPOT] Fetched {asset} OHLC (public): O={format_price(asset, ohlc_data['open'])} H={format_price(asset, ohlc_data['high'])} L={format_price(asset, ohlc_data['low'])} C={format_price(asset, ohlc_data['close'])} V={volume:.2f}")
        except Exception as e:
            logger.warning(f"[UNIFIED-SPOT] Public OHLC fetch failed for {asset}: {e}")
        
        # Try authenticated Exchange API as secondary OHLC source
        if not ohlc_data:
            api_key, api_secret = _get_coinbase_credentials()
            if api_key and api_secret:
                try:
                    ohlc_data = await self._fetch_ohlc_authenticated(pair, api_key, api_secret)
                    if ohlc_data:
                        volume = ohlc_data.get('volume', 0)
                        logger.info(f"[UNIFIED-SPOT] Fetched {asset} OHLC (auth): O={format_price(asset, ohlc_data['open'])} H={format_price(asset, ohlc_data['high'])} L={format_price(asset, ohlc_data['low'])} C={format_price(asset, ohlc_data['close'])} V={volume:.2f}")
                except Exception as e:
                    logger.warning(f"[UNIFIED-SPOT] Authenticated OHLC fetch failed for {asset}: {e}")
        
        # Combine data: use ticker price for velocity, OHLC for ATR/ADX
        if ticker_data:
            # Use ticker price as close, use OHLC for open/high/low if available
            if ohlc_data:
                final_data = {
                    'open': ohlc_data['open'],
                    'high': ohlc_data['high'],
                    'low': ohlc_data['low'],
                    'close': ticker_data['price'],  # Use ticker price for velocity calculation
                    'volume': ohlc_data.get('volume')
                }
                source = 'coinbase_ticker_hybrid'
            else:
                # CRITICAL FIX: When OHLC is unavailable, construct valid OHLC from price history
                # to avoid high=low invalid data that breaks volume extraction
                ticker_price = ticker_data['price']
                if asset in self._price_history and len(self._price_history[asset]) > 0:
                    # Use recent price history to construct OHLC
                    recent_prices = [p[1] for p in self._price_history[asset][-10:]]  # Last 10 prices
                    recent_prices.append(ticker_price)
                    final_data = {
                        'open': recent_prices[0],  # Oldest price as open
                        'high': max(recent_prices),  # Highest as high
                        'low': min(recent_prices),   # Lowest as low
                        'close': ticker_price,       # Current as close
                        'volume': None
                    }
                    source = 'coinbase_ticker_ohlc_proxy'
                else:
                    # No price history available - add small spread to avoid high=low
                    spread = ticker_price * 0.0001  # 0.01% spread
                    final_data = {
                        'open': ticker_price,
                        'high': ticker_price + spread,
                        'low': ticker_price - spread,
                        'close': ticker_price,
                        'volume': None
                    }
                    source = 'coinbase_ticker_spread_proxy'
            self._update_cache(asset, final_data, source=source)
            return True
        
        # Fallback to OHLC-only if ticker failed
        if ohlc_data:
            self._update_cache(asset, ohlc_data, source='coinbase_ohlc')
            return True
        
        # Final fallback to public spot price endpoint (OHLC proxy)
        try:
            ohlc_data = await self._fetch_spot_price_fallback_async(pair)
            if ohlc_data:
                self._update_cache(asset, ohlc_data, source='coinbase_public')
                logger.info(f"[UNIFIED-SPOT] Fetched {asset}: ${format_price(asset, ohlc_data['close'])} (OHLC proxy: O=H=L=C)")
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
        
        async def fetch_with_retry():
            return await loop.run_in_executor(None, fetch_sync)
        
        return await _retry_with_backoff(fetch_with_retry, max_retries=3, base_delay=0.5, max_delay=3.0)
    
    async def _fetch_ohlc_public(self, pair: str, granularity: int = 60, limit: int = 1) -> Optional[dict]:
        """Fetch OHLC data from Coinbase public candles API (no auth required).
        
        Args:
            pair: Trading pair (e.g., "BTC-USD")
            granularity: Candle granularity in seconds (default 60 for 1m, 900 for 15m)
            limit: Number of candles to fetch (default 1)
        
        Returns:
            Dict with 'open', 'high', 'low', 'close', 'volume' or None on failure
            If limit > 1, returns the most recent candle (index 0)
        """
        # Coinbase Exchange API public candles endpoint (no auth required)
        url = f"https://api.exchange.coinbase.com/products/{pair}/candles"
        
        # Request parameters for candles
        params = {
            'granularity': granularity,  # 60 seconds (1 minute) or 900 seconds (15 minutes)
            'limit': limit
        }
        
        loop = asyncio.get_running_loop()
        
        def fetch_sync():
            response = requests.get(url, params=params, timeout=5.0)
            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}: {response.text}")
            data = response.json()
            if not data or not isinstance(data, list) or len(data) == 0:
                raise Exception("No candles data returned")
            
            # Candle format: [timestamp, low, high, open, close, volume]
            # API returns candles in reverse chronological order (newest first)
            candle = data[0]  # Most recent candle
            return {
                'open': float(candle[3]),
                'high': float(candle[2]),
                'low': float(candle[1]),
                'close': float(candle[4]),
                'volume': float(candle[5]) if len(candle) > 5 else None,
                'candles': data  # Return full list for multi-candle access
            }
        
        async def fetch_with_retry():
            return await loop.run_in_executor(None, fetch_sync)
        
        return await _retry_with_backoff(fetch_with_retry, max_retries=3, base_delay=0.5, max_delay=3.0)
    
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
        
        async def fetch_with_retry():
            return await loop.run_in_executor(None, fetch_sync)
        
        return await _retry_with_backoff(fetch_with_retry, max_retries=3, base_delay=0.5, max_delay=3.0)
    
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
        
        async def fetch_with_retry():
            return await loop.run_in_executor(None, fetch_sync)
        
        return await _retry_with_backoff(fetch_with_retry, max_retries=3, base_delay=0.5, max_delay=3.0)
    
    def _update_cache(self, asset: str, ohlc_data: dict, source: str):
        """Update cache with OHLC data and compute recovery state/SQS.
        
        Args:
            asset: Asset symbol (e.g., "BTC")
            ohlc_data: Dict with 'open', 'high', 'low', 'close', 'volume'
            source: Data source identifier
        """
        now_ms = int(time.time() * 1000)

        # Enforce the OHLC invariant: high >= max(open, close) and low <= min(open, close).
        # This is critical because we combine a live ticker close with open/high/low from a
        # public 1m candle; the current ticker can trade outside that candle's range.
        open_p = ohlc_data.get('open') or ohlc_data['close']
        high_p = ohlc_data.get('high') or ohlc_data['close']
        low_p = ohlc_data.get('low') or ohlc_data['close']
        close_p = ohlc_data['close']

        ohlc_high = max(high_p, open_p, close_p)
        ohlc_low = min(low_p, open_p, close_p)

        if ohlc_high != high_p or ohlc_low != low_p:
            logger.info(
                f"[UNIFIED-SPOT-OHLC-INVARIANT] {asset}: expanded public OHLC to include close "
                f"(public H={high_p} L={low_p}) -> (effective H={ohlc_high} L={ohlc_low}) close={close_p}"
            )

        with self._cache_lock:
            self._cache[asset] = {
                'price': close_p,
                'timestamp': now_ms,
                'source': source,
                'open': open_p,
                'high': ohlc_high,
                'low': ohlc_low,
                'volume': ohlc_data.get('volume')  # Volume for volume confirmation filter
            }
            # Add to price history for volatility regime detection
            if asset not in self._price_history:
                self._price_history[asset] = []
            self._price_history[asset].append((now_ms, ohlc_data['close']))
            # Trim history to max length
            if len(self._price_history[asset]) > self._max_history_length:
                self._price_history[asset] = self._price_history[asset][-self._max_history_length:]
            
            # 2026 BEST PRACTICE: Update recovery state based on source and freshness
            old_state = self._data_states.get(asset, DataState.LIVE)
            new_state = self._classify_data_state(asset, source, now_ms)
            self._data_states[asset] = new_state
            
            # Track state transitions for metrics
            if old_state != new_state:
                self._state_transitions.setdefault(asset, []).append((now_ms, old_state.value, new_state.value))
                logger.info(f"[UNIFIED-SPOT] State transition: {asset} {old_state.value} -> {new_state.value} (source={source})")
            
            # Track fallback activations
            if "fallback" in source.lower() or "proxy" in source.lower():
                self._fallback_activations[asset] = self._fallback_activations.get(asset, 0) + 1
    
    def _classify_data_state(self, asset: str, source: str, timestamp_ms: int) -> DataState:
        """Classify data state based on source and freshness (2026 best practice).
        
        Args:
            asset: Asset symbol
            source: Data source identifier
            timestamp_ms: Data timestamp in milliseconds
            
        Returns:
            DataState classification
        """
        now_ms = int(time.time() * 1000)
        age_s = (now_ms - timestamp_ms) / 1000.0
        
        # Check if source is a fallback
        is_fallback = "fallback" in source.lower() or "proxy" in source.lower()
        
        # Previous state
        prev_state = self._data_states.get(asset, DataState.LIVE)
        
        if is_fallback:
            # Fallback data is always labeled as FALLBACK
            return DataState.FALLBACK
        
        # Check freshness
        if age_s <= self._freshness_thresholds["live_s"]:
            # Fresh data
            if prev_state == DataState.RECOVERING:
                # Require 3 consecutive fresh ticks to exit RECOVERING
                self._consecutive_fresh_ticks[asset] = self._consecutive_fresh_ticks.get(asset, 0) + 1
                if self._consecutive_fresh_ticks[asset] >= 3:
                    self._consecutive_fresh_ticks[asset] = 0
                    return DataState.LIVE
                return DataState.RECOVERING
            else:
                self._consecutive_fresh_ticks[asset] = 0
                return DataState.LIVE
        elif age_s <= self._freshness_thresholds["degraded_s"]:
            # Degraded but usable
            self._consecutive_fresh_ticks[asset] = 0
            return DataState.DEGRADED
        elif age_s <= self._freshness_thresholds["stale_s"]:
            # Stale - should trigger fallback
            self._consecutive_fresh_ticks[asset] = 0
            return DataState.STALE
        else:
            # Too old - DEAD
            self._consecutive_fresh_ticks[asset] = 0
            return DataState.DEAD
    
    def _compute_sqs(self, asset: str) -> SignalQualityScore:
        """Compute Signal Quality Score (SQS) for an asset (2026 best practice).
        
        SQS = weighted average of 4 components:
        - Data freshness (30% weight)
        - Regime deviation (35% weight)
        - Spread quality (20% weight)
        - Signal agreement (15% weight)
        
        Args:
            asset: Asset symbol
            
        Returns:
            SignalQualityScore with composite and components
        """
        with self._cache_lock:
            data = self._cache.get(asset)
            state = self._data_states.get(asset, DataState.DEAD)
        
        if not data:
            return SignalQualityScore(
                composite=0.0,
                components={},
                timestamp=int(time.time() * 1000),
                trade_permitted=False,
                threshold=self._sqs_thresholds.get(asset, 50.0),
                degradation_level="red"
            )
        
        # Component 1: Data freshness (30% weight)
        now_ms = int(time.time() * 1000)
        age_s = (now_ms - data['timestamp']) / 1000.0
        freshness_score = max(0.0, 100.0 * (1.0 - min(age_s / 30.0, 1.0)))  # Linear decay over 30s
        freshness_component = ComponentScore(
            name="data_freshness",
                score=freshness_score,
                weight=0.30,
                reason=f"Age: {age_s:.1f}s"
        )
        
        # Component 2: Regime deviation (35% weight) - based on state
        state_scores = {
            DataState.LIVE: 100.0,
            DataState.DEGRADED: 70.0,
            DataState.STALE: 40.0,
            DataState.FALLBACK: 50.0,
            DataState.RECOVERING: 60.0,
            DataState.DEAD: 0.0,
            DataState.MARKET_CLOSED: 80.0,
        }
        regime_score = state_scores.get(state, 0.0)
        regime_component = ComponentScore(
            name="regime_deviation",
            score=regime_score,
            weight=0.35,
            reason=f"State: {state.value}"
        )
        
        # Component 3: Spread quality (20% weight) - based on source quality
        source_scores = {
            "coinbase_ticker_hybrid": 100.0,
            "coinbase_ticker_ohlc_proxy": 70.0,
            "coinbase_ticker_spread_proxy": 50.0,
            "coinbase_ohlc": 80.0,
            "coinbase_public": 40.0,
        }
        spread_score = source_scores.get(data['source'], 50.0)
        spread_component = ComponentScore(
            name="spread_quality",
            score=spread_score,
            weight=0.20,
            reason=f"Source: {data['source']}"
        )
        
        # Component 4: Signal agreement (15% weight) - based on price history consistency
        agreement_score = 100.0  # Default if insufficient history
        if asset in self._price_history and len(self._price_history[asset]) >= 10:
            recent_prices = [p[1] for p in self._price_history[asset][-10:]]
            price_std = (max(recent_prices) - min(recent_prices)) / (sum(recent_prices) / len(recent_prices))
            agreement_score = max(0.0, 100.0 * (1.0 - min(price_std * 10, 1.0)))  # Penalize high volatility
        agreement_component = ComponentScore(
            name="signal_agreement",
            score=agreement_score,
            weight=0.15,
            reason=f"Price consistency: {agreement_score:.1f}"
        )
        
        # Compute weighted composite
        composite = (
            freshness_component.score * freshness_component.weight +
            regime_component.score * regime_component.weight +
            spread_component.score * spread_component.weight +
            agreement_component.score * agreement_component.weight
        )
        
        # Determine degradation level
        threshold = self._sqs_thresholds.get(asset, 50.0)
        if composite >= threshold:
            degradation_level = "normal"
        elif composite >= threshold * 0.6:
            degradation_level = "yellow"
        elif composite >= threshold * 0.3:
            degradation_level = "orange"
        else:
            degradation_level = "red"
        
        return SignalQualityScore(
            composite=composite,
            components={
                "data_freshness": freshness_component,
                "regime_deviation": regime_component,
                "spread_quality": spread_component,
                "signal_agreement": agreement_component,
            },
            timestamp=now_ms,
            trade_permitted=composite >= threshold,
            threshold=threshold,
            degradation_level=degradation_level
        )

    def get(self, asset: str) -> Union[SpotPrice, SpotError]:
        """Get cached spot price for asset with freshness check and SQS (2026 best practice).
        
        Returns:
            SpotPrice with recovery state and SQS if data is available
            SpotError if data is stale, missing, or asset is degraded
        """
        # Thread-safe cache access
        with self._cache_lock:
            data = self._cache.get(asset)
            state = self._data_states.get(asset, DataState.DEAD)
        
        if not data:
            logger.info(f"[UNIFIED-SPOT] No spot price available for {asset}")
            sqs = self._compute_sqs(asset)
            return SpotError(reason="no_data", asset=asset, state=DataState.DEAD, 
                           message="No cached data available", sqs=sqs)
        
        # Get single hard threshold from centralized config (default 120s for all assets)
        max_age_s = get_spot_max_age()
        
        # Calculate age in seconds
        now_ms = int(time.time() * 1000)
        age_ms = now_ms - data['timestamp']
        age_s = age_ms / 1000.0
        
        # Check staleness against single hard threshold
        if age_s > max_age_s:
            logger.warning(f"[UNIFIED-SPOT] Stale spot price for {asset} (age={age_s:.1f}s > {max_age_s}s threshold)")
            sqs = self._compute_sqs(asset)
            return SpotError(reason="stale", asset=asset, state=state, age_s=age_s,
                           message=f"Spot data age {age_s:.1f}s exceeds threshold {max_age_s}s", sqs=sqs)
        
        # 2026 BEST PRACTICE: Compute SQS for all returned data
        sqs = self._compute_sqs(asset)
        
        # 2026 BEST PRACTICE: Adjust confidence based on state and SQS
        confidence = sqs.composite / 100.0
        
        logger.info(f"[UNIFIED-SPOT] Returning spot price for {asset}: price={data['price']}, age={age_s:.1f}s, state={state.value}, sqs={sqs.composite:.1f}")
        return SpotPrice(
            price=data['price'],
            timestamp=data['timestamp'],
            source=data['source'],
            state=state,
            confidence=confidence,
            sqs=sqs,
            open=data.get('open'),
            high=data.get('high'),
            low=data.get('low'),
            volume=data.get('volume'),
            exchange_timestamp=data.get('timestamp'),  # Use cache timestamp as exchange timestamp
            received_timestamp=now_ms,
            age_seconds=age_s
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
            def __init__(self, price_usd: float, staleness_ms: int, source: str, open: float = None, high: float = None, low: float = None, volume: float = None):
                self.price_usd = price_usd
                self.staleness_ms = staleness_ms
                self.source = source
                self.open = open
                self.high = high
                self.low = low
                self.volume = volume
        
        return SpotSnapshot(
            price_usd=result.price,
            staleness_ms=staleness_ms,
            source=result.source,
            open=result.open,
            high=result.high,
            low=result.low,
            volume=result.volume
        )

    def get_spot_data(self, asset: str) -> Optional[Any]:
        """Get cached spot price for asset (alias for get_spot for compatibility).
        
        CRITICAL FIX (2026-07-17): Added for edge_based_exit_evaluator compatibility.
        Returns object with price_usd, staleness_ms, source attributes.
        Returns None if spot is unavailable or degraded (SpotError case).
        """
        result = self.get(asset)
        if isinstance(result, SpotError):
            return None
        
        # Convert SpotPrice to legacy format expected by callers
        now_ms = int(time.time() * 1000)
        staleness_ms = now_ms - result.timestamp
        
        # Create legacy-style spot snapshot object
        class SpotSnapshot:
            def __init__(self, price_usd: float, staleness_ms: int, source: str, open: float = None, high: float = None, low: float = None, volume: float = None):
                self.price_usd = price_usd
                self.staleness_ms = staleness_ms
                self.source = source
                self.open = open
                self.high = high
                self.low = low
                self.volume = volume
        
        return SpotSnapshot(
            price_usd=result.price,
            staleness_ms=staleness_ms,
            source=result.source,
            open=result.open,
            high=result.high,
            low=result.low,
            volume=result.volume
        )

    def get_ohlcv_buffer(self, asset: str, timeframe: str = "15m") -> Optional[list]:
        """Get OHLCV buffer for pattern detection (compatibility method).
        
        CRITICAL FIX (2026-07-17): Added for position_monitor pattern detection compatibility.
        Returns list of OHLCV candles with open, high, low, close, volume, timestamp_window_end attributes.
        Returns None if spot data is unavailable or degraded.
        
        Args:
            asset: Asset symbol (e.g., "BTC")
            timeframe: Timeframe string (currently unused, defaults to "15m")
        
        Returns:
            List of OHLCV candle objects or None
        """
        result = self.get(asset)
        if isinstance(result, SpotError):
            return None
        
        # Create OHLCV candle from current spot data
        class OHLCVCandle:
            def __init__(self, open: float, high: float, low: float, close: float, volume: float, timestamp_window_end: int):
                self.open = open
                self.high = high
                self.low = low
                self.close = close
                self.volume = volume
                self.timestamp_window_end = timestamp_window_end
        
        # Use current spot data to create a single candle
        # In production, this would return a buffer of historical candles
        # For now, return a single candle from current data
        now_ms = int(time.time() * 1000)
        
        candle = OHLCVCandle(
            open=result.open if result.open else result.price,
            high=result.high if result.high else result.price,
            low=result.low if result.low else result.price,
            close=result.price,
            volume=result.volume if result.volume else 0.0,
            timestamp_window_end=now_ms
        )
        
        return [candle]
    
    async def get_previous_15m_candle_close(self, asset: str) -> Optional[float]:
        """Get the closing price of the previous 15-minute candle.
        
        CRITICAL FIX (2026-07-24): This is the authoritative source for strike target price.
        Kalshi's 15-minute markets use the closing price of the previous 15-minute candle
        as the strike price for the new window.
        
        Args:
            asset: Asset symbol (e.g., "BTC")
        
        Returns:
            Previous 15m candle close price, or None if unavailable
        """
        pair = f"{asset}-USD"
        
        # Fetch 2 candles (current and previous) with 15m granularity (900 seconds)
        try:
            ohlc_data = await self._fetch_ohlc_public(pair, granularity=900, limit=2)
            if ohlc_data and isinstance(ohlc_data, dict):
                candles = ohlc_data.get('candles', [])
                if len(candles) >= 2:
                    # The API returns candles in reverse chronological order (newest first)
                    # So candles[0] is current forming candle, candles[1] is previous closed candle
                    # We need the close of the previous candle (index 1)
                    previous_candle = candles[1]
                    return float(previous_candle[4])  # Index 4 is close
        except Exception as e:
            logger.error(f"[UNIFIED-SPOT] Failed to fetch previous 15m candle close for {asset}: {e}")
        
        return None
    
    def get_previous_15m_candle_close_sync(self, asset: str) -> Optional[float]:
        """Synchronous version of get_previous_15m_candle_close for use in sync contexts.
        
        CRITICAL FIX (2026-07-24): This is the authoritative source for strike target price.
        Kalshi's 15-minute markets use the closing price of the previous 15-minute candle
        as the strike price for the new window.
        
        Args:
            asset: Asset symbol (e.g., "BTC")
        
        Returns:
            Previous 15m candle close price, or None if unavailable
        """
        pair = f"{asset}-USD"
        
        # Fetch 2 candles (current and previous) with 15m granularity (900 seconds)
        # Use synchronous requests to avoid event loop conflicts
        try:
            url = f"https://api.exchange.coinbase.com/products/{pair}/candles"
            params = {
                'granularity': 900,  # 15 minutes
                'limit': 2
            }
            response = requests.get(url, params=params, timeout=5.0)
            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}: {response.text}")
            data = response.json()
            if not data or not isinstance(data, list) or len(data) < 2:
                raise Exception("Insufficient candles data returned")
            
            # Candle format: [timestamp, low, high, open, close, volume]
            # API returns candles in reverse chronological order (newest first)
            # So data[0] is current forming candle, data[1] is previous closed candle
            # We need the close of the previous candle (index 1)
            previous_candle = data[1]
            return float(previous_candle[4])  # Index 4 is close
        except Exception as e:
            logger.error(f"[UNIFIED-SPOT] Failed to fetch previous 15m candle close for {asset}: {e}")
        
        return None
    
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
        """Health check with recovery states and SQS metrics (2026 best practice)."""
        with self._cache_lock:
            cached_count = len(self._cache)
            cache_status = {}
            sqs_scores = {}
            
            for asset in self.SUPPORTED_ASSETS:
                state = self._data_states.get(asset, DataState.DEAD)
                sqs = self._compute_sqs(asset)
                
                cache_status[asset] = {
                    "cached": asset in self._cache,
                    "state": state.value,
                    "stale": state in [DataState.STALE, DataState.DEAD],
                    "fallback_activations": self._fallback_activations.get(asset, 0),
                    "sla_degrade_s": get_spot_max_age(),
                }
                sqs_scores[asset] = {
                    "composite": sqs.composite,
                    "trade_permitted": sqs.trade_permitted,
                    "degradation_level": sqs.degradation_level,
                    "threshold": sqs.threshold,
                }
        
        # Count by state
        state_counts = {}
        for state in self._data_states.values():
            state_counts[state.value] = state_counts.get(state.value, 0) + 1
        
        # Count stale assets
        stale_count = sum(1 for state in self._data_states.values() if state in [DataState.STALE, DataState.DEAD])
        
        return {
            "status": "healthy" if cached_count == len(self.SUPPORTED_ASSETS) else "degraded",
            "cached_count": cached_count,
            "cached_assets": cached_count,
            "total_assets": len(self.SUPPORTED_ASSETS),
            "supported_assets": self.SUPPORTED_ASSETS,
            "running": self._running,
            "state_distribution": state_counts,
            "sqs_scores": sqs_scores,
            "cache_status": cache_status,
            "stale_count": stale_count,
            "degraded_count": stale_count,
        }
    
    def get_degradation_level(self) -> Literal["normal", "yellow", "orange", "red"]:
        """Get overall system degradation level based on SQS (2026 best practice).
        
        Returns:
            Degradation level for graduated exposure controls
        """
        with self._cache_lock:
            if not self._cache:
                return "red"
        
        # Compute average SQS across all assets
        total_sqs = 0.0
        count = 0
        for asset in self.SUPPORTED_ASSETS:
            sqs = self._compute_sqs(asset)
            total_sqs += sqs.composite
            count += 1
        
        if count == 0:
            return "red"
        
        avg_sqs = total_sqs / count
        
        # Graduated exposure thresholds (2026 best practice)
        if avg_sqs >= 65.0:
            return "normal"  # 100% exposure
        elif avg_sqs >= 50.0:
            return "yellow"  # 40% exposure
        elif avg_sqs >= 35.0:
            return "orange"  # 15% exposure
        else:
            return "red"  # 0% exposure (liquidation only)


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


def get_settlement_input_price(asset: str, spot_price: Optional[float] = None) -> Tuple[Optional[float], Optional[float]]:
    """Return the settlement reference price and the public-spot-to-CF-RTI basis.

    Production path: ingest the matching CME CF-RTI benchmark.  Until that feed is
    wired in, this applies an empirically modeled basis (default 0 bps) to the
    public spot price from the UnifiedSpotService.  The returned basis is the
    fractional adjustment (e.g. 0.0005 for 5 bps) so callers can log/audit it.
    """
    if spot_price is None:
        spot_price = get_unified_spot_service().get_spot_price(asset)
    if spot_price is None:
        logger.warning("[SETTLEMENT-INPUT] No spot price available for asset=%s", asset)
        return None, None

    per_asset_key = f"MERID_CF_RTI_BASIS_BPS_{asset.upper()}"
    raw = os.getenv(per_asset_key, os.getenv("MERID_CF_RTI_BASIS_BPS", "0.0"))
    try:
        basis_bps = float(raw)
    except (TypeError, ValueError):
        logger.warning("[SETTLEMENT-INPUT] Invalid basis bps for asset=%s: %s", asset, raw)
        basis_bps = 0.0

    basis = basis_bps / 10000.0
    settlement = spot_price * (1.0 + basis)
    logger.debug(
        "[SETTLEMENT-INPUT] asset=%s spot=%.4f basis_bps=%.4f settlement=%.4f",
        asset, spot_price, basis_bps, settlement
    )
    return settlement, basis
