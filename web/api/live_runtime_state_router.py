"""Operator-visible live runtime state endpoints.

These endpoints expose the canonical runtime state machine and provide safe
read-only status plus emergency halt/release actions.  Entry enablement is
handled by the startup preflight state machine, not a manual boolean, in
order to satisfy the durable operator contract (see AGENTS.md).

State-changing endpoints require an authenticated session
(``Depends(get_current_session)`` — ``X-Session-ID`` or
``Authorization: Bearer``).  ``POST /recover`` is the UI release path: it
re-enables entries only through the canonical ``RECOVERY_RUNNING ->
LIVE_ENTRIES_ENABLED`` gate with freshly probed recovery evidence — it never
bypasses reconciliation, watermark, router, or production-live checks.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Any, List, Optional

from merid.observability.live_runtime_state import (
    get_live_runtime_state,
    ReleaseAssertion,
    LiveRuntimeStateError,
    collect_runtime_recovery_evidence,
    runtime_recovery_evidence_missing,
)
from web.api.auth import get_current_session

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
async def halt_live_entries(
    req: HaltRequest,
    session: dict = Depends(get_current_session),
) -> dict:
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
async def release_live_entries(
    req: ReleaseRequest,
    session: dict = Depends(get_current_session),
) -> dict:
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


class RecoverRequest(BaseModel):
    reason: str = Field(default="operator_release")
    resolved_failure: bool = True


def _halted_fill_watermark() -> Any:
    """Trusted fill watermark captured when the fills poller halted entries."""
    try:
        from merid.event_venues.kalshi.fills_poller import get_fills_poller

        return getattr(get_fills_poller(), "_halted_fill_watermark", None)
    except Exception:
        return None


@router.post("/recover")
async def recover_live_entries(
    req: RecoverRequest,
    session: dict = Depends(get_current_session),
) -> dict:
    """Verified operator release for a halted runtime.

    Re-enables entries only when the canonical recovery evidence probe passes
    (resolved failure, fresh reconciliation, current non-regressing fill
    watermark, no critical discrepancy, exits + canonical router available,
    production/live identity intact) and ``complete_runtime_recovery`` commits
    the durable ``live_runtime_recovery_passed`` event.  Anything missing
    refuses with 409 — fail closed, matching the fills-poller auto-recovery
    path.  This is the endpoint the UI emergency control calls; it replaces
    the manual-token ``/release`` flow for routine operator release.
    """
    state = get_live_runtime_state()
    current = state.state
    if current == "LIVE_ENTRIES_ENABLED":
        return {"status": "enabled", "state": current, "recovery": "already_enabled"}
    if current not in ("LIVE_ENTRIES_HALTED", "RECOVERY_RUNNING"):
        raise HTTPException(
            status_code=409,
            detail=f"cannot recover entries from state {current}",
        )
    try:
        evidence = collect_runtime_recovery_evidence(
            resolved_failure=req.resolved_failure,
            fill_watermark_at_halt=_halted_fill_watermark(),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"recovery evidence unavailable: {exc}",
        )
    evidence["recovery"] = "operator_release"
    missing = runtime_recovery_evidence_missing(evidence)
    if missing:
        raise HTTPException(
            status_code=409,
            detail={"status": "recovery_refused", "missing": missing},
        )
    prior_reason = prior_codes = None
    if current == "LIVE_ENTRIES_HALTED":
        prior = state.to_dict()
        prior_reason = prior.get("reason")
        prior_codes = list(prior.get("reason_codes") or [])
        state.transition(
            "RECOVERY_RUNNING",
            "operator_recovery_evaluation",
            ["RECOVERY_EVALUATION"],
        )
    if not state.complete_runtime_recovery(req.reason, evidence):
        if current == "LIVE_ENTRIES_HALTED":
            state.transition(
                "LIVE_ENTRIES_HALTED",
                prior_reason or "operator_release_refused",
                prior_codes or ["RECOVERY_REFUSED"],
            )
        raise HTTPException(
            status_code=409,
            detail={"status": "recovery_refused", "missing": ["commit_refused"]},
        )
    return {"status": "enabled", "state": state.state, "recovery": "verified"}
