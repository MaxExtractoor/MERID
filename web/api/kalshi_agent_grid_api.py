"""
Kalshi Agent Grid API endpoints.

Provides manual control over the Kalshi trading agent grid lifecycle.
"""

from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Query

from merid.prediction.agent_grid_15m import get_agent_grid
from utils.logger import get_logger

logger = get_logger("web.api.kalshi_agent_grid_api")

router = APIRouter(prefix="/api/v1/kalshi-grid", tags=["Kalshi Agent Grid"])

# NOTE: /start, /stop, /status, /pause, /resume, /matrix, /agents, /fills, /pnl,
# /portfolio, /session, /kill-switch/reset, /health are all handled by kalshi_grid_api.py.
# This file adds /summary (grid.summary() wrapper) and edge telemetry endpoints.


@router.get("/summary")
async def get_grid_summary() -> Dict[str, Any]:
    """Get high-level summary of agent grid."""
    try:
        grid = get_agent_grid()
        summary = grid.summary()
        
        return {
            "running": grid.is_running,
            "agent_count": len(grid.agents),
            "summary": summary,
        }
        
    except Exception as e:
        logger.error(f"Failed to get grid summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get summary: {str(e)}")


@router.get("/edge-snapshots")
async def get_edge_snapshots(
    asset: str = Query(..., description="Asset ticker (e.g., BTC, ETH)"),
    limit: int = Query(100, description="Maximum number of snapshots to return")
) -> Dict[str, Any]:
    """Get recent edge snapshots for an asset.
    
    NOTE: This endpoint is deprecated. Edge snapshots are now tracked
    via RealizedEdgeStore. Use the realized edge endpoints instead.
    """
    return {
        "asset": asset,
        "limit": limit,
        "count": 0,
        "snapshots": [],
        "message": "DEPRECATED: Edge snapshots are now tracked via RealizedEdgeStore. Use realized edge endpoints instead."
    }


@router.get("/scheduler-metrics")
async def get_scheduler_metrics(
    asset: Optional[str] = Query(None, description="Asset ticker (optional, returns aggregate if not provided)")
) -> Dict[str, Any]:
    """Get scheduler metrics for an asset or all assets."""
    try:
        from merid.prediction.agent_grid_15m import get_scheduler_metrics
        
        metrics = get_scheduler_metrics(asset)
        
        return metrics
        
    except Exception as e:
        logger.error(f"Failed to get scheduler metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get scheduler metrics: {str(e)}")


@router.get("/edge-aggregations")
async def get_edge_aggregations(
    asset: str = Query(..., description="Asset ticker (e.g., BTC, ETH)"),
    window_minutes: int = Query(15, description="Time window in minutes")
) -> Dict[str, Any]:
    """Get edge aggregation statistics for an asset over a time window."""
    try:
        from merid.prediction.agent_grid_15m import compute_edge_aggregations
        
        aggregations = compute_edge_aggregations(asset, window_minutes)
        
        return aggregations
        
    except Exception as e:
        logger.error(f"Failed to get edge aggregations for {asset}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get edge aggregations: {str(e)}")


