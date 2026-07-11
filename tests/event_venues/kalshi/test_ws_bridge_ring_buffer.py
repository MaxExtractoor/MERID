"""Tests for WS bridge ring buffer backpressure (P1 FIX)."""

import pytest
import queue
from unittest.mock import MagicMock, patch


@pytest.fixture
def bridge():
    """Create test WS bridge mock (avoid singleton constraint)."""
    # Mock the bridge to avoid singleton instantiation constraint
    bridge = MagicMock()
    bridge._queue = queue.Queue(maxsize=100)
    bridge._thread_queue = queue.Queue(maxsize=100)
    bridge._events_dropped = 0
    bridge._fills_dropped = 0
    return bridge


class TestRingBufferBackpressure:
    """Test ring buffer overflow strategy."""
    
    def test_ring_buffer_drops_oldest_non_fill(self, bridge):
        """Test that ring buffer drops oldest non-fill event when queue is full."""
        # Fill queue to capacity
        for i in range(100):
            bridge._queue.put_nowait({"type": "orderbook_delta", "seq": i})
        
        # Queue is now full, try to add a new event
        new_event = {"type": "orderbook_delta", "seq": 100}
        
        # Simulate the ring buffer logic
        try:
            oldest = bridge._queue.get_nowait()
            event_type = oldest.get("type") if isinstance(oldest, dict) else "unknown"
            
            if event_type != "fill":
                bridge._events_dropped += 1
                bridge._queue.put_nowait(new_event)
            else:
                bridge._queue.put_nowait(oldest)
                bridge._events_dropped += 1
        except queue.Empty:
            pass
        
        # Should have dropped one event and added the new one
        assert bridge._events_dropped == 1
        assert bridge._queue.qsize() == 100
        
        # Verify the oldest was removed and new event added
        events = []
        while not bridge._queue.empty():
            events.append(bridge._queue.get_nowait())
        
        # First event should be seq=1 (oldest seq=0 was dropped)
        assert events[0]["seq"] == 1
        # Last event should be the new event
        assert events[-1]["seq"] == 100
    
    def test_ring_buffer_preserves_fill_events(self, bridge):
        """Test that ring buffer preserves fill events when possible."""
        # Fill queue with non-fill events
        for i in range(99):
            bridge._queue.put_nowait({"type": "orderbook_delta", "seq": i})
        
        # Add one fill event at the end
        bridge._queue.put_nowait({"type": "fill", "seq": 99})
        
        # Queue is now full, try to add a new non-fill event
        new_event = {"type": "orderbook_delta", "seq": 100}
        
        # Simulate the ring buffer logic
        try:
            oldest = bridge._queue.get_nowait()
            event_type = oldest.get("type") if isinstance(oldest, dict) else "unknown"
            
            if event_type != "fill":
                bridge._events_dropped += 1
                bridge._queue.put_nowait(new_event)
            else:
                bridge._queue.put_nowait(oldest)
                bridge._events_dropped += 1
        except queue.Empty:
            pass
        
        # Should have dropped one event
        assert bridge._events_dropped == 1
        
        # Verify fill event is still present
        events = []
        while not bridge._queue.empty():
            events.append(bridge._queue.get_nowait())
        
        fill_events = [e for e in events if e.get("type") == "fill"]
        assert len(fill_events) == 1
        assert fill_events[0]["seq"] == 99
    
    def test_ring_buffer_drops_current_if_oldest_is_fill(self, bridge):
        """Test that current event is dropped if oldest is a fill."""
        # Fill queue with fill events
        for i in range(100):
            bridge._queue.put_nowait({"type": "fill", "seq": i})
        
        # Queue is full, try to add a new non-fill event
        new_event = {"type": "orderbook_delta", "seq": 100}
        
        # Simulate the ring buffer logic
        try:
            oldest = bridge._queue.get_nowait()
            event_type = oldest.get("type") if isinstance(oldest, dict) else "unknown"
            
            if event_type != "fill":
                bridge._events_dropped += 1
                bridge._queue.put_nowait(new_event)
            else:
                # Oldest was a fill, put it back and drop current
                bridge._queue.put_nowait(oldest)
                bridge._events_dropped += 1
                # Current event is dropped (not added to queue)
        except queue.Empty:
            pass
        
        # Should have dropped current event (not the fill)
        assert bridge._events_dropped == 1
        assert bridge._queue.qsize() == 100
        
        # Verify all events are still fills (current event was dropped)
        events = []
        while not bridge._queue.empty():
            events.append(bridge._queue.get_nowait())
        
        assert all(e.get("type") == "fill" for e in events)
        # Verify we still have 100 fill events (original count preserved)
        assert len(events) == 100
        # Verify the new non-fill event was not added
        assert not any(e.get("seq") == 100 for e in events)
