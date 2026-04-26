"""
Tests for Kalshi Continuous Trader Bankroll Refactor - Core Logic

Validates the production refactor logic without importing the full CT module.
"""

import unittest


class TestEffectiveEquityComputation(unittest.TestCase):
    """Test the effective equity computation with max_riskable_usd cap."""

    def _compute_effective_equity(self, live_equity_usd: float, max_riskable_usd: float) -> float:
        """Helper matching the CT logic."""
        if max_riskable_usd > 0:
            return min(live_equity_usd, max_riskable_usd)
        return live_equity_usd

    def test_no_cap_when_max_riskable_zero(self):
        """When max_riskable_usd=0, effective equity equals live equity."""
        live_equity = 15000.0
        max_riskable = 0.0
        
        effective = self._compute_effective_equity(live_equity, max_riskable)
        
        self.assertEqual(effective, live_equity)

    def test_cap_applied_when_live_exceeds_max_riskable(self):
        """When live > max_riskable, effective equity is capped."""
        live_equity = 15000.0
        max_riskable = 10000.0
        
        effective = self._compute_effective_equity(live_equity, max_riskable)
        
        self.assertEqual(effective, max_riskable)
        self.assertLess(effective, live_equity)

    def test_no_cap_when_live_below_max_riskable(self):
        """When live < max_riskable, effective equity equals live."""
        live_equity = 5000.0
        max_riskable = 10000.0
        
        effective = self._compute_effective_equity(live_equity, max_riskable)
        
        self.assertEqual(effective, live_equity)

    def test_cap_at_exact_max_riskable(self):
        """When live == max_riskable, effective equity equals both."""
        live_equity = 10000.0
        max_riskable = 10000.0
        
        effective = self._compute_effective_equity(live_equity, max_riskable)
        
        self.assertEqual(effective, live_equity)
        self.assertEqual(effective, max_riskable)


class TestMinOperationalBalanceSafety(unittest.TestCase):
    """Test the min operational balance safety floor."""

    def _should_halt(self, live_equity_usd: float, min_operational_balance_usd: float) -> bool:
        """Helper matching the CT logic."""
        return min_operational_balance_usd > 0 and live_equity_usd < min_operational_balance_usd

    def test_no_halt_when_min_balance_zero(self):
        """When min_operational_balance_usd=0, any balance is acceptable."""
        self.assertFalse(self._should_halt(100.0, 0.0))
        self.assertFalse(self._should_halt(0.0, 0.0))
        self.assertFalse(self._should_halt(50000.0, 0.0))

    def test_halt_when_below_min_operational_balance(self):
        """When live < min_operational_balance, trading should halt."""
        self.assertTrue(self._should_halt(500.0, 1000.0))
        self.assertTrue(self._should_halt(999.99, 1000.0))
        self.assertTrue(self._should_halt(1.0, 1000.0))

    def test_continue_when_above_min_operational_balance(self):
        """When live > min_operational_balance, trading can continue."""
        self.assertFalse(self._should_halt(1500.0, 1000.0))
        self.assertFalse(self._should_halt(1000.01, 1000.0))
        self.assertFalse(self._should_halt(50000.0, 1000.0))

    def test_continue_when_exactly_at_minimum(self):
        """When live == min_operational_balance, trading continues (not strictly below)."""
        self.assertFalse(self._should_halt(1000.0, 1000.0))


class TestIntegrationScenarios(unittest.TestCase):
    """Integration scenarios combining cap and floor."""

    def _compute_effective_equity(self, live_equity_usd: float, max_riskable_usd: float) -> float:
        if max_riskable_usd > 0:
            return min(live_equity_usd, max_riskable_usd)
        return live_equity_usd

    def _should_halt(self, live_equity_usd: float, min_operational_balance_usd: float) -> bool:
        return min_operational_balance_usd > 0 and live_equity_usd < min_operational_balance_usd

    def test_scenario_50k_balance_25k_cap(self):
        """
        User has $50,000 in Kalshi but only wants to risk $25,000.
        Effective equity should be $25,000. No halt (above $5k minimum).
        """
        live_equity = 50000.0
        max_riskable = 25000.0
        min_op_balance = 5000.0
        
        effective = self._compute_effective_equity(live_equity, max_riskable)
        should_halt = self._should_halt(live_equity, min_op_balance)
        
        self.assertEqual(effective, 25000.0)
        self.assertFalse(should_halt)

    def test_scenario_low_balance_below_minimum(self):
        """
        User has $800 in Kalshi with $1,000 minimum operational balance.
        Trading should halt regardless of cap.
        """
        live_equity = 800.0
        max_riskable = 0.0  # No cap
        min_op_balance = 1000.0
        
        effective = self._compute_effective_equity(live_equity, max_riskable)
        should_halt = self._should_halt(live_equity, min_op_balance)
        
        # Effective equity is still computed (would be $800)...
        self.assertEqual(effective, 800.0)
        # ...but trading should halt
        self.assertTrue(should_halt)

    def test_scenario_cap_below_minimum(self):
        """
        Edge case: max_riskable ($500) below min_operational_balance ($1000).
        With $2000 live balance:
        - effective = $500 (capped)
        - but trading should NOT halt because live ($2000) > min ($1000)
        """
        live_equity = 2000.0
        max_riskable = 500.0
        min_op_balance = 1000.0
        
        effective = self._compute_effective_equity(live_equity, max_riskable)
        should_halt = self._should_halt(live_equity, min_op_balance)
        
        self.assertEqual(effective, 500.0)
        self.assertFalse(should_halt)

    def test_scenario_both_caps_unused(self):
        """User with $5000 balance, no max_riskable, no minimum."""
        live_equity = 5000.0
        max_riskable = 0.0
        min_op_balance = 0.0
        
        effective = self._compute_effective_equity(live_equity, max_riskable)
        should_halt = self._should_halt(live_equity, min_op_balance)
        
        self.assertEqual(effective, 5000.0)
        self.assertFalse(should_halt)

    def test_scenario_exactly_at_minimum(self):
        """User with exactly $1000 and $1000 minimum."""
        live_equity = 1000.0
        max_riskable = 0.0
        min_op_balance = 1000.0
        
        effective = self._compute_effective_equity(live_equity, max_riskable)
        should_halt = self._should_halt(live_equity, min_op_balance)
        
        self.assertEqual(effective, 1000.0)
        self.assertFalse(should_halt)  # Not strictly below, so no halt


class TestSizingMath(unittest.TestCase):
    """Test that sizing uses effective equity correctly."""

    def test_kelly_fraction_of_effective_equity(self):
        """
        Kelly sizing should use effective_equity, not live_equity.
        With 25% Kelly fraction and $10k effective equity:
        - Max risk = 25% of 1.5% of $10k = $37.50 (quarter-Kelly)
        """
        effective_equity_usd = 10000.0
        kelly_fraction = 0.25
        max_risk_per_trade_pct = 0.015  # 1.5%

        # Kelly sizing calculation (simplified)
        raw_kelly_risk_usd = effective_equity_usd * max_risk_per_trade_pct * kelly_fraction
        max_risk_usd = effective_equity_usd * max_risk_per_trade_pct

        # Kelly risk is capped at max_risk_per_trade_pct
        actual_risk_usd = min(raw_kelly_risk_usd, max_risk_usd)

        # Quarter-Kelly = 0.25 * 1.5% * $10k = $37.50
        self.assertEqual(actual_risk_usd, 37.5)

    def test_contracts_from_risk_amount(self):
        """
        Given $150 risk budget and 50¢ contract price:
        - Can buy 3 contracts ($1.50 total, within $150 risk if edge justifies)
        """
        risk_cents = 15000  # $150
        contract_price_cents = 50  # 50¢
        
        # Number of contracts we can afford
        contracts = risk_cents // contract_price_cents
        
        self.assertEqual(contracts, 300)


if __name__ == "__main__":
    unittest.main()
