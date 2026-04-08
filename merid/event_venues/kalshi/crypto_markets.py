"""Crypto market utilities and constants for Kalshi integration.

Defines series mappings for crypto assets across timeframes and helpers
for normalizing tickers to their series codes.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from merid.event_venues.kalshi.market_catalog import CatalogMarket

# Base crypto series (no timeframe suffix)
CRYPTO_SERIES: Dict[str, str] = {
    "BTC": "KXBTC",
    "ETH": "KXETH",
    "SOL": "KXSOL",
    "XRP": "KXXRP",
    "DOGE": "KXDOGE",
}

# Explicit 15m series codes used by Kalshi (instance tickers carry a trailing "-<timestamp>-<seq>")
CRYPTO_SERIES_15M: Dict[str, str] = {
    "BTC": "KXBTC15M",
    "ETH": "KXETH15M",
    "SOL": "KXSOL15M",
    "XRP": "KXXRP15M",
    "DOGE": "KXDOGE15M",
}

# Reverse mapping for quick asset lookup from a series ticker
SERIES_TO_CRYPTO: Dict[str, str] = {
    **{v: k for k, v in CRYPTO_SERIES.items()},
    **{v: k for k, v in CRYPTO_SERIES_15M.items()},
}


def normalize_series_ticker(ticker: Optional[str]) -> str:
    """Normalize a Kalshi market ticker to its series code.

    Example:
        "KXBTC15M-26MAR231500-00" -> "KXBTC15M"
        "KXDOGE15M-26MAR231515-15" -> "KXDOGE15M"
    """
    if not ticker:
        return ""
    return ticker.split("-")[0].upper()


def build_crypto_market_tickers(
    catalog: Any,
    *,
    assets: Optional[Iterable[str]] = None,
    timeframe: str = "15m",
) -> List[str]:
    """Build a list of crypto market tickers to subscribe to.

    Args:
        catalog: KalshiMarketCatalog (or compatible) instance.
        assets: Optional iterable of asset symbols to include.
        timeframe: Timeframe filter (default: "15m").

    Returns:
        List of full market tickers (instance-level) for the requested assets/timeframe.
    """
    target_assets = {a.upper() for a in (assets or CRYPTO_SERIES_15M.keys())}
    if not catalog:
        return []

    try:
        markets = catalog.get_markets_by_category("crypto", timeframe=timeframe)
    except Exception:
        markets = []

    # Fallback: scan all markets if timeframe categorization missed some entries
    if not markets and hasattr(catalog, "get_all_markets"):
        try:
            markets = catalog.get_all_markets()
        except Exception:
            markets = []

    tickers: List[str] = []
    seen = set()

    for entry in markets:
        # CatalogMarket carries the raw EventMarket under `market`
        ticker = getattr(entry, "market_id", None)
        if not ticker and isinstance(entry, CatalogMarket):
            ticker = getattr(entry.market, "market_id", None)
        elif not ticker and hasattr(entry, "market"):
            ticker = getattr(entry.market, "market_id", None)

        if not ticker:
            continue

        series = normalize_series_ticker(ticker)
        asset = SERIES_TO_CRYPTO.get(series)
        if asset and asset in target_assets and ticker not in seen:
            tickers.append(ticker)
            seen.add(ticker)

    return tickers
