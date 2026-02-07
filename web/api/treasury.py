"""
Treasury API Endpoints - Phase 22

Full treasury automation with yield strategies, drawdown governance,
auto-rebalancing, and emergency unwind capabilities.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from treasury import (
    get_yield_registry,
    get_strategy_competition,
    get_simulation_sandbox,
    get_drawdown_governor,
    get_auto_rebalancer,
    get_emergency_unwind,
    RiskTier,
    YieldProtocol,
    DrawdownLimits,
)
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/treasury", tags=["treasury"])
logger = get_logger("web.api.treasury")


class UpdateApyRequest(BaseModel):
    source_id: str
    new_apy: float


class RunCompetitionRequest(BaseModel):
    target_allocation_usd: float
    max_risk_tier: str = "tier_3_medium"


class VoteRequest(BaseModel):
    proposal_id: str
    voter_id: str
    vote: float  # -1 to 1


class SimulateStrategyRequest(BaseModel):
    strategy_id: str
    duration_days: int = 365
    monte_carlo_runs: int = 1000


class UpdateValueRequest(BaseModel):
    current_value_usd: float


class RecordPnlRequest(BaseModel):
    pnl_usd: float


class SetLimitsRequest(BaseModel):
    caution_pct: Optional[float] = None
    warning_pct: Optional[float] = None
    critical_pct: Optional[float] = None
    emergency_pct: Optional[float] = None
    max_daily_loss_pct: Optional[float] = None
    max_weekly_loss_pct: Optional[float] = None
    max_monthly_loss_pct: Optional[float] = None


class CheckDriftRequest(BaseModel):
    target_allocations: Dict[str, float]
    current_allocations: Dict[str, float]


class RebalanceRequest(BaseModel):
    target_allocations: Dict[str, float]
    current_allocations: Dict[str, float]
    total_value_usd: float
    estimated_cost_usd: float = 0.0


class QueueUnwindRequest(BaseModel):
    source_id: str
    protocol: str
    amount_usd: float
    risk_tier: str
    urgency: str = "normal"
    reason: str = ""


class CompleteUnwindRequest(BaseModel):
    unwind_id: str
    actual_amount_usd: float
    slippage_pct: float


# ============================================
# YIELD SOURCES
# ============================================

@router.get("/yield/sources")
async def get_yield_sources() -> Dict[str, Any]:
    """Get all yield sources."""
    sources = get_yield_registry().get_all_sources()
    return {
        "count": len(sources),
        "sources": [s.to_dict() for s in sources],
    }


@router.get("/yield/sources/top")
async def get_top_yield_sources(
    limit: int = 10,
    risk_adjusted: bool = True,
) -> Dict[str, Any]:
    """Get top yield sources by APY."""
    sources = get_yield_registry().get_top_sources(limit=limit, risk_adjusted=risk_adjusted)
    return {
        "count": len(sources),
        "risk_adjusted": risk_adjusted,
        "sources": [s.to_dict() for s in sources],
    }


@router.get("/yield/sources/by-risk/{risk_tier}")
async def get_sources_by_risk(risk_tier: str) -> Dict[str, Any]:
    """Get yield sources by risk tier."""
    try:
        tier = RiskTier(risk_tier)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid risk tier: {risk_tier}")
    
    sources = get_yield_registry().get_sources_by_risk(tier)
    return {
        "risk_tier": risk_tier,
        "count": len(sources),
        "sources": [s.to_dict() for s in sources],
    }


@router.get("/yield/sources/by-asset/{asset}")
async def get_sources_by_asset(asset: str) -> Dict[str, Any]:
    """Get yield sources by asset."""
    sources = get_yield_registry().get_sources_by_asset(asset)
    return {
        "asset": asset,
        "count": len(sources),
        "sources": [s.to_dict() for s in sources],
    }


@router.post("/yield/sources/update-apy")
async def update_source_apy(request: UpdateApyRequest) -> Dict[str, Any]:
    """Update APY for a yield source."""
    get_yield_registry().update_apy(request.source_id, request.new_apy)
    return {"status": "updated", "source_id": request.source_id, "new_apy": request.new_apy}


# ============================================
# STRATEGY COMPETITION
# ============================================

@router.get("/competition/agents")
async def get_yield_agents() -> Dict[str, Any]:
    """Get all yield strategy agents."""
    agents = get_strategy_competition().get_agents()
    return {
        "count": len(agents),
        "agents": [a.to_dict() for a in agents],
    }


@router.get("/competition/proposals")
async def get_proposals() -> Dict[str, Any]:
    """Get active strategy proposals."""
    proposals = get_strategy_competition().get_proposals()
    return {
        "count": len(proposals),
        "proposals": [p.to_dict() for p in proposals],
    }


@router.post("/competition/run")
async def run_competition(request: RunCompetitionRequest) -> Dict[str, Any]:
    """Run a strategy competition round."""
    try:
        max_tier = RiskTier(request.max_risk_tier)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid risk tier: {request.max_risk_tier}")
    
    proposals = get_strategy_competition().run_competition(
        registry=get_yield_registry(),
        target_allocation_usd=request.target_allocation_usd,
        max_risk_tier=max_tier,
    )
    
    return {
        "proposals_generated": len(proposals),
        "proposals": [p.to_dict() for p in proposals],
    }


@router.post("/competition/vote")
async def vote_on_proposal(request: VoteRequest) -> Dict[str, Any]:
    """Vote on a strategy proposal."""
    success = get_strategy_competition().vote_on_proposal(
        proposal_id=request.proposal_id,
        voter_id=request.voter_id,
        vote=request.vote,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return {"status": "voted", "proposal_id": request.proposal_id}


@router.get("/competition/winner")
async def get_winning_proposal() -> Dict[str, Any]:
    """Get the winning proposal."""
    winner = get_strategy_competition().get_winning_proposal()
    if not winner:
        return {"winner": None}
    return {"winner": winner.to_dict()}


@router.post("/competition/accept/{proposal_id}")
async def accept_proposal(proposal_id: str) -> Dict[str, Any]:
    """Accept a strategy proposal."""
    success = get_strategy_competition().accept_proposal(proposal_id)
    if not success:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return {"status": "accepted", "proposal_id": proposal_id}


# ============================================
# SIMULATION SANDBOX
# ============================================

@router.post("/simulation/run")
async def simulate_strategy(request: SimulateStrategyRequest) -> Dict[str, Any]:
    """Simulate a yield strategy."""
    # Find the strategy
    proposals = get_strategy_competition().get_proposals()
    strategy = None
    for p in proposals:
        if p.strategy.strategy_id == request.strategy_id:
            strategy = p.strategy
            break
    
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    result = get_simulation_sandbox().simulate_strategy(
        strategy=strategy,
        duration_days=request.duration_days,
        monte_carlo_runs=request.monte_carlo_runs,
    )
    
    return result


@router.get("/simulation/{simulation_id}")
async def get_simulation(simulation_id: str) -> Dict[str, Any]:
    """Get simulation results."""
    result = get_simulation_sandbox().get_simulation(simulation_id)
    if not result:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return result


# ============================================
# DRAWDOWN GOVERNOR
# ============================================

@router.get("/drawdown/status")
async def get_drawdown_status() -> Dict[str, Any]:
    """Get drawdown governor status."""
    return get_drawdown_governor().get_status()


@router.post("/drawdown/update-value")
async def update_treasury_value(request: UpdateValueRequest) -> Dict[str, Any]:
    """Update current treasury value and check drawdown."""
    action = get_drawdown_governor().update_value(request.current_value_usd)
    return {
        "action": action.value,
        "status": get_drawdown_governor().get_status(),
    }


@router.post("/drawdown/record-pnl")
async def record_pnl(request: RecordPnlRequest) -> Dict[str, Any]:
    """Record PnL for time-based limits."""
    get_drawdown_governor().record_pnl(request.pnl_usd)
    time_ok, violations = get_drawdown_governor().check_time_limits()
    return {
        "recorded": True,
        "time_limits_ok": time_ok,
        "violations": violations,
    }


@router.post("/drawdown/set-limits")
async def set_drawdown_limits(request: SetLimitsRequest) -> Dict[str, Any]:
    """Set drawdown limits."""
    gov = get_drawdown_governor()
    
    if request.caution_pct is not None:
        gov.limits.caution_pct = request.caution_pct
    if request.warning_pct is not None:
        gov.limits.warning_pct = request.warning_pct
    if request.critical_pct is not None:
        gov.limits.critical_pct = request.critical_pct
    if request.emergency_pct is not None:
        gov.limits.emergency_pct = request.emergency_pct
    if request.max_daily_loss_pct is not None:
        gov.limits.max_daily_loss_pct = request.max_daily_loss_pct
    if request.max_weekly_loss_pct is not None:
        gov.limits.max_weekly_loss_pct = request.max_weekly_loss_pct
    if request.max_monthly_loss_pct is not None:
        gov.limits.max_monthly_loss_pct = request.max_monthly_loss_pct
    
    return {"status": "updated", "limits": gov.limits.to_dict()}


@router.post("/drawdown/pause")
async def pause_treasury(reason: str) -> Dict[str, Any]:
    """Pause treasury operations."""
    get_drawdown_governor().pause(reason)
    return {"status": "paused", "reason": reason}


@router.post("/drawdown/resume")
async def resume_treasury(approval: str) -> Dict[str, Any]:
    """Resume treasury operations."""
    success = get_drawdown_governor().resume(approval)
    if not success:
        raise HTTPException(status_code=403, detail="Approval required")
    return {"status": "resumed"}


@router.post("/drawdown/reset-peak")
async def reset_peak(new_peak: Optional[float] = None) -> Dict[str, Any]:
    """Reset peak value."""
    get_drawdown_governor().reset_peak(new_peak)
    return {"status": "reset", "new_peak": get_drawdown_governor()._peak_value_usd}


# ============================================
# AUTO-REBALANCER
# ============================================

@router.get("/rebalancer/status")
async def get_rebalancer_status() -> Dict[str, Any]:
    """Get auto-rebalancer status."""
    return get_auto_rebalancer().get_status()


@router.post("/rebalancer/check-drift")
async def check_allocation_drift(request: CheckDriftRequest) -> Dict[str, Any]:
    """Check if allocations have drifted."""
    needs_rebalance, drifts = get_auto_rebalancer().check_drift(
        target_allocations=request.target_allocations,
        current_allocations=request.current_allocations,
    )
    return {
        "needs_rebalance": needs_rebalance,
        "drifts": drifts,
    }


@router.post("/rebalancer/calculate")
async def calculate_rebalance(request: RebalanceRequest) -> Dict[str, Any]:
    """Calculate rebalance trades needed."""
    trades = get_auto_rebalancer().calculate_rebalance(
        target_allocations=request.target_allocations,
        current_allocations=request.current_allocations,
        total_value_usd=request.total_value_usd,
    )
    return {
        "trades": trades,
        "trade_count": len(trades),
    }


@router.post("/rebalancer/execute")
async def execute_rebalance(request: RebalanceRequest) -> Dict[str, Any]:
    """Execute rebalance."""
    can_rebal, reason = get_auto_rebalancer().can_rebalance()
    if not can_rebal:
        raise HTTPException(status_code=400, detail=reason)
    
    trades = get_auto_rebalancer().calculate_rebalance(
        target_allocations=request.target_allocations,
        current_allocations=request.current_allocations,
        total_value_usd=request.total_value_usd,
    )
    
    result = get_auto_rebalancer().execute_rebalance(
        trades=trades,
        estimated_cost_usd=request.estimated_cost_usd,
        total_value_usd=request.total_value_usd,
    )
    
    return result


# ============================================
# EMERGENCY UNWIND
# ============================================

@router.get("/unwind/status")
async def get_unwind_status() -> Dict[str, Any]:
    """Get emergency unwind status."""
    return get_emergency_unwind().get_status()


@router.post("/unwind/queue")
async def queue_unwind(request: QueueUnwindRequest) -> Dict[str, Any]:
    """Queue a position for unwinding."""
    unwind_id = get_emergency_unwind().queue_unwind(
        source_id=request.source_id,
        protocol=request.protocol,
        amount_usd=request.amount_usd,
        risk_tier=request.risk_tier,
        urgency=request.urgency,
        reason=request.reason,
    )
    return {"status": "queued", "unwind_id": unwind_id}


@router.get("/unwind/next")
async def get_next_unwind() -> Dict[str, Any]:
    """Get next position to unwind."""
    unwind = get_emergency_unwind().get_next_unwind()
    if not unwind:
        return {"next": None}
    return {"next": unwind}


@router.post("/unwind/complete")
async def complete_unwind(request: CompleteUnwindRequest) -> Dict[str, Any]:
    """Mark unwind as complete."""
    success = get_emergency_unwind().complete_unwind(
        unwind_id=request.unwind_id,
        actual_amount_usd=request.actual_amount_usd,
        slippage_pct=request.slippage_pct,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Unwind not found")
    return {"status": "completed", "unwind_id": request.unwind_id}


@router.post("/unwind/emergency-all")
async def emergency_unwind_all(reason: str) -> Dict[str, Any]:
    """Queue emergency unwind for all positions."""
    unwind_ids = get_emergency_unwind().emergency_unwind_all(reason)
    return {"status": "queued", "unwind_ids": unwind_ids, "reason": reason}


# ============================================
# COMBINED STATUS
# ============================================

@router.get("/status")
async def get_treasury_status() -> Dict[str, Any]:
    """Get complete treasury status."""
    return {
        "yield_sources": len(get_yield_registry().get_all_sources()),
        "top_sources": [s.to_dict() for s in get_yield_registry().get_top_sources(5)],
        "active_agents": len(get_strategy_competition().get_agents()),
        "active_proposals": len(get_strategy_competition().get_proposals()),
        "drawdown": get_drawdown_governor().get_status(),
        "rebalancer": get_auto_rebalancer().get_status(),
        "unwind_queue": get_emergency_unwind().get_status(),
    }
