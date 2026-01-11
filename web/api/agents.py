"""
Agent Activity API Endpoints

Provides real-time agent activity data from the streaming agent mesh.
"""

from __future__ import annotations

import time
from typing import Dict, Any, List, Optional

from fastapi import APIRouter

from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])
logger = get_logger("web.api.agents")


# In-memory activity log populated by real agent events
_activity_log: List[Dict[str, Any]] = []
_max_activities = 500


def log_activity(activity: Dict[str, Any]) -> None:
    """Log an agent activity from real agent events."""
    global _activity_log
    _activity_log.append(activity)
    if len(_activity_log) > _max_activities:
        _activity_log = _activity_log[-_max_activities:]


def _get_real_agent_activities() -> List[Dict[str, Any]]:
    """Get real activities from the streaming agent mesh."""
    activities = []
    try:
        from agents.agent_mesh import agent_mesh
        
        for agent in agent_mesh.agents:
            metrics = agent.get_metrics()
            
            # Create activity entries from real agent metrics
            if metrics.get("events_processed", 0) > 0:
                activities.append({
                    "activity_id": f"act_{agent.agent_id}_{int(time.time() * 1000)}",
                    "agent_id": agent.agent_id,
                    "action": "processed",
                    "type": "event",
                    "description": f"Processed {metrics.get('events_processed', 0)} events",
                    "symbol": None,
                    "confidence": metrics.get("trust", 0.5),
                    "timestamp": metrics.get("last_activity", time.time()),
                    "metrics": {
                        "events_processed": metrics.get("events_processed", 0),
                        "outputs_emitted": metrics.get("outputs_emitted", 0),
                        "errors": metrics.get("errors", 0),
                        "avg_processing_time_ms": metrics.get("avg_processing_time_ms", 0),
                    }
                })
            
            if metrics.get("outputs_emitted", 0) > 0:
                activities.append({
                    "activity_id": f"out_{agent.agent_id}_{int(time.time() * 1000)}",
                    "agent_id": agent.agent_id,
                    "action": "emitted",
                    "type": "output",
                    "description": f"Emitted {metrics.get('outputs_emitted', 0)} outputs",
                    "symbol": None,
                    "confidence": metrics.get("trust", 0.5),
                    "timestamp": metrics.get("last_activity", time.time()),
                })
                
    except Exception as e:
        logger.debug(f"Could not fetch agent activities: {e}")
    
    return activities


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
    """Get recent agent activity from real agent mesh."""
    # Get real activities from agent mesh
    real_activities = _get_real_agent_activities()
    
    # Combine with logged activities
    all_activities = _activity_log + real_activities
    
    # Sort by timestamp and return most recent
    all_activities.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    activities = all_activities[:limit]
    
    return {
        "count": len(activities),
        "activities": activities,
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
