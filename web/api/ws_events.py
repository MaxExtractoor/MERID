"""
WebSocket Event Broadcasting

Minimal broadcast handler for swarm events.
Integrates with existing WebSocket infrastructure.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Set
from fastapi import WebSocket
from utils.logger import get_logger

logger = get_logger("web.api.ws_events")

# Global set of active WebSocket connections
_active_connections: Set[WebSocket] = set()


async def register_connection(websocket: WebSocket) -> None:
    """Register a new WebSocket connection."""
    _active_connections.add(websocket)
    logger.info(f"WebSocket registered (total: {len(_active_connections)})")


async def unregister_connection(websocket: WebSocket) -> None:
    """Unregister a WebSocket connection."""
    _active_connections.discard(websocket)
    logger.info(f"WebSocket unregistered (total: {len(_active_connections)})")


async def broadcast_event(event_type: str, payload: Dict[str, Any]) -> None:
    """
    Broadcast event to all connected WebSocket clients.
    
    Args:
        event_type: Event type name (e.g., 'strategy_opinion', 'consensus_decision')
        payload: Event payload dictionary
    """
    if not _active_connections:
        return
    
    message = {
        "type": event_type,
        "data": payload,
    }
    
    # Send to all connections
    dead_connections = set()
    for connection in _active_connections:
        try:
            await connection.send_json(message)
        except Exception as e:
            logger.warning(f"Failed to send to WebSocket: {e}")
            dead_connections.add(connection)
    
    # Clean up dead connections
    for connection in dead_connections:
        _active_connections.discard(connection)


async def broadcast_text(message: str) -> None:
    """Broadcast text message to all connected clients."""
    if not _active_connections:
        return
    
    dead_connections = set()
    for connection in _active_connections:
        try:
            await connection.send_text(message)
        except Exception as e:
            logger.warning(f"Failed to send text to WebSocket: {e}")
            dead_connections.add(connection)
    
    for connection in dead_connections:
        _active_connections.discard(connection)


def get_connection_count() -> int:
    """Get number of active WebSocket connections."""
    return len(_active_connections)
