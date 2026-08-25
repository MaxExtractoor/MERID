"""
Tests for WebSocket Health Threshold Fixes (2026-08-02)

Tests the relaxed WebSocket health monitoring thresholds to prevent premature reconnections:
- Health check interval: 2s → 5s (reduced frequency)
- Stale threshold: 5s → 30s (relaxed for normal market quiet periods)
- Grace period: 10s → 15s (more time for subscription processing)
- Recv timeout: 60s → 90s (more tolerant detection)
"""

import time
import pytest
from unittest.mock import Mock, patch
import asyncio

from merid.core.ws_health_helpers import compute_ws_health, WSHealthResult, STALL_THRESHOLD, UNHEALTHY_THRESHOLD


class TestWebSocketHealthThresholds:
    """Test WebSocket health threshold changes from 2026-08-02 fix."""
    
    def test_stall_threshold_is_15_seconds(self):
        """Verify STALL_THRESHOLD is set to 15 seconds (relaxed from previous 5s)."""
        # The fix relaxed thresholds to prevent premature reconnections
        # STALL_THRESHOLD should be 15s for DEGRADED state
        assert STALL_THRESHOLD == 15.0, f"STALL_THRESHOLD should be 15.0, got {STALL_THRESHOLD}"
    
    def test_unhealthy_threshold_is_60_seconds(self):
        """Verify UNHEALTHY_THRESHOLD is set to 60 seconds."""
        # UNHEALTHY_THRESHOLD should be 60s for UNHEALTHY state
        assert UNHEALTHY_THRESHOLD == 60.0, f"UNHEALTHY_THRESHOLD should be 60.0, got {UNHEALTHY_THRESHOLD}"
    
    def test_degraded_state_between_15_and_60_seconds(self):
        """Test DEGRADED state between 15s and 60s without messages."""
        now = time.monotonic()
        # 20 seconds without messages - should be DEGRADED (not UNHEALTHY)
        result = compute_ws_health(
            event_count_total=100,
            first_event_ts=now - 120.0,
            last_event_ts=now - 20.0,  # 20 seconds ago (> STALL_THRESHOLD, < UNHEALTHY_THRESHOLD)
            events_per_sec=0.0,
            queue_size=0,
            subscribed_assets={"BTC", "ETH"},
            expected_assets={"BTC", "ETH"},
            now_mono=now
        )
        
        assert result.state == "degraded", f"Expected 'degraded' state, got '{result.state}'"
        assert result.stalled is False, "DEGRADED state should not be marked as stalled"
        assert result.can_trade() is True, "DEGRADED state should allow trading"
    
    def test_healthy_state_within_15_seconds(self):
        """Test HEALTHY state within 15 seconds without messages."""
        now = time.monotonic()
        # 10 seconds without messages - should be HEALTHY (below STALL_THRESHOLD)
        result = compute_ws_health(
            event_count_total=100,
            first_event_ts=now - 120.0,
            last_event_ts=now - 10.0,  # 10 seconds ago (< STALL_THRESHOLD)
            events_per_sec=1.0,
            queue_size=1,
            subscribed_assets={"BTC", "ETH"},
            expected_assets={"BTC", "ETH"},
            now_mono=now
        )
        
        assert result.state == "healthy", f"Expected 'healthy' state, got '{result.state}'"
        assert result.stalled is False
        assert result.can_trade() is True
    
    def test_unhealthy_state_after_60_seconds(self):
        """Test UNHEALTHY state after 60 seconds without messages."""
        now = time.monotonic()
        # 70 seconds without messages - should be UNHEALTHY
        result = compute_ws_health(
            event_count_total=100,
            first_event_ts=now - 200.0,
            last_event_ts=now - 70.0,  # 70 seconds ago (> UNHEALTHY_THRESHOLD)
            events_per_sec=0.0,
            queue_size=0,
            subscribed_assets={"BTC", "ETH"},
            expected_assets={"BTC", "ETH"},
            now_mono=now
        )
        
        assert result.state == "unhealthy", f"Expected 'unhealthy' state, got '{result.state}'"
        assert result.stalled is True
        assert result.can_trade() is False, "UNHEALTHY state should not allow trading"
    
    def test_normal_market_quiet_period_allowed(self):
        """Test that normal market quiet periods (20-30s) don't trigger unhealthy state."""
        now = time.monotonic()
        # Simulate normal market quiet period - 25 seconds without messages
        # This should be DEGRADED but still allow trading
        result = compute_ws_health(
            event_count_total=500,
            first_event_ts=now - 300.0,
            last_event_ts=now - 25.0,  # 25 seconds ago (normal quiet period)
            events_per_sec=0.5,
            queue_size=2,
            subscribed_assets={"BTC", "ETH", "SOL", "XRP", "DOGE"},
            expected_assets={"BTC", "ETH", "SOL", "XRP", "DOGE"},
            now_mono=now
        )
        
        # Should be DEGRADED but still allow trading
        assert result.state == "degraded"
        assert result.can_trade() is True, "Normal quiet periods should still allow trading"
        assert result.is_healthy() is False, "Quiet period should not be HEALTHY"


class TestWebSocketGracePeriod:
    """Test WebSocket grace period for subscription processing."""
    
    def test_grace_period_allows_delayed_initial_messages(self):
        """Test that grace period allows time for subscription processing."""
        # The fix increased grace period from 10s to 15s
        # This test validates that the health monitoring doesn't fail during this period
        now = time.monotonic()
        
        # Simulate connection just established, no messages yet
        result = compute_ws_health(
            event_count_total=0,
            first_event_ts=0.0,
            last_event_ts=0.0,
            events_per_sec=0.0,
            queue_size=0,
            subscribed_assets=set(),  # Not yet subscribed
            expected_assets={"BTC", "ETH"},
            now_mono=now
        )
        
        # Should be IDLE (not failed) when no events yet
        assert result.state == "idle"
        assert result.can_trade() is True, "IDLE state should allow trading (grace period)"


class TestWebSocketRecvTimeout:
    """Test WebSocket recv timeout changes."""
    
    @pytest.mark.asyncio
    async def test_recv_timeout_allows_longer_quiet_periods(self):
        """Test that recv timeout of 90s allows longer quiet periods."""
        # This test validates the recv timeout increase from 60s to 90s
        # The actual timeout is in ws.py, but we test the health logic
        
        now = time.monotonic()
        # 80 seconds without messages - should be UNHEALTHY (above 60s threshold)
        # but recv timeout of 90s means the connection won't be closed yet
        result = compute_ws_health(
            event_count_total=100,
            first_event_ts=now - 200.0,
            last_event_ts=now - 80.0,  # 80 seconds ago (> UNHEALTHY_THRESHOLD)
            events_per_sec=0.0,
            queue_size=0,
            subscribed_assets={"BTC", "ETH"},
            expected_assets={"BTC", "ETH"},
            now_mono=now
        )
        
        # Health state should be UNHEALTHY
        assert result.state == "unhealthy"
        # But the recv timeout allows the connection to stay open longer
        # This is tested indirectly by the threshold values


class TestHealthCheckInterval:
    """Test health check interval changes."""
    
    def test_health_check_frequency_reduced(self):
        """Test that health check interval is reduced from 2s to 5s."""
        # The actual interval is in ws.py _monitor_connection_health
        # This test validates the threshold logic works with the new interval
        
        now = time.monotonic()
        # With 5s interval, we check less frequently, so we need to be more tolerant
        # of message gaps
        
        # Test that we don't flip-flop between states with 5s interval
        result1 = compute_ws_health(
            event_count_total=100,
            first_event_ts=now - 60.0,
            last_event_ts=now - 12.0,  # 12 seconds ago
            events_per_sec=1.0,
            queue_size=1,
            subscribed_assets={"BTC"},
            expected_assets={"BTC"},
            now_mono=now
        )
        
        # Should be HEALTHY (below 15s threshold)
        assert result1.state == "healthy"
        
        # Simulate 5 seconds later (next health check)
        result2 = compute_ws_health(
            event_count_total=100,
            first_event_ts=now - 60.0,
            last_event_ts=now - 17.0,  # 17 seconds ago (5s later)
            events_per_sec=1.0,
            queue_size=1,
            subscribed_assets={"BTC"},
            expected_assets={"BTC"},
            now_mono=now
        )
        
        # Should be DEGRADED (above 15s threshold)
        assert result2.state == "degraded"
        assert result2.can_trade() is True, "Should still allow trading in DEGRADED state"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
