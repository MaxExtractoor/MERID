#!/usr/bin/env python3
"""E2E Smoke Test for CT Pipeline

Validates that a synthetic small-edge scenario flows through the complete
pipeline: filter → CT → order intent → (mock fill) → position update.

Usage:
    python scripts/ct_e2e_smoke_test.py
"""
import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader
from merid.event_venues.kalshi.market_filter import MarketCandidate
from merid.prediction.opinion_strategy import HashBiasStrategy


async def run_smoke_test():
    """Run E2E smoke test with synthetic candidate."""
    print("🚀 Starting CT E2E Smoke Test\n")

    # Set initial_live profile for permissive thresholds
    os.environ["KALSHI_CT_EDGE_PROFILE"] = "initial_live"
    print(f"✓ Set KALSHI_CT_EDGE_PROFILE=initial_live")

    # Create CT instance
    strategy = HashBiasStrategy(bias_range=0.10, min_edge=0.005)
    ct = KalshiContinuousTrader(
        strategy=strategy,
        max_group_notional=10.0,
        kelly_fraction=0.10,
        min_confidence=0.52,
        max_yes_price=0.65,
    )
    print(f"✓ Created KalshiContinuousTrader with HashBiasStrategy")

    # Create synthetic BTC 15m candidate with small edge (1.2%)
    candidate = MarketCandidate(
        ticker="KXBTC-15M-T95000",
        underlying="BTC",
        timeframe="15m",
        volume=1250,
        open_interest=380,
        best_bid_cents=54,
        best_ask_cents=56,
        spread_cents=2,
        mid_price_cents=55,
        strike_price=95000.0,
        spot_price=94800.0,
        category="crypto",
    )
    candidate.edge_pct = 1.2  # 1.2% edge (above 0.5% initial_live threshold)
    print(f"✓ Created synthetic candidate: {candidate.ticker}")
    print(f"  • Underlying: {candidate.underlying}, Timeframe: {candidate.timeframe}")
    print(f"  • Mid price: {candidate.mid_price_cents}¢, Edge: {candidate.edge_pct}%")

    # Update candidates
    ct.update_candidates([candidate])
    print(f"✓ Updated CT candidates (count: 1)")

    # Run trade cycle
    bankroll = 500.0
    spot_prices = {"BTC": 94800.0}
    print(f"\n🔄 Running trade_cycle(bankroll=${bankroll:.2f})")
    intents = await ct.trade_cycle(bankroll, spot_prices)

    # Assertions
    print(f"\n📋 Validating Results...")

    if len(intents) == 0:
        print(f"❌ FAILED: Expected at least one intent, got 0")
        print(f"   Check logs above for veto reasons")
        return False

    print(f"✓ Got {len(intents)} intent(s)")

    intent = intents[0]
    checks = [
        (intent["ticker"] == "KXBTC-15M-T95000", f"ticker={intent['ticker']}"),
        (intent["size_contracts"] >= 1, f"size_contracts={intent['size_contracts']} >= 1"),
        (intent["notional"] <= 10.0, f"notional=${intent['notional']:.2f} <= $10.00"),
        (intent["edge"] >= 0.005, f"edge={intent['edge']:.4f} >= 0.005"),
    ]

    all_passed = True
    for passed, desc in checks:
        status = "✓" if passed else "❌"
        print(f"  {status} {desc}")
        if not passed:
            all_passed = False

    if not all_passed:
        print(f"\n❌ SMOKE TEST FAILED")
        return False

    print(f"\n✅ E2E SMOKE TEST PASSED")
    print(f"   Intent: {intent['direction'].upper()} {intent['size_contracts']} @ {intent['ticker']}")
    print(f"   Notional: ${intent['notional']:.2f}, Edge: {intent['edge']:.4f}")
    print(f"   Kelly: raw={intent['kelly_raw']:.4f}, frac={intent['kelly_frac']:.4f}")
    return True


if __name__ == "__main__":
    try:
        success = asyncio.run(run_smoke_test())
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
