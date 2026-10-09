#!/usr/bin/env python3
"""
Test script for peak bankroll tracking and 3% per-asset window limits.

Scenario from user:
- 2 yes orders at 35c and 62c, 1 no order at 45c = $1.42 exposure
- Bankroll $33.49
- 5% limit = $1.67
- Remaining capacity: $0.25

This test verifies:
1. Peak bankroll is locked in at window start
2. 5% total venue limit uses peak bankroll (not live bankroll)
3. 3% per-asset limit is enforced
4. Orders are rejected when limits are exceeded
"""

import sys
import time

def test_peak_bankroll_tracking():
    """Test that peak bankroll is locked in at window start and used for limit calculations."""
    print("\n=== TEST 1: Peak Bankroll Tracking ===")
    
    try:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
            compute_kalshi_crypto_15m_risk_envelope,
            _reset_shared_window_state_for_testing,
            _WINDOW_TRACKING_STATE
        )
        
        # Reset shared state for clean test
        _reset_shared_window_state_for_testing()
        
        # Initial bankroll: $100 (for easier math)
        initial_bankroll = 100.0
        envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=initial_bankroll)
        
        # 5% of $33.49 = $1.6745 total limit
        expected_5pct_limit = initial_bankroll * 0.05
        print(f"  Initial bankroll: ${initial_bankroll:.2f}")
        print(f"  Expected 5% limit: ${expected_5pct_limit:.2f}")
        
        # Check that peak bankroll is set at window start
        peak_bankroll = _WINDOW_TRACKING_STATE.get("peak_bankroll_usd", 0.0)
        print(f"  Peak bankroll at window start: ${peak_bankroll:.2f}")
        assert peak_bankroll == initial_bankroll, f"Peak bankroll should be ${initial_bankroll:.2f}, got ${peak_bankroll:.2f}"
        
        # Simulate bankroll increase mid-window (should NOT affect 5% limit)
        # Create new envelope with higher bankroll - peak bankroll should remain unchanged
        increased_bankroll = 150.0
        envelope2 = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=increased_bankroll)
        
        # Peak bankroll should still be the initial value (since we're in same window)
        peak_bankroll_after = _WINDOW_TRACKING_STATE.get("peak_bankroll_usd", 0.0)
        print(f"  Bankroll increased to: ${increased_bankroll:.2f}")
        print(f"  Peak bankroll (should remain initial): ${peak_bankroll_after:.2f}")
        assert peak_bankroll_after == initial_bankroll, f"Peak bankroll should remain ${initial_bankroll:.2f}, got ${peak_bankroll_after:.2f}"
        
        # Check window limit - should use peak bankroll ($100), not increased bankroll ($150)
        # 5% of $100 = $5.00, so $5.10 should be blocked
        allowed, reason = envelope2.check_window_limit("BTC_15M", 5.10, time.time(), asset="BTC")
        print(f"  Order for $5.10 (exceeds 5% of ${initial_bankroll:.2f}): allowed={allowed}")
        print(f"  Reason: {reason}")
        assert not allowed, "Order should be blocked by 5% limit using peak bankroll"
        assert "peak_bankroll" in reason, "Reason should mention peak_bankroll"
        
        # Verify the limit calculation used peak bankroll
        # 5% of $100 = $5.00, order is $5.10, so it should be blocked
        # If it used $50.00, 5% would be $2.50, and $5.10 would be blocked anyway
        # But if it used $150.00, 5% would be $7.50, and $5.10 would be allowed
        print(f"  [PASS] Peak bankroll tracking works correctly")
        return True
        
    except Exception as e:
        print(f"  [FAIL] {e}")
        import traceback
        traceback.print_exc()
        return False


def test_user_scenario_5pct_limit():
    """Test the user's specific scenario: $1.42 exposure with $33.49 bankroll."""
    print("\n=== TEST 2: User Scenario - 5% Total Venue Limit ===")
    
    try:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
            compute_kalshi_crypto_15m_risk_envelope,
            _reset_shared_window_state_for_testing
        )
        
        # Reset shared state for clean test
        _reset_shared_window_state_for_testing()
        
        # Bankroll: $33.49
        bankroll = 33.49
        envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=bankroll)
        
        # 5% limit = $1.6745
        limit_5pct = bankroll * 0.05
        print(f"  Bankroll: ${bankroll:.2f}")
        print(f"  5% limit: ${limit_5pct:.2f}")
        
        # Record user's scenario: 1 yes 50c BTC, 1 no 35c ETH, 1 yes 45c SOL, 1 no 13c XRP
        # Total: $0.50 + $0.35 + $0.45 + $0.13 = $1.43
        envelope.record_order_execution("BTC_15M", 0.50, asset="BTC")  # 1 contract @ 50c
        envelope.record_order_execution("ETH_15M", 0.35, asset="ETH")  # 1 contract @ 35c
        envelope.record_order_execution("SOL_15M", 0.45, asset="SOL")  # 1 contract @ 45c
        envelope.record_order_execution("XRP_15M", 0.13, asset="XRP")  # 1 contract @ 13c
        
        total_exposure = envelope.total_window_exposure_usd
        print(f"  Recorded exposure: ${total_exposure:.2f}")
        assert abs(total_exposure - 1.43) < 0.01, f"Exposure should be $1.43, got ${total_exposure:.2f}"
        
        # Remaining capacity: $1.6745 - $1.43 = $0.2445
        remaining = limit_5pct - total_exposure
        print(f"  Remaining capacity: ${remaining:.2f}")
        
        # Test: Order for $0.24 should be allowed
        allowed, reason = envelope.check_window_limit("DOGE_15M", 0.24, time.time(), asset="DOGE")
        print(f"  Order for $0.24: allowed={allowed}")
        if not allowed:
            print(f"  Reason: {reason}")
        assert allowed, f"Order for $0.24 should be allowed (remaining ${remaining:.2f})"
        
        # Test: Order for $0.25 should be blocked
        allowed, reason = envelope.check_window_limit("DOGE_15M", 0.25, time.time(), asset="DOGE")
        print(f"  Order for $0.25: allowed={allowed}")
        print(f"  Reason: {reason}")
        assert not allowed, "Order for $0.25 should be blocked (exceeds remaining capacity)"
        assert "total_venue_window_limit" in reason, "Reason should mention total_venue_window_limit"
        
        print(f"  [PASS] User scenario 5% limit works correctly")
        return True
        
    except Exception as e:
        print(f"  [FAIL] {e}")
        import traceback
        traceback.print_exc()
        return False


def test_per_asset_3pct_limit():
    """Test 3% per-asset window limit."""
    print("\n=== TEST 3: 3% Per-Asset Limit ===")
    
    try:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
            compute_kalshi_crypto_15m_risk_envelope,
            _reset_shared_window_state_for_testing,
            _WINDOW_TRACKING_STATE
        )
        
        # Reset shared state for clean test
        _reset_shared_window_state_for_testing()
        
        # Bankroll: $100 (for easy math)
        bankroll = 100.0
        envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=bankroll)
        
        # 3% per-asset limit = $3.00
        limit_3pct = bankroll * 0.03
        print(f"  Bankroll: ${bankroll:.2f}")
        print(f"  3% per-asset limit: ${limit_3pct:.2f}")
        
        # Record $1.00 exposure for BTC using BTC_15M agent (to avoid hitting per-agent limit)
        envelope.record_order_execution("BTC_15M", 1.00, asset="BTC")
        print(f"  Recorded BTC exposure via BTC_15M: $1.00")
        
        # Record $1.00 exposure for BTC using ETH_15M agent (same asset, different agent)
        # This tests per-asset limit specifically (not per-agent)
        envelope.record_order_execution("ETH_15M", 1.00, asset="BTC")
        print(f"  Recorded BTC exposure via ETH_15M: $1.00")
        
        # Verify asset exposure is tracked
        btc_exposure = _WINDOW_TRACKING_STATE["asset_exposure_usd"].get("BTC", 0.0)
        print(f"  BTC asset exposure in state: ${btc_exposure:.2f}")
        assert btc_exposure == 2.00, f"BTC asset exposure should be $2.00, got ${btc_exposure:.2f}"
        
        # Test: Another BTC order for $1.10 using SOL_15M agent should be blocked by per-asset limit
        # This specifically tests the per-asset limit (not per-agent)
        # $2.00 + $1.10 = $3.10 > $3.00 (3% limit)
        allowed, reason = envelope.check_window_limit("SOL_15M", 1.10, time.time(), asset="BTC")
        print(f"  SOL_15M order for $1.10 on BTC asset: allowed={allowed}")
        print(f"  Reason: {reason}")
        # The order should be blocked by per-asset limit
        assert not allowed, "Order for $1.10 on BTC asset should be blocked (BTC at 3% limit)"
        assert "per_asset_window_limit" in reason, "Should be blocked by per-asset limit"
        
        # Test: ETH order for $2.50 should be allowed (different asset, different agent)
        # Use SOL_15M agent to avoid per-agent limit (ETH_15M already has $1.00 from BTC order)
        # Total exposure would be $2.00 + $2.50 = $4.50 < $5.00 (5% total venue limit)
        allowed, reason = envelope.check_window_limit("SOL_15M", 2.50, time.time(), asset="ETH")
        print(f"  SOL_15M order for $2.50 on ETH asset: allowed={allowed}")
        if not allowed:
            print(f"  Reason: {reason}")
        assert allowed, "ETH order for $2.50 should be allowed (different asset, not at limit)"
        
        # Verify ETH exposure is tracked separately
        eth_exposure = _WINDOW_TRACKING_STATE["asset_exposure_usd"].get("ETH", 0.0)
        print(f"  ETH asset exposure: ${eth_exposure:.2f}")
        
        print(f"  [PASS] 3% per-asset limit works correctly")
        return True
        
    except Exception as e:
        print(f"  [FAIL] {e}")
        import traceback
        traceback.print_exc()
        return False


def test_combined_limits():
    """Test that both per-agent, per-asset, and total venue limits work together."""
    print("\n=== TEST 4: Combined Limits (Per-Agent + Per-Asset + Total Venue) ===")
    
    try:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
            compute_kalshi_crypto_15m_risk_envelope,
            _reset_shared_window_state_for_testing
        )
        
        # Reset shared state for clean test
        _reset_shared_window_state_for_testing()
        
        # Bankroll: $100
        bankroll = 100.0
        envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=bankroll)
        
        # Limits:
        # - 3% per agent = $3.00
        # - 3% per asset = $3.00
        # - 5% total venue = $5.00
        print(f"  Bankroll: ${bankroll:.2f}")
        print(f"  3% per-agent limit: $3.00")
        print(f"  3% per-asset limit: $3.00")
        print(f"  5% total venue limit: $5.00")
        
        # Agent 1 (BTC_15M): $2.00
        envelope.record_order_execution("BTC_15M", 2.00, asset="BTC")
        print(f"  BTC_15M exposure: $2.00")
        
        # Agent 2 (ETH_15M): $2.00
        envelope.record_order_execution("ETH_15M", 2.00, asset="ETH")
        print(f"  ETH_15M exposure: $2.00")
        
        # Total: $4.00 (within 5% limit of $5.00)
        
        # Test: BTC_15M order for $1.50 should be blocked by per-agent limit ($2.00 + $1.50 = $3.50 > $3.00)
        allowed, reason = envelope.check_window_limit("BTC_15M", 1.50, time.time(), asset="BTC")
        print(f"  BTC_15M order for $1.50: allowed={allowed}")
        print(f"  Reason: {reason}")
        assert not allowed, "Should be blocked by per-agent limit"
        assert "per_agent_window_limit" in reason, "Should be blocked by per-agent limit"
        
        # Test: BTC_15M order for $1.00 should be allowed (total $3.00 at per-agent limit)
        allowed, reason = envelope.check_window_limit("BTC_15M", 1.00, time.time(), asset="BTC")
        print(f"  BTC_15M order for $1.00: allowed={allowed}")
        assert allowed, "Should be allowed (at per-agent limit)"
        
        # Record it
        envelope.record_order_execution("BTC_15M", 1.00, asset="BTC")
        
        # Now total exposure: $5.00 (at 5% total venue limit)
        
        # Test: SOL_15M order for $0.50 should be blocked by total venue limit
        allowed, reason = envelope.check_window_limit("SOL_15M", 0.50, time.time(), asset="SOL")
        print(f"  SOL_15M order for $0.50: allowed={allowed}")
        print(f"  Reason: {reason}")
        assert not allowed, "Should be blocked by total venue limit"
        assert "total_venue_window_limit" in reason, "Should be blocked by total venue limit"
        
        print(f"  [PASS] Combined limits work correctly")
        return True
        
    except Exception as e:
        print(f"  [FAIL] {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("Testing Peak Bankroll Tracking and 3% Per-Asset Limits")
    print("=" * 60)
    
    results = []
    results.append(("Peak Bankroll Tracking", test_peak_bankroll_tracking()))
    results.append(("User Scenario 5% Limit", test_user_scenario_5pct_limit()))
    results.append(("3% Per-Asset Limit", test_per_asset_3pct_limit()))
    results.append(("Combined Limits", test_combined_limits()))
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    for name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status}: {name}")
    
    all_passed = all(passed for _, passed in results)
    
    if all_passed:
        print("\n[PASS] All tests passed!")
        sys.exit(0)
    else:
        print("\n[FAIL] Some tests failed!")
        sys.exit(1)
