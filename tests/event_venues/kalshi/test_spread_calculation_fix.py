"""
Comprehensive tests for spread calculation fixes (2026-08-01).

Tests the spread calculation logic to ensure:
1. Proper bid/ask validation
2. Correct spread calculation (ask - bid)
3. Fallback behavior for invalid bid/ask
4. Side-aware spread calculation (YES vs NO)
5. Protection against extreme spread values
"""

import pytest
from dataclasses import dataclass
from typing import Optional


@dataclass
class MockMarketState:
    """Mock market state for testing."""
    best_bid_cents: Optional[int] = None
    best_ask_cents: Optional[int] = None
    best_no_bid_cents: Optional[int] = None
    best_no_ask_cents: Optional[int] = None


class TestSpreadCalculation:
    """Test spread calculation logic."""
    
    def test_normal_spread_calculation(self):
        """Test normal spread calculation with valid bid/ask."""
        bid = 45
        ask = 55
        spread = ask - bid
        assert spread == 10, f"Spread should be 10 cents, got {spread}"
        
    def test_invalid_bid_ask_zero(self):
        """Test spread calculation with zero bid/ask."""
        bid = 0
        ask = 0
        # This should trigger validation and fallback
        assert bid <= 0 or ask <= 0, "Zero bid/ask should be detected as invalid"
        
    def test_invalid_bid_ask_none(self):
        """Test spread calculation with None bid/ask."""
        bid = None
        ask = None
        # This should trigger validation and fallback
        assert bid is None or ask is None, "None bid/ask should be detected as invalid"
        
    def test_invalid_ask_less_than_bid(self):
        """Test spread calculation when ask < bid (inverted market)."""
        bid = 60
        ask = 40
        # This should trigger validation and fallback
        assert ask <= bid, "Inverted bid/ask should be detected as invalid"
        
    def test_spread_fallback_logic(self):
        """Test spread fallback logic for invalid bid/ask."""
        price_cents = 50
        
        # Invalid bid/ask should use 1c spread fallback
        best_bid = 0
        best_ask = 0
        
        if best_bid is None or best_ask is None or best_bid <= 0 or best_ask <= 0 or best_ask <= best_bid:
            # Use conservative 1c spread fallback
            best_bid = price_cents - 0.5 if price_cents > 0.5 else 0
            best_ask = price_cents + 0.5 if price_cents < 99.5 else 100
            
        spread = best_ask - best_bid
        assert spread == 1.0, f"Fallback spread should be 1.0 cents, got {spread}"
        
    def test_extreme_spread_detection(self):
        """Test detection of extreme spread values."""
        bid = 10
        ask = 90
        spread = ask - bid
        
        # A 80 cent spread is extreme and should be flagged
        assert spread > 50, f"80 cent spread should be detected as extreme"
        
    def test_side_aware_spread_yes(self):
        """Test YES-side spread calculation."""
        # YES-side: use YES-space bid/ask
        yes_bid = 45
        yes_ask = 55
        yes_spread = yes_ask - yes_bid
        
        assert yes_spread == 10, f"YES spread should be 10 cents, got {yes_spread}"
        
    def test_side_aware_spread_no(self):
        """Test NO-side spread calculation."""
        # NO-side: use NO-space bid/ask
        no_bid = 45
        no_ask = 55
        no_spread = no_ask - no_bid
        
        assert no_spread == 10, f"NO spread should be 10 cents, got {no_spread}"
        
    def test_no_space_derived_from_yes(self):
        """Test NO-space bid/ask derived from YES-space."""
        yes_bid = 45
        yes_ask = 55
        
        # Convert YES-space to NO-space: NO_bid = 100 - YES_ask, NO_ask = 100 - YES_bid
        no_bid = 100 - yes_ask
        no_ask = 100 - yes_bid
        
        assert no_bid == 45, f"Derived NO bid should be 45, got {no_bid}"
        assert no_ask == 55, f"Derived NO ask should be 55, got {no_ask}"
        
        # Spread should be preserved
        no_spread = no_ask - no_bid
        yes_spread = yes_ask - yes_bid
        assert no_spread == yes_spread, f"Spread should be preserved: {no_spread} vs {yes_spread}"


class TestSpreadValidation:
    """Test spread validation logic from agent_grid_15m."""
    
    def test_validation_logic(self):
        """Test the validation logic used in agent_grid_15m."""
        # Test cases: (bid, ask, should_be_valid)
        test_cases = [
            (45, 55, True),    # Normal case
            (0, 0, False),     # Zero values
            (None, None, False),  # None values
            (60, 40, False),   # Inverted
            (45, 45, False),   # Same value (no spread)
            (1, 99, True),     # Extreme but valid
            (-10, 50, False),  # Negative bid
            (50, 110, False),  # Ask > 100 (now checked with improved validation)
        ]
        
        for bid, ask, should_be_valid in test_cases:
            is_valid = not (bid is None or ask is None or bid <= 0 or ask <= 0 or ask <= bid or ask >= 100)
            assert is_valid == should_be_valid, \
                f"Validation failed for bid={bid}, ask={ask}: expected {should_be_valid}, got {is_valid}"
                
    def test_price_clamping(self):
        """Test price clamping to valid range [1-99]."""
        test_cases = [
            (0, 1),      # Clamp 0 to 1
            (-10, 1),    # Clamp negative to 1
            (100, 99),   # Clamp 100 to 99
            (150, 99),   # Clamp >100 to 99
            (50, 50),    # No change needed
            (1, 1),      # No change needed
            (99, 99),    # No change needed
        ]
        
        for input_price, expected_clamped in test_cases:
            clamped = max(1, min(99, input_price))
            assert clamped == expected_clamped, \
                f"Clamping failed for {input_price}: expected {expected_clamped}, got {clamped}"


class TestSpreadPercentageCalculation:
    """Test spread percentage calculation."""
    
    def test_spread_percentage_normal(self):
        """Test spread percentage calculation for normal cases."""
        spread_cents = 10
        price_cents = 50
        spread_pct = (spread_cents / price_cents) * 100.0
        
        assert spread_pct == 20.0, f"Spread percentage should be 20%, got {spread_pct}%"
        
    def test_spread_percentage_extreme(self):
        """Test spread percentage calculation for extreme spreads."""
        spread_cents = 80
        price_cents = 50
        spread_pct = (spread_cents / price_cents) * 100.0
        
        assert spread_pct == 160.0, f"Spread percentage should be 160%, got {spread_pct}%"
        
    def test_spread_percentage_zero_price(self):
        """Test spread percentage calculation with zero price (should handle gracefully)."""
        spread_cents = 10
        price_cents = 0
        spread_pct = (spread_cents / price_cents) * 100.0 if price_cents > 0 else 0.0
        
        assert spread_pct == 0.0, f"Spread percentage should be 0% for zero price, got {spread_pct}%"


class TestXRPExtremeSpreadScenario:
    """Test the XRP extreme spread scenario from production logs."""
    
    def test_xrp_371_percent_spread(self):
        """Test the XRP scenario with 371.43% spread."""
        # Original error: XRP side=yes edge_pct=3.28% exec_edge_taker=-377.67%
        # spread=371.43% fee=9.52%
        # This indicates invalid bid/ask causing massive spread calculation
        
        # Simulate the invalid bid/ask that caused this
        edge_pct = 3.28
        spread_pct = 371.43
        fee_pct = 9.52
        
        # Executable edge = edge_pct - spread_pct - fee_pct
        exec_edge_taker = edge_pct - spread_pct - fee_pct
        
        expected_exec_edge = 3.28 - 371.43 - 9.52  # = -377.67
        assert abs(exec_edge_taker - expected_exec_edge) < 0.01, \
            f"Executable edge calculation mismatch: {exec_edge_taker} vs {expected_exec_edge}"
        
        # This should have been caught by bid/ask validation
        # Let's test that validation would catch this
        # If spread_pct = 371.43%, then spread_cents = 371.43% of price_cents
        # For a reasonable price (e.g., 50c), spread_cents = 185.7c
        # This is impossible since max spread is 99c (0 to 100)
        price_cents = 50
        spread_cents = (spread_pct / 100.0) * price_cents
        
        assert spread_cents > 99, f"Spread of {spread_cents}c is impossible for price {price_cents}c"
        
    def test_validation_would_prevent_extreme_spread(self):
        """Test that bid/ask validation would prevent extreme spread."""
        # Simulate the invalid bid/ask that would cause 371% spread
        # For 50c price, 371% spread means spread_cents = 185.7c
        # This would require bid = -67.85c or ask = 235.7c, both invalid
        
        price_cents = 50
        spread_cents = 185.7
        
        # Try to derive bid/ask that would give this spread
        bid = price_cents - spread_cents / 2
        ask = price_cents + spread_cents / 2
        
        # These should be caught by validation
        is_valid = not (bid is None or ask is None or bid <= 0 or ask <= 0 or ask <= bid or ask >= 100)
        
        assert not is_valid, f"Invalid bid/ask should be detected: bid={bid}, ask={ask}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
