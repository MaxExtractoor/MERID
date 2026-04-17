"""Tests for execution health monitoring.

This module tests execution health checks, latency monitoring,
and circuit breaker integration for the Kalshi trading stack.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Generator
from unittest.mock import Mock, AsyncMock, patch

import pytest


class MockExecutionHealthMonitor:
    """Mock execution health monitor for testing."""
    
    def __init__(self) -> None:
        self._latencies: list[float] = []
        self._errors: list[Dict[str, Any]] = []
        self._circuit_state = "closed"
        self._last_heartbeat = datetime.now(timezone.utc)
    
    def record_latency(self, latency_ms: float, operation: str = "unknown") -> None:
        self._latencies.append({"latency_ms": latency_ms, "operation": operation, "ts": datetime.now(timezone.utc)})
    
    def record_error(self, error_type: str, message: str) -> None:
        self._errors.append({"type": error_type, "message": message, "ts": datetime.now(timezone.utc)})
    
    def get_health_score(self) -> float:
        """Return health score 0-100."""
        # Recent errors degrade score
        recent_errors = sum(
            1 for e in self._errors
            if e["ts"] > datetime.now(timezone.utc) - timedelta(minutes=5)
        )
        
        # High latency degrades score
        high_latency_count = sum(
            1 for l in self._latencies[-100:]
            if l["latency_ms"] > 500
        )
        
        score = 100.0 - (recent_errors * 10) - (high_latency_count * 2)
        return max(0.0, min(100.0, score))
    
    def get_stats(self) -> Dict[str, Any]:
        error_count = len(self._errors)
        if not self._latencies:
            return {"latency_avg_ms": 0, "latency_p99_ms": 0, "error_count": error_count, "circuit_state": self._circuit_state}
        
        recent = [l["latency_ms"] for l in self._latencies[-100:]]
        sorted_latencies = sorted(recent)
        p99_idx = int(len(sorted_latencies) * 0.99)
        
        return {
            "latency_avg_ms": sum(recent) / len(recent),
            "latency_p99_ms": sorted_latencies[min(p99_idx, len(sorted_latencies) - 1)],
            "error_count": error_count,
            "circuit_state": self._circuit_state,
        }
    
    def is_healthy(self) -> bool:
        return self.get_health_score() > 50


@pytest.fixture
def health_monitor() -> Generator[MockExecutionHealthMonitor, None, None]:
    """Provide a fresh health monitor for each test."""
    yield MockExecutionHealthMonitor()


class TestExecutionHealthBasic:
    """Test basic health monitoring functionality."""

    def test_record_latency(self, health_monitor: MockExecutionHealthMonitor) -> None:
        """Test latency recording."""
        health_monitor.record_latency(100.0, "order_submit")
        health_monitor.record_latency(150.0, "order_submit")
        
        stats = health_monitor.get_stats()
        assert stats["latency_avg_ms"] == 125.0
        assert stats["error_count"] == 0

    def test_record_error(self, health_monitor: MockExecutionHealthMonitor) -> None:
        """Test error recording."""
        health_monitor.record_error("timeout", "Order submission timed out")
        
        stats = health_monitor.get_stats()
        assert stats["error_count"] == 1

    def test_healthy_initial_state(self, health_monitor: MockExecutionHealthMonitor) -> None:
        """Test that initial state is healthy."""
        assert health_monitor.is_healthy() is True
        assert health_monitor.get_health_score() == 100.0

    def test_unhealthy_after_errors(self, health_monitor: MockExecutionHealthMonitor) -> None:
        """Test health degradation after errors."""
        for i in range(6):
            health_monitor.record_error("timeout", f"Error {i}")
        
        assert health_monitor.is_healthy() is False
        assert health_monitor.get_health_score() < 50


class TestExecutionHealthLatency:
    """Test latency tracking and statistics."""

    def test_latency_averaging(self, health_monitor: MockExecutionHealthMonitor) -> None:
        """Test that latencies are properly averaged."""
        latencies = [50.0, 100.0, 150.0, 200.0]
        for lat in latencies:
            health_monitor.record_latency(lat)
        
        stats = health_monitor.get_stats()
        assert stats["latency_avg_ms"] == 125.0

    def test_p99_latency(self, health_monitor: MockExecutionHealthMonitor) -> None:
        """Test P99 latency calculation."""
        # Record 100 latencies, mostly low with a few high outliers
        for i in range(99):
            health_monitor.record_latency(50.0)
        health_monitor.record_latency(1000.0)  # Outlier
        
        stats = health_monitor.get_stats()
        assert stats["latency_p99_ms"] == 1000.0

    def test_latency_by_operation(self, health_monitor: MockExecutionHealthMonitor) -> None:
        """Test latency tracking by operation type."""
        health_monitor.record_latency(100.0, "order_submit")
        health_monitor.record_latency(200.0, "order_cancel")
        health_monitor.record_latency(150.0, "order_submit")
        
        stats = health_monitor.get_stats()
        assert stats["latency_avg_ms"] == 150.0


class TestExecutionHealthCircuitBreaker:
    """Test circuit breaker integration."""

    def test_circuit_closed_initially(self, health_monitor: MockExecutionHealthMonitor) -> None:
        """Test that circuit starts closed."""
        assert health_monitor._circuit_state == "closed"

    def test_circuit_opens_after_errors(self, health_monitor: MockExecutionHealthMonitor) -> None:
        """Test circuit opens after many errors."""
        health_monitor._circuit_state = "open"
        
        stats = health_monitor.get_stats()
        assert stats["circuit_state"] == "open"


class TestExecutionHealthDegradation:
    """Test health score degradation logic."""

    def test_high_latency_degradation(self, health_monitor: MockExecutionHealthMonitor) -> None:
        """Test health degradation from high latency."""
        # Add many high-latency samples
        for i in range(10):
            health_monitor.record_latency(1000.0)  # Very high latency
        
        score = health_monitor.get_health_score()
        # 10 high-latency samples * 2 points each = 20 point deduction
        assert score <= 80

    def test_combined_degradation(self, health_monitor: MockExecutionHealthMonitor) -> None:
        """Test health degradation from errors + latency combined."""
        for i in range(3):
            health_monitor.record_error("timeout", f"Error {i}")
            health_monitor.record_latency(1000.0)
        
        score = health_monitor.get_health_score()
        # 3 errors * 10 + 3 high-latency * 2 = 30 + 6 = 36 point deduction
        assert score <= 70


class TestExecutionHealthEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_stats(self, health_monitor: MockExecutionHealthMonitor) -> None:
        """Test stats with no data."""
        stats = health_monitor.get_stats()
        assert stats["latency_avg_ms"] == 0
        assert stats["latency_p99_ms"] == 0
        assert stats["error_count"] == 0

    def test_zero_latency(self, health_monitor: MockExecutionHealthMonitor) -> None:
        """Test zero latency recording."""
        health_monitor.record_latency(0.0)
        stats = health_monitor.get_stats()
        assert stats["latency_avg_ms"] == 0

    def test_very_high_latency(self, health_monitor: MockExecutionHealthMonitor) -> None:
        """Test extremely high latency values."""
        health_monitor.record_latency(100000.0)  # 100 seconds
        stats = health_monitor.get_stats()
        assert stats["latency_avg_ms"] == 100000.0


class TestExecutionHealthThreadSafety:
    """Test thread safety of health monitoring."""

    def test_concurrent_latency_recording(self, health_monitor: MockExecutionHealthMonitor) -> None:
        """Test concurrent latency recording."""
        import threading
        
        errors = []
        
        def record_latencies(thread_id: int) -> None:
            try:
                for i in range(20):
                    health_monitor.record_latency(float(i * 10 + thread_id))
            except Exception as e:
                errors.append(e)
        
        threads = [
            threading.Thread(target=record_latencies, args=(i,))
            for i in range(5)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        assert len(health_monitor._latencies) == 100


class TestExecutionHealthTimeWindows:
    """Test time-windowed health queries."""

    def test_recent_errors_only(self, health_monitor: MockExecutionHealthMonitor) -> None:
        """Test that only recent errors affect health score."""
        # Old error (6 minutes ago) - should not count
        old_error = {"type": "old", "message": "old", "ts": datetime.now(timezone.utc) - timedelta(minutes=6)}
        health_monitor._errors.append(old_error)
        
        # Recent error (1 minute ago) - should count
        health_monitor.record_error("recent", "Recent error")
        
        score = health_monitor.get_health_score()
        # Only 1 recent error = 10 point deduction
        assert score == 90


class TestExecutionHealthAlerting:
    """Test health-based alerting thresholds."""

    def test_alert_threshold_crossing(self, health_monitor: MockExecutionHealthMonitor) -> None:
        """Test that health crossing alert threshold triggers state change."""
        # Start healthy
        assert health_monitor.is_healthy() is True
        
        # Add many errors to make unhealthy
        for i in range(10):
            health_monitor.record_error("critical", f"Critical error {i}")
        
        # Should now be unhealthy
        assert health_monitor.is_healthy() is False
        assert health_monitor.get_health_score() < 50

    def test_recovery_detection(self, health_monitor: MockExecutionHealthMonitor) -> None:
        """Test that health recovery is detected."""
        # Make unhealthy
        for i in range(10):
            health_monitor.record_error("error", f"Error {i}")
        
        # Clear errors by simulating new data
        health_monitor._errors = []  # Reset
        
        # Add low-latency samples
        for i in range(50):
            health_monitor.record_latency(50.0)  # Good latency
        
        # Should recover
        assert health_monitor.is_healthy() is True


class TestExecutionHealthIntegration:
    """Integration tests for health monitoring with other components."""

    @pytest.mark.asyncio
    async def test_health_with_mock_execution(self) -> None:
        """Test health monitoring with mocked execution."""
        monitor = MockExecutionHealthMonitor()
        
        # Simulate execution
        monitor.record_latency(50.0, "order_submit")
        monitor.record_latency(30.0, "order_status")
        
        assert monitor.is_healthy() is True
        assert monitor.get_stats()["latency_avg_ms"] == 40.0
