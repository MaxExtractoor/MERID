"""
WebSocket Factory for MERID

Reduces duplication across WebSocket endpoints by providing a reusable
handler builder for topic-filtered event streams.
"""

from __future__ import annotations

import time
from typing import Optional, Callable, Dict, Tuple
from collections import defaultdict
from fastapi import WebSocket, Query, WebSocketDisconnect

from observability.event_stream import get_event_stream
from merid.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

# JWT imports (optional)
try:
    from fastapi_jwt_auth import AuthJWT
except ImportError:
    AuthJWT = None

# Rate limiting state
_connection_tracker: Dict[str, Tuple[int, float]] = defaultdict(lambda: (0, 0.0))
MAX_WS_CONNECTIONS_PER_IP = 10  # Max concurrent connections per IP
WS_CONNECTION_WINDOW = 60  # Time window in seconds

# Global connection cap
_total_ws_connections: int = 0
MAX_TOTAL_WS_CONNECTIONS: int = 100  # Global max across all IPs


def _check_global_connection_cap() -> bool:
    """Check if global WebSocket connection cap has been reached."""
    global _total_ws_connections
    if _total_ws_connections >= MAX_TOTAL_WS_CONNECTIONS:
        logger.warning(f"Global WebSocket cap reached: {_total_ws_connections}/{MAX_TOTAL_WS_CONNECTIONS}")
        return False
    _total_ws_connections += 1
    return True


def _release_global_connection() -> None:
    """Release a global connection slot."""
    global _total_ws_connections
    if _total_ws_connections > 0:
        _total_ws_connections -= 1


def _check_rate_limit(client_ip: str) -> bool:
    """
    Check if the client IP has exceeded the WebSocket connection rate limit.
    
    Returns True if connection should be allowed, False if rate limited.
    """
    count, window_start = _connection_tracker[client_ip]
    current_time = time.time()
    
    # Reset window if expired
    if current_time - window_start > WS_CONNECTION_WINDOW:
        _connection_tracker[client_ip] = (1, current_time)
        return True
    
    # Check limit
    if count >= MAX_WS_CONNECTIONS_PER_IP:
        logger.warning(f"WebSocket rate limit exceeded for IP: {client_ip}")
        return False
    
    # Increment counter
    _connection_tracker[client_ip] = (count + 1, window_start)
    return True


def _release_connection(client_ip: str) -> None:
    """Release a connection slot when WebSocket closes."""
    count, window_start = _connection_tracker[client_ip]
    if count > 0:
        _connection_tracker[client_ip] = (count - 1, window_start)


async def handle_topic_websocket(
    websocket: WebSocket,
    topic_prefix: str,
    token: Optional[str] = None,
    welcome_message: str = "Connected to event stream",
) -> None:
    """
    Generic WebSocket handler for topic-filtered event streams.
    
    Args:
        websocket: The WebSocket connection
        topic_prefix: Event type prefix to filter (e.g., "arbitrage.", "system.")
        token: Optional JWT token for authentication
        welcome_message: Message sent on successful connection
    """
    await websocket.accept()
    
    # Get client IP for rate limiting
    client_ip = websocket.client.host if websocket.client else "unknown"
    
    # Check rate limit
    if not _check_rate_limit(client_ip):
        await websocket.send_json({
            "type": "error",
            "detail": "Rate limit exceeded - too many connections"
        })
        await websocket.close(code=1008, reason="Rate limit exceeded")
        return
    
    # Check global connection cap
    if not _check_global_connection_cap():
        await websocket.send_json({
            "type": "error",
            "detail": "Server at capacity - try again later"
        })
        await websocket.close(code=1008, reason="Server at capacity")
        return
    
    try:
        # Check dev mode (safely via settings)
        dev_mode = settings.allow_websocket_dev_mode
        if dev_mode:
            logger.warning(f"WebSocket dev mode active for topic '{topic_prefix}' - anonymous connections allowed")
        
        if not dev_mode and not token:
            await websocket.close(code=1008, reason="Token required")
            return
        
        # Validate JWT token if available and not in dev mode
        if not dev_mode and AuthJWT is not None:
            Authorize = AuthJWT()
            Authorize.jwt_required("websocket", token=token)
            user = Authorize.get_jwt_subject()
        else:
            # Fallback: use token as simple user identifier or anonymous in dev mode
            user = token[:8] + "..." if token and len(token) > 8 else "anonymous"
            if dev_mode:
                user = "dev_user"
            else:
                logger.warning("JWT not available, using fallback authentication")
        
        # Send welcome message
        await websocket.send_json({
            "type": "connected",
            "user": user,
            "message": welcome_message,
        })
        
        # Subscribe to event stream
        event_stream = get_event_stream()
        queue = await event_stream.subscribe()
        
        try:
            while True:
                record = await queue.get()
                if not record.event_type.startswith(topic_prefix):
                    continue
                payload = {
                    "type": record.event_type,
                    "payload": record.payload,
                    "ts": record.timestamp,
                }
                await websocket.send_json(payload)
        finally:
            await event_stream.unsubscribe(queue)
            
    except Exception as e:
        logger.error(f"WebSocket error for topic '{topic_prefix}': {e}")
        await websocket.send_json({
            "type": "error",
            "detail": "Connection failed"
        })
        await websocket.close(code=1008)
    except WebSocketDisconnect:
        pass
    finally:
        _release_connection(client_ip)
        _release_global_connection()


def create_websocket_endpoint(
    topic_prefix: str,
    welcome_message: str,
) -> Callable:
    """
    Factory function that creates a WebSocket endpoint handler.
    
    Args:
        topic_prefix: Event type prefix to filter
        welcome_message: Connection success message
        
    Returns:
        Async function suitable for @router.websocket decorator
    """
    async def endpoint(websocket: WebSocket, token: str = Query(None)):
        await handle_topic_websocket(
            websocket=websocket,
            topic_prefix=topic_prefix,
            token=token,
            welcome_message=welcome_message,
        )
    
    return endpoint
