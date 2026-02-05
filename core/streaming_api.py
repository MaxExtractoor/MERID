"""MERID FastAPI Real-Time Streaming Endpoints.

Server-Sent Events (SSE) and WebSocket endpoints for real-time data streaming
to the React dashboard. Supports price ticks, order updates, and swarm events.
"""

from typing import AsyncIterator, Dict, Any, Optional, List
import asyncio
import json
from datetime import datetime
import structlog

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

logger = structlog.get_logger(__name__)


class StreamingManager:
    """Manages SSE and WebSocket streams."""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[str, List[WebSocket]] = {}  # channel -> websockets
        self.logger = logger.bind(component="StreamingManager")
        self.price_queues: Dict[str, asyncio.Queue] = {}
    
    async def connect(self, websocket: WebSocket):
        """Accept new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        self.logger.info(
            "websocket_connected",
            total=len(self.active_connections)
        )
    
    def disconnect(self, websocket: WebSocket):
        """Remove disconnected WebSocket."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            
            # Remove from subscriptions
            for channel, sockets in self.subscriptions.items():
                if websocket in sockets:
                    sockets.remove(websocket)
        
        self.logger.info(
            "websocket_disconnected",
            remaining=len(self.active_connections)
        )
    
    def subscribe(self, websocket: WebSocket, channel: str):
        """Subscribe WebSocket to a channel."""
        if channel not in self.subscriptions:
            self.subscriptions[channel] = []
        
        if websocket not in self.subscriptions[channel]:
            self.subscriptions[channel].append(websocket)
        
        self.logger.info("channel_subscribed", channel=channel)
    
    async def broadcast_to_channel(self, channel: str, message: Dict[str, Any]):
        """Broadcast message to all subscribers of a channel."""
        if channel not in self.subscriptions:
            return
        
        disconnected = []
        message_json = json.dumps(message)
        
        for websocket in self.subscriptions[channel]:
            try:
                await websocket.send_text(message_json)
            except Exception:
                disconnected.append(websocket)
        
        # Clean up disconnected sockets
        for ws in disconnected:
            self.disconnect(ws)
    
    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast message to all connections."""
        disconnected = []
        message_json = json.dumps(message)
        
        for websocket in self.active_connections:
            try:
                await websocket.send_text(message_json)
            except Exception:
                disconnected.append(websocket)
        
        for ws in disconnected:
            self.disconnect(ws)


# Singleton instance
stream_manager = StreamingManager()


async def price_stream_generator(symbol: str) -> AsyncIterator[str]:
    """Generator for price SSE stream."""
    queue = asyncio.Queue()
    stream_manager.price_queues[symbol] = queue
    
    try:
        while True:
            # Wait for price update
            price_data = await queue.get()
            
            # Format as SSE
            yield f"data: {json.dumps(price_data)}\n\n"
            
    except asyncio.CancelledError:
        del stream_manager.price_queues[symbol]
        raise


async def order_update_generator() -> AsyncIterator[str]:
    """Generator for order update SSE stream."""
    queue = asyncio.Queue()
    
    try:
        while True:
            # Wait for order update
            order_data = await queue.get()
            
            yield f"data: {json.dumps(order_data)}\n\n"
            
    except asyncio.CancelledError:
        raise


async def swarm_event_generator() -> AsyncIterator[str]:
    """Generator for swarm agent events SSE."""
    queue = asyncio.Queue()
    
    try:
        while True:
            event = await queue.get()
            yield f"data: {json.dumps(event)}\n\n"
            
    except asyncio.CancelledError:
        raise


class PriceFeedSimulator:
    """Simulates price feed for testing/demo."""
    
    def __init__(self, symbols: List[str] = None):
        self.symbols = symbols or ["AAPL", "TSLA", "BTC-USD", "ETH-USD"]
        self.base_prices = {
            "AAPL": 175.0,
            "TSLA": 240.0,
            "BTC-USD": 43000.0,
            "ETH-USD": 2600.0
        }
        self.running = False
        self.logger = logger.bind(component="PriceFeedSimulator")
    
    async def start(self, update_interval: float = 0.5):
        """Start simulating price updates."""
        self.running = True
        self.logger.info("price_simulation_started", symbols=self.symbols)
        
        import random
        
        while self.running:
            for symbol in self.symbols:
                # Generate random price movement
                base = self.base_prices.get(symbol, 100.0)
                change = random.uniform(-0.002, 0.002)
                new_price = base * (1 + change)
                self.base_prices[symbol] = new_price
                
                price_data = {
                    "type": "price",
                    "symbol": symbol,
                    "price": round(new_price, 2),
                    "timestamp": datetime.now().isoformat(),
                    "change": round(change * 100, 3)
                }
                
                # Broadcast to channel
                await stream_manager.broadcast_to_channel(
                    f"prices:{symbol}",
                    price_data
                )
                
                # Also to general prices channel
                await stream_manager.broadcast_to_channel("prices", price_data)
                
                # Send via SSE queues if any
                if symbol in stream_manager.price_queues:
                    try:
                        stream_manager.price_queues[symbol].put_nowait(price_data)
                    except Exception:
                        pass
            
            await asyncio.sleep(update_interval)
    
    def stop(self):
        """Stop simulation."""
        self.running = False
        self.logger.info("price_simulation_stopped")


# FastAPI route handlers

def register_streaming_routes(app: FastAPI):
    """Register streaming routes with FastAPI app."""
    
    @app.get("/api/stream/prices/{symbol}")
    async def stream_prices_sse(symbol: str):
        """SSE endpoint for real-time price streaming."""
        return StreamingResponse(
            price_stream_generator(symbol),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"  # Disable nginx buffering
            }
        )
    
    @app.get("/api/stream/orders")
    async def stream_orders_sse():
        """SSE endpoint for order updates."""
        return StreamingResponse(
            order_update_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"}
        )
    
    @app.get("/api/stream/swarm")
    async def stream_swarm_events_sse():
        """SSE endpoint for swarm agent events."""
        return StreamingResponse(
            swarm_event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"}
        )
    
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for bidirectional streaming."""
        await stream_manager.connect(websocket)
        
        try:
            while True:
                # Receive message
                data = await websocket.receive_text()
                message = json.loads(data)
                
                # Handle subscription
                if message.get("action") == "subscribe":
                    channel = message.get("channel")
                    if channel:
                        stream_manager.subscribe(websocket, channel)
                        await websocket.send_json({
                            "type": "subscribed",
                            "channel": channel
                        })
                
                # Handle ping
                elif message.get("action") == "ping":
                    await websocket.send_json({"type": "pong"})
                
                else:
                    # Echo back or process
                    await websocket.send_json({
                        "type": "received",
                        "data": message
                    })
                    
        except WebSocketDisconnect:
            stream_manager.disconnect(websocket)
        except Exception as e:
            logger.error("websocket_error", error=str(e))
            stream_manager.disconnect(websocket)
    
    @app.post("/api/stream/broadcast")
    async def broadcast_message(message: Dict[str, Any]):
        """Broadcast message to all connected clients."""
        await stream_manager.broadcast(message)
        return {"status": "broadcast", "connections": len(stream_manager.active_connections)}


class DashboardDataBroadcaster:
    """Helper for broadcasting dashboard data."""
    
    def __init__(self):
        self.logger = logger.bind(component="DashboardDataBroadcaster")
    
    async def broadcast_price_update(self, symbol: str, price: float, change: float):
        """Broadcast price update."""
        await stream_manager.broadcast_to_channel("prices", {
            "type": "price",
            "symbol": symbol,
            "price": price,
            "change": change,
            "timestamp": datetime.now().isoformat()
        })
    
    async def broadcast_order_update(self, order_id: str, status: str, data: Dict):
        """Broadcast order status update."""
        await stream_manager.broadcast_to_channel("orders", {
            "type": "order",
            "order_id": order_id,
            "status": status,
            "data": data,
            "timestamp": datetime.now().isoformat()
        })
    
    async def broadcast_risk_alert(self, alert_type: str, severity: str, message: str):
        """Broadcast risk alert."""
        await stream_manager.broadcast_to_channel("risk", {
            "type": "risk_alert",
            "alert_type": alert_type,
            "severity": severity,
            "message": message,
            "timestamp": datetime.now().isoformat()
        })
    
    async def broadcast_swarm_event(self, agent: str, event_type: str, data: Dict):
        """Broadcast swarm agent event."""
        await stream_manager.broadcast_to_channel("swarm", {
            "type": "swarm_event",
            "agent": agent,
            "event_type": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat()
        })
    
    async def broadcast_sentiment_update(self, ticker: str, score: float, mentions: int):
        """Broadcast sentiment update."""
        await stream_manager.broadcast_to_channel("sentiment", {
            "type": "sentiment",
            "ticker": ticker,
            "score": score,
            "mentions": mentions,
            "timestamp": datetime.now().isoformat()
        })


# Singleton
dashboard_broadcaster = DashboardDataBroadcaster()
