"""
Dedicated WebSocket endpoints for trades, prices, and portfolio updates.

These endpoints provide focused streams for specific UI components:
- /ws/trades: Real-time trade execution events
- /ws/prices: Live price updates for symbols
- /ws/portfolio: Portfolio position and balance updates
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from utils.logger import get_logger

logger = get_logger("web.api.ws_dedicated_streams")

router = APIRouter(prefix="/ws", tags=["ws-dedicated"])

HEARTBEAT_INTERVAL = 5


# ============================================
# /ws/trades - Trade Execution Stream
# ============================================

class TradesStreamManager:
    """Manages WebSocket connections for trade events."""
    
    def __init__(self):
        self._subscribers: Set[WebSocket] = set()
        self._recent_trades: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()
    
    async def subscribe(self, websocket: WebSocket) -> None:
        """Add a new subscriber."""
        async with self._lock:
            self._subscribers.add(websocket)
            logger.info(f"Trade stream subscriber added (total: {len(self._subscribers)})")
    
    async def unsubscribe(self, websocket: WebSocket) -> None:
        """Remove a subscriber."""
        async with self._lock:
            self._subscribers.discard(websocket)
            logger.info(f"Trade stream subscriber removed (total: {len(self._subscribers)})")
    
    async def broadcast_trade(self, trade_event: Dict[str, Any]) -> None:
        """Broadcast a trade event to all subscribers."""
        async with self._lock:
            # Store in recent trades
            self._recent_trades.append(trade_event)
            if len(self._recent_trades) > 100:
                self._recent_trades = self._recent_trades[-100:]
            
            # Broadcast to all subscribers
            dead_sockets = []
            for ws in self._subscribers:
                try:
                    await ws.send_json(trade_event)
                except Exception as e:
                    logger.warning(f"Failed to send to trade subscriber: {e}")
                    dead_sockets.append(ws)
            
            # Clean up dead connections
            for ws in dead_sockets:
                self._subscribers.discard(ws)
    
    def get_recent_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent trades for new subscribers."""
        return self._recent_trades[-limit:]


_trades_manager = TradesStreamManager()


def get_trades_manager() -> TradesStreamManager:
    """Get the singleton trades stream manager."""
    return _trades_manager


# NOTE: Disabled - using ws_trade_events.py /ws/trades instead to avoid duplicate routes
# The ws_trade_events.py implementation is more complete with agent decisions, mode changes, etc.
@router.websocket("/trades-dedicated")
async def trades_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for real-time trade execution events.
    
    NOTE: Use /ws/trades from ws_trade_events.py for the main trade stream.
    This endpoint is kept as a backup/dedicated stream.
    
    Emits:
    - order_filled: When an order is filled
    - order_partial: When an order is partially filled
    - order_cancelled: When an order is cancelled
    - order_rejected: When an order is rejected
    """
    await websocket.accept()
    logger.info("Trade stream WebSocket connected")
    
    manager = get_trades_manager()
    await manager.subscribe(websocket)
    
    try:
        # Send recent trades on connection
        recent_trades = manager.get_recent_trades(limit=20)
        if recent_trades:
            await websocket.send_json({
                "type": "trades_snapshot",
                "trades": recent_trades,
                "timestamp": time.time()
            })
        
        # Subscribe to paper trading engine for real trade events
        from trading.paper_trading import get_paper_engine
        
        paper_engine = get_paper_engine()
        
        def trade_callback(event: Dict[str, Any]) -> None:
            """Callback for paper trading events."""
            asyncio.create_task(manager.broadcast_trade(event))
        
        unsubscribe = paper_engine.subscribe_to_trades(trade_callback, limit=20)
        
        # Keep connection alive and send heartbeats
        last_heartbeat = time.time()
        
        while True:
            try:
                # Wait for messages from client (with timeout for heartbeat)
                message = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=HEARTBEAT_INTERVAL
                )
                
                # Handle client messages if needed
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": time.time()})
                
            except asyncio.TimeoutError:
                # Send heartbeat
                now = time.time()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                    await websocket.send_json({
                        "type": "heartbeat",
                        "timestamp": now
                    })
                    last_heartbeat = now
    
    except WebSocketDisconnect:
        logger.info("Trade stream WebSocket disconnected")
    except Exception as e:
        logger.error(f"Trade stream error: {e}")
    finally:
        await manager.unsubscribe(websocket)
        try:
            unsubscribe()
        except:
            pass


# ============================================
# /ws/prices - Live Price Stream
# ============================================

class PricesStreamManager:
    """Manages WebSocket connections for price updates."""
    
    def __init__(self):
        self._subscribers: Dict[WebSocket, Set[str]] = {}  # ws -> symbols
        self._current_prices: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
    
    async def subscribe(self, websocket: WebSocket, symbols: List[str]) -> None:
        """Add a new subscriber with symbol filters."""
        async with self._lock:
            self._subscribers[websocket] = set(symbols) if symbols else set()
            logger.info(f"Price stream subscriber added for {len(symbols)} symbols (total: {len(self._subscribers)})")
    
    async def unsubscribe(self, websocket: WebSocket) -> None:
        """Remove a subscriber."""
        async with self._lock:
            if websocket in self._subscribers:
                del self._subscribers[websocket]
                logger.info(f"Price stream subscriber removed (total: {len(self._subscribers)})")
    
    async def broadcast_price(self, symbol: str, price_data: Dict[str, Any]) -> None:
        """Broadcast a price update to relevant subscribers."""
        async with self._lock:
            # Store current price
            self._current_prices[symbol] = price_data
            
            # Broadcast to subscribers watching this symbol
            dead_sockets = []
            for ws, symbols in self._subscribers.items():
                # Send if no filter or symbol in filter
                if not symbols or symbol in symbols:
                    try:
                        await ws.send_json({
                            "type": "price_update",
                            "symbol": symbol,
                            **price_data
                        })
                    except Exception as e:
                        logger.warning(f"Failed to send to price subscriber: {e}")
                        dead_sockets.append(ws)
            
            # Clean up dead connections
            for ws in dead_sockets:
                self._subscribers.pop(ws, None)
    
    def get_current_prices(self, symbols: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
        """Get current prices for symbols."""
        if symbols:
            return {s: self._current_prices.get(s, {}) for s in symbols if s in self._current_prices}
        return self._current_prices.copy()


_prices_manager = PricesStreamManager()


def get_prices_manager() -> PricesStreamManager:
    """Get the singleton prices stream manager."""
    return _prices_manager


# NOTE: Renamed to avoid duplicate route with streams.py /ws/prices
@router.websocket("/prices-dedicated")
async def prices_websocket(
    websocket: WebSocket,
    symbols: str = Query(default="")
):
    """
    WebSocket endpoint for live price updates.
    
    Query params:
    - symbols: Comma-separated list of symbols to watch (e.g., "BTC/USD,ETH/USD")
               If empty, receives all price updates.
    
    Emits:
    - price_update: Real-time price changes
    """
    await websocket.accept()
    
    # Parse symbols filter
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else []
    logger.info(f"Price stream WebSocket connected for symbols: {symbol_list or 'ALL'}")
    
    manager = get_prices_manager()
    await manager.subscribe(websocket, symbol_list)
    
    try:
        # Send current prices on connection
        current_prices = manager.get_current_prices(symbol_list if symbol_list else None)
        if current_prices:
            await websocket.send_json({
                "type": "prices_snapshot",
                "prices": current_prices,
                "timestamp": time.time()
            })
        
        # Subscribe to live price feed
        from data.live_price_feed import get_live_price_feed
        
        price_feed = get_live_price_feed()
        
        def price_callback(price_data) -> None:
            """Callback for price updates."""
            asyncio.create_task(manager.broadcast_price(
                price_data.symbol,
                {
                    "price": price_data.price,
                    "volume": price_data.volume,
                    "timestamp": price_data.timestamp,
                    "change_24h": getattr(price_data, 'change_24h', None)
                }
            ))
        
        price_feed.subscribe(price_callback)
        
        # Keep connection alive
        last_heartbeat = time.time()
        
        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=HEARTBEAT_INTERVAL
                )
                
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": time.time()})
                elif message.get("type") == "subscribe":
                    # Update symbol filter
                    new_symbols = message.get("symbols", [])
                    await manager.subscribe(websocket, new_symbols)
            
            except asyncio.TimeoutError:
                now = time.time()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                    await websocket.send_json({
                        "type": "heartbeat",
                        "timestamp": now
                    })
                    last_heartbeat = now
    
    except WebSocketDisconnect:
        logger.info("Price stream WebSocket disconnected")
    except Exception as e:
        logger.error(f"Price stream error: {e}")
    finally:
        await manager.unsubscribe(websocket)


# ============================================
# /ws/portfolio - Portfolio Updates Stream
# ============================================

class PortfolioStreamManager:
    """Manages WebSocket connections for portfolio updates."""
    
    def __init__(self):
        self._subscribers: Set[WebSocket] = set()
        self._current_portfolio: Optional[Dict[str, Any]] = None
        self._lock = asyncio.Lock()
    
    async def subscribe(self, websocket: WebSocket) -> None:
        """Add a new subscriber."""
        async with self._lock:
            self._subscribers.add(websocket)
            logger.info(f"Portfolio stream subscriber added (total: {len(self._subscribers)})")
    
    async def unsubscribe(self, websocket: WebSocket) -> None:
        """Remove a subscriber."""
        async with self._lock:
            self._subscribers.discard(websocket)
            logger.info(f"Portfolio stream subscriber removed (total: {len(self._subscribers)})")
    
    async def broadcast_portfolio(self, portfolio_data: Dict[str, Any]) -> None:
        """Broadcast portfolio update to all subscribers."""
        async with self._lock:
            # Store current portfolio
            self._current_portfolio = portfolio_data
            
            # Broadcast to all subscribers
            dead_sockets = []
            for ws in self._subscribers:
                try:
                    await ws.send_json({
                        "type": "portfolio_update",
                        **portfolio_data
                    })
                except Exception as e:
                    logger.warning(f"Failed to send to portfolio subscriber: {e}")
                    dead_sockets.append(ws)
            
            # Clean up dead connections
            for ws in dead_sockets:
                self._subscribers.discard(ws)
    
    def get_current_portfolio(self) -> Optional[Dict[str, Any]]:
        """Get current portfolio snapshot."""
        return self._current_portfolio


_portfolio_manager = PortfolioStreamManager()


def get_portfolio_manager() -> PortfolioStreamManager:
    """Get the singleton portfolio stream manager."""
    return _portfolio_manager


@router.websocket("/portfolio")
async def portfolio_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for portfolio position and balance updates.
    
    Emits:
    - portfolio_update: Real-time portfolio changes
    - position_opened: New position opened
    - position_closed: Position closed
    - balance_update: Balance changed
    """
    await websocket.accept()
    logger.info("Portfolio stream WebSocket connected")
    
    manager = get_portfolio_manager()
    await manager.subscribe(websocket)
    
    try:
        # Send current portfolio on connection
        current_portfolio = manager.get_current_portfolio()
        if current_portfolio:
            await websocket.send_json({
                "type": "portfolio_snapshot",
                **current_portfolio,
                "timestamp": time.time()
            })
        
        # Subscribe to paper trading engine for portfolio updates
        from trading.paper_trading import get_paper_engine
        
        paper_engine = get_paper_engine()
        
        def summary_callback(event: Dict[str, Any]) -> None:
            """Callback for portfolio summary updates."""
            asyncio.create_task(manager.broadcast_portfolio(event.get("stats", {})))
        
        def position_callback(event: Dict[str, Any]) -> None:
            """Callback for position updates."""
            asyncio.create_task(websocket.send_json({
                "type": "positions_update",
                "positions": event.get("positions", []),
                "timestamp": time.time()
            }))
        
        unsubscribe_summary = paper_engine.subscribe_to_summary(summary_callback)
        unsubscribe_positions = paper_engine.subscribe_to_positions(position_callback, limit=50)
        
        # Keep connection alive
        last_heartbeat = time.time()
        
        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=HEARTBEAT_INTERVAL
                )
                
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": time.time()})
                elif message.get("type") == "refresh":
                    # Force refresh portfolio data
                    stats = paper_engine.get_global_stats()
                    await websocket.send_json({
                        "type": "portfolio_snapshot",
                        **stats,
                        "timestamp": time.time()
                    })
            
            except asyncio.TimeoutError:
                now = time.time()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                    await websocket.send_json({
                        "type": "heartbeat",
                        "timestamp": now
                    })
                    last_heartbeat = now
    
    except WebSocketDisconnect:
        logger.info("Portfolio stream WebSocket disconnected")
    except Exception as e:
        logger.error(f"Portfolio stream error: {e}")
    finally:
        await manager.unsubscribe(websocket)
        try:
            unsubscribe_summary()
            unsubscribe_positions()
        except:
            pass
