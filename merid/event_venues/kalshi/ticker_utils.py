"""Kalshi ticker utilities for validation and normalization.

This module provides functions to validate, normalize, and cache Kalshi market tickers
to ensure they match Kalshi's canonical format and prevent 404 errors from invalid tickers.
"""

import re
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Set, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

# Kalshi ticker regex pattern for 15m crypto markets
# Format: KX{ASSET}15M-{DD}{MMM}{YY}{HH}{MM}
# Example: KXBTC15M-26MAR251500
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
        
        self._last_update = datetime.utcnow()
        logger.info(f"[KALSHI_TICKER_CACHE] Updated with {len(markets)} markets, "
                   f"{sum(len(t) for t in self._cache.values())} valid tickers")
    
    def needs_refresh(self) -> bool:
        """Check if cache needs refresh based on TTL."""
        if not self._last_update:
            return True
        age = datetime.utcnow() - self._last_update
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
    """Parse and validate a Kalshi 15m ticker string.
    
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
    
    asset, day_str, month, year_short, time_str = match.groups()
    
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


def normalize_ticker_time(ticker: str, reference_time: Optional[datetime] = None) -> str:
    """Normalize ticker time to the nearest 15m window floor.
    
    Args:
        ticker: The ticker string to normalize
        reference_time: Optional reference time (defaults to UTC now)
        
    Returns:
        Normalized ticker string, or original if parsing fails
    """
    parsed = parse_kalshi_ticker(ticker)
    if not parsed or not parsed.is_valid:
        return ticker
    
    # If time is already valid, return original
    if parsed.minute in VALID_15M_MINUTES:
        return ticker
    
    # Floor minute to nearest 15m boundary
    floored_minute = (parsed.minute // 15) * 15
    
    # Reconstruct ticker with normalized time
    new_time = f"{parsed.hour:02d}{floored_minute:02d}"
    normalized = f"KX{parsed.asset}15M-{parsed.day:02d}{parsed.month}{str(parsed.year)[2:]}{new_time}"
    
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
    return floor_time_to_15m(datetime.utcnow())


def format_ticker_for_15m_window(asset: str, window_time: datetime) -> str:
    """Format a ticker string for a given 15m window.
    
    Args:
        asset: The asset symbol (e.g., "BTC", "DOGE")
        window_time: The 15m window datetime (should be floored to 15m boundary)
        
    Returns:
        Formatted ticker string (e.g., "KXDOGE15M-26APR251915")
    """
    # Ensure time is floored to 15m boundary
    floored = floor_time_to_15m(window_time)
    
    # Format: KX{ASSET}15M-{DD}{MMM}{YY}{HH}{MM}
    month_map = {
        1: 'JAN', 2: 'FEB', 3: 'MAR', 4: 'APR', 5: 'MAY', 6: 'JUN',
        7: 'JUL', 8: 'AUG', 9: 'SEP', 10: 'OCT', 11: 'NOV', 12: 'DEC'
    }
    
    day = floored.day
    month = month_map[floored.month]
    year_short = str(floored.year)[2:]
    hour = floored.hour
    minute = floored.minute
    
    return f"KX{asset.upper()}15M-{day:02d}{month}{year_short}{hour:02d}{minute:02d}"
