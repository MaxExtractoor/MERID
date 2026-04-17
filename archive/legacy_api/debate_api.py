"""
Strategic Debate Protocol API
Provides endpoints for debate session management, participant evaluation, and performance tracking.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

from web.api.auth import get_current_session

router = APIRouter(prefix="/api/v1/debate", tags=["debate"], dependencies=[Depends(get_current_session)])  # ZT6-01


# ── Response Models ────────────────────────────────────────────────────────

class DebateSessionResponse(BaseModel):
    """Debate session response."""
    id: str
    symbol: str
    status: str
    participant_ids: List[str]
    created_at: datetime
    started_at: Optional[datetime]
    closed_at: Optional[datetime]
    rounds_completed: int
    debate_lift: Optional[float]
    pre_debate_prob: Optional[float]
    post_debate_prob: Optional[float]


class DebateArgumentResponse(BaseModel):
    """Debate argument response."""
    id: str
    debate_id: str
    agent_id: str
    role: str
    content: str
    evidence: List[str]
    quality_score: Optional[float]
    created_at: datetime


class GateResultResponse(BaseModel):
    """Gate evaluation result response."""
    gate_name: str
    passed: bool
    score: float
    threshold: float
    recommendation: str
    details: Dict[str, float]


class GateSummaryResponse(BaseModel):
    """Gate evaluation summary response."""
    agent_id: str
    timestamp: datetime
    overall_passed: bool
    total_score: float
    blocked_reasons: List[str]
    gate_results: List[GateResultResponse]


class DebateMetricsResponse(BaseModel):
    """Debate performance metrics response."""
    debate_id: str
    created_at: datetime
    participants: List[str]
    rounds_completed: int
    arguments_count: int
    avg_argument_quality: float
    debate_lift: float
    consensus_improvement: float
    time_to_complete_minutes: float


class DebateLeaderboardResponse(BaseModel):
    """Debate leaderboard response."""
    agent_leaderboard: List[Dict[str, float]]
    team_leaderboard: List[Dict[str, float]]
    updated_at: datetime


# ── API Endpoints ────────────────────────────────────────────────────────

@router.get("/sessions", response_model=List[DebateSessionResponse])
async def list_debate_sessions(
    status: Optional[str] = Query(default=None, description="Filter by debate status"),
    symbol: Optional[str] = Query(default=None, description="Filter by trading symbol"),
    limit: int = Query(default=20, description="Maximum number of sessions to return")
):
    """
    List Kalshi prediction debate sessions with optional filtering.
    
    Args:
        status: Filter by debate status (open, active, closed, resolved)
        symbol: Filter by Kalshi prediction symbol
        limit: Maximum number of sessions to return
        
    Returns list of Kalshi debate sessions with participant and performance data.
    """
    try:
        from merid.prediction.debate import get_debate_store
        from merid.prediction.debate_orchestrator import get_debate_orchestrator
        
        store = get_debate_store()
        orchestrator = get_debate_orchestrator()
        
        # Get debates from store
        debates = store.list_debates(status=status, symbol=symbol, limit=limit)
        
        # Filter to Kalshi prediction domain only
        kalshi_debates = []
        for debate in debates:
            if orchestrator and orchestrator._is_kalshi_prediction_symbol(debate.symbol):
                kalshi_debates.append(debate)
        
        # Convert to response format
        session_responses = []
        for debate in kalshi_debates:
            response = DebateSessionResponse(
                id=debate.id,
                symbol=debate.symbol,
                status=debate.status,
                participant_ids=debate.participant_ids,
                created_at=datetime.fromtimestamp(debate.created_at, tz=timezone.utc),
                started_at=datetime.fromtimestamp(debate.started_at, tz=timezone.utc) if debate.started_at else None,
                closed_at=datetime.fromtimestamp(debate.closed_at, tz=timezone.utc) if debate.closed_at else None,
                rounds_completed=debate.rounds_completed or 0,
                debate_lift=debate.debate_lift,
                pre_debate_prob=debate.pre_debate_prob,
                post_debate_prob=debate.post_debate_prob
            )
            session_responses.append(response)
        
        return session_responses
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list Kalshi debate sessions: {str(e)}")


@router.get("/sessions/{debate_id}", response_model=DebateSessionResponse)
async def get_debate_session(debate_id: str):
    """
    Get detailed information about a specific Kalshi debate session.
    
    Args:
        debate_id: Unique identifier for the debate session
        
    Returns detailed Kalshi debate session information.
    """
    try:
        from merid.prediction.debate import get_debate_store
        from merid.prediction.debate_orchestrator import get_debate_orchestrator
        
        store = get_debate_store()
        orchestrator = get_debate_orchestrator()
        
        debate = store.get_debate(debate_id)
        if not debate:
            raise HTTPException(status_code=404, detail=f"Kalshi debate session {debate_id} not found")
        
        # Validate debate is in Kalshi prediction domain
        if orchestrator and not orchestrator._is_kalshi_prediction_symbol(debate.symbol):
            raise HTTPException(status_code=404, detail=f"Debate session {debate_id} not found in Kalshi prediction domain")
        
        return DebateSessionResponse(
            id=debate.id,
            symbol=debate.symbol,
            status=debate.status,
            participant_ids=debate.participant_ids,
            created_at=datetime.fromtimestamp(debate.created_at, tz=timezone.utc),
            started_at=datetime.fromtimestamp(debate.started_at, tz=timezone.utc) if debate.started_at else None,
            closed_at=datetime.fromtimestamp(debate.closed_at, tz=timezone.utc) if debate.closed_at else None,
            rounds_completed=debate.rounds_completed or 0,
            debate_lift=debate.debate_lift,
            pre_debate_prob=debate.pre_debate_prob,
            post_debate_prob=debate.post_debate_prob
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get Kalshi debate session: {str(e)}")


@router.get("/sessions/{debate_id}/arguments", response_model=List[DebateArgumentResponse])
async def get_debate_arguments(
    debate_id: str,
    agent_id: Optional[str] = Query(default=None, description="Filter by agent ID"),
    limit: int = Query(default=50, description="Maximum number of arguments to return")
):
    """
    Get arguments for a specific debate session.
    
    Args:
        debate_id: Unique identifier for the debate session
        agent_id: Optional filter for specific agent's arguments
        limit: Maximum number of arguments to return
        
    Returns list of debate arguments with content and metadata.
    """
    try:
        from merid.prediction.debate import get_debate_store
        store = get_debate_store()
        
        # Verify debate exists
        debate = store.get_debate(debate_id)
        if not debate:
            raise HTTPException(status_code=404, detail=f"Debate session {debate_id} not found")
        
        # Get arguments
        arguments = store.list_debate_arguments(debate_id, agent_id=agent_id, limit=limit)
        
        # Convert to response format
        argument_responses = []
        for arg in arguments:
            response = DebateArgumentResponse(
                id=arg.id,
                debate_id=arg.debate_id,
                agent_id=arg.agent_id,
                role=arg.role,
                content=arg.content,
                evidence=arg.evidence or [],
                quality_score=arg.quality_score,
                created_at=datetime.fromtimestamp(arg.created_at, tz=timezone.utc)
            )
            argument_responses.append(response)
        
        return argument_responses
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get debate arguments: {str(e)}")


@router.post("/agents/{agent_id}/evaluate", response_model=GateSummaryResponse)
async def evaluate_agent_gates(agent_id: str):
    """
    Evaluate an agent against quantitative debate participation gates.
    
    Args:
        agent_id: Unique identifier for the agent
        
    Returns comprehensive gate evaluation with pass/fail status and recommendations.
    """
    try:
        from merid.prediction.quantitative_gates import get_quantitative_gates
        from merid.prediction.debate_orchestrator import get_debate_orchestrator
        
        gates = get_quantitative_gates()
        orchestrator = get_debate_orchestrator()
        
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Debate orchestrator not available")
        
        # Collect agent data
        agent_data = await orchestrator._collect_agent_data(agent_id)
        if not agent_data:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found or no data available")
        
        # Evaluate against gates
        gate_summary = gates.evaluate_agent(agent_id, agent_data)
        
        # Convert gate results
        gate_results = []
        for result in gate_summary.gate_results:
            gate_result = GateResultResponse(
                gate_name=result.gate_name,
                passed=result.passed,
                score=result.score,
                threshold=result.threshold,
                recommendation=result.recommendation,
                details=result.details
            )
            gate_results.append(gate_result)
        
        return GateSummaryResponse(
            agent_id=gate_summary.agent_id,
            timestamp=gate_summary.timestamp,
            overall_passed=gate_summary.overall_passed,
            total_score=gate_summary.total_score,
            blocked_reasons=gate_summary.blocked_reasons,
            gate_results=gate_results
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to evaluate agent gates: {str(e)}")


@router.get("/sessions/{debate_id}/metrics", response_model=DebateMetricsResponse)
async def get_debate_metrics(debate_id: str):
    """
    Get comprehensive performance metrics for a debate session.
    
    Args:
        debate_id: Unique identifier for the debate session
        
    Returns detailed metrics including participation, quality, and consensus impact.
    """
    try:
        from merid.prediction.debate_orchestrator import get_debate_orchestrator
        
        orchestrator = get_debate_orchestrator()
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Debate orchestrator not available")
        
        # Calculate metrics
        metrics = await orchestrator._calculate_debate_metrics(debate_id)
        
        return DebateMetricsResponse(
            debate_id=metrics.debate_id,
            created_at=metrics.created_at,
            participants=metrics.participants,
            rounds_completed=metrics.rounds_completed,
            arguments_count=metrics.arguments_count,
            avg_argument_quality=metrics.avg_argument_quality,
            debate_lift=metrics.debate_lift,
            consensus_improvement=metrics.consensus_improvement,
            time_to_complete_minutes=metrics.time_to_complete_minutes
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get debate metrics: {str(e)}")


@router.get("/leaderboard", response_model=DebateLeaderboardResponse)
async def get_debate_leaderboard(
    limit: int = Query(default=20, description="Maximum number of entries per leaderboard"),
    decay_lambda: float = Query(default=0.0, description="Time decay factor for points")
):
    """
    Get debate performance leaderboards for agents and teams.
    
    Args:
        limit: Maximum number of entries per leaderboard
        decay_lambda: Time decay factor for historical points (0 = no decay)
        
    Returns agent and team leaderboards with points and rankings.
    """
    try:
        from merid.prediction.debate import get_debate_store
        store = get_debate_store()
        
        # Compute leaderboards
        leaderboard_data = store.compute_leaderboard(limit=limit, decay_lambda=decay_lambda)
        
        return DebateLeaderboardResponse(
            agent_leaderboard=leaderboard_data.get("agents", []),
            team_leaderboard=leaderboard_data.get("teams", []),
            updated_at=datetime.now(timezone.utc)
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get leaderboard: {str(e)}")


@router.get("/agents/{agent_id}/debates", response_model=List[DebateSessionResponse])
async def get_agent_debate_history(
    agent_id: str,
    limit: int = Query(default=20, description="Maximum number of debates to return")
):
    """
    Get Kalshi debate participation history for a specific agent.
    
    Args:
        agent_id: Unique identifier for the agent
        limit: Maximum number of debates to return
        
    Returns list of Kalshi debate sessions the agent participated in.
    """
    try:
        from merid.prediction.debate import get_debate_store
        from merid.prediction.debate_orchestrator import get_debate_orchestrator
        
        store = get_debate_store()
        orchestrator = get_debate_orchestrator()
        
        # Get agent's debate history
        debates = store.list_agent_debates(agent_id, limit=limit)
        
        # Filter to Kalshi prediction domain only
        kalshi_debates = []
        for debate in debates:
            if orchestrator and orchestrator._is_kalshi_prediction_symbol(debate.symbol):
                kalshi_debates.append(debate)
        
        # Convert to response format
        session_responses = []
        for debate in kalshi_debates:
            response = DebateSessionResponse(
                id=debate.id,
                symbol=debate.symbol,
                status=debate.status,
                participant_ids=debate.participant_ids,
                created_at=datetime.fromtimestamp(debate.created_at, tz=timezone.utc),
                started_at=datetime.fromtimestamp(debate.started_at, tz=timezone.utc) if debate.started_at else None,
                closed_at=datetime.fromtimestamp(debate.closed_at, tz=timezone.utc) if debate.closed_at else None,
                rounds_completed=debate.rounds_completed or 0,
                debate_lift=debate.debate_lift,
                pre_debate_prob=debate.pre_debate_prob,
                post_debate_prob=debate.post_debate_prob
            )
            session_responses.append(response)
        
        return session_responses
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get agent Kalshi debate history: {str(e)}")


@router.get("/opportunities", response_model=List[str])
async def get_debate_opportunities(
    limit: int = Query(default=10, description="Maximum number of opportunities to return")
):
    """
    Get Kalshi prediction instruments that would benefit from debate due to high disagreement.
    
    Args:
        limit: Maximum number of opportunities to return
        
    Returns list of Kalshi prediction symbols with high disagreement scores.
    """
    try:
        from consensus.taco_consensus import get_consensus_coordinator
        from merid.prediction.debate_orchestrator import get_debate_orchestrator
        
        coordinator = get_consensus_coordinator()
        orchestrator = get_debate_orchestrator()
        opportunities = []
        
        # Find symbols with high disagreement (Kalshi prediction domain only)
        for symbol, opinions in getattr(coordinator, '_opinions', {}).items():
            if len(opinions) >= 3:  # Minimum opinions for meaningful debate
                # Validate symbol is in Kalshi prediction domain
                if orchestrator and not orchestrator._is_kalshi_prediction_symbol(symbol):
                    continue
                    
                # Calculate opinion variance
                scores = [op.score for op in opinions]
                if len(scores) > 1:
                    variance = sum((s - sum(scores)/len(scores))**2 for s in scores) / len(scores)
                    if variance > 0.1:  # High disagreement threshold
                        opportunities.append(symbol)
                        if len(opportunities) >= limit:
                            break
        
        return opportunities
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get Kalshi debate opportunities: {str(e)}")


@router.get("/status")
async def get_debate_system_status():
    """
    Get overall status of the debate system.
    
    Returns system health, active sessions, and configuration information.
    """
    try:
        from merid.prediction.debate_orchestrator import get_debate_orchestrator
        from merid.prediction.debate import get_debate_store
        
        orchestrator = get_debate_orchestrator()
        store = get_debate_store()
        
        # Get system metrics
        active_sessions = len(orchestrator.active_sessions) if orchestrator else 0
        pending_invitations = sum(len(invites) for invites in orchestrator.pending_invitations.values()) if orchestrator else 0
        
        # Get debate statistics
        debate_stats = store.get_debate_statistics()
        
        return {
            "status": "healthy" if orchestrator and orchestrator._running else "stopped",
            "orchestrator_running": orchestrator._running if orchestrator else False,
            "active_sessions": active_sessions,
            "pending_invitations": pending_invitations,
            "total_debates": debate_stats.get("total_debates", 0),
            "resolved_debates": debate_stats.get("resolved_debates", 0),
            "avg_debate_lift": debate_stats.get("avg_debate_lift", 0.0),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


@router.post("/sessions/{debate_id}/arguments")
async def submit_debate_argument(
    debate_id: str,
    agent_id: str,
    content: str,
    role: str = "participant",
    evidence: List[str] = []
):
    """
    Submit an argument to an active debate session.
    
    Args:
        debate_id: Unique identifier for the debate session
        agent_id: Agent submitting the argument
        content: Argument content
        role: Argument role (proposer, challenger, arbiter)
        evidence: List of evidence citations
        
    Creates and stores the argument in the debate session.
    """
    try:
        from merid.prediction.debate import get_debate_store, DebateArgument
        
        store = get_debate_store()
        
        # Verify debate exists and is active
        debate = store.get_debate(debate_id)
        if not debate:
            raise HTTPException(status_code=404, detail=f"Debate session {debate_id} not found")
        
        if debate.status != "active":
            raise HTTPException(status_code=400, detail=f"Debate {debate_id} is not active")
        
        if agent_id not in debate.participant_ids:
            raise HTTPException(status_code=403, detail=f"Agent {agent_id} not a participant in debate {debate_id}")
        
        # Create argument
        argument = DebateArgument(
            debate_id=debate_id,
            agent_id=agent_id,
            role=role,
            content=content,
            evidence=evidence,
            created_at=time.time()
        )
        
        # Store argument
        store.create_argument(argument)
        
        return {
            "message": "Argument submitted successfully",
            "argument_id": argument.id,
            "debate_id": debate_id,
            "agent_id": agent_id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to submit argument: {str(e)}")
