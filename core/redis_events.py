"""Redis pub/sub integration for MERID real-time updates."""

import asyncio
import json
from typing import Callable, Optional, Dict, Any
import aioredis
import structlog

logger = structlog.get_logger(__name__)


class RedisEventBus:
    """Event bus using Redis pub/sub for agent/UI communication."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self.redis: Optional[aioredis.Redis] = None
        self.pubsub: Optional[aioredis.client.PubSub] = None
        self.subscribers: Dict[str, list] = {}
        self.logger = logger.bind(component="RedisEventBus")
    
    async def connect(self):
        """Establish Redis connection."""
        self.redis = aioredis.from_url(self.redis_url, decode_responses=True)
        self.pubsub = self.redis.pubsub()
        self.logger.info("redis_connected", url=self.redis_url)
    
    async def disconnect(self):
        """Close Redis connection."""
        if self.pubsub:
            await self.pubsub.close()
        if self.redis:
            await self.redis.close()
        self.logger.info("redis_disconnected")
    
    async def publish(self, channel: str, message: Dict[str, Any]):
        """Publish message to a channel."""
        if not self.redis:
            raise RuntimeError("Redis not connected")
        
        await self.redis.publish(channel, json.dumps(message))
        self.logger.debug("message_published", channel=channel, message_type=message.get("type"))
    
    async def subscribe(self, channel: str, handler: Callable):
        """Subscribe to a channel with a message handler."""
        if not self.pubsub:
            raise RuntimeError("Redis not connected")
        
        await self.pubsub.subscribe(channel)
        
        if channel not in self.subscribers:
            self.subscribers[channel] = []
        self.subscribers[channel].append(handler)
        
        self.logger.info("channel_subscribed", channel=channel)
    
    async def listen(self):
        """Listen for messages and dispatch to handlers."""
        if not self.pubsub:
            raise RuntimeError("Redis not connected")
        
        async for message in self.pubsub.listen():
            if message["type"] == "message":
                channel = message["channel"]
                data = json.loads(message["data"])
                
                # Dispatch to handlers
                for handler in self.subscribers.get(channel, []):
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler(data)
                        else:
                            handler(data)
                    except Exception as e:
                        self.logger.error("handler_error", channel=channel, error=str(e))


class OrderEventPublisher:
    """Publisher for order-related events."""
    
    def __init__(self, event_bus: RedisEventBus):
        self.event_bus = event_bus
        self.logger = logger.bind(component="OrderEventPublisher")
    
    async def publish_order_created(self, order_id: str, symbol: str, side: str, quantity: float):
        """Publish order created event."""
        await self.event_bus.publish("orders", {
            "type": "order_created",
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "timestamp": asyncio.get_event_loop().time()
        })
    
    async def publish_order_filled(self, order_id: str, filled_price: float, filled_qty: float):
        """Publish order filled event."""
        await self.event_bus.publish("orders", {
            "type": "order_filled",
            "order_id": order_id,
            "filled_price": filled_price,
            "filled_quantity": filled_qty,
            "timestamp": asyncio.get_event_loop().time()
        })
    
    async def publish_order_failed(self, order_id: str, error: str):
        """Publish order failed event."""
        await self.event_bus.publish("orders", {
            "type": "order_failed",
            "order_id": order_id,
            "error": error,
            "timestamp": asyncio.get_event_loop().time()
        })


class SwarmEventPublisher:
    """Publisher for swarm agent events."""
    
    def __init__(self, event_bus: RedisEventBus):
        self.event_bus = event_bus
        self.logger = logger.bind(component="SwarmEventPublisher")
    
    async def publish_agent_decision(self, agent_name: str, decision: Dict[str, Any]):
        """Publish agent decision event."""
        await self.event_bus.publish("swarm", {
            "type": "agent_decision",
            "agent": agent_name,
            "decision": decision,
            "timestamp": asyncio.get_event_loop().time()
        })
    
    async def publish_trade_signal(self, signal: Dict[str, Any], confidence: float):
        """Publish trade signal from swarm."""
        await self.event_bus.publish("swarm", {
            "type": "trade_signal",
            "signal": signal,
            "confidence": confidence,
            "timestamp": asyncio.get_event_loop().time()
        })


# UI Update Channel
class UIUpdatePublisher:
    """Publisher for UI real-time updates."""
    
    def __init__(self, event_bus: RedisEventBus):
        self.event_bus = event_bus
        self.logger = logger.bind(component="UIUpdatePublisher")
    
    async def update_portfolio(self, data: Dict[str, Any]):
        """Send portfolio update to UI."""
        await self.event_bus.publish("ui:portfolio", {
            "type": "portfolio_update",
            "data": data
        })
    
    async def update_positions(self, positions: list):
        """Send positions update to UI."""
        await self.event_bus.publish("ui:positions", {
            "type": "positions_update",
            "positions": positions
        })
    
    async def update_risk_metrics(self, metrics: Dict[str, Any]):
        """Send risk metrics update to UI."""
        await self.event_bus.publish("ui:risk", {
            "type": "risk_update",
            "metrics": metrics
        })
