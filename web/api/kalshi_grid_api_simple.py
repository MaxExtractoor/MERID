"""Simplified Kalshi Grid API for debugging - minimal imports."""

from __future__ import annotations

from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException, Request
from utils.logger import get_logger

router = APIRouter(prefix="/kalshi-grid", tags=["kalshi-grid"])
logger = get_logger("web.api.kalshi_grid_simple")


@router.get("/test")
async def test_endpoint():
    """Simple test endpoint to verify router is working."""
    return {"status": "ok", "message": "kalshi-grid simple router is working"}


@router.get("/status")
async def get_status(request: Request):
    """Get basic grid status without complex imports."""
    try:
        # Simple check if grid exists in app.state
        grid = getattr(request.app.state, "agent_grid_15m", None)
        if grid is None:
            return {
                "status": "error",
                "message": "Agent grid not initialized",
                "grid_available": False
            }
        
        # Basic grid info without complex imports
        return {
            "status": "ok",
            "message": "Agent grid available",
            "grid_available": True,
            "grid_type": str(type(grid).__name__),
            "timestamp": "2026-06-04T20:52:00Z"
        }
        
    except Exception as e:
        logger.error("Status endpoint failed: %s", e)
        return {
            "status": "error", 
            "message": f"Status endpoint failed: {e}",
            "grid_available": False
        }


@router.get("/agents")
async def get_agents(request: Request):
    """Get basic agent list without complex imports."""
    try:
        grid = getattr(request.app.state, "agent_grid_15m", None)
        if grid is None:
            raise HTTPException(status_code=503, detail="Agent grid not initialized")
        
        # Simple agent count without detailed summaries
        if hasattr(grid, '_agents'):
            agents = []
            for agent in grid._agents:
                agent_info = {
                    "name": getattr(agent, 'name', 'Unknown'),
                    "enabled": getattr(agent, 'enabled', False),
                    "type": str(type(agent).__name__)
                }
                agents.append(agent_info)
            
            return {
                "status": "ok",
                "agents": agents,
                "count": len(agents)
            }
        else:
            return {"status": "ok", "agents": [], "count": 0}
            
    except Exception as e:
        logger.error("Agents endpoint failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Agents endpoint failed: {e}")
