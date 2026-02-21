"""Cognitive Layer API — structured hypotheses, reality debugging, and human-in-the-loop actions.

Endpoints:
  POST /cognitive/snapshots              — create a cognitive snapshot
  GET  /cognitive/snapshots              — list snapshots (filter by domain, owner)
  GET  /cognitive/snapshots/{id}         — get snapshot by ID
  GET  /cognitive/snapshots/market/{id}  — get snapshot history for a market
  GET  /cognitive/hypotheses/{id}        — get hypothesis by ID
  POST /cognitive/hypotheses/{id}/confidence — update hypothesis confidence
  POST /cognitive/hypotheses/{id}/broken    — mark hypothesis as broken
  POST /cognitive/hypotheses/{id}/retire    — retire a hypothesis
  POST /cognitive/hypotheses/{id}/evidence  — add evidence to a hypothesis
  GET  /cognitive/reality-debug          — full reality debug report
  GET  /cognitive/health                 — cognitive health metrics
  GET  /cognitive/actions                — recent cognitive actions log
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from utils.logger import get_logger

logger = get_logger("web.api.cognitive_api")

router = APIRouter(prefix="/api/v1/cognitive", tags=["cognitive"])


# ── Pydantic request models ──────────────────────────────────────────

class HypothesisInput(BaseModel):
    text: str = ""
    regime_category: str = ""
    regime_label: str = ""
    regime_description: str = ""
    confidence: float = 0.5
    owner: str = ""

class EvidenceLinkInput(BaseModel):
    evidence_type: str = "external_data"
    reference_id: str = ""
    title: str = ""
    url: str = ""
    supports: bool = True
    strength: float = 0.5
    notes: str = ""

class CreateSnapshotRequest(BaseModel):
    market_id: str
    domain: str = "market"
    hypotheses: List[HypothesisInput] = Field(default_factory=list)
    overall_regime_confidence: float = 0.5
    owner: str = ""
    opinion_id: str = ""
    debate_id: str = ""
    notes: str = ""

class UpdateConfidenceRequest(BaseModel):
    new_confidence: float
    actor: str = ""
    reason: str = ""

class MarkBrokenRequest(BaseModel):
    actor: str = ""
    reason: str = ""

class RetireRequest(BaseModel):
    actor: str = ""
    reason: str = ""

class AddEvidenceRequest(BaseModel):
    evidence_type: str = "external_data"
    reference_id: str = ""
    title: str = ""
    url: str = ""
    supports: bool = True
    strength: float = 0.5
    actor: str = ""
    notes: str = ""

class RealityDebugRequest(BaseModel):
    market_brier_scores: Dict[str, float] = Field(default_factory=dict)
    market_surprise_times: Optional[Dict[str, float]] = None
    agent_probabilities: Optional[Dict[str, Dict[str, float]]] = None
    window_s: float = 604800.0


# ── Helpers ───────────────────────────────────────────────────────────

def _get_store():
    from merid.cognitive.store import get_cognitive_store
    return get_cognitive_store()

def _get_debugger():
    from merid.cognitive.reality_debugger import get_reality_debugger
    return get_reality_debugger()

def _emit_cognitive_event(action: str, hypothesis_id: str, actor: str, **kwargs):
    """Emit a CognitiveEvent into the reward engine (best-effort)."""
    try:
        from merid.rewards.events import CognitiveEvent
        from merid.rewards.engine import get_reward_engine
        engine = get_reward_engine()
        event = CognitiveEvent(
            agent_id=actor,
            action=action,
            hypothesis_id=hypothesis_id,
            regime_tag=kwargs.get("regime_tag", ""),
            prior_confidence=kwargs.get("prior_confidence"),
            new_confidence=kwargs.get("new_confidence"),
            evidence_count=kwargs.get("evidence_count", 0),
            was_contradicted=kwargs.get("was_contradicted", False),
            venue=kwargs.get("venue", "cognitive"),
        )
        engine.process_event(event)
    except Exception as exc:
        logger.warning("Failed to emit cognitive reward event: %s", exc)


# ── Snapshot endpoints ────────────────────────────────────────────────

@router.post("/snapshots")
async def create_snapshot(req: CreateSnapshotRequest):
    """Create a new cognitive snapshot with hypotheses."""
    from merid.cognitive.models import (
        CognitiveSnapshot, Hypothesis, RegimeTag,
    )
    store = _get_store()

    hypotheses = []
    for h_in in req.hypotheses:
        hyp = Hypothesis(
            text=h_in.text,
            regime_tag=RegimeTag(
                category=h_in.regime_category,
                label=h_in.regime_label,
                description=h_in.regime_description,
            ),
            confidence=h_in.confidence,
            owner=h_in.owner or req.owner,
        )
        hypotheses.append(hyp)

    snap = CognitiveSnapshot(
        market_id=req.market_id,
        domain=req.domain,
        hypotheses=hypotheses,
        overall_regime_confidence=req.overall_regime_confidence,
        owner=req.owner,
        opinion_id=req.opinion_id,
        debate_id=req.debate_id,
        notes=req.notes,
    )
    saved = store.save_snapshot(snap)

    # Emit reward events for each hypothesis created
    for hyp in hypotheses:
        _emit_cognitive_event(
            "created", hyp.id, hyp.owner,
            regime_tag=hyp.regime_tag.label,
            new_confidence=hyp.confidence,
        )

    return {"status": "ok", "snapshot": saved.to_dict()}


@router.get("/snapshots")
async def list_snapshots(
    domain: Optional[str] = None,
    owner: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
):
    """List cognitive snapshots with optional filters."""
    store = _get_store()
    snaps = store.list_snapshots(domain=domain, owner=owner, limit=limit)
    return {"snapshots": [s.to_dict() for s in snaps], "count": len(snaps)}


@router.get("/snapshots/{snapshot_id}")
async def get_snapshot(snapshot_id: str):
    """Get a cognitive snapshot by ID."""
    store = _get_store()
    snap = store.get_snapshot(snapshot_id)
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return {"snapshot": snap.to_dict()}


@router.get("/snapshots/market/{market_id}")
async def get_market_snapshots(
    market_id: str,
    limit: int = Query(50, ge=1, le=200),
):
    """Get snapshot history for a market."""
    store = _get_store()
    snaps = store.get_snapshots_for_market(market_id, limit=limit)
    return {"market_id": market_id, "snapshots": [s.to_dict() for s in snaps], "count": len(snaps)}


# ── Hypothesis action endpoints ───────────────────────────────────────

@router.get("/hypotheses/{hypothesis_id}")
async def get_hypothesis(hypothesis_id: str):
    """Get a hypothesis by ID with evidence links."""
    store = _get_store()
    hyp = store.get_hypothesis(hypothesis_id)
    if not hyp:
        raise HTTPException(status_code=404, detail="Hypothesis not found")
    return {"hypothesis": hyp.to_dict()}


@router.post("/hypotheses/{hypothesis_id}/confidence")
async def update_confidence(hypothesis_id: str, req: UpdateConfidenceRequest):
    """Update a hypothesis's confidence (human-in-the-loop action)."""
    store = _get_store()
    hyp = store.update_hypothesis_confidence(
        hypothesis_id, req.new_confidence, actor=req.actor, reason=req.reason,
    )
    if not hyp:
        raise HTTPException(status_code=404, detail="Hypothesis not found")

    _emit_cognitive_event(
        "updated", hypothesis_id, req.actor,
        prior_confidence=hyp.prior_confidence,
        new_confidence=req.new_confidence,
        regime_tag=hyp.regime_tag.label,
    )

    return {"status": "ok", "hypothesis": hyp.to_dict()}


@router.post("/hypotheses/{hypothesis_id}/broken")
async def mark_broken(hypothesis_id: str, req: MarkBrokenRequest):
    """Mark a hypothesis as broken (reality contradicted it)."""
    store = _get_store()
    hyp = store.mark_hypothesis_broken(
        hypothesis_id, actor=req.actor, reason=req.reason,
    )
    if not hyp:
        raise HTTPException(status_code=404, detail="Hypothesis not found")

    _emit_cognitive_event(
        "broken", hypothesis_id, req.actor,
        was_contradicted=True,
        regime_tag=hyp.regime_tag.label,
        prior_confidence=hyp.confidence,
        new_confidence=0.0,
    )

    return {"status": "ok", "hypothesis": hyp.to_dict()}


@router.post("/hypotheses/{hypothesis_id}/retire")
async def retire_hypothesis(hypothesis_id: str, req: RetireRequest):
    """Retire a hypothesis (superseded or no longer relevant)."""
    store = _get_store()
    hyp = store.retire_hypothesis(
        hypothesis_id, actor=req.actor, reason=req.reason,
    )
    if not hyp:
        raise HTTPException(status_code=404, detail="Hypothesis not found")

    _emit_cognitive_event(
        "retired", hypothesis_id, req.actor,
        regime_tag=hyp.regime_tag.label,
    )

    return {"status": "ok", "hypothesis": hyp.to_dict()}


@router.post("/hypotheses/{hypothesis_id}/evidence")
async def add_evidence(hypothesis_id: str, req: AddEvidenceRequest):
    """Add an evidence link to a hypothesis."""
    from merid.cognitive.models import EvidenceLink
    store = _get_store()
    evidence = EvidenceLink(
        evidence_type=req.evidence_type,
        reference_id=req.reference_id,
        title=req.title,
        url=req.url,
        supports=req.supports,
        strength=req.strength,
        added_by=req.actor,
        notes=req.notes,
    )
    ok = store.add_evidence(hypothesis_id, evidence, actor=req.actor)
    if not ok:
        raise HTTPException(status_code=404, detail="Hypothesis not found")

    _emit_cognitive_event(
        "updated", hypothesis_id, req.actor,
        evidence_count=1,
    )

    return {"status": "ok", "evidence": evidence.to_dict()}


# ── Reality debug endpoint ────────────────────────────────────────────

@router.post("/reality-debug")
async def reality_debug(req: RealityDebugRequest):
    """Generate a full reality debug report.

    Detects stuck models, conceptual disagreements, and hypothesis dynamics.
    """
    debugger = _get_debugger()
    report = debugger.reality_debug(
        market_brier_scores=req.market_brier_scores,
        market_surprise_times=req.market_surprise_times,
        agent_probabilities=req.agent_probabilities,
        window_s=req.window_s,
    )
    return report


@router.get("/reality-debug")
async def reality_debug_get(
    window_s: float = Query(604800.0, description="Time window in seconds"),
):
    """Get a reality debug report (no market data — uses store state only)."""
    debugger = _get_debugger()
    report = debugger.reality_debug(window_s=window_s)
    return report


# ── Health & metrics endpoints ────────────────────────────────────────

@router.get("/health")
async def cognitive_health(
    window_s: float = Query(604800.0, description="Time window in seconds"),
):
    """Get cognitive health metrics for observability."""
    debugger = _get_debugger()
    health = debugger.get_cognitive_health(window_s=window_s)
    return health


@router.get("/actions")
async def cognitive_actions(
    market_id: Optional[str] = None,
    window_s: float = Query(604800.0, description="Time window in seconds"),
    limit: int = Query(100, ge=1, le=500),
):
    """Get recent cognitive actions log."""
    store = _get_store()
    if market_id:
        actions = store.get_actions_for_market(market_id, window_s=window_s, limit=limit)
    else:
        actions = store.get_all_actions(window_s=window_s, limit=limit)
    return {"actions": actions, "count": len(actions)}


@router.get("/metrics")
async def cognitive_metrics(
    window_s: float = Query(604800.0, description="Time window in seconds"),
):
    """Get cognitive store metrics."""
    store = _get_store()
    return store.get_cognitive_metrics(window_s=window_s)


@router.get("/snapshot")
async def get_latest_snapshot():
    """Get the latest cognitive snapshot (convenience alias for dashboard).

    The frontend ``useCognitive`` hook fetches ``/api/v1/cognitive/snapshot``
    (singular).  This returns the most recent snapshot or a safe empty stub.
    """
    try:
        store = _get_store()
        snaps = store.list_snapshots(limit=1)
        if snaps:
            return {"snapshot": snaps[0].to_dict()}
        return {
            "snapshot": None,
            "hypotheses": [],
            "regime_tags": [],
            "overall_regime_confidence": 0.0,
        }
    except Exception as exc:
        logger.warning("cognitive/snapshot failed: %s", exc)
        return {
            "snapshot": None,
            "hypotheses": [],
            "regime_tags": [],
            "overall_regime_confidence": 0.0,
        }
