#!/usr/bin/env python3
"""Test script for spend caps implementation.

This script validates that:
1. SPEND_CAPS are defined for all 25 (asset, timeframe) pairs
2. Spend cap helper functions work correctly
3. The risk engine properly clips sizes to spend caps
4. Global portfolio cap is enforced
5. Per-asset total cap is enforced
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from merid.event_venues.kalshi.crypto_kalshi_risk import (
    CRYPTO_ASSETS,
    TIMEFRAMES,
    SPEND_CAPS,
    PER_ASSET_TOTAL_CAP,
    PORTFOLIO_GLOBAL_CAP,
    get_spend_cap,
    get_spend_cap_midpoint,
    get_per_asset_total_cap,
    get_per_asset_total_cap_midpoint,
    KalshiCryptoRiskEngine,
)


def test_spend_caps_coverage():
    """Test that spend caps are defined for all expected pairs."""
    print("\n=== Testing Spend Caps Coverage ===")

    expected_pairs = [(asset, tf) for asset in CRYPTO_ASSETS for tf in TIMEFRAMES]
    print(f"Expected {len(expected_pairs)} (asset, timeframe) pairs")

    missing = []
    for asset, timeframe in expected_pairs:
        key = (asset, timeframe)
        if key not in SPEND_CAPS:
            missing.append(key)

    if missing:
        print(f"❌ MISSING {len(missing)} spend caps:")
        for key in missing:
            print(f"   {key}")
        return False
    else:
        print(f"✓ All {len(expected_pairs)} spend caps defined")
        return True


def test_spend_cap_helpers():
    """Test spend cap helper functions."""
    print("\n=== Testing Spend Cap Helpers ===")

    # Test get_spend_cap
    btc_15m_cap = get_spend_cap("BTC", "15m")
    print(f"BTC/15m cap: {btc_15m_cap} (expecting (0.05, 0.07))")
    assert btc_15m_cap == (0.05, 0.07), f"Expected (0.05, 0.07), got {btc_15m_cap}"

    # Test get_spend_cap_midpoint
    btc_15m_mid = get_spend_cap_midpoint("BTC", "15m")
    print(f"BTC/15m midpoint: {btc_15m_mid:.3f} (expecting 0.060)")
    assert btc_15m_mid == 0.06, f"Expected 0.06, got {btc_15m_mid}"

    # Test per-asset total cap
    btc_total_cap = get_per_asset_total_cap("BTC")
    print(f"BTC total cap: {btc_total_cap} (expecting (0.20, 0.25))")
    assert btc_total_cap == (0.20, 0.25), f"Expected (0.20, 0.25), got {btc_total_cap}"

    # Test per-asset total cap midpoint
    btc_total_mid = get_per_asset_total_cap_midpoint("BTC")
    print(f"BTC total midpoint: {btc_total_mid:.3f} (expecting 0.225)")
    assert btc_total_mid == 0.225, f"Expected 0.225, got {btc_total_mid}"

    print("✓ All helper functions passed")
    return True


def test_risk_engine_spend_cap_clipping():
    """Test that the risk engine clips sizes to spend caps."""
    print("\n=== Testing Risk Engine Spend Cap Clipping ===")

    engine = KalshiCryptoRiskEngine()
    bankroll = 10000.0  # $10k bankroll
    price = 0.50  # 50¢ per contract

    # BTC/15m has a 5-7% cap (midpoint 6%)
    # Max exposure = $10k * 6% = $600
    # Max contracts = $600 / $0.50 = 1200 contracts

    # Test with a large uncapped size
    contracts = engine.compute_contracts_for_order(
        bankroll=bankroll,
        price=price,
        asset="BTC",
        timeframe="15m",
        max_risk_pct_trade=0.10,  # 10% risk (would be 2000 contracts uncapped)
        cushion_pct_trade=0.0,
    )

    print(f"BTC/15m: Uncapped would be ~2000, capped to {contracts} (expecting ≤1200)")
    assert contracts <= 1200, f"Expected ≤1200 contracts, got {contracts}"
    print(f"✓ Size correctly clipped to spend cap")

    # Test DOGE/daily which has a 1-2% cap (midpoint 1.5%)
    # Max exposure = $10k * 1.5% = $150
    # Max contracts = $150 / $0.50 = 300 contracts
    contracts_doge = engine.compute_contracts_for_order(
        bankroll=bankroll,
        price=price,
        asset="DOGE",
        timeframe="daily",
        max_risk_pct_trade=0.05,  # 5% risk (would be 1000 contracts uncapped)
        cushion_pct_trade=0.0,
    )

    print(f"DOGE/daily: Uncapped would be ~1000, capped to {contracts_doge} (expecting ≤300)")
    assert contracts_doge <= 300, f"Expected ≤300 contracts, got {contracts_doge}"
    print(f"✓ DOGE/daily size correctly clipped")

    return True


def test_global_portfolio_cap():
    """Test that global portfolio cap is enforced."""
    print("\n=== Testing Global Portfolio Cap ===")

    engine = KalshiCryptoRiskEngine()
    bankroll = 10000.0
    price = 0.50

    # Create positions totaling 35% of bankroll
    # Global cap is 40%, so we should be able to add 5% more
    open_positions = {
        "TICKER1": {"asset": "BTC", "contracts": 4000, "entry_price": 0.50},  # $2000
        "TICKER2": {"asset": "ETH", "contracts": 3000, "entry_price": 0.50},  # $1500
        # Total: $3500 = 35% of $10k
    }

    # Try to add an order that would bring us to 45% (should fail)
    # $1000 new exposure = 10% of bankroll
    contracts_to_add = 2000  # 2000 * $0.50 = $1000
    can_add, reason = engine.check_can_add_order(
        total_bankroll=bankroll,
        current_equity=bankroll,
        open_positions=open_positions,
        asset="SOL",
        price=price,
        contracts=contracts_to_add,
    )

    print(f"Attempting to add $1000 (10%) to existing $3500 (35%) exposure")
    print(f"Result: {can_add}, reason: {reason}")
    assert not can_add, f"Expected rejection, but order was allowed"
    assert reason == "global_portfolio_cap", f"Expected 'global_portfolio_cap', got '{reason}'"
    print("✓ Global portfolio cap correctly enforced")

    # Now try a smaller order that fits (3% = $300)
    contracts_to_add = 600  # 600 * $0.50 = $300
    can_add, reason = engine.check_can_add_order(
        total_bankroll=bankroll,
        current_equity=bankroll,
        open_positions=open_positions,
        asset="SOL",
        price=price,
        contracts=contracts_to_add,
    )

    print(f"Attempting to add $300 (3%) to existing $3500 (35%) exposure")
    print(f"Result: {can_add}, reason: {reason}")
    assert can_add, f"Expected approval, but order was rejected: {reason}"
    print("✓ Small order within cap correctly allowed")

    return True


def test_per_asset_total_cap():
    """Test that per-asset total cap is enforced."""
    print("\n=== Testing Per-Asset Total Cap ===")

    engine = KalshiCryptoRiskEngine()
    bankroll = 10000.0
    price = 0.50

    # BTC has a 20-25% total cap (midpoint 22.5%)
    # Create BTC positions totaling 20% across different timeframes
    open_positions = {
        "BTC_15M": {"asset": "BTC", "timeframe": "15m", "contracts": 2000, "entry_price": 0.50},  # $1000
        "BTC_1H": {"asset": "BTC", "timeframe": "1h", "contracts": 2000, "entry_price": 0.50},   # $1000
        # Total BTC: $2000 = 20% of $10k
    }

    # Try to add another BTC position that would exceed 22.5% cap
    # Adding $500 (5%) would bring us to 25%, which exceeds the midpoint
    contracts_to_add = 1000  # 1000 * $0.50 = $500
    can_add, reason = engine.check_can_add_order(
        total_bankroll=bankroll,
        current_equity=bankroll,
        open_positions=open_positions,
        asset="BTC",
        price=price,
        contracts=contracts_to_add,
    )

    print(f"BTC positions: $2000 (20%), attempting to add $500 (5%)")
    print(f"Result: {can_add}, reason: {reason}")
    # This should fail because it exceeds the midpoint cap
    assert not can_add, f"Expected rejection, but order was allowed"
    assert "per_asset_total_cap" in reason, f"Expected 'per_asset_total_cap', got '{reason}'"
    print("✓ Per-asset total cap correctly enforced")

    return True


def print_all_spend_caps():
    """Print all spend caps for reference."""
    print("\n=== All Spend Caps ===")

    for asset in CRYPTO_ASSETS:
        print(f"\n{asset}:")
        for timeframe in TIMEFRAMES:
            min_cap, max_cap = get_spend_cap(asset, timeframe)
            mid = get_spend_cap_midpoint(asset, timeframe)
            print(f"  {timeframe:8s}: {min_cap*100:.1f}%-{max_cap*100:.1f}% (mid: {mid*100:.1f}%)")

        # Print per-asset total cap
        min_total, max_total = get_per_asset_total_cap(asset)
        mid_total = get_per_asset_total_cap_midpoint(asset)
        print(f"  {'TOTAL':8s}: {min_total*100:.1f}%-{max_total*100:.1f}% (mid: {mid_total*100:.1f}%)")

    print(f"\nGLOBAL PORTFOLIO CAP: {PORTFOLIO_GLOBAL_CAP*100:.1f}%")


def main():
    """Run all tests."""
    print("=" * 60)
    print("SPEND CAPS TEST SUITE")
    print("=" * 60)

    tests = [
        ("Spend Caps Coverage", test_spend_caps_coverage),
        ("Spend Cap Helpers", test_spend_cap_helpers),
        ("Risk Engine Clipping", test_risk_engine_spend_cap_clipping),
        ("Global Portfolio Cap", test_global_portfolio_cap),
        ("Per-Asset Total Cap", test_per_asset_total_cap),
    ]

    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"❌ {name} FAILED with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    for name, passed in results:
        status = "✓ PASSED" if passed else "❌ FAILED"
        print(f"{status}: {name}")

    # Print all caps for reference
    print_all_spend_caps()

    # Exit with appropriate code
    all_passed = all(passed for _, passed in results)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
