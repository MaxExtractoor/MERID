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

import os
import threading
import asyncio
import concurrent.futures
from pathlib import Path

# CRITICAL DIAGNOSTIC: Log module load to confirm code version
from utils.logger import get_logger
logger = get_logger("kalshi.market_catalog")

# VERSION TAG: This log identifies the deployed revision of market_catalog.py
# Changes in v20260526a:
# - No functional changes in this file, but version tag added for deployment tracking
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set

from config.kalshi_universe import kalshi_agent_grid_catalog_series_tickers
from merid.event_venues.base import EventMarket, MarketFilter
from merid.event_venues.kalshi.client import KalshiVenueClient

# PRIORITY_SERIES: The 5 crypto 15m series for symmetric discovery
_PRIORITY_SERIES = kalshi_agent_grid_catalog_series_tickers()


def compute_current_window_suffix(now: datetime) -> str:
    """
    Compute Kalshi 15-minute window suffix for a given UTC timestamp.
    
    CRITICAL REFACTOR: This function is now COSMETIC ONLY.
    - Used for display/logging/diagnostic purposes only
    - NOT used for market selection or expiry determination
    - Market selection uses Kalshi's close_ts field as single source of truth
    
    Kalshi ticker format: KXBTC15M-26JUN111330-30
    Suffix format: YYMMMDDHHMM-MM (INCLUDES YEAR)
    - YY: Year (2 digits, e.g., 26 for 2026)
    - MMM: Month (3-letter uppercase, e.g., JUN)
    - DD: Day (2 digits)
    - HHMM: Time in 24-hour format UTC (rounded down to 15-min boundary)
    - MM: Minute offset within the 15-min window (00, 15, 30, 45)
    "26APR22H12 - the date and the hour-quarter. This window opened at 12:00 UTC on April 22, 2026."
    
    Examples:
    - 2026-06-26 14:37:22 UTC → 26JUN261430-30 (year 26, June 26, 14:30 UTC)
    - 2026-06-26 14:02:05 UTC → 26JUN261400-00 (year 26, June 26, 14:00 UTC)
    """
    from merid.event_venues.kalshi.kalshi_15m_time import get_current_utc_window
    
    # Ensure UTC
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    
    # Use shared UTC helper to get current window
    window = get_current_utc_window(now)
    
    # DEBUG: Log the computed suffix for verification
    import logging
    logger = logging.getLogger(__name__)
    logger.info(
        "[COMPUTE-SUFFIX] now_utc=%s window.start_utc=%s window.end_utc=%s suffix=%s",
        now, window.start_utc, window.end_utc, window.suffix
    )
    
    return window.suffix


def get_target_ticker(series: str, now: datetime) -> str:
    """
    Build the full expected ticker for a series at a given time.
    
    CRITICAL REFACTOR: This function is now COSMETIC ONLY.
    - Used for display/logging/diagnostic purposes only
    - NOT used for market selection or expiry determination
    - Market selection uses Kalshi's close_ts field as single source of truth
    
    Args:
        series: Series ticker (e.g., "KXBTC15M")
        now: UTC timestamp
    
    Returns:
        Full ticker (e.g., "KXBTC15M-26JUN071430-30")
    """
    suffix = compute_current_window_suffix(now)
    return f"{series}-{suffix}"


async def diagnostic_broad_scan(client: KalshiVenueClient, now: datetime) -> Dict[str, Any]:
    """
    Perform a broad scan of 15m crypto markets to compare expected vs actual tickers.
    
    This diagnostic function helps distinguish between:
    1. Filter/status semantics (ticker exists but not returned by active_only=True)
    2. True listing gap (ticker not present in broad scan at all)
    
    Args:
        client: KalshiVenueClient instance
        now: UTC timestamp for target ticker computation
    
    Returns:
        Dict with diagnostic results:
        - target_tickers: Dict mapping series to expected ticker
        - all_15m_tickers: List of all 15m crypto tickers from broad scan
        - missing_targets: List of series whose target ticker is missing from broad scan
        - present_targets: List of series whose target ticker is present in broad scan
    """
    # Compute expected target tickers for all 5 series
    target_tickers = {
        series: get_target_ticker(series, now)
        for series in _PRIORITY_SERIES
    }
    
    # Perform broad scan without series-specific filter
    # Use a broader search to capture all 15m crypto markets
    # NOTE: No max_expiration_time filter - rely on snapshot() 0-30min expiry filtering instead
    # This ensures we fetch all available markets and filter by actual expiry time
    try:
        broad_result = await asyncio.wait_for(
            client.list_markets_result(
                MarketFilter(
                    search="15M",  # Broad search for 15-minute markets
                    active_only=False,  # Include all markets for discovery
                    limit=1000,
                )
            ),
            timeout=15.0
        )
        
        if broad_result.success and broad_result.data:
            all_15m_tickers = [m.market_id for m in broad_result.data if "15M" in m.market_id]
        else:
            all_15m_tickers = []
            logger.warning("[DIAG-BROAD-SCAN] Broad scan failed or returned no data")
    except Exception as e:
        logger.error("[DIAG-BROAD-SCAN] Broad scan exception: %s", e)
        all_15m_tickers = []
    
    # Compare expected vs actual
    missing_targets = []
    present_targets = []
    
    for series, target_ticker in target_tickers.items():
        if target_ticker in all_15m_tickers:
            present_targets.append(series)
        else:
            missing_targets.append(series)
    
    # Log diagnostic results
    logger.info(
        "[DIAG-TARGET-TICKERS] expected=%s",
        target_tickers
    )
    logger.info(
        "[DIAG-ALL-15M-TICKERS] count=%d sample=%s",
        len(all_15m_tickers),
        all_15m_tickers[:10] if all_15m_tickers else []
    )
    
    if missing_targets:
        logger.error(
            "[DIAG-MISSING-TARGETS] series=%s targets=%s - these tickers not in broad 15m scan",
            missing_targets,
            [target_tickers[s] for s in missing_targets]
        )
    else:
        logger.info(
            "[DIAG-ALL-TARGETS-PRESENT] all 5 expected tickers found in broad scan"
        )
    
    logger.info("DIAG-TARGET-TICKERS: %s", target_tickers)
    logger.info("DIAG-ALL-15M-TICKERS: count=%d sample=%s", len(all_15m_tickers), all_15m_tickers[:10] if all_15m_tickers else [])
    if missing_targets:
        logger.warning("DIAG-MISSING-TARGETS: series=%s targets=%s", missing_targets, [target_tickers[s] for s in missing_targets])
    else:
        logger.info("DIAG-ALL-TARGETS-PRESENT: all 5 expected tickers found")
    
    return {
        "target_tickers": target_tickers,
        "all_15m_tickers": all_15m_tickers,
        "missing_targets": missing_targets,
        "present_targets": present_targets,
    }
from merid.event_venues.kalshi.kalshi_config import get_kalshi_config
from merid.event_venues.kalshi.allowed_market_policy import (
    filter_allowed_markets,
    get_allowed_assets,
    is_market_allowed,
)
from merid.event_venues.kalshi.market_universe import MarketUniverse
from merid.event_venues.kalshi.expiry_fallback import apply_crypto_interval_expiry_fallback
from merid.event_venues.kalshi.contract_normalization import normalize_kalshi_contract
from utils.logger import get_logger

# Production scope validation
try:
    from config.trading_scope import (
        get_trading_scope,
        validate_series_ticker_for_trading,
    )
    TRADING_SCOPE_AVAILABLE = True
except ImportError:
    TRADING_SCOPE_AVAILABLE = False

logger = get_logger("merid.event_venues.kalshi.market_catalog")

def log_market_catalog_version() -> None:
    """Log market catalog version at startup (not import time)."""
    logger.info("[CATALOG-MODULE-LOADED] path=%s", __file__)
    logger.info("[MARKET-CATALOG VERSION v20260526a] Loaded - periodic market discovery and categorization")
    print("[MARKET-CATALOG VERSION v20260529a-cache-fix] Loaded - periodic market discovery and categorization")
    logger.info("[MARKET-CATALOG VERSION v20260529a-cache-fix] Loaded - periodic market discovery and categorization")


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
    """Enriched market with MERID-specific tags.
    
    Status fields:
        api_status: Raw Kalshi API status ("open", "closed", "settled", "paused")
        health_status: Normalization status ("ok", "expired", "invalid_metadata")
        tradeable: Derived flag indicating if market is currently tradable
                  (api_status in {"open", "closed"} AND health_status == "ok" 
                   AND 0 < minutes_to_expiry <= entry_window_max)
    """
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
    api_status: str = "unknown"  # Raw Kalshi API status
    health_status: str = "invalid_metadata"  # Normalization status
    tradeable: bool = False  # Derived flag for tradability


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

    def get_current_15m_market(self, asset: str) -> Optional[CatalogMarket]:
        """
        Get the current 15m market for a given asset from this snapshot.

        CRITICAL INVARIANT: There is exactly ONE active 15m market per asset at any time.
        This function resolves to that single market by exact ET window match.
        It does NOT select among multiple candidates - if the exact match is missing,
        the asset is unavailable for this window.

        Args:
            asset: Asset name (BTC, ETH, SOL, XRP, DOGE)

        Returns:
            CatalogMarket if found in current ET window, None otherwise
        """
        # CRITICAL FIX: Validate asset is in allowed list
        if asset not in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            logger.warning("[GET-CURRENT-15M] Invalid asset=%s - returning None", asset)
            return None
        
        from datetime import datetime, timezone
        from merid.event_venues.kalshi.kalshi_15m_time import get_kalshi_15m_window

        # Get current ET 15m window
        window = get_kalshi_15m_window()
        logger.info("[GET-CURRENT-15M] asset=%s window.end_utc=%s window.suffix=%s", asset, window.end_utc, window.suffix)

        # Filter to 15m markets for this asset that are NOT settled
        asset_markets = []
        for m in self.markets:
            if m.asset == asset and m.timeframe == "15m":
                # Status is in raw_data for EventMarket objects
                raw_data = m.market.raw_data or {}
                market_status = raw_data.get("status", "").lower()
                is_settled = market_status == "settled"
                if not is_settled:
                    asset_markets.append(m)

        logger.info("[GET-CURRENT-15M] asset=%s snapshot_markets=%d asset_15m_markets=%d", asset, len(self.markets), len(asset_markets))
        
        if not asset_markets:
            logger.warning("[GET-CURRENT-15M] asset=%s no 15m markets found - returning None", asset)
            return None

        # Find the market that exactly matches the current ET window end time
        # This enforces the single-market invariant: no selection, just exact match
        for m in asset_markets:
            # Get close time from market object
            if hasattr(m, 'expires_at') and m.expires_at:
                close_time = m.expires_at
                if close_time.tzinfo is None:
                    close_time = close_time.replace(tzinfo=timezone.utc)
            elif hasattr(m.market, 'end_date') and m.market.end_date:
                close_time = m.market.end_date
                if close_time.tzinfo is None:
                    close_time = close_time.replace(tzinfo=timezone.utc)
            else:
                continue

            # Check if close_time matches the current ET window end time (within 1 second tolerance)
            # CRITICAL FIX: Validate close_time is not None before comparison
            if close_time is None:
                continue
            # CRITICAL FIX: Validate window.end_utc is not None before comparison
            if window.end_utc is None:
                logger.warning("[GET-CURRENT-15M] window.end_utc is None - skipping market")
                continue
            time_diff = abs((close_time - window.end_utc).total_seconds())
            # CRITICAL FIX: Validate time_diff is reasonable (not NaN or extreme)
            if not (-10000 <= time_diff <= 10000):
                logger.warning(
                    "[GET-CURRENT-15M] Skipping market=%s extreme time_diff=%s",
                    m.market.market_id, time_diff
                )
                continue
            # CRITICAL FIX: Kalshi markets close 15 minutes after window end
            # Increase tolerance from 1s to 900s (15 minutes) to match market behavior
            if time_diff <= 900.0:
                return m

        # No exact match found - asset unavailable this window
        return None


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
        _MAX_REFRESH_INTERVAL_S = 600.0  # Maximum 10 minutes to prevent stale catalog
        if refresh_interval_s is None:
            import os
            # CRITICAL FIX: Reduce default refresh interval to 5s for 15m crypto markets
            # 15m markets have a 10-minute trading window (2-12 min to expiry)
            # 5s refresh ensures we catch window rollovers quickly
            refresh_interval_s = float(os.getenv("MERID_KALSHI_CATALOG_REFRESH_INTERVAL_S", "5.0"))
        
        # CRITICAL FIX: Validate refresh_interval_s is reasonable
        if refresh_interval_s < 0:
            logger.warning(
                "Catalog refresh interval %.1fs is negative - using default 5.0",
                refresh_interval_s
            )
            refresh_interval_s = 5.0
        
        if refresh_interval_s < _MIN_REFRESH_INTERVAL_S:
            logger.warning(
                "Catalog refresh interval %.1fs is below minimum %.1fs, clamping to minimum",
                refresh_interval_s, _MIN_REFRESH_INTERVAL_S
            )
            refresh_interval_s = _MIN_REFRESH_INTERVAL_S
        
        if refresh_interval_s > _MAX_REFRESH_INTERVAL_S:
            logger.warning(
                "Catalog refresh interval %.1fs is above maximum %.1fs, clamping to maximum",
                refresh_interval_s, _MAX_REFRESH_INTERVAL_S
            )
            refresh_interval_s = _MAX_REFRESH_INTERVAL_S
        
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
        # Thread-safe lock for _last_refresh access (refresh runs in separate thread)
        self._refresh_lock = threading.Lock()
        # Lazy-init lock to avoid event loop binding issues
        self._lock: Optional[asyncio.Lock] = None
        self._lock_init_lock = threading.Lock()
        self._task: Optional[asyncio.Task] = None
        # Lazy-init shutdown event to avoid event loop binding issues
        self._shutdown: Optional[asyncio.Event] = None
        self._shutdown_init_lock = threading.Lock()

        # Catalog audit tracking
        self._last_catalog_change_ts: Dict[str, datetime] = {}  # series_ticker -> last change timestamp
        self._last_catalog_ticker: Dict[str, str] = {}  # series_ticker -> last active ticker
        self._catalog_stuck_threshold_sec: float = 120.0  # 2 windows = 30s * 4 = 120s
        
        # Roll-over detection and single resync tracking
        self._last_rollover_sync_ts: Dict[str, float] = {}  # series_ticker -> last roll-over sync timestamp
        self._rollover_sync_cooldown_s: float = 60.0  # Only one resync per minute per series
        
        # Series health tracking (Kalshi alignment: Invariant 5)
        self._series_health: Dict[str, str] = {}  # series_ticker -> "healthy", "lagging", "no_active_tickers", "unknown"

        # Thread-based refresh loop to avoid event loop contention with WS bridge
        self._refresh_thread: Optional[threading.Thread] = None
        self._refresh_loop_started = threading.Event()
        self._first_refresh_completed = threading.Event()

    def _ensure_lock(self) -> asyncio.Lock:
        """Lazy-initialize the asyncio.Lock in the current event loop."""
        if self._lock is None:
            with self._lock_init_lock:
                if self._lock is None:
                    self._lock = asyncio.Lock()
        return self._lock

    def _ensure_shutdown_event(self) -> asyncio.Event:
        """Lazy-initialize the asyncio.Event in the current event loop."""
        if self._shutdown is None:
            with self._shutdown_init_lock:
                if self._shutdown is None:
                    self._shutdown = asyncio.Event()
        return self._shutdown

    def get_health_status(self) -> Dict[str, Any]:
        """Get catalog health status for readiness endpoint."""
        now = datetime.now(timezone.utc)
        with self._refresh_lock:
            last_refresh = self._last_refresh
        
        thread_alive = self._refresh_thread is not None and self._refresh_thread.is_alive()
        time_since_refresh = (now - last_refresh).total_seconds() if last_refresh else float('inf')
        
        # Catalog is stale if refresh interval is 5s but no refresh for >15s
        is_stale = time_since_refresh > (self._refresh_interval * 3)
        
        # CRITICAL: Check health of 5 crypto assets
        critical_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        asset_health = {}
        missing_assets = []
        
        snapshot = self.snapshot()
        for asset in critical_assets:
            asset_markets = [m for m in snapshot.markets if m.asset == asset and m.timeframe == "15m"]
            tradeable_markets = [m for m in asset_markets if m.tradeable]
            
            asset_health[asset] = {
                "total_15m_markets": len(asset_markets),
                "tradeable_15m_markets": len(tradeable_markets),
                "has_tradeable": len(tradeable_markets) > 0
            }
            
            if len(tradeable_markets) == 0:
                missing_assets.append(asset)
        
        # CRITICAL ALERT: Log if any critical assets are missing
        if missing_assets:
            logger.error(
                "[CATALOG-HEALTH] CRITICAL: Missing tradeable 15m markets for assets: %s. "
                "This will cause trading failures for these assets.",
                missing_assets
            )
        
        return {
            "last_refresh": last_refresh.isoformat() if last_refresh else None,
            "last_refresh_age_s": time_since_refresh,
            "thread_alive": thread_alive,
            "total_markets": len(self._markets),
            "refresh_count": self._refresh_count,
            "status": "stale" if is_stale else ("dead" if not thread_alive else "ok"),
            "critical_assets_health": asset_health,
            "missing_critical_assets": missing_assets,
            "all_critical_assets_present": len(missing_assets) == 0
        }

    # ── Lifecycle ────────────────────────────────────────────────────────

    def _run_refresh_loop_in_thread(self) -> None:
        """Run the refresh loop in a separate thread with its own event loop."""
        logger.critical("[CATALOG-THREAD] ENTRY - thread function reached")
        
        try:
            loop = asyncio.new_event_loop()
            # CRITICAL FIX: Do NOT call asyncio.set_event_loop(loop) here
            # Setting the loop globally causes it to be shared with other threads
            # When this loop is closed, it breaks unified_spot_service and other services
            # which use loop.run_in_executor(None, ...) with the default loop
            logger.info("[CATALOG-THREAD] Event loop created (thread-local, not set globally)")
        except Exception as e:
            logger.error(f"[CATALOG-THREAD] Failed to create event loop: {e}", exc_info=True)
            return
        
        # CRITICAL FIX: Initialize shutdown event in this thread's event loop
        # to avoid "bound to a different event loop" errors
        self._shutdown = asyncio.Event()
        logger.info("[CATALOG-THREAD] Shutdown event initialized in thread's event loop")
        
        self._refresh_loop_started.set()
        
        # CRITICAL FIX: Ensure loop never exits - restart on any crash
        while True:
            try:
                loop.run_until_complete(self._refresh_loop())
                logger.error("[CATALOG-THREAD] Refresh loop returned unexpectedly - restarting")
                # Create a new event loop if the old one was closed
                loop = asyncio.new_event_loop()
                # CRITICAL FIX: Do NOT call asyncio.set_event_loop(loop) here
                # Re-initialize shutdown event in new loop
                self._shutdown = asyncio.Event()
            except Exception as e:
                logger.error(f"[CATALOG-THREAD] Refresh loop thread crashed: {e}", exc_info=True)
                # Small backoff before restart
                import time
                time.sleep(1.0)
                # Create a new event loop
                loop = asyncio.new_event_loop()
                # CRITICAL FIX: Do NOT call asyncio.set_event_loop(loop) here
                # Re-initialize shutdown event in new loop
                self._shutdown = asyncio.Event()

    def start(self) -> None:
        """Start periodic refresh loop with initial refresh."""
        logger.critical("[CATALOG-START] ENTRY - start() method reached")
        logger.info("[CATALOG-START-DIAG] start() method entry point")
        logger.info("[CATALOG-START] start() ENTRY")
        
        if self._refresh_thread and self._refresh_thread.is_alive():
            logger.warning("[CATALOG-START] Catalog already started, skipping duplicate start")
            return
        
        # CRITICAL FIX: Do NOT initialize shutdown event here - it will be created in the thread's event loop
        # to avoid "bound to a different event loop" errors
        logger.info("[CATALOG-START-DIAG] Skipping shutdown.clear() - will be handled in thread")
        
        # CRITICAL FIX: Start refresh loop in separate thread to avoid event loop contention
        # The initial refresh will be done by the thread's first iteration
        # The WS bridge processes massive orderbook deltas that saturate the main event loop
        logger.info("[CATALOG-START] Starting refresh loop in separate thread...")
        
        self._refresh_thread = threading.Thread(
            target=self._run_refresh_loop_in_thread,
            name="kalshi-catalog-refresh-thread",
            daemon=True
        )
        
        self._refresh_thread.start()
        logger.info("[CATALOG-START] Thread started, waiting for event loop")
        
        # CRITICAL FIX: Wait for refresh thread to start its event loop
        # This ensures the thread is ready before we return
        self._refresh_loop_started.wait(timeout=5.0)
        if not self._refresh_loop_started.is_set():
            logger.error("[CATALOG-START] Refresh thread failed to start within 5s timeout")
        else:
            logger.info("[CATALOG-START] Refresh thread started successfully")
        
        # CRITICAL FIX: Wait for first refresh to complete before returning
        # This ensures the catalog has data before the 15m loop starts
        # Increased timeout to 60s to account for slow API responses during startup
        logger.info("[CATALOG-START] Waiting for first catalog refresh to complete...")
        self._first_refresh_completed.wait(timeout=60.0)  # Allow up to 60s for first refresh
        if not self._first_refresh_completed.is_set():
            logger.error("[CATALOG-START] First refresh did not complete within 60s timeout")
        else:
            logger.info("[CATALOG-START] First refresh completed successfully")
        
        logger.info(f"KalshiMarketCatalog started — refresh loop running in thread with {len(self._markets)} markets loaded")

    def stop(self) -> None:
        """Stop the periodic refresh loop."""
        logger.info("[CATALOG-STOP] Stopping catalog refresh loop...")
        self._ensure_shutdown_event().set()
        if self._refresh_thread and self._refresh_thread.is_alive():
            self._refresh_thread.join(timeout=10.0)
            if self._refresh_thread.is_alive():
                logger.warning("[CATALOG-STOP] Refresh thread did not stop within 10 seconds")
            else:
                logger.info("[CATALOG-STOP] Refresh thread stopped")
        
        # Reset events for clean restart
        self._refresh_loop_started.clear()
        self._first_refresh_completed.clear()
        logger.info("KalshiMarketCatalog stopped")

    async def _refresh_loop(self) -> None:
        logger.info("[CATALOG-REFRESH-LOOP] Starting periodic refresh loop (interval=%.1fs)", self._refresh_interval)
        
        # CRITICAL FIX: Do immediate refresh on thread startup
        logger.info("[CATALOG-REFRESH-LOOP] Performing immediate initial refresh in thread...")
        try:
            await self.refresh(force=True)
            logger.info(f"[CATALOG-REFRESH-LOOP] Initial refresh completed - catalog has {len(self._markets)} markets")
            # CRITICAL: Signal that first refresh has completed
            self._first_refresh_completed.set()
            logger.info("[CATALOG-REFRESH-LOOP] First refresh completed event set")
        except Exception as e:
            logger.error(f"[CATALOG-REFRESH-LOOP] Initial refresh failed: {e}", exc_info=True)
            # Still set the event so startup can proceed (catalog will be empty but not blocked)
            self._first_refresh_completed.set()
            logger.warning("[CATALOG-REFRESH-LOOP] First refresh completed event set despite failure")
        
        # CRITICAL FIX: Use while True to ensure loop never exits silently
        iteration_count = 0
        while True:
            iteration_count += 1
            try:
                logger.info("[CATALOG-REFRESH-LOOP] Iteration %d: Sleeping for %.1fs before next refresh", iteration_count, self._refresh_interval)
                await asyncio.sleep(self._refresh_interval)
                if self._ensure_shutdown_event().is_set():
                    logger.info("[CATALOG-REFRESH-LOOP] Shutdown requested, exiting loop")
                    break
                logger.info("[CATALOG-REFRESH-LOOP] Iteration %d: Starting refresh", iteration_count)
                # CRITICAL: Add timeout to prevent indefinite blocking
                try:
                    await asyncio.wait_for(self.refresh(force=True), timeout=30.0)
                    logger.info("[CATALOG-REFRESH-LOOP] Iteration %d: Refresh completed", iteration_count)
                except asyncio.TimeoutError:
                    logger.error("[CATALOG-REFRESH-LOOP] Iteration %d: Refresh timed out after 30s", iteration_count)
                    # Continue loop despite timeout
            except Exception as e:
                logger.exception("[CATALOG-REFRESH-LOOP] Iteration %d: crashed", iteration_count, exc_info=e)
                # Small backoff to avoid hammering if it's broken
                await asyncio.sleep(self._refresh_interval)
        
        logger.info("[CATALOG-REFRESH-LOOP] Refresh loop exited after %d iterations", iteration_count)

    # ── Core refresh ─────────────────────────────────────────────────────

    async def refresh(self, force: bool = False) -> int:
        """Refresh the catalog from the Kalshi API.

        Args:
            force: If True, bypass rate limiting and force a refresh.

        Returns:
            Number of markets in the catalog after refresh.
        """
        # CRITICAL FIX: Implement rate limiting to prevent excessive catalog refreshes
        # Only refresh if at least 30 seconds have passed since last refresh
        # Rate limiting is bypassed when force=True (for periodic loop calls)
        now = datetime.now(timezone.utc)
        with self._refresh_lock:
            last_refresh = self._last_refresh
        time_since_refresh = (now - last_refresh).total_seconds() if last_refresh else 0
        
        if not force and last_refresh:
            if time_since_refresh < self._refresh_interval:
                logger.info(
                    "[CATALOG-REFRESH-RATE-LIMIT] Skipping refresh - last refresh was %.1fs ago (min %.1fs)",
                    time_since_refresh, self._refresh_interval
                )
                return len(self._markets)
        
        logger.info("[CATALOG-REFRESH] Starting catalog refresh (last refresh: %s, interval: %s)",
                   last_refresh, f"{time_since_refresh:.1f}s" if last_refresh else "N/A")
        logger.debug("[CATALOG-REFRESH-ENTRY] refresh() called, force=%s", force)

        refresh_start = datetime.now(timezone.utc)
        now_utc = datetime.now(timezone.utc)

        # CRITICAL FIX: Remove lock to prevent deadlock
        # The refresh loop runs in a separate thread with its own event loop
        # Rate limiting is handled by the loop's sleep interval, not by a lock
        try:
            # PRODUCTION AUDIT (Step 3): Priority series restricted to 15m only
            # 5 assets (BTC, ETH, SOL, XRP, DOGE) x 15m timeframe only.
            # All other timeframes are signal-only and excluded from trading catalog.
            logger.info("[CATALOG-REFRESH] Fetching priority series tickers...")
            _PRIORITY_SERIES = list(
                dict.fromkeys(
                    kalshi_agent_grid_catalog_series_tickers()
                )
            )
            logger.info("[CATALOG-REFRESH] Priority series tickers fetched: %s", _PRIORITY_SERIES)
            
            # PRODUCTION AUDIT (Step 3): Log scope enforcement
            logger.info(
                "[DISCOVERY_SCOPE] Catalog refresh using production whitelist: "
                f"series={_PRIORITY_SERIES} (BTC/ETH/SOL/XRP/DOGE 15m only)"
            )
            raw_markets: list = []
            seen_tickers: set = set()

            # 1. Fetch priority series with rate limiting and retry logic for 429 errors
            # CRITICAL FIX: Use REST API directly for crypto 15m series to bypass public API rate limits
            # CRITICAL FIX: Add max_expiration_time filter to fetch only markets within 16 minutes to prevent old tickers
            async def _fetch_series_with_retry(series: str, now_utc: datetime, max_retries: int = 3):
                for attempt in range(max_retries):
                    try:
                        logger.info("[CATALOG-FETCH] Fetching series=%s with REST API (attempt %d/%d)", series, attempt + 1, max_retries)

                        # Use REST API directly via _request_with_resilience
                        # CRITICAL FIX: Add max_expiration_time filter to fetch only markets within 16 minutes
                        # This reduces data transfer and prevents old tickers from being fetched at the source
                        max_expiry = now_utc + timedelta(minutes=16)
                        max_expiry_str = max_expiry.strftime("%Y-%m-%dT%H:%M:%SZ")

                        result = await self._client._request_with_resilience(
                            "GET",
                            f"/markets?series_ticker={series}&limit=200&max_expiration_time={max_expiry_str}",
                            operation_name=f"fetch_series_{series}"
                        )
                        
                        if result.success and result.data:
                            markets = result.data
                            logger.info("[CATALOG-FETCH] Fetched series=%s count=%d via REST API", series, len(markets))
                            return series, result
                        else:
                            logger.warning("[CATALOG-FETCH] REST API error for series=%s: %s", series, result.error)
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2 ** attempt)
                                continue
                            else:
                                return series, None
                            
                    except asyncio.TimeoutError:
                        logger.warning("Catalog series fetch timeout: series=%s timeout=15s (attempt %d/%d)", series, attempt + 1, max_retries)
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2 ** attempt)  # Exponential backoff
                        else:
                            return series, None
                    except Exception as _exc:
                        # Check if it's a 429 error
                        if "429" in str(_exc) or "Too Many Requests" in str(_exc):
                            logger.warning("Catalog series fetch 429 rate limit: series=%s (attempt %d/%d), retrying with backoff", series, attempt + 1, max_retries)
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s, 4s
                                continue
                            else:
                                logger.error("Catalog series fetch failed after %d retries due to rate limit: series=%s", max_retries, series)
                                return series, None
                        else:
                            logger.warning("Catalog series fetch error: series=%s err=%s (attempt %d/%d)", series, _exc, attempt + 1, max_retries)
                            if attempt < max_retries - 1:
                                await asyncio.sleep(1)  # Brief pause before retry
                            else:
                                return series, None
                return series, None

            # Stagger fetches to avoid 429 rate limit errors
            # CRITICAL FIX: Increase stagger to 1 second to avoid Kalshi API rate limits
            # 200ms was insufficient - still getting 429 errors
            tasks = []
            for i, series in enumerate(_PRIORITY_SERIES):
                task = asyncio.create_task(_fetch_series_with_retry(series, now_utc))
                tasks.append(task)
                # Stagger by 1 second between each fetch to avoid rate limiting
                if i < len(_PRIORITY_SERIES) - 1:
                    await asyncio.sleep(1.0)

            results = await asyncio.gather(*tasks, return_exceptions=False)
            series_to_markets = {}
            for series, r in results:
                if r is None:
                    series_to_markets[series] = []
                    continue
                # Handle REST API response format: {'markets': [...]}
                raw_markets_list = r.data if isinstance(r.data, list) else r.data.get('markets', []) if isinstance(r.data, dict) else []
                
                # Convert raw dicts to EventMarket objects for enrichment
                markets_list = []
                for raw_m in raw_markets_list:
                    try:
                        # Parse raw dict to KalshiMarket, then convert to EventMarket
                        kalshi_market = self._client._parse_market(raw_m)
                        if kalshi_market:
                            event_market = self._client._to_event_market(kalshi_market)
                            if event_market:
                                markets_list.append(event_market)
                            else:
                                logger.warning("[CATALOG-CONVERT] _to_event_market returned None for market_id=%s", raw_m.get('market_id', 'unknown'))
                        else:
                            logger.warning("[CATALOG-CONVERT] _parse_market returned None for market_id=%s", raw_m.get('market_id', 'unknown'))
                    except Exception as e:
                        logger.warning("[CATALOG-CONVERT] Failed to convert market to EventMarket: market_id=%s error=%s", raw_m.get('market_id', 'unknown'), e)
                
                _count = len(markets_list) if r.success else 0
                logger.info(
                    "Catalog series fetch: series=%s status=%s count=%d sample=%s",
                    series,
                    "ok" if r.success else r.error,
                    _count,
                    [m.market_id for m in (markets_list or [])[:3]],
                )
                if r.success:
                    # Log ticker canonicality for first 3 markets per series
                    for m in markets_list[:3]:
                        logger.info(
                            "[CATALOG-TICKER] series=%s ticker=%s expiry=%s",
                            series,
                            m.market_id,
                            m.close_date if hasattr(m, 'close_date') else 'N/A'
                        )
                    # DIAGNOSTIC: Log ALL tickers to see what markets are available
                    logger.info(
                        "[CATALOG-ALL-TICKERS] series=%s total_markets=%d tickers=%s",
                        series,
                        len(markets_list),
                        [m.market_id for m in markets_list]
                    )
                    # CRITICAL DIAGNOSTIC: Write to health_diagnostic.txt to ensure capture
                    logger.debug("CATALOG-ALL-TICKERS: series=%s total_markets=%d tickers=%s", series, len(markets_list), [m.market_id for m in markets_list])
                    logger.debug("CATALOG-FILTER-DEBUG: AFTER robust discovery, series=%s, r.success=%s, markets_list length=%d", series, r.success, len(markets_list) if markets_list else 0)
                    # ROBUST DISCOVERY: If active_only=True returns 0, try active_only=False for ALL series
                    if len(markets_list) == 0:
                        logger.warning(
                            "[CATALOG-ROBUST] series=%s returned 0 active markets with active_only=True - attempting fallback with active_only=False",
                            series
                        )
                        try:
                            # CRITICAL FIX: Add max_expiration_time filter to prevent fetching markets expired hours ago
                            # This prevents old markets from being logged and processed
                            max_expiry = now_utc + timedelta(minutes=16)
                            debug_result = await asyncio.wait_for(
                                self._client.list_markets_result(
                                    MarketFilter(active_only=False, limit=200, search=series, max_expiration_time=max_expiry)
                                ),
                                timeout=15.0
                            )
                            debug_count = len(debug_result.data) if debug_result.success else 0
                            logger.warning(
                                "[CATALOG-ROBUST] series=%s active_only=False count=%d tickers=%s",
                                series,
                                debug_count,
                                [m.market_id for m in (debug_result.data or [])]
                            )
                            
                            # If fallback found markets, use those instead
                            if debug_result.success and debug_result.data:
                                logger.info(
                                    "[CATALOG-ROBUST] series=%s recovered %d markets from fallback, using those",
                                    series,
                                    len(debug_result.data)
                                )
                                # Handle REST API response format for fallback
                                fallback_markets = debug_result.data if isinstance(debug_result.data, list) else debug_result.data.get('markets', []) if isinstance(debug_result.data, dict) else []
                                markets_list = fallback_markets
                        except Exception as debug_exc:
                            logger.error(
                                "[CATALOG-ROBUST] series=%s fallback fetch failed: %s",
                                series,
                                debug_exc
                            )
                    
                    series_to_markets[series] = markets_list if r.success else []
                    logger.debug("CATALOG-FILTER-DEBUG: AFTER series_to_markets assignment, series=%s, r.success=%s, markets_list length=%d", series, r.success, len(markets_list))
                    for m in markets_list:
                        # CRITICAL FIX: Filter out expired markets before adding to raw_markets
                        # This prevents markets expired hours ago from being logged and processed
                        if m.end_date:
                            minutes_to_expiry = (m.end_date - now_utc).total_seconds() / 60.0
                            if minutes_to_expiry < -5.0:  # Allow slight buffer, but reject truly old markets
                                logger.debug(
                                    "[CATALOG-FILTER-EXPIRED] Skipping expired market: ticker=%s minutes_to_expiry=%.1f",
                                    m.market_id, minutes_to_expiry
                                )
                                continue
                        
                        if m.market_id not in seen_tickers:
                            raw_markets.append(m)
                            seen_tickers.add(m.market_id)
                else:
                    series_to_markets[series] = []
            
            # CRITICAL DIAGNOSTIC: Log raw_markets count before health check
            logger.debug("CATALOG-PRE-HEALTH-CHECK: raw_markets count=%d series_to_markets keys=%s", len(raw_markets), list(series_to_markets.keys()))
            
            # CATALOG HEALTH CHECK: Alert but continue with partial set after robust discovery
            missing_series = [s for s in _PRIORITY_SERIES if not series_to_markets.get(s)]
            if missing_series:
                logger.error(
                    "[CATALOG-PARTIAL] After robust discovery, still missing series=%s (expected 5, discovered %d). "
                    "Continuing with partial asset set - this may indicate a Kalshi listing gap or temporary liquidity issue.",
                    missing_series,
                    len([s for s in _PRIORITY_SERIES if series_to_markets.get(s)])
                )
                logger.warning("CATALOG-PARTIAL: missing_series=%s discovered=%d/5 - CONTINUING WITH PARTIAL SET", missing_series, len([s for s in _PRIORITY_SERIES if series_to_markets.get(s)]))
                
                # DIAGNOSTIC: Run broad scan to distinguish filter vs listing gap
                logger.info("[DIAGNOSTIC] Running broad scan to diagnose missing series")
                diag_results = await diagnostic_broad_scan(self._client, refresh_start)
            else:
                logger.info(
                    "[CATALOG-FULL] Successfully discovered all 5 series with robust discovery: %s",
                    sorted([s for s in _PRIORITY_SERIES if series_to_markets.get(s)])
                )
                logger.info("CATALOG-FULL: raw_markets count=%d", len(raw_markets))

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

        # CRITICAL FIX: Enrich markets BEFORE filtering
        # The filter needs asset/category fields to work correctly, but these are only set during enrichment
        # Previously we filtered raw markets (asset=None, category=None) which caused issues
        logger.info(
            "[ENRICHMENT-PRE-FILTER] Enriching %d raw markets before filtering",
            len(raw_markets)
        )
        enriched_markets = []
        for mkt in raw_markets:
            cm = self._enrich(mkt, now)
            enriched_markets.append(cm)
        logger.info(
            "[ENRICHMENT-PRE-FILTER] Enriched %d markets",
            len(enriched_markets)
        )

        # Apply AllowedMarketPolicy filter at the edge
        # This ensures only BTC/ETH/SOL/XRP/DOGE 15m markets proceed to indexing
        logger.info(
            "[ALLOWED-MARKET-POLICY] Pre-filter: %d enriched markets",
            len(enriched_markets)
        )
        filtered_markets = filter_allowed_markets(enriched_markets)
        logger.info(
            "[ALLOWED-MARKET-POLICY] Post-filter: %d markets allowed (BTC/ETH/SOL/XRP/DOGE 15m only)",
            len(filtered_markets)
        )

        # CRITICAL FIX: Add time-based filtering to prevent future market contamination
        # Filter to only markets within 0-15.5 minutes to expiry (current 15m window)
        # This prevents 4-day future markets and old tickers from previous windows from being fed to the state store
        from merid.event_venues.kalshi.kalshi_15m_time import compute_minutes_to_expiry
        now_utc = datetime.now(timezone.utc)
        
        # Visibility filter: markets visible for data/WS subscription (-5 to 15.5 min)
        # CRITICAL FIX: Include markets from -5 minutes to account for Kalshi's lifecycle
        # where markets open ~5 minutes before the window starts (unopened -> open)
        # This ensures unopened markets that are about to become open are visible
        visible_markets = []
        for cm in filtered_markets:
            if cm.expires_at:
                mte = compute_minutes_to_expiry(cm.expires_at, now_utc)
                # CRITICAL FIX: Validate mte is not None and is reasonable
                if mte is None:
                    logger.warning(
                        "[CATALOG-VISIBILITY-FILTER] Skipping market=%s (mte is None)",
                        cm.market.market_id
                    )
                    continue
                if not (-1000 <= mte <= 10000):
                    logger.warning(
                        "[CATALOG-VISIBILITY-FILTER] Skipping market=%s extreme mte=%.1fmin",
                        cm.market.market_id, mte
                    )
                    continue
                if 0.0 <= mte <= 15.5:  # Only include non-expired markets (0 to 15.5 min to expiry)
                    visible_markets.append(cm)
                else:
                    logger.debug(
                        "[CATALOG-VISIBILITY-FILTER] Skipping market=%s mte=%.1fmin (outside -5 to 15.5min window)",
                        cm.market.market_id, mte
                    )
            else:
                logger.warning(
                    "[CATALOG-VISIBILITY-FILTER] Skipping market=%s (no expiry time)",
                    cm.market.market_id
                )

        logger.info(
            "[CATALOG-VISIBILITY-FILTER] Post-visibility-filter: %d markets in 0 to 15.5min window (from %d)",
            len(visible_markets), len(filtered_markets)
        )
        
        # Tradeability filter: markets eligible for agent entry (2-12 min entry window)
        # This is separate from visibility to allow agents to see markets but only enter in optimal window
        tradeable_markets = []
        for cm in visible_markets:
            if cm.expires_at:
                mte = compute_minutes_to_expiry(cm.expires_at, now_utc)
                if 2.0 <= mte <= 12.0:  # Entry window for optimal trading
                    tradeable_markets.append(cm)
                    # Mark as tradeable in the CatalogMarket object
                    cm.tradeable = True
                else:
                    # Market is visible but not tradeable (outside entry window)
                    cm.tradeable = False
                    logger.debug(
                        "[CATALOG-TRADEABILITY-FILTER] Market=%s mte=%.1fmin is visible but not tradeable (outside 2-12min entry window)",
                        cm.market.market_id, mte
                    )
        
        logger.info(
            "[CATALOG-TRADEABILITY-FILTER] Post-tradeability-filter: %d markets in 2-12min entry window (from %d visible)",
            len(tradeable_markets), len(visible_markets)
        )
        
        # Use visible markets for indexing and feed (includes all markets in current 15m window)
        filtered_markets = visible_markets

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
        
        # CRITICAL FIX: Check if event loop is still running before submitting to executor
        # This prevents "cannot schedule new futures after shutdown" errors
        if loop.is_closed() or not loop.is_running():
            logger.error("[CATALOG-REFRESH] Event loop is closed or not running - cannot build indexes")
            raise RuntimeError("Event loop shutdown during catalog refresh")
        
        # CRITICAL FIX: Check if shutdown was requested before submitting to executor
        if self._ensure_shutdown_event().is_set():
            logger.info("[CATALOG-REFRESH] Shutdown requested - skipping index build")
            raise RuntimeError("Shutdown requested during catalog refresh")
        
        # CRITICAL FIX: Use try/except to handle executor shutdown gracefully
        try:
            enriched, cat_idx, asset_idx, tf_idx, ticker_idx, categories_found, assets_found = await loop.run_in_executor(
                None, self._build_indexes, filtered_markets, now
            )
        except RuntimeError as e:
            if "cannot schedule new futures after shutdown" in str(e):
                logger.error("[CATALOG-REFRESH] Executor shutdown detected - event loop closing")
                raise RuntimeError("Executor shutdown during catalog refresh") from e
            else:
                raise

        # Debug logging for first refresh to see what's happening
        if self._refresh_count == 0 and enriched:
            sample = enriched[0]
            logger.debug(
                f"Sample market: ticker={sample.market.market_id}, "
                f"category={sample.category}, asset={sample.asset}, "
                f"question={sample.market.question[:50]}..."
            )
            # CRITICAL DIAGNOSTIC: Log exact ticker format from Kalshi REST API
            logger.info(
                "[CATALOG-TICKER-FORMAT] Kalshi REST API ticker format: %s (first 5 tickers: %s)",
                sample.market.market_id,
                [m.market.market_id for m in enriched[:5]]
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
        
        # Enforce catalog invariants: exactly 5 assets (BTC, ETH, SOL, XRP, DOGE) with 15m tickers
        from config.kalshi_15m_crypto_config import KALSHI_15M_SERIES_TICKERS
        expected_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        assets_with_tickers = set()
        assets_missing_tickers = []
        
        for asset in expected_assets:
            series_ticker = KALSHI_15M_SERIES_TICKERS.get(asset)
            asset_markets = [m for m in enriched if m.asset == asset and m.series_ticker == series_ticker]
            if asset_markets:
                assets_with_tickers.add(asset)
            else:
                assets_missing_tickers.append(asset)
        
        # Log invariant check results
        if len(assets_with_tickers) == len(expected_assets):
            logger.info(
                "[CATALOG-INVARIANT] PASS: All 5 assets have active 15m tickers: %s",
                sorted(assets_with_tickers)
            )
        else:
            # Reduce log level from ERROR to WARNING - this is transient during startup/refresh
            # System triggers WS bridge sync to recover, so not a critical error
            logger.warning(
                "[CATALOG-INVARIANT] FAIL: Missing 15m tickers for assets: %s (have: %s, expected: %s)",
                assets_missing_tickers,
                sorted(assets_with_tickers),
                sorted(expected_assets)
            )
            # This is a catalog/WS bug - not "no market" - should be treated as a system error
            if assets_missing_tickers:
                logger.warning(
                    "[CATALOG-INVARIANT] System cannot trade missing assets - triggering WS bridge sync for recovery"
                )
        
        # Calculate total refresh latency
        refresh_end = datetime.now(timezone.utc)
        total_latency_ms = (refresh_end - refresh_start).total_seconds() * 1000
        time_since_last = (now - last_refresh).total_seconds() if last_refresh else 0
        
        # Thread-safe update of _last_refresh (refresh runs in separate thread)
        with self._refresh_lock:
            self._last_refresh = now
            self._refresh_count += 1

        _log = logger.info if enriched else logger.debug
        _log(
            f"Catalog refreshed: {len(enriched)} markets, "
            f"{len(cat_idx)} categories, {len(asset_idx)} assets"
        )
        
        logger.info(
            f"[CATALOG-REFRESH-METRICS] completed | "
            f"total_latency={total_latency_ms:.0f}ms | "
            f"markets_added={len(enriched)} | "
            f"time_since_last={time_since_last:.1f}s"
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

        # CRITICAL: Universe management - sync catalog, WS bridge, and state store
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            from merid.event_venues.kalshi.universe_manager import get_universe_manager
            store = get_kalshi_market_state_store()
            universe = get_universe_manager()
            
            # Get current ticker sets
            catalog_tickers = {m.market.market_id for m in enriched}
            state_tickers = set(store._states.keys()) if hasattr(store, '_states') else set()
            
            # Validate universe invariant
            # CRITICAL FIX: Use canonical WS bridge from merid.event_venues.kalshi
            # This prevents creating duplicate WS connections during catalog refresh
            from merid.event_venues.kalshi.ws_bridge import get_bridge
            bridge = get_bridge()
            ws_tickers = set(bridge._subscribed_tickers) if hasattr(bridge, '_subscribed_tickers') else set()
            
            validation_result = universe.validate_universe_invariant(
                catalog_tickers, state_tickers, ws_tickers
            )
            
            # If validation fails, trigger WS bridge sync
            if not validation_result["valid"]:
                logger.error("[CATALOG-REFRESH] Universe invariant violated, triggering WS bridge sync")
                try:
                    # Set sync flag for WS bridge to pick up in its main event loop
                    bridge._sync_requested = True
                    logger.info("[CATALOG-REFRESH] WS bridge sync flag set")
                except Exception as sync_error:
                    logger.error(f"[CATALOG-REFRESH] Failed to set WS bridge sync flag: {sync_error}")
            else:
                logger.info("[CATALOG-REFRESH] Universe invariant validated, no sync needed")
            
            # Clean up stale market states
            store.cleanup_stale_states(list(catalog_tickers))
            logger.info(f"[CATALOG-REFRESH] Universe management completed, catalog tickers: {len(catalog_tickers)}")
            
        except Exception as universe_error:
            logger.error(f"[CATALOG-REFRESH] Universe management failed: {universe_error}")

        # Feed REST data into MarketStateStore so expiry/volume/OI/strikes are available
        # for UI display (crypto spot vs kalshi needs these fields).
        # RE-ENABLED: Async feed to populate expiry fields for timing-aware SLA
        # This is critical for MD health reporting (minutes_to_expiry calculation)
        logger.info("[BOOT-TRACE] Catalog → MarketStateStore async feed starting (expiry fields for SLA)")
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        store = get_kalshi_market_state_store()
        
        # Feed expiry data synchronously to avoid lock hang
        # Only populate REST-owned fields (expiry, volume, OI, strikes)
        # WS-owned fields (bid/ask) are handled by WS bridge
        feed_count = 0
        missing_expiry_count = 0
        logger.info(f"[CATALOG-FEED] Starting feed loop for {len(enriched)} enriched markets")
        
        # CRITICAL DIAGNOSTIC: Log first 5 tickers to verify time window filtering
        sample_tickers = [cm.market.market_id for cm in enriched[:5]]
        logger.info(
            f"[CATALOG-FEED] Sample tickers being fed to state store: {sample_tickers}"
        )
        
        for idx, cm in enumerate(enriched):
            ticker = cm.market.market_id
            logger.info(f"[CATALOG-FEED] Processing market {idx+1}/{len(enriched)}: ticker={ticker} asset={cm.asset}")
            try:
                # EventMarket uses end_date, not close_time
                expiry_dt = cm.market.end_date
                if expiry_dt is None:
                    logger.error(
                        f"[CATALOG-FEED] MISSING_EXPIRY_FOR_15M_MARKET: ticker={ticker} "
                        f"asset={cm.asset} has no end_date - cannot compute seconds_to_expiry"
                    )
                    missing_expiry_count += 1
                    continue
                
                market_data = {
                    "ticker": cm.market.market_id,
                    "expiration_time": expiry_dt.isoformat(),
                    "expected_expiration_time": expiry_dt.isoformat(),
                    "latest_expiration_time": expiry_dt.isoformat(),
                    "volume_24h": int(cm.market.volume) if cm.market.volume else 0,
                    "open_interest": int(cm.market.open_interest) if cm.market.open_interest else 0,
                    "notional_value": 0,  # Not available in EventMarket
                    "underlying": cm.asset,
                    "strike_price": cm.strike_price,
                    "floor_strike": cm.floor_strike,
                    "cap_strike": cm.cap_strike,
                    "status": "open" if cm.market.active else "closed",
                }
                # Apply REST data to state store (async-safe)
                logger.info(f"[CATALOG-FEED] About to call apply_rest_market for ticker={ticker}")
                store.apply_rest_market(market_data)
                feed_count += 1
                logger.info(f"[CATALOG-FEED] Successfully fed ticker={ticker} (count={feed_count})")
            except Exception as e:
                logger.error(
                    f"[CATALOG-FEED] Failed to feed market {ticker}: {e}",
                    exc_info=True
                )
                # Continue to next ticker instead of breaking
                continue
        
        logger.info(f"[BOOT-TRACE] Catalog → MarketStateStore async feed completed: {feed_count}/{len(enriched)} markets fed successfully")

        # Pre-register settlement buffers for RTI-settled markets so the
        # 60-slot grid is allocated before the first RTI tick arrives.
        try:
            from config.kalshi_crypto_series_meta import is_rti_settled_kalshi_crypto_ticker
            from merid.data.settlement_rti_buffer import get_settlement_buffer_registry
            _sb_reg = get_settlement_buffer_registry()
            await self._ensure_buffers_batched(enriched, _sb_reg, batch_size=10)
        except Exception as _sb_exc:
            logger.debug("Settlement buffer registration error (non-fatal): %s", _sb_exc)

        # Catalog audit: log snapshot and check for lagging detection
        self._log_catalog_snapshot(now_utc=now)
        self._check_catalog_lagging(now_utc=now)

        return len(enriched)

    # ── Catalog audit methods ─────────────────────────────────────────────

    def _log_catalog_snapshot(self, now_utc: datetime) -> None:
        """Log CATALOG-SNAPSHOT for each 15m series with window alignment check."""
        import os
        from config.kalshi_universe import kalshi_agent_grid_catalog_series_tickers

        series_tickers = kalshi_agent_grid_catalog_series_tickers()
        max_staleness_sec = float(os.getenv("CATALOG_MAX_STALENESS_SEC", "60"))

        for series_ticker in series_tickers:
            # Get active markets for this series
            series_markets = [m for m in self._markets if m.series_ticker == series_ticker]
            
            # Calculate expected current window start (15m alignment)
            minute = now_utc.minute
            window_minute = (minute // 15) * 15
            current_window_start = now_utc.replace(minute=window_minute, second=0, microsecond=0)
            current_window_end = current_window_start + timedelta(minutes=15)
            
            # 15-MINUTE ENTRY WINDOW FILTER: Include markets with 0-15 minutes to expiry
            # Kalshi 15-minute markets open at the top of each quarter hour (00, 15, 30, 45)
            # and trade for exactly 15 minutes before settling
            from merid.event_venues.kalshi.kalshi_15m_time import compute_minutes_to_expiry
            
            active_tickers = []
            for m in series_markets:
                # Status is in raw_data for EventMarket objects
                raw_data = m.market.raw_data or {}
                market_status = raw_data.get("status", "").lower()
                is_settled = market_status == "settled"
                
                if not is_settled:
                    # Filter by 0-15 minute entry window
                    if m.expires_at:
                        mte = compute_minutes_to_expiry(m.expires_at, now_utc)
                        if 0.0 <= mte <= 15.0:
                            active_tickers.append(m.market.market_id)

            # CRITICAL FIX: Removed selection logic - no longer needed
            # The canonical get_current_15m_market() now handles market resolution by exact window match
            # This diagnostic snapshot only needs to log active tickers, not select one
            # Set best_ticker to first active ticker for legacy compatibility (needed for window alignment check)
            best_ticker = active_tickers[0] if active_tickers else None

            # Log snapshot
            with self._refresh_lock:
                last_refresh_snapshot = self._last_refresh
            age_since_refresh = (now_utc - last_refresh_snapshot).total_seconds() if last_refresh_snapshot else 0
            logger.info(
                "[CATALOG-SNAPSHOT] series=%s now_utc=%s current_window_start=%s "
                "active_tickers=%s age_since_refresh=%.1fs max_staleness=%s",
                series_ticker,
                now_utc.isoformat(),
                current_window_start.isoformat(),
                active_tickers[:5] if len(active_tickers) > 5 else active_tickers,
                age_since_refresh,
                max_staleness_sec
            )

            # Window alignment check
            if best_ticker:
                # HF-RELAX: Handle single-contract series as normal case
                # Kalshi API returns only 1 active 15m contract per series, not a rolling window
                # So ticker changes only when contract expires, not every 15 minutes
                # Check if the current contract is still valid (not expired)
                best_market = self._by_ticker.get(best_ticker)
                contract_valid = False
                if best_market and hasattr(best_market, 'market'):
                    market = best_market.market
                    if hasattr(market, 'end_date') and market.end_date:
                        # Contract is valid if it hasn't expired yet
                        contract_valid = market.end_date > now_utc
                
                # Check if ticker has advanced since last snapshot
                last_ticker = self._last_catalog_ticker.get(series_ticker)
                if last_ticker != best_ticker:
                    self._last_catalog_change_ts[series_ticker] = now_utc
                    self._last_catalog_ticker[series_ticker] = best_ticker
                    # Ticker advanced - mark series as healthy
                    self._series_health[series_ticker] = "healthy"
                    
                    # Extract asset from series ticker for logging
                    asset = series_ticker.replace("15M", "").replace("15m", "").replace("KX", "")
                    
                    # Log explicit 15m contract schedule
                    logger.info(
                        "[15M-SCHEDULE] asset=%s new_front=%s window_start=%s window_end=%s",
                        asset,
                        best_ticker,
                        current_window_start.isoformat(),
                        (current_window_start.replace(minute=(current_window_start.minute + 15) % 60, second=0, microsecond=0)).isoformat()
                    )
                    
                    # Reset strip order counts when ticker changes (new 15m strip)
                    # This prevents stale strip limits from blocking new markets
                    try:
                        from merid.prediction.agent_grid_15m import reset_strip_order_counts
                        reset_strip_order_counts()
                        logger.info(
                            "[CATALOG-STRIP-RESET] Ticker changed for %s from %s to %s - reset strip order counts",
                            series_ticker, last_ticker, best_ticker
                        )
                    except ImportError:
                        logger.debug("[CATALOG-STRIP-RESET] agent_grid_15m not available, skipping strip reset")
                    except Exception as e:
                        logger.warning("[CATALOG-STRIP-RESET] Failed to reset strip order counts: %s", e)
                    
                    # Sync WS bridge subscriptions to new front ticker with cooldown protection
                    # This fixes the roll-over bug where WS stays subscribed to expired contracts
                    # Only trigger one resync per series per cooldown period to prevent churning
                    try:
                        from merid.event_venues.kalshi.ws_bridge import get_bridge
                        ws_bridge = get_bridge()
                        
                        # Check cooldown before triggering resync
                        now = now_utc.timestamp()
                        last_sync = self._last_rollover_sync_ts.get(series_ticker, 0.0)
                        if now - last_sync < self._rollover_sync_cooldown_s:
                            logger.debug(
                                "[CATALOG-STRIP-RESET] Skipping resync for %s - cooldown active (%.1fs remaining)",
                                series_ticker, self._rollover_sync_cooldown_s - (now - last_sync)
                            )
                        elif ws_bridge:
                            ws_bridge._sync_requested = True
                            self._last_rollover_sync_ts[series_ticker] = now
                            logger.info(
                                "[CATALOG-STRIP-RESET] Requested WS bridge resync for %s roll-over (sync_requested flag set)",
                                series_ticker
                            )
                        else:
                            logger.debug("[CATALOG-STRIP-RESET] WS bridge not available, skipping resync")
                    except ImportError:
                        logger.debug("[CATALOG-STRIP-RESET] ws_bridge not available, skipping WS resync")
                    except Exception as e:
                        logger.warning("[CATALOG-STRIP-RESET] Failed to trigger WS bridge resync: %s", e)

                # HF-RELAX: Only mark as lagging if contract is expired and no new ticker appeared
                # Don't mark as lagging just because ticker hasn't changed in 2 windows
                # This is normal for single-contract series
                last_change = self._last_catalog_change_ts.get(series_ticker)
                if last_change:
                    time_since_change = (now_utc - last_change).total_seconds()
                    
                    # Only consider lagging if contract is expired (no valid active contract)
                    if not contract_valid and time_since_change > self._catalog_stuck_threshold_sec:
                        logger.debug(
                            "[CATALOG-LAGGING-WARN] series=%s reason=EXPIRED_CONTRACT_NO_ROLL "
                            "expected_window=%s current_ticker=%s time_since_change=%.1fs (NOT blocking - scheduler allows trading if MD is fresh)",
                            series_ticker,
                            current_window_start.isoformat(),
                            best_ticker,
                            time_since_change
                        )
                        # Mark series as lagging only if contract expired
                        self._series_health[series_ticker] = "lagging"
                    else:
                        # Contract is still valid or within threshold - mark as healthy
                        # Even if ticker hasn't changed, the contract is still tradeable
                        self._series_health[series_ticker] = "healthy"
                        if time_since_change > 60:  # Log info if ticker hasn't changed in 1 minute
                            logger.info(
                                "[CATALOG-SINGLE-CONTRACT] series=%s ticker unchanged for %.1fs (normal for single-contract series)",
                                series_ticker,
                                time_since_change
                            )
                else:
                    # First time seeing this series with active ticker - mark as healthy
                    self._last_catalog_change_ts[series_ticker] = now_utc
                    self._last_catalog_ticker[series_ticker] = best_ticker
                    self._series_health[series_ticker] = "healthy"
            else:
                logger.warning(
                    "[CATALOG-SNAPSHOT] series=%s has no active tickers (catalog may be empty)",
                    series_ticker
                )
                # Mark series as having no active tickers
                self._series_health[series_ticker] = "no_active_tickers"

    def _check_catalog_lagging(self, now_utc: datetime) -> None:
        """Check if catalog has advanced to expected window for each series."""
        from config.kalshi_universe import kalshi_agent_grid_catalog_series_tickers

        series_tickers = kalshi_agent_grid_catalog_series_tickers()

        for series_ticker in series_tickers:
            series_markets = [m for m in self._markets if m.series_ticker == series_ticker]
            
            # SIMPLE 15m FILTER: Include all markets that are NOT settled
            active_tickers = []
            for m in series_markets:
                # Status is in raw_data for EventMarket objects
                raw_data = m.market.raw_data or {}
                market_status = raw_data.get("status", "").lower()
                is_settled = market_status == "settled"
                
                if not is_settled:
                    active_tickers.append(m.market.market_id)

            if not active_tickers:
                logger.warning(
                    "[CATALOG-LAGGING] series=%s reason=NO_ACTIVE_TICKERS expected_window=%s",
                    series_ticker,
                    now_utc.isoformat()
                )
                continue

            # Check if all tickers are future windows (should not happen with active_only=True)
            minute = now_utc.minute
            window_minute = (minute // 15) * 15
            current_window_start = now_utc.replace(minute=window_minute, second=0, microsecond=0)

            all_future = True
            has_valid_close_time = False
            for ticker in active_tickers:
                # Extract expiry time from ticker if possible
                if hasattr(self._by_ticker.get(ticker), 'market'):
                    market = self._by_ticker[ticker].market
                    if hasattr(market, 'end_date') and market.end_date:
                        has_valid_close_time = True
                        # Check if end_date is in the next window or beyond
                        if market.end_date > current_window_start + timedelta(minutes=15):
                            continue  # Future window
                        else:
                            all_future = False
                            break

            # Only warn if we have valid close_time data AND all are future
            if all_future and has_valid_close_time and active_tickers:
                logger.warning(
                    "[CATALOG-LAGGING] series=%s reason=ONLY_FUTURE_WINDOWS "
                    "expected_window=%s active_tickers=%s",
                    series_ticker,
                    current_window_start.isoformat(),
                    active_tickers[:3]
                )

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
            # CRITICAL FIX: Use nested market.market_id for key since mkt may be CatalogMarket
            if hasattr(cm, "market") and hasattr(cm.market, "market_id"):
                ticker_idx[cm.market.market_id] = cm
            elif hasattr(mkt, "market_id"):
                ticker_idx[mkt.market_id] = cm
            else:
                logger.warning(
                    "[BUILD-INDEXES] Cannot index market - no market_id found: type=%s",
                    type(mkt).__name__
                )

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
            # CRITICAL FIX: market_id is on nested EventMarket
            if hasattr(cm, "market") and hasattr(cm.market, "market_id"):
                tid = cm.market.market_id
            elif hasattr(cm, "market_id"):
                tid = cm.market_id
            else:
                continue
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
            # CRITICAL FIX: market_id is on nested EventMarket
            if hasattr(cm, "market") and hasattr(cm.market, "market_id"):
                tid = cm.market.market_id
            elif hasattr(cm, "market_id"):
                tid = cm.market_id
            else:
                continue
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
        # CRITICAL FIX: Check if mkt is already a CatalogMarket (from previous enrichment)
        # If so, extract the nested EventMarket
        if hasattr(mkt, "market") and isinstance(mkt.market, EventMarket):
            # Already a CatalogMarket, extract the nested EventMarket
            mkt = mkt.market
        elif not isinstance(mkt, EventMarket):
            logger.warning(
                "[ENRICH] Unexpected market type: %s, skipping enrichment",
                type(mkt).__name__
            )
            # Return as-is if it's already a CatalogMarket
            if hasattr(mkt, "market"):
                return mkt
            raise TypeError(f"Expected EventMarket, got {type(mkt).__name__}")

        # Extract event_ticker / series_ticker from raw_data
        raw = mkt.raw_data or {}
        event_ticker = raw.get("event_ticker", "") or ""
        series_ticker = raw.get("series_ticker", "") or ""
        
        # CRITICAL FIX: Override series_ticker from market_id if API returns incorrect value
        # Kalshi API returns KXBTC instead of KXBTC15M for series_ticker field
        # Extract full series ticker: KXBTC15M, KXBTCH1, KXBTCD1, KXBTCW1, etc.
        import re
        series_match = re.match(r"^(KX[A-Z]+15M|KX[A-Z]+H1|KX[A-Z]+D1|KX[A-Z]+W1|KX[A-Z]+1M|KX[A-Z]+Y|KX[A-Z]+)", mkt.market_id.upper())
        if series_match:
            extracted_series = series_match.group(1)
            if series_ticker != extracted_series:
                series_ticker = extracted_series
                # CRITICAL: Update raw_data so downstream code reads the correct value
                if mkt.raw_data is None:
                    mkt.raw_data = {}
                mkt.raw_data["series_ticker"] = extracted_series
                logger.debug(
                    "[SERIES-TICKER-OVERRIDE] market_id=%s api_series=%s extracted_series=%s (updated raw_data)",
                    mkt.market_id, raw.get("series_ticker", ""), extracted_series
                )

        # 1. Primary detection: ticker prefix → category + asset
        # CRITICAL FIX: Use series_ticker if available (canonical for 15m contracts like KXBTC15M)
        # Fall back to event_ticker, then market_id if series_ticker is empty
        ticker_for_detection = series_ticker or event_ticker or mkt.market_id
        ticker_category, ticker_asset = self._detect_from_ticker(ticker_for_detection)

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

        # STAGE 1 FIX: Use authoritative normalization function for 15m crypto contracts
        # This enforces symmetric treatment across BTC/ETH/SOL/XRP/DOGE
        # The normalization function is the SINGLE SOURCE OF TRUTH for expiry metadata
        minutes_to_expiry = 0.0
        health_status = "invalid_metadata"
        api_status = "unknown"
        
        # Extract API status from raw market data
        # Kalshi API returns status field with values: open, closed, settled
        raw_data = mkt.raw_data or {}
        api_status = raw_data.get("status", "unknown").lower()
        
        # CRITICAL: Extract close_ts from raw_data if available (Kalshi's ground truth)
        close_ts = raw_data.get("close_ts") or raw_data.get("close_time_ts")
        close_time_utc = None
        if close_ts:
            try:
                close_time_utc = datetime.fromtimestamp(float(close_ts), tz=timezone.utc)
                # SANITY CHECK: Log now_utc vs close_time_utc to detect clock skew
                time_diff = (close_time_utc - now).total_seconds()
                if abs(time_diff) > 3600:  # More than 1 hour difference is suspicious
                    logger.warning(
                        "[CLOCK-SKEW-DETECTED] ticker=%s close_ts=%s close_time_utc=%s now_utc=%s diff_seconds=%.1f",
                        mkt.market_id, close_ts, close_time_utc.isoformat(), now.isoformat(), time_diff
                    )
            except (ValueError, TypeError):
                pass
        
        # DEBUG: Log raw_data keys for 15m crypto markets to understand status field
        if timeframe == "15m" and asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            logger.debug("[RAW-DATA-DEBUG] market_id=%s raw_data_keys=%s api_status=%s close_ts=%s close_time_utc=%s", mkt.market_id, list(raw_data.keys())[:20], api_status, close_ts, close_time_utc)
        
        if timeframe == "15m" and asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            # CRITICAL REFACTOR: Use Kalshi's close_ts as primary source of truth
            # Priority: close_ts (from API) > expected_expiration_time > expiration_time > end_date > close_time > ticker inference
            # This ensures we use Kalshi's ground truth epoch timestamp when available
            normalized = normalize_kalshi_contract(
                ticker=mkt.market_id,
                expiration_time=None,  # Not available in EventMarket
                expected_expiration_time=None,  # Not available in EventMarket
                end_date=close_time_utc or mkt.end_date,  # Prefer close_ts-derived time
                close_time=close_time_utc or getattr(mkt, 'close_time', None),  # Prefer close_ts-derived time
                now=now
            )
            
            # Use normalized values (canonical fields)
            minutes_to_expiry = normalized.minutes_to_expiry
            health_status = normalized.status
            
            # Update end_date to normalized expiry_ts if normalization succeeded
            # This ensures all downstream consumers see the canonical expiry timestamp
            if normalized.status == "ok" and normalized.expiry_ts:
                if mkt.end_date != normalized.expiry_ts:
                    mkt.end_date = normalized.expiry_ts
                    logger.debug(
                        "[CATALOG-NORMALIZE] ticker=%s asset=%s updated end_date to normalized expiry_ts (source: %s)",
                        mkt.market_id, asset, normalized.status_reason
                    )
            elif normalized.status == "invalid_metadata":
                logger.warning(
                    "[CATALOG-NORMALIZE] ticker=%s asset=%s has invalid metadata: %s → treating as expired",
                    mkt.market_id, asset, normalized.status_reason
                )
            
            # Log normalization result for debugging
            logger.info(
                "[CATALOG-NORMALIZE] ticker=%s asset=%s api_status=%s health_status=%s seconds_to_expiry=%.1f minutes_to_expiry=%.1f reason=%s close_ts_used=%s",
                mkt.market_id, asset, api_status, normalized.status, normalized.seconds_to_expiry, normalized.minutes_to_expiry, normalized.status_reason, str(close_ts is not None)
            )
        else:
            # Non-15m or non-crypto: use original logic (legacy path)
            # TODO: Eventually migrate these to use normalization function as well
            if mkt.end_date and mkt.end_date > now:
                minutes_to_expiry = (mkt.end_date - now).total_seconds() / 60.0
                health_status = "ok"
            elif mkt.end_date is None or mkt.end_date <= now:
                logger.warning(
                    "[CATALOG-ENRICH-WARN] ticker=%s asset=%s timeframe=%s end_date=%s → treating as expired (minutes_to_expiry=0.0)",
                    mkt.market_id, asset, timeframe, mkt.end_date
                )
                health_status = "expired"
        
        # Compute tradeable flag = DATA availability for the current ~15-minute window.
        # DECOUPLED (2026-06): previously this used is_tradeable() (the 2-12 min ENTRY
        # window), which starved WS subscription / catalog visibility during minutes
        # 12-15 and 0-2 of every cycle and tripped HALT_CRITICAL. Entry timing is
        # enforced authoritatively downstream by agent_grid_15m.check_autonomous_gate
        # (profile guardrails min/max_entry_mins) + MIN_TIME_TO_EXPIRY_FOR_ENTRY_MIN.
        from merid.event_venues.kalshi.kalshi_15m_time import is_market_live
        
        # Use the normalized expiry time if available, otherwise use end_date
        expiry_time = None
        if timeframe == "15m" and asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            # CRITICAL FIX: Use normalized expiry_ts regardless of status
            # This ensures expired markets are correctly identified and filtered out
            # Previously we only used normalized expiry for status="ok", which meant
            # expired markets kept their stale end_date and bypassed time filtering
            if normalized.expiry_ts:
                expiry_time = normalized.expiry_ts
            elif mkt.end_date:
                expiry_time = mkt.end_date
        
        # Compute tradeable (= visible/live for data) if we have an expiry time
        if expiry_time:
            tradeable = is_market_live(expiry_time, now, health_status)
        else:
            # No expiry time - not tradeable
            tradeable = False
        
        # DEBUG: Log individual conditions for 15m crypto markets
        if timeframe == "15m" and asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            logger.debug("[ENRICH-TRADEABLE] market_id=%s asset=%s health_status=%s expiry_time=%s mte=%s tradeable=%s", mkt.market_id, asset, health_status, expiry_time, minutes_to_expiry, tradeable)

        # CRITICAL FIX: Use normalized expiry_ts for expires_at regardless of status
        # This ensures expired markets are correctly identified and filtered out
        # Previously expires_at was set to mkt.end_date which could be stale for expired markets
        final_expires_at = None
        if timeframe == "15m" and asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            if normalized.expiry_ts:
                final_expires_at = normalized.expiry_ts
            else:
                final_expires_at = mkt.end_date
        else:
            final_expires_at = mkt.end_date
        
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
            expires_at=final_expires_at,
            minutes_to_expiry=minutes_to_expiry,
            api_status=api_status,
            health_status=health_status,
            tradeable=tradeable,
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
        max_minutes_to_expiry: Optional[float] = None,
    ) -> List[CatalogMarket]:
        """Get active (open) markets with optional filtering by asset and timeframe.

        CRITICAL REFACTOR: Now supports A/B testing between old and new selectors.
        Phase 1: USE_CANONICAL_SELECTOR=false (default) - runs both paths and logs comparison
        Phase 2: USE_CANONICAL_SELECTOR=true - uses new canonical selector only

        For 15m crypto markets, enforces the 5-asset universe:
        - Only allows series tickers: KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M
        - Only allows timeframe == "15m"
        
        Args:
            asset: Optional asset filter (e.g., "BTC")
            timeframe: Optional timeframe filter (e.g., "15m")
            max_minutes_to_expiry: Optional maximum minutes to expiry (e.g., 15.0 for 15-minute window)
        """
        from datetime import datetime, timezone
        from pathlib import Path
        from merid.settings import settings
        
        # CRITICAL: Define the 5-asset 15m crypto universe
        # These are the ONLY series tickers allowed for 15m crypto trading
        ALLOWED_15M_CRYPTO_SERIES = {
            "KXBTC15M",
            "KXETH15M",
            "KXSOL15M",
            "KXXRP15M",
            "KXDOGE15M",
        }
        
        logger.debug("[GET-ACTIVE-MARKETS] ENTRY asset=%s timeframe=%s max_mte=%s", asset, timeframe, max_minutes_to_expiry)
        
        # SIMPLE SELECTOR: Use tradeable flag only - no A/B testing, no complex logic
        markets = [m for m in self._markets if m.tradeable]
        
        # Apply filters
        if timeframe == "15m":
            markets = [m for m in markets if m.series_ticker in ALLOWED_15M_CRYPTO_SERIES]
        if asset:
            markets = [m for m in markets if m.asset == asset]
        # CRITICAL FIX: Don't filter by timeframe field - Kalshi API returns N/A for this field
        # Instead, rely on series ticker filtering (e.g., KXBTC15M) which identifies 15m markets
        # if timeframe:
        #     markets = [m for m in markets if m.timeframe == timeframe]
        if max_minutes_to_expiry is not None:
            markets = [m for m in markets if m.minutes_to_expiry and m.minutes_to_expiry <= max_minutes_to_expiry]
        
        # CRITICAL: Log venue down state when no tradeable 15m markets found for all 5 assets
        if timeframe == "15m" and not markets:
            logger.warning(
                "KALSHI-15M-UNIVERSE No tradeable 15m BTC/ETH/SOL/XRP/DOGE markets within 0-30 min; treating venue as unavailable."
            )
        
        # CRITICAL: Assert max one tradeable 15m market per asset at a time
        # If Kalshi lists overlapping 15m strips, log and choose the nearest-expiry one deterministically
        if timeframe == "15m":
            markets_by_asset = {}
            for m in markets:
                markets_by_asset.setdefault(m.asset, []).append(m)
            
            for asset, asset_markets in markets_by_asset.items():
                if len(asset_markets) > 1:
                    logger.warning(
                        "KALSHI-15M-UNIVERSE Multiple tradeable 15m markets for asset=%s: %d markets. "
                        "Choosing nearest-expiry one deterministically.",
                        asset, len(asset_markets)
                    )
                    # Sort by minutes_to_expiry and keep only the nearest-expiry
                    asset_markets.sort(key=lambda m: m.minutes_to_expiry if m.minutes_to_expiry else float('inf'))
                    # Remove all but the first (nearest-expiry)
                    for m in asset_markets[1:]:
                        markets.remove(m)
                    logger.debug(
                        "[KALSHI-15M-UNIVERSE] Deduplicated asset=%s to nearest-expiry market: %s",
                        asset, asset_markets[0].market.market_id,
                    )
        
        # DEBUG: Log sample markets if result is empty
        if not markets and timeframe:
            sample = [m for m in self._markets if hasattr(m, 'timeframe') and m.timeframe][:5]
            logger.debug(
                "[GET-ACTIVE-MARKETS] No markets found for timeframe=%s. Sample: %s",
                timeframe,
                [f"{m.market.market_id}:tf={m.timeframe}:asset={m.asset}:mte={m.minutes_to_expiry}" for m in sample],
            )
        
        logger.debug("[GET-ACTIVE-MARKETS] RETURN: %d markets", len(markets))
        
        return markets

    def get_active_15m_market(self, asset: str) -> Optional[CatalogMarket]:
        """Get the single current active 15m market for a given asset.

        This is the canonical helper for 15m crypto trading. It enforces the invariant:
        - Exactly one active 15m market per asset (BTC, ETH, SOL, XRP, DOGE)
        - Market must be in the current ET 15m window
        - Market must be tradeable (api_status in {open, closed}, health ok, 0 < minutes_to_expiry <= 15)

        If no market is found or multiple markets are found, this logs a warning and returns None.
        The caller should treat this as "asset unavailable" and not attempt fallback to other markets.

        Args:
            asset: Asset name (e.g., "BTC", "ETH", "SOL", "XRP", "DOGE")

        Returns:
            Single CatalogMarket for the current 15m window, or None if not found
        """
        from datetime import datetime, timezone
        from pathlib import Path

        # Get current ET 15m window
        from merid.event_venues.kalshi.kalshi_15m_time import get_kalshi_15m_window
        window = get_kalshi_15m_window()

        # Get all tradeable 15m markets for this asset
        markets = self.get_active_markets(asset=asset, timeframe="15m", max_minutes_to_expiry=15.0)

        # Filter to markets in the current ET window
        current_window_markets = []
        for m in markets:
            # CatalogMarket has expires_at field, not market.close_time
            if m.expires_at and m.expires_at.tzinfo is None:
                close_time = m.expires_at.replace(tzinfo=timezone.utc)
            else:
                close_time = m.expires_at

            # Check if close_time matches the current ET window end time (within 1 second tolerance)
            # This ensures we select only the market that expires at the end of the current 15m window
            if close_time and abs((close_time - window.end_utc).total_seconds()) <= 1.0:
                current_window_markets.append(m)

        # Log diagnostic
        logger.debug(
            "CATALOG-15M-SINGLE-MARKET asset=%s total_tradeable=%d in_current_window=%d window_start=%s window_end=%s",
            asset, len(markets), len(current_window_markets), window.start_utc, window.end_utc
        )
        if current_window_markets:
            for m in current_window_markets:
                logger.debug(
                    "  - market_id=%s end_date=%s mte=%s",
                    m.market.market_id, m.market.end_date, m.minutes_to_expiry
                )

        # Invariant check: exactly one market in current window
        if len(current_window_markets) == 0:
            logger.warning(
                "CATALOG-15M-INVARIANT-ERROR asset=%s: No markets in current ET window. "
                "Treating asset as unavailable.",
                asset
            )
            logger.debug("CATALOG-15M-INVARIANT-ERROR asset=%s reason=no_markets_in_window total_tradeable=%d", asset, len(markets))
            return None

        if len(current_window_markets) > 1:
            logger.critical(
                "CATALOG-15M-INVARIANT-ERROR asset=%s: %d markets in current ET window. "
                "Expected exactly 1. Treating asset as unavailable.",
                asset, len(current_window_markets)
            )
            logger.debug("CATALOG-15M-INVARIANT-ERROR asset=%s reason=multiple_markets_in_window count=%d", asset, len(current_window_markets))
            return None

        # Exactly one market found - return it
        chosen = current_window_markets[0]
        logger.info(
            "CATALOG-15M-SINGLE-MARKET asset=%s chosen=%s mte=%.1f",
            asset, chosen.market.market_id, chosen.minutes_to_expiry
        )
        return chosen

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
    
    def get_series_health(self, series_ticker: str) -> str:
        """Get health status for a series ticker.
        
        This API enforces Invariant 5: Catalog Health Is Binding.
        Returns the health status which controls scheduler behavior.
        
        Args:
            series_ticker: Series ticker (e.g., "KXBTC15M")
            
        Returns:
            Health status: "healthy", "lagging", "no_active_tickers", "unknown"
        """
        return self._series_health.get(series_ticker, "unknown")

    def get_market_by_id(self, market_id: str) -> Optional[CatalogMarket]:
        """Get a market by its market ID.
        
        Args:
            market_id: Market ID (e.g., "KXBTC15M-26MAY261730-30")
            
        Returns:
            CatalogMarket if found, None otherwise
        """
        for market in self._markets:
            if market.market.market_id == market_id:
                return market
        return None

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
        from merid.event_venues.kalshi.kalshi_rest_client import get_kalshi_rest_client
        client = await get_kalshi_rest_client()
        kalshi_client = await client._ensure_client()
        
        # Query Kalshi API for this series
        # NOTE: No max_expiration_time filter - rely on snapshot() 0-30min expiry filtering instead
        result = await kalshi_client._request_with_resilience(
            "GET",
            f"/markets?series_ticker={series_ticker}&limit=200",
            operation_name=f"get_markets_for_series({series_ticker})"
        )
        
        if not result.success or not result.data:
            logger.warning(
                "[CATALOG-SERIES-QUERY] Failed to fetch markets for series=%s: %s",
                series_ticker, result.error
            )
            return []
        
        # Handle REST API response format: {'markets': [...]}
        raw_markets_list = result.data if isinstance(result.data, list) else result.data.get('markets', []) if isinstance(result.data, dict) else []
        
        # Convert raw dicts to EventMarket objects for enrichment
        enriched = []
        for raw_m in raw_markets_list:
            try:
                # Parse raw dict to KalshiMarket, then convert to EventMarket
                kalshi_market = kalshi_client._parse_market(raw_m)
                if kalshi_market:
                    event_market = kalshi_client._to_event_market(kalshi_market)
                    if event_market:
                        catalog_market = self._enrich(event_market, datetime.now(timezone.utc))
                        enriched.append(catalog_market)
            except Exception as e:
                logger.warning(
                    "[CATALOG-SERIES-QUERY] Failed to enrich market %s: %s",
                    raw_m.get("market_id", "unknown") if isinstance(raw_m, dict) else "unknown", e
                )
        
        logger.info(
            "[CATALOG-SERIES-QUERY] Fetched %d markets for series=%s",
            len(enriched), series_ticker
        )
        return enriched

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
        with self._refresh_lock:
            last_refresh = self._last_refresh
        return {
            "market_count": len(self._markets),
            "last_refresh": last_refresh.isoformat() if last_refresh else None,
            "refresh_count": self._refresh_count,
            "categories": {k: len(v) for k, v in self._by_category.items()},
            "assets": {k: len(v) for k, v in self._by_asset.items()},
            "timeframes": {k: len(v) for k, v in self._by_timeframe.items()},
            "running": self._task is not None and not self._task.done(),
        }

    def snapshot(self) -> CatalogSnapshot:
        """
        Return a point-in-time snapshot of active, non-expired markets.
        
        SIMPLIFIED: Filter by non-settled 15m crypto markets within 0-30 minutes to expiry.
        """
        from merid.event_venues.kalshi.kalshi_15m_time import compute_minutes_to_expiry
        
        active_markets = []
        allowed_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
        
        # Entry window: -2 to 30 minutes to expiry
        # Allow negative MTE to include markets that just opened (next window)
        MIN_MINUTES_TO_EXPIRY = -2.0
        MAX_MINUTES_TO_EXPIRY = 30.0
        
        now = datetime.now(timezone.utc)
        
        logger.info("[SNAPSHOT-CREATE] Starting snapshot creation, total_catalog_markets=%d catalog_id=%s", len(self._markets), id(self))
        
        for m in self._markets:
            # Filter: non-settled 15m crypto markets within entry window
            raw_data = m.market.raw_data or {}
            market_status = raw_data.get("status", "").lower()
            is_settled = market_status == "settled"
            
            # DIAGNOSTIC: Log timeframe value for debugging
            logger.info("[SNAPSHOT-FILTER-DEBUG] ticker=%s asset=%s timeframe=%s status=%s", 
                        m.market.market_id, m.asset, m.timeframe, market_status)
            
            # CRITICAL FIX: Don't filter by timeframe field - Kalshi API returns N/A for this field
            # Instead, rely on series ticker filtering (e.g., KXBTC15M) which identifies 15m markets
            # The series ticker is already validated in the enrichment phase
            if (not is_settled and 
                m.asset in allowed_assets and
                m.expires_at):
                
                mte = compute_minutes_to_expiry(m.expires_at, now)
                
                logger.debug("[SNAPSHOT-FILTER] ticker=%s asset=%s mte=%.2f status=%s", 
                            m.market.market_id, m.asset, mte, market_status)
                
                # Filter by entry window (0-30 minutes to expiry)
                if MIN_MINUTES_TO_EXPIRY <= mte <= MAX_MINUTES_TO_EXPIRY:
                    active_markets.append(m)
        
        # Build nested by_asset_timeframe counts from filtered markets
        by_asset_tf: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for m in active_markets:
            if m.asset and m.timeframe:
                by_asset_tf[m.asset][m.timeframe] += 1
        # Convert to regular dict for serialization
        by_asset_tf_serializable = {k: dict(v) for k, v in by_asset_tf.items()}

        # DIAGNOSTIC: Log snapshot tickers to debug stale data issue
        tickers_in_snapshot = [m.market.market_id for m in active_markets] if active_markets else []
        now = datetime.now(timezone.utc)
        # Thread-safe read of _last_refresh (refresh runs in separate thread)
        with self._refresh_lock:
            last_refresh = self._last_refresh
        time_since_refresh = (now - last_refresh).total_seconds() if last_refresh else -1
        
        # Warn if catalog has never been refreshed (empty catalog)
        if last_refresh is None:
            logger.warning(
                "[CATALOG-SNAPSHOT] Catalog has never been refreshed - returning empty snapshot. "
                "This may indicate the refresh thread has not started or has failed to complete initial fetch."
            )
        
        # Log if we filtered out expired markets
        total_markets = len(self._markets)
        filtered_count = total_markets - len(active_markets)
        if filtered_count > 0:
            logger.warning(
                "[CATALOG-SNAPSHOT] Filtered out %d expired/inactive markets (total=%d, active=%d)",
                filtered_count, total_markets, len(active_markets)
            )
        
        logger.info(
            "[CATALOG-SNAPSHOT] Returning %d active tickers: %s (last_refresh=%s, time_since=%.1fs)",
            len(tickers_in_snapshot),
            sorted(tickers_in_snapshot),
            last_refresh.isoformat() if last_refresh else None,
            time_since_refresh
        )

        return CatalogSnapshot(
            markets=active_markets,
            refreshed_at=last_refresh,
            market_count=len(active_markets),
            by_category={k: len(v) for k, v in self._by_category.items()},
            by_asset={k: len(v) for k, v in self._by_asset.items()},
            by_timeframe={k: len(v) for k, v in self._by_timeframe.items()},
            by_asset_timeframe=by_asset_tf_serializable,
        )

    def get_current_15m_market(self, asset: str) -> Optional[CatalogMarket]:
        """
        Get the current 15m market for a given asset.

        CRITICAL REFACTOR: Now uses canonical select_live_markets_by_ts() function
        to ensure consistent market selection with get_active_markets().

        Selection criteria (via canonical selector):
        - Uses open_time and close_time from Kalshi API (authoritative)
        - Market is "live" if: open_time <= now_utc < close_time
        - Market is "tradeable" if: 2 <= minutes_to_expiry <= 12 (entry window)
        - Returns the market with smallest minutes_to_expiry if multiple exist

        Args:
            asset: Asset name (BTC, ETH, SOL, XRP, DOGE)

        Returns:
            CatalogMarket if found in current window, None otherwise
        """
        # CRITICAL FIX: Validate asset is in allowed list
        if asset not in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            logger.warning("[GET-CURRENT-15M] Invalid asset=%s - returning None", asset)
            return None
        
        from merid.event_venues.kalshi.kalshi_15m_time import select_live_markets_by_ts

        # Filter to 15m markets for this asset that are NOT settled
        # CRITICAL FIX: Don't filter by timeframe field - Kalshi API returns N/A for this field
        # Instead, rely on series ticker filtering (e.g., KXBTC15M) which identifies 15m markets
        # The series ticker is already validated in the enrichment phase
        asset_markets = []
        for m in self._markets:
            if m.asset == asset:
                # Status is in raw_data for EventMarket objects
                raw_data = m.market.raw_data or {}
                market_status = raw_data.get("status", "").lower()
                is_settled = market_status == "settled"
                if not is_settled:
                    asset_markets.append(m)

        if not asset_markets:
            logger.debug("[GET-CURRENT-15M] No 15m markets for asset=%s", asset)
            return None

        # Use canonical selector to find live markets
        # 2026 FIX: Read min_entry_mins from profile instead of hardcoding 12.0
        # Profile has min_entry_mins: 2.0 and max_entry_mins: 15.0
        # Previous hardcoded value of 12.0 was filtering out all markets
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            profile_adapter = get_active_profile()
            if profile_adapter and hasattr(profile_adapter.profile, 'guardrails_min_entry_mins'):
                min_entry_mins = profile_adapter.profile.guardrails_min_entry_mins
            else:
                min_entry_mins = 2.0  # Fallback to profile default
        except Exception as e:
            logger.warning("[GET-CURRENT-15M] Failed to load min_entry_mins from profile: %s, using fallback 2.0", e)
            min_entry_mins = 2.0  # Fallback to profile default
        
        max_entry_mins = 15.0  # Profile max_entry_mins
        
        logger.info("[GET-CURRENT-15M] Filtering %d markets for asset=%s with min_minutes_to_expiry=%.1f", len(asset_markets), asset, min_entry_mins)
        live_markets = select_live_markets_by_ts(
            asset_markets,
            min_minutes_to_expiry=min_entry_mins,
            max_minutes_to_expiry=max_entry_mins,
            require_exactly_one_per_asset=False
        )
        logger.info("[GET-CURRENT-15M] Filter returned %d live markets for asset=%s", len(live_markets) if live_markets else 0, asset)

        if not live_markets:
            logger.debug("[GET-CURRENT-15M] No live markets for asset=%s", asset)
            return None

        # Safety check: log if multiple live markets
        if len(live_markets) > 1:
            market_ids = [getattr(m.market, 'market_id', 'unknown') for m in live_markets]
            logger.warning(
                "[GET-CURRENT-15M] Multiple live markets for asset=%s: %s. Selecting nearest expiry.",
                asset, market_ids
            )

        # Return market with smallest minutes_to_expiry
        live_markets.sort(key=lambda m: m.minutes_to_expiry if hasattr(m, 'minutes_to_expiry') else float('inf'))
        return live_markets[0]


async def validate_catalog_against_kalshi_api(
    catalog: "KalshiMarketCatalog",
    assets: List[str] = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
) -> dict:
    """
    Validate catalog's view of 15m crypto markets against Kalshi's Get Markets API.
    
    This ensures catalog discovery is aligned with Kalshi's ground truth for
    15-minute crypto markets. For each asset, compares:
    - Number of markets with status=open
    - Market IDs match between catalog and API
    - Status field matches (open/closed)
    
    Args:
        catalog: KalshiMarketCatalog instance
        assets: List of assets to validate (default: all 5 crypto assets)
        
    Returns:
        Dict with validation results per asset
    """
    from config.kalshi_15m_crypto_config import KALSHI_15M_SERIES_TICKERS
    
    results = {}
    
    for asset in assets:
        series_ticker = KALSHI_15M_SERIES_TICKERS.get(asset)
        if not series_ticker:
            results[asset] = {"status": "error", "reason": f"No series ticker for {asset}"}
            continue
        
        try:
            # Get catalog view
            catalog_markets = catalog.get_markets_by_asset(asset, timeframe="15m")
            catalog_open = [m for m in catalog_markets if hasattr(m.market, 'active') and m.market.active]
            catalog_ids = set(m.market.market_id for m in catalog_markets)
            catalog_open_ids = set(m.market.market_id for m in catalog_open)
            
            # Get Kalshi API view
            api_markets = await catalog.get_markets_for_series(series_ticker)
            api_open = [m for m in api_markets if hasattr(m.market, 'active') and m.market.active]
            api_ids = set(m.market.market_id for m in api_markets)
            api_open_ids = set(m.market.market_id for m in api_open)
            
            # Compare
            results[asset] = {
                "status": "ok",
                "series_ticker": series_ticker,
                "catalog": {
                    "total": len(catalog_markets),
                    "open": len(catalog_open),
                    "ids": sorted(list(catalog_ids))[:5]  # Sample first 5
                },
                "api": {
                    "total": len(api_markets),
                    "open": len(api_open),
                    "ids": sorted(list(api_ids))[:5]  # Sample first 5
                },
                "mismatch": {
                    "total_count": len(catalog_markets) != len(api_markets),
                    "open_count": len(catalog_open) != len(api_open),
                    "missing_in_catalog": sorted(list(api_ids - catalog_ids))[:5],
                    "extra_in_catalog": sorted(list(catalog_ids - api_ids))[:5],
                }
            }
            
            if results[asset]["mismatch"]["total_count"] or results[asset]["mismatch"]["open_count"]:
                logger.error(
                    "[CATALOG-VALIDATION] asset=%s MISMATCH - catalog_total=%d api_total=%d catalog_open=%d api_open=%d",
                    asset,
                    len(catalog_markets),
                    len(api_markets),
                    len(catalog_open),
                    len(api_open)
                )
            else:
                logger.info(
                    "[CATALOG-VALIDATION] asset=%s OK - catalog_total=%d api_total=%d catalog_open=%d api_open=%d",
                    asset,
                    len(catalog_markets),
                    len(api_markets),
                    len(catalog_open),
                    len(api_open)
                )
                
        except Exception as e:
            logger.error(
                "[CATALOG-VALIDATION] asset=%s ERROR: %s",
                asset, e, exc_info=True
            )
            results[asset] = {"status": "error", "reason": str(e)}
    
    return results


# ── Singleton ────────────────────────────────────────────────────────────

_catalog: Optional[KalshiMarketCatalog] = None
_catalog_lock = threading.Lock()


def get_market_catalog() -> Optional[KalshiMarketCatalog]:
    """Get the singleton KalshiMarketCatalog.
    
    Returns None if the catalog has not been initialized through the proper startup path.
    This prevents premature catalog creation that bypasses the FastAPI lifespan startup.
    The catalog must be created in the startup function and set via set_market_catalog().
    """
    global _catalog
    if _catalog is None:
        with _catalog_lock:
            if _catalog is None:
                # CRITICAL FIX: Do NOT create catalog automatically
                # This prevents bypassing the FastAPI lifespan startup
                logger.warning("[CATALOG-SINGLETON] Catalog not initialized - called before startup")
                logger.warning("[CATALOG-SINGLETON] Catalog must be created in startup and set via set_market_catalog()")
                return None
            else:
                logger.info("[CATALOG-SINGLETON] Returning existing catalog instance id=%s (double-checked)", id(_catalog))
    else:
        logger.debug("[CATALOG-SINGLETON] Returning existing catalog instance id=%s", id(_catalog))
    return _catalog


def set_market_catalog(catalog: KalshiMarketCatalog) -> None:
    """Set the singleton KalshiMarketCatalog instance.
    
    This is used during startup to ensure all components (WS bridge, main loop, etc.)
    use the same catalog instance.
    """
    global _catalog
    with _catalog_lock:
        logger.info("[CATALOG-SINGLETON] Setting singleton catalog id=%s (previous id=%s)", id(catalog), id(_catalog) if _catalog else None)
        _catalog = catalog


def reset_market_catalog() -> None:
    """Reset the global singleton instance (for clean startup)."""
    global _catalog
    with _catalog_lock:
        _catalog = None


# Module-level convenience wrapper for tests and external callers
def _detect_from_ticker(ticker: str) -> tuple:
    """Detect category and asset from Kalshi event_ticker prefix.

    Module-level wrapper around KalshiMarketCatalog._detect_from_ticker.
    Returns (category, asset) — either may be None.
    """
    return KalshiMarketCatalog._detect_from_ticker(ticker)
