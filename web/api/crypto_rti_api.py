"""
MERID RTI API — Internal Real-Time Index for spot price reference.

Exposes unified_spot_service as a CFB RTI-equivalent endpoint for UnifiedEdgeComputer.

Provides:
  GET /api/v1/rti/{asset}
    Per-asset (BTC, ETH, SOL, XRP, DOGE):
      - index_price: current spot price
      - timestamp: price timestamp (ms)
      - num_exchanges: number of venues contributing (currently 1 for Coinbase)
      - staleness_ms: age of price in milliseconds
      - data_quality_score: confidence score (0-1)

This replaces CFB RTI dependency with internal multi-venue aggregation.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/rti", tags=["crypto-rti"])

# Supported assets (must match unified_spot_service.SUPPORTED_ASSETS)
SUPPORTED_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]


@router.get("/{asset}")
async def get_rti_spot(asset: str) -> Dict[str, Any]:
    """Get RTI spot price for an asset.

    Returns a CFB RTI-equivalent response structure for UnifiedEdgeComputer.

    Args:
        asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)

    Returns:
        Dict with:
            - asset: normalized asset symbol
            - index_price: current spot price
            - timestamp: price timestamp (milliseconds)
            - num_exchanges: number of venues (currently 1 for Coinbase)
            - staleness_ms: age of price in milliseconds
            - data_quality_score: confidence score (0-1)

    Raises:
        HTTPException 404: if asset not supported or spot unavailable
    """
    asset_upper = asset.upper()

    if asset_upper not in SUPPORTED_ASSETS:
        raise HTTPException(
            status_code=404,
            detail=f"Unsupported asset: {asset}. Supported: {SUPPORTED_ASSETS}"
        )

    try:
        from data.unified_spot_service import get_unified_spot_service

        spot_service = get_unified_spot_service()
        spot = spot_service.get(asset_upper)

        if spot is None:
            raise HTTPException(
                status_code=503,
                detail=f"Spot price unavailable for {asset_upper} - service may be warming up"
            )

        now_ms = int(time.time() * 1000)
        staleness_ms = now_ms - spot.timestamp

        # Currently unified_spot_service uses Coinbase only (single venue)
        # Future: wire to crypto_spot_service for multi-venue aggregation
        num_exchanges = 1
        data_quality_score = spot.confidence

        return {
            "asset": asset_upper,
            "index_price": spot.price,
            "timestamp": spot.timestamp,
            "num_exchanges": num_exchanges,
            "staleness_ms": staleness_ms,
            "data_quality_score": data_quality_score,
        }

    except Exception as exc:
        logger.error("[RTI-API] Failed to get spot for %s: %s", asset_upper, exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal error fetching spot for {asset_upper}: {exc}"
        )


@router.get("/health")
async def rti_health() -> Dict[str, Any]:
    """Get RTI service health status.

    Returns per-asset cache status from unified_spot_service.
    """
    try:
        from data.unified_spot_service import get_unified_spot_service

        spot_service = get_unified_spot_service()
        health = spot_service.health_check()

        return {
            "status": "healthy" if health["running"] else "stopped",
            "supported_assets": SUPPORTED_ASSETS,
            "cache_status": health["cache_status"],
            "cached_count": health["cached_count"],
            "stale_count": health["stale_count"],
        }
    except Exception as exc:
        logger.error("[RTI-API] Health check failed: %s", exc, exc_info=True)
        return {
            "status": "error",
            "error": str(exc),
            "supported_assets": SUPPORTED_ASSETS,
        }
