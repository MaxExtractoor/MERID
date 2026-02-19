"""
MERID-ARCHIVE API Endpoints

Memory & Truth API.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/archive", tags=["archive"])
logger = get_logger("web.api.archive")


class RecordOutcomeRequest(BaseModel):
    """Request to record an agent outcome."""
    agent_id: str
    outcome_type: str
    prediction: Any
    confidence: float
    symbol: Optional[str] = None
    context: Dict[str, Any] = {}


class ResolveOutcomeRequest(BaseModel):
    """Request to resolve an outcome."""
    outcome_id: str
    actual_result: Any
    result: str  # correct, incorrect, partially_correct
    profit_impact: float = 0.0


class CreateAutopsyRequest(BaseModel):
    """Request to create a strategy autopsy."""
    strategy_id: str
    strategy_name: str
    start_date: float
    end_date: float
    outcome: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    max_drawdown: float = 0.0


# ═══════════════════════════════════════════════════════════════════
# OUTCOME SCORING ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@router.get("/outcomes/status")
async def get_outcome_status() -> Dict[str, Any]:
    """Get outcome scoring engine status."""
    from archive.outcome_scoring import get_outcome_scoring
    
    engine = get_outcome_scoring()
    return engine.get_status()


@router.get("/outcomes/leaderboard")
async def get_agent_leaderboard(min_outcomes: int = 10) -> Dict[str, Any]:
    """Get agent leaderboard by accuracy."""
    
    engine = get_outcome_scoring()
    return {"leaderboard": engine.get_leaderboard(min_outcomes)}


@router.get("/outcomes/agent/{agent_id}")
async def get_agent_scorecard(agent_id: str) -> Dict[str, Any]:
    """Get scorecard for an agent."""
    
    engine = get_outcome_scoring()
    scorecard = engine.get_agent_scorecard(agent_id)
    
    if not scorecard:
        return {"agent_id": agent_id, "message": "No outcomes recorded"}
    
    return scorecard.to_dict()


@router.get("/outcomes/agent/{agent_id}/history")
async def get_agent_outcome_history(
    agent_id: str,
    limit: int = 50,
    include_pending: bool = True,
) -> Dict[str, Any]:
    """Get outcome history for an agent."""
    
    engine = get_outcome_scoring()
    outcomes = engine.get_agent_outcomes(agent_id, limit, include_pending)
    
    return {
        "agent_id": agent_id,
        "outcomes": [o.to_dict() for o in outcomes],
    }


@router.get("/outcomes/pending")
async def get_pending_outcomes(max_age_hours: float = 24) -> Dict[str, Any]:
    """Get pending outcomes that need resolution."""
    
    engine = get_outcome_scoring()
    pending = engine.get_pending_outcomes(max_age_hours)
    
    return {
        "pending": [o.to_dict() for o in pending],
        "count": len(pending),
    }


@router.post("/outcomes/record")
async def record_outcome(request: RecordOutcomeRequest) -> Dict[str, Any]:
    """Record a new outcome to track."""
    from archive.outcome_scoring import get_outcome_scoring, OutcomeType
    
    try:
        outcome_type = OutcomeType(request.outcome_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid outcome type: {request.outcome_type}")
    
    engine = get_outcome_scoring()
    outcome = engine.record_outcome(
        agent_id=request.agent_id,
        outcome_type=outcome_type,
        prediction=request.prediction,
        confidence=request.confidence,
        symbol=request.symbol,
        context=request.context,
    )
    
    return outcome.to_dict()


@router.post("/outcomes/resolve")
async def resolve_outcome(request: ResolveOutcomeRequest) -> Dict[str, Any]:
    """Resolve an outcome with actual result."""
    from archive.outcome_scoring import get_outcome_scoring, OutcomeResult
    
    try:
        result = OutcomeResult(request.result)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid result: {request.result}")
    
    engine = get_outcome_scoring()
    outcome = engine.resolve_outcome(
        outcome_id=request.outcome_id,
        actual_result=request.actual_result,
        result=result,
        profit_impact=request.profit_impact,
    )
    
    if not outcome:
        raise HTTPException(status_code=404, detail=f"Outcome not found: {request.outcome_id}")
    
    return outcome.to_dict()


# ═══════════════════════════════════════════════════════════════════
# STRATEGY AUTOPSY ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@router.get("/autopsy/status")
async def get_autopsy_status() -> Dict[str, Any]:
    """Get strategy autopsy engine status."""
    from archive.strategy_autopsy import get_strategy_autopsy
    
    engine = get_strategy_autopsy()
    return engine.get_status()


@router.get("/autopsy/all")
async def get_all_autopsies(limit: int = 50) -> Dict[str, Any]:
    """Get all strategy autopsies."""
    
    engine = get_strategy_autopsy()
    return {"autopsies": engine.get_all_autopsies(limit)}


@router.get("/autopsy/{autopsy_id}")
async def get_autopsy(autopsy_id: str) -> Dict[str, Any]:
    """Get a specific autopsy."""
    
    engine = get_strategy_autopsy()
    autopsy = engine.get_autopsy(autopsy_id)
    
    if not autopsy:
        raise HTTPException(status_code=404, detail=f"Autopsy not found: {autopsy_id}")
    
    return autopsy.to_dict()


@router.get("/autopsy/strategy/{strategy_id}")
async def get_strategy_autopsies(strategy_id: str) -> Dict[str, Any]:
    """Get all autopsies for a strategy."""
    
    engine = get_strategy_autopsy()
    autopsies = engine.get_autopsies_by_strategy(strategy_id)
    
    return {
        "strategy_id": strategy_id,
        "autopsies": [a.to_dict() for a in autopsies],
    }


@router.get("/autopsy/category/{category}")
async def get_autopsies_by_category(category: str) -> Dict[str, Any]:
    """Get autopsies by failure category."""
    from archive.strategy_autopsy import get_strategy_autopsy, FailureCategory
    
    try:
        failure_category = FailureCategory(category)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid category: {category}")
    
    engine = get_strategy_autopsy()
    autopsies = engine.get_autopsies_by_category(failure_category)
    
    return {
        "category": category,
        "autopsies": [a.to_dict() for a in autopsies],
    }


@router.get("/autopsy/statistics")
async def get_failure_statistics() -> Dict[str, Any]:
    """Get failure statistics."""
    
    engine = get_strategy_autopsy()
    return engine.get_failure_statistics()


@router.get("/autopsy/lessons")
async def get_all_lessons() -> Dict[str, Any]:
    """Get all lessons learned."""
    
    engine = get_strategy_autopsy()
    return {"lessons": engine.get_all_lessons()}


@router.post("/autopsy/create")
async def create_autopsy(request: CreateAutopsyRequest) -> Dict[str, Any]:
    """Create a new strategy autopsy."""
    from archive.strategy_autopsy import (
        get_strategy_autopsy,
        StrategyOutcome,
        StrategyPerformance,
    )
    
    try:
        outcome = StrategyOutcome(request.outcome)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid outcome: {request.outcome}")
    
    performance = StrategyPerformance(
        total_trades=request.total_trades,
        winning_trades=request.winning_trades,
        losing_trades=request.losing_trades,
        gross_profit=request.gross_profit,
        gross_loss=request.gross_loss,
        max_drawdown=request.max_drawdown,
    )
    
    engine = get_strategy_autopsy()
    autopsy = engine.create_autopsy(
        strategy_id=request.strategy_id,
        strategy_name=request.strategy_name,
        start_date=request.start_date,
        end_date=request.end_date,
        outcome=outcome,
        performance=performance,
    )
    
    return autopsy.to_dict()


@router.post("/autopsy/{autopsy_id}/lesson")
async def add_lesson(autopsy_id: str, lesson: str) -> Dict[str, Any]:
    """Add a lesson to an autopsy."""
    
    engine = get_strategy_autopsy()
    success = engine.add_lesson(autopsy_id, lesson)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Autopsy not found: {autopsy_id}")
    
    return {"added": True, "lesson": lesson}


@router.post("/autopsy/{autopsy_id}/review")
async def mark_reviewed(autopsy_id: str, reviewer: str) -> Dict[str, Any]:
    """Mark an autopsy as reviewed."""
    
    engine = get_strategy_autopsy()
    success = engine.mark_reviewed(autopsy_id, reviewer)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Autopsy not found: {autopsy_id}")
    
    return {"reviewed": True, "reviewer": reviewer}


# ═══════════════════════════════════════════════════════════════════
# COMBINED STATUS ENDPOINT
# ═══════════════════════════════════════════════════════════════════

@router.get("/status")
async def get_archive_status() -> Dict[str, Any]:
    """Get combined ARCHIVE status."""
    
    outcomes = get_outcome_scoring()
    autopsy = get_strategy_autopsy()
    
    return {
        "outcome_scoring": outcomes.get_status(),
        "strategy_autopsy": autopsy.get_status(),
    }
