"""Canonical crypto universe for MERID's Kalshi integration.

This module is the **single authoritative source of truth** for:
  - Active crypto assets (BTC, ETH, SOL, XRP, DOGE)
  - Active Kalshi timeframe identifiers (both catalog and WS variants)
  - Mood/timeframe label mapping for the sentiment bus
  - The 5×4 asset × timeframe grid used by agents, catalogs, and sentiment

All other modules that need these lists **must** import from here instead
of maintaining their own copies.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, List, Tuple

# ── Active crypto assets ────────────────────────────────────────────────────

ACTIVE_CRYPTO_ASSETS: List[str] = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
"""Ordered list of the five crypto assets MERID actively trades on Kalshi."""

ALL_CRYPTO_ASSETS: FrozenSet[str] = frozenset(ACTIVE_CRYPTO_ASSETS)
"""Immutable set for fast membership checks (e.g. ``"BTC" in ALL_CRYPTO_ASSETS``)."""

# ── Active timeframes ───────────────────────────────────────────────────────

ACTIVE_CRYPTO_FREQS: List[str] = ["15M", "1H", "D1", "W1"]
"""Canonical Kalshi frequency codes used by catalog rows and series detection."""

ACTIVE_CRYPTO_WS_TIMEFRAMES: List[str] = ["15m", "1h", "daily", "weekly"]
"""Human-readable timeframe labels used by the continuous trader and sentiment bus."""

# Mapping from catalog freq code → WS/trader timeframe label
FREQ_TO_WS_TIMEFRAME: Dict[str, str] = {
    "15M": "15m",
    "1H": "1h",
    "D1": "daily",
    "W1": "weekly",
}

WS_TIMEFRAME_TO_FREQ: Dict[str, str] = {v: k for k, v in FREQ_TO_WS_TIMEFRAME.items()}

# ── Mood / sentiment label mapping ──────────────────────────────────────────

WS_TIMEFRAME_TO_MOOD_LABEL: Dict[str, str] = {
    "15m": "scalp",
    "1h": "intraday",
    "daily": "swing",
    "weekly": "position",
}
"""Maps WS timeframe labels to the mood/sentiment label used by hashtag agents."""

MOOD_LABEL_TO_WS_TIMEFRAME: Dict[str, str] = {v: k for k, v in WS_TIMEFRAME_TO_MOOD_LABEL.items()}


# ── 5×4 grid helper ─────────────────────────────────────────────────────────

def active_crypto_asset_mood_timeframe_grid() -> List[Tuple[str, str, str]]:
    """Return the canonical 5×4 (asset × timeframe × mood) grid.

    Returns a list of ``(asset, ws_timeframe, mood_label)`` triples for
    all twenty active (asset, timeframe) combinations.

    Example::

        for asset, tf, mood in active_crypto_asset_mood_timeframe_grid():
            print(asset, tf, mood)
        # BTC 15m scalp
        # BTC 1h intraday
        # ...
    """
    grid: List[Tuple[str, str, str]] = []
    for asset in ACTIVE_CRYPTO_ASSETS:
        for tf in ACTIVE_CRYPTO_WS_TIMEFRAMES:
            mood = WS_TIMEFRAME_TO_MOOD_LABEL[tf]
            grid.append((asset, tf, mood))
    return grid
