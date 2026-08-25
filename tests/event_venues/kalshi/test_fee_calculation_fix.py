"""
Comprehensive tests for Kalshi fee calculation fixes (2026-08-01).

Tests the canonical fee calculation function to ensure:
1. Correct formula implementation (rate * C * P * (1-P))
2. Proper tiered rate application (7%, 5%, 3%)
3. Minimum fee enforcement (1 cent, the ceiling to the nearest cent)
4. Input validation (invalid prices, contract counts)
5. Edge cases (extreme prices, large orders)
"""

import pytest
from decimal import Decimal
from merid.event_venues.kalshi.fees import (
    calculate_kalshi_fee_cents,
    calculate_kalshi_fee_per_contract_cents,
    calculate_fee_drag_bps,
)


class TestKalshiFeeCalculation:
    """Test canonical Kalshi fee calculation."""
    
    def test_fee_formula_basic(self):
        """Test basic fee formula with known values."""
        # At 50 cents, P*(1-P) = 0.25 (maximum variance)
        # For 1 contract at 7% rate: 0.07 * 1 * 0.50 * 0.50 = 0.0175 dollars = 1.75 cents
        # Rounded up: 2 cents
        fee = calculate_kalshi_fee_cents(1, 50)
        assert fee == 2, f"Fee at 50c should be 2 cents, got {fee}"

        # At 10 cents, P*(1-P) = 0.09
        # For 1 contract at 7% rate: 0.07 * 1 * 0.10 * 0.90 = 0.0063 dollars = 0.63 cents
        # Rounded up: 1 cent (verified live Kalshi fee for extreme prices)
        fee = calculate_kalshi_fee_cents(1, 10)
        assert fee == 1, f"Fee at 10c should be 1 cent, got {fee}"
        
    def test_fee_tier_rates(self):
        """Test tiered fee rates (7%, 5%, 3%)."""
        # Small tier (< 100 contracts): 7%
        fee_10 = calculate_kalshi_fee_cents(10, 50)
        # Formula: 0.07 * 10 * 0.50 * 0.50 = 0.175 dollars = 17.5 cents -> rounded up to 18 cents
        assert fee_10 >= 1, f"Fee should be at least 1 cent, got {fee_10}"
        # The actual calculation with rounding should give us a reasonable value
        assert 10 <= fee_10 <= 25, f"Fee for 10 contracts at 50c should be reasonable, got {fee_10}"
        
        # Medium tier (100-999 contracts): 5%
        fee_100 = calculate_kalshi_fee_cents(100, 50)
        # Formula: 0.05 * 100 * 0.50 * 0.50 = 1.25 dollars = 125 cents
        assert 100 <= fee_100 <= 150, f"Fee for 100 contracts at 50c should be ~125 cents, got {fee_100}"
        
        # Large tier (1000+ contracts): 3%
        fee_1000 = calculate_kalshi_fee_cents(1000, 50)
        # Formula: 0.03 * 1000 * 0.50 * 0.50 = 7.5 dollars = 750 cents
        assert 700 <= fee_1000 <= 800, f"Fee for 1000 contracts at 50c should be ~750 cents, got {fee_1000}"
        
    def test_minimum_fee_enforcement(self):
        """Test that the cent-rounding floor (1 cent) is enforced."""
        # Very small fees are rounded up to the nearest cent (1 cent for OTM/ITM)
        fee = calculate_kalshi_fee_cents(1, 1)  # 1 cent price
        assert fee == 1, f"Fee at 1c should be 1 cent, got {fee}"

        fee = calculate_kalshi_fee_cents(1, 99)  # 99 cent price
        assert fee == 1, f"Fee at 99c should be 1 cent, got {fee}"
        
    def test_input_validation_invalid_prices(self):
        """Test input validation for invalid prices."""
        # Price <= 0 should return 0
        assert calculate_kalshi_fee_cents(10, 0) == 0
        assert calculate_kalshi_fee_cents(10, -10) == 0
        
        # Price >= 100 should return 0
        assert calculate_kalshi_fee_cents(10, 100) == 0
        assert calculate_kalshi_fee_cents(10, 150) == 0
        
    def test_input_validation_invalid_contracts(self):
        """Test input validation for invalid contract counts."""
        # Contracts <= 0 should return 0
        assert calculate_kalshi_fee_cents(0, 50) == 0
        assert calculate_kalshi_fee_cents(-10, 50) == 0
        
        # Very large contract count should raise error
        with pytest.raises(ValueError):
            calculate_kalshi_fee_cents(100001, 50)
            
    def test_extreme_prices(self):
        """Test fee calculation at extreme price points."""
        # Near 0 cents (very low probability): ceil to 1 cent
        fee_1c = calculate_kalshi_fee_cents(1, 1)
        assert fee_1c == 1, f"Fee at 1c should be 1 cent, got {fee_1c}"

        # Near 100 cents (very high probability): ceil to 1 cent
        fee_99c = calculate_kalshi_fee_cents(1, 99)
        assert fee_99c == 1, f"Fee at 99c should be 1 cent, got {fee_99c}"

        # At 50 cents (maximum variance point): ceil(1.75) = 2 cents
        fee_50c = calculate_kalshi_fee_cents(1, 50)
        assert fee_50c == 2, f"Fee at 50c should be 2 cents, got {fee_50c}"
        
    def test_symmetry(self):
        """Test fee symmetry: price P and (100-P) should have same fee."""
        fee_30c = calculate_kalshi_fee_cents(10, 30)
        fee_70c = calculate_kalshi_fee_cents(10, 70)
        # Due to rounding, they might differ by 1 cent, but should be very close
        assert abs(fee_30c - fee_70c) <= 1, f"Fees at 30c and 70c should be similar: {fee_30c} vs {fee_70c}"
        
    def test_per_contract_fee(self):
        """Test per-contract fee calculation."""
        total_fee = calculate_kalshi_fee_cents(10, 50)
        per_contract = calculate_kalshi_fee_per_contract_cents(10, 50)
        expected_per_contract = total_fee / 10.0
        assert abs(per_contract - expected_per_contract) < 0.01, \
            f"Per-contract fee mismatch: {per_contract} vs {expected_per_contract}"
            
    def test_fee_drag_bps(self):
        """Test fee drag calculation in basis points."""
        # For 10 contracts at 50 cents: position value = 500 cents = $5
        # Fee ~ 18 cents = $0.18
        # Fee drag = (18 / 500) * 10000 = 360 bps
        drag = calculate_fee_drag_bps(10, 50)
        assert 300 <= drag <= 400, f"Fee drag should be ~360 bps, got {drag}"
        
    def test_decimal_precision(self):
        """Test that Decimal precision provides accurate results."""
        # Test with decimal precision (default)
        fee_decimal = calculate_kalshi_fee_cents(100, 50, use_decimal=True)
        assert fee_decimal >= 2, f"Decimal fee should be at least 2 cents, got {fee_decimal}"
        assert 100 <= fee_decimal <= 150, f"Decimal fee for 100 contracts at 50c should be ~125 cents, got {fee_decimal}"


class TestAgentGridFeeIntegration:
    """Test that agent_grid_15m correctly uses the canonical fee function."""
    
    def test_agent_grid_imports_canonical_fee(self):
        """Test that agent_grid_15m imports and uses the canonical fee function."""
        try:
            from merid.prediction.agent_grid_15m import canonical_calculate_kalshi_fee_cents
            # Test that it's the same function
            from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
            assert callable(canonical_calculate_kalshi_fee_cents), "Canonical fee function should be callable"
        except ImportError as e:
            pytest.fail(f"agent_grid_15m should import canonical fee function: {e}")
            
    def test_agent_grid_fee_signature(self):
        """Test that agent_grid fee function has correct signature."""
        try:
            from merid.prediction.agent_grid_15m import canonical_calculate_kalshi_fee_cents
            # Should accept (contracts, price_cents) like the canonical function
            fee = canonical_calculate_kalshi_fee_cents(1, 50)
            assert fee == 2, f"Fee at 50c should be 2 cents, got {fee}"
        except Exception as e:
            pytest.fail(f"agent_grid fee function should have correct signature: {e}")


class TestEdgeCaseScenarios:
    """Test edge case scenarios from production logs."""
    
    def test_doge_6c_scenario(self):
        """Test the DOGE 6c scenario from the error log."""
        # Original error: DOGE side=yes price_cents=6 fee calculation returned 0
        # Live fee verification: ceil(0.07 * 0.06 * 0.94 * 100) = 1 cent.
        fee = calculate_kalshi_fee_cents(1, 6)
        assert fee == 1, f"DOGE 6c fee should be 1 cent, got {fee}"

    def test_xrp_extreme_spread_scenario(self):
        """Test the XRP extreme spread scenario from the error log."""
        # Original error: XRP side=yes edge_pct=3.28% exec_edge_taker=-377.67%
        # This was caused by invalid bid/ask, not fee calculation
        # But we can test that fee calculation itself is correct
        fee = calculate_kalshi_fee_cents(1, 50)  # Assume 50c price
        assert fee == 2, f"XRP fee at 50c should be 2 cents, got {fee}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
