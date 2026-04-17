"""Real-time agent data endpoints - NO MOCK DATA."""

import time
import os
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime

# BUG-L13 FIX: Skip agent mesh entirely in VALIDATION_MODE to prevent startup lag
_is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
if _is_validation:
    # In validation mode, don't import agent_mesh at all
    agent_mesh = None
else:
    from agents.agent_mesh import agent_mesh

from core.agent_orchestrator import get_agent_orchestrator
from web.api.auth import get_current_session
from utils.logger import get_logger

router = APIRouter(dependencies=[Depends(get_current_session)])  # ZT6-02
logger = get_logger("api.agents_real")


@router.get("/api/agents/{agent_id}")
async def get_agent_detail(agent_id: str) -> Dict[str, Any]:
    """
    Get detailed metrics for a specific agent.
    
    Returns real-time performance data, decision history, and health metrics.
    """
    # BUG-L13 FIX: Return empty in VALIDATION_MODE
    if agent_mesh is None:
        raise HTTPException(status_code=503, detail="Agent mesh disabled in validation mode")
    
    try:
        # Find the agent in the mesh
        target_agent = None
        for agent in agent_mesh.agents:
            if getattr(agent, 'agent_id', None) == agent_id:
                target_agent = agent
                break
        
        if not target_agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        
        # Get comprehensive metrics
        metrics = target_agent.get_metrics() if hasattr(target_agent, 'get_metrics') else {}
        
        # Get agent state
        state = getattr(target_agent, 'state', None)
        is_running = getattr(target_agent, 'running', False)
        
        # Get decision history if available
        decisions = []
        if hasattr(target_agent, '_prediction_history'):
            decisions = target_agent._prediction_history[-10:]  # Last 10 decisions
        
        # Get performance metrics
        performance = {
            "tasks_completed": metrics.get('tasks_completed', 0),
            "success_rate": metrics.get('success_rate', 0.0),
            "average_confidence": metrics.get('average_confidence', 0.0),
            "response_time_ms": metrics.get('response_time_ms', 0),
            "error_count": metrics.get('error_count', 0),
        }
        
        # Get resource usage
        resources = {
            "cpu_percent": metrics.get('cpu_percent', 0.0),
            "memory_mb": metrics.get('memory_mb', 0),
            "active_tasks": metrics.get('active_tasks', 0),
        }
        
        return {
            "id": agent_id,
            "name": agent_id.replace('-', ' ').title(),
            "status": "active" if is_running else "idle",
            "role": metrics.get('role', 'agent'),
            "expertise_score": getattr(target_agent, 'expertise_score', 0.0),
            "risk_factor": getattr(target_agent, 'risk_factor', 0.0),
            "performance": performance,
            "resources": resources,
            "recent_decisions": decisions,
            "state": state.value if state else "unknown",
            "uptime_seconds": metrics.get('uptime_seconds', 0),
            "last_active": metrics.get('last_active', int(time.time() * 1000)),
            "timestamp": int(time.time() * 1000)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting agent detail for {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/agents/{agent_id}/command")
async def send_agent_command(agent_id: str, command: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send a command to a specific agent.
    
    Allows manual control and testing of agent behavior.
    """
    # BUG-L13 FIX: Return error in VALIDATION_MODE
    if agent_mesh is None:
        raise HTTPException(status_code=503, detail="Agent mesh disabled in validation mode")
    
    try:
        # Find the agent
        target_agent = None
        for agent in agent_mesh.agents:
            if getattr(agent, 'agent_id', None) == agent_id:
                target_agent = agent
                break
        
        if not target_agent:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        
        command_type = command.get('type')
        
        if command_type == 'start':
            if hasattr(target_agent, 'start'):
                await target_agent.start()
                return {"status": "success", "message": f"Agent {agent_id} started"}
        
        elif command_type == 'stop':
            if hasattr(target_agent, 'stop'):
                await target_agent.stop()
                return {"status": "success", "message": f"Agent {agent_id} stopped"}
        
        elif command_type == 'reset':
            if hasattr(target_agent, 'reset'):
                target_agent.reset()
                return {"status": "success", "message": f"Agent {agent_id} reset"}
        
        else:
            raise HTTPException(status_code=400, detail=f"Unknown command type: {command_type}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending command to agent {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
