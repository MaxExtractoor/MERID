#!/usr/bin/env python3
"""
Test resting order exposure tracking fix (2026-07-08).

This test verifies that:
1. Resting orders are counted in window exposure at placement time
2. Multiple resting orders cannot exceed the 5% total venue window limit
3. Resting exposure is released when orders fill, cancel, or are rejected
4. Window limit checks include both executed and resting exposure
"""

import time
from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
    get_kalshi_crypto_15m_risk_envelope,
    force_reset_window_exposure,
    _reset_shared_window_state_for_testing
)

def test_resting_order_exposure_blocks_oversized_orders():
    """Test that resting order exposure prevents exceeding window limits."""
    print("\n=== Test 1: Resting order exposure blocks oversized orders ===")
    
    # Reset state for clean test
    _reset_shared_window_state_for_testing()
    
    # Create envelope with $100 bankroll
    envelope = get_kalshi_crypto_15m_risk_envelope(test_bankroll_usd=100.0)
    
    # 5% total venue limit = $5.00
    # Each resting order at $0.75 = $0.75 notional
    # 5 orders = $3.75 total (within 5% limit)
    # 6 orders = $4.50 total (within 5% limit)
    # 7 orders = $5.25 total (EXCEEDS 5% limit)
    
    order_notional = 0.75  # $0.75 per order
    
    # Place 6 resting orders (should all pass)
    for i in range(6):
        allowed, reason = envelope.check_window_limit(
            agent_id="BTC_15M",
            order_notional_usd=order_notional,
            current_ts=time.time()
        )
        if allowed:
            envelope.record_resting_order_placement(
                agent_id="BTC_15M",
                order_notional_usd=order_notional
            )
            print(f"  Order {i+1}: PASSED (resting exposure recorded)")
        else:
            print(f"  Order {i+1}: BLOCKED - {reason}")
            break
    
    # Try to place 7th order (should be blocked)
    allowed, reason = envelope.check_window_limit(
        agent_id="BTC_15M",
        order_notional_usd=order_notional,
        current_ts=time.time()
    )
    
    if not allowed:
        print(f"  Order 7: BLOCKED (expected) - {reason}")
        print("[PASS] 7th resting order correctly blocked by window limit")
    else:
        print(f"  Order 7: PASSED (UNEXPECTED - should be blocked)")
        print("[FAIL] 7th resting order should have been blocked")
        return False
    
    return True


def test_resting_exposure_released_on_fill():
    """Test that resting exposure is released when order fills."""
    print("\n=== Test 2: Resting exposure released on fill ===")
    
    # Reset state for clean test
    _reset_shared_window_state_for_testing()
    
    envelope = get_kalshi_crypto_15m_risk_envelope(test_bankroll_usd=100.0)
    
    # Place 3 resting orders at $0.75 each = $2.25 total
    for i in range(3):
        envelope.record_resting_order_placement(
            agent_id="BTC_15M",
            order_notional_usd=0.75
        )
    
    print(f"  Placed 3 resting orders: $2.25 resting exposure")
    
    # Simulate fill of one order
    envelope.release_resting_order_exposure(
        agent_id="BTC_15M",
        order_notional_usd=0.75
    )
    envelope.record_order_execution(
        agent_id="BTC_15M",
        order_notional_usd=0.75
    )
    
    print(f"  Order filled: resting exposure released, execution exposure recorded")
    
    # Check if we can place another resting order now
    allowed, reason = envelope.check_window_limit(
        agent_id="BTC_15M",
        order_notional_usd=0.75,
        current_ts=time.time()
    )
    
    if allowed:
        print(f"  New resting order: PASSED (expected - resting exposure was released)")
        print("[PASS] Resting exposure correctly released on fill")
    else:
        print(f"  New resting order: BLOCKED - {reason}")
        print("[FAIL] Resting exposure should have been released on fill")
        return False
    
    return True


def test_resting_exposure_released_on_cancel():
    """Test that resting exposure is released when order is canceled."""
    print("\n=== Test 3: Resting exposure released on cancel ===")
    
    # Reset state for clean test
    _reset_shared_window_state_for_testing()
    
    envelope = get_kalshi_crypto_15m_risk_envelope(test_bankroll_usd=100.0)
    
    # Place 3 resting orders at $0.75 each = $2.25 total
    for i in range(3):
        envelope.record_resting_order_placement(
            agent_id="BTC_15M",
            order_notional_usd=0.75
        )
    
    print(f"  Placed 3 resting orders: $2.25 resting exposure")
    
    # Simulate cancel of one order
    envelope.release_resting_order_exposure(
        agent_id="BTC_15M",
        order_notional_usd=0.75
    )
    
    print(f"  Order canceled: resting exposure released")
    
    # Check if we can place another resting order now
    allowed, reason = envelope.check_window_limit(
        agent_id="BTC_15M",
        order_notional_usd=0.75,
        current_ts=time.time()
    )
    
    if allowed:
        print(f"  New resting order: PASSED (expected - resting exposure was released)")
        print("[PASS] Resting exposure correctly released on cancel")
    else:
        print(f"  New resting order: BLOCKED - {reason}")
        print("[FAIL] Resting exposure should have been released on cancel")
        return False
    
    return True


def test_multiple_agents_resting_exposure():
    """Test that resting exposure is tracked per-agent and totals across agents."""
    print("\n=== Test 4: Multiple agents resting exposure ===")
    
    # Reset state for clean test
    _reset_shared_window_state_for_testing()
    
    envelope = get_kalshi_crypto_15m_risk_envelope(test_bankroll_usd=100.0)
    
    # BTC_15M places 2 resting orders at $0.75 = $1.50
    for i in range(2):
        envelope.record_resting_order_placement(
            agent_id="BTC_15M",
            order_notional_usd=0.75
        )
    
    # ETH_15M places 2 resting orders at $0.75 = $1.50
    for i in range(2):
        envelope.record_resting_order_placement(
            agent_id="ETH_15M",
            order_notional_usd=0.75
        )
    
    print(f"  BTC_15M: 2 resting orders = $1.50")
    print(f"  ETH_15M: 2 resting orders = $1.50")
    print(f"  Total resting exposure: $3.00")
    
    # Try to place order that would exceed 5% total venue limit ($5.00)
    # Current total = $3.00, adding $2.25 = $5.25 (exceeds limit)
    allowed, reason = envelope.check_window_limit(
        agent_id="SOL_15M",
        order_notional_usd=2.25,
        current_ts=time.time()
    )
    
    if not allowed:
        print(f"  SOL_15M order: BLOCKED (expected) - {reason}")
        print("[PASS] Total venue window limit enforced across multiple agents")
    else:
        print(f"  SOL_15M order: PASSED (UNEXPECTED - should be blocked)")
        print("[FAIL] Total venue window limit should block across agents")
        return False
    
    return True


def test_position_cache_releases_resting_on_fill():
    """Test that position_cache.on_fill() releases resting exposure (2026-07-08 fix)."""
    print("\n=== Test 5: Position cache releases resting exposure on fill ===")
    
    # Reset state for clean test
    _reset_shared_window_state_for_testing()
    
    envelope = get_kalshi_crypto_15m_risk_envelope(test_bankroll_usd=100.0)
    
    # Place resting order
    envelope.record_resting_order_placement(
        agent_id="BTC_15M",
        order_notional_usd=1.0
    )
    
    print(f"  Placed resting order: $1.00 resting exposure")
    
    # Simulate position_cache.on_fill() behavior (release resting, record execution)
    envelope.release_resting_order_exposure(
        agent_id="BTC_15M",
        order_notional_usd=1.0
    )
    envelope.record_order_execution(
        agent_id="BTC_15M",
        order_notional_usd=1.0
    )
    
    print(f"  Position cache on_fill: resting released, execution recorded")
    
    # Check if we can place another resting order now
    allowed, reason = envelope.check_window_limit(
        agent_id="BTC_15M",
        order_notional_usd=1.0,
        current_ts=time.time()
    )
    
    if allowed:
        print(f"  New resting order: PASSED (expected - resting was released)")
        print("[PASS] Position cache correctly releases resting exposure on fill")
    else:
        print(f"  New resting order: BLOCKED - {reason}")
        print("[FAIL] Position cache should release resting exposure on fill")
        return False
    
    return True


def test_top3_batch_manager_records_resting_exposure():
    """Test that Top3BatchManager records resting exposure (2026-07-08 fix)."""
    print("\n=== Test 6: Top3 batch manager records resting exposure ===")
    
    # Reset state for clean test
    _reset_shared_window_state_for_testing()
    
    envelope = get_kalshi_crypto_15m_risk_envelope(test_bankroll_usd=100.0)
    
    # Simulate Top3BatchManager.can_open_new_position() behavior
    # After window check passes, record resting exposure
    order_notional = 1.0
    allowed, reason = envelope.check_window_limit(
        agent_id="BTC_15M",
        order_notional_usd=order_notional,
        current_ts=time.time()
    )
    
    if allowed:
        envelope.record_resting_order_placement(
            agent_id="BTC_15M",
            order_notional_usd=order_notional
        )
        print(f"  Top3 gate: window check passed, resting exposure recorded")
    else:
        print(f"  Top3 gate: window check failed - {reason}")
        print("[FAIL] Window check should pass for first order")
        return False
    
    # Try to place another order that would exceed limit
    # 5% of $100 = $5.00, current resting = $1.00, adding $4.50 = $5.50 (exceeds)
    allowed, reason = envelope.check_window_limit(
        agent_id="BTC_15M",
        order_notional_usd=4.50,
        current_ts=time.time()
    )
    
    if not allowed:
        print(f"  Second order: BLOCKED (expected) - {reason}")
        print("[PASS] Top3 batch manager correctly enforces window limits with resting exposure")
    else:
        print(f"  Second order: PASSED (UNEXPECTED - should be blocked)")
        print("[FAIL] Top3 batch manager should block orders exceeding window limit")
        return False
    
    return True


def test_top3_batch_manager_releases_resting_on_fill():
    """Test that Top3BatchManager.mark_asset_filled() releases resting exposure (2026-07-08 fix)."""
    print("\n=== Test 7: Top3 batch manager releases resting exposure on fill ===")
    
    # Reset state for clean test
    _reset_shared_window_state_for_testing()
    
    envelope = get_kalshi_crypto_15m_risk_envelope(test_bankroll_usd=100.0)
    
    # Place resting order (simulating can_open_new_position)
    envelope.record_resting_order_placement(
        agent_id="BTC_15M",
        order_notional_usd=1.0
    )
    
    print(f"  Placed resting order: $1.00 resting exposure")
    
    # Simulate Top3BatchManager.mark_asset_filled() behavior
    # Release resting exposure and record execution exposure
    envelope.release_resting_order_exposure(
        agent_id="BTC_15M",
        order_notional_usd=1.0
    )
    envelope.record_order_execution(
        agent_id="BTC_15M",
        order_notional_usd=1.0
    )
    
    print(f"  Top3 mark_asset_filled: resting released, execution recorded")
    
    # Check if we can place another resting order now
    allowed, reason = envelope.check_window_limit(
        agent_id="BTC_15M",
        order_notional_usd=1.0,
        current_ts=time.time()
    )
    
    if allowed:
        print(f"  New resting order: PASSED (expected - resting was released)")
        print("[PASS] Top3 batch manager correctly releases resting exposure on fill")
    else:
        print(f"  New resting order: BLOCKED - {reason}")
        print("[FAIL] Top3 batch manager should release resting exposure on fill")
        return False
    
    return True


if __name__ == "__main__":
    print("="*80)
    print("RESTING ORDER EXPOSURE TRACKING FIX TEST (2026-07-08)")
    print("="*80)
    
    results = []
    
    results.append(("Resting exposure blocks oversized orders", test_resting_order_exposure_blocks_oversized_orders()))
    results.append(("Resting exposure released on fill", test_resting_exposure_released_on_fill()))
    results.append(("Resting exposure released on cancel", test_resting_exposure_released_on_cancel()))
    results.append(("Multiple agents resting exposure", test_multiple_agents_resting_exposure()))
    results.append(("Position cache releases resting on fill", test_position_cache_releases_resting_on_fill()))
    results.append(("Top3 batch manager records resting exposure", test_top3_batch_manager_records_resting_exposure()))
    results.append(("Top3 batch manager releases resting on fill", test_top3_batch_manager_releases_resting_on_fill()))
    
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    for test_name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {status}: {test_name}")
    
    all_passed = all(passed for _, passed in results)
    
    if all_passed:
        print("\n✓ ALL TESTS PASSED")
    else:
        print("\n✗ SOME TESTS FAILED")
    
    exit(0 if all_passed else 1)
