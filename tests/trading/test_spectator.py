"""Tests for trading/spectator.py."""
import pytest
import time
import threading
from dataclasses import dataclass
from trading.spectator import SpectatorLog, get_spectator_log


@dataclass
class TestEvent:
    """Test dataclass for serialization."""
    name: str
    value: int


class TestSpectatorLog:
    """Test SpectatorLog class."""

    def test_initialization(self):
        """Test SpectatorLog initialization."""
        log = SpectatorLog(max_events=100)
        assert log.get_recent(limit=10) == []

    def test_ingest_event_dict(self):
        """Test ingesting dict event."""
        log = SpectatorLog()
        log.ingest_event("test", {"key": "value"})
        events = log.get_recent(limit=1)
        assert len(events) == 1
        assert events[0]["event_type"] == "test"
        assert events[0]["payload"] == {"key": "value"}

    def test_ingest_event_primitive(self):
        """Test ingesting primitive event."""
        log = SpectatorLog()
        log.ingest_event("number", 42)
        events = log.get_recent(limit=1)
        assert events[0]["payload"] == 42

    def test_ingest_event_dataclass(self):
        """Test ingesting dataclass event."""
        log = SpectatorLog()
        event = TestEvent(name="test", value=123)
        log.ingest_event("dataclass", event)
        events = log.get_recent(limit=1)
        assert events[0]["payload"] == {"name": "test", "value": 123}

    def test_get_recent_limit(self):
        """Test get_recent respects limit."""
        log = SpectatorLog()
        for i in range(10):
            log.ingest_event("event", i)
        events = log.get_recent(limit=5)
        assert len(events) == 5

    def test_max_events_respected(self):
        """Test max_events limit is respected."""
        log = SpectatorLog(max_events=5)
        for i in range(10):
            log.ingest_event("event", i)
        all_events = log.dump_all()
        assert len(all_events) == 5

    def test_thread_safety(self):
        """Test thread-safe ingestion."""
        log = SpectatorLog()
        errors = []
        
        def ingest():
            try:
                for i in range(100):
                    log.ingest_event("thread_event", i)
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=ingest) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        assert len(log.dump_all()) == 500

    def test_serialize_none(self):
        """Test _serialize with None."""
        result = SpectatorLog._serialize(None)
        assert result is None

    def test_serialize_list(self):
        """Test _serialize with list."""
        result = SpectatorLog._serialize([1, 2, 3])
        assert result == [1, 2, 3]

    def test_serialize_object_with_dict(self):
        """Test _serialize with object having dict method."""
        class FakeModel:
            def dict(self):
                return {"model": "data"}
        result = SpectatorLog._serialize(FakeModel())
        assert result == {"model": "data"}

    def test_serialize_fallback(self):
        """Test _serialize fallback to repr."""
        class Unserializable:
            pass
        result = SpectatorLog._serialize(Unserializable())
        assert "Unserializable" in result


class TestGetSpectatorLog:
    """Test get_spectator_log function."""

    def test_singleton(self):
        """Test get_spectator_log returns singleton."""
        log1 = get_spectator_log()
        log2 = get_spectator_log()
        assert log1 is log2
