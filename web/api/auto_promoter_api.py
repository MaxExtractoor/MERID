"""Auto-Promoter API.

Endpoints:
  GET /api/v1/kalshi/deployment/auto-promoter/status     — Current auto-promoter status
  GET /api/v1/kalshi/deployment/auto-promoter/promotions  — Recent promotion evaluations
"""

from typing import Any, Dict

from fastapi import APIRouter, Query

from utils.logger import get_logger

logger = get_logger("web.api.auto_promoter_api")

router = APIRouter(
    prefix="/api/v1/kalshi/deployment/auto-promoter",
    tags=["auto-promoter"],
)


def _get_promoter():
    from merid.event_venues.kalshi.auto_promoter import get_auto_promoter
    return get_auto_promoter()


@router.get("/status")
async def get_auto_promoter_status() -> Dict[str, Any]:
    """Get auto-promoter runtime status."""
    try:
        promoter = _get_promoter()
        return promoter.status()
    except Exception as exc:
        logger.error("Auto-promoter status failed: %s", exc)
        return {
            "running": False,
            "eval_interval_seconds": 0,
            "eval_count": 0,
            "last_eval_ago_seconds": None,
            "total_promotions": 0,
            "recent_evaluations": [],
            "error": str(exc),
        }


@router.get("/promotions")
async def get_recent_promotions(
    limit: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    """Get recent promotion evaluations with gate details."""
    try:
        promoter = _get_promoter()
        status = promoter.status()
        evaluations = status.get("recent_evaluations", [])
        promotions = []
        for evaluation in evaluations[:limit]:
            from_phase = evaluation.get("from_phase", "?")
            to_phase = evaluation.get("to_phase", "?")
            promotions.append({
                "id": evaluation.get("timestamp"),
                "agent": evaluation.get("agent"),
                "ticker": evaluation.get("agent"),
                "direction": f"{from_phase}→{to_phase}",
                "verdict": "promote" if evaluation.get("promoted") else "hold",
                "timestamp": evaluation.get("timestamp"),
                "blocked_by": evaluation.get("blocked_by"),
                "gates": evaluation.get("gates", []),
            })
        return {
            "count": len(evaluations[:limit]),
            "evaluations": evaluations[:limit],
            "promotions": promotions,
            "total_promotions": status.get("total_promotions", 0),
        }
    except Exception as exc:
        logger.error("Auto-promoter promotions failed: %s", exc)
        return {"count": 0, "evaluations": [], "promotions": [], "error": str(exc)}
