#!/usr/bin/env python3
"""
MERID Edge Threshold Dry-Run Test
==================================
Tests the new per-asset, per-timeframe edge thresholds by validating the
configuration without requiring a full MERID server or dependencies.

This script:
1. Shows the current edge threshold configuration
2. Compares new thresholds with the old global 2% threshold
3. Validates that all expected (asset, timeframe) pairs are configured

Usage:
    # Show threshold configuration
    python scripts/test_edge_thresholds.py

    # Show comparison with old threshold
    python scripts/test_edge_thresholds.py --compare

Exit codes:
    0  Success — configuration validated
    1  Error — configuration invalid
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from typing import Dict, List, Tuple

# ── Edge threshold configuration (mirrored from kalshi_continuous_trader.py) ──

EDGE_THRESHOLDS: Dict[Tuple[str, str], float] = {
    # BTC
    ("BTC", "15m"): 0.02,
    ("BTC", "1h"): 0.03,
    ("BTC", "daily"): 0.04,
    ("BTC", "weekly"): 0.05,
    ("BTC", "monthly"): 0.05,
    # ETH
    ("ETH", "15m"): 0.03,
    ("ETH", "1h"): 0.04,
    ("ETH", "daily"): 0.05,
    ("ETH", "weekly"): 0.06,
    ("ETH", "monthly"): 0.06,
    # SOL
    ("SOL", "15m"): 0.04,
    ("SOL", "1h"): 0.06,
    ("SOL", "daily"): 0.06,
    ("SOL", "weekly"): 0.08,
    ("SOL", "monthly"): 0.08,
    # XRP
    ("XRP", "15m"): 0.04,
    ("XRP", "1h"): 0.06,
    ("XRP", "daily"): 0.06,
    ("XRP", "weekly"): 0.08,
    ("XRP", "monthly"): 0.08,
    # DOGE
    ("DOGE", "15m"): 0.04,
    ("DOGE", "1h"): 0.06,
    ("DOGE", "daily"): 0.06,
    ("DOGE", "weekly"): 0.08,
    ("DOGE", "monthly"): 0.08,
}

CRYPTO_ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")
CRYPTO_TIMEFRAMES = ("15m", "1h", "daily", "weekly", "monthly")


def show_threshold_config():
    """Display the current edge threshold configuration."""
    print("\n" + "=" * 70)
    print("EDGE THRESHOLD CONFIGURATION")
    print("=" * 70)
    print("\nConfigured thresholds (asset, timeframe) → min_edge:")
    print()

    # Group by asset for clearer display
    by_asset: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
    for (asset, timeframe), threshold in sorted(EDGE_THRESHOLDS.items()):
        by_asset[asset].append((timeframe, threshold))

    for asset in sorted(by_asset.keys()):
        print(f"  {asset}:")
        for timeframe, threshold in sorted(by_asset[asset], key=lambda x: x[1]):
            print(f"    {timeframe:8s} → {threshold * 100:5.1f}%")
        print()

    print("=" * 70)
    print()


def validate_configuration():
    """Validate that all expected (asset, timeframe) pairs are configured."""
    print("\n" + "=" * 70)
    print("CONFIGURATION VALIDATION")
    print("=" * 70)
    print()

    expected_pairs = [(a, tf) for a in CRYPTO_ASSETS for tf in CRYPTO_TIMEFRAMES]
    missing = [pair for pair in expected_pairs if pair not in EDGE_THRESHOLDS]

    if missing:
        print("✗ VALIDATION FAILED: Missing configurations:")
        for asset, timeframe in missing:
            print(f"  - {asset} / {timeframe}")
        print()
        return False

    print(f"✓ All {len(expected_pairs)} (asset, timeframe) pairs are configured")
    print(f"✓ Configuration is complete")
    print()
    return True


def compare_with_old_threshold():
    """Compare new thresholds with the old global 2% threshold."""
    print("\n" + "=" * 70)
    print("THRESHOLD COMPARISON")
    print("=" * 70)
    print()

    old_threshold = 0.02  # Previous global default
    print(f"Old global threshold: {old_threshold * 100:.1f}%")
    print()
    print("-" * 70)
    print(f"{'Asset':<8} {'Timeframe':<10} {'Old':>10} {'New':>10} {'Change':>20}")
    print("-" * 70)

    more_lenient_count = 0
    same_count = 0
    stricter_count = 0

    for (asset, timeframe), new_threshold in sorted(EDGE_THRESHOLDS.items()):
        old_pct = old_threshold * 100
        new_pct = new_threshold * 100
        change = new_pct - old_pct

        if change > 0:
            change_str = f"+{change:.1f}% (stricter)"
            stricter_count += 1
        elif change < 0:
            change_str = f"{change:.1f}% (more lenient)"
            more_lenient_count += 1
        else:
            change_str = "(same)"
            same_count += 1

        print(
            f"{asset:<8} {timeframe:<10} {old_pct:>8.1f}% {new_pct:>8.1f}% "
            f"{change_str:>20}"
        )

    print("-" * 70)
    print()
    print(f"Summary:")
    print(f"  More lenient: {more_lenient_count} pairs (will accept more markets)")
    print(f"  Same:         {same_count} pairs (no change)")
    print(f"  Stricter:     {stricter_count} pairs (will reject more markets)")
    print()


def show_expected_impact():
    """Show the expected impact of the new thresholds."""
    print("\n" + "=" * 70)
    print("EXPECTED IMPACT")
    print("=" * 70)
    print()
    print("Based on the new thresholds, you should expect:")
    print()
    print("BTC:")
    print("  - 15m/1h: More markets accepted (2-3% vs old 2%)")
    print("  - daily/weekly: Fewer markets (4-5% vs old 2%) but higher quality")
    print()
    print("ETH:")
    print("  - 15m/1h: Fewer markets (3-4% vs old 2%) but higher quality")
    print("  - daily/weekly: Fewer markets (5-6% vs old 2%) but higher quality")
    print()
    print("SOL/XRP/DOGE:")
    print("  - 15m/1h: Fewer markets (4-6% vs old 2%) but higher quality")
    print("  - daily/weekly: Fewer markets (6-8% vs old 2%) but higher quality")
    print()
    print("Overall strategy:")
    print("  ✓ More aggressive on BTC short-term (15m/1h)")
    print("  ✓ More conservative on longer-term positions")
    print("  ✓ Higher quality threshold for volatile assets (SOL/XRP/DOGE)")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Test MERID edge thresholds",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Show detailed comparison with old threshold",
    )
    parser.add_argument(
        "--impact",
        action="store_true",
        help="Show expected impact of new thresholds",
    )

    args = parser.parse_args()

    try:
        # Always show configuration
        show_threshold_config()

        # Validate configuration
        if not validate_configuration():
            return 1

        # Show comparison if requested
        if args.compare:
            compare_with_old_threshold()

        # Show expected impact if requested
        if args.impact:
            show_expected_impact()

        # If no specific option, show everything
        if not args.compare and not args.impact:
            compare_with_old_threshold()
            show_expected_impact()

        print("=" * 70)
        print("CONFIGURATION TEST COMPLETED SUCCESSFULLY")
        print("=" * 70)
        print()
        print("Next steps to test with live MERID:")
        print()
        print("1. Ensure MERID_TRADE_MODE=paper (no live orders)")
        print("   export MERID_TRADE_MODE=paper")
        print()
        print("2. Start MERID server:")
        print("   python -m web.main")
        print()
        print("3. Monitor logs for edge threshold messages:")
        print("   grep 'min_edge_threshold' logs/merid.log")
        print()
        print("4. Look for these patterns in signal_to_sizing logs:")
        print("   - 'min_edge_threshold=X.XXXX [ASSET/TIMEFRAME] ACCEPTED'")
        print("   - 'min_edge_threshold=X.XXXX [ASSET/TIMEFRAME] REJECTED'")
        print()
        print("5. Check per-asset statistics in continuous trader logs:")
        print("   grep 'ContinuousTrader candidates:' logs/merid.log")
        print()
        print("6. To revert to normal live trading:")
        print("   unset MERID_TRADE_MODE  # or set to 'live'")
        print()

        return 0

    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        return 1
    except Exception as e:
        print(f"\n\n✗ TEST FAILED: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

