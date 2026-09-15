"""Operator-visible live runtime state endpoints.

These endpoints expose the canonical runtime state machine and provide safe
read-only status plus an emergency halt action.  Entry enablement is handled by
the startup preflight state machine, not a manual button, in order to satisfy the
durable operator contract (see AGENTS.md).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional

from merid.observability.live_runtime_state import (
    get_live_runtime_state,
    ReleaseAssertion,
    LiveRuntimeStateError,
)

router = APIRouter(prefix="/live-runtime-state", tags=["live_runtime_state"])


@router.get("/")
async def get_live_runtime_state_info() -> dict:
    """Return the current live runtime state and recent transition history."""
    state = get_live_runtime_state()
    state_dict = state.to_dict()
    return {
        "state": state_dict["state"],
        "entry_halted": state_dict["entry_halted"],
        "reason": state_dict.get("reason"),
        "reason_codes": state_dict.get("reason_codes"),
        "transition_history": state_dict.get("transition_history", []),
        "release_assertion": state_dict.get("release_assertion"),
    }


class HaltRequest(BaseModel):
    reason: str = Field(default="operator_halt")
    reason_codes: List[str] = Field(default_factory=lambda: ["OPERATOR_HALT"])


@router.post("/halt")
async def halt_live_entries(req: HaltRequest) -> dict:
    """Operator-initiated emergency halt.  Always transitions to LIVE_ENTRIES_HALTED."""
    state = get_live_runtime_state()
    state.halt_entries(req.reason, req.reason_codes)
    return {"status": "halted", "state": state.state}


class ReleaseRequest(BaseModel):
    manual_release_token_hash: Optional[str] = None
    emergency_token_hash: Optional[str] = None
    preflight_snapshot_id: Optional[str] = None
    fresh_reconciliation: bool = True


@router.post("/release")
async def release_live_entries(req: ReleaseRequest) -> dict:
    """Explicit manual release after a fresh passing preflight.

    This is intended for rare operator actions, not normal startup.  Normal
    production startup with ``auto_execution_mode: 1`` transitions automatically
    after the lifespan preflight completes.
    """
    state = get_live_runtime_state()
    assertion = ReleaseAssertion(
        state=state.state,
        manual_release_token_hash=req.manual_release_token_hash or "",
        emergency_token_hash=req.emergency_token_hash or "",
        preflight_snapshot_id=req.preflight_snapshot_id or "",
        fresh_reconciliation=req.fresh_reconciliation,
    )
    try:
        state.request_live_entries_enabled(assertion)
    except LiveRuntimeStateError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return {"status": "enabled", "state": state.state}
