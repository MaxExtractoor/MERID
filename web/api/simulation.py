"""
Simulation Control API Endpoints.

Provides API for controlling simulation playback, speed, and state management.
"""

from __future__ import annotations

import time
import json
from typing import Dict, Any, Optional
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/simulation", tags=["simulation"])
logger = get_logger("web.api.simulation")


# Global simulation state
_simulation_state = {
    "running": False,
    "speed": 1,
    "current_time": time.time(),
    "start_time": time.time(),
    "elapsed_seconds": 0,
    "events_processed": 0,
    "paused_at": None
}


class SimulationSpeedRequest(BaseModel):
    """Request to change simulation speed."""
    speed: int = Field(..., ge=1, le=10000, description="Simulation speed multiplier")


@router.get("/status")
async def get_simulation_status() -> Dict[str, Any]:
    """Get current simulation status."""
    global _simulation_state
    
    # Update elapsed time if running
    if _simulation_state["running"]:
        elapsed = time.time() - _simulation_state["start_time"]
        _simulation_state["elapsed_seconds"] = int(elapsed * _simulation_state["speed"])
    
    return {
        "running": _simulation_state["running"],
        "speed": _simulation_state["speed"],
        "current_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(_simulation_state["current_time"])),
        "elapsed_seconds": _simulation_state["elapsed_seconds"],
        "events_processed": _simulation_state["events_processed"]
    }


@router.post("/start")
async def start_simulation() -> Dict[str, Any]:
    """Start or resume simulation."""
    global _simulation_state
    
    if _simulation_state["running"]:
        return {"status": "already_running", "message": "Simulation is already running"}
    
    _simulation_state["running"] = True
    
    if _simulation_state["paused_at"]:
        # Resuming from pause
        pause_duration = time.time() - _simulation_state["paused_at"]
        _simulation_state["start_time"] += pause_duration
        _simulation_state["paused_at"] = None
    else:
        # Starting fresh
        _simulation_state["start_time"] = time.time()
    
    logger.info(f"Simulation started at speed {_simulation_state['speed']}x")
    
    return {
        "status": "started",
        "speed": _simulation_state["speed"],
        "message": "Simulation started successfully"
    }


@router.post("/pause")
async def pause_simulation() -> Dict[str, Any]:
    """Pause simulation."""
    global _simulation_state
    
    if not _simulation_state["running"]:
        return {"status": "already_paused", "message": "Simulation is not running"}
    
    _simulation_state["running"] = False
    _simulation_state["paused_at"] = time.time()
    
    # Update elapsed time
    elapsed = time.time() - _simulation_state["start_time"]
    _simulation_state["elapsed_seconds"] = int(elapsed * _simulation_state["speed"])
    
    logger.info("Simulation paused")
    
    return {
        "status": "paused",
        "elapsed_seconds": _simulation_state["elapsed_seconds"],
        "message": "Simulation paused successfully"
    }


@router.post("/reset")
async def reset_simulation() -> Dict[str, Any]:
    """Reset simulation to initial state."""
    global _simulation_state
    
    # Reset paper trading engine
    try:
        from trading.paper_trading import get_paper_trading_engine
        engine = get_paper_trading_engine()
        
        # Clear all portfolios
        for user_id in list(engine.portfolios.keys()):
            portfolio = engine.portfolios[user_id]
            portfolio.current_balance = portfolio.starting_balance
            portfolio.total_pnl = 0.0
            portfolio.total_trades = 0
            portfolio.winning_trades = 0
            portfolio.losing_trades = 0
            portfolio.positions.clear()
            portfolio.orders.clear()
            portfolio.trade_history.clear()
        
        logger.info("Paper trading engine reset")
    except Exception as e:
        logger.error(f"Failed to reset paper trading engine: {e}")
    
    # Reset simulation state
    _simulation_state.update({
        "running": False,
        "speed": 1,
        "current_time": time.time(),
        "start_time": time.time(),
        "elapsed_seconds": 0,
        "events_processed": 0,
        "paused_at": None
    })
    
    logger.info("Simulation reset to initial state")
    
    return {
        "status": "reset",
        "message": "Simulation reset successfully"
    }


@router.post("/speed/{speed}")
async def set_simulation_speed(speed: int) -> Dict[str, Any]:
    """Set simulation speed multiplier."""
    global _simulation_state
    
    if speed < 1 or speed > 10000:
        raise HTTPException(status_code=400, detail="Speed must be between 1 and 10000")
    
    old_speed = _simulation_state["speed"]
    _simulation_state["speed"] = speed
    
    logger.info(f"Simulation speed changed from {old_speed}x to {speed}x")
    
    return {
        "status": "speed_updated",
        "old_speed": old_speed,
        "new_speed": speed,
        "message": f"Simulation speed set to {speed}x"
    }


@router.post("/save")
async def save_simulation_state() -> Response:
    """Save current simulation state to file."""
    global _simulation_state
    
    try:
        engine = get_paper_trading_engine()
        
        # Collect all portfolio data
        portfolios_data = {}
        for user_id, portfolio in engine.portfolios.items():
            portfolios_data[user_id] = {
                "starting_balance": portfolio.starting_balance,
                "current_balance": portfolio.current_balance,
                "total_pnl": portfolio.total_pnl,
                "total_trades": portfolio.total_trades,
                "winning_trades": portfolio.winning_trades,
                "losing_trades": portfolio.losing_trades,
                "positions": [
                    {
                        "position_id": pos.position_id,
                        "asset": pos.asset,
                        "side": pos.side,
                        "size_usd": pos.size_usd,
                        "entry_price": pos.entry_price,
                        "current_price": pos.current_price,
                        "leverage": pos.leverage,
                        "unrealized_pnl": pos.unrealized_pnl,
                        "opened_at": pos.opened_at,
                        "market_type": pos.market_type
                    }
                    for pos in portfolio.positions.values()
                ],
                "orders": [
                    {
                        "order_id": order.order_id,
                        "asset": order.asset,
                        "side": order.side,
                        "order_type": order.order_type.value,
                        "size_usd": order.size_usd,
                        "price": order.price,
                        "status": order.status.value,
                        "created_at": order.created_at
                    }
                    for order in portfolio.orders.values()
                ]
            }
        
        state_data = {
            "simulation_state": _simulation_state,
            "portfolios": portfolios_data,
            "saved_at": time.time()
        }
        
        # Return as JSON file download
        json_content = json.dumps(state_data, indent=2)
        
        return Response(
            content=json_content,
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=simulation_state_{int(time.time())}.json"
            }
        )
    
    except Exception as e:
        logger.error(f"Failed to save simulation state: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/load")
async def load_simulation_state(state_data: Dict[str, Any]) -> Dict[str, Any]:
    """Load simulation state from data."""
    global _simulation_state
    
    try:
        # Restore simulation state
        if "simulation_state" in state_data:
            _simulation_state.update(state_data["simulation_state"])
        
        # Restore portfolios
        if "portfolios" in state_data:
            from trading.paper_trading import get_paper_trading_engine, PaperPosition, PaperOrder, PaperOrderType, PaperOrderStatus
            engine = get_paper_trading_engine()
            
            for user_id, portfolio_data in state_data["portfolios"].items():
                portfolio = engine.get_portfolio(user_id)
                
                portfolio.starting_balance = portfolio_data["starting_balance"]
                portfolio.current_balance = portfolio_data["current_balance"]
                portfolio.total_pnl = portfolio_data["total_pnl"]
                portfolio.total_trades = portfolio_data["total_trades"]
                portfolio.winning_trades = portfolio_data["winning_trades"]
                portfolio.losing_trades = portfolio_data["losing_trades"]
                
                # Restore positions
                portfolio.positions.clear()
                for pos_data in portfolio_data.get("positions", []):
                    position = PaperPosition(**pos_data)
                    position_key = f"{position.asset}_{position.side}_{position.market_type}"
                    portfolio.positions[position_key] = position
                
                # Restore orders
                portfolio.orders.clear()
                for order_data in portfolio_data.get("orders", []):
                    order_data["order_type"] = PaperOrderType[order_data["order_type"].upper()]
                    order_data["status"] = PaperOrderStatus[order_data["status"].upper()]
                    order = PaperOrder(**order_data)
                    portfolio.orders[order.order_id] = order
        
        logger.info("Simulation state loaded successfully")
        
        return {
            "status": "loaded",
            "message": "Simulation state loaded successfully"
        }
    
    except Exception as e:
        logger.error(f"Failed to load simulation state: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/events")
async def get_simulation_events(limit: int = 100) -> Dict[str, Any]:
    """Get recent simulation events."""
    # Placeholder for event tracking
    return {
        "events": [],
        "count": 0,
        "message": "Event tracking not yet implemented"
    }
