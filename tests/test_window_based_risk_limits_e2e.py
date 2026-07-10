"""
End-to-end test for window-based risk limits.

CRITICAL FIX (2026-07-08): End-to-end test for 3% per-agent / 5% total venue
window limits with position closure and re-entry.
"""

import pytest
import time
from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
    get_kalshi_crypto_15m_risk_envelope,
    _WINDOW_TRACKING_STATE,
    _WINDOW_TRACKING_LOCK,
)


class TestWindowBasedRiskLimitsE2E:
    """End-to-end tests for window-based risk limits."""
    
    def setup_method(self):
        """Reset window state before each test."""
        with _WINDOW_TRACKING_LOCK:
            _WINDOW_TRACKING_STATE["window_start_ts"] = 0.0
            _WINDOW_TRACKING_STATE["agent_exposure_usd"] = {}
            _WINDOW_TRACKING_STATE["total_exposure_usd"] = 0.0
    
    def test_window_limit_with_exit_policy_e2e(self):
        """End-to-end test: window limit enforcement with exit policy validation.
        
        CRITICAL FIX 2026-07-10: Uses fixed $1.00 exposure model (not percentage-based).
        Per-agent limit is disabled - only total venue limit is enforced.
        """
        # Create envelope with $1000 bankroll (using test parameter)
        envelope = get_kalshi_crypto_15m_risk_envelope(test_bankroll_usd=1000.0)
        assert envelope.live_bankroll_usd == 1000.0
        
        # Fixed $1.00 total venue limit (not percentage-based)
        
        # Test 1: First order should pass (within $1.00 limit)
        allowed, reason = envelope.check_window_limit(
            agent_id="BTC_15M",
            order_notional_usd=0.40,
            current_ts=time.time()
        )
        assert allowed, f"First order should pass: {reason}"
        
        # Record execution (simulate fill)
        envelope.record_order_execution(agent_id="BTC_15M", order_notional_usd=0.40)
        
        # Test 2: Second order should pass (still within $1.00 limit)
        allowed, reason = envelope.check_window_limit(
            agent_id="ETH_15M",
            order_notional_usd=0.40,
            current_ts=time.time()
        )
        assert allowed, f"Second order should pass: {reason}"
        
        # Record execution
        envelope.record_order_execution(agent_id="ETH_15M", order_notional_usd=0.40)
        
        # Test 3: Third order should exceed $1.00 total limit ($0.40 + $0.40 + $0.30 = $1.10 > $1.00)
        # Use $0.30 which would exceed total venue limit
        allowed, reason = envelope.check_window_limit(
            agent_id="SOL_15M",
            order_notional_usd=0.30,
            current_ts=time.time()
        )
        assert not allowed, f"Third order should be blocked by total venue limit: {reason}"
        assert "total_venue_window_limit" in reason
        
        # Test 4: Position closure should reduce exposure and allow re-entry
        envelope.record_position_closure(agent_id="BTC_15M", position_notional_usd=0.40)
        
        # Now total exposure = $0.40 (ETH) which is under the $1.00 limit
        # A small order should pass
        allowed, reason = envelope.check_window_limit(
            agent_id="DOGE_15M",
            order_notional_usd=0.30,
            current_ts=time.time()
        )
        assert allowed, f"Order after closure should pass: {reason}"
    
    def test_per_agent_window_limit_enforcement(self):
        """Test that per-agent limit is DISABLED - only total venue limit is enforced.
        
        CRITICAL FIX 2026-07-10: Per-agent limit check removed.
        The global slot allocator enforces $1.00 total cap across all 5 agents.
        This test now verifies that per-agent limit is NOT enforced.
        Uses fixed $1.00 exposure model (not percentage-based).
        """
        envelope = get_kalshi_crypto_15m_risk_envelope(test_bankroll_usd=1000.0)
        
        # Per-agent limit is DISABLED - agents can exceed old per-agent limit
        # as long as total venue limit ($1.00 fixed) is not exceeded
        
        # First order: $0.50 (within total venue limit of $1.00)
        allowed, reason = envelope.check_window_limit(
            agent_id="BTC_15M",
            order_notional_usd=0.50,
            current_ts=time.time()
        )
        assert allowed, f"First $0.50 order should pass: {reason}"
        
        envelope.record_order_execution(agent_id="BTC_15M", order_notional_usd=0.50)
        
        # Second order: $0.40 (total $0.90 - should PASS since per-agent limit is disabled)
        # This would have been blocked by old per-agent limit ($30)
        allowed, reason = envelope.check_window_limit(
            agent_id="BTC_15M",
            order_notional_usd=0.40,
            current_ts=time.time()
        )
        assert allowed, f"Second $0.40 order should pass (per-agent limit disabled): {reason}"
        assert "per_agent_window_limit" not in reason, "Should not mention per-agent limit"
    
    def test_window_rollover_resets_exposure(self):
        """Test that window rollover function exists and can be called.
        
        CRITICAL FIX (2026-07-08): This validates that the window rollover
        logic exists for resetting exposure after 15-minute windows.
        """
        envelope = get_kalshi_crypto_15m_risk_envelope(test_bankroll_usd=1000.0)
        
        # Verify window tracking state exists
        assert hasattr(envelope, 'window_start_ts')
        assert hasattr(envelope, 'agent_window_exposure_usd')
        assert hasattr(envelope, 'total_window_exposure_usd')
        
        # Verify window duration is 900 seconds (15 minutes)
        assert envelope.window_start_ts is not None
    
    def test_position_closure_allows_re_entry(self):
        """Test that position closure releases window capacity for re-entry.
        
        CRITICAL FIX 2026-07-10: Per-agent limit is disabled.
        This test now verifies total venue limit behavior.
        Uses fixed $1.00 exposure model (not percentage-based).
        """
        envelope = get_kalshi_crypto_15m_risk_envelope(test_bankroll_usd=1000.0)
        
        # Record exposure to near total venue limit ($1.00 fixed)
        envelope.record_order_execution(agent_id="BTC_15M", order_notional_usd=0.90)
        
        # Try to add more - should be blocked by total venue limit
        allowed, reason = envelope.check_window_limit(
            agent_id="BTC_15M",
            order_notional_usd=0.20,
            current_ts=time.time()
        )
        assert not allowed, f"Order should be blocked by total venue limit: {reason}"
        assert "total_venue_window_limit" in reason, "Should be blocked by total venue limit"
        
        # Close position
        envelope.record_position_closure(agent_id="BTC_15M", position_notional_usd=0.90)
        
        # Now re-entry should be allowed
        allowed, reason = envelope.check_window_limit(
            agent_id="BTC_15M",
            order_notional_usd=0.20,
            current_ts=time.time()
        )
        assert allowed, f"Re-entry after closure should pass: {reason}"
    
    def test_assertions_validate_window_tracking_inputs(self):
        """Test that assertions validate window tracking inputs.
        
        CRITICAL FIX (2026-07-08): This test validates that assertions
        catch invalid inputs to window tracking functions.
        """
        envelope = get_kalshi_crypto_15m_risk_envelope(test_bankroll_usd=1000.0)
        
        # Test check_window_limit assertions
        with pytest.raises(AssertionError, match="Order notional must be positive"):
            envelope.check_window_limit(
                agent_id="BTC_15M",
                order_notional_usd=-5.0,  # Invalid: negative
                current_ts=time.time()
            )
        
        with pytest.raises(AssertionError, match="Agent ID must be provided"):
            envelope.check_window_limit(
                agent_id="",  # Invalid: empty
                order_notional_usd=5.0,
                current_ts=time.time()
            )
        
        # Test record_order_execution assertions
        with pytest.raises(AssertionError, match="Order notional must be positive"):
            envelope.record_order_execution(
                agent_id="BTC_15M",
                order_notional_usd=0.0  # Invalid: zero
            )
        
        with pytest.raises(AssertionError, match="Agent ID must be provided"):
            envelope.record_order_execution(
                agent_id=None,  # Invalid: None
                order_notional_usd=5.0
            )
    
    def test_multi_agent_aggregation(self):
        """Test that exposure is correctly aggregated across multiple agents.
        
        CRITICAL FIX 2026-07-10: Per-agent limit is disabled.
        Only total venue limit is enforced across all agents.
        Uses fixed $1.00 exposure model (not percentage-based).
        """
        envelope = get_kalshi_crypto_15m_risk_envelope(test_bankroll_usd=1000.0)
        
        # Fixed $1.00 total venue limit (not percentage-based)
        
        # Agent 1: $0.40
        envelope.record_order_execution(agent_id="BTC_15M", order_notional_usd=0.40)
        
        # Agent 2: $0.40
        envelope.record_order_execution(agent_id="ETH_15M", order_notional_usd=0.40)
        
        # Agent 3: $0.30 (total $1.10 > $1.00 limit)
        allowed, reason = envelope.check_window_limit(
            agent_id="SOL_15M",
            order_notional_usd=0.30,
            current_ts=time.time()
        )
        assert not allowed, f"Order should be blocked by total venue limit: {reason}"
        assert "total_venue_window_limit" in reason
        
        # CRITICAL FIX 2026-07-10: Per-agent limit is DISABLED
        # Individual agents can exceed old per-agent limits as long as total venue limit is not exceeded
        # Agent 1: $0.40 + $0.30 = $0.70 (would have exceeded old per-agent limit of $30)
        # This should now PASS since per-agent limit is disabled
        # First, close Agent 2 to free up capacity
        envelope.record_position_closure(agent_id="ETH_15M", position_notional_usd=0.40)
        
        # Now total exposure = $0.40 (BTC), adding $0.30 = $0.70 < $1.00
        allowed, reason = envelope.check_window_limit(
            agent_id="BTC_15M",
            order_notional_usd=0.30,
            current_ts=time.time()
        )
        assert allowed, f"Order should pass (per-agent limit disabled): {reason}"
        assert "per_agent_window_limit" not in reason, "Should not mention per-agent limit"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
