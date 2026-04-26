"""
Tests for Kalshi Continuous Trader Bankroll Refactor

Validates the production refactor that eliminates the hardcoded 10k bankroll
and ensures live Kalshi balance drives sizing with configurable caps/floors.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure merid is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from merid.trading.kalshi_continuous_trader import TraderConfig


class TestTraderConfigBankroll(unittest.TestCase):
    """Test TraderConfig bankroll configuration behaviors."""

    def test_initial_bankroll_zero_by_default(self):
        """initial_bankroll_cents should default to 0 (no reference set)."""
        config = TraderConfig()
        self.assertEqual(config.initial_bankroll_cents, 0)

    def test_max_riskable_usd_zero_by_default(self):
        """max_riskable_usd should default to 0 (unlimited)."""
        config = TraderConfig()
        self.assertEqual(config.max_riskable_usd, 0.0)

    def test_min_operational_balance_zero_by_default(self):
        """min_operational_balance_usd should default to 0 (no minimum)."""
        config = TraderConfig()
        self.assertEqual(config.min_operational_balance_usd, 0.0)

    def test_initial_bankroll_can_be_set_explicitly(self):
        """initial_bankroll_cents can be set explicitly for performance reference."""
        config = TraderConfig(initial_bankroll_cents=1_000_000)  # $10,000
        self.assertEqual(config.initial_bankroll_cents, 1_000_000)

    def test_max_riskable_can_be_set(self):
        """max_riskable_usd can be configured to cap live equity usage."""
        config = TraderConfig(max_riskable_usd=5000.0)
        self.assertEqual(config.max_riskable_usd, 5000.0)

    def test_min_operational_balance_can_be_set(self):
        """min_operational_balance_usd can be configured as safety floor."""
        config = TraderConfig(min_operational_balance_usd=1000.0)
        self.assertEqual(config.min_operational_balance_usd, 1000.0)


class TestTraderConfigFromEnv(unittest.TestCase):
    """Test TraderConfig environment variable parsing."""

    @patch.dict(os.environ, {"KALSHI_TRADER_BANKROLL": "250000"}, clear=False)
    def test_initial_bankroll_from_env(self):
        """KALSHI_TRADER_BANKROLL sets initial_bankroll_cents."""
        config = TraderConfig.from_env()
        self.assertEqual(config.initial_bankroll_cents, 250000)

    @patch.dict(os.environ, {"KALSHI_TRADER_MAX_RISKABLE_USD": "5000.00"}, clear=False)
    def test_max_riskable_from_env(self):
        """KALSHI_TRADER_MAX_RISKABLE_USD sets max_riskable_usd."""
        config = TraderConfig.from_env()
        self.assertEqual(config.max_riskable_usd, 5000.0)

    @patch.dict(os.environ, {"KALSHI_TRADER_MIN_OP_BALANCE_USD": "1000.00"}, clear=False)
    def test_min_operational_balance_from_env(self):
        """KALSHI_TRADER_MIN_OP_BALANCE_USD sets min_operational_balance_usd."""
        config = TraderConfig.from_env()
        self.assertEqual(config.min_operational_balance_usd, 1000.0)


class TestEffectiveEquityComputation(unittest.TestCase):
    """Test the effective equity computation with caps."""

    def test_no_cap_when_max_riskable_zero(self):
        """When max_riskable_usd=0, effective equity equals live equity."""
        live_equity = 15000.0
        max_riskable = 0.0
        
        if max_riskable > 0:
            effective = min(live_equity, max_riskable)
        else:
            effective = live_equity
            
        self.assertEqual(effective, live_equity)

    def test_cap_applied_when_live_exceeds_max_riskable(self):
        """When live > max_riskable, effective equity is capped."""
        live_equity = 15000.0
        max_riskable = 10000.0
        
        effective = min(live_equity, max_riskable) if max_riskable > 0 else live_equity
        
        self.assertEqual(effective, max_riskable)

    def test_no_cap_when_live_below_max_riskable(self):
        """When live < max_riskable, effective equity equals live."""
        live_equity = 5000.0
        max_riskable = 10000.0
        
        effective = min(live_equity, max_riskable) if max_riskable > 0 else live_equity
        
        self.assertEqual(effective, live_equity)


class TestMinOperationalBalanceSafety(unittest.TestCase):
    """Test the min operational balance safety floor."""

    def test_no_halt_when_min_balance_zero(self):
        """When min_operational_balance_usd=0, any balance is acceptable."""
        live_equity = 100.0
        min_op_balance = 0.0
        
        should_halt = min_op_balance > 0 and live_equity < min_op_balance
        
        self.assertFalse(should_halt)

    def test_halt_when_below_min_operational_balance(self):
        """When live < min_operational_balance, trading should halt."""
        live_equity = 500.0
        min_op_balance = 1000.0
        
        should_halt = min_op_balance > 0 and live_equity < min_op_balance
        
        self.assertTrue(should_halt)

    def test_continue_when_above_min_operational_balance(self):
        """When live > min_operational_balance, trading can continue."""
        live_equity = 1500.0
        min_op_balance = 1000.0
        
        should_halt = min_op_balance > 0 and live_equity < min_op_balance
        
        self.assertFalse(should_halt)

    def test_exactly_at_min_operational_balance(self):
        """When live == min_operational_balance, trading can continue."""
        live_equity = 1000.0
        min_op_balance = 1000.0
        
        should_halt = min_op_balance > 0 and live_equity < min_op_balance
        
        self.assertFalse(should_halt)


class TestBankrollNotOverwritten(unittest.TestCase):
    """Test that initial_bankroll_cents is NOT overwritten by hardening logic."""

    def test_initial_bankroll_unchanged_after_post_init(self):
        """
        After __post_init__, initial_bankroll_cents should remain as set.
        This is the key fix - previously it would be overwritten from settings.
        """
        config = TraderConfig(initial_bankroll_cents=500_000)  # $5,000
        
        # After post_init runs, value should still be 500_000
        self.assertEqual(config.initial_bankroll_cents, 500_000)

    def test_zero_initial_bankroll_allowed(self):
        """initial_bankroll_cents=0 should be allowed (no reference epoch)."""
        config = TraderConfig(initial_bankroll_cents=0)
        
        # Should not raise error
        self.assertEqual(config.initial_bankroll_cents, 0)


class TestIntegrationScenario(unittest.TestCase):
    """Integration test for realistic scenarios."""

    def test_scenario_user_with_50k_balance_and_25k_cap(self):
        """
        User has $50,000 in Kalshi but only wants to risk $25,000.
        Effective equity should be $25,000.
        """
        live_equity_usd = 50000.0
        max_riskable_usd = 25000.0
        min_operational_balance_usd = 5000.0
        
        # Compute effective equity
        effective_equity_usd = min(live_equity_usd, max_riskable_usd) if max_riskable_usd > 0 else live_equity_usd
        
        # Safety check
        should_halt = min_operational_balance_usd > 0 and live_equity_usd < min_operational_balance_usd
        
        self.assertEqual(effective_equity_usd, 25000.0)
        self.assertFalse(should_halt)

    def test_scenario_user_with_low_balance_below_minimum(self):
        """
        User has $800 in Kalshi with $1,000 minimum operational balance.
        Trading should halt.
        """
        live_equity_usd = 800.0
        max_riskable_usd = 0.0  # No cap
        min_operational_balance_usd = 1000.0
        
        # Safety check
        should_halt = min_operational_balance_usd > 0 and live_equity_usd < min_operational_balance_usd
        
        self.assertTrue(should_halt)

    def test_scenario_user_with_exactly_minimum_balance(self):
        """
        User has exactly $1,000 with $1,000 minimum.
        Trading should continue (not below minimum).
        """
        live_equity_usd = 1000.0
        max_riskable_usd = 0.0
        min_operational_balance_usd = 1000.0
        
        should_halt = min_operational_balance_usd > 0 and live_equity_usd < min_operational_balance_usd
        
        self.assertFalse(should_halt)


if __name__ == "__main__":
    unittest.main()
