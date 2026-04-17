"""Operator API endpoints for MERID guard and promotion management."""

from __future__ import annotations

import asyncio
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks

from auth.user_manager import require_role
from web.api.auth import get_current_session
from utils.logger import get_logger
from merid.promotion_report import (
    get_cached_promotion_report, 
    get_effective_domain_status,
    get_effective_agent_status
)

logger = get_logger("merid.operator_api")

router = APIRouter(prefix="/api/operator", tags=["operator"], dependencies=[Depends(get_current_session)])  # ZT6-01


def _get_execution_guard():
    """Get execution guard if available, return None for Kalshi-only mode."""
    try:
        from merid.execution_guard import get_execution_guard
        return get_execution_guard()
    except ImportError:
        # Execution guard not available in Kalshi-only mode
        return None


@router.post("/guard/kill-switch/on")
async def activate_kill_switch(reason: str = "manual", _user=Depends(require_role("operator", "admin"))):
    """Activate the global kill switch to block all execution."""
    try:
        guard = _get_execution_guard()
        if guard is None:
            # Use Kalshi-specific kill switch instead
            from merid.risk.kill_switches import risk_controller
            risk_controller.emergency_stop(reason)
            logger.warning(f"Kalshi kill switch activated via API: {reason}")
            return {"status": "activated", "reason": reason, "type": "kalshi"}
        
        guard.activate_kill_switch(reason)
        logger.warning(f"Kill switch activated via API: {reason}")
        return {"status": "activated", "reason": reason, "type": "generic"}
    except Exception as e:
        logger.error(f"Failed to activate kill switch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/guard/kill-switch/off")
async def deactivate_kill_switch(_user=Depends(require_role("operator", "admin"))):
    """Deactivate the global kill switch to re-enable execution."""
    try:
        guard = _get_execution_guard()
        if guard is None:
            # Use Kalshi-specific kill switch instead
            from merid.risk.kill_switches import risk_controller
            risk_controller.reset()
            logger.info("Kalshi kill switch deactivated via API")
            return {"status": "deactivated", "type": "kalshi"}
        
        guard.deactivate_kill_switch()
        # ALSO reset RiskController since pre_trade_check checks both
        from merid.risk.kill_switches import risk_controller
        risk_controller.reset()
        logger.info("Kill switch deactivated via API (both ExecutionGuard and RiskController)")
        return {"status": "deactivated", "type": "generic"}
    except Exception as e:
        logger.error(f"Failed to deactivate kill switch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/promotion-report/refresh")
async def refresh_promotion_report(background_tasks: BackgroundTasks):
    """Refresh the promotion report cache and sync with execution guard."""
    try:
        # Run in background to avoid blocking the API
        async def _refresh():
            try:
                guard = _get_execution_guard()
                if guard is None:
                    logger.debug("Execution guard unavailable for promotion refresh")
                    return
                guard.sync_promotion_report()
                logger.info("Promotion report refreshed via API")
            except Exception as e:
                logger.error(f"Background promotion refresh failed: {e}")
        
        background_tasks.add_task(_refresh)
        return {"status": "refreshing", "message": "Promotion report refresh started"}
    except Exception as e:
        logger.error(f"Failed to start promotion refresh: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/guard/status")
async def get_guard_status():
    """Get current execution guard status including caps and promotion sync."""
    try:
        guard = _get_execution_guard()
        if guard is None:
            raise HTTPException(status_code=503, detail="Execution guard unavailable")
        return {
            "guard_status": guard.summary(),
            "promotion_sync": {
                "last_sync": getattr(guard, '_promotion_report_ts', 0.0),
                "eligible_domains": list(getattr(guard, '_promotion_eligible_domains', []) or []),
                "blocked_agents": list(getattr(guard, '_promotion_blocked_agents', []) or []),
            }
        }
    except Exception as e:
        logger.error(f"Failed to get guard status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/promotion-report")
async def get_promotion_report():
    """Get the current promotion report."""
    try:
        report = get_cached_promotion_report(gauntlet_cycles=5)
        return report.to_dict()
    except Exception as e:
        logger.error(f"Failed to get promotion report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/domain/{domain}/status")
async def get_domain_status(domain: str):
    """Get effective status for a specific domain."""
    try:
        status = get_effective_domain_status(domain)
        return {"domain": domain, "status": status}
    except Exception as e:
        logger.error(f"Failed to get domain status for {domain}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agent/{agent_id}/status")
async def get_agent_status(agent_id: str):
    """Get effective status for a specific agent."""
    try:
        status = get_effective_agent_status(agent_id)
        return {"agent_id": agent_id, "status": status}
    except Exception as e:
        logger.error(f"Failed to get agent status for {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/domain/{domain}/promote")
async def promote_domain(domain: str, reason: str = "manual promotion", _user=Depends(require_role("operator", "admin"))):
    """Promote a domain to eligible status."""
    try:
        from merid.promotion_report import get_promotion_log
        log = get_promotion_log()
        log.manual_promote("domain", domain, reason)
        logger.info(f"Domain {domain} promoted via API: {reason}")
        return {"domain": domain, "status": "promoted", "reason": reason}
    except Exception as e:
        logger.error(f"Failed to promote domain {domain}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/domain/{domain}/demote")
async def demote_domain(domain: str, reason: str = "manual demotion", _user=Depends(require_role("operator", "admin"))):
    """Demote a domain to blocked status."""
    try:
        from merid.promotion_report import get_promotion_log
        log = get_promotion_log()
        log.manual_demote("domain", domain, reason)
        logger.info(f"Domain {domain} demoted via API: {reason}")
        return {"domain": domain, "status": "demoted", "reason": reason}
    except Exception as e:
        logger.error(f"Failed to demote domain {domain}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agent/{agent_id}/promote")
async def promote_agent(agent_id: str, reason: str = "manual promotion", _user=Depends(require_role("operator", "admin"))):
    """Promote an agent to eligible status."""
    try:
        from merid.promotion_report import get_promotion_log
        log = get_promotion_log()
        log.manual_promote("agent", agent_id, reason)
        logger.info(f"Agent {agent_id} promoted via API: {reason}")
        return {"agent_id": agent_id, "status": "promoted", "reason": reason}
    except Exception as e:
        logger.error(f"Failed to promote agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agent/{agent_id}/demote")
async def demote_agent(agent_id: str, reason: str = "manual demotion", _user=Depends(require_role("operator", "admin"))):
    """Demote an agent to blocked status."""
    try:
        from merid.promotion_report import get_promotion_log
        log = get_promotion_log()
        log.manual_demote("agent", agent_id, reason)
        logger.info(f"Agent {agent_id} demoted via API: {reason}")
        return {"agent_id": agent_id, "status": "demoted", "reason": reason}
    except Exception as e:
        logger.error(f"Failed to demote agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
