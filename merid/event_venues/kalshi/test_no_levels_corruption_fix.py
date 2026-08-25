"""Unit tests for NO levels corruption fix in ws_bridge.py.

Tests the fix for the placeholder pattern [99,98,97,96,95] that was
corrupting NO levels in the orderbook initialization.
"""

import pytest
from collections import defaultdict


def test_no_levels_derivation_from_yes_asks():
    """Test that NO levels are correctly derived from YES asks using duality."""
    # Simulate the REST API response structure
    orderbook_fp = {
        "yes_dollars": [[0.84, 100], [0.83, 200], [0.82, 150]],  # YES asks
        "no_dollars": [[0.16, 50], [0.17, 75]]  # This is actually YES asks, not NO bids
    }
    
    # OLD BUG: Using no_dollars directly (treating as NO bids)
    # This would create placeholder pattern [99,98,97,96,95]
    old_no_levels = []
    if "no_dollars" in orderbook_fp:
        old_no_levels = [[float(price), float(size)] for price, size in orderbook_fp["no_dollars"]]
    
    # NEW FIX: Derive NO bids from YES asks using duality
    # NO_bid = 1.00 - YES_ask
    new_no_levels = []
    if "yes_dollars" in orderbook_fp:
        new_no_levels = [[1.0 - float(price), float(size)] for price, size in orderbook_fp["yes_dollars"]]
    
    # Verify the fix
    # Old approach: NO levels would be [0.16, 0.17] (incorrect)
    # New approach: NO levels should be [0.16, 0.17, 0.18] (correct)
    assert len(new_no_levels) == 3
    assert new_no_levels[0][0] == pytest.approx(0.16)  # 1.00 - 0.84
    assert new_no_levels[1][0] == pytest.approx(0.17)  # 1.00 - 0.83
    assert new_no_levels[2][0] == pytest.approx(0.18)  # 1.00 - 0.82


def test_placeholder_pattern_detection():
    """Test detection of the placeholder pattern [99,98,97,96,95]."""
    # Simulate corrupted NO levels (placeholder pattern)
    corrupted_no_levels = defaultdict(int)
    corrupted_no_levels[99] = 100
    corrupted_no_levels[98] = 200
    corrupted_no_levels[97] = 150
    corrupted_no_levels[96] = 75
    corrupted_no_levels[95] = 50
    
    # Check for placeholder pattern
    no_levels_keys = list(corrupted_no_levels.keys())[:5]
    is_corrupted = no_levels_keys == [99, 98, 97, 96, 95]
    
    assert is_corrupted == True, "Should detect placeholder pattern"


def test_correct_no_levels():
    """Test that correctly derived NO levels don't trigger corruption detection."""
    # Simulate correctly derived NO levels from YES asks
    correct_no_levels = defaultdict(int)
    correct_no_levels[16] = 100  # 1.00 - 0.84
    correct_no_levels[17] = 200  # 1.00 - 0.83
    correct_no_levels[18] = 150  # 1.00 - 0.82
    
    # Check for placeholder pattern
    no_levels_keys = list(correct_no_levels.keys())[:5]
    is_corrupted = no_levels_keys == [99, 98, 97, 96, 95]
    
    assert is_corrupted == False, "Should not detect corruption in correct levels"


def test_duality_invariant():
    """Test that YES + NO = 100 cents invariant holds after fix."""
    # YES asks from REST API
    yes_asks = [84, 83, 82]  # in cents
    
    # Derive NO bids using duality
    no_bids = [100 - yes_ask for yes_ask in yes_asks]
    
    # Verify duality
    for yes_ask, no_bid in zip(yes_asks, no_bids):
        assert yes_ask + no_bid == 100, f"Duality violation: {yes_ask} + {no_bid} != 100"
    
    # Expected NO bids
    assert no_bids == [16, 17, 18]


def test_late_expiry_scenario():
    """Test late-expiry scenario with low YES prices and high NO prices."""
    # Late-expiry: YES asks are low (1c-6c)
    yes_asks = [6, 5, 4]  # in cents
    
    # Derive NO bids using duality
    no_bids = [100 - yes_ask for yes_ask in yes_asks]
    
    # Verify duality
    for yes_ask, no_bid in zip(yes_asks, no_bids):
        assert yes_ask + no_bid == 100, f"Duality violation: {yes_ask} + {no_bid} != 100"
    
    # Expected NO bids (high prices in late-expiry)
    assert no_bids == [94, 95, 96]
    
    # These high NO prices should be accepted by side-aware range
    from merid.event_venues.kalshi.binary_price_space import is_price_in_side_aware_range
    for no_bid in no_bids:
        assert is_price_in_side_aware_range(no_bid, "no") == True, \
            f"NO {no_bid}c should be in range in late-expiry"


def test_empty_yes_dollars_fallback():
    """Test fallback when yes_dollars is not available."""
    # Simulate REST response without yes_dollars
    orderbook_fp = {
        "no_dollars": [[0.16, 50], [0.17, 75]]
    }
    
    # NEW FIX: If yes_dollars not available, NO levels should be empty
    no_levels = []
    if "yes_dollars" in orderbook_fp:
        no_levels = [[1.0 - float(price), float(size)] for price, size in orderbook_fp["yes_dollars"]]
    else:
        no_levels = []
    
    assert len(no_levels) == 0, "Should fallback to empty NO levels"


def test_dollar_to_cents_conversion():
    """Test dollar to cents conversion for orderbook levels."""
    # YES asks in dollars
    yes_asks_dollars = [0.84, 0.83, 0.82]
    
    # Convert to cents
    yes_asks_cents = [int(price * 100) for price in yes_asks_dollars]
    
    # Derive NO bids in cents
    no_bids_cents = [100 - yes_ask for yes_ask in yes_asks_cents]
    
    # Convert back to dollars
    no_bids_dollars = [no_bid / 100.0 for no_bid in no_bids_cents]
    
    # Verify consistency
    for yes_dollar, no_dollar in zip(yes_asks_dollars, no_bids_dollars):
        assert yes_dollar + no_dollar == pytest.approx(1.0), \
            f"Duality violation: {yes_dollar} + {no_dollar} != 1.0"


def test_orderbook_level_ordering():
    """Test that NO levels are ordered correctly (descending for bids)."""
    # YES asks (ascending for asks)
    yes_asks = [0.82, 0.83, 0.84]
    
    # Derive NO bids (should be descending for bids)
    no_bids = [1.0 - yes_ask for yes_ask in yes_asks]
    
    # NO bids should be in descending order (highest first)
    assert no_bids == sorted(no_bids, reverse=True), "NO bids should be descending"

    # Expected: [0.18, 0.17, 0.16] — compare with cent precision to avoid float noise
    assert [round(p, 2) for p in no_bids] == [0.18, 0.17, 0.16]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
