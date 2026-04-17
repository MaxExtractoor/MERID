"""
Live Stream WebSocket Endpoint - Production streaming to UI.

Connects UI clients to the event bus for real-time updates.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Dict, List, Optional, Set, Union

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from core.streaming_bus import streaming_bus, EventChannel
from utils.logger import get_logger

logger = get_logger("web.api.live_stream")

router = APIRouter()


# ── Channel freshness tracking ────────────────────────────────────────
# Records the last time an event was sent on each WS channel.
# Used by the WsChannelStaleAlert to detect connected-but-frozen feeds.

_channel_last_event_ts: Dict[str, float] = {}


def record_channel_event(channel: str) -> None:
    """Record that an event was sent on this channel."""
    _channel_last_event_ts[channel] = time.time()


def get_channel_freshness() -> Dict[str, Dict[str, float]]:
    """Return per-channel freshness data for observability."""
    now = time.time()
    result: Dict[str, Dict[str, float]] = {}
    for channel, ts in _channel_last_event_ts.items():
        result[channel] = {
            "last_event_ts": ts,
            "age_seconds": round(now - ts, 1),
        }
    return result


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


# ── Shared WS endpoint helper ─────────────────────────────────────────

async def _run_ws_endpoint(
    websocket: WebSocket,
    event_queue: asyncio.Queue,
    stream_name: str,
    freshness_label: Optional[str] = None,
) -> None:
    """Shared sender/receiver loop for all WS endpoints.

    Args:
        websocket: The accepted WebSocket connection.
        event_queue: asyncio.Queue from the streaming bus subscription.
        stream_name: Human-readable name for log messages.
        freshness_label: If set, a fixed channel label for record_channel_event.
                         If None, uses event.channel.value (for multi-channel streams).
    """

    async def _sender():
        while True:
            event = await event_queue.get()
            label = freshness_label or event.channel.value
            record_channel_event(label)
            await websocket.send_json({
                "channel": event.channel.value,
                "event_type": event.event_type,
                "data": event.data,
                "timestamp": event.timestamp,
                "source": event.source,
            })

    async def _receiver():
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                if msg.get("event") == "ping":
                    await websocket.send_json({"event": "pong", "ts": msg.get("ts")})
            except (json.JSONDecodeError, TypeError):
                logger.debug("silent catch in live_stream:122")

    sender_task = asyncio.create_task(_sender())
    receiver_task = asyncio.create_task(_receiver())
    try:
        done, pending = await asyncio.wait(
            {sender_task, receiver_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            if task.exception():
                raise task.exception()
    except WebSocketDisconnect:
        logger.info(f"{stream_name} client disconnected normally")
    except Exception as exc:
        logger.error(f"{stream_name} error: {exc}")
    finally:
        manager.disconnect(websocket)
        await streaming_bus.unsubscribe(event_queue)


# ── Endpoints ──────────────────────────────────────────────────────────

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
    
    import uuid
    from core.streaming_bus import subscribe_by_id, _subscriber_queues
    subscriber_id = f"ws-live-{uuid.uuid4().hex[:8]}"
    all_channels = list(EventChannel)
    await subscribe_by_id(subscriber_id, all_channels)
    event_queue = _subscriber_queues.get(subscriber_id)

    await websocket.send_json({
        "type": "connected",
        "message": "Live stream connected",
        "channels": "all"
    })
    await _run_ws_endpoint(websocket, event_queue, "Live stream")


@router.websocket("/ws/market")
async def websocket_market_stream(websocket: WebSocket):
    """Market data only WebSocket endpoint."""
    await manager.connect(websocket)
    event_queue = await streaming_bus.subscribe(channels=[EventChannel.MARKET_DATA])

    await websocket.send_json({
        "type": "connected",
        "message": "Market stream connected",
        "channels": ["market_data"]
    })
    await _run_ws_endpoint(websocket, event_queue, "Market stream", freshness_label="market_data")


@router.websocket("/ws/news")
async def websocket_news_stream(websocket: WebSocket):
    """News only WebSocket endpoint."""
    await manager.connect(websocket)
    event_queue = await streaming_bus.subscribe(channels=[EventChannel.NEWS])

    await websocket.send_json({
        "type": "connected",
        "message": "News stream connected",
        "channels": ["news"]
    })
    await _run_ws_endpoint(websocket, event_queue, "News stream", freshness_label="news")


@router.websocket("/ws/agents")
async def websocket_agent_stream(websocket: WebSocket):
    """Agent outputs only WebSocket endpoint."""
    await manager.connect(websocket)
    event_queue = await streaming_bus.subscribe(channels=[EventChannel.AGENT_OUTPUT])

    await websocket.send_json({
        "type": "connected",
        "message": "Agent stream connected",
        "channels": ["agent_output"]
    })
    await _run_ws_endpoint(websocket, event_queue, "Agent stream", freshness_label="agent_output")
