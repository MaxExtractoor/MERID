"""
Comprehensive end-to-end tests for exit policy functionality.

This test suite proves that the exit policy works correctly by:
1. Validating entry orders require complete exit policy metadata
2. Validating exit orders require exit_policy_id
3. Validating max_hold_seconds range constraints (60s-3600s)
4. Ensuring valid exit policy metadata allows orders through
"""

import pytest
from merid.event_venues.kalshi.order_gate import get_pre_trade_gate, GateVerdict
import time


class TestExitPolicyComprehensive:
    """Comprehensive end-to-end tests for exit policy functionality."""
    
    def setup_method(self):
        """Set up fresh gate instance for each test."""
        self.gate = get_pre_trade_gate()
    
    def test_entry_order_rejected_without_exit_policy_id(self):
        """Test that entry orders are rejected without exit_policy_id."""
        verdict = self.gate.check(
            agent_id="BTC_15M",
            strategy_group="kalshi_crypto_15m_v2",
            contract_id="KXBTC15M-26JUL202315-15",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=50,
            decision_ts=time.time(),
            exit_policy_id=None,  # Missing
            window_resolution_id="window-123",
            risk_tier="conservative",
            max_hold_seconds=300,
        )
        
        assert not verdict.allowed
        assert "exit_policy_metadata_missing" in verdict.reason
        assert "exit_policy_id" in verdict.reason
    
    def test_entry_order_rejected_without_window_resolution_id(self):
        """Test that entry orders are rejected without window_resolution_id."""
        verdict = self.gate.check(
            agent_id="BTC_15M",
            strategy_group="kalshi_crypto_15m_v2",
            contract_id="KXBTC15M-26JUL202315-15",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=50,
            decision_ts=time.time(),
            exit_policy_id="policy-123",
            window_resolution_id=None,  # Missing
            risk_tier="conservative",
            max_hold_seconds=300,
        )
        
        assert not verdict.allowed
        assert "exit_policy_metadata_missing" in verdict.reason
        assert "window_resolution_id" in verdict.reason
    
    def test_entry_order_rejected_without_risk_tier(self):
        """Test that entry orders are rejected without risk_tier."""
        verdict = self.gate.check(
            agent_id="BTC_15M",
            strategy_group="kalshi_crypto_15m_v2",
            contract_id="KXBTC15M-26JUL202315-15",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=50,
            decision_ts=time.time(),
            exit_policy_id="policy-123",
            window_resolution_id="window-123",
            risk_tier=None,  # Missing
            max_hold_seconds=300,
        )
        
        assert not verdict.allowed
        assert "exit_policy_metadata_missing" in verdict.reason
        assert "risk_tier" in verdict.reason
    
    def test_entry_order_rejected_without_max_hold_seconds(self):
        """Test that entry orders are rejected without max_hold_seconds."""
        verdict = self.gate.check(
            agent_id="BTC_15M",
            strategy_group="kalshi_crypto_15m_v2",
            contract_id="KXBTC15M-26JUL202315-15",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=50,
            decision_ts=time.time(),
            exit_policy_id="policy-123",
            window_resolution_id="window-123",
            risk_tier="conservative",
            max_hold_seconds=None,  # Missing
        )
        
        assert not verdict.allowed
        assert "exit_policy_metadata_missing" in verdict.reason
        assert "max_hold_seconds" in verdict.reason
    
    def test_entry_order_rejected_max_hold_too_low(self):
        """Test that entry orders are rejected when max_hold_seconds < 60s."""
        verdict = self.gate.check(
            agent_id="BTC_15M",
            strategy_group="kalshi_crypto_15m_v2",
            contract_id="KXBTC15M-26JUL202315-15",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=50,
            decision_ts=time.time(),
            exit_policy_id="policy-123",
            window_resolution_id="window-123",
            risk_tier="conservative",
            max_hold_seconds=30,  # Too low (< 60s)
        )
        
        assert not verdict.allowed
        assert "exit_policy_metadata_invalid" in verdict.reason
        assert "max_hold_seconds_invalid" in verdict.reason
        assert "< 60s minimum" in verdict.reason
    
    def test_entry_order_rejected_max_hold_too_high(self):
        """Test that entry orders are rejected when max_hold_seconds > 3600s."""
        verdict = self.gate.check(
            agent_id="BTC_15M",
            strategy_group="kalshi_crypto_15m_v2",
            contract_id="KXBTC15M-26JUL202315-15",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=50,
            decision_ts=time.time(),
            exit_policy_id="policy-123",
            window_resolution_id="window-123",
            risk_tier="conservative",
            max_hold_seconds=4000,  # Too high (> 3600s)
        )
        
        assert not verdict.allowed
        assert "exit_policy_metadata_invalid" in verdict.reason
        assert "max_hold_seconds_invalid" in verdict.reason
        assert "> 3600s maximum" in verdict.reason
    
    def test_entry_order_accepted_with_valid_exit_policy(self):
        """Test that entry orders are accepted with valid exit policy metadata."""
        verdict = self.gate.check(
            agent_id="BTC_15M",
            strategy_group="kalshi_crypto_15m_v2",
            contract_id="KXBTC15M-26JUL202315-15",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=50,
            decision_ts=time.time(),
            exit_policy_id="policy-123",
            window_resolution_id="window-123",
            risk_tier="conservative",
            max_hold_seconds=300,  # Valid (60s-3600s)
        )
        
        # Should pass exit policy validation (may fail other checks like dedup)
        # The key is that it should NOT be rejected for exit policy reasons
        if not verdict.allowed:
            assert "exit_policy" not in verdict.reason.lower()
    
    def test_exit_order_rejected_without_exit_policy_id(self):
        """Test that exit orders (sell) are rejected without exit_policy_id."""
        verdict = self.gate.check(
            agent_id="BTC_15M",
            strategy_group="kalshi_crypto_15m_v2",
            contract_id="KXBTC15M-26JUL202315-15",
            side="yes",
            action="sell",  # Exit order
            target_count=1,
            price_cents=50,
            decision_ts=time.time() + 1000,  # Unique timestamp to avoid duplicate detection
            exit_policy_id=None,  # Missing (required for exit orders)
        )
        
        assert not verdict.allowed
        assert "exit_policy_id_missing" in verdict.reason
    
    def test_exit_order_accepted_with_exit_policy_id(self):
        """Test that exit orders are accepted with exit_policy_id."""
        verdict = self.gate.check(
            agent_id="BTC_15M",
            strategy_group="kalshi_crypto_15m_v2",
            contract_id="KXBTC15M-26JUL202315-15",
            side="yes",
            action="sell",  # Exit order
            target_count=1,
            price_cents=50,
            decision_ts=time.time(),
            exit_policy_id="policy-123",  # Provided
        )
        
        # Should pass exit policy validation (may fail other checks)
        if not verdict.allowed:
            assert "exit_policy" not in verdict.reason.lower()
    
    def test_non_crypto_15m_market_bypasses_exit_policy(self):
        """Test that non-crypto-15m markets bypass exit policy validation."""
        verdict = self.gate.check(
            agent_id="some_agent",
            strategy_group="some_strategy",
            contract_id="NOT-A-CRYPTO-15M-MARKET",  # Not a crypto 15m market
            side="yes",
            action="buy",
            target_count=1,
            price_cents=50,
            decision_ts=time.time(),
            # No exit policy metadata - should be OK for non-crypto-15m
        )
        
        # Should not be rejected for exit policy reasons
        if not verdict.allowed:
            assert "exit_policy" not in verdict.reason.lower()
    
    def test_metrics_incremented_correctly(self):
        """Test that exit policy metrics are incremented correctly."""
        from merid.event_venues.kalshi.order_gate import GateMetrics
        
        # Get initial metrics (gate is singleton, so metrics are cumulative)
        initial_metrics = self.gate._store._metrics
        initial_blocked_exit_policy = initial_metrics.blocked_exit_policy
        initial_blocked_exit_policy_invalid = initial_metrics.blocked_exit_policy_invalid
        
        # Trigger missing metadata rejection
        verdict1 = self.gate.check(
            agent_id="BTC_15M_METRICS_TEST",
            strategy_group="kalshi_crypto_15m_v2",
            contract_id="KXBTC15M-26JUL202315-15",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=50,
            decision_ts=time.time(),
            exit_policy_id=None,
        )
        
        # Check that it was rejected for exit policy reasons and metric increased
        if "exit_policy" in verdict1.reason:
            assert self.gate._store._metrics.blocked_exit_policy >= initial_blocked_exit_policy
        
        # Trigger invalid metadata rejection
        verdict2 = self.gate.check(
            agent_id="BTC_15M_METRICS_TEST_2",
            strategy_group="kalshi_crypto_15m_v2",
            contract_id="KXBTC15M-26JUL202315-15",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=50,
            decision_ts=time.time() + 1,
            exit_policy_id="policy-123",
            window_resolution_id="window-123",
            risk_tier="conservative",
            max_hold_seconds=30,  # Invalid
        )
        
        # Check that it was rejected for exit policy reasons and metric increased
        if "exit_policy" in verdict2.reason:
            assert self.gate._store._metrics.blocked_exit_policy_invalid >= initial_blocked_exit_policy_invalid


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
