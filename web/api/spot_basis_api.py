"""Spot/Kalshi Basis REST API.

Exposes the live SpotBasisTracker state over HTTP so the frontend panel
and external monitoring can read per-asset alignment status.

Endpoints:
    GET /api/v1/kalshi/spot-basis         — Current basis state for all 5 assets
    GET /api/v1/kalshi/spot-basis/stats   — Rolling stats (mean, median, p95, etc.)

The tracker is started by web/main.py lifespan; these endpoints are read-only
pass-throughs.  All errors are caught and returned as JSON so the frontend
degrades gracefully instead of 500-ing.
"""
from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, Query
from utils.logger import get_logger

logger = get_logger("web.api.spot_basis_api")

router = APIRouter(prefix="/api/v1/kalshi", tags=["spot-basis"])


# ── Helpers ────────────────────────────────────────────────────────────────────


def _get_tracker():
    """Lazy accessor — avoids import at module level (no circular risk)."""
    from merid.alignment import get_spot_basis_tracker
    return get_spot_basis_tracker()


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get("/spot-basis")
async def get_spot_basis() -> Dict[str, Any]:
    """Current spot/Kalshi basis state for all 5 crypto assets.

    Response shape::

        {
          "timestamp": 1744800000.0,
          "assets": {
            "BTC": {
              "asset": "BTC",
              "spot_price": 84231.5,
              "spot_status": "ok",            // ok | stale | missing
              "kalshi_book_status": "ok",     // ok | stale | missing
              "implied_spot_mid": 84180.0,    // null when unavailable
              "implied_spot_bid": 84120.0,
              "implied_spot_ask": 84240.0,
              "basis_mid": -51.5,             // null when unavailable
              "basis_bid": -111.5,
              "basis_ask": 8.5,
              "alignment": "aligned",         // aligned | offside | stale_feed
              "breach_count": 0,
              "markets_used": 4,
              "nearest_expiry_secs": 1800.0,  // null when unavailable
              "computed_at": 123456.789       // monotonic clock
            },
            "ETH": { ... },
            ...
          }
        }
    """
    try:
        tracker = _get_tracker()
        all_basis = tracker.get_all()
        return {
            "timestamp": time.time(),
            "assets": {asset: ab.to_dict() for asset, ab in all_basis.items()},
        }
    except Exception as exc:
        logger.exception("spot-basis endpoint error")
        return {
            "timestamp": time.time(),
            "error": str(exc),
            "assets": {},
        }


@router.get("/spot-basis/stats")
async def get_spot_basis_stats(
    window_minutes: int = Query(default=60, ge=1, le=1440, description="Rolling window in minutes"),
) -> Dict[str, Any]:
    """Rolling basis statistics for all 5 assets over the last N minutes (default: 60).

    Response shape::

        {
          "timestamp": 1744800000.0,
          "window_minutes": 60,
          "assets": {
            "BTC": {
              "basis_mean": -8.2,       // null if no samples
              "basis_median": -5.1,
              "basis_p5": -42.3,
              "basis_p95": 35.7,
              "sample_count": 3420,
              "offside_pct": 2.1        // % of samples where |basis| > threshold
            },
            ...
          }
        }
    """
    try:
        tracker = _get_tracker()
        stats = tracker.get_stats(window_seconds=window_minutes * 60)
        return {
            "timestamp": time.time(),
            "window_minutes": window_minutes,
            "assets": stats,
        }
    except Exception as exc:
        logger.exception("spot-basis/stats endpoint error")
        return {
            "timestamp": time.time(),
            "window_minutes": window_minutes,
            "error": str(exc),
            "assets": {},
        }
