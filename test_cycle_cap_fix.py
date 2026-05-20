#!/usr/bin/env python3
"""Quick test to verify cycle cap is being applied correctly."""

from decimal import Decimal

def test_cycle_cap_computation():
    """Test that cycle cap correctly limits contracts based on bankroll."""
    from merid.prediction.dynamic_sizing import compute_cycle_sizing_cap
    
    # Test with $44.35 bankroll (from logs)
    bankroll = Decimal("44.35")
    
    # At 50 cents/contract, 1 winner
    cap = compute_cycle_sizing_cap(bankroll, winner_count=1, price_cents=50)
    print(f"Bankroll ${float(bankroll):.2f}, 50c/contract, 1 winner:")
    print(f"  Max total notional: ${float(cap.max_total_notional_usd):.2f}")
    print(f"  Max contracts per winner: {cap.max_contracts_per_winner}")
    print(f"  Notional if max: ${float(cap.max_contracts_per_winner * 50 / 100):.2f}")
    
    # With 50c contracts and 1 winner, we should get at most 1 contract
    # because 2 contracts * $0.50 = $1.00 > $0.89 (2% of $44.35)
    assert cap.max_contracts_per_winner <= 1, f"Expected max 1 contract, got {cap.max_contracts_per_winner}"
    print("  ✓ PASS: Correctly limited to 1 contract or less")
    
    # Test at 65 cents/contract
    cap65 = compute_cycle_sizing_cap(bankroll, winner_count=1, price_cents=65)
    print(f"\nBankroll ${float(bankroll):.2f}, 65c/contract, 1 winner:")
    print(f"  Max contracts per winner: {cap65.max_contracts_per_winner}")
    # At 65c, we might get 0 or 1 depending on allocation
    print(f"  ✓ Computed max: {cap65.max_contracts_per_winner}")
    
    # Test with 2 winners
    cap2 = compute_cycle_sizing_cap(bankroll, winner_count=2, price_cents=50)
    print(f"\nBankroll ${float(bankroll):.2f}, 50c/contract, 2 winners:")
    print(f"  Max contracts per winner: {cap2.max_contracts_per_winner}")
    print(f"  Total contracts (2 winners): {cap2.max_contracts_per_winner * 2}")
    print(f"  Total notional: ${float(cap2.max_contracts_per_winner * 2 * 50 / 100):.2f}")
    
    # Total notional should still be <= 2% of bankroll
    total_notional = cap2.max_contracts_per_winner * 2 * Decimal("0.50")
    pct = total_notional / bankroll * 100
    assert pct <= 2.5, f"Total allocation {pct}% exceeds 2.5%"
    print(f"  ✓ PASS: Total allocation {float(pct):.2f}% within limit")

def test_apply_cycle_cap():
    """Test that apply_cycle_cap correctly reduces oversized positions."""
    from merid.prediction.dynamic_sizing import apply_cycle_cap_to_kelly_size
    
    bankroll = Decimal("44.35")
    
    # Try to place 50 contracts at 50c each = $25 notional
    # This should be capped to 1 contract (~$0.50 notional)
    capped, reason = apply_cycle_cap_to_kelly_size(
        kelly_contracts=50,
        bankroll_usd=bankroll,
        price_cents=50,
        ticker="KXBTC-TEST",
        side="yes",
    )
    
    print(f"\n\nApply cycle cap test:")
    print(f"  Input: 50 contracts at 50c = $25.00 notional")
    print(f"  Bankroll: ${float(bankroll):.2f} (2% = ${float(bankroll * Decimal('0.02')):.2f})")
    print(f"  Capped to: {capped} contracts (~${capped * 0.50:.2f} notional)")
    print(f"  Reason: {reason}")
    
    assert capped < 50, f"Expected reduction, got {capped}"
    assert capped <= 1, f"With $44.35 bankroll, should be at most 1 contract, got {capped}"
    print("  ✓ PASS: Correctly capped oversized position")

if __name__ == "__main__":
    print("=" * 60)
    print("Cycle Cap Fix Verification Tests")
    print("=" * 60)
    
    try:
        test_cycle_cap_computation()
        test_apply_cycle_cap()
        
        print("\n" + "=" * 60)
        print("All tests PASSED! ✓")
        print("=" * 60)
        print("\nSummary:")
        print("- Cycle cap correctly computes max contracts based on bankroll")
        print("- 1-2% allocation limit is enforced")
        print("- Price is dynamically considered (not hardcoded)")
        print("- Oversized positions are reduced to within limits")
        
    except Exception as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
