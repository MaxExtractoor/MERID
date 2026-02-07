"""Tests for core infrastructure - Batch 9 Coverage (streaming_bus, error_handling)."""
import pytest
import time

from core.streaming_bus import EventChannel, StreamEvent, StreamingBus, get_event_bus
from core.error_handling import (
    ErrorSeverity,
    RecoveryStrategy,
    ErrorContext,
    CircuitBreakerState,
    CircuitBreaker
)


class TestEventChannel:
    """Tests for EventChannel enum."""

    def test_all_channels_exist(self):
        """Test all event channels are defined."""
        assert EventChannel.MARKET_DATA.value == "market_data"
        assert EventChannel.NEWS.value == "news"
        assert EventChannel.SOCIAL.value == "social"
        assert EventChannel.ONCHAIN.value == "onchain"
        assert EventChannel.AGENT_OUTPUT.value == "agent_output"
        assert EventChannel.CONSENSUS.value == "consensus"
        assert EventChannel.EXECUTION.value == "execution"
        assert EventChannel.SIMULATION.value == "simulation"
        assert EventChannel.SYSTEM.value == "system"
        assert EventChannel.AUDIT.value == "audit"


class TestStreamEvent:
    """Tests for StreamEvent dataclass."""

    def test_event_creation(self):
        """Test creating a stream event."""
        event = StreamEvent(
            channel=EventChannel.MARKET_DATA,
            event_type="price_update",
            data={"symbol": "AAPL", "price": 150.0},
            source="test_source"
        )
        assert event.channel == EventChannel.MARKET_DATA
        assert event.event_type == "price_update"
        assert event.data["symbol"] == "AAPL"
        assert event.source == "test_source"
        assert event.timestamp > 0

    def test_event_to_dict(self):
        """Test StreamEvent serialization."""
        event = StreamEvent(
            channel=EventChannel.EXECUTION,
            event_type="order_filled",
            data={"order_id": "123", "status": "filled"},
            source="executor"
        )
        d = event.to_dict()
        assert d["channel"] == "execution"
        assert d["event_type"] == "order_filled"
        assert d["data"]["order_id"] == "123"
        assert d["source"] == "executor"
        assert "timestamp" in d

    def test_default_timestamp(self):
        """Test timestamp is auto-generated."""
        before = time.time()
        event = StreamEvent(
            channel=EventChannel.SYSTEM,
            event_type="startup",
            data={}
        )
        after = time.time()
        assert before <= event.timestamp <= after

    def test_default_source(self):
        """Test default source is 'unknown'."""
        event = StreamEvent(
            channel=EventChannel.NEWS,
            event_type="article",
            data={"title": "Test"}
        )
        assert event.source == "unknown"


class TestStreamingBusBasic:
    """Basic tests for StreamingBus."""

    def test_bus_initialization(self):
        """Test bus initialization."""
        bus = StreamingBus(max_queue_size=100)
        assert bus.max_queue_size == 100
        assert bus._dropped_events == 0

    def test_get_event_bus(self):
        """Test getting global event bus."""
        bus = get_event_bus()
        assert bus is not None
        assert isinstance(bus, StreamingBus)

    def test_get_metrics_empty(self):
        """Test metrics on fresh bus."""
        bus = StreamingBus()
        metrics = bus.get_metrics()
        assert metrics["total_subscribers"] == 0
        assert metrics["global_subscribers"] == 0
        assert metrics["dropped_events"] == 0
        assert len(metrics["event_counts"]) == len(EventChannel)

    def test_get_subscriber_count_empty(self):
        """Test subscriber count on fresh bus."""
        bus = StreamingBus()
        assert bus.get_subscriber_count() == 0
        assert bus.get_subscriber_count(EventChannel.MARKET_DATA) == 0


class TestErrorSeverity:
    """Tests for ErrorSeverity enum."""

    def test_all_severities_exist(self):
        """Test all severity levels are defined."""
        assert ErrorSeverity.LOW.value == "low"
        assert ErrorSeverity.MEDIUM.value == "medium"
        assert ErrorSeverity.HIGH.value == "high"
        assert ErrorSeverity.CRITICAL.value == "critical"


class TestRecoveryStrategy:
    """Tests for RecoveryStrategy enum."""

    def test_all_strategies_exist(self):
        """Test all recovery strategies are defined."""
        assert RecoveryStrategy.RETRY.value == "retry"
        assert RecoveryStrategy.FALLBACK.value == "fallback"
        assert RecoveryStrategy.CIRCUIT_BREAK.value == "circuit_break"
        assert RecoveryStrategy.ESCALATE.value == "escalate"
        assert RecoveryStrategy.IGNORE.value == "ignore"


class TestErrorContext:
    """Tests for ErrorContext dataclass."""

    def test_context_creation(self):
        """Test creating error context."""
        context = ErrorContext(
            error_id="err_123",
            timestamp=time.time(),
            component="trading",
            operation="execute_trade",
            error_type="ValueError",
            error_message="Invalid price",
            severity=ErrorSeverity.MEDIUM,
            stack_trace="Traceback..."
        )
        assert context.error_id == "err_123"
        assert context.component == "trading"
        assert context.operation == "execute_trade"
        assert context.error_type == "ValueError"
        assert context.severity == ErrorSeverity.MEDIUM
        assert context.recovery_attempted is False
        assert context.recovery_successful is False
        assert context.recovery_strategy is None

    def test_context_with_defaults(self):
        """Test context with default values."""
        context = ErrorContext(
            error_id="err_456",
            timestamp=time.time(),
            component="execution",
            operation="place_order",
            error_type="ConnectionError",
            error_message="Network timeout",
            severity=ErrorSeverity.HIGH,
            stack_trace="Traceback..."
        )
        assert context.metadata == {}
        assert context.recovery_attempted is False

    def test_context_with_metadata(self):
        """Test context with metadata."""
        context = ErrorContext(
            error_id="err_789",
            timestamp=time.time(),
            component="validation",
            operation="check_order",
            error_type="ValidationError",
            error_message="Invalid quantity",
            severity=ErrorSeverity.LOW,
            stack_trace="Traceback...",
            metadata={"order_id": "order_123", "symbol": "AAPL"}
        )
        assert context.metadata["order_id"] == "order_123"
        assert context.metadata["symbol"] == "AAPL"


class TestCircuitBreakerState:
    """Tests for CircuitBreakerState dataclass."""

    def test_initial_state(self):
        """Test initial circuit state."""
        state = CircuitBreakerState()
        assert state.failure_count == 0
        assert state.success_count == 0
        assert state.state == "closed"
        assert state.last_failure_time is None
        assert state.last_success_time is None
        assert state.open_until is None

    def test_state_with_failures(self):
        """Test state after failures."""
        now = time.time()
        state = CircuitBreakerState(
            failure_count=5,
            last_failure_time=now,
            state="open",
            open_until=now + 60
        )
        assert state.failure_count == 5
        assert state.state == "open"
        assert state.last_failure_time == now

    def test_state_with_success(self):
        """Test state with success tracking."""
        now = time.time()
        state = CircuitBreakerState(
            success_count=3,
            last_success_time=now,
            state="half_open"
        )
        assert state.success_count == 3
        assert state.state == "half_open"
        assert state.last_success_time == now


class TestCircuitBreaker:
    """Tests for CircuitBreaker class."""

    def test_initialization_defaults(self):
        """Test breaker with default parameters."""
        breaker = CircuitBreaker(name="test_breaker")
        assert breaker.name == "test_breaker"
        assert breaker.failure_threshold == 5
        assert breaker.success_threshold == 2
        assert breaker.timeout == 60.0
        assert breaker.state.state == "closed"

    def test_initialization_custom(self):
        """Test breaker with custom parameters."""
        breaker = CircuitBreaker(
            name="custom_breaker",
            failure_threshold=3,
            success_threshold=1,
            timeout=30.0,
            half_open_timeout=15.0
        )
        assert breaker.name == "custom_breaker"
        assert breaker.failure_threshold == 3
        assert breaker.success_threshold == 1
        assert breaker.timeout == 30.0
        assert breaker.half_open_timeout == 15.0

    def test_state_property(self):
        """Test accessing state property."""
        breaker = CircuitBreaker(name="test")
        assert isinstance(breaker.state, CircuitBreakerState)
        assert breaker.state.failure_count == 0
