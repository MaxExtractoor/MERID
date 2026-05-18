"""KalshiMarketCatalog — Periodic market discovery and categorization.

Responsibilities:
1. Periodically call GET /markets and cache results
2. Group markets by category, event_ticker, series_ticker
3. Tag with MERID-friendly labels: asset, timeframe, type
4. Expose filter methods for agents and UI

Categories (from Kalshi):
  crypto, economics, financials, politics, climate, tech, sports, culture, science

MERID asset mapping:
  BTC, ETH, SOL, XRP, DOGE  (crypto)
  CPI, GDP, JOBS, RATES      (macro/economics)
  SPX, NDX, DJI              (financials/indices)
  WEATHER, CLIMATE            (climate)
  ELECTION, POLITICS          (politics)

Usage::

    catalog = get_market_catalog()
    await catalog.refresh()
    btc_markets = catalog.get_markets_by_asset("BTC")
    crypto_15m  = catalog.get_markets_by_category("crypto", timeframe="15m")
"""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set

from merid.event_venues.base import EventMarket, MarketFilter
from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.models import KalshiConfig
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.market_catalog")

# ── Process pool for CPU-intensive index building ────────────────────────
# Shared across all catalog instances to avoid creating too many processes.
# Max 2 workers since we typically only have one or two catalogs.

_PROCESS_POOL: Optional[ProcessPoolExecutor] = None


def _get_process_pool() -> ProcessPoolExecutor:
    """Get or create the shared process pool for catalog indexing."""
    global _PROCESS_POOL
    if _PROCESS_POOL is None:
        _PROCESS_POOL = ProcessPoolExecutor(max_workers=2)
    return _PROCESS_POOL


# ── Ticker-prefix → category mapping (primary detection) ────────────────
# Kalshi API v2 returns no 'category' field on markets. The event_ticker
# prefix is the most reliable signal for categorization.

_TICKER_CATEGORY_MAP: List[tuple] = [
    # Crypto
    (re.compile(r"^KX(?:BTC|BITCOIN)", re.I), "crypto", "BTC"),
    (re.compile(r"^KX(?:ETH|ETHEREUM)", re.I), "crypto", "ETH"),
    (re.compile(r"^KX(?:SOL|SOLANA)", re.I), "crypto", "SOL"),
    (re.compile(r"^KX(?:XRP|RIPPLE)", re.I), "crypto", "XRP"),
    (re.compile(r"^KX(?:DOGE|DOGECOIN)", re.I), "crypto", "DOGE"),
    (re.compile(r"^KXCRYPTO", re.I), "crypto", None),
    # Financials / indices
    (re.compile(r"^KX(?:SPX|SPY|SP500)", re.I), "financials", "SPX"),
    (re.compile(r"^KX(?:NDX|QQQ|NASDAQ)", re.I), "financials", "NDX"),
    (re.compile(r"^KX(?:DJI|DJIA|DOW)", re.I), "financials", "DJI"),
    (re.compile(r"^KX(?:RUSSELL|RUT|IWM)", re.I), "financials", None),
    (re.compile(r"^KXFINANCIALS", re.I), "financials", None),
    (re.compile(r"^KXSTOCK", re.I), "financials", None),
    # Economics / macro
    (re.compile(r"^KXCPI", re.I), "economics", "CPI"),
    (re.compile(r"^KXGDP", re.I), "economics", "GDP"),
    (re.compile(r"^KX(?:JOBS|NFP|NONFARM|PAYROLL|UNEMPLOYMENT)", re.I), "economics", "JOBS"),
    (re.compile(r"^KX(?:FED|FOMC|RATE)", re.I), "economics", "RATES"),
    (re.compile(r"^KXECON", re.I), "economics", None),
    # Energy / commodities (NEW)
    (re.compile(r"^KX(?:ERCOT|ELECTRICITY|GRID)", re.I), "energy", "ERCOT"),
    (re.compile(r"^KX(?:OIL|WTI|BRENT|CRUDE)", re.I), "energy", "OIL"),
    (re.compile(r"^KX(?:GAS|NATGAS|LNG)", re.I), "energy", "GAS"),
    (re.compile(r"^KX(?:CARBON|EMISSION)", re.I), "energy", "CARBON"),
    (re.compile(r"^KX(?:RENEW|SOLAR|WIND)", re.I), "energy", "RENEWABLE"),
    (re.compile(r"^KXENERGY", re.I), "energy", None),
    # Politics
    (re.compile(r"^KX(?:ELECTION|PRES|SENATE|CONGRESS|GOV|POLITICS|SCOTUS|TRUMP|BIDEN)", re.I), "politics", "ELECTION"),
    # Climate / weather
    (re.compile(r"^KX(?:WEATHER|TEMP|HURRICANE|TORNADO)", re.I), "climate", "WEATHER"),
    (re.compile(r"^KX(?:CLIMATE)", re.I), "climate", "CLIMATE"),
    # Sports — broad patterns
    (re.compile(r"^KX(?:NBA|NBAGAME|NBAPTS|NBASPREAD|NBAPROP)", re.I), "sports", "NBA"),
    (re.compile(r"^KX(?:NFL|NFLGAME|NFLPTS|NFLSPREAD|NFLPROP)", re.I), "sports", "NFL"),
    (re.compile(r"^KX(?:MLB|MLBGAME|MLBPROP)", re.I), "sports", "MLB"),
    (re.compile(r"^KX(?:NHL|NHLGAME|NHLPROP)", re.I), "sports", "NHL"),
    (re.compile(r"^KX(?:SOCCER|MLS|EPL|UEFA|FIFA)", re.I), "sports", "SOCCER"),
    (re.compile(r"^KX(?:TENNIS|ATP|WTA)", re.I), "sports", "TENNIS"),
    (re.compile(r"^KX(?:GOLF|PGA)", re.I), "sports", "GOLF"),
    (re.compile(r"^KX(?:MMA|UFC|BOXING)", re.I), "sports", "MMA"),
    (re.compile(r"^KX(?:ESPORT)", re.I), "sports", "ESPORTS"),
    (re.compile(r"^KXMVESPORT", re.I), "sports", "SPORTS_COMBO"),
    (re.compile(r"^KXSPORT", re.I), "sports", None),
    # Tech
    (re.compile(r"^KXTECH", re.I), "tech", None),
    (re.compile(r"^KX(?:AI|OPENAI|GOOGLE|APPLE|META|MSFT|NVDA)", re.I), "tech", None),
    # Culture / entertainment
    (re.compile(r"^KX(?:CULTURE|ENTERTAINMENT|OSCAR|GRAMMY|EMMY|MOVIE)", re.I), "culture", None),
    # Science
    (re.compile(r"^KX(?:SCIENCE|SPACE|NASA|SPACEX)", re.I), "science", None),
]

# ── Asset detection patterns (text-based, secondary) ──────────────────────

_ASSET_PATTERNS: Dict[str, List[re.Pattern]] = {
    "BTC": [re.compile(r"\bBTC\b|bitcoin", re.I)],
    "ETH": [re.compile(r"\bETH\b|ethereum|ether\b", re.I)],
    "SOL": [re.compile(r"\bSOL\b|solana", re.I)],
    "XRP": [re.compile(r"\bXRP\b|ripple", re.I)],
    "DOGE": [re.compile(r"\bDOGE\b|dogecoin", re.I)],
    "PEPE": [re.compile(r"\bPEPE\b", re.I)],
    "WIF": [re.compile(r"\bWIF\b|dogwifhat", re.I)],
    "CPI": [re.compile(r"\bCPI\b|consumer price|inflation", re.I)],
    "GDP": [re.compile(r"\bGDP\b|gross domestic", re.I)],
    "JOBS": [re.compile(r"\bjobs?\b|nonfarm|unemployment|payroll", re.I)],
    "RATES": [re.compile(r"\bfed\s*fund|interest rate|fomc|fed\b.*rate", re.I)],
    "SPX": [re.compile(r"\bS&P\s*500\b|\bSPX\b|\bSPY\b", re.I)],
    "NDX": [re.compile(r"\bNASDAQ\b|\bNDX\b|\bQQQ\b", re.I)],
    "DJI": [re.compile(r"\bDow\b|\bDJI\b|\bDJIA\b", re.I)],
    "WEATHER": [re.compile(r"\bweather\b|temperature|hurricane|tornado", re.I)],
    "CLIMATE": [re.compile(r"\bclimate\b", re.I)],
    "ELECTION": [re.compile(r"\belection\b|president|congress|senate|governor", re.I)],
    # Energy assets (NEW)
    "ERCOT": [re.compile(r"\bERCOT\b|texas\s+grid|electricity\s+price", re.I)],
    "OIL": [re.compile(r"\boil\b|crude|WTI|brent|petroleum|barrel", re.I)],
    "GAS": [re.compile(r"\bnatural\s+gas\b|LNG|gas\s+price|natgas", re.I)],
    "CARBON": [re.compile(r"\bcarbon\b|emission|carbon\s+credit", re.I)],
    "RENEWABLE": [re.compile(r"\brenewable\b|solar|wind\s+power|green\s+energy", re.I)],
    # Sports assets (detected from title text)
    "NBA": [re.compile(r"\bNBA\b", re.I)],
    "NFL": [re.compile(r"\bNFL\b", re.I)],
    "MLB": [re.compile(r"\bMLB\b", re.I)],
    "NHL": [re.compile(r"\bNHL\b", re.I)],
}

# ── Timeframe detection ─────────────────────────────────────────────────

_TIMEFRAME_PATTERNS = [
    # 15m patterns - aggressive matching for critical short-term markets
    (re.compile(r"15[\s-]*min|15M|FIFTEEN", re.I), "15m"),
    (re.compile(r"hourly|1[\s-]*hour|60[\s-]*min", re.I), "1h"),
    (re.compile(r"daily|end[\s-]*of[\s-]*day|eod|close[\s-]*today", re.I), "daily"),
    (re.compile(r"weekly|end[\s-]*of[\s-]*week|eow", re.I), "weekly"),
    (re.compile(r"monthly|end[\s-]*of[\s-]*month|eom", re.I), "monthly"),
    (re.compile(r"year|annual|eoy|end[\s-]*of[\s-]*year", re.I), "annual"),
    (re.compile(r"pre[\s-]*market|premarket", re.I), "pre-market"),
]

# ── Market type detection ───────────────────────────────────────────────

_TYPE_PATTERNS = [
    (re.compile(r"above|below|over|under|range|between", re.I), "range"),
    (re.compile(r"will.*reach|hit|cross", re.I), "binary"),
]


@dataclass
class CatalogMarket:
    """Enriched market with MERID-specific tags."""
    market: EventMarket
    asset: Optional[str] = None
    timeframe: Optional[str] = None
    market_type: str = "binary"
    category: Optional[str] = None
    event_ticker: Optional[str] = None
    series_ticker: Optional[str] = None
    strike_price: Optional[float] = None
    floor_strike: Optional[float] = None
    cap_strike: Optional[float] = None
    expires_at: Optional[datetime] = None
    minutes_to_expiry: Optional[float] = None
    direction: Optional[str] = None  # "up" or "down" for crypto markets


@dataclass
class CatalogSnapshot:
    """Point-in-time snapshot of the catalog."""
    markets: List[CatalogMarket] = field(default_factory=list)
    refreshed_at: Optional[datetime] = None
    market_count: int = 0
    by_category: Dict[str, int] = field(default_factory=dict)
    by_asset: Dict[str, int] = field(default_factory=dict)
    by_timeframe: Dict[str, int] = field(default_factory=dict)


class KalshiMarketCatalog:
    """Discovers, caches, and categorizes all Kalshi markets.

    Thread-safe via asyncio lock. Refresh interval configurable.
    """

    def __init__(
        self,
        client: Optional[KalshiVenueClient] = None,
        refresh_interval_s: float = 300.0,
        max_markets: int = 2000,
        use_process_indexing: bool = True,
    ):
        self._client = client or KalshiVenueClient(KalshiConfig())
        self._refresh_interval = refresh_interval_s
        self._max_markets = max_markets
        self._use_process_indexing = use_process_indexing

        self._markets: List[CatalogMarket] = []
        self._by_category: Dict[str, List[CatalogMarket]] = defaultdict(list)
        self._by_asset: Dict[str, List[CatalogMarket]] = defaultdict(list)
        self._by_timeframe: Dict[str, List[CatalogMarket]] = defaultdict(list)
        self._by_ticker: Dict[str, CatalogMarket] = {}

        # Track active/subscribed markets to scope periodic refreshes
        self._active_tickers: Set[str] = set()

        self._last_refresh: Optional[datetime] = None
        self._refresh_count: int = 0
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start periodic refresh loop with desynchronized initial delay."""
        if self._task and not self._task.done():
            return
        self._shutdown.clear()
        await self.refresh()
        self._task = asyncio.create_task(self._refresh_loop(), name="kalshi-catalog-refresh")
        logger.info(f"KalshiMarketCatalog started — {len(self._markets)} markets cached")

    async def stop(self) -> None:
        """Stop periodic refresh."""
        self._shutdown.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("KalshiMarketCatalog stopped")

    async def _refresh_loop(self) -> None:
        """Periodic refresh loop with desynchronized schedule to avoid T+5min storms."""
        import random
        # Add random initial offset (30-90 seconds) to desynchronize from other 5-min tasks
        initial_offset = random.uniform(30.0, 90.0)
        logger.debug(f"Catalog refresh loop: initial offset {initial_offset:.1f}s")
        await asyncio.sleep(initial_offset)

        while not self._shutdown.is_set():
            try:
                await asyncio.sleep(self._refresh_interval)
                if self._shutdown.is_set():
                    break
                await self.refresh()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"Catalog refresh error: {exc}")

    # ── Core refresh ─────────────────────────────────────────────────────

    async def refresh(self) -> int:
        """Fetch all active markets from Kalshi and rebuild indexes.

        Startup (refresh_count == 0):
        - Performs full enrichment and indexing on all markets
        - Optionally uses ProcessPoolExecutor for CPU-intensive index building

        Periodic (refresh_count > 0):
        - If active_tickers is empty, performs full refresh (fallback)
        - Otherwise, only enriches active/subscribed markets for efficiency
        - Reduces P95 lag by avoiding 5000-market processing every 5 minutes

        Returns:
            Number of markets cataloged.
        """
        async with self._lock:
            is_startup = (self._refresh_count == 0)

            try:
                result = await self._client.list_markets_result(
                    MarketFilter(active_only=True, limit=self._max_markets)
                )
                if not result.success:
                    logger.warning(
                        "Failed to fetch markets: %s (status=%s, retries=%s, circuit_open=%s)",
                        result.error, getattr(result, 'status_code', None),
                        result.retries, getattr(result, 'circuit_open', False),
                    )
                    return len(self._markets)
                raw_markets = result.data
            except Exception as exc:
                logger.warning(f"Failed to fetch markets: {exc}")
                return len(self._markets)

            now = datetime.now(timezone.utc)

            if is_startup:
                # ── Startup refresh: full enrichment ──────────────────────────
                logger.info(f"Catalog startup refresh: processing {len(raw_markets)} markets")

                if self._use_process_indexing and len(raw_markets) > 100:
                    # Use ProcessPoolExecutor for CPU-intensive index building
                    enriched = await self._refresh_with_process_pool(raw_markets, now)
                else:
                    # Fallback to synchronous enrichment for small catalogs or tests
                    enriched = await self._refresh_synchronous(raw_markets, now)
            else:
                # ── Periodic refresh: scoped to active markets ─────────────────
                if self._active_tickers:
                    # Scope to active markets only
                    active_raw = [m for m in raw_markets if m.market_id in self._active_tickers]
                    logger.debug(
                        f"Catalog periodic refresh: scoped to {len(active_raw)}/{len(raw_markets)} active markets"
                    )
                    # For periodic refreshes, always use synchronous (fast for ~400 markets)
                    enriched = await self._refresh_synchronous(active_raw, now)

                    # Preserve existing enriched markets not in active set
                    existing_inactive = [m for m in self._markets if m.market.market_id not in self._active_tickers]
                    enriched.extend(existing_inactive)
                else:
                    # Fallback: no active tickers tracked, do full refresh
                    logger.warning(
                        "Catalog periodic refresh: no active tickers tracked, falling back to full refresh"
                    )
                    enriched = await self._refresh_synchronous(raw_markets, now)

            # ── Rebuild indexes ───────────────────────────────────────────────
            cat_idx: Dict[str, List[CatalogMarket]] = defaultdict(list)
            asset_idx: Dict[str, List[CatalogMarket]] = defaultdict(list)
            tf_idx: Dict[str, List[CatalogMarket]] = defaultdict(list)
            ticker_idx: Dict[str, CatalogMarket] = {}

            categories_found = set()
            assets_found = set()

            for cm in enriched:
                ticker_idx[cm.market.market_id] = cm
                if cm.category:
                    cat_idx[cm.category].append(cm)
                    categories_found.add(cm.category)
                if cm.asset:
                    asset_idx[cm.asset].append(cm)
                    assets_found.add(cm.asset)
                if cm.timeframe:
                    tf_idx[cm.timeframe].append(cm)

            self._markets = enriched
            self._by_category = cat_idx
            self._by_asset = asset_idx
            self._by_timeframe = tf_idx
            self._by_ticker = ticker_idx
            self._last_refresh = now
            self._refresh_count += 1

            _log = logger.info if enriched else logger.debug
            _log(
                f"Catalog refreshed (#{self._refresh_count}): {len(enriched)} markets, "
                f"{len(cat_idx)} categories, {len(asset_idx)} assets"
            )

            # Per-asset/timeframe INFO logging
            if is_startup or self._refresh_count % 5 == 0:  # Log every 5th periodic refresh
                _CRYPTO_ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")
                for _asset in _CRYPTO_ASSETS:
                    _asset_mkts = asset_idx.get(_asset, [])
                    if _asset_mkts:
                        _15m = sum(1 for m in _asset_mkts if m.timeframe == "15m")
                        _1h = sum(1 for m in _asset_mkts if m.timeframe == "1h")
                        _daily = sum(1 for m in _asset_mkts if m.timeframe == "daily")
                        _weekly = sum(1 for m in _asset_mkts if m.timeframe == "weekly")
                        _monthly = sum(1 for m in _asset_mkts if m.timeframe == "monthly")
                        logger.info(
                            "Catalog %s: total=%d  15m=%d  1h=%d  daily=%d  weekly=%d  monthly=%d",
                            _asset, len(_asset_mkts), _15m, _1h, _daily, _weekly, _monthly,
                        )

            return len(enriched)

    async def _refresh_synchronous(
        self, raw_markets: List[EventMarket], now: datetime
    ) -> List[CatalogMarket]:
        """Synchronous market enrichment (fallback or small catalogs)."""
        enriched: List[CatalogMarket] = []
        for mkt in raw_markets:
            cm = self._enrich(mkt, now)
            enriched.append(cm)
        return enriched

    async def _refresh_with_process_pool(
        self, raw_markets: List[EventMarket], now: datetime
    ) -> List[CatalogMarket]:
        """Process-pool-based enrichment to bypass GIL for CPU-heavy work."""
        try:
            from merid.event_venues.kalshi.catalog_indexer import build_indexes

            # Prepare serializable data for the worker process
            raw_dicts = []
            for m in raw_markets:
                raw_dicts.append({
                    "market_id": m.market_id,
                    "event_ticker": m.raw_data.get("event_ticker") if m.raw_data else "",
                    "series_ticker": m.raw_data.get("series_ticker") if m.raw_data else "",
                    "question": m.question or "",
                    "description": m.description or "",
                    "category": m.category or "",
                    "end_date": m.end_date.isoformat() if m.end_date else None,
                })

            now_iso = now.isoformat()

            # Run CPU-intensive indexing in a separate process
            loop = asyncio.get_running_loop()
            pool = _get_process_pool()
            index_result = await loop.run_in_executor(
                pool, build_indexes, raw_dicts, now_iso
            )

            # Merge index results with EventMarket objects
            ticker_to_tags = {
                item["ticker"]: item for item in index_result["enriched_markets"]
            }

            enriched: List[CatalogMarket] = []
            for mkt in raw_markets:
                tags = ticker_to_tags.get(mkt.market_id, {})
                # Still need to call _enrich for strikes and detailed parsing
                # but the heavy regex work is already done
                cm = self._enrich(mkt, now)
                # Override with process-computed tags
                if tags.get("category"):
                    cm.category = tags["category"]
                if tags.get("asset"):
                    cm.asset = tags["asset"]
                if tags.get("timeframe"):
                    cm.timeframe = tags["timeframe"]
                enriched.append(cm)

            logger.debug(
                f"Process-pool indexing completed: {len(enriched)} markets enriched"
            )
            return enriched
        except Exception as exc:
            logger.warning(f"Process-pool indexing failed: {exc}, falling back to synchronous")
            return await self._refresh_synchronous(raw_markets, now)

    # ── Enrichment ───────────────────────────────────────────────────────

    def _enrich(self, mkt: EventMarket, now: datetime) -> CatalogMarket:
        """Tag a raw EventMarket with asset, timeframe, type, and strikes."""
        # Extract event_ticker / series_ticker from raw_data
        raw = mkt.raw_data or {}
        event_ticker = raw.get("event_ticker", "") or ""
        series_ticker = raw.get("series_ticker", "") or ""

        # 1. Primary detection: ticker prefix → category + asset
        ticker_category, ticker_asset = self._detect_from_ticker(event_ticker or mkt.market_id)

        # 2. Secondary detection: text-based patterns
        text = f"{mkt.market_id} {event_ticker} {mkt.question or ''} {mkt.description or ''} {mkt.category or ''}"
        text_asset = self._detect_asset(text)
        timeframe = self._detect_timeframe(text, mkt.end_date, now)
        market_type = self._detect_type(text)
        strikes = self._detect_strikes(text)

        # Merge: ticker-prefix wins for category; first non-None wins for asset
        category = mkt.category or ticker_category
        asset = ticker_asset or text_asset

        minutes_to_expiry = None
        if mkt.end_date and mkt.end_date > now:
            minutes_to_expiry = (mkt.end_date - now).total_seconds() / 60.0

        # 3. Parse direction for crypto up/down markets
        direction = None
        if category == "crypto" and asset:
            from merid.event_venues.kalshi.direction_semantics import parse_kalshi_crypto_direction
            direction = parse_kalshi_crypto_direction(
                ticker=event_ticker or mkt.market_id,
                title=mkt.question,
                description=mkt.description
            )

        return CatalogMarket(
            market=mkt,
            asset=asset,
            timeframe=timeframe,
            market_type=market_type,
            category=category,
            event_ticker=event_ticker or None,
            series_ticker=series_ticker or None,
            strike_price=strikes.get("strike"),
            floor_strike=strikes.get("floor"),
            cap_strike=strikes.get("cap"),
            expires_at=mkt.end_date,
            minutes_to_expiry=minutes_to_expiry,
            direction=direction,
        )

    @staticmethod
    def _detect_strikes(text: str) -> Dict[str, float]:
        """Extract strike prices from market text and ticker components.

        Supports:
        1. Ticker-embedded strikes: KXETH-26APR0722-T2839.99 → strike=2839.99
        2. Ticker-embedded strikes with decimals: KXXRP-15M-T2.0399 → strike=2.0399
        3. Text-based strikes: "above 50,000" → strike=50000
        4. Range strikes: "between 100 and 200" → floor=100, cap=200
        """
        res = {}

        # PRIORITY 1: Parse ticker-embedded strikes (-T<number>)
        # Format: KXETH-26APR0722-T2839.99 or KXXRP-15M-T2.0399
        ticker_strike_match = re.search(r"-T([\d]+\.?[\d]*)", text, re.I)
        if ticker_strike_match:
            try:
                strike_val = float(ticker_strike_match.group(1))
                res["strike"] = strike_val
                logger.debug(
                    "[SPOT-STRIKE] Parsed ticker-embedded strike: %s → %.4f",
                    ticker_strike_match.group(0), strike_val
                )
            except ValueError as e:
                logger.warning(
                    "[SPOT-STRIKE] Failed to parse ticker strike '%s': %s",
                    ticker_strike_match.group(0), e
                )

        # FALLBACK 2: Text-based strike extraction (legacy support)
        # Only apply if ticker parsing didn't find a strike
        if "strike" not in res:
            # Simple "above/below X"
            strike_match = re.search(r"(?:above|below|at|over|under)\s*\$?([\d,]+\.?\d*)", text, re.I)
            if strike_match:
                try:
                    res["strike"] = float(strike_match.group(1).replace(",", ""))
                except ValueError:
                    pass

        # Range "between X and Y"
        range_match = re.search(r"between\s*\$?([\d,]+\.?\d*)\s*and\s*\$?([\d,]+\.?\d*)", text, re.I)
        if range_match:
            try:
                res["floor"] = float(range_match.group(1).replace(",", ""))
                res["cap"] = float(range_match.group(2).replace(",", ""))
            except ValueError:
                pass

        return res

    @staticmethod
    def _detect_from_ticker(ticker: str) -> tuple:
        """Detect category and asset from Kalshi event_ticker prefix.

        Returns (category, asset) — either may be None.
        """
        for pat, category, asset in _TICKER_CATEGORY_MAP:
            if pat.search(ticker):
                return category, asset
        return None, None

    @staticmethod
    def _detect_asset(text: str) -> Optional[str]:
        for asset, patterns in _ASSET_PATTERNS.items():
            for pat in patterns:
                if pat.search(text):
                    return asset
        return None

    @staticmethod
    def _detect_timeframe(
        text: str,
        end_date: Optional[datetime],
        now: datetime,
    ) -> Optional[str]:
        # First try text patterns
        for pat, tf in _TIMEFRAME_PATTERNS:
            if pat.search(text):
                return tf

        # Infer from time to expiry
        if end_date and end_date > now:
            delta = end_date - now
            minutes = delta.total_seconds() / 60.0
            if minutes <= 20:
                return "15m"
            elif minutes <= 90:
                return "1h"
            elif minutes <= 60 * 24:
                return "daily"
            elif minutes <= 60 * 24 * 7:
                return "weekly"
            elif minutes <= 60 * 24 * 31:
                return "monthly"
            else:
                return "annual"
        return None

    @staticmethod
    def _detect_type(text: str) -> str:
        for pat, mtype in _TYPE_PATTERNS:
            if pat.search(text):
                return mtype
        return "binary"

    # ── Query methods ────────────────────────────────────────────────────

    def get_all_markets(self) -> List[CatalogMarket]:
        """Return all cached markets."""
        return list(self._markets)

    def get_market(self, ticker: str) -> Optional[CatalogMarket]:
        """Look up a single market by ticker."""
        return self._by_ticker.get(ticker)

    def get_markets_by_category(
        self,
        category: str,
        *,
        timeframe: Optional[str] = None,
        asset: Optional[str] = None,
    ) -> List[CatalogMarket]:
        """Filter markets by category with optional sub-filters."""
        results = self._by_category.get(category, [])
        if timeframe:
            results = [m for m in results if m.timeframe == timeframe]
        if asset:
            results = [m for m in results if m.asset == asset]
        return results

    def get_markets_by_asset(
        self,
        asset: str,
        *,
        timeframe: Optional[str] = None,
    ) -> List[CatalogMarket]:
        """Filter markets by MERID asset tag."""
        results = self._by_asset.get(asset, [])
        if timeframe:
            results = [m for m in results if m.timeframe == timeframe]
        return results

    def get_markets_by_timeframe(self, timeframe: str) -> List[CatalogMarket]:
        """Filter markets by timeframe."""
        return self._by_timeframe.get(timeframe, [])

    def get_markets_by_event(self, event_keyword: str) -> List[CatalogMarket]:
        """Search markets by event keyword in question/description."""
        kw = event_keyword.lower()
        return [
            m for m in self._markets
            if kw in m.market.question.lower() or kw in m.market.description.lower()
        ]

    def get_expiring_soon(self, within_minutes: float = 60.0) -> List[CatalogMarket]:
        """Markets expiring within N minutes."""
        return [
            m for m in self._markets
            if m.minutes_to_expiry is not None and 0 < m.minutes_to_expiry <= within_minutes
        ]

    def get_markets_by_min_volume(self, min_volume: float) -> List[CatalogMarket]:
        """Filter markets with volume >= min_volume (USD or contracts)."""
        return [
            m for m in self._markets
            if (float(m.market.volume) if m.market.volume else 0) >= min_volume
        ]

    def sort_by_volume(
        self,
        markets: Optional[List[CatalogMarket]] = None,
        descending: bool = True,
    ) -> List[CatalogMarket]:
        """Sort markets by volume. Defaults to all cached markets."""
        source = markets if markets is not None else list(self._markets)
        return sorted(
            source,
            key=lambda m: float(m.market.volume) if m.market.volume else 0,
            reverse=descending,
        )

    def categories(self) -> List[str]:
        """List all known categories."""
        return sorted(self._by_category.keys())

    def assets(self) -> List[str]:
        """List all detected assets."""
        return sorted(self._by_asset.keys())

    def timeframes(self) -> List[str]:
        """List all detected timeframes."""
        return sorted(self._by_timeframe.keys())

    # ── Active market tracking ───────────────────────────────────────────

    def mark_active(self, ticker: str) -> None:
        """Mark a ticker as active/subscribed for scoped periodic refreshes."""
        self._active_tickers.add(ticker)

    def mark_inactive(self, ticker: str) -> None:
        """Remove a ticker from active set."""
        self._active_tickers.discard(ticker)

    def get_active_count(self) -> int:
        """Return number of active/subscribed tickers."""
        return len(self._active_tickers)

    # ── Status ───────────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """JSON-serializable catalog status."""
        return {
            "market_count": len(self._markets),
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
            "refresh_count": self._refresh_count,
            "categories": {k: len(v) for k, v in self._by_category.items()},
            "assets": {k: len(v) for k, v in self._by_asset.items()},
            "timeframes": {k: len(v) for k, v in self._by_timeframe.items()},
            "running": self._task is not None and not self._task.done(),
        }

    def snapshot(self) -> CatalogSnapshot:
        """Return a point-in-time snapshot."""
        return CatalogSnapshot(
            markets=list(self._markets),
            refreshed_at=self._last_refresh,
            market_count=len(self._markets),
            by_category={k: len(v) for k, v in self._by_category.items()},
            by_asset={k: len(v) for k, v in self._by_asset.items()},
            by_timeframe={k: len(v) for k, v in self._by_timeframe.items()},
        )


# ── Singleton ────────────────────────────────────────────────────────────

_catalog: Optional[KalshiMarketCatalog] = None


def get_market_catalog() -> KalshiMarketCatalog:
    """Get or create the singleton KalshiMarketCatalog."""
    global _catalog
    if _catalog is None:
        _catalog = KalshiMarketCatalog()
    return _catalog
