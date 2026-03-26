"""
Local Venue API Endpoints

REST endpoints for the local venue/microstructure section:
- Engine status and control
- Order book data
- Recent trades
- Feed handler health
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from pydantic import BaseModel, Field

try:
    from execution.simulator import get_execution_simulator
except ImportError:  # pragma: no cover - optional simulator
    class _DummySimulator:
        def __init__(self):
            self._running = False
            self._order_queue = []
            self._message_count = 0
            self._start_time = time.time()

        async def start(self):
            self._running = True

        async def stop(self):
            self._running = False

    _dummy_simulator = _DummySimulator()

    def get_execution_simulator():
        return _dummy_simulator
from execution.persistent_book import get_persistent_book_manager
from execution.book_builder import get_book_builder
from data.feed_handlers import get_feed_handler_manager
from venues.local_sim_adapter import create_local_sim_adapter
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/localvenue", tags=["local-venue"])


class EngineStatus(BaseModel):
    """Engine status response."""
    is_running: bool
    queue_depth: int = 0
    messages_per_sec: float = 0.0
    dropped_messages: int = 0
    last_match_ts: Optional[float] = None
    total_trades: int = 0
    uptime_seconds: float = 0.0


class OrderBookLevel(BaseModel):
    """Order book level."""
    price: float
    quantity: int


class OrderBookResponse(BaseModel):
    """Order book response."""
    symbol: str
    timestamp: float
    bids: List[OrderBookLevel]
    asks: List[OrderBookLevel]
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    spread: Optional[float] = None
    sequence_number: int = 0


class Trade(BaseModel):
    """Trade response."""
    symbol: str
    side: str
    quantity: int
    price: float
    timestamp: float
    trade_id: str
    pnl: float = 0.0


class TradesResponse(BaseModel):
    """Trades response."""
    trades: List[Trade]
    total_count: int


class ControlRequest(BaseModel):
    """Control request."""
    action: str = Field(..., description="Action to perform: start, stop, flush_orders, reset_book")
    reason: str = Field(default="dashboard", description="Reason for the action")


class ControlResponse(BaseModel):
    """Control response."""
    success: bool
    message: str
    timestamp: float


class FeedHandlerStatus(BaseModel):
    """Feed handler status."""
    handler_name: str
    handler_type: str
    status: str
    last_heartbeat: float
    symbol_count: int
    messages_per_sec: float = 0.0
    error_count: int = 0


# Global state
_local_adapter = None
_websocket_connections: List[WebSocket] = []


@router.get("/engine-status", response_model=EngineStatus)
async def get_engine_status():
    """Get local venue engine status."""
    try:
        global _local_adapter
        if _local_adapter is None:
            _local_adapter = create_local_sim_adapter()
        
        simulator = get_execution_simulator()
        book_manager = get_persistent_book_manager()
        
        # Get engine metrics
        is_running = simulator._running if hasattr(simulator, '_running') else False
        queue_depth = len(simulator._order_queue) if hasattr(simulator, '_order_queue') else 0
        
        # Calculate messages per second
        messages_per_sec = 0.0
        if hasattr(simulator, '_message_count') and hasattr(simulator, '_start_time'):
            elapsed = time.time() - simulator._start_time
            if elapsed > 0:
                messages_per_sec = simulator._message_count / elapsed
        
        # Get total trades
        total_trades = 0
        for symbol in book_manager.get_symbols():
            book = book_manager.get_book(symbol)
            if book:
                events = book.query_events()
                total_trades += len([e for e in events if e.event_type.value == 'execute_order'])
        
        return EngineStatus(
            is_running=is_running,
            queue_depth=queue_depth,
            messages_per_sec=messages_per_sec,
            dropped_messages=0,  # TODO: Implement dropped message tracking
            last_match_ts=time.time() if is_running else None,
            total_trades=total_trades,
            uptime_seconds=time.time() if is_running else 0.0
        )
    
    except Exception as e:
        logger.error(f"Error getting engine status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orderbook", response_model=OrderBookResponse)
async def get_order_book(symbol: str = "BTCUSDT", limit: int = 20):
    """Get order book for a symbol."""
    try:
        book_builder = get_book_builder()
        book = book_builder.get_book(symbol)
        
        if not book:
            # Try to get from persistent book manager
            book_manager = get_persistent_book_manager()
            persistent_book = book_manager.get_book(symbol)
            snapshot = persistent_book.get_snapshot()
            
            return OrderBookResponse(
                symbol=symbol,
                timestamp=snapshot.timestamp,
                bids=[OrderBookLevel(price=level.price, quantity=level.quantity) for level in snapshot.bids[:limit]],
                asks=[OrderBookLevel(price=level.price, quantity=level.quantity) for level in snapshot.asks[:limit]],
                best_bid=persistent_book.get_best_bid(),
                best_ask=persistent_book.get_best_ask(),
                spread=persistent_book.get_spread(),
                sequence_number=snapshot.sequence_number
            )
        
        # Get from book builder
        snapshot = book.get_snapshot()
        
        return OrderBookResponse(
            symbol=symbol,
            timestamp=snapshot["timestamp"],
            bids=[OrderBookLevel(price=level["price"], quantity=level["quantity"]) for level in snapshot["bids"][:limit]],
            asks=[OrderBookLevel(price=level["price"], quantity=level["quantity"]) for level in snapshot["asks"][:limit]],
            best_bid=snapshot.get("best_bid"),
            best_ask=snapshot.get("best_ask"),
            spread=snapshot.get("spread"),
            sequence_number=snapshot.get("sequence_number", 0)
        )
    
    except Exception as e:
        logger.error(f"Error getting order book for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trades", response_model=TradesResponse)
async def get_trades(limit: int = 50, symbol: Optional[str] = None):
    """Get recent trades."""
    try:
        book_manager = get_persistent_book_manager()
        all_trades = []
        
        symbols_to_check = [symbol] if symbol else book_manager.get_symbols()
        
        for sym in symbols_to_check:
            book = book_manager.get_book(sym)
            if book:
                events = book.query_events()
                trade_events = [e for e in events if e.event_type.value == 'execute_order']
                
                for event in trade_events[-limit:]:  # Get recent trades
                    trade = Trade(
                        symbol=sym,
                        side=event.metadata.get('side', 'unknown'),
                        quantity=event.quantity,
                        price=event.price,
                        timestamp=event.timestamp,
                        trade_id=f"{sym}_{int(event.timestamp * 1000000)}",
                        pnl=0.0  # TODO: Calculate P&L
                    )
                    all_trades.append(trade)
        
        # Sort by timestamp and limit
        all_trades.sort(key=lambda t: t.timestamp, reverse=True)
        all_trades = all_trades[:limit]
        
        return TradesResponse(
            trades=all_trades,
            total_count=len(all_trades)
        )
    
    except Exception as e:
        logger.error(f"Error getting trades: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/control", response_model=ControlResponse)
async def control_engine(request: ControlRequest, background_tasks: BackgroundTasks):
    """Control the local venue engine."""
    try:
        global _local_adapter
        if _local_adapter is None:
            _local_adapter = create_local_sim_adapter()
        
        simulator = get_execution_simulator()
        book_manager = get_persistent_book_manager()
        
        action = request.action.lower()
        reason = request.reason
        
        if action == "start":
            if not simulator._running:
                await simulator.start()
                book_manager.start_all()
                logger.info(f"Engine started: {reason}")
                return ControlResponse(
                    success=True,
                    message="Engine started successfully",
                    timestamp=time.time()
                )
            else:
                return ControlResponse(
                    success=False,
                    message="Engine is already running",
                    timestamp=time.time()
                )
        
        elif action == "stop":
            if simulator._running:
                await simulator.stop()
                book_manager.stop_all()
                logger.info(f"Engine stopped: {reason}")
                return ControlResponse(
                    success=True,
                    message="Engine stopped successfully",
                    timestamp=time.time()
                )
            else:
                return ControlResponse(
                    success=False,
                    message="Engine is not running",
                    timestamp=time.time()
                )
        
        elif action == "flush_orders":
            # Flush all orders
            for symbol in book_manager.get_symbols():
                book = book_manager.get_book(symbol)
                if book:
                    # Clear orders but keep book structure
                    book._clear_book()
            
            logger.info(f"Orders flushed: {reason}")
            return ControlResponse(
                success=True,
                message="Orders flushed successfully",
                timestamp=time.time()
            )
        
        elif action == "reset_book":
            # Reset all order books
            for symbol in book_manager.get_symbols():
                book = book_manager.get_book(symbol)
                if book:
                    book._clear_book()
            
            logger.info(f"Order books reset: {reason}")
            return ControlResponse(
                success=True,
                message="Order books reset successfully",
                timestamp=time.time()
            )
        
        else:
            return ControlResponse(
                success=False,
                message=f"Unknown action: {action}",
                timestamp=time.time()
            )
    
    except Exception as e:
        logger.error(f"Error controlling engine: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/feed-handlers")
async def get_feed_handlers():
    """Get feed handler status."""
    try:
        feed_manager = get_feed_handler_manager()
        handlers = feed_manager.list_handlers()
        
        return [
            FeedHandlerStatus(
                handler_name=handler["handler_name"],
                handler_type=handler["handler_type"],
                status=handler["status"],
                last_heartbeat=handler["last_heartbeat"],
                symbol_count=handler["symbol_count"]
            )
            for handler in handlers
        ]
    
    except Exception as e:
        logger.error(f"Error getting feed handlers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await websocket.accept()
    _websocket_connections.append(websocket)
    
    try:
        while True:
            # Send periodic updates
            await asyncio.sleep(1)
            
            # Get current status
            status = await get_engine_status()
            await websocket.send_json({
                "type": "engine_status",
                "data": status.dict()
            })
            
            # Check for new trades
            trades = await get_trades(limit=10)
            if trades.trades:
                await websocket.send_json({
                    "type": "trades",
                    "data": [trade.dict() for trade in trades.trades]
                })
    
    except WebSocketDisconnect:
        _websocket_connections.remove(websocket)
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        if websocket in _websocket_connections:
            _websocket_connections.remove(websocket)


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        simulator = get_execution_simulator()
        book_manager = get_persistent_book_manager()
        
        is_healthy = simulator._running if hasattr(simulator, '_running') else False
        
        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "engine_running": is_healthy,
            "order_books": len(book_manager.get_symbols()),
            "timestamp": time.time()
        }
    
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": time.time()
        }
