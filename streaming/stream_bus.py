"""
StreamBus Abstraction for MERID.

Provides a unified interface for event streaming that can be backed by:
- In-memory queues (development/testing)
- Kafka (production)
- Redis Streams (lightweight production)

This abstraction allows MERID to evolve from local event-driven to
distributed Kafka architecture without changing agent code.

Design principles:
- Agents publish/subscribe to topics without knowing the backend
- Schema enforcement via dataclasses
- Idempotent processing with event_id tracking
- Backpressure handling with configurable limits
"""

from __future__ import annotations

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Set, Awaitable
from enum import Enum

from utils.logger import get_logger

logger = get_logger("streaming.stream_bus")


# ============================================
# EVENT SCHEMA
# ============================================

class EventType(str, Enum):
    """Standard event types for the stream bus."""
    # Market data
    PRICE_TICK = "price.tick"
    PRICE_BAR = "price.bar"
    ORDERBOOK_SNAPSHOT = "orderbook.snapshot"
    ORDERBOOK_DELTA = "orderbook.delta"
    
    # Signals
    NEWS_ITEM = "news.item"
    SOCIAL_MENTION = "social.mention"
    ONCHAIN_EVENT = "onchain.event"
    
    # Agent outputs
    AGENT_OPINION = "agent.opinion"
    TRADE_PLAN = "agent.trade_plan"
    RISK_ALERT = "agent.risk_alert"
    
    # Execution
    TRADE_INTENT = "trade.intent"
    TRADE_EXECUTED = "trade.executed"
    TRADE_CANCELLED = "trade.cancelled"
    
    # System
    HEARTBEAT = "system.heartbeat"
    MODE_CHANGE = "system.mode_change"


@dataclass
class StreamEvent:
    """
    Base event structure for all stream messages.
    
    All events have:
    - Unique event_id for idempotency
    - Type classification
    - Timestamp for ordering
    - Source identification
    - Payload data
    """
    event_id: str
    event_type: str
    timestamp: float
    source: str
    
    # Routing
    topic: str
    partition_key: Optional[str] = None  # e.g., symbol for ordered processing
    
    # Payload
    payload: Dict[str, Any] = field(default_factory=dict)
    
    # Metadata
    schema_version: str = "1.0"
    correlation_id: Optional[str] = None  # For tracing related events
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StreamEvent":
        return cls(**data)
    
    @classmethod
    def create(
        cls,
        event_type: str,
        topic: str,
        source: str,
        payload: Dict[str, Any],
        partition_key: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> "StreamEvent":
        """Factory method to create a new event."""
        return cls(
            event_id=f"evt_{uuid.uuid4().hex[:16]}",
            event_type=event_type,
            timestamp=time.time(),
            source=source,
            topic=topic,
            partition_key=partition_key,
            payload=payload,
            correlation_id=correlation_id,
        )


# ============================================
# STREAM BUS INTERFACE
# ============================================

class StreamBus(ABC):
    """
    Abstract base class for stream bus implementations.
    
    Provides publish/subscribe semantics with:
    - Topic-based routing
    - Partition-key ordering (within a topic)
    - Consumer groups
    - Idempotent processing
    """
    
    @abstractmethod
    async def publish(self, event: StreamEvent) -> bool:
        """
        Publish an event to the stream.
        
        Returns True if published successfully.
        """
        pass
    
    @abstractmethod
    async def subscribe(
        self,
        topics: List[str],
        handler: Callable[[StreamEvent], Awaitable[None]],
        consumer_group: Optional[str] = None,
    ) -> str:
        """
        Subscribe to topics with a handler.
        
        Returns subscription ID for later unsubscription.
        """
        pass
    
    @abstractmethod
    async def unsubscribe(self, subscription_id: str) -> bool:
        """Unsubscribe from a previous subscription."""
        pass
    
    @abstractmethod
    async def get_recent_events(
        self,
        topic: str,
        limit: int = 100,
        since_timestamp: Optional[float] = None,
    ) -> List[StreamEvent]:
        """Get recent events from a topic (for catch-up)."""
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the stream bus is connected and healthy."""
        pass


# ============================================
# IN-MEMORY IMPLEMENTATION
# ============================================

class InMemoryStreamBus(StreamBus):
    """
    In-memory stream bus for development and testing.
    
    Features:
    - Async queues per topic
    - Consumer group simulation
    - Event retention with TTL
    - Backpressure via queue limits
    """
    
    _instance: Optional["InMemoryStreamBus"] = None
    
    def __init__(
        self,
        max_events_per_topic: int = 10000,
        event_ttl_seconds: float = 3600.0,
        max_queue_size: int = 1000,
    ):
        self.max_events = max_events_per_topic
        self.event_ttl = event_ttl_seconds
        self.max_queue_size = max_queue_size
        
        # Topic storage
        self._topics: Dict[str, List[StreamEvent]] = defaultdict(list)
        
        # Subscriptions: sub_id -> (topics, handler, consumer_group)
        self._subscriptions: Dict[str, tuple] = {}
        
        # Consumer group tracking for load balancing
        self._consumer_groups: Dict[str, Set[str]] = defaultdict(set)
        
        # Processed event IDs for idempotency (per consumer group)
        self._processed_ids: Dict[str, Set[str]] = defaultdict(set)
        
        # Async queues for subscribers
        self._queues: Dict[str, asyncio.Queue] = {}
        
        # Running flag
        self._running = True
        
        logger.info("InMemoryStreamBus initialized")
    
    @classmethod
    def get_instance(cls) -> "InMemoryStreamBus":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    async def publish(self, event: StreamEvent) -> bool:
        """Publish event and notify subscribers."""
        if not self._running:
            return False
        
        # Store event
        self._topics[event.topic].append(event)
        
        # Prune old events
        self._prune_topic(event.topic)
        
        # Notify subscribers
        for sub_id, (topics, handler, group) in self._subscriptions.items():
            if event.topic in topics:
                queue = self._queues.get(sub_id)
                if queue:
                    try:
                        queue.put_nowait(event)
                    except asyncio.QueueFull:
                        logger.warning(f"Queue full for subscription {sub_id}, dropping event")
        
        return True
    
    async def subscribe(
        self,
        topics: List[str],
        handler: Callable[[StreamEvent], Awaitable[None]],
        consumer_group: Optional[str] = None,
    ) -> str:
        """Subscribe and start processing events."""
        sub_id = f"sub_{uuid.uuid4().hex[:12]}"
        
        self._subscriptions[sub_id] = (topics, handler, consumer_group)
        self._queues[sub_id] = asyncio.Queue(maxsize=self.max_queue_size)
        
        if consumer_group:
            self._consumer_groups[consumer_group].add(sub_id)
        
        # Start consumer task
        asyncio.create_task(self._consumer_loop(sub_id))
        
        logger.info(f"Subscription {sub_id} created for topics: {topics}")
        return sub_id
    
    async def unsubscribe(self, subscription_id: str) -> bool:
        """Stop subscription and cleanup."""
        if subscription_id not in self._subscriptions:
            return False
        
        topics, handler, group = self._subscriptions.pop(subscription_id)
        self._queues.pop(subscription_id, None)
        
        if group:
            self._consumer_groups[group].discard(subscription_id)
        
        logger.info(f"Subscription {subscription_id} removed")
        return True
    
    async def get_recent_events(
        self,
        topic: str,
        limit: int = 100,
        since_timestamp: Optional[float] = None,
    ) -> List[StreamEvent]:
        """Get recent events for catch-up."""
        events = self._topics.get(topic, [])
        
        if since_timestamp:
            events = [e for e in events if e.timestamp >= since_timestamp]
        
        return events[-limit:]
    
    def is_connected(self) -> bool:
        return self._running
    
    async def _consumer_loop(self, sub_id: str) -> None:
        """Process events from queue."""
        queue = self._queues.get(sub_id)
        if not queue:
            return
        
        while self._running and sub_id in self._subscriptions:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                
                topics, handler, group = self._subscriptions.get(sub_id, ([], None, None))
                if not handler:
                    continue
                
                # Idempotency check
                if group:
                    if event.event_id in self._processed_ids[group]:
                        continue
                    self._processed_ids[group].add(event.event_id)
                    
                    # Limit processed ID tracking
                    if len(self._processed_ids[group]) > 100000:
                        # Remove oldest half
                        self._processed_ids[group] = set(list(self._processed_ids[group])[-50000:])
                
                # Call handler
                try:
                    await handler(event)
                except Exception as e:
                    logger.error(f"Handler error for {sub_id}: {e}")
                    
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Consumer loop error for {sub_id}: {e}")
    
    def _prune_topic(self, topic: str) -> None:
        """Remove old events from topic."""
        events = self._topics[topic]
        
        # Prune by count
        if len(events) > self.max_events:
            self._topics[topic] = events[-self.max_events:]
        
        # Prune by TTL
        cutoff = time.time() - self.event_ttl
        self._topics[topic] = [e for e in self._topics[topic] if e.timestamp >= cutoff]
    
    async def shutdown(self) -> None:
        """Graceful shutdown."""
        self._running = False
        logger.info("InMemoryStreamBus shutdown")


# ============================================
# KAFKA IMPLEMENTATION
# ============================================

class KafkaStreamBus(StreamBus):
    """
    Kafka-backed stream bus for production.
    
    Uses aiokafka for async Kafka operations.
    Requires: pip install aiokafka
    """
    
    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        schema_registry_url: Optional[str] = None,
        client_id: str = "merid-stream-bus",
    ):
        self.bootstrap_servers = bootstrap_servers
        self.schema_registry_url = schema_registry_url
        self.client_id = client_id
        self._connected = False
        self._producer: Optional[Any] = None
        self._consumers: Dict[str, Any] = {}
        self._consumer_tasks: Dict[str, asyncio.Task] = {}
        self._handlers: Dict[str, Callable[[StreamEvent], Awaitable[None]]] = {}
        self._running = True
        self._lock = asyncio.Lock()
        
    async def connect(self) -> bool:
        """Connect to Kafka broker."""
        try:
            from aiokafka import AIOKafkaProducer
            
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                client_id=f"{self.client_id}-producer",
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                key_serializer=lambda k: k.encode('utf-8') if k else None,
                acks='all',
                enable_idempotence=True,
            )
            await self._producer.start()
            self._connected = True
            logger.info(f"KafkaStreamBus connected to {self.bootstrap_servers}")
            return True
        except ImportError:
            logger.error("aiokafka not installed. Run: pip install aiokafka")
            return False
        except Exception as e:
            logger.error(f"Failed to connect to Kafka: {e}")
            return False
    
    async def publish(self, event: StreamEvent) -> bool:
        """Publish event to Kafka topic."""
        if not self._connected or not self._producer:
            logger.warning("KafkaStreamBus not connected, attempting connect...")
            if not await self.connect():
                return False
        
        try:
            # Use event_id as key for partitioning
            key = event.event_id
            value = event.to_dict()
            
            await self._producer.send_and_wait(
                topic=event.topic,
                key=key,
                value=value,
            )
            logger.debug(f"Published event {event.event_id} to {event.topic}")
            return True
        except Exception as e:
            logger.error(f"Failed to publish event: {e}")
            return False
    
    async def subscribe(
        self,
        topics: List[str],
        handler: Callable[[StreamEvent], Awaitable[None]],
        consumer_group: Optional[str] = None,
    ) -> str:
        """Subscribe to Kafka topics."""
        try:
            from aiokafka import AIOKafkaConsumer
            
            subscription_id = f"sub_{uuid.uuid4().hex[:8]}"
            group_id = consumer_group or f"{self.client_id}-{subscription_id}"
            
            consumer = AIOKafkaConsumer(
                *topics,
                bootstrap_servers=self.bootstrap_servers,
                client_id=f"{self.client_id}-consumer-{subscription_id}",
                group_id=group_id,
                value_deserializer=lambda v: json.loads(v.decode('utf-8')),
                auto_offset_reset='latest',
                enable_auto_commit=True,
            )
            await consumer.start()
            
            self._consumers[subscription_id] = consumer
            self._handlers[subscription_id] = handler
            
            # Start consumer task
            task = asyncio.create_task(
                self._consume_loop(subscription_id, consumer, handler)
            )
            self._consumer_tasks[subscription_id] = task
            
            logger.info(f"Subscribed to {topics} with ID {subscription_id}")
            return subscription_id
            
        except ImportError:
            logger.error("aiokafka not installed. Run: pip install aiokafka")
            raise
        except Exception as e:
            logger.error(f"Failed to subscribe: {e}")
            raise
    
    async def _consume_loop(
        self,
        subscription_id: str,
        consumer: Any,
        handler: Callable[[StreamEvent], Awaitable[None]],
    ) -> None:
        """Consumer loop for processing messages."""
        try:
            async for msg in consumer:
                if not self._running:
                    break
                try:
                    # Parse message into StreamEvent
                    data = msg.value
                    event = StreamEvent(
                        event_id=data.get("event_id", str(uuid.uuid4())),
                        event_type=EventType(data.get("event_type", "custom")),
                        topic=msg.topic,
                        timestamp=data.get("timestamp", time.time()),
                        payload=data.get("payload", {}),
                        source=data.get("source", "kafka"),
                        schema_version=data.get("schema_version", "1.0"),
                    )
                    await handler(event)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
        except asyncio.CancelledError:
            logger.info(f"Consumer {subscription_id} cancelled")
        except Exception as e:
            logger.error(f"Consumer loop error: {e}")
        finally:
            await consumer.stop()
    
    async def unsubscribe(self, subscription_id: str) -> bool:
        """Unsubscribe from Kafka topics."""
        async with self._lock:
            if subscription_id in self._consumer_tasks:
                self._consumer_tasks[subscription_id].cancel()
                try:
                    await self._consumer_tasks[subscription_id]
                except asyncio.CancelledError:
                    pass
                del self._consumer_tasks[subscription_id]
            
            if subscription_id in self._consumers:
                del self._consumers[subscription_id]
            
            if subscription_id in self._handlers:
                del self._handlers[subscription_id]
            
            logger.info(f"Unsubscribed {subscription_id}")
            return True
    
    async def get_recent_events(
        self,
        topic: str,
        limit: int = 100,
        since_timestamp: Optional[float] = None,
    ) -> List[StreamEvent]:
        """Get recent events from Kafka topic (tail read)."""
        try:
            from aiokafka import AIOKafkaConsumer
            
            consumer = AIOKafkaConsumer(
                topic,
                bootstrap_servers=self.bootstrap_servers,
                value_deserializer=lambda v: json.loads(v.decode('utf-8')),
                auto_offset_reset='latest',
                enable_auto_commit=False,
            )
            await consumer.start()
            
            # Seek to end and go back
            partitions = consumer.assignment()
            if not partitions:
                await consumer.seek_to_end()
                partitions = consumer.assignment()
            
            events: List[StreamEvent] = []
            
            # Poll for messages with timeout
            try:
                batch = await asyncio.wait_for(
                    consumer.getmany(timeout_ms=1000, max_records=limit),
                    timeout=5.0
                )
                for tp, messages in batch.items():
                    for msg in messages:
                        data = msg.value
                        event = StreamEvent(
                            event_id=data.get("event_id", str(uuid.uuid4())),
                            event_type=EventType(data.get("event_type", "custom")),
                            topic=msg.topic,
                            timestamp=data.get("timestamp", time.time()),
                            payload=data.get("payload", {}),
                            source=data.get("source", "kafka"),
                        )
                        if since_timestamp is None or event.timestamp >= since_timestamp:
                            events.append(event)
            except asyncio.TimeoutError:
                pass
            
            await consumer.stop()
            return events[-limit:]
            
        except ImportError:
            logger.error("aiokafka not installed")
            return []
        except Exception as e:
            logger.error(f"Failed to get recent events: {e}")
            return []
    
    def is_connected(self) -> bool:
        return self._connected
    
    async def shutdown(self) -> None:
        """Graceful shutdown."""
        self._running = False
        
        # Cancel all consumer tasks
        for task in self._consumer_tasks.values():
            task.cancel()
        
        # Wait for tasks to complete
        if self._consumer_tasks:
            await asyncio.gather(*self._consumer_tasks.values(), return_exceptions=True)
        
        # Stop producer
        if self._producer:
            await self._producer.stop()
        
        self._connected = False
        logger.info("KafkaStreamBus shutdown complete")


# ============================================
# FACTORY
# ============================================

_stream_bus: Optional[StreamBus] = None


def get_stream_bus(backend: str = "memory") -> StreamBus:
    """
    Get the stream bus singleton.
    
    Args:
        backend: "memory" or "kafka"
    """
    global _stream_bus
    
    if _stream_bus is None:
        if backend == "kafka":
            _stream_bus = KafkaStreamBus()
        else:
            _stream_bus = InMemoryStreamBus.get_instance()
    
    return _stream_bus


# ============================================
# HELPER FUNCTIONS
# ============================================

async def publish_price_tick(
    symbol: str,
    venue: str,
    price: float,
    volume: Optional[float] = None,
    source: str = "price_feed",
) -> bool:
    """Convenience function to publish a price tick."""
    bus = get_stream_bus()
    event = StreamEvent.create(
        event_type=EventType.PRICE_TICK.value,
        topic=f"prices.{venue}.{symbol}",
        source=source,
        partition_key=f"{venue}:{symbol}",
        payload={
            "symbol": symbol,
            "venue": venue,
            "price": price,
            "volume": volume,
        },
    )
    return await bus.publish(event)


async def publish_agent_opinion(
    agent_id: str,
    symbol: str,
    stance: str,
    score: float,
    confidence: float,
    rationale: str,
    source: str = "agent",
) -> bool:
    """Convenience function to publish an agent opinion."""
    bus = get_stream_bus()
    event = StreamEvent.create(
        event_type=EventType.AGENT_OPINION.value,
        topic="agent.opinions",
        source=source,
        partition_key=symbol,
        payload={
            "agent_id": agent_id,
            "symbol": symbol,
            "stance": stance,
            "score": score,
            "confidence": confidence,
            "rationale": rationale,
        },
    )
    return await bus.publish(event)


async def publish_trade_execution(
    order_id: str,
    symbol: str,
    venue: str,
    side: str,
    size: float,
    price: float,
    agent_id: Optional[str] = None,
    source: str = "execution",
) -> bool:
    """Convenience function to publish a trade execution."""
    bus = get_stream_bus()
    event = StreamEvent.create(
        event_type=EventType.TRADE_EXECUTED.value,
        topic="trades.executed",
        source=source,
        partition_key=f"{venue}:{symbol}",
        payload={
            "order_id": order_id,
            "symbol": symbol,
            "venue": venue,
            "side": side,
            "size": size,
            "price": price,
            "agent_id": agent_id,
        },
    )
    return await bus.publish(event)
