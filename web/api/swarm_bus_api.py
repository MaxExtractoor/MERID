"""Swarm Bus API — /api/v1/kalshi/swarm/*

Exposes critic history, edge recalibration status, and execution
subscriber stats for the CalibrationDashboardView (Sprint M).

Endpoints:
  GET  /api/v1/kalshi/swarm/critic/history     — Recent critique messages
  GET  /api/v1/kalshi/swarm/recalibration      — Edge recalibration status
  GET  /api/v1/kalshi/swarm/execution/stats     — Execution subscriber stats
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter

from utils.logger import get_logger

logger = get_logger("web.api.swarm_bus_api")

router = APIRouter(
    prefix="/api/v1/kalshi/swarm",
    tags=["kalshi-swarm-bus"],
)


@router.get("/critic/history")
async def get_critic_history() -> Dict[str, Any]:
    """Return recent critique messages from the CriticAgent."""
    try:
        from merid.swarm.critic_agent import get_critic_agent
        agent = get_critic_agent()
        return {
            "critiques": agent.history[-50:],
            "count": len(agent.history),
        }
    except Exception as exc:
        logger.debug(f"Critic history unavailable: {exc}")
        return {"critiques": [], "count": 0, "error": str(exc)}


@router.get("/recalibration")
async def get_recalibration_status() -> Dict[str, Any]:
    """Return edge recalibration history and current status."""
    try:
        from merid.prediction.edge_recalibrator import get_edge_recalibrator
        recal = get_edge_recalibrator()
        latest = recal.latest
        return {
            "latest": latest.to_dict() if latest else None,
            "history": [r.to_dict() for r in recal.history[-20:]],
            "history_count": len(recal.history),
        }
    except Exception as exc:
        logger.debug(f"Recalibration status unavailable: {exc}")
        return {"latest": None, "history": [], "history_count": 0, "error": str(exc)}


@router.get("/execution/stats")
async def get_execution_stats() -> Dict[str, Any]:
    """Return execution subscriber stats and recent routing history."""
    try:
        from merid.swarm.execution_subscriber import get_execution_subscriber
        sub = get_execution_subscriber()
        return {
            "stats": sub.stats,
            "history": sub.history[-30:],
        }
    except Exception as exc:
        logger.debug(f"Execution stats unavailable: {exc}")
        return {"stats": {}, "history": [], "error": str(exc)}
