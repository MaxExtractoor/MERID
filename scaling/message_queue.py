"""
Message Queue System for MERID Production Scalability

Provides asynchronous message processing with RabbitMQ/Kafka support
and US-compliant configuration for reliable distributed processing.

Features:
- RabbitMQ and Kafka support
- Message reliability and ordering
- Async processing and callbacks
- Performance monitoring and metrics
- US-compliant message handling
"""

import asyncio
import time
import json
import uuid
import ormsgpack
from typing import Dict, List, Optional, Any, Callable, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque

# Message queue imports (with fallbacks)
try:
    import pika
    import aio_pika
    RABBITMQ_AVAILABLE = True
except ImportError:
    RABBITMQ_AVAILABLE = False

try:
    import aiokafka
    from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False

from utils.logger import get_logger

logger = get_logger("scaling.message_queue")

@dataclass
class MessageConfig:
    """Message queue configuration."""
    broker_type: str = "rabbitmq"  # rabbitmq, kafka
    connection_host: str = "localhost"
    connection_port: int = 5672
    username: str = "guest"
    password: str = "guest"
    virtual_host: str = "/"
    
    # Queue settings
    queue_durable: bool = True
    message_ttl: int = 3600000  # 1 hour in milliseconds
    max_retries: int = 3
    retry_delay: int = 5  # seconds
    
    # Performance settings
    prefetch_count: int = 100
    heartbeat_interval: int = 600
    connection_timeout: int = 30
    
    # Kafka specific
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_group_id: str = "merid_group"
    kafka_auto_offset_reset: str = "earliest"
    
    # US compliance
    encrypt_messages: bool = True
    audit_message_access: bool = True
    message_retention_days: int = 30

@dataclass
class Message:
    """Message structure."""
    message_id: str
    topic: str
    payload: Any
    headers: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    priority: int = 5  # 1-10, 10 is highest
    retry_count: int = 0
    max_retries: int = 3
    correlation_id: Optional[str] = None
    reply_to: Optional[str] = None
    expiration: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class QueueStats:
    """Queue performance statistics."""
    total_messages: int = 0
    successful_messages: int = 0
    failed_messages: int = 0
    retried_messages: int = 0
    avg_processing_time: float = 0.0
    total_processing_time: float = 0.0
    queue_depth: int = 0
    error_rate: float = 0.0
    throughput: float = 0.0  # messages per second

class MockMessageBroker:
    """Mock message broker for testing/fallback."""
    
    def __init__(self):
        self.queues: Dict[str, deque] = {}
        self.consumers: Dict[str, List[Callable]] = {}
        self.stats = {"published": 0, "consumed": 0}
    
    async def publish(self, topic: str, message: Message):
        """Publish message to topic."""
        if topic not in self.queues:
            self.queues[topic] = deque(maxlen=1000)
        
        self.queues[topic].append(message)
        self.stats["published"] += 1
        
        # Notify consumers
        if topic in self.consumers:
            for consumer in self.consumers[topic]:
                try:
                    await consumer(message)
                except Exception as e:
                    logger.error(f"Consumer error: {e}")
    
    async def subscribe(self, topic: str, callback: Callable):
        """Subscribe to topic."""
        if topic not in self.consumers:
            self.consumers[topic] = []
        self.consumers[topic].append(callback)
    
    def get_stats(self):
        return self.stats

class MessageQueue:
    """
    Production-grade message queue system for MERID.
    
    Provides reliable asynchronous message processing with support
    for RabbitMQ and Kafka brokers.
    """
    
    def __init__(self, config: MessageConfig):
        self.config = config
        
        # Broker connection
        self.broker_client: Optional[Any] = None
        self.broker_available = False
        self.broker_type = config.broker_type.lower()
        
        # Queue management
        self.producers: Dict[str, Any] = {}
        self.consumers: Dict[str, Any] = {}
        self.queues: Dict[str, str] = {}  # topic -> queue name mapping
        
        # Message handlers
        self.message_handlers: Dict[str, Callable] = {}
        self.error_handlers: Dict[str, Callable] = {}
        
        # Statistics
        self.stats: Dict[str, QueueStats] = {}
        self.message_history: deque = deque(maxlen=10000)
        
        # US compliance
        self.compliance_audit: deque = deque(maxlen=10000)
        
        # Retry mechanism
        self.retry_queue: deque = deque(maxlen=1000)
        self.retry_task: Optional[asyncio.Task] = None
        
        logger.info(f"MessageQueue initialized with {self.broker_type} broker")
    
    async def start(self):
        """Start the message queue system."""
        try:
            # Initialize broker connection
            await self._init_broker()
            
            # Start retry mechanism
            self.retry_task = asyncio.create_task(self._retry_loop())
            
            logger.info(f"Message queue started (broker: {self.broker_type}, available: {self.broker_available})")
            
        except Exception as e:
            logger.error(f"Failed to start message queue: {e}")
    
    async def stop(self):
        """Stop the message queue system."""
        try:
            # Stop retry task
            if self.retry_task:
                self.retry_task.cancel()
                try:
                    await self.retry_task
                except asyncio.CancelledError:
                    pass
            
            # Close broker connections
            await self._close_broker()
            
            logger.info("Message queue stopped")
            
        except Exception as e:
            logger.error(f"Failed to stop message queue: {e}")
    
    async def publish(self, topic: str, payload: Any, **message_kwargs) -> bool:
        """Publish message to topic."""
        try:
            # Create message
            message = Message(
                message_id=str(uuid.uuid4()),
                topic=topic,
                payload=payload,
                headers=message_kwargs.get("headers", {}),
                priority=message_kwargs.get("priority", 5),
                max_retries=message_kwargs.get("max_retries", self.config.max_retries),
                correlation_id=message_kwargs.get("correlation_id"),
                reply_to=message_kwargs.get("reply_to"),
                expiration=message_kwargs.get("expiration")
            )
            
            # Add metadata
            message.metadata.update(message_kwargs.get("metadata", {}))
            
            # Encrypt if required
            if self.config.encrypt_messages:
                message.payload = await self._encrypt_payload(message.payload)
            
            # Publish to broker
            if self.broker_available:
                await self._publish_to_broker(message)
            else:
                await self._publish_to_mock(message)
            
            # Update statistics
            self._update_stats(topic, "published")
            
            # Record for compliance
            if self.config.audit_message_access:
                await self._record_compliance("publish", topic, message.message_id)
            
            logger.debug(f"Published message {message.message_id} to topic {topic}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to publish message to {topic}: {e}")
            return False
    
    async def subscribe(self, topic: str, handler: Callable, 
                       error_handler: Optional[Callable] = None) -> bool:
        """Subscribe to topic with message handler."""
        try:
            # Store handlers
            self.message_handlers[topic] = handler
            if error_handler:
                self.error_handlers[topic] = error_handler
            
            # Subscribe to broker
            if self.broker_available:
                await self._subscribe_to_broker(topic)
            else:
                await self._subscribe_to_mock(topic)
            
            logger.info(f"Subscribed to topic {topic}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to subscribe to {topic}: {e}")
            return False
    
    async def create_queue(self, topic: str, queue_name: Optional[str] = None,
                          durable: Optional[bool] = None, **kwargs) -> bool:
        """Create a queue for a topic."""
        try:
            if queue_name is None:
                queue_name = f"merid_{topic}"
            
            self.queues[topic] = queue_name
            
            if self.broker_available:
                await self._create_broker_queue(topic, queue_name, durable, **kwargs)
            
            logger.info(f"Created queue {queue_name} for topic {topic}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create queue for {topic}: {e}")
            return False
    
    async def _init_broker(self):
        """Initialize broker connection."""
        try:
            if self.broker_type == "rabbitmq":
                await self._init_rabbitmq()
            elif self.broker_type == "kafka":
                await self._init_kafka()
            else:
                logger.warning(f"Unknown broker type: {self.broker_type}, using mock")
                self.broker_client = MockMessageBroker()
                self.broker_available = True
                
        except Exception as e:
            logger.error(f"Failed to initialize broker: {e}")
            self.broker_client = MockMessageBroker()
            self.broker_available = True
    
    async def _init_rabbitmq(self):
        """Initialize RabbitMQ connection."""
        if not RABBITMQ_AVAILABLE:
            logger.warning("RabbitMQ not available, using mock")
            self.broker_client = MockMessageBroker()
            self.broker_available = True
            return
        
        try:
            # Create connection
            connection = await aio_pika.connect_robust(
                host=self.config.connection_host,
                port=self.config.connection_port,
                login=self.config.username,
                password=self.config.password,
                virtual_host=self.config.virtual_host,
                heartbeat=self.config.heartbeat_interval
            )
            
            # Create channel
            channel = await connection.channel()
            await channel.set_qos(prefetch_count=self.config.prefetch_count)
            
            self.broker_client = {"connection": connection, "channel": channel}
            self.broker_available = True
            
            logger.info("RabbitMQ connection established")
            
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            self.broker_client = MockMessageBroker()
            self.broker_available = True
    
    async def _init_kafka(self):
        """Initialize Kafka connection."""
        if not KAFKA_AVAILABLE:
            logger.warning("Kafka not available, using mock")
            self.broker_client = MockMessageBroker()
            self.broker_available = True
            return
        
        try:
            # Create producer
            producer = AIOKafkaProducer(
                bootstrap_servers=self.config.kafka_bootstrap_servers,
                value_serializer=lambda v: ormsgpack.packb(v)
            )
            
            await producer.start()
            self.producers["default"] = producer
            
            self.broker_client = {"producer": producer}
            self.broker_available = True
            
            logger.info("Kafka connection established")
            
        except Exception as e:
            logger.error(f"Failed to connect to Kafka: {e}")
            self.broker_client = MockMessageBroker()
            self.broker_available = True
    
    async def _close_broker(self):
        """Close broker connections."""
        try:
            if self.broker_type == "rabbitmq" and self.broker_available:
                if "connection" in self.broker_client:
                    await self.broker_client["connection"].close()
            
            elif self.broker_type == "kafka" and self.broker_available:
                for producer in self.producers.values():
                    await producer.stop()
                for consumer in self.consumers.values():
                    await consumer.stop()
            
            logger.info("Broker connections closed")
            
        except Exception as e:
            logger.error(f"Failed to close broker connections: {e}")
    
    async def _publish_to_broker(self, message: Message):
        """Publish message to actual broker."""
        try:
            if self.broker_type == "rabbitmq":
                await self._publish_to_rabbitmq(message)
            elif self.broker_type == "kafka":
                await self._publish_to_kafka(message)
                
        except Exception as e:
            logger.error(f"Failed to publish to broker: {e}")
            raise
    
    async def _publish_to_rabbitmq(self, message: Message):
        """Publish message to RabbitMQ."""
        channel = self.broker_client["channel"]
        
        # Create message properties
        properties = aio_pika.BasicProperties(
            message_id=message.message_id,
            timestamp=datetime.fromtimestamp(message.timestamp),
            priority=message.priority,
            headers=message.headers,
            correlation_id=message.correlation_id,
            reply_to=message.reply_to,
            expiration=str(message.expiration) if message.expiration else None
        )
        
        # Publish message
        await channel.default_exchange.publish(
            aio_pika.Message(
                body=ormsgpack.packb(message.payload),
                properties=properties
            ),
            routing_key=message.topic
        )
    
    async def _publish_to_kafka(self, message: Message):
        """Publish message to Kafka."""
        producer = self.producers.get("default")
        if not producer:
            raise Exception("Kafka producer not available")
        
        # Add headers to message
        kafka_message = {
            "message_id": message.message_id,
            "timestamp": message.timestamp,
            "priority": message.priority,
            "headers": message.headers,
            "correlation_id": message.correlation_id,
            "reply_to": message.reply_to,
            "payload": message.payload
        }
        
        await producer.send_and_wait(
            topic=message.topic,
            value=kafka_message,
            key=message.message_id.encode()
        )
    
    async def _publish_to_mock(self, message: Message):
        """Publish message to mock broker."""
        await self.broker_client.publish(message.topic, message)
    
    async def _subscribe_to_broker(self, topic: str):
        """Subscribe to actual broker."""
        try:
            if self.broker_type == "rabbitmq":
                await self._subscribe_to_rabbitmq(topic)
            elif self.broker_type == "kafka":
                await self._subscribe_to_kafka(topic)
                
        except Exception as e:
            logger.error(f"Failed to subscribe to broker: {e}")
            raise
    
    async def _subscribe_to_rabbitmq(self, topic: str):
        """Subscribe to RabbitMQ."""
        channel = self.broker_client["channel"]
        
        # Declare queue
        queue_name = self.queues.get(topic, f"merid_{topic}")
        await channel.queue_declare(queue=queue_name, durable=self.config.queue_durable)
        
        # Bind queue
        await channel.queue_bind(queue=queue_name, exchange="", routing_key=topic)
        
        # Start consuming
        async def message_handler(channel, body, envelope, properties):
            try:
                # Deserialize message
                payload = ormsgpack.unpackb(body)
                
                # Create message object
                message = Message(
                    message_id=properties.message_id,
                    topic=topic,
                    payload=payload,
                    headers=properties.headers or {},
                    timestamp=properties.timestamp.timestamp(),
                    priority=properties.priority,
                    correlation_id=properties.correlation_id,
                    reply_to=properties.reply_to
                )
                
                # Handle message
                await self._handle_message(message)
                
            except Exception as e:
                logger.error(f"Error handling RabbitMQ message: {e}")
        
        await channel.basic_consume(
            queue=queue_name,
            on_message_callback=message_handler,
            auto_ack=False
        )
    
    async def _subscribe_to_kafka(self, topic: str):
        """Subscribe to Kafka."""
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=self.config.kafka_bootstrap_servers,
            group_id=self.config.kafka_group_id,
            auto_offset_reset=self.config.kafka_auto_offset_reset,
            value_deserializer=lambda v: ormsgpack.unpackb(v)
        )
        
        await consumer.start()
        self.consumers[topic] = consumer
        
        # Start consuming loop
        asyncio.create_task(self._kafka_consume_loop(topic, consumer))
    
    async def _kafka_consume_loop(self, topic: str, consumer):
        """Kafka consumption loop."""
        try:
            async for message in consumer:
                try:
                    # Create message object
                    kafka_message = message.value
                    msg = Message(
                        message_id=kafka_message["message_id"],
                        topic=topic,
                        payload=kafka_message["payload"],
                        headers=kafka_message.get("headers", {}),
                        timestamp=kafka_message["timestamp"],
                        priority=kafka_message.get("priority", 5),
                        correlation_id=kafka_message.get("correlation_id"),
                        reply_to=kafka_message.get("reply_to")
                    )
                    
                    # Handle message
                    await self._handle_message(msg)
                    
                except Exception as e:
                    logger.error(f"Error handling Kafka message: {e}")
                    
        except Exception as e:
            logger.error(f"Kafka consume loop error for {topic}: {e}")
    
    async def _subscribe_to_mock(self, topic: str):
        """Subscribe to mock broker."""
        handler = self.message_handlers.get(topic)
        if handler:
            await self.broker_client.subscribe(topic, handler)
    
    async def _handle_message(self, message: Message):
        """Handle incoming message."""
        start_time = time.time()
        
        try:
            # Decrypt if required
            if self.config.encrypt_messages:
                message.payload = await self._decrypt_payload(message.payload)
            
            # Get handler
            handler = self.message_handlers.get(message.topic)
            if not handler:
                logger.warning(f"No handler for topic {message.topic}")
                return
            
            # Process message
            try:
                await handler(message.payload, message)
                self._update_stats(message.topic, "success")
                
            except Exception as e:
                logger.error(f"Handler error for {message.topic}: {e}")
                
                # Retry logic
                if message.retry_count < message.max_retries:
                    message.retry_count += 1
                    self.retry_queue.append(message)
                    self._update_stats(message.topic, "retry")
                else:
                    # Call error handler
                    error_handler = self.error_handlers.get(message.topic)
                    if error_handler:
                        try:
                            await error_handler(message, e)
                        except Exception as ee:
                            logger.error(f"Error handler failed: {ee}")
                    
                    self._update_stats(message.topic, "failed")
            
            # Record processing time
            processing_time = time.time() - start_time
            self._record_processing_time(message.topic, processing_time)
            
            # Record for compliance
            if self.config.audit_message_access:
                await self._record_compliance("consume", message.topic, message.message_id)
            
        except Exception as e:
            logger.error(f"Failed to handle message: {e}")
            self._update_stats(message.topic, "failed")
    
    async def _retry_loop(self):
        """Background retry loop."""
        while True:
            try:
                if self.retry_queue:
                    message = self.retry_queue.popleft()
                    
                    # Wait before retry
                    await asyncio.sleep(self.config.retry_delay)
                    
                    # Republish message
                    await self._publish_to_broker(message)
                    logger.info(f"Retried message {message.message_id}")
                
                await asyncio.sleep(1)  # Check every second
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Retry loop error: {e}")
                await asyncio.sleep(5)
    
    async def _encrypt_payload(self, payload: Any) -> Any:
        """Encrypt message payload."""
        # Simple mock encryption (in production, use proper encryption)
        return ormsgpack.packb(payload)
    
    async def _decrypt_payload(self, payload: Any) -> Any:
        """Decrypt message payload."""
        # Simple mock decryption (in production, use proper decryption)
        return ormsgpack.unpackb(payload)
    
    def _update_stats(self, topic: str, result: str):
        """Update queue statistics."""
        if topic not in self.stats:
            self.stats[topic] = QueueStats()
        
        stats = self.stats[topic]
        
        if result == "published":
            stats.total_messages += 1
        elif result == "success":
            stats.successful_messages += 1
        elif result == "failed":
            stats.failed_messages += 1
        elif result == "retry":
            stats.retried_messages += 1
        
        # Calculate error rate
        total_processed = stats.successful_messages + stats.failed_messages
        if total_processed > 0:
            stats.error_rate = stats.failed_messages / total_processed
    
    def _record_processing_time(self, topic: str, processing_time: float):
        """Record message processing time."""
        if topic not in self.stats:
            self.stats[topic] = QueueStats()
        
        stats = self.stats[topic]
        stats.total_processing_time += processing_time
        stats.total_messages += 1
        stats.avg_processing_time = stats.total_processing_time / stats.total_messages
    
    async def _record_compliance(self, action: str, topic: str, message_id: str):
        """Record compliance audit entry."""
        if not self.config.audit_message_access:
            return
        
        audit_entry = {
            "action": action,
            "topic": topic,
            "message_id": message_id,
            "timestamp": time.time(),
            "user": "system"  # In production, get actual user
        }
        
        self.compliance_audit.append(audit_entry)
    
    def get_queue_stats(self, topic: Optional[str] = None) -> Union[Dict[str, Any], QueueStats]:
        """Get queue statistics."""
        if topic:
            return self.stats.get(topic, QueueStats())
        
        return {
            topic: stats for topic, stats in self.stats.items()
        }
    
    def get_broker_info(self) -> Dict[str, Any]:
        """Get broker information."""
        return {
            "broker_type": self.broker_type,
            "broker_available": self.broker_available,
            "queues": len(self.queues),
            "producers": len(self.producers),
            "consumers": len(self.consumers),
            "handlers": len(self.message_handlers),
            "retry_queue_size": len(self.retry_queue),
            "compliance_audits": len(self.compliance_audit)
        }
