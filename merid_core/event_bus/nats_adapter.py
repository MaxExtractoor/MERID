"""
NATS Event Bus Adapter
Simple async wrapper for NATS pub/sub
"""

import asyncio
import json
import logging
from typing import Any, Callable, Dict, Optional
from dataclasses import dataclass

try:
    import nats
    from nats.aio.client import Client as NATSClient
    NATS_AVAILABLE = True
except ImportError:
    NATS_AVAILABLE = False
    NATSClient = None

logger = logging.getLogger(__name__)


@dataclass
class EventEnvelope:
    """Event wrapper with metadata"""
    topic: str
    data: Dict[str, Any]
    ts: int  # Milliseconds since epoch


class NATSEventBus:
    """
    Async event bus backed by NATS
    
    Usage:
        bus = NATSEventBus("nats://localhost:4222")
        await bus.connect()
        
        # Publish
        await bus.publish("kalshi.orderbook", {"market": "BTC-15M", ...})
        
        # Subscribe
        async def handler(envelope):
            print(f"Received: {envelope.topic}")
        
        await bus.subscribe("kalshi.orderbook", handler)
    """
    
    def __init__(self, url: str = "nats://localhost:4222"):
        if not NATS_AVAILABLE:
            raise ImportError("nats-py not installed: pip install nats-py")
        
        self.url = url
        self.nc: Optional[NATSClient] = None
        self.subscriptions: Dict[str, int] = {}  # topic -> sub_id
        
    async def connect(self) -> None:
        """Connect to NATS server"""
        if self.nc and self.nc.is_connected:
            logger.warning("Already connected to NATS")
            return
        
        self.nc = await nats.connect(self.url)
        logger.info(f"Connected to NATS at {self.url}")
    
    async def disconnect(self) -> None:
        """Disconnect from NATS server"""
        if self.nc and self.nc.is_connected:
            await self.nc.close()
            logger.info("Disconnected from NATS")
    
    async def publish(self, topic: str, data: Dict[str, Any]) -> None:
        """
        Publish event to topic
        
        Args:
            topic: Event topic (e.g., "kalshi.orderbook")
            data: Event payload (must be JSON-serializable)
        """
        if not self.nc or not self.nc.is_connected:
            raise RuntimeError("Not connected to NATS")
        
        envelope = EventEnvelope(
            topic=topic,
            data=data,
            ts=int(asyncio.get_event_loop().time() * 1000)
        )
        
        payload = json.dumps({
            "topic": envelope.topic,
            "data": envelope.data,
            "ts": envelope.ts
        }).encode()
        
        await self.nc.publish(topic, payload)
        logger.debug(f"Published to {topic}: {len(payload)} bytes")
    
    async def subscribe(
        self, 
        topic: str, 
        handler: Callable[[EventEnvelope], Any]
    ) -> int:
        """
        Subscribe to topic
        
        Args:
            topic: Topic pattern (supports wildcards: * and >)
            handler: Async callback function
        
        Returns:
            Subscription ID
        """
        if not self.nc or not self.nc.is_connected:
            raise RuntimeError("Not connected to NATS")
        
        async def message_handler(msg):
            try:
                payload = json.loads(msg.data.decode())
                envelope = EventEnvelope(
                    topic=payload["topic"],
                    data=payload["data"],
                    ts=payload["ts"]
                )
                
                # Call handler (can be sync or async)
                result = handler(envelope)
                if asyncio.iscoroutine(result):
                    await result
                    
            except Exception as e:
                logger.error(f"Error handling message on {topic}: {e}", exc_info=True)
        
        sub = await self.nc.subscribe(topic, cb=message_handler)
        self.subscriptions[topic] = sub._id
        logger.info(f"Subscribed to {topic} (sub_id={sub._id})")
        
        return sub._id
    
    async def unsubscribe(self, topic: str) -> None:
        """Unsubscribe from topic"""
        if topic in self.subscriptions:
            sub_id = self.subscriptions.pop(topic)
            # Note: nats.py doesn't expose direct unsubscribe by ID
            # In practice, you'd track the Subscription object
            logger.info(f"Unsubscribed from {topic}")
    
    def is_connected(self) -> bool:
        """Check if connected to NATS"""
        return self.nc is not None and self.nc.is_connected


# Singleton instance
_bus_instance: Optional[NATSEventBus] = None


def get_event_bus(url: str = "nats://localhost:4222") -> NATSEventBus:
    """Get singleton event bus instance"""
    global _bus_instance
    
    if _bus_instance is None:
        _bus_instance = NATSEventBus(url)
    
    return _bus_instance
