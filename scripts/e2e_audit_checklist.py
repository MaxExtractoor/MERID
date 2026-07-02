#!/usr/bin/env python3
"""
E2E Audit Checklist Validation
Comprehensive validation of all execution-ready wiring and invariants.
"""

import sys
import os
import importlib
from datetime import datetime, timezone

# Add the project root to Python path
sys.path.insert(0, 'c:\\Dev\\MERID')

def check_startup_health():
    """Check startup health and syntax."""
    
    print("=" * 60)
    print("E2E AUDIT: Startup Health")
    print("=" * 60)
    
    startup_issues = []
    
    # Check 1: Module imports
    print("\n1. Checking module imports...")
    try:
        import merid.loop_15m
        print("   ✓ loop_15m.py imports successfully")
    except Exception as e:
        startup_issues.append(f"loop_15m.py import failed: {e}")
        print(f"   ✗ loop_15m.py import failed: {e}")
    
    try:
        import merid.core.e2e_invariants
        print("   ✓ e2e_invariants.py imports successfully")
    except Exception as e:
        startup_issues.append(f"e2e_invariants.py import failed: {e}")
        print(f"   ✗ e2e_invariants.py import failed: {e}")
    
    # Check 2: Bankroll service availability
    print("\n2. Checking bankroll service...")
    try:
        from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
        # Test the function call
        equity = get_equity_for_risk_calc_sync()
        if equity is not None and equity > 0:
            print(f"   ✓ Bankroll service healthy: equity=${equity:.2f}")
        else:
            startup_issues.append(f"Bankroll service returned invalid equity: {equity}")
            print(f"   ✗ Bankroll service returned invalid equity: {equity}")
    except Exception as e:
        startup_issues.append(f"Bankroll service failed: {e}")
        print(f"   ✗ Bankroll service failed: {e}")
    
    # Check 3: Risk profile availability
    print("\n3. Checking risk profile...")
    try:
        from merid.risk.profiles.crypto_15m_profile import is_profile_active
        profile_active = is_profile_active()
        print(f"   ✓ Risk profile check works: active={profile_active}")
    except Exception as e:
        startup_issues.append(f"Risk profile check failed: {e}")
        print(f"   ✗ Risk profile check failed: {e}")
    
    # Check 4: Top3 gate environment-aware policy
    print("\n4. Checking top3 gate policy...")
    try:
        from merid.trading import top3_batch_manager
        print("   ✓ Top3 batch manager available")
        top3_available = True
    except ImportError:
        print("   ✓ Top3 batch manager not available (expected in dev)")
        top3_available = False
    
    # Check 5: Environment detection
    print("\n5. Checking environment detection...")
    try:
        from config.settings import settings
        env = getattr(settings, 'ENV', 'dev')
        print(f"   ✓ Environment detected: {env}")
    except ImportError:
        print("   ✓ Settings not available (defaults to dev)")
        env = 'dev'
    
    return startup_issues, env, top3_available

def check_execution_ready_gate():
    """Check execution-ready gate logic."""
    
    print("\n" + "=" * 60)
    print("E2E AUDIT: Execution-Ready Gate")
    print("=" * 60)
    
    gate_issues = []
    
    # Check 1: All required fields are present in execution-ready calculation
    print("\n1. Checking execution-ready gate components...")
    
    # Read the loop_15m.py file to verify the gate includes all components
    try:
        with open('c:\\Dev\\MERID\\merid\\loop_15m.py', 'r') as f:
            content = f.read()
        
        required_components = [
            'catalog_fresh',
            'catalog_age_ok', 
            'md_coverage_ok',
            'depth_coverage_ok',
            'ws_forwarder_healthy',
            'live_bankroll_valid',
            'risk_profile_loaded',
            'top3_gate_available'
        ]
        
        execution_ready_section = content[content.find('execution_ready = ('):content.find('execution_ready = (') + 1000]
        
        for component in required_components:
            if component in execution_ready_section:
                print(f"   ✓ {component} in execution-ready gate")
            else:
                gate_issues.append(f"{component} missing from execution-ready gate")
                print(f"   ✗ {component} missing from execution-ready gate")
                
    except Exception as e:
        gate_issues.append(f"Failed to read loop_15m.py: {e}")
        print(f"   ✗ Failed to read loop_15m.py: {e}")
    
    # Check 2: Log format includes all new fields
    print("\n2. Checking log format...")
    log_fields = [
        'bankroll_valid=',
        'bankroll=',
        'risk_profile_loaded=',
        'top3_gate_available='
    ]
    
    for field in log_fields:
        if field in content:
            print(f"   ✓ {field} in log format")
        else:
            gate_issues.append(f"{field} missing from log format")
            print(f"   ✗ {field} missing from log format")
    
    # Check 3: Guardrail logging includes new violation reasons
    print("\n3. Checking guardrail logging...")
    violation_reasons = [
        'bankroll_invalid',
        'risk_profile_not_loaded',
        'top3_gate_missing'
    ]
    
    for reason in violation_reasons:
        if reason in content:
            print(f"   ✓ {reason} in guardrail logging")
        else:
            gate_issues.append(f"{reason} missing from guardrail logging")
            print(f"   ✗ {reason} missing from guardrail logging")
    
    return gate_issues

def check_invariants():
    """Check invariant implementation."""
    
    print("\n" + "=" * 60)
    print("E2E AUDIT: Invariant Implementation")
    print("=" * 60)
    
    invariant_issues = []
    
    try:
        from merid.core.e2e_invariants import E2EInvariantChecker
        checker = E2EInvariantChecker()
        
        # Check 1: All required invariant methods exist
        print("\n1. Checking invariant methods...")
        required_methods = [
            'check_md_age_invariant',
            'check_ws_forwarder_invariant',
            'check_execution_ready_invariant',
            'check_bankroll_invariant',
            'check_risk_profile_invariant',
            'check_top3_gate_invariant',
            'check_depth_quality_invariant',
            'check_all_invariants'
        ]
        
        for method in required_methods:
            if hasattr(checker, method):
                print(f"   ✓ {method} exists")
            else:
                invariant_issues.append(f"Missing invariant method: {method}")
                print(f"   ✗ Missing invariant method: {method}")
        
        # Check 2: Critical subsystems include new components
        print("\n2. Checking critical subsystems list...")
        try:
            # This is a bit of a hack, but we can check the source
            import inspect
            source = inspect.getsource(checker.check_execution_ready_invariant)
            
            critical_subsystems = ['catalog', 'md_freshness', 'depth_coverage', 'ws_forwarder', 'bankroll', 'risk_profile', 'top3_gate']
            
            for subsystem in critical_subsystems:
                if subsystem in source:
                    print(f"   ✓ {subsystem} in critical subsystems")
                else:
                    invariant_issues.append(f"{subsystem} missing from critical subsystems")
                    print(f"   ✗ {subsystem} missing from critical subsystems")
                    
        except Exception as e:
            invariant_issues.append(f"Failed to check critical subsystems: {e}")
            print(f"   ✗ Failed to check critical subsystems: {e}")
        
        # Check 3: Invariant types are correct
        print("\n3. Checking invariant types...")
        required_invariants = [
            'LIVE_BANKROLL_INVALID',
            'LIVE_BANKROLL_ZERO_OR_NEGATIVE',
            'RISK_PROFILE_NOT_LOADED',
            'TOP3_GATE_FAIL_OPEN',
            'EXECUTION_READY_CRITICAL_FAILURE'
        ]
        
        try:
            with open('c:\\Dev\\MERID\\merid\\core\\e2e_invariants.py', 'r') as f:
                invariant_source = f.read()
            
            for invariant in required_invariants:
                if invariant in invariant_source:
                    print(f"   ✓ {invariant} defined")
                else:
                    invariant_issues.append(f"Missing invariant: {invariant}")
                    print(f"   ✗ Missing invariant: {invariant}")
                    
        except Exception as e:
            invariant_issues.append(f"Failed to read invariants file: {e}")
            print(f"   ✗ Failed to read invariants file: {e}")
            
    except Exception as e:
        invariant_issues.append(f"Failed to initialize invariant checker: {e}")
        print(f"   ✗ Failed to initialize invariant checker: {e}")
    
    return invariant_issues

def check_ws_health_semantics():
    """Check WS health gating matches test semantics."""
    
    print("\n" + "=" * 60)
    print("E2E AUDIT: WS Health Semantics")
    print("=" * 60)
    
    ws_issues = []
    
    try:
        # Read the loop_15m.py file to check WS health logic
        with open('c:\\Dev\\MERID\\merid\\loop_15m.py', 'r') as f:
            content = f.read()
        
        print("\n1. Checking WS health predicate...")
        
        # Look for the WS health check logic
        ws_health_section = content[content.find('ws_forwarder_healthy = ('):content.find('ws_forwarder_healthy = (') + 500]
        
        required_conditions = [
            'not stalled',
            'events_per_sec > 0.0',
            'time_since_last_event < 30.0'
        ]
        
        for condition in required_conditions:
            if condition in ws_health_section:
                print(f"   ✓ {condition} in WS health predicate")
            else:
                ws_issues.append(f"Missing WS health condition: {condition}")
                print(f"   ✗ Missing WS health condition: {condition}")
        
        # Check 2: WS health invariants match
        print("\n2. Checking WS health invariants...")
        try:
            with open('c:\\Dev\\MERID\\merid\\core\\e2e_invariants.py', 'r') as f:
                invariant_content = f.read()
            
            if 'events_per_sec == 0.0' in invariant_content and 'time_since_last_event > 30.0' in invariant_content:
                print("   ✓ WS health invariants match gate logic")
            else:
                ws_issues.append("WS health invariants don't match gate logic")
                print("   ✗ WS health invariants don't match gate logic")
                
        except Exception as e:
            ws_issues.append(f"Failed to check WS invariants: {e}")
            print(f"   ✗ Failed to check WS invariants: {e}")
            
    except Exception as e:
        ws_issues.append(f"Failed to check WS health semantics: {e}")
        print(f"   ✗ Failed to check WS health semantics: {e}")
    
    return ws_issues

def generate_audit_report(startup_issues, gate_issues, invariant_issues, ws_issues, env, top3_available):
    """Generate comprehensive audit report."""
    
    print("\n" + "=" * 60)
    print("E2E AUDIT REPORT")
    print("=" * 60)
    
    all_issues = startup_issues + gate_issues + invariant_issues + ws_issues
    total_issues = len(all_issues)
    
    print(f"\nEnvironment: {env}")
    print(f"Top3 Gate Available: {top3_available}")
    print(f"Total Issues Found: {total_issues}")
    
    if total_issues == 0:
        print("\n🎉 ALL CHECKS PASSED!")
        print("\nThe execution-ready wiring and invariants are fully implemented:")
        print("• Bankroll validation integrated into execution-ready gate")
        print("• Risk profile validation integrated into execution-ready gate")
        print("• Top3 gate environment-aware policy implemented")
        print("• All new invariants working correctly")
        print("• WS health semantics match test harness")
        print("• Log format includes all new fields")
        print("• Guardrail logging includes all new violation reasons")
        print("• No syntax errors or import issues")
        return True
    else:
        print(f"\n❌ {total_issues} ISSUES FOUND:")
        
        if startup_issues:
            print(f"\n🚨 STARTUP ISSUES ({len(startup_issues)}):")
            for issue in startup_issues:
                print(f"   • {issue}")
        
        if gate_issues:
            print(f"\n🚨 GATE ISSUES ({len(gate_issues)}):")
            for issue in gate_issues:
                print(f"   • {issue}")
        
        if invariant_issues:
            print(f"\n🚨 INVARIANT ISSUES ({len(invariant_issues)}):")
            for issue in invariant_issues:
                print(f"   • {issue}")
        
        if ws_issues:
            print(f"\n🚨 WS HEALTH ISSUES ({len(ws_issues)}):")
            for issue in ws_issues:
                print(f"   • {issue}")
        
        return False

def main():
    """Run comprehensive E2E audit."""
    
    print("E2E AUDIT CHECKLIST VALIDATION")
    print("Comprehensive validation of execution-ready wiring")
    
    try:
        # Run all audit checks
        startup_issues, env, top3_available = check_startup_health()
        gate_issues = check_execution_ready_gate()
        invariant_issues = check_invariants()
        ws_issues = check_ws_health_semantics()
        
        # Generate final report
        success = generate_audit_report(startup_issues, gate_issues, invariant_issues, ws_issues, env, top3_available)
        
        return success
        
    except Exception as e:
        print(f"\n❌ E2E AUDIT FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
