"""Correlation Risk API — /api/v1/kalshi/correlation/*

Exposes inter-asset correlation matrix, exposure reduction factors,
and cluster health for the portfolio risk layer (Sprint D).

Endpoints:
  GET  /api/v1/kalshi/correlation/matrix    — Full correlation matrix
  GET  /api/v1/kalshi/correlation/factor     — Reduction factor for a pair
  GET  /api/v1/kalshi/correlation/clusters   — Cluster definitions + utilization
  POST /api/v1/kalshi/correlation/record     — Record a return observation
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger("web.api.correlation_api")

router = APIRouter(prefix="/api/v1/kalshi/correlation", tags=["kalshi-correlation"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


class RecordReturnRequest(BaseModel):
    asset: str
    ret: float
    timestamp: Optional[float] = None


@router.get("/matrix")
async def get_correlation_matrix() -> Dict[str, Any]:
    """Get the full inter-asset correlation matrix."""
    from merid.risk.correlation import get_correlation_tracker
    tracker = get_correlation_tracker()
    matrix = tracker.get_matrix()
    return {
        "status": "ok",
        "matrix": matrix.to_dict(),
        "tracked_assets": tracker.tracked_assets,
    }


@router.get("/factor")
async def get_reduction_factor(
    asset_a: str = Query(..., description="First asset"),
    asset_b: str = Query(..., description="Second asset"),
) -> Dict[str, Any]:
    """Get the exposure reduction factor for a pair of assets."""
    from merid.risk.correlation import get_correlation_tracker
    tracker = get_correlation_tracker()
    corr = tracker.get_correlation(asset_a, asset_b)
    factor = tracker.exposure_reduction_factor(asset_a, asset_b)
    return {
        "asset_a": asset_a.upper(),
        "asset_b": asset_b.upper(),
        "correlation": round(corr, 4),
        "reduction_factor": round(factor, 4),
        "interpretation": (
            "no_reduction" if factor >= 0.99
            else "mild_reduction" if factor >= 0.7
            else "significant_reduction" if factor >= 0.5
            else "severe_reduction"
        ),
    }


@router.get("/clusters")
async def get_clusters() -> Dict[str, Any]:
    """Get asset cluster definitions and current correlation factors."""
    from merid.risk.correlation import get_correlation_tracker, ASSET_CLUSTERS
    tracker = get_correlation_tracker()
    clusters = []
    for name, members in ASSET_CLUSTERS.items():
        pairs = []
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                corr = tracker.get_correlation(a, b)
                factor = tracker.exposure_reduction_factor(a, b)
                pairs.append({
                    "asset_a": a,
                    "asset_b": b,
                    "correlation": round(corr, 4),
                    "reduction_factor": round(factor, 4),
                })
        clusters.append({
            "cluster_name": name,
            "members": members,
            "pairs": pairs,
        })
    return {"status": "ok", "clusters": clusters}


@router.post("/record")
async def record_return(req: RecordReturnRequest) -> Dict[str, Any]:
    """Record a return observation for an asset."""
    from merid.risk.correlation import get_correlation_tracker
    tracker = get_correlation_tracker()
    tracker.record_return(req.asset, req.ret, req.timestamp)
    return {
        "status": "ok",
        "asset": req.asset.upper(),
        "tracked_assets": tracker.tracked_assets,
    }
