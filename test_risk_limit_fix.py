#!/usr/bin/env python3
"""Test script to verify 3% per-trade risk limit enforcement in order router.

This test verifies that the fix for the SOL trade exceeding 3% limit works correctly.
With $33.72 bankroll, 3% = $1.01 max per trade. The system previously allowed $1.95 (5.8%).
"""

import sys
from decimal import Decimal

def test_risk_based_sizing():
    """Test that _apply_risk_based_order_sizing enforces 3% limit."""
    print("=" * 70)
    print("TEST: 3% Per-Trade Risk Limit Enforcement")
    print("=" * 70)
    
    # Simulate the incident scenario
    bankroll_usd = Decimal("33.72")
    price_cents = 32  # NO SOL at 32 cents
    requested_count = 6  # 6 contracts as reported
    
    print(f"\nScenario:")
    print(f"  Bankroll: ${bankroll_usd}")
    print(f"  3% Limit: ${bankroll_usd * Decimal('0.03'):.2f}")
    print(f"  Requested: {requested_count} contracts @ {price_cents}c = ${requested_count * price_cents / 100:.2f}")
    print(f"  Violation: ${requested_count * price_cents / 100:.2f} / ${bankroll_usd} = {(requested_count * price_cents / 100) / float(bankroll_usd) * 100:.1f}%")
    
    # Import the function
    try:
        from merid.event_venues.kalshi.order_router import _apply_risk_based_order_sizing
        from merid.event_venues.kalshi.order_router import OrderIntent
    except ImportError as e:
        print(f"\n[ERROR] Failed to import: {e}")
        return False
    
    # Create a mock OrderIntent
    intent = OrderIntent(
        ticker="KXSOL15M-26JUL051900-00",
        side="no",
        action="buy",
        price_cents=price_cents,
        count=requested_count,
        intent_id="test-intent-001",
    )
    
    # Apply risk-based sizing with explicit bankroll (since service not initialized in test)
    try:
        capped_count = _apply_risk_based_order_sizing(intent, bankroll_usd=bankroll_usd)
    except Exception as e:
        print(f"\n[ERROR] _apply_risk_based_order_sizing failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Calculate expected max contracts at 3% limit
    max_notional = bankroll_usd * Decimal("0.03")
    max_contracts = int(max_notional / (price_cents / Decimal("100")))
    
    print(f"\nResult:")
    print(f"  Capped count: {capped_count} contracts")
    print(f"  Expected max: {max_contracts} contracts (at 3% limit)")
    print(f"  Capped notional: ${capped_count * price_cents / 100:.2f}")
    
    # Verify the fix
    if capped_count == 0:
        print(f"\n[SUCCESS] Order REJECTED (count=0) - correctly blocked exceeding 3% limit")
        return True
    elif capped_count <= max_contracts:
        print(f"\n[SUCCESS] Order CAPPED to {capped_count} contracts - within 3% limit")
        return True
    else:
        print(f"\n[FAILURE] Order NOT capped - {capped_count} > {max_contracts} (exceeds 3% limit)")
        return False


def test_unified_sizing_direct():
    """Test unified_sizing.compute_order_size directly."""
    print("\n" + "=" * 70)
    print("TEST: Unified Sizing Direct Call")
    print("=" * 70)
    
    try:
        from merid.prediction.unified_sizing import compute_order_size
    except ImportError as e:
        print(f"\n[ERROR] Failed to import unified_sizing: {e}")
        return False
    
    bankroll_usd = Decimal("33.72")
    price_cents = 32
    asset = "SOL"
    
    print(f"\nCalling compute_order_size:")
    print(f"  bankroll_usd: ${bankroll_usd}")
    print(f"  price_cents: {price_cents}")
    print(f"  asset: {asset}")
    
    try:
        count, notional_usd, metadata = compute_order_size(
            bankroll_usd=bankroll_usd,
            price_cents=price_cents,
            asset=asset,
        )
    except Exception as e:
        print(f"\n[ERROR] compute_order_size failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print(f"\nResult:")
    print(f"  count: {count} contracts")
    print(f"  notional_usd: ${float(notional_usd):.2f}")
    print(f"  metadata: {metadata}")
    
    max_notional = bankroll_usd * Decimal("0.03")
    print(f"\n3% Limit: ${max_notional:.2f}")
    
    if count == 0:
        print(f"\n[SUCCESS] unified_sizing returned 0 - correctly enforces 3% limit")
        return True
    elif float(notional_usd) <= float(max_notional):
        print(f"\n[SUCCESS] notional ${float(notional_usd):.2f} <= 3% limit ${float(max_notional):.2f}")
        return True
    else:
        print(f"\n[FAILURE] notional ${float(notional_usd):.2f} > 3% limit ${float(max_notional):.2f}")
        return False


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("RISK LIMIT FIX VERIFICATION")
    print("=" * 70)
    
    # Test 1: Risk-based sizing in order router
    test1_passed = test_risk_based_sizing()
    
    # Test 2: Unified sizing direct call
    test2_passed = test_unified_sizing_direct()
    
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Test 1 (Order Router): {'PASSED' if test1_passed else 'FAILED'}")
    print(f"Test 2 (Unified Sizing): {'PASSED' if test2_passed else 'FAILED'}")
    
    if test1_passed and test2_passed:
        print("\n[ALL TESTS PASSED] Fix verified successfully")
        sys.exit(0)
    else:
        print("\n[SOME TESTS FAILED] Fix needs review")
        sys.exit(1)
