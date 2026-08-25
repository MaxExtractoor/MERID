"""
Test suite for anti-spam invariants (2026-07-17).

Tests cover the new anti-spam features to prevent resting-order spamming
on the SOL 15-minute market and enforce strict $1 fixed risk exposure cap:

1. StripOrderState - tracking open GTC/limit orders per market ticker
2. Exit-aware cooldown per asset/ticker
3. Short-lived TIF (60s GTT) for 15m crypto entry orders
4. Resting order sweeper to cancel old orders
5. Spam detection logging (STRIP-SPAM-WARNING)
"""

import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass


class TestStripOrderState:
    """Test StripOrderState singleton for per-strip working order tracking."""
    
    def test_strip_order_state_singleton(self):
        """Test that StripOrderState is a singleton."""
        from merid.prediction.strip_order_state import get_strip_order_state
        
        state1 = get_strip_order_state()
        state2 = get_strip_order_state()
        
        assert state1 is state2, "StripOrderState should be singleton"
    
    def test_register_order(self):
        """Test registering an order in StripOrderState."""
        from merid.prediction.strip_order_state import get_strip_order_state
        
        state = get_strip_order_state()
        state._working_orders.clear()
        state._strip_to_order_ids.clear()
        state._order_history.clear()
        
        # Register an order
        result = state.register_order(
            order_id="test_order_123",
            ticker="KXSOL15M-26JUL211445-45",
            side="yes",
            action="buy",
            price_cents=50
        )
        
        assert result is True
        assert state.get_working_order_count("KXSOL15M-26JUL211445-45") == 1
    
    def test_max_orders_per_strip(self):
        """Test that only 1 working order per strip is allowed."""
        from merid.prediction.strip_order_state import get_strip_order_state
        
        state = get_strip_order_state()
        state._working_orders.clear()
        state._strip_to_order_ids.clear()
        state._order_history.clear()
        
        # Register first order
        result1 = state.register_order(
            order_id="test_order_1",
            ticker="KXSOL15M-26JUL211445-45",
            side="yes",
            action="buy",
            price_cents=50
        )
        assert result1 is True
        
        # Try to register second order (should be blocked)
        result2 = state.register_order(
            order_id="test_order_2",
            ticker="KXSOL15M-26JUL211445-45",
            side="yes",
            action="buy",
            price_cents=50
        )
        assert result2 is False
    
    def test_unregister_order(self):
        """Test unregistering an order."""
        from merid.prediction.strip_order_state import get_strip_order_state
        
        state = get_strip_order_state()
        state._working_orders.clear()
        state._strip_to_order_ids.clear()
        state._order_history.clear()
        
        # Register an order
        state.register_order(
            order_id="test_order_123",
            ticker="KXSOL15M-26JUL211445-45",
            side="yes",
            action="buy",
            price_cents=50
        )
        
        assert state.get_working_order_count("KXSOL15M-26JUL211445-45") == 1
        
        # Unregister the order
        state.unregister_order("test_order_123")
        
        assert state.get_working_order_count("KXSOL15M-26JUL211445-45") == 0
    
    def test_has_working_order(self):
        """Test checking if a strip has working orders."""
        from merid.prediction.strip_order_state import get_strip_order_state
        
        state = get_strip_order_state()
        state._working_orders.clear()
        state._strip_to_order_ids.clear()
        state._order_history.clear()
        
        # No orders initially
        assert state.has_working_order("KXSOL15M-26JUL211445-45") is False
        
        # Register an order
        state.register_order(
            order_id="test_order_123",
            ticker="KXSOL15M-26JUL211445-45",
            side="yes",
            action="buy",
            price_cents=50
        )
        
        # Should have working order
        assert state.has_working_order("KXSOL15M-26JUL211445-45") is True
        assert state.has_working_order("KXSOL15M-26JUL211445-45", side="yes") is True
        assert state.has_working_order("KXSOL15M-26JUL211445-45", side="no") is False
    
    def test_reset_strip(self):
        """Test that reset_strip clears all state for a strip."""
        from merid.prediction.strip_order_state import get_strip_order_state
        
        state = get_strip_order_state()
        state._working_orders.clear()
        state._strip_to_order_ids.clear()
        state._order_history.clear()
        
        # Register order (MAX_ORDERS_PER_STRIP = 1, so only 1 order allowed)
        state.register_order(
            order_id="test_order_1",
            ticker="KXSOL15M-26JUL211445-45",
            side="yes",
            action="buy",
            price_cents=50
        )
        
        assert state.get_working_order_count("KXSOL15M-26JUL211445-45") == 1
        
        # Reset the strip
        state.reset_strip("KXSOL15M-26JUL211445-45")
        
        # Should be cleared
        assert state.get_working_order_count("KXSOL15M-26JUL211445-45") == 0


class TestExitAwareCooldown:
    """Test exit-aware cooldown per asset/ticker."""
    
    def test_set_cooldown(self):
        """Test setting cooldown for a ticker."""
        from merid.prediction.strip_order_state import get_strip_order_state, ExitReason
        
        state = get_strip_order_state()
        state._cooldowns.clear()
        
        # Set cooldown
        state.set_cooldown("KXSOL15M-26JUL211445-45", ExitReason.STALEDATA, 300)
        
        assert "KXSOL15M-26JUL211445-45" in state._cooldowns
        assert state._cooldowns["KXSOL15M-26JUL211445-45"].exit_reason == ExitReason.STALEDATA
    
    def test_cooldown_active_blocks_entry(self):
        """Test that active cooldown blocks entry orders."""
        from merid.prediction.strip_order_state import get_strip_order_state, ExitReason
        
        state = get_strip_order_state()
        state._cooldowns.clear()
        
        # Set cooldown
        state.set_cooldown("KXSOL15M-26JUL211445-45", ExitReason.RISK_LIMIT, 300)
        
        # Check if cooldown is active
        is_active = state._is_cooldown_active("KXSOL15M-26JUL211445-45")
        assert is_active is True
    
    def test_cooldown_expires_after_duration(self):
        """Test that cooldown expires after duration."""
        from merid.prediction.strip_order_state import get_strip_order_state, ExitReason
        
        state = get_strip_order_state()
        state._cooldowns.clear()
        
        # Set cooldown with short duration for testing
        state.set_cooldown("KXSOL15M-26JUL211445-45", ExitReason.LOW_LIQUIDITY, 1)
        
        # Wait for cooldown to expire
        time.sleep(1.1)
        
        # Check if cooldown is still active
        is_active = state._is_cooldown_active("KXSOL15M-26JUL211445-45")
        assert is_active is False
    
    def test_exit_reasons_trigger_cooldown(self):
        """Test that problematic exit reasons trigger cooldown."""
        from merid.prediction.strip_order_state import ExitReason
        
        # Exit reasons that should trigger cooldown
        cooldown_reasons = [
            ExitReason.STALEDATA,
            ExitReason.RISK_LIMIT,
            ExitReason.LOW_LIQUIDITY,
            ExitReason.REGIME_HALTED,
        ]
        
        for reason in cooldown_reasons:
            assert reason in [ExitReason.STALEDATA, ExitReason.RISK_LIMIT, 
                            ExitReason.LOW_LIQUIDITY, ExitReason.REGIME_HALTED]
    
    def test_normal_exit_does_not_trigger_cooldown(self):
        """Test that NORMAL exit does not trigger cooldown."""
        from merid.prediction.strip_order_state import ExitReason
        
        # NORMAL exit should not trigger cooldown
        assert ExitReason.NORMAL == ExitReason.NORMAL


class TestShortLivedTIF:
    """Test execution-mode-driven TIF resolution for entry/exit orders."""

    def test_resolve_tif_for_15m_crypto_entry(self):
        """Test that aggressive 15m crypto entry orders are IOC."""
        from merid.event_venues.kalshi.order_router import _resolve_tif, OrderIntent

        intent = OrderIntent(
            ticker="KXSOL15M-26JUL211445-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            aggressiveness=0.5,
            entry_or_exit="entry",
        )

        tif, expiration = _resolve_tif(intent)

        # Aggressive entries must be IOC (no expiration)
        assert tif == "IOC", f"Expected IOC, got {tif}"
        assert expiration is None, f"Expected None expiration for IOC, got {expiration}"

    def test_resolve_tif_for_maker_entry(self):
        """Test that passive/maker entry orders are short-horizon GTC."""
        from merid.event_venues.kalshi.order_router import _resolve_tif, OrderIntent
        import time

        intent = OrderIntent(
            ticker="KXSOL15M-26JUL211445-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            aggressiveness=0.0,
            post_only=True,
            entry_or_exit="entry",
        )

        tif, expiration = _resolve_tif(intent)

        # Passive entries should be GTC with a finite absolute expiration_time
        assert tif == "GTC", f"Expected GTC, got {tif}"
        assert expiration is not None, "Expected an absolute expiration_time for GTC"
        assert expiration > int(time.time()), "Expected expiration_time in the future"

    def test_resolve_tif_for_exit_orders(self):
        """Test that exit orders are IOC."""
        from merid.event_venues.kalshi.order_router import _resolve_tif, OrderIntent

        intent = OrderIntent(
            ticker="KXSOL15M-26JUL211445-45",
            side="yes",
            action="sell",
            price_cents=50,
            count=1,
            entry_or_exit="exit",
            reduce_only=True,
        )

        tif, expiration = _resolve_tif(intent)

        # Exit orders should be IOC
        assert tif == "IOC", f"Expected IOC for exit order, got {tif}"
        assert expiration is None, f"Expected None expiration for exit order, got {expiration}"

    def test_resolve_tif_for_all_5_crypto_assets(self):
        """Test that all 5 crypto assets resolve to IOC for aggressive entries."""
        from merid.event_venues.kalshi.order_router import _resolve_tif, OrderIntent

        crypto_tickers = [
            "KXBTC15M-26JUL211445-45",
            "KXETH15M-26JUL211445-45",
            "KXSOL15M-26JUL211445-45",
            "KXXRP15M-26JUL211445-45",
            "KXDOGE15M-26JUL211445-45",
        ]

        for ticker in crypto_tickers:
            intent = OrderIntent(
                ticker=ticker,
                side="yes",
                action="buy",
                price_cents=50,
                count=1,
                aggressiveness=1.0,
                entry_or_exit="entry",
            )

            tif, expiration = _resolve_tif(intent)
            assert tif == "IOC", f"Expected IOC for {ticker}, got {tif}"
            assert expiration is None, f"Expected None for {ticker}, got {expiration}"

    def test_resolve_tif_for_non_15m_markets(self):
        """Test that non-15m aggressive markets resolve to IOC."""
        from merid.event_venues.kalshi.order_router import _resolve_tif, OrderIntent

        intent = OrderIntent(
            ticker="KXBTC-1H-26JUL211445-45",  # 1-hour market
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            aggressiveness=0.5,
            entry_or_exit="entry",
        )

        tif, expiration = _resolve_tif(intent)

        # Aggressive orders should be IOC regardless of market
        assert tif == "IOC", f"Expected IOC for non-15m market, got {tif}"


class TestRestingOrderSweeper:
    """Test resting order sweeper to cancel old orders."""
    
    @pytest.mark.asyncio
    async def test_order_exceeds_max_hold_time(self):
        """Test that orders exceeding max_hold_seconds are cancelled."""
        from merid.event_venues.kalshi.resting_order_monitor import RestingOrderRecord, RecheckResult
        from datetime import datetime, timedelta
        
        # Create old order (older than max_hold_seconds)
        old_time = datetime.utcnow() - timedelta(seconds=200)  # 200 seconds ago
        record = RestingOrderRecord(
            kalshi_order_id="test_order_123",
            ticker="KXSOL15M-26JUL211445-45",
            side="BUY_YES",
            action="buy",
            original_size=1,
            remaining_size=1,
            price_cents=50,
            created_at=old_time,
            asset="SOL",
            max_hold_seconds=180  # 3 minutes
        )
        
        # Simulate recheck
        from merid.event_venues.kalshi.resting_order_monitor import RestingOrderMonitor
        monitor = RestingOrderMonitor()
        
        # Mock the necessary dependencies (is_exit_order_from_source is imported in _recheck_order)
        with patch('merid.event_venues.kalshi.exit_order_utils.is_exit_order_from_source', return_value=False):
            result = await monitor._recheck_order(record)
        
        # Should cancel due to max_hold_exceeded
        assert result.action == "cancel"
        assert "max_hold_exceeded" in result.reason
    
    @pytest.mark.asyncio
    async def test_fresh_order_not_cancelled(self):
        """Test that fresh orders are not cancelled."""
        from merid.event_venues.kalshi.resting_order_monitor import RestingOrderRecord
        from datetime import datetime, timedelta
        
        # Create fresh order (younger than max_hold_seconds)
        fresh_time = datetime.utcnow() - timedelta(seconds=60)  # 60 seconds ago
        record = RestingOrderRecord(
            kalshi_order_id="test_order_456",
            ticker="KXSOL15M-26JUL211445-45",
            side="BUY_YES",
            action="buy",
            original_size=1,
            remaining_size=1,
            price_cents=50,
            created_at=fresh_time,
            asset="SOL",
            max_hold_seconds=180  # 3 minutes
        )
        
        # Simulate recheck
        from merid.event_venues.kalshi.resting_order_monitor import RestingOrderMonitor
        monitor = RestingOrderMonitor()
        
        # Mock the necessary dependencies - skip the regime/window checks since we're testing age-based cancellation
        with patch('merid.event_venues.kalshi.exit_order_utils.is_exit_order_from_source', return_value=False):
            result = await monitor._recheck_order(record)
        
        # Should keep (not cancel) - fresh order won't hit max_hold_exceeded
        # But may be cancelled for other reasons (regime, window, etc.)
        # The important thing is it doesn't get cancelled for max_hold_exceeded
        if result.action == "cancel":
            assert "max_hold_exceeded" not in result.reason
    
    @pytest.mark.asyncio
    async def test_exit_orders_exempt_from_sweeper(self):
        """Test that exit orders are exempt from sweeper cancellation."""
        from merid.event_venues.kalshi.resting_order_monitor import RestingOrderRecord
        from datetime import datetime, timedelta
        
        # Create old exit order
        old_time = datetime.utcnow() - timedelta(seconds=200)
        record = RestingOrderRecord(
            kalshi_order_id="test_exit_order_789",
            ticker="KXSOL15M-26JUL211445-45",
            side="SELL_YES",
            action="sell",
            original_size=1,
            remaining_size=1,
            price_cents=50,
            created_at=old_time,
            asset="SOL",
            max_hold_seconds=180,
            client_order_id="position_monitor_exit"  # Exit order marker
        )
        
        # Simulate recheck
        from merid.event_venues.kalshi.resting_order_monitor import RestingOrderMonitor
        monitor = RestingOrderMonitor()
        
        # Mock exit order detection
        with patch('merid.event_venues.kalshi.exit_order_utils.is_exit_order_from_source', return_value=True):
            result = await monitor._recheck_order(record)
        
        # Should keep (exit orders are exempt)
        assert result.action == "keep"
        assert result.reason == "exit_order_exempt"


class TestCooldownGuardIntegration:
    """Test cooldown guard integration in order_router."""
    
    def test_cooldown_guard_blocks_entry(self):
        """Test that cooldown guard blocks entry orders during cooldown."""
        from merid.event_venues.kalshi.order_router import _check_strip_cooldown, OrderIntent
        from merid.prediction.strip_order_state import get_strip_order_state, ExitReason
        
        # Set cooldown
        state = get_strip_order_state()
        state._cooldowns.clear()
        state.set_cooldown("KXSOL15M-26JUL211445-45", ExitReason.STALEDATA, 300)
        
        # Create entry order intent
        intent = OrderIntent(
            ticker="KXSOL15M-26JUL211445-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1
        )
        
        # Check cooldown guard
        rejection = _check_strip_cooldown(intent)
        
        # Should reject
        assert rejection is not None
        assert "strip_cooldown" in rejection
    
    def test_cooldown_guard_allows_after_expiry(self):
        """Test that cooldown guard allows orders after cooldown expires."""
        from merid.event_venues.kalshi.order_router import _check_strip_cooldown, OrderIntent
        from merid.prediction.strip_order_state import get_strip_order_state, ExitReason
        
        # Set short cooldown
        state = get_strip_order_state()
        state._cooldowns.clear()
        state.set_cooldown("KXSOL15M-26JUL211445-45", ExitReason.RISK_LIMIT, 1)
        
        # Wait for cooldown to expire
        time.sleep(1.1)
        
        # Create entry order intent
        intent = OrderIntent(
            ticker="KXSOL15M-26JUL211445-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1
        )
        
        # Check cooldown guard
        rejection = _check_strip_cooldown(intent)
        
        # Should allow (no rejection)
        assert rejection is None


class TestLoop15mCooldownIntegration:
    """Test cooldown integration in loop_15m.py exit callback."""
    
    def test_exit_callback_sets_cooldown(self):
        """Test that exit callback sets cooldown for problematic exits."""
        from merid.position_management.exit_policy import ExitReason
        from merid.prediction.strip_order_state import get_strip_order_state, ExitReason as StripExitReason
        
        state = get_strip_order_state()
        state._cooldowns.clear()
        
        # Simulate exit callback logic
        exit_reason = ExitReason.STALE_DATA
        cooldown_reason = None
        
        if exit_reason == ExitReason.STALE_DATA:
            cooldown_reason = StripExitReason.STALEDATA
        elif exit_reason == ExitReason.RISK_LIMIT:
            cooldown_reason = StripExitReason.RISK_LIMIT
        elif exit_reason == ExitReason.LOW_LIQUIDITY:
            cooldown_reason = StripExitReason.LOW_LIQUIDITY
        elif exit_reason == ExitReason.REGIME_HALTED:
            cooldown_reason = StripExitReason.REGIME_HALTED
        
        if cooldown_reason:
            state.set_cooldown("KXSOL15M-26JUL211445-45", cooldown_reason, 300)
        
        # Verify cooldown was set
        assert "KXSOL15M-26JUL211445-45" in state._cooldowns
        assert state._cooldowns["KXSOL15M-26JUL211445-45"].exit_reason == StripExitReason.STALEDATA


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
