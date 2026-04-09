"""
Live Price Feed for MERID.

Real-time cryptocurrency price data from multiple exchanges.
Production-grade implementation using CCXT and WebSocket connections.

INVARIANT (PATCH-1 / EGG-1): For the five Kalshi crypto assets (BTC, ETH,
SOL, XRP, DOGE) the *canonical spot* used for strike-distance checks, risk
sizing, and PnL attribution is always USD-denominated and stored under bare
asset keys ("BTC", not "BTC/USDT").  Kalshi contracts pay 1.00 USD per
contract; mixing USDT prices would introduce silent drift on any USDT depeg.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from utils.deps import optional_dependency

ccxt = optional_dependency("ccxt")  # type: ignore
_CCXT_AVAILABLE = ccxt is not None

from utils.logger import get_logger
from core.environment import get_environment_flags
from core.network_client import RoutingProfile, get_network_client

logger = get_logger("data.live_price_feed")

# ── Kalshi-specific constants ────────────────────────────────────────────
# These are the five assets traded on Kalshi whose spot prices must be in USD.
KALSHI_ASSETS = frozenset({"BTC", "ETH", "SOL", "XRP", "DOGE"})

# USDT depeg guard — env-configurable (PATCH-1 / EGG-1)
_USDT_DEPEG_THRESHOLD_PCT = float(os.getenv("MERID_USDT_DEPEG_THRESHOLD_PCT", "0.50"))
_USDT_DEPEG_BLOCK_TRADES = os.getenv("MERID_USDT_DEPEG_BLOCK_TRADES", "true").lower() != "false"
# Maximum age (seconds) for a Kalshi spot price to be considered fresh
_SPOT_MAX_STALENESS_SECONDS = float(os.getenv("MERID_SPOT_MAX_STALENESS_SECONDS", "60"))

# CoinGecko IDs for all five Kalshi assets (PATCH-8 / EGG-9: adds XRP and DOGE)
_COINGECKO_IDS: Dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "DOGE": "dogecoin",
}


@dataclass
class SpotUSDData:
    """USD-denominated spot price for a single Kalshi asset.

    INVARIANT: ``price_usd`` is always in US dollars, never USDT.
    When the upstream source is USDT-quoted, the conversion factor and
    depeg status are recorded in ``spot_source`` so operators can audit
    any drift against Kalshi's USD-settled contracts.

    Attributes:
        asset:        Bare asset key, e.g. "BTC".
        price_usd:    USD price, or None if unavailable / depegged.
        timestamp:    POSIX epoch seconds when the price was fetched.
        spot_source:  Provenance tag, one of:
                        "coinbase_usd"       – Coinbase BTC/USD direct quote
                        "kraken_usd"         – Kraken BTC/USD direct quote
                        "gemini_usd"         – Gemini BTC/USD direct quote
                        "binance_usdt_normalized" – Binance BTCUSDT × USDT/USD
                        "coingecko_usd"      – CoinGecko public API (fallback)
                        "usdt_depegged"      – Binance only, USDT peg exceeded
                                               threshold; price_usd is None
                        "stale"              – Cached price exceeds staleness
                                               threshold; price_usd is None
    """
    asset: str
    price_usd: Optional[float]
    timestamp: float
    spot_source: str


@dataclass
class PriceData:
    """Price data structure."""
    symbol: str
    price: float
    bid: float
    ask: float
    volume_24h: float
    change_24h_pct: float
    timestamp: datetime
    exchange: str


class LivePriceFeed:
    """
    Production live price feed.
    
    Fetches real-time price data from multiple exchanges using CCXT.
    Supports WebSocket streaming for low-latency updates.
    """
    
    def __init__(self, symbols: List[str] = None):
        """
        Initialize live price feed with enhanced error recovery.
        
        Args:
            symbols: List of symbols to track (e.g., ['BTC/USDT', 'ETH/USDT'])
        """
        self.symbols = symbols or [
            # Major crypto
            'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'AVAX/USDT',
            # Kalshi assets not in major list
            'XRP/USDT',
            # Alt L1/L2
            'ADA/USDT', 'DOT/USDT', 'ATOM/USDT', 'NEAR/USDT',
            'APT/USDT', 'SUI/USDT', 'SEI/USDT',
            'POL/USDT', 'ARB/USDT', 'OP/USDT',
            # DeFi
            'LINK/USDT', 'UNI/USDT', 'AAVE/USDT', 'MKR/USDT',
            'SNX/USDT', 'CRV/USDT', 'LDO/USDT',
            # Memecoins
            'DOGE/USDT', 'SHIB/USDT', 'PEPE/USDT', 'WIF/USDT',
            'BONK/USDT', 'FLOKI/USDT',
            # Infrastructure / Storage
            'FIL/USDT', 'AR/USDT', 'RENDER/USDT',
            # Stablecoins (reference)
            'USDC/USDT',
        ]
        self.exchanges = {}
        self.price_cache: Dict[str, PriceData] = {}
        self.subscribers: List[Callable] = []
        
        self.running = False
        self.update_interval = 1.0  # Update every 1 second
        self.exchange_priority = ['kraken', 'coinbase', 'gemini']  # All accessible from US
        
        # Error recovery parameters
        self.max_retries = 3
        self.retry_delay = 2.0  # seconds
        self.exchange_failures: Dict[str, int] = {}
        self.last_successful_fetch: Dict[str, float] = {}
        self.circuit_breaker_threshold = 10  # failures before circuit break
        self.circuit_breaker_reset_time = 300  # 5 minutes
        self._network_client = get_network_client()
        self._module_name = "data.live_price_feed"
        self._network_client.register_module_profile(self._module_name, RoutingProfile.VPN_A)
        
        # Initialize exchanges
        self._initialize_exchanges()
        
        logger.info(f"Live price feed initialized for {len(self.symbols)} symbols with error recovery")
    
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
            asyncio.get_event_loop().create_task(self._close_exchanges())
        
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
                'apiKey': os.getenv('COINBASE_API_KEY'),
                'secret': os.getenv('COINBASE_API_SECRET')
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
        """Start streaming price updates."""
        if self.running:
            logger.debug("start_streaming() called but already running — skipping")
            return
        self.running = True
        self._cycle_count = 0
        logger.info("Price streaming started for %d symbols across %d exchanges", len(self.symbols), len(self.exchanges))
        
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
    
    def stop_streaming(self):
        """Stop price streaming."""
        self.running = False
        logger.info("Price streaming stopped")
        asyncio.get_event_loop().create_task(self._close_exchanges())

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
        """Fetch price with retry logic and circuit breaker.

        PATCH-1 / EGG-1: For the five Kalshi assets, prices fetched from USD
        exchanges (Kraken, Coinbase, Gemini) are stored under *both* the
        original symbol key and the bare asset key so that get_spot_usd()
        can look them up directly.  For Binance (USDT-denominated), the USDT
        peg is checked before the price is stored; if it depegs by more than
        MERID_USDT_DEPEG_THRESHOLD_PCT the Binance price is discarded.
        """
        fetched = False
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
                    
                    # Adjust symbol format for different exchanges.
                    # USD-native exchanges: rewrite /USDT → /USD
                    fetch_symbol = symbol
                    _is_usd_exchange = exchange_name in ['kraken', 'coinbase', 'gemini']
                    if _is_usd_exchange:
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
                    raw_price = ticker['last']

                    # ── Binance USDT depeg guard (PATCH-1 / EGG-1) ──────────
                    # Binance quotes are USDT-denominated.  Before using the
                    # price we check the USDT/USD peg; if it has moved beyond
                    # the configured threshold the price is unusable for Kalshi.
                    if exchange_name == 'binance' and symbol.endswith('/USDT'):
                        asset_key = symbol.split("/")[0].upper()
                        if asset_key in KALSHI_ASSETS:
                            peg = await self._fetch_usdt_usd_peg(exchange)
                            if peg is None:
                                # Cannot determine peg — skip this price
                                logger.warning(
                                    "binance_depeg_check: unable to fetch USDT/USD peg "
                                    "for %s — skipping price", symbol
                                )
                                break
                            depeg_pct = abs(1.0 - peg) * 100.0
                            if depeg_pct > _USDT_DEPEG_THRESHOLD_PCT:
                                logger.critical(
                                    "USDT DEPEG DETECTED: asset=%s peg=%.6f depeg_pct=%.4f%% "
                                    "threshold=%.2f%% — discarding Binance price for Kalshi path",
                                    asset_key, peg, depeg_pct, _USDT_DEPEG_THRESHOLD_PCT,
                                )
                                # Store sentinel so get_spot_usd() knows price is unavailable
                                self.price_cache[asset_key] = PriceData(
                                    symbol=asset_key,
                                    price=0.0,
                                    bid=0.0,
                                    ask=0.0,
                                    volume_24h=0.0,
                                    change_24h_pct=0.0,
                                    timestamp=datetime.now(),
                                    exchange="usdt_depegged",
                                )
                                break
                            # Peg within threshold — normalise to USD
                            raw_price = raw_price * peg

                    price_data = PriceData(
                        symbol=symbol,
                        price=raw_price,
                        bid=ticker['bid'] or raw_price,
                        ask=ticker['ask'] or raw_price,
                        volume_24h=ticker['quoteVolume'] or 0,
                        change_24h_pct=ticker['percentage'] or 0,
                        timestamp=datetime.now(),
                        exchange=exchange_name
                    )
                    
                    # Update cache under the original symbol key
                    self.price_cache[symbol] = price_data

                    # For Kalshi assets fetched from USD-native exchanges, also
                    # store under the bare asset key with a clear source tag.
                    asset_key = symbol.split("/")[0].upper() if "/" in symbol else symbol.upper()
                    if asset_key in KALSHI_ASSETS and (_is_usd_exchange or
                            (exchange_name == 'binance' and symbol.endswith('/USDT'))):
                        _src = f"{exchange_name}_usd" if _is_usd_exchange else "binance_usdt_normalized"
                        self.price_cache[asset_key] = PriceData(
                            symbol=asset_key,
                            price=raw_price,
                            bid=price_data.bid,
                            ask=price_data.ask,
                            volume_24h=price_data.volume_24h,
                            change_24h_pct=price_data.change_24h_pct,
                            timestamp=price_data.timestamp,
                            exchange=_src,
                        )
                    
                    # Register price assertion with Reality Registry
                    self._register_price_assertion(price_data, exchange_name)
                    
                    # Broadcast to subscribers
                    await self._broadcast_update(price_data)
                    
                    # Reset failure count on success
                    self.exchange_failures[exchange_name] = 0
                    self.last_successful_fetch[exchange_name] = time.time()
                    
                    fetched = True
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
                        # Elevate final failure to WARNING for first exchange in priority list
                        log_level = logger.warning if exchange_name == self.exchange_priority[0] else logger.debug
                        log_level(f"Failed to fetch {symbol} from {exchange_name} after {self.max_retries} attempts: {exc}")
            
            if fetched:
                break
        
        if not fetched:
            fetched = await self._fetch_from_coingecko(symbol)
            if not fetched:
                logger.debug(f"Failed to fetch {symbol} from exchanges and CoinGecko")
                if symbol in self.price_cache:
                    cached_age = (datetime.now() - self.price_cache[symbol].timestamp).total_seconds()
                    if cached_age < 60:
                        logger.info(f"Using cached price for {symbol} (age: {cached_age:.1f}s)")
                    else:
                        logger.error(f"Cached price for {symbol} too old ({cached_age:.1f}s)")
    
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
        """Get current cached price for a symbol."""
        return self.price_cache.get(symbol)
    
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
        
        return {
            "running": self.running,
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

    async def _fetch_from_coingecko(self, symbol: str) -> bool:
        """Fallback to CoinGecko public API (US-accessible).

        PATCH-1 / EGG-9: mapping extended to cover all five Kalshi assets
        (BTC, ETH, SOL, XRP, DOGE) using bare asset keys.  Prices are fetched
        in USD ("vs_currency": "usd") and stored under bare keys so that
        get_spot_usd() finds them directly.
        """
        # Support both bare keys ("BTC") and legacy /USDT keys ("BTC/USDT")
        asset_key = symbol.split("/")[0] if "/" in symbol else symbol.upper()
        asset_id = _COINGECKO_IDS.get(asset_key)
        if not asset_id:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.coingecko.com/api/v3/coins/markets",
                    params={
                        "vs_currency": "usd",
                        "ids": asset_id,
                        "price_change_percentage": "24h",
                    },
                )
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            logger.error(f"CoinGecko fallback failed for {symbol}: {exc}")
            return False
        if not data:
            return False
        market = data[0]
        price = float(market.get("current_price") or 0)
        if price <= 0:
            return False
        timestamp = datetime.utcnow()
        price_data = PriceData(
            symbol=symbol,
            price=price,
            bid=price * 0.999,
            ask=price * 1.001,
            volume_24h=float(market.get("total_volume") or 0),
            change_24h_pct=float(market.get("price_change_percentage_24h") or 0.0),
            timestamp=timestamp,
            exchange="coingecko",
        )
        # Store under both the original symbol key AND the bare asset key so
        # get_spot_usd() finds the price without knowing the /USDT suffix.
        self.price_cache[symbol] = price_data
        if asset_key in KALSHI_ASSETS:
            self.price_cache[asset_key] = PriceData(
                symbol=asset_key,
                price=price,
                bid=price_data.bid,
                ask=price_data.ask,
                volume_24h=price_data.volume_24h,
                change_24h_pct=price_data.change_24h_pct,
                timestamp=timestamp,
                exchange="coingecko_usd",
            )
        await self._broadcast_update(price_data)
        return True

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

    # ── Kalshi USD spot accessor ──────────────────────────────────────────

    def get_spot_usd(self, asset: str) -> Optional[SpotUSDData]:
        """Return the canonical USD spot price for a Kalshi asset.

        INVARIANT (PATCH-1 / EGG-1): The returned ``SpotUSDData.price_usd``
        is always denominated in US dollars, never USDT.  Callers in the
        Kalshi trading path MUST use this accessor instead of
        ``get_price("BTC/USDT")``.

        Staleness is checked against ``MERID_SPOT_MAX_STALENESS_SECONDS``
        (default 60 s).  Stale prices return ``price_usd=None`` and
        ``spot_source="stale"``.

        If the cached entry was produced by the Binance depeg sentinel
        (``exchange=="usdt_depegged"``) the method returns
        ``price_usd=None, spot_source="usdt_depegged"``.

        Args:
            asset: Bare asset key, e.g. "BTC".  Case-insensitive.

        Returns:
            SpotUSDData or None if no data has ever been fetched.
        """
        asset_up = asset.upper()
        cached = self.price_cache.get(asset_up)
        if cached is None:
            return None

        # Depeg sentinel — price is unusable
        if cached.exchange == "usdt_depegged":
            return SpotUSDData(
                asset=asset_up,
                price_usd=None,
                timestamp=cached.timestamp.timestamp(),
                spot_source="usdt_depegged",
            )

        # Use timezone-aware now() when comparing with potentially tz-aware timestamps.
        # Fall back to naive comparison if timestamp is naive (legacy path).
        _now = datetime.now(timezone.utc)
        try:
            if cached.timestamp.tzinfo is not None:
                _ts_aware = cached.timestamp
            else:
                # Naive timestamp — assume UTC (legacy path from exchanges that
                # don't attach tzinfo), attach UTC so comparison works correctly
                _ts_aware = cached.timestamp.replace(tzinfo=timezone.utc)
            age_s = (_now - _ts_aware).total_seconds()
        except Exception:
            # Safety fallback: treat price as stale if we can't compute age
            age_s = _SPOT_MAX_STALENESS_SECONDS + 1
        if age_s > _SPOT_MAX_STALENESS_SECONDS:
            logger.warning(
                "get_spot_usd: %s price is stale (age=%.1fs > %.0fs threshold)",
                asset_up, age_s, _SPOT_MAX_STALENESS_SECONDS,
            )
            return SpotUSDData(
                asset=asset_up,
                price_usd=None,
                timestamp=cached.timestamp.timestamp(),
                spot_source="stale",
            )

        return SpotUSDData(
            asset=asset_up,
            price_usd=cached.price if cached.price > 0 else None,
            timestamp=cached.timestamp.timestamp(),
            spot_source=cached.exchange,
        )

    def get_price(self, symbol: str) -> Optional[PriceData]:
        """Alias for older callers expecting get_price.

        .. deprecated::
            For the Kalshi trading path (BTC/ETH/SOL/XRP/DOGE), use
            :meth:`get_spot_usd` instead.  This shim still works but logs a
            deprecation warning when the caller passes a bare Kalshi asset key
            without a /USDT suffix, which is the new convention.
        """
        # Detect callers that have been migrated to bare keys
        asset_up = symbol.upper()
        if asset_up in KALSHI_ASSETS:
            logger.warning(
                "get_price('%s'): DEPRECATED for Kalshi path — use get_spot_usd('%s') instead",
                symbol, asset_up,
            )
            return self.get_current_price(asset_up)
        return self.get_current_price(symbol)

    async def _fetch_usdt_usd_peg(self, exchange) -> Optional[float]:
        """Fetch the USDT/USD exchange rate from a Binance exchange instance.

        PATCH-1 / EGG-1: Used to normalise Binance USDT prices to USD before
        storing them in the Kalshi spot cache.  Returns None on failure.
        """
        try:
            # Try USDT/USD directly
            for pair in ("USDT/USD", "USDC/USDT"):
                try:
                    ticker = await asyncio.to_thread(exchange.fetch_ticker, pair)
                    price = ticker.get("last")
                    if price and price > 0:
                        # USDC/USDT gives the inverse rate
                        return float(price) if pair == "USDT/USD" else 1.0 / float(price)
                except Exception:
                    continue
            return None
        except Exception as exc:
            logger.debug("_fetch_usdt_usd_peg failed: %s", exc)
            return None


# Global singleton
_live_price_feed: Optional[LivePriceFeed] = None


def get_live_price_feed() -> LivePriceFeed:
    """Get or create live price feed singleton."""
    global _live_price_feed
    if _live_price_feed is None:
        _live_price_feed = LivePriceFeed()
    return _live_price_feed
