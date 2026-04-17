"""Single source of truth for Kalshi crypto lane: assets and normalized frequencies.

**Do not** duplicate ``ACTIVE_CRYPTO_ASSETS`` / ``ACTIVE_CRYPTO_FREQS`` /
``ACTIVE_CRYPTO_WS_TIMEFRAMES`` elsewhere — import from this module (or
``config.kalshi_universe`` aliases). Series lists remain in
:data:`config.kalshi_universe.KALSHI_CRYPTO_PRODUCTS`.

Downstream (WS subscriptions, discovery filters, risk aggregation) should use
these constants — avoid hard-coded BTC-only lists in new code.
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
    "active_crypto_asset_mood_timeframe_grid",
    "get_merid_swarm_confidence_min",
    "kalshi_ticker_to_asset",
    "check_ws_ticker_asset_coverage",
]

# Canonical five-asset grid (order stable for logs and UI).
ACTIVE_CRYPTO_ASSETS: List[str] = ["BTC", "ETH", "SOL", "XRP", "DOGE"]

# Normalized frequency labels (aligned with :mod:`merid.event_venues.kalshi.crypto_catalog`).
ACTIVE_CRYPTO_FREQS: List[str] = ["15M", "1H", "D1", "W1", "M1"]

# Catalog / REST timeframe strings used on :class:`CatalogMarket` and WS ticker filters.
FREQ_TO_CATALOG_TIMEFRAME: Dict[str, str] = {
    "15M": "15m",
    "1H": "1h",
    "D1": "daily",
    "W1": "weekly",
    "M1": "monthly",
}

ACTIVE_CRYPTO_WS_TIMEFRAMES: List[str] = [
    FREQ_TO_CATALOG_TIMEFRAME[f] for f in ACTIVE_CRYPTO_FREQS
]

# MarketMoodBus / SentimentContext use short labels (not catalog "D1"/"W1").
WS_TIMEFRAME_TO_MOOD_LABEL: Dict[str, str] = {
    "15m": "15m",
    "1h": "1h",
    "daily": "daily",
    "weekly": "weekly",
    "monthly": "monthly",
}


def get_merid_swarm_confidence_min() -> float:
    """Minimum swarm ``consensus_confidence`` for sentiment-driven sizing (0 = disabled).

    Reads :attr:`merid.settings.settings.MERID_SWARM_CONFIDENCE_MIN`; falls back to env.
    """
    try:
        from merid.settings import settings as _s

        return float(_s.MERID_SWARM_CONFIDENCE_MIN)
    except Exception:
        v = os.environ.get("MERID_SWARM_CONFIDENCE_MIN", "0").strip()
        return float(v) if v else 0.0


def active_crypto_asset_mood_timeframe_grid() -> List[Tuple[str, str]]:
    """All (asset, timeframe) pairs for lane/swarm/mood surfaces.

    Aligns :data:`ACTIVE_CRYPTO_ASSETS` with :data:`ACTIVE_CRYPTO_WS_TIMEFRAMES`
    via :data:`WS_TIMEFRAME_TO_MOOD_LABEL` so sentiment and dashboards are not
    BTC‑skewed or missing weekly coverage.
    """
    out: List[Tuple[str, str]] = []
    for asset in ACTIVE_CRYPTO_ASSETS:
        for ws in ACTIVE_CRYPTO_WS_TIMEFRAMES:
            label = WS_TIMEFRAME_TO_MOOD_LABEL.get(ws)
            if label:
                out.append((asset, label))
    return out


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
