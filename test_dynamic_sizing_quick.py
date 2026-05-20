#!/usr/bin/env python3
"""Quick test for dynamic sizing logic."""

from decimal import Decimal

# Test parameters (from the log)
bankroll_usd = Decimal("44.35")
allocation_pct = Decimal("0.02")  # 2%
price_cents = 50  # ~50 cents per contract

print(f"Bankroll: ${float(bankroll_usd):.2f}")
print(f"Allocation: {float(allocation_pct)*100:.0f}%")
print(f"Price: {price_cents} cents")
print()

for winner_count in [1, 2, 3]:
    max_total = bankroll_usd * allocation_pct
    per_winner = max_total / Decimal(winner_count)
    price_usd = Decimal(price_cents) / Decimal("100")
    max_contracts = int(per_winner / price_usd)
    
    print(f"{winner_count} winner(s):")
    print(f"  Max total notional: ${float(max_total):.2f}")
    print(f"  Per winner: ${float(per_winner):.2f}")
    print(f"  Max contracts per winner: {max_contracts}")
    print(f"  Actual notional if 1 contract each: ${winner_count * float(price_usd):.2f} ({(winner_count * float(price_usd) / float(bankroll_usd) * 100):.2f}% of bankroll)")
    print()

print("KEY INSIGHT: With $44.35 bankroll and 2% allocation = $0.89 total:")
print("- At 50 cents/contract, we can only afford 1 contract TOTAL, not per winner")
print("- The current code tries to trade 50 contracts = $25 notional (56% of bankroll!)")
print("- This is why the risk gate is rejecting the orders")
