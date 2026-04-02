"""Process-safe catalog index builder for bypassing GIL contention.

This module contains pure-Python index-building logic that can be offloaded
to a ProcessPoolExecutor to avoid blocking the main event loop during
CPU-intensive regex matching, datetime parsing, and dictionary construction
over large market lists.

Design:
- Takes serializable inputs (list of raw market dicts)
- Returns serializable outputs (dict of indexes)
- No asyncio, no complex objects - just data transformation
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple


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


def detect_from_ticker(ticker: str) -> Tuple[Optional[str], Optional[str]]:
    """Detect category and asset from Kalshi event_ticker prefix.

    Returns (category, asset) — either may be None.
    """
    for pat, category, asset in _TICKER_CATEGORY_MAP:
        if pat.search(ticker):
            return category, asset
    return None, None


def detect_asset(text: str) -> Optional[str]:
    """Detect asset from combined text using pattern matching."""
    for asset, patterns in _ASSET_PATTERNS.items():
        for pat in patterns:
            if pat.search(text):
                return asset
    return None


def detect_timeframe(text: str, end_date_iso: Optional[str], now_iso: str) -> Optional[str]:
    """Detect timeframe from text or time-to-expiry."""
    # First try text patterns
    for pat, tf in _TIMEFRAME_PATTERNS:
        if pat.search(text):
            return tf

    # Infer from time to expiry
    if end_date_iso:
        try:
            end_date = datetime.fromisoformat(end_date_iso.replace('Z', '+00:00'))
            now = datetime.fromisoformat(now_iso.replace('Z', '+00:00'))
            if end_date > now:
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
        except (ValueError, TypeError):
            pass
    return None


def build_indexes(raw_markets: List[Dict[str, Any]], now_iso: str) -> Dict[str, Any]:
    """Build category, asset, and timeframe indexes from raw market data.

    This function is CPU-intensive (regex, parsing, dict operations) and is
    designed to run in a ProcessPoolExecutor to bypass GIL contention.

    Args:
        raw_markets: List of raw market dicts from Kalshi API
        now_iso: Current time as ISO string

    Returns:
        Dict with keys:
        - enriched_markets: List of enriched market dicts with tags
        - by_category: Dict[str, List[str]] mapping category -> ticker list
        - by_asset: Dict[str, List[str]] mapping asset -> ticker list
        - by_timeframe: Dict[str, List[str]] mapping timeframe -> ticker list
        - categories_found: Set of detected categories
        - assets_found: Set of detected assets
    """
    enriched_markets: List[Dict[str, Any]] = []
    by_category: Dict[str, List[str]] = defaultdict(list)
    by_asset: Dict[str, List[str]] = defaultdict(list)
    by_timeframe: Dict[str, List[str]] = defaultdict(list)
    categories_found: Set[str] = set()
    assets_found: Set[str] = set()

    for raw in raw_markets:
        ticker = raw.get("market_id", "")
        event_ticker = raw.get("event_ticker", "") or ""
        series_ticker = raw.get("series_ticker", "") or ""
        question = raw.get("question", "") or ""
        description = raw.get("description", "") or ""
        category_field = raw.get("category", "") or ""
        end_date_iso = raw.get("end_date")

        # Primary detection from ticker
        ticker_category, ticker_asset = detect_from_ticker(event_ticker or ticker)

        # Secondary detection from text
        text = f"{ticker} {event_ticker} {question} {description} {category_field}"
        text_asset = detect_asset(text)
        timeframe = detect_timeframe(text, end_date_iso, now_iso)

        # Merge: ticker-prefix wins for category; first non-None wins for asset
        category = category_field or ticker_category
        asset = ticker_asset or text_asset

        # Build enriched record
        enriched = {
            "ticker": ticker,
            "category": category,
            "asset": asset,
            "timeframe": timeframe,
            "event_ticker": event_ticker or None,
            "series_ticker": series_ticker or None,
        }
        enriched_markets.append(enriched)

        # Build indexes
        if category:
            by_category[category].append(ticker)
            categories_found.add(category)
        if asset:
            by_asset[asset].append(ticker)
            assets_found.add(asset)
        if timeframe:
            by_timeframe[timeframe].append(ticker)

    return {
        "enriched_markets": enriched_markets,
        "by_category": dict(by_category),
        "by_asset": dict(by_asset),
        "by_timeframe": dict(by_timeframe),
        "categories_found": list(categories_found),
        "assets_found": list(assets_found),
    }
