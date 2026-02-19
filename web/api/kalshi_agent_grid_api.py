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
# /portfolio, /session, /kill-switch/reset, /health are all handled by kalshi_grid_api.py.
# This file only adds /summary (grid.summary() wrapper).


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


