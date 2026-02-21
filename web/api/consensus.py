"""
Consensus Engine API Endpoints.

Exposes consensus voting, decisions, and metrics for UI display.
"""

from __future__ import annotations

import time
from typing import Dict, Any, List

from fastapi import APIRouter, HTTPException

from core.consensus_engine import get_consensus_engine, Vote, ConsensusResult
from utils.logger import get_logger

logger = get_logger("web.api.consensus")

router = APIRouter(prefix="/api/v1/consensus", tags=["consensus"])


@router.get("/status")
async def get_consensus_status() -> Dict[str, Any]:
    """Get current consensus engine status and metrics."""
    engine = get_consensus_engine()
    
    pending_votes = list(engine.pending_votes.values())
    
    # Calculate vote distribution
    vote_distribution = {"bullish": 0, "bearish": 0, "neutral": 0}
    total_weight = 0.0
    
    for vote in pending_votes:
        signal = vote.signal.lower()
        if signal in vote_distribution:
            vote_distribution[signal] += vote.weight
            total_weight += vote.weight
    
    # Normalize to percentages
    if total_weight > 0:
        for signal in vote_distribution:
            vote_distribution[signal] = round((vote_distribution[signal] / total_weight) * 100, 1)
    
    return {
        "running": engine.running,
        "pending_votes": len(pending_votes),
        "min_votes_required": engine.min_votes,
        "quorum_threshold": engine.quorum_threshold,
        "consensus_interval": engine.consensus_interval,
        "vote_window": engine.vote_window,
        "last_consensus_time": engine.last_consensus_time,
        "time_until_next": max(0, engine.consensus_interval - (time.time() - engine.last_consensus_time)),
        "vote_distribution": vote_distribution,
        "trust_scores": dict(engine.trust_scores),
    }


@router.get("/votes")
async def get_pending_votes() -> Dict[str, Any]:
    """Get current pending votes awaiting consensus."""
    engine = get_consensus_engine()
    
    votes = []
    for vote in engine.pending_votes.values():
        votes.append({
            "agent_id": vote.agent_id,
            "proposal": vote.proposal,
            "signal": vote.signal,
            "confidence": vote.confidence,
            "energy": vote.energy,
            "trust": vote.trust,
            "weight": vote.weight,
            "timestamp": vote.timestamp,
        })
    
    # Sort by weight descending
    votes.sort(key=lambda v: v["weight"], reverse=True)
    
    return {
        "votes": votes,
        "count": len(votes),
        "quorum_met": len(votes) >= engine.min_votes,
    }


@router.get("/history")
async def get_consensus_history(limit: int = 20) -> Dict[str, Any]:
    """Get recent consensus decisions."""
    try:
        engine = get_consensus_engine()
        history = engine.consensus_logger.get_recent_decisions(limit=limit)
        return {
            "decisions": history,
            "count": len(history),
        }
    except Exception as e:
        logger.warning("Consensus history unavailable: %s", e)
        return {"decisions": [], "count": 0}


@router.get("/metrics")
async def get_consensus_metrics() -> Dict[str, Any]:
    """Get consensus engine performance metrics."""
    try:
        engine = get_consensus_engine()
        
        # Get metrics from logger
        metrics = engine.consensus_logger.get_metrics()
        
        return {
            "total_rounds": metrics.get("total_rounds", 0),
            "successful_consensus": metrics.get("successful", 0),
            "vetoed_decisions": metrics.get("vetoed", 0),
            "rerounds_requested": metrics.get("rerounds", 0),
            "avg_vote_count": metrics.get("avg_votes", 0),
            "avg_confidence": metrics.get("avg_confidence", 0),
            "quorum_rate": metrics.get("quorum_rate", 0),
            "trust_scores": dict(engine.trust_scores),
        }
    except Exception:
        return {
            "total_rounds": 0,
            "successful_consensus": 0,
            "vetoed_decisions": 0,
            "rerounds_requested": 0,
            "avg_vote_count": 0,
            "avg_confidence": 0,
            "quorum_rate": 0,
            "trust_scores": {},
        }


@router.post("/start")
async def start_consensus_engine() -> Dict[str, Any]:
    """Start the consensus engine."""
    engine = get_consensus_engine()
    
    if engine.running:
        return {"status": "already_running"}
    
    await engine.start()
    return {"status": "started"}


@router.post("/stop")
async def stop_consensus_engine() -> Dict[str, Any]:
    """Stop the consensus engine."""
    engine = get_consensus_engine()
    
    if not engine.running:
        return {"status": "already_stopped"}
    
    await engine.stop()
    return {"status": "stopped"}
