"""
Unified Trade Events WebSocket - The "Trade Floor" pipe.

Emits all trading activity (intents, orders, fills, PnL, agent decisions)
from both human and agent traders into a single stream for the UI.

This is the central nervous system that makes the "wall of agents trading" view work.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from trading.paper_trading import get_paper_engine
from trading.mode_controller import get_trading_mode_controller
from core.agent_orchestrator import get_agent_orchestrator
from utils.logger import get_logger

router = APIRouter(prefix="/ws", tags=["ws-trade-events"])
logger = get_logger("web.api.ws_trade_events")

HEARTBEAT_INTERVAL = 5
MAX_EVENTS_BUFFER = 100


class TraderType(str, Enum):
    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"


class EventType(str, Enum):
    # Agent events
    AGENT_OPINION = "agent_opinion"
    AGENT_DECISION = "agent_decision"
    CONSENSUS = "consensus"
    
    # Trading events
    INTENT = "intent"
    ORDER_NEW = "order_new"
    ORDER_FILLED = "order_filled"
    ORDER_PARTIAL = "order_partial"
    ORDER_CANCELLED = "order_cancelled"
    ORDER_REJECTED = "order_rejected"
    
    # Position events
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    POSITION_UPDATED = "position_updated"
    
    # PnL events
    PNL_UPDATE = "pnl_update"
    
    # System events
    MODE_CHANGE = "mode_change"
    RISK_ALERT = "risk_alert"
    HEARTBEAT = "heartbeat"


@dataclass
class TradeEvent:
    """Unified trade event schema for all trading activity."""
    event_type: str
    trader_type: str
    trader_id: str
    timestamp: float
    
    # Optional fields based on event type
    venue: Optional[str] = None
    symbol: Optional[str] = None
    side: Optional[str] = None
    qty: Optional[float] = None
    price: Optional[float] = None
    status: Optional[str] = None
    order_id: Optional[str] = None
    
    # Agent-specific fields
    confidence: Optional[float] = None
    reasoning: Optional[str] = None
    signal: Optional[str] = None
    
    # PnL fields
    realized_pnl: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    
    # Mode fields
    mode: Optional[str] = None
    is_simulated: bool = False
    
    # Extra data
    extra: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict, excluding None values."""
        result = {}
        for key, value in asdict(self).items():
            if value is not None:
                result[key] = value
        return result


class TradeEventBroadcaster:
    """
    Singleton broadcaster that collects trade events from all sources
    and distributes them to connected WebSocket clients.
    """
    
    _instance: Optional["TradeEventBroadcaster"] = None
    
    def __init__(self):
        self._subscribers: Set[asyncio.Queue] = set()
        self._recent_events: List[TradeEvent] = []
        self._lock = asyncio.Lock()
    
    @classmethod
    def get_instance(cls) -> "TradeEventBroadcaster":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    async def publish(self, event: TradeEvent) -> None:
        """Publish an event to all subscribers."""
        async with self._lock:
            # Store in recent events buffer
            self._recent_events.append(event)
            if len(self._recent_events) > MAX_EVENTS_BUFFER:
                self._recent_events = self._recent_events[-MAX_EVENTS_BUFFER:]
            
            # Broadcast to all subscribers
            dead_queues = []
            for queue in self._subscribers:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning("Dropping event for slow subscriber: %s", event.event_type)
                except Exception:
                    dead_queues.append(queue)
            
            # Clean up dead queues
            for queue in dead_queues:
                self._subscribers.discard(queue)
    
    def subscribe(self) -> asyncio.Queue:
        """Subscribe to events, returns a queue that will receive events."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        return queue
    
    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Unsubscribe from events."""
        self._subscribers.discard(queue)
    
    def get_recent_events(self, limit: int = 50) -> List[TradeEvent]:
        """Get recent events for new subscribers."""
        return self._recent_events[-limit:]


def get_trade_broadcaster() -> TradeEventBroadcaster:
    """Get the singleton trade event broadcaster."""
    return TradeEventBroadcaster.get_instance()


# ============================================
# EVENT PUBLISHERS - Wire these to your systems
# ============================================

async def publish_agent_decision(
    agent_id: str,
    signal: str,
    confidence: float,
    reasoning: str,
    symbol: Optional[str] = None,
    extra: Optional[Dict] = None,
) -> None:
    """Publish an agent decision event."""
    event = TradeEvent(
        event_type=EventType.AGENT_DECISION.value,
        trader_type=TraderType.AGENT.value,
        trader_id=agent_id,
        timestamp=time.time(),
        signal=signal,
        confidence=confidence,
        reasoning=reasoning,
        symbol=symbol,
        extra=extra,
    )
    await get_trade_broadcaster().publish(event)


async def publish_order_event(
    trader_type: str,
    trader_id: str,
    event_type: EventType,
    order_id: str,
    venue: str,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    status: str,
    is_simulated: bool = False,
    extra: Optional[Dict] = None,
) -> None:
    """Publish an order event (new, filled, cancelled, etc)."""
    event = TradeEvent(
        event_type=event_type.value,
        trader_type=trader_type,
        trader_id=trader_id,
        timestamp=time.time(),
        venue=venue,
        symbol=symbol,
        side=side,
        qty=qty,
        price=price,
        status=status,
        order_id=order_id,
        is_simulated=is_simulated,
        extra=extra,
    )
    await get_trade_broadcaster().publish(event)


async def publish_pnl_update(
    trader_type: str,
    trader_id: str,
    realized_pnl: float,
    unrealized_pnl: float,
    extra: Optional[Dict] = None,
) -> None:
    """Publish a PnL update event."""
    event = TradeEvent(
        event_type=EventType.PNL_UPDATE.value,
        trader_type=trader_type,
        trader_id=trader_id,
        timestamp=time.time(),
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        extra=extra,
    )
    await get_trade_broadcaster().publish(event)


async def publish_risk_alert(
    title: str,
    severity: str = "warning",
    category: str = "general",
    detail: Optional[str] = None,
    extra: Optional[Dict] = None,
) -> None:
    """Publish a risk alert event to all WS subscribers."""
    event = TradeEvent(
        event_type=EventType.RISK_ALERT.value,
        trader_type=TraderType.SYSTEM.value,
        trader_id="risk-monitor",
        timestamp=time.time(),
        status=severity,
        signal=category,
        reasoning=title,
        extra={**(extra or {}), "detail": detail or "", "category": category},
    )
    await get_trade_broadcaster().publish(event)


async def publish_mode_change(mode: str, is_simulated: bool) -> None:
    """Publish a mode change event."""
    event = TradeEvent(
        event_type=EventType.MODE_CHANGE.value,
        trader_type=TraderType.SYSTEM.value,
        trader_id="system",
        timestamp=time.time(),
        mode=mode,
        is_simulated=is_simulated,
    )
    await get_trade_broadcaster().publish(event)


# ============================================
# WEBSOCKET ENDPOINT
# ============================================

@router.get("/replay")
async def replay_events(limit: int = 50, since: float = 0.0):
    """T-062: Replay recent trade events for clients that missed them.
    
    Query params:
        limit: Max events to return (default 50, max 100)
        since: Only return events after this epoch timestamp
    """
    limit = min(limit, MAX_EVENTS_BUFFER)
    broadcaster = get_trade_broadcaster()
    events = broadcaster.get_recent_events(limit)
    if since > 0:
        events = [e for e in events if e.timestamp > since]
    return {
        "events": [e.to_dict() for e in events],
        "count": len(events),
        "server_time": time.time(),
    }


@router.websocket("/trades")
async def trade_events_stream(websocket: WebSocket) -> None:
    """
    Unified trade events WebSocket.
    
    Streams all trading activity (agents + human) in real-time:
    - Agent decisions and opinions
    - Orders (new, filled, cancelled)
    - Position changes
    - PnL updates
    - Mode changes
    
    Connect to: ws://localhost:8011/ws/trades
    """
    await websocket.accept()
    logger.info("[WS] Trade events client connected")
    
    queue = None
    try:
        broadcaster = get_trade_broadcaster()
        queue = broadcaster.subscribe()
    except Exception as exc:
        logger.error("[WS] Failed to initialize trade broadcaster: %s", exc)
        await websocket.send_json({
            "type": "feature_unavailable",
            "reason": "Trade event system not available",
            "timestamp": time.time(),
        })
        await websocket.close(1000)
        return
    
    try:
        # Send recent events to new subscriber
        for event in broadcaster.get_recent_events(20):
            await websocket.send_json(event.to_dict())
        
        # Send current mode
        try:
            controller = get_trading_mode_controller()
            await websocket.send_json({
                "event_type": "mode_status",
                "trader_type": "system",
                "trader_id": "system",
                "timestamp": time.time(),
                "mode": controller.mode_name,
                "is_simulated": not controller.is_live,
            })
        except Exception as mode_exc:
            logger.warning("[WS] Could not get trading mode: %s", mode_exc)
            await websocket.send_json({
                "event_type": "mode_status",
                "trader_type": "system",
                "trader_id": "system",
                "timestamp": time.time(),
                "mode": "UNKNOWN",
                "is_simulated": True,
            })
        
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL)
                await websocket.send_json(event.to_dict())
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_json({
                    "event_type": "heartbeat",
                    "trader_type": "system",
                    "trader_id": "system",
                    "timestamp": time.time(),
                })
    except WebSocketDisconnect:
        logger.info("[WS] Trade events client disconnected")
    except Exception as exc:
        logger.error("[WS] Trade events error: %s", exc)
    finally:
        if queue:
            broadcaster.unsubscribe(queue)


@router.websocket("/orders")
async def orders_stream(websocket: WebSocket) -> None:
    """
    Orders-only WebSocket stream.
    Filters trade events to only order-related events.
    """
    await websocket.accept()
    logger.info("[WS] Orders stream client connected")
    
    broadcaster = get_trade_broadcaster()
    queue = broadcaster.subscribe()
    
    order_events = {
        EventType.ORDER_NEW.value,
        EventType.ORDER_FILLED.value,
        EventType.ORDER_PARTIAL.value,
        EventType.ORDER_CANCELLED.value,
        EventType.ORDER_REJECTED.value,
    }
    
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL)
                if event.event_type in order_events:
                    await websocket.send_json(event.to_dict())
            except asyncio.TimeoutError:
                await websocket.send_json({
                    "event_type": "heartbeat",
                    "timestamp": time.time(),
                })
    except WebSocketDisconnect:
        logger.info("[WS] Orders stream client disconnected")
    except Exception as exc:
        logger.error("[WS] Orders stream error: %s", exc)
    finally:
        broadcaster.unsubscribe(queue)


@router.websocket("/risk")
async def risk_stream(websocket: WebSocket) -> None:
    """
    Risk-focused WebSocket stream.
    Emits PnL updates, risk alerts, and position changes.
    """
    await websocket.accept()
    logger.info("[WS] Risk stream client connected")
    
    queue = None
    try:
        broadcaster = get_trade_broadcaster()
        queue = broadcaster.subscribe()
    except Exception as exc:
        logger.error("[WS] Failed to initialize risk broadcaster: %s", exc)
        await websocket.send_json({
            "type": "feature_unavailable",
            "reason": "Risk monitoring system not available",
            "timestamp": time.time(),
        })
        await websocket.close(1000)
        return
    
    risk_events = {
        EventType.PNL_UPDATE.value,
        EventType.RISK_ALERT.value,
        EventType.POSITION_OPENED.value,
        EventType.POSITION_CLOSED.value,
        EventType.POSITION_UPDATED.value,
    }
    
    # Also send periodic risk summary
    try:
        paper_engine = get_paper_engine()
    except Exception as exc:
        logger.error("[WS] Failed to initialize paper engine: %s", exc)
        paper_engine = None
    
    try:
        last_summary_time = 0
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=2)
                if event.event_type in risk_events:
                    await websocket.send_json(event.to_dict())
            except asyncio.TimeoutError:
                # Send risk summary every 5 seconds
                now = time.time()
                if now - last_summary_time >= 5:
                    if paper_engine:
                        try:
                            summary = paper_engine.get_portfolio_summary()
                            await websocket.send_json({
                                "event_type": "risk_summary",
                                "timestamp": now,
                                "total_equity": summary.get("total_equity", 0),
                                "total_pnl": summary.get("total_pnl", 0),
                                "unrealized_pnl": summary.get("unrealized_pnl", 0),
                                "position_count": summary.get("position_count", 0),
                                "exposure": summary.get("total_exposure", 0),
                            })
                        except Exception as exc:
                            logger.debug("Risk summary skipped: %s", exc)
                    else:
                        # Send placeholder summary
                        await websocket.send_json({
                            "event_type": "risk_summary",
                            "timestamp": now,
                            "total_equity": 0,
                            "total_pnl": 0,
                            "unrealized_pnl": 0,
                            "position_count": 0,
                            "exposure": 0,
                        })
                    last_summary_time = now
    except WebSocketDisconnect:
        logger.info("[WS] Risk stream client disconnected")
    except Exception as exc:
        logger.error("[WS] Risk stream error: %s", exc)
    finally:
        if queue:
            broadcaster.unsubscribe(queue)
