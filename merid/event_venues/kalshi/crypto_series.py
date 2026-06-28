"""Kalshi Crypto Series Discovery — Dynamic series listing with caching and backoff.

Provides utilities for discovering and fetching Kalshi crypto prediction market series
with Redis caching, 429 backoff, and batch fetching capabilities.

Usage::

    from merid.event_venues.kalshi.crypto_series import (
        list_crypto_series,
        fetch_markets_batch,
        CRYPTO_FREQUENCIES,
    )

    # List all crypto series
    series = await list_crypto_series(category="crypto")

    # Fetch markets for specific series with backoff
    markets = await fetch_markets_batch(["KXBTC", "KXETH"], status="open")
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, List, Literal, Optional, Union

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.crypto_series")

# ── Constants ──────────────────────────────────────────────────────────────

# PRODUCTION AUDIT (Step 3): Only 15m timeframe allowed for trading
CRYPTO_FREQUENCIES = ["15m"]
"""Supported crypto market frequencies (production: 15m only)."""

# Series ticker prefixes for crypto assets
CRYPTO_SERIES_PREFIXES = {
    "BTC": "KXBTC",
    "ETH": "KXETH",
    "SOL": "KXSOL",
    "XRP": "KXXRP",
    "DOGE": "KXDOGE",
}

# Frequency suffix mapping
FREQUENCY_SUFFIXES = {
    "15m": "15M",
    "hourly": "",
    "daily": "D1",
    "weekly": "W1",
    "monthly": "1M",
    "annual": "Y",
}

# Cache settings
CACHE_PREFIX = "kalshi:crypto_series"
CACHE_TTL_SECONDS = int(timedelta(minutes=15).total_seconds())  # 15 minutes

# Backoff schedule for 429 responses (in seconds): 0.25, 1, 4
BACKOFF_SCHEDULE = [0.25, 1.0, 4.0]


# ── Data Models ─────────────────────────────────────────────────────────────

@dataclass
class CryptoSeries:
    """Represents a Kalshi crypto series."""

    series_ticker: str
    asset: str  # BTC, ETH, SOL, XRP, DOGE
    frequency: str  # 15m, hourly, daily, weekly
    title: str
    category: str = "crypto"
    volume_24h: Optional[float] = None
    open_interest: Optional[int] = None
    market_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "series_ticker": self.series_ticker,
            "asset": self.asset,
            "frequency": self.frequency,
            "title": self.title,
            "category": self.category,
            "volume_24h": self.volume_24h,
            "open_interest": self.open_interest,
            "market_count": self.market_count,
        }


@dataclass
class MarketInfo:
    """Represents a Kalshi market within a series."""

    market_id: str
    series_ticker: str
    title: str
    status: str  # open, closed, settled
    yes_price: Optional[int] = None  # in cents
    no_price: Optional[int] = None  # in cents
    volume: Optional[int] = None
    open_interest: Optional[int] = None
    expiration_time: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "series_ticker": self.series_ticker,
            "title": self.title,
            "status": self.status,
            "yes_price": self.yes_price,
            "no_price": self.no_price,
            "volume": self.volume,
            "open_interest": self.open_interest,
            "expiration_time": self.expiration_time,
        }


# ── Cache Interface ─────────────────────────────────────────────────────────

class _CacheAdapter:
    """Simple cache adapter supporting Redis or in-memory fallback."""

    def __init__(self) -> None:
        self._redis: Optional[Any] = None
        self._memory: Dict[str, Any] = {}
        self._ttl: Dict[str, float] = {}
        self._try_redis()

    def _try_redis(self) -> None:
        """Attempt to connect to Redis, fall back to memory if unavailable."""
        try:
            import redis

            # Try Redis with configurable host
            redis_host = os.getenv("REDIS_HOST", "localhost")
            r = redis.Redis(host=redis_host, port=6379, decode_responses=True, socket_connect_timeout=2)
            r.ping()
            self._redis = r
            logger.info("Cache: Connected to Redis")
        except Exception:
            self._redis = None
            logger.debug("Cache: Using in-memory fallback (Redis unavailable)")

    async def get(self, key: str) -> Optional[str]:
        """Get value from cache."""
        try:
            if self._redis:
                return self._redis.get(key)  # type: ignore
        except Exception as e:
            logger.debug(f"Redis get failed: {e}")

        # In-memory fallback with TTL check
        now = time.time()
        if key in self._memory:
            if self._ttl.get(key, 0) > now:
                return self._memory[key]
            else:
                # Expired
                del self._memory[key]
                self._ttl.pop(key, None)
        return None

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """Set value in cache with TTL."""
        try:
            if self._redis:
                self._redis.setex(key, ttl_seconds, value)  # type: ignore
                return
        except Exception as e:
            logger.debug(f"Redis set failed: {e}")

        # In-memory fallback
        self._memory[key] = value
        self._ttl[key] = time.time() + ttl_seconds

    async def delete(self, pattern: str) -> int:
        """Delete keys matching pattern. Returns count deleted."""
        try:
            if self._redis:
                keys = self._redis.keys(pattern)
                if keys:
                    return self._redis.delete(*keys)  # type: ignore
                return 0
        except Exception as e:
            logger.debug(f"Redis delete failed: {e}")

        # In-memory fallback - simple prefix match
        count = 0
        keys_to_delete = [k for k in self._memory.keys() if k.startswith(pattern.replace("*", ""))]
        for k in keys_to_delete:
            del self._memory[k]
            self._ttl.pop(k, None)
            count += 1
        return count


# Global cache instance
_cache = _CacheAdapter()


def _make_cache_key(*parts: str) -> str:
    """Build a cache key with the proper prefix."""
    key = f"{CACHE_PREFIX}:{':'.join(parts)}"
    # Hash long keys to stay within Redis limits
    if len(key) > 200:
        h = hashlib.md5(key.encode()).hexdigest()[:16]
        key = f"{CACHE_PREFIX}:{h}"
    return key


# ── Backoff Logic ───────────────────────────────────────────────────────────

async def _fetch_with_backoff(
    fetch_fn,
    *args,
    max_retries: int = 3,
    **kwargs,
) -> Any:
    """Execute fetch function with 429 backoff.

    Args:
        fetch_fn: Async function to call
        *args: Positional arguments for fetch_fn
        max_retries: Maximum retry attempts (default 3 for backoff schedule [0.25, 1, 4])
        **kwargs: Keyword arguments for fetch_fn

    Returns:
        Result from fetch_fn

    Raises:
        Exception: If all retries exhausted
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return await fetch_fn(*args, **kwargs)
        except Exception as exc:
            last_exception = exc
            error_str = str(exc).lower()

            # Check for 429 or rate limit indicators
            is_rate_limit = (
                "429" in error_str
                or "rate limit" in error_str
                or "too many requests" in error_str
                or "ratelimited" in error_str
            )

            if is_rate_limit and attempt < max_retries:
                delay = BACKOFF_SCHEDULE[min(attempt, len(BACKOFF_SCHEDULE) - 1)]
                logger.warning(f"Rate limited (429), backing off for {delay}s (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(delay)
            else:
                # Not a rate limit or exhausted retries
                raise

    # Should not reach here, but just in case
    raise last_exception or Exception("Max retries exceeded")


# ── Client Interface ────────────────────────────────────────────────────────

async def _get_kalshi_client():
    """Get or create Kalshi client instance."""
    from merid.event_venues.kalshi.client import get_kalshi_client

    return get_kalshi_client()


# ── Public API ───────────────────────────────────────────────────────────────

async def list_crypto_series(
    category: str = "crypto",
    min_volume: Optional[float] = None,
    frequency: Optional[str] = None,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> List[CryptoSeries]:
    """List available Kalshi crypto series with optional filtering.

    Args:
        category: Category filter (default "crypto")
        min_volume: Minimum 24h volume filter (optional)
        frequency: Frequency filter - "15m", "hourly", "daily", "weekly" (optional)
        use_cache: Whether to use Redis cache (default True)
        force_refresh: Force cache refresh (default False)

    Returns:
        List of CryptoSeries objects matching filters
    """
    cache_key = _make_cache_key("list", category, str(min_volume), str(frequency))

    # Try cache first
    if use_cache and not force_refresh:
        cached = await _cache.get(cache_key)
        if cached:
            try:
                data = json.loads(cached)
                result = [CryptoSeries(**s) for s in data]
                logger.debug(f"Cache hit: {len(result)} series from cache")
                return result
            except Exception as exc:
                logger.debug(f"Cache parse error: {exc}")

    # Fetch from API with backoff
    try:
        series_list = await _fetch_with_backoff(_fetch_series_from_api, category)
    except Exception as exc:
        logger.warning(f"Failed to fetch series: {exc}")
        return []

    # Apply filters
    result: List[CryptoSeries] = []
    for series in series_list:
        # Category filter
        if category and series.category != category:
            continue

        # Volume filter
        if min_volume is not None and (series.volume_24h or 0) < min_volume:
            continue

        # Frequency filter
        if frequency is not None and series.frequency != frequency:
            continue

        result.append(series)

    # Cache result
    if use_cache and result:
        try:
            cache_data = json.dumps([s.to_dict() for s in result])
            await _cache.set(cache_key, cache_data, CACHE_TTL_SECONDS)
            logger.debug(f"Cached {len(result)} series for {CACHE_TTL_SECONDS}s")
        except Exception as exc:
            logger.debug(f"Cache write error: {exc}")

    return result


async def _fetch_series_from_api(category: str) -> List[CryptoSeries]:
    """Fetch series list from Kalshi API."""
    client = await _get_kalshi_client()

    result: List[CryptoSeries] = []

    # Build series for all crypto assets and frequencies
    for asset, prefix in CRYPTO_SERIES_PREFIXES.items():
        for freq, suffix in FREQUENCY_SUFFIXES.items():
            series_ticker = f"{prefix}{suffix}"

            # Create series info
            freq_display = freq if freq != "hourly" else "hourly"
            title = f"{asset} {freq_display.upper()}"

            series = CryptoSeries(
                series_ticker=series_ticker,
                asset=asset,
                frequency=freq,
                title=title,
                category=category,
            )

            result.append(series)

    # Try to enrich with live data from catalog
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog

        catalog = get_market_catalog()

        # Count markets per series
        for series in result:
            count = 0
            total_volume = 0
            total_oi = 0

            for cm in catalog.get_all_markets():
                # CRITICAL FIX: CatalogMarket wraps EventMarket, so raw_data is on nested market.market
                if hasattr(cm, "market") and hasattr(cm.market, "raw_data"):
                    raw = cm.market.raw_data or {}
                elif hasattr(cm, "raw_data"):
                    raw = cm.raw_data or {}
                else:
                    raw = {}
                
                mkt_series = raw.get("series_ticker", "")
                if mkt_series and mkt_series.upper() == series.series_ticker.upper():
                    count += 1
                    # CRITICAL FIX: volume is on nested EventMarket
                    if hasattr(cm, "market") and hasattr(cm.market, "volume"):
                        total_volume += float(cm.market.volume or 0)
                    elif hasattr(cm, "volume"):
                        total_volume += float(cm.volume or 0)
                    total_oi += int(raw.get("open_interest", 0) or 0)

            series.market_count = count
            series.volume_24h = total_volume if total_volume > 0 else None
            series.open_interest = total_oi if total_oi > 0 else None

    except Exception as exc:
        logger.debug(f"Could not enrich series with catalog data: {exc}")

    return result


async def fetch_markets_batch(
    series_tickers: List[str],
    status: Optional[Literal["open", "closed", "settled"]] = None,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> List[MarketInfo]:
    """Fetch markets for multiple series tickers with batching and backoff.

    Args:
        series_tickers: List of series tickers (e.g., ["KXBTC", "KXETH"])
        status: Optional status filter - "open", "closed", or "settled"
        use_cache: Whether to use Redis cache (default True)
        force_refresh: Force cache refresh (default False)

    Returns:
        List of MarketInfo objects
    """
    if not series_tickers:
        return []

    result: List[MarketInfo] = []

    for series_ticker in series_tickers:
        markets = await _fetch_markets_for_series(
            series_ticker,
            status=status,
            use_cache=use_cache,
            force_refresh=force_refresh,
        )
        result.extend(markets)

    return result


async def _fetch_markets_for_series(
    series_ticker: str,
    status: Optional[str] = None,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> List[MarketInfo]:
    """Fetch markets for a single series ticker."""
    cache_key = _make_cache_key("markets", series_ticker, str(status))

    # Try cache first
    if use_cache and not force_refresh:
        cached = await _cache.get(cache_key)
        if cached:
            try:
                data = json.loads(cached)
                result = [MarketInfo(**m) for m in data]
                logger.debug(f"Cache hit: {len(result)} markets for {series_ticker}")
                return result
            except Exception as exc:
                logger.debug(f"Cache parse error for {series_ticker}: {exc}")

    # Fetch from API with backoff
    try:
        markets = await _fetch_with_backoff(_fetch_markets_from_api, series_ticker, status)
    except Exception as exc:
        logger.warning(f"Failed to fetch markets for {series_ticker}: {exc}")
        return []

    # Cache result
    if use_cache and markets:
        try:
            cache_data = json.dumps([m.to_dict() for m in markets])
            await _cache.set(cache_key, cache_data, CACHE_TTL_SECONDS)
        except Exception as exc:
            logger.debug(f"Cache write error for {series_ticker}: {exc}")

    return markets


async def _fetch_markets_from_api(
    series_ticker: str,
    status: Optional[str] = None,
) -> List[MarketInfo]:
    """Fetch markets from Kalshi API."""
    client = await _get_kalshi_client()

    result: List[MarketInfo] = []

    try:
        # Use the catalog for market lookup
        from merid.event_venues.kalshi.market_catalog import get_market_catalog

        catalog = get_market_catalog()
        all_markets = catalog.get_all_markets()

        for cm in all_markets:
            # CRITICAL FIX: CatalogMarket wraps EventMarket, so raw_data is on nested market.market
            if hasattr(cm, "market") and hasattr(cm.market, "raw_data"):
                raw = cm.market.raw_data or {}
            elif hasattr(cm, "raw_data"):
                raw = cm.raw_data or {}
            else:
                raw = {}
            
            mkt_series = raw.get("series_ticker", "")

            # Match series ticker
            if not mkt_series or mkt_series.upper() != series_ticker.upper():
                continue

            # CRITICAL FIX: market_id is on nested EventMarket
            if hasattr(cm, "market") and hasattr(cm.market, "market_id"):
                mkt_id = cm.market.market_id or ""
            elif hasattr(cm, "market_id"):
                mkt_id = cm.market_id or ""
            else:
                continue

            # Determine status
            mkt_status = "open"
            # CRITICAL FIX: resolved and active are on nested EventMarket
            if hasattr(cm, "market") and hasattr(cm.market, "resolved") and cm.market.resolved:
                mkt_status = "settled"
            elif hasattr(cm, "resolved") and cm.resolved:
                mkt_status = "settled"
            elif hasattr(cm, "market") and hasattr(cm.market, "active") and not cm.market.active:
                mkt_status = "closed"
            elif hasattr(cm, "active") and not cm.active:
                mkt_status = "closed"

            # Apply status filter
            if status and mkt_status != status:
                continue

            # Extract prices
            yes_price = None
            no_price = None
            # CRITICAL FIX: yes_price and no_price are on nested EventMarket
            if hasattr(cm, "market") and hasattr(cm.market, "yes_price"):
                yes_price = int(cm.market.yes_price) if cm.market.yes_price is not None else None
            elif hasattr(cm, "yes_price"):
                yes_price = int(cm.yes_price) if cm.yes_price is not None else None
            if hasattr(cm, "market") and hasattr(cm.market, "no_price"):
                no_price = int(cm.market.no_price) if cm.market.no_price is not None else None
            elif hasattr(cm, "no_price"):
                no_price = int(cm.no_price) if cm.no_price is not None else None

            # CRITICAL FIX: volume, question, and end_date are on nested EventMarket
            if hasattr(cm, "market") and hasattr(cm.market, "volume"):
                volume = int(cm.market.volume) if cm.market.volume else None
            elif hasattr(cm, "volume"):
                volume = int(cm.volume) if cm.volume else None
            else:
                volume = None

            if hasattr(cm, "market") and hasattr(cm.market, "question"):
                title = cm.market.question
            elif hasattr(cm, "question"):
                title = cm.question
            else:
                title = mkt_id

            if hasattr(cm, "market") and hasattr(cm.market, "end_date"):
                end_date = cm.market.end_date
            elif hasattr(cm, "end_date"):
                end_date = cm.end_date
            else:
                end_date = None

            market_info = MarketInfo(
                market_id=mkt_id,
                series_ticker=mkt_series,
                title=title,
                status=mkt_status,
                yes_price=yes_price,
                no_price=no_price,
                volume=volume,
                open_interest=raw.get("open_interest"),
                expiration_time=raw.get("expiration_time") or end_date,
            )

            result.append(market_info)

    except Exception as exc:
        logger.debug(f"Error fetching markets from catalog: {exc}")

    # If catalog is empty or failed, try REST API fallback
    if not result:
        try:
            from merid.event_venues.base import MarketFilter

            filter_params = MarketFilter(
                search=series_ticker,
                active_only=(status == "open"),
                limit=100,
            )

            api_result = await client.list_markets_result(filter_params)

            if api_result.success and api_result.data:
                for market in api_result.data:
                    raw = getattr(market, "raw_data", {}) or {}
                    mkt_series = raw.get("series_ticker", "")

                    if mkt_series.upper() != series_ticker.upper():
                        continue

                    mkt_status = "open" if getattr(market, "active", False) else "closed"
                    if getattr(market, "resolved", False):
                        mkt_status = "settled"

                    if status and mkt_status != status:
                        continue

                    market_info = MarketInfo(
                        market_id=getattr(market, "market_id", ""),
                        series_ticker=mkt_series,
                        title=getattr(market, "question", ""),
                        status=mkt_status,
                        yes_price=int(getattr(market, "yes_price", 0)) if hasattr(market, "yes_price") else None,
                        no_price=int(getattr(market, "no_price", 0)) if hasattr(market, "no_price") else None,
                        volume=int(getattr(market, "volume", 0)) if hasattr(market, "volume") else None,
                        open_interest=raw.get("open_interest"),
                        expiration_time=getattr(market, "end_date", None),
                    )
                    result.append(market_info)

        except Exception as exc:
            logger.debug(f"REST API fallback failed: {exc}")

    return result


# ── Cache Management ─────────────────────────────────────────────────────────

async def invalidate_crypto_series_cache(category: Optional[str] = None) -> int:
    """Invalidate cached crypto series data.

    Args:
        category: Optional category to target (invalidates all if None)

    Returns:
        Number of cache entries deleted
    """
    pattern = f"{CACHE_PREFIX}:*" if category is None else f"{CACHE_PREFIX}:list:{category}*"
    count = await _cache.delete(pattern)
    logger.info(f"Invalidated {count} cache entries for pattern {pattern}")
    return count


async def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics for crypto series."""
    # This is a best-effort stats collection
    return {
        "prefix": CACHE_PREFIX,
        "ttl_seconds": CACHE_TTL_SECONDS,
        "backoff_schedule": BACKOFF_SCHEDULE,
        "cache_type": "redis" if _cache._redis else "memory",
    }
