"""Kalshi Market Utilities — Public helper functions for market/ticker handling.

This module provides public, stable APIs for:
- Extracting underlying assets from tickers
- Group ID resolution
- Timeframe bucketing

All functions here are safe to import from any module without circular dependency issues.
"""

from typing import Dict, List, Tuple

# ═══════════════════════════════════════════════════════════════════════════
# Ticker → Underlying Asset Mapping (comprehensive coverage)
# ═══════════════════════════════════════════════════════════════════════════

# (prefix, underlying) pairs for _get_underlying extraction.
# Order matters: longer/more specific prefixes should come first.
TICKER_UNDERLYING_MAP: List[Tuple[str, str]] = [
    # Crypto (primary)
    ("KXBTC", "BTC"),    ("KXETH", "ETH"),     ("KXSOL", "SOL"),
    ("KXXRP", "XRP"),    ("KXDOGE", "DOGE"),   ("KXLTC", "LTC"),
    ("KXADA", "ADA"),    ("KXDOT", "DOT"),     ("KXMATIC", "MATIC"),
    ("KXSHIB", "SHIB"),  ("KXAVAX", "AVAX"),   ("KXLINK", "LINK"),
    ("KXUNI", "UNI"),    ("KXATOM", "ATOM"),   ("KXXLM", "XLM"),
    ("KXETC", "ETC"),    ("KXFIL", "FIL"),     ("KXT", "BTC"),      # Fallback BTC
    # Forex
    ("KXEUR", "EUR"),    ("KXGBP", "GBP"),     ("KXJPY", "JPY"),
    ("KXUSD", "USD"),    ("KXCAD", "CAD"),     ("KXCHF", "CHF"),
    # Commodities
    ("KXGLD", "GOLD"),   ("KXSLV", "SILVER"),  ("KXWTI", "OIL"),
    ("KXOIL", "OIL"),    ("KXNGL", "NATGAS"),  ("KXUNG", "NATGAS"),
    # Indices
    ("KXSPX", "SPX"),    ("KXNDX", "NDX"),     ("KXVIX", "VIX"),
    ("KXDJI", "DJI"),    ("KXRUT", "RUT"),
    # Economics
    ("KXCPI", "CPI"),    ("KXGDP", "GDP"),     ("KXJOB", "JOBS"),
    ("KXUNEMP", "UNEMP"),
    # Tech/AI stocks
    ("KXAI", "AI"),      ("KXOPENAI", "AI"),   ("KXNVDA", "NVDA"),
    ("KXAPPLE", "AAPL"), ("KXMETA", "META"),   ("KXGOOGLE", "GOOGL"),
    ("KXMSFT", "MSFT"),  ("KXTECH", "TECH"),
]


def get_underlying(ticker: str) -> str:
    """Extract underlying asset symbol from any Kalshi ticker (all categories).

    Args:
        ticker: Kalshi market ticker (e.g., "KXBTC15M-27APR-T101500")

    Returns:
        Uppercase underlying asset code (e.g., "BTC", "ETH", "SPX")
        Returns "OTHER" if no match found.

    Examples:
        >>> get_underlying("KXBTC15M-27APR-T101500")
        'BTC'
        >>> get_underlying("KXETH-D-240101")
        'ETH'
        >>> get_underlying("KXSPX-W-240101")
        'SPX'
    """
    upper = ticker.upper()
    for prefix, underlying in TICKER_UNDERLYING_MAP:
        if prefix in upper:
            return underlying
    return "OTHER"
