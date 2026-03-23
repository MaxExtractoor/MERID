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
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set

from merid.event_venues.base import EventMarket, MarketFilter
from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.models import KalshiConfig
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.market_catalog")

_CRYPTO_ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")
_CRYPTO_TIMEFRAMES = ("15m", "1h", "daily", "weekly", "monthly", "yearly")


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
    # Politics
    (re.compile(r"^KX(?:ELECTION|PRES|SENATE|CONGRESS|GOV|POLITICS|SCOTUS|TRUMP|BIDEN)", re.I), "politics", "ELECTION"),
    # Climate / weather
    (re.compile(r"^KX(?:WEATHER|TEMP|HURRICANE|TORNADO)", re.I), "climate", "WEATHER"),
    (re.compile(r"^KX(?:CLIMATE|CARBON|EMISSION)", re.I), "climate", "CLIMATE"),
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
    "CLIMATE": [re.compile(r"\bclimate\b|carbon|emissions", re.I)],
    "ELECTION": [re.compile(r"\belection\b|president|congress|senate|governor", re.I)],
    # Sports assets (detected from title text)
    "NBA": [re.compile(r"\bNBA\b", re.I)],
    "NFL": [re.compile(r"\bNFL\b", re.I)],
    "MLB": [re.compile(r"\bMLB\b", re.I)],
    "NHL": [re.compile(r"\bNHL\b", re.I)],
}

# ── Timeframe detection ─────────────────────────────────────────────────

_TIMEFRAME_PATTERNS = [
    (re.compile(r"15[\s-]*min", re.I), "15m"),
    (re.compile(r"hourly|1[\s-]*hour|60[\s-]*min", re.I), "1h"),
    (re.compile(r"daily|end[\s-]*of[\s-]*day|eod|close[\s-]*today", re.I), "daily"),
    (re.compile(r"weekly|end[\s-]*of[\s-]*week|eow", re.I), "weekly"),
    (re.compile(r"monthly|end[\s-]*of[\s-]*month|eom", re.I), "monthly"),
    (re.compile(r"year|annual|eoy|end[\s-]*of[\s-]*year", re.I), "yearly"),
    (re.compile(r"pre[\s-]*market|premarket", re.I), "pre-market"),
]

# ── Market type detection ───────────────────────────────────────────────

_TYPE_PATTERNS = [
    (re.compile(r"above|below|over|under|range|between", re.I), "range"),
    (re.compile(r"will.*reach|hit|cross", re.I), "binary"),
]

_CRYPTO_TF_PATTERNS = [
    (re.compile(r"15M|15[-\s]*MIN", re.I), "15m"),
    (re.compile(r"\b1H\b|\bH1\b|-H\b|HOURLY|HOUR", re.I), "1h"),
    (re.compile(r"\bDAILY\b|\b1D\b|-D\b", re.I), "daily"),
    (re.compile(r"\bWEEK(LY)?\b|-W\b", re.I), "weekly"),
    (re.compile(r"\bMONTH(LY)?\b|\b-?MTH\b", re.I), "monthly"),
    (re.compile(r"\bYEAR(LY)?\b|\b-?Y\b", re.I), "yearly"),
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


@dataclass
class CatalogSnapshot:
    """Point-in-time snapshot of the catalog."""
    markets: List[CatalogMarket] = field(default_factory=list)
    refreshed_at: Optional[datetime] = None
    market_count: int = 0
    by_category: Dict[str, int] = field(default_factory=dict)
    by_asset: Dict[str, int] = field(default_factory=dict)
    by_timeframe: Dict[str, int] = field(default_factory=dict)
    by_asset_timeframe: Dict[str, Dict[str, int]] = field(default_factory=dict)


class KalshiMarketCatalog:
    """Discovers, caches, and categorizes all Kalshi markets.

    Thread-safe via asyncio lock. Refresh interval configurable.
    """

    def __init__(
        self,
        client: Optional[KalshiVenueClient] = None,
        refresh_interval_s: float = 300.0,
        max_markets: int = 2000,
    ):
        self._client = client or KalshiVenueClient(KalshiConfig())
        self._refresh_interval = refresh_interval_s
        self._max_markets = max_markets

        self._markets: List[CatalogMarket] = []
        self._by_category: Dict[str, List[CatalogMarket]] = defaultdict(list)
        self._by_asset: Dict[str, List[CatalogMarket]] = defaultdict(list)
        self._by_timeframe: Dict[str, List[CatalogMarket]] = defaultdict(list)
        self._by_ticker: Dict[str, CatalogMarket] = {}

        self._last_refresh: Optional[datetime] = None
        self._refresh_count: int = 0
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start periodic refresh loop."""
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

        Returns:
            Number of markets cataloged.
        """
        async with self._lock:
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
            enriched: List[CatalogMarket] = []
            cat_idx: Dict[str, List[CatalogMarket]] = defaultdict(list)
            asset_idx: Dict[str, List[CatalogMarket]] = defaultdict(list)
            tf_idx: Dict[str, List[CatalogMarket]] = defaultdict(list)
            ticker_idx: Dict[str, CatalogMarket] = {}

            categories_found = set()
            assets_found = set()
            
            for mkt in raw_markets:
                cm = self._enrich(mkt, now)
                enriched.append(cm)
                ticker_idx[mkt.market_id] = cm

                if cm.category:
                    cat_idx[cm.category].append(cm)
                    categories_found.add(cm.category)
                if cm.asset:
                    asset_idx[cm.asset].append(cm)
                    assets_found.add(cm.asset)
                if cm.timeframe:
                    tf_idx[cm.timeframe].append(cm)
            
            # Debug logging for first refresh to see what's happening
            if self._refresh_count == 0 and enriched:
                sample = enriched[0]
                logger.debug(
                    f"Sample market: ticker={sample.market.market_id}, "
                    f"category={sample.category}, asset={sample.asset}, "
                    f"question={sample.market.question[:50]}..."
                )
                if categories_found:
                    logger.info(f"Categories detected: {sorted(categories_found)}")
                if assets_found:
                    logger.info(f"Assets detected: {sorted(assets_found)}")

            self._markets = enriched
            self._by_category = cat_idx
            self._by_asset = asset_idx
            self._by_timeframe = tf_idx
            self._by_ticker = ticker_idx
            self._last_refresh = now
            self._refresh_count += 1

            if cat_idx.get("crypto"):
                crypto_counts = self.counts_by_asset_timeframe(_CRYPTO_ASSETS, _CRYPTO_TIMEFRAMES)
                msg_parts = []
                for asset in _CRYPTO_ASSETS:
                    total = len(asset_idx.get(asset, []))
                    tf_counts = crypto_counts.get(asset, {})
                    tf_snippets = ", ".join(
                        f"{tf}={tf_counts.get(tf, 0)}"
                        for tf in ("15m", "1h", "daily")
                    )
                    msg_parts.append(f"{asset}:{total} ({tf_snippets})")
                logger.info("Catalog crypto coverage: %s", " | ".join(msg_parts))

            _log = logger.info if enriched else logger.debug
            _log(
                f"Catalog refreshed: {len(enriched)} markets, "
                f"{len(cat_idx)} categories, {len(asset_idx)} assets"
            )
            return len(enriched)

    # ── Enrichment ───────────────────────────────────────────────────────

    def _enrich(self, mkt: EventMarket, now: datetime) -> CatalogMarket:
        """Tag a raw EventMarket with asset, timeframe, type, and strikes."""
        # Extract event_ticker / series_ticker from raw_data
        raw = mkt.raw_data or {}
        event_ticker = raw.get("event_ticker", "") or ""
        series_ticker = raw.get("series_ticker", "") or ""

        # Crypto-specific detection from tickers (first-class path)
        crypto_asset, crypto_tf = self._detect_crypto_from_tickers(event_ticker, series_ticker)

        # 1. Primary detection: ticker prefix → category + asset
        ticker_category, ticker_asset = self._detect_from_ticker(event_ticker or mkt.market_id)

        # 2. Secondary detection: text-based patterns
        text = f"{mkt.market_id} {event_ticker} {mkt.question or ''} {mkt.description or ''} {mkt.category or ''}"
        text_asset = self._detect_asset(text)
        timeframe = crypto_tf or self._detect_timeframe(text, mkt.end_date, now)
        market_type = self._detect_type(text)
        strikes = self._detect_strikes(text)

        # Merge: ticker-prefix wins for category; first non-None wins for asset
        category = mkt.category or ticker_category
        asset = crypto_asset or ticker_asset or text_asset

        minutes_to_expiry = None
        if mkt.end_date and mkt.end_date > now:
            minutes_to_expiry = (mkt.end_date - now).total_seconds() / 60.0

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
        )

    @staticmethod
    def _detect_strikes(text: str) -> Dict[str, float]:
        """Extract strike prices from market text."""
        res = {}
        # Patterns for various strike formats
        # Examples: "above 50,000", "below $1.50", "between 100 and 200"
        
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
                return "yearly"
        return None

    @staticmethod
    def _detect_type(text: str) -> str:
        for pat, mtype in _TYPE_PATTERNS:
            if pat.search(text):
                return mtype
        return "binary"

    @staticmethod
    def _detect_crypto_from_tickers(event_ticker: str, series_ticker: str) -> tuple[Optional[str], Optional[str]]:
        """Detect crypto asset/timeframe directly from Kalshi tickers."""
        ticker_text = f"{event_ticker} {series_ticker}".upper()
        asset = None
        match = re.search(r"\bKX(BTC|ETH|SOL|XRP|DOGE)", ticker_text)
        if match:
            asset = match.group(1)

        timeframe = None
        for pat, tf in _CRYPTO_TF_PATTERNS:
            if pat.search(ticker_text):
                timeframe = tf
                break

        return asset, timeframe

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

    async def get_active_markets(
        self,
        category: Optional[str] = None,
        *,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> List[CatalogMarket]:
        """Return active markets, optionally filtered by category/asset/timeframe."""
        if not self._markets:
            await self.refresh()

        markets = self.get_all_markets()
        if category:
            markets = [m for m in markets if m.category == category]
        if asset:
            markets = [m for m in markets if m.asset == asset]
        if timeframe:
            markets = [m for m in markets if m.timeframe == timeframe]

        return [m for m in markets if getattr(m.market, "active", False)]

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

    def counts_by_asset_timeframe(
        self,
        assets: Optional[List[str]] = None,
        timeframes: Optional[List[str]] = None,
    ) -> Dict[str, Dict[str, int]]:
        """Return nested counts per asset/timeframe."""
        assets = assets or self.assets()
        timeframes = timeframes or self.timeframes()
        counts: Dict[str, Dict[str, int]] = {}
        for asset in assets:
            counts[asset] = {}
            for tf in timeframes:
                counts[asset][tf] = len([
                    m for m in self._by_asset.get(asset, [])
                    if m.timeframe == tf
                ])
        return counts

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
            by_asset_timeframe=self.counts_by_asset_timeframe(),
        )


# ── Singleton ────────────────────────────────────────────────────────────

_catalog: Optional[KalshiMarketCatalog] = None


def get_market_catalog() -> KalshiMarketCatalog:
    """Get or create the singleton KalshiMarketCatalog."""
    global _catalog
    if _catalog is None:
        _catalog = KalshiMarketCatalog()
    return _catalog
