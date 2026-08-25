"""
Tests for Callback Health Monitor
"""

import pytest
import time

from merid.position_management.callback_health_monitor import (
    CallbackHealthMonitor,
    CallbackFailure,
)


class TestCallbackHealthMonitor:
    """Tests for CallbackHealthMonitor."""
    
    @pytest.fixture
    def monitor(self):
        """Create a monitor with default settings."""
        return CallbackHealthMonitor(failure_threshold=5, window_seconds=300)
    
    def test_record_success(self, monitor):
        """Test recording successful callback."""
        monitor.record_success()
        
        assert monitor._success_count == 1
        assert monitor._total_count == 1
        assert monitor.is_healthy()
    
    def test_record_failure(self, monitor):
        """Test recording callback failure."""
        error = Exception("Test error")
        monitor.record_failure(error)
        
        assert len(monitor._failures) == 1
        assert monitor._total_count == 1
        assert monitor._success_count == 0
        assert monitor.is_healthy()  # Still healthy (below threshold)
    
    def test_is_healthy_below_threshold(self, monitor):
        """Test healthy state when failures below threshold."""
        for i in range(4):
            monitor.record_failure(Exception(f"Error {i}"))
        
        assert monitor.is_healthy()
    
    def test_is_healthy_above_threshold(self, monitor):
        """Test unhealthy state when failures exceed threshold."""
        for i in range(5):
            monitor.record_failure(Exception(f"Error {i}"))
        
        assert not monitor.is_healthy()
    
    def test_get_failure_count(self, monitor):
        """Test getting failure count."""
        for i in range(3):
            monitor.record_failure(Exception(f"Error {i}"))
        
        assert monitor.get_failure_count() == 3
    
    def test_get_success_rate(self, monitor):
        """Test getting success rate."""
        monitor.record_success()
        monitor.record_success()
        monitor.record_failure(Exception("Error"))
        
        assert monitor.get_success_rate() == 2.0 / 3.0
    
    def test_get_success_rate_no_calls(self, monitor):
        """Test success rate with no calls."""
        assert monitor.get_success_rate() == 1.0
    
    def test_get_metrics(self, monitor):
        """Test getting health metrics."""
        monitor.record_success()
        monitor.record_success()
        monitor.record_failure(Exception("Error"))
        
        metrics = monitor.get_metrics()
        
        assert metrics["total_count"] == 3
        assert metrics["success_count"] == 2
        assert metrics["failure_count"] == 1
        assert metrics["success_rate"] == 2.0 / 3.0
        assert metrics["is_healthy"] is True
        assert metrics["failure_threshold"] == 5
        assert metrics["window_seconds"] == 300
    
    def test_clean_old_failures(self, monitor):
        """Test that old failures are cleaned up."""
        # Record failures
        for i in range(3):
            monitor.record_failure(Exception(f"Error {i}"))
        
        assert monitor.get_failure_count() == 3
        
        # Wait for failures to expire
        time.sleep(0.1)
        
        # Create monitor with very short window
        short_monitor = CallbackHealthMonitor(failure_threshold=5, window_seconds=0.05)
        for i in range(3):
            short_monitor.record_failure(Exception(f"Error {i}"))
        
        time.sleep(0.1)
        
        # Old failures should be cleaned
        assert short_monitor.get_failure_count() == 0
    
    def test_reset(self, monitor):
        """Test resetting monitor state."""
        monitor.record_success()
        monitor.record_failure(Exception("Error"))
        
        monitor.reset()
        
        assert monitor._success_count == 0
        assert monitor._total_count == 0
        assert len(monitor._failures) == 0
        assert monitor.is_healthy()
    
    def test_failure_record_structure(self, monitor):
        """Test that failure records have correct structure."""
        error = ValueError("Test error")
        monitor.record_failure(error)
        
        assert len(monitor._failures) == 1
        failure = monitor._failures[0]
        assert isinstance(failure, CallbackFailure)
        assert failure.error_type == "ValueError"
        assert "Test error" in failure.error
        assert failure.timestamp > 0
