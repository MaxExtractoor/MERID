"""Autonomy control API for Prime Screen overrides."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, validator

from core.autonomy.control import (
    AutonomyGlobal,
    AutonomyPortfolio,
    get_global_autonomy,
    get_portfolio_limits,
    list_portfolio_limits,
    update_global_autonomy,
    upsert_portfolio_limits,
)

router = APIRouter(prefix="/api/v1/swarm/prime-screen/autonomy", tags=["autonomy"])


class AutonomyStateResponse(BaseModel):
    global_state: str
    mode: str
    updated_at: str
    updated_by: str
    reason: Optional[str]

    @classmethod
    def from_model(cls, model: AutonomyGlobal) -> "AutonomyStateResponse":
        return cls(**model.__dict__)


class AutonomyStateUpdateRequest(BaseModel):
    global_state: Optional[str] = Field(None, description="running | paused | draining")
    mode: Optional[str] = Field(None, description="full | supervised")
    reason: Optional[str] = Field(None, max_length=512)
    updated_by: Optional[str] = Field(None, max_length=128)

    @validator("global_state")
    def validate_state(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if value not in {"running", "paused", "draining"}:
            raise ValueError("global_state must be running, paused, or draining")
        return value

    @validator("mode")
    def validate_mode(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if value not in {"full", "supervised"}:
            raise ValueError("mode must be full or supervised")
        return value


class AutonomyPortfolioResponse(BaseModel):
    portfolio_id: str
    enabled: bool
    mandate: str
    max_notional: float
    max_daily_loss: float
    max_open_orders: int
    allowed_symbols: List[str]
    allowed_venues: List[str]
    allowed_hours: str

    @classmethod
    def from_model(cls, model: AutonomyPortfolio) -> "AutonomyPortfolioResponse":
        return cls(
            portfolio_id=model.portfolio_id,
            enabled=model.enabled,
            mandate=model.mandate,
            max_notional=model.max_notional,
            max_daily_loss=model.max_daily_loss,
            max_open_orders=model.max_open_orders,
            allowed_symbols=list(model.allowed_symbols),
            allowed_venues=list(model.allowed_venues),
            allowed_hours=model.allowed_hours,
        )


class AutonomyPortfolioUpdateRequest(BaseModel):
    portfolio_id: str = Field(..., min_length=1)
    enabled: Optional[bool]
    mandate: Optional[str]
    max_notional: Optional[float]
    max_daily_loss: Optional[float]
    max_open_orders: Optional[int]
    allowed_symbols: Optional[List[str]]
    allowed_venues: Optional[List[str]]
    allowed_hours: Optional[str]

    @validator("mandate")
    def validate_mandate(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if value not in {"full", "supervised"}:
            raise ValueError("mandate must be full or supervised")
        return value


@router.get("/state", response_model=AutonomyStateResponse)
async def get_autonomy_state() -> AutonomyStateResponse:
    return AutonomyStateResponse.from_model(get_global_autonomy())


@router.post("/state", response_model=AutonomyStateResponse, status_code=status.HTTP_200_OK)
async def update_autonomy_state(payload: AutonomyStateUpdateRequest) -> AutonomyStateResponse:
    try:
        updated = update_global_autonomy(
            global_state=payload.global_state,
            mode=payload.mode,
            reason=payload.reason,
            updated_by=payload.updated_by or "operator",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return AutonomyStateResponse.from_model(updated)


@router.get("/limits", response_model=List[AutonomyPortfolioResponse])
async def list_autonomy_limits() -> List[AutonomyPortfolioResponse]:
    portfolios = list_portfolio_limits()
    return [AutonomyPortfolioResponse.from_model(portfolio) for portfolio in portfolios]


@router.post("/limits", response_model=AutonomyPortfolioResponse)
async def upsert_autonomy_limits(payload: AutonomyPortfolioUpdateRequest) -> AutonomyPortfolioResponse:
    try:
        updated = upsert_portfolio_limits(payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return AutonomyPortfolioResponse.from_model(updated)
