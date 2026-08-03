"""
Unit tests for fee-aware edge calculation integration with router.

Tests that the router's edge calculation correctly accounts for Kalshi
taker fees using the canonical tiered fee formula.
"""

import pytest
from merid.event_venues.kalshi.spread_edge_analytics import (
    compute_canonical_spreads,
    compute_per_side_edges,
    PerSideEdgeMetrics
)


def test_fee_aware_edge_calculation_yes_side():
    """Test fee-aware edge calculation for YES side."""
    # Setup: YES bid 40c, NO bid 60c (market implies 40% YES probability)
    yes_bid_cents = 40
    no_bid_cents = 60
    
    # Model thinks YES is 50% (edge = 10c)
    p_hat_yes_cents = 50.0
    
    # Compute spreads
    spread_metrics = compute_canonical_spreads(yes_bid_cents, no_bid_cents)
    
    # Compute edges with fee deduction
    # CRITICAL FIX 2026-07-28: Pass order_side for correct price usage
    # CRITICAL FIX 2026-07-31: Use taker economics to test fee calculation
    yes_edge, no_edge = compute_per_side_edges(p_hat_yes_cents, spread_metrics, order_price_cents=40, contracts=1, order_side="yes", use_maker_economics=False)
    
    # Verify fee is included in calculation
    assert yes_edge.taker_fee_cents > 0, f"YES side should have positive taker fee, got {yes_edge.taker_fee_cents}c"
    
    # Verify executable edge accounts for fee
    # Raw edge = 50c - 40c = 10c
    # Executable edge = raw_edge - spread_cost - taker_fee
    # Should be less than raw edge
    assert yes_edge.executable_edge_cents < yes_edge.raw_edge_cents, \
        f"Executable edge ({yes_edge.executable_edge_cents}c) should be < raw edge ({yes_edge.raw_edge_cents}c)"
    
    # Verify executable edge is positive (edge > costs)
    assert yes_edge.executable_edge_cents > 0, \
        f"Executable edge should be positive, got {yes_edge.executable_edge_cents}c"


def test_fee_aware_edge_calculation_no_side():
    """Test fee-aware edge calculation for NO side."""
    # Setup: YES bid 40c, NO bid 60c (market implies 40% YES probability)
    yes_bid_cents = 40
    no_bid_cents = 60
    
    # Model thinks YES is 30% (NO prob = 70%)
    # CRITICAL FIX 2026-07-31: For NO orders, pass NO probability as canonical YES probability
    # This ensures the edge calculation works correctly: no_raw_edge = (100 - p_hat_yes) - no_bid
    # With p_hat_yes=70 (NO prob): no_raw_edge = (100 - 70) - 60 = -30c (negative, expected)
    # Wait, this is wrong. Let me reconsider...
    # 
    # Actually, the edge calculation should be:
    # - For BUY_NO at 60c when model thinks NO is 70c: edge = 70c - 60c = 10c (positive)
    # - But compute_per_side_edges expects canonical YES prob and derives NO internally
    # - So we need to pass the YES probability that makes the derived NO probability correct
    # - If model thinks NO=70c, then YES=30c, which is what we should pass
    # - Then no_raw_edge = (100 - 30) - 60 = 10c (correct!)
    p_hat_yes_cents = 30.0  # YES probability (model thinks YES is 30%, NO is 70%)
    
    # Compute spreads
    spread_metrics = compute_canonical_spreads(yes_bid_cents, no_bid_cents)
    
    # Compute edges with fee deduction
    # CRITICAL FIX 2026-07-28: Pass order_side for correct price usage
    # CRITICAL FIX 2026-07-31: Use taker economics to test fee calculation
    yes_edge, no_edge = compute_per_side_edges(p_hat_yes_cents, spread_metrics, order_price_cents=60, contracts=1, order_side="no", use_maker_economics=False)
    
    # Verify fee is included in calculation
    assert no_edge.taker_fee_cents > 0, f"NO side should have positive taker fee, got {no_edge.taker_fee_cents}c"
    
    # Verify executable edge accounts for fee
    # Raw edge = (100 - 30c) - 60c = 10c
    # Executable edge = raw_edge - spread_cost - taker_fee
    # Should be less than raw edge
    assert no_edge.executable_edge_cents < no_edge.raw_edge_cents, \
        f"Executable edge ({no_edge.executable_edge_cents}c) should be < raw edge ({no_edge.raw_edge_cents}c)"
    
    # Verify executable edge is positive (edge > costs)
    assert no_edge.executable_edge_cents > 0, \
        f"Executable edge should be positive, got {no_edge.executable_edge_cents}c"


def test_fee_aware_edge_with_multiple_contracts():
    """Test fee-aware edge calculation with multiple contracts."""
    # Setup: YES bid 40c, NO bid 60c
    yes_bid_cents = 40
    no_bid_cents = 60
    p_hat_yes_cents = 50.0
    
    # Compute spreads
    spread_metrics = compute_canonical_spreads(yes_bid_cents, no_bid_cents)
    
    # Compute edges with 10 contracts
    # CRITICAL FIX 2026-07-28: Pass order_side for correct price usage
    # CRITICAL FIX 2026-07-31: Use taker economics to test fee calculation
    yes_edge_10, no_edge_10 = compute_per_side_edges(p_hat_yes_cents, spread_metrics, order_price_cents=40, contracts=10, order_side="yes", use_maker_economics=False)
    
    # Compute edges with 100 contracts (different fee tier)
    # CRITICAL FIX 2026-07-28: Pass order_side for correct price usage
    # CRITICAL FIX 2026-07-31: Use taker economics to test fee calculation
    yes_edge_100, no_edge_100 = compute_per_side_edges(p_hat_yes_cents, spread_metrics, order_price_cents=40, contracts=100, order_side="yes", use_maker_economics=False)
    
    # Fee per contract should be different due to tiering
    # 10 contracts: 7% tier
    # 100 contracts: 5% tier
    # Fee per contract should be lower for 100 contracts
    assert yes_edge_100.taker_fee_cents < yes_edge_10.taker_fee_cents, \
        f"Fee per contract for 100 contracts ({yes_edge_100.taker_fee_cents}c) should be < fee for 10 contracts ({yes_edge_10.taker_fee_cents}c)"


def test_fee_aware_edge_at_extreme_prices():
    """Test fee-aware edge calculation at price extremes (5c and 95c)."""
    # Setup: YES bid 5c, NO bid 95c (extreme price)
    yes_bid_cents = 5
    no_bid_cents = 95
    p_hat_yes_cents = 10.0  # Model thinks 10% YES (edge = 5c)
    
    # Compute spreads
    spread_metrics = compute_canonical_spreads(yes_bid_cents, no_bid_cents)
    
    # Compute edges
    # CRITICAL FIX 2026-07-28: Pass order_side for correct price usage
    # CRITICAL FIX 2026-07-31: Use taker economics to test fee calculation
    yes_edge, no_edge = compute_per_side_edges(p_hat_yes_cents, spread_metrics, order_price_cents=5, contracts=1, order_side="yes", use_maker_economics=False)
    
    # Fee should be minimal at extreme prices
    assert yes_edge.taker_fee_cents >= 0, f"Fee should be non-negative at 5c, got {yes_edge.taker_fee_cents}c"
    
    # Executable edge should still be positive
    assert yes_edge.executable_edge_cents > 0, \
        f"Executable edge should be positive at extreme price, got {yes_edge.executable_edge_cents}c"


def test_fee_aware_edge_cost_breakdown():
    """Test that edge metrics include complete cost breakdown."""
    # Setup: YES bid 39c, NO bid 60c (spread = 1c)
    yes_bid_cents = 39
    no_bid_cents = 60
    p_hat_yes_cents = 50.0
    
    # Compute spreads
    spread_metrics = compute_canonical_spreads(yes_bid_cents, no_bid_cents)
    
    # Compute edges
    # CRITICAL FIX 2026-07-28: Pass order_side for correct price usage
    # CRITICAL FIX 2026-07-31: Use taker economics to test fee calculation
    yes_edge, no_edge = compute_per_side_edges(p_hat_yes_cents, spread_metrics, order_price_cents=39, contracts=1, order_side="yes", use_maker_economics=False)
    
    # Verify all cost fields are populated
    assert yes_edge.spread_cost_cents >= 0, f"Spread cost should be non-negative, got {yes_edge.spread_cost_cents}c"
    assert yes_edge.taker_fee_cents > 0, f"Taker fee should be positive, got {yes_edge.taker_fee_cents}c"
    
    # Verify executable edge formula: raw_edge - spread_cost - taker_fee
    expected_executable = yes_edge.raw_edge_cents - yes_edge.spread_cost_cents - yes_edge.taker_fee_cents
    assert abs(yes_edge.executable_edge_cents - expected_executable) < 0.01, \
        f"Executable edge calculation mismatch: expected {expected_executable}c, got {yes_edge.executable_edge_cents}c"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
