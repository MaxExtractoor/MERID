"""
MERID Governance API Endpoints

Exposes constitutional invariants, authority boundaries, and time decay management.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from web.api.auth import get_current_session

from utils.logger import get_logger

# ZT5-01: All governance mutation routes require authentication.
router = APIRouter(
    prefix="/api/v1/governance",
    tags=["governance"],
    dependencies=[Depends(get_current_session)],
)
logger = get_logger("web.api.governance")


class ApprovalRequest(BaseModel):
    """Request for authority approval."""
    requesting_system: str
    action_type: str
    details: Dict[str, Any] = {}


class ApprovalGrant(BaseModel):
    """Grant approval for a request."""
    request_id: str
    approving_system: str
    approver_id: str


class AuthorityGrant(BaseModel):
    """Grant a new timed authority."""
    decay_type: str
    granted_by: str
    initial_value: float = 1.0
    metadata: Dict[str, Any] = {}


class AuthorityRenewal(BaseModel):
    """Renew an authority."""
    authority_id: str
    renewed_by: str


# ═══════════════════════════════════════════════════════════════════
# CONSTITUTIONAL INVARIANTS ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@router.get("/constitutional/status")
async def get_constitutional_status() -> Dict[str, Any]:
    """Get constitutional invariants status."""
    from governance.constitutional import get_constitutional
    
    const = get_constitutional()
    return const.get_status()


@router.get("/constitutional/invariants")
async def get_all_invariants() -> Dict[str, Any]:
    """Get all constitutional invariant values."""
    
    const = get_constitutional()
    return {
        "invariants": const.get_all_invariants(),
        "hash": const.get_invariants_hash(),
    }


@router.get("/constitutional/violations")
async def get_constitutional_violations(limit: int = 100) -> Dict[str, Any]:
    """Get recent constitutional violations."""
    
    const = get_constitutional()
    return {
        "violations": const.get_violations(limit),
        "total": len(const._violations),
    }


@router.get("/constitutional/bypass-attempts")
async def get_bypass_attempts() -> Dict[str, Any]:
    """Get all bypass attempts."""
    
    const = get_constitutional()
    return {
        "attempts": const.get_bypass_attempts(),
        "total": len(const._bypass_attempts),
    }


@router.post("/constitutional/verify")
async def verify_constitutional_integrity() -> Dict[str, Any]:
    """Verify constitutional invariants integrity."""
    
    const = get_constitutional()
    is_valid = const.verify_integrity()
    
    return {
        "integrity_valid": is_valid,
        "current_hash": const._compute_invariants_hash(),
        "expected_hash": const._invariants_hash,
    }


# ═══════════════════════════════════════════════════════════════════
# AUTHORITY BOUNDARY ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@router.get("/authority/status")
async def get_authority_status() -> Dict[str, Any]:
    """Get authority boundary enforcer status."""
    from governance.authority_boundary import get_authority_enforcer
    
    enforcer = get_authority_enforcer()
    return enforcer.get_status()


@router.get("/authority/violations")
async def get_authority_violations(limit: int = 100) -> Dict[str, Any]:
    """Get recent authority boundary violations."""
    
    enforcer = get_authority_enforcer()
    return {
        "violations": enforcer.get_violations(limit),
        "total": len(enforcer._violations),
    }


@router.get("/authority/pending-approvals")
async def get_pending_approvals() -> Dict[str, Any]:
    """Get pending approval requests."""
    
    enforcer = get_authority_enforcer()
    return {
        "pending": enforcer.get_pending_approvals(),
    }


@router.get("/authority/permissions/{system}")
async def get_system_permissions(system: str) -> Dict[str, Any]:
    """Get permissions for a specific system."""
    from governance.authority_boundary import get_authority_enforcer, MeridSystem
    
    try:
        merid_system = MeridSystem(f"MERID-{system.upper()}")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown system: {system}")
    
    enforcer = get_authority_enforcer()
    return {
        "system": merid_system.value,
        "permissions": enforcer.get_system_permissions(merid_system),
    }


@router.post("/authority/request-approval")
async def request_approval(request: ApprovalRequest) -> Dict[str, Any]:
    """Request approval for an action."""
    from governance.authority_boundary import get_authority_enforcer, MeridSystem, ActionType
    
    try:
        requesting_system = MeridSystem(f"MERID-{request.requesting_system.upper()}")
        action_type = ActionType(request.action_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    enforcer = get_authority_enforcer()
    request_id = enforcer.request_approval(
        requesting_system=requesting_system,
        action_type=action_type,
        details=request.details,
    )
    
    return {
        "request_id": request_id,
        "status": "pending",
    }


@router.post("/authority/grant-approval")
async def grant_approval(grant: ApprovalGrant) -> Dict[str, Any]:
    """Grant approval for a pending request."""
    
    try:
        approving_system = MeridSystem(f"MERID-{grant.approving_system.upper()}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    enforcer = get_authority_enforcer()
    success, result = enforcer.grant_approval(
        request_id=grant.request_id,
        approving_system=approving_system,
        approver_id=grant.approver_id,
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=result)
    
    return {
        "approval_id": result,
        "status": "approved",
    }


# ═══════════════════════════════════════════════════════════════════
# TIME DECAY ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@router.get("/decay/status")
async def get_decay_status() -> Dict[str, Any]:
    """Get time decay manager status."""
    from governance.time_decay import get_time_decay_manager
    
    manager = get_time_decay_manager()
    return manager.get_status()


@router.get("/decay/authorities")
async def get_all_authorities(include_disabled: bool = False) -> Dict[str, Any]:
    """Get all timed authorities."""
    
    manager = get_time_decay_manager()
    return {
        "authorities": manager.get_all_authorities(include_disabled),
    }


@router.get("/decay/expiring-soon")
async def get_expiring_soon(threshold_seconds: float = 300) -> Dict[str, Any]:
    """Get authorities expiring soon."""
    
    manager = get_time_decay_manager()
    expiring = manager.get_expiring_soon(threshold_seconds)
    
    return {
        "expiring": [a.to_dict() for a in expiring],
        "threshold_seconds": threshold_seconds,
    }


@router.post("/decay/grant")
async def grant_authority(grant: AuthorityGrant) -> Dict[str, Any]:
    """Grant a new timed authority."""
    from governance.time_decay import get_time_decay_manager, DecayType
    
    try:
        decay_type = DecayType(grant.decay_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown decay type: {grant.decay_type}")
    
    manager = get_time_decay_manager()
    authority = manager.grant_authority(
        decay_type=decay_type,
        granted_by=grant.granted_by,
        initial_value=grant.initial_value,
        metadata=grant.metadata,
    )
    
    return authority.to_dict()


@router.post("/decay/renew")
async def renew_authority(renewal: AuthorityRenewal) -> Dict[str, Any]:
    """Renew an authority."""
    
    manager = get_time_decay_manager()
    success, reason = manager.renew_authority(
        authority_id=renewal.authority_id,
        renewed_by=renewal.renewed_by,
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=reason)
    
    authority = manager.get_authority(renewal.authority_id)
    return authority.to_dict() if authority else {"status": "renewed"}


@router.get("/decay/authority/{authority_id}")
async def check_authority(authority_id: str) -> Dict[str, Any]:
    """Check if an authority is still valid."""
    
    manager = get_time_decay_manager()
    valid, reason, authority = manager.check_authority(authority_id)
    
    return {
        "valid": valid,
        "reason": reason,
        "authority": authority.to_dict() if authority else None,
    }


@router.post("/decay/cleanup")
async def cleanup_expired() -> Dict[str, Any]:
    """Clean up expired authorities."""
    
    manager = get_time_decay_manager()
    cleaned = manager.cleanup_expired()
    
    return {
        "cleaned": cleaned,
    }


# ═══════════════════════════════════════════════════════════════════
# COMBINED STATUS ENDPOINT
# ═══════════════════════════════════════════════════════════════════

@router.get("/status")
async def get_governance_status() -> Dict[str, Any]:
    """Get combined governance status."""
    
    const = get_constitutional()
    enforcer = get_authority_enforcer()
    decay = get_time_decay_manager()
    
    return {
        "constitutional": const.get_status(),
        "authority_boundary": enforcer.get_status(),
        "time_decay": decay.get_status(),
        "system_halted": const.is_halted(),
        "halt_reason": const.get_halt_reason(),
    }


# ═══════════════════════════════════════════════════════════════════
# CONSENSUS ENGINE ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@router.get("/consensus/status")
async def get_consensus_status() -> Dict[str, Any]:
    """Get consensus engine status for dashboard."""
    try:
        from core.consensus_engine import get_consensus_engine
        consensus = get_consensus_engine()
        status = consensus.get_status() if hasattr(consensus, 'get_status') else {}
        return {
            "status": status.get('status', 'active'),
            "pending_votes": status.get('pending_votes', 0),
            "resolved_today": status.get('resolved_today', 0),
            "quorum_threshold": status.get('quorum_threshold', 0.67),
            "active_proposals": status.get('active_proposals', 0)
        }
    except Exception as e:
        logger.error(f"Consensus status error: {e}")
        return {
            "status": "active",
            "pending_votes": 0,
            "resolved_today": 0,
            "quorum_threshold": 0.67,
            "error": str(e)
        }
