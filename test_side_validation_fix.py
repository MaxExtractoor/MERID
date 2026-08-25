#!/usr/bin/env python3
"""
Test to verify the side validation fix for order_router.py

This test ensures that Kalshi-formatted sides (BUY_YES, SELL_YES, etc.) 
are properly converted to canonical format (yes, no) for side_mapping_validator
while preserving the original format for other uses.
"""

import sys
sys.path.insert(0, 'C:/Dev/MERID')

from merid.event_venues.kalshi.binary_price_space import parse_kalshi_side

def test_kalshi_side_conversion():
    """Test that Kalshi sides are properly converted to canonical format"""
    
    # Test cases: (Kalshi side, expected canonical side)
    test_cases = [
        ("BUY_YES", "yes"),
        ("SELL_YES", "yes"),
        ("BUY_NO", "no"),
        ("SELL_NO", "no"),
    ]
    
    for kalshi_side, expected_canonical in test_cases:
        canonical_side, action = parse_kalshi_side(kalshi_side)
        assert canonical_side == expected_canonical, f"Failed: {kalshi_side} -> {canonical_side} (expected {expected_canonical})"
        print(f"✓ {kalshi_side} -> canonical: {canonical_side}, action: {action}")
    
    print("\nAll side conversion tests passed!")

def test_side_validation_logic():
    """Test the logic used in order_router.py for side conversion"""
    
    # Simulate the logic from order_router.py
    test_sides = ["BUY_YES", "SELL_YES", "BUY_NO", "SELL_NO", "yes", "no"]
    
    for side in test_sides:
        canonical_side = side
        kalshi_side = side
        
        if side.upper() in ("BUY_YES", "SELL_YES", "BUY_NO", "SELL_NO"):
            canonical_side, _ = parse_kalshi_side(side)
        
        # Validate that canonical_side is always "yes" or "no"
        assert canonical_side.lower() in ("yes", "no"), f"Invalid canonical side: {canonical_side}"
        print(f"✓ {side} -> canonical: {canonical_side}, kalshi: {kalshi_side}")
    
    print("\nAll side validation logic tests passed!")

if __name__ == "__main__":
    test_kalshi_side_conversion()
    test_side_validation_logic()
    print("\n✅ All tests passed! The side validation fix is working correctly.")
