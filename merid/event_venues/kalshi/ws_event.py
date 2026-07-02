"""
Kalshi WebSocket Event Parser

Provides centralized parsing of Kalshi WebSocket messages into strongly-typed WsEvent objects.
This eliminates scattered parsing logic and ensures all message types are handled consistently.

Reference: https://docs.kalshi.com/websockets/orderbook-updates
"""
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional
from enum import Enum
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.ws_event")

# Dev mode flag for stricter assertions
_DEV_MODE = os.getenv("MERID_DEV_MODE", "false").lower() in ("true", "1", "yes")


class WsEventKind(str, Enum):
    """Kalshi WebSocket message kinds."""
    ORDERBOOK_SNAPSHOT = "orderbook_snapshot"
    ORDERBOOK_DELTA = "orderbook_delta"
    TICKER_SNAPSHOT = "ticker_snapshot"
    FILL = "fill"
    ORDER_GROUP_UPDATE = "order_group_update"
    UNKNOWN = "unknown"


@dataclass
class WsEvent:
    """Strongly-typed Kalshi WebSocket event.
    
    All WS messages are parsed through this single factory method,
    ensuring consistent handling and provenance tracking.
    """
    kind: WsEventKind
    ticker: str
    raw: Dict[str, Any]
    parsed: Optional[Dict[str, Any]] = None
    ts_received: float = 0.0
    
    @classmethod
    def from_kalshi_message(cls, raw_msg: Dict[str, Any]) -> "WsEvent":
        """Parse Kalshi WS message into WsEvent.
        
        Handles both ticker and market_ticker field names, and nested msg structures.
        Normalizes to single format for downstream processing.
        
        Args:
            raw_msg: Raw Kalshi WS message dict
            
        Returns:
            WsEvent with kind, ticker, and raw message
            
        Reference:
            - https://docs.kalshi.com/websockets/orderbook-updates
            - https://docs.kalshi.com/getting_started/orderbook_responses
        """
        # Extract nested msg if present (Kalshi sometimes wraps messages)
        nested_msg = raw_msg.get("msg", {})
        if nested_msg and isinstance(nested_msg, dict):
            # Use nested structure for type/channel/ticker extraction
            source_msg = nested_msg
        else:
            source_msg = raw_msg
        
        # Extract ticker from multiple possible locations
        # Kalshi messages may have ticker at top level or nested in msg object
        ticker = (
            source_msg.get("ticker")
            or source_msg.get("market_ticker")
            or raw_msg.get("ticker")
            or raw_msg.get("market_ticker")
            or "unknown"
        )
        
        # Determine message kind from both type and channel fields
        # Some messages use type, others use channel
        msg_type = source_msg.get("type") or source_msg.get("channel") or raw_msg.get("type") or raw_msg.get("channel") or ""
        channel = source_msg.get("channel") or raw_msg.get("channel") or ""
        
        # Map to WsEventKind based on documented Kalshi message types
        if msg_type == "orderbook_snapshot" or channel == "orderbook_snapshot":
            kind = WsEventKind.ORDERBOOK_SNAPSHOT
        elif msg_type == "orderbook_delta" or channel == "orderbook_delta":
            kind = WsEventKind.ORDERBOOK_DELTA
        elif msg_type == "ticker" or channel == "ticker":
            kind = WsEventKind.TICKER_SNAPSHOT
        elif msg_type == "fill" or channel == "fill":
            kind = WsEventKind.FILL
        elif msg_type in ("order_group_update", "order_group_updates") or channel in ("order_group_update", "order_group_updates"):
            kind = WsEventKind.ORDER_GROUP_UPDATE
        else:
            kind = WsEventKind.UNKNOWN
            # Dev mode: log unknown message types for investigation
            if _DEV_MODE:
                logger.warning(
                    "[WS-EVENT-UNKNOWN] Unknown Kalshi WS message type: msg_type=%s, channel=%s, ticker=%s, raw_keys=%s",
                    msg_type,
                    channel,
                    ticker,
                    list(raw_msg.keys()),
                )
        
        return cls(
            kind=kind,
            ticker=ticker,
            raw=raw_msg,
            ts_received=time.monotonic()
        )
