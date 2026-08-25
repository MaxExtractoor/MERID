"""
Combined Smoke Test for MD Age + WS Health Integration

End-to-end test that validates both MD age normalization and WS health
monitoring work together correctly in a realistic 15m trading scenario.
"""

import time
import pytest
from unittest.mock import Mock, patch

from merid.core.md_age_helpers import compute_md_age, MDAgeResult
from merid.core.ws_health_helpers import compute_ws_health, WSHealthResult


class TestMDWSIntegrationSmoke:
    """Combined smoke test for MD age and WS health integration."""
    
    def test_scenario_healthy_trading_session(self):
        """Test scenario: Healthy trading session with fresh MD and active WS."""
        now = time.monotonic()
        
        # Simulate healthy market state
        market_state = Mock()
        market_state.last_book_update_ts = now - 30.0  # 30 seconds ago (fresh)
        
        # Simulate healthy WebSocket state
        ws_health = compute_ws_health(
            event_count_total=100,
            first_event_ts=now - 300.0,  # Started 5 minutes ago
            last_event_ts=now - 2.0,     # Last event 2 seconds ago
            events_per_sec=2.5,
            queue_size=1,
            subscribed_assets={"BTC", "ETH", "SOL", "XRP", "DOGE"},
            expected_assets={"BTC", "ETH", "SOL", "XRP", "DOGE"},
            now_mono=now
        )
        
        # Compute MD age
        md_result = compute_md_age(market_state, now_mono=now)
        
        # Assertions: Both systems should report healthy state
        assert md_result.status == "fresh"
        assert md_result.is_stale() is False
        assert md_result.has_data() is True
        assert 25 <= md_result.age_s <= 35  # Allow some timing variance
        
        assert ws_health.state == "healthy"
        assert ws_health.stalled is False
        assert ws_health.is_healthy() is True
        assert ws_health.has_events() is True
        assert ws_health.is_processing() is True
        assert ws_health.subscription_coverage["coverage_complete"] is True
        
        # No impossible ages or stalled states
        assert md_result.status != "impossible"
        assert ws_health.state != "stalled"
    
    def test_scenario_startup_idle_transition(self):
        """Test scenario: Startup with idle WS transitioning to healthy."""
        now = time.monotonic()
        
        # Phase 1: Initial startup (idle WS, no MD yet)
        ws_health_idle = compute_ws_health(
            event_count_total=0,
            first_event_ts=0.0,
            last_event_ts=0.0,
            events_per_sec=0.0,
            queue_size=0,
            subscribed_assets=set(),
            expected_assets={"BTC", "ETH", "SOL", "XRP", "DOGE"},
            now_mono=now
        )
        
        market_state_no_data = None
        md_result_no_data = compute_md_age(market_state_no_data, now_mono=now)
        
        # Initial state should be idle/no-data but not failed
        assert ws_health_idle.state == "idle"
        assert ws_health_idle.is_healthy() is True  # Idle is acceptable
        assert ws_health_idle.has_events() is False
        
        assert md_result_no_data.status == "no_data"
        assert md_result_no_data.is_stale() is True  # No data is considered stale
        assert md_result_no_data.has_data() is False
        
        # Phase 2: WS starts receiving events, MD still no data
        ws_health_starting = compute_ws_health(
            event_count_total=5,
            first_event_ts=now - 10.0,
            last_event_ts=now - 1.0,
            events_per_sec=0.5,
            queue_size=2,
            subscribed_assets={"BTC"},  # Partial subscription
            expected_assets={"BTC", "ETH", "SOL", "XRP", "DOGE"},
            now_mono=now
        )
        
        assert ws_health_starting.state == "healthy"
        assert ws_health_starting.is_healthy() is True
        assert ws_health_starting.has_events() is True
        assert ws_health_starting.subscription_coverage["coverage_complete"] is False
        
        # Phase 3: MD arrives and becomes fresh
        market_state_fresh = Mock()
        market_state_fresh.last_book_update_ts = now - 15.0
        
        md_result_fresh = compute_md_age(market_state_fresh, now_mono=now)
        
        assert md_result_fresh.status == "fresh"
        assert md_result_fresh.is_stale() is False
        assert md_result_fresh.has_data() is True
        
        # Final state: Both systems healthy
        assert ws_health_starting.is_healthy() and md_result_fresh.is_fresh()
    
    def test_scenario_ws_stalled_with_fresh_md(self):
        """Test scenario: WS stalled but MD is still fresh (edge case)."""
        now = time.monotonic()
        
        # Fresh market data
        market_state = Mock()
        market_state.last_book_update_ts = now - 20.0  # Fresh
        
        md_result = compute_md_age(market_state, now_mono=now)
        assert md_result.status == "fresh"
        
        # Degraded WebSocket (no events for >15s, <60s)
        ws_health_stalled = compute_ws_health(
            event_count_total=50,
            first_event_ts=now - 300.0,
            last_event_ts=now - 45.0,  # 45 seconds ago (degraded)
            events_per_sec=0.0,
            queue_size=0,
            subscribed_assets={"BTC", "ETH", "SOL", "XRP", "DOGE"},
            expected_assets={"BTC", "ETH", "SOL", "XRP", "DOGE"},
            now_mono=now
        )
        
        assert ws_health_stalled.state == "degraded"
        assert ws_health_stalled.stalled is False
        assert ws_health_stalled.is_healthy() is False
        
        # This scenario should be detected as problematic
        # MD is fresh but WS is stalled - indicates MD is coming from REST fallback
        assert md_result.is_fresh() and not ws_health_stalled.is_healthy()
    
    def test_scenario_md_impossible_age_detection(self):
        """Test scenario: Detection of impossible MD ages (timebase mismatch)."""
        now = time.monotonic()
        
        # Simulate timebase mismatch: Unix timestamp in monotonic field
        market_state_corrupted = Mock()
        market_state_corrupted.last_book_update_ts = 1_750_000_000.0  # Unix timestamp
        
        md_result = compute_md_age(market_state_corrupted, now_mono=now)
        
        # Should detect impossible age and handle gracefully
        assert md_result.status == "impossible"
        assert md_result.is_stale() is True
        assert md_result.has_data() is True  # Has timestamp but corrupted
        assert "IMPOSSIBLE_AGE" in md_result.reason
        
        # WS should still be healthy independently
        ws_health = compute_ws_health(
            event_count_total=10,
            first_event_ts=now - 60.0,
            last_event_ts=now - 5.0,
            events_per_sec=1.0,
            queue_size=0,
            subscribed_assets={"BTC"},
            expected_assets={"BTC"},
            now_mono=now
        )
        
        assert ws_health.state == "healthy"
        assert ws_health.is_healthy() is True
        
        # Overall system should detect MD issue despite healthy WS
        assert md_result.status == "impossible" and ws_health.state == "healthy"
    
    def test_scenario_ws_idle_too_long_warning(self):
        """Test scenario: WS idle for too long (potential wiring issue)."""
        now = time.monotonic()
        
        # WS idle for extended period
        ws_health_idle_long = compute_ws_health(
            event_count_total=0,
            first_event_ts=0.0,
            last_event_ts=0.0,
            events_per_sec=0.0,
            queue_size=0,
            subscribed_assets=set(),
            expected_assets={"BTC", "ETH", "SOL", "XRP", "DOGE"},
            now_mono=now
        )
        
        assert ws_health_idle_long.state == "idle"
        assert ws_health_idle_long.is_healthy() is True  # Idle is technically healthy
        
        # But system should detect this as problematic for extended periods
        # (This would be handled by higher-level monitoring)
        assert ws_health_idle_long.event_count_total == 0
        assert ws_health_idle_long.time_since_last_event is None
    
    def test_execution_readiness_integration(self):
        """Test execution readiness logic combining both health signals."""
        now = time.monotonic()
        
        # Simulate execution readiness check combining MD and WS health
        def is_execution_ready(md_result: MDAgeResult, ws_health: WSHealthResult) -> tuple[bool, str]:
            """Combined execution readiness check."""
            reasons = []
            
            # MD freshness check
            if md_result.is_stale():
                reasons.append(f"MD_{md_result.status.upper()}")
            
            # WS health check
            if not ws_health.is_healthy():
                reasons.append(f"WS_{ws_health.state.upper()}")
            
            # Coverage check
            if not ws_health.subscription_coverage["coverage_complete"]:
                reasons.append("COVERAGE_INCOMPLETE")
            
            is_ready = len(reasons) == 0
            return is_ready, ";".join(reasons) if reasons else "READY"
        
        # Test 1: Everything ready
        md_fresh = compute_md_age(Mock(last_book_update_ts=now - 10.0), now_mono=now)
        ws_healthy = compute_ws_health(
            event_count_total=10, first_event_ts=now-60, last_event_ts=now-2,
            events_per_sec=1.0, queue_size=0,
            subscribed_assets={"BTC", "ETH"}, expected_assets={"BTC", "ETH"},
            now_mono=now
        )
        
        ready, reason = is_execution_ready(md_fresh, ws_healthy)
        assert ready is True
        assert reason == "READY"
        
        # Test 2: MD stale
        md_stale = compute_md_age(Mock(last_book_update_ts=now - 200.0), now_mono=now)
        ready, reason = is_execution_ready(md_stale, ws_healthy)
        assert ready is False
        assert "MD_STALE" in reason
        
        # Test 3: WS degraded (no events for >15s, <60s)
        ws_stalled = compute_ws_health(
            event_count_total=10, first_event_ts=now-60, last_event_ts=now-40,
            events_per_sec=0.0, queue_size=0,
            subscribed_assets={"BTC"}, expected_assets={"BTC"},
            now_mono=now
        )
        ready, reason = is_execution_ready(md_fresh, ws_stalled)
        assert ready is False
        assert "WS_DEGRADED" in reason
        
        # Test 4: Coverage incomplete
        ws_partial = compute_ws_health(
            event_count_total=5, first_event_ts=now-30, last_event_ts=now-5,
            events_per_sec=0.5, queue_size=1,
            subscribed_assets={"BTC"}, expected_assets={"BTC", "ETH"},
            now_mono=now
        )
        ready, reason = is_execution_ready(md_fresh, ws_partial)
        assert ready is False
        assert "COVERAGE_INCOMPLETE" in reason


class TestSmokeTestScenarios:
    """Real-world smoke test scenarios."""
    
    def test_15m_trading_session_simulation(self):
        """Simulate a realistic 15m trading session timeline."""
        start_time = time.monotonic()
        
        # Phase 1: Startup (0-30s)
        # System starts, no events, no MD
        ws_phase1 = compute_ws_health(
            event_count_total=0, first_event_ts=0.0, last_event_ts=0.0,
            events_per_sec=0.0, queue_size=0,
            subscribed_assets=set(), expected_assets={"BTC", "ETH", "SOL", "XRP", "DOGE"},
            now_mono=start_time + 15
        )
        md_phase1 = compute_md_age(None, now_mono=start_time + 15)
        
        assert ws_phase1.state == "idle"
        assert md_phase1.status == "no_data"
        
        # Phase 2: WS Connection (30-60s)
        # WebSocket connects, starts receiving events
        ws_phase2 = compute_ws_health(
            event_count_total=20, first_event_ts=start_time + 30, last_event_ts=start_time + 55,
            events_per_sec=1.0, queue_size=2,
            subscribed_assets={"BTC", "ETH"}, expected_assets={"BTC", "ETH", "SOL", "XRP", "DOGE"},
            now_mono=start_time + 60
        )
        
        assert ws_phase2.state == "healthy"
        assert ws_phase2.subscription_coverage["coverage_complete"] is False
        
        # Phase 3: MD Arrival (60-90s)
        # Market data starts arriving
        market_state = Mock()
        market_state.last_book_update_ts = start_time + 75
        md_phase3 = compute_md_age(market_state, now_mono=start_time + 90)
        
        assert md_phase3.status == "fresh"
        
        # Phase 4: Full Operation (90-300s)
        # All systems operational
        ws_phase4 = compute_ws_health(
            event_count_total=200, first_event_ts=start_time + 30, last_event_ts=start_time + 295,
            events_per_sec=2.5, queue_size=1,
            subscribed_assets={"BTC", "ETH", "SOL", "XRP", "DOGE"},
            expected_assets={"BTC", "ETH", "SOL", "XRP", "DOGE"},
            now_mono=start_time + 300
        )
        # Update market state to keep it fresh (MD should be regularly updated)
        market_state.last_book_update_ts = start_time + 280  # 20 seconds ago (fresh)
        md_phase4 = compute_md_age(market_state, now_mono=start_time + 300)
        
        assert ws_phase4.state == "healthy"
        assert ws_phase4.subscription_coverage["coverage_complete"] is True
        assert md_phase4.status == "fresh"
        
        # Verify no impossible ages or stalls occurred
        assert md_phase4.status != "impossible"
        assert ws_phase4.state != "stalled"
        
        # Verify consistent timebase usage
        assert 0 <= md_phase4.age_s <= 300  # Should be reasonable
        assert ws_phase4.time_since_last_event <= 30  # Should be recent


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
