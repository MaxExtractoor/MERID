"""Standalone test for side-aware price range filtering (no imports)."""

# Replicate the function logic for testing
def is_price_in_side_aware_range(price_cents: int, side: str) -> bool:
    """Check if price is in side-aware range (accounts for YES/NO duality)."""
    if side == "yes":
        # YES range: 1c-75c (expanded low end for late-expiry)
        YES_MIN_CENTS = 1
        YES_MAX_CENTS = 75
        return YES_MIN_CENTS <= price_cents <= YES_MAX_CENTS
    else:  # side == "no"
        # NO range: 25c-99c (expanded high end for late-expiry)
        NO_MIN_CENTS = 25
        NO_MAX_CENTS = 99
        return NO_MIN_CENTS <= price_cents <= NO_MAX_CENTS


def yes_to_no_price(yes_price_cents: int) -> int:
    """Convert YES price to NO price using duality."""
    return 100 - yes_price_cents


def no_to_yes_price(no_price_cents: int) -> int:
    """Convert NO price to YES price using duality."""
    return 100 - no_price_cents


def test_side_aware_yes_range():
    """Test that YES prices use expanded range (1c-75c)."""
    print("Testing YES range...")
    assert is_price_in_side_aware_range(1, "yes") == True
    assert is_price_in_side_aware_range(6, "yes") == True
    assert is_price_in_side_aware_range(10, "yes") == True
    assert is_price_in_side_aware_range(25, "yes") == True
    assert is_price_in_side_aware_range(50, "yes") == True
    assert is_price_in_side_aware_range(75, "yes") == True
    assert is_price_in_side_aware_range(0, "yes") == False
    assert is_price_in_side_aware_range(76, "yes") == False
    assert is_price_in_side_aware_range(94, "yes") == False
    print("[PASS] YES range tests passed")


def test_side_aware_no_range():
    """Test that NO prices use expanded range (25c-99c)."""
    print("Testing NO range...")
    assert is_price_in_side_aware_range(25, "no") == True
    assert is_price_in_side_aware_range(50, "no") == True
    assert is_price_in_side_aware_range(75, "no") == True
    assert is_price_in_side_aware_range(90, "no") == True
    assert is_price_in_side_aware_range(94, "no") == True  # FIX: Now accepted
    assert is_price_in_side_aware_range(95, "no") == True  # FIX: Now accepted
    assert is_price_in_side_aware_range(97, "no") == True  # FIX: Now accepted
    assert is_price_in_side_aware_range(99, "no") == True  # FIX: Now accepted
    assert is_price_in_side_aware_range(24, "no") == False
    assert is_price_in_side_aware_range(100, "no") == False
    print("[PASS] NO range tests passed")


def test_late_expiry_scenario():
    """Test late-expiry scenario where YES is low and NO is high."""
    print("Testing late-expiry scenario...")
    yes_price = 6
    no_price = 94
    
    assert is_price_in_side_aware_range(yes_price, "yes") == True
    assert is_price_in_side_aware_range(no_price, "no") == True
    assert yes_to_no_price(yes_price) == 94
    assert no_to_yes_price(no_price) == 6
    print("[PASS] Late-expiry scenario tests passed")


def test_all_assets_late_expiry():
    """Test all assets from the logs with late-expiry prices."""
    print("Testing all assets from logs...")
    test_cases = [
        ("BTC", 3, 97),
        ("ETH", 1, 99),
        ("SOL", 1, 99),
        ("XRP", 6, 94),
        ("DOGE", 1, 99),
    ]
    
    for asset, yes_price, no_price in test_cases:
        assert is_price_in_side_aware_range(yes_price, "yes") == True, \
            f"{asset}: YES {yes_price}c should be in range"
        assert is_price_in_side_aware_range(no_price, "no") == True, \
            f"{asset}: NO {no_price}c should be in range (FIX)"
        assert yes_to_no_price(yes_price) == no_price, \
            f"{asset}: Duality violation: {yes_price}c + {no_price}c != 100"
    
    print("[PASS] All assets late-expiry tests passed")


def test_edge_cases():
    """Test edge cases for side-aware range."""
    print("Testing edge cases...")
    # Boundary values for YES
    assert is_price_in_side_aware_range(1, "yes") == True   # Min YES
    assert is_price_in_side_aware_range(75, "yes") == True  # Max YES
    assert is_price_in_side_aware_range(0, "yes") == False   # Just below min
    assert is_price_in_side_aware_range(76, "yes") == False  # Just above max
    
    # Boundary values for NO
    assert is_price_in_side_aware_range(25, "no") == True  # Min NO
    assert is_price_in_side_aware_range(99, "no") == True  # Max NO
    assert is_price_in_side_aware_range(24, "no") == False  # Just below min
    assert is_price_in_side_aware_range(100, "no") == False  # Just above max
    print("[PASS] Edge case tests passed")


if __name__ == "__main__":
    print("=" * 60)
    print("Running side-aware price range tests...")
    print("=" * 60)
    
    test_side_aware_yes_range()
    test_side_aware_no_range()
    test_late_expiry_scenario()
    test_all_assets_late_expiry()
    test_edge_cases()
    
    print("=" * 60)
    print("[SUCCESS] All tests passed!")
    print("=" * 60)
