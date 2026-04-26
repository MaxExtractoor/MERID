"""Competitive moat analysis API — evaluates MERID's structural advantages."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from core.env import capabilities
from moat.moat_runtime import MoatRuntimeService, get_moat_runtime_service
from web.api.auth import get_current_session


router = APIRouter(prefix="/moat", tags=["moat"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


def _require_service_token(request: Request) -> None:
    expected = capabilities.moat_service_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Moat service token not configured",
        )

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")

    token = auth_header.split(" ", 1)[1]
    if token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def _get_runtime() -> MoatRuntimeService:
    return get_moat_runtime_service()


@router.get("/status")
async def moat_status(_: None = Depends(_require_service_token)) -> Dict[str, Any]:
    runtime = _get_runtime()
    return runtime.get_status_payload()


@router.post("/start")
async def moat_start(
    interval: float = 300.0,
    _: None = Depends(_require_service_token),
) -> Dict[str, Any]:
    runtime = _get_runtime()
    await runtime.start(interval=interval)
    return {"status": runtime.status.value, "interval": interval}


@router.post("/stop")
async def moat_stop(_: None = Depends(_require_service_token)) -> Dict[str, Any]:
    runtime = _get_runtime()
    await runtime.stop()
    return {"status": runtime.status.value}


@router.post("/measure")
async def moat_measure(_: None = Depends(_require_service_token)) -> Dict[str, Any]:
    runtime = _get_runtime()
    payload = await runtime.measure_now()
    return {"status": runtime.status.value, "payload": payload}


class FeatureProposalPayload(BaseModel):
    name: str
    description: str


@router.post("/proposals")
async def moat_proposal(
    payload: FeatureProposalPayload,
    _: None = Depends(_require_service_token),
) -> Dict[str, Any]:
    runtime = _get_runtime()
    proposal = runtime.submit_feature_proposal(payload.name, payload.description)
    return {
        "proposal_id": proposal.proposal_id,
        "approved": proposal.approved,
        "moat_score": proposal.moat_score,
        "impacts": {pillar.value: impact.value for pillar, impact in proposal.moat_impacts.items()},
        "recommendations": proposal.recommendations,
        "reason": proposal.approval_reason,
    }
