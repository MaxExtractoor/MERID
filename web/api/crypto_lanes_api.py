"""
Crypto Lanes API - Endpoints for crypto trading lane management.

Provides REST endpoints for:
- Getting crypto lane status
- Toggling individual lanes on/off
- Lane configuration and monitoring
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Dict, List, Optional, Any
import time

from utils.logger import get_logger
from merid.lanes.registry import get_lane_registry

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/lanes", tags=["crypto-lanes"])


class LaneToggleRequest(BaseModel):
    """Request model for toggling a lane."""
    enabled: bool


class LaneStatusResponse(BaseModel):
    """Response model for lane status."""
    lane_id: str
    symbol: str
    enabled: bool
    running: bool
    open_positions: int
    max_positions: int
    markets_live: int
    max_markets_live: int
    last_edge_bps: float
    last_p_model: float
    last_fg_contrarian: float
    last_updated: float
    paper: bool = False


class CryptoLanesStatusResponse(BaseModel):
    """Response model for crypto lanes status."""
    lanes: List[LaneStatusResponse]
    total_lanes: int
    running_lanes: int
    timestamp: float


@router.get("/crypto/status", response_model=CryptoLanesStatusResponse)
async def get_crypto_lanes_status():
    """Get status of all crypto trading lanes."""
    try:
        registry = get_lane_registry()
        summary = registry.get_status_summary()
        
        lanes = []
        for lane_id, lane_data in summary.get("lanes", {}).items():
            # Only include crypto lanes (15m)
            if not (lane_id.endswith("_15M") or lane_id.endswith("_15M_PAPER")):
                continue
            
            # Extract lane status
            status = lane_data
            
            # Create response model
            lane_response = LaneStatusResponse(
                lane_id=lane_id,
                symbol=status.get("symbol", ""),
                enabled=status.get("enabled", False),
                running=status.get("running", False),
                open_positions=status.get("open_positions", 0),
                max_positions=status.get("config", {}).get("max_positions", 1),
                markets_live=status.get("markets_live", 0),
                max_markets_live=status.get("config", {}).get("max_markets_live", 1),
                last_edge_bps=status.get("last_edge_bps", 0.0),
                last_p_model=status.get("last_p_model", 0.0),
                last_fg_contrarian=status.get("last_fg_contrarian", 0.0),
                last_updated=status.get("last_cycle_time", time.time()),
                paper=status.get("paper", False))
            lanes.append(lane_response)
        
        response = CryptoLanesStatusResponse(
            lanes=lanes,
            total_lanes=len(lanes),
            running_lanes=len([l for l in lanes if l.running]),
            timestamp=time.time())
        
        logger.debug(f"Returned status for {len(lanes)} crypto lanes")
        return response
        
    except Exception as exc:
        logger.error(f"Failed to get crypto lanes status: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{lane_id}/toggle")
async def toggle_lane(lane_id: str, request: LaneToggleRequest, background_tasks: BackgroundTasks):
    """Toggle a lane on or off."""
    try:
        registry = get_lane_registry()
        lane = registry.get_lane(lane_id)
        
        if not lane:
            raise HTTPException(status_code=404, detail=f"Lane {lane_id} not found")
        
        # Update lane configuration
        config = registry.get_config(lane_id)
        if config:
            config.enable = request.enabled
            logger.info(f"Updated lane {lane_id} enabled={request.enabled}")
        
        # Start or stop the lane
        if request.enabled and not lane.is_running:
            background_tasks.add_task(lane.start)
            logger.info(f"Starting lane {lane_id}")
        elif not request.enabled and lane.is_running:
            background_tasks.add_task(lane.stop)
            logger.info(f"Stopping lane {lane_id}")
        
        return {"success": True, "lane_id": lane_id, "enabled": request.enabled}
        
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to toggle lane {lane_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/crypto/summary")
async def get_crypto_lanes_summary():
    """Get summary of crypto lanes configuration and status."""
    try:
        registry = get_lane_registry()
        summary = registry.get_status_summary()
        
        # Filter for crypto lanes only
        crypto_lanes = {}
        for lane_id, lane_data in summary.get("lanes", {}).items():
            if lane_id.endswith("_15M") or lane_id.endswith("_15M_PAPER"):
                crypto_lanes[lane_id] = lane_data
        
        return {
            "total_lanes": len(crypto_lanes),
            "live_lanes": len([l for l in crypto_lanes.values() if not l.get("paper", False)]),
            "paper_lanes": len([l for l in crypto_lanes.values() if l.get("paper", False)]),
            "running_lanes": len([l for l in crypto_lanes.values() if l.get("running", False)]),
            "symbols": list(set(l.get("symbol", "") for l in crypto_lanes.values())),
            "lanes": crypto_lanes,
            "timestamp": time.time(),
        }
        
    except Exception as exc:
        logger.error(f"Failed to get crypto lanes summary: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{lane_id}/status")
async def get_lane_status(lane_id: str):
    """Get detailed status for a specific lane."""
    try:
        registry = get_lane_registry()
        lane = registry.get_lane(lane_id)
        
        if not lane:
            raise HTTPException(status_code=404, detail=f"Lane {lane_id} not found")
        
        status = lane.get_status()
        return status
        
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to get lane status {lane_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{lane_id}/start")
async def start_lane(lane_id: str, background_tasks: BackgroundTasks):
    """Start a specific lane."""
    try:
        registry = get_lane_registry()
        lane = registry.get_lane(lane_id)
        
        if not lane:
            raise HTTPException(status_code=404, detail=f"Lane {lane_id} not found")
        
        if lane.is_running:
            return {"success": True, "lane_id": lane_id, "message": "Lane already running"}
        
        # Enable the lane if disabled
        config = registry.get_config(lane_id)
        if config and not config.enable:
            config.enable = True
        
        background_tasks.add_task(lane.start)
        logger.info(f"Starting lane {lane_id}")
        
        return {"success": True, "lane_id": lane_id, "message": "Lane start initiated"}
        
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to start lane {lane_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{lane_id}/stop")
async def stop_lane(lane_id: str, background_tasks: BackgroundTasks):
    """Stop a specific lane."""
    try:
        registry = get_lane_registry()
        lane = registry.get_lane(lane_id)
        
        if not lane:
            raise HTTPException(status_code=404, detail=f"Lane {lane_id} not found")
        
        if not lane.is_running:
            return {"success": True, "lane_id": lane_id, "message": "Lane already stopped"}
        
        background_tasks.add_task(lane.stop)
        logger.info(f"Stopping lane {lane_id}")
        
        return {"success": True, "lane_id": lane_id, "message": "Lane stop initiated"}
        
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to stop lane {lane_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
