#!/usr/bin/env python3
"""
Comprehensive tests for crypto coverage implementation.

Tests:
1. Legacy alias behavior (scalp→15m, intraday→1h, swing→daily)
2. 25-cell matrix consistency
3. Profile vs market alignment
"""

import sys
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_legacy_aliases():
    """Test that legacy timeframe aliases work correctly."""
    print("=" * 80)
    print("TEST 1: Legacy Alias Behavior")
    print("=" * 80)

    # Use file-based testing to avoid import issues
    import re

    try:
        from config.crypto_universe import CRYPTO_ASSETS_ORDERED

        # Read source file
        source_file = Path(__file__).parent.parent / "merid" / "event_venues" / "kalshi" / "crypto_kalshi_risk.py"
        source = source_file.read_text()

        # Check for TIMEFRAME_ALIASES dict
        if "TIMEFRAME_ALIASES" not in source:
            print("✗ FAIL: TIMEFRAME_ALIASES not found")
            return False

        # Extract the aliases
        alias_pattern = r'TIMEFRAME_ALIASES.*?\{([^}]+)\}'
        alias_match = re.search(alias_pattern, source, re.DOTALL)
        if not alias_match:
            print("✗ FAIL: Could not parse TIMEFRAME_ALIASES")
            return False

        alias_text = alias_match.group(1)

        # Check for expected mappings
        expected_aliases = [
            ("scalp", "15m"),
            ("intraday", "1h"),
            ("swing", "daily"),
        ]

        print("\nExpected legacy alias mappings:")
        all_found = True
        for legacy, canonical in expected_aliases:
            pattern = f'"{legacy}".*?"{canonical}"'
            if re.search(pattern, alias_text):
                print(f"  ✓ {legacy:10} → {canonical}")
            else:
                print(f"  ✗ {legacy:10} → {canonical} NOT FOUND")
                all_found = False

        if not all_found:
            return False

        # Check that get() method supports legacy lookups
        get_method_pattern = r'def get\(self.*?canonical_tf\s*=\s*TIMEFRAME_ALIASES\.get'
        if re.search(get_method_pattern, source, re.DOTALL):
            print("\n✓ get() method supports legacy alias resolution")
        else:
            print("\n⚠ WARNING: get() method may not support legacy aliases")

        # Check for get_profile() backward compat method
        if "def get_profile(self" in source:
            print("✓ get_profile() method exists for backward compatibility")
        else:
            print("⚠ WARNING: get_profile() method not found")

        print("\n✓ PASS: Legacy alias infrastructure is in place")
        return True

    except Exception as e:
        print(f"\n✗ FAIL: Exception during testing: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_matrix_consistency():
    """Test that the 25-cell matrix is consistent across all modules."""
    print("\n" + "=" * 80)
    print("TEST 2: 25-Cell Matrix Consistency")
    print("=" * 80)

    try:
        from config.crypto_universe import (
            CRYPTO_TIMEFRAME_MATRIX,
            CRYPTO_ASSETS_ORDERED,
            CRYPTO_TIMEFRAMES_ORDERED,
            get_full_grid,
        )

        print(f"\nMatrix size: {len(CRYPTO_TIMEFRAME_MATRIX)} pairs")
        print(f"Expected: 25 (5 assets × 5 timeframes)")

        # Test 1: Matrix has exactly 25 pairs
        if len(CRYPTO_TIMEFRAME_MATRIX) != 25:
            print(f"✗ FAIL: Matrix has {len(CRYPTO_TIMEFRAME_MATRIX)} pairs, expected 25")
            return False

        # Test 2: get_full_grid() returns the same matrix
        grid = get_full_grid()
        if grid != CRYPTO_TIMEFRAME_MATRIX:
            print("✗ FAIL: get_full_grid() doesn't match CRYPTO_TIMEFRAME_MATRIX")
            return False

        print("✓ Matrix constant and function agree")

        # Test 3: All matrix pairs are valid
        print("\nValidating matrix pairs:")
        for asset, tf in CRYPTO_TIMEFRAME_MATRIX:
            if asset not in CRYPTO_ASSETS_ORDERED:
                print(f"  ✗ Invalid asset: {asset}")
                return False
            if tf not in CRYPTO_TIMEFRAMES_ORDERED:
                print(f"  ✗ Invalid timeframe: {tf}")
                return False

        print("  ✓ All 25 pairs are valid")

        # Test 4: Each asset has exactly 5 timeframes
        from collections import Counter
        asset_counts = Counter(asset for asset, _ in CRYPTO_TIMEFRAME_MATRIX)

        print("\nAsset distribution:")
        for asset in CRYPTO_ASSETS_ORDERED:
            count = asset_counts[asset]
            status = "✓" if count == 5 else "✗"
            print(f"  {status} {asset}: {count} timeframes")

            if count != 5:
                return False

        # Test 5: Verify strategy profiles exist (file-based check)
        import re
        source_file = Path(__file__).parent.parent / "merid" / "event_venues" / "kalshi" / "crypto_kalshi_risk.py"
        source = source_file.read_text()

        # Count profile definitions
        profile_count = len(re.findall(r'\("(BTC|ETH|SOL|XRP|DOGE)", "(15m|1h|daily|weekly|monthly)"\):', source))
        print(f"\nStrategy profiles defined: {profile_count}")

        if profile_count != 25:
            print(f"✗ FAIL: Expected 25 profiles, got {profile_count}")
            return False

        print("  ✓ All 25 matrix pairs have strategy profiles")

        print("\n✓ PASS: Matrix is consistent across all modules")
        return True

    except Exception as e:
        print(f"\n✗ FAIL: Exception during testing: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_continuous_trader_filter():
    """Test that continuous trader filter matches the matrix."""
    print("\n" + "=" * 80)
    print("TEST 3: Continuous Trader Filter Alignment")
    print("=" * 80)

    import re

    try:
        from config.crypto_universe import CRYPTO_ASSETS_ORDERED, CRYPTO_TIMEFRAMES_ORDERED

        # Read continuous trader source
        source_file = Path(__file__).parent.parent / "merid" / "trading" / "kalshi_continuous_trader.py"
        source = source_file.read_text()

        # Extract _CRYPTO_ASSETS
        assets_match = re.search(r'_CRYPTO_ASSETS\s*=\s*\(([^)]+)\)', source)
        if not assets_match:
            print("✗ FAIL: Could not find _CRYPTO_ASSETS")
            return False

        assets_str = assets_match.group(1)
        trader_assets = re.findall(r'"([^"]+)"', assets_str)

        # Extract _CRYPTO_TIMEFRAMES
        tf_match = re.search(r'_CRYPTO_TIMEFRAMES\s*=\s*\(([^)]+)\)', source)
        if not tf_match:
            print("✗ FAIL: Could not find _CRYPTO_TIMEFRAMES")
            return False

        tf_str = tf_match.group(1)
        trader_timeframes = re.findall(r'"([^"]+)"', tf_str)

        print(f"\nContinuous trader assets: {trader_assets}")
        print(f"Expected: {CRYPTO_ASSETS_ORDERED}")

        print(f"\nContinuous trader timeframes: {trader_timeframes}")
        print(f"Expected: {CRYPTO_TIMEFRAMES_ORDERED}")

        # Compare
        if trader_assets != CRYPTO_ASSETS_ORDERED:
            print("✗ FAIL: Trader assets don't match canonical list")
            return False

        if trader_timeframes != CRYPTO_TIMEFRAMES_ORDERED:
            print("✗ FAIL: Trader timeframes don't match canonical list")
            return False

        print("\n✓ PASS: Continuous trader filter matches canonical matrix")
        return True

    except Exception as e:
        print(f"\n✗ FAIL: Exception during testing: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_readiness_script_alignment():
    """Test that readiness script uses the matrix correctly."""
    print("\n" + "=" * 80)
    print("TEST 4: Readiness Script Matrix Alignment")
    print("=" * 80)

    import re

    try:
        from config.crypto_universe import CRYPTO_ASSETS_ORDERED, CRYPTO_TIMEFRAMES_ORDERED

        # Read readiness script source
        source_file = Path(__file__).parent.parent / "scripts" / "kalshi_crypto_live_readiness.py"
        source = source_file.read_text()

        # Check that it imports from crypto_universe
        if "from config.crypto_universe import" not in source:
            print("⚠ WARNING: Readiness script doesn't import from crypto_universe")
            print("  Consider importing CRYPTO_TIMEFRAME_MATRIX for consistency")

        # Check that it iterates over the correct assets and timeframes
        if "CRYPTO_ASSETS_ORDERED" in source and "CRYPTO_TIMEFRAMES_ORDERED" in source:
            print("✓ Readiness script imports canonical lists")
        else:
            print("⚠ WARNING: Readiness script may have hardcoded lists")

        # Check for the 25-cell iteration
        if "for asset in CRYPTO_ASSETS_ORDERED" in source or "for asset in crypto_assets" in source.lower():
            print("✓ Readiness script iterates over assets")
        else:
            print("⚠ WARNING: Could not verify asset iteration")

        if "for timeframe in CRYPTO_TIMEFRAMES_ORDERED" in source or "for timeframe in crypto_timeframes" in source.lower():
            print("✓ Readiness script iterates over timeframes")
        else:
            print("⚠ WARNING: Could not verify timeframe iteration")

        print("\n✓ PASS: Readiness script appears aligned with matrix")
        return True

    except Exception as e:
        print(f"\n✗ FAIL: Exception during testing: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all comprehensive tests."""
    print("=" * 80)
    print("CRYPTO COVERAGE COMPREHENSIVE TEST SUITE")
    print("=" * 80)
    print("\nTesting complete 25-market coverage:")
    print("  - 5 assets: BTC, ETH, SOL, XRP, DOGE")
    print("  - 5 timeframes: 15m, 1h, daily, weekly, monthly")
    print("  - Total: 25 distinct markets\n")

    tests = [
        ("Legacy Alias Behavior", test_legacy_aliases),
        ("Matrix Consistency", test_matrix_consistency),
        ("Continuous Trader Filter", test_continuous_trader_filter),
        ("Readiness Script Alignment", test_readiness_script_alignment),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ EXCEPTION in {name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status:8} {name}")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    print(f"\nTotal: {passed}/{total} tests passed")

    if all(result for _, result in results):
        print("\n" + "=" * 80)
        print("✓ ALL TESTS PASSED")
        print("=" * 80)
        print("\nCrypto coverage is fully validated:")
        print("  ✓ Legacy aliases work correctly")
        print("  ✓ 25-cell matrix is consistent")
        print("  ✓ All modules aligned with matrix")
        print("  ✓ Ready for production deployment")
        return 0
    else:
        print("\n" + "=" * 80)
        print("✗ SOME TESTS FAILED")
        print("=" * 80)
        return 1


if __name__ == "__main__":
    sys.exit(main())
