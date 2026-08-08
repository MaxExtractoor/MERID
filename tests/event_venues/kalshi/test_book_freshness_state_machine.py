"""
Test suite for Book Freshness State Machine.

Tests the layered approach to data freshness validation with explicit
states: LIVE / DEGRADED / STALE / FALLBACK / DEAD / MARKET_CLOSED.

Reference: https://eodhd.com/financial-academy/fundamental-analysis-examples/real-time-market-data-reliability-stale-price-detection-rest-fallback-and-websocket-recovery
"""

import time
import pytest
from types import SimpleNamespace
from unittest.mock import patch
from merid.event_venues.kalshi.book_freshness import (
    BookState,
    BookFreshnessState,
    BookFreshnessTracker,
    get_book_freshness_tracker,
)


class TestBookFreshnessState:
    """Test individual BookFreshnessState behavior."""
    
    def test_initial_state(self):
        """Test initial state is DEAD with no data."""
        state = BookFreshnessState()
        assert state.state == BookState.DEAD
        assert state.age_seconds == float('inf')
        assert not state.is_tradable()
        assert not state.is_healthy()
    
    def test_ws_update_with_exchange_timestamp(self):
        """Test WebSocket update with exchange timestamp marks LIVE after stability."""
        state = BookFreshnessState()
        now = time.time()
        
        # First update - should be DEGRADED (not yet stable)
        state.update_from_ws(exchange_ts=now, received_ts=now)
        assert state.state == BookState.DEGRADED
        assert state.stable_update_count == 1
        assert state.is_tradable()
        assert state.is_healthy()
        
        # Second update - still DEGRADED
        state.update_from_ws(exchange_ts=now + 0.1, received_ts=now + 0.1)
        assert state.state == BookState.DEGRADED
        assert state.stable_update_count == 2
        
        # Third update - should be LIVE (stable)
        state.update_from_ws(exchange_ts=now + 0.2, received_ts=now + 0.2)
        assert state.state == BookState.LIVE
        assert state.stable_update_count == 3
        assert state.is_tradable()
        assert state.is_healthy()
        
        # Reset state for cleanup
        state.state = BookState.DEAD
    
    def test_ws_update_missing_exchange_timestamp(self):
        """Test WebSocket update without exchange timestamp marks DEGRADED."""
        state = BookFreshnessState()
        now = time.time()
        
        state.update_from_ws(exchange_ts=None, received_ts=now)
        assert state.state == BookState.DEGRADED
        assert state.exchange_timestamp is None
        assert state.received_timestamp == now
        assert state.computed_timestamp == now
        assert state.is_tradable()  # DEGRADED is still tradable
        assert state.is_healthy()
    
    def test_rest_bootstrap(self):
        """Test REST bootstrap marks as REST_BOOTSTRAP."""
        state = BookFreshnessState()
        now = time.time()
        
        state.update_from_rest(received_ts=now, is_fallback=False)
        assert state.state == BookState.DEGRADED  # REST data is DEGRADED until stable
        assert state.source == "REST_BOOTSTRAP"
        assert state.stable_update_count == 0  # REST doesn't count toward stability
        assert state.is_tradable()
    
    def test_rest_fallback(self):
        """Test REST fallback marks as FALLBACK."""
        state = BookFreshnessState()
        now = time.time()
        
        state.update_from_rest(received_ts=now, is_fallback=True)
        assert state.state == BookState.FALLBACK
        assert state.source == "REST_FALLBACK"
        assert state.is_tradable()  # FALLBACK is still tradable
        assert not state.is_healthy()  # But not healthy
    
    def test_stale_data(self):
        """Test stale data marks as STALE."""
        state = BookFreshnessState()
        now = time.time()
        
        # Set old timestamp (beyond threshold)
        old_timestamp = now - 20.0  # 20 seconds old (threshold is 15s)
        state.update_from_ws(exchange_ts=old_timestamp, received_ts=old_timestamp)
        
        assert state.state == BookState.STALE
        assert state.age_seconds > state.staleness_threshold_seconds
        assert not state.is_tradable()
        assert not state.is_healthy()
    
    def test_connection_lost(self):
        """Test connection lost marks LIVE as DEGRADED."""
        state = BookFreshnessState()
        now = time.time()
        
        # First establish LIVE state
        for i in range(3):
            state.update_from_ws(exchange_ts=now + i * 0.1, received_ts=now + i * 0.1)
        assert state.state == BookState.LIVE
        
        # Mark connection lost
        state.mark_connection_lost()
        assert state.state == BookState.DEGRADED
        assert not state.connection_healthy
        assert state.is_tradable()  # DEGRADED is still tradable
        # CRITICAL FIX: DEGRADED with unhealthy connection is not considered healthy
        assert not state.is_healthy()
        
        # Reset state for cleanup
        state.state = BookState.DEAD  # But not healthy
    
    def test_computed_timestamp_priority(self):
        """Test computed timestamp uses exchange_timestamp over received_timestamp."""
        state = BookFreshnessState()
        now = time.time()
        
        # Update with both timestamps
        state.update_from_ws(exchange_ts=now - 1.0, received_ts=now - 0.5)
        assert state.computed_timestamp == now - 1.0  # Uses exchange timestamp
        assert state.age_seconds == 1.0  # Age based on exchange timestamp
        
        # Update with only received timestamp
        state.update_from_ws(exchange_ts=None, received_ts=now - 0.5)
        assert state.computed_timestamp == now - 0.5  # Falls back to received timestamp
        assert state.age_seconds == 0.5  # Age based on received timestamp
    
    def test_out_of_order_updates(self):
        """Test out-of-order updates are handled correctly."""
        state = BookFreshnessState()
        now = time.time()
        
        # First update with old timestamp
        state.update_from_ws(exchange_ts=now - 5.0, received_ts=now - 5.0)
        assert state.age_seconds == 5.0
        
        # Second update with newer timestamp
        state.update_from_ws(exchange_ts=now - 1.0, received_ts=now - 1.0)
        assert state.age_seconds == 1.0  # Age should reflect newest timestamp
        
        # Third update with older timestamp (should not increase age)
        state.update_from_ws(exchange_ts=now - 3.0, received_ts=now - 3.0)
        assert state.age_seconds == 3.0  # Age reflects this update
    
    def test_diagnostic_info(self):
        """Test diagnostic info returns complete state."""
        state = BookFreshnessState()
        
        # Get current time for each update to avoid negative age
        state.update_from_ws(exchange_ts=time.time(), received_ts=time.time())
        time.sleep(0.05)  # Small delay
        state.update_from_ws(exchange_ts=time.time(), received_ts=time.time())
        
        diagnostic = state.get_diagnostic_info()
        assert diagnostic["state"] == "DEGRADED"
        assert diagnostic["source"] == "WS_LIVE"
        assert diagnostic["age_seconds"] >= 0
        assert diagnostic["exchange_timestamp"] is not None
        assert diagnostic["received_timestamp"] is not None
        assert diagnostic["is_tradable"] == True
        assert diagnostic["is_healthy"] == True

        # Reset state for cleanup
        state.state = BookState.DEAD


class TestBookFreshnessRouterIntegration:
    """
    Test suite for book freshness integration with order router (CRITICAL FIX 2026-08-03).

    Tests the state-based degradation logic in the router that replaces hard fails
    with state-aware routing decisions.
    """

    def test_live_book_allows_routing(self):
        """
        Test that LIVE book state allows routing.

        Scenario: Book in LIVE state with fresh data.
        Expected: Routing proceeds without rejection.
        """
        tracker = BookFreshnessTracker()
        now = time.time()

        # Set up LIVE state
        ticker = "KXBTC15M-26AUG021345-45"
        state = tracker.get_state(ticker)
        for i in range(3):
            state.update_from_ws(exchange_ts=now + i * 0.1, received_ts=now + i * 0.1)

        # Should be LIVE
        assert state.state == BookState.LIVE
        assert state.is_tradable()
        assert state.is_healthy()

    def test_degraded_book_allows_routing(self):
        """
        Test that DEGRADED book state allows routing.

        Scenario: Book in DEGRADED state (missing exchange timestamp but fresh received timestamp).
        Expected: Routing proceeds (DEGRADED is acceptable).
        """
        tracker = BookFreshnessTracker()
        now = time.time()

        # Set up DEGRADED state (missing exchange timestamp)
        ticker = "KXETH15M-26AUG021345-45"
        state = tracker.get_state(ticker)
        state.update_from_ws(exchange_ts=None, received_ts=now)

        # Should be DEGRADED but still tradable
        assert state.state == BookState.DEGRADED
        assert state.is_tradable()
        assert state.is_healthy()

    def test_degraded_book_does_not_trigger_state_object_enum_mismatch(self):
        """
        Regression test for order_router comparing BookFreshnessState to BookState enum.

        The microstructure gate must check ``book_state.state`` (the enum) when
        deciding whether to accept LIVE/DEGRADED/FALLBACK books. Previously it
        compared the ``BookFreshnessState`` object directly to the enum values,
        which is always False, causing every order to be rejected with
        ``book_state_unacceptable:DEGRADED`` (or whatever the actual state was).
        """
        from merid.event_venues.kalshi.order_router import (
            OrderIntent,
            _validate_signal_metadata,
        )

        ticker = "KXBTC15M-26AUG021345-45"
        tracker = BookFreshnessTracker()
        state = tracker.get_state(ticker)
        state.update_from_ws(exchange_ts=None, received_ts=time.time())

        assert state.state == BookState.DEGRADED
        assert state.is_tradable()

        intent = OrderIntent(
            ticker=ticker,
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            source="merid.prediction.agent_grid_15m",
            rationale="velocity_based",
            model_prob=0.65,
            edge_pct=0.05,
            confidence=0.75,
            yes_bid_cents=95,
            yes_ask_cents=99,  # triggers degenerate-book branch
            no_bid_cents=1,
            no_ask_cents=5,
            yes_depth=100,
            no_depth=100,
        )

        mock_profile = SimpleNamespace(
            fee_aware_edge_enabled=False,
            market_microstructure_enabled=True,
            use_edge_aware_microstructure_gate=False,
            market_microstructure_max_spread_cents=20,
            market_microstructure_min_depth_usd=0.0,
            market_microstructure_min_yes_depth=1,
            market_microstructure_min_no_depth=1,
            momentum_fvg_liquidity_min_threshold=1,
        )
        mock_adapter = SimpleNamespace(profile=mock_profile)

        with patch(
            "merid.risk.profiles.crypto_15m_profile.Crypto15mProfileAdapter",
            return_value=mock_adapter,
        ), patch(
            "merid.event_venues.kalshi.order_router.check_market_microstructure",
            return_value=(True, "ok"),
        ), patch(
            "merid.event_venues.kalshi.book_freshness.get_book_freshness_tracker",
            return_value=tracker,
        ):
            result = _validate_signal_metadata(intent)

        assert result is None, (
            f"Expected _validate_signal_metadata to return None for a DEGRADED "
            f"book, but got: {result}"
        )

    def test_fallback_book_allows_routing(self):
        """
        Test that FALLBACK book state allows routing.

        Scenario: Book in FALLBACK state (REST snapshot used).
        Expected: Routing proceeds (FALLBACK is acceptable).
        """
        tracker = BookFreshnessTracker()
        now = time.time()

        # Set up FALLBACK state
        ticker = "KXSOL15M-26AUG021345-45"
        state = tracker.get_state(ticker)
        state.update_from_rest(received_ts=now, is_fallback=True)

        # Should be FALLBACK and tradable
        assert state.state == BookState.FALLBACK
        assert state.is_tradable()
        assert not state.is_healthy()  # Fallback is not healthy but is tradable

    def test_dead_book_blocks_routing(self):
        """
        Test that DEAD book state blocks routing.

        Scenario: Book in DEAD state (no data available).
        Expected: Routing is blocked (DEAD is not tradable).
        """
        tracker = BookFreshnessTracker()

        # Set up DEAD state (default state)
        ticker = "KXXRP15M-26AUG021345-45"
        state = tracker.get_state(ticker)

        # Should be DEAD and not tradable
        assert state.state == BookState.DEAD
        assert not state.is_tradable()
        assert not state.is_healthy()

    def test_market_closed_book_blocks_routing(self):
        """
        Test that MARKET_CLOSED book state blocks routing.

        Scenario: Book in MARKET_CLOSED state.
        Expected: Routing is blocked (MARKET_CLOSED is not tradable).
        """
        tracker = BookFreshnessTracker()
        now = time.time()

        # Set up MARKET_CLOSED state
        ticker = "KXDOGE15M-26AUG021345-45"
        state = tracker.get_state(ticker)
        state.source = "MARKET_CLOSED"
        state._update_state()

        # Should be MARKET_CLOSED and not tradable
        assert state.state == BookState.MARKET_CLOSED
        assert not state.is_tradable()

    def test_missing_timestamp_with_fresh_received_time_becomes_degraded(self):
        """
        Test that missing exchange timestamp with fresh received timestamp becomes DEGRADED.

        Scenario: WebSocket update without exchange timestamp but fresh received timestamp.
        Expected: State is DEGRADED (not hard fail).
        """
        tracker = BookFreshnessTracker()
        now = time.time()

        ticker = "KXBTC15M-26AUG021345-45"
        state = tracker.get_state(ticker)
        state.update_from_ws(exchange_ts=None, received_ts=now)

        # Should be DEGRADED (not DEAD)
        assert state.state == BookState.DEGRADED
        assert state.is_tradable()
        assert state.exchange_timestamp is None
        assert state.received_timestamp == now
        assert state.computed_timestamp == now

    def test_stale_book_triggers_refresh_then_uses_fallback_if_acceptable(self):
        """
        Test that stale book triggers refresh attempt.

        Scenario: Book in STALE state (age > threshold).
        Expected: State is STALE, refresh should be attempted.
        """
        tracker = BookFreshnessTracker()
        now = time.time()

        ticker = "KXETH15M-26AUG021345-45"
        state = tracker.get_state(ticker)

        # Set old timestamp (beyond threshold)
        old_timestamp = now - 20.0  # 20 seconds old (threshold is 15s)
        state.update_from_ws(exchange_ts=old_timestamp, received_ts=old_timestamp)

        # Should be STALE
        assert state.state == BookState.STALE
        assert state.age_seconds > state.staleness_threshold_seconds
        assert not state.is_tradable()

        # After refresh attempt, if fallback is acceptable, should use it
        state.update_from_rest(received_ts=now, is_fallback=True)
        assert state.state == BookState.FALLBACK
        assert state.is_tradable()

    def test_state_machine_prevents_hard_fail_on_missing_exchange_timestamp(self):
        """
        Test that state machine prevents hard fail on missing exchange timestamp.

        Scenario: Multiple updates without exchange timestamp but fresh received timestamps.
        Expected: State remains DEGRADED (acceptable), never hard fails.
        """
        tracker = BookFreshnessTracker()
        now = time.time()

        ticker = "KXBTC15M-26AUG021345-45"
        state = tracker.get_state(ticker)

        # Multiple updates without exchange timestamp
        for i in range(5):
            state.update_from_ws(exchange_ts=None, received_ts=now + i * 0.1)

        # Should remain DEGRADED (acceptable)
        assert state.state == BookState.DEGRADED
        assert state.is_tradable()
        assert state.is_healthy()

    def test_age_calculation_uses_best_available_timestamp(self):
        """
        Test that age calculation uses best available timestamp (exchange > received).

        Scenario: Both exchange and received timestamps available.
        Expected: Age is based on exchange timestamp (more accurate).
        """
        tracker = BookFreshnessTracker()
        now = time.time()

        ticker = "KXETH15M-26AUG021345-45"
        state = tracker.get_state(ticker)

        # Update with both timestamps (exchange is older)
        state.update_from_ws(exchange_ts=now - 5.0, received_ts=now - 1.0)

        # Age should be based on exchange timestamp (older)
        assert state.computed_timestamp == now - 5.0
        assert state.age_seconds == pytest.approx(5.0, abs=0.01)

        # Update with only received timestamp
        state.update_from_ws(exchange_ts=None, received_ts=now - 0.5)

        # Age should be based on received timestamp (fallback)
        assert state.computed_timestamp == now - 0.5
        assert state.age_seconds == pytest.approx(0.5, abs=0.01)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestBookFreshnessTracker:
    """Test BookFreshnessTracker behavior."""
    
    def test_per_ticker_state(self):
        """Test state is tracked per ticker."""
        tracker = BookFreshnessTracker()
        now = time.time()
        
        # Update different tickers (without lock for test simplicity)
        tracker._states["KXBTC15M-26AUG021345-45"] = BookFreshnessState()
        tracker._states["KXETH15M-26AUG021345-45"] = BookFreshnessState()
        
        tracker._states["KXBTC15M-26AUG021345-45"].update_from_ws(exchange_ts=now, received_ts=now)
        tracker._states["KXETH15M-26AUG021345-45"].update_from_ws(exchange_ts=None, received_ts=now)
        
        btc_state = tracker.get_state("KXBTC15M-26AUG021345-45")
        eth_state = tracker.get_state("KXETH15M-26AUG021345-45")
        
        # BTC should be DEGRADED (not yet stable)
        assert btc_state.state == BookState.DEGRADED
        assert btc_state.exchange_timestamp is not None
        
        # ETH should be DEGRADED (missing exchange timestamp)
        assert eth_state.state == BookState.DEGRADED
        assert eth_state.exchange_timestamp is None
    
    def test_is_tradable(self):
        """Test is_tradable reflects state."""
        tracker = BookFreshnessTracker()
        now = time.time()
        
        # Create state directly (without lock for test simplicity)
        tracker._states["KXBTC15M-26AUG021345-45"] = BookFreshnessState()
        
        # Fresh data - should be tradable
        tracker._states["KXBTC15M-26AUG021345-45"].update_from_ws(exchange_ts=now, received_ts=now)
        assert tracker.is_tradable("KXBTC15M-26AUG021345-45")
        
        # Stale data - should not be tradable
        tracker._states["KXBTC15M-26AUG021345-45"].update_from_ws(exchange_ts=now - 20.0, received_ts=now - 20.0)
        assert not tracker.is_tradable("KXBTC15M-26AUG021345-45")
    
    def test_get_all_states(self):
        """Test get_all_states returns all ticker states."""
        tracker = BookFreshnessTracker()
        now = time.time()
        
        # Create states directly (without lock for test simplicity)
        tracker._states["KXBTC15M-26AUG021345-45"] = BookFreshnessState()
        tracker._states["KXETH15M-26AUG021345-45"] = BookFreshnessState()
        
        tracker._states["KXBTC15M-26AUG021345-45"].update_from_ws(exchange_ts=now, received_ts=now)
        tracker._states["KXETH15M-26AUG021345-45"].update_from_rest(received_ts=now, is_fallback=True)
        
        all_states = tracker.get_all_states()
        assert "KXBTC15M-26AUG021345-45" in all_states
        assert "KXETH15M-26AUG021345-45" in all_states
        assert all_states["KXBTC15M-26AUG021345-45"]["source"] == "WS_LIVE"
        assert all_states["KXETH15M-26AUG021345-45"]["source"] == "REST_FALLBACK"


class TestBookFreshnessIntegration:
    """Integration tests for book freshness with market data."""
    
    def test_missing_exchange_timestamp_but_fresh_received(self):
        """Test that missing exchange timestamp but fresh received timestamp allows trading."""
        state = BookFreshnessState()
        now = time.time()
        
        # Simulate WS message without exchange timestamp but fresh received timestamp
        state.update_from_ws(exchange_ts=None, received_ts=now)
        
        assert state.state == BookState.DEGRADED
        assert state.is_tradable()  # Should still be tradable
        assert state.is_healthy()
        assert state.age_seconds < 1.0  # Fresh based on received timestamp
    
    def test_frozen_websocket_with_stale_quotes(self):
        """Test frozen WebSocket with stale quotes is detected."""
        state = BookFreshnessState()
        now = time.time()
        
        # Establish LIVE state
        for i in range(3):
            state.update_from_ws(exchange_ts=now + i * 0.1, received_ts=now + i * 0.1)
        assert state.state == BookState.LIVE
        
        # Mark connection lost explicitly
        state.mark_connection_lost()
        
        assert state.state == BookState.DEGRADED
        assert not state.connection_healthy
        assert state.is_tradable()  # Still tradable if data is fresh
        assert not state.is_healthy()  # But not healthy due to connection issue
    
    def test_rest_fallback_labeling(self):
        """Test REST fallback is properly labeled."""
        state = BookFreshnessState()
        now = time.time()
        
        # REST fallback should be labeled as such
        state.update_from_rest(received_ts=now, is_fallback=True)
        
        assert state.state == BookState.FALLBACK
        assert state.source == "REST_FALLBACK"
        assert state.is_tradable()  # FALLBACK is tradable
        assert not state.is_healthy()  # But not healthy


if __name__ == "__main__":
    pytest.main([__file__, "-v"])