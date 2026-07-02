"""
Canonical asset/ticker list for Kalshi 15m crypto trading profile.

This module is the SINGLE SOURCE OF TRUTH for:
- Active tickers for kalshi_crypto_15m_v2 profile
- Asset metadata (friendly names, series codes)
- Ladder levels and configuration

All other modules (WS bridge, market_state, agent grid, unified spot)
MUST import from this module to ensure consistency.
"""

from typing import List, Dict, Optional

# =============================================================================
# ACTIVE TICKERS - Single source of truth for 15m crypto markets
# =============================================================================

ACTIVE_TICKERS: List[str] = [
    "KXBTC15M",
    "KXETH15M",
    "KXSOL15M",
    "KXXRP15M",
    "KXDOGE15M",
]

# =============================================================================
# ASSET METADATA
# =============================================================================

ASSET_METADATA: Dict[str, Dict[str, str]] = {
    "KXBTC-15M": {
        "base_asset": "BTC",
        "friendly_name": "Bitcoin 15m",
        "series_code": "KXBTC-15M",
        "underlying": "BTC",
        "timeframe": "15m",
    },
    "KXETH-15M": {
        "base_asset": "ETH",
        "friendly_name": "Ethereum 15m",
        "series_code": "KXETH-15M",
        "underlying": "ETH",
        "timeframe": "15m",
    },
    "KXSOL-15M": {
        "base_asset": "SOL",
        "friendly_name": "Solana 15m",
        "series_code": "KXSOL-15M",
        "underlying": "SOL",
        "timeframe": "15m",
    },
    "KXXRP-15M": {
        "base_asset": "XRP",
        "friendly_name": "Ripple 15m",
        "series_code": "KXXRP-15M",
        "underlying": "XRP",
        "timeframe": "15m",
    },
    "KXDOGE-15M": {
        "base_asset": "DOGE",
        "friendly_name": "Dogecoin 15m",
        "series_code": "KXDOGE-15M",
        "underlying": "DOGE",
        "timeframe": "15m",
    },
}

# =============================================================================
# SERIES CODES (for catalog resolution)
# =============================================================================

SERIES_CODES: List[str] = [
    "KXBTC15M",
    "KXETH15M",
    "KXSOL15M",
    "KXXRP15M",
    "KXDOGE15M",
]

# =============================================================================
# LADDER LEVELS (for position sizing)
# =============================================================================

LADDER_LEVELS: Dict[str, List[int]] = {
    "BTC": [1, 2, 5, 10, 20, 50],
    "ETH": [1, 2, 5, 10, 20, 50],
    "SOL": [1, 2, 5, 10, 20, 50],
    "XRP": [1, 2, 5, 10, 20, 50],
    "DOGE": [1, 2, 5, 10, 20, 50],
}

# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_ticker_for_asset(asset: str) -> Optional[str]:
    """Get the 15m ticker for a base asset."""
    for ticker, meta in ASSET_METADATA.items():
        if meta["base_asset"] == asset:
            return ticker
    return None


def get_asset_for_ticker(ticker: str) -> Optional[str]:
    """Get the base asset for a ticker."""
    meta = ASSET_METADATA.get(ticker)
    return meta["base_asset"] if meta else None


def get_friendly_name(ticker: str) -> str:
    """Get the friendly name for a ticker."""
    meta = ASSET_METADATA.get(ticker)
    return meta["friendly_name"] if meta else ticker


def get_ladder_levels(asset: str) -> List[int]:
    """Get ladder levels for an asset."""
    return LADDER_LEVELS.get(asset, [1, 2, 5, 10, 20, 50])


def is_active_ticker(ticker: str) -> bool:
    """Check if a ticker is in the active set."""
    return ticker in ACTIVE_TICKERS


def get_all_active_tickers() -> List[str]:
    """Get all active tickers."""
    return ACTIVE_TICKERS.copy()


def get_all_series_codes() -> List[str]:
    """Get all series codes."""
    return SERIES_CODES.copy()
