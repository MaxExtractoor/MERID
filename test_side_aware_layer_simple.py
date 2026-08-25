"""Simple test script for side-aware trading layer (no pytest required)."""

import sys
sys.path.insert(0, 'C:/Dev/MERID')

from merid.event_venues.kalshi.side_aware_trading_layer import (
    BinaryProbability,
    SideAwareOrderIntent,
    SideAwarePriceValidator,
    SideAwareEdgeCalculator,
    InvariantChecker,
    create_side_aware_intent,
    validate_order_intent,
)

def test_binary_probability():
    """Test unified probability model."""
    print("Testing BinaryProbability...")
    
    # Valid probability model
    prob = BinaryProbability(yes_cents=65.0, no_cents=35.0)
    assert prob.yes_cents == 65.0
    assert prob.no_cents == 35.0
    print("✓ Valid probability model")
    
    # Duality invariant enforcement
    try:
        BinaryProbability(yes_cents=70.0, no_cents=35.0)
        print("✗ Duality invariant not enforced")
        return False
    except ValueError as e:
        print("✓ Duality invariant enforced:", str(e))
    
    # Factory methods
    prob_from_yes = BinaryProbability.from_yes(65.0)
    assert prob_from_yes.no_cents == 35.0
    print("✓ from_yes factory works")
    
    prob_from_no = BinaryProbability.from_no(35.0)
    assert prob_from_no.yes_cents == 65.0
    print("✓ from_no factory works")
    
    return True

def test_side_aware_intent():
    """Test side-aware order intent."""
    print("\nTesting SideAwareOrderIntent...")
    
    # BUY_YES intent
    intent = SideAwareOrderIntent.from_components(
        ticker="KXBTC15M-TEST",
        side="yes",
        action="buy",
        price_cents=50,
        count=1,
        yes_probability=65.0,
    )
    assert intent.order_type.value == "BUY_YES"
    assert intent.is_entry_order is True
    print("✓ BUY_YES intent created")
    
    # BUY_NO intent
    intent = SideAwareOrderIntent.from_components(
        ticker="KXBTC15M-TEST",
        side="no",
        action="buy",
        price_cents=40,
        count=1,
        no_probability=35.0,
    )
    assert intent.order_type.value == "BUY_NO"
    assert intent.is_entry_order is True
    print("✓ BUY_NO intent created")
    
    # SELL_YES intent
    intent = SideAwareOrderIntent.from_components(
        ticker="KXBTC15M-TEST",
        side="yes",
        action="sell",
        price_cents=60,
        count=1,
        yes_probability=45.0,
    )
    assert intent.order_type.value == "SELL_YES"
    assert intent.is_exit_order is True
    print("✓ SELL_YES intent created")
    
    # SELL_NO intent
    intent = SideAwareOrderIntent.from_components(
        ticker="KXBTC15M-TEST",
        side="no",
        action="sell",
        price_cents=40,
        count=1,
        no_probability=55.0,
    )
    assert intent.order_type.value == "SELL_NO"
    assert intent.is_exit_order is True
    print("✓ SELL_NO intent created")
    
    # Mandatory probability requirement
    try:
        SideAwareOrderIntent.from_components(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            yes_probability=None,
            no_probability=None,
        )
        print("✗ Mandatory probability not enforced")
        return False
    except ValueError as e:
        print("✓ Mandatory probability enforced:", str(e))
    
    return True

def test_price_validator():
    """Test side-aware price validation."""
    print("\nTesting SideAwarePriceValidator...")
    
    # YES order validation
    is_valid, reason = SideAwarePriceValidator.validate_order_price(
        order_price_cents=50,
        side="yes",
        yes_mid_cents=55,
        yes_bid_cents=53,
        yes_ask_cents=57,
    )
    assert is_valid is True
    print("✓ YES order validation passed")
    
    # NO order validation (with price space conversion)
    is_valid, reason = SideAwarePriceValidator.validate_order_price(
        order_price_cents=45,
        side="no",
        yes_mid_cents=55,  # YES mid = 55c, so NO mid = 45c
        yes_bid_cents=53,
        yes_ask_cents=57,
    )
    assert is_valid is True
    print("✓ NO order validation passed")
    
    # Price too far from mid
    is_valid, reason = SideAwarePriceValidator.validate_order_price(
        order_price_cents=110,
        side="yes",
        yes_mid_cents=55,
        max_deviation_cents=50,
    )
    assert is_valid is False
    assert "price_too_far_from_mid" in reason
    print("✓ Price too far from mid rejected")
    
    # Buy above ask
    is_valid, reason = SideAwarePriceValidator.validate_order_price(
        order_price_cents=60,
        side="yes",
        yes_mid_cents=55,
        yes_bid_cents=53,
        yes_ask_cents=57,
    )
    assert is_valid is False
    assert "buy_above_ask" in reason
    print("✓ Buy above ask rejected")
    
    # Price space conversion
    no_price = SideAwarePriceValidator.convert_price_to_side_space(
        price_cents=65,
        from_side="yes",
        to_side="no",
    )
    assert no_price == 35  # 100 - 65
    print("✓ Price space conversion works")
    
    return True

def test_edge_calculator():
    """Test side-aware edge calculation."""
    print("\nTesting SideAwareEdgeCalculator...")
    
    # BUY_YES edge
    intent = SideAwareOrderIntent.from_components(
        ticker="KXBTC15M-TEST",
        side="yes",
        action="buy",
        price_cents=50,
        count=1,
        yes_probability=65.0,
    )
    
    edge, description = SideAwareEdgeCalculator.calculate_edge(
        order_type=intent.order_type,
        order_price_cents=intent.price_cents,
        probability=intent.probability,
        yes_bid_cents=55,
        no_bid_cents=45,
    )
    
    # Edge = model_prob - market_bid = 65 - 55 = 10c
    assert edge == 10.0
    assert "BUY_yes" in description
    print("✓ BUY_YES edge calculation:", description)
    
    # BUY_NO edge (using NO probability directly)
    intent = SideAwareOrderIntent.from_components(
        ticker="KXBTC15M-TEST",
        side="no",
        action="buy",
        price_cents=40,
        count=1,
        no_probability=25.0,
    )
    
    edge, description = SideAwareEdgeCalculator.calculate_edge(
        order_type=intent.order_type,
        order_price_cents=intent.price_cents,
        probability=intent.probability,
        yes_bid_cents=70,
        no_bid_cents=30,
    )
    
    # Edge = model_prob - market_bid = 25 - 30 = -5c
    assert edge == -5.0
    assert "BUY_no" in description
    print("✓ BUY_NO edge calculation:", description)
    
    return True

def test_invariant_checker():
    """Test invariant checking."""
    print("\nTesting InvariantChecker...")
    
    # Entry from zero
    is_valid, reason = InvariantChecker.check_entry_exit_invariant(
        order_type="BUY_YES",
        pre_position_size=0,
        count=1,
    )
    assert is_valid is True
    print("✓ Entry from zero passed")
    
    # Entry from non-zero
    is_valid, reason = InvariantChecker.check_entry_exit_invariant(
        order_type="BUY_YES",
        pre_position_size=5,
        count=1,
    )
    assert is_valid is False
    assert "entry_from_nonzero" in reason
    print("✓ Entry from non-zero rejected")
    
    # Exit from zero (prevents side inversion)
    is_valid, reason = InvariantChecker.check_entry_exit_invariant(
        order_type="SELL_NO",
        pre_position_size=0,
        count=1,
    )
    assert is_valid is False
    assert "exit_from_zero" in reason
    print("✓ Exit from zero rejected (side inversion prevention)")
    
    # Exit overclose
    is_valid, reason = InvariantChecker.check_entry_exit_invariant(
        order_type="SELL_YES",
        pre_position_size=3,
        count=5,
    )
    assert is_valid is False
    assert "exit_overclose" in reason
    print("✓ Exit overclose rejected")
    
    # Duality invariant
    is_valid, reason = InvariantChecker.check_duality_invariant(
        yes_price=65,
        no_price=35,
    )
    assert is_valid is True
    print("✓ Duality invariant passed")
    
    is_valid, reason = InvariantChecker.check_duality_invariant(
        yes_price=70,
        no_price=35,
    )
    assert is_valid is False
    assert "duality_violation" in reason
    print("✓ Duality violation detected")
    
    return True

def test_factory_functions():
    """Test factory functions."""
    print("\nTesting factory functions...")
    
    # create_side_aware_intent
    intent = create_side_aware_intent(
        ticker="KXBTC15M-TEST",
        side="yes",
        action="buy",
        price_cents=50,
        count=1,
        yes_probability=65.0,
    )
    assert isinstance(intent, SideAwareOrderIntent)
    print("✓ create_side_aware_intent works")
    
    # validate_order_intent
    is_valid, reason = validate_order_intent(intent)
    assert is_valid is True
    print("✓ validate_order_intent passed")
    
    # Invalid intent (price outside range)
    intent = create_side_aware_intent(
        ticker="KXBTC15M-TEST",
        side="yes",
        action="buy",
        price_cents=5,  # Below canonical minimum
        count=1,
        yes_probability=65.0,
    )
    is_valid, reason = validate_order_intent(intent)
    assert is_valid is False
    assert "price_outside_canonical_range" in reason
    print("✓ Invalid intent rejected")
    
    return True

def main():
    """Run all tests."""
    print("=" * 60)
    print("SIDE-AWARE TRADING LAYER TESTS")
    print("=" * 60)
    
    tests = [
        test_binary_probability,
        test_side_aware_intent,
        test_price_validator,
        test_edge_calculator,
        test_invariant_checker,
        test_factory_functions,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"✗ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
