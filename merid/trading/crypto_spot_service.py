"""Unified Crypto Spot Price Service for MERID.

Provides multi-asset spot price fetching with the following priority:
1. Coinbase Advanced (primary) - per-asset calls using existing adapter
2. BinanceUS (fallback) - batch call for missing assets
3. CoinGecko (final fallback) - batch call for remaining assets

Features:
- Rate limit aware with token bucket per source
- TTL caching with stale-while-revalidate pattern
- Source tracking for observability
- Synchronous API (for use in CT run_in_executor contexts)

Env vars:
    SPOT_SERVICE_CACHE_TTL_SECONDS: int (default: 10)
    SPOT_SERVICE_STALE_TTL_SECONDS: int (default: 30)
    SPOT_SERVICE_COINGECKO_API_KEY: Optional[str]
"""

from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import json
import time
import os
import logging

import httpx
import requests

logger = logging.getLogger(__name__)

# Asset to symbol mappings
ASSET_TO_COINBASE_PRODUCT = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
    "XRP": "XRP-USD",
    "DOGE": "DOGE-USD",
}

ASSET_TO_BINANCEUS_SYMBOL = {
    "BTC": "BTCUSD",
    "ETH": "ETHUSD",
    "SOL": "SOLUSD",
    "XRP": "XRPUSD",
    "DOGE": "DOGEUSD",
}

ASSET_TO_COINGECKO_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "DOGE": "dogecoin",
}

_SPOT_VENUE_ERROR_STREAK_MAX: int = int(os.getenv("SPOT_VENUE_ERROR_STREAK_MAX", "5"))


@dataclass
class SpotPrice:
    """Spot price result with metadata."""
    asset: str
    price: float
    source: str  # 'coinbase', 'binanceus', 'coingecko', 'cache'
    timestamp: float
    age_seconds: float = field(default=0.0)
    is_stale: bool = field(default=False)


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
        coingecko_api_key: Optional[str] = None,
    ):
        self.cache_ttl = cache_ttl_seconds or int(os.getenv("SPOT_SERVICE_CACHE_TTL_SECONDS", "10"))
        self.stale_ttl = stale_ttl_seconds or int(os.getenv("SPOT_SERVICE_STALE_TTL_SECONDS", "30"))
        self.coingecko_api_key = coingecko_api_key or os.getenv("SPOT_SERVICE_COINGECKO_API_KEY")
        
        # Cache: asset -> _CacheEntry
        self._cache: Dict[str, _CacheEntry] = {}
        self._cache_lock = None  # Lazy init
        
        # Rate limiters per source
        # Coinbase: 10 requests per second (generous for 5 assets)
        self._coinbase_limiter = TokenBucket(rate_per_second=10.0, burst=5)
        # BinanceUS: 20 requests per second
        self._binanceus_limiter = TokenBucket(rate_per_second=20.0, burst=10)
        # CoinGecko: 10-30 calls/minute for free tier, 1 call per 2 seconds
        self._coingecko_limiter = TokenBucket(rate_per_second=0.5, burst=1)
        
        # HTTP clients (lazy init)
        self._http_client: Optional[httpx.Client] = None
        
        # Upstream failure metrics for observability
        self._failure_metrics: Dict[str, Dict[str, int]] = {
            "coinbase": {"429": 0, "timeout": 0, "http_error": 0, "other": 0},
            "binanceus": {"429": 0, "timeout": 0, "http_error": 0, "other": 0},
            "coingecko": {"429": 0, "timeout": 0, "http_error": 0, "other": 0},
        }
        self._venue_error_streak: Dict[str, int] = {
            "coinbase": 0,
            "binanceus": 0,
            "coingecko": 0,
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
    
    def _get_http_client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=10.0, follow_redirects=True)
        return self._http_client

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
                logger.debug("Coinbase v2 success: %s = %.2f", asset, price)
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
                logger.debug("Coinbase Exchange success: %s = %.2f", asset, price)
                self._clear_venue_error("coinbase")
                return price
        except Exception as e:
            logger.debug("Coinbase Exchange fallback failed for %s: %s", asset, e)

        self._bump_venue_error("coinbase")
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
    
    def _try_coingecko_batch(self, assets: List[str]) -> Dict[str, float]:
        """Try to fetch spot prices from CoinGecko for multiple assets.
        
        Uses the /simple/price endpoint with multiple IDs in one call.
        Respects CoinGecko's limit of 50 tokens per request.
        """
        if not assets:
            return {}
        
        # CoinGecko limits to 50 tokens per request
        if len(assets) > 50:
            logger.warning("CoinGecko batch size %d exceeds 50-token limit, truncating", len(assets))
            assets = assets[:50]
        
        if not self._coingecko_limiter.acquire(timeout=5.0):
            logger.warning("CoinGecko rate limit exceeded")
            return {}
        
        # Map assets to CoinGecko IDs
        ids = []
        id_to_asset = {}
        for asset in assets:
            cg_id = ASSET_TO_COINGECKO_ID.get(asset.upper())
            if cg_id:
                ids.append(cg_id)
                id_to_asset[cg_id] = asset.upper()
        
        if not ids:
            return {}
        
        results = {}
        try:
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {
                "ids": ",".join(ids),
                "vs_currencies": "usd",
            }
            
            # Add API key if available (for higher rate limits)
            headers = {}
            if self.coingecko_api_key:
                headers["x-cg-pro-api-key"] = self.coingecko_api_key
            
            logger.debug("CoinGecko request: GET %s with ids=%s", url, params["ids"])
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            
            if resp.status_code == 429:
                logger.warning("CoinGecko rate limited (429) - %d assets", len(ids))
                self._failure_metrics["coingecko"]["429"] += 1
                self._bump_venue_error("coingecko")
                return {}
            
            resp.raise_for_status()
            data = resp.json()
            
            for cg_id, values in data.items():
                asset = id_to_asset.get(cg_id)
                if asset and "usd" in values:
                    results[asset] = float(values["usd"])
                    logger.debug("CoinGecko success: %s = %.2f", asset, results[asset])
            
            # Log missing assets
            missing_ids = set(ids) - set(data.keys())
            if missing_ids:
                logger.warning("CoinGecko: ids not returned: %s", missing_ids)
            if results:
                self._clear_venue_error("coingecko")
                    
        except requests.exceptions.HTTPError as e:
            logger.warning("CoinGecko HTTP error: %s (status=%s)", e, resp.status_code)
            self._failure_metrics["coingecko"]["http_error"] += 1
            self._bump_venue_error("coingecko")
        except requests.exceptions.Timeout:
            logger.warning("CoinGecko timeout")
            self._failure_metrics["coingecko"]["timeout"] += 1
            self._bump_venue_error("coingecko")
        except Exception as e:
            logger.debug("CoinGecko batch fetch failed: %s", e)
            self._failure_metrics["coingecko"]["other"] += 1
            self._bump_venue_error("coingecko")
        
        return results
    
    def get_spot(self, asset: str, use_cache: bool = True) -> Optional[SpotPrice]:
        """Get spot price for a single asset.
        
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
        
        # Try sources in priority order
        # 1. Coinbase
        price = self._try_coinbase(asset)
        if price is not None:
            self._set_cache(asset, price, "coinbase")
            return SpotPrice(
                asset=asset,
                price=price,
                source="coinbase",
                timestamp=now
            )
        
        # 2. BinanceUS (single asset as batch of 1)
        results = self._try_binanceus_batch([asset])
        if asset in results:
            self._set_cache(asset, results[asset], "binanceus")
            return SpotPrice(
                asset=asset,
                price=results[asset],
                source="binanceus",
                timestamp=now
            )
        
        # 3. CoinGecko (single asset as batch of 1)
        results = self._try_coingecko_batch([asset])
        if asset in results:
            self._set_cache(asset, results[asset], "coingecko")
            return SpotPrice(
                asset=asset,
                price=results[asset],
                source="coingecko",
                timestamp=now
            )
        
        return None
    
    def get_all_spots(
        self,
        assets: List[str],
        use_cache: bool = True
    ) -> SpotServiceResult:
        """Get spot prices for multiple assets with efficient batching.
        
        Returns partial results: assets with successful fetches are in `prices`,
        failed assets are in `failed`. Callers MUST check `asset not in result.failed`
        or use `.get()` before accessing prices. Missing key ⇒ price unavailable.
        
        Strategy:
        1. Check cache for all assets
        2. Try Coinbase for remaining (per-asset, parallel-friendly)
        3. Batch failed assets through BinanceUS
        4. Batch remaining through CoinGecko
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
        by_source: Dict[str, List[str]] = {"coinbase": [], "binanceus": [], "coingecko": [], "cache": [], "stale_cache": []}
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
        
        # Step 2: Try Coinbase for remaining assets
        coinbase_success = []
        if needed:
            for asset in list(needed):
                price = self._try_coinbase(asset)
                if price is not None:
                    self._set_cache(asset, price, "coinbase")
                    results[asset] = SpotPrice(
                        asset=asset,
                        price=price,
                        source="coinbase",
                        timestamp=time.time()
                    )
                    by_source["coinbase"].append(asset)
                    needed.remove(asset)
                    coinbase_success.append(asset)
                    live_fetches += 1
        
        # Step 3: Batch remaining through BinanceUS
        if needed:
            binance_results = self._try_binanceus_batch(list(needed))
            for asset, price in binance_results.items():
                self._set_cache(asset, price, "binanceus")
                results[asset] = SpotPrice(
                    asset=asset,
                    price=price,
                    source="binanceus",
                    timestamp=time.time()
                )
                by_source["binanceus"].append(asset)
                needed.discard(asset)
                live_fetches += 1
        
        # Step 4: Batch remaining through CoinGecko
        if needed:
            coingecko_results = self._try_coingecko_batch(list(needed))
            for asset, price in coingecko_results.items():
                self._set_cache(asset, price, "coingecko")
                results[asset] = SpotPrice(
                    asset=asset,
                    price=price,
                    source="coingecko",
                    timestamp=time.time()
                )
                by_source["coingecko"].append(asset)
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
    """Get or create the singleton spot service instance."""
    global crypto_spot_service
    if crypto_spot_service is None:
        crypto_spot_service = CryptoSpotService()
    return crypto_spot_service
