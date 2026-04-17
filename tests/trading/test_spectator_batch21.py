"""Tests for spectator module - Batch 21 Coverage."""
import pytest
from dataclasses import dataclass
from unittest.mock import patch

from trading.spectator import SpectatorLog, get_spectator_log


class TestSpectatorLog:
    """Tests for SpectatorLog."""

    @pytest.fixture
    def log(self):
        """Create fresh spectator log."""
        return SpectatorLog(max_events=100)

    def test_initialization(self, log):
        """Test log initialization."""
        assert log._events.maxlen == 100
        assert len(log._events) == 0

    def test_ingest_event(self, log):
        """Test ingesting an event."""
        log.ingest_event("test_event", {"data": "test"})
        
        assert len(log._events) == 1
        event = log._events[0]
        assert event["event_type"] == "test_event"
        assert event["payload"] == {"data": "test"}
        assert "ts" in event

    def test_ingest_event_none_payload(self, log):
        """Test ingesting event with None payload."""
        log.ingest_event("null_event", None)
        
        event = log._events[0]
        assert event["payload"] is None

    def test_ingest_event_dataclass_payload(self, log):
        """Test ingesting event with dataclass payload."""
        @dataclass
        class TestData:
            name: str
            value: int
        
        data = TestData(name="test", value=42)
        log.ingest_event("dataclass_event", data)
        
        event = log._events[0]
        assert event["payload"] == {"name": "test", "value": 42}

    def test_ingest_event_primitive_payload(self, log):
        """Test ingesting event with primitive payload."""
        log.ingest_event("string_event", "test_string")
        assert log._events[0]["payload"] == "test_string"
        
        log.ingest_event("int_event", 42)
        assert log._events[0]["payload"] == 42
        
        log.ingest_event("float_event", 3.14)
        assert log._events[0]["payload"] == 3.14
        
        log.ingest_event("bool_event", True)
        assert log._events[0]["payload"] is True

    def test_ingest_event_list_payload(self, log):
        """Test ingesting event with list payload."""
        log.ingest_event("list_event", [1, 2, 3])
        assert log._events[0]["payload"] == [1, 2, 3]

    def test_ingest_event_object_with_dict_method(self, log):
        """Test ingesting event with object that has dict() method."""
        class Dictable:
            def dict(self):
                return {"key": "value"}
        
        obj = Dictable()
        log.ingest_event("dictable_event", obj)
        assert log._events[0]["payload"] == {"key": "value"}

    def test_ingest_event_unknown_object(self, log):
        """Test ingesting event with unknown object type."""
        class Unknown:
            def __repr__(self):
                return "UnknownObject()"
        
        obj = Unknown()
        log.ingest_event("unknown_event", obj)
        assert "UnknownObject" in log._events[0]["payload"]

    def test_max_events_limit(self, log):
        """Test that max events limit is enforced."""
        for i in range(150):
            log.ingest_event("event", {"index": i})
        
        assert len(log._events) == 100  # max_events limit

    def test_get_recent(self, log):
        """Test getting recent events."""
        for i in range(10):
            log.ingest_event("event", {"index": i})
        
        recent = log.get_recent(limit=5)
        assert len(recent) == 5
        # Most recent first (index 9, 8, 7, 6, 5)
        assert recent[0]["payload"]["index"] == 9

    def test_get_recent_default_limit(self, log):
        """Test getting recent events with default limit."""
        for i in range(150):
            log.ingest_event("event", {"index": i})
        
        recent = log.get_recent()  # default limit 200, but log max is 100
        assert len(recent) == 100  # limited by max_events

    def test_dump_all(self, log):
        """Test dumping all events."""
        for i in range(5):
            log.ingest_event("event", {"index": i})
        
        all_events = log.dump_all()
        assert len(all_events) == 5

    def test_thread_safety(self, log):
        """Test thread-safe event ingestion."""
        import threading
        
        errors = []
        
        def ingest_events():
            try:
                for i in range(50):
                    log.ingest_event("thread_event", {"index": i})
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=ingest_events) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        assert len(log._events) == 100  # max limit


class TestGetSpectatorLog:
    """Tests for get_spectator_log singleton."""

    def test_singleton(self):
        """Test singleton pattern."""
        # Reset singleton for test
        import trading.spectator as spectator_module
        spectator_module._spectator_log = None
        
        log1 = get_spectator_log()
        log2 = get_spectator_log()
        
        assert log1 is log2
