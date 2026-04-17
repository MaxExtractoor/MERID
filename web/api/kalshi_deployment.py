"""Kalshi Deployment Controller API — paper/shadow/live promotion and rollback.

Endpoints:
  GET  /api/v1/kalshi/deployment/status          — full deployment status
  POST /api/v1/kalshi/deployment/promote-shadow  — promote agent to SHADOW
  POST /api/v1/kalshi/deployment/promote-live    — promote agent to LIVE
  POST /api/v1/kalshi/deployment/rollback        — rollback agent to PAPER
  POST /api/v1/kalshi/deployment/halt            — halt agent (no orders)
  GET  /api/v1/kalshi/deployment/transitions     — recent transition audit log
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger("web.api.kalshi_deployment")

router = APIRouter(prefix="/api/v1/kalshi/deployment", tags=["kalshi-deployment"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


# ── Request models ─────────────────────────────────────────────────────

class AgentActionRequest(BaseModel):
    agent_name: str
    reason: Optional[str] = "api"
    readiness: Optional[Dict[str, Any]] = None


# ── Endpoints ──────────────────────────────────────────────────────────

@router.get("/status")
async def get_deployment_status() -> Dict[str, Any]:
    """Full deployment status for all registered agents.

    Returns the deployment dict directly so the frontend can consume it
    as ``DeploymentStatus`` without unwrapping.
    """
    try:
        from merid.event_venues.kalshi.deployment import get_deployment_controller
        dc = get_deployment_controller()
        return dc.status()
    except Exception as exc:
        logger.error("deployment status error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/promote-shadow")
async def promote_to_shadow(request: AgentActionRequest) -> Dict[str, Any]:
    """Promote an agent from PAPER to SHADOW mode.

    Shadow mode runs real live orders alongside parallel paper tracking
    for side-by-side comparison before full live promotion.
    """
    try:
        from merid.event_venues.kalshi.deployment import get_deployment_controller
        dc = get_deployment_controller()
        ok, reason = dc.promote_to_shadow(request.agent_name, readiness=request.readiness)
        if not ok:
            raise HTTPException(status_code=400, detail=reason)
        return {"status": "ok", "agent": request.agent_name, "mode": "SHADOW", "reason": reason}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("promote_to_shadow error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/promote-live")
async def promote_to_live(request: AgentActionRequest) -> Dict[str, Any]:
    """Promote an agent to full LIVE mode.

    Requires passing readiness gates (min paper trades, profit factor,
    drawdown, error rate) unless readiness check is disabled in config.
    """
    try:
        from merid.event_venues.kalshi.deployment import get_deployment_controller
        dc = get_deployment_controller()
        ok, reason = dc.promote_to_live(request.agent_name, readiness=request.readiness)
        if not ok:
            raise HTTPException(status_code=400, detail=reason)

        # Reload VenueGate so the order path knows live is now active
        try:
            from merid.prediction.venue_gate import get_venue_gate
            get_venue_gate().reload()
        except Exception as _vge:
            logger.debug("VenueGate reload after promote-live: %s", _vge)

        return {"status": "ok", "agent": request.agent_name, "mode": "LIVE", "reason": reason}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("promote_to_live error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/rollback")
async def rollback_agent(request: AgentActionRequest) -> Dict[str, Any]:
    """Rollback an agent from LIVE/SHADOW back to PAPER mode."""
    try:
        from merid.event_venues.kalshi.deployment import get_deployment_controller
        dc = get_deployment_controller()
        ok, reason = dc.rollback(request.agent_name, reason=request.reason or "api")
        if not ok:
            raise HTTPException(status_code=400, detail=reason)
        return {"status": "ok", "agent": request.agent_name, "mode": "PAPER", "reason": reason}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("rollback error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/halt")
async def halt_agent(request: AgentActionRequest) -> Dict[str, Any]:
    """Halt an agent — no orders until explicitly re-promoted."""
    try:
        from merid.event_venues.kalshi.deployment import get_deployment_controller
        dc = get_deployment_controller()
        ok, reason = dc.halt(request.agent_name, reason=request.reason or "api")
        if not ok:
            raise HTTPException(status_code=400, detail=reason)
        return {"status": "ok", "agent": request.agent_name, "mode": "HALTED", "reason": reason}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("halt error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/transitions")
async def get_transition_log(limit: int = 20) -> Dict[str, Any]:
    """Recent deployment transition audit log."""
    try:
        from merid.event_venues.kalshi.deployment import get_deployment_controller
        dc = get_deployment_controller()
        log = dc.transition_log[-limit:]
        return {"status": "ok", "transitions": log, "total": len(dc.transition_log)}
    except Exception as exc:
        logger.error("transition log error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
