"""
Test for BUG #1: WebSocket Forwarder Impossible-OK Violation Fix

Tests the improved WS forwarder invariant check with:
- Subscription validation
- REST fallback logic
- Degraded mode support
"""

import pytest
from unittest.mock import Mock
from merid.event_venues.kalshi.health_snapshot import check_ws_forwarder_impossible_ok


class TestWSForwarderBugFix:
    """Test suite for WS forwarder impossible-OK bug fix."""
    
    def test_subscription_violation_detected(self):
        """Test that missing subscriptions are detected as violations."""
        # Setup: WS connected but no subscriptions
        ws_stats = {
            "ws_connected": True,
            "ws_healthy": True,
            "ws_raw_messages_seen": 0,
            "ws_events_enqueued": 0,
            "ws_forwarder_events_processed": 0,
            "time_since_last_event": 15.0,  # > 10s grace period
            "events_per_sec": 0.0,
            "markets": []  # No subscriptions
        }
        
        states = {}  # No market states
        
        # Test: Should fail invariant due to subscription violation
        result = check_ws_forwarder_impossible_ok(loop_tick=10, ws_stats=ws_stats, states=states)
        assert result == False, "Should detect subscription violation"
    
    def test_subscription_grace_period(self):
        """Test that subscription check has 10s grace period."""
        # Setup: WS connected but no subscriptions, but within grace period
        ws_stats = {
            "ws_connected": True,
            "ws_healthy": True,
            "ws_raw_messages_seen": 0,
            "ws_events_enqueued": 0,
            "ws_forwarder_events_processed": 0,
            "time_since_last_event": 5.0,  # < 10s grace period
            "events_per_sec": 0.0,
            "markets": []  # No subscriptions
        }
        
        states = {}
        
        # Test: Should pass due to grace period
        result = check_ws_forwarder_impossible_ok(loop_tick=10, ws_stats=ws_stats, states=states)
        assert result == True, "Should allow grace period for subscription setup"
    
    def test_rest_fallback_allows_degraded_mode(self):
        """Test that REST fallback allows degraded mode when WS is stalled."""
        # Setup: WS stalled but REST is healthy
        ws_stats = {
            "ws_connected": True,
            "ws_healthy": True,
            "ws_raw_messages_seen": 0,
            "ws_events_enqueued": 0,
            "ws_forwarder_events_processed": 0,
            "time_since_last_event": 35.0,  # > 30s threshold
            "events_per_sec": 0.0,
            "markets": ["KXBTC15M-26JUN102130-30"]  # Has subscriptions
        }
        
        # Mock state with healthy REST transport
        rest_state = Mock()
        rest_state.transport_mode = "rest"
        rest_state.transport_stale = False
        
        states = {"KXBTC15M-26JUN102130-30": rest_state}
        
        # Test: Should pass invariant due to REST fallback
        result = check_ws_forwarder_impossible_ok(loop_tick=10, ws_stats=ws_stats, states=states)
        assert result == True, "Should allow degraded mode with REST fallback"
    
    def test_no_rest_fallback_fails_invariant(self):
        """Test that invariant fails when both WS and REST are degraded."""
        # Setup: WS stalled and no REST fallback
        ws_stats = {
            "ws_connected": True,
            "ws_healthy": True,
            "ws_raw_messages_seen": 0,
            "ws_events_enqueued": 0,
            "ws_forwarder_events_processed": 0,
            "time_since_last_event": 35.0,  # > 30s threshold
            "events_per_sec": 0.0,
            "markets": ["KXBTC15M-26JUN102130-30"]
        }
        
        # Mock state with stale REST transport
        rest_state = Mock()
        rest_state.transport_mode = "rest"
        rest_state.transport_stale = True  # REST is also stale
        
        states = {"KXBTC15M-26JUN102130-30": rest_state}
        
        # Test: Should fail invariant
        result = check_ws_forwarder_impossible_ok(loop_tick=10, ws_stats=ws_stats, states=states)
        assert result == False, "Should fail when both WS and REST are degraded"
    
    def test_healthy_ws_passes_invariant(self):
        """Test that healthy WS passes invariant."""
        # Setup: WS is healthy with activity
        ws_stats = {
            "ws_connected": True,
            "ws_healthy": True,
            "ws_raw_messages_seen": 100,
            "ws_events_enqueued": 95,
            "ws_forwarder_events_processed": 90,
            "time_since_last_event": 1.0,
            "events_per_sec": 5.0,
            "markets": ["KXBTC15M-26JUN102130-30"]
        }
        
        # Mock state with healthy WS transport
        ws_state = Mock()
        ws_state.transport_mode = "ws"
        ws_state.transport_stale = False
        
        states = {"KXBTC15M-26JUN102130-30": ws_state}
        
        # Test: Should pass invariant
        result = check_ws_forwarder_impossible_ok(loop_tick=10, ws_stats=ws_stats, states=states)
        assert result == True, "Healthy WS should pass invariant"
    
    def test_warmup_period_always_passes(self):
        """Test that warmup period (first 3 ticks) always passes."""
        # Setup: Even with violations, warmup should pass
        ws_stats = {
            "ws_connected": True,
            "ws_healthy": True,
            "ws_raw_messages_seen": 0,
            "ws_events_enqueued": 0,
            "ws_forwarder_events_processed": 0,
            "time_since_last_event": 100.0,
            "events_per_sec": 0.0,
            "markets": []
        }
        
        states = {}
        
        # Test: Should pass during warmup
        for tick in [0, 1, 2]:
            result = check_ws_forwarder_impossible_ok(loop_tick=tick, ws_stats=ws_stats, states=states)
            assert result == True, f"Should pass during warmup tick {tick}"
    
    def test_ws_not_connected_passes(self):
        """Test that invariant passes when WS is not connected."""
        # Setup: WS not connected
        ws_stats = {
            "ws_connected": False,
            "ws_healthy": False,
            "ws_raw_messages_seen": 0,
            "ws_events_enqueued": 0,
            "ws_forwarder_events_processed": 0,
            "time_since_last_event": 0.0,
            "events_per_sec": 0.0,
            "markets": []
        }
        
        states = {}
        
        # Test: Should pass when WS not connected
        result = check_ws_forwarder_impossible_ok(loop_tick=10, ws_stats=ws_stats, states=states)
        assert result == True, "Should pass when WS not connected"
    
    def test_counter_violation_detected(self):
        """Test that counter violations are detected."""
        # Setup: WS claims healthy but counters don't match
        ws_stats = {
            "ws_connected": True,
            "ws_healthy": True,
            "ws_raw_messages_seen": 100,  # Raw seen
            "ws_events_enqueued": 0,  # But nothing enqueued
            "ws_forwarder_events_processed": 0,  # And nothing processed
            "time_since_last_event": 1.0,
            "events_per_sec": 5.0,
            "markets": ["KXBTC15M-26JUN102130-30"]
        }
        
        # Mock state with healthy WS transport
        ws_state = Mock()
        ws_state.transport_mode = "ws"
        ws_state.transport_stale = False
        
        states = {"KXBTC15M-26JUN102130-30": ws_state}
        
        # Test: Should fail due to counter violation
        result = check_ws_forwarder_impossible_ok(loop_tick=10, ws_stats=ws_stats, states=states)
        assert result == False, "Should detect counter violation"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
