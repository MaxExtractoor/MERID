"""Discover-Health API — reports Kalshi crypto discovery coverage.

GET /api/v1/system/discover-health

Returns, for each of BTC/ETH/SOL/XRP/DOGE:
  - markets_discovered  per timeframe (15m/1h/daily/weekly)
  - ws_subscribed       count per asset (from catalog)
  - coverage_complete   boolean

The endpoint is intentionally lightweight: it uses the in-memory singleton
KalshiMarketCatalog (if running) or accepts an injected market list for
testing.  It does **not** trigger a live Kalshi API call.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from utils.logger import get_logger

from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS, ACTIVE_CRYPTO_WS_TIMEFRAMES
from merid.event_venues.kalshi.crypto_catalog import (
    build_kalshi_crypto_catalog_from_catalog_markets,
    collect_crypto_ws_subscription_tickers,
    kalshi_ticker_to_asset,
    summarize_crypto_ws_coverage,
)

logger = get_logger("web.api.discover_health_api")

router = APIRouter(tags=["system"])


# ── Core computation (pure, no I/O) ─────────────────────────────────────────


def _compute_discover_health(catalog_markets: List[Any]) -> Dict[str, Any]:
    """Compute the Discover health payload from a list of CatalogMarket objects.

    This function is pure (no side-effects) so it can be unit-tested directly.

    Args:
        catalog_markets: Output of ``KalshiMarketCatalog.get_all_markets()``.

    Returns:
        JSON-serializable health dict with ``assets`` keyed by symbol.
    """
    crypto_catalog = build_kalshi_crypto_catalog_from_catalog_markets(catalog_markets)
    ws_tickers = collect_crypto_ws_subscription_tickers(crypto_catalog)
    coverage = summarize_crypto_ws_coverage(ws_tickers)

    # Count WS-subscribed tickers per asset from the coverage summary
    ws_by_asset: Dict[str, int] = coverage.get("by_asset", {})

    # Build per-asset breakdown
    assets_detail: Dict[str, Any] = {}
    for asset in ACTIVE_CRYPTO_ASSETS:
        tf_counts: Dict[str, int] = {}
        total_markets = 0
        for tf in ACTIVE_CRYPTO_WS_TIMEFRAMES:
            count = len(crypto_catalog.iter_tickers(asset, tf))
            tf_counts[tf] = count
            total_markets += count

        ws_count = ws_by_asset.get(asset, 0)
        assets_detail[asset] = {
            "markets_discovered": total_markets,
            "markets_by_timeframe": tf_counts,
            "ws_subscribed": ws_count,
            "status": "green" if total_markets > 0 and ws_count > 0 else "red",
        }

    all_green = all(v["status"] == "green" for v in assets_detail.values())
    return {
        "discover_green": all_green,
        "assets": assets_detail,
        "missing_assets": coverage.get("missing_assets", []),
        "total_ws_tickers": coverage.get("total_tickers", 0),
        "timestamp": int(time.time()),
    }


# ── Endpoint ─────────────────────────────────────────────────────────────────


@router.get("/api/v1/system/discover-health")
async def get_discover_health() -> Dict[str, Any]:
    """Return Discover-stage health for BTC/ETH/SOL/XRP/DOGE.

    Uses the running KalshiMarketCatalog singleton.  If the catalog has
    not been started (e.g., in test mode), returns empty coverage with
    ``discover_green: false``.
    """
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        catalog = get_market_catalog()
        markets = catalog.get_all_markets()
    except Exception as exc:
        logger.warning("discover-health: could not access market catalog: %s", exc)
        markets = []

    return _compute_discover_health(markets)
