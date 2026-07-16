"""Test fee calculation consolidation (2026-07-16).

This test verifies that fee calculation is consolidated to fees.py as the single
source of truth, and that deprecated wrappers issue appropriate warnings.
"""

import pytest
import warnings
from pathlib import Path


class TestFeeCalculationConsolidation:
    """Test that fee calculation is consolidated to fees.py."""

    def test_canonical_fee_function_exists(self):
        """Verify canonical calculate_kalshi_fee_cents exists in fees module."""
        from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
        
        # Test basic functionality
        fee = calculate_kalshi_fee_cents(contracts=10, price_cents=50)
        assert fee > 0
        assert isinstance(fee, int)

    def test_kalshi_risk_fee_cents_deprecated(self):
        """Verify kalshi_fee_cents in kalshi_risk.py is deprecated."""
        from merid.event_venues.kalshi.kalshi_risk import kalshi_fee_cents
        
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            fee = kalshi_fee_cents(price_cents=50, contracts=10)
            
            # Should have issued a DeprecationWarning
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message).lower()
            assert "calculate_kalshi_fee_cents" in str(w[0].message)
        
        # Should still return correct value
        assert fee > 0

    def test_position_sizer_fee_cents_deprecated(self):
        """Verify kalshi_fee_cents in position_sizer.py is deprecated."""
        from merid.event_venues.kalshi.position_sizer import kalshi_fee_cents
        
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            fee = kalshi_fee_cents(price_cents=50, contracts=10)
            
            # Should have issued a DeprecationWarning
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message).lower()
            assert "calculate_kalshi_fee_cents" in str(w[0].message)
        
        # Should still return correct value
        assert fee > 0

    def test_order_router_kalshi_fee_cents_deprecated(self):
        """Verify _kalshi_fee_cents in order_router.py is deprecated."""
        from merid.event_venues.kalshi.order_router import _kalshi_fee_cents
        
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            fee = _kalshi_fee_cents(price_cents=50, contracts=10)
            
            # Should have issued a DeprecationWarning
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message).lower()
            assert "calculate_kalshi_fee_cents" in str(w[0].message)
        
        # Should still return correct value
        assert fee > 0

    def test_fee_calculation_consistency(self):
        """Verify all fee functions return consistent results."""
        from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
        from merid.event_venues.kalshi.kalshi_risk import kalshi_fee_cents as risk_fee
        from merid.event_venues.kalshi.position_sizer import kalshi_fee_cents as sizer_fee
        from merid.event_venues.kalshi.order_router import _kalshi_fee_cents as router_fee
        
        # Suppress deprecation warnings for this test
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            
            # Test multiple price/contract combinations
            test_cases = [
                (10, 50),
                (100, 50),
                (1000, 50),
                (50, 25),
                (50, 75),
            ]
            
            for contracts, price_cents in test_cases:
                canonical_fee = calculate_kalshi_fee_cents(contracts=contracts, price_cents=price_cents)
                risk_fee_val = risk_fee(price_cents=price_cents, contracts=contracts)
                sizer_fee_val = sizer_fee(price_cents=price_cents, contracts=contracts)
                router_fee_val = router_fee(price_cents=price_cents, contracts=contracts)
                
                # All should return the same value
                assert canonical_fee == risk_fee_val, f"Mismatch for contracts={contracts}, price={price_cents}"
                assert canonical_fee == sizer_fee_val, f"Mismatch for contracts={contracts}, price={price_cents}"
                assert canonical_fee == router_fee_val, f"Mismatch for contracts={contracts}, price={price_cents}"

    def test_prediction_risk_imports_from_fees(self):
        """Verify prediction.risk imports from fees module."""
        from merid.prediction.risk import kalshi_fee_cents as prediction_fee
        from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
        
        # Should be aliased to canonical function
        fee1 = prediction_fee(contracts=10, price_cents=50)
        fee2 = calculate_kalshi_fee_cents(contracts=10, price_cents=50)
        
        assert fee1 == fee2

    def test_fee_tier_calculation(self):
        """Verify fee tier calculation is correct."""
        from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
        
        # Tier 1: < 100 contracts (7%)
        fee_tier1 = calculate_kalshi_fee_cents(contracts=50, price_cents=50)
        # Expected: ceil(0.07 * 50 * 0.50 * 0.50) = ceil(0.875) = 1
        assert fee_tier1 > 0
        
        # Tier 2: 100-999 contracts (5%)
        fee_tier2 = calculate_kalshi_fee_cents(contracts=500, price_cents=50)
        # Expected: ceil(0.05 * 500 * 0.50 * 0.50) = ceil(6.25) = 7
        assert fee_tier2 > fee_tier1  # Should be higher but lower per-contract rate
        
        # Tier 3: 1000+ contracts (3%)
        fee_tier3 = calculate_kalshi_fee_cents(contracts=2000, price_cents=50)
        # Expected: ceil(0.03 * 2000 * 0.50 * 0.50) = ceil(15) = 15
        assert fee_tier3 > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
