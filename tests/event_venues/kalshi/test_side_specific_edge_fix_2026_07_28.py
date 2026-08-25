"""
Test suite for side-specific edge calculation fix (2026-07-28).

This test validates the critical fix where BUY_NO orders were incorrectly using
the YES-side price for edge calculation instead of the NO-side price.

The bug was in compute_per_side_edges() where line 233 reassigned no_order_price
to order_price_cents directly, overriding the correct side-specific assignment
done at lines 195-200 based on order_side.

This test ensures:
1. BUY_YES orders use order_price_cents for YES side, market bid for NO side
2. BUY_NO orders use order_price_cents for NO side, market bid for YES side
3. The edge calculation is correct for both sides
"""

import pytest
from merid.event_venues.kalshi.spread_edge_analytics import (
    compute_canonical_spreads,
    compute_per_side_edges,
    PerSideSpreadMetrics
)


class TestSideSpecificEdgeCalculation:
    """Test that order_price_cents is used correctly for the specified side."""
    
    def test_buy_yes_uses_order_price_for_yes_side(self):
        """BUY_YES should use order_price_cents for YES side, market bid for NO side."""
        # Market: YES bid=50c, NO bid=40c (spread=10c)
        spread_metrics = compute_canonical_spreads(yes_bid_cents=50, no_bid_cents=40)
        
        # Model prediction: YES at 60c (p_hat_yes=60c)
        p_hat_yes_cents = 60.0
        
        # Order: BUY YES at 55c (limit order better than market bid)
        order_price_cents = 55
        
        # Compute edges with order_side="yes"
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes_cents,
            spread_metrics=spread_metrics,
            order_price_cents=order_price_cents,
            contracts=1,
            order_side="yes"
        )
        
        # YES side should use order_price_cents (55c), not market bid (50c)
        # Raw edge = p_hat_yes - order_price = 60 - 55 = +5c
        assert yes_edge.raw_edge_cents == pytest.approx(5.0, abs=0.1)
        
        # NO side should use market bid (40c), not order_price_cents (55c)
        # p_hat_no = 100 - 60 = 40c
        # Raw edge = p_hat_no - no_bid = 40 - 40 = 0c
        assert no_edge.raw_edge_cents == pytest.approx(0.0, abs=0.1)
    
    def test_buy_no_uses_order_price_for_no_side(self):
        """BUY_NO should use order_price_cents for NO side, market bid for YES side."""
        # Market: YES bid=50c, NO bid=40c (spread=10c)
        spread_metrics = compute_canonical_spreads(yes_bid_cents=50, no_bid_cents=40)
        
        # Model prediction: YES at 60c (p_hat_yes=60c)
        p_hat_yes_cents = 60.0
        
        # Order: BUY NO at 35c (limit order better than market bid)
        order_price_cents = 35
        
        # Compute edges with order_side="no"
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes_cents,
            spread_metrics=spread_metrics,
            order_price_cents=order_price_cents,
            contracts=1,
            order_side="no"
        )
        
        # YES side should use market bid (50c), not order_price_cents (35c)
        # Raw edge = p_hat_yes - yes_bid = 60 - 50 = +10c
        assert yes_edge.raw_edge_cents == pytest.approx(10.0, abs=0.1)
        
        # NO side should use order_price_cents (35c), not market bid (40c)
        # p_hat_no = 100 - 60 = 40c
        # Raw edge = p_hat_no - order_price = 40 - 35 = +5c
        assert no_edge.raw_edge_cents == pytest.approx(5.0, abs=0.1)
    
    def test_bug_scenario_buy_no_positive_edge(self):
        """
        Test the exact bug scenario from logs:
        BTC BUY_NO p_hat=7.0c was rejected with edge=-55.00c (should be positive).
        
        The bug was that BUY_NO was using YES-side price instead of NO-side price.
        """
        # Market: YES bid=62c, NO bid=38c (spread=24c)
        spread_metrics = compute_canonical_spreads(yes_bid_cents=62, no_bid_cents=38)
        
        # Model prediction: YES at 93c (p_hat_yes=93c)
        # This means p_hat_no = 100 - 93 = 7c
        p_hat_yes_cents = 93.0
        
        # Order: BUY NO at 35c (NO-side price)
        order_price_cents = 35
        
        # Compute edges with order_side="no"
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes_cents,
            spread_metrics=spread_metrics,
            order_price_cents=order_price_cents,
            contracts=1,
            order_side="no"
        )
        
        # With the fix, NO side should use order_price_cents (35c)
        # p_hat_no = 100 - 93 = 7c
        # Raw edge = p_hat_no - order_price = 7 - 35 = -28c (negative due to spread cost)
        # But this is the CORRECT calculation using NO-side price
        
        # The bug would have used YES-side price (62c) incorrectly:
        # Bug calculation: raw_edge = 7 - 62 = -55c (WRONG)
        # Fixed calculation: raw_edge = 7 - 35 = -28c (CORRECT)
        
        # Verify we're using the NO-side price (35c), not YES-side (62c)
        assert no_edge.raw_edge_cents == pytest.approx(-28.0, abs=0.5)
        
        # Verify it's NOT the buggy calculation (-55c)
        assert no_edge.raw_edge_cents != pytest.approx(-55.0, abs=1.0)
    
    def test_no_order_side_uses_market_bids(self):
        """When order_side is None, both sides should use market bids."""
        # Market: YES bid=50c, NO bid=40c
        spread_metrics = compute_canonical_spreads(yes_bid_cents=50, no_bid_cents=40)
        
        # Model prediction: YES at 60c
        p_hat_yes_cents = 60.0
        
        # Order price provided but no order_side
        order_price_cents = 55
        
        # Compute edges with order_side=None
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes_cents,
            spread_metrics=spread_metrics,
            order_price_cents=order_price_cents,
            contracts=1,
            order_side=None
        )
        
        # Both sides should use market bids (legacy behavior)
        # YES: raw_edge = 60 - 50 = +10c
        assert yes_edge.raw_edge_cents == pytest.approx(10.0, abs=0.1)
        
        # NO: p_hat_no = 40, raw_edge = 40 - 40 = 0c
        assert no_edge.raw_edge_cents == pytest.approx(0.0, abs=0.1)
    
    def test_no_order_price_uses_market_bids(self):
        """When order_price_cents is None, both sides should use market bids."""
        # Market: YES bid=50c, NO bid=40c
        spread_metrics = compute_canonical_spreads(yes_bid_cents=50, no_bid_cents=40)
        
        # Model prediction: YES at 60c
        p_hat_yes_cents = 60.0
        
        # Compute edges with no order_price_cents
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes_cents,
            spread_metrics=spread_metrics,
            order_price_cents=None,
            contracts=1,
            order_side="yes"
        )
        
        # Both sides should use market bids
        # YES: raw_edge = 60 - 50 = +10c
        assert yes_edge.raw_edge_cents == pytest.approx(10.0, abs=0.1)
        
        # NO: p_hat_no = 40, raw_edge = 40 - 40 = 0c
        assert no_edge.raw_edge_cents == pytest.approx(0.0, abs=0.1)
    
    def test_case_insensitive_order_side(self):
        """order_side should be case-insensitive."""
        spread_metrics = compute_canonical_spreads(yes_bid_cents=50, no_bid_cents=40)
        p_hat_yes_cents = 60.0
        order_price_cents = 55
        
        # Test various case variations
        for side in ["yes", "YES", "Yes", "buy_yes", "BUY_YES"]:
            yes_edge, no_edge = compute_per_side_edges(
                p_hat_yes_cents=p_hat_yes_cents,
                spread_metrics=spread_metrics,
                order_price_cents=order_price_cents,
                contracts=1,
                order_side=side
            )
            # All should treat it as YES order
            assert yes_edge.raw_edge_cents == pytest.approx(5.0, abs=0.1)
        
        for side in ["no", "NO", "No", "buy_no", "BUY_NO"]:
            yes_edge, no_edge = compute_per_side_edges(
                p_hat_yes_cents=p_hat_yes_cents,
                spread_metrics=spread_metrics,
                order_price_cents=35,
                contracts=1,
                order_side=side
            )
            # All should treat it as NO order
            assert no_edge.raw_edge_cents == pytest.approx(5.0, abs=0.1)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
