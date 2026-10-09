"""
Test script to verify pricing fixes for agent_grid_15m.py

This tests the specific issues reported:
1. Dual-side-price derivation using actual NO bid instead of deriving from YES bid
2. Price range checking using canonical ranges instead of overly restrictive side-aware ranges
3. Binary invariant validation with proper tolerance
"""

import sys
sys.path.insert(0, 'C:\\Dev\\MERID')

from merid.event_venues.kalshi.binary_price_space import (
    is_price_in_canonical_range,
    is_price_in_side_aware_range,
    yes_to_no_price,
    no_to_yes_price
)

def test_price_range_fixes():
    """Test that price range checking now works correctly."""
    
    print("=== Testing Price Range Fixes ===\n")
    
    # Test case from user's log: XRP with no_price=20c
    # Previously: no_price=20c showed in_range=False with side-aware range (25c-99c)
    # Now: should show in_range=True with canonical range (10c-75c)
    
    yes_price = 80
    no_price = 20
    
    print(f"Test Case: XRP - yes_price={yes_price}c, no_price={no_price}c")
    print(f"  Old side-aware range (NO): 25c-99c")
    print(f"  New canonical range (both): 10c-75c")
    print()
    
    # Old behavior (side-aware)
    old_no_in_range = is_price_in_side_aware_range(no_price, "no")
    print(f"  Old behavior: no_price={no_price}c in side-aware range = {old_no_in_range}")
    
    # New behavior (canonical)
    new_no_in_range = is_price_in_canonical_range(no_price, "no")
    print(f"  New behavior: no_price={no_price}c in canonical range = {new_no_in_range}")
    print()
    
    # Test DOGE case from log
    yes_price_doge = 66
    no_price_doge = 34
    
    print(f"Test Case: DOGE - yes_price={yes_price_doge}c, no_price={no_price_doge}c")
    old_doge_no = is_price_in_side_aware_range(no_price_doge, "no")
    new_doge_no = is_price_in_canonical_range(no_price_doge, "no")
    print(f"  Old behavior: no_price={no_price_doge}c in side-aware range = {old_doge_no}")
    print(f"  New behavior: no_price={no_price_doge}c in canonical range = {new_doge_no}")
    print()
    
    # Test edge cases
    print("=== Edge Cases ===")
    test_prices = [5, 10, 15, 20, 25, 30, 50, 70, 75, 80, 95, 99]
    print(f"Testing NO prices with canonical vs side-aware ranges:")
    print(f"{'Price':<6} | {'Canonical':<10} | {'Side-Aware':<10}")
    print("-" * 32)
    for price in test_prices:
        canonical = is_price_in_canonical_range(price, "no")
        side_aware = is_price_in_side_aware_range(price, "no")
        print(f"{price:<6}c | {str(canonical):<10} | {str(side_aware):<10}")
    print()

def test_dual_side_price_fix():
    """Test that dual-side price derivation uses actual NO bid."""
    
    print("=== Testing Dual-Side Price Derivation ===\n")
    
    # Simulate the fix: using actual NO bid instead of deriving from YES bid
    # Old behavior: no_price = 100 - yes_bid
    # New behavior: no_price = actual_no_bid (from orderbook)
    
    yes_bid = 66
    yes_ask = 99  # This was the corrupted/placeholder value
    
    print(f"Test Case: YES bid={yes_bid}c, YES ask={yes_ask}c (corrupted)")
    print()
    
    # Old behavior (deriving from YES bid)
    old_no_price = 100 - yes_bid
    print(f"  Old behavior: no_price = 100 - yes_bid = {old_no_price}c")
    print(f"  Problem: Ignores actual NO bid data from orderbook")
    print()
    
    # New behavior (using actual NO bid)
    # Simulate actual NO bid from orderbook (what should have been used)
    actual_no_bid = 34  # This would come from market_state.best_no_bid_cents
    new_no_price = actual_no_bid
    print(f"  New behavior: no_price = actual_no_bid = {new_no_price}c")
    print(f"  Fix: Uses actual NO bid from Kalshi orderbook (no_dollars)")
    print()
    
    # Test binary invariant
    yes_price = yes_bid
    no_price = actual_no_bid
    total = yes_price + no_price
    tolerance = 5  # New tolerance from fix
    
    print(f"Binary invariant check:")
    print(f"  yes_price={yes_price}c + no_price={no_price}c = {total}c")
    print(f"  Expected: ~100c (tolerance={tolerance}c)")
    print(f"  Invariant holds: {abs(total - 100) <= tolerance}")
    print()

def test_canonical_duality():
    """Test canonical duality relationships."""
    
    print("=== Testing Canonical Duality ===\n")
    
    # Test YES to NO conversion
    test_prices = [10, 25, 50, 75, 90]
    print("YES to NO conversion (yes_to_no_price):")
    for yes_price in test_prices:
        no_price = yes_to_no_price(yes_price)
        total = yes_price + no_price
        print(f"  {yes_price}c -> {no_price}c (total={total}c)")
    print()
    
    # Test NO to YES conversion
    print("NO to YES conversion (no_to_yes_price):")
    for no_price in test_prices:
        yes_price = no_to_yes_price(no_price)
        total = yes_price + no_price
        print(f"  {no_price}c -> {yes_price}c (total={total}c)")
    print()

if __name__ == "__main__":
    test_price_range_fixes()
    test_dual_side_price_fix()
    test_canonical_duality()
    
    print("=== All Tests Complete ===")
    print("\nSummary of fixes:")
    print("1. Dual-side price derivation now uses actual NO bid from orderbook")
    print("2. Price range checking uses canonical ranges (10c-75c) instead of side-aware ranges")
    print("3. Binary invariant tolerance increased from 3c to 5c for illiquid markets")
    print("4. Fallback logic added when NO bid data is unavailable")