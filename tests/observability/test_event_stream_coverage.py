"""Comprehensive tests for observability/event_stream.py - Coverage improvement."""

import pytest
import asyncio

from observability.event_stream import (
    EventRecord, EventStream, get_event_stream, publish_event,
    publish_event_async
)


# =============================================================================
# EventRecord Dataclass Tests
# =============================================================================

class TestEventRecord:
    """Test EventRecord dataclass."""

    def test_creation(self):
        record = EventRecord(
            event_type="test_event",
            payload={"key": "value"}
        )
        assert record.event_type == "test_event"
        assert record.payload == {"key": "value"}

    def test_timestamp_default(self):
        record = EventRecord(event_type="test", payload={})
        assert record.timestamp > 0


# =============================================================================
# EventStream Tests
# =============================================================================

@pytest.fixture
def stream():
    """Create EventStream."""
    return EventStream(max_queue=10)


class TestEventStreamInit:
    """Test EventStream initialization."""

    def test_defaults(self, stream):
        assert len(stream._listeners) == 0
        assert stream._max_queue == 10


class TestSubscribe:
    """Test subscribe method."""

    @pytest.mark.asyncio
    async def test_subscribe_returns_queue(self, stream):
        queue = await stream.subscribe()
        assert isinstance(queue, asyncio.Queue)
        assert queue in stream._listeners


class TestUnsubscribe:
    """Test unsubscribe method."""

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_queue(self, stream):
        queue = await stream.subscribe()
        await stream.unsubscribe(queue)
        assert queue not in stream._listeners


class TestPublish:
    """Test publish method."""

    @pytest.mark.asyncio
    async def test_publish_to_subscriber(self, stream):
        queue = await stream.subscribe()
        
        await stream.publish("test_event", {"data": "value"})
        
        record = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert record.event_type == "test_event"

    @pytest.mark.asyncio
    async def test_publish_empty_payload(self, stream):
        queue = await stream.subscribe()
        
        await stream.publish("test_event")
        
        record = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert record.payload == {}

    @pytest.mark.asyncio
    async def test_publish_to_full_queue(self, stream):
        small_stream = EventStream(max_queue=2)
        queue = await small_stream.subscribe()
        
        for i in range(5):
            await small_stream.publish(f"event_{i}", {"i": i})
        
        assert queue.qsize() <= 2


# =============================================================================
# Singleton Tests
# =============================================================================

class TestGetEventStream:
    """Test get_event_stream singleton."""

    def test_returns_stream(self):
        import observability.event_stream as module
        module._stream = None
        
        stream = get_event_stream()
        assert isinstance(stream, EventStream)

    def test_returns_same_instance(self):
        import observability.event_stream as module
        module._stream = None
        
        stream1 = get_event_stream()
        stream2 = get_event_stream()
        assert stream1 is stream2


# =============================================================================
# Publish Helper Tests
# =============================================================================

class TestPublishEventAsync:
    """Test publish_event_async function."""

    @pytest.mark.asyncio
    async def test_publishes_event(self):
        import observability.event_stream as module
        module._stream = None
        
        stream = get_event_stream()
        queue = await stream.subscribe()
        
        await publish_event_async("async_event", {"key": "value"})
        
        record = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert record.event_type == "async_event"


class TestPublishEvent:
    """Test publish_event function."""

    def test_publishes_without_loop(self):
        import observability.event_stream as module
        module._stream = None
        
        publish_event("sync_event", {"test": True})

    @pytest.mark.asyncio
    async def test_publishes_with_loop(self):
        import observability.event_stream as module
        module._stream = None
        
        stream = get_event_stream()
        queue = await stream.subscribe()
        
        publish_event("loop_event", {"running": True})
        
        await asyncio.sleep(0.1)
        assert not queue.empty()
