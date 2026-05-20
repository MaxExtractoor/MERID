"""Portfolio Service API - REST and WebSocket endpoints.

This module provides:
- REST endpoints for portfolio snapshots
- WebSocket endpoint for real-time portfolio updates
- Integration with portfolio engine and PnL computer
- Real-time push of portfolio state changes

Design principles:
- Portfolio engine is single source of truth
- REST for snapshots, WebSocket for real-time deltas
- All monetary values in cents (integers) except PnL (Decimal)
- Thread-safe singleton access
"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Set, Literal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from utils.logger import get_logger
from merid.event_venues.kalshi.portfolio_engine import get_portfolio_engine
from merid.event_venues.kalshi.portfolio_pnl_computer import (
    get_pnl_computer,
    PortfolioPnLUpdate,
)

logger = get_logger("web.api.portfolio")


# ═══════════════════════════════════════════════════════════════════════════
# Pydantic Models for API (Frozen Data Contract)
# ═══════════════════════════════════════════════════════════════════════════

class PositionSnapshot(BaseModel):
    """Single position snapshot."""
    instrument_id: str = Field(..., description="Kalshi market ticker + side (e.g., KXBTC-15M_yes)")
    ticker: str = Field(..., description="Kalshi market ticker")
    side: str = Field(..., description="Position side: 'yes' or 'no'")
    quantity: int = Field(..., description="Signed quantity (positive for long, negative for short)")
    avg_entry_price_cents: int = Field(..., description="Weighted average entry price in cents")
    mark_price_cents: int = Field(..., description="Current market price in cents")
    unrealized_pnl_cents: int = Field(..., description="Unrealized PnL in cents")
    unrealized_pnl_usd: float = Field(..., description="Unrealized PnL in USD")
    last_updated: str = Field(..., description="ISO timestamp of last update")


class PortfolioSnapshotResponse(BaseModel):
    """Portfolio snapshot response - frozen data contract."""
    account_id: str = Field(..., description="Account identifier")
    sequence_id: int = Field(..., description="Last processed event sequence ID")
    timestamp: str = Field(..., description="ISO timestamp of snapshot")
    
    # Cash state
    cash_available_cents: int = Field(..., description="Available cash in cents")
    cash_available_usd: float = Field(..., description="Available cash in USD")
    cash_reserved_cents: int = Field(..., description="Reserved cash for open orders in cents")
    cash_total_cents: int = Field(..., description="Total cash (available + reserved) in cents")
    
    # Portfolio value (analogous to Kalshi's portfolio_value)
    portfolio_value_cents: int = Field(..., description="Portfolio mark-to-market value in cents")
    portfolio_value_usd: float = Field(..., description="Portfolio mark-to-market value in USD")
    
    # PnL
    realized_pnl_cents: int = Field(..., description="Crystallized PnL in cents")
    realized_pnl_usd: float = Field(..., description="Crystallized PnL in USD")
    unrealized_pnl_cents: int = Field(..., description="Unrealized PnL in cents")
    unrealized_pnl_usd: float = Field(..., description="Unrealized PnL in USD")
    total_pnl_cents: int = Field(..., description="Total PnL (realized + unrealized) in cents")
    total_pnl_usd: float = Field(..., description="Total PnL in USD")
    
    # Total equity
    total_equity_cents: int = Field(..., description="Total equity (cash + portfolio_value) in cents")
    total_equity_usd: float = Field(..., description="Total equity in USD")
    
    # Positions
    positions: list[PositionSnapshot] = Field(default_factory=list, description="Open positions")
    position_count: int = Field(..., description="Number of open positions")
    
    # Open orders (optional, for ExecuteView margin display)
    open_orders_count: int = Field(default=0, description="Number of open orders")
    open_orders_reserved_cents: int = Field(default=0, description="Cash reserved for open orders in cents")


class WebSocketMessage(BaseModel):
    """Base WebSocket message."""
    type: Literal["snapshot", "delta", "ping"] = Field(..., description="Message type")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SnapshotMessage(WebSocketMessage):
    """Full snapshot message."""
    type: Literal["snapshot"] = "snapshot"
    data: PortfolioSnapshotResponse = Field(..., description="Full portfolio snapshot")


class DeltaMessage(WebSocketMessage):
    """Delta update message (partial update)."""
    type: Literal["delta"] = "delta"
    data: Dict[str, Any] = Field(..., description="Delta changes (changed positions, updated aggregates)")


class PingMessage(WebSocketMessage):
    """Ping message for keep-alive."""
    type: Literal["ping"] = "ping"
    data: Optional[Dict[str, Any]] = None


# ═══════════════════════════════════════════════════════════════════════════
# Portfolio Service API
# ═══════════════════════════════════════════════════════════════════════════

router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])

# WebSocket connection manager
class ConnectionManager:
    """Manages WebSocket connections for portfolio updates."""
    
    def __init__(self):
        self._active_connections: Set[WebSocket] = set()
        self._lock = threading.Lock()
    
    async def connect(self, websocket: WebSocket, account_id: str = "default") -> None:
        """Accept a WebSocket connection."""
        # Connection already accepted by handler
        with self._lock:
            self._active_connections.add(websocket)
        logger.info(
            "Portfolio WebSocket: connection accepted (account=%s, total=%d)",
            account_id,
            len(self._active_connections)
        )
    
    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        with self._lock:
            self._active_connections.discard(websocket)
        logger.info(
            "Portfolio WebSocket: connection closed (total=%d)",
            len(self._active_connections)
        )
    
    async def broadcast_pnl_update(self, pnl_update: PortfolioPnLUpdate) -> None:
        """Broadcast PnL update to all connected clients."""
        message = pnl_update.to_dict()
        
        with self._lock:
            connections = list(self._active_connections)
        
        disconnected = []
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(
                    "Portfolio WebSocket: error sending to client: %s",
                    e
                )
                disconnected.append(connection)
        
        # Clean up disconnected clients
        for connection in disconnected:
            self.disconnect(connection)


manager = ConnectionManager()


# ═══════════════════════════════════════════════════════════════════════════
# REST Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/snapshot/{account_id}", response_model=PortfolioSnapshotResponse)
async def get_portfolio_snapshot(account_id: str = "default") -> PortfolioSnapshotResponse:
    """Get current portfolio snapshot.
    
    Args:
        account_id: Account ID (default: "default")
        
    Returns:
        PortfolioSnapshotResponse with current state
    """
    engine = get_portfolio_engine()
    pnl_computer = get_pnl_computer()
    
    # Get snapshot with current PnL
    snapshot = pnl_computer.get_snapshot_with_pnl(account_id)
    snapshot_dict = snapshot.to_dict()
    
    return PortfolioSnapshotResponse(**snapshot_dict)


@router.get("/snapshot", response_model=PortfolioSnapshotResponse)
async def get_default_portfolio_snapshot() -> PortfolioSnapshotResponse:
    """Get default portfolio snapshot (account_id="default")."""
    return await get_portfolio_snapshot("default")


@router.get("/sequence/{account_id}")
async def get_last_sequence_id(account_id: str = "default") -> Dict[str, Any]:
    """Get the last processed sequence ID.
    
    Args:
        account_id: Account ID (default: "default")
        
    Returns:
        Dictionary with sequence_id
    """
    engine = get_portfolio_engine()
    sequence_id = engine.get_last_sequence_id()
    
    return {
        "account_id": account_id,
        "sequence_id": sequence_id,
    }


# ═══════════════════════════════════════════════════════════════════════════
# WebSocket Endpoint
# ═══════════════════════════════════════════════════════════════════════════

@router.websocket("/ws/{account_id}")
async def portfolio_websocket(websocket: WebSocket, account_id: str = "default") -> None:
    """WebSocket endpoint for real-time portfolio updates.
    
    Args:
        websocket: WebSocket connection
        account_id: Account ID (default: "default")
    """
    # Accept the connection immediately to avoid 403
    await websocket.accept()
    await manager.connect(websocket, account_id)
    
    # Send initial snapshot
    try:
        engine = get_portfolio_engine()
        pnl_computer = get_pnl_computer()
        snapshot = pnl_computer.get_snapshot_with_pnl(account_id)
        await websocket.send_json(snapshot.to_dict())
    except Exception as e:
        logger.error(
            "Portfolio WebSocket: error sending initial snapshot: %s",
            e,
            exc_info=True
        )
    
    # Subscribe to PnL updates
    def on_pnl_update(pnl_update: PortfolioPnLUpdate) -> None:
        """Handle PnL update and broadcast to client."""
        asyncio.create_task(manager.broadcast_pnl_update(pnl_update))
    
    pnl_computer = get_pnl_computer()
    pnl_computer.subscribe(on_pnl_update)
    
    try:
        # Keep connection alive
        while True:
            # Wait for client messages (keep-alive pings)
            data = await websocket.receive_text()
            # Echo back or handle client commands
            await websocket.send_json({"type": "pong", "data": data})
    except WebSocketDisconnect:
        logger.info("Portfolio WebSocket: client disconnected")
    except Exception as e:
        logger.error(
            "Portfolio WebSocket: error in connection loop: %s",
            e,
            exc_info=True
        )
    finally:
        pnl_computer.unsubscribe(on_pnl_update)
        manager.disconnect(websocket)


@router.websocket("/ws")
async def portfolio_websocket_default(websocket: WebSocket) -> None:
    """WebSocket endpoint for default account (account_id="default")."""
    await websocket.accept()
    await portfolio_websocket(websocket, "default")
