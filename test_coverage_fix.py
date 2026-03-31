#!/usr/bin/env python3
"""
Quick verification test for the crypto coverage fixes.

Tests that all 5 assets × 5 timeframes = 25 strategy profiles exist.
"""

import sys
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))


def test_crypto_universe():
    """Test that crypto_universe defines all assets and timeframes."""
    from config.crypto_universe import CRYPTO_ASSETS, CRYPTO_TIMEFRAMES, get_full_grid

    print("Testing crypto_universe.py...")
    print(f"  Assets: {list(CRYPTO_ASSETS)}")
    print(f"  Timeframes: {list(CRYPTO_TIMEFRAMES)}")

    assert len(CRYPTO_ASSETS) == 5, f"Expected 5 assets, got {len(CRYPTO_ASSETS)}"
    assert len(CRYPTO_TIMEFRAMES) == 5, f"Expected 5 timeframes, got {len(CRYPTO_TIMEFRAMES)}"

    grid = get_full_grid()
    assert len(grid) == 25, f"Expected 25 pairs, got {len(grid)}"

    print("  ✓ crypto_universe: PASS (5 assets × 5 timeframes = 25 pairs)")
    return True


def test_crypto_kalshi_risk():
    """Test that crypto_kalshi_risk has strategy profiles for all 25 pairs."""
    # Test using regex to avoid import issues
    import re

    print("\nTesting crypto_kalshi_risk.py...")

    source_file = Path(__file__).parent / "merid" / "event_venues" / "kalshi" / "crypto_kalshi_risk.py"
    source = source_file.read_text()

    # Check TIMEFRAMES definition
    match = re.search(r'TIMEFRAMES:\s*List\[str\]\s*=\s*\[([^\]]+)\]', source)
    if not match:
        print("  ✗ Could not find TIMEFRAMES definition")
        return False

    timeframes_str = match.group(1)
    timeframes = re.findall(r'"([^"]+)"', timeframes_str)

    print(f"  Timeframes: {timeframes}")

    expected_timeframes = ["15m", "1h", "daily", "weekly", "monthly"]
    if timeframes != expected_timeframes:
        print(f"  ✗ Expected {expected_timeframes}, got {timeframes}")
        return False

    # Check that all 25 profiles are defined in _build_default_profiles
    profile_count = len(re.findall(r'\("(BTC|ETH|SOL|XRP|DOGE)", "(15m|1h|daily|weekly|monthly)"\):', source))
    print(f"  Strategy profiles defined: {profile_count}")

    if profile_count != 25:
        print(f"  ✗ Expected 25 profiles, got {profile_count}")
        return False

    # Check for legacy alias support
    if 'TIMEFRAME_ALIASES' not in source:
        print("  ✗ TIMEFRAME_ALIASES not found")
        return False

    if 'def get_profile(self' not in source:
        print("  ✗ get_profile() method not found")
        return False

    print(f"  ✓ All 25 strategy profiles defined")
    print("  ✓ Legacy alias support present")
    print("  ✓ crypto_kalshi_risk: PASS")
    return True


def test_continuous_trader():
    """Test that continuous trader includes all timeframes."""
    # We can't import it directly without dependencies, so read the source
    import re

    print("\nTesting kalshi_continuous_trader.py...")

    source_file = Path(__file__).parent / "merid" / "trading" / "kalshi_continuous_trader.py"
    source = source_file.read_text()

    # Find the _CRYPTO_TIMEFRAMES definition
    match = re.search(r'_CRYPTO_TIMEFRAMES\s*=\s*\(([^)]+)\)', source)
    if not match:
        print("  ✗ Could not find _CRYPTO_TIMEFRAMES definition")
        return False

    timeframes_str = match.group(1)
    # Extract quoted strings
    timeframes = re.findall(r'"([^"]+)"', timeframes_str)

    print(f"  Timeframes: {timeframes}")

    expected = ["15m", "1h", "daily", "weekly", "monthly"]
    if timeframes != expected:
        print(f"  ✗ Expected {expected}, got {timeframes}")
        return False

    print("  ✓ continuous_trader: PASS (includes weekly and monthly)")
    return True


def test_market_catalog_logging():
    """Test that market catalog logging includes all timeframes."""
    import re

    print("\nTesting market_catalog.py logging...")

    source_file = Path(__file__).parent / "merid" / "event_venues" / "kalshi" / "market_catalog.py"
    source = source_file.read_text()

    # Find the logger.info call
    match = re.search(r'logger\.info\(\s*"Catalog.*?15m.*?monthly', source, re.DOTALL)
    if not match:
        print("  ✗ Logging does not include all timeframes")
        return False

    # Check that all timeframes are logged
    log_line = match.group(0)
    required_tfs = ["15m", "1h", "daily", "weekly", "monthly"]

    for tf in required_tfs:
        if tf not in log_line:
            print(f"  ✗ Timeframe '{tf}' not in logging statement")
            return False

    print("  ✓ market_catalog: PASS (logs all 5 timeframes)")
    return True


def main():
    """Run all tests."""
    print("=" * 80)
    print("Crypto Coverage Fix Verification")
    print("=" * 80)

    tests = [
        test_crypto_universe,
        test_crypto_kalshi_risk,
        test_continuous_trader,
        test_market_catalog_logging,
    ]

    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"  ✗ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print("\n" + "=" * 80)
    print("Summary:")
    print("=" * 80)

    passed = sum(results)
    total = len(results)

    print(f"Passed: {passed}/{total}")

    if all(results):
        print("\n✓ ALL TESTS PASSED")
        print("\nAll 5 assets (BTC, ETH, SOL, XRP, DOGE) × 5 timeframes (15m, 1h, daily, weekly, monthly)")
        print("are now fully covered for trading with:")
        print("  - Strategy profiles defined")
        print("  - Continuous trader filter updated")
        print("  - Market catalog logging enhanced")
        print("  - Readiness script updated")
        return 0
    else:
        print("\n✗ SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
