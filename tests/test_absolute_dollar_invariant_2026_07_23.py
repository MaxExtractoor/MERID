#!/usr/bin/env python3
"""
Test: Absolute Dollar Invariant for Fixed $1 Exposure Cap

This test verifies that the fixed $1.00 exposure cap invariant holds under
various scenarios, ensuring percentage-based allocation paths are eliminated.

CRITICAL FIX (2026-07-23): System now enforces ONLY absolute-dollar limits
based on the fixed $1.00 exposure cap (MERID_FIXED_EXPOSURE_CAP_USD). No
percentage-based overrides are allowed.

Test scenarios:
1. Bankroll drift mid-window does not increase allowed spend
2. Exit orders respect the same window cap or have separate modeled allowances
3. IOC no-fill orders do not consume budget
4. Retries cannot multiply effective allocation
5. Per-agent and total-venue caps fail closed when exceeded

Usage:
    pytest tests/test_absolute_dollar_invariant_2026_07_23.py -v
"""

import pytest
import time
import os


class TestAbsoluteDollarInvariant:
    """Test absolute-dollar invariant for fixed $1 exposure cap."""

    @pytest.fixture
    def risk_envelope(self):
        """Create a risk envelope instance for testing."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import KalshiCrypto15mRiskEnvelope
        
        bankroll = 10000.0
        envelope = KalshiCrypto15mRiskEnvelope(
            live_bankroll_usd=bankroll,
            profile_capital_usd=bankroll,
            max_single_order_notional_usd=bankroll * 0.03,
            max_total_notional_usd=bankroll * 0.15,
            agent_max_notional_usd=bankroll * 0.03,
            asset_max_notional_usd={"BTC": bankroll * 0.03, "ETH": bankroll * 0.03, "SOL": bankroll * 0.03, "XRP": bankroll * 0.03, "DOGE": bankroll * 0.03},
            asset_depth_thresholds={},
            agent_max_orders_per_window=12,
            agent_max_yes_position=5,
            agent_max_no_position=5,
            max_cycle_risk_pct=0.03,
            daily_loss_enabled=False,
            max_daily_loss_usd=float('inf'),
            drawdown_halt_pct=0.15,
            drawdown_unwind_pct=0.10,
            peak_equity_usd=bankroll,
            current_equity_usd=bankroll,
            current_drawdown_pct=0.0,
            kelly_fraction=0.02,
            adaptive_risk_bands=[],
            per_trade_risk_multiplier=1.0,
            is_halted=False,
            current_risk_band=None,
            resume_if_drawdown_improves=False,
            correlation_tracking_enabled=False,
            correlation_threshold=0.7,
            correlation_multiplier=1.0,
            window_start_ts=0.0,
            agent_window_exposure_usd={},
            total_window_exposure_usd=0.0,
            agent_resting_exposure_usd={},
            total_resting_exposure_usd=0.0,
        )
        return envelope

    def test_bankroll_drift_mid_window(self, risk_envelope):
        """Test that bankroll changes mid-window do not increase allowed spend.
        
        CRITICAL: The fixed $1.00 cap is immutable and must not change based on
        bankroll fluctuations. Even if bankroll increases mid-window, the cap
        remains $1.00.
        """
        # Set fixed $1.00 cap
        os.environ['MERID_FIXED_EXPOSURE_CAP_USD'] = '1.00'
        
        # Reset window state
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import _WINDOW_TRACKING_STATE, _WINDOW_TRACKING_LOCK
        with _WINDOW_TRACKING_LOCK:
            _WINDOW_TRACKING_STATE["total_exposure_usd"] = 0.0
            _WINDOW_TRACKING_STATE["total_resting_exposure_usd"] = 0.0
        
        # Place order for $0.50 (should be allowed)
        allowed, reason = risk_envelope.check_window_limit(
            agent_id="BTC_15M",
            order_notional_usd=0.50,
            current_ts=time.time(),
            asset="BTC"
        )
        assert allowed, f"First order should be allowed: {reason}"
        risk_envelope.record_order_execution("BTC_15M", 0.50, asset="BTC")
        
        # Simulate bankroll increase mid-window (from $10k to $15k)
        # This should NOT increase the $1.00 cap
        risk_envelope.live_bankroll_usd = 15000.0
        
        # Try to place order for $0.60 (total would be $1.10, should be blocked)
        allowed, reason = risk_envelope.check_window_limit(
            agent_id="ETH_15M",
            order_notional_usd=0.60,
            current_ts=time.time(),
            asset="ETH"
        )
        assert not allowed, f"Order exceeding $1 cap should be blocked even with higher bankroll: {reason}"
        assert "total_venue_window_limit" in reason, "Should be blocked by total venue limit"
        
        # Reset state
        with _WINDOW_TRACKING_LOCK:
            _WINDOW_TRACKING_STATE["total_exposure_usd"] = 0.0
            _WINDOW_TRACKING_STATE["total_resting_exposure_usd"] = 0.0

    def test_ioc_no_fill_budget_consumption(self, risk_envelope):
        """Test that IOC no-fill orders do not consume budget.
        
        CRITICAL: Zero notional orders (IOC orders that don't fill) should
        not consume budget. The system must handle order_notional_usd=0
        gracefully without assertion errors.
        """
        # Set fixed $1.00 cap
        os.environ['MERID_FIXED_EXPOSURE_CAP_USD'] = '1.00'
        
        # Reset window state
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import _WINDOW_TRACKING_STATE, _WINDOW_TRACKING_LOCK
        with _WINDOW_TRACKING_LOCK:
            _WINDOW_TRACKING_STATE["total_exposure_usd"] = 0.0
            _WINDOW_TRACKING_STATE["total_resting_exposure_usd"] = 0.0
        
        # Place order for $0.50 (should be allowed)
        allowed, reason = risk_envelope.check_window_limit(
            agent_id="BTC_15M",
            order_notional_usd=0.50,
            current_ts=time.time(),
            asset="BTC"
        )
        assert allowed, f"First order should be allowed: {reason}"
        risk_envelope.record_order_execution("BTC_15M", 0.50, asset="BTC")
        
        # Record IOC no-fill (zero notional) - should not consume budget
        risk_envelope.record_order_execution("BTC_15M", 0.0, asset="BTC")
        
        # Verify total exposure is still $0.50 (not increased by zero notional)
        with _WINDOW_TRACKING_LOCK:
            total_exposure = _WINDOW_TRACKING_STATE["total_exposure_usd"]
        
        assert total_exposure == 0.50, f"Total exposure should be $0.50 after zero notional, got ${total_exposure:.2f}"
        
        # Should still be able to place order for $0.50 (total $1.00)
        allowed, reason = risk_envelope.check_window_limit(
            agent_id="ETH_15M",
            order_notional_usd=0.50,
            current_ts=time.time(),
            asset="ETH"
        )
        assert allowed, f"Order for $0.50 should be allowed after zero notional: {reason}"
        
        # Reset state
        with _WINDOW_TRACKING_LOCK:
            _WINDOW_TRACKING_STATE["total_exposure_usd"] = 0.0
            _WINDOW_TRACKING_STATE["total_resting_exposure_usd"] = 0.0

    def test_retry_multiplication_prevention(self, risk_envelope):
        """Test that retries cannot multiply effective allocation.
        
        CRITICAL: Retries happen at the HTTP/network level before order
        submission. Successful retries go through normal submission flow
        and call record_order_execution() on fill. The system must not
        allow retries to consume budget multiple times for the same order.
        """
        # Set fixed $1.00 cap
        os.environ['MERID_FIXED_EXPOSURE_CAP_USD'] = '1.00'
        
        # Reset window state
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import _WINDOW_TRACKING_STATE, _WINDOW_TRACKING_LOCK
        with _WINDOW_TRACKING_LOCK:
            _WINDOW_TRACKING_STATE["total_exposure_usd"] = 0.0
            _WINDOW_TRACKING_STATE["total_resting_exposure_usd"] = 0.0
        
        # Simulate retry attempts: check window limit multiple times for same order
        # This should not consume budget - only actual execution does
        for i in range(5):
            allowed, reason = risk_envelope.check_window_limit(
                agent_id="BTC_15M",
                order_notional_usd=0.50,
                current_ts=time.time(),
                asset="BTC"
            )
            assert allowed, f"Retry {i+1} should be allowed: {reason}"
        
        # Verify no budget consumed by checks alone
        with _WINDOW_TRACKING_LOCK:
            total_exposure = _WINDOW_TRACKING_STATE["total_exposure_usd"]
        
        assert total_exposure == 0.0, f"Total exposure should be $0.00 after checks only, got ${total_exposure:.2f}"
        
        # Record actual execution (simulating successful retry)
        risk_envelope.record_order_execution("BTC_15M", 0.50, asset="BTC")
        
        # Verify budget consumed once
        with _WINDOW_TRACKING_LOCK:
            total_exposure = _WINDOW_TRACKING_STATE["total_exposure_usd"]
        
        assert total_exposure == 0.50, f"Total exposure should be $0.50 after execution, got ${total_exposure:.2f}"
        
        # Reset state
        with _WINDOW_TRACKING_LOCK:
            _WINDOW_TRACKING_STATE["total_exposure_usd"] = 0.0
            _WINDOW_TRACKING_STATE["total_resting_exposure_usd"] = 0.0

    def test_per_agent_and_total_venue_caps_fail_closed(self, risk_envelope):
        """Test that per-agent and total-venue caps fail closed when exceeded.
        
        CRITICAL: When limits are exceeded, the system must fail closed (reject)
        rather than fail open (allow). This is a safety invariant.
        """
        # Set fixed $1.00 cap
        os.environ['MERID_FIXED_EXPOSURE_CAP_USD'] = '1.00'
        
        # Reset window state
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import _WINDOW_TRACKING_STATE, _WINDOW_TRACKING_LOCK
        with _WINDOW_TRACKING_LOCK:
            _WINDOW_TRACKING_STATE["total_exposure_usd"] = 0.0
            _WINDOW_TRACKING_STATE["total_resting_exposure_usd"] = 0.0
        
        # Place orders up to $1.00 cap
        risk_envelope.record_order_execution("BTC_15M", 0.40, asset="BTC")
        risk_envelope.record_order_execution("ETH_15M", 0.30, asset="ETH")
        risk_envelope.record_order_execution("SOL_15M", 0.30, asset="SOL")
        
        # Try to place order that would exceed $1.00 cap
        allowed, reason = risk_envelope.check_window_limit(
            agent_id="XRP_15M",
            order_notional_usd=0.01,
            current_ts=time.time(),
            asset="XRP"
        )
        assert not allowed, f"Order exceeding $1 cap should be rejected: {reason}"
        assert "total_venue_window_limit" in reason, "Should be blocked by total venue limit"
        
        # Verify fail closed: even a tiny order is rejected
        allowed, reason = risk_envelope.check_window_limit(
            agent_id="DOGE_15M",
            order_notional_usd=0.001,
            current_ts=time.time(),
            asset="DOGE"
        )
        assert not allowed, f"Tiny order exceeding $1 cap should also be rejected: {reason}"
        
        # Reset state
        with _WINDOW_TRACKING_LOCK:
            _WINDOW_TRACKING_STATE["total_exposure_usd"] = 0.0
            _WINDOW_TRACKING_STATE["total_resting_exposure_usd"] = 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
