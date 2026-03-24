#!/usr/bin/env python3
"""Standalone test script for maker/taker fee calculations.

Run without pytest dependencies to verify fee calculation logic.
"""

import sys
import math
sys.path.insert(0, '/home/runner/work/MERID/MERID')

from merid.event_venues.kalshi.maker_taker_policy import (
    kalshi_parabolic_taker_fee_cents,
    kalshi_maker_fee_cents,
    classify_order_role,
    OrderRole,
    PolicyMode,
    MakerTakerPolicyEngine,
)


def test_parabolic_fee():
    """Test parabolic taker fee at various price points."""
    print("\n=== Testing Parabolic Taker Fee ===")

    # Test at midpoint (50¢): should peak at ~1.75¢/contract
    fee = kalshi_parabolic_taker_fee_cents(50, 10)
    print(f"✓ Fee at 50¢ for 10 contracts: {fee}¢ (expected ~20¢)")
    assert fee == 20, f"Expected 20¢, got {fee}¢"

    # Test at extremes (10¢, 90¢): should be minimal
    fee_10 = kalshi_parabolic_taker_fee_cents(10, 10)
    fee_90 = kalshi_parabolic_taker_fee_cents(90, 10)
    print(f"✓ Fee at 10¢ for 10 contracts: {fee_10}¢ (expected ~10¢)")
    print(f"✓ Fee at 90¢ for 10 contracts: {fee_90}¢ (expected ~10¢)")
    assert fee_10 <= 15, f"Fee at extremes should be minimal, got {fee_10}¢"
    assert fee_90 <= 15, f"Fee at extremes should be minimal, got {fee_90}¢"

    # Test symmetry: 25¢ and 75¢ should have same fee
    fee_25 = kalshi_parabolic_taker_fee_cents(25, 10)
    fee_75 = kalshi_parabolic_taker_fee_cents(75, 10)
    print(f"✓ Fee at 25¢ for 10 contracts: {fee_25}¢")
    print(f"✓ Fee at 75¢ for 10 contracts: {fee_75}¢ (should match 25¢)")
    assert fee_25 == fee_75, f"Parabolic fee should be symmetric, but {fee_25}¢ != {fee_75}¢"

    print("✓ All parabolic fee tests passed!\n")


def test_maker_fee():
    """Test maker fee (should always be zero)."""
    print("=== Testing Maker Fee ===")

    fees = [
        kalshi_maker_fee_cents(1, 10),
        kalshi_maker_fee_cents(50, 10),
        kalshi_maker_fee_cents(99, 10),
        kalshi_maker_fee_cents(25, 100),
    ]

    for fee in fees:
        assert fee == 0, f"Maker fee should be 0, got {fee}¢"

    print("✓ All maker fees are zero as expected!\n")


def test_order_classification():
    """Test order role classification."""
    print("=== Testing Order Classification ===")

    # Market order is always taker
    role = classify_order_role(
        order_type="market",
        limit_price_cents=None,
        best_bid_cents=54,
        best_ask_cents=56,
        side="yes",
        action="buy",
    )
    print(f"✓ Market order classified as: {role} (expected TAKER)")
    assert role == OrderRole.TAKER

    # Buy limit crossing ask is taker
    role = classify_order_role(
        order_type="limit",
        limit_price_cents=56,  # At ask, crosses book
        best_bid_cents=54,
        best_ask_cents=56,
        side="yes",
        action="buy",
    )
    print(f"✓ Buy limit at ask classified as: {role} (expected TAKER)")
    assert role == OrderRole.TAKER

    # Buy limit below ask is maker
    role = classify_order_role(
        order_type="limit",
        limit_price_cents=55,  # Below ask, rests
        best_bid_cents=54,
        best_ask_cents=56,
        side="yes",
        action="buy",
    )
    print(f"✓ Buy limit below ask classified as: {role} (expected MAKER)")
    assert role == OrderRole.MAKER

    print("✓ All order classification tests passed!\n")


def test_policy_engine_neutral_mm():
    """Test policy engine in neutral_mm mode."""
    print("=== Testing Policy Engine: Neutral MM ===")

    engine = MakerTakerPolicyEngine(neutral_mm_min_edge_pct=1.0)

    # Should approve maker with sufficient edge
    decision = engine.evaluate(
        policy_mode=PolicyMode.NEUTRAL_MM,
        fair_value_cents=58,
        mid_price_cents=55,
        best_bid_cents=54,
        best_ask_cents=56,
        side="yes",
        action="buy",
        contracts=10,
        raw_edge_pct=5.0,
    )
    print(f"✓ Decision: allowed={decision.allowed}, role={decision.recommended_role}, post_only={decision.post_only}")
    assert decision.allowed is True
    assert decision.recommended_role == OrderRole.MAKER
    assert decision.post_only is True

    # Should reject with insufficient edge
    decision = engine.evaluate(
        policy_mode=PolicyMode.NEUTRAL_MM,
        fair_value_cents=56,
        mid_price_cents=55,
        best_bid_cents=54,
        best_ask_cents=56,
        side="yes",
        action="buy",
        contracts=10,
        raw_edge_pct=0.5,
    )
    print(f"✓ Decision with low edge: allowed={decision.allowed} (expected False)")
    assert decision.allowed is False

    print("✓ Neutral MM policy tests passed!\n")


def test_policy_engine_aggressive():
    """Test policy engine in aggressive_conviction mode."""
    print("=== Testing Policy Engine: Aggressive Conviction ===")

    engine = MakerTakerPolicyEngine(aggressive_min_edge_multiple=3.0)

    # High edge should allow taker
    decision = engine.evaluate(
        policy_mode=PolicyMode.AGGRESSIVE_CONVICTION,
        fair_value_cents=75,  # Huge edge
        mid_price_cents=55,
        best_bid_cents=54,
        best_ask_cents=56,
        side="yes",
        action="buy",
        contracts=10,
        raw_edge_pct=36.0,
    )
    print(f"✓ High edge decision: allowed={decision.allowed}, role={decision.recommended_role}")
    assert decision.allowed is True
    assert decision.recommended_role == OrderRole.TAKER

    # Moderate edge should fall back to maker
    decision = engine.evaluate(
        policy_mode=PolicyMode.AGGRESSIVE_CONVICTION,
        fair_value_cents=58,  # Moderate edge
        mid_price_cents=55,
        best_bid_cents=54,
        best_ask_cents=56,
        side="yes",
        action="buy",
        contracts=10,
        raw_edge_pct=5.0,
    )
    print(f"✓ Moderate edge decision: allowed={decision.allowed}, role={decision.recommended_role}")
    assert decision.allowed is True
    assert decision.recommended_role == OrderRole.MAKER
    assert decision.post_only is True

    print("✓ Aggressive conviction policy tests passed!\n")


def test_fee_comparison():
    """Compare fees at different price points."""
    print("=== Fee Comparison at Various Prices ===")

    prices = [10, 25, 50, 75, 90]
    contracts = 10

    print(f"{'Price':<8} {'Taker Fee':<12} {'Fee/Contract':<15}")
    print("-" * 40)

    for price in prices:
        taker_fee = kalshi_parabolic_taker_fee_cents(price, contracts)
        fee_per = taker_fee / contracts
        print(f"{price}¢{'':<5} {taker_fee}¢{'':<9} {fee_per:.2f}¢")

    print("\n✓ Fee comparison complete!\n")


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("  MERID Maker/Taker Policy Engine - Standalone Tests")
    print("="*60)

    try:
        test_parabolic_fee()
        test_maker_fee()
        test_order_classification()
        test_policy_engine_neutral_mm()
        test_policy_engine_aggressive()
        test_fee_comparison()

        print("="*60)
        print("  ✅ ALL TESTS PASSED!")
        print("="*60)
        print()
        return 0

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
