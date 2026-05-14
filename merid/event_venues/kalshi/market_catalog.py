"""KalshiMarketCatalog — Periodic market discovery and categorization.

Responsibilities:
1. Periodically call GET /markets and cache results
2. Group markets by category, event_ticker, series_ticker
3. Tag with MERID-friendly labels: asset, timeframe, type
4. Expose filter methods for agents and UI

Categories (from Kalshi):
  cross_category, crypto, economics, macro, financials, politics, climate, tech, sports, culture, science, equities, other

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

import threading
import asyncio
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set

from config.kalshi_universe import kalshi_agent_grid_catalog_series_tickers
from merid.event_venues.base import EventMarket, MarketFilter
from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.models import KalshiConfig
from merid.event_venues.kalshi.allowed_market_policy import (
    filter_allowed_markets,
    get_allowed_assets,
    is_market_allowed,
)
from merid.event_venues.kalshi.market_universe import MarketUniverse
from utils.logger import get_logger

# Production scope validation
try:
    from config.trading_scope import (
        get_trading_scope,
        is_15m_series_ticker,
    )
    TRADING_SCOPE_AVAILABLE = True
except ImportError:
    TRADING_SCOPE_AVAILABLE = False

logger = get_logger("merid.event_venues.kalshi.market_catalog")


# ── Ticker-prefix → category mapping (primary detection) ────────────────
# Kalshi API v2 returns no 'category' field on markets. The event_ticker
# prefix is the most reliable signal for categorization.

# BUG-04 fix: patterns use .match() (enforced in _detect_from_ticker) so the
# leading ^ anchor is respected without relying on .search() semantics.
# Ordering rule: longer / more-specific prefixes MUST appear before shorter
# catch-all alternatives so that e.g. KXTRUMPCPI hits economics before politics
# and KXNFLGAME hits sports before a hypothetical broad NFL match.
_TICKER_CATEGORY_MAP: List[tuple] = [
    # ── Crypto (specific assets first, broad crypto catch-all last) ──────
    (re.compile(r"^KXBITCOIN", re.I), "crypto", "BTC"),
    (re.compile(r"^KXBTC", re.I), "crypto", "BTC"),
    (re.compile(r"^KXETHEREUM", re.I), "crypto", "ETH"),
    (re.compile(r"^KXETH", re.I), "crypto", "ETH"),
    (re.compile(r"^KXSOLANA", re.I), "crypto", "SOL"),
    (re.compile(r"^KXSOL", re.I), "crypto", "SOL"),
    (re.compile(r"^KXRIPPLE", re.I), "crypto", "XRP"),
    (re.compile(r"^KXXRP", re.I), "crypto", "XRP"),
    (re.compile(r"^KXDOGECOIN", re.I), "crypto", "DOGE"),
    (re.compile(r"^KXDOGE", re.I), "crypto", "DOGE"),
    (re.compile(r"^KXCRYPTO", re.I), "crypto", None),
    # ── Financials / indices ─────────────────────────────────────────────
    (re.compile(r"^KXSP500", re.I), "financials", "SPX"),
    (re.compile(r"^KXSPX", re.I), "financials", "SPX"),
    (re.compile(r"^KXSPY", re.I), "financials", "SPX"),
    (re.compile(r"^KXNASDAQ", re.I), "financials", "NDX"),
    (re.compile(r"^KXNDX", re.I), "financials", "NDX"),
    (re.compile(r"^KXQQQ", re.I), "financials", "NDX"),
    (re.compile(r"^KXDJIA", re.I), "financials", "DJI"),
    (re.compile(r"^KXDJI", re.I), "financials", "DJI"),
    (re.compile(r"^KXDOW", re.I), "financials", "DJI"),
    (re.compile(r"^KXRUSSELL", re.I), "financials", None),
    (re.compile(r"^KXRUT", re.I), "financials", None),
    (re.compile(r"^KXIWM", re.I), "financials", None),
    (re.compile(r"^KXFINANCIALS", re.I), "financials", None),
    (re.compile(r"^KXSTOCK", re.I), "financials", None),
    # ── Economics / macro (specific releases before broad FOMC/FED) ──────
    (re.compile(r"^KXCPI", re.I), "economics", "CPI"),
    (re.compile(r"^KXGDP", re.I), "economics", "GDP"),
    (re.compile(r"^KXNONFARM", re.I), "economics", "JOBS"),
    (re.compile(r"^KXPAYROLL", re.I), "economics", "JOBS"),
    (re.compile(r"^KXUNEMPLOYMENT", re.I), "economics", "JOBS"),
    (re.compile(r"^KXNFP", re.I), "economics", "JOBS"),
    (re.compile(r"^KXJOBS", re.I), "economics", "JOBS"),
    (re.compile(r"^KXFOMC", re.I), "economics", "RATES"),
    (re.compile(r"^KXFED", re.I), "economics", "RATES"),
    (re.compile(r"^KXRATE", re.I), "economics", "RATES"),
    (re.compile(r"^KXECON", re.I), "economics", None),
    # ── Politics (narrow explicit terms; no short substrings like GOV/TRUMP
    #    that collide with economic tickers such as KXTRUMPCPI) ───────────
    (re.compile(r"^KXELECTION", re.I), "politics", "ELECTION"),
    (re.compile(r"^KXSCOTUS", re.I), "politics", "ELECTION"),
    (re.compile(r"^KXSENATE", re.I), "politics", "ELECTION"),
    (re.compile(r"^KXCONGRESS", re.I), "politics", "ELECTION"),
    (re.compile(r"^KXPOLITICS", re.I), "politics", "ELECTION"),
    (re.compile(r"^KXPRES", re.I), "politics", "ELECTION"),
    (re.compile(r"^KXBIDEN", re.I), "politics", "ELECTION"),
    (re.compile(r"^KXTRUMP(?!CPI|GDP|CPI|JOBS|RATE|FED|FOMC)", re.I), "politics", "ELECTION"),
    (re.compile(r"^KXGOVT", re.I), "politics", None),
    # ── Climate / weather ────────────────────────────────────────────────
    (re.compile(r"^KXHURRICANE", re.I), "climate", "WEATHER"),
    (re.compile(r"^KXTORNADO", re.I), "climate", "WEATHER"),
    (re.compile(r"^KXWEATHER", re.I), "climate", "WEATHER"),
    (re.compile(r"^KXTEMP", re.I), "climate", "WEATHER"),
    (re.compile(r"^KXEMISSION", re.I), "climate", "CLIMATE"),
    (re.compile(r"^KXCARBON", re.I), "climate", "CLIMATE"),
    (re.compile(r"^KXCLIMATE", re.I), "climate", "CLIMATE"),
    # ── Sports (longer compound prefixes before shorter root) ────────────
    (re.compile(r"^KXNBAGAME|^KXNBAPTS|^KXNBASPREAD|^KXNBAPROP", re.I), "sports", "NBA"),
    (re.compile(r"^KXNBA", re.I), "sports", "NBA"),
    (re.compile(r"^KXNFLGAME|^KXNFLPTS|^KXNFLSPREAD|^KXNFLPROP", re.I), "sports", "NFL"),
    (re.compile(r"^KXNFL", re.I), "sports", "NFL"),
    (re.compile(r"^KXMLBGAME|^KXMLBPROP", re.I), "sports", "MLB"),
    (re.compile(r"^KXMLB", re.I), "sports", "MLB"),
    (re.compile(r"^KXNHLGAME|^KXNHLPROP", re.I), "sports", "NHL"),
    (re.compile(r"^KXNHL", re.I), "sports", "NHL"),
    (re.compile(r"^KXSOCCER|^KXMLS|^KXEPL|^KXUEFA|^KXFIFA", re.I), "sports", "SOCCER"),
    (re.compile(r"^KXTENNIS|^KXATP|^KXWTA", re.I), "sports", "TENNIS"),
    (re.compile(r"^KXGOLF|^KXPGA", re.I), "sports", "GOLF"),
    (re.compile(r"^KXMMA|^KXUFC|^KXBOXING", re.I), "sports", "MMA"),
    (re.compile(r"^KXESPORT", re.I), "sports", "ESPORTS"),
    (re.compile(r"^KXMVESPORT", re.I), "sports", "SPORTS_COMBO"),
    (re.compile(r"^KXSPORT", re.I), "sports", None),
    # ── Tech ─────────────────────────────────────────────────────────────
    (re.compile(r"^KXOPENAI", re.I), "tech", None),
    (re.compile(r"^KXGOOGLE", re.I), "tech", None),
    (re.compile(r"^KXAPPLE", re.I), "tech", None),
    (re.compile(r"^KXNVDA", re.I), "tech", None),
    (re.compile(r"^KXMSFT", re.I), "tech", None),
    (re.compile(r"^KXMETA", re.I), "tech", None),
    (re.compile(r"^KXAI", re.I), "tech", None),
    (re.compile(r"^KXTECH", re.I), "tech", None),
    # ── Culture / entertainment ──────────────────────────────────────────
    (re.compile(r"^KXENTERTAINMENT", re.I), "culture", None),
    (re.compile(r"^KXCULTURE", re.I), "culture", None),
    (re.compile(r"^KXOSCAR|^KXGRAMMY|^KXEMMY|^KXMOVIE", re.I), "culture", None),
    # ── Science ──────────────────────────────────────────────────────────
    (re.compile(r"^KXSPACEX", re.I), "science", None),
    (re.compile(r"^KXSCIENCE|^KXSPACE|^KXNASA", re.I), "science", None),
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


@dataclass
class CatalogSnapshot:
    """Point-in-time snapshot of the catalog."""
    markets: List[CatalogMarket] = field(default_factory=list)
    refreshed_at: Optional[datetime] = None
    market_count: int = 0
    by_category: Dict[str, int] = field(default_factory=dict)
    by_asset: Dict[str, int] = field(default_factory=dict)
    by_timeframe: Dict[str, int] = field(default_factory=dict)
    by_asset_timeframe: Dict[str, Dict[str, int]] = field(default_factory=dict)  # {"BTC": {"15m": 3, "1h": 2}}


class KalshiMarketCatalog:
    """Discovers, caches, and categorizes all Kalshi markets.

    Thread-safe via asyncio lock. Refresh interval configurable.
    """

    def __init__(
        self,
        client: Optional[KalshiVenueClient] = None,
        refresh_interval_s: Optional[float] = None,
        max_markets: int = 5000,
    ):
        # Configurable refresh interval (default 60s for 15m markets, reduced from 300s)
        # Enforce minimum of 2s to prevent accidental self-DoS via misconfiguration
        _MIN_REFRESH_INTERVAL_S = 2.0
        if refresh_interval_s is None:
            import os
            refresh_interval_s = float(os.getenv("MERID_KALSHI_CATALOG_REFRESH_INTERVAL_S", "60.0"))
        
        if refresh_interval_s < _MIN_REFRESH_INTERVAL_S:
            logger.warning(
                "Catalog refresh interval %.1fs is below minimum %.1fs, clamping to minimum",
                refresh_interval_s, _MIN_REFRESH_INTERVAL_S
            )
            refresh_interval_s = _MIN_REFRESH_INTERVAL_S
        
        # Calculate expected calls per hour for rate limit awareness
        _calls_per_hour = 3600.0 / refresh_interval_s
        logger.info(
            "KalshiMarketCatalog config: refresh_interval=%.1fs (min=%.1fs), expected_calls/hour=%.1f",
            refresh_interval_s, _MIN_REFRESH_INTERVAL_S, _calls_per_hour
        )

        if client is None:
            from merid.event_venues.kalshi.client import get_kalshi_client
            client = get_kalshi_client()
        self._client = client
        self._refresh_interval = refresh_interval_s
        self._max_markets = max_markets

        self._markets: List[CatalogMarket] = []
        self._by_category: Dict[str, List[CatalogMarket]] = defaultdict(list)
        self._by_asset: Dict[str, List[CatalogMarket]] = defaultdict(list)
        self._by_timeframe: Dict[str, List[CatalogMarket]] = defaultdict(list)
        self._by_ticker: Dict[str, CatalogMarket] = {}

        # MarketUniverse: canonical source of truth for allowed markets
        # Created once from filtered catalog and injected into downstream components
        self._market_universe: Optional[MarketUniverse] = None

        self._last_refresh: Optional[datetime] = None
        self._refresh_count: int = 0
        # Lazy-init lock to avoid event loop binding issues
        self._lock: Optional[asyncio.Lock] = None
        self._lock_init_lock = threading.Lock()
        self._task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()

    def _ensure_lock(self) -> asyncio.Lock:
        """Lazy-initialize the asyncio.Lock in the current event loop."""
        if self._lock is None:
            with self._lock_init_lock:
                if self._lock is None:
                    self._lock = asyncio.Lock()
        return self._lock

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start periodic refresh loop."""
        if self._task and not self._task.done():
            return
        self._shutdown.clear()
        # FIX: Defer initial refresh to avoid blocking startup with 5000 market fetch
        # Start refresh loop immediately, which will do initial refresh on first iteration
        self._task = asyncio.create_task(self._refresh_loop(), name="kalshi-catalog-refresh")
        def _task_done_cb(task: asyncio.Task) -> None:
            if not task.cancelled() and task.exception():
                logger.error("KalshiMarketCatalog refresh task crashed: %s", task.exception())
        self._task.add_done_callback(_task_done_cb)
        logger.info(f"KalshiMarketCatalog started — refresh loop running (deferred initial load)")

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
        lock = self._ensure_lock()
        async with lock:
            try:
                # PRODUCTION AUDIT (Step 3): Priority series restricted to 15m only
                # 5 assets (BTC, ETH, SOL, XRP, DOGE) x 15m timeframe only.
                # All other timeframes are signal-only and excluded from trading catalog.
                _PRIORITY_SERIES = list(
                    dict.fromkeys(
                        kalshi_agent_grid_catalog_series_tickers()
                    )
                )
                
                # PRODUCTION AUDIT (Step 3): Log scope enforcement
                logger.info(
                    "[DISCOVERY_SCOPE] Catalog refresh using production whitelist: "
                    f"series={_PRIORITY_SERIES} (BTC/ETH/SOL/XRP/DOGE 15m only)"
                )
                raw_markets: list = []
                seen_tickers: set = set()

                # 1. Fetch priority series concurrently (was sequential — caused 2s+ lag spikes)
                async def _fetch_series(series: str):
                    try:
                        return series, await self._client.list_markets_result(
                            MarketFilter(active_only=True, limit=200, search=series)
                        )
                    except Exception as _exc:
                        logger.warning("Catalog series fetch error: series=%s err=%s", series, _exc)
                        return series, None

                results = await asyncio.gather(
                    *[_fetch_series(s) for s in _PRIORITY_SERIES],
                    return_exceptions=False,
                )
                for series, r in results:
                    if r is None:
                        continue
                    _count = len(r.data) if r.success else 0
                    logger.debug(
                        "Catalog series fetch: series=%s status=%s count=%d sample=%s",
                        series,
                        "ok" if r.success else r.error,
                        _count,
                        [m.market_id for m in (r.data or [])[:3]],
                    )
                    if r.success:
                        for m in r.data:
                            if m.market_id not in seen_tickers:
                                raw_markets.append(m)
                                seen_tickers.add(m.market_id)

                # 2. BACKFILL DISABLED: AllowedMarketPolicy filters at the edge
                # We no longer fetch all 5000 markets and filter later.
                # Instead, we only fetch the priority series (BTC/ETH/SOL/XRP/DOGE 15m)
                # and filter those using the AllowedMarketPolicy.
                # This prevents the system from processing 5000 markets.
                logger.info(
                    "[ALLOWED-MARKET-POLICY] Backfill disabled - using priority series only "
                    f"(allowed_assets={get_allowed_assets()})"
                )
            except Exception as exc:
                logger.warning(f"Failed to fetch markets: {exc}")
                return len(self._markets)

            # Apply AllowedMarketPolicy filter at the edge
            # This ensures only BTC/ETH/SOL/XRP/DOGE 15m markets proceed to enrichment
            logger.info(
                "[ALLOWED-MARKET-POLICY] Pre-filter: %d raw markets fetched",
                len(raw_markets)
            )
            filtered_markets = filter_allowed_markets(raw_markets)
            logger.info(
                "[ALLOWED-MARKET-POLICY] Post-filter: %d markets allowed (BTC/ETH/SOL/XRP/DOGE 15m only)",
                len(filtered_markets)
            )

            # Create MarketUniverse from filtered markets
            # This is the canonical source of truth for allowed markets
            self._market_universe = MarketUniverse.from_markets(filtered_markets)
            if not self._market_universe.validate_universe():
                logger.warning(
                    "[MARKET-UNIVERSE] Universe validation failed - proceeding with empty universe"
                )
            self._market_universe.log_summary()

            now = datetime.now(timezone.utc)

            # Offload the CPU-bound enrichment loop (now for filtered markets only)
            # to a thread pool executor so it cannot block the event loop.
            loop = asyncio.get_running_loop()
            (
                enriched,
                cat_idx,
                asset_idx,
                tf_idx,
                ticker_idx,
                categories_found,
                assets_found,
            ) = await loop.run_in_executor(None, self._build_indexes, filtered_markets, now)

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

            _log = logger.info if enriched else logger.debug
            _log(
                f"Catalog refreshed: {len(enriched)} markets, "
                f"{len(cat_idx)} categories, {len(asset_idx)} assets"
            )

            # STARTUP METRICS: Log market counts for observability
            logger.info(
                "[STARTUP-METRICS] kalshi_catalog_refresh "
                f"markets_fetched={len(raw_markets)} "
                f"markets_allowed={len(filtered_markets)} "
                f"markets_enriched={len(enriched)} "
                f"assets={sorted(assets_found)} "
                f"categories={sorted(categories_found)}"
            )

            # Feed REST data into MarketStateStore so expiry/volume/OI/strikes are available
            # for UI display (crypto spot vs kalshi needs these fields).
            # IMPORTANT: keep this on the event loop (not asyncio.to_thread) because
            # apply_rest_market uses threading.Lock — offloading to a thread causes WS
            # handlers (also using that lock) to block the event loop waiting for it.
            # batch_size=10 ensures max ~6ms of synchronous work before each yield.
            try:
                from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                store = get_kalshi_market_state_store()
                await self._apply_rest_markets_batched(enriched, store, batch_size=10)
            except Exception as _exc:
                logger.debug("Catalog → MarketStateStore feed error (non-fatal): %s", _exc)

            # Pre-register settlement buffers for RTI-settled markets so the
            # 60-slot grid is allocated before the first RTI tick arrives.
            try:
                from config.kalshi_crypto_series_meta import is_rti_settled_kalshi_crypto_ticker
                from merid.data.settlement_rti_buffer import get_settlement_buffer_registry
                _sb_reg = get_settlement_buffer_registry()
                await self._ensure_buffers_batched(enriched, _sb_reg, batch_size=10)
            except Exception as _sb_exc:
                logger.debug("Settlement buffer registration error (non-fatal): %s", _sb_exc)

            return len(enriched)

    # ── Index builder (sync, runs in thread pool) ────────────────────────

    def _build_indexes(
        self,
        raw_markets: list,
        now: datetime,
    ) -> tuple:
        """Build enriched market list and all lookup indexes.

        Runs in a thread-pool executor so the ~2s CPU work (regex, datetime,
        text detection over 5000 markets) does not block the event loop.

        Returns:
            (enriched, cat_idx, asset_idx, tf_idx, ticker_idx,
             categories_found, assets_found)
        """
        enriched: List[CatalogMarket] = []
        cat_idx: Dict[str, List[CatalogMarket]] = defaultdict(list)
        asset_idx: Dict[str, List[CatalogMarket]] = defaultdict(list)
        tf_idx: Dict[str, List[CatalogMarket]] = defaultdict(list)
        ticker_idx: Dict[str, CatalogMarket] = {}
        categories_found: set = set()
        assets_found: set = set()

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

        return enriched, cat_idx, asset_idx, tf_idx, ticker_idx, categories_found, assets_found

    # ── Async batched post-processing (event-loop friendly) ───────────────

    async def _apply_rest_markets_batched(
        self,
        enriched: List[CatalogMarket],
        store: "KalshiMarketStateStore",  # type: ignore  # noqa: F821
        batch_size: int = 200,
    ) -> int:
        """Feed REST market data into MarketStateStore in async-batched chunks.

        Processes at most *batch_size* markets per iteration, then yields
        control with asyncio.sleep(0) to prevent event-loop blocking.
        Returns the number of markets applied.
        """
        applied = 0
        for i, cm in enumerate(enriched):
            mkt = cm.market
            store.apply_rest_market({
                "ticker": mkt.market_id,
                "volume_24h": int(mkt.volume) if mkt.volume else 0,
                "open_interest": int(mkt.open_interest) if mkt.open_interest else 0,
                "notional_value": 0,  # Not directly available from EventMarket
                "expiration_time": mkt.end_date.isoformat() if mkt.end_date else None,
                "expected_expiration_time": mkt.end_date.isoformat() if mkt.end_date else None,
                "latest_expiration_time": mkt.end_date.isoformat() if mkt.end_date else None,
                "underlying": cm.asset,
                "strike_price": cm.strike_price,
                "floor_strike": cm.floor_strike,
                "cap_strike": cm.cap_strike,
            })
            applied += 1
            # Yield control every batch_size to avoid blocking the event loop
            if (i + 1) % batch_size == 0:
                await asyncio.sleep(0)
        return applied

    async def _ensure_buffers_batched(
        self,
        enriched: List[CatalogMarket],
        sb_reg: "SettlementBufferRegistry",  # type: ignore  # noqa: F821
        batch_size: int = 200,
    ) -> int:
        """Pre-register settlement buffers for RTI-settled markets in async-batched chunks.

        Processes at most *batch_size* markets per iteration, then yields
        control with asyncio.sleep(0) to prevent event-loop blocking.
        Returns the number of buffers registered.
        """
        from config.kalshi_crypto_series_meta import is_rti_settled_kalshi_crypto_ticker

        registered = 0
        for i, cm in enumerate(enriched):
            tid = cm.market.market_id
            if cm.asset and cm.expires_at and is_rti_settled_kalshi_crypto_ticker(tid):
                sb_reg.ensure_buffer(
                    market_ticker=tid,
                    asset=cm.asset,
                    expiry_epoch=int(cm.expires_at.timestamp()),
                )
                registered += 1
            # Yield control every batch_size to avoid blocking the event loop
            if (i + 1) % batch_size == 0:
                await asyncio.sleep(0)
        if registered:
            logger.debug("Settlement buffer: registered %d RTI-settled markets", registered)
        return registered

    def _apply_rest_markets_sync(
        self,
        enriched: List[CatalogMarket],
        store: "KalshiMarketStateStore",  # type: ignore  # noqa: F821
    ) -> int:
        """Sync version of _apply_rest_markets_batched — intended for thread-pool use.

        Runs the full market-state update loop without yielding, but completely
        off the event loop so no lag is incurred.  Thread-safe: all mutations go
        through KalshiMarketStateStore._lock (threading.Lock).
        """
        applied = 0
        for cm in enriched:
            mkt = cm.market
            store.apply_rest_market({
                "ticker": mkt.market_id,
                "volume_24h": int(mkt.volume) if mkt.volume else 0,
                "open_interest": int(mkt.open_interest) if mkt.open_interest else 0,
                "notional_value": 0,
                "expiration_time": mkt.end_date.isoformat() if mkt.end_date else None,
                "expected_expiration_time": mkt.end_date.isoformat() if mkt.end_date else None,
                "latest_expiration_time": mkt.end_date.isoformat() if mkt.end_date else None,
                "underlying": cm.asset,
                "strike_price": cm.strike_price,
                "floor_strike": cm.floor_strike,
                "cap_strike": cm.cap_strike,
            })
            applied += 1
        return applied

    def _ensure_buffers_sync(
        self,
        enriched: List[CatalogMarket],
        sb_reg: "SettlementBufferRegistry",  # type: ignore  # noqa: F821
    ) -> int:
        """Sync version of _ensure_buffers_batched — intended for thread-pool use.

        Runs the full settlement-buffer registration loop without yielding.
        """
        from config.kalshi_crypto_series_meta import is_rti_settled_kalshi_crypto_ticker

        registered = 0
        for cm in enriched:
            tid = cm.market.market_id
            if cm.asset and cm.expires_at and is_rti_settled_kalshi_crypto_ticker(tid):
                sb_reg.ensure_buffer(
                    market_ticker=tid,
                    asset=cm.asset,
                    expiry_epoch=int(cm.expires_at.timestamp()),
                )
                registered += 1
        if registered:
            logger.debug("Settlement buffer (sync): registered %d RTI-settled markets", registered)
        return registered

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
        # Timeframe: check series_ticker suffix first (e.g. KXBTC15M → "15m",
        # KXBTCH1 → "1h", KXBTCD1 → "daily") to avoid misclassification when
        # a longer-lived contract's remaining-time doesn't match its series.
        timeframe = self._detect_timeframe_from_series(series_ticker) or self._detect_timeframe(text, mkt.end_date, now)
        market_type = self._detect_type(text)
        strikes = self._detect_strikes(text, mkt.market_id)

        # Prefer native Kalshi REST API strike fields over text-parsed values.
        # The API provides strike_type, floor_strike, cap_strike as top-level
        # numeric fields which are more reliable than regex on question text.
        if raw.get("floor_strike") is not None:
            try:
                strikes.setdefault("floor", float(raw["floor_strike"]))
            except (TypeError, ValueError):
                pass
        if raw.get("cap_strike") is not None:
            try:
                strikes.setdefault("cap", float(raw["cap_strike"]))
            except (TypeError, ValueError):
                pass
        if raw.get("strike_price") is not None:
            try:
                strikes.setdefault("strike", float(raw["strike_price"]))
            except (TypeError, ValueError):
                pass

        # Merge: ticker-prefix detection is the primary signal.
        # BUG-05 fix: only accept mkt.category if it is a recognised category
        # string. An unvalidated API value (e.g. "cryptocurrency", "weather")
        # would otherwise silently override the ticker map and produce a
        # non-standard category that is invisible to all pool queries.
        from merid.event_venues.kalshi.universe import KNOWN_CATEGORIES as _KC
        _api_cat = (mkt.category or "").strip().lower()
        _api_cat_valid = _api_cat if _api_cat in _KC else None
        category = ticker_category or _api_cat_valid
        asset = ticker_asset or text_asset

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
    def _detect_strikes(text: str, ticker: str = "") -> Dict[str, float]:
        """Extract strike prices from market text and ticker suffix.
        
        Args:
            text: Market question/description text to parse.
            ticker: Optional Kalshi ticker (e.g., "KXBTC-26MAR2501-T80199.99")
                   for suffix-based strike extraction.
        """
        res = {}
        
        # 1. Ticker suffix extraction (most reliable for threshold/bracket markets)
        # Patterns: -T80199.99 (threshold above), -B80150 (bracket below)
        if ticker:
            # Threshold: -T followed by number at end (e.g., KXBTC-26MAR2501-T80199.99)
            t_match = re.search(r"-T(\d+(?:\.\d+)?)$", ticker)
            if t_match:
                try:
                    res["strike"] = float(t_match.group(1))
                    res["strike_type"] = "threshold"
                    return res  # Ticker suffix is authoritative
                except ValueError:
                    pass
            # Bracket: -B followed by number (e.g., KXBTC-26MAR2501-B80150)
            b_match = re.search(r"-B(\d+(?:\.\d+)?)$", ticker)
            if b_match:
                try:
                    res["strike"] = float(b_match.group(1))
                    res["strike_type"] = "bracket"
                    return res  # Ticker suffix is authoritative
                except ValueError:
                    pass

            # 15m market format: KXBTC15M-26APR111630-30 has no strike suffix
            # but we can detect if it's a 15m market and mark it for text parsing
            is_15m = "15M" in ticker.upper() or re.search(r"\d{2}:\d{2}$", ticker) is not None
        
        # 2. Text-based patterns (fallback when ticker suffix not available)
        # Examples: "above 50,000", "below $1.50", "between 100 and 200"
        
        # Enhanced pattern for PM crypto markets: "Will BTC be above $79,200 at 11:30?"
        # Matches: above/below/over/under/at + optional $ + number with optional commas/decimals
        # The pattern is more permissive to catch variations in question formatting
        strike_patterns = [
            # Pattern: above $79,200 or above 79200
            r"(?:above|below|at|over|under)\s+(?:the\s+)?(?:price\s+)?(?:of\s+)?\$?([\d,]+(?:\.\d+)?)",
            # Pattern: be above $79,200 at 11:30 (for 15m markets)
            r"be\s+(?:above|below|at|over|under)\s+\$?([\d,]+(?:\.\d+)?)",
            # Pattern: trading above/below $79,200
            r"trading\s+(?:above|below|at|over|under)\s+\$?([\d,]+(?:\.\d+)?)",
            # Original simpler pattern as fallback
            r"(?:above|below|at|over|under)\s*\$?([\d,]+\.?\d*)",
        ]
        
        for pattern in strike_patterns:
            strike_match = re.search(pattern, text, re.I)
            if strike_match:
                try:
                    strike_str = strike_match.group(1).replace(",", "")
                    res["strike"] = float(strike_str)
                    res["strike_type"] = "threshold"
                    break  # Use first successful match
                except ValueError:
                    continue
        
        # Range "between X and Y" for bracket markets
        range_match = re.search(r"between\s*\$?([\d,]+\.?\d*)\s*and\s*\$?([\d,]+\.?\d*)", text, re.I)
        if range_match:
            try:
                res["floor"] = float(range_match.group(1).replace(",", ""))
                res["cap"] = float(range_match.group(2).replace(",", ""))
                res["strike_type"] = "bracket"
            except ValueError:
                logger.debug("Failed to parse range from text: %s", text[:80])
        
        return res

    @staticmethod
    def _detect_from_ticker(ticker: str) -> tuple:
        """Detect category and asset from Kalshi event_ticker prefix.

        Returns (category, asset) — either may be None.
        Uses .match() so every pattern's leading ^ anchor is enforced and
        cannot fire on a mid-string substring (BUG-04 fix).
        """
        upper = ticker.upper()
        for pat, category, asset in _TICKER_CATEGORY_MAP:
            if pat.match(upper):
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
    def _detect_timeframe_from_series(series_ticker: str) -> Optional[str]:
        """Derive timeframe from known Kalshi series ticker suffixes.

        Handles two naming conventions:
        - UPDOWN-style: KXBTUPDOWN-15M, KXETHUPDOWN-1H → "15m", "1h"
        - Compact-style: KXBTC15M, KXBTCH1, KXBTCD1 → "15m", "1h", "daily"

        More reliable than text/expiry heuristics for crypto series where
        multiple contracts at different lifecycle stages are open concurrently.
        """
        if not series_ticker:
            return None
        upper = series_ticker.upper()

        # Hourly roots (no suffix): KXBTC, KXETH, … — API series_ticker for 1h contracts.
        _HOURLY_ROOTS = frozenset(
            {"KXBTC", "KXETH", "KXSOL", "KXXRP", "KXDOGE"}
        )
        if upper in _HOURLY_ROOTS:
            return "1h"

        # Handle UPDOWN-style with dashes: KXBTUPDOWN-15M, KXETHUPDOWN-1H
        if "-" in upper:
            suffix = upper.split("-")[-1]
            if suffix == "15M":
                return "15m"
            if suffix in ("1H", "H1"):
                return "1h"
            if suffix == "1D" or suffix == "D1":
                return "daily"
            if suffix == "1W" or suffix == "W1":
                return "weekly"
            if suffix == "1MO" or suffix == "M1":
                return "monthly"

        # Handle compact-style: KXBTC15M, KXBTCH1, KXBTCD1, KXBTCW1, KXBTC1M, KXBTCY
        if upper.endswith("15M"):
            return "15m"
        if upper.endswith("H1"):
            return "1h"
        if upper.endswith("D1"):
            return "daily"
        if upper.endswith("W1"):
            return "weekly"
        if upper.endswith("1M"):
            return "monthly"
        if re.fullmatch(r"KX(BTC|ETH|SOL|XRP|DOGE)Y", upper):
            return "annual"

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

    def get_market_universe(self) -> Optional[MarketUniverse]:
        """
        Return the MarketUniverse (canonical source of truth for allowed markets).
        
        This is the single source of truth that downstream components should use
        to determine which markets are allowed. It is created once from the
        filtered catalog after AllowedMarketPolicy is applied.
        
        Returns:
            MarketUniverse instance, or None if catalog hasn't been refreshed yet
        """
        return self._market_universe

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
        
        # Production scope filter: only allow 15m crypto markets
        if TRADING_SCOPE_AVAILABLE and category == "crypto":
            results = [m for m in results if m.timeframe == "15m"]
            logger.debug(
                f"[SCOPE_FILTER] Filtered to 15m crypto markets only: {len(results)} results"
            )
        
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
        
        # Production scope filter: only allow 15m crypto markets
        if TRADING_SCOPE_AVAILABLE and asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            results = [m for m in results if m.timeframe == "15m"]
            logger.debug(
                f"[SCOPE_FILTER] Filtered {asset} to 15m markets only: {len(results)} results"
            )
        
        return results

    def get_markets_by_timeframe(self, timeframe: str) -> List[CatalogMarket]:
        """Filter markets by timeframe."""
        return self._by_timeframe.get(timeframe, [])

    def get_active_markets(
        self,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> List[CatalogMarket]:
        """Get active (open) markets with optional filtering by asset and timeframe.

        Uses market.active status which aligns with Kalshi's status=open semantics.
        """
        markets = [m for m in self._markets if m.market.active]
        if asset:
            markets = [m for m in markets if m.asset == asset]
        if timeframe:
            markets = [m for m in markets if m.timeframe == timeframe]
        return markets

    def get_markets_by_event(self, event_keyword: str) -> List[CatalogMarket]:
        """Search markets by event keyword in question/description."""
        kw = event_keyword.lower()
        return [
            m for m in self._markets
            if kw in (m.market.question or "").lower() or kw in (m.market.description or "").lower()
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

    async def get_markets_for_series(self, series_ticker: str) -> List[CatalogMarket]:
        """Query Kalshi REST API for markets belonging to a specific series.
        
        PRODUCTION FIX (2026-05-01): This method enables series-specific market discovery
        when the cached catalog doesn't contain markets for the requested series.
        
        Args:
            series_ticker: The Kalshi series ticker (e.g., "KXBTC", "KXETHD1")
            
        Returns:
            List of CatalogMarket objects for markets in this series
        """
        try:
            # Query Kalshi for markets matching this series
            _filter = MarketFilter(
                active_only=True,
                limit=200,
                search=series_ticker,
            )
            _result = await self._client.list_markets_result(_filter)
            
            if not _result.success:
                logger.debug("Series query failed for %s: %s", series_ticker, _result.error)
                return []
            
            # Convert to CatalogMarket objects
            _markets: List[CatalogMarket] = []
            for m in (_result.data or []):
                # Enrich with metadata
                cm = self._enrich_market(m)
                _markets.append(cm)
            
            logger.debug(
                "Series %s: discovered %d markets via REST API",
                series_ticker, len(_markets)
            )
            return _markets
            
        except Exception as exc:
            logger.debug("Error querying series %s: %s", series_ticker, exc)
            return []

    def categories(self) -> List[str]:
        """List all known categories."""
        return sorted(self._by_category.keys())

    def assets(self) -> List[str]:
        """List all detected assets."""
        return sorted(self._by_asset.keys())

    def timeframes(self) -> List[str]:
        """List all detected timeframes."""
        return sorted(self._by_timeframe.keys())

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
        # Build nested by_asset_timeframe counts
        by_asset_tf: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for m in self._markets:
            if m.asset and m.timeframe:
                by_asset_tf[m.asset][m.timeframe] += 1
        # Convert to regular dict for serialization
        by_asset_tf_serializable = {k: dict(v) for k, v in by_asset_tf.items()}

        return CatalogSnapshot(
            markets=list(self._markets),
            refreshed_at=self._last_refresh,
            market_count=len(self._markets),
            by_category={k: len(v) for k, v in self._by_category.items()},
            by_asset={k: len(v) for k, v in self._by_asset.items()},
            by_timeframe={k: len(v) for k, v in self._by_timeframe.items()},
            by_asset_timeframe=by_asset_tf_serializable,
        )


# ── Singleton ────────────────────────────────────────────────────────────

_catalog: Optional[KalshiMarketCatalog] = None
_catalog_lock = threading.Lock()


def get_market_catalog() -> KalshiMarketCatalog:
    """Get or create the singleton KalshiMarketCatalog."""
    global _catalog
    if _catalog is None:
        with _catalog_lock:
            if _catalog is None:
                _catalog = KalshiMarketCatalog()
    return _catalog


# Module-level convenience wrapper for tests and external callers
def _detect_from_ticker(ticker: str) -> tuple:
    """Detect category and asset from Kalshi event_ticker prefix.

    Module-level wrapper around KalshiMarketCatalog._detect_from_ticker.
    Returns (category, asset) — either may be None.
    """
    return KalshiMarketCatalog._detect_from_ticker(ticker)
