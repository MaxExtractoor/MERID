"""Tests for telemetry manager - Batch 17 Coverage."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from core.telemetry_manager import (
    DataClassification,
    RetentionTier,
    TelemetryConfig,
    StructuredLog,
    MetricPoint,
    TraceSpan,
    TelemetryManager,
    get_telemetry_manager
)


class TestDataClassification:
    """Tests for DataClassification enum."""

    def test_classification_values(self):
        assert DataClassification.PUBLIC.value == "public"
        assert DataClassification.INTERNAL.value == "internal"
        assert DataClassification.SENSITIVE.value == "sensitive"
        assert DataClassification.SECRET.value == "secret"


class TestRetentionTier:
    """Tests for RetentionTier enum."""

    def test_retention_tier_values(self):
        assert RetentionTier.HOT.value == "hot"
        assert RetentionTier.WARM.value == "warm"
        assert RetentionTier.COLD.value == "cold"
        assert RetentionTier.ARCHIVE.value == "archive"


class TestTelemetryConfig:
    """Tests for TelemetryConfig dataclass."""

    def test_config_creation(self):
        config = TelemetryConfig(
            stream_name="test_stream",
            classification=DataClassification.INTERNAL,
            retention_tier=RetentionTier.HOT,
            sampling_rate=0.5,
            retention_days=30
        )
        assert config.stream_name == "test_stream"
        assert config.sampling_rate == 0.5
        assert config.retention_days == 30

    def test_config_defaults(self):
        config = TelemetryConfig(
            stream_name="test",
            classification=DataClassification.PUBLIC,
            retention_tier=RetentionTier.WARM
        )
        assert config.sampling_rate == 1.0
        assert config.retention_days == 30
        assert config.pii_fields == set()


class TestTelemetryManager:
    """Tests for TelemetryManager."""

    @pytest.fixture
    def manager(self):
        """Create fresh telemetry manager."""
        return TelemetryManager()

    def test_initialization(self, manager):
        """Test manager initialization."""
        assert len(manager._configs) == 0
        assert len(manager._logs) == 0
        assert len(manager._metrics) == 0
        assert len(manager._traces) == 0

    def test_register_stream(self, manager):
        """Test stream registration."""
        config = TelemetryConfig(
            stream_name="test_stream",
            classification=DataClassification.INTERNAL,
            retention_tier=RetentionTier.HOT
        )
        manager.register_stream(config)
        assert "test_stream" in manager._configs

    def test_check_forbidden_keys(self, manager):
        """Test forbidden key detection."""
        with pytest.raises(ValueError):
            manager._check_forbidden_keys({"password": "secret123"})
        
        with pytest.raises(ValueError):
            manager._check_forbidden_keys({"api_key": "key123"})

    def test_pseudonymize(self, manager):
        """Test PII pseudonymization."""
        pseudo1 = manager._pseudonymize("test@example.com")
        pseudo2 = manager._pseudonymize("test@example.com")
        assert pseudo1 == pseudo2  # Deterministic
        assert len(pseudo1) == 16

    def test_mask_pii(self, manager):
        """Test PII masking."""
        config = TelemetryConfig(
            stream_name="test",
            classification=DataClassification.INTERNAL,
            retention_tier=RetentionTier.HOT,
            mask_fields={"email", "phone"}
        )
        
        data = {"email": "test@example.com", "phone": "555-1234", "name": "John"}
        masked = manager._mask_pii(data, config)
        
        assert masked["email"] != "test@example.com"
        assert masked["phone"] != "555-1234"
        assert masked["name"] == "John"

    def test_should_sample_always(self, manager):
        """Test sampling with rate 1.0."""
        config = TelemetryConfig(
            stream_name="test",
            classification=DataClassification.INTERNAL,
            retention_tier=RetentionTier.HOT,
            sampling_rate=1.0
        )
        manager.register_stream(config)
        
        # Should always sample when rate is 1.0
        assert manager._should_sample("test") is True

    def test_should_sample_never(self, manager):
        """Test sampling with rate 0.0."""
        config = TelemetryConfig(
            stream_name="test",
            classification=DataClassification.INTERNAL,
            retention_tier=RetentionTier.HOT,
            sampling_rate=0.0
        )
        manager.register_stream(config)
        
        # Should never sample when rate is 0.0
        assert manager._should_sample("test") is False

    def test_log_structured(self, manager):
        """Test structured logging."""
        config = TelemetryConfig(
            stream_name="execution",
            classification=DataClassification.SENSITIVE,
            retention_tier=RetentionTier.HOT
        )
        manager.register_stream(config)
        
        log = manager.log_structured(
            stream_name="execution",
            level="INFO",
            event_type="order_placed",
            message="Order executed",
            fields={"order_id": "123", "size": 100.0}
        )
        
        assert log is not None
        assert log.event_type == "order_placed"
        assert log.level == "INFO"
        assert len(manager._logs) == 1

    def test_log_structured_unregistered_stream(self, manager):
        """Test logging to unregistered stream raises error."""
        with pytest.raises(ValueError):
            manager.log_structured(
                stream_name="unregistered",
                level="INFO",
                event_type="test",
                message="Test",
                fields={}
            )

    def test_log_structured_forbidden_keys(self, manager):
        """Test logging with forbidden keys raises error."""
        config = TelemetryConfig(
            stream_name="test",
            classification=DataClassification.INTERNAL,
            retention_tier=RetentionTier.HOT
        )
        manager.register_stream(config)
        
        with pytest.raises(ValueError):
            manager.log_structured(
                stream_name="test",
                level="INFO",
                event_type="test",
                message="Test",
                fields={"password": "secret"}
            )

    def test_record_metric(self, manager):
        """Test metric recording."""
        config = TelemetryConfig(
            stream_name="metrics",
            classification=DataClassification.INTERNAL,
            retention_tier=RetentionTier.HOT
        )
        manager.register_stream(config)
        
        metric = manager.record_metric(
            stream_name="metrics",
            metric_name="latency_ms",
            value=150.5,
            tags={"venue": "binance"},
            unit="ms"
        )
        
        assert metric is not None
        assert metric.metric_name == "latency_ms"
        assert metric.value == 150.5
        assert len(manager._metrics) == 1

    def test_start_trace_span(self, manager):
        """Test starting trace span."""
        config = TelemetryConfig(
            stream_name="traces",
            classification=DataClassification.INTERNAL,
            retention_tier=RetentionTier.HOT
        )
        manager.register_stream(config)
        
        span = manager.start_trace_span(
            stream_name="traces",
            operation_name="process_order"
        )
        
        assert span is not None
        assert span.operation_name == "process_order"
        assert span.trace_id is not None
        assert span.span_id is not None
        assert span.end_time is None

    def test_end_trace_span(self, manager):
        """Test ending trace span."""
        config = TelemetryConfig(
            stream_name="traces",
            classification=DataClassification.INTERNAL,
            retention_tier=RetentionTier.HOT
        )
        manager.register_stream(config)
        
        span = manager.start_trace_span(
            stream_name="traces",
            operation_name="process_order"
        )
        
        manager.end_trace_span(span)
        
        assert span.end_time is not None
        assert span.duration_ms is not None
        assert span.duration_ms >= 0

    def test_get_logs(self, manager):
        """Test log querying."""
        config = TelemetryConfig(
            stream_name="execution",
            classification=DataClassification.INTERNAL,
            retention_tier=RetentionTier.HOT
        )
        manager.register_stream(config)
        
        manager.log_structured(
            stream_name="execution",
            level="INFO",
            event_type="execution.test",
            message="Test 1",
            fields={},
            agent_id="agent_1"
        )
        
        manager.log_structured(
            stream_name="execution",
            level="ERROR",
            event_type="execution.test",
            message="Test 2",
            fields={},
            agent_id="agent_2"
        )
        
        logs = manager.get_logs(level="INFO")
        assert len(logs) == 1
        assert logs[0].level == "INFO"

    def test_get_metrics(self, manager):
        """Test metric querying."""
        config = TelemetryConfig(
            stream_name="metrics",
            classification=DataClassification.INTERNAL,
            retention_tier=RetentionTier.HOT
        )
        manager.register_stream(config)
        
        manager.record_metric(
            stream_name="metrics",
            metric_name="latency",
            value=100.0,
            tags={"venue": "binance"}
        )
        
        manager.record_metric(
            stream_name="metrics",
            metric_name="throughput",
            value=50.0,
            tags={"venue": "coinbase"}
        )
        
        metrics = manager.get_metrics(metric_name="latency")
        assert len(metrics) == 1
        assert metrics[0].metric_name == "latency"

    def test_get_trace(self, manager):
        """Test trace retrieval."""
        config = TelemetryConfig(
            stream_name="traces",
            classification=DataClassification.INTERNAL,
            retention_tier=RetentionTier.HOT
        )
        manager.register_stream(config)
        
        span = manager.start_trace_span(
            stream_name="traces",
            operation_name="test_op"
        )
        
        spans = manager.get_trace(span.trace_id)
        assert len(spans) == 1
        assert spans[0].operation_name == "test_op"

    def test_get_telemetry_stats(self, manager):
        """Test telemetry stats."""
        config = TelemetryConfig(
            stream_name="test",
            classification=DataClassification.INTERNAL,
            retention_tier=RetentionTier.HOT
        )
        manager.register_stream(config)
        
        stats = manager.get_telemetry_stats()
        assert "total_logs" in stats
        assert "total_metrics" in stats
        assert "total_traces" in stats
        assert "streams" in stats

    def test_cleanup_expired(self, manager):
        """Test cleanup of expired telemetry."""
        config = TelemetryConfig(
            stream_name="test",
            classification=DataClassification.INTERNAL,
            retention_tier=RetentionTier.HOT,
            retention_days=0  # Expire immediately
        )
        manager.register_stream(config)
        
        # Add old log
        old_log = StructuredLog(
            timestamp=datetime.utcnow() - timedelta(days=10),
            level="INFO",
            agent_id=None,
            strategy_id=None,
            venue=None,
            correlation_id="test",
            trace_id="test",
            event_type="test",
            message="Old",
            fields={},
            classification=DataClassification.INTERNAL
        )
        manager._logs.append(old_log)
        
        removed = manager.cleanup_expired()
        assert removed["logs"] == 1


class TestGetTelemetryManager:
    """Tests for singleton."""

    def test_singleton(self):
        manager1 = get_telemetry_manager()
        manager2 = get_telemetry_manager()
        assert manager1 is manager2
