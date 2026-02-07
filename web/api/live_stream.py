"""
Live Stream WebSocket Endpoint - Production streaming to UI.

Connects UI clients to the event bus for real-time updates.
"""

from __future__ import annotations

import asyncio
import json
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from core.streaming_bus import streaming_bus, EventChannel
from utils.logger import get_logger

logger = get_logger("web.api.live_stream")

router = APIRouter()


class ConnectionManager:
    """Manages WebSocket connections."""
    
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
    
    async def connect(self, websocket: WebSocket):
        """Accept new WebSocket connection."""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket connected - {len(self.active_connections)} active")
    
    def disconnect(self, websocket: WebSocket):
        """Remove WebSocket connection."""
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket disconnected - {len(self.active_connections)} active")
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients."""
        dead_connections = set()
        
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as exc:
                logger.warning(f"Failed to send to client: {exc}")
                dead_connections.add(connection)
        
        # Clean up dead connections
        for connection in dead_connections:
            self.disconnect(connection)


manager = ConnectionManager()


@router.websocket("/ws/live")
async def websocket_live_stream(websocket: WebSocket):
    """
    Live data stream WebSocket endpoint.
    
    Streams all events from the event bus to connected UI clients:
    - Market data (tickers, funding rates)
    - News articles
    - Agent outputs
    - Consensus decisions
    - Simulation blocks
    """
    await manager.connect(websocket)
    
    # Subscribe to all channels using unique subscriber ID
    import uuid
    from core.streaming_bus import subscribe_by_id, _subscriber_queues, unsubscribe_by_id, EventChannel
    subscriber_id = f"ws-live-{uuid.uuid4().hex[:8]}"
    all_channels = list(EventChannel)
    await subscribe_by_id(subscriber_id, all_channels)
    event_queue = _subscriber_queues.get(subscriber_id)
    
    try:
        # Send initial connection message
        await websocket.send_json({
            "type": "connected",
            "message": "Live stream connected",
            "channels": "all"
        })
        
        # Stream events to client
        while True:
            # Get event from bus
            event = await event_queue.get()
            
            # Convert to JSON-serializable format
            message = {
                "channel": event.channel.value,
                "event_type": event.event_type,
                "data": event.data,
                "timestamp": event.timestamp,
                "source": event.source
            }
            
            # Send to client
            await websocket.send_json(message)
            
    except WebSocketDisconnect:
        logger.info("Client disconnected normally")
    except Exception as exc:
        logger.error(f"WebSocket error: {exc}")
    finally:
        manager.disconnect(websocket)
        await streaming_bus.unsubscribe(event_queue)


@router.websocket("/ws/market")
async def websocket_market_stream(websocket: WebSocket):
    """
    Market data only WebSocket endpoint.
    
    Streams only market data events (tickers, funding rates).
    """
    await manager.connect(websocket)
    
    # Subscribe to market data channel only
    event_queue = await streaming_bus.subscribe(channels=[EventChannel.MARKET_DATA])
    
    try:
        await websocket.send_json({
            "type": "connected",
            "message": "Market stream connected",
            "channels": ["market_data"]
        })
        
        while True:
            event = await event_queue.get()
            
            message = {
                "channel": event.channel.value,
                "event_type": event.event_type,
                "data": event.data,
                "timestamp": event.timestamp,
                "source": event.source
            }
            
            await websocket.send_json(message)
            
    except WebSocketDisconnect:
        logger.info("Market stream client disconnected")
    except Exception as exc:
        logger.error(f"Market stream error: {exc}")
    finally:
        manager.disconnect(websocket)
        await streaming_bus.unsubscribe(event_queue)


@router.websocket("/ws/news")
async def websocket_news_stream(websocket: WebSocket):
    """
    News only WebSocket endpoint.
    
    Streams only news events.
    """
    await manager.connect(websocket)
    
    # Subscribe to news channel only
    event_queue = await streaming_bus.subscribe(channels=[EventChannel.NEWS])
    
    try:
        await websocket.send_json({
            "type": "connected",
            "message": "News stream connected",
            "channels": ["news"]
        })
        
        while True:
            event = await event_queue.get()
            
            message = {
                "channel": event.channel.value,
                "event_type": event.event_type,
                "data": event.data,
                "timestamp": event.timestamp,
                "source": event.source
            }
            
            await websocket.send_json(message)
            
    except WebSocketDisconnect:
        logger.info("News stream client disconnected")
    except Exception as exc:
        logger.error(f"News stream error: {exc}")
    finally:
        manager.disconnect(websocket)
        await streaming_bus.unsubscribe(event_queue)


@router.websocket("/ws/agents")
async def websocket_agent_stream(websocket: WebSocket):
    """
    Agent outputs only WebSocket endpoint.
    
    Streams only agent output events.
    """
    await manager.connect(websocket)
    
    # Subscribe to agent output channel only
    event_queue = await streaming_bus.subscribe(channels=[EventChannel.AGENT_OUTPUT])
    
    try:
        await websocket.send_json({
            "type": "connected",
            "message": "Agent stream connected",
            "channels": ["agent_output"]
        })
        
        while True:
            event = await event_queue.get()
            
            message = {
                "channel": event.channel.value,
                "event_type": event.event_type,
                "data": event.data,
                "timestamp": event.timestamp,
                "source": event.source
            }
            
            await websocket.send_json(message)
            
    except WebSocketDisconnect:
        logger.info("Agent stream client disconnected")
    except Exception as exc:
        logger.error(f"Agent stream error: {exc}")
    finally:
        manager.disconnect(websocket)
        await streaming_bus.unsubscribe(event_queue)
