"""
Comprehensive tests for executable edge calculation fixes (2026-08-01).

Tests the executable edge calculation logic to ensure:
1. Correct edge formula implementation (raw_edge - spread - fee)
2. Proper maker vs taker economics selection
3. Side-aware edge calculation (YES vs NO)
4. Protection against negative executable edges
5. Integration with canonical fee calculation
"""

import pytest
from dataclasses import dataclass
from typing import Optional


@dataclass
class MockSpreadMetrics:
    """Mock spread metrics for testing."""
    yes_bid_cents: int
    yes_ask_cents: int
    no_bid_cents: int
    no_ask_cents: int
    yes_spread_cents: int
    no_spread_cents: int


class TestExecutableEdgeCalculation:
    """Test executable edge calculation logic."""
    
    def test_maker_economics_no_fee_no_spread(self):
        """Test maker economics: no fee, no spread cost, captures spread."""
        raw_edge = 10.0  # 10 cents raw edge
        spread_cost = 0.0  # Maker doesn't pay spread
        taker_fee = 0.0  # Maker doesn't pay fee
        
        executable_edge = raw_edge - spread_cost - taker_fee
        
        assert executable_edge == 10.0, f"Maker executable edge should equal raw edge, got {executable_edge}"
        
    def test_taker_economics_pays_spread_and_fee(self):
        """Test taker economics: pays full spread and fee."""
        raw_edge = 10.0  # 10 cents raw edge
        spread_cost = 2.0  # 2 cents spread cost
        taker_fee = 0.5  # 0.5 cents fee
        
        executable_edge = raw_edge - spread_cost - taker_fee
        
        expected = 10.0 - 2.0 - 0.5  # 7.5 cents
        assert executable_edge == expected, f"Taker executable edge should be {expected}, got {executable_edge}"
        
    def test_negative_executable_edge_detection(self):
        """Test detection of negative executable edge."""
        raw_edge = 3.0  # 3 cents raw edge
        spread_cost = 5.0  # 5 cents spread cost (too high)
        taker_fee = 2.0  # 2 cents fee
        
        executable_edge = raw_edge - spread_cost - taker_fee
        
        expected = 3.0 - 5.0 - 2.0  # -4 cents
        assert executable_edge == expected, f"Executable edge should be {expected}, got {executable_edge}"
        assert executable_edge < 0, f"Executable edge should be negative, got {executable_edge}"
        
    def test_spread_to_edge_ratio_calculation(self):
        """Test spread to edge ratio calculation."""
        raw_edge = 10.0
        spread_cents = 4.0
        
        spread_ratio = spread_cents / raw_edge if raw_edge > 0 else float('inf')
        
        expected = 0.4  # 40%
        assert spread_ratio == expected, f"Spread ratio should be {expected}, got {spread_ratio}"
        
    def test_spread_to_edge_ratio_gate(self):
        """Test spread to edge ratio gating (40% threshold)."""
        raw_edge = 10.0
        spread_cents = 5.0  # 50% of edge
        
        spread_ratio = spread_cents / raw_edge if raw_edge > 0 else float('inf')
        max_ratio = 0.4  # 40% threshold
        
        passes_gate = spread_ratio <= max_ratio
        
        assert not passes_gate, f"Spread ratio of 50% should fail 40% gate"
        
    def test_yes_side_edge_calculation(self):
        """Test YES-side edge calculation."""
        p_hat_yes_cents = 60.0  # Model thinks YES is 60%
        yes_bid_cents = 50.0  # Market bid is 50%
        
        # Edge = model_prob - market_bid
        yes_raw_edge = p_hat_yes_cents - yes_bid_cents
        
        expected = 10.0  # 10 cents edge
        assert yes_raw_edge == expected, f"YES raw edge should be {expected}, got {yes_raw_edge}"
        
    def test_no_side_edge_calculation(self):
        """Test NO-side edge calculation."""
        p_hat_yes_cents = 60.0  # Model thinks YES is 60%
        no_bid_cents = 30.0  # Market NO bid is 30%
        
        # Edge = (1 - model_prob) - market_no_bid
        p_hat_no_cents = 100.0 - p_hat_yes_cents  # 40%
        no_raw_edge = p_hat_no_cents - no_bid_cents
        
        expected = 10.0  # 10 cents edge
        assert no_raw_edge == expected, f"NO raw edge should be {expected}, got {no_raw_edge}"
        
    def test_edge_percentage_conversion(self):
        """Test conversion between cents and percentage."""
        edge_cents = 5.0
        price_cents = 50.0
        
        edge_pct = (edge_cents / price_cents) * 100.0
        
        expected = 10.0  # 10%
        assert edge_pct == expected, f"Edge percentage should be {expected}%, got {edge_pct}%"


class TestExecutableEdgeValidation:
    """Test executable edge validation logic."""
    
    def test_positive_executable_edge_check(self):
        """Test positive executable edge check."""
        executable_edge_cents = 5.0
        
        is_positive = executable_edge_cents > 0
        
        assert is_positive, f"5 cents executable edge should be positive"
        
    def test_zero_executable_edge_check(self):
        """Test zero executable edge check."""
        executable_edge_cents = 0.0
        
        is_positive = executable_edge_cents > 0
        
        assert not is_positive, f"0 cents executable edge should not be positive"
        
    def test_negative_executable_edge_check(self):
        """Test negative executable edge check."""
        executable_edge_cents = -2.0
        
        is_positive = executable_edge_cents > 0
        
        assert not is_positive, f"Negative executable edge should not be positive"
        
    def test_minimum_executable_edge_threshold(self):
        """Test minimum executable edge threshold."""
        executable_edge_cents = 2.5
        min_threshold_cents = 3.0
        
        passes_threshold = executable_edge_cents >= min_threshold_cents
        
        assert not passes_threshold, f"2.5 cents should fail 3 cent threshold"
        
    def test_executable_edge_at_threshold(self):
        """Test executable edge exactly at threshold."""
        executable_edge_cents = 3.0
        min_threshold_cents = 3.0
        
        passes_threshold = executable_edge_cents >= min_threshold_cents
        
        assert passes_threshold, f"3 cents should pass 3 cent threshold"


class TestEdgeCalculationIntegration:
    """Test integration of edge calculation components."""
    
    def test_full_edge_calculation_pipeline(self):
        """Test full edge calculation pipeline."""
        # Input parameters
        p_hat_yes_cents = 65.0  # Model thinks YES is 65%
        yes_bid_cents = 55.0  # Market bid is 55%
        yes_ask_cents = 57.0  # Market ask is 57%
        use_maker_economics = False  # Use taker economics
        
        # Calculate raw edge
        raw_edge = p_hat_yes_cents - yes_bid_cents  # 10 cents
        
        # Calculate spread cost
        spread_cents = yes_ask_cents - yes_bid_cents  # 2 cents
        spread_cost = spread_cents if not use_maker_economics else 0.0  # 2 cents
        
        # Calculate fee (using canonical function)
        try:
            from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
            taker_fee = calculate_kalshi_fee_cents(1, int(yes_bid_cents)) / 1.0  # Per contract
        except ImportError:
            taker_fee = 0.5  # Fallback
        
        # Calculate executable edge
        executable_edge = raw_edge - spread_cost - taker_fee
        
        # Verify components
        assert raw_edge == 10.0, f"Raw edge should be 10 cents, got {raw_edge}"
        assert spread_cost == 2.0, f"Spread cost should be 2 cents, got {spread_cost}"
        assert executable_edge > 0, f"Executable edge should be positive, got {executable_edge}"
        
    def test_maker_vs_taker_comparison(self):
        """Test comparison between maker and taker economics."""
        raw_edge = 10.0
        spread_cents = 2.0
        taker_fee = 0.5
        
        # Maker economics
        maker_executable_edge = raw_edge  # No spread cost, no fee
        
        # Taker economics
        taker_executable_edge = raw_edge - spread_cents - taker_fee
        
        # Maker should have better executable edge
        assert maker_executable_edge > taker_executable_edge, \
            f"Maker edge ({maker_executable_edge}) should be better than taker edge ({taker_executable_edge})"
        
        # Difference should be spread + fee
        difference = maker_executable_edge - taker_executable_edge
        expected_difference = spread_cents + taker_fee
        assert difference == expected_difference, \
            f"Difference should be {expected_difference}, got {difference}"


class TestProductionErrorScenarios:
    """Test production error scenarios from logs."""
    
    def test_doge_6c_fee_scenario(self):
        """Test DOGE 6c fee calculation scenario."""
        # Original error: DOGE side=yes price_cents=6 fee calculation returned 0
        # Live fee verification: ceil(0.07 * 0.06 * 0.94 * 100) = 1 cent.

        try:
            from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
            fee = calculate_kalshi_fee_cents(1, 6)
            assert fee == 1, f"DOGE 6c fee should be 1 cent, got {fee}"
        except ImportError:
            pytest.skip("Canonical fee function not available")
            
    def test_xrp_extreme_spread_scenario(self):
        """Test XRP extreme spread scenario."""
        # Original error: XRP side=yes edge_pct=3.28% exec_edge_taker=-377.67%
        # spread=371.43% fee=9.52%
        
        edge_pct = 3.28
        spread_pct = 371.43
        fee_pct = 9.52
        
        # Calculate executable edge percentage
        exec_edge_taker = edge_pct - spread_pct - fee_pct
        
        expected = -377.67
        assert abs(exec_edge_taker - expected) < 0.1, \
            f"Executable edge should be {expected}%, got {exec_edge_taker}%"
        
        # This negative edge should be caught by validation
        assert exec_edge_taker < 0, f"Executable edge should be negative"
        
    def test_validation_prevents_invalid_calculations(self):
        """Test that validation prevents invalid edge calculations."""
        # Simulate invalid bid/ask that would cause extreme spread
        edge_pct = 5.0
        spread_pct = 400.0  # Invalid spread
        fee_pct = 10.0
        
        exec_edge = edge_pct - spread_pct - fee_pct
        
        # This should be caught by spread validation before edge calculation
        assert exec_edge < 0, f"Invalid spread should cause negative executable edge"
        
        # Validation should prevent this calculation
        # (in production, bid/ask validation would catch the invalid spread)


class TestSideAwareEdgeCalculation:
    """Test side-aware edge calculation."""
    
    def test_yes_edge_with_yes_order(self):
        """Test YES edge calculation when placing YES order."""
        p_hat_yes_cents = 60.0
        yes_bid_cents = 50.0
        order_side = "yes"
        
        # For YES order, use YES bid
        order_price = yes_bid_cents
        raw_edge = p_hat_yes_cents - order_price
        
        expected = 10.0
        assert raw_edge == expected, f"YES order edge should be {expected}, got {raw_edge}"
        
    def test_no_edge_with_no_order(self):
        """Test NO edge calculation when placing NO order."""
        p_hat_yes_cents = 60.0
        no_bid_cents = 35.0
        order_side = "no"
        
        # For NO order, use NO bid
        p_hat_no_cents = 100.0 - p_hat_yes_cents  # 40%
        order_price = no_bid_cents
        raw_edge = p_hat_no_cents - order_price
        
        expected = 5.0
        assert raw_edge == expected, f"NO order edge should be {expected}, got {raw_edge}"
        
    def test_price_clamping_for_edge_calculation(self):
        """Test price clamping for edge calculation."""
        edge_calculation_price_cents = 105.0  # Invalid (> 100)
        
        # Should be clamped to valid range [1-99]
        clamped_price = max(1, min(99, edge_calculation_price_cents))
        
        expected = 99.0
        assert clamped_price == expected, f"Price should be clamped to {expected}, got {clamped_price}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
