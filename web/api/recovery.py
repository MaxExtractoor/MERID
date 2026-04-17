"""
Disaster Recovery API Endpoints - Phase 25

Provides API access to disaster recovery, failover, and cold-start capabilities.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from web.api.auth import get_current_session

from recovery import (
    get_disaster_recovery,
    SystemState,
    RecoveryMode,
)
from utils.logger import get_logger

# ZT6-01: All recovery mutation routes require authentication.
router = APIRouter(
    prefix="/api/v1/recovery",
    tags=["recovery"],
    dependencies=[Depends(get_current_session)],
)
logger = get_logger("web.api.recovery")


class SetStateRequest(BaseModel):
    state: str


class FreezeRequest(BaseModel):
    reason: str


class UnfreezeRequest(BaseModel):
    approval_signature: str


class QuarantineAgentRequest(BaseModel):
    agent_id: str
    reason: str


class ReleaseAgentRequest(BaseModel):
    agent_id: str
    approval: Optional[str] = None


class PromoteRequest(BaseModel):
    approval_signature: Optional[str] = None


class CheckAgentHealthRequest(BaseModel):
    agent_id: str
    bad_decisions: int = 0
    consensus_rejections: int = 0
    trust_score: float = 1.0


class DetectAnomalyRequest(BaseModel):
    event_type: str
    value: float
    threshold_key: str
    component: Optional[str] = None


@router.get("/status")
async def get_status() -> Dict[str, Any]:
    """Get disaster recovery status."""
    return get_disaster_recovery().get_status()


@router.post("/state")
async def set_system_state(request: SetStateRequest) -> Dict[str, Any]:
    """Set system state."""
    try:
        state = SystemState(request.state)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid state: {request.state}")
    
    get_disaster_recovery().set_system_state(state)
    return {"status": "updated", "state": state.value}


@router.post("/recovery-point")
async def create_recovery_point() -> Dict[str, Any]:
    """Create a recovery point."""
    point = get_disaster_recovery().create_recovery_point()
    return {"status": "created", "recovery_point": point.to_dict()}


@router.get("/recovery-points")
async def get_recovery_points(limit: int = 10) -> Dict[str, Any]:
    """Get recent recovery points."""
    points = get_disaster_recovery().get_recovery_points(limit)
    return {
        "count": len(points),
        "recovery_points": [p.to_dict() for p in points],
    }


@router.get("/playbooks")
async def get_playbooks() -> Dict[str, Any]:
    """Get available disaster recovery playbooks."""
    dr = get_disaster_recovery()
    return {"playbooks": dr._playbooks}


@router.post("/playbooks/{playbook_name}/execute")
async def execute_playbook(playbook_name: str) -> Dict[str, Any]:
    """Execute a disaster recovery playbook."""
    result = get_disaster_recovery().execute_playbook(playbook_name)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/freeze")
async def freeze_capital(request: FreezeRequest) -> Dict[str, Any]:
    """Freeze all capital operations."""
    get_disaster_recovery().capital_freeze.freeze(request.reason)
    return {"status": "frozen", "reason": request.reason}


@router.post("/unfreeze")
async def unfreeze_capital(request: UnfreezeRequest) -> Dict[str, Any]:
    """Unfreeze capital operations."""
    success = get_disaster_recovery().capital_freeze.unfreeze(request.approval_signature)
    if not success:
        raise HTTPException(status_code=403, detail="Approval signature required")
    return {"status": "unfrozen"}


@router.get("/freeze/status")
async def get_freeze_status() -> Dict[str, Any]:
    """Get capital freeze status."""
    return get_disaster_recovery().capital_freeze.get_status()


@router.post("/anomaly/detect")
async def detect_anomaly(request: DetectAnomalyRequest) -> Dict[str, Any]:
    """Detect and record an anomaly."""
    anomaly = get_disaster_recovery().capital_freeze.detect_anomaly(
        event_type=request.event_type,
        value=request.value,
        threshold_key=request.threshold_key,
        component=request.component,
    )
    if anomaly:
        return {"detected": True, "anomaly": anomaly.to_dict()}
    return {"detected": False}


@router.post("/quarantine")
async def quarantine_agent(request: QuarantineAgentRequest) -> Dict[str, Any]:
    """Quarantine an agent."""
    get_disaster_recovery().agent_quarantine.quarantine_agent(
        agent_id=request.agent_id,
        reason=request.reason,
    )
    return {"status": "quarantined", "agent_id": request.agent_id}


@router.post("/quarantine/release")
async def release_agent(request: ReleaseAgentRequest) -> Dict[str, Any]:
    """Release agent from quarantine."""
    success = get_disaster_recovery().agent_quarantine.release_agent(
        agent_id=request.agent_id,
        approval=request.approval,
    )
    if not success:
        raise HTTPException(status_code=400, detail="Failed to release agent")
    return {"status": "released", "agent_id": request.agent_id}


@router.get("/quarantine/status")
async def get_quarantine_status() -> Dict[str, Any]:
    """Get agent quarantine status."""
    return get_disaster_recovery().agent_quarantine.get_status()


@router.post("/quarantine/check-health")
async def check_agent_health(request: CheckAgentHealthRequest) -> Dict[str, Any]:
    """Check agent health and quarantine if needed."""
    reason = get_disaster_recovery().agent_quarantine.check_agent_health(
        agent_id=request.agent_id,
        bad_decisions=request.bad_decisions,
        consensus_rejections=request.consensus_rejections,
        trust_score=request.trust_score,
    )
    if reason:
        return {"quarantined": True, "reason": reason}
    return {"quarantined": False, "agent_id": request.agent_id}


@router.get("/partial-boot/status")
async def get_partial_boot_status() -> Dict[str, Any]:
    """Get partial boot status."""
    return get_disaster_recovery().partial_boot.get_status()


@router.post("/partial-boot/report-health")
async def report_component_health(
    component_id: str,
    healthy: bool,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """Report component health."""
    get_disaster_recovery().partial_boot.report_health(
        component_id=component_id,
        healthy=healthy,
        error=error,
    )
    return {"status": "reported", "component_id": component_id}


@router.get("/shadow/promotion/status")
async def get_shadow_promotion_status() -> Dict[str, Any]:
    """Get shadow promotion status."""
    return get_disaster_recovery().shadow_promotion.get_status()


@router.post("/shadow/check-eligibility")
async def check_promotion_eligibility(
    shadow_hours: float,
    divergence_pct: float,
    trade_count: int,
) -> Dict[str, Any]:
    """Check if shadow can be promoted to primary."""
    eligible, issues = get_disaster_recovery().shadow_promotion.check_promotion_eligibility(
        shadow_hours=shadow_hours,
        divergence_pct=divergence_pct,
        trade_count=trade_count,
    )
    return {"eligible": eligible, "issues": issues}


@router.post("/shadow/promote")
async def promote_to_primary(request: PromoteRequest) -> Dict[str, Any]:
    """Promote shadow to primary."""
    success = get_disaster_recovery().shadow_promotion.promote_to_primary(
        approval_signature=request.approval_signature,
    )
    if not success:
        raise HTTPException(status_code=403, detail="Manual approval required")
    return {"status": "promoted", "mode": "primary"}


@router.post("/shadow/demote")
async def demote_to_shadow(reason: str) -> Dict[str, Any]:
    """Demote primary back to shadow."""
    get_disaster_recovery().shadow_promotion.demote_to_shadow(reason)
    return {"status": "demoted", "mode": "shadow"}


@router.get("/reconstruction/scan")
async def scan_logs(since_timestamp: Optional[float] = None) -> Dict[str, Any]:
    """Scan logs for reconstructable events."""
    events = get_disaster_recovery().state_reconstructor.scan_logs(since_timestamp)
    return {
        "trades": len(events["trades"]),
        "orders": len(events["orders"]),
        "consensus_blocks": len(events["consensus_blocks"]),
        "agent_decisions": len(events["agent_decisions"]),
        "state_changes": len(events["state_changes"]),
    }


@router.post("/reconstruction/positions")
async def reconstruct_positions() -> Dict[str, Any]:
    """Reconstruct position state from logs."""
    positions = get_disaster_recovery().state_reconstructor.reconstruct_positions()
    return {"status": "completed", "positions": positions}


@router.get("/reconstruction/log")
async def get_reconstruction_log() -> Dict[str, Any]:
    """Get reconstruction activity log."""
    log = get_disaster_recovery().state_reconstructor.get_reconstruction_log()
    return {"log": log}
