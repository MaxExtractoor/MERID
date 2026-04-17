"""Runtime Kalshi crypto config snapshot — code defaults plus selected env (operator / tests)."""

from __future__ import annotations

import os
from typing import Any, Dict

SNAPSHOT_SCHEMA_VERSION = 1


def build_kalshi_crypto_runtime_snapshot() -> Dict[str, Any]:
    from merid.event_venues.kalshi.constants import ALL_CRYPTO_ASSETS
    from config.kalshi_universe import KALSHI_CRYPTO_PRODUCTS, kalshi_ct_default_series_tickers
    from merid.event_venues.kalshi.invariants import KALSHI_CRYPTOTIMEFRAMES
    from merid.trading.kalshi_continuous_trader import TraderConfig

    tc = TraderConfig()
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "all_crypto_assets": sorted(ALL_CRYPTO_ASSETS),
        "kalshi_cryptotimeframes": list(KALSHI_CRYPTOTIMEFRAMES),
        "ct_allowlist_series_tickers": sorted(kalshi_ct_default_series_tickers()),
        "trader_config_series_tickers": sorted(tc.series_tickers),
        "kalshi_crypto_products_keys": sorted(KALSHI_CRYPTO_PRODUCTS.keys()),
        "env": {
            "MERID_PROFILE": os.environ.get("MERID_PROFILE"),
            "KALSHI_USE_DEMO": os.environ.get("KALSHI_USE_DEMO"),
            "MERID_PM_TRADING_MODE": os.environ.get("MERID_PM_TRADING_MODE"),
            "MERID_PM_LIVE_ENABLED": os.environ.get("MERID_PM_LIVE_ENABLED"),
        },
    }
