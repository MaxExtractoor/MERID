"""
Canonical Kalshi Identity Helper Module

Purpose: Provide single source of truth for asset, window, and market ID extraction
from Kalshi tickers. This ensures consistency across all layers (agent grid, loop, router,
catalog, position cache, resting monitor).

Date: 2026-07-21
Context: Fix for asset-window key derivation inconsistencies causing duplicate order enforcement failures.
"""

from typing import Tuple, Optional
import re

# Canonical asset symbols for 15m crypto stack
CANONICAL_ASSETS = {"BTC", "ETH", "SOL", "XRP", "DOGE"}


def extract_asset(ticker: str) -> str:
    """
    Extract canonical asset symbol from Kalshi ticker.
    
    Args:
        ticker: Kalshi ticker (e.g., "KXBTC15M-26JUL211745-45")
    
    Returns:
        Canonical asset symbol (e.g., "BTC")
    
    Examples:
        >>> extract_asset("KXBTC15M-26JUL211745-45")
        "BTC"
        >>> extract_asset("KXETH15M-26JUL211730-30")
        "ETH"
    """
    if not ticker:
        return "UNKNOWN"
    
    ticker_upper = ticker.upper()
    
    # Canonical extraction: substring match for asset symbols
    # This matches the logic in order_router.py and loop_15m.py
    for asset in CANONICAL_ASSETS:
        if asset in ticker_upper:
            return asset
    
    # Fallback: try to extract from ticker prefix
    # Handles cases like "BTC15M" or "KXBTC"
    match = re.search(r'(BTC|ETH|SOL|XRP|DOGE)', ticker_upper)
    if match:
        return match.group(1)
    
    return "UNKNOWN"


def extract_window_id(ticker: str) -> str:
    """
    Extract 15-minute window ID from Kalshi ticker.
    
    Args:
        ticker: Kalshi ticker (e.g., "KXBTC15M-26JUL211745-45")
    
    Returns:
        Window ID (e.g., "26JUL211745")
    
    Examples:
        >>> extract_window_id("KXBTC15M-26JUL211745-45")
        "26JUL211745"
        >>> extract_window_id("KXETH15M-26JUL211730-30")
        "26JUL211730"
    """
    if not ticker:
        return "UNKNOWN"
    
    # Kalshi ticker format: KX{ASSET}15M-{DATE}{TIME}-{STRIKE}
    # Window ID is the second-to-last component (DATE{TIME})
    parts = ticker.split("-")
    if len(parts) >= 2:
        return parts[-2]
    
    # Fallback: return ticker if no hyphens
    return ticker


def extract_asset_window_key(ticker: str) -> str:
    """
    Generate asset-window key for one-contract-per-asset-per-15-minute rule enforcement.
    
    Args:
        ticker: Kalshi ticker (e.g., "KXBTC15M-26JUL211745-45")
    
    Returns:
        Asset-window key (e.g., "BTC:26JUL211745")
    
    Examples:
        >>> extract_asset_window_key("KXBTC15M-26JUL211745-45")
        "BTC:26JUL211745"
    """
    asset = extract_asset(ticker)
    window_id = extract_window_id(ticker)
    return f"{asset}:{window_id}"


def extract_series(ticker: str) -> str:
    """
    Extract series identifier from Kalshi ticker.
    
    Args:
        ticker: Kalshi ticker (e.g., "KXBTC15M-26JUL211745-45")
    
    Returns:
        Series identifier (e.g., "KXBTC15M")
    
    Examples:
        >>> extract_series("KXBTC15M-26JUL211745-45")
        "KXBTC15M"
    """
    if not ticker:
        return "UNKNOWN"
    
    # Series is everything before the first hyphen
    parts = ticker.split("-")
    if parts:
        return parts[0]
    
    return ticker


def extract_market_id(ticker: str) -> str:
    """
    Extract full market ID from Kalshi ticker.
    
    Args:
        ticker: Kalshi ticker (e.g., "KXBTC15M-26JUL211745-45")
    
    Returns:
        Full market ID (e.g., "KXBTC15M-26JUL211745-45")
    
    Note:
        This is essentially the ticker itself, but provided for API consistency.
    """
    return ticker if ticker else "UNKNOWN"


def validate_ticker(ticker: str) -> Tuple[bool, Optional[str]]:
    """
    Validate that a Kalshi ticker has the expected format.
    
    Args:
        ticker: Kalshi ticker to validate
    
    Returns:
        Tuple of (is_valid, error_message)
    
    Examples:
        >>> validate_ticker("KXBTC15M-26JUL211745-45")
        (True, None)
        >>> validate_ticker("INVALID")
        (False, "Invalid ticker format")
    """
    if not ticker:
        return False, "Ticker is empty"
    
    # Check for expected components
    asset = extract_asset(ticker)
    if asset == "UNKNOWN":
        return False, f"Cannot extract valid asset from ticker: {ticker}"
    
    window_id = extract_window_id(ticker)
    if window_id == "UNKNOWN":
        return False, f"Cannot extract valid window ID from ticker: {ticker}"
    
    return True, None


def parse_kalshi_ticker(ticker: str) -> dict:
    """
    Parse a Kalshi ticker into all its components.
    
    Args:
        ticker: Kalshi ticker (e.g., "KXBTC15M-26JUL211745-45")
    
    Returns:
        Dictionary with all parsed components:
        {
            "asset": "BTC",
            "window_id": "26JUL211745",
            "asset_window_key": "BTC:26JUL211745",
            "series": "KXBTC15M",
            "market_id": "KXBTC15M-26JUL211745-45",
            "is_valid": True,
            "error": None
        }
    
    Examples:
        >>> parse_kalshi_ticker("KXBTC15M-26JUL211745-45")
        {
            "asset": "BTC",
            "window_id": "26JUL211745",
            "asset_window_key": "BTC:26JUL211745",
            "series": "KXBTC15M",
            "market_id": "KXBTC15M-26JUL211745-45",
            "is_valid": True,
            "error": None
        }
    """
    is_valid, error = validate_ticker(ticker)
    
    return {
        "asset": extract_asset(ticker),
        "window_id": extract_window_id(ticker),
        "asset_window_key": extract_asset_window_key(ticker),
        "series": extract_series(ticker),
        "market_id": extract_market_id(ticker),
        "is_valid": is_valid,
        "error": error
    }
