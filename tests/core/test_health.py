"""Tests for core/health.py."""
import pytest
from unittest.mock import Mock, patch
from core.health import (
    HealthStatus, ComponentHealth, HealthMonitor, get_health_monitor
)


class TestHealthStatus:
    """Test HealthStatus enum."""

    def test_status_values(self):
        """Test HealthStatus enum values."""
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"
        assert HealthStatus.UNKNOWN.value == "unknown"


class TestComponentHealth:
    """Test ComponentHealth dataclass."""

    def test_creation(self):
        """Test ComponentHealth creation."""
        comp = ComponentHealth(
            name="Test Component",
            status=HealthStatus.HEALTHY,
            message="All good",
            metrics={"cpu": 50.0}
        )
        assert comp.name == "Test Component"
        assert comp.status == HealthStatus.HEALTHY
        assert comp.message == "All good"
        assert comp.metrics["cpu"] == 50.0

    def test_to_dict(self):
        """Test ComponentHealth to_dict."""
        comp = ComponentHealth(
            name="Test",
            status=HealthStatus.HEALTHY,
            message="OK"
        )
        d = comp.to_dict()
        assert d["name"] == "Test"
        assert d["status"] == "healthy"
        assert d["message"] == "OK"


class TestHealthMonitor:
    """Test HealthMonitor class."""

    def test_initialization(self):
        """Test monitor initialization."""
        monitor = HealthMonitor()
        assert monitor._components == {}
        assert monitor._running is False

    @pytest.mark.asyncio
    async def test_start_stop(self):
        """Test start and stop monitoring."""
        monitor = HealthMonitor()
        await monitor.start()
        assert monitor._running is True
        await monitor.stop()
        assert monitor._running is False

    @pytest.mark.asyncio
    async def test_start_already_running(self):
        """Test start when already running."""
        monitor = HealthMonitor()
        await monitor.start()
        await monitor.start()  # Should not raise or create duplicate task
        await monitor.stop()

    @pytest.mark.asyncio
    async def test_check_all(self):
        """Test checking all components."""
        monitor = HealthMonitor()
        components = await monitor.check_all()
        assert isinstance(components, dict)

    def test_get_overall_status_unknown(self):
        """Test overall status when no components."""
        monitor = HealthMonitor()
        status = monitor.get_overall_status()
        assert status == HealthStatus.UNKNOWN

    def test_get_overall_status_healthy(self):
        """Test overall status when all healthy."""
        monitor = HealthMonitor()
        monitor._components = {
            "comp1": ComponentHealth("c1", HealthStatus.HEALTHY),
            "comp2": ComponentHealth("c2", HealthStatus.HEALTHY)
        }
        status = monitor.get_overall_status()
        assert status == HealthStatus.HEALTHY

    def test_get_overall_status_degraded(self):
        """Test overall status when degraded."""
        monitor = HealthMonitor()
        monitor._components = {
            "comp1": ComponentHealth("c1", HealthStatus.HEALTHY),
            "comp2": ComponentHealth("c2", HealthStatus.DEGRADED)
        }
        status = monitor.get_overall_status()
        assert status == HealthStatus.DEGRADED

    def test_get_overall_status_unhealthy(self):
        """Test overall status when unhealthy."""
        monitor = HealthMonitor()
        monitor._components = {
            "comp1": ComponentHealth("c1", HealthStatus.HEALTHY),
            "comp2": ComponentHealth("c2", HealthStatus.UNHEALTHY)
        }
        status = monitor.get_overall_status()
        assert status == HealthStatus.UNHEALTHY

    def test_get_summary(self):
        """Test getting health summary."""
        monitor = HealthMonitor()
        monitor._components = {
            "comp1": ComponentHealth("c1", HealthStatus.HEALTHY)
        }
        summary = monitor.get_summary()
        assert "status" in summary
        assert "uptime_seconds" in summary
        assert "components" in summary
        assert "healthy_count" in summary
        assert summary["healthy_count"] == 1
        assert summary["total_components"] == 1


class TestGetHealthMonitor:
    """Test get_health_monitor singleton."""

    def test_singleton(self):
        """Test get_health_monitor returns singleton."""
        monitor1 = get_health_monitor()
        monitor2 = get_health_monitor()
        assert monitor1 is monitor2
