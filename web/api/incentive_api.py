"""Incentive Ledger & Social Advisory API.

Exposes:
  GET /api/v1/incentives/leaderboard       — top agents by cumulative edge
  GET /api/v1/incentives/agent/{agent_id}  — per-agent summary
  GET /api/v1/incentives/social/{symbol}   — per-market social advisory breakdown
  GET /api/v1/incentives/social-weights     — current social source weights
  PUT /api/v1/incentives/social-weights     — tune social source weights at runtime
  GET /api/v1/incentives/weight-history    — agent weight adjustment history
  POST /api/v1/incentives/apply-feedback   — trigger ledger feedback application
  POST /api/v1/incentives/audit-feedback   — dry-run feedback (compute but don't apply)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from consensus.consensus_coordinator import get_consensus_coordinator
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/incentives", tags=["incentives"])
logger = get_logger("web.api.incentive")


# ── Response / Request models ────────────────────────────────────────────


class SocialWeightUpdate(BaseModel):
    source: str
    weight: float = Field(..., ge=0.0, le=1.0)


# ── Leaderboard ──────────────────────────────────────────────────────────


@router.get("/leaderboard")
async def get_leaderboard(top_n: int = 10) -> Dict[str, Any]:
    """Return top agents ranked by cumulative edge."""
    try:
        coord = get_consensus_coordinator()
        return {
            "leaderboard": coord.incentive_ledger.leaderboard(top_n=top_n),
        }
    except Exception as exc:
        logger.warning("incentive leaderboard error: %s", exc)
        return {"leaderboard": [], "error": str(exc)}


# ── Per-agent summary ────────────────────────────────────────────────────


@router.get("/agent/{agent_id}")
async def get_agent_stats(agent_id: str) -> Dict[str, Any]:
    """Return incentive summary for a single agent."""
    coord = get_consensus_coordinator()
    return coord.incentive_ledger.summary(agent_id)


# ── Per-market social advisory breakdown ─────────────────────────────────


@router.get("/social/{symbol}")
async def get_social_breakdown(symbol: str) -> Dict[str, Any]:
    """Return current social advisory signals for a market/asset symbol."""
    coord = get_consensus_coordinator()
    signals = coord.get_social_signals(symbol)
    items = []
    for s in signals:
        items.append({
            "source": s.source,
            "agent_id": s.agent_id,
            "score": round(s.score, 4),
            "confidence": round(s.confidence, 4),
            "volume": s.volume,
            "timestamp": s.timestamp,
        })
    nudge = coord._compute_social_nudge(symbol)
    return {
        "symbol": symbol,
        "signal_count": len(items),
        "signals": items,
        "computed_nudge": round(nudge, 6),
    }


# ── Social weights read / update ─────────────────────────────────────────


@router.get("/social-weights")
async def get_social_weights() -> Dict[str, Any]:
    """Return current social advisory weights and max nudge cap."""
    coord = get_consensus_coordinator()
    return {
        "weights": dict(coord.config.social_advisory_weights),
        "max_nudge": coord.config.social_advisory_max_nudge,
    }


@router.put("/social-weights")
async def update_social_weight(req: SocialWeightUpdate) -> Dict[str, Any]:
    """Tune a social source weight at runtime."""
    coord = get_consensus_coordinator()
    coord.set_social_advisory_weight(req.source, req.weight)
    return {
        "source": req.source,
        "new_weight": coord.config.social_advisory_weights.get(req.source, 0.0),
    }


# ── Weight History ────────────────────────────────────────────────────────


@router.get("/weight-history")
async def get_weight_history(limit: int = 50) -> Dict[str, Any]:
    """Return agent weight adjustment history from feedback applications."""
    coord = get_consensus_coordinator()
    history = getattr(coord, '_weight_adjustment_history', [])
    return {
        "history": history[-limit:],
        "count": len(history),
    }


# ── Feedback Trigger & Audit ─────────────────────────────────────────────


class FeedbackTriggerRequest(BaseModel):
    min_rounds: int = 5
    dry_run: bool = False


@router.post("/apply-feedback")
async def apply_feedback(req: FeedbackTriggerRequest) -> Dict[str, Any]:
    """Trigger ledger feedback application to adjust agent weights.
    
    Set dry_run=true to preview changes without applying them.
    """
    coord = get_consensus_coordinator()
    
    if req.dry_run:
        # Compute but don't apply
        preview = coord.preview_ledger_feedback(min_rounds=req.min_rounds)
        return {
            "mode": "dry_run",
            "preview": preview,
            "message": f"Would adjust {len(preview)} agent weights",
        }
    
    # Actually apply
    adjusted = coord.apply_ledger_feedback(min_rounds=req.min_rounds)
    return {
        "mode": "applied",
        "adjusted_agents": adjusted,
        "adjusted_count": len(adjusted),
        "message": f"Adjusted {len(adjusted)} agent weights",
    }


@router.post("/audit-feedback")
async def audit_feedback(req: FeedbackTriggerRequest) -> Dict[str, Any]:
    """Dry-run feedback computation - compute but don't apply weight changes.
    
    Returns detailed preview of what would happen if feedback were applied.
    """
    coord = get_consensus_coordinator()
    preview = coord.preview_ledger_feedback(min_rounds=req.min_rounds)
    
    # Calculate statistics
    increases = sum(1 for p in preview if p['delta'] > 0)
    decreases = sum(1 for p in preview if p['delta'] < 0)
    unchanged = sum(1 for p in preview if p['delta'] == 0)
    
    return {
        "mode": "audit",
        "preview": preview,
        "statistics": {
            "total": len(preview),
            "increases": increases,
            "decreases": decreases,
            "unchanged": unchanged,
        },
        "message": f"Audit: {len(preview)} agents would be adjusted ({increases} up, {decreases} down)",
    }
