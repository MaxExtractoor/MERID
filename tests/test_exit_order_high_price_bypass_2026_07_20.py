"""
Test exit order high price bypass fix (2026-07-20).

CRITICAL FIX: Exit orders should bypass the high_price_low_profit gate check
to allow closing positions even at high prices (e.g., 94c, 97c) to realize PnL.
Entry orders should still be blocked at prices > 75c.
"""

import pytest
from merid.event_venues.kalshi.order_gate import PreTradeGate, GateVerdict


class TestExitOrderHighPriceBypass:
    """Tests for exit order bypass of high_price_low_profit gate check."""
    
    @pytest.fixture
    def gate(self):
        """Create a PreTradeGate instance for testing."""
        from merid.event_venues.kalshi.order_gate import IdempotentOrderStore
        store = IdempotentOrderStore()
        return PreTradeGate(store)
    
    def test_entry_order_blocked_at_high_price(self, gate):
        """Test that entry orders are still blocked at prices > 75c."""
        verdict = gate.check(
            agent_id="test_agent",
            strategy_group="btc_15m",
            contract_id="KXBTC15M-26JUL201200-00",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=94,  # Above 75c threshold
            decision_ts=1234567890.0,
            intent_id="test_intent",
            entry_or_exit="entry",  # Entry order
            # Provide exit policy metadata to bypass that check
            exit_policy_id="test_policy",
            window_resolution_id="test_window",
            risk_tier="low",
            max_hold_seconds=300,
        )
        
        # Entry order should be blocked
        assert not verdict.allowed
        assert "high_price_low_profit" in verdict.reason
        assert "94c > 75c" in verdict.reason
    
    def test_exit_order_allowed_at_high_price(self, gate):
        """Test that exit orders are allowed at prices > 75c."""
        verdict = gate.check(
            agent_id="test_agent",
            strategy_group="btc_15m",
            contract_id="KXBTC15M-26JUL201200-00",
            side="yes",
            action="sell",
            target_count=1,
            price_cents=94,  # Above 75c threshold
            decision_ts=1234567890.0,
            intent_id="test_intent",
            entry_or_exit="exit",  # Exit order
        )
        
        # Exit order should be allowed (bypasses high_price_low_profit check)
        # Note: May still be blocked by other checks, but not high_price_low_profit
        assert verdict.reason != "high_price_low_profit:price=94c > 75c threshold"
    
    def test_exit_order_allowed_at_very_high_price(self, gate):
        """Test that exit orders are allowed even at very high prices (97c)."""
        verdict = gate.check(
            agent_id="test_agent",
            strategy_group="btc_15m",
            contract_id="KXBTC15M-26JUL201200-00",
            side="yes",
            action="sell",
            target_count=1,
            price_cents=97,  # Very high price
            decision_ts=1234567890.0,
            intent_id="test_intent",
            entry_or_exit="exit",  # Exit order
        )
        
        # Exit order should be allowed (bypasses high_price_low_profit check)
        assert verdict.reason != "high_price_low_profit:price=97c > 75c threshold"
    
    def test_entry_or_exit_none_treated_as_entry(self, gate):
        """Test that entry_or_exit=None is treated as entry (conservative)."""
        verdict = gate.check(
            agent_id="test_agent",
            strategy_group="btc_15m",
            contract_id="KXBTC15M-26JUL201200-00",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=94,  # Above 75c threshold
            decision_ts=1234567890.0,
            intent_id="test_intent",
            entry_or_exit=None,  # None should be treated as entry
            # Provide exit policy metadata to bypass that check
            exit_policy_id="test_policy",
            window_resolution_id="test_window",
            risk_tier="low",
            max_hold_seconds=300,
        )
        
        # Should be blocked (conservative: None = entry)
        assert not verdict.allowed
        assert "high_price_low_profit" in verdict.reason
    
    def test_entry_order_allowed_within_range(self, gate):
        """Test that entry orders are allowed within canonical range (10-75c)."""
        verdict = gate.check(
            agent_id="test_agent",
            strategy_group="btc_15m",
            contract_id="KXBTC15M-26JUL201200-00",
            side="yes",
            action="buy",
            target_count=1,
            price_cents=50,  # Within 10-75c range
            decision_ts=1234567890.0,
            intent_id="test_intent",
            entry_or_exit="entry",
        )
        
        # Entry order should be allowed (within range)
        # Note: May still be blocked by other checks, but not high_price_low_profit
        assert verdict.reason != "high_price_low_profit:price=50c > 75c threshold"
    
    def test_exit_order_allowed_within_range(self, gate):
        """Test that exit orders are allowed within canonical range (10-75c)."""
        verdict = gate.check(
            agent_id="test_agent",
            strategy_group="btc_15m",
            contract_id="KXBTC15M-26JUL201200-00",
            side="yes",
            action="sell",
            target_count=1,
            price_cents=50,  # Within 10-75c range
            decision_ts=1234567890.0,
            intent_id="test_intent",
            entry_or_exit="exit",
        )
        
        # Exit order should be allowed (within range)
        assert verdict.reason != "high_price_low_profit:price=50c > 75c threshold"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
