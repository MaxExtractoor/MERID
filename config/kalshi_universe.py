"""Kalshi crypto universe aliases.

Re-exports from ``config.kalshi_crypto_config`` so that code referencing
``KALSHI_CRYPTO_ASSETS`` or ``kalshi_universe`` continues to work without
maintaining a separate list.
"""

from __future__ import annotations

from config.kalshi_crypto_config import (  # noqa: F401
    ACTIVE_CRYPTO_ASSETS,
    ALL_CRYPTO_ASSETS,
    ACTIVE_CRYPTO_FREQS,
    ACTIVE_CRYPTO_WS_TIMEFRAMES,
    FREQ_TO_WS_TIMEFRAME,
    WS_TIMEFRAME_TO_FREQ,
    WS_TIMEFRAME_TO_MOOD_LABEL,
    MOOD_LABEL_TO_WS_TIMEFRAME,
    active_crypto_asset_mood_timeframe_grid,
)

# Alias so that existing code using KALSHI_CRYPTO_ASSETS keeps working.
KALSHI_CRYPTO_ASSETS = ACTIVE_CRYPTO_ASSETS
