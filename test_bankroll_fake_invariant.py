#!/usr/bin/env python3
"""
Test script to verify bankroll fake value invariant catches fake constants correctly.
This validates that our guardrails work as intended.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from merid.core.e2e_invariants import E2EInvariantChecker, InvariantViolation

def test_fake_bankroll_invariant():
    """Test that fake bankroll values trigger CRITICAL invariants in live profiles."""
    checker = E2EInvariantChecker()
    
    print("=== Testing Bankroll Fake Value Invariant ===")
    
    # Test 1: Fake constants in live profile should trigger violations
    fake_constants = [10000.0, 10000, 1000.0, 1000, 15.80]
    
    for fake_value in fake_constants:
        violation = checker.check_bankroll_fake_value_invariant(
            equity_usd=fake_value,
            source="kalshi",  # Even with legit source, fake value should trigger
            is_live_profile=True
        )
        
        if violation:
            print(f"✅ CORRECTLY caught fake value ${fake_value}: {violation.invariant_name}")
        else:
            print(f"❌ FAILED to catch fake value ${fake_value}")
            return False
    
    # Test 2: Real values should NOT trigger violations
    real_values = [15.51, 100.0, 5000.25, 12345.67]
    
    for real_value in real_values:
        violation = checker.check_bankroll_fake_value_invariant(
            equity_usd=real_value,
            source="kalshi",
            is_live_profile=True
        )
        
        if violation:
            print(f"❌ FALSE POSITIVE for real value ${real_value}: {violation.invariant_name}")
            return False
        else:
            print(f"✅ CORRECTLY allowed real value ${real_value}")
    
    # Test 3: Non-Kalshi sources in live profile should trigger violations
    suspicious_sources = ["config", "settings", "bootstrap", "fallback", "test"]
    
    for source in suspicious_sources:
        violation = checker.check_bankroll_fake_value_invariant(
            equity_usd=15.51,  # Real value but suspicious source
            source=source,
            is_live_profile=True
        )
        
        if violation:
            print(f"✅ CORRECTLY caught suspicious source '{source}': {violation.invariant_name}")
        else:
            print(f"❌ FAILED to catch suspicious source '{source}'")
            return False
    
    # Test 4: Test profiles should allow fake values (but with legit sources)
    violation = checker.check_bankroll_fake_value_invariant(
        equity_usd=10000.0,
        source="test_config",
        is_live_profile=False  # Test profile
    )
    
    if violation:
        print(f"❌ Test profile should allow fake values: {violation.invariant_name}")
        return False
    else:
        print("✅ CORRECTLY allowed fake values in test profile")
    
    print("\n=== All Invariant Tests PASSED ===")
    return True

if __name__ == "__main__":
    success = test_fake_bankroll_invariant()
    sys.exit(0 if success else 1)
