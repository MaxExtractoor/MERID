"""
Test dynamic group notional cap calculation.

This test verifies that the dynamic percentage-based group notional cap
follows 2026 best practices for prediction market risk management:
- Uses percentage-based sizing (2-5% of bankroll per position)
- Ensures minimum floor for small bankrolls (allows trading)
- Ensures maximum ceiling for large bankrolls (prevents excessive exposure)
"""

import unittest
from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter


class TestDynamicGroupNotionalCap(unittest.TestCase):
    """Test dynamic group notional cap calculation."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a mock profile adapter with the new dynamic parameters
        self.adapter = Crypto15mProfileAdapter.__new__(Crypto15mProfileAdapter)
        # Store parameters directly since profile property has no setter
        self.pct = 0.05  # 5%
        self.min_usd = 5.00  # $5 minimum
        self.max_usd = 2000.0  # $2000 maximum

    def test_small_bankroll_uses_minimum_floor(self):
        """Test that small bankrolls use the minimum floor cap."""
        # With $40 bankroll at 5%, percentage cap would be $2.00
        # But minimum floor is $5.00, so should use $5.00
        bankroll = 40.0
        
        result = self.adapter._compute_dynamic_group_notional_cap(bankroll, self.pct, self.min_usd, self.max_usd)
        
        # Should use minimum floor since 5% of $40 is only $2.00
        self.assertEqual(result, 5.00)
        
    def test_medium_bankroll_uses_percentage(self):
        """Test that medium bankrolls use the percentage-based cap."""
        # With $1000 bankroll at 5%, percentage cap is $50.00
        # This is within min/max bounds, so should use $50.00
        bankroll = 1000.0
        
        result = self.adapter._compute_dynamic_group_notional_cap(bankroll, self.pct, self.min_usd, self.max_usd)
        
        # Should use percentage-based cap
        self.assertEqual(result, 50.00)
        
    def test_large_bankroll_uses_maximum_ceiling(self):
        """Test that large bankrolls use the maximum ceiling cap."""
        # With $100,000 bankroll at 5%, percentage cap would be $5,000.00
        # But maximum ceiling is $2,000.00, so should use $2,000.00
        bankroll = 100000.0
        
        result = self.adapter._compute_dynamic_group_notional_cap(bankroll, self.pct, self.min_usd, self.max_usd)
        
        # Should use maximum ceiling since 5% of $100k exceeds max
        self.assertEqual(result, 2000.00)
        
    def test_edge_case_exact_minimum(self):
        """Test edge case where percentage cap equals minimum floor."""
        # With $100 bankroll at 5%, percentage cap is $5.00
        # This equals the minimum floor, so should use $5.00
        bankroll = 100.0
        
        result = self.adapter._compute_dynamic_group_notional_cap(bankroll, self.pct, self.min_usd, self.max_usd)
        
        # Should use percentage-based cap (equals minimum)
        self.assertEqual(result, 5.00)
        
    def test_edge_case_exact_maximum(self):
        """Test edge case where percentage cap equals maximum ceiling."""
        # With $40,000 bankroll at 5%, percentage cap is $2,000.00
        # This equals the maximum ceiling, so should use $2,000.00
        bankroll = 40000.0
        
        result = self.adapter._compute_dynamic_group_notional_cap(bankroll, self.pct, self.min_usd, self.max_usd)
        
        # Should use percentage-based cap (equals maximum)
        self.assertEqual(result, 2000.00)
        
    def test_current_production_bankroll(self):
        """Test with the current production bankroll of ~$40.31."""
        # Current production bankroll is approximately $40.31
        # At 5%, this would be $2.02, but minimum floor is $5.00
        bankroll = 40.31
        
        result = self.adapter._compute_dynamic_group_notional_cap(bankroll, self.pct, self.min_usd, self.max_usd)
        
        # Should use minimum floor to allow trading
        self.assertEqual(result, 5.00)
        # This is significantly higher than the current $0.81 (2% of $40.31)
        # and should allow trades to execute


if __name__ == '__main__':
    unittest.main()
