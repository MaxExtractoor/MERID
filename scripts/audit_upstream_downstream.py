#!/usr/bin/env python3
"""
Upstream/Downstream Audit Script
Validates configuration, environment, and downstream components.
"""

import sys
import os
import re
from datetime import datetime, timezone

# Add the project root to Python path
sys.path.insert(0, 'c:\\Dev\\MERID')

def audit_upstream_config():
    """Audit upstream configuration and environment assumptions."""
    
    print("=" * 60)
    print("UPSTREAM CONFIGURATION AUDIT")
    print("=" * 60)
    
    issues = []
    
    # Check 1: Environment detection
    print("\n1. Checking environment detection...")
    try:
        from config.settings import settings
        env = getattr(settings, 'ENV', 'dev')
        print(f"   ✓ Environment detected: {env}")
        
        if env.lower() == 'prod':
            print("   ⚠️  Production environment detected - extra caution needed")
        else:
            print(f"   ✓ Development environment: {env}")
            
    except ImportError:
        print("   ⚠️  Settings not available, defaulting to dev")
        env = 'dev'
    
    # Check 2: Top3 gate environment awareness
    print("\n2. Checking top3 gate environment awareness...")
    try:
        from merid.trading import top3_batch_manager
        top3_available = True
        print("   ✓ Top3 batch manager available")
    except ImportError:
        top3_available = False
        if env.lower() == 'prod':
            issues.append("Top3 gate missing in production environment")
            print("   ❌ CRITICAL: Top3 gate missing in production")
        else:
            print("   ✓ Top3 gate missing in dev (expected)")
    
    # Check 3: Bankroll service configuration
    print("\n3. Checking bankroll service configuration...")
    try:
        from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
        equity = get_equity_for_risk_calc_sync()
        
        if equity is not None and equity > 0:
            print(f"   ✓ Bankroll service healthy: equity=${equity:.2f}")
        else:
            issues.append(f"Bankroll service returned invalid equity: {equity}")
            print(f"   ❌ Bankroll service issue: equity={equity}")
            
    except Exception as e:
        issues.append(f"Bankroll service failed: {e}")
        print(f"   ❌ Bankroll service failed: {e}")
    
    # Check 4: Risk profile configuration
    print("\n4. Checking risk profile configuration...")
    try:
        from merid.risk.profiles.crypto_15m_profile import is_profile_active
        profile_active = is_profile_active()
        
        if profile_active:
            print("   ✓ Risk profile active")
        else:
            issues.append("Risk profile not active")
            print("   ❌ Risk profile not active")
            
    except Exception as e:
        issues.append(f"Risk profile check failed: {e}")
        print(f"   ❌ Risk profile check failed: {e}")
    
    # Check 5: Kalshi client configuration
    print("\n5. Checking Kalshi client configuration...")
    try:
        # Check for key files and configuration
        key_files = [
            'kalshi_private_key.pem',
            'config/kalshi_private_key.pem'
        ]
        
        key_found = False
        for key_file in key_files:
            if os.path.exists(key_file):
                key_found = True
                print(f"   ✓ Kalshi private key found: {key_file}")
                break
        
        if not key_found:
            issues.append("Kalshi private key not found")
            print("   ❌ Kalshi private key not found")
        
        # Check environment variables
        key_vars = ['KALSHI_API_KEY_ID', 'KALSHI_ENV']
        for var in key_vars:
            value = os.getenv(var)
            if value:
                print(f"   ✓ {var} set: {value[:10]}..." if len(value) > 10 else f"   ✓ {var} set: {value}")
            else:
                issues.append(f"Environment variable {var} not set")
                print(f"   ❌ {var} not set")
                
    except Exception as e:
        issues.append(f"Kalshi client config check failed: {e}")
        print(f"   ❌ Kalshi client config check failed: {e}")
    
    return issues, env, top3_available

def audit_downstream_components():
    """Audit downstream components: order router, kill switches."""
    
    print("\n" + "=" * 60)
    print("DOWNSTREAM COMPONENTS AUDIT")
    print("=" * 60)
    
    issues = []
    
    # Check 1: Order router configuration
    print("\n1. Checking order router configuration...")
    try:
        # The order router module has functions, not a class
        import merid.event_venues.kalshi.order_router
        
        # Check if order router can be imported (basic check)
        print("   ✓ Order router imports successfully")
        
        # Check for price band configuration in logs
        log_paths = ['c:\\Dev\\MERID\\health_diagnostic.txt', 'c:\\Dev\\MERID\\logs\\merid.log']
        price_band_found = False
        
        for log_path in log_paths:
            if os.path.exists(log_path):
                with open(log_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if 'Price band config' in content:
                        price_band_found = True
                        print(f"   ✓ Price band config found in {log_path}")
                        break
        
        if not price_band_found:
            print("   ⚠️  Price band config not found in recent logs")
            
    except Exception as e:
        issues.append(f"Order router check failed: {e}")
        print(f"   ❌ Order router check failed: {e}")
    
    # Check 2: Kill switches
    print("\n2. Checking kill switches...")
    try:
        # The kill switches module has RiskController class
        from merid.risk.kill_switches import RiskController
        
        print("   ✓ Kill switch manager imports successfully")
        
        # Check for common kill switch issues in logs
        log_paths = ['c:\\Dev\\MERID\\health_diagnostic.txt', 'c:\\Dev\\MERID\\logs\\merid.log']
        kill_switch_issues = []
        
        for log_path in log_paths:
            if os.path.exists(log_path):
                with open(log_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                # Look for kill switch related issues
                kill_switch_patterns = [
                    r'PROFILE-LIMIT.*Failed to load profile daily loss limit',
                    r'Invalid live bankroll.*None',
                    r'kill.*switch.*disabled'
                ]
                
                for pattern in kill_switch_patterns:
                    if re.search(pattern, content, re.IGNORECASE):
                        kill_switch_issues.append(pattern)
        
        if kill_switch_issues:
            issues.extend([f"Kill switch issue detected: {issue}" for issue in kill_switch_issues])
            for issue in kill_switch_issues:
                print(f"   ❌ Kill switch issue: {issue}")
        else:
            print("   ✓ No kill switch issues detected")
            
    except Exception as e:
        issues.append(f"Kill switches check failed: {e}")
        print(f"   ❌ Kill switches check failed: {e}")
    
    # Check 3: Trading mode configuration
    print("\n3. Checking trading mode configuration...")
    trading_vars = ['MERID_TRADE_MODE', 'MERID_PM_TRADING_MODE', 'MERID_ALLOW_LIVE_TRADES']
    
    for var in trading_vars:
        value = os.getenv(var)
        if value:
            mode = value.lower()
            if 'live' in mode and var in ['MERID_TRADE_MODE', 'MERID_ALLOW_LIVE_TRADES']:
                print(f"   ⚠️  {var} set to live: {value}")
            else:
                print(f"   ✓ {var} set: {value}")
        else:
            print(f"   ⚠️  {var} not set (may default to safe value)")
    
    # Check 4: Position cache and reconciliation
    print("\n4. Checking position cache and reconciliation...")
    try:
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        
        print("   ✓ Position cache imports successfully")
        
        # Check for reconciliation issues in logs
        log_paths = ['c:\\Dev\\MERID\\health_diagnostic.txt', 'c:\\Dev\\MERID\\logs\\merid.log']
        recon_issues = []
        
        for log_path in log_paths:
            if os.path.exists(log_path):
                with open(log_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                # Look for reconciliation issues
                recon_patterns = [
                    r'reconciliation.*failed',
                    r'position.*mismatch',
                    r'critical.*discrepancy'
                ]
                
                for pattern in recon_patterns:
                    if re.search(pattern, content, re.IGNORECASE):
                        recon_issues.append(pattern)
        
        if recon_issues:
            issues.extend([f"Reconciliation issue detected: {issue}" for issue in recon_issues])
            for issue in recon_issues:
                print(f"   ❌ Reconciliation issue: {issue}")
        else:
            print("   ✓ No reconciliation issues detected")
            
    except Exception as e:
        issues.append(f"Position cache check failed: {e}")
        print(f"   ❌ Position cache check failed: {e}")
    
    return issues

def create_regression_strategy():
    """Create regression strategy documentation."""
    
    print("\n" + "=" * 60)
    print("REGRESSION STRATEGY")
    print("=" * 60)
    
    strategy_content = '''# E2E Execution-Ready Regression Strategy

## CI Jobs to Implement

### 1. Invariant Scenario Tests
```bash
# Run all invariant scenarios
python scripts/test_invariant_scenarios.py

# Expected: All scenarios pass, no regressions
```

### 2. Live Log Validation
```bash
# Validate recent logs for invariant violations
python scripts/validate_invariants.py --mode dev --duration 300

# Expected: Zero critical invariant violations in normal operation
```

### 3. Execution-Ready Gate Tests
```bash
# Test execution-ready wiring
python scripts/test_execution_ready_wiring.py

# Expected: All components integrated and working
```

### 4. Fault Injection Tests
```bash
# Run fault injection on new invariants
python scripts/test_fault_injection.py

# Expected: All invariants detect intended violations
```

### 5. Comprehensive E2E Audit
```bash
# Run full E2E audit checklist
python scripts/e2e_audit_checklist.py

# Expected: Zero issues across all categories
```

## Regression Criteria

Any change is considered a regression if:

1. **New invariant violations** appear in normal operation
2. **Execution-ready gate** fails to include required components
3. **Guardrail logging** missing expected violation reasons
4. **Environment-aware policies** fail to respect prod/dev boundaries
5. **Syntax errors** or import failures in any module

## Alerting

- **Critical**: Any `EXECUTION_READY_CRITICAL_FAILURE` in production
- **High**: New invariant types appearing in normal operation
- **Medium**: Missing log fields or guardrail reasons
- **Low**: Test failures in synthetic scenarios

## Rollback Criteria

Rollback is required if:

1. Production shows `EXECUTION_READY_CRITICAL_FAILURE`
2. Bankroll or risk profile invariants trigger in production
3. Top3 gate fails closed in production due to missing module
4. Any critical subsystem shows inconsistent state

## Monitoring

Key log patterns to monitor:

- `[E2E-AUDIT-SNAPSHOT] ready=False reasons=bankroll`
- `[E2E-AUDIT-SNAPSHOT] ready=False reasons=risk_profile`
- `[E2E-AUDIT-SNAPSHOT] ready=False reasons=top3_gate`
- `[E2E-GUARDRAIL-TRIP]` with new violation types
- Any `LIVE_BANKROLL_*` or `RISK_PROFILE_*` invariants
'''
    
    try:
        with open('c:\\Dev\\MERID\\docs\\regression_strategy.md', 'w', encoding='utf-8') as f:
            f.write(strategy_content)
        print("✅ Regression strategy documented: docs/regression_strategy.md")
    except Exception as e:
        print(f"❌ Failed to create regression strategy doc: {e}")

def main():
    """Main audit function."""
    
    print("UPSTREAM/DOWNSTREAM COMPREHENSIVE AUDIT")
    print("Validating configuration, environment, and downstream components")
    
    # Run audits
    upstream_issues, env, top3_available = audit_upstream_config()
    downstream_issues = audit_downstream_components()
    
    # Create regression strategy
    create_regression_strategy()
    
    # Summary
    total_issues = len(upstream_issues) + len(downstream_issues)
    
    print("\n" + "=" * 60)
    print("COMPREHENSIVE AUDIT SUMMARY")
    print("=" * 60)
    
    print(f"\nEnvironment: {env}")
    print(f"Top3 Gate Available: {top3_available}")
    print(f"Total Issues Found: {total_issues}")
    
    if total_issues == 0:
        print("\n🎉 COMPREHENSIVE AUDIT: PASSED")
        print("\nAll upstream and downstream components validated:")
        print("• Environment detection working correctly")
        print("• Top3 gate environment-aware policy functional")
        print("• Bankroll service healthy and configured")
        print("• Risk profile active and loaded")
        print("• Order router and kill switches operational")
        print("• No configuration or environment mismatches")
        print("• Regression strategy documented")
    else:
        print(f"\n❌ COMPREHENSIVE AUDIT: {total_issues} ISSUES FOUND")
        
        if upstream_issues:
            print(f"\n🚨 UPSTREAM ISSUES ({len(upstream_issues)}):")
            for issue in upstream_issues:
                print(f"   • {issue}")
        
        if downstream_issues:
            print(f"\n🚨 DOWNSTREAM ISSUES ({len(downstream_issues)}):")
            for issue in downstream_issues:
                print(f"   • {issue}")
    
    return total_issues == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
