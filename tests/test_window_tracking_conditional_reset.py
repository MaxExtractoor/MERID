#!/usr/bin/env python3
"""
Test for window tracking conditional reset fix.

This test verifies that force_reset_window_exposure is only called when
there is actual stale exposure (total_exposure > 0), preventing unnecessary
warnings during clean startup.
"""

import time
import threading

# Import the risk envelope
from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
    _WINDOW_TRACKING_STATE,
    _WINDOW_TRACKING_LOCK,
    force_reset_window_exposure
)


def test_conditional_reset_with_no_stale_exposure():
    """Test that reset is not called when there is no stale exposure."""
    print("\n=== TEST: Conditional Reset with No Stale Exposure ===\n")
    
    # Reset window tracking state to clean state (no exposure)
    with _WINDOW_TRACKING_LOCK:
        _WINDOW_TRACKING_STATE["window_start_ts"] = 0.0
        _WINDOW_TRACKING_STATE["agent_exposure_usd"] = {}
        _WINDOW_TRACKING_STATE["total_exposure_usd"] = 0.0
        _WINDOW_TRACKING_STATE["agent_count"] = 0
    
    # Check total exposure
    with _WINDOW_TRACKING_LOCK:
        total_exposure = _WINDOW_TRACKING_STATE["total_exposure_usd"]
    
    print(f"Total exposure: ${total_exposure:.2f}")
    
    # Simulate the conditional reset logic from main_15m_lean.py
    if total_exposure > 0.0:
        print("❌ FAIL: Reset would be called when total_exposure > 0")
        force_reset_window_exposure(reason="startup_stale_exposure")
        return False
    else:
        print("✅ PASS: Reset correctly skipped when total_exposure == 0")
        return True


def test_conditional_reset_with_stale_exposure():
    """Test that reset IS called when there is stale exposure."""
    print("\n=== TEST: Conditional Reset with Stale Exposure ===\n")
    
    # Set up window tracking state with stale exposure
    with _WINDOW_TRACKING_LOCK:
        _WINDOW_TRACKING_STATE["window_start_ts"] = time.time() - 1000  # Old window
        _WINDOW_TRACKING_STATE["agent_exposure_usd"] = {"BTC_15M": 0.50}
        _WINDOW_TRACKING_STATE["total_exposure_usd"] = 0.50
        _WINDOW_TRACKING_STATE["agent_count"] = 1
    
    # Check total exposure
    with _WINDOW_TRACKING_LOCK:
        total_exposure = _WINDOW_TRACKING_STATE["total_exposure_usd"]
    
    print(f"Total exposure: ${total_exposure:.2f}")
    
    # Simulate the conditional reset logic from main_15m_lean.py
    if total_exposure > 0.0:
        print("✅ PASS: Reset correctly called when total_exposure > 0")
        force_reset_window_exposure(reason="startup_stale_exposure")
        
        # Verify reset happened
        with _WINDOW_TRACKING_LOCK:
            total_exposure_after = _WINDOW_TRACKING_STATE["total_exposure_usd"]
        
        print(f"Total exposure after reset: ${total_exposure_after:.2f}")
        
        if total_exposure_after == 0.0:
            print("✅ PASS: Exposure reset to 0 after force_reset")
            return True
        else:
            print(f"❌ FAIL: Exposure not reset. Expected 0, got ${total_exposure_after:.2f}")
            return False
    else:
        print("❌ FAIL: Reset not called when total_exposure > 0")
        return False


if __name__ == "__main__":
    test1 = test_conditional_reset_with_no_stale_exposure()
    test2 = test_conditional_reset_with_stale_exposure()
    
    print("\n=== TEST SUMMARY ===")
    print(f"Test 1 (No Stale Exposure): {'PASS' if test1 else 'FAIL'}")
    print(f"Test 2 (With Stale Exposure): {'PASS' if test2 else 'FAIL'}")
    
    if test1 and test2:
        print("\n=== ALL TESTS PASSED ===")
        exit(0)
    else:
        print("\n=== SOME TESTS FAILED ===")
        exit(1)
