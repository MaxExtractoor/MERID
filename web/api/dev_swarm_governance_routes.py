"""
Dev Swarm Governance API Routes

REST API for DevProposal lifecycle, HITL approvals, debates, and audit log.
Sprint 13: Dev Swarm Governance & Guardrails
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger(__name__)

from core.dev_swarm_governance import (
    DevProposal,
    ApprovalRecord,
    DebateRound,
    ProposalMetrics,
    GovernanceMetrics,
    ProposalKind,
    ProposalStatus,
    RiskTier,
    ApprovalAction,
    ReviewerRole,
    AuditEventType,
    RISK_TIER_POLICY,
    KIND_DEFAULT_RISK,
    get_governance_store,
)

router = APIRouter(prefix="/api/dev-swarm/governance", tags=["dev-swarm-governance"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


# ── Request models ───────────────────────────────────────────────────

class CreateProposalRequest(BaseModel):
    kind: str = Field(..., description="Proposal kind from ProposalKind enum")
    title: str = Field(..., min_length=5, max_length=500)
    description: str = Field(default="", max_length=5000)
    target: str = Field(default="")
    diff_summary: str = Field(default="")
    risk_tier: Optional[str] = Field(default=None, description="Override risk tier; auto-derived from kind if omitted")
    risk_score: float = Field(default=0.5, ge=0.0, le=1.0)
    affected_subsystems: List[str] = Field(default=[])
    proposer_id: str = Field(default="human")
    owner_id: str = Field(default="human")
    branch_ref: str = Field(default="")
    pr_link: str = Field(default="")
    forecast_question: str = Field(default="")
    rollout_strategy: str = Field(default="full")
    tags: List[str] = Field(default=[])


class SubmitApprovalRequest(BaseModel):
    reviewer_id: str = Field(..., min_length=1)
    reviewer_role: str = Field(default="human_reviewer")
    action: str = Field(..., description="approve, reject, request_changes, abstain")
    justification: str = Field(default="")


class AddDebateRoundRequest(BaseModel):
    proposer_argument: str = Field(..., min_length=1)
    challenger_argument: str = Field(..., min_length=1)
    evidence_refs: List[str] = Field(default=[])
    metrics_snapshot: Dict[str, Any] = Field(default={})
    actor_id: str = Field(default="system")


class AttachMetricsRequest(BaseModel):
    metrics: List[Dict[str, Any]] = Field(...)
    actor_id: str = Field(default="system")


class UpdateStatusRequest(BaseModel):
    status: str = Field(...)
    actor_id: str = Field(default="system")


# ── Endpoints ────────────────────────────────────────────────────────

@router.post("/proposals", status_code=201)
async def create_proposal(req: CreateProposalRequest) -> Dict[str, Any]:
    """Create a new DevProposal."""
    store = get_governance_store()

    # Derive risk tier from kind if not explicitly set
    risk_tier = req.risk_tier
    if not risk_tier:
        try:
            kind_enum = ProposalKind(req.kind)
            risk_tier = KIND_DEFAULT_RISK.get(kind_enum, RiskTier.MEDIUM).value
        except ValueError:
            risk_tier = RiskTier.MEDIUM.value

    proposal = DevProposal(
        kind=req.kind,
        title=req.title,
        description=req.description,
        target=req.target,
        diff_summary=req.diff_summary,
        risk_tier=risk_tier,
        risk_score=req.risk_score,
        affected_subsystems=req.affected_subsystems,
        status=ProposalStatus.DRAFT.value,
        proposer_id=req.proposer_id,
        owner_id=req.owner_id,
        branch_ref=req.branch_ref,
        pr_link=req.pr_link,
        forecast_question=req.forecast_question,
        rollout_strategy=req.rollout_strategy,
        tags=req.tags,
    )
    created = store.create_proposal(proposal, actor_id=req.proposer_id)
    return created.to_dict()


@router.get("/proposals")
async def list_proposals(
    status: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    risk_tier: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """List proposals with optional filters."""
    store = get_governance_store()
    proposals = store.list_proposals(status=status, kind=kind, risk_tier=risk_tier, limit=limit, offset=offset)
    return {
        "proposals": [p.to_dict() for p in proposals],
        "total": len(proposals),
    }


@router.get("/proposals/{proposal_id}")
async def get_proposal(proposal_id: str) -> Dict[str, Any]:
    """Get a specific proposal."""
    store = get_governance_store()
    p = store.get_proposal(proposal_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found")
    return p.to_dict()


@router.patch("/proposals/{proposal_id}/status")
async def update_proposal_status(proposal_id: str, req: UpdateStatusRequest) -> Dict[str, Any]:
    """Update proposal status."""
    store = get_governance_store()
    p = store.update_status(proposal_id, req.status, actor_id=req.actor_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found")
    return p.to_dict()


# ── Approvals ────────────────────────────────────────────────────────

@router.post("/proposals/{proposal_id}/approvals")
async def submit_approval(proposal_id: str, req: SubmitApprovalRequest) -> Dict[str, Any]:
    """Submit an approval/rejection for a proposal."""
    store = get_governance_store()
    # Validate action
    valid_actions = [a.value for a in ApprovalAction]
    if req.action not in valid_actions:
        raise HTTPException(status_code=400, detail=f"Invalid action. Must be one of: {valid_actions}")

    record = store.submit_approval(
        proposal_id=proposal_id,
        reviewer_id=req.reviewer_id,
        reviewer_role=req.reviewer_role,
        action=req.action,
        justification=req.justification,
    )
    if not record:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found")

    # Return updated proposal
    p = store.get_proposal(proposal_id)
    return {"approval": record.to_dict(), "proposal": p.to_dict() if p else None}


@router.get("/proposals/{proposal_id}/approvals")
async def list_approvals(proposal_id: str) -> Dict[str, Any]:
    """List approvals for a proposal."""
    store = get_governance_store()
    p = store.get_proposal(proposal_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found")
    return {
        "approvals": [a.to_dict() for a in p.approvals],
        "total": len(p.approvals),
        "approval_count": p.approval_count,
        "rejection_count": p.rejection_count,
        "meets_threshold": p.meets_approval_threshold,
    }


# ── Debates ──────────────────────────────────────────────────────────

@router.post("/proposals/{proposal_id}/debates")
async def add_debate_round(proposal_id: str, req: AddDebateRoundRequest) -> Dict[str, Any]:
    """Add a debate round to a proposal."""
    store = get_governance_store()
    dr = store.add_debate_round(
        proposal_id=proposal_id,
        proposer_argument=req.proposer_argument,
        challenger_argument=req.challenger_argument,
        evidence_refs=req.evidence_refs,
        metrics_snapshot=req.metrics_snapshot,
        actor_id=req.actor_id,
    )
    if not dr:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found")
    return dr.to_dict()


@router.get("/proposals/{proposal_id}/debates")
async def list_debates(proposal_id: str) -> Dict[str, Any]:
    """List debate rounds for a proposal."""
    store = get_governance_store()
    p = store.get_proposal(proposal_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found")
    return {
        "debate_rounds": [r.to_dict() for r in p.debate_rounds],
        "total_rounds": len(p.debate_rounds),
    }


# ── Metrics ──────────────────────────────────────────────────────────

@router.post("/proposals/{proposal_id}/metrics")
async def attach_metrics(proposal_id: str, req: AttachMetricsRequest) -> Dict[str, Any]:
    """Attach before/after metrics to a proposal."""
    store = get_governance_store()
    metrics_list = [
        ProposalMetrics(
            metric_name=m.get("metric_name", ""),
            baseline_value=m.get("baseline_value", 0.0),
            expected_value=m.get("expected_value", 0.0),
            actual_value=m.get("actual_value"),
            unit=m.get("unit", ""),
            improved=m.get("improved"),
        )
        for m in req.metrics
    ]
    ok = store.attach_metrics(proposal_id, metrics_list, actor_id=req.actor_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found")
    return {"attached": len(metrics_list)}


# ── Governance dashboard ─────────────────────────────────────────────

@router.get("/metrics")
async def governance_metrics() -> Dict[str, Any]:
    """Aggregate governance metrics for dashboards."""
    store = get_governance_store()
    m = store.compute_governance_metrics()
    return m.to_dict()


@router.get("/agent-stats")
async def agent_governance_stats() -> List[Dict[str, Any]]:
    """Per-agent governance stats."""
    store = get_governance_store()
    return store.get_agent_governance_stats()


# ── Risk policy ──────────────────────────────────────────────────────

@router.get("/risk-policy")
async def get_risk_policy() -> Dict[str, Any]:
    """Return risk tier policies and kind→tier mappings."""
    return {
        "risk_tiers": {tier.value: policy for tier, policy in RISK_TIER_POLICY.items()},
        "kind_defaults": {kind.value: tier.value for kind, tier in KIND_DEFAULT_RISK.items()},
    }


# ── Audit log ────────────────────────────────────────────────────────

@router.get("/audit-log")
async def get_audit_log(
    proposal_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """Query the immutable audit log."""
    store = get_governance_store()
    events = store.get_audit_log(proposal_id=proposal_id, event_type=event_type, limit=limit, offset=offset)
    return {
        "events": [e.to_dict() for e in events],
        "total": len(events),
    }


# ── HITL pending queue ───────────────────────────────────────────────

@router.get("/pending-approvals")
async def pending_approvals() -> Dict[str, Any]:
    """List proposals awaiting human approval (HITL queue)."""
    store = get_governance_store()
    proposals = store.list_proposals(status=ProposalStatus.IN_REVIEW.value, limit=500)
    pending = [p for p in proposals if not p.meets_approval_threshold]
    return {
        "pending": [p.to_dict() for p in pending],
        "total": len(pending),
    }
