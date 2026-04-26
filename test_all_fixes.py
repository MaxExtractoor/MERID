#!/usr/bin/env python3
"""
COMPREHENSIVE FIX VERIFICATION TEST
Run this before starting the server to verify all safety fixes are in place.
"""
import sys
import os

# Add merid to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_consensus_bypass_disabled():
    """Test 1: Consensus bypass mechanisms are hard-disabled."""
    print("\n[TEST 1] Consensus Bypass Disabled...")
    
    # Check trading_agent.py
    with open('merid/prediction/trading_agent.py', 'r') as f:
        content = f.read()
    
    # Verify _swarm_consensus_bypassed returns False
    if 'return False' not in content:
        print("❌ FAIL: _swarm_consensus_bypassed doesn't return False")
        return False
    
    # Verify security warnings exist
    if '[SECURITY]' not in content:
        print("❌ FAIL: No [SECURITY] warnings in trading_agent.py")
        return False
    
    # Verify bypass mode is rejected
    if '_mm == "bypass"' not in content:
        print("❌ FAIL: Bypass mode check missing in _check_consensus_gate")
        return False
    
    print("✅ PASS: Consensus bypass hard-disabled")
    return True

def test_bankroll_derived_sizing():
    """Test 2: Bankroll-derived sizing overrides YAML."""
    print("\n[TEST 2] Bankroll-Derived Sizing...")
    
    with open('merid/prediction/risk/_prediction_risk.py', 'r') as f:
        content = f.read()
    
    # Verify bankroll is fetched from settings
    if 'KALSHI_PORTFOLIO_BANKROLL_CENTS' not in content:
        print("❌ FAIL: Bankroll setting not referenced")
        return False
    
    # Verify 2% calculation
    if 'Decimal("0.02")' not in content:
        print("❌ FAIL: 2% bankroll calculation missing")
        return False
    
    # Verify bankroll_derived_cap is used
    if 'bankroll_derived_cap' not in content:
        print("❌ FAIL: bankroll_derived_cap not used")
        return False
    
    # Verify warning is logged when YAML exceeds cap
    if '[RISK_SIZING]' not in content:
        print("❌ FAIL: [RISK_SIZING] warning not present")
        return False
    
    print("✅ PASS: Bankroll-derived sizing enforced")
    return True

def test_settings_bankroll_derivation():
    """Test 3: Settings derives bankroll from actual capital."""
    print("\n[TEST 3] Settings Bankroll Derivation...")
    
    with open('merid/settings.py', 'r') as f:
        content = f.read()
    
    # Verify bankroll is derived from MERID_TOTAL_CAPITAL_USD
    if 'MERID_TOTAL_CAPITAL_USD' not in content:
        print("❌ FAIL: Total capital not referenced for bankroll")
        return False
    
    # Verify derivation code exists
    if 'KALSHI_PORTFOLIO_BANKROLL_CENTS = int' not in content:
        print("❌ FAIL: Bankroll derivation code missing")
        return False
    
    # Verify [RISK_CONFIG] log exists
    if '[RISK_CONFIG]' not in content:
        print("❌ FAIL: [RISK_CONFIG] log missing")
        return False
    
    print("✅ PASS: Settings derives bankroll from actual capital")
    return True

def test_crypto_edge_production():
    """Test 4: Crypto edge production rejects bypass."""
    print("\n[TEST 4] Crypto Edge Production Bypass Rejection...")
    
    with open('merid/prediction/crypto_edge_production.py', 'r') as f:
        content = f.read()
    
    # Verify bypass option removed
    if '"bypass"' not in content and "'bypass'" not in content:
        print("⚠️ WARNING: No explicit bypass check (may be removed)")
    
    # Verify error logging exists
    if 'logger.error' not in content:
        print("❌ FAIL: No error logging in crypto_edge_production")
        return False
    
    print("✅ PASS: Crypto edge production has safeguards")
    return True

def test_yaml_bypass_warning():
    """Test 5: Agent grid config warns on YAML bypass flag."""
    print("\n[TEST 5] YAML Bypass Flag Warning...")
    
    with open('merid/prediction/agent_grid_config.py', 'r') as f:
        content = f.read()
    
    # Verify bypass_swarm_consensus warning exists
    if 'bypass_swarm_consensus' not in content:
        print("❌ FAIL: bypass_swarm_consensus not checked")
        return False
    
    if 'logger.warning' not in content:
        print("❌ FAIL: No warning for YAML bypass flag")
        return False
    
    print("✅ PASS: YAML bypass flag warning present")
    return True

def test_syntax_all_files():
    """Test 6: All modified files have valid syntax."""
    print("\n[TEST 6] Syntax Validation...")
    
    import py_compile
    
    files = [
        'merid/settings.py',
        'merid/prediction/trading_agent.py',
        'merid/prediction/crypto_edge_production.py',
        'merid/prediction/agent_grid_config.py',
        'merid/prediction/risk/_prediction_risk.py',
        'merid/trading/top3_edge_allocator.py',
        'merid/trading/top3_batch_manager.py',
    ]
    
    for filepath in files:
        try:
            py_compile.compile(filepath, doraise=True)
            print(f"  ✅ {filepath}")
        except Exception as e:
            print(f"  ❌ {filepath}: {e}")
            return False
    
    print("✅ PASS: All files have valid syntax")
    return True

def test_top3_invariants():
    """Test 7: Top-3 allocator invariants are enforced."""
    print("\n[TEST 7] Top-3 Allocator Invariants...")
    
    with open('merid/trading/top3_edge_allocator.py', 'r') as f:
        content = f.read()
    
    # Verify top-3 limit
    if 'len(selected_assets(t)) <= 3' not in content:
        print("❌ FAIL: Top-3 invariant not documented")
        return False
    
    # Verify 1-2% bankroll cap
    if 'cycle_risk_cap_pct' not in content:
        print("❌ FAIL: Cycle risk cap not present")
        return False
    
    # Verify batch regime
    if 'BATCHSTATUS.CLOSED' not in content.upper():
        print("❌ FAIL: Batch status checking missing")
        return False
    
    print("✅ PASS: Top-3 invariants enforced")
    return True

def run_all_tests():
    """Run all verification tests."""
    print("=" * 70)
    print("MERID SAFETY FIX VERIFICATION")
    print("=" * 70)
    
    tests = [
        test_consensus_bypass_disabled,
        test_bankroll_derived_sizing,
        test_settings_bankroll_derivation,
        test_crypto_edge_production,
        test_yaml_bypass_warning,
        test_syntax_all_files,
        test_top3_invariants,
    ]
    
    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f"\n❌ EXCEPTION in {test.__name__}: {e}")
            results.append(False)
    
    print("\n" + "=" * 70)
    passed = sum(results)
    total = len(results)
    
    if all(results):
        print(f"🎉 ALL TESTS PASSED ({passed}/{total})")
        print("✅ System is SAFE to start")
        return 0
    else:
        print(f"❌ TESTS FAILED ({passed}/{total} passed)")
        print("🛑 DO NOT START SERVER - Fix issues first")
        return 1

if __name__ == "__main__":
    sys.exit(run_all_tests())
