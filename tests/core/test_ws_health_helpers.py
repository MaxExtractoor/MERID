"""
Tests for WebSocket Health Monitoring Helpers

Tests the centralized WebSocket health monitoring with proper idle vs stalled
semantics and comprehensive diagnostics.
"""

import time
import logging
import pytest
from unittest.mock import Mock, patch

from merid.core.ws_health_helpers import (
    compute_ws_health, WSHealthResult, validate_ws_health_consistency,
    log_ws_health_diagnostics, IDLE_WARN_AFTER, STALL_THRESHOLD
)


class TestWSHealthComputation:
    """Test WS health computation with various states and edge cases."""
    
    def test_idle_state_no_events(self):
        """Test idle state when no events have been processed."""
        result = compute_ws_health(
            event_count_total=0,
            first_event_ts=0.0,
            last_event_ts=0.0,
            events_per_sec=0.0,
            queue_size=0,
            subscribed_assets=set(),
            expected_assets={"BTC", "ETH"},
            now_mono=100.0
        )
        
        assert result.state == "idle"
        assert result.stalled is False
        assert result.event_count_total == 0
        assert result.time_since_last_event is None
        assert result.is_healthy() is True
        assert result.has_events() is False
        assert result.is_processing() is False
    
    def test_healthy_state_processing_events(self):
        """Test healthy state when actively processing events."""
        now = time.monotonic()
        result = compute_ws_health(
            event_count_total=100,
            first_event_ts=now - 60.0,
            last_event_ts=now - 5.0,  # 5 seconds ago
            events_per_sec=2.5,
            queue_size=3,
            subscribed_assets={"BTC", "ETH"},
            expected_assets={"BTC", "ETH", "SOL"},
            now_mono=now
        )
        
        assert result.state == "healthy"
        assert result.stalled is False
        assert result.event_count_total == 100
        assert result.time_since_last_event == 5.0
        assert result.is_healthy() is True
        assert result.has_events() is True
        assert result.is_processing() is True
        assert result.subscription_coverage["subscribed_count"] == 2
        assert result.subscription_coverage["expected_count"] == 3
        assert result.subscription_coverage["coverage_complete"] is False
    
    def test_degraded_state_events_stopped(self):
        """Test degraded state when events have stopped."""
        now = time.monotonic()
        result = compute_ws_health(
            event_count_total=50,
            first_event_ts=now - 120.0,
            last_event_ts=now - 45.0,  # 45 seconds ago (> STALL_THRESHOLD, < UNHEALTHY_THRESHOLD)
            events_per_sec=0.0,  # No recent events
            queue_size=0,
            subscribed_assets={"BTC", "ETH", "SOL"},
            expected_assets={"BTC", "ETH", "SOL"},
            now_mono=now
        )
        
        assert result.state == "degraded"
        assert result.stalled is False
        assert result.event_count_total == 50
        assert result.time_since_last_event == 45.0
        assert result.is_healthy() is False
        assert result.has_events() is True
        assert result.is_processing() is False
        assert result.subscription_coverage["coverage_complete"] is True
    
    def test_edge_case_exactly_stall_threshold(self):
        """Test behavior exactly at stall threshold."""
        now = time.monotonic()
        result = compute_ws_health(
            event_count_total=10,
            first_event_ts=now - 60.0,
            last_event_ts=now - STALL_THRESHOLD,  # Exactly at threshold
            events_per_sec=1.0,
            queue_size=1,
            subscribed_assets={"BTC"},
            expected_assets={"BTC"},
            now_mono=now
        )
        
        # Exactly at threshold should be healthy (not > threshold)
        assert result.state == "healthy"
        assert result.stalled is False
    
    def test_edge_case_just_over_stall_threshold(self):
        """Test behavior just over stall threshold."""
        now = time.monotonic()
        result = compute_ws_health(
            event_count_total=10,
            first_event_ts=now - 60.0,
            last_event_ts=now - (STALL_THRESHOLD + 0.1),  # Just over threshold
            events_per_sec=0.5,
            queue_size=2,
            subscribed_assets={"BTC"},
            expected_assets={"BTC"},
            now_mono=now
        )
        
        # Just over threshold should be degraded (not unhealthy until >60s)
        assert result.state == "degraded"
        assert result.stalled is False
    
    def test_subscription_coverage_calculation(self):
        """Test subscription coverage calculation."""
        result = compute_ws_health(
            event_count_total=5,
            first_event_ts=100.0,
            last_event_ts=105.0,
            events_per_sec=1.0,
            queue_size=0,
            subscribed_assets={"BTC", "ETH"},  # Missing SOL, XRP, DOGE
            expected_assets={"BTC", "ETH", "SOL", "XRP", "DOGE"},
            now_mono=110.0
        )
        
        coverage = result.subscription_coverage
        assert set(coverage["subscribed_assets"]) == {"BTC", "ETH"}
        assert set(coverage["missing_assets"]) == {"SOL", "XRP", "DOGE"}
        assert coverage["expected_count"] == 5
        assert coverage["subscribed_count"] == 2
        assert coverage["coverage_complete"] is False


class TestWSHealthResultMethods:
    """Test WSHealthResult helper methods."""
    
    def test_is_healthy(self):
        """Test is_healthy() method."""
        # Idle should be healthy
        result = WSHealthResult("idle", False, 0, 0.0, 0, None, 0.0, 0.0, {})
        assert result.is_healthy() is True
        
        # Healthy should be healthy
        result = WSHealthResult("healthy", False, 10, 1.0, 2, 5.0, 100.0, 105.0, {})
        assert result.is_healthy() is True
        
        # Stalled should not be healthy
        result = WSHealthResult("stalled", True, 10, 0.0, 0, 45.0, 100.0, 60.0, {})
        assert result.is_healthy() is False
    
    def test_has_events(self):
        """Test has_events() method."""
        # No events should return False
        result = WSHealthResult("idle", False, 0, 0.0, 0, None, 0.0, 0.0, {})
        assert result.has_events() is False
        
        # With events should return True
        result = WSHealthResult("healthy", False, 10, 1.0, 2, 5.0, 100.0, 105.0, {})
        assert result.has_events() is True
    
    def test_is_processing(self):
        """Test is_processing() method."""
        # Idle should not be processing
        result = WSHealthResult("idle", False, 0, 0.0, 0, None, 0.0, 0.0, {})
        assert result.is_processing() is False
        
        # Healthy should be processing
        result = WSHealthResult("healthy", False, 10, 1.0, 2, 5.0, 100.0, 105.0, {})
        assert result.is_processing() is True
        
        # Stalled should not be processing
        result = WSHealthResult("stalled", True, 10, 0.0, 0, 45.0, 100.0, 60.0, {})
        assert result.is_processing() is False


class TestWSHealthValidation:
    """Test WS health result validation."""
    
    def test_validation_consistent_healthy(self):
        """Test validation with consistent healthy result."""
        result = WSHealthResult(
            state="healthy",
            stalled=False,
            event_count_total=10,
            events_per_sec=1.5,
            queue_size=2,
            time_since_last_event=5.0,
            first_event_ts=100.0,
            last_event_ts=105.0,
            subscription_coverage={}
        )
        assert validate_ws_health_consistency(result) is True
    
    def test_validation_consistent_idle(self):
        """Test validation with consistent idle result."""
        result = WSHealthResult(
            state="idle",
            stalled=False,
            event_count_total=0,
            events_per_sec=0.0,
            queue_size=0,
            time_since_last_event=None,
            first_event_ts=0.0,
            last_event_ts=0.0,
            subscription_coverage={}
        )
        assert validate_ws_health_consistency(result) is True
    
    def test_validation_consistent_stalled(self):
        """Test validation with consistent stalled result."""
        result = WSHealthResult(
            state="stalled",
            stalled=True,
            event_count_total=10,
            events_per_sec=0.0,
            queue_size=0,
            time_since_last_event=45.0,
            first_event_ts=60.0,  # First event should be before last event
            last_event_ts=100.0,
            subscription_coverage={}
        )
        assert validate_ws_health_consistency(result) is True
    
    def test_validation_inconsistent_idle_with_events(self):
        """Test validation failure: idle state with events."""
        result = WSHealthResult(
            state="idle",
            stalled=False,
            event_count_total=10,  # Should be 0 for idle
            events_per_sec=1.0,
            queue_size=0,
            time_since_last_event=None,
            first_event_ts=100.0,
            last_event_ts=105.0,
            subscription_coverage={}
        )
        assert validate_ws_health_consistency(result) is False
    
    def test_validation_inconsistent_healthy_no_events(self):
        """Test validation failure: healthy state with no events."""
        result = WSHealthResult(
            state="healthy",
            stalled=False,
            event_count_total=0,  # Should be > 0 for healthy
            events_per_sec=0.0,
            queue_size=0,
            time_since_last_event=5.0,
            first_event_ts=0.0,
            last_event_ts=0.0,
            subscription_coverage={}
        )
        assert validate_ws_health_consistency(result) is False
    
    def test_validation_inconsistent_stalled_not_stalled(self):
        """Test validation failure: stalled state not marked as stalled."""
        result = WSHealthResult(
            state="stalled",
            stalled=False,  # Should be True for stalled
            event_count_total=10,
            events_per_sec=0.0,
            queue_size=0,
            time_since_last_event=45.0,
            first_event_ts=100.0,
            last_event_ts=60.0,
            subscription_coverage={}
        )
        assert validate_ws_health_consistency(result) is False
    
    def test_validation_timestamp_order(self):
        """Test validation failure: first event after last event."""
        result = WSHealthResult(
            state="healthy",
            stalled=False,
            event_count_total=10,
            events_per_sec=1.0,
            queue_size=0,
            time_since_last_event=5.0,
            first_event_ts=110.0,  # After last event
            last_event_ts=100.0,
            subscription_coverage={}
        )
        assert validate_ws_health_consistency(result) is False
    
    def test_validation_invalid_numeric_values(self):
        """Test validation failure: invalid numeric values."""
        # Negative events per sec
        result = WSHealthResult(
            state="healthy", stalled=False, event_count_total=10,
            events_per_sec=-1.0, queue_size=0, time_since_last_event=5.0,
            first_event_ts=100.0, last_event_ts=105.0, subscription_coverage={}
        )
        assert validate_ws_health_consistency(result) is False
        
        # Negative queue size
        result = WSHealthResult(
            state="healthy", stalled=False, event_count_total=10,
            events_per_sec=1.0, queue_size=-1, time_since_last_event=5.0,
            first_event_ts=100.0, last_event_ts=105.0, subscription_coverage={}
        )
        assert validate_ws_health_consistency(result) is False


class TestWSHealthLogging:
    """Test WS health diagnostic logging."""
    
    def test_log_diagnostics_healthy(self, caplog):
        """Test diagnostic logging for healthy state."""
        result = WSHealthResult(
            state="healthy",
            stalled=False,
            event_count_total=10,
            events_per_sec=1.5,
            queue_size=2,
            time_since_last_event=5.0,
            first_event_ts=100.0,
            last_event_ts=105.0,
            subscription_coverage={
                "subscribed_count": 2,
                "expected_count": 3
            }
        )
        
        with caplog.at_level(logging.INFO):
            log_ws_health_diagnostics(result, url="wss://test.example.com")
        
        # Check that diagnostic info was logged
        assert "[WS_HEALTH]" in caplog.text
        assert "status=HEALTHY" in caplog.text
        assert "stalled=False" in caplog.text
        assert "stale_ms=5000" in caplog.text
        assert "reason=ok" in caplog.text
        assert "uri=wss://test.example.com" in caplog.text
    
    def test_log_diagnostics_idle(self, caplog):
        """Test diagnostic logging for idle state."""
        result = WSHealthResult(
            state="idle",
            stalled=False,
            event_count_total=0,
            events_per_sec=0.0,
            queue_size=0,
            time_since_last_event=None,
            first_event_ts=0.0,
            last_event_ts=0.0,
            subscription_coverage={
                "subscribed_count": 0,
                "expected_count": 3
            }
        )
        
        # Mock time to be less than IDLE_WARN_AFTER to avoid warning
        with patch('time.monotonic', return_value=30.0):
            with caplog.at_level(logging.INFO):
                log_ws_health_diagnostics(result)
        
        # Check that idle state was logged
        assert "[WS_HEALTH]" in caplog.text
        assert "status=IDLE" in caplog.text
        assert "stalled=False" in caplog.text
        assert "stale_ms=0" in caplog.text
        assert "reason=ok" in caplog.text
    
    def test_log_diagnostics_degraded(self, caplog):
        """Test diagnostic logging for degraded state."""
        result = WSHealthResult(
            state="degraded",
            stalled=False,
            event_count_total=10,
            events_per_sec=0.0,
            queue_size=0,
            time_since_last_event=45.0,
            first_event_ts=100.0,
            last_event_ts=60.0,
            subscription_coverage={
                "subscribed_count": 3,
                "expected_count": 3
            }
        )
        
        with caplog.at_level(logging.INFO):
            log_ws_health_diagnostics(result)
        
        # Check that both the diagnostic summary and the degraded warning were logged
        assert "[WS_HEALTH]" in caplog.text
        assert "status=DEGRADED" in caplog.text
        assert "stalled=False" in caplog.text
        assert "stale_ms=45000" in caplog.text
        assert "reason=stale_connection" in caplog.text
        assert "DEGRADED for 45.0s" in caplog.text


if __name__ == "__main__":
    pytest.main([__file__])
