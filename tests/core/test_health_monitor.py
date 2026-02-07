"""
Tests for core/health_monitor.py - Health monitoring system.

Tests health checks, system metrics, monitoring loops, and error handling.
"""
import pytest
import time
import threading
from unittest.mock import MagicMock, patch, Mock
from datetime import datetime, timedelta

from core.health_monitor import (
    HealthMonitor, HealthStatus, HealthCheck, HealthReport,
    get_health_monitor, check_memory_health, check_cpu_health, check_disk_health
)


class TestHealthStatus:
    """Test HealthStatus enum."""

    def test_health_status_values(self):
        """Test health status enum values."""
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"
        assert HealthStatus.UNKNOWN.value == "unknown"

    def test_health_status_order(self):
        """Test health status ordering for severity."""
        statuses = [HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.UNHEALTHY, HealthStatus.UNKNOWN]
        assert len(statuses) == 4


class TestHealthCheck:
    """Test HealthCheck dataclass."""

    def test_health_check_initialization(self):
        """Test health check initialization."""
        def dummy_check():
            return {"status": "healthy"}

        check = HealthCheck(
            name="test_check",
            check_func=dummy_check,
            interval=30.0,
            timeout=2.0,
            critical=True
        )

        assert check.name == "test_check"
        assert check.interval == 30.0
        assert check.timeout == 2.0
        assert check.critical is True
        assert check.last_status == HealthStatus.UNKNOWN
        assert check.consecutive_failures == 0
        assert check.total_runs == 0
        assert check.total_failures == 0

    def test_health_check_defaults(self):
        """Test health check default values."""
        def dummy_check():
            return {"status": "healthy"}

        check = HealthCheck(name="test", check_func=dummy_check)
        assert check.interval == 60.0
        assert check.timeout == 5.0
        assert check.critical is False


class TestHealthReport:
    """Test HealthReport dataclass."""

    def test_health_report_initialization(self):
        """Test health report initialization."""
        report = HealthReport(
            timestamp="2024-01-01T00:00:00",
            overall_status=HealthStatus.HEALTHY,
            checks={"check1": {"status": "healthy"}},
            system_metrics={"cpu": {"percent": 50.0}},
            warnings=["minor issue"],
            errors=[]
        )

        assert report.timestamp == "2024-01-01T00:00:00"
        assert report.overall_status == HealthStatus.HEALTHY
        assert "check1" in report.checks
        assert report.warnings == ["minor issue"]
        assert report.errors == []


class TestHealthMonitorInit:
    """Test HealthMonitor initialization."""

    def test_initialization(self):
        """Test health monitor initialization."""
        with patch('core.health_monitor.logger'):
            monitor = HealthMonitor()

            assert monitor._checks == {}
            assert monitor._running is False
            assert monitor._monitor_thread is None
            assert monitor._history == []
            assert monitor._max_history == 100

            # Check thresholds
            assert monitor._cpu_warning_threshold == 70.0
            assert monitor._cpu_critical_threshold == 90.0
            assert monitor._memory_warning_threshold == 70.0
            assert monitor._memory_critical_threshold == 90.0
            assert monitor._disk_warning_threshold == 80.0
            assert monitor._disk_critical_threshold == 95.0


class TestHealthMonitorRegistration:
    """Test health check registration."""

    @pytest.fixture
    def monitor(self):
        """Create health monitor for testing."""
        with patch('core.health_monitor.logger'):
            return HealthMonitor()

    def test_register_check(self, monitor):
        """Test registering a health check."""
        def dummy_check():
            return {"status": "healthy"}

        monitor.register_check("test_check", dummy_check, interval=30.0, critical=True)

        assert "test_check" in monitor._checks
        check = monitor._checks["test_check"]
        assert check.name == "test_check"
        assert check.interval == 30.0
        assert check.critical is True

    def test_register_duplicate_check(self, monitor):
        """Test registering a duplicate health check."""
        def dummy_check():
            return {"status": "healthy"}

        monitor.register_check("test_check", dummy_check)
        monitor.register_check("test_check", dummy_check)  # Should be ignored

        assert len(monitor._checks) == 1

    def test_unregister_check(self, monitor):
        """Test unregistering a health check."""
        def dummy_check():
            return {"status": "healthy"}

        monitor.register_check("test_check", dummy_check)
        assert "test_check" in monitor._checks

        result = monitor.unregister_check("test_check")
        assert result is True
        assert "test_check" not in monitor._checks

    def test_unregister_nonexistent_check(self, monitor):
        """Test unregistering a nonexistent health check."""
        result = monitor.unregister_check("nonexistent")
        assert result is False


class TestHealthMonitorExecution:
    """Test health check execution."""

    @pytest.fixture
    def monitor(self):
        """Create health monitor for testing."""
        with patch('core.health_monitor.logger'):
            return HealthMonitor()

    def test_run_check_success(self, monitor):
        """Test running a successful health check."""
        def healthy_check():
            return {"status": "healthy", "data": "test"}

        monitor.register_check("test_check", healthy_check)
        result = monitor.run_check("test_check")

        assert result is not None
        assert result["status"] == "healthy"
        assert result["data"] == "test"
        assert "duration_ms" in result
        assert "timestamp" in result

        check = monitor._checks["test_check"]
        assert check.total_runs == 1
        assert check.total_failures == 0
        assert check.consecutive_failures == 0
        assert check.last_status == HealthStatus.HEALTHY

    def test_run_check_degraded(self, monitor):
        """Test running a degraded health check."""
        def degraded_check():
            return {"status": "degraded", "warning": "high load"}

        monitor.register_check("test_check", degraded_check)
        result = monitor.run_check("test_check")

        assert result["status"] == "degraded"
        assert result["warning"] == "high load"

        check = monitor._checks["test_check"]
        assert check.last_status == HealthStatus.DEGRADED
        assert check.consecutive_failures == 0

    def test_run_check_unhealthy(self, monitor):
        """Test running an unhealthy health check."""
        def unhealthy_check():
            return {"status": "unhealthy", "error": "service down"}

        monitor.register_check("test_check", unhealthy_check)
        result = monitor.run_check("test_check")

        assert result["status"] == "unhealthy"
        assert result["error"] == "service down"

        check = monitor._checks["test_check"]
        assert check.last_status == HealthStatus.UNHEALTHY
        assert check.consecutive_failures == 1
        assert check.total_failures == 1

    def test_run_check_exception(self, monitor):
        """Test running a health check that throws an exception."""
        def failing_check():
            raise ValueError("Test error")

        monitor.register_check("test_check", failing_check)
        result = monitor.run_check("test_check")

        assert result["status"] == "unhealthy"
        assert "error" in result
        assert "Test error" in result["error"]
        assert "duration_ms" in result

        check = monitor._checks["test_check"]
        assert check.last_status == HealthStatus.UNHEALTHY
        assert check.consecutive_failures == 1

    def test_run_check_invalid_result(self, monitor):
        """Test running a health check with invalid result format."""
        def invalid_check():
            return "not a dict"

        monitor.register_check("test_check", invalid_check)
        result = monitor.run_check("test_check")

        assert result["status"] == "unhealthy"
        assert "error" in result

    def test_run_check_missing_status(self, monitor):
        """Test running a health check missing status key."""
        def invalid_check():
            return {"data": "missing status"}

        monitor.register_check("test_check", invalid_check)
        result = monitor.run_check("test_check")

        assert result["status"] == "unhealthy"
        assert "error" in result

    def test_run_nonexistent_check(self, monitor):
        """Test running a nonexistent health check."""
        result = monitor.run_check("nonexistent")
        assert result is None


class TestHealthMonitorSystemMetrics:
    """Test system metrics collection."""

    @pytest.fixture
    def monitor(self):
        """Create health monitor for testing."""
        with patch('core.health_monitor.logger'):
            return HealthMonitor()

    @patch('psutil.cpu_percent')
    @patch('psutil.virtual_memory')
    @patch('psutil.disk_usage')
    def test_get_system_metrics_normal(self, mock_disk, mock_memory, mock_cpu, monitor):
        """Test getting system metrics under normal conditions."""
        mock_cpu.return_value = 45.0
        mock_memory.return_value = Mock(percent=60.0, total=8589934592, available=3435973836, used=5153960756)
        mock_disk.return_value = Mock(percent=75.0, total=107374182400, used=80530636800, free=26843545600)

        metrics = monitor.get_system_metrics()

        assert metrics["cpu"]["percent"] == 45.0
        assert metrics["cpu"]["status"] == "healthy"
        assert metrics["memory"]["percent"] == 60.0
        assert metrics["memory"]["status"] == "healthy"
        assert metrics["disk"]["percent"] == 75.0
        assert metrics["disk"]["status"] == "healthy"

    @patch('psutil.cpu_percent')
    @patch('psutil.virtual_memory')
    @patch('psutil.disk_usage')
    def test_get_system_metrics_warnings(self, mock_disk, mock_memory, mock_cpu, monitor):
        """Test getting system metrics with warnings."""
        mock_cpu.return_value = 75.0  # Warning threshold
        mock_memory.return_value = Mock(percent=75.0, total=8589934592, available=2147483648, used=6442450944)
        mock_disk.return_value = Mock(percent=85.0, total=107374182400, used=91268055040, free=16106127360)

        metrics = monitor.get_system_metrics()

        assert metrics["cpu"]["status"] == "warning"
        assert metrics["memory"]["status"] == "warning"
        assert metrics["disk"]["status"] == "warning"

    @patch('psutil.cpu_percent')
    @patch('psutil.virtual_memory')
    @patch('psutil.disk_usage')
    def test_get_system_metrics_critical(self, mock_disk, mock_memory, mock_cpu, monitor):
        """Test getting system metrics with critical levels."""
        mock_cpu.return_value = 95.0  # Critical threshold
        mock_memory.return_value = Mock(percent=95.0, total=8589934592, available=429496729, used=8160437863)
        mock_disk.return_value = Mock(percent=97.0, total=107374182400, used=104018739200, free=3355443200)

        metrics = monitor.get_system_metrics()

        assert metrics["cpu"]["status"] == "critical"
        assert metrics["memory"]["status"] == "critical"
        assert metrics["disk"]["status"] == "critical"

    @patch('psutil.cpu_percent')
    def test_get_system_metrics_exception(self, mock_cpu, monitor):
        """Test getting system metrics when psutil fails."""
        mock_cpu.side_effect = Exception("psutil error")

        metrics = monitor.get_system_metrics()

        assert "error" in metrics
        assert metrics["status"] == "unknown"


class TestHealthMonitorReporting:
    """Test health reporting functionality."""

    @pytest.fixture
    def monitor(self):
        """Create health monitor for testing."""
        with patch('core.health_monitor.logger'):
            return HealthMonitor()

    def test_get_health_report_empty(self, monitor):
        """Test getting health report with no checks."""
        report = monitor.get_health_report()

        assert report.overall_status == HealthStatus.HEALTHY
        assert report.checks == {}
        assert report.warnings == []
        assert report.errors == []
        assert "cpu" in report.system_metrics

    def test_get_health_report_with_checks(self, monitor):
        """Test getting health report with registered checks."""
        def healthy_check():
            return {"status": "healthy", "uptime": 3600}

        def degraded_check():
            return {"status": "degraded", "latency": 500}

        def unhealthy_check():
            return {"status": "unhealthy", "error": "connection failed"}

        monitor.register_check("healthy_check", healthy_check, critical=False)
        monitor.register_check("degraded_check", degraded_check, critical=False)
        monitor.register_check("unhealthy_check", unhealthy_check, critical=True)

        report = monitor.get_health_report()

        assert report.overall_status == HealthStatus.UNHEALTHY  # Critical check failed
        assert len(report.checks) == 3
        assert len(report.warnings) >= 1  # degraded + unhealthy non-critical
        assert len(report.errors) >= 1   # critical unhealthy

    def test_get_health_history(self, monitor):
        """Test getting health history."""
        # Generate some reports
        for i in range(5):
            monitor.get_health_report()

        history = monitor.get_health_history(limit=3)
        assert len(history) == 3

        # Test default limit
        history = monitor.get_health_history()
        assert len(history) == 5

    def test_health_history_max_size(self, monitor):
        """Test health history respects maximum size."""
        monitor._max_history = 3

        # Generate more reports than max
        for i in range(5):
            monitor.get_health_report()

        assert len(monitor._history) == 3


class TestHealthMonitorMonitoring:
    """Test background monitoring functionality."""

    @pytest.fixture
    def monitor(self):
        """Create health monitor for testing."""
        with patch('core.health_monitor.logger'):
            return HealthMonitor()

    def test_start_stop_monitoring(self, monitor):
        """Test starting and stopping background monitoring."""
        assert not monitor._running

        monitor.start_monitoring(interval=0.1)
        assert monitor._running
        assert monitor._monitor_thread is not None
        assert monitor._monitor_thread.is_alive()

        monitor.stop_monitoring()
        assert not monitor._running

    def test_start_monitoring_already_running(self, monitor):
        """Test starting monitoring when already running."""
        monitor.start_monitoring()
        assert monitor._running

        monitor.start_monitoring()  # Should be ignored
        assert monitor._running

    def test_stop_monitoring_not_running(self, monitor):
        """Test stopping monitoring when not running."""
        monitor.stop_monitoring()  # Should not crash
        assert not monitor._running

    @patch('time.sleep')
    def test_monitor_loop(self, mock_sleep, monitor):
        """Test the monitoring loop execution."""
        def healthy_check():
            return {"status": "healthy"}

        monitor.register_check("test", healthy_check, interval=0.1)
        monitor._running = True

        # Run one iteration
        monitor._monitor_loop(0.1)

        # Check that sleep was called
        mock_sleep.assert_called_with(0.1)


class TestHealthMonitorThresholds:
    """Test threshold configuration."""

    @pytest.fixture
    def monitor(self):
        """Create health monitor for testing."""
        with patch('core.health_monitor.logger'):
            return HealthMonitor()

    def test_set_thresholds_partial(self, monitor):
        """Test setting some thresholds."""
        monitor.set_thresholds(cpu_warning=80.0, memory_critical=85.0)

        assert monitor._cpu_warning_threshold == 80.0
        assert monitor._cpu_critical_threshold == 90.0  # Unchanged
        assert monitor._memory_critical_threshold == 85.0
        assert monitor._memory_warning_threshold == 70.0  # Unchanged

    def test_set_thresholds_all(self, monitor):
        """Test setting all thresholds."""
        monitor.set_thresholds(
            cpu_warning=75.0,
            cpu_critical=95.0,
            memory_warning=80.0,
            memory_critical=90.0,
            disk_warning=85.0,
            disk_critical=98.0
        )

        assert monitor._cpu_warning_threshold == 75.0
        assert monitor._cpu_critical_threshold == 95.0
        assert monitor._memory_warning_threshold == 80.0
        assert monitor._memory_critical_threshold == 90.0
        assert monitor._disk_warning_threshold == 85.0
        assert monitor._disk_critical_threshold == 98.0


class TestHealthMonitorSingleton:
    """Test singleton pattern."""

    def test_get_health_monitor_singleton(self):
        """Test singleton behavior."""
        with patch('core.health_monitor.logger'):
            monitor1 = get_health_monitor()
            monitor2 = get_health_monitor()

            assert monitor1 is monitor2
            assert isinstance(monitor1, HealthMonitor)


class TestStandardHealthChecks:
    """Test standard health check functions."""

    @patch('psutil.virtual_memory')
    def test_check_memory_health_healthy(self, mock_memory):
        """Test memory health check when healthy."""
        mock_memory.return_value = Mock(percent=50.0)
        result = check_memory_health()
        assert result["status"] == "healthy"
        assert result["memory_percent"] == 50.0

    @patch('psutil.virtual_memory')
    def test_check_memory_health_degraded(self, mock_memory):
        """Test memory health check when degraded."""
        mock_memory.return_value = Mock(percent=75.0)
        result = check_memory_health()
        assert result["status"] == "degraded"
        assert result["memory_percent"] == 75.0
        assert "reason" in result

    @patch('psutil.virtual_memory')
    def test_check_memory_health_unhealthy(self, mock_memory):
        """Test memory health check when unhealthy."""
        mock_memory.return_value = Mock(percent=95.0)
        result = check_memory_health()
        assert result["status"] == "unhealthy"
        assert result["memory_percent"] == 95.0

    @patch('psutil.cpu_percent')
    def test_check_cpu_health(self, mock_cpu):
        """Test CPU health check."""
        mock_cpu.return_value = 45.0
        result = check_cpu_health()
        assert result["status"] == "healthy"
        assert result["cpu_percent"] == 45.0

    @patch('psutil.disk_usage')
    def test_check_disk_health(self, mock_disk):
        """Test disk health check."""
        mock_disk.return_value = Mock(percent=70.0)
        result = check_disk_health()
        assert result["status"] == "healthy"
        assert result["disk_percent"] == 70.0

    def test_health_checks_exception_handling(self):
        """Test that health checks handle exceptions gracefully."""
        with patch('psutil.virtual_memory', side_effect=Exception("test error")):
            result = check_memory_health()
            assert result["status"] == "unhealthy"
            assert "error" in result

        with patch('psutil.cpu_percent', side_effect=Exception("test error")):
            result = check_cpu_health()
            assert result["status"] == "unhealthy"
            assert "error" in result

        with patch('psutil.disk_usage', side_effect=Exception("test error")):
            result = check_disk_health()
            assert result["status"] == "unhealthy"
            assert "error" in result
