"""Unified trading suite API exposing runtime config + execution router."""

from __future__ import annotations

import os
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel, Field
from utils.logger import get_logger

logger = get_logger(__name__)

from trading.agents.execution_agent import ExecutionAgent, OrderSide, OrderType
from trading.adapters.registry import get_adapter
from trading.adapters.base import TradeSide
from trading.config.runtime_config import get_runtime_config
from merid.execution.router import TraderIdentity, ExecutionRouter, get_execution_router
from trading.spectator import get_spectator_log
from observability.event_stream import get_event_stream

router = APIRouter(prefix="/api/v1/trading-suite", tags=["trading-suite"])

_runtime_config = get_runtime_config()
_execution_router = get_execution_router()


class GlobalConfigUpdate(BaseModel):
    mode: Optional[Literal["offline", "sim", "paper", "live", "hybrid"]] = None
    allow_live_trades: Optional[bool] = None
    spectator_mode: Optional[bool] = None


class VenueConfigUpdate(BaseModel):
    label: Optional[str] = None
    mode: Optional[Literal["disabled", "sim", "paper", "live"]] = None
    max_notional_usd: Optional[float] = Field(default=None, ge=0)
    daily_limit_usd: Optional[float] = Field(default=None, ge=0)
    credentials_present: Optional[bool] = None


class TraderConfigUpdate(BaseModel):
    mode: Optional[Literal["sim", "paper", "live"]] = None
    spectator_only: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None


class UnifiedOrderRequest(BaseModel):
    trader_type: Literal["human", "agent"]
    trader_id: str
    venue_id: str
    instrument: str
    side: Literal["buy", "sell"]
    size: float = Field(..., gt=0)
    price: Optional[float] = Field(default=None, gt=0)
    extra_params: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


@router.get("/config")
async def get_global_config() -> Dict[str, Any]:
    """Return snapshot of runtime trading configuration."""
    return _runtime_config.snapshot()


@router.post("/config")
async def update_global_config(payload: GlobalConfigUpdate) -> Dict[str, Any]:
    """Mutate global trading configuration."""
    data = payload.dict(exclude_unset=True)
    return _runtime_config.update_global_mode(
        mode=data.get("mode"),
        allow_live_trades=data.get("allow_live_trades"),
        spectator_mode=data.get("spectator_mode"),
    )


@router.get("/venues")
async def list_venues() -> Dict[str, Any]:
    """List venue configurations."""
    snapshot = _runtime_config.snapshot()
    return {"venues": list(snapshot.get("venues", {}).values())}


@router.post("/venues/{venue_id}")
async def update_venue(venue_id: str, payload: VenueConfigUpdate) -> Dict[str, Any]:
    """Update a venue configuration."""
    try:
        return _runtime_config.upsert_venue(venue_id, payload.dict(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/traders")
async def list_traders() -> Dict[str, Any]:
    """List trader-specific configuration overrides."""
    snapshot = _runtime_config.snapshot()
    return {"traders": snapshot.get("traders", {})}


@router.post("/traders/{trader_id}")
async def update_trader(trader_id: str, payload: TraderConfigUpdate) -> Dict[str, Any]:
    """Update trader-specific settings (mode/spectator flag)."""
    return _runtime_config.upsert_trader(trader_id, payload.dict(exclude_unset=True))


@router.get("/portfolio")
async def get_portfolio_snapshot() -> Dict[str, Any]:
    """Aggregate positions/PnL across all registered executors."""
    snapshot = await _execution_router.get_portfolio_snapshot()
    return {
        "total_unrealized_pnl": snapshot.total_unrealized_pnl,
        "total_notional": snapshot.total_notional,
        "positions": [
            {
                "symbol": pos.symbol,
                "total_size": pos.total_size,
                "avg_entry_price": pos.avg_entry_price,
                "unrealized_pnl": pos.unrealized_pnl,
                "venue_breakdown": pos.venue_breakdown,
            }
            for pos in snapshot.positions
        ],
        "metadata": snapshot.metadata,
    }


@router.get("/risk")
async def get_risk_overview() -> Dict[str, Any]:
    """Return current exposure vs configured limits and guard state."""
    config = _runtime_config.snapshot()
    portfolio = await _execution_router.get_portfolio_snapshot()
    limits = {
        "max_notional_per_trade_usd": float(os.getenv("MERID_MAX_NOTIONAL_PER_TRADE_USD", "0") or 0),
        "max_memecoin_notional_usd": float(os.getenv("MERID_MAX_MEMECOIN_NOTIONAL_USD", "0") or 0),
        "solana_sniper_min_liquidity_usd": float(os.getenv("MERID_SOLANA_SNIPER_MIN_LIQUIDITY_USD", "0") or 0),
    }
    exposures = {
        "current_total_notional": portfolio.total_notional,
        "current_unrealized_pnl": portfolio.total_unrealized_pnl,
        "open_positions": len(portfolio.positions),
    }
    guard = {
        "mode": config.get("mode"),
        "allow_live_trades": config.get("allow_live_trades"),
        "spectator_mode": config.get("spectator_mode"),
    }
    return {
        "limits": limits,
        "exposures": exposures,
        "guard": guard,
    }


@router.get("/telemetry")
async def get_trading_telemetry() -> Dict[str, Any]:
    """Summarize key metrics + alerts for the trading suite."""
    config = _runtime_config.snapshot()
    portfolio = await _execution_router.get_portfolio_snapshot()
    venues_cfg = config.get("venues", {}) or {}
    venue_count = len(venues_cfg)
    trader_count = len(config.get("traders", {}) or {})
    enabled_venues = [v for v in venues_cfg.values() if v.get("enabled")]
    venues_with_credentials = sum(1 for v in enabled_venues if v.get("credentials_present"))
    venues_missing_credentials = [v for v in enabled_venues if not v.get("credentials_present")]
    limits = {
        "max_notional_per_trade_usd": float(os.getenv("MERID_MAX_NOTIONAL_PER_TRADE_USD", "0") or 0),
        "max_memecoin_notional_usd": float(os.getenv("MERID_MAX_MEMECOIN_NOTIONAL_USD", "0") or 0),
    }
    top_position = None
    if portfolio.positions:
        top_position = max(portfolio.positions, key=lambda pos: abs(pos.total_size))

    metrics = [
        {"label": "Active Venues", "value": venue_count},
        {"label": "Trader Overrides", "value": trader_count},
        {"label": "Open Positions", "value": len(portfolio.positions)},
        {"label": "Total Notional", "value": portfolio.total_notional},
        {"label": "Unrealized PnL", "value": portfolio.total_unrealized_pnl},
        {"label": "Venues Ready", "value": venues_with_credentials},
        {"label": "Venues Enabled", "value": len(enabled_venues)},
        {"label": "Venues Missing Creds", "value": len(venues_missing_credentials)},
    ]
    if top_position:
        metrics.append(
            {
                "label": "Top Position",
                "value": f"{top_position.symbol} {top_position.total_size:.4f}",
            }
        )

    alerts = []
    if limits["max_notional_per_trade_usd"] and portfolio.total_notional > limits["max_notional_per_trade_usd"]:
        alerts.append(
            {
                "severity": "error",
                "message": f"Total notional {portfolio.total_notional:,.0f} exceeds configured per-trade cap {limits['max_notional_per_trade_usd']:,.0f}.",
            }
        )
    if config.get("spectator_mode") and config.get("allow_live_trades"):
        alerts.append(
            {
                "severity": "warn",
                "message": "Spectator mode is ON while live trades are allowed. Manual intents will be blocked.",
            }
        )
    if not enabled_venues:
        alerts.append(
            {
                "severity": "error",
                "message": "No venues are enabled. Agents cannot execute trades.",
            }
        )
    elif venues_missing_credentials:
        venue_labels = ", ".join(v.get("label") or v.get("venue_id") or "unknown" for v in venues_missing_credentials)
        alerts.append(
            {
                "severity": "warn",
                "message": f"{len(venues_missing_credentials)} venue(s) enabled without credentials: {venue_labels}.",
            }
        )
    if not alerts:
        alerts.append({"severity": "ok", "message": "No active trading alerts."})

    return {"metrics": metrics, "alerts": alerts}


@router.post("/order")
async def submit_order(request: UnifiedOrderRequest) -> Dict[str, Any]:
    """Submit a manual/agent order through the unified execution router."""
    trader_identity = TraderIdentity(
        trader_type=request.trader_type,
        trader_id=request.trader_id,
    )

    result = await _execution_router.submit_trade(
        trader=trader_identity,
        venue_id=request.venue_id,
        symbol=request.instrument,
        side=request.side,
        size=request.size,
        price=request.price,
        params=request.extra_params,
        metadata=request.metadata,
    )

    return {
        "success": result.success,
        "venue": result.venue,
        "symbol": result.symbol,
        "side": result.side,
        "size": result.size,
        "price": result.price,
        "tx_id": result.tx_id,
        "error": result.error,
        "explanation_id": result.explanation_id,
        "metadata": result.metadata,
    }


class AgentOrderRequest(BaseModel):
    agent_id: str
    venue_id: str
    instrument: str
    side: Literal["buy", "sell"]
    size: float = Field(..., gt=0)
    price: Optional[float] = Field(default=None, gt=0)
    order_type: Literal["market", "limit", "ioc", "fok"] = "market"
    metadata: Dict[str, Any] = Field(default_factory=dict)


@router.post("/agent/order")
async def submit_agent_order(request: AgentOrderRequest) -> Dict[str, Any]:
    """Agent-only shortcut to submit orders through the unified router."""
    trader_identity = TraderIdentity(trader_type="agent", trader_id=request.agent_id)

    result = await _execution_router.submit_trade(
        trader=trader_identity,
        venue_id=request.venue_id,
        symbol=request.instrument,
        side=request.side,
        size=request.size,
        price=request.price,
        params={"order_type": request.order_type},
        metadata=request.metadata,
    )

    return {
        "success": result.success,
        "venue": result.venue,
        "symbol": result.symbol,
        "side": result.side,
        "size": result.size,
        "price": result.price,
        "tx_id": result.tx_id,
        "error": result.error,
        "explanation_id": result.explanation_id,
        "metadata": result.metadata,
    }


@router.get("/spectator/history")
async def get_spectator_history(limit: int = 200) -> Dict[str, Any]:
    """Return recent trading intents/results for spectator UI."""
    log = get_spectator_log()
    events = log.get_recent(limit)
    return {"events": events, "count": len(events)}


@router.websocket("/spectator/stream")
async def spectator_stream(websocket: WebSocket, token: str = Query(None)) -> None:
    """WebSocket endpoint for spectator trading stream with optional authentication."""
    
    # Development bypass - allow anonymous connections in dev mode
    dev_mode = os.getenv("MERID_DEV_ALLOW_WS", "false").lower() in ("1", "true", "yes")
    
    if not dev_mode and not token:
        await websocket.close(code=1008, reason="Token required")
        return
    
    await websocket.accept()
    
    # Log connection
    user = token[:8] + "..." if token and len(token) > 8 else "anonymous"
    if dev_mode:
        user = "dev_user"
    
    log = get_spectator_log()
    await websocket.send_json({
        "type": "snapshot", 
        "events": log.get_recent(200),
        "user": user,
        "message": "Connected to spectator stream"
    })

    event_stream = get_event_stream()
    queue = await event_stream.subscribe()
    try:
        while True:
            record = await queue.get()
            if not record.event_type.startswith("trading."):
                continue
            payload = {
                "type": record.event_type,
                "payload": record.payload,
                "ts": record.timestamp,
            }
            await websocket.send_json(payload)
    except WebSocketDisconnect:
        await event_stream.unsubscribe(queue)
    except Exception:
        await event_stream.unsubscribe(queue)
