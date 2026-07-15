# web/api/agent_modes_api.py
"""Agent modes configuration API."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Dict, Any
from web.api.auth import get_current_session
from utils.logger import get_logger
from config.agent_modes import (
    get_all_agent_modes, 
    set_agent_mode,
    get_agent_mode_config
)

logger = get_logger("web.api.agent_modes")

router = APIRouter(
    prefix="/api/v1/agents",
    tags=["Agent Modes"],
)


class AgentModeRequest(BaseModel):
    mode: str  # "shadow", "paper", "live"
    size_multiplier: float = 1.0


@router.get("/modes")
async def get_all_agent_modes():
    """Get mode configurations for all agents."""
    try:
        modes = get_all_agent_modes()
        return {
            "modes": {
                agent_id: {
                    "mode": config.mode,
                    "size_multiplier": config.size_multiplier,
                    "enabled": config.enabled
                }
                for agent_id, config in modes.items()
            },
            "timestamp": logger.info("Agent modes retrieved")
        }
    except Exception as exc:
        logger.error(f"Failed to get agent modes: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/modes/{agent_id}")
async def get_agent_mode(agent_id: str):
    """Get mode configuration for a specific agent."""
    try:
        config = get_agent_mode_config(agent_id)
        return {
            "agent_id": agent_id,
            "mode": config.mode,
            "size_multiplier": config.size_multiplier,
            "enabled": config.enabled,
            "timestamp": logger.info(f"Agent mode retrieved for {agent_id}")
        }
    except Exception as exc:
        logger.error(f"Failed to get agent mode for {agent_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/modes/{agent_id}")
async def set_agent_mode_endpoint(agent_id: str, request: AgentModeRequest):
    """Set mode configuration for a specific agent."""
    try:
        if request.mode not in ["shadow", "paper", "live"]:
            raise HTTPException(status_code=400, detail="Mode must be one of: shadow, paper, live")
        
        if request.size_multiplier <= 0 or request.size_multiplier > 10:
            raise HTTPException(status_code=400, detail="Size multiplier must be between 0 and 10")
        
        set_agent_mode(agent_id, request.mode, request.size_multiplier)
        
        return {
            "agent_id": agent_id,
            "mode": request.mode,
            "size_multiplier": request.size_multiplier,
            "message": f"Agent {agent_id} mode updated successfully",
            "timestamp": logger.info(f"Agent mode updated for {agent_id} to {request.mode}")
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to set agent mode for {agent_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/routing-status")
async def get_routing_status():
    """Get routing status for all agents."""
    # PROFILE-GUARD: Disable for kalshi_crypto_15m_v2 (agent mode routing not needed for sealed 15m profile)
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile == "kalshi_crypto_15m_v2":
        raise HTTPException(
            403,
            "Agent mode routing is disabled for kalshi_crypto_15m_v2 profile (sealed 15m profile uses direct agent grid)"
        )
    
    try:
        from merid.kalshi.agent_mode_router import get_agent_mode_router
        router = get_agent_mode_router()
        
        status = {}
        for agent_id in ["btc_15m_regime", "eth_15m_regime", "sol_15m_regime", "xrp_15m_regime", "doge_15m_regime"]:
            status[agent_id] = router.get_agent_routing_status(agent_id)
        
        return {
            "routing_status": status,
            "timestamp": logger.info("Routing status retrieved")
        }
    except Exception as exc:
        logger.error(f"Failed to get routing status: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
