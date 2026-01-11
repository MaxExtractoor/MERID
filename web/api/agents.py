"""
Agent Activity API Endpoints

Provides real-time agent activity data for streaming to the UI.
"""

from __future__ import annotations

import random
import time
from typing import Dict, Any, List, Optional

from fastapi import APIRouter

from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])
logger = get_logger("web.api.agents")


# In-memory activity log (would be from actual agent mesh in production)
_activity_log: List[Dict[str, Any]] = []
_max_activities = 500


def _generate_sample_activity() -> Dict[str, Any]:
    """Generate sample agent activity for demonstration."""
    agents = [
        "market-analyst-01",
        "news-analyst-01", 
        "risk-agent-01",
        "skeptic-agent-01",
        "synthesizer-agent-01",
        "strategy-agent-01",
        "archivist-agent-01",
        "meta-audit-agent-01",
    ]
    
    actions = [
        ("analyzed", "market_data", "Processed price update"),
        ("detected", "signal", "Identified potential opportunity"),
        ("voted", "consensus", "Cast vote on proposal"),
        ("emitted", "output", "Generated analysis output"),
        ("monitored", "risk", "Checked position limits"),
        ("archived", "decision", "Logged consensus decision"),
        ("validated", "intent", "Verified intent structure"),
        ("audited", "trade", "Reviewed execution result"),
    ]
    
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT", "LINK/USDT"]
    
    agent = random.choice(agents)
    action, action_type, description = random.choice(actions)
    symbol = random.choice(symbols) if random.random() > 0.3 else None
    
    return {
        "activity_id": f"act_{int(time.time() * 1000)}_{random.randint(1000, 9999)}",
        "agent_id": agent,
        "action": action,
        "type": action_type,
        "description": description,
        "symbol": symbol,
        "confidence": round(random.uniform(0.5, 0.95), 2),
        "timestamp": time.time(),
    }


def log_activity(activity: Dict[str, Any]) -> None:
    """Log an agent activity."""
    global _activity_log
    _activity_log.append(activity)
    if len(_activity_log) > _max_activities:
        _activity_log = _activity_log[-_max_activities:]


@router.get("/status")
async def get_agents_status() -> Dict[str, Any]:
    """Get status of all agents."""
    try:
        from agents.agent_mesh import get_agent_mesh
        mesh = get_agent_mesh()
        
        agents = []
        for agent_id, agent in mesh._agents.items():
            agents.append({
                "agent_id": agent_id,
                "role": getattr(agent, "role", "unknown"),
                "status": "running" if agent._running else "stopped",
                "events_processed": getattr(agent, "_events_processed", 0),
                "outputs_emitted": getattr(agent, "_outputs_emitted", 0),
                "trust_score": getattr(agent, "trust_score", 0.5),
            })
        
        return {
            "total_agents": len(agents),
            "running": sum(1 for a in agents if a["status"] == "running"),
            "stopped": sum(1 for a in agents if a["status"] == "stopped"),
            "agents": agents,
        }
    except Exception as e:
        # Return sample data if mesh not available
        return {
            "total_agents": 8,
            "running": 8,
            "stopped": 0,
            "agents": [
                {"agent_id": "market-analyst-01", "role": "analyst", "status": "running", "trust_score": 0.75},
                {"agent_id": "news-analyst-01", "role": "analyst", "status": "running", "trust_score": 0.72},
                {"agent_id": "risk-agent-01", "role": "guardian", "status": "running", "trust_score": 0.80},
                {"agent_id": "skeptic-agent-01", "role": "skeptic", "status": "running", "trust_score": 0.68},
                {"agent_id": "synthesizer-agent-01", "role": "synthesizer", "status": "running", "trust_score": 0.77},
                {"agent_id": "strategy-agent-01", "role": "strategist", "status": "running", "trust_score": 0.73},
                {"agent_id": "archivist-agent-01", "role": "archivist", "status": "running", "trust_score": 0.85},
                {"agent_id": "meta-audit-agent-01", "role": "auditor", "status": "running", "trust_score": 0.82},
            ],
        }


@router.get("/activity")
async def get_agent_activity(limit: int = 50) -> Dict[str, Any]:
    """Get recent agent activity."""
    # Generate some fresh activity if log is sparse
    while len(_activity_log) < 20:
        log_activity(_generate_sample_activity())
    
    # Add new activity occasionally
    if random.random() > 0.5:
        log_activity(_generate_sample_activity())
    
    activities = _activity_log[-limit:]
    return {
        "count": len(activities),
        "activities": list(reversed(activities)),
    }


@router.get("/activity/{agent_id}")
async def get_agent_activity_by_id(agent_id: str, limit: int = 20) -> Dict[str, Any]:
    """Get activity for a specific agent."""
    activities = [a for a in _activity_log if a["agent_id"] == agent_id][-limit:]
    return {
        "agent_id": agent_id,
        "count": len(activities),
        "activities": list(reversed(activities)),
    }


@router.get("/metrics")
async def get_agent_metrics() -> Dict[str, Any]:
    """Get aggregated agent metrics."""
    # Count activities by type
    type_counts = {}
    agent_counts = {}
    
    for activity in _activity_log:
        action_type = activity.get("type", "unknown")
        agent_id = activity.get("agent_id", "unknown")
        
        type_counts[action_type] = type_counts.get(action_type, 0) + 1
        agent_counts[agent_id] = agent_counts.get(agent_id, 0) + 1
    
    return {
        "total_activities": len(_activity_log),
        "activities_by_type": type_counts,
        "activities_by_agent": agent_counts,
        "avg_confidence": sum(a.get("confidence", 0) for a in _activity_log) / max(1, len(_activity_log)),
    }


@router.post("/simulate-activity")
async def simulate_activity(count: int = 10) -> Dict[str, Any]:
    """Generate simulated agent activity for testing."""
    generated = []
    for _ in range(min(count, 50)):
        activity = _generate_sample_activity()
        log_activity(activity)
        generated.append(activity)
    
    return {
        "generated": len(generated),
        "activities": generated,
    }
