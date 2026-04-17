"""MERID US-Compliant Venue Configuration.

Organizes venues into three categories:
1. US-COMPLIANT: Fully enabled for live trading
2. BLOCKED: Explicitly prohibited (Bybit, etc.)
3. OPTIONAL/DATA-ONLY: Available for data/sim, live blocked by default
"""

from typing import Set

# ============================================================
# 1. US-COMPLIANT VENUES - Fully enabled for live trading
# ============================================================
US_COMPLIANT_VENUES: Set[str] = {
    # US Equities & ETFs
    "alpaca",           # US stocks, ETFs, crypto (paper + live)
    "ibkr",             # Interactive Brokers (stocks, futures, options, FX)
    
    # US Crypto
    "binanceus",        # Binance.US (crypto spot only)
    "coinbase",         # Coinbase (US compliant)
    "coinbase_advanced", # Coinbase Advanced Trade API
    "kraken",           # Kraken (US compliant where available)
    "gemini",           # Gemini (US compliant)
    
    # Prediction Markets
    "kalshi",           # CFTC-regulated US prediction market
    
    # MERID Internal
    "merid_sim",        # MERID simulator (paper trading)
    "merid_spectator",  # MERID spectator mode (read-only)
}

# ============================================================
# 2. BLOCKED VENUES - Explicitly prohibited for US users
# ============================================================
BLOCKED_VENUES: Set[str] = {
    "bybit",            # Bybit - US RESTRICTED (ToS violation)
    "binance",          # Global Binance (not US compliant)
    "bitmex",           # BitMEX - restricted in US
    "deribit",          # Deribit - restricted in US
    "ftx",              # FTX (defunct)
    "huobi",            # Huobi - restricted in US
}

# ============================================================
# 3. OPTIONAL/DATA-ONLY VENUES - Data/sim allowed, live blocked
# ============================================================
OPTIONAL_VENUES: Set[str] = {
    "bitget",           # Data/sim only for US residents
    "kucoin",           # Data/sim only for US residents
    "gateio",           # Data/sim only for US residents
    "mexc",             # Data/sim only for US residents
    "htx",              # HTX (Huobi) - data/sim only for US
    "okx",              # OKX - data/sim only for US
}

# All venues that can be used (compliant + optional)
ALLOWED_VENUES: Set[str] = US_COMPLIANT_VENUES | OPTIONAL_VENUES

# Venue types by asset class (US-compliant only for live trading)
VENUE_ASSET_CLASSES = {
    "equities": {"alpaca", "ibkr"},
    "etfs": {"alpaca", "ibkr"},
    "options": {"ibkr"},
    "futures": {"ibkr"},
    "fx": {"ibkr"},
    "crypto_spot": {"alpaca", "binanceus", "coinbase", "coinbase_advanced", "kraken", "gemini"},
    "crypto_perp": set(),  # No US-compliant perp venues in default list
    "prediction": {"kalshi"},
}

# Optional venues for data (not live trading)
OPTIONAL_ASSET_CLASSES = {
    "crypto_spot": {"bitget", "kucoin", "gateio", "mexc"},
}

# Venue endpoints (US-only)
US_ENDPOINTS = {
    "binanceus": "https://api.binance.us",
    "alpaca": "https://paper-api.alpaca.markets",
    "alpaca_live": "https://api.alpaca.markets",
    "kalshi": "https://trading-api.kalshi.com",
    "ibkr": "127.0.0.1:7497",
}


def is_venue_allowed(venue: str) -> bool:
    """Check if venue is allowed (compliant or optional)."""
    return venue.lower() in ALLOWED_VENUES


def is_venue_blocked(venue: str) -> bool:
    """Check if venue is explicitly blocked."""
    return venue.lower() in BLOCKED_VENUES


def is_venue_optional(venue: str) -> bool:
    """Check if venue is optional/data-only."""
    return venue.lower() in OPTIONAL_VENUES


def is_venue_us_compliant(venue: str) -> bool:
    """Check if venue is fully US-compliant for live trading."""
    return venue.lower() in US_COMPLIANT_VENUES


def get_venues_for_asset_class(asset_class: str) -> Set[str]:
    """Get US-compliant venues for an asset class."""
    return VENUE_ASSET_CLASSES.get(asset_class.lower(), set())


def validate_venue_selection(venue: str, asset_class: str, live: bool = True) -> bool:
    """Validate venue selection.
    
    Args:
        venue: Venue name
        asset_class: Asset class
        live: If True, requires full US compliance
    """
    venue = venue.lower()
    
    if venue in BLOCKED_VENUES:
        return False
    
    if live and venue in OPTIONAL_VENUES:
        return False  # Optional venues blocked for live trading
    
    if venue not in ALLOWED_VENUES:
        return False
    
    allowed_venues = get_venues_for_asset_class(asset_class)
    return venue in allowed_venues
