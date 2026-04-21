"""
Canonical symbol constants for MERID.

This module defines the standard internal representation for trading symbols
across the platform. All major crypto assets are quoted in USD to align with:
- Coinbase spot USD markets (BTC-USD, ETH-USD, etc.)
- Kalshi USD-settled contracts

Any USDT pairs should be treated as legacy and migrated to USD.
"""

from typing import Set, List, Dict

# ============================================================================
# MAJOR CRYPTO ASSETS - USD QUOTED (Canonical)
# ============================================================================

BTC_USD = "BTC/USD"
ETH_USD = "ETH/USD"
SOL_USD = "SOL/USD"
XRP_USD = "XRP/USD"
DOGE_USD = "DOGE/USD"

# All major assets as a set for quick lookup
MAJOR_CRYPTO_ASSETS: Set[str] = {
    BTC_USD,
    ETH_USD,
    SOL_USD,
    XRP_USD,
    DOGE_USD,
}

# Base assets (without quote currency)
MAJOR_CRYPTO_BASES: Set[str] = {"BTC", "ETH", "SOL", "XRP", "DOGE"}

# Default symbols for tests and examples
DEFAULT_MAJOR_SYMBOLS: List[str] = [BTC_USD, ETH_USD, SOL_USD]

# ============================================================================
# VENUE-SPECIFIC MAPPINGS
# ============================================================================

# Coinbase Advanced Trade uses hyphen format: BTC-USD
COINBASE_SYMBOLS: Dict[str, str] = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
    "XRP": "XRP-USD",
    "DOGE": "DOGE-USD",
}

# Kalshi uses KX prefix with series codes
KALSHI_SERIES_BASE: Dict[str, str] = {
    "BTC": "KXBTC",
    "ETH": "KXETH",
    "SOL": "KXSOL",
    "XRP": "KXXRP",
    "DOGE": "KXDOGE",
}

# ============================================================================
# LEGACY / MIGRATION
# ============================================================================

# These symbols are deprecated and should be migrated to USD equivalents
DEPRECATED_USDT_SYMBOLS: Set[str] = {
    "BTC/USDT", "BTC-USDT",
    "ETH/USDT", "ETH-USDT",
    "SOL/USDT", "SOL-USDT",
    "XRP/USDT", "XRP-USDT",
    "DOGE/USDT", "DOGE-USDT",
}

# USDT is allowed only for:
# 1. Non-major crypto assets (altcoins not in MAJOR_CRYPTO_BASES)
# 2. Specific external APIs that only offer USDT pairs
# 3. On-chain token contracts (USDT as an asset, not quote currency)
ALLOWED_USDT_USE_CASES = [
    "external_api_only",  # APIs that don't offer USD pairs
    "on_chain_token",     # USDT token contract addresses
    "altcoin_pairing",    # Non-major assets that only trade against USDT
]


def normalize_to_usd(symbol: str) -> str:
    """
    Normalize a symbol to USD quote format.
    
    Args:
        symbol: Trading symbol (e.g., "BTC/USDT", "BTC-USD", "BTC")
        
    Returns:
        Normalized symbol (e.g., "BTC/USD")
    """
    if not symbol:
        return symbol
        
    # Already in correct format
    if symbol in MAJOR_CRYPTO_ASSETS:
        return symbol
        
    # Replace USDT with USD for major assets (both slash and hyphen formats)
    if symbol in DEPRECATED_USDT_SYMBOLS:
        if "/USDT" in symbol:
            return symbol.replace("/USDT", "/USD")
        elif "-USDT" in symbol:
            return symbol.replace("-USDT", "/USD")
        
    # Handle hyphen format (Coinbase)
    if symbol in ("BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD"):
        return symbol.replace("-", "/")
        
    # Handle concatenated format (BTCUSDT -> BTC/USD)
    upper_sym = symbol.upper()
    if upper_sym.startswith("BTC") and upper_sym.endswith("USDT"):
        return "BTC/USD"
    if upper_sym.startswith("ETH") and upper_sym.endswith("USDT"):
        return "ETH/USD"
    if upper_sym.startswith("SOL") and upper_sym.endswith("USDT"):
        return "SOL/USD"
    if upper_sym.startswith("XRP") and upper_sym.endswith("USDT"):
        return "XRP/USD"
    if upper_sym.startswith("DOGE") and upper_sym.endswith("USDT"):
        return "DOGE/USD"
    
    # Handle base-only symbols
    if upper_sym in MAJOR_CRYPTO_BASES:
        return f"{upper_sym}/USD"
        
    return symbol


def is_major_crypto(symbol: str) -> bool:
    """Check if symbol is a major crypto asset (USD-quoted)."""
    if not symbol:
        return False
    
    # Check full symbol
    if symbol.upper() in (s.upper() for s in MAJOR_CRYPTO_ASSETS):
        return True
        
    # Check base asset
    base = symbol.split("/")[0].split("-")[0].upper()
    return base in MAJOR_CRYPTO_BASES


def get_base_asset(symbol: str) -> str:
    """Extract base asset from symbol."""
    if not symbol:
        return ""
    return symbol.split("/")[0].split("-")[0].upper()


def to_coinbase_format(symbol: str) -> str:
    """Convert internal symbol to Coinbase format (BTC-USD)."""
    base = get_base_asset(symbol)
    return COINBASE_SYMBOLS.get(base, symbol)


def to_internal_format(symbol: str) -> str:
    """Convert any format to internal /USD format."""
    return normalize_to_usd(symbol)
