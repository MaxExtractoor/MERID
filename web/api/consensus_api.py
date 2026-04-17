"""
Consensus API Endpoints.

Exposes TACo-style consensus system via REST and WebSocket.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from consensus import (
    get_consensus_coordinator,
    AgentOpinion,
    TradePlan,
    create_opinion_from_vote,
)
from web.api.auth import get_current_session
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/consensus", tags=["consensus"], dependencies=[Depends(get_current_session)]  # ZT6-01
)
logger = get_logger("web.api.consensus")


# ============================================
# REQUEST MODELS
# ============================================

class SubmitOpinionRequest(BaseModel):
    """Request to submit an agent opinion."""
    agent_id: str
    role: str = "analyst"
    symbol: str
    venue: str = "paper"
    stance: str  # bull, bear, neutral, strong_bull, strong_bear
    score: float = Field(..., ge=-1.0, le=1.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str = ""
    horizon: str = "short"
    data_sources: List[str] = []


class RiskReviewRequest(BaseModel):
    """Request for risk manager to review a plan."""
    plan_id: str
    approved: bool
    approved_size: Optional[float] = None
    reason: Optional[str] = None


# ============================================
# REST ENDPOINTS
# ============================================

@router.post("/opinions")
async def submit_opinion(request: SubmitOpinionRequest) -> Dict[str, Any]:
    """Submit an agent opinion for consensus consideration."""
    import uuid
    
    opinion = AgentOpinion(
        opinion_id=f"op_{uuid.uuid4().hex[:12]}",
        agent_id=request.agent_id,
        role=request.role,
        symbol=request.symbol,
        venue=request.venue,
        stance=request.stance,
        score=request.score,
        confidence=request.confidence,
        rationale=request.rationale,
        horizon=request.horizon,
        data_sources=request.data_sources,
    )
    
    coordinator = get_consensus_coordinator()
    await coordinator.submit_opinion(opinion)
    
    return {
        "status": "submitted",
        "opinion_id": opinion.opinion_id,
        "symbol": opinion.symbol,
    }


@router.get("/opinions")
async def get_recent_opinions(
    symbol: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """Get recent agent opinions."""
    coordinator = get_consensus_coordinator()
    opinions = coordinator.get_recent_opinions(symbol=symbol, limit=limit)
    
    return {
        "count": len(opinions),
        "opinions": opinions,
    }


@router.get("/plans")
async def get_active_plans(symbol: Optional[str] = None) -> Dict[str, Any]:
    """Get active trade plans."""
    coordinator = get_consensus_coordinator()
    plans = coordinator.get_active_plans(symbol=symbol)
    
    return {
        "count": len(plans),
        "plans": plans,
    }


@router.get("/status/{symbol}")
async def get_consensus_status(symbol: str) -> Dict[str, Any]:
    """Get current consensus status for a symbol."""
    coordinator = get_consensus_coordinator()
    return coordinator.get_consensus_status(symbol)


@router.get("/all-status")
async def get_all_consensus_status() -> Dict[str, Any]:
    """Get consensus status for all tracked symbols."""
    coordinator = get_consensus_coordinator()
    metrics = coordinator.get_metrics()
    
    statuses = {}
    for symbol in metrics.get("tracked_symbols", []):
        statuses[symbol] = coordinator.get_consensus_status(symbol)
    
    return {
        "symbols": statuses,
        "metrics": metrics,
    }


@router.post("/plans/{plan_id}/risk-review")
async def risk_review_plan(plan_id: str, request: RiskReviewRequest) -> Dict[str, Any]:
    """Risk manager reviews a trade plan."""
    coordinator = get_consensus_coordinator()
    
    plan = await coordinator.risk_review_plan(
        plan_id=plan_id,
        approved=request.approved,
        approved_size=request.approved_size,
        reason=request.reason,
    )
    
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    return {
        "status": "reviewed",
        "plan": plan.to_dict(),
    }


@router.get("/coordinator-metrics")
async def get_consensus_metrics() -> Dict[str, Any]:
    """Get consensus coordinator metrics."""
    coordinator = get_consensus_coordinator()
    return coordinator.get_metrics()


# ============================================
# WEBSOCKET ENDPOINT
# ============================================

@router.websocket("/ws/stream")
async def consensus_stream(websocket: WebSocket) -> None:
    """
    WebSocket stream for consensus events.
    
    Streams:
    - New opinions as they arrive
    - Trade plans as consensus is reached
    - Status updates
    """
    await websocket.accept()
    logger.info("[WS] Consensus stream client connected")
    
    unsubscribe = None
    try:
        coordinator = get_consensus_coordinator()
    except Exception as exc:
        logger.error(f"[WS] Failed to initialize consensus coordinator: {exc}")
        await websocket.send_json({
            "type": "feature_unavailable",
            "reason": "Consensus system not available",
            "ts": time.time(),
        })
        await websocket.close(1000)
        return
    
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    
    async def event_handler(event_type: str, data: Dict[str, Any]) -> None:
        try:
            await queue.put({"type": event_type, "data": data, "ts": time.time()})
        except asyncio.QueueFull:
            logger.warning("Consensus queue full, dropping event")
    
    try:
        unsubscribe = coordinator.subscribe(event_handler)
    except Exception as exc:
        logger.error(f"[WS] Failed to subscribe to consensus: {exc}")
        await websocket.send_json({
            "type": "feature_unavailable",
            "reason": "Consensus subscription failed",
            "ts": time.time(),
        })
        await websocket.close(1000)
        return
    
    # Send current state
    try:
        metrics = coordinator.get_metrics()
        await websocket.send_json({
            "type": "init",
            "data": {
                "metrics": metrics,
                "recent_opinions": coordinator.get_recent_opinions(limit=10),
                "active_plans": coordinator.get_active_plans(),
            },
            "ts": time.time(),
        })
    except Exception as exc:
        logger.warning(f"[WS] Could not send initial consensus state: {exc}")
        await websocket.send_json({
            "type": "init",
            "data": {"metrics": {}, "recent_opinions": [], "active_plans": []},
            "ts": time.time(),
        })
    
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=10.0)
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_json({
                    "type": "heartbeat",
                    "ts": time.time(),
                })
    except WebSocketDisconnect:
        logger.info("[WS] Consensus stream client disconnected")
    except Exception as exc:
        logger.error(f"[WS] Consensus stream error: {exc}")
    finally:
        if unsubscribe:
            unsubscribe()
