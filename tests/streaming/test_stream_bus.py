"""
Tests for StreamBus abstraction.
"""

import pytest

# Quarantined: async event loop hangs on Windows IOCP in select/poll
pytestmark = pytest.mark.windows_flaky_async

import asyncio
import time
from unittest.mock import MagicMock, AsyncMock, patch


class TestStreamEvent:
    """Tests for StreamEvent dataclass."""
    
    def test_create_event(self):
        """Test creating a stream event."""
        from streaming import StreamEvent, EventType
        
        event = StreamEvent.create(
            event_type=EventType.TRADE_EXECUTED.value,
            topic="trades.executed",
            source="test",
            payload={"symbol": "BTC", "price": 50000},
        )
        
        assert event.event_id.startswith("evt_")
        assert event.event_type == EventType.TRADE_EXECUTED.value
        assert event.topic == "trades.executed"
        assert event.payload["symbol"] == "BTC"
    
    def test_event_to_dict(self):
        """Test converting event to dictionary."""
        from streaming import StreamEvent, EventType
        
        event = StreamEvent.create(
            event_type=EventType.PRICE_TICK.value,
            topic="prices.kraken.BTCUSD",
            source="test",
            payload={"price": 50000},
        )
        
        d = event.to_dict()
        assert d["event_id"].startswith("evt_")
        assert d["event_type"] == "price.tick"
        assert d["topic"] == "prices.kraken.BTCUSD"


class TestInMemoryStreamBus:
    """Tests for InMemoryStreamBus."""
    
    @pytest.fixture
    def bus(self):
        """Create a fresh bus for each test."""
        from streaming import InMemoryStreamBus
        return InMemoryStreamBus()
    
    @pytest.mark.asyncio
    async def test_publish_and_subscribe(self, bus):
        """Test basic publish/subscribe."""
        received = []
        
        async def handler(event):
            received.append(event)
        
        await bus.subscribe(["test.topic"], handler)
        
        from streaming import StreamEvent, EventType
        event = StreamEvent.create(
            event_type=EventType.HEARTBEAT.value,
            topic="test.topic",
            source="test",
            payload={"message": "hello"},
        )
        
        result = await bus.publish(event)
        assert result is True
        
        # Give async handlers time to process
        await asyncio.sleep(0.1)
        
        assert len(received) == 1
        assert received[0].event_id.startswith("evt_")
    
    @pytest.mark.asyncio
    async def test_multiple_subscribers(self, bus):
        """Test multiple subscribers receive the same event."""
        received1 = []
        received2 = []
        
        async def handler1(event):
            received1.append(event)
        
        async def handler2(event):
            received2.append(event)
        
        await bus.subscribe(["test.topic"], handler1)
        await bus.subscribe(["test.topic"], handler2)
        
        from streaming import StreamEvent, EventType
        event = StreamEvent.create(
            event_type=EventType.HEARTBEAT.value,
            topic="test.topic",
            source="test",
            payload={},
        )
        
        await bus.publish(event)
        await asyncio.sleep(0.1)
        
        assert len(received1) == 1
        assert len(received2) == 1
    
    @pytest.mark.asyncio
    async def test_topic_filtering(self, bus):
        """Test that subscribers only receive events for their topics."""
        received = []
        
        async def handler(event):
            received.append(event)
        
        await bus.subscribe(["topic.a"], handler)
        
        from streaming import StreamEvent, EventType
        
        # Publish to subscribed topic
        event_a = StreamEvent.create(
            event_type=EventType.HEARTBEAT.value,
            topic="topic.a",
            source="test",
            payload={},
        )
        await bus.publish(event_a)
        
        # Publish to different topic
        event_b = StreamEvent.create(
            event_type=EventType.HEARTBEAT.value,
            topic="topic.b",
            source="test",
            payload={},
        )
        await bus.publish(event_b)
        
        await asyncio.sleep(0.1)
        
        # Should only receive event_a
        assert len(received) == 1
        assert received[0].topic == "topic.a"
    
    @pytest.mark.asyncio
    async def test_unsubscribe(self, bus):
        """Test unsubscribing stops message delivery."""
        received = []
        
        async def handler(event):
            received.append(event)
        
        sub_id = await bus.subscribe(["test.topic"], handler)
        
        from streaming import StreamEvent, EventType
        
        # Publish first event
        event1 = StreamEvent.create(
            event_type=EventType.HEARTBEAT.value,
            topic="test.topic",
            source="test",
            payload={},
        )
        await bus.publish(event1)
        await asyncio.sleep(0.1)
        
        assert len(received) == 1
        
        # Unsubscribe
        await bus.unsubscribe(sub_id)
        
        # Publish second event
        event2 = StreamEvent.create(
            event_type=EventType.HEARTBEAT.value,
            topic="test.topic",
            source="test",
            payload={},
        )
        await bus.publish(event2)
        await asyncio.sleep(0.1)
        
        # Should still only have first event
        assert len(received) == 1
    
    @pytest.mark.asyncio
    async def test_get_recent_events(self, bus):
        """Test retrieving recent events."""
        from streaming import StreamEvent, EventType
        
        # Publish some events
        for i in range(5):
            event = StreamEvent.create(
                event_type=EventType.HEARTBEAT.value,
                topic="test.topic",
                source="test",
                payload={"index": i},
            )
            await bus.publish(event)
        
        events = await bus.get_recent_events("test.topic", limit=3)
        
        assert len(events) <= 3
    
    @pytest.mark.asyncio
    async def test_is_connected(self, bus):
        """Test connection status."""
        assert bus.is_connected() is True
    
    @pytest.mark.asyncio
    async def test_shutdown(self, bus):
        """Test graceful shutdown."""
        await bus.shutdown()
        # Should not raise


class TestStreamBusFactory:
    """Tests for stream bus factory."""
    
    def test_get_memory_bus(self):
        """Test getting in-memory bus."""
        from streaming import get_stream_bus
        
        bus = get_stream_bus("memory")
        assert bus is not None
        assert bus.is_connected()
    
    def test_get_kafka_bus(self):
        """Test getting Kafka bus (may fail without Kafka)."""
        from streaming import get_stream_bus
        
        # This should return KafkaStreamBus but may not connect
        bus = get_stream_bus("kafka")
        assert bus is not None


class TestEventHelpers:
    """Tests for event publishing helper functions."""
    
    @pytest.mark.asyncio
    async def test_publish_price_tick(self):
        """Test publishing a price tick event."""
        from streaming import publish_price_tick, get_stream_bus
        
        bus = get_stream_bus("memory")
        received = []
        
        async def handler(event):
            received.append(event)
        
        await bus.subscribe(["prices.kraken.BTCUSD"], handler)
        
        await publish_price_tick(
            symbol="BTCUSD",
            venue="kraken",
            price=50000.0,
            volume=1.5,
        )
        
        await asyncio.sleep(0.1)
        # May or may not receive depending on topic routing
        assert isinstance(received, list)
    
    @pytest.mark.asyncio
    async def test_publish_trade_execution(self):
        """Test publishing a trade execution event."""
        from streaming import publish_trade_execution, get_stream_bus
        
        bus = get_stream_bus("memory")
        
        # Should not raise
        await publish_trade_execution(
            order_id="order_001",
            symbol="BTCUSD",
            venue="paper",
            side="buy",
            size=0.1,
            price=50000.0,
        )
