"""Kalshi ticker utilities for validation and normalization.

This module provides functions to validate, normalize, and cache Kalshi market tickers
to ensure they match Kalshi's canonical format and prevent 404 errors from invalid tickers.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Set, Tuple
from dataclasses import dataclass

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.ticker_utils")

# Kalshi ticker regex pattern for 15m crypto markets
# Format: KX{ASSET}15M-{YY}{MMM}{DD}{HHMM}  (YYMONDD, time in America/New_York)
# Example: KXBTC15M-26AUG031530 -> year 2026, AUG, day 03, 15:30 ET
# CRITICAL FIX (2026-08-03): groups were previously mislabeled DDMMMYYHHMM,
# swapping day/year. API-confirmed via close_ts (see expiry_fallback.py).
KALSHI_15M_TICKER_PATTERN = re.compile(
    r'^KX([A-Z]+)15M-(\d{2})([A-Z]{3})(\d{2})(\d{4})$'
)

# Valid 15-minute window minutes
VALID_15M_MINUTES = {0, 15, 30, 45}

# Asset mapping for validation
VALID_CRYPTO_ASSETS = {
    'BTC', 'ETH', 'SOL', 'XRP', 'DOGE'
}


@dataclass(frozen=True)
class ParsedKalshiTicker:
    """Parsed components of a Kalshi 15m ticker."""
    asset: str
    day: int
    month: str
    year: int
    hour: int
    minute: int
    is_valid: bool
    error_message: Optional[str] = None


class KalshiTickerCache:
    """Cache for valid Kalshi market tickers fetched from the API."""
    
    def __init__(self):
        self._cache: Dict[str, Dict[str, str]] = {}  # asset -> {ticker: market_id}
        self._last_update: Optional[datetime] = None
        self._cache_ttl_minutes = 5
    
    def is_valid(self, ticker: str) -> bool:
        """Check if a ticker exists in the cached valid markets."""
        for asset_tickers in self._cache.values():
            if ticker in asset_tickers:
                return True
        return False
    
    def get_market_id(self, ticker: str) -> Optional[str]:
        """Get the market_id for a cached ticker."""
        for asset_tickers in self._cache.values():
            if ticker in asset_tickers:
                return asset_tickers[ticker]
        return None
    
    def update_cache(self, markets: List[Dict]) -> None:
        """Update cache with markets from Kalshi API."""
        self._cache.clear()
        for market in markets:
            ticker = market.get("ticker", "")
            market_id = market.get("id", "")
            parsed = parse_kalshi_ticker(ticker)
            if parsed and parsed.is_valid:
                asset = parsed.asset
                if asset not in self._cache:
                    self._cache[asset] = {}
                self._cache[asset][ticker] = market_id
        
        self._last_update = datetime.now(timezone.utc)
        logger.info(f"[KALSHI_TICKER_CACHE] Updated with {len(markets)} markets, "
                   f"{sum(len(t) for t in self._cache.values())} valid tickers")
    
    def needs_refresh(self) -> bool:
        """Check if cache needs refresh based on TTL."""
        if not self._last_update:
            return True
        age = datetime.now(timezone.utc) - self._last_update
        return age > timedelta(minutes=self._cache_ttl_minutes)
    
    def get_cached_tickers(self, asset: Optional[str] = None) -> Set[str]:
        """Get all cached tickers, optionally filtered by asset."""
        if asset:
            return set(self._cache.get(asset, {}).keys())
        return set(t for asset_tickers in self._cache.values() for t in asset_tickers.keys())


# Global singleton cache
_ticker_cache: Optional[KalshiTickerCache] = None


def get_ticker_cache() -> KalshiTickerCache:
    """Get the global ticker cache singleton."""
    global _ticker_cache
    if _ticker_cache is None:
        _ticker_cache = KalshiTickerCache()
    return _ticker_cache


def parse_kalshi_ticker(ticker: str) -> Optional[ParsedKalshiTicker]:
    """Parse and validate a Kalshi 15m ticker string (STRICT validation).
    
    This is the strict parser used for validation. It enforces:
    - Asset must be in VALID_CRYPTO_ASSETS
    - Minute must be on 15m boundary (0, 15, 30, 45)
    - Month must be valid 3-letter abbreviation
    
    For loose parsing (normalization), use _parse_kalshi_ticker_loose().
    
    Args:
        ticker: The ticker string to parse (e.g., "KXBTC15M-26MAR251500")
        
    Returns:
        ParsedKalshiTicker with components and validation status, or None if invalid format
    """
    if not ticker:
        return None
    
    match = KALSHI_15M_TICKER_PATTERN.match(ticker.upper())
    if not match:
        return None

    # Groups are YY, MON, DD, HHMM (NOT DD, MON, YY, HHMM - see pattern comment)
    asset, year_short, month, day_str, time_str = match.groups()

    try:
        day = int(day_str)
        hour = int(time_str[:2])
        minute = int(time_str[2:])
        year = 2000 + int(year_short)  # Convert YY to YYYY
    except ValueError:
        return None

    # Validate asset
    if asset not in VALID_CRYPTO_ASSETS:
        return ParsedKalshiTicker(
            asset=asset, day=day, month=month, year=year,
            hour=hour, minute=minute, is_valid=False,
            error_message=f"Invalid asset: {asset}"
        )
    
    # Validate minute is on 15m boundary
    if minute not in VALID_15M_MINUTES:
        return ParsedKalshiTicker(
            asset=asset, day=day, month=month, year=year,
            hour=hour, minute=minute, is_valid=False,
            error_message=f"Invalid minute {minute}, must be 00, 15, 30, or 45"
        )
    
    # Validate month abbreviation
    valid_months = {'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
                   'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'}
    if month not in valid_months:
        return ParsedKalshiTicker(
            asset=asset, day=day, month=month, year=year,
            hour=hour, minute=minute, is_valid=False,
            error_message=f"Invalid month: {month}"
        )
    
    return ParsedKalshiTicker(
        asset=asset, day=day, month=month, year=year,
        hour=hour, minute=minute, is_valid=True
    )


def _parse_kalshi_ticker_loose(ticker: str) -> Optional[ParsedKalshiTicker]:
    """Parse a Kalshi ticker without enforcing 15m boundary constraint.
    
    Used internally for normalization when we need to accept any minute
    value (0-59) and floor it to the nearest 15m boundary.
    
    Args:
        ticker: The ticker string to parse
        
    Returns:
        ParsedKalshiTicker with is_valid=True if structurally parsable,
        or None if format is completely invalid
    """
    if not ticker:
        return None
    
    match = KALSHI_15M_TICKER_PATTERN.match(ticker.upper())
    if not match:
        return None

    # Groups are YY, MON, DD, HHMM (NOT DD, MON, YY, HHMM - see pattern comment)
    asset, year_short, month, day_str, time_str = match.groups()

    try:
        day = int(day_str)
        hour = int(time_str[:2])
        minute = int(time_str[2:])
        year = 2000 + int(year_short)
    except ValueError:
        return None
    
    # Basic validation: month must be valid
    valid_months = {'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
                   'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'}
    if month not in valid_months:
        return None
    
    # Return as parsable (is_valid=True means "structurally valid")
    # We don't check minute boundary here - that's for strict validation
    return ParsedKalshiTicker(
        asset=asset,
        day=day,
        month=month,
        year=year,
        hour=hour,
        minute=minute,
        is_valid=True
    )


def normalize_ticker_time(ticker: str) -> str:
    """Normalize ticker time to the nearest 15m window floor.
    
    Accepts any structurally-valid ticker and floors its minute value
    to the nearest 15m boundary (0, 15, 30, 45). Used to repair malformed
    tickers with non-boundary minutes.
    
    Args:
        ticker: The ticker string to normalize (e.g., "KXBTC15M-26MAR251713")
        
    Returns:
        Normalized ticker string with minute floored to 15m boundary,
        or original if parsing fails completely
        
    Example:
        "KXBTC15M-26MAR251713" -> "KXBTC15M-26MAR251715"  (13 -> 15)
        "KXBTC15M-26MAR251746" -> "KXBTC15M-26MAR251745"  (46 -> 45)
        "KXBTC15M-26MAR251700" -> "KXBTC15M-26MAR251700"  (already valid)
    """
    parsed = _parse_kalshi_ticker_loose(ticker)
    if not parsed:
        return ticker
    
    # Floor minute to nearest 15m boundary
    floored_minute = (parsed.minute // 15) * 15

    # Reconstruct ticker with normalized time (canonical YYMONDDHHMM order)
    new_time = f"{parsed.hour:02d}{floored_minute:02d}"
    normalized = f"KX{parsed.asset}15M-{str(parsed.year)[2:]}{parsed.month}{parsed.day:02d}{new_time}"
    
    if normalized != ticker:
        logger.warning(f"[KALSHI_TICKER_NORMALIZED] {ticker} -> {normalized}")
    
    return normalized


def is_valid_kalshi_ticker(ticker: str, require_cached: bool = False) -> Tuple[bool, Optional[str]]:
    """Validate a Kalshi ticker string.
    
    Args:
        ticker: The ticker string to validate
        require_cached: If True, also require ticker to be in the API cache
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not ticker:
        return False, "Empty ticker"
    
    parsed = parse_kalshi_ticker(ticker)
    if not parsed:
        return False, f"Invalid ticker format: {ticker}"
    
    if not parsed.is_valid:
        return False, parsed.error_message or f"Invalid ticker: {ticker}"
    
    if require_cached:
        cache = get_ticker_cache()
        if not cache.is_valid(ticker):
            return False, f"Ticker not found in cached markets: {ticker}"
    
    return True, None


def floor_time_to_15m(dt: datetime) -> datetime:
    """Floor a datetime to the nearest 15-minute boundary.
    
    Args:
        dt: The datetime to floor
        
    Returns:
        Datetime floored to 15m boundary (e.g., 19:16:45 -> 19:15:00)
    """
    return dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)


def get_current_15m_window() -> datetime:
    """Get the current 15-minute window start time (floored)."""
    return floor_time_to_15m(datetime.now(timezone.utc))


def format_ticker_for_15m_window(asset: str, window_time: datetime) -> str:
    """Format a ticker string for a given 15m window.
    
    Args:
        asset: The asset symbol (e.g., "BTC", "DOGE")
        window_time: The 15m window datetime (should be floored to 15m boundary)
        
    Returns:
        Formatted ticker string (e.g., "KXDOGE15M-26APR251915")
    """
    # Kalshi 15m tickers encode the window end in America/New_York (ET), not UTC
    try:
        from zoneinfo import ZoneInfo
        floored = floor_time_to_15m(window_time.astimezone(ZoneInfo("America/New_York")))
    except Exception:
        floored = floor_time_to_15m(window_time)

    # Format: KX{ASSET}15M-{YY}{MMM}{DD}{HHMM}  (YYMONDDHHMM, ET)
    month_map = {
        1: 'JAN', 2: 'FEB', 3: 'MAR', 4: 'APR', 5: 'MAY', 6: 'JUN',
        7: 'JUL', 8: 'AUG', 9: 'SEP', 10: 'OCT', 11: 'NOV', 12: 'DEC'
    }

    day = floored.day
    month = month_map[floored.month]
    year_short = str(floored.year)[2:]
    hour = floored.hour
    minute = floored.minute

    return f"KX{asset.upper()}15M-{year_short}{month}{day:02d}{hour:02d}{minute:02d}"


def normalize_ticker_for_order(ticker: str) -> str:
    """Normalize a ticker for order submission by stripping strike suffix.
    
    CRITICAL FIX (2026-05-01): Kalshi market tickers can include strike price
    suffixes like -30, -T80199.99, or -B80150. The order API expects the base
    market ticker without these suffixes.
    
    Examples:
        "KXETH15M-26MAY011530-30" -> "KXETH15M-26MAY011530"
        "KXBTC-26MAR2501-T80199.99" -> "KXBTC-26MAR2501"
        "KXBTC15M-26MAR251500" -> "KXBTC15M-26MAR251500" (no change)
    
    Args:
        ticker: The raw ticker string from market discovery
        
    Returns:
        Normalized ticker suitable for order submission
    """
    if not ticker:
        return ticker
    
    # Pattern 1: Strip numeric-only suffix after time (e.g., -30, -45)
    # Matches: KXETH15M-26MAY011530-30 -> KXETH15M-26MAY011530
    #          KXETH15M-26MAY2025011530-30 -> KXETH15M-26MAY2025011530 (4-digit year)
    # This is the most common case for 15m markets
    # Handle both 2-digit year (0600 = 6 digits) and 4-digit year (20250600 = 8 digits)
    numeric_suffix_pattern = r'^(KX[A-Z]+\d{2}[A-Z]{3}\d{6,8})-\d+$'
    match = re.match(numeric_suffix_pattern, ticker.upper())
    if match:
        normalized = match.group(1)
        if normalized != ticker:
            logger.debug(f"[TICKER_NORMALIZE] Stripped numeric suffix: {ticker} -> {normalized}")
        return normalized
    
    # Pattern 2: Strip threshold strike suffix (e.g., -T80199.99)
    # Matches: KXBTC-26MAR2501-T80199.99 -> KXBTC-26MAR2501
    threshold_pattern = r'^(KX[A-Z]+(?:\d{2}[A-Z]{3}\d{2,4})?)-T\d+(?:\.\d+)?$'
    match = re.match(threshold_pattern, ticker.upper())
    if match:
        normalized = match.group(1)
        if normalized != ticker:
            logger.debug(f"[TICKER_NORMALIZE] Stripped threshold suffix: {ticker} -> {normalized}")
        return normalized
    
    # Pattern 3: Strip bracket strike suffix (e.g., -B80150)
    # Matches: KXBTC-26MAR2501-B80150 -> KXBTC-26MAR2501
    bracket_pattern = r'^(KX[A-Z]+(?:\d{2}[A-Z]{3}\d{2,4})?)-B\d+(?:\.\d+)?$'
    match = re.match(bracket_pattern, ticker.upper())
    if match:
        normalized = match.group(1)
        if normalized != ticker:
            logger.debug(f"[TICKER_NORMALIZE] Stripped bracket suffix: {ticker} -> {normalized}")
        return normalized
    
    # No patterns matched - return original ticker
    return ticker
