"""Tests for streams/base_stream.py."""
import pytest
import asyncio
import time
from unittest.mock import Mock, patch, AsyncMock
from streams.base_stream import (
    StreamState, BackpressurePolicy, StreamError, ConnectionError, BackpressureError,
    StreamConfig, StreamHealth, BaseStream, StreamRegistry, get_stream_registry, _stream_registry
)


class TestStreamState:
    """Test StreamState enum."""

    def test_state_values(self):
        """Test stream state enum values."""
        assert StreamState.INITIALIZING.value == "initializing"
        assert StreamState.CONNECTING.value == "connecting"
        assert StreamState.CONNECTED.value == "connected"
        assert StreamState.STREAMING.value == "streaming"
        assert StreamState.PAUSED.value == "paused"
        assert StreamState.RECONNECTING.value == "reconnecting"
        assert StreamState.BACKPRESSURE.value == "backpressure"
        assert StreamState.ERROR.value == "error"
        assert StreamState.STOPPED.value == "stopped"


class TestBackpressurePolicy:
    """Test BackpressurePolicy enum."""

    def test_policy_values(self):
        """Test backpressure policy enum values."""
        assert BackpressurePolicy.DROP_OLDEST.value == "drop_oldest"
        assert BackpressurePolicy.DROP_NEWEST.value == "drop_newest"
        assert BackpressurePolicy.BLOCK.value == "block"
        assert BackpressurePolicy.RAISE.value == "raise"


class TestStreamErrors:
    """Test stream exception classes."""

    def test_stream_error(self):
        """Test StreamError exception."""
        error = StreamError("stream_123", "Test error")
        assert error.stream_id == "stream_123"
        assert error.message == "Test error"
        assert str(error) == "[stream_123] Test error"

    def test_connection_error(self):
        """Test ConnectionError exception."""
        error = ConnectionError("stream_123", "Connection failed")
        assert error.stream_id == "stream_123"
        assert isinstance(error, StreamError)

    def test_backpressure_error(self):
        """Test BackpressureError exception."""
        error = BackpressureError("stream_123", "Buffer full")
        assert error.stream_id == "stream_123"
        assert isinstance(error, StreamError)


class TestStreamConfig:
    """Test StreamConfig dataclass."""

    def test_default_values(self):
        """Test default config values."""
        config = StreamConfig()
        assert config.buffer_size == 1000
        assert config.backpressure_policy == BackpressurePolicy.DROP_OLDEST
        assert config.reconnect_attempts == 5
        assert config.reconnect_delay_seconds == 1.0
        assert config.heartbeat_interval_seconds == 10.0
        assert config.dedup_enabled is True

    def test_custom_values(self):
        """Test custom config values."""
        config = StreamConfig(
            buffer_size=500,
            backpressure_policy=BackpressurePolicy.BLOCK,
            reconnect_attempts=3
        )
        assert config.buffer_size == 500
        assert config.backpressure_policy == BackpressurePolicy.BLOCK
        assert config.reconnect_attempts == 3


class TestStreamHealth:
    """Test StreamHealth dataclass."""

    def test_creation(self):
        """Test StreamHealth creation."""
        health = StreamHealth(
            stream_id="stream_123",
            stream_type="market",
            state=StreamState.STREAMING,
            last_heartbeat=time.time(),
            last_event_at=time.time(),
            uptime_seconds=60.0,
            events_emitted=100,
            events_dropped=5,
            events_deduplicated=10,
            errors_count=0,
            buffer_size=1000,
            buffer_used=100,
            buffer_utilization=0.1,
            reconnect_count=0,
            last_error=None
        )
        assert health.stream_id == "stream_123"
        assert health.is_healthy() is True

    def test_is_healthy_error_state(self):
        """Test is_healthy returns False in error state."""
        health = StreamHealth(
            stream_id="stream_123",
            stream_type="market",
            state=StreamState.ERROR,
            last_heartbeat=time.time(),
            last_event_at=None,
            uptime_seconds=0.0,
            events_emitted=0,
            events_dropped=0,
            events_deduplicated=0,
            errors_count=1,
            buffer_size=1000,
            buffer_used=0,
            buffer_utilization=0.0,
            reconnect_count=0,
            last_error="Test error"
        )
        assert health.is_healthy() is False

    def test_is_healthy_stale_heartbeat(self):
        """Test is_healthy returns False with stale heartbeat."""
        health = StreamHealth(
            stream_id="stream_123",
            stream_type="market",
            state=StreamState.STREAMING,
            last_heartbeat=time.time() - 120.0,  # 2 minutes ago
            last_event_at=None,
            uptime_seconds=0.0,
            events_emitted=0,
            events_dropped=0,
            events_deduplicated=0,
            errors_count=0,
            buffer_size=1000,
            buffer_used=0,
            buffer_utilization=0.0,
            reconnect_count=0,
            last_error=None
        )
        assert health.is_healthy() is False

    def test_to_dict(self):
        """Test to_dict serialization."""
        health = StreamHealth(
            stream_id="stream_123",
            stream_type="market",
            state=StreamState.STREAMING,
            last_heartbeat=1234567890.0,
            last_event_at=1234567890.0,
            uptime_seconds=60.0,
            events_emitted=100,
            events_dropped=5,
            events_deduplicated=10,
            errors_count=0,
            buffer_size=1000,
            buffer_used=100,
            buffer_utilization=0.1,
            reconnect_count=0,
            last_error=None
        )
        d = health.to_dict()
        assert d["stream_id"] == "stream_123"
        assert d["state"] == "streaming"
        assert "is_healthy" in d


class TestBaseStream:
    """Test BaseStream abstract class."""

    def test_initialization(self):
        """Test stream initialization."""
        # Create a concrete implementation
        class TestStream(BaseStream):
            @property
            def stream_type(self) -> str:
                return "test"
            async def _connect(self) -> None:
                pass
            async def _disconnect(self) -> None:
                pass
            async def _fetch_data(self):
                return None
            def _transform_to_events(self, data):
                return []

        stream = TestStream("test_stream")
        assert stream.stream_id == "test_stream"
        assert stream.state == StreamState.INITIALIZING
        assert stream.is_running is False

    def test_initialization_empty_id(self):
        """Test stream initialization with empty ID raises error."""
        class TestStream(BaseStream):
            @property
            def stream_type(self) -> str:
                return "test"
            async def _connect(self) -> None:
                pass
            async def _disconnect(self) -> None:
                pass
            async def _fetch_data(self):
                return None
            def _transform_to_events(self, data):
                return []

        with pytest.raises(ValueError, match="stream_id cannot be empty"):
            TestStream("")

    def test_get_health(self):
        """Test get_health method."""
        class TestStream(BaseStream):
            @property
            def stream_type(self) -> str:
                return "test"
            async def _connect(self) -> None:
                pass
            async def _disconnect(self) -> None:
                pass
            async def _fetch_data(self):
                return None
            def _transform_to_events(self, data):
                return []

        stream = TestStream("test_stream")
        health = stream.get_health()
        assert health.stream_id == "test_stream"
        assert health.stream_type == "test"
        assert health.state == StreamState.INITIALIZING

    def test_subscribe_unsubscribe(self):
        """Test subscribe and unsubscribe methods."""
        class TestStream(BaseStream):
            @property
            def stream_type(self) -> str:
                return "test"
            async def _connect(self) -> None:
                pass
            async def _disconnect(self) -> None:
                pass
            async def _fetch_data(self):
                return None
            def _transform_to_events(self, data):
                return []

        stream = TestStream("test_stream")
        
        def callback(event):
            pass
        
        stream.subscribe(callback)
        assert callback in stream._subscribers
        
        stream.unsubscribe(callback)
        assert callback not in stream._subscribers


class TestStreamRegistry:
    """Test StreamRegistry class."""

    def test_initialization(self):
        """Test registry initialization."""
        registry = StreamRegistry()
        assert registry._streams == {}

    def test_register_stream(self):
        """Test registering a stream."""
        class TestStream(BaseStream):
            @property
            def stream_type(self) -> str:
                return "test"
            async def _connect(self) -> None:
                pass
            async def _disconnect(self) -> None:
                pass
            async def _fetch_data(self):
                return None
            def _transform_to_events(self, data):
                return []

        registry = StreamRegistry()
        stream = TestStream("test_stream")
        registry.register(stream)
        
        assert "test_stream" in registry._streams
        assert registry._streams["test_stream"] == stream

    def test_register_duplicate(self):
        """Test registering duplicate stream raises error."""
        class TestStream(BaseStream):
            @property
            def stream_type(self) -> str:
                return "test"
            async def _connect(self) -> None:
                pass
            async def _disconnect(self) -> None:
                pass
            async def _fetch_data(self):
                return None
            def _transform_to_events(self, data):
                return []

        registry = StreamRegistry()
        stream = TestStream("test_stream")
        registry.register(stream)
        
        with pytest.raises(ValueError, match="Stream test_stream already registered"):
            registry.register(stream)

    def test_unregister_stream(self):
        """Test unregistering a stream."""
        class TestStream(BaseStream):
            @property
            def stream_type(self) -> str:
                return "test"
            async def _connect(self) -> None:
                pass
            async def _disconnect(self) -> None:
                pass
            async def _fetch_data(self):
                return None
            def _transform_to_events(self, data):
                return []

        registry = StreamRegistry()
        stream = TestStream("test_stream")
        registry.register(stream)
        
        unregistered = registry.unregister("test_stream")
        assert unregistered == stream
        assert "test_stream" not in registry._streams

    def test_get_stream(self):
        """Test getting a stream by ID."""
        class TestStream(BaseStream):
            @property
            def stream_type(self) -> str:
                return "test"
            async def _connect(self) -> None:
                pass
            async def _disconnect(self) -> None:
                pass
            async def _fetch_data(self):
                return None
            def _transform_to_events(self, data):
                return []

        registry = StreamRegistry()
        stream = TestStream("test_stream")
        registry.register(stream)
        
        retrieved = registry.get("test_stream")
        assert retrieved == stream
        
        # Non-existent stream
        assert registry.get("non_existent") is None

    def test_get_all_streams(self):
        """Test getting all registered streams."""
        class TestStream(BaseStream):
            @property
            def stream_type(self) -> str:
                return "test"
            async def _connect(self) -> None:
                pass
            async def _disconnect(self) -> None:
                pass
            async def _fetch_data(self):
                return None
            def _transform_to_events(self, data):
                return []

        registry = StreamRegistry()
        stream1 = TestStream("stream1")
        stream2 = TestStream("stream2")
        registry.register(stream1)
        registry.register(stream2)
        
        all_streams = registry.get_all()
        assert len(all_streams) == 2
        assert stream1 in all_streams
        assert stream2 in all_streams

    def test_get_health_report(self):
        """Test getting health report for all streams."""
        class TestStream(BaseStream):
            @property
            def stream_type(self) -> str:
                return "test"
            async def _connect(self) -> None:
                pass
            async def _disconnect(self) -> None:
                pass
            async def _fetch_data(self):
                return None
            def _transform_to_events(self, data):
                return []

        registry = StreamRegistry()
        stream = TestStream("test_stream")
        registry.register(stream)
        
        health_report = registry.get_health_report()
        assert "test_stream" in health_report
        assert health_report["test_stream"].stream_id == "test_stream"


class TestGetStreamRegistry:
    """Test get_stream_registry function."""

    def setup_method(self):
        """Reset singleton before each test."""
        global _stream_registry
        import streams.base_stream as bs
        bs._stream_registry = None

    def test_singleton(self):
        """Test get_stream_registry returns singleton."""
        registry1 = get_stream_registry()
        registry2 = get_stream_registry()
        assert registry1 is registry2
