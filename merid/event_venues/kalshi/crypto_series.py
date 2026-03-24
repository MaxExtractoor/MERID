"""Crypto series discovery utilities for Kalshi.

Supports multi-asset, multi-frequency discovery (BTC/ETH/SOL/XRP/DOGE),
caches series metadata, and batches market polling with graceful
backoff for rate limits and maintenance windows.
"""

from __future__ import annotations

import asyncio
from typing import Dict, Iterable, List, Optional, Sequence, Set

from core.cache import cache
from merid.event_venues.base import EventMarket, MarketFilter
from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.resilience import OperationResult
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.crypto_series")

TARGET_ASSETS: Set[str] = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
_CACHE_KEY = "kalshi:crypto_series:v1"
_DEFAULT_CACHE_TTL = 900  # seconds (15 minutes)
_BACKOFF_SCHEDULE = (0.25, 1.0, 4.0)

_FREQ_NORMALIZATION = {
    "15m": "15m",
    "15_minute": "15m",
    "15-minute": "15m",
    "1h": "1h",
    "hourly": "1h",
    "1hour": "1h",
    "1d": "1d",
    "daily": "1d",
    "1day": "1d",
    "1w": "1w",
    "weekly": "1w",
    "1m": "1m",
    "monthly": "1m",
    "1y": "1y",
    "annual": "1y",
    "yearly": "1y",
    "one-time": "one_time",
    "one_time": "one_time",
    "ot": "one_time",
}


def _normalize_frequency(freq: Optional[str]) -> Optional[str]:
    if not freq:
        return None
    return _FREQ_NORMALIZATION.get(freq.lower(), freq)


def _asset_from_tags(tags: Iterable[str]) -> Optional[str]:
    for tag in tags:
        upper = tag.upper()
        if upper in TARGET_ASSETS:
            return upper
    return None


def _validate_series_ticker(series_ticker: str) -> Optional[str]:
    ticker = (series_ticker or "").strip().upper()
    if not ticker:
        return None
    if not ticker.startswith("KX"):
        return None
    return ticker


async def _fetch_series_from_api(
    client: KalshiVenueClient,
    min_updated_ts: Optional[int] = None,
) -> List[Dict]:
    """Fetch raw crypto series from Kalshi."""
    result: OperationResult[List[Dict]] = await client.list_series(
        limit=500,
        category="crypto",
        include_volume=True,
        min_updated_ts=min_updated_ts,
    )
    if not result.success:
        logger.warning("list_series failed: %s", result.error or result.error_message)
        return []
    return result.data or []


async def list_crypto_series(
    client: KalshiVenueClient,
    *,
    min_updated_ts: Optional[int] = None,
    force_refresh: bool = False,
    use_cache: bool = True,
    cache_ttl_seconds: int = _DEFAULT_CACHE_TTL,
) -> List[Dict[str, object]]:
    """List crypto series across all supported assets and frequencies.

    Uses Kalshi /series endpoint with category=crypto and caches the
    filtered result set for 15 minutes. Cache is bypassed when a
    min_updated_ts is provided or force_refresh is True.
    """
    if use_cache and not force_refresh and min_updated_ts is None:
        cached = cache.get_json(_CACHE_KEY)
        if cached:
            return cached  # type: ignore[return-value]

    raw_series = await _fetch_series_from_api(client, min_updated_ts=min_updated_ts)

    filtered: List[Dict[str, object]] = []
    for series in raw_series:
        tags = series.get("tags", []) or []
        asset = _asset_from_tags(tags)
        if not asset:
            continue
        freq = _normalize_frequency(series.get("frequency"))
        ticker = _validate_series_ticker(series.get("ticker", ""))
        if not ticker or not freq:
            continue
        filtered.append(
            {
                "ticker": ticker,
                "asset": asset,
                "frequency": freq,
                "title": series.get("title"),
                "tags": tags,
                "volume_fp": series.get("volume_fp", "0"),
            }
        )

    if use_cache and not min_updated_ts:
        cache.set_json(_CACHE_KEY, filtered, ttl=cache_ttl_seconds)
    return filtered


def group_frequencies_by_asset(series: Iterable[Dict[str, object]]) -> Dict[str, Set[str]]:
    """Build map of asset -> discovered frequencies."""
    result: Dict[str, Set[str]] = {}
    for item in series:
        asset = item.get("asset")
        freq = item.get("frequency")
        if not isinstance(asset, str) or not isinstance(freq, str):
            continue
        result.setdefault(asset, set()).add(freq)
    return result


async def fetch_markets_batch(
    client: KalshiVenueClient,
    series_batch: Sequence[str],
    *,
    status: str = "open",
    throttle_seconds: float = 0.1,
    backoff_schedule: Sequence[float] = _BACKOFF_SCHEDULE,
    max_per_series: int = 200,
) -> List[EventMarket]:
    """Fetch markets for a batch of series tickers with backoff on 429."""
    markets: List[EventMarket] = []
    status_lower = status.lower()
    active_only = status_lower == "open"

    for raw_ticker in series_batch:
        series_ticker = _validate_series_ticker(raw_ticker)
        if not series_ticker:
            logger.debug("fetch_markets_batch: skipping invalid ticker %s", raw_ticker)
            continue

        attempts = len(backoff_schedule) + 1
        for attempt in range(attempts):
            if attempt > 0:
                await asyncio.sleep(backoff_schedule[attempt - 1])

            filt = MarketFilter(
                search=series_ticker,
                active_only=active_only,
                limit=max_per_series,
            )
            result = await client.list_markets_result(filt)
            if result.success:
                if result.data:
                    markets.extend(result.data)
                if throttle_seconds > 0:
                    await asyncio.sleep(throttle_seconds)
                break

            status_code = result.metadata.get("status_code") if isinstance(result.metadata, dict) else None
            if status_code == 429 and attempt < len(backoff_schedule):
                continue

            logger.warning(
                "fetch_markets_batch: failed for %s (%s): %s",
                series_ticker,
                status_lower,
                result.error or result.error_message,
            )
            break

    return markets
