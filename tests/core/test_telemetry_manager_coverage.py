"""Comprehensive tests for core/telemetry_manager.py - Coverage improvement."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from core.telemetry_manager import (
    DataClassification, RetentionTier, TelemetryConfig, StructuredLog,
    MetricPoint, TraceSpan, TelemetryManager, get_telemetry_manager
)


# =============================================================================
# Enum Tests
# =============================================================================

class TestDataClassification:
    """Test DataClassification enum."""

    def test_public(self):
        assert DataClassification.PUBLIC.value == "public"

    def test_internal(self):
        assert DataClassification.INTERNAL.value == "internal"

    def test_sensitive(self):
        assert DataClassification.SENSITIVE.value == "sensitive"

    def test_secret(self):
        assert DataClassification.SECRET.value == "secret"


class TestRetentionTier:
    """Test RetentionTier enum."""

    def test_hot(self):
        assert RetentionTier.HOT.value == "hot"

    def test_warm(self):
        assert RetentionTier.WARM.value == "warm"

    def test_cold(self):
        assert RetentionTier.COLD.value == "cold"

    def test_archive(self):
        assert RetentionTier.ARCHIVE.value == "archive"


# =============================================================================
# Dataclass Tests
# =============================================================================

class TestTelemetryConfig:
    """Test TelemetryConfig dataclass."""

    def test_creation(self):
        config = TelemetryConfig(
            stream_name="test",
            classification=DataClassification.INTERNAL,
            retention_tier=RetentionTier.HOT
        )
        assert config.stream_name == "test"
        assert config.sampling_rate == 1.0


class TestStructuredLog:
    """Test StructuredLog dataclass."""

    def test_creation(self):
        log = StructuredLog(
            timestamp=datetime.utcnow(),
            level="INFO",
            agent_id="agent_1",
            strategy_id=None,
            venue=None,
            correlation_id="corr_1",
            trace_id="trace_1",
            event_type="test_event",
            message="Test message",
            fields={},
            classification=DataClassification.INTERNAL
        )
        assert log.level == "INFO"


class TestMetricPoint:
    """Test MetricPoint dataclass."""

    def test_creation(self):
        metric = MetricPoint(
            timestamp=datetime.utcnow(),
            metric_name="latency_ms",
            value=50.0,
            tags={"venue": "alpaca"},
            classification=DataClassification.PUBLIC
        )
        assert metric.value == 50.0


class TestTraceSpan:
    """Test TraceSpan dataclass."""

    def test_creation(self):
        span = TraceSpan(
            trace_id="trace_1",
            span_id="span_1",
            parent_span_id=None,
            operation_name="execute_trade",
            start_time=datetime.utcnow(),
            end_time=None,
            duration_ms=None,
            tags={},
            logs=[],
            classification=DataClassification.SENSITIVE
        )
        assert span.operation_name == "execute_trade"


# =============================================================================
# TelemetryManager Tests
# =============================================================================

@pytest.fixture
def manager():
    """Create TelemetryManager."""
    return TelemetryManager()


@pytest.fixture
def configured_manager(manager):
    """Create TelemetryManager with registered stream."""
    config = TelemetryConfig(
        stream_name="test_stream",
        classification=DataClassification.INTERNAL,
        retention_tier=RetentionTier.HOT,
        sampling_rate=1.0,
        mask_fields={"secret_field"}
    )
    manager.register_stream(config)
    return manager


class TestTelemetryManagerInit:
    """Test TelemetryManager initialization."""

    def test_init(self, manager):
        assert manager._configs == {}
        assert manager._logs == []


class TestRegisterStream:
    """Test register_stream method."""

    def test_registers_stream(self, manager):
        config = TelemetryConfig(
            stream_name="execution",
            classification=DataClassification.SENSITIVE,
            retention_tier=RetentionTier.HOT
        )
        manager.register_stream(config)
        assert "execution" in manager._configs


class TestLogStructured:
    """Test log_structured method."""

    def test_basic_log(self, configured_manager):
        log = configured_manager.log_structured(
            stream_name="test_stream",
            level="INFO",
            event_type="test_event",
            message="Test message",
            fields={"key": "value"}
        )
        assert log is not None
        assert log.message == "Test message"

    def test_forbidden_key_raises(self, configured_manager):
        with pytest.raises(ValueError, match="Forbidden key"):
            configured_manager.log_structured(
                stream_name="test_stream",
                level="INFO",
                event_type="test",
                message="Test",
                fields={"api_key": "secret123"}
            )

    def test_unregistered_stream_raises(self, manager):
        with pytest.raises(ValueError, match="not registered"):
            manager.log_structured(
                stream_name="unknown",
                level="INFO",
                event_type="test",
                message="Test",
                fields={}
            )

    def test_masks_pii_fields(self, configured_manager):
        log = configured_manager.log_structured(
            stream_name="test_stream",
            level="INFO",
            event_type="test",
            message="Test",
            fields={"secret_field": "sensitive_data"}
        )
        assert log.fields["secret_field"] != "sensitive_data"


class TestRecordMetric:
    """Test record_metric method."""

    def test_basic_metric(self, configured_manager):
        metric = configured_manager.record_metric(
            stream_name="test_stream",
            metric_name="latency",
            value=100.0
        )
        assert metric is not None
        assert metric.value == 100.0

    def test_unregistered_stream_raises(self, manager):
        with pytest.raises(ValueError, match="not registered"):
            manager.record_metric(
                stream_name="unknown",
                metric_name="test",
                value=1.0
            )


class TestTraceSpans:
    """Test trace span methods."""

    def test_start_trace_span(self, configured_manager):
        span = configured_manager.start_trace_span(
            stream_name="test_stream",
            operation_name="execute"
        )
        assert span is not None
        assert span.operation_name == "execute"

    def test_end_trace_span(self, configured_manager):
        span = configured_manager.start_trace_span(
            stream_name="test_stream",
            operation_name="execute"
        )
        configured_manager.end_trace_span(span)
        assert span.end_time is not None
        assert span.duration_ms is not None

    def test_add_span_log(self, configured_manager):
        span = configured_manager.start_trace_span(
            stream_name="test_stream",
            operation_name="execute"
        )
        configured_manager.add_span_log(span, {"event": "started"})
        assert len(span.logs) == 1


class TestGetLogs:
    """Test get_logs method."""

    def test_get_all_logs(self, configured_manager):
        configured_manager.log_structured(
            stream_name="test_stream",
            level="INFO",
            event_type="test",
            message="Test 1",
            fields={}
        )
        logs = configured_manager.get_logs()
        assert len(logs) >= 1

    def test_filter_by_level(self, configured_manager):
        configured_manager.log_structured(
            stream_name="test_stream",
            level="ERROR",
            event_type="test",
            message="Error",
            fields={}
        )
        logs = configured_manager.get_logs(level="ERROR")
        assert all(log.level == "ERROR" for log in logs)


class TestGetMetrics:
    """Test get_metrics method."""

    def test_get_all_metrics(self, configured_manager):
        configured_manager.record_metric(
            stream_name="test_stream",
            metric_name="latency",
            value=50.0
        )
        metrics = configured_manager.get_metrics()
        assert len(metrics) >= 1


class TestGetTrace:
    """Test get_trace method."""

    def test_get_trace(self, configured_manager):
        span = configured_manager.start_trace_span(
            stream_name="test_stream",
            operation_name="test"
        )
        spans = configured_manager.get_trace(span.trace_id)
        assert len(spans) == 1


class TestGetTelemetryStats:
    """Test get_telemetry_stats method."""

    def test_stats(self, configured_manager):
        stats = configured_manager.get_telemetry_stats()
        assert "total_logs" in stats
        assert "streams" in stats


class TestCleanupExpired:
    """Test cleanup_expired method."""

    def test_cleanup(self, configured_manager):
        result = configured_manager.cleanup_expired()
        assert "logs" in result
        assert "metrics" in result
        assert "traces" in result


# =============================================================================
# Singleton Tests
# =============================================================================

class TestGetTelemetryManager:
    """Test get_telemetry_manager singleton."""

    def test_returns_manager(self):
        import core.telemetry_manager as module
        module._telemetry_manager = None
        
        manager = get_telemetry_manager()
        assert isinstance(manager, TelemetryManager)
