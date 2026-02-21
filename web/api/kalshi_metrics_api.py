"""Kalshi Forecaster Metrics API — /api/v1/kalshi/metrics/*

Exposes Brier calibration scores, realized edge stats, and outcome
resolver status for each forecaster agent.

Endpoints:
  GET  /api/v1/kalshi/metrics/forecasters         — All forecasters with Brier + edge stats
  GET  /api/v1/kalshi/metrics/forecaster/{id}      — Detailed breakdown for one forecaster
  GET  /api/v1/kalshi/metrics/markets/{market_id}  — Forecasts + trades for a specific market
  GET  /api/v1/kalshi/metrics/resolver             — Outcome resolver status
  POST /api/v1/kalshi/metrics/resolve              — Manually resolve a market outcome
  POST /api/v1/kalshi/metrics/resolve-all          — Trigger a full resolution pass
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from utils.logger import get_logger

logger = get_logger("web.api.kalshi_metrics_api")

router = APIRouter(prefix="/api/v1/kalshi/metrics", tags=["kalshi-metrics"])


# ── Request models ───────────────────────────────────────────────────────

class ManualResolveRequest(BaseModel):
    market_id: str
    outcome: int  # 1 = YES, 0 = NO


# ── GET /forecasters — All forecasters with combined stats ───────────────

@router.get("/forecasters")
async def get_all_forecasters() -> Dict[str, Any]:
    """List all forecasters with their Brier calibration and realized edge stats."""
    try:
        from merid.metrics.calibration import get_calibration_store
        from merid.metrics.realized_edge import get_realized_edge_store

        cal = get_calibration_store()
        edge = get_realized_edge_store()

        forecaster_ids = set(cal.list_forecasters())
        # Also include forecasters that only have edge data
        for es in edge.get_all_edge_stats():
            forecaster_ids.add(es.forecaster_id)

        results = []
        for fid in sorted(forecaster_ids):
            brier_stats = [s.to_dict() for s in cal.get_all_forecaster_stats()
                           if s.forecaster_id == fid]
            edge_stats = [s.to_dict() for s in edge.get_all_edge_stats()
                          if s.forecaster_id == fid]

            # Compute aggregate Brier across buckets
            total_resolved = sum(s.get("resolved_count", 0) for s in brier_stats)
            avg_brier = 0.25
            if total_resolved > 0:
                weighted = sum(
                    s.get("ewma_brier", 0.25) * s.get("resolved_count", 0)
                    for s in brier_stats
                )
                avg_brier = weighted / total_resolved

            # Compute aggregate edge stats
            total_pnl = sum(s.get("sum_pnl_cents", 0) for s in edge_stats)
            total_trades = sum(s.get("trade_count", 0) for s in edge_stats)
            total_resolved_trades = sum(s.get("resolved_count", 0) for s in edge_stats)

            # Get consensus weight (use first bucket or average)
            weight = 1.0
            if brier_stats:
                bucket = brier_stats[0].get("bucket", "unknown")
                weight = cal.get_weight(fid, bucket)

            results.append({
                "forecaster_id": fid,
                "avg_ewma_brier": round(avg_brier, 6),
                "total_forecasts_resolved": total_resolved,
                "consensus_weight": round(weight, 4),
                "total_trades": total_trades,
                "total_trades_resolved": total_resolved_trades,
                "total_pnl_cents": total_pnl,
                "brier_by_bucket": {s["bucket"]: s for s in brier_stats},
                "edge_by_bucket": {s["bucket"]: s for s in edge_stats},
            })

        return {
            "forecasters": results,
            "count": len(results),
        }

    except Exception as exc:
        logger.warning(f"Error fetching forecaster metrics: {exc}")
        return {"forecasters": [], "count": 0, "error": str(exc)}


# ── GET /forecaster/{id} — Detailed breakdown for one forecaster ─────────

@router.get("/forecaster/{forecaster_id}")
async def get_forecaster_detail(forecaster_id: str) -> Dict[str, Any]:
    """Detailed calibration and edge breakdown for a single forecaster."""
    try:
        from merid.metrics.calibration import get_calibration_store
        from merid.metrics.realized_edge import get_realized_edge_store

        cal = get_calibration_store()
        edge = get_realized_edge_store()

        cal_summary = cal.get_forecaster_summary(forecaster_id)
        edge_stats = [
            s.to_dict() for s in edge.get_all_edge_stats()
            if s.forecaster_id == forecaster_id
        ]

        # Compute per-bucket weights
        bucket_weights = {}
        for bucket_name, bucket_data in cal_summary.get("buckets", {}).items():
            bucket_weights[bucket_name] = {
                "weight": round(cal.get_weight(forecaster_id, bucket_name), 4),
                "brier": bucket_data,
            }

        return {
            "forecaster_id": forecaster_id,
            "calibration": cal_summary,
            "edge_stats": edge_stats,
            "bucket_weights": bucket_weights,
        }

    except Exception as exc:
        logger.warning(f"Error fetching forecaster {forecaster_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /markets/{market_id} — Forecasts + trades for a market ───────────

@router.get("/markets/{market_id}")
async def get_market_metrics(market_id: str) -> Dict[str, Any]:
    """Get all forecasts and trade edge records for a specific market."""
    try:
        from merid.metrics.calibration import get_calibration_store
        from merid.metrics.realized_edge import get_realized_edge_store

        cal = get_calibration_store()
        edge = get_realized_edge_store()

        forecasts = [f.to_dict() for f in cal.get_forecasts_for_market(market_id)]
        trades = [t.to_dict() for t in edge.get_trades_for_market(market_id)]

        return {
            "market_id": market_id,
            "forecasts": forecasts,
            "forecast_count": len(forecasts),
            "trades": trades,
            "trade_count": len(trades),
        }

    except Exception as exc:
        logger.warning(f"Error fetching market metrics for {market_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /resolver — Outcome resolver status ──────────────────────────────

@router.get("/resolver")
async def get_resolver_status() -> Dict[str, Any]:
    """Get the outcome resolver's status and pending market counts."""
    try:
        from merid.metrics.outcome_resolver import get_outcome_resolver
        resolver = get_outcome_resolver()
        return resolver.status()
    except Exception as exc:
        logger.warning(f"Error fetching resolver status: {exc}")
        return {"error": str(exc)}


# ── POST /resolve — Manually resolve a market ────────────────────────────

@router.post("/resolve")
async def resolve_market(req: ManualResolveRequest) -> Dict[str, Any]:
    """Manually resolve a market outcome (useful for paper/sim modes).

    Body:
        market_id: Kalshi market ticker.
        outcome: 1 for YES, 0 for NO.
    """
    if req.outcome not in (0, 1):
        raise HTTPException(status_code=400, detail="outcome must be 0 or 1")

    try:
        from merid.metrics.outcome_resolver import get_outcome_resolver
        resolver = get_outcome_resolver()
        result = resolver.resolve_manual(req.market_id, req.outcome)
        return result.to_dict()
    except Exception as exc:
        logger.warning(f"Error resolving market {req.market_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /resolve-all — Trigger full resolution pass ─────────────────────

@router.post("/resolve-all")
async def resolve_all_markets() -> Dict[str, Any]:
    """Trigger a full resolution pass across all unresolved markets."""
    try:
        from merid.metrics.outcome_resolver import get_outcome_resolver
        resolver = get_outcome_resolver()
        results = await resolver.resolve_all()
        resolved_count = sum(1 for r in results if r.resolved)
        return {
            "checked": len(results),
            "resolved": resolved_count,
            "pending": len(results) - resolved_count,
            "results": [r.to_dict() for r in results[:50]],  # cap output
        }
    except Exception as exc:
        logger.warning(f"Error in resolve-all: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
