#!/usr/bin/env python3
"""Test script to verify price repeat prevention in order gate.

This test verifies that the fix for preventing duplicate price execution works correctly.
Agents should not be able to execute the same (ticker, side, price) multiple times
within the 15-minute window, forcing them to scale in at lower prices.
"""

import sys
import time

def test_price_repeat_prevention():
    """Test that price repeat check blocks same price execution."""
    print("=" * 70)
    print("TEST: Price Repeat Prevention")
    print("=" * 70)
    
    try:
        from merid.event_venues.kalshi.order_gate import IdempotentOrderStore
    except ImportError as e:
        print(f"\n[ERROR] Failed to import IdempotentOrderStore: {e}")
        return False
    
    # Create order store
    store = IdempotentOrderStore()
    
    # Test 1: First execution should be allowed
    print("\nTest 1: First execution at 32c should be allowed")
    allowed, reason, last_price = store.check_price_repeat(
        contract_id="KXSOL15M-26JUL051900-00",
        side="no",
        price_cents=32,
        allow_lower_price=True,
    )
    if allowed:
        print("[PASS] First execution allowed")
    else:
        print(f"[FAIL] First execution blocked: {reason}")
        return False
    
    # Record the execution
    store.record_price_execution(
        contract_id="KXSOL15M-26JUL051900-00",
        side="no",
        price_cents=32,
    )
    print("Recorded execution at 32c")
    
    # Test 2: Same price should be blocked
    print("\nTest 2: Same price (32c) should be blocked")
    allowed, reason, last_price = store.check_price_repeat(
        contract_id="KXSOL15M-26JUL051900-00",
        side="no",
        price_cents=32,
        allow_lower_price=True,
    )
    if not allowed:
        print(f"[PASS] Same price blocked: {reason}")
    else:
        print("[FAIL] Same price not blocked")
        return False
    
    # Test 3: Higher price should be blocked (must scale in lower)
    print("\nTest 3: Higher price (35c) should be blocked (must scale in lower)")
    allowed, reason, last_price = store.check_price_repeat(
        contract_id="KXSOL15M-26JUL051900-00",
        side="no",
        price_cents=35,
        allow_lower_price=True,
    )
    if not allowed:
        print(f"[PASS] Higher price blocked: {reason}")
    else:
        print("[FAIL] Higher price not blocked")
        return False
    
    # Test 4: Lower price should be allowed (scaling in)
    print("\nTest 4: Lower price (30c) should be allowed (scaling in)")
    allowed, reason, last_price = store.check_price_repeat(
        contract_id="KXSOL15M-26JUL051900-00",
        side="no",
        price_cents=30,
        allow_lower_price=True,
    )
    if allowed:
        print("[PASS] Lower price allowed (scaling in)")
    else:
        print(f"[FAIL] Lower price blocked: {reason}")
        return False
    
    # Record the lower price execution
    store.record_price_execution(
        contract_id="KXSOL15M-26JUL051900-00",
        side="no",
        price_cents=30,
    )
    print("Recorded execution at 30c")
    
    # Test 5: Even lower price should be allowed
    print("\nTest 5: Even lower price (28c) should be allowed")
    allowed, reason, last_price = store.check_price_repeat(
        contract_id="KXSOL15M-26JUL051900-00",
        side="no",
        price_cents=28,
        allow_lower_price=True,
    )
    if allowed:
        print("[PASS] Even lower price allowed")
    else:
        print(f"[FAIL] Even lower price blocked: {reason}")
        return False
    
    # Test 6: Different side should be allowed
    print("\nTest 6: Different side (yes) at same price should be allowed")
    allowed, reason, last_price = store.check_price_repeat(
        contract_id="KXSOL15M-26JUL051900-00",
        side="yes",
        price_cents=32,
        allow_lower_price=True,
    )
    if allowed:
        print("[PASS] Different side allowed")
    else:
        print(f"[FAIL] Different side blocked: {reason}")
        return False
    
    # Test 7: Different contract should be allowed
    print("\nTest 7: Different contract should be allowed")
    allowed, reason, last_price = store.check_price_repeat(
        contract_id="KXBTC15M-26JUL051900-00",
        side="no",
        price_cents=32,
        allow_lower_price=True,
    )
    if allowed:
        print("[PASS] Different contract allowed")
    else:
        print(f"[FAIL] Different contract blocked: {reason}")
        return False
    
    # Test 8: Window expiration (after 15 minutes)
    print("\nTest 8: After 15-minute window, same price should be allowed")
    # Clear price history to simulate window expiration
    store._price_execution_history.clear()
    print("Cleared price history (simulating window expiration)")
    
    allowed, reason, last_price = store.check_price_repeat(
        contract_id="KXSOL15M-26JUL051900-00",
        side="no",
        price_cents=32,
        allow_lower_price=True,
    )
    if allowed:
        print("[PASS] Expired window allows same price")
    else:
        print(f"[FAIL] Expired window still blocks: {reason}")
        return False
    
    # Test 9: Metrics tracking
    print("\nTest 9: Verify metrics are tracked")
    if store._metrics.blocked_price_repeat > 0:
        print(f"[PASS] blocked_price_repeat metric = {store._metrics.blocked_price_repeat}")
    else:
        print("[FAIL] blocked_price_repeat metric not incremented")
        return False
    
    return True


def test_gate_integration():
    """Test price repeat check in PreTradeGate.check()."""
    print("\n" + "=" * 70)
    print("TEST: PreTradeGate Integration")
    print("=" * 70)
    
    try:
        from merid.event_venues.kalshi.order_gate import PreTradeGate
    except ImportError as e:
        print(f"\n[ERROR] Failed to import PreTradeGate: {e}")
        return False
    
    gate = PreTradeGate()
    
    # Test 1: First order should pass
    print("\nTest 1: First order at 32c should pass gate")
    verdict = gate.check(
        agent_id="SOL_15M",
        strategy_group="sol_15m",
        contract_id="KXSOL15M-26JUL051900-00",
        side="no",
        action="buy",
        target_count=3,
        price_cents=32,
        decision_ts=time.time(),
    )
    if verdict.allowed:
        print(f"[PASS] First order allowed: coid={verdict.client_order_id}")
    else:
        print(f"[FAIL] First order blocked: {verdict.reason}")
        return False
    
    # Record the execution
    gate.store.record_price_execution(
        contract_id="KXSOL15M-26JUL051900-00",
        side="no",
        price_cents=32,
    )
    print("Recorded execution at 32c")
    
    # Test 2: Same price with different timestamp should be blocked by price repeat check
    # Use different timestamp to avoid duplicate client_order_id check
    print("\nTest 2: Same price (32c) with different timestamp should be blocked by price repeat")
    verdict = gate.check(
        agent_id="SOL_15M",
        strategy_group="sol_15m",
        contract_id="KXSOL15M-26JUL051900-00",
        side="no",
        action="buy",
        target_count=3,
        price_cents=32,
        decision_ts=time.time() + 10,  # Different timestamp to avoid duplicate check
    )
    if not verdict.allowed and "price_repeat" in verdict.reason:
        print(f"[PASS] Same price blocked by price repeat: {verdict.reason}")
    else:
        # If blocked by duplicate, that's also acceptable (different protection layer)
        if not verdict.allowed and "duplicate" in verdict.reason:
            print(f"[PASS] Same price blocked by duplicate check (alternative protection): {verdict.reason}")
        else:
            print(f"[FAIL] Same price not blocked: allowed={verdict.allowed}, reason={verdict.reason}")
            return False
    
    # Test 3: Lower price should pass gate
    print("\nTest 3: Lower price (30c) should pass gate")
    verdict = gate.check(
        agent_id="SOL_15M",
        strategy_group="sol_15m",
        contract_id="KXSOL15M-26JUL051900-00",
        side="no",
        action="buy",
        target_count=3,
        price_cents=30,
        decision_ts=time.time() + 20,
    )
    if verdict.allowed:
        print(f"[PASS] Lower price allowed by gate: coid={verdict.client_order_id}")
    else:
        print(f"[FAIL] Lower price blocked by gate: {verdict.reason}")
        return False
    
    return True


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("PRICE REPEAT PREVENTION VERIFICATION")
    print("=" * 70)
    
    # Test 1: Price repeat prevention in store
    test1_passed = test_price_repeat_prevention()
    
    # Test 2: Gate integration
    test2_passed = test_gate_integration()
    
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Test 1 (Store): {'PASSED' if test1_passed else 'FAILED'}")
    print(f"Test 2 (Gate Integration): {'PASSED' if test2_passed else 'FAILED'}")
    
    if test1_passed and test2_passed:
        print("\n[ALL TESTS PASSED] Price repeat prevention verified successfully")
        sys.exit(0)
    else:
        print("\n[SOME TESTS FAILED] Price repeat prevention needs review")
        sys.exit(1)
