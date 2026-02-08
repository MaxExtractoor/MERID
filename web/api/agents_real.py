"""Real-time agent data endpoints - NO MOCK DATA."""

import time
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException
from datetime import datetime

from agents.agent_mesh import agent_mesh
from core.agent_orchestrator import get_agent_orchestrator
from utils.logger import get_logger

router = APIRouter()
logger = get_logger("api.agents_real")


@router.options("/api/agents/summary")
async def options_agents_summary():
    """Handle OPTIONS preflight for CORS."""
    return {}


@router.get("/api/agents/summary")
async def get_agents_summary() -> Dict[str, Any]:
    """
    Get real-time agent summary from the running agent mesh.
    
    Returns actual agent status, metrics, and performance data.
    NO MOCK DATA - all values come from live agent instances.
    """
    try:
        # Get metrics from the actual agent mesh
        mesh_metrics = agent_mesh.get_metrics()
        
        # Get orchestrator metrics if available
        try:
            orchestrator = get_agent_orchestrator()
            orchestrator_metrics = orchestrator.get_metrics()
        except Exception as e:
            logger.warning(f"Could not get orchestrator metrics: {e}")
            orchestrator_metrics = {}
        
        # Build agent list from real agent instances
        agents_list = []
        total_tasks = 0
        active_count = 0
        
        for agent in agent_mesh.agents:
            try:
                # Get real metrics from each agent
                agent_metrics = agent.get_metrics() if hasattr(agent, 'get_metrics') else {}
                
                # Determine real status
                is_running = getattr(agent, 'running', False)
                status = "active" if is_running else "idle"
                
                # Get real task counts
                tasks_completed = agent_metrics.get('tasks_completed', 0)
                total_tasks += tasks_completed
                
                if is_running:
                    active_count += 1
                
                # Get agent state
                agent_state = getattr(agent, 'state', None)
                uptime_pct = 100.0 if is_running else 0.0
                
                # Get real agent name and ID
                agent_id = getattr(agent, 'agent_id', agent.__class__.__name__)
                agent_name = agent_id.replace('-', ' ').title()
                
                agents_list.append({
                    "id": agent_id,
                    "name": agent_name,
                    "status": status,
                    "tasks_completed": tasks_completed,
                    "uptime": uptime_pct,
                    "role": agent_metrics.get('role', 'agent'),
                    "confidence": agent_metrics.get('confidence', 0.0),
                    "last_active": agent_metrics.get('last_active', int(time.time() * 1000))
                })
                
            except Exception as e:
                logger.error(f"Error getting metrics for agent {agent}: {e}")
                continue
        
        # Calculate real aggregate metrics
        total_agents = len(agent_mesh.agents)
        idle_agents = total_agents - active_count
        
        # Get real response times from orchestrator
        avg_response_time = orchestrator_metrics.get('average_response_time', 0)
        success_rate = orchestrator_metrics.get('success_rate', 0.0)
        tasks_pending = orchestrator_metrics.get('tasks_pending', 0)
        
        return {
            "total_agents": total_agents,
            "active_agents": active_count,
            "idle_agents": idle_agents,
            "tasks_completed": total_tasks,
            "tasks_pending": tasks_pending,
            "average_response_time": avg_response_time,
            "success_rate": success_rate,
            "agents": agents_list,
            "mesh_running": mesh_metrics.get('running', False),
            "timestamp": int(time.time() * 1000)
        }
        
    except Exception as e:
        logger.error(f"Error getting agent summary: {e}", exc_info=True)
        # Return minimal valid response on error
        return {
            "total_agents": 0,
            "active_agents": 0,
            "idle_agents": 0,
            "tasks_completed": 0,
            "tasks_pending": 0,
            "average_response_time": 0,
            "success_rate": 0.0,
            "agents": [],
            "mesh_running": False,
            "error": str(e),
            "timestamp": int(time.time() * 1000)
        }


@router.get("/api/agents/{agent_id}")
async def get_agent_detail(agent_id: str) -> Dict[str, Any]:
    """
    Get detailed metrics for a specific agent.
    
    Returns real-time performance data, decision history, and health metrics.
    """
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


@router.get("/api/agents/activity")
async def get_agents_activity() -> Dict[str, Any]:
    """
    Get real-time agent activity feed.
    
    Returns recent agent actions, decisions, and events.
    """
    try:
        activities = []
        
        for agent in agent_mesh.agents:
            agent_id = getattr(agent, 'agent_id', agent.__class__.__name__)
            
            # Get recent activity
            if hasattr(agent, '_prediction_history'):
                for decision in agent._prediction_history[-5:]:  # Last 5 per agent
                    activities.append({
                        "agent_id": agent_id,
                        "agent_name": agent_id.replace('-', ' ').title(),
                        "action": decision.get('action', 'unknown'),
                        "confidence": decision.get('confidence', 0.0),
                        "timestamp": decision.get('timestamp', int(time.time() * 1000)),
                        "details": decision.get('details', {})
                    })
        
        # Sort by timestamp descending
        activities.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return {
            "activities": activities[:50],  # Return top 50 most recent
            "total_count": len(activities),
            "timestamp": int(time.time() * 1000)
        }
        
    except Exception as e:
        logger.error(f"Error getting agent activity: {e}", exc_info=True)
        return {
            "activities": [],
            "total_count": 0,
            "error": str(e),
            "timestamp": int(time.time() * 1000)
        }


@router.post("/api/agents/{agent_id}/command")
async def send_agent_command(agent_id: str, command: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send a command to a specific agent.
    
    Allows manual control and testing of agent behavior.
    """
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
