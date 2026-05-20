#!/usr/bin/env python3
"""
Unit tests for dynamic entry window resolver.

Tests the resolver at various minutes_to_expiry values for each asset
to confirm allow/deny matches expectations.
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.prediction.dynamic_entry_window import (
    resolve_entry_window,
    EntryWindowDecision,
    get_policies,
    update_policies,
    DEFAULT_POLICIES,
    TerminalPhaseConfig,
    AssetWindowPolicy,
    VolatilityTier,
    VOLATILITY_TIERED_BASE_THRESHOLDS,
    T2E_MULTIPLIERS,
    BOOK_QUALITY_MULTIPLIERS,
)


def test_btc_policy():
    """Test BTC policy: 12-3 base window, terminal 3-0 with dynamic edge threshold."""
    print("\n=== Testing BTC Policy (12-3 base, terminal 3-0, dynamic threshold) ===")
    
    # Test cases: (minutes_to_expiry, edge_pct, expected_allowed, expected_reason)
    # Note: With dynamic thresholds, the exact edge threshold varies based on volatility tier,
    # time-to-expiry multiplier, and orderbook quality. These tests use approximate expectations.
    test_cases = [
        # Outside window (too early)
        (15.0, 15.0, False, EntryWindowDecision.OUTSIDE_WINDOW),
        (13.0, 15.0, False, EntryWindowDecision.OUTSIDE_WINDOW),
        
        # In base window (should allow regardless of edge)
        (12.0, 10.0, True, EntryWindowDecision.ALLOWED_BASE),
        (10.0, 5.0, True, EntryWindowDecision.ALLOWED_BASE),
        (5.0, 1.0, True, EntryWindowDecision.ALLOWED_BASE),
        (4.0, 1.0, True, EntryWindowDecision.ALLOWED_BASE),
        
        # In terminal band (3-0) - very low edge should reject
        (2.5, 5.0, False, EntryWindowDecision.TERMINAL_EDGE_TOO_LOW),
        (2.0, 8.0, False, EntryWindowDecision.TERMINAL_EDGE_TOO_LOW),
        
        # In terminal band - moderate to high edge should allow (dynamic threshold varies)
        (2.5, 22.0, True, EntryWindowDecision.ALLOWED_TERMINAL_OVERRIDE),
        (2.0, 25.0, True, EntryWindowDecision.ALLOWED_TERMINAL_OVERRIDE),
        (1.0, 30.0, True, EntryWindowDecision.ALLOWED_TERMINAL_OVERRIDE),
        (0.5, 50.0, True, EntryWindowDecision.ALLOWED_TERMINAL_OVERRIDE),
        
        # Outside window (past expiry)
        (-1.0, 50.0, False, EntryWindowDecision.OUTSIDE_WINDOW),
    ]
    
    passed = 0
    failed = 0
    
    for minutes, edge, expected_allowed, expected_reason in test_cases:
        resolution = resolve_entry_window(
            asset="BTC",
            minutes_to_expiry=minutes,
            edge_pct=edge
        )
        
        if resolution.allowed == expected_allowed and resolution.reason == expected_reason:
            passed += 1
            print(f"  ✓ PASS: minutes={minutes:5.1f}, edge={edge:5.1f}% → allowed={resolution.allowed}, reason={resolution.reason.value}")
        else:
            failed += 1
            print(f"  ✗ FAIL: minutes={minutes:5.1f}, edge={edge:5.1f}% → expected_allowed={expected_allowed}, expected_reason={expected_reason.value}")
            print(f"         got: allowed={resolution.allowed}, reason={resolution.reason.value}")
    
    print(f"\n  BTC: {passed}/{len(test_cases)} tests passed")
    return failed == 0


def test_eth_policy():
    """Test ETH policy: 12-3 base window, terminal 3-0 with dynamic edge threshold."""
    print("\n=== Testing ETH Policy (12-3 base, terminal 3-0, dynamic threshold) ===")
    
    test_cases = [
        # In base window
        (10.0, 5.0, True, EntryWindowDecision.ALLOWED_BASE),
        (5.0, 1.0, True, EntryWindowDecision.ALLOWED_BASE),
        
        # Terminal with high edge
        (2.5, 22.0, True, EntryWindowDecision.ALLOWED_TERMINAL_OVERRIDE),
        
        # Terminal with very low edge (dynamic threshold varies)
        (2.5, 5.0, False, EntryWindowDecision.TERMINAL_EDGE_TOO_LOW),
    ]
    
    passed = 0
    failed = 0
    
    for minutes, edge, expected_allowed, expected_reason in test_cases:
        resolution = resolve_entry_window(
            asset="ETH",
            minutes_to_expiry=minutes,
            edge_pct=edge
        )
        
        if resolution.allowed == expected_allowed and resolution.reason == expected_reason:
            passed += 1
            print(f"  ✓ PASS: minutes={minutes:5.1f}, edge={edge:5.1f}% → allowed={resolution.allowed}, reason={resolution.reason.value}")
        else:
            failed += 1
            print(f"  ✗ FAIL: minutes={minutes:5.1f}, edge={edge:5.1f}% → expected_allowed={expected_allowed}, expected_reason={expected_reason.value}")
            print(f"         got: allowed={resolution.allowed}, reason={resolution.reason.value}")
    
    print(f"\n  ETH: {passed}/{len(test_cases)} tests passed")
    return failed == 0


def test_sol_policy():
    """Test SOL policy: 10-4 base window, terminal enabled with dynamic threshold."""
    print("\n=== Testing SOL Policy (10-4 base, terminal enabled, dynamic threshold) ===")
    
    test_cases = [
        # In base window
        (10.0, 5.0, True, EntryWindowDecision.ALLOWED_BASE),
        (8.0, 5.0, True, EntryWindowDecision.ALLOWED_BASE),
        (5.0, 1.0, True, EntryWindowDecision.ALLOWED_BASE),
        (4.5, 1.0, True, EntryWindowDecision.ALLOWED_BASE),
        
        # Terminal band - now enabled with dynamic threshold
        (3.5, 28.0, True, EntryWindowDecision.ALLOWED_TERMINAL_OVERRIDE),
        (2.0, 30.0, True, EntryWindowDecision.ALLOWED_TERMINAL_OVERRIDE),
        
        # Terminal band with very low edge should reject
        (1.0, 5.0, False, EntryWindowDecision.TERMINAL_EDGE_TOO_LOW),
        
        # Outside window (too early)
        (12.0, 50.0, False, EntryWindowDecision.OUTSIDE_WINDOW),
    ]
    
    passed = 0
    failed = 0
    
    for minutes, edge, expected_allowed, expected_reason in test_cases:
        resolution = resolve_entry_window(
            asset="SOL",
            minutes_to_expiry=minutes,
            edge_pct=edge
        )
        
        if resolution.allowed == expected_allowed and resolution.reason == expected_reason:
            passed += 1
            print(f"  ✓ PASS: minutes={minutes:5.1f}, edge={edge:5.1f}% → allowed={resolution.allowed}, reason={resolution.reason.value}")
        else:
            failed += 1
            print(f"  ✗ FAIL: minutes={minutes:5.1f}, edge={edge:5.1f}% → expected_allowed={expected_allowed}, expected_reason={expected_reason.value}")
            print(f"         got: allowed={resolution.allowed}, reason={resolution.reason.value}")
    
    print(f"\n  SOL: {passed}/{len(test_cases)} tests passed")
    return failed == 0


def test_xrp_policy():
    """Test XRP policy: 10-4 base window, terminal enabled with dynamic threshold."""
    print("\n=== Testing XRP Policy (10-4 base, terminal enabled, dynamic threshold) ===")
    
    test_cases = [
        (8.0, 5.0, True, EntryWindowDecision.ALLOWED_BASE),
        (3.5, 28.0, True, EntryWindowDecision.ALLOWED_TERMINAL_OVERRIDE),
        (1.0, 5.0, False, EntryWindowDecision.TERMINAL_EDGE_TOO_LOW),
    ]
    
    passed = 0
    failed = 0
    
    for minutes, edge, expected_allowed, expected_reason in test_cases:
        resolution = resolve_entry_window(
            asset="XRP",
            minutes_to_expiry=minutes,
            edge_pct=edge
        )
        
        if resolution.allowed == expected_allowed and resolution.reason == expected_reason:
            passed += 1
            print(f"  ✓ PASS: minutes={minutes:5.1f}, edge={edge:5.1f}% → allowed={resolution.allowed}, reason={resolution.reason.value}")
        else:
            failed += 1
            print(f"  ✗ FAIL: minutes={minutes:5.1f}, edge={edge:5.1f}% → expected_allowed={expected_allowed}, expected_reason={expected_reason.value}")
            print(f"         got: allowed={resolution.allowed}, reason={resolution.reason.value}")
    
    print(f"\n  XRP: {passed}/{len(test_cases)} tests passed")
    return failed == 0


def test_doge_policy():
    """Test DOGE policy: 10-4 base window, terminal enabled with dynamic threshold."""
    print("\n=== Testing DOGE Policy (10-4 base, terminal enabled, dynamic threshold) ===")
    
    test_cases = [
        (8.0, 5.0, True, EntryWindowDecision.ALLOWED_BASE),
        (3.5, 32.0, True, EntryWindowDecision.ALLOWED_TERMINAL_OVERRIDE),
        (1.0, 5.0, False, EntryWindowDecision.TERMINAL_EDGE_TOO_LOW),
    ]
    
    passed = 0
    failed = 0
    
    for minutes, edge, expected_allowed, expected_reason in test_cases:
        resolution = resolve_entry_window(
            asset="DOGE",
            minutes_to_expiry=minutes,
            edge_pct=edge
        )
        
        if resolution.allowed == expected_allowed and resolution.reason == expected_reason:
            passed += 1
            print(f"  ✓ PASS: minutes={minutes:5.1f}, edge={edge:5.1f}% → allowed={resolution.allowed}, reason={resolution.reason.value}")
        else:
            failed += 1
            print(f"  ✗ FAIL: minutes={minutes:5.1f}, edge={edge:5.1f}% → expected_allowed={expected_allowed}, expected_reason={expected_reason.value}")
            print(f"         got: allowed={resolution.allowed}, reason={resolution.reason.value}")
    
    print(f"\n  DOGE: {passed}/{len(test_cases)} tests passed")
    return failed == 0


def test_policy_update():
    """Test that policy updates are reflected in resolver."""
    print("\n=== Testing Policy Update ===")
    
    # Get current policies
    original_policies = get_policies()
    
    # Create custom policy with different window (6-1 instead of 12-3)
    custom_policy = AssetWindowPolicy(
        asset="BTC",
        base_window_start_minutes=6,
        base_window_end_minutes=1,
        terminal_config=TerminalPhaseConfig(
            enabled=False,
            edge_threshold_pct=30.0,
            max_terminal_minutes=1
        ),
        policy_name="test_custom_btc"
    )
    
    # Update policies
    update_policies({"BTC": custom_policy})
    
    # Test with new policy - 8 minutes should be outside the 6-1 window
    resolution = resolve_entry_window(
        asset="BTC",
        minutes_to_expiry=8.0,
        edge_pct=50.0
    )
    
    # Test with new policy - 4 minutes should be inside the 6-1 window
    resolution_inside = resolve_entry_window(
        asset="BTC",
        minutes_to_expiry=4.0,
        edge_pct=50.0
    )
    
    success = True
    if resolution.allowed:
        print(f"  ✗ FAIL: Custom policy should reject 8.0 minutes (outside 6-1 window), got allowed=True")
        success = False
    else:
        print(f"  ✓ PASS: Custom policy rejected 8.0 minutes (outside 6-1 window)")
    
    if not resolution_inside.allowed:
        print(f"  ✗ FAIL: Custom policy should allow 4.0 minutes (inside 6-1 window), got allowed=False")
        success = False
    else:
        print(f"  ✓ PASS: Custom policy allowed 4.0 minutes (inside 6-1 window)")
    
    # Restore original policies
    update_policies(original_policies)
    
    print(f"\n  Policy Update: {'PASS' if success else 'FAIL'}")
    return success


def test_bucket_classification():
    """Test that minutes_to_expiry is correctly classified into buckets."""
    print("\n=== Testing Bucket Classification ===")
    
    test_cases = [
        (0.5, "0-2"),
        (1.5, "0-2"),
        (2.5, "2-5"),
        (4.5, "2-5"),
        (5.5, "5-10"),
        (9.5, "5-10"),
        (10.5, "10+"),
        (15.0, "10+"),
    ]
    
    passed = 0
    failed = 0
    
    for minutes, expected_bucket in test_cases:
        resolution = resolve_entry_window(
            asset="BTC",
            minutes_to_expiry=minutes,
            edge_pct=50.0
        )
        
        if resolution.bucket == expected_bucket:
            passed += 1
            print(f"  ✓ PASS: minutes={minutes:5.1f} → bucket={resolution.bucket}")
        else:
            failed += 1
            print(f"  ✗ FAIL: minutes={minutes:5.1f} → expected bucket={expected_bucket}, got={resolution.bucket}")
    
    print(f"\n  Bucket Classification: {passed}/{len(test_cases)} tests passed")
    return failed == 0


def test_dynamic_threshold_metadata():
    """Test that dynamic threshold metadata is populated in WindowResolution."""
    print("\n=== Testing Dynamic Threshold Metadata ===")
    
    # Test with dynamic threshold enabled (default)
    resolution = resolve_entry_window(
        asset="BTC",
        minutes_to_expiry=2.5,
        edge_pct=25.0,
        ticker="KXBTC-26FEB-ABOVE-50000"
    )
    
    # Check that dynamic threshold metadata fields are populated
    success = True
    if resolution.dynamic_edge_threshold is None:
        print(f"  ✗ FAIL: dynamic_edge_threshold should be populated")
        success = False
    else:
        print(f"  ✓ PASS: dynamic_edge_threshold={resolution.dynamic_edge_threshold:.2%}")
    
    if resolution.volatility_tier is None:
        print(f"  ✗ FAIL: volatility_tier should be populated")
        success = False
    else:
        print(f"  ✓ PASS: volatility_tier={resolution.volatility_tier}")
    
    # t2e_multiplier is None (removed to prevent over-conservative thresholds)
    if resolution.t2e_multiplier is not None:
        print(f"  ✗ FAIL: t2e_multiplier should be None (removed)")
        success = False
    else:
        print(f"  ✓ PASS: t2e_multiplier is None (removed)")
    
    if resolution.book_quality_multiplier is None:
        print(f"  ✗ FAIL: book_quality_multiplier should be populated")
        success = False
    else:
        print(f"  ✓ PASS: book_quality_multiplier={resolution.book_quality_multiplier}")
    
    print(f"\n  Dynamic Threshold Metadata: {'PASS' if success else 'FAIL'}")
    return success


def test_static_threshold_fallback():
    """Test that static threshold is used when dynamic threshold is disabled."""
    print("\n=== Testing Static Threshold Fallback ===")
    
    # Create policy with dynamic threshold disabled
    custom_policy = AssetWindowPolicy(
        asset="BTC",
        base_window_start_minutes=12,
        base_window_end_minutes=3,
        terminal_config=TerminalPhaseConfig(
            enabled=True,
            edge_threshold_pct=25.0,
            max_terminal_minutes=3,
            use_dynamic_threshold=False,  # Disable dynamic threshold
        ),
        policy_name="test_static_btc"
    )
    
    # Update policies temporarily
    original_policies = get_policies()
    update_policies({"BTC": custom_policy})
    
    # Test with static threshold
    resolution = resolve_entry_window(
        asset="BTC",
        minutes_to_expiry=2.5,
        edge_pct=25.0,
        ticker="KXBTC-26FEB-ABOVE-50000"
    )
    
    # Restore original policies
    update_policies(original_policies)
    
    success = True
    # With dynamic disabled, should use static 25.0% threshold (0.25 as decimal)
    expected_threshold = 0.25  # 25% as decimal
    if resolution.dynamic_edge_threshold != expected_threshold:
        print(f"  ✗ FAIL: Expected static threshold {expected_threshold:.2%}, got {resolution.dynamic_edge_threshold:.2%}")
        success = False
    else:
        print(f"  ✓ PASS: Using static threshold {resolution.dynamic_edge_threshold:.2%}")
    
    # Volatility tier and multipliers should be None when dynamic is disabled
    if resolution.volatility_tier is not None:
        print(f"  ✗ FAIL: volatility_tier should be None with static threshold")
        success = False
    else:
        print(f"  ✓ PASS: volatility_tier is None with static threshold")
    
    print(f"\n  Static Threshold Fallback: {'PASS' if success else 'FAIL'}")
    return success


def test_volatility_tiered_thresholds():
    """Test that volatility-tiered base thresholds are defined correctly."""
    print("\n=== Testing Volatility-Tiered Base Thresholds ===")
    
    success = True
    expected_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    expected_tiers = ["low", "medium", "high"]
    
    for asset in expected_assets:
        if asset not in VOLATILITY_TIERED_BASE_THRESHOLDS:
            print(f"  ✗ FAIL: Asset {asset} not in threshold table")
            success = False
        else:
            thresholds = VOLATILITY_TIERED_BASE_THRESHOLDS[asset]
            for tier in expected_tiers:
                if tier not in thresholds:
                    print(f"  ✗ FAIL: Tier {tier} not defined for {asset}")
                    success = False
                else:
                    low, high = thresholds[tier]
                    if low >= high:
                        print(f"  ✗ FAIL: {asset} {tier} threshold invalid: low={low} >= high={high}")
                        success = False
                    print(f"  ✓ PASS: {asset} {tier}: {low:.0%}-{high:.0%}")
    
    print(f"\n  Volatility-Tiered Thresholds: {'PASS' if success else 'FAIL'}")
    return success


def main():
    """Run all unit tests."""
    print("=" * 70)
    print("Dynamic Entry Window Resolver - Unit Tests")
    print("=" * 70)
    
    all_passed = True
    
    # Test each asset policy
    all_passed &= test_btc_policy()
    all_passed &= test_eth_policy()
    all_passed &= test_sol_policy()
    all_passed &= test_xrp_policy()
    all_passed &= test_doge_policy()
    
    # Test policy updates
    all_passed &= test_policy_update()
    
    # Test bucket classification
    all_passed &= test_bucket_classification()
    
    # Test new dynamic threshold functionality
    all_passed &= test_dynamic_threshold_metadata()
    all_passed &= test_static_threshold_fallback()
    all_passed &= test_volatility_tiered_thresholds()
    
    print("\n" + "=" * 70)
    if all_passed:
        print("ALL TESTS PASSED ✓")
        return 0
    else:
        print("SOME TESTS FAILED ✗")
        return 1


if __name__ == "__main__":
    sys.exit(main())
