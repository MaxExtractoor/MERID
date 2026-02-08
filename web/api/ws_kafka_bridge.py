"""
WebSocket to Kafka Bridge

Bridges WebSocket connections to Kafka/Redpanda streams, allowing
the React frontend to consume Kafka topics via WebSocket.
"""

import asyncio
import json
import time
from typing import Dict, Set, Optional, Any
from fastapi import WebSocket, WebSocketDisconnect
from utils.logger import get_logger

logger = get_logger("ws_kafka_bridge")


class KafkaBridge:
    """
    Bridges Kafka topics to WebSocket clients.
    
    Each topic gets a dedicated consumer that broadcasts to all
    connected WebSocket clients subscribed to that topic.
    """
    
    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        client_id: str = "merid-ws-bridge",
    ):
        self.bootstrap_servers = bootstrap_servers
        self.client_id = client_id
        self._consumers: Dict[str, Any] = {}
        self._consumer_tasks: Dict[str, asyncio.Task] = {}
        self._topic_subscribers: Dict[str, Set[WebSocket]] = {}
        self._running = True
        self._lock = asyncio.Lock()
        
    async def subscribe_client(
        self,
        websocket: WebSocket,
        topics: list[str],
    ) -> None:
        """Subscribe a WebSocket client to Kafka topics."""
        async with self._lock:
            for topic in topics:
                if topic not in self._topic_subscribers:
                    self._topic_subscribers[topic] = set()
                    # Start consumer for this topic
                    await self._start_topic_consumer(topic)
                
                self._topic_subscribers[topic].add(websocket)
                logger.info(f"Client subscribed to {topic}")
    
    async def unsubscribe_client(self, websocket: WebSocket) -> None:
        """Unsubscribe a WebSocket client from all topics."""
        async with self._lock:
            for topic, subscribers in list(self._topic_subscribers.items()):
                subscribers.discard(websocket)
                
                # Stop consumer if no more subscribers
                if not subscribers:
                    await self._stop_topic_consumer(topic)
                    del self._topic_subscribers[topic]
    
    async def _start_topic_consumer(self, topic: str) -> None:
        """Start a Kafka consumer for a topic."""
        try:
            from aiokafka import AIOKafkaConsumer
            
            consumer = AIOKafkaConsumer(
                topic,
                bootstrap_servers=self.bootstrap_servers,
                client_id=f"{self.client_id}-{topic}",
                group_id=f"{self.client_id}-ws-group",
                value_deserializer=lambda v: json.loads(v.decode('utf-8')),
                auto_offset_reset='latest',
                enable_auto_commit=True,
            )
            await consumer.start()
            
            self._consumers[topic] = consumer
            task = asyncio.create_task(self._consume_and_broadcast(topic, consumer))
            self._consumer_tasks[topic] = task
            
            logger.info(f"Started Kafka consumer for {topic}")
            
        except ImportError:
            logger.warning("aiokafka not installed, using mock consumer")
            # Fallback to in-memory stream bus
            await self._start_mock_consumer(topic)
        except Exception as e:
            logger.error(f"Failed to start consumer for {topic}: {e}")
    
    async def _start_mock_consumer(self, topic: str) -> None:
        """Start a mock consumer using InMemoryStreamBus."""
        try:
            from streaming import get_stream_bus
            
            bus = get_stream_bus("memory")
            
            async def handler(event):
                await self._broadcast_to_topic(topic, event.to_dict())
            
            sub_id = await bus.subscribe([topic], handler)
            self._consumers[topic] = {"type": "mock", "sub_id": sub_id, "bus": bus}
            logger.info(f"Started mock consumer for {topic}")
            
        except Exception as e:
            logger.error(f"Failed to start mock consumer: {e}")
    
    async def _stop_topic_consumer(self, topic: str) -> None:
        """Stop a Kafka consumer for a topic."""
        if topic in self._consumer_tasks:
            self._consumer_tasks[topic].cancel()
            try:
                await self._consumer_tasks[topic]
            except asyncio.CancelledError:
                pass
            del self._consumer_tasks[topic]
        
        if topic in self._consumers:
            consumer = self._consumers[topic]
            if isinstance(consumer, dict) and consumer.get("type") == "mock":
                # Mock consumer cleanup
                bus = consumer.get("bus")
                if bus:
                    await bus.unsubscribe(consumer.get("sub_id", ""))
            else:
                # Kafka consumer cleanup
                await consumer.stop()
            del self._consumers[topic]
        
        logger.info(f"Stopped consumer for {topic}")
    
    async def _consume_and_broadcast(self, topic: str, consumer: Any) -> None:
        """Consume messages and broadcast to WebSocket clients."""
        try:
            async for msg in consumer:
                if not self._running:
                    break
                
                try:
                    data = msg.value
                    # Add metadata
                    data["_topic"] = topic
                    data["_partition"] = msg.partition
                    data["_offset"] = msg.offset
                    data["_timestamp"] = msg.timestamp
                    
                    await self._broadcast_to_topic(topic, data)
                    
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    
        except asyncio.CancelledError:
            logger.info(f"Consumer for {topic} cancelled")
        except Exception as e:
            logger.error(f"Consumer loop error for {topic}: {e}")
    
    async def _broadcast_to_topic(self, topic: str, data: dict) -> None:
        """Broadcast message to all subscribers of a topic."""
        subscribers = self._topic_subscribers.get(topic, set())
        
        if not subscribers:
            return
        
        message = json.dumps(data)
        disconnected = set()
        
        for ws in subscribers:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.add(ws)
        
        # Clean up disconnected clients
        for ws in disconnected:
            subscribers.discard(ws)
    
    async def shutdown(self) -> None:
        """Graceful shutdown."""
        self._running = False
        
        # Stop all consumers
        for topic in list(self._consumers.keys()):
            await self._stop_topic_consumer(topic)
        
        logger.info("KafkaBridge shutdown complete")


# Singleton instance
_bridge: Optional[KafkaBridge] = None


def get_kafka_bridge() -> KafkaBridge:
    """Get the singleton Kafka bridge instance."""
    global _bridge
    if _bridge is None:
        import os
        bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        _bridge = KafkaBridge(bootstrap_servers=bootstrap)
    return _bridge


async def kafka_bridge_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for Kafka bridge.
    
    Protocol:
    - Client connects and sends: {"subscribe": ["topic1", "topic2"]}
    - Server streams messages from those topics
    - Client can send: {"unsubscribe": ["topic1"]} to stop
    """
    await websocket.accept()
    bridge = get_kafka_bridge()
    subscribed_topics: Set[str] = set()
    
    try:
        # Send connection confirmation
        await websocket.send_json({
            "type": "connected",
            "timestamp": time.time(),
            "message": "Kafka bridge connected"
        })
        
        while True:
            try:
                # Wait for subscription requests
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=30.0
                )
                
                if "subscribe" in data:
                    topics = data["subscribe"]
                    if isinstance(topics, list):
                        await bridge.subscribe_client(websocket, topics)
                        subscribed_topics.update(topics)
                        await websocket.send_json({
                            "type": "subscribed",
                            "topics": topics
                        })
                
                if "unsubscribe" in data:
                    topics = data["unsubscribe"]
                    # Note: full unsubscribe happens on disconnect
                    subscribed_topics.difference_update(topics)
                    await websocket.send_json({
                        "type": "unsubscribed",
                        "topics": topics
                    })
                
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                    
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_json({
                    "type": "heartbeat",
                    "timestamp": time.time()
                })
                
    except WebSocketDisconnect:
        logger.info("Kafka bridge client disconnected")
    except Exception as e:
        logger.error(f"Kafka bridge error: {e}")
    finally:
        await bridge.unsubscribe_client(websocket)
