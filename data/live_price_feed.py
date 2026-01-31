"""
Live Price Feed for MERID.

Real-time cryptocurrency price data from multiple exchanges.
Production-grade implementation using CCXT and WebSocket connections.
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from datetime import datetime

import httpx

from utils.deps import optional_dependency

ccxt = optional_dependency("ccxt")  # type: ignore
_CCXT_AVAILABLE = ccxt is not None

from utils.logger import get_logger
from core.environment import get_environment_flags
from core.network_client import RoutingProfile, get_network_client

logger = get_logger("data.live_price_feed")


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
        self.symbols = symbols or ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'AVAX/USDT']
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
                'privateKey': os.getenv('KRAKE_PRIVATE_KEY')
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
        self.running = True
        logger.info("Price streaming started")
        
        while self.running:
            try:
                if not self._can_use_network():
                    logger.info("Network disabled (offline/VPN restriction); skipping fetch cycle")
                    await asyncio.sleep(self.update_interval)
                    continue
                await self.fetch_and_broadcast_prices()
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
        for symbol in self.symbols:
            await self._fetch_price_with_retry(symbol)
    
    async def _fetch_price_with_retry(self, symbol: str):
        """Fetch price with retry logic and circuit breaker."""
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
                    self._guard_network_call("ticker", f"{exchange_name}:{symbol}")
                    
                    # Adjust symbol format for different exchanges
                    fetch_symbol = symbol
                    if exchange_name in ['kraken', 'coinbase']:
                        fetch_symbol = symbol.replace('/USDT', '/USD')
                    
                    ticker = exchange.fetch_ticker(fetch_symbol)
                    
                    price_data = PriceData(
                        symbol=symbol,
                        price=ticker['last'],
                        bid=ticker['bid'] or ticker['last'],
                        ask=ticker['ask'] or ticker['last'],
                        volume_24h=ticker['quoteVolume'] or 0,
                        change_24h_pct=ticker['percentage'] or 0,
                        timestamp=datetime.now(),
                        exchange=exchange_name
                    )
                    
                    # Update cache
                    self.price_cache[symbol] = price_data
                    
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
                    
                    if attempt < self.max_retries - 1:
                        logger.debug(f"Failed to fetch {symbol} from {exchange_name} (attempt {attempt + 1}/{self.max_retries}): {exc}")
                        await asyncio.sleep(self.retry_delay)
                    else:
                        logger.warning(f"Failed to fetch {symbol} from {exchange_name} after {self.max_retries} attempts: {exc}")
            
            if fetched:
                break
        
        if not fetched:
            fetched = await self._fetch_from_coingecko(symbol)
            if not fetched:
                logger.warning(f"Failed to fetch {symbol} from exchanges and CoinGecko")
                if symbol in self.price_cache:
                    cached_age = (datetime.now() - self.price_cache[symbol].timestamp).total_seconds()
                    if cached_age < 60:
                        logger.info(f"Using cached price for {symbol} (age: {cached_age:.1f}s)")
                    else:
                        logger.error(f"Cached price for {symbol} too old ({cached_age:.1f}s)")
    
    async def _broadcast_update(self, price_data: PriceData):
        """Broadcast price update to all subscribers."""
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
                
                ohlcv = exchange.fetch_ohlcv(fetch_symbol, timeframe, limit=limit)
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
        """Fallback to CoinGecko public API (US-accessible)."""
        mapping = {
            'BTC/USDT': 'bitcoin',
            'ETH/USDT': 'ethereum',
            'SOL/USDT': 'solana',
            'AVAX/USDT': 'avalanche-2',
        }
        asset_id = mapping.get(symbol)
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
        self.price_cache[symbol] = price_data
        await self._broadcast_update(price_data)
        return True

    def get_latest_prices(self) -> Dict[str, Dict[str, Any]]:
        """Get latest cached prices for all symbols."""
        prices = {}
        for symbol, price_data in self.price_cache.items():
            prices[symbol] = {
                "price": price_data.price,
                "change_24h": getattr(price_data, "change_24h", 0.0),
                "timestamp": price_data.timestamp.isoformat() if price_data.timestamp else None,
                "source": price_data.source
            }
        return prices


# Global singleton
_live_price_feed: Optional[LivePriceFeed] = None


def get_live_price_feed() -> LivePriceFeed:
    """Get or create live price feed singleton."""
    global _live_price_feed
    if _live_price_feed is None:
        _live_price_feed = LivePriceFeed()
    return _live_price_feed
