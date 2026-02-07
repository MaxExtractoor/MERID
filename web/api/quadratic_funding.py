"""Quadratic funding API endpoints."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from governance.quadratic_funding import (
    Contribution,
    Proposal,
    ProposalStatus,
    QuadraticFundingProgram,
    QuadraticFundingRound,
    RoundStatus,
    get_quadratic_funding_program,
)

router = APIRouter(prefix="/api/v1/quadratic-funding", tags=["quadratic_funding"])


class ProposalPayload(BaseModel):
    title: str = Field(..., max_length=160)
    description: str = Field(..., max_length=4000)
    requested_budget_usd: float = Field(..., gt=0)
    target_swarm: str = Field(..., max_length=120)
    tags: Optional[List[str]] = None
    owner: str = Field("", max_length=120)
    metadata: Optional[Dict[str, Any]] = None


class RoundPayload(BaseModel):
    matching_pool_usd: float = Field(..., gt=0)
    proposal_ids: Optional[List[str]] = None


class ContributionPayload(BaseModel):
    round_id: str
    proposal_id: str
    contributor_id: str = Field(..., max_length=120)
    amount_usd: float = Field(..., gt=0)
    metadata: Optional[Dict[str, Any]] = None


class RoundFinalizePayload(BaseModel):
    round_id: str
    governance_notes: Optional[List[str]] = None


class GovernanceNotePayload(BaseModel):
    round_id: str
    note: str = Field(..., max_length=400)


class RoundSummaryResponse(BaseModel):
    round_id: str
    status: str
    matching_pool_usd: float
    total_direct_usd: float
    total_matched_usd: float
    total_allocated_usd: float
    proposal_breakdown: List[Dict[str, Any]]
    governance_notes: List[str]
    created_at: str


_program: QuadraticFundingProgram = get_quadratic_funding_program()


@router.post("/proposals", response_model=Proposal)
async def register_proposal(payload: ProposalPayload) -> Proposal:
    return _program.register_proposal(
        title=payload.title,
        description=payload.description,
        requested_budget_usd=payload.requested_budget_usd,
        target_swarm=payload.target_swarm,
        tags=payload.tags,
        owner=payload.owner,
        metadata=payload.metadata,
    )


@router.get("/proposals", response_model=List[Proposal])
async def list_proposals(status: Optional[ProposalStatus] = None) -> List[Proposal]:
    return _program.list_proposals(status=status)


@router.get("/proposals/{proposal_id}", response_model=Proposal)
async def get_proposal(proposal_id: str) -> Proposal:
    proposal = _program.get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Unknown proposal")
    return proposal


@router.post("/rounds", response_model=QuadraticFundingRound)
async def start_round(payload: RoundPayload) -> QuadraticFundingRound:
    return _program.start_round(
        matching_pool_usd=payload.matching_pool_usd,
        proposal_ids=payload.proposal_ids,
    )


@router.get("/rounds", response_model=List[QuadraticFundingRound])
async def list_rounds(status: Optional[RoundStatus] = None) -> List[QuadraticFundingRound]:
    return _program.list_rounds(status=status)


@router.get("/rounds/summary", response_model=List[RoundSummaryResponse])
async def list_round_summaries(
    status: Optional[RoundStatus] = Query(default=None),
    limit: Optional[int] = Query(default=5, ge=1, le=50),
) -> List[Dict[str, Any]]:
    return _program.summarize_rounds(status=status, limit=limit)


@router.get("/rounds/{round_id}", response_model=QuadraticFundingRound)
async def get_round(round_id: str) -> QuadraticFundingRound:
    round_obj = _program.get_round(round_id)
    if not round_obj:
        raise HTTPException(status_code=404, detail="Unknown round")
    return round_obj


@router.get("/rounds/{round_id}/summary", response_model=RoundSummaryResponse)
async def round_summary(round_id: str) -> Dict[str, Any]:
    try:
        return _program.summary_for_round(round_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/contributions", response_model=Contribution)
async def record_contribution(payload: ContributionPayload) -> Contribution:
    try:
        return _program.record_contribution(
            round_id=payload.round_id,
            proposal_id=payload.proposal_id,
            contributor_id=payload.contributor_id,
            amount_usd=payload.amount_usd,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/rounds/finalize")
async def finalize_round(payload: RoundFinalizePayload) -> Dict[str, Dict[str, float]]:
    return _program.finalize_round(
        round_id=payload.round_id,
        governance_notes=payload.governance_notes,
    )


@router.post("/rounds/note")
async def append_governance_note(payload: GovernanceNotePayload) -> Dict[str, Any]:
    round_obj = _program.get_round(payload.round_id)
    if not round_obj:
        raise HTTPException(status_code=404, detail="Unknown round")
    round_obj.governance_notes.append(payload.note)
    return {"round_id": payload.round_id, "notes": round_obj.governance_notes}


@router.get("/proposals/{proposal_id}/support")
async def proposal_support(proposal_id: str) -> Dict[str, Any]:
    try:
        return _program.proposal_support(proposal_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
