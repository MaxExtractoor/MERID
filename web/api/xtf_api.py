"""Cross-Timeframe Aggregator API.

Endpoints:
  GET  /api/v1/xtf/signals         — All aggregated cross-timeframe signals
  GET  /api/v1/xtf/signal/{asset}  — Single asset cross-timeframe signal
  GET  /api/v1/xtf/status          — Aggregator status
  POST /api/v1/xtf/sync            — Pull latest data from sentiment bus + consensus
"""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from utils.logger import get_logger

logger = get_logger("web.api.xtf_api")

router = APIRouter(prefix="/api/v1/xtf", tags=["cross-timeframe"])


def _get_aggregator():
    from merid.sentiment.cross_timeframe_aggregator import get_cross_timeframe_aggregator
    return get_cross_timeframe_aggregator()


@router.get("/signals")
async def get_all_signals() -> Dict[str, Any]:
    """Get cross-timeframe signals for all tracked assets."""
    try:
        agg = _get_aggregator()
        results = agg.aggregate_all()
        return {
            asset: sig.to_dict()
            for asset, sig in results.items()
        }
    except Exception as exc:
        logger.error("XTF signals fetch failed: %s", exc)
        return {"error": str(exc)}


@router.get("/signal/{asset}")
async def get_signal(asset: str) -> Dict[str, Any]:
    """Get cross-timeframe signal for a single asset."""
    try:
        agg = _get_aggregator()
        result = agg.aggregate(asset)
        return result.to_dict()
    except Exception as exc:
        logger.error("XTF signal fetch failed for %s: %s", asset, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/status")
async def get_status() -> Dict[str, Any]:
    """Get aggregator runtime status."""
    try:
        agg = _get_aggregator()
        return agg.status()
    except Exception as exc:
        logger.error("XTF status failed: %s", exc)
        return {"error": str(exc)}


@router.post("/sync")
async def sync_signals() -> Dict[str, Any]:
    """Pull latest signals from SentimentBusV2 and SwarmConsensusAggregator."""
    try:
        agg = _get_aggregator()
        sentiment_count = agg.sync_from_sentiment_bus()
        consensus_count = agg.sync_from_consensus()
        return {
            "synced": True,
            "sentiment_assets": sentiment_count,
            "consensus_views": consensus_count,
        }
    except Exception as exc:
        logger.error("XTF sync failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
