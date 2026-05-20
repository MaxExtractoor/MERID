"""Incentive Ledger & Social Advisory API.

LEGACY REMOVAL: This entire API depends on consensus.consensus_coordinator which has been deleted.
All endpoints are disabled.

Exposes:
  GET /api/v1/incentives/leaderboard       — top agents by cumulative edge (DISABLED)
  GET /api/v1/incentives/agent/{agent_id}  — per-agent summary (DISABLED)
  GET /api/v1/incentives/social/{symbol}   — per-market social advisory breakdown (DISABLED)
  GET /api/v1/incentives/social-weights     — current social source weights (DISABLED)
  PUT /api/v1/incentives/social-weights     — tune social source weights at runtime (DISABLED)
  GET /api/v1/incentives/weight-history    — agent weight adjustment history (DISABLED)
  POST /api/v1/incentives/apply-feedback   — trigger ledger feedback application (DISABLED)
  POST /api/v1/incentives/audit-feedback   — dry-run feedback (DISABLED)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

# LEGACY REMOVAL: consensus.consensus_coordinator import removed - consensus module deleted
# from consensus.consensus_coordinator import get_consensus_coordinator
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
    # LEGACY REMOVAL: Consensus module deleted - endpoint disabled
    logger.warning("incentive leaderboard disabled - consensus module deleted")
    return {
        "leaderboard": [],
        "message": "Consensus module deleted"
    }


# ── Per-agent summary ────────────────────────────────────────────────────


@router.get("/agent/{agent_id}")
async def get_agent_stats(agent_id: str) -> Dict[str, Any]:
    """Return incentive summary for a single agent."""
    # LEGACY REMOVAL: Consensus module deleted - endpoint disabled
    logger.warning(f"incentive agent stats disabled - consensus module deleted: {agent_id}")
    return {
        "agent_id": agent_id,
        "message": "Consensus module deleted"
    }


# ── Per-market social advisory breakdown ─────────────────────────────────


@router.get("/social/{symbol}")
async def get_social_breakdown(symbol: str) -> Dict[str, Any]:
    """Return current social advisory signals for a market/asset symbol."""
    # LEGACY REMOVAL: Consensus module deleted - endpoint disabled
    logger.warning(f"incentive social breakdown disabled - consensus module deleted: {symbol}")
    return {
        "symbol": symbol,
        "signals": [],
        "message": "Consensus module deleted"
    }


# ── Social weights read / update ─────────────────────────────────────────


@router.get("/social-weights")
async def get_social_weights() -> Dict[str, Any]:
    """Return current social advisory weights and max nudge cap."""
    # LEGACY REMOVAL: Consensus module deleted - endpoint disabled
    logger.warning("incentive social weights disabled - consensus module deleted")
    return {
        "weights": {},
        "max_nudge": 0.0,
        "message": "Consensus module deleted"
    }


@router.put("/social-weights")
async def update_social_weight(req: SocialWeightUpdate) -> Dict[str, Any]:
    """Tune a social source weight at runtime."""
    # LEGACY REMOVAL: Consensus module deleted - endpoint disabled
    logger.warning(f"incentive social weight update disabled - consensus module deleted: {req.source}")
    return {
        "source": req.source,
        "new_weight": 0.0,
        "message": "Consensus module deleted"
    }


# ── Weight History ────────────────────────────────────────────────────────


@router.get("/weight-history")
async def get_weight_history(limit: int = 50) -> Dict[str, Any]:
    """Return agent weight adjustment history from feedback applications."""
    # LEGACY REMOVAL: Consensus module deleted - endpoint disabled
    logger.warning("incentive weight history disabled - consensus module deleted")
    return {
        "history": [],
        "count": 0,
        "message": "Consensus module deleted"
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
    # LEGACY REMOVAL: Consensus module deleted - endpoint disabled
    logger.warning(f"incentive apply feedback disabled - consensus module deleted: dry_run={req.dry_run}")
    return {
        "dry_run": req.dry_run,
        "preview": [],
        "message": "Consensus module deleted"
    }


@router.post("/audit-feedback")
async def audit_feedback(req: FeedbackTriggerRequest) -> Dict[str, Any]:
    """Dry-run feedback computation - compute but don't apply weight changes.
    
    Returns detailed preview of what would happen if feedback were applied.
    """
    # LEGACY REMOVAL: Consensus module deleted - endpoint disabled
    logger.warning(f"incentive audit feedback disabled - consensus module deleted: min_rounds={req.min_rounds}")
    return {
        "min_rounds": req.min_rounds,
        "preview": [],
        "increases": 0,
        "decreases": 0,
        "message": "Consensus module deleted"
    }
