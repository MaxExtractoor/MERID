"""
Agents Health API Endpoint

Provides health and status information for all active agents in the system.
"""

from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException

from utils.logger import get_logger

logger = get_logger("web.api.agents_health")

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


@router.get("/health")
async def get_agents_health() -> Dict[str, Any]:
    """
    Get health status of all agents.
    
    Returns:
        {
            "agents": [
                {
                    "id": str,
                    "name": str,
                    "role": str,
                    "strategy": str,
                    "cluster": str,
                    "status": "ONLINE" | "DEGRADED" | "OFFLINE",
                    "cpuPercent": float,
                    "memoryMb": float,
                    "taskCount": int,
                    "latencyMs": float | null,
                    "lastSeen": str (ISO timestamp)
                }
            ],
            "meta": {
                "total": int,
                "online": int,
                "degraded": int,
                "offline": int
            }
        }
    """
    try:
        from core.agent_orchestrator import get_agent_orchestrator
        
        orchestrator = get_agent_orchestrator()
        agent_status = orchestrator.get_agent_status()
        
        # Transform to expected format
        agents = []
        for agent_id, status in agent_status.items():
            agents.append({
                "id": agent_id,
                "name": status.get("name", agent_id),
                "role": status.get("role", "UNKNOWN"),
                "strategy": status.get("strategy", "UNKNOWN"),
                "cluster": status.get("cluster", "default"),
                "status": status.get("status", "UNKNOWN"),
                "cpuPercent": status.get("cpu_percent", 0.0),
                "memoryMb": status.get("memory_mb", 0.0),
                "taskCount": status.get("task_count", 0),
                "latencyMs": status.get("latency_ms"),
                "lastSeen": status.get("last_seen", "")
            })
        
        # Calculate meta
        meta = {
            "total": len(agents),
            "online": sum(1 for a in agents if a["status"] == "ONLINE"),
            "degraded": sum(1 for a in agents if a["status"] == "DEGRADED"),
            "offline": sum(1 for a in agents if a["status"] == "OFFLINE")
        }
        
        return {
            "agents": agents,
            "meta": meta
        }
        
    except Exception as e:
        logger.error(f"Failed to get agents health: {e}")
        raise HTTPException(status_code=500, detail=str(e))
