#!/usr/bin/env python3
"""
Fault injection test script for new execution-ready invariants.
This script deliberately breaks bankroll and risk profile systems to verify
that the new invariants and guardrails work correctly.
"""

import sys
import os
from datetime import datetime, timezone

# Add the project root to Python path
sys.path.insert(0, 'c:\\Dev\\MERID')

def test_bankroll_fault_injection():
    """Test bankroll fault injection scenarios."""
    
    print("=" * 60)
    print("FAULT INJECTION: Bankroll Validation")
    print("=" * 60)
    
    from merid.core.e2e_invariants import E2EInvariantChecker
    checker = E2EInvariantChecker()
    
    # Test 1: Bankroll invalid (None)
    print("\n1. Testing bankroll = None (invalid)...")
    system_state = {
        "execution_ready": False,
        "subsystem_health": {
            "catalog": "HEALTH_GOOD",
            "md_freshness": "HEALTH_GOOD",
            "depth_coverage": "HEALTH_GOOD", 
            "ws_forwarder": "HEALTH_GOOD",
            "bankroll": "HEALTH_ERROR",
            "risk_profile": "HEALTH_GOOD",
            "top3_gate": "HEALTH_GOOD"
        },
        "bankroll": {
            "live_bankroll": 0.0,
            "valid": False,
            "status": "ERROR"
        },
        "risk_profile": {
            "loaded": True,
            "status": "OK"
        },
        "top3_gate": {
            "available": True,
            "status": "OK"
        }
    }
    
    violations = checker.check_all_invariants(system_state)
    bankroll_violations = [v for v in violations if "BANKROLL" in v.invariant_name]
    
    if bankroll_violations:
        print(f"   ✓ Bankroll violations detected: {[v.invariant_name for v in bankroll_violations]}")
    else:
        print("   ✗ No bankroll violations detected")
    
    # Test 2: Bankroll zero/negative
    print("\n2. Testing bankroll = 0.0 (zero)...")
    system_state["bankroll"] = {
        "live_bankroll": 0.0,
        "valid": False,
        "status": "ERROR"  # Should be ERROR for zero bankroll
    }
    system_state["subsystem_health"]["bankroll"] = "HEALTH_ERROR"
    
    violations = checker.check_all_invariants(system_state)
    zero_violations = [v for v in violations if v.invariant_name == "LIVE_BANKROLL_ZERO_OR_NEGATIVE"]
    
    if zero_violations:
        print("   ✓ LIVE_BANKROLL_ZERO_OR_NEGATIVE invariant detected")
    else:
        print("   ✗ LIVE_BANKROLL_ZERO_OR_NEGATIVE invariant not detected")
    
    # Test 3: Bankroll negative
    print("\n3. Testing bankroll = -100.0 (negative)...")
    system_state["bankroll"] = {
        "live_bankroll": -100.0,
        "valid": False,
        "status": "ERROR"
    }
    
    violations = checker.check_all_invariants(system_state)
    negative_violations = [v for v in violations if v.invariant_name == "LIVE_BANKROLL_ZERO_OR_NEGATIVE"]
    
    if negative_violations:
        print("   ✓ LIVE_BANKROLL_ZERO_OR_NEGATIVE invariant detected for negative bankroll")
    else:
        print("   ✗ LIVE_BANKROLL_ZERO_OR_NEGATIVE invariant not detected for negative bankroll")
    
    # Test 4: Bankroll OK but invalid (inconsistent state)
    print("\n4. Testing inconsistent bankroll state (OK status but invalid)...")
    system_state["bankroll"] = {
        "live_bankroll": 0.0,
        "valid": False,
        "status": "OK"  # This should trigger invariant
    }
    system_state["subsystem_health"]["bankroll"] = "HEALTH_GOOD"  # Inconsistent!
    
    violations = checker.check_all_invariants(system_state)
    inconsistent_violations = [v for v in violations if v.invariant_name == "LIVE_BANKROLL_INVALID"]
    
    if inconsistent_violations:
        print("   ✓ LIVE_BANKROLL_INVALID invariant detected for inconsistent state")
    else:
        print("   ✗ LIVE_BANKROLL_INVALID invariant not detected for inconsistent state")

def test_risk_profile_fault_injection():
    """Test risk profile fault injection scenarios."""
    
    print("\n" + "=" * 60)
    print("FAULT INJECTION: Risk Profile Validation")
    print("=" * 60)
    
    from merid.core.e2e_invariants import E2EInvariantChecker
    checker = E2EInvariantChecker()
    
    # Test 1: Risk profile not loaded
    print("\n1. Testing risk profile not loaded...")
    system_state = {
        "execution_ready": False,
        "subsystem_health": {
            "catalog": "HEALTH_GOOD",
            "md_freshness": "HEALTH_GOOD",
            "depth_coverage": "HEALTH_GOOD", 
            "ws_forwarder": "HEALTH_GOOD",
            "bankroll": "HEALTH_GOOD",
            "risk_profile": "HEALTH_ERROR",
            "top3_gate": "HEALTH_GOOD"
        },
        "bankroll": {
            "live_bankroll": 1000.0,
            "valid": True,
            "status": "OK"
        },
        "risk_profile": {
            "loaded": False,
            "status": "ERROR"
        },
        "top3_gate": {
            "available": True,
            "status": "OK"
        }
    }
    
    violations = checker.check_all_invariants(system_state)
    risk_violations = [v for v in violations if v.invariant_name == "RISK_PROFILE_NOT_LOADED"]
    
    if risk_violations:
        print("   ✓ RISK_PROFILE_NOT_LOADED invariant detected")
    else:
        print("   ✗ RISK_PROFILE_NOT_LOADED invariant not detected")
    
    # Test 2: Risk profile OK but not loaded (inconsistent state)
    print("\n2. Testing inconsistent risk profile state (OK status but not loaded)...")
    system_state["risk_profile"] = {
        "loaded": False,
        "status": "OK"  # This should trigger invariant
    }
    system_state["subsystem_health"]["risk_profile"] = "HEALTH_GOOD"  # Inconsistent!
    
    violations = checker.check_all_invariants(system_state)
    inconsistent_risk_violations = [v for v in violations if v.invariant_name == "RISK_PROFILE_NOT_LOADED"]
    
    if inconsistent_risk_violations:
        print("   ✓ RISK_PROFILE_NOT_LOADED invariant detected for inconsistent state")
    else:
        print("   ✗ RISK_PROFILE_NOT_LOADED invariant not detected for inconsistent state")

def test_top3_gate_fault_injection():
    """Test top3 gate fault injection scenarios."""
    
    print("\n" + "=" * 60)
    print("FAULT INJECTION: Top3 Gate Validation")
    print("=" * 60)
    
    from merid.core.e2e_invariants import E2EInvariantChecker
    checker = E2EInvariantChecker()
    
    # Test 1: Top3 gate not available
    print("\n1. Testing top3 gate not available...")
    system_state = {
        "execution_ready": False,
        "subsystem_health": {
            "catalog": "HEALTH_GOOD",
            "md_freshness": "HEALTH_GOOD",
            "depth_coverage": "HEALTH_GOOD", 
            "ws_forwarder": "HEALTH_GOOD",
            "bankroll": "HEALTH_GOOD",
            "risk_profile": "HEALTH_GOOD",
            "top3_gate": "HEALTH_ERROR"
        },
        "bankroll": {
            "live_bankroll": 1000.0,
            "valid": True,
            "status": "OK"
        },
        "risk_profile": {
            "loaded": True,
            "status": "OK"
        },
        "top3_gate": {
            "available": False,
            "status": "ERROR"
        }
    }
    
    violations = checker.check_all_invariants(system_state)
    top3_violations = [v for v in violations if v.invariant_name == "TOP3_GATE_FAIL_OPEN"]
    
    if top3_violations:
        print("   ✓ TOP3_GATE_FAIL_OPEN invariant detected")
    else:
        print("   ✗ TOP3_GATE_FAIL_OPEN invariant not detected")
    
    # Test 2: Top3 gate OK but not available (inconsistent state)
    print("\n2. Testing inconsistent top3 gate state (OK status but not available)...")
    system_state["top3_gate"] = {
        "available": False,
        "status": "OK"  # This should trigger invariant
    }
    system_state["subsystem_health"]["top3_gate"] = "HEALTH_GOOD"  # Inconsistent!
    
    violations = checker.check_all_invariants(system_state)
    inconsistent_top3_violations = [v for v in violations if v.invariant_name == "TOP3_GATE_FAIL_OPEN"]
    
    if inconsistent_top3_violations:
        print("   ✓ TOP3_GATE_FAIL_OPEN invariant detected for inconsistent state")
    else:
        print("   ✗ TOP3_GATE_FAIL_OPEN invariant not detected for inconsistent state")

def test_execution_ready_critical_failure():
    """Test that execution-ready fails when any critical subsystem fails."""
    
    print("\n" + "=" * 60)
    print("FAULT INJECTION: Execution-Ready Critical Failure")
    print("=" * 60)
    
    from merid.core.e2e_invariants import E2EInvariantChecker
    checker = E2EInvariantChecker()
    
    # Test: All subsystems healthy except bankroll
    print("\n1. Testing execution-ready with bankroll failure...")
    system_state = {
        "execution_ready": True,  # This should trigger invariant
        "subsystem_health": {
            "catalog": "HEALTH_GOOD",
            "md_freshness": "HEALTH_GOOD",
            "depth_coverage": "HEALTH_GOOD", 
            "ws_forwarder": "HEALTH_GOOD",
            "bankroll": "HEALTH_ERROR",  # Critical failure
            "risk_profile": "HEALTH_GOOD",
            "top3_gate": "HEALTH_GOOD"
        },
        "bankroll": {
            "live_bankroll": 0.0,
            "valid": False,
            "status": "ERROR"
        },
        "risk_profile": {
            "loaded": True,
            "status": "OK"
        },
        "top3_gate": {
            "available": True,
            "status": "OK"
        }
    }
    
    violations = checker.check_all_invariants(system_state)
    critical_violations = [v for v in violations if v.invariant_name == "EXECUTION_READY_CRITICAL_FAILURE"]
    
    if critical_violations:
        print("   ✓ EXECUTION_READY_CRITICAL_FAILURE invariant detected for bankroll failure")
    else:
        print("   ✗ EXECUTION_READY_CRITICAL_FAILURE invariant not detected for bankroll failure")
    
    # Test: All subsystems healthy except risk profile
    print("\n2. Testing execution-ready with risk profile failure...")
    system_state["execution_ready"] = True
    system_state["subsystem_health"]["bankroll"] = "HEALTH_GOOD"
    system_state["subsystem_health"]["risk_profile"] = "HEALTH_ERROR"  # Critical failure
    system_state["bankroll"] = {
        "live_bankroll": 1000.0,
        "valid": True,
        "status": "OK"
    }
    system_state["risk_profile"] = {
        "loaded": False,
        "status": "ERROR"
    }
    
    violations = checker.check_all_invariants(system_state)
    critical_risk_violations = [v for v in violations if v.invariant_name == "EXECUTION_READY_CRITICAL_FAILURE"]
    
    if critical_risk_violations:
        print("   ✓ EXECUTION_READY_CRITICAL_FAILURE invariant detected for risk profile failure")
    else:
        print("   ✗ EXECUTION_READY_CRITICAL_FAILURE invariant not detected for risk profile failure")

def main():
    """Run all fault injection tests."""
    
    try:
        print("FAULT INJECTION TEST SUITE")
        print("Testing new execution-ready invariants")
        
        test_bankroll_fault_injection()
        test_risk_profile_fault_injection()
        test_top3_gate_fault_injection()
        test_execution_ready_critical_failure()
        
        print("\n" + "=" * 60)
        print("✅ FAULT INJECTION TESTS COMPLETED")
        print("=" * 60)
        print("\nAll fault injection scenarios tested.")
        print("Check output above for any ✗ markers indicating issues.")
        
        return True
        
    except Exception as e:
        print(f"\n❌ FAULT INJECTION TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
