"""
Live Price Feed for MERID.

Real-time cryptocurrency price data from Coinbase Advanced Trade API.
Primary source for Kalshi BRTI index alignment.

Features:
- Primary: Coinbase Advanced Trade API (BTC-USD, ETH-USD, SOL-USD, XRP-USD, DOGE-USD)
- Timeframes: 1m, 5m, 15m, 1h, 4h, 1d, 1w
- Live ticker: price, 24h change %, volume, high/low
- OHLCV candles with 100-candle history
- Order book depth (top 20 bids/asks)
- Poll intervals: 5s (1m/5m), 30s (longer TFs)
- 5-min cache with Kraken fallback
- Price delta logging vs CoinGecko

Env vars:
    MERID_COINBASE_API_KEY / COINBASE_CLIENT_API_KEY / COINBASE_API_KEY
    MERID_COINBASE_API_SECRET / COINBASE_CLIENT_API_SECRET / COINBASE_API_SECRET
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

import httpx

from utils.deps import optional_dependency

ccxt = optional_dependency("ccxt")  # type: ignore
_CCXT_AVAILABLE = ccxt is not None

from utils.logger import get_logger
from merid.coinbase_env import coinbase_api_key, coinbase_api_secret
from core.environment import get_environment_flags
from core.network_client import RoutingProfile, get_network_client

logger = get_logger("data.live_price_feed")

# Coinbase Advanced Trade API v3
COINBASE_BASE_URL = "https://api.coinbase.com"

# Trading pairs matching Kalshi BRTI index constituents
COINBASE_PAIRS = [
    "BTC-USD",   # Primary reference for Kalshi BRTI
    "ETH-USD",
    "SOL-USD",
    "XRP-USD",
    "DOGE-USD",
]

# Standard trading timeframes with poll intervals
TIMEFRAMES = {
    "1m": {"granularity": "ONE_MINUTE", "poll_seconds": 5},
    "5m": {"granularity": "FIVE_MINUTE", "poll_seconds": 5},
    "15m": {"granularity": "FIFTEEN_MINUTE", "poll_seconds": 30},
    "1h": {"granularity": "ONE_HOUR", "poll_seconds": 30},
    "4h": {"granularity": "FOUR_HOUR", "poll_seconds": 30},
    "1d": {"granularity": "ONE_DAY", "poll_seconds": 30},
    "1w": {"granularity": "ONE_WEEK", "poll_seconds": 30},
}

# Cache TTL: 5 minutes
CACHE_TTL_SECONDS = 300
# Operator/risk: stale if no tick this long (distinct from CACHE_TTL and MERID_PM_MAX_SPOT_AGE_SECONDS)
LIVE_FEED_HEALTH_MAX_AGE_SECONDS = 120.0
LIVE_FEED_WARMING_GRACE_SECONDS = 90.0

# Configurable warning/cooldown intervals (from env vars for tuning without code changes)
_STALE_PRICE_LOG_THROTTLE_SECONDS = float(os.getenv("MERID_STALE_PRICE_LOG_THROTTLE_SECONDS", "25.0"))
_COINGECKO_COOLDOWN_SECONDS = float(os.getenv("MERID_COINGECKO_COOLDOWN_SECONDS", "30.0"))
_COINGECKO_MIN_INTERVAL_SECONDS = float(os.getenv("MERID_COINGECKO_MIN_INTERVAL_SECONDS", "5.0"))


@dataclass
class PriceData:
    """Price data structure."""
    symbol: str
    price: float
    bid: float
    ask: float
    volume_24h: float
    change_24h_pct: float
    high_24h: float
    low_24h: float
    timestamp: datetime
    exchange: str


@dataclass
class OHLCVCandle:
    """OHLCV candle data."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class OrderBookLevel:
    """Single order book level."""
    price: float
    size: float


@dataclass
class OrderBookDepth:
    """Order book depth data."""
    symbol: str
    bids: List[OrderBookLevel]  # Top 20
    asks: List[OrderBookLevel]  # Top 20
    timestamp: datetime
    spread_pct: float


@dataclass
class CachedData:
    """Cache entry with timestamp."""
    data: Any
    timestamp: float


def _utc_age_seconds(ts: datetime) -> float:
    """Seconds from *ts* to now in UTC, safe for naive or aware *ts*."""
    if getattr(ts, "tzinfo", None) is None:
        ts_naive = ts
    else:
        ts_naive = ts.astimezone(timezone.utc).replace(tzinfo=None)
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    return (now_naive - ts_naive).total_seconds()


class LivePriceFeed:
    """
    Production live price feed with Coinbase Advanced Trade API as primary.
    
    Features:
    - Coinbase Advanced Trade API (primary) - BTC-USD, ETH-USD, SOL-USD, XRP-USD, DOGE-USD
    - Timeframes: 1m, 5m, 15m, 1h, 4h, 1d, 1w with OHLCV candles
    - Order book depth (top 20 bids/asks)
    - 5s polling for 1m/5m, 30s for longer timeframes
    - 5-min cache with Kraken/CCXT fallback
    - Price delta logging vs previous CoinGecko feed
    """
    
    def __init__(self, symbols: List[str] = None):
        """
        Initialize live price feed with Coinbase Advanced Trade API as primary.
        
        Args:
            symbols: List of symbols to track (legacy, uses COINBASE_PAIRS primarily)
        """
        # CCXT fallback symbols — Kalshi-relevant assets, USD-denominated to match
        # Coinbase primary and Kalshi BRTI index. USDT pairs removed to prevent
        # price-source conflicts; Kalshi contracts are settled in USD.
        self.symbols = symbols or [
            'BTC/USD', 'ETH/USD', 'SOL/USD', 'XRP/USD', 'DOGE/USD',
        ]
        
        # Coinbase Advanced Trade API pairs (primary)
        self.coinbase_pairs = COINBASE_PAIRS.copy()
        self.timeframes = list(TIMEFRAMES.keys())
        
        # Coinbase API credentials
        self.coinbase_api_key = coinbase_api_key()
        self.coinbase_api_secret = coinbase_api_secret()
        self._has_coinbase_credentials = bool(self.coinbase_api_key and self.coinbase_api_secret)
        
        # Coinbase HTTP client
        self._coinbase_http: Optional[httpx.AsyncClient] = None
        
        # Data caches with TTL
        self.price_cache: Dict[str, PriceData] = {}
        self._candles_cache: Dict[str, Dict[str, CachedData]] = {}  # pair -> timeframe -> cached
        self._orderbook_cache: Dict[str, CachedData] = {}
        
        # Subscribers
        self.subscribers: List[Callable] = []
        self._candle_subscribers: List[Callable] = []
        self._orderbook_subscribers: List[Callable] = []
        
        # Background tasks
        self.running = False
        self._tasks: List[asyncio.Task] = []
        self._lock = asyncio.Lock()
        
        # CCXT exchanges (fallback)
        self.exchanges = {}
        self.update_interval = 1.0
        # Priority order for CCXT fallback fetches.
        # binance/bybit/okx are configured in _initialize_exchanges() but were
        # previously unreachable because they weren't in this list (upstream audit fix).
        self.exchange_priority = ['kraken', 'coinbase', 'gemini', 'binance', 'bybit', 'okx']
        
        # Error recovery parameters
        self.max_retries = 3
        self.retry_delay = 2.0
        self.exchange_failures: Dict[str, int] = {}
        self.last_successful_fetch: Dict[str, float] = {}
        self.circuit_breaker_threshold = 10
        self.circuit_breaker_reset_time = 300
        
        # Throttle "cache stale" logs in CCXT fallback path (avoid ERROR spam under loop lag)
        self._stale_fallback_log_at: Dict[str, float] = {}

        # CoinGecko rate limiting (fallback only)
        self._coingecko_semaphore = asyncio.Semaphore(1)
        self._coingecko_last_request: float = 0.0
        self._coingecko_cooldown_until: Optional[float] = None
        
        # Price delta tracking for source transition logging
        self._previous_coingecko_prices: Dict[str, float] = {}
        # Monotonic clocks for operator health (not serialized)
        self._last_tick_monotonic: Dict[str, float] = {}
        self._last_global_tick_monotonic: float = 0.0
        self._stream_start_monotonic: float = 0.0
        
        # Network client
        self._network_client = get_network_client()
        self._module_name = "data.live_price_feed"
        self._network_client.register_module_profile(self._module_name, RoutingProfile.VPN_A)
        
        # Initialize CCXT exchanges (fallback)
        self._initialize_exchanges()
        
        logger.info(
            f"Live price feed initialized: {len(self.coinbase_pairs)} Coinbase pairs, "
            f"Coinbase credentials: {self._has_coinbase_credentials}"
        )
    
    def _initialize_exchanges(self):
        """Initialize exchange connections with real API keys and retry logic."""
        # Skip crypto exchanges in Kalshi-only mode
        from merid.settings import settings
        if settings.KALSHI_ONLY:
            logger.info("Crypto exchanges SKIPPED (Kalshi-only mode)")
            return
        
        if not _CCXT_AVAILABLE:
            logger.warning("CCXT not installed; LivePriceFeed running in offline stub mode")
            return

        if not self._can_use_network():
            logger.warning("LivePriceFeed running in offline/VPN-restricted mode; skipping exchange init")
            return

        if self.exchanges:
            # Defensive: ensure previous exchange clients are torn down before recreating.
            logger.debug("Closing existing exchanges before reinitializing")
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._close_exchanges())
                else:
                    loop.run_until_complete(self._close_exchanges())
            except RuntimeError:
                pass  # No event loop available; skip teardown on reinit
        
        # Import environment variables for API keys
        import os
        
        exchanges_config = [
            ('kraken', {
                'enableRateLimit': True,
                'apiKey': os.getenv('KRAKEN_API_KEY'),
                'privateKey': os.getenv('KRAKEN_PRIVATE_KEY')
            }, 'primary'),
            ('coinbase', {
                'enableRateLimit': True,
                'apiKey': coinbase_api_key(),
                'secret': coinbase_api_secret(),
            }, 'backup'),
            ('gemini', {
                'enableRateLimit': True,
                # Gemini doesn't require API keys for public data
            }, 'tertiary'),
            ('binance', {
                'enableRateLimit': True,
                'apiKey': os.getenv('BINANCE_API_KEY'),
                'secret': os.getenv('BINANCE_API_SECRET')
            }, 'quaternary'),
            ('bybit', {
                'enableRateLimit': True,
                'apiKey': os.getenv('BYBIT_API_KEY'),
                'secret': os.getenv('BYBIT_API_SECRET')
            }, 'quinary'),
            ('okx', {
                'enableRateLimit': True,
                'apiKey': os.getenv('OKX_API_KEY'),
                'secret': os.getenv('OKX_SECRET_KEY'),
                'password': os.getenv('OKX_API_KEY_NAME')
            }, 'senary')
        ]
        
        for exchange_name, config, priority in exchanges_config:
            for attempt in range(self.max_retries):
                try:
                    exchange_class = getattr(ccxt, exchange_name)
                    
                    # Filter out None values from config
                    filtered_config = {k: v for k, v in config.items() if v is not None and v != 'change_me'}
                    
                    self._guard_network_call("init", exchange_name)
                    self.exchanges[exchange_name] = exchange_class(filtered_config)
                    self.exchange_failures[exchange_name] = 0
                    
                    # Log API key status
                    api_key_status = "configured" if filtered_config.get('apiKey') else "public only"
                    logger.info(f"{exchange_name.capitalize()} exchange initialized ({priority}) - {api_key_status}")
                    break
                except Exception as exc:
                    if attempt < self.max_retries - 1:
                        logger.warning(f"Failed to initialize {exchange_name} (attempt {attempt + 1}/{self.max_retries}): {exc}")
                        time.sleep(self.retry_delay)
                    else:
                        logger.error(f"Failed to initialize {exchange_name} after {self.max_retries} attempts: {exc}")
                        self.exchange_failures[exchange_name] = self.circuit_breaker_threshold
    
    async def start_streaming(self):
        """
        Start streaming price updates.
        Uses Coinbase Advanced Trade API as primary, falls back to CCXT/CoinGecko.
        """
        self._stream_start_monotonic = time.monotonic()
        # Try Coinbase Advanced Trade API first (primary source)
        coinbase_started = await self.start_coinbase_streaming()
        if coinbase_started:
            logger.info("Primary streaming via Coinbase Advanced Trade API active")
            return True
        
        # Fallback to legacy CCXT streaming
        logger.warning("Coinbase streaming failed — using CCXT/CoinGecko fallback")
        return await self._start_ccxt_streaming()
    
    async def _start_ccxt_streaming(self) -> bool:
        """Legacy CCXT streaming fallback."""
        if self.running:
            logger.debug("start_streaming() called but already running — skipping")
            return True
        
        self.running = True
        self._cycle_count = 0
        logger.info("Price streaming started (CCXT fallback): %d symbols, %d exchanges", 
                   len(self.symbols), len(self.exchanges))
        
        while self.running:
            try:
                if not self._can_use_network():
                    logger.info("Network disabled (offline/VPN restriction); skipping fetch cycle")
                    await asyncio.sleep(self.update_interval)
                    continue
                await self.fetch_and_broadcast_prices()
                self._cycle_count += 1
                if self._cycle_count == 1:
                    cached = len(self.price_cache)
                    logger.info("First CCXT fetch cycle complete: %d/%d symbols cached", cached, len(self.symbols))
                    if cached == 0:
                        logger.warning("CCXT fetch cycle produced 0 prices — falling back to CoinGecko via /api/prices/live")
                await asyncio.sleep(self.update_interval)
            except Exception as exc:
                logger.error(f"Error in price streaming loop: {exc}")
                await asyncio.sleep(self.update_interval)
        return True
    
    def stop_streaming(self):
        """Stop price streaming."""
        self.running = False

        # Cancel all background tasks
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

        logger.info("Price streaming stopped")
        # Schedule exchange teardown on the running loop if one exists; fall back to
        # a fire-and-forget thread if called from outside an async context (Python 3.10+
        # deprecated asyncio.get_event_loop() with no current loop).
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._close_exchanges())
        except RuntimeError:
            # No running event loop — best-effort teardown in a new thread
            import threading
            def _teardown():
                asyncio.run(self._close_exchanges())
            threading.Thread(target=_teardown, daemon=True).start()

    async def _close_exchanges(self):
        """Close any CCXT exchange clients to avoid aiohttp connector leaks."""
        if not self.exchanges:
            return
        logger.debug("Closing %d exchange clients", len(self.exchanges))
        for name, exchange in list(self.exchanges.items()):
            close_fn = getattr(exchange, "close", None)
            if not close_fn:
                continue
            try:
                if asyncio.iscoroutinefunction(close_fn):
                    await close_fn()
                else:
                    close_fn()
            except Exception as exc:
                logger.warning(f"Failed to close exchange {name}: {exc}")
        self.exchanges.clear()
    
    async def fetch_and_broadcast_prices(self):
        """Fetch latest prices and broadcast to subscribers with error recovery."""
        for i, symbol in enumerate(self.symbols):
            await self._fetch_price_with_retry(symbol)
            # Yield to event loop every 5 symbols so HTTP requests can be served
            if (i + 1) % 5 == 0:
                await asyncio.sleep(0)
    
    async def _fetch_price_with_retry(self, symbol: str):
        """
        Fetch price with retry logic and fallback chain.
        
        Fetch sequence (in order of preference):
        1. Coinbase Public API (PRIMARY) - no auth required, fast, reliable
        2. Kraken Public API (FALLBACK #1) - no auth required, good depth
        3. CCXT exchanges (FALLBACK #2) - authenticated exchanges via CCXT
        4. CoinGecko (LAST RESORT) - rate limited, batch fetch
        
        Args:
            symbol: Asset symbol in internal format (e.g., "BTC/USD")
        """
        fetched: Optional[PriceData] = None
        
        # === PRIMARY: Coinbase Public API ===
        try:
            fetched = await self._fetch_from_coinbase_public(symbol)
            if fetched:
                logger.debug(f"Price fetched from Coinbase public API for {symbol}")
                return
        except Exception as exc:
            logger.debug(f"Coinbase public API failed for {symbol}: {exc}")
        
        # === FALLBACK #1: Kraken Public API ===
        logger.info(f"Falling back from Coinbase to Kraken public API for {symbol}")
        try:
            fetched = await self._fetch_from_kraken_public(symbol)
            if fetched:
                logger.debug(f"Price fetched from Kraken public API for {symbol}")
                return
        except Exception as exc:
            logger.debug(f"Kraken public API failed for {symbol}: {exc}")
        
        # === FALLBACK #2: CCXT exchanges (authenticated) ===
        logger.info(f"Falling back from public APIs to CCXT exchanges for {symbol}")
        for exchange_name in self.exchange_priority:
            if exchange_name not in self.exchanges:
                continue
            
            # Check circuit breaker
            if self._is_circuit_breaker_active(exchange_name):
                logger.debug(f"Circuit breaker active for {exchange_name}, skipping")
                continue
            
            # Try to fetch with retries
            for attempt in range(self.max_retries):
                try:
                    exchange = self.exchanges[exchange_name]
                    try:
                        self._guard_network_call("ticker", f"{exchange_name}:{symbol}")
                    except RuntimeError:
                        break  # Network guard blocked — skip this exchange
                    
                    # Adjust symbol format for different exchanges
                    fetch_symbol = symbol
                    if exchange_name in ['kraken', 'coinbase', 'gemini']:
                        fetch_symbol = symbol.replace('/USDT', '/USD')
                    
                    # Load markets if not yet loaded, then skip unlisted symbols
                    if not exchange.markets:
                        try:
                            await asyncio.to_thread(exchange.load_markets)
                        except Exception:
                            pass  # proceed anyway
                    if exchange.markets and fetch_symbol not in exchange.markets:
                        break
                    
                    ticker = await asyncio.to_thread(exchange.fetch_ticker, fetch_symbol)
                    
                    price_data = PriceData(
                        symbol=symbol,
                        price=ticker['last'],
                        bid=ticker['bid'] or ticker['last'],
                        ask=ticker['ask'] or ticker['last'],
                        volume_24h=ticker['quoteVolume'] or 0,
                        change_24h_pct=ticker['percentage'] or 0,
                        high_24h=ticker.get('high') or ticker['last'],
                        low_24h=ticker.get('low') or ticker['last'],
                        timestamp=datetime.now(timezone.utc),
                        exchange=exchange_name
                    )
                    
                    # Update cache
                    self.price_cache[symbol] = price_data
                    self._bump_tick_clock(symbol)
                    
                    # Register price assertion with Reality Registry
                    self._register_price_assertion(price_data, exchange_name)
                    
                    # Broadcast to subscribers
                    await self._broadcast_update(price_data)
                    
                    # Reset failure count on success
                    self.exchange_failures[exchange_name] = 0
                    self.last_successful_fetch[exchange_name] = time.time()
                    
                    fetched = price_data
                    break
                    
                except Exception as exc:
                    self.exchange_failures[exchange_name] = self.exchange_failures.get(exchange_name, 0) + 1
                    
                    # 401/403 = auth or permission error — don't retry, skip exchange
                    exc_str = str(exc)
                    if "401" in exc_str or "403" in exc_str:
                        logger.debug(f"Auth error for {symbol} on {exchange_name}, skipping: {exc}")
                        break
                    
                    if attempt < self.max_retries - 1:
                        logger.debug(f"Failed to fetch {symbol} from {exchange_name} (attempt {attempt + 1}/{self.max_retries}): {exc}")
                        await asyncio.sleep(self.retry_delay)
                    else:
                        logger.debug(f"Failed to fetch {symbol} from {exchange_name} after {self.max_retries} attempts: {exc}")
            
            if fetched:
                break
        
        # === LAST RESORT: CoinGecko ===
        if not fetched:
            logger.info(f"Falling back from CCXT to CoinGecko for {symbol}")
            fetched_coingecko = await self._fetch_from_coingecko(symbol)
            if fetched_coingecko:
                return
        
        # === FAILURE: Log and use cached if available ===
        if not fetched:
            logger.warning(f"All price sources failed for {symbol} (Coinbase public, Kraken public, CCXT, CoinGecko)")
            if symbol in self.price_cache:
                cached_age = _utc_age_seconds(self.price_cache[symbol].timestamp)
                if cached_age < 60:
                    logger.info(f"Using cached price for {symbol} (age: {cached_age:.1f}s)")
                else:
                    _now = time.monotonic()
                    _last = self._stale_fallback_log_at.get(symbol, 0.0)
                    if _now - _last >= _STALE_PRICE_LOG_THROTTLE_SECONDS:
                        self._stale_fallback_log_at[symbol] = _now
                        logger.warning(
                            "Cached price for %s stale while refresh failed (age=%.1fs) — "
                            "check event-loop lag, Coinbase ticker, or CoinGecko 429",
                            symbol,
                            cached_age,
                        )
    
    async def _broadcast_update(self, price_data: PriceData):
        """Broadcast price update to all subscribers, validating against data contracts."""
        # Validate against data contract (if registered for this exchange)
        try:
            from core.data_contracts import get_data_contract_registry
            registry = get_data_contract_registry()
            feed_id = price_data.exchange.lower()
            if registry.get_contract(feed_id):
                data_dict = {
                    "price": price_data.price,
                    "volume": price_data.volume_24h,
                    "symbol": price_data.symbol,
                    "timestamp": price_data.timestamp.timestamp(),
                }
                result = registry.validate(feed_id, data_dict)
                if not result.valid:
                    logger.warning(f"Data contract violation for {feed_id}/{price_data.symbol}: {result.errors}")
        except ImportError:
            pass  # data_contracts module not available
        except Exception as exc:
            logger.debug(f"Data contract check error: {exc}")

        for subscriber in self.subscribers:
            try:
                if asyncio.iscoroutinefunction(subscriber):
                    await subscriber(price_data)
                else:
                    subscriber(price_data)
            except Exception as exc:
                logger.error(f"Error broadcasting to subscriber: {exc}")
    
    def subscribe(self, callback: Callable):
        """
        Subscribe to price updates.
        
        Args:
            callback: Function to call with PriceData on each update
        """
        self.subscribers.append(callback)
        logger.info(f"New subscriber added (total: {len(self.subscribers)})")
    
    def unsubscribe(self, callback: Callable):
        """Unsubscribe from price updates."""
        if callback in self.subscribers:
            self.subscribers.remove(callback)
            logger.info(f"Subscriber removed (total: {len(self.subscribers)})")
    
    def get_current_price(self, symbol: str) -> Optional[PriceData]:
        """Get current cached price for a symbol.

        Returns None if the cached entry is older than CACHE_TTL_SECONDS
        to prevent stale prices from flowing into the edge model.
        """
        entry = self.price_cache.get(symbol)
        if entry is None:
            return None
        age = _utc_age_seconds(entry.timestamp)
        if age > CACHE_TTL_SECONDS:
            logger.debug("Price cache expired for %s (age=%.0fs > TTL=%ds)", symbol, age, CACHE_TTL_SECONDS)
            return None
        return entry
    
    # Legacy compatibility
    def get_price(self, symbol: str) -> Optional[PriceData]:
        """Alias for older callers expecting get_price."""
        return self.get_current_price(symbol)
    
    def get_all_prices(self) -> Dict[str, PriceData]:
        """Get all current cached prices."""
        return self.price_cache.copy()
    
    async def fetch_historical_ohlcv(
        self,
        symbol: str,
        timeframe: str = '1h',
        limit: int = 100
    ) -> List[List]:
        """
        Fetch historical OHLCV data.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Timeframe (1m, 5m, 15m, 1h, 4h, 1d)
            limit: Number of candles to fetch
            
        Returns:
            List of OHLCV candles [timestamp, open, high, low, close, volume]
        """
        exchange_priority = ['kraken', 'coinbase', 'binance']
        
        for exchange_name in exchange_priority:
            if exchange_name not in self.exchanges:
                continue
                
            try:
                exchange = self.exchanges[exchange_name]
                self._guard_network_call("ohlcv", f"{exchange_name}:{symbol}:{timeframe}")
                fetch_symbol = symbol
                if exchange_name in ['kraken', 'coinbase']:
                    fetch_symbol = symbol.replace('/USDT', '/USD')
                
                ohlcv = await asyncio.to_thread(exchange.fetch_ohlcv, fetch_symbol, timeframe, limit)
                return ohlcv
            except Exception as exc:
                logger.debug(f"Failed to fetch OHLCV from {exchange_name}: {exc}")
                continue
        
        logger.error(f"Failed to fetch OHLCV for {symbol} from all exchanges")
        return []
    
    def _register_price_assertion(self, price_data: PriceData, exchange_name: str):
        """Register price data as assertion in Reality Registry."""
        try:
            from core.reality_registry import (
                get_reality_registry,
                AssertionDomain,
                AssertionProvenance,
            )
            import time
            
            registry = get_reality_registry()
            
            # Calculate confidence based on bid-ask spread
            if price_data.price <= 0:
                return
            spread_pct = abs(price_data.ask - price_data.bid) / price_data.price * 100
            confidence = max(0.7, min(0.95, 1.0 - (spread_pct / 10)))  # Lower confidence for wide spreads
            
            # Provenance score based on exchange reliability
            exchange_scores = {
                'kraken': 0.95,
                'coinbase': 0.93,
                'binance': 0.90,
            }
            provenance_score = exchange_scores.get(exchange_name, 0.80)
            
            # Register assertion
            registry.register_assertion(
                domain=AssertionDomain.MARKET,
                description=f"{price_data.symbol} price: ${price_data.price:.2f} from {exchange_name}",
                confidence=confidence,
                provenance_score=provenance_score,
                regime_compatibility=1.0,
                decay_rate=0.1,  # Price data decays quickly
                validity_window=60,  # Valid for 60 seconds
                sources=[AssertionProvenance(
                    source_id=f"live-price-{exchange_name}",
                    module_id="data.live_price_feed",
                    evidence_hash=f"price:{price_data.symbol}:{price_data.timestamp.timestamp()}",
                    weight=1.0,
                    timestamp=time.time(),
                )],
            )
            
        except Exception as e:
            logger.debug(f"Failed to register price assertion: {e}")
    
    def _is_circuit_breaker_active(self, exchange_name: str) -> bool:
        """Check if circuit breaker is active for an exchange."""
        failures = self.exchange_failures.get(exchange_name, 0)
        
        if failures < self.circuit_breaker_threshold:
            return False
        
        # Check if enough time has passed to reset
        last_success = self.last_successful_fetch.get(exchange_name, 0)
        time_since_success = time.time() - last_success
        
        if time_since_success > self.circuit_breaker_reset_time:
            logger.info(f"Resetting circuit breaker for {exchange_name}")
            self.exchange_failures[exchange_name] = 0
            return False
        
        return True
    
    def _bump_tick_clock(self, symbol: str) -> None:
        """Record monotonic time of last successful price tick for health diagnostics."""
        now = time.monotonic()
        self._last_tick_monotonic[symbol] = now
        self._last_global_tick_monotonic = now
        # Notify FeedStalenessMonitor so it can auto-recover paused agents.
        # Strip "/USD" to match asset names used in agent config (e.g. "BTC/USD" → "BTC").
        try:
            from core.feed_staleness_monitor import get_feed_staleness_monitor
            _asset = symbol.replace("/USD", "").replace("/USDT", "").upper()
            if _asset:
                get_feed_staleness_monitor().record_update("coinbase", _asset)
        except Exception:
            pass

    def get_pm_feed_health_snapshot(
        self, assets: Sequence[str]
    ) -> Dict[str, Any]:
        """
        Per-asset feed health for PM spot diagnostics (risk-state / operator UI).

        Distinct from CACHE_TTL and MERID_PM_MAX_SPOT_AGE_SECONDS: uses
        LIVE_FEED_HEALTH_MAX_AGE_SECONDS for "stream is dead" vs "stale PM threshold".
        """
        now = time.monotonic()
        grace = LIVE_FEED_WARMING_GRACE_SECONDS
        max_age = LIVE_FEED_HEALTH_MAX_AGE_SECONDS
        started = self._stream_start_monotonic or 0.0
        warming = started > 0 and (now - started) < grace
        per_asset: Dict[str, Any] = {}
        for raw in assets:
            sym = (raw or "").strip().upper()
            if not sym:
                continue
            key = sym if "/" in sym else f"{sym}/USD"
            alt_usdt = key.replace("/USD", "/USDT")
            last_m = self._last_tick_monotonic.get(key)
            if last_m is None and alt_usdt != key:
                last_m = self._last_tick_monotonic.get(alt_usdt)
            if last_m is not None:
                age_s: Optional[float] = now - last_m
            else:
                age_s = None
            if not self.running:
                healthy = False
            elif last_m is None:
                healthy = warming
            else:
                healthy = bool(age_s is not None and age_s <= max_age)
            per_asset[key] = {
                "live_price_feed_healthy": healthy,
                "last_stream_tick_age_seconds": age_s,
                "warming": warming,
            }
        last_global_age: Optional[float] = None
        if self._last_global_tick_monotonic:
            last_global_age = now - self._last_global_tick_monotonic
        return {
            "live_price_feed_running": self.running,
            "live_feed_warming": warming,
            "last_global_stream_tick_age_seconds": last_global_age,
            "per_asset": per_asset,
        }

    def get_stats(self) -> Dict:
        """Get comprehensive price feed statistics."""
        exchange_health = {}
        for exchange_name in self.exchanges.keys():
            failures = self.exchange_failures.get(exchange_name, 0)
            circuit_breaker = self._is_circuit_breaker_active(exchange_name)
            last_success = self.last_successful_fetch.get(exchange_name, 0)
            
            exchange_health[exchange_name] = {
                "failures": failures,
                "circuit_breaker_active": circuit_breaker,
                "last_successful_fetch": last_success,
                "time_since_success": time.time() - last_success if last_success > 0 else None
            }
        
        # Coinbase stats
        coinbase_stats = {
            "connected": self._coinbase_http is not None,
            "credentials_configured": self._has_coinbase_credentials,
            "pairs_tracked": len(self.coinbase_pairs),
            "candle_subscribers": len(self._candle_subscribers),
            "orderbook_subscribers": len(self._orderbook_subscribers),
            "cached_candles": {pair: len(tfs) for pair, tfs in self._candles_cache.items()},
            "cached_orderbooks": list(self._orderbook_cache.keys()),
        }
        
        return {
            "running": self.running,
            "primary_source": "coinbase_advanced" if self._has_coinbase_credentials else "ccxt_fallible",
            "coinbase": coinbase_stats,
            "symbols_tracked": len(self.symbols),
            "exchanges_connected": len(self.exchanges),
            "subscribers": len(self.subscribers),
            "cached_prices": len(self.price_cache),
            "update_interval": self.update_interval,
            "exchange_health": exchange_health,
        }

    def _can_use_network(self) -> bool:
        flags = get_environment_flags()
        if not flags.online:
            return False
        return self._network_client.can_call_outbound(self._module_name)

    def _guard_network_call(self, action: str, endpoint: str) -> None:
        self._network_client.resolve_endpoint(self._module_name, f"{action}:{endpoint}")

    # ============================================================================
    # COINBASE ADVANCED TRADE API METHODS (PRIMARY SOURCE)
    # ============================================================================

    def _coinbase_auth_headers(self, method: str, path: str, body: str = "") -> Dict[str, str]:
        """Build Coinbase Advanced Trade API v3 auth headers.
        
        Uses HMAC-SHA256 signature with base64 encoding as required by Coinbase v3:
        - timestamp + method + path + body (no separators)
        - Secret is base64-decoded before use as HMAC key
        - HMAC-SHA256(secret, message)
        - Base64 encode the final signature
        """
        import base64
        
        ts = str(int(time.time()))
        message = f"{ts}{method.upper()}{path}{body}".encode("utf-8")
        
        # Decode secret from base64 (Coinbase provides it base64-encoded)
        try:
            secret = base64.b64decode(self.coinbase_api_secret)
        except Exception:
            # Fallback: treat as raw string if not valid base64
            secret = self.coinbase_api_secret.encode("utf-8")
        
        # HMAC-SHA256 with base64 encoding (Coinbase v3 requirement)
        sig = hmac.new(secret, message, hashlib.sha256).digest()
        sig_b64 = base64.b64encode(sig).decode("utf-8")
        
        headers = {
            "CB-ACCESS-KEY": self.coinbase_api_key,
            "CB-ACCESS-SIGN": sig_b64,
            "CB-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json",
        }
        
        # Add passphrase if available (some keys require it)
        passphrase = os.getenv("COINBASE_PASSPHRASE", "")
        if passphrase:
            headers["CB-ACCESS-PASSPHRASE"] = passphrase
        
        return headers

    async def _connect_coinbase(self) -> bool:
        """Connect to Coinbase Advanced Trade API."""
        if not self._has_coinbase_credentials:
            logger.warning("Coinbase credentials not configured — using CCXT fallback only")
            return False
        
        try:
            self._coinbase_http = httpx.AsyncClient(
                base_url=COINBASE_BASE_URL,
                timeout=15.0,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
            
            # Test connection with accounts endpoint (requires portfolio:read permission)
            path = "/api/v3/brokerage/accounts"
            resp = await self._coinbase_http.get(
                path,
                headers=self._coinbase_auth_headers("GET", path),
            )
            resp.raise_for_status()
            
            logger.info("Coinbase Advanced Trade API connected successfully")
            return True
            
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            # Rate-limited logging to prevent error budget spam
            _now = time.monotonic()
            _last_log = getattr(self, '_coinbase_auth_error_logged_at', 0)
            should_log = (_now - _last_log) >= 300  # Log once per 5 minutes

            if status == 401:
                if should_log:
                    self._coinbase_auth_error_logged_at = _now
                    logger.warning(
                        "[COINBASE-AUTH] Coinbase v3 connection failed with 401 — "
                        "check that MERID_COINBASE_API_KEY / COINBASE_API_KEY is a valid "
                        "Advanced Trade API key. Continuing with CCXT fallback."
                    )
            elif status == 403:
                if should_log:
                    self._coinbase_auth_error_logged_at = _now
                    logger.warning(
                        "[COINBASE-AUTH] Coinbase v3 connection failed with 403 — "
                        "API key lacks 'portfolio:read' permission. Continuing with CCXT fallback."
                    )
            else:
                if should_log:
                    self._coinbase_auth_error_logged_at = _now
                    logger.warning(f"[COINBASE-AUTH] Coinbase connection test failed with HTTP {status}: {e}")
            return False
        except Exception as e:
            # Non-auth errors also rate-limited
            _now = time.monotonic()
            _last_log = getattr(self, '_coinbase_error_logged_at', 0)
            if (_now - _last_log) >= 300:
                self._coinbase_error_logged_at = _now
                logger.warning(f"[COINBASE-AUTH] Coinbase connection failed: {e}")
            return False

    async def start_coinbase_streaming(self):
        """Start Coinbase Advanced Trade streaming with all pairs and timeframes."""
        if not await self._connect_coinbase():
            logger.warning("Coinbase streaming not started — connection failed, using CCXT fallback")
            # Fall back to legacy CCXT streaming directly (not via start_streaming to avoid recursion)
            await self._start_ccxt_streaming()
            return False
        
        self.running = True
        
        # Start ticker polling tasks (fast: 5s) for all pairs
        for pair in self.coinbase_pairs:
            task = asyncio.create_task(
                self._coinbase_ticker_loop(pair),
                name=f"coinbase_ticker_{pair}",
            )
            self._tasks.append(task)
        
        # Start candle polling tasks (timeframe-dependent intervals)
        for pair in self.coinbase_pairs:
            for tf in self.timeframes:
                task = asyncio.create_task(
                    self._coinbase_candle_loop(pair, tf),
                    name=f"coinbase_candles_{pair}_{tf}",
                )
                self._tasks.append(task)
        
        # Start order book polling tasks (30s)
        for pair in self.coinbase_pairs:
            task = asyncio.create_task(
                self._coinbase_orderbook_loop(pair),
                name=f"coinbase_orderbook_{pair}",
            )
            self._tasks.append(task)
        
        logger.info(
            f"Coinbase streaming started: {len(self.coinbase_pairs)} pairs, "
            f"{len(self.timeframes)} timeframes, {len(self._tasks)} tasks"
        )
        return True

    async def _coinbase_ticker_loop(self, pair: str):
        """Poll ticker data from Coinbase every 5 seconds."""
        while self.running:
            try:
                ticker = await self._fetch_coinbase_ticker(pair)
                # BTC-USD → BTC/USD for all cache/staleness keys (USD-only after USDT removal).
                usd_symbol = pair.replace("-", "/")
                if ticker:
                    self.price_cache[usd_symbol] = ticker
                    self._bump_tick_clock(usd_symbol)

                    # Log price delta vs previous CoinGecko price
                    await self._log_price_delta(pair, ticker.price)

                    # Broadcast to subscribers
                    await self._broadcast_update(ticker)

                    # Register price assertion
                    self._register_price_assertion(ticker, "coinbase_advanced")
                else:
                    # Coinbase returned None (auth error, 429, maintenance, network drop).
                    # Fall back to CoinGecko so price_cache stays fresh and the execution
                    # gate does not trip BLOCKED after the 120-second staleness threshold.
                    await self._fetch_from_coingecko(usd_symbol)

                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Coinbase ticker loop error for {pair}: {e}")
                await asyncio.sleep(5)

    async def _coinbase_candle_loop(self, pair: str, timeframe: str):
        """Poll candle data from Coinbase based on timeframe."""
        poll_seconds = TIMEFRAMES[timeframe]["poll_seconds"]
        
        while self.running:
            try:
                candles = await self._fetch_coinbase_candles(pair, timeframe)
                if candles:
                    async with self._lock:
                        if pair not in self._candles_cache:
                            self._candles_cache[pair] = {}
                        self._candles_cache[pair][timeframe] = CachedData(
                            data=candles,
                            timestamp=time.time(),
                        )
                    
                    # Broadcast to candle subscribers
                    for callback in self._candle_subscribers:
                        try:
                            if asyncio.iscoroutinefunction(callback):
                                await callback(pair, timeframe, candles)
                            else:
                                callback(pair, timeframe, candles)
                        except Exception as e:
                            logger.error(f"Error broadcasting candles: {e}")
                
                await asyncio.sleep(poll_seconds)
            except Exception as e:
                logger.error(f"Coinbase candle loop error for {pair}/{timeframe}: {e}")
                await asyncio.sleep(poll_seconds)

    async def _coinbase_orderbook_loop(self, pair: str):
        """Poll order book data from Coinbase every 30 seconds."""
        while self.running:
            try:
                depth = await self._fetch_coinbase_orderbook(pair)
                if depth:
                    async with self._lock:
                        self._orderbook_cache[pair] = CachedData(
                            data=depth,
                            timestamp=time.time(),
                        )
                    
                    # Broadcast to orderbook subscribers
                    for callback in self._orderbook_subscribers:
                        try:
                            if asyncio.iscoroutinefunction(callback):
                                await callback(depth)
                            else:
                                callback(depth)
                        except Exception as e:
                            logger.error(f"Error broadcasting orderbook: {e}")
                
                await asyncio.sleep(30)
            except Exception as e:
                logger.error(f"Coinbase orderbook loop error for {pair}: {e}")
                await asyncio.sleep(30)

    async def _fetch_coinbase_ticker(self, pair: str) -> Optional[PriceData]:
        """Fetch live ticker data from Coinbase Advanced Trade API."""
        if not self._coinbase_http:
            return None
        
        try:
            path = f"/api/v3/brokerage/products/{pair}"
            resp = await self._coinbase_http.get(
                path,
                headers=self._coinbase_auth_headers("GET", path),
            )
            resp.raise_for_status()
            data = resp.json()
            
            price = float(data.get("price", 0))
            if price <= 0:
                return None

            # Coinbase v3 product endpoint fields:
            #   best_bid / best_ask (not bid / ask)
            #   price_percentage_change_24h — already a % value, not absolute delta
            #   volume_24h — available directly
            #   high_24h / low_24h — not in product endpoint; default to price
            change_pct = float(data.get("price_percentage_change_24h") or 0.0)

            ticker = PriceData(
                symbol=pair.replace("-", "/"),  # BTC-USD → BTC/USD for legacy compat
                price=price,
                bid=float(data.get("best_bid") or price * 0.999),
                ask=float(data.get("best_ask") or price * 1.001),
                volume_24h=float(data.get("volume_24h") or 0),
                change_24h_pct=change_pct,
                high_24h=float(data.get("high_24h") or price),
                low_24h=float(data.get("low_24h") or price),
                timestamp=datetime.now(timezone.utc),
                exchange="coinbase_advanced",
            )
            
            return ticker
            
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 401:
                # Config issue - not a runtime error. System falls back to CCXT.
                logger.warning(
                    f"[COINBASE-AUTH] Coinbase v3 API returned 401 for {pair} — "
                    f"check MERID_COINBASE_API_KEY. Using CCXT fallback."
                )
            elif status == 403:
                logger.warning(
                    f"[COINBASE-AUTH] Coinbase v3 API returned 403 for {pair} — "
                    f"API key lacks permission. Using CCXT fallback."
                )
            elif status == 429:
                logger.warning(f"Coinbase rate limit hit for {pair}")
            else:
                logger.error(f"Coinbase API error for {pair}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching Coinbase ticker for {pair}: {e}")
            return None

    async def _fetch_coinbase_candles(self, pair: str, timeframe: str) -> Optional[List[OHLCVCandle]]:
        """Fetch OHLCV candles from Coinbase Advanced Trade API."""
        if not self._coinbase_http:
            return None
        
        try:
            granularity = TIMEFRAMES[timeframe]["granularity"]

            # Coinbase v3 expects Unix integer timestamps for start/end
            end_ts = int(datetime.now(timezone.utc).timestamp())

            path = f"/api/v3/brokerage/products/{pair}/candles"
            params = {
                "granularity": granularity,
                "end": end_ts,
                "limit": 100,  # 100 candles history
            }
            
            resp = await self._coinbase_http.get(
                path,
                headers=self._coinbase_auth_headers("GET", path),
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            
            candles_data = data.get("candles", [])
            if not candles_data:
                return None
            
            candles = []
            for candle in candles_data:
                # Coinbase v3 returns dicts: {"start": "unix_ts", "low": ..., "high": ...,
                #                             "open": ..., "close": ..., "volume": ...}
                candles.append(OHLCVCandle(
                    timestamp=datetime.fromtimestamp(int(candle["start"]), tz=timezone.utc),
                    low=float(candle["low"]),
                    high=float(candle["high"]),
                    open=float(candle["open"]),
                    close=float(candle["close"]),
                    volume=float(candle["volume"]),
                ))
            
            # Sort by timestamp ascending
            candles.sort(key=lambda c: c.timestamp)
            
            return candles[-100:] if len(candles) > 100 else candles
            
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 401:
                logger.warning(
                    f"[COINBASE-AUTH] Candles API 401 for {pair}/{timeframe} — "
                    f"using CCXT fallback"
                )
            elif status == 403:
                logger.warning(
                    f"[COINBASE-AUTH] Candles API 403 for {pair}/{timeframe} — "
                    f"using CCXT fallback"
                )
            else:
                logger.error(f"Coinbase candles API error for {pair}/{timeframe}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching Coinbase candles for {pair}/{timeframe}: {e}")
            return None

    async def _fetch_coinbase_orderbook(self, pair: str) -> Optional[OrderBookDepth]:
        """Fetch order book depth (top 20 bids/asks) from Coinbase Advanced Trade API."""
        if not self._coinbase_http:
            return None
        
        try:
            path = f"/api/v3/brokerage/products/{pair}/book"
            params = {"level": 2}  # Top 50 bids/asks
            
            resp = await self._coinbase_http.get(
                path,
                headers=self._coinbase_auth_headers("GET", path),
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            
            # Coinbase v3 wraps inside "pricebook"; each entry is {"price":..,"size":..}
            pricebook = data.get("pricebook", data)
            bids_data = pricebook.get("bids", [])[:20]  # Top 20
            asks_data = pricebook.get("asks", [])[:20]

            bids = [
                OrderBookLevel(price=float(b["price"]), size=float(b["size"]))
                for b in bids_data
            ]
            asks = [
                OrderBookLevel(price=float(a["price"]), size=float(a["size"]))
                for a in asks_data
            ]
            
            # Calculate spread %
            spread_pct = 0.0
            if bids and asks:
                best_bid = bids[0].price
                best_ask = asks[0].price
                mid = (best_bid + best_ask) / 2
                if mid > 0:
                    spread_pct = (best_ask - best_bid) / mid * 100
            
            return OrderBookDepth(
                symbol=pair,
                bids=bids,
                asks=asks,
                timestamp=datetime.now(timezone.utc),
                spread_pct=spread_pct,
            )
            
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 401:
                logger.warning(
                    f"[COINBASE-AUTH] Orderbook API 401 for {pair} — using fallback"
                )
            elif status == 403:
                logger.warning(
                    f"[COINBASE-AUTH] Orderbook API 403 for {pair} — using fallback"
                )
            else:
                logger.error(f"Coinbase orderbook API error for {pair}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching Coinbase orderbook for {pair}: {e}")
            return None

    async def _log_price_delta(self, pair: str, new_price: float):
        """Log price delta vs previous CoinGecko price."""
        legacy_symbol = pair.replace("-", "/")
        if legacy_symbol in self._previous_coingecko_prices:
            prev_price = self._previous_coingecko_prices[legacy_symbol]
            delta_pct = abs(new_price - prev_price) / prev_price * 100
            
            if delta_pct > 0.1:  # Alert if delta > 0.1%
                logger.warning(
                    f"PRICE_DELTA_ALERT: {pair} delta={delta_pct:.3f}% "
                    f"(CoinGecko: ${prev_price:.2f}, Coinbase: ${new_price:.2f})"
                )
            else:
                logger.info(
                    f"PRICE_DELTA_OK: {pair} delta={delta_pct:.4f}% (<0.1% threshold)"
                )

    def record_coingecko_price(self, symbol: str, price: float):
        """Record CoinGecko price for delta comparison during source transition."""
        self._previous_coingecko_prices[symbol] = price
        logger.info(f"Recorded CoinGecko price for {symbol}: ${price:.2f}")

    # Public API for candles and orderbook

    def get_candles(self, pair: str, timeframe: str) -> Optional[List[OHLCVCandle]]:
        """Get cached candle data (with 5-min TTL check)."""
        if pair not in self._candles_cache:
            return None
        
        cached = self._candles_cache[pair].get(timeframe)
        if not cached:
            return None
        
        age = time.time() - cached.timestamp
        if age > CACHE_TTL_SECONDS:
            logger.debug(f"Candles cache expired for {pair}/{timeframe} (age: {age:.0f}s)")
            return None
        
        return cached.data

    def get_orderbook(self, pair: str) -> Optional[OrderBookDepth]:
        """Get cached order book data (with 5-min TTL check)."""
        cached = self._orderbook_cache.get(pair)
        if not cached:
            return None
        
        age = time.time() - cached.timestamp
        if age > CACHE_TTL_SECONDS:
            logger.debug(f"Orderbook cache expired for {pair} (age: {age:.0f}s)")
            return None
        
        return cached.data

    def subscribe_candles(self, callback: Callable):
        """Subscribe to candle updates."""
        self._candle_subscribers.append(callback)
        logger.info(f"New candles subscriber (total: {len(self._candle_subscribers)})")

    def unsubscribe_candles(self, callback: Callable):
        """Unsubscribe from candle updates."""
        if callback in self._candle_subscribers:
            self._candle_subscribers.remove(callback)

    def subscribe_orderbook(self, callback: Callable):
        """Subscribe to order book updates."""
        self._orderbook_subscribers.append(callback)
        logger.info(f"New orderbook subscriber (total: {len(self._orderbook_subscribers)})")

    def unsubscribe_orderbook(self, callback: Callable):
        """Unsubscribe from order book updates."""
        if callback in self._orderbook_subscribers:
            self._orderbook_subscribers.remove(callback)

    # ============================================================================
    # PUBLIC API PRICE SOURCES (Primary: Coinbase, Fallback: Kraken)
    # ============================================================================

    # Asset mapping for public APIs: internal symbol -> exchange pair format
    _COINBASE_PUBLIC_PAIRS: Dict[str, str] = {
        "BTC/USD": "BTC-USD",
        "ETH/USD": "ETH-USD",
        "SOL/USD": "SOL-USD",
        "XRP/USD": "XRP-USD",
        "DOGE/USD": "DOGE-USD",
    }

    _KRAKEN_PUBLIC_PAIRS: Dict[str, str] = {
        "BTC/USD": "XXBTZUSD",   # Kraken uses XXBTZUSD for BTC/USD
        "ETH/USD": "XETHZUSD",   # Kraken uses XETHZUSD for ETH/USD
        "SOL/USD": "SOLUSD",     # SOL/USD on Kraken
        "XRP/USD": "XXRPZUSD",   # XRP/USD on Kraken
        "DOGE/USD": "XDGUSD",    # DOGE/USD on Kraken (XDG is their DOGE code)
    }

    # Reverse mapping for Kraken response parsing (Kraken pair -> internal symbol)
    _KRAKEN_PAIR_TO_SYMBOL: Dict[str, str] = {
        "XXBTZUSD": "BTC/USD",
        "XETHZUSD": "ETH/USD",
        "SOLUSD": "SOL/USD",
        "XXRPZUSD": "XRP/USD",
        "XDGUSD": "DOGE/USD",
    }

    async def _fetch_from_coinbase_public(self, symbol: str) -> Optional[PriceData]:
        """
        Fetch price from Coinbase public REST API (PRIMARY source).
        
        Uses the public /v2/prices/{pair}/spot endpoint which requires no authentication.
        This is the primary price source for BTC, ETH, SOL, XRP, DOGE.
        
        Args:
            symbol: Internal symbol format (e.g., "BTC/USD")
            
        Returns:
            PriceData if successful, None otherwise
        """
        pair = self._COINBASE_PUBLIC_PAIRS.get(symbol)
        if not pair:
            logger.debug(f"No Coinbase public pair mapping for {symbol}")
            return None

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Coinbase public API - no auth required
                url = f"https://api.coinbase.com/v2/prices/{pair}/spot"
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()

                # Parse Coinbase response: {"data": {"base": "BTC", "currency": "USD", "amount": "65000.00"}}
                price_data = data.get("data", {})
                price_str = price_data.get("amount", "0")
                price = float(price_str)

                if price <= 0:
                    logger.warning(f"Coinbase public API returned invalid price for {symbol}: {price_str}")
                    return None

                # Get 24h stats from exchange rates endpoint for additional context
                # This is a separate call but provides volume/change data
                stats_url = f"https://api.coinbase.com/v2/exchange-rates?currency={pair.split('-')[0]}"
                try:
                    stats_response = await client.get(stats_url, timeout=5.0)
                    stats_data = stats_response.json() if stats_response.status_code == 200 else {}
                except Exception:
                    stats_data = {}

                # Build PriceData with Coinbase as source
                # Note: Public API doesn't provide bid/ask spread, volume, or 24h change
                # We estimate bid/ask as 0.1% around spot price
                bid = price * 0.999
                ask = price * 1.001

                price_data_obj = PriceData(
                    symbol=symbol,
                    price=price,
                    bid=bid,
                    ask=ask,
                    volume_24h=0.0,  # Not available in public API
                    change_24h_pct=0.0,  # Not available in public API
                    high_24h=price,  # Not available in public API
                    low_24h=price,  # Not available in public API
                    timestamp=datetime.now(timezone.utc),
                    exchange="coinbase_public",
                )

                # Update cache and broadcast
                self.price_cache[symbol] = price_data_obj
                self._bump_tick_clock(symbol)
                await self._broadcast_update(price_data_obj)

                logger.debug(f"Coinbase public API: {symbol} = ${price:.2f}")
                return price_data_obj

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning(f"Coinbase public API rate limited for {symbol}")
            else:
                logger.debug(f"Coinbase public API HTTP error for {symbol}: {e.response.status_code}")
            return None
        except Exception as e:
            logger.debug(f"Coinbase public API fetch failed for {symbol}: {e}")
            return None

    async def _fetch_from_kraken_public(self, symbol: str) -> Optional[PriceData]:
        """
        Fetch price from Kraken public REST API (FALLBACK source).
        
        Uses the public /0/public/Ticker endpoint which requires no authentication.
        This is the fallback price source when Coinbase public API fails.
        
        Args:
            symbol: Internal symbol format (e.g., "BTC/USD")
            
        Returns:
            PriceData if successful, None otherwise
        """
        kraken_pair = self._KRAKEN_PUBLIC_PAIRS.get(symbol)
        if not kraken_pair:
            logger.debug(f"No Kraken public pair mapping for {symbol}")
            return None

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Kraken public API - no auth required
                url = f"https://api.kraken.com/0/public/Ticker?pair={kraken_pair}"
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()

                # Check for Kraken API errors
                if data.get("error"):
                    logger.debug(f"Kraken API error for {symbol}: {data['error']}")
                    return None

                # Parse Kraken response: {"result": {"XXBTZUSD": {"c": ["65000.0", "1.5"], ...}}}
                result = data.get("result", {})
                ticker_data = result.get(kraken_pair)
                if not ticker_data:
                    logger.debug(f"No ticker data in Kraken response for {symbol} (pair: {kraken_pair})")
                    return None

                # Kraken ticker format:
                # c = last trade [price, volume]
                # b = best bid [price, volume]
                # a = best ask [price, volume]
                # v = volume [today, last 24h]
                # p = VWAP [today, last 24h]
                # l = low [today, last 24h]
                # h = high [today, last 24h]
                # o = opening price
                last_trade = ticker_data.get("c", ["0", "0"])
                price = float(last_trade[0]) if last_trade else 0.0

                if price <= 0:
                    logger.warning(f"Kraken public API returned invalid price for {symbol}: {last_trade}")
                    return None

                best_bid = ticker_data.get("b", [price * 0.999, "0"])
                best_ask = ticker_data.get("a", [price * 1.001, "0"])
                bid = float(best_bid[0]) if best_bid else price * 0.999
                ask = float(best_ask[0]) if best_ask else price * 1.001

                volume_24h = 0.0
                vol_data = ticker_data.get("v", ["0", "0"])
                if vol_data and len(vol_data) > 1:
                    volume_24h = float(vol_data[1])  # Last 24h volume

                # Calculate 24h change from opening price
                opening = ticker_data.get("o", "0")
                open_price = float(opening) if opening else 0.0
                change_24h_pct = 0.0
                if open_price > 0:
                    change_24h_pct = ((price - open_price) / open_price) * 100

                # Get high/low from last 24h
                high_data = ticker_data.get("h", [price, price])
                low_data = ticker_data.get("l", [price, price])
                high_24h = float(high_data[1]) if high_data and len(high_data) > 1 else price
                low_24h = float(low_data[1]) if low_data and len(low_data) > 1 else price

                price_data_obj = PriceData(
                    symbol=symbol,
                    price=price,
                    bid=bid,
                    ask=ask,
                    volume_24h=volume_24h,
                    change_24h_pct=change_24h_pct,
                    high_24h=high_24h,
                    low_24h=low_24h,
                    timestamp=datetime.now(timezone.utc),
                    exchange="kraken_public",
                )

                # Update cache and broadcast
                self.price_cache[symbol] = price_data_obj
                self._bump_tick_clock(symbol)
                await self._broadcast_update(price_data_obj)

                logger.debug(f"Kraken public API: {symbol} = ${price:.2f}")
                return price_data_obj

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning(f"Kraken public API rate limited for {symbol}")
            else:
                logger.debug(f"Kraken public API HTTP error for {symbol}: {e.response.status_code}")
            return None
        except Exception as e:
            logger.debug(f"Kraken public API fetch failed for {symbol}: {e}")
            return None

    # ============================================================================
    # FALLBACK METHODS (CoinGecko - rate limited, last resort)
    # ============================================================================

    # CoinGecko coin IDs — keyed by the USD pair name used in price_cache.
    _COINGECKO_IDS: Dict[str, str] = {
        "BTC/USD":  "bitcoin",
        "ETH/USD":  "ethereum",
        "SOL/USD":  "solana",
        "XRP/USD":  "ripple",
        "DOGE/USD": "dogecoin",
    }

    async def _fetch_from_coingecko(self, symbol: str) -> bool:
        """Fetch price from CoinGecko as fallback when exchanges fail.

        Uses batch fetch to populate all assets efficiently (1 API call vs 5).
        Returns True if the requested symbol was successfully fetched.
        """
        # Check cooldown from previous rate limit
        if self._coingecko_cooldown_until and time.time() < self._coingecko_cooldown_until:
            logger.debug(f"CoinGecko in cooldown until {self._coingecko_cooldown_until:.0f}")
            return False

        # Check semaphore and rate limiting
        if self._coingecko_semaphore.locked():
            logger.debug("CoinGecko semaphore locked, skipping")
            return False

        now = time.time()
        time_since_last = now - self._coingecko_last_request
        if time_since_last < _COINGECKO_MIN_INTERVAL_SECONDS:  # Min interval between requests
            logger.debug(f"CoinGecko rate limit: {time_since_last:.1f}s since last request")
            return False
        
        # Use batch fetch to get all assets in one call (more efficient)
        return await self._fetch_batch_from_coingecko(symbol)
    
    async def _fetch_batch_from_coingecko(self, target_symbol: str) -> bool:
        """Batch fetch all crypto asset prices from CoinGecko in one call.
        
        This is much more efficient than individual calls (1 API call vs 5),
        reducing rate limit pressure and ensuring all assets populate together.
        
        Args:
            target_symbol: The specific symbol the caller requested (e.g., "ETH/USD")
            
        Returns True if the target symbol was successfully fetched.
        """
        # Get all CoinGecko IDs for batch request
        all_ids = ",".join(self._COINGECKO_IDS.values())
        if not all_ids:
            return False
        
        # Build reverse mapping: coingecko id -> our symbol
        id_to_symbol = {v: k for k, v in self._COINGECKO_IDS.items()}
        target_fetched = False
        
        async with self._coingecko_semaphore:
            try:
                # Wait minimum delay between requests
                time_since_last = time.time() - self._coingecko_last_request
                if time_since_last < _COINGECKO_MIN_INTERVAL_SECONDS:
                    await asyncio.sleep(_COINGECKO_MIN_INTERVAL_SECONDS - time_since_last)
                
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(
                        "https://api.coingecko.com/api/v3/coins/markets",
                        params={
                            "vs_currency": "usd",
                            "ids": all_ids,
                            "price_change_percentage": "24h",
                        },
                    )
                    self._coingecko_last_request = time.time()
                    
                    if response.status_code == 429:
                        # Rate limited - enter cooldown
                        self._coingecko_cooldown_until = time.time() + _COINGECKO_COOLDOWN_SECONDS
                        logger.warning(f"CoinGecko rate limited (429) - cooling down for {_COINGECKO_COOLDOWN_SECONDS}s")
                        return False
                    
                    response.raise_for_status()
                    data = response.json()
            except Exception as exc:
                logger.debug(f"CoinGecko batch fetch failed: {exc}")
                return False
            finally:
                self._coingecko_last_request = time.time()
            
            if not data:
                return False
            
            success_count = 0
            for market in data:
                cg_id = market.get("id")
                symbol = id_to_symbol.get(cg_id)
                if not symbol:
                    continue
                
                price = float(market.get("current_price") or 0)
                if price <= 0:
                    continue
                
                price_data = PriceData(
                    symbol=symbol,
                    price=price,
                    bid=price * 0.999,
                    ask=price * 1.001,
                    volume_24h=float(market.get("total_volume") or 0),
                    change_24h_pct=float(market.get("price_change_percentage_24h") or 0.0),
                    high_24h=float(market.get("high_24h") or price),
                    low_24h=float(market.get("low_24h") or price),
                    timestamp=datetime.now(timezone.utc),
                    exchange="coingecko",
                )
                self.price_cache[symbol] = price_data
                self._bump_tick_clock(symbol)
                success_count += 1
                
                if symbol == target_symbol:
                    target_fetched = True
                
                # Broadcast update
                try:
                    await self._broadcast_update(price_data)
                except Exception:
                    pass
            
            if success_count > 0:
                logger.info(f"CoinGecko batch fetch: populated {success_count}/5 assets")
            
            return target_fetched

    def get_latest_prices(self) -> Dict[str, Dict[str, Any]]:
        """Get latest cached prices for all symbols."""
        prices = {}
        for symbol, price_data in self.price_cache.items():
            prices[symbol] = {
                "price": price_data.price,
                "change_24h": getattr(price_data, "change_24h_pct", 0.0),
                "timestamp": price_data.timestamp.isoformat() if price_data.timestamp else None,
                "source": getattr(price_data, "exchange", "unknown"),
                "volume_24h": getattr(price_data, "volume_24h", 0.0),
            }
        return prices


# Global singleton
_live_price_feed: Optional[LivePriceFeed] = None
_live_price_feed_lock = threading.Lock()


def get_live_price_feed() -> LivePriceFeed:
    """Get or create live price feed singleton."""
    global _live_price_feed
    if _live_price_feed is None:
        with _live_price_feed_lock:
            if _live_price_feed is None:
                _live_price_feed = LivePriceFeed()
    return _live_price_feed


# Backward-compat alias used by system_endpoints.py and any other caller
get_live_feed = get_live_price_feed


# ============================================================================
# TEST / VERIFICATION
# ============================================================================

async def test_btc_1m_candle_integration() -> Dict[str, Any]:
    """
    Test BTC 1m candle data integration from Coinbase Advanced Trade API.
    
    Returns:
        Test result dict with success flag and sample data
    """
    logger.info("=" * 60)
    logger.info("BTC 1M CANDLE INTEGRATION TEST")
    logger.info("=" * 60)
    
    feed = get_live_price_feed()
    
    # Test 1: Verify Coinbase credentials
    logger.info("Test 1: Verifying Coinbase credentials...")
    if not feed._has_coinbase_credentials:
        logger.error("FAIL: Coinbase credentials not configured")
        logger.error(
            "Set Coinbase credentials (MERID_COINBASE_* / COINBASE_CLIENT_* / COINBASE_API_*)"
        )
        return {"success": False, "error": "credentials_not_configured"}
    logger.info("PASS: Coinbase credentials configured")
    
    # Test 2: Connect to Coinbase
    logger.info("Test 2: Connecting to Coinbase API...")
    connected = await feed._connect_coinbase()
    if not connected:
        logger.error("FAIL: Could not connect to Coinbase API")
        return {"success": False, "error": "connection_failed"}
    logger.info("PASS: Connected to Coinbase Advanced Trade API")
    
    # Test 3: Fetch BTC ticker
    logger.info("Test 3: Fetching BTC-USD ticker...")
    ticker = await feed._fetch_coinbase_ticker("BTC-USD")
    if not ticker:
        logger.error("FAIL: Could not fetch BTC ticker")
        return {"success": False, "error": "ticker_fetch_failed"}
    logger.info(f"PASS: BTC price: ${ticker.price:.2f}")
    logger.info(f"       Volume 24h: {ticker.volume_24h:,.2f}")
    logger.info(f"       Change 24h: {ticker.change_24h_pct:.2f}%")
    logger.info(f"       High 24h: ${ticker.high_24h:.2f}")
    logger.info(f"       Low 24h: ${ticker.low_24h:.2f}")
    
    # Test 4: Fetch BTC 1m candles
    logger.info("Test 4: Fetching BTC 1m candles (100-candle history)...")
    candles = await feed._fetch_coinbase_candles("BTC-USD", "1m")
    if not candles:
        logger.error("FAIL: Could not fetch BTC 1m candles")
        return {"success": False, "error": "candles_fetch_failed"}
    
    candle_count = len(candles)
    logger.info(f"PASS: Fetched {candle_count} 1m candles")
    
    # Verify candle structure
    sample = candles[-1] if candles else None
    if sample:
        logger.info(f"       Latest candle: {sample.timestamp.isoformat()}")
        logger.info(f"       O: ${sample.open:.2f}, H: ${sample.high:.2f}, L: ${sample.low:.2f}, C: ${sample.close:.2f}")
        logger.info(f"       Volume: {sample.volume:,.4f}")
    
    # Verify we have at least some candles
    if candle_count < 10:
        logger.warning(f"WARN: Only {candle_count} candles returned (expected 100)")
    
    # Test 5: Fetch order book
    logger.info("Test 5: Fetching BTC-USD order book depth...")
    orderbook = await feed._fetch_coinbase_orderbook("BTC-USD")
    if not orderbook:
        logger.error("FAIL: Could not fetch order book")
        return {"success": False, "error": "orderbook_fetch_failed"}
    
    bid_count = len(orderbook.bids)
    ask_count = len(orderbook.asks)
    logger.info(f"PASS: Order book fetched - {bid_count} bids, {ask_count} asks")
    logger.info(f"       Spread: {orderbook.spread_pct:.4f}%")
    
    if bid_count > 0 and ask_count > 0:
        best_bid = orderbook.bids[0].price
        best_ask = orderbook.asks[0].price
        logger.info(f"       Best bid: ${best_bid:.2f} (size: {orderbook.bids[0].size:.6f})")
        logger.info(f"       Best ask: ${best_ask:.2f} (size: {orderbook.asks[0].size:.6f})")
    
    # Test 6: Verify all required pairs
    logger.info("Test 6: Verifying all Kalshi BRTI pairs...")
    required_pairs = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD"]
    missing_pairs = [p for p in required_pairs if p not in feed.coinbase_pairs]
    if missing_pairs:
        logger.error(f"FAIL: Missing pairs: {missing_pairs}")
        return {"success": False, "error": "missing_pairs", "missing": missing_pairs}
    logger.info(f"PASS: All {len(required_pairs)} pairs configured")
    
    # Test 7: Verify all timeframes
    logger.info("Test 7: Verifying all timeframes...")
    required_tfs = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
    missing_tfs = [tf for tf in required_tfs if tf not in feed.timeframes]
    if missing_tfs:
        logger.error(f"FAIL: Missing timeframes: {missing_tfs}")
        return {"success": False, "error": "missing_timeframes", "missing": missing_tfs}
    logger.info(f"PASS: All {len(required_tfs)} timeframes configured")
    
    logger.info("=" * 60)
    logger.info("ALL TESTS PASSED - Coinbase integration verified")
    logger.info("=" * 60)
    
    return {
        "success": True,
        "ticker": {
            "symbol": ticker.symbol,
            "price": ticker.price,
            "volume_24h": ticker.volume_24h,
            "change_24h_pct": ticker.change_24h_pct,
            "high_24h": ticker.high_24h,
            "low_24h": ticker.low_24h,
        },
        "candles": {
            "count": candle_count,
            "timeframe": "1m",
            "latest": {
                "timestamp": sample.timestamp.isoformat() if sample else None,
                "open": sample.open if sample else None,
                "high": sample.high if sample else None,
                "low": sample.low if sample else None,
                "close": sample.close if sample else None,
                "volume": sample.volume if sample else None,
            }
        },
        "orderbook": {
            "bids_count": bid_count,
            "asks_count": ask_count,
            "spread_pct": orderbook.spread_pct if orderbook else None,
        },
        "pairs_configured": feed.coinbase_pairs,
        "timeframes_configured": feed.timeframes,
    }


# ============================================================================
# PRICE SOURCE HEALTH CHECK
# ============================================================================

async def check_price_source_health() -> Dict[str, Any]:
    """
    Health check for all price sources (Coinbase public, Kraken public, CoinGecko).
    
    Fetches prices for all five supported assets (BTC, ETH, SOL, XRP, DOGE) using
    the normal fetch sequence (Coinbase primary, Kraken fallback, CoinGecko last resort).
    
    Returns a structured health report without side effects (does not update cache).
    
    Returns:
        Dict with structure:
        {
            "healthy": bool,  # True if all assets have positive, recent prices
            "timestamp": str,  # ISO format UTC timestamp
            "assets": {
                "BTC/USD": {"price": float, "source": str, "age_seconds": float, "healthy": bool},
                "ETH/USD": {...},
                "SOL/USD": {...},
                "XRP/USD": {...},
                "DOGE/USD": {...},
            },
            "summary": {
                "total_assets": 5,
                "healthy_assets": int,
                "sources_used": List[str],  # Unique sources that provided data
            }
        }
    """
    from dataclasses import asdict
    
    assets = ["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "DOGE/USD"]
    results: Dict[str, Dict[str, Any]] = {}
    sources_used: set = set()
    healthy_count = 0
    
    logger.info("=" * 60)
    logger.info("PRICE SOURCE HEALTH CHECK")
    logger.info("=" * 60)
    
    # Create a temporary feed instance for health check (doesn't affect singleton cache)
    temp_feed = LivePriceFeed()
    
    for symbol in assets:
        asset_result: Dict[str, Any] = {
            "price": None,
            "source": None,
            "age_seconds": None,
            "healthy": False,
            "error": None,
        }
        
        try:
            # Try Coinbase public API first
            price_data = await temp_feed._fetch_from_coinbase_public(symbol)
            if price_data:
                asset_result["price"] = price_data.price
                asset_result["source"] = price_data.exchange
                asset_result["age_seconds"] = 0.0  # Just fetched
                asset_result["healthy"] = price_data.price > 0
                sources_used.add("coinbase_public")
            else:
                # Try Kraken public API
                logger.info(f"  {symbol}: Coinbase failed, trying Kraken...")
                price_data = await temp_feed._fetch_from_kraken_public(symbol)
                if price_data:
                    asset_result["price"] = price_data.price
                    asset_result["source"] = price_data.exchange
                    asset_result["age_seconds"] = 0.0
                    asset_result["healthy"] = price_data.price > 0
                    sources_used.add("kraken_public")
                else:
                    # Last resort: CoinGecko
                    logger.info(f"  {symbol}: Kraken failed, trying CoinGecko...")
                    success = await temp_feed._fetch_from_coingecko(symbol)
                    if success:
                        # Get from cache after coingecko fetch
                        cached = temp_feed.price_cache.get(symbol)
                        if cached:
                            asset_result["price"] = cached.price
                            asset_result["source"] = cached.exchange
                            asset_result["age_seconds"] = 0.0
                            asset_result["healthy"] = cached.price > 0
                            sources_used.add("coingecko")
                    else:
                        asset_result["error"] = "All sources failed"
                        
        except Exception as e:
            asset_result["error"] = str(e)
            logger.error(f"  {symbol}: Health check error: {e}")
        
        if asset_result["healthy"]:
            healthy_count += 1
            
        results[symbol] = asset_result
        
        # Log result
        if asset_result["price"]:
            logger.info(
                f"  {symbol}: ${asset_result['price']:.2f} from {asset_result['source']} "
                f"({'✓ healthy' if asset_result['healthy'] else '✗ invalid'})"
            )
        else:
            logger.error(f"  {symbol}: FAILED - {asset_result['error']}")
    
    overall_healthy = healthy_count == len(assets)
    
    logger.info("-" * 60)
    logger.info(f"SUMMARY: {healthy_count}/{len(assets)} assets healthy")
    logger.info(f"Sources used: {', '.join(sources_used) if sources_used else 'None'}")
    logger.info(f"Overall status: {'✓ HEALTHY' if overall_healthy else '✗ DEGRADED'}")
    logger.info("=" * 60)
    
    return {
        "healthy": overall_healthy,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "assets": results,
        "summary": {
            "total_assets": len(assets),
            "healthy_assets": healthy_count,
            "sources_used": sorted(list(sources_used)),
        }
    }


async def test_public_price_sources() -> Dict[str, Any]:
    """
    Lightweight test helper that pulls prices for all five assets via public APIs.
    
    This is intended for use in tests and validation scripts. It uses the
    normal fetch logic (Coinbase primary, Kraken fallback) and asserts that
    values are positive and recent.
    
    Returns:
        Dict with test results including a simple table of asset prices
    """
    logger.info("\n" + "=" * 60)
    logger.info("PUBLIC PRICE SOURCE TEST")
    logger.info("=" * 60)
    
    health = await check_price_source_health()
    
    # Build simple table for logging
    logger.info("\nPrice Table:")
    logger.info(f"{'Asset':<10} {'Price':>15} {'Source':<15} {'Status':<10}")
    logger.info("-" * 60)
    
    for symbol, data in health["assets"].items():
        asset = symbol.replace("/USD", "")
        price = data.get("price")
        source = data.get("source", "N/A")
        status = "✓" if data.get("healthy") else "✗"
        
        if price:
            logger.info(f"{asset:<10} ${price:>14.2f} {source:<15} {status:<10}")
        else:
            logger.info(f"{asset:<10} {'N/A':>15} {source:<15} {'FAILED':<10}")
    
    logger.info("=" * 60)
    
    return {
        "success": health["healthy"],
        "all_prices_positive": all(
            a.get("price", 0) > 0 for a in health["assets"].values()
        ),
        "all_prices_recent": all(
            a.get("age_seconds", 999) < 60 for a in health["assets"].values()
        ),
        "sources_used": health["summary"]["sources_used"],
        "health_report": health,
    }
