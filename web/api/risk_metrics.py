"""
Risk Metrics API Endpoints.

Exposes agent performance metrics (Sharpe, drawdown, PnL)
for dashboard visualization and risk management.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from risk import get_agent_metrics_tracker
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/risk-metrics", tags=["risk-metrics"])
logger = get_logger("web.api.risk_metrics")


class RecordTradeRequest(BaseModel):
    """Request to record a trade."""
    agent_id: str
    pnl: float
    is_win: bool
    trade_size: float = 0.0


class RecordOpinionRequest(BaseModel):
    """Request to record an opinion outcome."""
    agent_id: str
    was_correct: Optional[bool] = None


# ============================================
# AGENT METRICS
# ============================================

@router.get("/agents")
async def get_all_agent_metrics() -> Dict[str, Any]:
    """Get metrics for all agents."""
    tracker = get_agent_metrics_tracker()
    agents = tracker.get_all_agents()
    global_stats = tracker.get_global_stats()
    
    return {
        "agents": agents,
        "global_stats": global_stats,
        "count": len(agents),
    }


@router.get("/agents/{agent_id}")
async def get_agent_metrics(agent_id: str) -> Dict[str, Any]:
    """Get metrics for a specific agent."""
    tracker = get_agent_metrics_tracker()
    agent = tracker.get_agent(agent_id)
    
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    return agent.to_dict()


@router.get("/agents/{agent_id}/equity-history")
async def get_agent_equity_history(
    agent_id: str,
    limit: int = 100,
) -> Dict[str, Any]:
    """Get equity history for an agent."""
    tracker = get_agent_metrics_tracker()
    history = tracker.get_equity_history(agent_id, limit)
    
    return {
        "agent_id": agent_id,
        "history": history,
        "count": len(history),
    }


@router.get("/agents/{agent_id}/drawdown-history")
async def get_agent_drawdown_history(
    agent_id: str,
    limit: int = 100,
) -> Dict[str, Any]:
    """Get drawdown history for an agent."""
    tracker = get_agent_metrics_tracker()
    history = tracker.get_drawdown_history(agent_id, limit)
    
    return {
        "agent_id": agent_id,
        "history": history,
        "count": len(history),
    }


# ============================================
# LEADERBOARD
# ============================================

@router.get("/leaderboard")
async def get_leaderboard(
    metric: str = "sharpe_ratio",
    limit: int = 10,
) -> Dict[str, Any]:
    """
    Get top agents by a specific metric.
    
    Metrics: sharpe_ratio, total_pnl, win_rate, prediction_accuracy, consensus_weight
    """
    tracker = get_agent_metrics_tracker()
    leaderboard = tracker.get_leaderboard(metric=metric, limit=limit)
    
    return {
        "metric": metric,
        "leaderboard": leaderboard,
        "count": len(leaderboard),
    }


# ============================================
# TRADE RECORDING
# ============================================

@router.post("/trades")
async def record_trade(request: RecordTradeRequest) -> Dict[str, Any]:
    """Record a completed trade for an agent."""
    tracker = get_agent_metrics_tracker()
    tracker.record_trade(
        agent_id=request.agent_id,
        pnl=request.pnl,
        is_win=request.is_win,
        trade_size=request.trade_size,
    )
    
    agent = tracker.get_agent(request.agent_id)
    return {
        "status": "recorded",
        "agent_id": request.agent_id,
        "metrics": agent.to_dict() if agent else None,
    }


@router.post("/opinions")
async def record_opinion(request: RecordOpinionRequest) -> Dict[str, Any]:
    """Record an opinion outcome for an agent."""
    tracker = get_agent_metrics_tracker()
    tracker.record_opinion(
        agent_id=request.agent_id,
        was_correct=request.was_correct,
    )
    
    agent = tracker.get_agent(request.agent_id)
    return {
        "status": "recorded",
        "agent_id": request.agent_id,
        "metrics": agent.to_dict() if agent else None,
    }


# ============================================
# GLOBAL STATS
# ============================================

@router.get("/stats")
async def get_global_stats() -> Dict[str, Any]:
    """Get aggregate statistics across all agents."""
    tracker = get_agent_metrics_tracker()
    return tracker.get_global_stats()
