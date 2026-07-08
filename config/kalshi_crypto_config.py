"""Single source of truth for Kalshi crypto lane: assets and normalized frequencies.



**Do not** duplicate ``ACTIVE_CRYPTO_ASSETS`` / ``ACTIVE_CRYPTO_FREQS`` /

``ACTIVE_CRYPTO_WS_TIMEFRAMES`` elsewhere — import from this module (or

``config.kalshi_universe`` aliases). Series lists remain in

:data:`config.kalshi_universe.KALSHI_CRYPTO_PRODUCTS`.



Downstream (WS subscriptions, discovery filters, risk aggregation) should use

these constants — avoid hard-coded BTC-only lists in new code.



NOTE: For 15m crypto trading, canonical configuration is now in

config.kalshi_15m_crypto_config. This module remains for backward compatibility

and for broader crypto lane operations beyond 15m trading.

"""



from __future__ import annotations



import os

from collections import Counter

from typing import Dict, List, Optional, Sequence, Tuple



__all__ = [

    "ACTIVE_CRYPTO_ASSETS",

    "ACTIVE_CRYPTO_FREQS",

    "ACTIVE_CRYPTO_WS_TIMEFRAMES",

    "FREQ_TO_CATALOG_TIMEFRAME",

    "WS_TIMEFRAME_TO_MOOD_LABEL",

    "TOP_N_EDGE_ASSETS",

    "active_crypto_asset_mood_timeframe_grid",

    "get_merid_swarm_confidence_min",

    "kalshi_ticker_to_asset",

    "check_ws_ticker_asset_coverage",

    "MARKET_ORDER_FALLBACK_ENABLED",

    "MARKET_ORDER_FALLBACK_CONFIG",

]



# Import from canonical 15m config if available for consistency

try:

    from config.kalshi_universe import KALSHI_15M_CRYPTO_ASSETS, KALSHI_15M_SERIES_TICKERS

    _USE_CANONICAL_15M = True

except ImportError:

    _USE_CANONICAL_15M = False



# Canonical five-asset grid

# All 5 assets are required for kalshi_crypto_15m_v2 profile

if _USE_CANONICAL_15M:

    ACTIVE_CRYPTO_ASSETS = list(KALSHI_15M_CRYPTO_ASSETS)

else:

    ACTIVE_CRYPTO_ASSETS: List[str] = ["BTC", "ETH", "SOL", "XRP", "DOGE"]



# CRITICAL SAFETY: Maximum number of assets to execute per cycle (default 3)

# This prevents over-trading all 5 assets when only top edge has sufficient quality

# REVERTED (2026-05-08): default 3 (was 1) to restore profitable trading volume

TOP_N_EDGE_ASSETS = int(os.getenv("MERID_TOP_N_EDGE_ASSETS", "3"))



# Normalized frequency labels (aligned with :mod:`merid.event_venues.kalshi.crypto_catalog`).

# FOCUS: 15m timeframe only for trading. All other timeframes are signal-only.

if _USE_CANONICAL_15M:

    ACTIVE_CRYPTO_FREQS: List[str] = ["15M"]

else:

    ACTIVE_CRYPTO_FREQS: List[str] = ["15M"]



# Catalog / REST timeframe strings used on :class:`CatalogMarket` and WS ticker filters.

# FOCUS: 15m timeframe only for trading.

FREQ_TO_CATALOG_TIMEFRAME: Dict[str, str] = {

    "15M": "15m",

}



ACTIVE_CRYPTO_WS_TIMEFRAMES: List[str] = [

    FREQ_TO_CATALOG_TIMEFRAME[f] for f in ACTIVE_CRYPTO_FREQS

]



# REMOVED: WS_TIMEFRAME_TO_MOOD_LABEL - sentiment/mood components not used in 15m stack

# REMOVED: get_merid_swarm_confidence_min() - sentiment-driven sizing not used in 15m stack

# REMOVED: active_crypto_asset_mood_timeframe_grid() - mood surfaces not used in 15m stack



def kalshi_ticker_to_asset(ticker: str) -> Optional[str]:

    """Map a Kalshi market ticker to a canonical asset using longest series-prefix match.



    Uses :data:`config.kalshi_universe.KALSHI_CRYPTO_PRODUCTS` (lazy import) so series

    lists stay in one place while avoiding import cycles at module load.

    """

    if not ticker:

        return None

    u = ticker.upper().strip()

    from config.kalshi_universe import KALSHI_CRYPTO_PRODUCTS



    pairs: list[tuple[str, str]] = []

    for key, tickers in KALSHI_CRYPTO_PRODUCTS.items():

        asset = key.split("_", 1)[0]

        if asset not in ACTIVE_CRYPTO_ASSETS:

            continue

        for s in tickers:

            pairs.append((s.upper(), asset))

    pairs.sort(key=lambda x: len(x[0]), reverse=True)

    for prefix, asset in pairs:

        if u.startswith(prefix):

            return asset

    return None





def check_ws_ticker_asset_coverage(

    tickers: Sequence[str],

    *,

    strict: Optional[bool] = None,

) -> Tuple[bool, Counter, List[str]]:

    """Verify WS subscription list contains at least one ticker per configured asset.



    Uses :func:`kalshi_ticker_to_asset` for each ticker. Tickers that do not map

    to a canonical asset are skipped in the per-asset counts (and may indicate

    bad catalog data).



    Args:

        tickers: Market tickers passed to :meth:`KalshiWebSocketBridge.start`.

        strict: If True, raise ``ValueError`` when any asset is missing. If

            ``None``, use env ``MERID_STRICT_WS_CRYPTO_COVERAGE=1`` as True.



    Returns:

        (ok, counts_by_asset, missing_assets) where *counts* includes only

        mapped assets (subset of ACTIVE_CRYPTO_ASSETS keys may be absent).

    """

    if strict is None:

        strict = os.environ.get("MERID_STRICT_WS_CRYPTO_COVERAGE", "").strip() == "1"



    counts: Counter = Counter()

    for t in tickers:

        a = kalshi_ticker_to_asset(t)

        if a:

            counts[a] += 1



    missing = [a for a in ACTIVE_CRYPTO_ASSETS if counts[a] <= 0]

    ok = not missing



    if not ok and strict:

        raise ValueError(

            f"WS ticker list missing assets (expected each of {ACTIVE_CRYPTO_ASSETS}): "

            f"missing={missing}, counts={dict(counts)}, total_tickers={len(tickers)}"

        )



    return ok, counts, missing


# Market order fallback configuration
# Enable/disable market order fallback for resting limit orders
MARKET_ORDER_FALLBACK_ENABLED = os.getenv("MERID_MARKET_ORDER_FALLBACK_ENABLED", "true").lower() in ("1", "true", "yes")

# Fallback configuration parameters
MARKET_ORDER_FALLBACK_CONFIG = {
    # Time-based triggers
    "fallback_after_seconds": int(os.getenv("MERID_FALLBACK_AFTER_SECONDS", "90")),  # Convert after 90s
    "min_age_before_fallback": int(os.getenv("MERID_MIN_AGE_BEFORE_FALLBACK", "30")),  # Minimum age
    
    # Conviction thresholds
    "min_edge_pct": float(os.getenv("MERID_MIN_EDGE_PCT", "0.04")),  # 4% minimum edge
    "min_confidence": float(os.getenv("MERID_MIN_CONFIDENCE", "0.70")),  # 70% minimum confidence
    
    # Time to expiry
    "max_tte_for_fallback": int(os.getenv("MERID_MAX_TTE_FOR_FALLBACK", "300")),  # Max 5 minutes
    "urgent_tte_threshold": int(os.getenv("MERID_URGENT_TTE_THRESHOLD", "120")),  # Urgent if < 2 minutes
    
    # Market conditions
    "max_spread_cents": int(os.getenv("MERID_MAX_SPREAD_CENTS", "10")),  # Max 10 cent spread
    "min_depth_contracts": int(os.getenv("MERID_MIN_DEPTH_CONTRACTS", "5")),  # Minimum 5 contracts depth
    
    # Asset-specific overrides (lower thresholds for high-volume assets)
    "asset_overrides": {
        "BTC": {
            "min_edge_pct": float(os.getenv("MERID_BTC_MIN_EDGE_PCT", "0.03")),  # 3% for BTC
            "fallback_after_seconds": int(os.getenv("MERID_BTC_FALLBACK_AFTER_SECONDS", "60")),  # Faster for BTC
        },
        "ETH": {
            "min_edge_pct": float(os.getenv("MERID_ETH_MIN_EDGE_PCT", "0.03")),  # 3% for ETH
            "fallback_after_seconds": int(os.getenv("MERID_ETH_FALLBACK_AFTER_SECONDS", "60")),  # Faster for ETH
        },
    }
}

