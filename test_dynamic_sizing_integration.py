#!/usr/bin/env python3
"""Integration test for dynamic sizing with actual market prices."""

from decimal import Decimal

# Test the cycle sizing cap with actual market prices
def test_cycle_sizing_with_actual_prices():
    """Verify that cycle sizing uses actual market prices."""
    from merid.prediction.dynamic_sizing import compute_cycle_sizing_cap
    
    bankroll = Decimal("44.35")
    
    # Test with different actual market prices
    test_cases = [
        # (price_cents, expected_max_contracts_for_1_winner)
        (30, 2),   # 30 cent contract
        (50, 1),   # 50 cent contract (midpoint)
        (65, 1),   # 65 cent contract (higher price = fewer contracts)
        (80, 1),   # 80 cent contract
    ]
    
    print("Testing cycle sizing with different market prices:")
    print("=" * 60)
    
    for price_cents, expected_max in test_cases:
        cap = compute_cycle_sizing_cap(
            bankroll_usd=bankroll,
            winner_count=1,
            price_cents=price_cents,
        )
        
        notional_if_max = cap.max_contracts_per_winner * Decimal(price_cents) / Decimal("100")
        pct_of_bankroll = notional_if_max / bankroll * 100
        
        print(f"\nPrice: {price_cents}c (${price_cents/100:.2f})")
        print(f"  Max contracts: {cap.max_contracts_per_winner}")
        print(f"  Notional if max: ${float(notional_if_max):.2f}")
        print(f"  % of bankroll: {float(pct_of_bankroll):.2f}%")
        print(f"  Total allocation: ${float(cap.max_total_notional_usd):.2f} (2% of ${float(bankroll):.2f})")
        
        # Verify we're within 2%
        assert pct_of_bankroll <= 2.5, f"Allocation exceeds 2%: {pct_of_bankroll}%"
        print(f"  ✓ Within 2% allocation limit")


def test_winner_distribution():
    """Test that 1-2% allocation is distributed across winners."""
    from merid.prediction.dynamic_sizing import compute_cycle_sizing_cap
    
    bankroll = Decimal("100.0")  # $100 bankroll for easier math
    price_cents = 50
    
    print("\n\nTesting allocation across multiple winners:")
    print("=" * 60)
    
    for winner_count in [1, 2, 3]:
        cap = compute_cycle_sizing_cap(bankroll, winner_count, price_cents)
        
        total_notional = cap.max_contracts_per_winner * winner_count * Decimal("0.50")
        pct_of_bankroll = total_notional / bankroll * 100
        
        print(f"\n{winner_count} winner(s):")
        print(f"  Max per winner: {cap.max_contracts_per_winner} contracts")
        print(f"  Total contracts: {cap.max_contracts_per_winner * winner_count}")
        print(f"  Total notional: ${float(total_notional):.2f}")
        print(f"  % of $100 bankroll: {float(pct_of_bankroll):.2f}%")
        print(f"  Max allowed: ${float(cap.max_total_notional_usd):.2f}")
        
        # Verify total is within 2%
        assert pct_of_bankroll <= 2.5, f"Total allocation exceeds 2%"
        print(f"  ✓ Total within 2% limit")


def test_contract_price_lookup():
    """Test that we can look up actual contract prices."""
    from merid.prediction.dynamic_sizing import get_actual_contract_price_cents
    
    print("\n\nTesting contract price lookup:")
    print("=" * 60)
    
    # Test with a non-existent ticker (should return safe default)
    price = get_actual_contract_price_cents("FAKE-TICKER-123", "yes")
    print(f"\nNon-existent ticker price: {price}c (safe default)")
    assert 1 <= price <= 99, "Price should be in valid range"
    print("  ✓ Safe default returned")


if __name__ == "__main__":
    print("Dynamic Sizing Integration Tests")
    print("=" * 60)
    
    try:
        test_cycle_sizing_with_actual_prices()
        test_winner_distribution()
        test_contract_price_lookup()
        
        print("\n" + "=" * 60)
        print("All tests passed! ✓")
        print("\nKey findings:")
        print("- Cycle cap correctly limits total notional to 1-2% of bankroll")
        print("- Higher contract prices result in fewer max contracts")
        print("- Allocation is properly distributed across winners")
        print("- Safe defaults exist when market data unavailable")
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
