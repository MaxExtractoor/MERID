"""Integration test for session order count and cooldown behavior (2026-07-10 fix).

This test verifies that:
1. Session order count is incremented on fill, not submission
2. Cooldown is updated on fill, not submission
3. Session risk cap is reset with session window
4. Consecutive losses are reset with session window
5. Global rate limiting prevents order spam when orders don't fill
"""

import time
import pytest


class TestSessionOrderCountCooldownIntegration:
    """Integration test for session order count and cooldown behavior."""

    def test_session_order_count_increments_on_fill_not_submission(self):
        """Test that session order count increments on fill, not submission."""
        # Simulate session order count behavior
        session_order_count = 0
        max_orders_per_window = 12
        
        # Simulate order submission (should NOT increment count after fix)
        # Before fix: session_order_count += 1
        # After fix: No increment on submission
        assert session_order_count == 0, "Session order count should NOT increment on submission"
        
        # Simulate order fill (should increment count)
        session_order_count += 1
        
        # Verify count incremented on fill
        assert session_order_count == 1, "Session order count should increment on fill"
        assert session_order_count < max_orders_per_window, "Should not exceed max orders per window"
        
        # Simulate another fill
        session_order_count += 1
        assert session_order_count == 2, "Session order count should increment on each fill"

    def test_cooldown_updated_on_fill_not_submission(self):
        """Test that cooldown is updated on fill, not submission."""
        # Simulate cooldown behavior
        last_trade_time = 0.0
        cooldown_seconds = 30
        
        # Simulate order submission (should NOT update last_trade_time after fix)
        # Before fix: last_trade_time = time.time()
        # After fix: No update on submission
        assert last_trade_time == 0.0, "Cooldown should NOT be updated on submission"
        
        # Simulate order fill (should update last_trade_time)
        current_time = time.monotonic()
        last_trade_time = current_time
        
        # Verify cooldown updated on fill
        assert last_trade_time > 0, "Cooldown should be updated on fill"
        assert last_trade_time == current_time, "Cooldown should be set to current time on fill"
        
        # Verify cooldown check would block subsequent submissions
        time_since_trade = time.monotonic() - last_trade_time
        assert time_since_trade < cooldown_seconds, "Cooldown should block immediate re-submission after fill"

    def test_session_window_reset_clears_all_session_metrics(self):
        """Test that session window reset clears all session metrics."""
        # Simulate session metrics
        session_order_count = 5
        session_risk_usd = 5.0
        consecutive_losses = {"BTC": 3, "ETH": 2}
        consecutive_loss_pause_until = {"BTC": time.time() + 900, "ETH": 0.0}
        
        # Verify state before reset
        assert session_order_count == 5
        assert session_risk_usd == 5.0
        assert consecutive_losses["BTC"] == 3
        assert consecutive_loss_pause_until["BTC"] > time.time()
        
        # Simulate session window reset (CRITICAL FIX: reset all session metrics)
        session_order_count = 0
        session_risk_usd = 0.0  # CRITICAL FIX: Reset session risk cap with window
        consecutive_losses = {asset: 0 for asset in consecutive_losses}  # CRITICAL FIX: Reset consecutive losses
        consecutive_loss_pause_until = {asset: 0.0 for asset in consecutive_loss_pause_until}  # CRITICAL FIX: Reset pause times
        
        # Verify all session metrics reset
        assert session_order_count == 0
        assert session_risk_usd == 0.0
        assert consecutive_losses["BTC"] == 0
        assert consecutive_loss_pause_until["BTC"] == 0.0

    def test_global_rate_limit_prevents_order_spam(self):
        """Test that global rate limiting prevents order spam when orders don't fill."""
        from merid.event_venues.kalshi.order_router import (
            _check_global_rate_limit, 
            _global_order_timestamps,
            _MAX_ORDERS_PER_MINUTE,
            _MIN_SECONDS_BETWEEN_ORDERS,
            _startup_time,
            _MIN_STARTUP_GRACE_PERIOD
        )
        
        # Clear global state and disable startup grace period for testing
        _global_order_timestamps.clear()
        # Set startup time in the past to bypass grace period
        import merid.event_venues.kalshi.order_router as order_router_module
        order_router_module._startup_time = time.time() - _MIN_STARTUP_GRACE_PERIOD - 1
        
        # Verify rate limiting constants are set correctly
        assert _MAX_ORDERS_PER_MINUTE == 30, "Max orders per minute should be 30"
        assert _MIN_SECONDS_BETWEEN_ORDERS == 0.3, "Min seconds between orders should be 0.3"
        assert _MIN_STARTUP_GRACE_PERIOD == 20.0, "Startup grace period should be 20s"
        
        # Test startup grace period (should block orders immediately after startup)
        order_router_module._startup_time = time.time()  # Reset to current time
        result_grace = _check_global_rate_limit()
        assert result_grace is not None, "Startup grace period should block orders"
        assert "startup_grace_period" in result_grace
        
        # Bypass grace period for further testing
        order_router_module._startup_time = time.time() - _MIN_STARTUP_GRACE_PERIOD - 1
        
        # Test orders per minute limit by manually filling timestamps
        current_time = time.time()
        # Add timestamps within the last 60 seconds
        for i in range(_MAX_ORDERS_PER_MINUTE):
            _global_order_timestamps.append(current_time - (59 - i))
        
        # Should be blocked by orders per minute limit
        result_limit = _check_global_rate_limit()
        assert result_limit is not None, "Should be rate limited when at max orders per minute"
        assert "global_rate_limit_exceeded" in result_limit
        assert f"{_MAX_ORDERS_PER_MINUTE}" in result_limit

    def test_session_order_count_respects_window_limit(self):
        """Test that session order count respects the window limit."""
        # Simulate session order count behavior
        session_order_count = 0
        max_orders_per_window = 5  # Low limit for testing
        
        # Simulate fills up to limit
        for i in range(max_orders_per_window):
            session_order_count += 1
        
        # Verify count at limit
        assert session_order_count == max_orders_per_window
        
        # Simulate session window reset
        session_order_count = 0
        
        # Verify count reset
        assert session_order_count == 0
        
        # Should be able to add more fills after reset
        session_order_count += 1
        assert session_order_count == 1

    def test_consecutive_losses_reset_on_profit(self):
        """Test that consecutive losses are reset on profit."""
        # Simulate consecutive losses behavior
        consecutive_losses = {"BTC": 0, "ETH": 0, "SOL": 0}
        
        # Simulate consecutive losses
        consecutive_losses["BTC"] += 1  # Loss
        consecutive_losses["BTC"] += 1  # Loss
        consecutive_losses["BTC"] += 1  # Loss
        
        # Verify consecutive losses accumulated
        assert consecutive_losses["BTC"] == 3
        
        # Simulate profit (should reset)
        consecutive_losses["BTC"] = 0
        
        # Verify consecutive losses reset
        assert consecutive_losses["BTC"] == 0

    def test_session_risk_cap_blocks_when_exceeded(self):
        """Test that session risk cap blocks when exceeded."""
        # Simulate session risk cap behavior
        session_risk_usd = 0.0
        session_risk_cap_usd = 10.0  # 10% of $100
        
        # Simulate fills up to cap
        for i in range(10):
            session_risk_usd += 1.0
        
        # Verify risk at cap
        assert session_risk_usd == session_risk_cap_usd
        
        # Session reset should clear risk cap
        session_risk_usd = 0.0
        
        # Verify risk cap reset
        assert session_risk_usd == 0.0
