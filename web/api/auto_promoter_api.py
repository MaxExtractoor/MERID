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
        return {
            "count": len(evaluations[:limit]),
            "evaluations": evaluations[:limit],
            "total_promotions": status.get("total_promotions", 0),
        }
    except Exception as exc:
        logger.error("Auto-promoter promotions failed: %s", exc)
        return {"count": 0, "evaluations": [], "error": str(exc)}
