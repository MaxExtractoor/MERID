"""
Trading Mode API - Endpoints for trading mode control and spectator feature.

Provides:
- Trading mode toggle (Paper/Live/Hybrid/Autonomous)
- Spectator view of agent paper trades
- Trade logging for strategy development
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from web.api.auth import get_current_session

from trading.mode_controller import (
    get_trading_mode_controller,
    TradingMode,
)
from trading.paper_trading import get_paper_engine
from utils.logger import get_logger

logger = get_logger("web.api.trading_mode")

router = APIRouter(prefix="/api/v1/trading-mode", tags=["trading-mode"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


class ModeChangeRequest(BaseModel):
    """Request to change trading mode."""
    mode: str = Field(..., description="Target mode: paper, live, hybrid, autonomous")
    reason: str = Field(default="", description="Reason for mode change")


class AutonomousLimitsRequest(BaseModel):
    """Request to update autonomous mode limits."""
    max_position_usd: Optional[float] = None
    max_daily_trades: Optional[int] = None
    max_daily_volume_usd: Optional[float] = None
    allowed_symbols: Optional[List[str]] = None


class RecordTradeRequest(BaseModel):
    """Request to record a spectator trade."""
    agent_id: str
    symbol: str
    action: str
    quantity: float
    price: float
    strategy: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CloseTradeRequest(BaseModel):
    """Request to close a trade."""
    trade_id: str
    exit_price: float
    pnl: float


@router.get("/status")
async def get_trading_mode_status() -> Dict[str, Any]:
    """Get current trading mode status and live paper telemetry."""
    controller = get_trading_mode_controller()
    status = controller.get_status()
    try:
        engine = get_paper_engine()
        stats = engine.get_global_stats()
    except Exception as exc:
        logger.warning(f"Failed to gather paper telemetry: {exc}")
        stats = {
            "accounts": 0,
            "active_positions": 0,
            "volume_24h": 0,
            "trades_24h": 0,
            "total_pnl": 0,
            "equity": 0,
            "cash": 0,
            "positions": []
        }

    return {
        "controller": status,
        "paper": stats
    }


@router.get("/mode")
async def get_current_mode() -> Dict[str, Any]:
    """Get current trading mode."""
    controller = get_trading_mode_controller()
    return {
        "mode": controller.mode_name,
        "is_paper": controller.is_paper,
        "is_live": controller.is_live,
        "is_hybrid": controller.is_hybrid,
        "is_autonomous": controller.is_autonomous,
    }


@router.post("/mode")
async def set_trading_mode(
    request: ModeChangeRequest,
    _session: dict = Depends(get_current_session),  # ZT4-02
) -> Dict[str, Any]:
    """Change trading mode."""
    controller = get_trading_mode_controller()
    
    valid_modes = ["paper", "live", "hybrid", "autonomous"]
    if request.mode.lower() not in valid_modes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode. Must be one of: {valid_modes}"
        )
    
    success = controller.set_mode(
        mode=request.mode,
        changed_by="api",
        reason=request.reason,
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to change mode")

    # L2: Reload VenueGate singleton so prediction market order path reflects new mode
    try:
        from merid.prediction.venue_gate import get_venue_gate
        get_venue_gate().reload()
    except Exception as _vge:
        logger.warning("VenueGate reload after mode change failed (non-fatal): %s", _vge)

    # Reset CT singleton so it re-reads TraderConfig.from_env() with the new mode
    try:
        from merid.trading.kalshi_continuous_trader import reset_continuous_trader
        reset_continuous_trader()
    except Exception as _cte:
        logger.warning("CT reset after mode change failed (non-fatal): %s", _cte)

    return {
        "status": "success",
        "mode": controller.mode_name,
        "message": f"Trading mode changed to {controller.mode_name}",
    }


@router.get("/history")
async def get_mode_history(limit: int = 20) -> Dict[str, Any]:
    """Get mode change history."""
    controller = get_trading_mode_controller()
    history = controller.get_mode_history(limit=limit)
    
    return {
        "history": [h.to_dict() for h in history],
        "count": len(history),
    }


@router.get("/limits")
async def get_autonomous_limits() -> Dict[str, Any]:
    """Get autonomous mode limits."""
    controller = get_trading_mode_controller()
    status = controller.get_status()
    
    return {
        "limits": status["autonomous_limits"],
        "daily_stats": status["daily_stats"],
    }


@router.post("/limits")
async def set_autonomous_limits(
    request: AutonomousLimitsRequest,
    _session: dict = Depends(get_current_session),  # ZT4-02
) -> Dict[str, Any]:
    """Update autonomous mode limits."""
    controller = get_trading_mode_controller()
    
    limits = {}
    if request.max_position_usd is not None:
        limits["max_position_usd"] = request.max_position_usd
    if request.max_daily_trades is not None:
        limits["max_daily_trades"] = request.max_daily_trades
    if request.max_daily_volume_usd is not None:
        limits["max_daily_volume_usd"] = request.max_daily_volume_usd
    if request.allowed_symbols is not None:
        limits["allowed_symbols"] = request.allowed_symbols
    
    if limits:
        controller.set_autonomous_limits(limits)
    
    return {
        "status": "success",
        "limits": controller.get_status()["autonomous_limits"],
    }


@router.get("/can-execute")
async def check_can_execute(symbol: str, amount_usd: float) -> Dict[str, Any]:
    """Check if a live trade can be executed."""
    controller = get_trading_mode_controller()
    can_execute, reason = controller.can_execute_live(symbol, amount_usd)
    
    return {
        "can_execute": can_execute,
        "reason": reason,
        "mode": controller.mode_name,
    }


# ============================================
# SPECTATOR ENDPOINTS
# ============================================

@router.get("/spectator/trades")
async def get_spectator_trades(
    limit: int = 50,
    agent_id: Optional[str] = None,
    symbol: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """Get trades for spectator view."""
    controller = get_trading_mode_controller()
    
    trades = controller.get_spectator_trades(
        limit=limit,
        agent_id=agent_id,
        symbol=symbol,
        status=status,
    )
    
    return {
        "trades": [t.to_dict() for t in trades],
        "count": len(trades),
        "mode": controller.mode_name,
    }


@router.get("/spectator/live")
async def get_live_spectator_feed(limit: int = 20) -> Dict[str, Any]:
    """Get live spectator feed of recent trades."""
    controller = get_trading_mode_controller()
    
    # Get most recent trades
    trades = controller.get_spectator_trades(limit=limit)
    
    # Calculate summary stats
    open_trades = [t for t in trades if t.status == "open"]
    closed_trades = [t for t in trades if t.status == "closed"]
    total_pnl = sum(t.pnl for t in closed_trades)
    
    # Group by agent
    agents = {}
    for trade in trades:
        if trade.agent_id not in agents:
            agents[trade.agent_id] = {
                "agent_id": trade.agent_id,
                "trade_count": 0,
                "open_positions": 0,
                "total_pnl": 0.0,
            }
        agents[trade.agent_id]["trade_count"] += 1
        if trade.status == "open":
            agents[trade.agent_id]["open_positions"] += 1
        agents[trade.agent_id]["total_pnl"] += trade.pnl
    
    return {
        "trades": [t.to_dict() for t in trades],
        "summary": {
            "total_trades": len(trades),
            "open_trades": len(open_trades),
            "closed_trades": len(closed_trades),
            "total_pnl": total_pnl,
        },
        "agents": list(agents.values()),
        "mode": controller.mode_name,
    }


@router.post("/spectator/record")
async def record_spectator_trade(
    request: RecordTradeRequest,
    _session: dict = Depends(get_current_session),  # ZT4-02
) -> Dict[str, Any]:
    """Record a trade for spectator viewing."""
    controller = get_trading_mode_controller()
    
    trade = controller.record_trade(
        agent_id=request.agent_id,
        symbol=request.symbol,
        action=request.action,
        quantity=request.quantity,
        price=request.price,
        strategy=request.strategy,
        confidence=request.confidence,
        reasoning=request.reasoning,
        metadata=request.metadata,
    )
    
    return {
        "status": "recorded",
        "trade": trade.to_dict(),
    }


@router.post("/spectator/close")
async def close_spectator_trade(
    request: CloseTradeRequest,
    _session: dict = Depends(get_current_session),  # ZT4-02
) -> Dict[str, Any]:
    """Close a spectator trade."""
    controller = get_trading_mode_controller()
    
    trade = controller.close_trade(
        trade_id=request.trade_id,
        exit_price=request.exit_price,
        pnl=request.pnl,
    )
    
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    
    return {
        "status": "closed",
        "trade": trade.to_dict(),
    }


@router.get("/spectator/stats")
async def get_spectator_stats() -> Dict[str, Any]:
    """Get spectator statistics."""
    controller = get_trading_mode_controller()
    
    trades = controller.get_spectator_trades(limit=1000)
    
    # Calculate stats
    total_trades = len(trades)
    open_trades = len([t for t in trades if t.status == "open"])
    closed_trades = len([t for t in trades if t.status == "closed"])
    
    winning_trades = len([t for t in trades if t.status == "closed" and t.pnl > 0])
    losing_trades = len([t for t in trades if t.status == "closed" and t.pnl < 0])
    
    total_pnl = sum(t.pnl for t in trades if t.status == "closed")
    avg_pnl = total_pnl / closed_trades if closed_trades > 0 else 0
    
    win_rate = (winning_trades / closed_trades * 100) if closed_trades > 0 else 0
    
    # Group by symbol
    symbols = {}
    for trade in trades:
        if trade.symbol not in symbols:
            symbols[trade.symbol] = {"count": 0, "pnl": 0.0}
        symbols[trade.symbol]["count"] += 1
        symbols[trade.symbol]["pnl"] += trade.pnl
    
    # Group by strategy
    strategies = {}
    for trade in trades:
        if trade.strategy:
            if trade.strategy not in strategies:
                strategies[trade.strategy] = {"count": 0, "pnl": 0.0}
            strategies[trade.strategy]["count"] += 1
            strategies[trade.strategy]["pnl"] += trade.pnl
    
    return {
        "total_trades": total_trades,
        "open_trades": open_trades,
        "closed_trades": closed_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_pnl": avg_pnl,
        "by_symbol": symbols,
        "by_strategy": strategies,
        "mode": controller.mode_name,
    }
