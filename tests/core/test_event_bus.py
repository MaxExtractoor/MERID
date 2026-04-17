"""Tests for core/event_bus.py."""
import pytest
import asyncio
from core.event_bus import LiveEventStream, event_stream


class TestLiveEventStream:
    """Test LiveEventStream class."""

    @pytest.mark.asyncio
    async def test_initialization(self):
        """Test stream initialization."""
        stream = LiveEventStream()
        assert stream._listeners == set()
        assert stream._max_queue == 200

    @pytest.mark.asyncio
    async def test_subscribe(self):
        """Test subscribing to stream."""
        stream = LiveEventStream()
        queue = await stream.subscribe()
        assert isinstance(queue, asyncio.Queue)
        assert queue in stream._listeners
        assert stream.listener_count() == 1

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        """Test unsubscribing from stream."""
        stream = LiveEventStream()
        queue = await stream.subscribe()
        await stream.unsubscribe(queue)
        assert queue not in stream._listeners
        assert stream.listener_count() == 0

    @pytest.mark.asyncio
    async def test_publish(self):
        """Test publishing event."""
        stream = LiveEventStream()
        queue = await stream.subscribe()
        await stream.publish("test_event", {"key": "value"})
        
        # Check event was received
        event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert event["type"] == "test_event"
        assert event["payload"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_publish_multiple_listeners(self):
        """Test publishing to multiple listeners."""
        stream = LiveEventStream()
        queue1 = await stream.subscribe()
        queue2 = await stream.subscribe()
        
        await stream.publish("event", {"data": 123})
        
        event1 = await asyncio.wait_for(queue1.get(), timeout=1.0)
        event2 = await asyncio.wait_for(queue2.get(), timeout=1.0)
        
        assert event1["type"] == "event"
        assert event2["type"] == "event"

    @pytest.mark.asyncio
    async def test_publish_removes_full_queues(self):
        """Test that full queues are removed from listeners."""
        stream = LiveEventStream()
        # Create a queue and fill it
        queue = asyncio.Queue(maxsize=1)
        queue.put_nowait({"dummy": "event"})  # Fill the queue
        
        # Manually add to listeners
        stream._listeners.add(queue)
        
        await stream.publish("test", {})
        # Queue should be removed because it was full
        assert queue not in stream._listeners


class TestGlobalEventStream:
    """Test global event_stream instance."""

    def test_stream_exists(self):
        """Test global event_stream exists."""
        assert event_stream is not None
        assert isinstance(event_stream, LiveEventStream)
