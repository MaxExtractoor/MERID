"""Unified Crypto Spot Price Service for MERID.

DEPRECATED: Use data.unified_spot_service.UnifiedSpotService instead.

This module is kept for:
1. Shadow mode comparison in UnifiedSpotService
2. Legacy consumers (KalshiContinuousTrader, crypto_venue_bridge, risk_posture)
3. Test compatibility

Provides multi-asset spot price fetching with the following priority (aligned with Kalshi's CFB RTI):
1. Coinbase (primary) - USD spot pairs: BTC-USD, ETH-USD, SOL-USD, XRP-USD, DOGE-USD
2. Kraken (secondary) - USD spot pairs: XBT/USD, ETH/USD, SOL/USD, XRP/USD, DOGE/USD
3. BinanceUS (tertiary) - USD pairs: BTC/USD, ETH/USD, SOL/USD, XRP/USD, DOGE/USD

This aligns with Kalshi's methodology which aggregates exchange prices in USD every second
and uses a 60-second average before expiration to settle markets.

Features:
- Rate limit aware with token bucket per source
- TTL caching with stale-while-revalidate pattern
- Source tracking for observability
- Synchronous API (for use in CT run_in_executor contexts)
- USD-only hard filter (rejects USDT, USDC, cross-crypto pairs)
- Time-aligned composite price aggregation (median across available USD feeds)
- 60-second averaging window to match Kalshi's CFB RTI

Env vars:
    SPOT_SERVICE_CACHE_TTL_SECONDS: int (default: 10)
    SPOT_SERVICE_STALE_TTL_SECONDS: int (default: 30)
    MERID_SPOT_STALE_MS: float (default: 5000) - milliseconds before spot is stale
    MERID_SPOT_MISSING_MS: float (default: 30000) - milliseconds before spot is missing
    MERID_KALSHI_COMPOSITE_WINDOW_S: int (default: 5) - composite window for Kalshi 15m contracts
"""

from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import json
import time
import os

import httpx
import requests

from utils.logger import get_logger

logger = get_logger("merid.trading.crypto_spot_service")

# Asset to symbol mappings (USD-only, aligned with Kalshi's CFB RTI methodology)
ASSET_TO_COINBASE_PRODUCT = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
    "XRP": "XRP-USD",
    "DOGE": "DOGE-USD",
}

ASSET_TO_KRAKEN_PAIR = {
    "BTC": "XBTUSD",  # Kraken uses XBT for Bitcoin
    "ETH": "ETHUSD",
    "SOL": "SOLUSD",
    "XRP": "XRPUSD",
    "DOGE": "DOGEUSD",
}

ASSET_TO_BINANCEUS_SYMBOL = {
    "BTC": "BTCUSD",
    "ETH": "ETHUSD",
    "SOL": "SOLUSD",
    "XRP": "XRPUSD",
    "DOGE": "DOGEUSD",
}

_SPOT_VENUE_ERROR_STREAK_MAX: int = int(os.getenv("SPOT_VENUE_ERROR_STREAK_MAX", "5"))


@dataclass
class SpotPrice:
    """Spot price result with metadata."""
    asset: str
    price: float
    source: str  # 'coinbase', 'kraken', 'binanceus', 'cache', 'composite', 'single_venue:{source}'
    timestamp: float
    age_seconds: float = field(default=0.0)
    is_stale: bool = field(default=False)
    is_composite: bool = field(default=False)  # True if price is a 60-second median composite


@dataclass
class SpotServiceResult:
    """Result from fetching multiple spot prices."""
    prices: Dict[str, SpotPrice]
    failed: List[str]  # Assets that couldn't be fetched
    by_source: Dict[str, List[str]]  # Asset -> source mapping summary
    cache_hits: int
    live_fetches: int
    total_time_ms: float
    # Per-venue error streaks (see CryptoSpotService.venue_health_snapshot)
    venue_health: Dict[str, str] = field(default_factory=dict)
    spot_feed_degraded: bool = False


class TokenBucket:
    """Simple token bucket rate limiter."""
    
    def __init__(self, rate_per_second: float, burst: int = 1):
        self.rate = rate_per_second
        self.burst = burst
        self.tokens = burst
        self.last_update = time.time()
        self._lock = None  # Will use threading.Lock if needed
    
    def _get_lock(self):
        if self._lock is None:
            import threading
            self._lock = threading.Lock()
        return self._lock
    
    def acquire(self, tokens: int = 1, timeout: float = 5.0) -> bool:
        """Try to acquire tokens. Returns True if acquired."""
        with self._get_lock():
            now = time.time()
            elapsed = now - self.last_update
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_update = now
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            
            # Calculate wait time
            needed = tokens - self.tokens
            wait_time = needed / self.rate
            if wait_time > timeout:
                return False
        
        # Wait outside lock
        time.sleep(wait_time)
        return self.acquire(tokens, timeout=0)


class _CacheEntry:
    """Internal cache entry."""
    def __init__(self, price: float, source: str, timestamp: float):
        self.price = price
        self.source = source
        self.timestamp = timestamp
        self.access_count = 0


class CryptoSpotService:
    """Unified spot price service with tiered fallback.
    
    Usage:
        service = CryptoSpotService()
        result = service.get_all_spots(["BTC", "ETH", "SOL", "XRP", "DOGE"])
        
        for asset, spot in result.prices.items():
            print(f"{asset}: ${spot.price:.2f} from {spot.source}")
    """
    
    def __init__(
        self,
        cache_ttl_seconds: Optional[int] = None,
        stale_ttl_seconds: Optional[int] = None,
    ):
        self.cache_ttl = cache_ttl_seconds or int(os.getenv("SPOT_SERVICE_CACHE_TTL_SECONDS", "10"))
        # FIX: Use unified staleness threshold from environment variable
        # Matches spot_basis_config.py and live_price_feed.py for consistency
        spot_missing_ms = float(os.getenv("MERID_SPOT_MISSING_MS", "30000"))
        self.stale_ttl = stale_ttl_seconds or int(spot_missing_ms / 1000.0)  # Convert ms to seconds
        
        # Cache: asset -> _CacheEntry
        self._cache: Dict[str, _CacheEntry] = {}
        self._cache_lock = None  # Lazy init
        
        # FIX: Kalshi-specific composite window for 15m contracts
        # General: 60-second rolling window (matches Kalshi CFB RTI)
        # Kalshi: 5-second rolling window for near-real-time 15m settlement
        self._kalshi_window_seconds = float(os.getenv("MERID_KALSHI_COMPOSITE_WINDOW_S", "5"))
        self._price_window: Dict[str, List[Tuple[float, float, str]]] = {}  # asset -> [(timestamp, price, source), ...]
        self._window_lock = None  # Lazy init
        self._window_seconds = 60.0  # Default for general trading
        self._max_window_points = 600  # Hard cap to avoid unbounded growth at high tick rates
        
        # Rate limiters per source (aligned with Kalshi's CFB RTI methodology)
        # Coinbase: 10 requests per second (generous for 5 assets)
        self._coinbase_limiter = TokenBucket(rate_per_second=10.0, burst=5)
        # Kraken: 15 requests per second
        self._kraken_limiter = TokenBucket(rate_per_second=15.0, burst=10)
        # BinanceUS: 20 requests per second
        self._binanceus_limiter = TokenBucket(rate_per_second=20.0, burst=10)
        
        # HTTP clients (lazy init)
        self._http_client: Optional[httpx.Client] = None
        
        # Upstream failure metrics for observability
        self._failure_metrics: Dict[str, Dict[str, int]] = {
            "coinbase": {"429": 0, "timeout": 0, "http_error": 0, "other": 0, "stale": 0},
            "kraken": {"429": 0, "timeout": 0, "http_error": 0, "other": 0},
            "binanceus": {"429": 0, "timeout": 0, "http_error": 0, "other": 0},
        }
        self._venue_error_streak: Dict[str, int] = {
            "coinbase": 0,
            "kraken": 0,
            "binanceus": 0,
        }

        logger.info(
            "CryptoSpotService initialized: cache_ttl=%ds, stale_ttl=%ds",
            self.cache_ttl, self.stale_ttl
        )
    
    def _get_cache_lock(self):
        if self._cache_lock is None:
            import threading
            self._cache_lock = threading.Lock()
        return self._cache_lock
    
    def _get_window_lock(self):
        if self._window_lock is None:
            import threading
            self._window_lock = threading.Lock()
        return self._window_lock
    
    def _add_to_price_window(
        self,
        asset: str,
        price: float,
        timestamp: float,
        source: Optional[str] = None,
    ) -> None:
        """Add a price point to the 60-second rolling window for composite aggregation.

        Args:
            asset: Asset symbol
            price: Price value
            timestamp: Unix timestamp
            source: Exchange source (coinbase, kraken, binanceus) for debugging
        """
        with self._get_window_lock():
            if asset not in self._price_window:
                self._price_window[asset] = []

            # Add new price point with source
            self._price_window[asset].append((timestamp, price, source))

            # Prune old entries outside the 60-second window (time-based)
            cutoff = timestamp - self._window_seconds
            self._price_window[asset] = [
                (ts, p, s) for ts, p, s in self._price_window[asset] if ts > cutoff
            ]

            # Hard cap to avoid pathological growth at high tick rates
            if len(self._price_window[asset]) > self._max_window_points:
                self._price_window[asset] = self._price_window[asset][-self._max_window_points:]
    
    def _get_composite_price(
        self,
        asset: str,
        min_samples: int = 2,
        max_staleness_seconds: float = 15.0,
    ) -> Optional[Tuple[float, str]]:
        """Calculate composite price from the 60-second rolling window.

        Uses median of all prices in the window to align with Kalshi's CFB RTI methodology
        which aggregates exchange prices in USD every second and uses a 60-second average
        before expiration to settle markets.

        Args:
            asset: Asset symbol
            min_samples: Minimum number of price points required to compute composite
            max_staleness_seconds: Maximum age of latest point to consider composite valid

        Returns:
            Tuple of (median_price, source_tag) or None if insufficient data or too stale
            source_tag indicates "composite", "single_venue:{source}", or "stale"
        """
        with self._get_window_lock():
            if asset not in self._price_window or not self._price_window[asset]:
                return None

            if len(self._price_window[asset]) < min_samples:
                return None

            now = time.time()
            latest_timestamp = self._price_window[asset][-1][0]
            latest_age = now - latest_timestamp

            # Age-aware guard: reject composite if latest point is too stale
            if latest_age > max_staleness_seconds:
                logger.debug(
                    "[SPOT-COMPOSITE] Composite for %s rejected: latest point %.1fs old (max %.1fs)",
                    asset, latest_age, max_staleness_seconds
                )
                return None

            prices = [p for _, p, _ in self._price_window[asset]]
            sources = [s for _, _, s in self._price_window[asset] if s]

            if not prices:
                return None

            # Calculate median (time-aligned composite)
            prices.sort()
            n = len(prices)
            if n % 2 == 0:
                median = (prices[n // 2 - 1] + prices[n // 2]) / 2
            else:
                median = prices[n // 2]

            # Detect single-venue composite for drift detection
            unique_sources = set(s for s in sources if s)
            if len(unique_sources) == 1:
                source_tag = f"single_venue:{unique_sources.pop()}"
                logger.debug(
                    "[SPOT-COMPOSITE] Single-venue composite for %s: %s (considered degraded)",
                    asset, source_tag
                )
            else:
                source_tag = "composite"

            return median, source_tag
    
    def _get_http_client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=10.0, follow_redirects=True)
        return self._http_client
    
    def close(self) -> None:
        """Close the HTTP client to free resources. Call on shutdown."""
        if self._http_client is not None:
            try:
                self._http_client.close()
                self._http_client = None
                logger.info("CryptoSpotService: HTTP client closed")
            except Exception as e:
                logger.warning("CryptoSpotService: error closing HTTP client: %s", e)
    
    def __del__(self) -> None:
        """Cleanup on garbage collection (fallback if close() not called)."""
        self.close()

    def _bump_venue_error(self, venue: str) -> None:
        self._venue_error_streak[venue] = min(
            self._venue_error_streak.get(venue, 0) + 1,
            _SPOT_VENUE_ERROR_STREAK_MAX + 10,
        )

    def _clear_venue_error(self, venue: str) -> None:
        if venue in self._venue_error_streak:
            self._venue_error_streak[venue] = 0

    def venue_health_snapshot(self) -> Dict[str, str]:
        """ok | warn | degraded based on consecutive failures per venue."""
        out: Dict[str, str] = {}
        for v, streak in self._venue_error_streak.items():
            if streak >= _SPOT_VENUE_ERROR_STREAK_MAX:
                out[v] = "degraded"
            elif streak > 0:
                out[v] = "warn"
            else:
                out[v] = "ok"
        return out

    def spot_feed_globally_degraded(self) -> bool:
        """True when every tracked venue has hit the degrade streak (rare)."""
        if not self._venue_error_streak:
            return False
        return all(
            self._venue_error_streak.get(v, 0) >= _SPOT_VENUE_ERROR_STREAK_MAX
            for v in self._venue_error_streak
        )
    
    def _get_from_cache(self, asset: str) -> Optional[_CacheEntry]:
        """Get cache entry if valid."""
        with self._get_cache_lock():
            entry = self._cache.get(asset.upper())
            if entry is None:
                return None
            
            age = time.time() - entry.timestamp
            if age > self.stale_ttl:
                # Too stale, remove
                del self._cache[asset.upper()]
                return None
            
            entry.access_count += 1
            return entry
    
    def _set_cache(self, asset: str, price: float, source: str) -> None:
        """Store price in cache."""
        with self._get_cache_lock():
            self._cache[asset.upper()] = _CacheEntry(
                price=price,
                source=source,
                timestamp=time.time()
            )
    
    def _try_coinbase(self, asset: str) -> Optional[float]:
        """Try to fetch spot price from Coinbase.

        Uses the **public v2 spot price endpoint** which requires no authentication:
            GET https://api.coinbase.com/v2/prices/{pair}/spot

        The previous v3 brokerage endpoint (/api/v3/brokerage/products/) returned
        401 because it requires CDP JWT auth with an EC private key, but the
        configured credentials are legacy v2 API key/secret.
        """
        product = ASSET_TO_COINBASE_PRODUCT.get(asset.upper())
        if not product:
            logger.warning("Coinbase: no product mapping for asset %s", asset)
            return None

        if not self._coinbase_limiter.acquire(timeout=2.0):
            logger.warning("Coinbase rate limit exceeded for %s", asset)
            return None

        # --- Attempt 1: Coinbase v2 public spot price (no auth) ---
        try:
            url = f"https://api.coinbase.com/v2/prices/{product}/spot"
            logger.debug("Coinbase v2 request: GET %s", url)
            resp = requests.get(url, timeout=8)
            resp.raise_for_status()
            data = resp.json()
            amount = data.get("data", {}).get("amount")
            if amount:
                price = float(amount)
                # Extract timestamp from API response for staleness validation
                # Coinbase v2 returns timestamp in "data.base" or "data.timestamp" fields
                api_timestamp = data.get("data", {}).get("timestamp")
                if api_timestamp:
                    try:
                        # Coinbase v2 timestamp is in ISO 8601 format
                        from datetime import datetime
                        ts = datetime.fromisoformat(api_timestamp.replace('Z', '+00:00'))
                        api_ts = ts.timestamp()
                        age_seconds = time.time() - api_ts
                        if age_seconds > 30.0:
                            logger.warning(
                                "Coinbase v2 stale price for %s: %.2f (age=%.1fs > 30s threshold)",
                                asset, price, age_seconds
                            )
                            self._failure_metrics["coinbase"]["stale"] += 1
                            # Reject stale data
                            return None
                        logger.debug("Coinbase v2 success: %s = %.8f (age=%.1fs)", asset, price, age_seconds)
                    except (ValueError, TypeError) as e:
                        logger.debug("Coinbase v2 timestamp parse failed for %s: %s", asset, e)
                        # If timestamp parsing fails, accept price but log warning
                        logger.debug("Coinbase v2 success: %s = %.8f (timestamp unavailable)", asset, price)
                else:
                    logger.debug("Coinbase v2 success: %s = %.8f (no timestamp in response)", asset, price)
                self._clear_venue_error("coinbase")
                return price
            else:
                logger.warning("Coinbase v2: no amount field in response for %s", asset)
        except requests.exceptions.HTTPError as e:
            status = getattr(resp, "status_code", "?")
            logger.warning("Coinbase v2 HTTP error for %s: %s (status=%s)", asset, e, status)
            self._failure_metrics["coinbase"]["http_error"] += 1
        except requests.exceptions.Timeout:
            logger.warning("Coinbase v2 timeout for %s", asset)
            self._failure_metrics["coinbase"]["timeout"] += 1
        except Exception as e:
            logger.debug("Coinbase v2 fetch failed for %s: %s", asset, e)
            self._failure_metrics["coinbase"]["other"] += 1

        # --- Attempt 2: Coinbase Exchange public ticker (no auth) ---
        try:
            url = f"https://api.exchange.coinbase.com/products/{product}/ticker"
            logger.debug("Coinbase Exchange request: GET %s", url)
            resp = requests.get(url, timeout=8, headers={"Accept": "application/json"})
            resp.raise_for_status()
            data = resp.json()
            price_str = data.get("price")
            if price_str:
                price = float(price_str)
                # Extract timestamp from API response for staleness validation
                # Coinbase Exchange returns timestamp in "time" field (Unix ms)
                api_time = data.get("time")
                if api_time:
                    try:
                        # Coinbase Exchange timestamp is in milliseconds
                        api_ts = float(api_time) / 1000.0
                        age_seconds = time.time() - api_ts
                        if age_seconds > 30.0:
                            logger.warning(
                                "Coinbase Exchange stale price for %s: %.2f (age=%.1fs > 30s threshold)",
                                asset, price, age_seconds
                            )
                            self._failure_metrics["coinbase"]["stale"] += 1
                            # Reject stale data
                            return None
                        logger.debug("Coinbase Exchange success: %s = %.8f (age=%.1fs)", asset, price, age_seconds)
                    except (ValueError, TypeError) as e:
                        logger.debug("Coinbase Exchange timestamp parse failed for %s: %s", asset, e)
                        # If timestamp parsing fails, accept price but log warning
                        logger.debug("Coinbase Exchange success: %s = %.8f (timestamp unavailable)", asset, price)
                else:
                    logger.debug("Coinbase Exchange success: %s = %.8f (no timestamp in response)", asset, price)
                self._clear_venue_error("coinbase")
                return price
        except Exception as e:
            logger.debug("Coinbase Exchange fallback failed for %s: %s", asset, e)

        self._bump_venue_error("coinbase")
        return None

    def _try_kraken(self, asset: str) -> Optional[float]:
        """Try to fetch spot price from Kraken.

        Uses the public Ticker endpoint which requires no authentication:
            GET https://api.kraken.com/0/public/Ticker?pair=XBTUSD

        Kraken uses XBT for Bitcoin in API responses.
        """
        pair = ASSET_TO_KRAKEN_PAIR.get(asset.upper())
        if not pair:
            logger.warning("Kraken: no pair mapping for asset %s", asset)
            return None

        if not self._kraken_limiter.acquire(timeout=2.0):
            logger.warning("Kraken rate limit exceeded for %s", asset)
            return None

        try:
            url = "https://api.kraken.com/0/public/Ticker"
            params = {"pair": pair}
            logger.debug("Kraken request: GET %s with params %s", url, params)
            resp = requests.get(url, params=params, timeout=8)
            resp.raise_for_status()
            data = resp.json()
            
            # Kraken returns data in a nested structure: {"result": {"XXBTZUSD": {"c": ["PRICE", ...]}}}
            if data.get("error"):
                logger.warning("Kraken API error for %s: %s", asset, data.get("error"))
                self._bump_venue_error("kraken")
                return None
            
            result = data.get("result", {})
            if not result:
                logger.warning("Kraken: no result data for %s", asset)
                self._bump_venue_error("kraken")
                return None
            
            # Get the first (and only) key in the result
            if result and result.keys():
                ticker_key = list(result.keys())[0]
            else:
                logger.warning("Kraken: empty result keys for %s", asset)
                self._bump_venue_error("kraken")
                return None
            ticker_data = result[ticker_key]
            
            # 'c' is the last trade closed array: [price, volume]
            c_array = ticker_data.get("c", [])
            if c_array:
                price_str = c_array[0]
            else:
                logger.warning("Kraken: no price array in response for %s", asset)
                self._bump_venue_error("kraken")
                return None
            if price_str:
                price = float(price_str)
                logger.debug("Kraken success: %s = %.2f", asset, price)
                self._clear_venue_error("kraken")
                return price
            else:
                logger.warning("Kraken: no price field in response for %s", asset)
                self._bump_venue_error("kraken")
                return None
                
        except requests.exceptions.HTTPError as e:
            status = getattr(resp, "status_code", "?")
            logger.warning("Kraken HTTP error for %s: %s (status=%s)", asset, e, status)
            self._failure_metrics["kraken"]["http_error"] += 1
            self._bump_venue_error("kraken")
        except requests.exceptions.Timeout:
            logger.warning("Kraken timeout for %s", asset)
            self._failure_metrics["kraken"]["timeout"] += 1
            self._bump_venue_error("kraken")
        except Exception as e:
            logger.debug("Kraken fetch failed for %s: %s", asset, e)
            self._failure_metrics["kraken"]["other"] += 1
            self._bump_venue_error("kraken")
        
        return None

    def _try_binanceus_one_by_one(
        self, symbols: List[str], symbol_to_asset: Dict[str, str]
    ) -> Dict[str, float]:
        """Fallback when batch `symbols` JSON is rejected (400) by Binance.US."""
        results: Dict[str, float] = {}
        url = "https://api.binance.us/api/v3/ticker/price"
        for sym in symbols:
            try:
                resp = requests.get(url, params={"symbol": sym}, timeout=8)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict) and "price" in data:
                    asset = symbol_to_asset.get(sym.upper())
                    if asset:
                        results[asset] = float(data["price"])
            except requests.exceptions.HTTPError as e:
                logger.debug("BinanceUS single-symbol %s: %s", sym, e)
            except Exception as e:
                logger.debug("BinanceUS single-symbol %s failed: %s", sym, e)
        if results:
            self._clear_venue_error("binanceus")
        return results
    
    def _try_binanceus_batch(self, assets: List[str]) -> Dict[str, float]:
        """Try to fetch spot prices from Binance.US for multiple assets.
        
        Uses the /api/v3/ticker/price endpoint which supports multiple symbols.
        """
        if not assets:
            return {}
        
        if not self._binanceus_limiter.acquire(timeout=3.0):
            logger.warning("BinanceUS rate limit exceeded")
            return {}
        
        # Map assets to symbols
        symbols = []
        symbol_to_asset = {}
        for asset in assets:
            symbol = ASSET_TO_BINANCEUS_SYMBOL.get(asset.upper())
            if symbol:
                symbols.append(symbol)
                symbol_to_asset[symbol] = asset.upper()
        
        if not symbols:
            return {}
        
        results = {}
        try:
            # BinanceUS expects symbols as JSON array string: ["BTCUSD","ETHUSD"]
            symbols_param = json.dumps(symbols) if len(symbols) > 1 else symbols[0]
            url = "https://api.binance.us/api/v3/ticker/price"
            params = {"symbols": symbols_param} if len(symbols) > 1 else {"symbol": symbols[0]}
            
            logger.debug("BinanceUS request: GET %s with params %s", url, params)
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 400 and len(symbols) > 1:
                logger.warning(
                    "BinanceUS rejected batch ticker request (400); retrying per symbol"
                )
                return self._try_binanceus_one_by_one(symbols, symbol_to_asset)
            resp.raise_for_status()
            data = resp.json()
            
            # Handle both single and batch responses
            if isinstance(data, list):
                for item in data:
                    symbol = item.get("symbol", "").upper()
                    asset = symbol_to_asset.get(symbol)
                    if asset and "price" in item:
                        results[asset] = float(item["price"])
                        logger.debug("BinanceUS success: %s = %.2f", asset, results[asset])
            elif isinstance(data, dict) and "price" in data:
                symbol = data.get("symbol", "").upper()
                asset = symbol_to_asset.get(symbol)
                if asset:
                    results[asset] = float(data["price"])
                    logger.debug("BinanceUS success: %s = %.2f", asset, results[asset])
            
            # Log any assets that weren't returned
            missing = set(symbols) - {data.get("symbol", "").upper() if isinstance(data, dict) else 
                       item.get("symbol", "").upper() for item in (data if isinstance(data, list) else [data])}
            if missing:
                logger.warning("BinanceUS: symbols not returned: %s", missing)
            if results:
                self._clear_venue_error("binanceus")
                    
        except requests.exceptions.HTTPError as e:
            logger.warning("BinanceUS HTTP error: %s (status=%s)", e, resp.status_code)
            self._failure_metrics["binanceus"]["http_error"] += 1
            self._bump_venue_error("binanceus")
        except requests.exceptions.Timeout:
            logger.warning("BinanceUS timeout")
            self._failure_metrics["binanceus"]["timeout"] += 1
            self._bump_venue_error("binanceus")
        except Exception as e:
            logger.debug("BinanceUS batch fetch failed: %s", e)
            self._failure_metrics["binanceus"]["other"] += 1
            self._bump_venue_error("binanceus")
        
        return results
    
    def get_spot(self, asset: str, use_cache: bool = True) -> Optional[SpotPrice]:
        """Get spot price for a single asset.

        Returned price is a 60-second median composite across available USD sources
        when sufficient data is present (≥2 points in window); otherwise, the latest
        primary source quote is used. This aligns with Kalshi's CFB RTI methodology
        which aggregates exchange prices in USD every second and uses a 60-second
        average before expiration to settle markets.

        Priority order (aligned with Kalshi's CFB RTI):
        1. Coinbase (primary) - USD spot
        2. Kraken (secondary) - USD spot
        3. BinanceUS (tertiary) - USD pairs

        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            use_cache: Whether to check cache first

        Returns:
            SpotPrice or None if all sources failed
        """
        asset = asset.upper()
        now = time.time()

        # Check cache first
        if use_cache:
            cached = self._get_from_cache(asset)
            if cached:
                age = now - cached.timestamp
                return SpotPrice(
                    asset=asset,
                    price=cached.price,
                    source=f"{cached.source}_cache",
                    timestamp=cached.timestamp,
                    age_seconds=age,
                    is_stale=age > self.cache_ttl
                )

        # Try sources in priority order (Coinbase > Kraken > BinanceUS)
        # 1. Coinbase
        price = self._try_coinbase(asset)
        if price is not None:
            self._add_to_price_window(asset, price, now, "coinbase")
            composite = self._get_composite_price(asset, min_samples=2)
            final_price = composite[0] if composite else price
            source_tag = composite[1] if composite else "coinbase"
            is_composite = composite is not None

            self._set_cache(asset, final_price, source_tag)
            return SpotPrice(
                asset=asset,
                price=final_price,
                source=source_tag,
                timestamp=now,
                is_composite=is_composite
            )

        # 2. Kraken
        price = self._try_kraken(asset)
        if price is not None:
            self._add_to_price_window(asset, price, now, "kraken")
            composite = self._get_composite_price(asset, min_samples=2)
            final_price = composite[0] if composite else price
            source_tag = composite[1] if composite else "kraken"
            is_composite = composite is not None

            self._set_cache(asset, final_price, source_tag)
            return SpotPrice(
                asset=asset,
                price=final_price,
                source=source_tag,
                timestamp=now,
                is_composite=is_composite
            )

        # 3. BinanceUS (single asset as batch of 1)
        results = self._try_binanceus_batch([asset])
        if asset in results:
            self._add_to_price_window(asset, results[asset], now, "binanceus")
            composite = self._get_composite_price(asset, min_samples=2)
            final_price = composite[0] if composite else results[asset]
            source_tag = composite[1] if composite else "binanceus"
            is_composite = composite is not None

            self._set_cache(asset, final_price, source_tag)
            return SpotPrice(
                asset=asset,
                price=final_price,
                source=source_tag,
                timestamp=now,
                is_composite=is_composite
            )

        return None
    
    def get_all_spots(
        self,
        assets: List[str],
        use_cache: bool = True
    ) -> SpotServiceResult:
        """Get spot prices for multiple assets with efficient batching.

        Returned prices are 60-second median composites across available USD sources
        when sufficient data is present (≥2 points in window); otherwise, the latest
        primary source quote is used. This aligns with Kalshi's CFB RTI methodology
        which aggregates exchange prices in USD every second and uses a 60-second
        average before expiration to settle markets.

        Returns partial results: assets with successful fetches are in `prices`,
        failed assets are in `failed`. Callers MUST check `asset not in result.failed`
        or use `.get()` before accessing prices. Missing key ⇒ price unavailable.

        Strategy (aligned with Kalshi's CFB RTI):
        1. Check cache for all assets
        2. Try Coinbase for remaining (primary - USD spot)
        3. Try Kraken for remaining (secondary - USD spot)
        4. Batch remaining through BinanceUS (tertiary - USD pairs)
        5. Return stale cache entries if live sources fail

        Args:
            assets: List of asset symbols (e.g., ["BTC", "ETH"])
            use_cache: Whether to use cached prices

        Returns:
            SpotServiceResult with:
            - prices: Dict[str, SpotPrice] - only successful fetches
            - failed: List[str] - assets that couldn't be fetched (any reason)
            - by_source: breakdown of which source served each asset

        Example:
            result = service.get_all_spots(["BTC", "ETH"])
            for asset in ["BTC", "ETH"]:
                if asset in result.failed:
                    continue  # Skip this asset
                spot = result.prices[asset]  # Safe to access
        """
        t0 = time.perf_counter()
        assets = [a.upper() for a in assets]
        
        # Defensive: filter to only known assets (BTC, ETH, SOL, XRP, DOGE)
        known_assets = set(ASSET_TO_COINBASE_PRODUCT.keys())
        unknown_assets = [a for a in assets if a not in known_assets]
        if unknown_assets:
            logger.warning(
                "CryptoSpotService: ignoring unknown assets %s (only %s supported)",
                unknown_assets, sorted(known_assets)
            )
        assets = [a for a in assets if a in known_assets]
        
        now = time.time()
        
        results: Dict[str, SpotPrice] = {}
        failed: List[str] = []
        by_source: Dict[str, List[str]] = {"coinbase": [], "kraken": [], "binanceus": [], "composite": [], "cache": [], "stale_cache": []}
        cache_hits = 0
        live_fetches = 0
        
        # Track which assets still need fetching
        needed = set(assets)
        
        # Step 1: Check cache
        if use_cache:
            for asset in list(needed):
                cached = self._get_from_cache(asset)
                if cached:
                    age = now - cached.timestamp
                    is_stale = age > self.cache_ttl
                    
                    results[asset] = SpotPrice(
                        asset=asset,
                        price=cached.price,
                        source=f"{cached.source}_cache",
                        timestamp=cached.timestamp,
                        age_seconds=age,
                        is_stale=is_stale
                    )
                    
                    if is_stale:
                        by_source["stale_cache"].append(asset)
                        # Keep in needed for refresh
                    else:
                        by_source["cache"].append(asset)
                        needed.remove(asset)
                        cache_hits += 1
        
        # Step 2: Try Coinbase for remaining assets (primary)
        if needed:
            for asset in list(needed):
                price = self._try_coinbase(asset)
                if price is not None:
                    self._add_to_price_window(asset, price, now, "coinbase")
                    composite = self._get_composite_price(asset, min_samples=2)
                    final_price = composite[0] if composite else price
                    source_tag = composite[1] if composite else "coinbase"
                    is_composite = composite is not None

                    self._set_cache(asset, final_price, source_tag)
                    results[asset] = SpotPrice(
                        asset=asset,
                        price=final_price,
                        source=source_tag,
                        timestamp=now,
                        is_composite=is_composite
                    )
                    by_source["coinbase" if "composite" not in source_tag else "composite"].append(asset)
                    needed.remove(asset)
                    live_fetches += 1

        # Step 3: Try Kraken for remaining assets (secondary)
        if needed:
            for asset in list(needed):
                price = self._try_kraken(asset)
                if price is not None:
                    self._add_to_price_window(asset, price, now, "kraken")
                    composite = self._get_composite_price(asset, min_samples=2)
                    final_price = composite[0] if composite else price
                    source_tag = composite[1] if composite else "kraken"
                    is_composite = composite is not None

                    self._set_cache(asset, final_price, source_tag)
                    results[asset] = SpotPrice(
                        asset=asset,
                        price=final_price,
                        source=source_tag,
                        timestamp=now,
                        is_composite=is_composite
                    )
                    by_source["kraken" if "composite" not in source_tag else "composite"].append(asset)
                    needed.remove(asset)
                    live_fetches += 1

        # Step 4: Batch remaining through BinanceUS (tertiary)
        if needed:
            binance_results = self._try_binanceus_batch(list(needed))
            for asset, price in binance_results.items():
                self._add_to_price_window(asset, price, now, "binanceus")
                composite = self._get_composite_price(asset, min_samples=2)
                final_price = composite[0] if composite else price
                source_tag = composite[1] if composite else "binanceus"
                is_composite = composite is not None

                self._set_cache(asset, final_price, source_tag)
                results[asset] = SpotPrice(
                    asset=asset,
                    price=final_price,
                    source=source_tag,
                    timestamp=now,
                    is_composite=is_composite
                )
                by_source["binanceus" if "composite" not in source_tag else "composite"].append(asset)
                needed.discard(asset)
                live_fetches += 1
        
        # Step 5: Fall back to stale cache for any remaining
        if needed and use_cache:
            for asset in list(needed):
                # Force read stale cache
                with self._get_cache_lock():
                    entry = self._cache.get(asset)
                    if entry:
                        age = now - entry.timestamp
                        results[asset] = SpotPrice(
                            asset=asset,
                            price=entry.price,
                            source=f"{entry.source}_stale_cache",
                            timestamp=entry.timestamp,
                            age_seconds=age,
                            is_stale=True
                        )
                        by_source["stale_cache"].append(asset)
                        needed.remove(asset)
                        logger.warning(
                            "Using stale cache for %s: age=%.1fs, price=%.2f",
                            asset, age, entry.price
                        )
        
        # Any still remaining are truly failed
        failed = sorted(list(needed))
        if failed:
            logger.error("Failed to fetch spot prices for: %s", failed)
        
        total_time_ms = (time.perf_counter() - t0) * 1000
        venue_health = self.venue_health_snapshot()
        n = len(assets)
        spot_feed_degraded = bool(
            n > 0
            and (
                len(failed) > n // 2
                or any(s == "degraded" for s in venue_health.values())
            )
        )

        return SpotServiceResult(
            prices=results,
            failed=failed,
            by_source=by_source,
            cache_hits=cache_hits,
            live_fetches=live_fetches,
            total_time_ms=total_time_ms,
            venue_health=venue_health,
            spot_feed_degraded=spot_feed_degraded,
        )
    
    def clear_cache(self) -> None:
        """Clear all cached prices."""
        with self._get_cache_lock():
            self._cache.clear()
        logger.info("Cache cleared")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._get_cache_lock():
            now = time.time()
            total = len(self._cache)
            fresh = sum(1 for e in self._cache.values() if now - e.timestamp <= self.cache_ttl)
            stale = total - fresh
            total_accesses = sum(e.access_count for e in self._cache.values())
            
        return {
            "total_entries": total,
            "fresh_entries": fresh,
            "stale_entries": stale,
            "total_accesses": total_accesses,
            "cache_ttl_seconds": self.cache_ttl,
            "stale_ttl_seconds": self.stale_ttl,
        }
    
    def get_failure_metrics(self) -> Dict[str, Dict[str, int]]:
        """Get upstream failure metrics for observability.
        
        Returns per-source counts of:
        - 429: Rate limit responses
        - timeout: Request timeouts
        - http_error: Other HTTP errors (4xx/5xx)
        - other: Exceptions (network, parse, etc.)
        """
        return self._failure_metrics.copy()
    
    def reset_failure_metrics(self) -> None:
        """Reset failure metrics counters."""
        for source in self._failure_metrics:
            for key in self._failure_metrics[source]:
                self._failure_metrics[source][key] = 0


# Singleton instance for reuse
crypto_spot_service: Optional[CryptoSpotService] = None


def get_crypto_spot_service() -> CryptoSpotService:
    """Get or create the singleton spot service instance.
    
    DEPRECATED: Use data.unified_spot_service.get_unified_spot_service() instead.
    This function is kept for legacy compatibility and will be removed in a future version.
    """
    import warnings
    warnings.warn(
        "get_crypto_spot_service() is deprecated. Use data.unified_spot_service.get_unified_spot_service() instead.",
        DeprecationWarning,
        stacklevel=2
    )
    
    global crypto_spot_service
    if crypto_spot_service is None:
        crypto_spot_service = CryptoSpotService()
    return crypto_spot_service
