"""Comprehensive tests for trading/spectator.py - Coverage improvement."""

import pytest
import time
from dataclasses import dataclass
from typing import Dict, Any

from trading.spectator import SpectatorLog, get_spectator_log


# =============================================================================
# SpectatorLog Tests
# =============================================================================

class TestSpectatorLogInit:
    """Test SpectatorLog initialization."""

    def test_init_default_max_events(self):
        log = SpectatorLog()
        assert log._events.maxlen == 500

    def test_init_custom_max_events(self):
        log = SpectatorLog(max_events=100)
        assert log._events.maxlen == 100


class TestIngestEvent:
    """Test ingest_event method."""

    def test_ingest_simple_event(self):
        log = SpectatorLog()
        log.ingest_event("trade", {"symbol": "BTC"})
        
        events = log.get_recent(1)
        assert len(events) == 1
        assert events[0]["event_type"] == "trade"
        assert events[0]["payload"]["symbol"] == "BTC"

    def test_ingest_multiple_events(self):
        log = SpectatorLog()
        log.ingest_event("trade1", {"id": 1})
        log.ingest_event("trade2", {"id": 2})
        log.ingest_event("trade3", {"id": 3})
        
        events = log.get_recent()
        assert len(events) == 3
        # Most recent first
        assert events[0]["payload"]["id"] == 3

    def test_ingest_respects_max_events(self):
        log = SpectatorLog(max_events=3)
        for i in range(5):
            log.ingest_event(f"event_{i}", {"id": i})
        
        events = log.dump_all()
        assert len(events) == 3


class TestGetRecent:
    """Test get_recent method."""

    def test_get_recent_empty(self):
        log = SpectatorLog()
        events = log.get_recent()
        assert events == []

    def test_get_recent_with_limit(self):
        log = SpectatorLog()
        for i in range(10):
            log.ingest_event(f"event_{i}", {"id": i})
        
        events = log.get_recent(limit=5)
        assert len(events) == 5

    def test_get_recent_default_limit(self):
        log = SpectatorLog()
        for i in range(300):
            log.ingest_event(f"event_{i}", {"id": i})
        
        events = log.get_recent()
        assert len(events) == 200  # Default limit


class TestDumpAll:
    """Test dump_all method."""

    def test_dump_all_empty(self):
        log = SpectatorLog()
        events = log.dump_all()
        assert events == []

    def test_dump_all_with_events(self):
        log = SpectatorLog()
        for i in range(10):
            log.ingest_event(f"event_{i}", {"id": i})
        
        events = log.dump_all()
        assert len(events) == 10


class TestSerialize:
    """Test _serialize static method."""

    def test_serialize_none(self):
        result = SpectatorLog._serialize(None)
        assert result is None

    def test_serialize_dict(self):
        data = {"key": "value"}
        result = SpectatorLog._serialize(data)
        assert result == data

    def test_serialize_string(self):
        result = SpectatorLog._serialize("hello")
        assert result == "hello"

    def test_serialize_int(self):
        result = SpectatorLog._serialize(42)
        assert result == 42

    def test_serialize_float(self):
        result = SpectatorLog._serialize(3.14)
        assert result == 3.14

    def test_serialize_bool(self):
        result = SpectatorLog._serialize(True)
        assert result is True

    def test_serialize_list(self):
        data = [1, 2, 3]
        result = SpectatorLog._serialize(data)
        assert result == data

    def test_serialize_dataclass(self):
        @dataclass
        class TestData:
            name: str
            value: int
        
        obj = TestData(name="test", value=42)
        result = SpectatorLog._serialize(obj)
        
        assert result == {"name": "test", "value": 42}

    def test_serialize_dataclass_error(self):
        # Create a mock object that looks like a dataclass but fails asdict
        from unittest.mock import patch, MagicMock
        
        @dataclass
        class BrokenData:
            name: str
        
        obj = BrokenData(name="test")
        
        with patch("trading.spectator.asdict", side_effect=Exception("Cannot convert")):
            result = SpectatorLog._serialize(obj)
        
        # Should fall back to repr
        assert "BrokenData" in str(result)

    def test_serialize_object_with_dict_method(self):
        class DictableObject:
            def dict(self):
                return {"type": "dictable", "value": 123}
        
        obj = DictableObject()
        result = SpectatorLog._serialize(obj)
        
        assert result == {"type": "dictable", "value": 123}

    def test_serialize_object_with_dict_method_error(self):
        class BrokenDictable:
            def dict(self):
                raise ValueError("Cannot serialize")
        
        obj = BrokenDictable()
        result = SpectatorLog._serialize(obj)
        
        # Should fall back to repr
        assert "BrokenDictable" in str(result)

    def test_serialize_unknown_object(self):
        class CustomObject:
            pass
        
        obj = CustomObject()
        result = SpectatorLog._serialize(obj)
        
        # Should return repr
        assert "CustomObject" in str(result)


class TestThreadSafety:
    """Test thread safety of SpectatorLog."""

    def test_concurrent_ingest(self):
        import threading
        
        log = SpectatorLog(max_events=1000)
        
        def ingest_events(start_id: int):
            for i in range(100):
                log.ingest_event("event", {"id": start_id + i})
        
        threads = [
            threading.Thread(target=ingest_events, args=(i * 100,))
            for i in range(5)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        events = log.dump_all()
        assert len(events) == 500


# =============================================================================
# Singleton Tests
# =============================================================================

class TestGetSpectatorLog:
    """Test get_spectator_log singleton."""

    def test_returns_same_instance(self):
        import trading.spectator as module
        module._spectator_log = None
        
        log1 = get_spectator_log()
        log2 = get_spectator_log()
        
        assert log1 is log2

    def test_creates_instance(self):
        import trading.spectator as module
        module._spectator_log = None
        
        log = get_spectator_log()
        
        assert isinstance(log, SpectatorLog)


# =============================================================================
# Integration Tests
# =============================================================================

class TestSpectatorIntegration:
    """Integration tests for spectator functionality."""

    def test_full_workflow(self):
        log = SpectatorLog()
        
        # Ingest various event types
        log.ingest_event("trade_intent", {"symbol": "BTC", "side": "buy"})
        log.ingest_event("trade_result", {"symbol": "BTC", "filled": True})
        log.ingest_event("error", {"message": "Connection lost"})
        
        # Verify retrieval
        events = log.get_recent(limit=10)
        assert len(events) == 3
        
        # Verify ordering (most recent first)
        assert events[0]["event_type"] == "error"
        assert events[2]["event_type"] == "trade_intent"
        
        # Verify timestamps
        for event in events:
            assert "ts" in event
            assert event["ts"] <= time.time()
