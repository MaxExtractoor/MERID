"""
MERID Streaming Module.

Provides event streaming abstractions that can be backed by:
- In-memory queues (development)
- Kafka (production)
- Redis Streams (lightweight production)
"""

from streaming.stream_bus import (
    StreamBus,
    StreamEvent,
    EventType,
    InMemoryStreamBus,
    KafkaStreamBus,
    get_stream_bus,
    publish_price_tick,
    publish_agent_opinion,
    publish_trade_execution,
)

__all__ = [
    "StreamBus",
    "StreamEvent",
    "EventType",
    "InMemoryStreamBus",
    "KafkaStreamBus",
    "get_stream_bus",
    "publish_price_tick",
    "publish_agent_opinion",
    "publish_trade_execution",
]
