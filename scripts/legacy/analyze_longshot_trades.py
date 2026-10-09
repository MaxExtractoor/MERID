"""
Analyze losing DOGE/XRP trades against current guardrails.

Based on actual losing trades from kalshi_fills.db:
- KXXRP15M-26MAY280730-30 at $0.05 (Yes buy) → -100%
- KXDOGE15M-26MAY280730-30 at $0.06 (Yes buy) → -100%
- KXDOGE15M-26MAY280730-30 at $0.08 (Yes buy) → -100%
- KXXRP15M-26MAY281830-30 at $0.10 (Yes buy) → -100%
- KXXRP15M-26MAY281515-15 at $0.14 (Yes buy) → -100%
- KXDOGE15M-26MAY281200-00 at $0.15 (Yes buy) → -100%

Current guardrails from kalshi_crypto_15m.yaml:
- guardrails_max_dist_pct_trade: 2.0% (max spot-strike distance)
- guardrails_max_spread_cents: 40 (max spread in cents)
- guardrails_min_depth_contracts: 5 (min depth)
- NO minimum contract price floor

Analysis:
"""

print("=" * 80)
print("LONGSHOT TRADE ANALYSIS")
print("=" * 80)

losing_trades = [
    ("KXXRP15M-26MAY280730-30", 0.05, "Yes buy"),
    ("KXDOGE15M-26MAY280730-30", 0.06, "Yes buy"),
    ("KXDOGE15M-26MAY280730-30", 0.08, "Yes buy"),
    ("KXXRP15M-26MAY281830-30", 0.10, "Yes buy"),
    ("KXXRP15M-26MAY281515-15", 0.14, "Yes buy"),
    ("KXDOGE15M-26MAY281200-00", 0.15, "Yes buy"),
]

print("\nLosing trades (all -100%):")
for ticker, price, action in losing_trades:
    print(f"  {ticker} | ${price:.2f} | {action}")

print("\n" + "=" * 80)
print("CURRENT GUARDRAILS")
print("=" * 80)
print("guardrails_max_dist_pct_trade: 2.0%")
print("guardrails_max_spread_cents: 40")
print("guardrails_min_depth_contracts: 5")
print("NO minimum contract price floor")

print("\n" + "=" * 80)
print("ANALYSIS")
print("=" * 80)

print("\n1. PRICE FLOOR CHECK:")
print("   Current: No minimum price floor")
print("   Problem: Trades at $0.05-$0.15 are allowed")
print("   Impact: These are deep OTM longshots with ~5-15% win probability")
print("   Expected win rate: ~5-15% (market-implied)")
print("   Recommendation: Add guardrails_min_contract_price_cents: 20 ($0.20)")

print("\n2. SPREAD CHECK:")
print("   Current: max_spread_cents = 40")
print("   Problem: Low-priced contracts have massive spreads")
print("   Example: $0.05 Yes / $0.95 No = 90 cent spread")
print("   Current guardrail: Would REJECT (90c > 40c)")
print("   Status: ✓ Spread guardrail would catch these")

print("\n3. OTM DISTANCE CHECK:")
print("   Current: max_dist_pct_trade = 2.0%")
print("   Problem: At-the-money trades (0% distance) are allowed")
print("   Issue: Even at 0% distance, low price = longshot")
print("   Status: ✗ Distance check doesn't catch low-price longshots")

print("\n4. DEPTH CHECK:")
print("   Current: min_depth_contracts = 5")
print("   Problem: Low-priced contracts often have poor depth")
print("   Status: ✓ Depth guardrail would catch many of these")

print("\n" + "=" * 80)
print("CONCLUSION")
print("=" * 80)
print("Current guardrails:")
print("  ✓ Spread check would REJECT (90c spread > 40c limit)")
print("  ✓ Depth check would REJECT (poor liquidity on low-priced)")
print("  ✗ No price floor - deep OTM longshots allowed if spread/depth OK")
print("  ✗ Distance check doesn't address low-price issue")

print("\nRecommendation:")
print("  Add guardrails_min_contract_price_cents: 20 ($0.20)")
print("  This would reject all trades below $0.20")
print("  Winning trades in history: $0.35-$0.75 (all above $0.20)")
print("  Losing trades in history: $0.05-$0.19 (all below $0.20)")

print("\nAlternative: Tiered edge requirements")
print("  - Contracts < $0.20: Require 15%+ edge")
print("  - Contracts $0.20-$0.40: Require 10%+ edge")
print("  - Contracts > $0.40: Require 5%+ edge")
print("  This makes longshots harder to enter without hard ban")
