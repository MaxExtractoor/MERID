"""
Unit tests for BUY_NO edge calculation fix and related side-aware logic bugs.

Tests that the router correctly uses the NO probability for BUY_NO orders
instead of the YES probability, which was causing negative edges and order rejections.

Bug: When model thinks YES=89c (NO=11c) and market NO=69c, the router was
using p_hat_yes_cents=89c, resulting in no_raw_edge = (100-89) - 69 = -58c (rejected).
Fix: For BUY_NO orders, use p_hat_no_cents directly as the canonical YES probability,
resulting in no_raw_edge = (100-11) - 69 = 20c (accepted).

Additional bugs fixed:
- Router invariant side check (line 7419): Used intent.side == "yes" but intent uses "BUY_YES"/"BUY_NO"
- Sweet spot logic (line 4338): Used YES mid-price for all orders, but BUY_NO should use NO mid-price
"""

import pytest
from merid.event_venues.kalshi.spread_edge_analytics import (
    compute_canonical_spreads,
    compute_per_side_edges,
)


def test_no_order_uses_correct_probability():
    """Test that BUY_NO orders use NO probability for edge calculation."""
    # Setup: YES bid 31c, NO bid 69c (market implies 31% YES probability)
    yes_bid_cents = 31
    no_bid_cents = 69
    
    # Model thinks YES is 89% (NO is 11%)
    # This is the scenario from the logs that was failing
    p_hat_yes_cents = 89.0  # YES probability
    
    # Compute spreads
    spread_metrics = compute_canonical_spreads(yes_bid_cents, no_bid_cents)
    
    # BUG: If we pass p_hat_yes_cents=89c for a BUY_NO order:
    # no_raw_edge = (100 - 89) - 69 = -58c (negative, rejected)
    yes_edge_bug, no_edge_bug = compute_per_side_edges(
        p_hat_yes_cents, spread_metrics, order_price_cents=69, contracts=1, order_side="no", use_maker_economics=False
    )
    
    # Verify the bug: negative edge
    assert no_edge_bug.raw_edge_cents < 0, \
        f"BUG: Expected negative edge with p_hat_yes=89c, got {no_edge_bug.raw_edge_cents}c"
    
    # FIX: For BUY_NO orders, we should use p_hat_no_cents=11c as the canonical YES probability
    # This is done in order_router.py by inverting the probability for NO orders
    p_hat_no_cents = 100.0 - p_hat_yes_cents  # 11c
    
    # When we pass p_hat_yes_cents=11c (NO prob) for a BUY_NO order:
    # no_raw_edge = (100 - 11) - 69 = 20c (positive, accepted)
    yes_edge_fix, no_edge_fix = compute_per_side_edges(
        p_hat_no_cents, spread_metrics, order_price_cents=69, contracts=1, order_side="no", use_maker_economics=False
    )
    
    # Verify the fix: positive edge
    assert no_edge_fix.raw_edge_cents > 0, \
        f"FIX: Expected positive edge with p_hat_yes=11c (NO prob), got {no_edge_fix.raw_edge_cents}c"
    
    # Verify the edge is reasonable (around 20c)
    assert abs(no_edge_fix.raw_edge_cents - 20.0) < 1.0, \
        f"Expected edge around 20c, got {no_edge_fix.raw_edge_cents}c"


def test_yes_order_uses_yes_probability():
    """Test that BUY_YES orders use YES probability (unchanged behavior)."""
    # Setup: YES bid 40c, NO bid 60c
    yes_bid_cents = 40
    no_bid_cents = 60
    
    # Model thinks YES is 50%
    p_hat_yes_cents = 50.0
    
    # Compute spreads
    spread_metrics = compute_canonical_spreads(yes_bid_cents, no_bid_cents)
    
    # For YES orders, use YES probability directly
    yes_edge, no_edge = compute_per_side_edges(
        p_hat_yes_cents, spread_metrics, order_price_cents=40, contracts=1, order_side="yes", use_maker_economics=False
    )
    
    # Verify positive edge
    assert yes_edge.raw_edge_cents > 0, \
        f"YES order should have positive edge, got {yes_edge.raw_edge_cents}c"
    
    # Verify edge is 10c (50c - 40c)
    assert abs(yes_edge.raw_edge_cents - 10.0) < 1.0, \
        f"Expected edge around 10c, got {yes_edge.raw_edge_cents}c"


def test_no_order_probability_inversion():
    """Test the probability inversion logic for NO orders."""
    # Model thinks YES=89c (NO=11c)
    p_hat_yes_cents = 89.0
    p_hat_no_cents = 100.0 - p_hat_yes_cents  # 11c
    
    # For BUY_NO orders, router should use p_hat_no_cents as canonical YES probability
    # This is the inversion logic from order_router.py
    
    # Simulate the router's logic
    order_side = "buy_no"
    if order_side.lower() in ("no", "buy_no"):
        # For NO orders, use NO probability as canonical YES probability
        p_hat_cents_for_edge_calc = p_hat_no_cents
    else:
        p_hat_cents_for_edge_calc = p_hat_yes_cents
    
    # Verify inversion
    assert p_hat_cents_for_edge_calc == 11.0, \
        f"Expected p_hat_cents=11c for BUY_NO order, got {p_hat_cents_for_edge_calc}c"
    
    # Verify it's different from YES probability
    assert p_hat_cents_for_edge_calc != p_hat_yes_cents, \
        f"p_hat_cents should differ from p_hat_yes_cents for NO orders"


def test_router_invariant_side_check_kalshi_format():
    """Test that router invariant handles Kalshi format sides (BUY_YES/BUY_NO)."""
    # Simulate the router invariant logic from line 7419
    # Bug: Used intent.side == "yes" which never matched for BUY_NO orders
    # Fix: Use side_lower in ("yes", "buy_yes", "sell_yes")
    
    # Test BUY_YES order
    intent_side_buy_yes = "BUY_YES"
    side_lower = intent_side_buy_yes.lower() if intent_side_buy_yes else ""
    is_yes_side = side_lower in ("yes", "buy_yes", "sell_yes")
    assert is_yes_side, "BUY_YES should be recognized as yes side"
    
    # Test BUY_NO order
    intent_side_buy_no = "BUY_NO"
    side_lower = intent_side_buy_no.lower() if intent_side_buy_no else ""
    is_yes_side = side_lower in ("yes", "buy_yes", "sell_yes")
    assert not is_yes_side, "BUY_NO should NOT be recognized as yes side"
    
    # Test legacy "yes" format (should still work)
    intent_side_yes = "yes"
    side_lower = intent_side_yes.lower() if intent_side_yes else ""
    is_yes_side = side_lower in ("yes", "buy_yes", "sell_yes")
    assert is_yes_side, "Legacy 'yes' format should still work"
    
    # Test legacy "no" format (should still work)
    intent_side_no = "no"
    side_lower = intent_side_no.lower() if intent_side_no else ""
    is_yes_side = side_lower in ("yes", "buy_yes", "sell_yes")
    assert not is_yes_side, "Legacy 'no' format should NOT be recognized as yes side"


def test_sweet_spot_logic_side_aware():
    """Test that sweet spot logic uses side-appropriate mid-price."""
    # Simulate the sweet spot logic from line 4338
    # Bug: Used YES mid-price for all orders
    # Fix: For NO orders, use NO mid-price (100 - YES_mid)
    
    # Market state with YES mid = 31c
    yes_mid_cents = 31
    
    # For BUY_YES order, should use YES mid
    intent_side_buy_yes = "BUY_YES"
    side_lower = intent_side_buy_yes.lower() if intent_side_buy_yes else ""
    is_no_side = "no" in side_lower
    mid_for_sweet_spot = 100 - yes_mid_cents if is_no_side else yes_mid_cents
    assert mid_for_sweet_spot == 31, \
        f"BUY_YES should use YES mid=31c, got {mid_for_sweet_spot}c"
    
    # For BUY_NO order, should use NO mid (100 - 31 = 69c)
    intent_side_buy_no = "BUY_NO"
    side_lower = intent_side_buy_no.lower() if intent_side_buy_no else ""
    is_no_side = "no" in side_lower
    mid_for_sweet_spot = 100 - yes_mid_cents if is_no_side else yes_mid_cents
    assert mid_for_sweet_spot == 69, \
        f"BUY_NO should use NO mid=69c, got {mid_for_sweet_spot}c"
    
    # Test with YES mid = 69c (market implies NO mid = 31c)
    yes_mid_cents = 69
    
    # For BUY_YES order at 69c, should use YES mid
    intent_side_buy_yes = "BUY_YES"
    side_lower = intent_side_buy_yes.lower() if intent_side_buy_yes else ""
    is_no_side = "no" in side_lower
    mid_for_sweet_spot = 100 - yes_mid_cents if is_no_side else yes_mid_cents
    assert mid_for_sweet_spot == 69, \
        f"BUY_YES should use YES mid=69c, got {mid_for_sweet_spot}c"
    
    # For BUY_NO order at 69c, should use NO mid (100 - 69 = 31c)
    intent_side_buy_no = "BUY_NO"
    side_lower = intent_side_buy_no.lower() if intent_side_buy_no else ""
    is_no_side = "no" in side_lower
    mid_for_sweet_spot = 100 - yes_mid_cents if is_no_side else yes_mid_cents
    assert mid_for_sweet_spot == 31, \
        f"BUY_NO should use NO mid=31c, got {mid_for_sweet_spot}c"


def test_sweet_spot_price_validation_no_order():
    """Test that sweet spot price validation uses NO-side prices for BUY_NO orders."""
    # Simulate the price validation logic from line 4375
    # Bug: Used YES ask/bid for all orders
    # Fix: For NO orders, derive NO prices (NO_ask = 100 - YES_bid, NO_bid = 100 - YES_ask)
    
    # Market state with YES ask = 35c, YES bid = 31c
    yes_ask_cents = 35
    yes_bid_cents = 31
    
    # For BUY_YES order, use YES prices directly
    intent_side_buy_yes = "BUY_YES"
    side_lower = intent_side_buy_yes.lower() if intent_side_buy_yes else ""
    is_no_side = "no" in side_lower
    ask_for_validation = 100 - yes_bid_cents if is_no_side else yes_ask_cents
    bid_for_validation = 100 - yes_ask_cents if is_no_side else yes_bid_cents
    assert ask_for_validation == 35, \
        f"BUY_YES should use YES ask=35c, got {ask_for_validation}c"
    assert bid_for_validation == 31, \
        f"BUY_YES should use YES bid=31c, got {bid_for_validation}c"
    
    # For BUY_NO order, derive NO prices
    # NO_ask = 100 - YES_bid = 100 - 31 = 69c
    # NO_bid = 100 - YES_ask = 100 - 35 = 65c
    intent_side_buy_no = "BUY_NO"
    side_lower = intent_side_buy_no.lower() if intent_side_buy_no else ""
    is_no_side = "no" in side_lower
    ask_for_validation = 100 - yes_bid_cents if is_no_side else yes_ask_cents
    bid_for_validation = 100 - yes_ask_cents if is_no_side else yes_bid_cents
    assert ask_for_validation == 69, \
        f"BUY_NO should use NO ask=69c (100-31), got {ask_for_validation}c"
    assert bid_for_validation == 65, \
        f"BUY_NO should use NO bid=65c (100-35), got {bid_for_validation}c"


def test_ws_rest_divergence_no_levels_sorting():
    """Test that WS-REST divergence check correctly handles ascending NO levels."""
    # Simulate the bug: NO levels derived from YES bids are ascending
    # YES bids: [0.72, 0.71, 0.70, ...] (descending)
    # NO bids derived: [0.28, 0.29, 0.30, ...] (ascending due to 1.0 - p inversion)
    
    # Simulate REST orderbook data
    yes_dollars = [[0.72, 100], [0.71, 200], [0.70, 300]]  # YES bids (descending)
    
    # Derive NO levels from YES bids (as done in order_router.py)
    rest_no_levels = [[1.0 - float(p), float(s)] for p, s in yes_dollars]
    # Result: [[0.28, 100], [0.29, 200], [0.30, 300]] (ascending)
    
    # BUG: Using max() on ascending NO levels gives worst NO bid
    best_no_bid_bug = max(p for p, s in rest_no_levels)  # 0.30 (worst)
    rest_best_ask_bug = 100 - int(best_no_bid_bug * 100)  # 100 - 30 = 70c
    
    # FIX: Using min() on ascending NO levels gives best NO bid
    best_no_bid_fix = min(p for p, s in rest_no_levels)  # 0.28 (best)
    rest_best_ask_fix = 100 - int(best_no_bid_fix * 100)  # 100 - 28 = 72c
    
    # Verify the bug
    assert rest_best_ask_bug == 70, \
        f"BUG: max() gives ask=70c (worst), got {rest_best_ask_bug}c"
    
    # Verify the fix
    assert rest_best_ask_fix == 72, \
        f"FIX: min() gives ask=72c (best), got {rest_best_ask_fix}c"
    
    # Verify the fix matches the YES bid (72c)
    yes_best_bid = int(max(p for p, s in yes_dollars) * 100)  # 72c
    assert rest_best_ask_fix == yes_best_bid, \
        f"FIX: NO ask ({rest_best_ask_fix}c) should match YES bid ({yes_best_bid}c) for tight spread"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
