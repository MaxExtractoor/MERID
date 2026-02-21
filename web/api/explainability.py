"""
MERID Explainability API Endpoints
Constitutional requirement: Expose all explainability data via API
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query

from agents.explainability import get_explainability_tracker
from core.consensus_logging import get_consensus_logger
from core.trust_transparency import get_trust_manager
from core.error_handling import get_error_handler, get_health_monitor
from core.signal_provenance import get_provenance_tracker
from utils.logger import get_logger

logger = get_logger("web.api.explainability")

router = APIRouter(prefix="/api/v1/explainability", tags=["explainability"])


def _iso_from_unix_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _normalize_decision_for_dashboard(decision: Any) -> Dict[str, Any]:
    """Normalize tracker DecisionReasoning into dashboard ExplainabilityDecision shape."""
    supporting = list(getattr(decision, "supporting_factors", []) or [])
    contrary = list(getattr(decision, "contrary_factors", []) or [])
    total_factors = max(len(supporting) + len(contrary), 1)

    factors: List[Dict[str, Any]] = []
    for idx, text in enumerate(supporting):
        factors.append(
            {
                "name": f"supporting_{idx + 1}",
                "weight": round(1.0 / total_factors, 4),
                "value": 1.0,
                "impact": "positive",
                "explanation": text,
            }
        )
    for idx, text in enumerate(contrary):
        factors.append(
            {
                "name": f"contrary_{idx + 1}",
                "weight": round(1.0 / total_factors, 4),
                "value": 1.0,
                "impact": "negative",
                "explanation": text,
            }
        )

    ts = float(getattr(decision, "timestamp", 0.0) or 0.0)
    timestamp = _iso_from_unix_ts(ts) if ts > 0 else datetime.now(timezone.utc).isoformat()

    return {
        "id": str(getattr(decision, "decision_id", "")),
        "agent_name": str(getattr(decision, "agent_id", "unknown")),
        "decision": str(getattr(decision, "decision", "")),
        "action_taken": str(getattr(decision, "decision", "")),
        "timestamp": timestamp,
        "confidence": float(getattr(decision, "confidence", 0.0) or 0.0),
        "outcome": "pending",
        "reasoning": str(getattr(decision, "primary_reason", "")),
        "factors": factors,
        "alternatives": [],
        "data_sources": [
            {
                "name": str(source),
                "type": "signal",
                "reliability": 1.0,
                "timestamp": timestamp,
            }
            for source in (getattr(decision, "data_sources", []) or [])
        ],
        "execution_time_ms": float(getattr(decision, "processing_time_ms", 0.0) or 0.0),
    }


# ============================================================================
# AGENT DECISION EXPLAINABILITY
# ============================================================================

@router.get("/agents/{agent_id}/decisions")
async def get_agent_decisions(
    agent_id: str,
    limit: int = Query(50, ge=1, le=500)
) -> Dict[str, Any]:
    """Get recent decisions for an agent with full reasoning"""
    try:
        tracker = get_explainability_tracker()
        decisions = tracker.get_agent_decisions(agent_id, limit)
        
        return {
            "agent_id": agent_id,
            "total_decisions": len(decisions),
            "decisions": [d.to_dict() for d in decisions]
        }
    except Exception as e:
        logger.error(f"Error fetching agent decisions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agents/{agent_id}/decisions/{decision_id}")
async def get_decision_detail(
    agent_id: str,
    decision_id: str
) -> Dict[str, Any]:
    """Get detailed reasoning for a specific decision"""
    try:
        tracker = get_explainability_tracker()
        decision = tracker.get_decision_by_id(decision_id)
        
        if not decision:
            raise HTTPException(status_code=404, detail="Decision not found")
        
        if decision.agent_id != agent_id:
            raise HTTPException(status_code=400, detail="Decision does not belong to this agent")
        
        return {
            "decision": decision.to_dict(),
            "human_readable": decision.to_human_readable()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching decision detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/decisions/recent")
async def get_recent_decisions(
    limit: int = Query(100, ge=1, le=500)
) -> Dict[str, Any]:
    """Get recent decisions across all agents"""
    try:
        tracker = get_explainability_tracker()
        decisions = tracker.get_recent_decisions(limit)
        
        return {
            "total": len(decisions),
            "decisions": [d.to_dict() for d in decisions]
        }
    except Exception as e:
        logger.error(f"Error fetching recent decisions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/decisions")
async def get_decisions_for_dashboard(
    limit: int = Query(100, ge=1, le=500),
    agent: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Canonical dashboard endpoint used by ExplainabilityPanel.tsx.

    Returns normalized decision records with a stable schema expected by the UI.
    """
    try:
        tracker = get_explainability_tracker()
        raw_decisions = (
            tracker.get_agent_decisions(agent, limit)
            if agent
            else tracker.get_recent_decisions(limit)
        )

        # Newest-first for operator dashboard readability.
        normalized = [
            _normalize_decision_for_dashboard(d)
            for d in reversed(raw_decisions)
        ]
        return {
            "total": len(normalized),
            "decisions": normalized,
        }
    except Exception as exc:
        logger.error(f"Error fetching dashboard decisions: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/stats")
async def get_explainability_stats() -> Dict[str, Any]:
    """Get explainability system statistics"""
    try:
        tracker = get_explainability_tracker()
        return tracker.get_decision_stats()
    except Exception as e:
        logger.error(f"Error fetching explainability stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# PLAIN-LANGUAGE DECISION EXPLANATION (S5-03)
# ============================================================================

@router.get("/explain/{decision_id}")
async def explain_decision_plain_language(decision_id: str) -> Dict[str, Any]:
    """Return a human-readable, plain-language explanation for a decision.

    Converts structured ExplanationRecord into conversational English
    suitable for operator queries like "why did we take that trade?"
    """
    try:
        from core.explainability import get_explainability_service
        service = get_explainability_service()
        result = service.explain_plain_language(decision_id)

        if result is None:
            raise HTTPException(
                status_code=404,
                detail=f"No explanation found for decision_id={decision_id}",
            )

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating plain-language explanation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/explain/correlation/{correlation_id}")
async def explain_correlated_decisions(correlation_id: str) -> Dict[str, Any]:
    """Return plain-language explanations for all decisions sharing a correlation_id."""
    try:
        service = get_explainability_service()
        records = service.find_by_correlation_id(correlation_id)

        if not records:
            raise HTTPException(
                status_code=404,
                detail=f"No explanations found for correlation_id={correlation_id}",
            )

        explanations = []
        for record in records:
            if record.decision_id:
                expl = service.explain_plain_language(record.decision_id)
                if expl:
                    explanations.append(expl)

        return {
            "correlation_id": correlation_id,
            "total": len(explanations),
            "explanations": explanations,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating correlated explanations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# CONSENSUS TRANSPARENCY
# ============================================================================

@router.get("/consensus/rounds")
async def get_consensus_rounds(
    limit: int = Query(50, ge=1, le=200)
) -> Dict[str, Any]:
    """Get recent consensus rounds with full timeline"""
    try:
        consensus_logger = get_consensus_logger()
        rounds = consensus_logger.get_recent_rounds(limit)
        
        return {
            "total": len(rounds),
            "rounds": [r.to_dict() for r in rounds]
        }
    except Exception as e:
        logger.error(f"Error fetching consensus rounds: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/consensus/rounds/{round_id}")
async def get_consensus_round_detail(round_id: str) -> Dict[str, Any]:
    """Get detailed timeline for a specific consensus round"""
    try:
        consensus_logger = get_consensus_logger()
        round_timeline = consensus_logger.get_round(round_id)
        
        if not round_timeline:
            raise HTTPException(status_code=404, detail="Consensus round not found")
        
        return {
            "timeline": round_timeline.to_dict(),
            "human_readable": round_timeline.to_human_readable()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching consensus round detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/consensus/stats")
async def get_consensus_stats() -> Dict[str, Any]:
    """Get consensus system statistics"""
    try:
        consensus_logger = get_consensus_logger()
        return consensus_logger.get_consensus_stats()
    except Exception as e:
        logger.error(f"Error fetching consensus stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# TRUST TRANSPARENCY
# ============================================================================

@router.get("/trust/profiles")
async def get_all_trust_profiles() -> Dict[str, Any]:
    """Get trust profiles for all agents"""
    try:
        trust_manager = get_trust_manager()
        profiles = trust_manager.get_all_profiles()
        
        return {
            "total_agents": len(profiles),
            "profiles": [p.to_dict() for p in profiles]
        }
    except Exception as e:
        logger.error(f"Error fetching trust profiles: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trust/agents/{agent_id}/profile")
async def get_agent_trust_profile(agent_id: str) -> Dict[str, Any]:
    """Get complete trust profile for an agent"""
    try:
        trust_manager = get_trust_manager()
        profile = trust_manager.get_trust_profile(agent_id)
        
        if not profile:
            raise HTTPException(status_code=404, detail="Agent trust profile not found")
        
        return profile.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching trust profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trust/agents/{agent_id}/history")
async def get_agent_trust_history(
    agent_id: str,
    limit: int = Query(50, ge=1, le=200)
) -> Dict[str, Any]:
    """Get trust adjustment history for an agent"""
    try:
        trust_manager = get_trust_manager()
        history = trust_manager.get_adjustment_history(agent_id, limit)
        
        return {
            "agent_id": agent_id,
            "total_adjustments": len(history),
            "adjustments": [e.to_dict() for e in history]
        }
    except Exception as e:
        logger.error(f"Error fetching trust history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trust/stats")
async def get_trust_stats() -> Dict[str, Any]:
    """Get trust system statistics"""
    try:
        trust_manager = get_trust_manager()
        return trust_manager.get_trust_stats()
    except Exception as e:
        logger.error(f"Error fetching trust stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# HEALTH & ERROR MONITORING
# ============================================================================

@router.get("/health/system")
async def get_system_health() -> Dict[str, Any]:
    """Get overall system health status"""
    try:
        health_monitor = get_health_monitor()
        return health_monitor.get_system_health()
    except Exception as e:
        logger.error(f"Error fetching system health: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health/components")
async def get_component_health() -> Dict[str, Any]:
    """Get health status for all components"""
    try:
        health_monitor = get_health_monitor()
        system_health = health_monitor.get_system_health()
        return system_health.get("components", {})
    except Exception as e:
        logger.error(f"Error fetching component health: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/errors/stats")
async def get_error_stats() -> Dict[str, Any]:
    """Get error statistics"""
    try:
        error_handler = get_error_handler()
        return error_handler.get_error_stats()
    except Exception as e:
        logger.error(f"Error fetching error stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/errors/recent")
async def get_recent_errors(
    limit: int = Query(50, ge=1, le=200)
) -> Dict[str, Any]:
    """Get recent errors"""
    try:
        error_handler = get_error_handler()
        stats = error_handler.get_error_stats()
        recent = stats.get("recent_errors", [])
        
        return {
            "total": len(recent),
            "errors": recent[-limit:]
        }
    except Exception as e:
        logger.error(f"Error fetching recent errors: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# MEV DEFENSE MONITORING
# ============================================================================

@router.get("/mev/status")
async def get_mev_status() -> Dict[str, Any]:
    """Get MEV defense system status"""
    try:
        from trading.execution.defense import get_mev_defense
        mev_defender = get_mev_defense()
        return mev_defender.get_status()
    except Exception as e:
        logger.error(f"Error fetching MEV status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mev/heatmap/{symbol}")
async def get_mev_heatmap(symbol: str) -> Dict[str, Any]:
    """Get MEV intensity heatmap for a symbol"""
    try:
        mev_defender = get_mev_defense()
        return mev_defender.get_mev_summary(symbol)
    except Exception as e:
        logger.error(f"Error fetching MEV heatmap: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mev/events")
async def get_mev_events(
    limit: int = Query(50, ge=1, le=200)
) -> Dict[str, Any]:
    """Get recent MEV attack events"""
    try:
        mev_defender = get_mev_defense()
        
        front_running = mev_defender.front_running_detector.get_recent_events(limit)
        sandwich = mev_defender.sandwich_detector.get_recent_events(limit)
        
        return {
            "front_running_events": [e.to_dict() for e in front_running],
            "sandwich_events": [e.to_dict() for e in sandwich],
            "total_events": len(front_running) + len(sandwich)
        }
    except Exception as e:
        logger.error(f"Error fetching MEV events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# SIGNAL SYNTHESIS PROVENANCE
# ============================================================================

@router.get("/signals/syntheses")
async def get_signal_syntheses(
    limit: int = Query(50, ge=1, le=200)
) -> Dict[str, Any]:
    """Get recent signal syntheses with full provenance"""
    try:
        provenance_tracker = get_provenance_tracker()
        syntheses = provenance_tracker.get_recent_syntheses(limit)
        
        return {
            "total": len(syntheses),
            "syntheses": [s.to_dict() for s in syntheses]
        }
    except Exception as e:
        logger.error(f"Error fetching signal syntheses: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signals/syntheses/{synthesis_id}")
async def get_synthesis_detail(synthesis_id: str) -> Dict[str, Any]:
    """Get detailed provenance for a specific synthesis"""
    try:
        provenance_tracker = get_provenance_tracker()
        synthesis = provenance_tracker.get_synthesis(synthesis_id)
        
        if not synthesis:
            raise HTTPException(status_code=404, detail="Synthesis not found")
        
        return {
            "synthesis": synthesis.to_dict(),
            "human_readable": synthesis.to_human_readable()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching synthesis detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signals/stats")
async def get_signal_synthesis_stats() -> Dict[str, Any]:
    """Get signal synthesis statistics"""
    try:
        provenance_tracker = get_provenance_tracker()
        return provenance_tracker.get_synthesis_stats()
    except Exception as e:
        logger.error(f"Error fetching synthesis stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
