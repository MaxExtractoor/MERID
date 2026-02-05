"""Tests for core/observability_manager.py - Batch B."""
import pytest
import logging
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, mock_open
from collections import deque

from core.observability_manager import (
    LogLevel, MetricType, AlertSeverity,
    LogEntry, Metric, Alert,
    ObservabilityManager, StructuredLogHandler,
    get_observability_manager, initialize_observability,
    trace, debug, info, warning, error, critical,
    increment_counter, set_gauge, record_histogram, record_timer,
    _observability_manager
)


class TestEnumsAndDataclasses:
    """Test basic enums and dataclasses."""
    
    def test_log_level_values(self):
        """Test log level enum values."""
        assert LogLevel.TRACE.value == 5
        assert LogLevel.DEBUG.value == 4
        assert LogLevel.INFO.value == 3
        assert LogLevel.WARNING.value == 2
        assert LogLevel.ERROR.value == 1
        assert LogLevel.CRITICAL.value == 0
    
    def test_metric_type_values(self):
        """Test metric type enum values."""
        assert MetricType.COUNTER.value == "counter"
        assert MetricType.GAUGE.value == "gauge"
        assert MetricType.HISTOGRAM.value == "histogram"
        assert MetricType.TIMER.value == "timer"
    
    def test_alert_severity_values(self):
        """Test alert severity enum values."""
        assert AlertSeverity.INFO.value == "info"
        assert AlertSeverity.WARNING.value == "warning"
        assert AlertSeverity.ERROR.value == "error"
        assert AlertSeverity.CRITICAL.value == "critical"
    
    def test_log_entry_creation(self):
        """Test LogEntry dataclass."""
        entry = LogEntry(
            timestamp=datetime.now(),
            level=LogLevel.INFO,
            component="test",
            message="test message",
            metadata={"key": "value"},
            trace_id="trace-123"
        )
        assert entry.component == "test"
        assert entry.message == "test message"
        assert entry.metadata == {"key": "value"}
        assert entry.trace_id == "trace-123"
    
    def test_metric_creation(self):
        """Test Metric dataclass."""
        metric = Metric(
            name="test_metric",
            value=100.0,
            metric_type=MetricType.COUNTER,
            timestamp=datetime.now(),
            labels={"env": "test"},
            unit="count"
        )
        assert metric.name == "test_metric"
        assert metric.value == 100.0
        assert metric.labels == {"env": "test"}
    
    def test_alert_creation(self):
        """Test Alert dataclass."""
        alert = Alert(
            name="test_alert",
            severity=AlertSeverity.WARNING,
            message="Test alert message",
            timestamp=datetime.now(),
            metadata={"source": "test"}
        )
        assert alert.name == "test_alert"
        assert alert.severity == AlertSeverity.WARNING
        assert alert.resolved is False


class TestObservabilityManagerInit:
    """Test ObservabilityManager initialization."""
    
    def test_default_initialization(self):
        """Test initialization with default config."""
        with patch.object(ObservabilityManager, '_setup_logging'):
            manager = ObservabilityManager()
            assert manager.config is not None
            assert "log_level" in manager.config
            manager._running = False  # Stop background threads
    
    def test_custom_config(self):
        """Test initialization with custom config."""
        config = {"log_level": "DEBUG", "custom_key": "value", "log_file": "logs/test.log"}
        with patch.object(ObservabilityManager, '_setup_logging'):
            manager = ObservabilityManager(config)
            assert manager.config["log_level"] == "DEBUG"
            assert manager.config["custom_key"] == "value"
            manager._running = False
    
    def test_default_config_method(self):
        """Test _default_config method."""
        with patch.object(ObservabilityManager, '_setup_logging'):
            manager = ObservabilityManager()
            default = manager._default_config()
            assert "log_retention_days" in default
            assert "metrics_retention_hours" in default
            assert "alert_retention_days" in default
            manager._running = False


class TestObservabilityManagerLogging:
    """Test logging methods."""
    
    @pytest.fixture
    def manager(self):
        """Create manager with disabled background threads for testing."""
        with patch.object(ObservabilityManager, '_setup_logging'):
            with patch.object(ObservabilityManager, '_metrics_collector'):
                with patch.object(ObservabilityManager, '_cleanup_old_data'):
                    m = ObservabilityManager()
                    m._running = True
                    return m
    
    def test_log_creates_entry(self, manager):
        """Test log method creates LogEntry."""
        manager.log(LogLevel.INFO, "test_component", "test message")
        
        assert len(manager.log_entries) == 1
        entry = manager.log_entries[0]
        assert entry.component == "test_component"
        assert entry.message == "test message"
        assert entry.level == LogLevel.INFO
    
    def test_log_not_running(self, manager):
        """Test log does nothing when not running."""
        manager._running = False
        manager.log(LogLevel.INFO, "test", "message")
        assert len(manager.log_entries) == 0
    
    def test_log_creates_alert_on_error(self, manager):
        """Test log creates alert for ERROR level."""
        manager.log(LogLevel.ERROR, "test", "error message")
        
        assert len(manager.alerts) == 1
        assert manager.alerts[0].severity == AlertSeverity.ERROR
    
    def test_log_creates_alert_on_critical(self, manager):
        """Test log creates alert for CRITICAL level."""
        manager.log(LogLevel.CRITICAL, "test", "critical message")
        
        assert len(manager.alerts) == 1
        assert manager.alerts[0].severity == AlertSeverity.CRITICAL
    
    def test_convenience_log_methods(self, manager):
        """Test convenience logging methods."""
        manager.trace("test", "trace message")
        assert manager.log_entries[-1].level == LogLevel.TRACE
        
        manager.debug("test", "debug message")
        assert manager.log_entries[-1].level == LogLevel.DEBUG
        
        manager.info("test", "info message")
        assert manager.log_entries[-1].level == LogLevel.INFO
        
        manager.warning("test", "warning message")
        assert manager.log_entries[-1].level == LogLevel.WARNING
        
        manager.error("test", "error message")
        assert manager.log_entries[-1].level == LogLevel.ERROR
        
        manager.critical("test", "critical message")
        assert manager.log_entries[-1].level == LogLevel.CRITICAL


class TestObservabilityManagerMetrics:
    """Test metrics methods."""
    
    @pytest.fixture
    def manager(self):
        """Create manager with disabled background threads."""
        with patch.object(ObservabilityManager, '_setup_logging'):
            with patch.object(ObservabilityManager, '_metrics_collector'):
                with patch.object(ObservabilityManager, '_cleanup_old_data'):
                    m = ObservabilityManager()
                    m._running = True
                    return m
    
    def test_increment_counter(self, manager):
        """Test counter increment."""
        manager.increment_counter("test_counter", 5.0, {"label": "value"})
        
        assert manager.counters["test_counter"] == 5.0
        assert "test_counter" in manager.metrics
    
    def test_increment_counter_disabled(self, manager):
        """Test counter increment when metrics disabled."""
        manager.config["enable_metrics"] = False
        manager.increment_counter("test", 1.0)
        assert "test" not in manager.counters
    
    def test_set_gauge(self, manager):
        """Test gauge setting."""
        manager.set_gauge("test_gauge", 100.0, {"env": "test"})
        
        assert manager.gauges["test_gauge"] == 100.0
        assert "test_gauge" in manager.metrics
    
    def test_set_gauge_disabled(self, manager):
        """Test gauge setting when metrics disabled."""
        manager.config["enable_metrics"] = False
        manager.set_gauge("test", 100.0)
        assert "test" not in manager.gauges
    
    def test_record_histogram(self, manager):
        """Test histogram recording."""
        manager.record_histogram("test_histogram", 50.0)
        manager.record_histogram("test_histogram", 75.0)
        
        assert len(manager.histograms["test_histogram"]) == 2
        assert "test_histogram" in manager.metrics
    
    def test_record_histogram_trimming(self, manager):
        """Test histogram trimming after max values."""
        # Add 1001 values
        for i in range(1001):
            manager.record_histogram("test_hist", float(i))
        
        # Should be trimmed to 1000
        assert len(manager.histograms["test_hist"]) == 1000
    
    def test_record_timer(self, manager):
        """Test timer recording."""
        manager.record_timer("test_timer", 0.5, {"endpoint": "/api"})
        
        assert len(manager.timers["test_timer"]) == 1
        assert "test_timer" in manager.metrics


class TestObservabilityManagerQueries:
    """Test query methods."""
    
    @pytest.fixture
    def manager(self):
        """Create manager with test data."""
        with patch.object(ObservabilityManager, '_setup_logging'):
            with patch.object(ObservabilityManager, '_metrics_collector'):
                with patch.object(ObservabilityManager, '_cleanup_old_data'):
                    m = ObservabilityManager()
                    m._running = True
                    
                    # Add test logs (this creates alerts for ERROR level)
                    m.log(LogLevel.INFO, "comp1", "info1")
                    m.log(LogLevel.INFO, "comp2", "info2")  # Changed from ERROR
                    m.log(LogLevel.INFO, "comp1", "info3")
                    
                    # Add test metrics
                    m.increment_counter("counter1", 1.0)
                    m.set_gauge("gauge1", 100.0)
                    
                    return m
    
    def test_get_metrics_by_name(self, manager):
        """Test getting metrics by name."""
        metrics = manager.get_metrics(name="counter1")
        assert len(metrics) == 1
        assert metrics[0].name == "counter1"
    
    def test_get_all_metrics(self, manager):
        """Test getting all metrics."""
        metrics = manager.get_metrics()
        assert len(metrics) == 2  # counter1 and gauge1
    
    def test_get_metrics_since(self, manager):
        """Test getting metrics since a time."""
        since = datetime.now() - timedelta(minutes=5)
        metrics = manager.get_metrics(since=since)
        assert len(metrics) == 2
    
    def test_get_logs_filtered_by_level(self, manager):
        """Test getting logs filtered by level."""
        # Add an ERROR level log explicitly for this test
        manager.log(LogLevel.ERROR, "test_comp", "error message")
        
        logs = manager.get_logs(level=LogLevel.ERROR)
        assert len(logs) >= 1
        assert all(l.level == LogLevel.ERROR for l in logs)
    
    def test_get_logs_filtered_by_component(self, manager):
        """Test getting logs filtered by component."""
        logs = manager.get_logs(component="comp1")
        assert len(logs) == 2
        assert all(l.component == "comp1" for l in logs)
    
    def test_get_logs_with_limit(self, manager):
        """Test getting logs with limit."""
        logs = manager.get_logs(limit=2)
        assert len(logs) == 2
    
    def test_get_alerts(self, manager):
        """Test getting alerts."""
        initial_count = len(manager.alerts)
        # Add test alerts
        manager._create_alert("alert1", AlertSeverity.WARNING, "warning message")
        manager._create_alert("alert2", AlertSeverity.ERROR, "error message")
        
        alerts = manager.get_alerts()
        assert len(alerts) == initial_count + 2
    
    def test_get_alerts_filtered_by_severity(self, manager):
        """Test getting alerts filtered by severity."""
        # Clear existing alerts and add fresh ones
        manager.alerts = []
        manager._create_alert("alert1", AlertSeverity.WARNING, "warning")
        manager._create_alert("alert2", AlertSeverity.ERROR, "error")
        
        alerts = manager.get_alerts(severity=AlertSeverity.ERROR)
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.ERROR
    
    def test_get_alerts_filtered_by_resolved(self, manager):
        """Test getting alerts filtered by resolved status."""
        # Clear and add fresh alert
        manager.alerts = []
        manager._create_alert("test_alert", AlertSeverity.WARNING, "warning")
        
        manager.resolve_alert("test_alert")
        
        alerts = manager.get_alerts(resolved=True)
        assert len(alerts) == 1
        assert alerts[0].resolved is True
    
    def test_resolve_alert(self, manager):
        """Test resolving an alert."""
        # Clear and add fresh alert
        manager.alerts = []
        manager._create_alert("test_alert", AlertSeverity.WARNING, "test")
        
        manager.resolve_alert("test_alert", resolved_by="admin")
        
        alert = manager.alerts[0]
        assert alert.resolved is True
        assert alert.resolved_at is not None
        assert alert.metadata.get("resolved_by") == "admin"


class TestObservabilityManagerCallbacks:
    """Test callback functionality."""
    
    @pytest.fixture
    def manager(self):
        """Create manager with disabled background threads."""
        with patch.object(ObservabilityManager, '_setup_logging'):
            with patch.object(ObservabilityManager, '_metrics_collector'):
                with patch.object(ObservabilityManager, '_cleanup_old_data'):
                    m = ObservabilityManager()
                    m._running = True
                    return m
    
    def test_add_alert_callback(self, manager):
        """Test adding alert callback."""
        callback_called = False
        
        def callback(alert):
            nonlocal callback_called
            callback_called = True
        
        manager.add_alert_callback(callback)
        manager._create_alert("test", AlertSeverity.WARNING, "test")
        
        assert callback_called is True
    
    def test_add_metric_callback(self, manager):
        """Test adding metric callback."""
        callback_called = False
        
        def callback(metric):
            nonlocal callback_called
            callback_called = True
        
        manager.add_metric_callback(callback)
        manager.increment_counter("test", 1.0)
        
        assert callback_called is True


class TestSystemHealth:
    """Test system health methods."""
    
    @pytest.fixture
    def manager(self):
        """Create manager with disabled background threads."""
        with patch.object(ObservabilityManager, '_setup_logging'):
            with patch.object(ObservabilityManager, '_metrics_collector'):
                with patch.object(ObservabilityManager, '_cleanup_old_data'):
                    m = ObservabilityManager()
                    m._running = True
                    return m
    
    def test_get_system_health(self, manager):
        """Test getting system health."""
        health = manager.get_system_health()
        
        assert "timestamp" in health
        assert "status" in health
        assert "error_rate" in health
        assert "log_counts" in health
        assert "alert_counts" in health
    
    def test_get_uptime(self, manager):
        """Test getting uptime."""
        # Mock file not found
        with patch('builtins.open', side_effect=FileNotFoundError):
            uptime = manager._get_uptime()
            assert uptime == "Unknown"
    
    def test_get_memory_usage(self, manager):
        """Test getting memory usage."""
        # Mock psutil not available
        with patch.dict('sys.modules', {'psutil': None}):
            memory = manager._get_memory_usage()
            assert "percent" in memory
            assert memory["percent"] == 0
    
    def test_get_disk_usage(self, manager):
        """Test getting disk usage."""
        # Mock psutil not available
        with patch.dict('sys.modules', {'psutil': None}):
            disk = manager._get_disk_usage()
            assert "percent" in disk
            assert disk["percent"] == 0


class TestStructuredLogHandler:
    """Test StructuredLogHandler."""
    
    def test_emit_creates_log_entry(self):
        """Test emit creates LogEntry."""
        with patch.object(ObservabilityManager, '_setup_logging'):
            with patch.object(ObservabilityManager, '_metrics_collector'):
                with patch.object(ObservabilityManager, '_cleanup_old_data'):
                    manager = ObservabilityManager()
                    handler = StructuredLogHandler(manager)
                    
                    record = logging.LogRecord(
                        name="test",
                        level=logging.INFO,
                        pathname="test.py",
                        lineno=1,
                        msg="test message",
                        args=(),
                        exc_info=None
                    )
                    
                    handler.emit(record)
                    
                    assert len(manager.log_entries) == 1


class TestGlobalFunctions:
    """Test global convenience functions."""
    
    def test_get_observability_manager_singleton(self):
        """Test singleton getter."""
        # Reset global
        import core.observability_manager as om
        om._observability_manager = None
        
        with patch.object(ObservabilityManager, '_setup_logging'):
            with patch.object(ObservabilityManager, '_metrics_collector'):
                with patch.object(ObservabilityManager, '_cleanup_old_data'):
                    m1 = get_observability_manager()
                    m2 = get_observability_manager()
                    assert m1 is m2
    
    def test_initialize_observability(self):
        """Test initialize function."""
        import core.observability_manager as om
        
        with patch.object(ObservabilityManager, '_setup_logging'):
            with patch.object(ObservabilityManager, '_metrics_collector'):
                with patch.object(ObservabilityManager, '_cleanup_old_data'):
                    manager = initialize_observability({"log_level": "DEBUG"})
                    assert manager.config["log_level"] == "DEBUG"
                    assert om._observability_manager is manager
