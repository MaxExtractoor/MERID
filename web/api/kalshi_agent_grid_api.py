"""
Kalshi Agent Grid API endpoints.

Provides manual control over the Kalshi trading agent grid lifecycle.
"""

from typing import Any, Dict
from fastapi import APIRouter, HTTPException

from merid.prediction.agent_grid import get_agent_grid
from utils.logger import get_logger

logger = get_logger("web.api.kalshi_agent_grid_api")

router = APIRouter(prefix="/api/v1/kalshi-grid", tags=["Kalshi Agent Grid"])

# NOTE: /start, /stop, /status, /pause, /resume, /matrix, /agents, /fills, /pnl,
# /portfolio, /session, /kill-switch/reset are all handled by kalshi_grid_api.py.
# This file only adds /health (detailed) and /summary (grid.summary() wrapper).


@router.get("/health")
async def get_agent_grid_health() -> Dict[str, Any]:
    """Health check for Kalshi agent grid - returns operational status."""
    try:
        grid = get_agent_grid()
        
        total_agents = len(grid._agents)
        running_agents = sum(1 for a in grid._agents if a.state.running)
        enabled_agents = sum(1 for a in grid._agents if a.state.enabled)
        agents_with_errors = sum(1 for a in grid._agents if a.state.last_error)
        
        total_cycles = sum(a.state.cycles_run for a in grid._agents)
        total_orders = sum(a.state.orders_placed for a in grid._agents)
        
        # Check if any agent hasn't cycled recently
        import time
        now = time.time()
        stale_threshold = 300  # 5 minutes
        stale_agents = []
        for a in grid._agents:
            if a.state.last_cycle_at:
                age = now - a.state.last_cycle_at.timestamp()
                if age > stale_threshold and a.state.enabled:
                    stale_agents.append(a.config.name)
        
        health_status = "healthy"
        if not grid._running:
            health_status = "stopped"
        elif agents_with_errors > 0 or stale_agents:
            health_status = "degraded"
        elif enabled_agents == 0:
            health_status = "paused"
        
        return {
            "status": health_status,
            "grid_running": grid._running,
            "agents": {
                "total": total_agents,
                "running": running_agents,
                "enabled": enabled_agents,
                "with_errors": agents_with_errors,
                "stale": stale_agents,
            },
            "activity": {
                "total_cycles": total_cycles,
                "total_orders": total_orders,
                "avg_cycles_per_agent": round(total_cycles / total_agents, 1) if total_agents > 0 else 0,
            },
        }
    except Exception as exc:
        logger.error(f"Failed to get agent grid health: {exc}")
        return {
            "status": "error",
            "error": str(exc),
        }


@router.get("/summary")
async def get_grid_summary() -> Dict[str, Any]:
    """Get high-level summary of agent grid."""
    try:
        grid = get_agent_grid()
        summary = grid.summary()
        
        return {
            "running": grid._running,
            "agent_count": len(grid._agents),
            "summary": summary,
        }
        
    except Exception as e:
        logger.error(f"Failed to get grid summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get summary: {str(e)}")


