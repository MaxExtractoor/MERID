import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

import httpx

from .models import KalshiConfig

logger = logging.getLogger(__name__)


@dataclass
class PublicSeriesInfo:
    ticker: str
    category: str
    frequency: Optional[str]
    raw: Dict[str, Any]


@dataclass
class PublicMarketInfo:
    market_id: str
    series_ticker: str
    close_ts: int  # unix seconds
    category: str
    raw: Dict[str, Any]


@dataclass
class SeriesCache:
    ttl_seconds: int = 300
    last_refresh_ts: float = 0.0
    by_symbol: Dict[str, PublicSeriesInfo] = field(default_factory=dict)


class KalshiPublicDataClient:
    def __init__(self, cfg: KalshiConfig, timeout: float = 5.0):
        self._cfg = cfg
        self._timeout = timeout
        # Lazy-initialize httpx.AsyncClient to avoid event loop binding issues
        self._http: Optional[httpx.AsyncClient] = None
        self._series_cache = SeriesCache()

    def _get_http(self) -> httpx.AsyncClient:
        """Lazy-initialize httpx.AsyncClient to avoid cross-event loop binding."""
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self._cfg.public_rest_api_url, timeout=self._timeout
            )
        return self._http

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()

    async def refresh_crypto_15m_series(self, force: bool = False) -> Dict[str, PublicSeriesInfo]:
        now = time.time()
        if not force and (now - self._series_cache.last_refresh_ts) < self._series_cache.ttl_seconds:
            logger.info(
                "KALSHI_PUBLIC_SERIES_CACHE_HIT returning cached count=%d assets=%s",
                len(self._series_cache.by_symbol),
                sorted(self._series_cache.by_symbol.keys()),
            )
            return self._series_cache.by_symbol

        # Get all series, then filter to crypto 15m.
        # If this is too big, add ?category=crypto&status=active once you confirm fields.
        url = "/series"
        params = {"status": "active"}  # per docs; adjust if needed.

        try:
            http = self._get_http()
            r = await http.get(url, params=params)
            r.raise_for_status()
        except Exception as exc:
            logger.error("KALSHI_PUBLIC_SERIES_ERROR err=%s", exc)
            return self._series_cache.by_symbol  # stale cache if present

        payload = r.json()
        series_list = payload.get("series", []) or payload.get("results", [])

        by_symbol: Dict[str, PublicSeriesInfo] = {}
        # Log all crypto series for debugging
        crypto_series_seen = []
        for s in series_list:
            category = s.get("category", "")
            frequency = s.get("frequency") or s.get("freq")
            ticker = s.get("ticker") or s.get("series_ticker")
            if not ticker:
                continue

            # Log all crypto series regardless of frequency for debugging
            if category.lower() == "crypto":
                crypto_series_seen.append(f"{ticker} (freq={frequency})")

            if category.lower() != "crypto":
                continue
            # 15m frequency; adjust key name once confirmed from docs.
            # Relax filter to include more variants
            if frequency and "15" not in str(frequency).lower() and "min" not in str(frequency).lower():
                continue

            # Derive a stable asset symbol from series ticker, e.g. KXBTC15M → BTC
            asset = self._derive_asset_symbol(ticker)
            info = PublicSeriesInfo(
                ticker=ticker,
                category=category,
                frequency=frequency,
                raw=s,
            )
            by_symbol[asset] = info

        # Log all crypto series seen for debugging
        if len(by_symbol) < 5:
            logger.warning(
                "KALSHI_PUBLIC_SERIES_INCOMPLETE Expected 5 crypto assets (BTC/ETH/SOL/XRP/DOGE) but only found %d: %s",
                len(by_symbol),
                sorted(by_symbol.keys()),
            )
        logger.info(
            "KALSHI_PUBLIC_SERIES_DEBUG all_crypto_series=%d %s",
            len(crypto_series_seen),
            crypto_series_seen[:20],  # Log first 20
        )

        self._series_cache.by_symbol = by_symbol
        self._series_cache.last_refresh_ts = now

        logger.info(
            "KALSHI_PUBLIC_SERIES_REFRESH count=%d assets=%s",
            len(by_symbol),
            sorted(by_symbol.keys()),
        )
        return by_symbol

    @staticmethod
    def _derive_asset_symbol(series_ticker: str) -> str:
        t = series_ticker.upper()
        # Strip leading KX and trailing timeframe code; adjust as needed.
        # KXBTC15M → BTC, KXETH15M → ETH, etc.
        if t.startswith("KX"):
            t = t[2:]
        # Drop common timeframe suffixes
        for suffix in ("15M", "H1", "D1", "W1", "1M", "Y"):
            if t.endswith(suffix):
                return t[: -len(suffix)]
        return t

    async def list_open_markets_for_series(
        self,
        series_ticker: str,
        min_close_ts: Optional[int] = None,
        max_close_ts: Optional[int] = None,
        limit: int = 1000,
    ) -> List[PublicMarketInfo]:
        """Public market discovery for a single series with cursor-based pagination.
        
        Per Kalshi API contract: series are advisory, not guaranteed to have markets.
        Empty responses (count=0) are valid states and should be treated as "no tradeable markets right now."
        
        Args:
            series_ticker: The series ticker (e.g., KXBTC15M)
            min_close_ts: Minimum close timestamp (Unix epoch seconds) - filters markets closing after this time
            max_close_ts: Maximum close timestamp (Unix epoch seconds) - filters markets closing before this time
            limit: Maximum number of markets to fetch per page
        """
        cursor = None
        all_markets: List[dict] = []
        
        # Cursor-based pagination to fetch all markets for the series
        while True:
            params = {"series_ticker": series_ticker, "status": "open"}
            if cursor:
                params["cursor"] = cursor
            if limit:
                params["limit"] = str(limit)
            if min_close_ts is not None:
                params["min_close_ts"] = str(min_close_ts)
            if max_close_ts is not None:
                params["max_close_ts"] = str(max_close_ts)

            try:
                http = self._get_http()
                r = await http.get("/markets", params=params)
                r.raise_for_status()
            except Exception as exc:
                logger.error(
                    "KALSHI_PUBLIC_MARKETS_ERROR series=%s cursor=%s err=%s",
                    series_ticker,
                    cursor[:20] if cursor else None,
                    exc,
                )
                # Don't fail hard - return what we have so far
                break

            data = r.json()
            markets = data.get("markets", [])
            all_markets.extend(markets)

            # Log first page response for diagnostics (raw API call before any filtering)
            if not cursor:
                # Include resolved base URL for diagnostics
                http = self._get_http()
                base_url = str(http.base_url) if hasattr(http, 'base_url') else "unknown"
                # Log all markets with close timestamps to check if multiple exist
                market_details = []
                for m in markets[:10]:
                    ticker = m.get("ticker") or m.get("market_ticker")
                    close_ts = m.get("close_ts") or m.get("close_time_ts")
                    market_details.append(f"{ticker}(close={close_ts})")
                logger.warning(
                    "KALSHI_API_RESPONSE series=%s base_url=%s status=%d markets_count=%d cursor=%s all_markets=%s",
                    series_ticker,
                    base_url,
                    r.status_code,
                    len(markets),
                    data.get("cursor", "none"),
                    market_details
                )
                # CRITICAL DIAGNOSTIC: Log if only 1 market returned - this might indicate API limitation
                if len(markets) == 1:
                    logger.warning(
                        "KALSHI_SINGLE_MARKET_WARNING series=%s only returned 1 market. This might be expected if only one 15m contract is currently open, or API limitation.",
                        series_ticker
                    )

            # Check for cursor to continue pagination
            cursor = data.get("cursor")
            if not cursor or len(markets) == 0:
                # No more pages or empty response
                logger.debug(
                    "KALSHI_PAGINATION_END series=%s cursor=%s markets_on_page=%d total_markets=%d",
                    series_ticker,
                    cursor,
                    len(markets),
                    len(all_markets)
                )
                break
        
        results: List[PublicMarketInfo] = []

        for m in all_markets:
            market_id = m.get("ticker") or m.get("market_ticker")
            if not market_id:
                continue
            close_ts = m.get("close_ts") or m.get("close_time_ts") or 0
            category = m.get("category", "")
            st = m.get("series_ticker") or series_ticker

            info = PublicMarketInfo(
                market_id=market_id,
                series_ticker=st,
                close_ts=int(close_ts),
                category=category,
                raw=m,
            )
            results.append(info)

        # Optional: local freshness filter
        if min_close_ts is not None:
            fresh = [m for m in results if m.close_ts >= min_close_ts]
            filtered_count = len(results) - len(fresh)
            # Log close_ts range for diagnostics
            close_times = [m.close_ts for m in results]
            min_close = min(close_times) if close_times else 0
            max_close = max(close_times) if close_times else 0
            logger.info(
                "KALSHI_FRESHNESS_FILTER series=%s initial_count=%d filtered_count=%d cutoff=%d close_min=%d close_max=%d",
                series_ticker,
                len(results),
                filtered_count,
                min_close_ts,
                min_close,
                max_close,
            )
            logger.info(
                "KALSHI_PUBLIC_MARKETS_SUCCESS series=%s total_raw=%d total_after_freshness=%d returned=%d status_filter=open",
                series_ticker,
                len(results),
                len(fresh),
                len(fresh),
            )
            return fresh
        
        logger.info(
            "KALSHI_FRESHNESS_FILTER_DISABLED series=%s",
            series_ticker,
        )
        logger.info(
            "KALSHI_PUBLIC_MARKETS_SUCCESS series=%s total_raw=%d total_after_freshness=%d returned=%d status_filter=open sample=%s",
            series_ticker,
            len(results),
            len(results),
            len(results),
            [m.market_id for m in results[:5]] if results else []
        )
        return results
