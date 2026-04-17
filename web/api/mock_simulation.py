"""
Mock API endpoints for testing sections that don't have real APIs yet
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, List, Any
import time
import random

router = APIRouter()

# Mock data stores
mock_simulation_runs = []
mock_arena_status = {}
mock_portfolio_data = {}

@router.get("/status")
async def get_simulation_status():
    """Get simulation engine status"""
    return {
        "status": "running",
        "is_running": True,
        "is_paused": False,
        "active_runs": len(mock_simulation_runs),
        "total_runs": len(mock_simulation_runs) + 10,
        "total_agents": 8,
        "engine": "Simulation Engine v2",
        "engine_status": "Ready"
    }

@router.get("/runs")
async def get_simulation_runs():
    """Get all simulation runs"""
    # Generate some mock runs if empty
    if not mock_simulation_runs:
        mock_simulation_runs.extend([
            {
                "id": f"run_{i}",
                "name": f"Simulation Run {i+1}",
                "description": f"Test simulation run {i+1}",
                "status": random.choice(["running", "completed", "failed", "paused"]),
                "started_at": time.time() - random.randint(3600, 86400),
                "duration": f"{random.randint(1, 60)}m",
                "agent_count": random.randint(3, 8),
                "current_step": random.randint(0, 100),
                "total_steps": 100,
                "elapsed": f"{random.randint(1, 3600)}s"
            }
            for i in range(5)
        ])
    
    return {"runs": mock_simulation_runs}

@router.get("/runs/{run_id}")
async def get_simulation_run(run_id: str):
    """Get specific simulation run details"""
    run = next((r for r in mock_simulation_runs if r["id"] == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    
    # Add some mock events
    run["events"] = [
        {
            "type": "step",
            "title": f"Step {run['current_step']}",
            "description": f"Processing step {run['current_step']} of {run['total_steps']}",
            "timestamp": time.time(),
            "agent": f"agent_{random.randint(1, 8)}"
        }
        for _ in range(3)
    ]
    
    return run

@router.post("/runs")
async def create_simulation_run(run_data: Dict[str, Any]):
    """Create a new simulation run"""
    new_run = {
        "id": f"run_{len(mock_simulation_runs) + 1}",
        "name": run_data.get("name", "New Run"),
        "description": run_data.get("description", "Created from UI"),
        "status": "running",
        "started_at": time.time(),
        "duration": "0m",
        "agent_count": run_data.get("agent_count", 5),
        "current_step": 0,
        "total_steps": 100,
        "elapsed": "0s",
        "model": run_data.get("model", "default"),
        "scenario": run_data.get("scenario", "default")
    }
    
    mock_simulation_runs.append(new_run)
    return {"run": new_run}

@router.post("/runs/{run_id}/pause")
async def pause_simulation_run(run_id: str):
    """Pause/resume a simulation run"""
    run = next((r for r in mock_simulation_runs if r["id"] == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    
    run["status"] = "paused" if run["status"] == "running" else "running"
    return {"status": "success"}

@router.post("/runs/{run_id}/stop")
async def stop_simulation_run(run_id: str):
    """Stop a simulation run"""
    run = next((r for r in mock_simulation_runs if r["id"] == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    
    run["status"] = "stopped"
    return {"status": "success"}

@router.get("/agents")
async def get_simulation_agents():
    """Get all simulation agents"""
    return {
        "agents": [
            {
                "id": f"agent_{i}",
                "name": f"Agent {i+1}",
                "type": "Agent",
                "archetype": random.choice(["PIT", "TTC", "PIT/TTC"]),
                "tier": random.choice(["tier_1", "tier_2", "tier_3"]),
                "status": random.choice(["active", "idle", "error"])
            }
            for i in range(8)
        ]
    }

@router.get("/runs/{run_id}/events")
async def get_run_events(run_id: str, limit: int = 10):
    """Get events for a specific run"""
    return {
        "events": [
            {
                "type": random.choice(["step", "agent_action", "error", "info"]),
                "title": f"Event {i+1}",
                "description": f"Mock event {i+1} for run {run_id}",
                "timestamp": time.time() - random.randint(0, 3600),
                "agent": f"agent_{random.randint(1, 8)}"
            }
            for i in range(limit)
        ]
    }
