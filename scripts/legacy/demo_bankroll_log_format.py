#!/usr/bin/env python3
"""
Demo script showing the exact log format for bankroll source fields.

This demonstrates what the logs look like with the new fake bankroll protection
in both normal operation and when fake bankroll is detected.
"""

import os
import sys
import time
from datetime import datetime
from unittest.mock import Mock, patch

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def demo_normal_bankroll_logs():
    """Show log format when bankroll is valid (normal operation)."""
    print("🔍 DEMO: Normal Bankroll Log Format")
    print("=" * 60)
    
    # Simulate the exact log format from loop_15m.py
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Normal operation with real bankroll
    live_bankroll = 3681.25
    live_bankroll_source = "kalshi"
    live_bankroll_valid = True
    fake_bankroll_used = False
    bankroll_source_valid = True
    is_live_profile = True
    
    # Simulate all gate conditions being met
    catalog_fresh = True
    catalog_age_ok = True
    md_coverage_ok = True
    depth_coverage_ok = True
    ws_forwarder_healthy = True
    risk_profile_loaded = True
    top3_gate_available = True
    
    execution_ready = all([
        catalog_fresh, catalog_age_ok, md_coverage_ok, depth_coverage_ok,
        ws_forwarder_healthy, live_bankroll_valid, bankroll_source_valid,
        risk_profile_loaded, top3_gate_available
    ])
    
    print(f"[{timestamp}] [15M-EXECUTION-READY] execution_ready=True")
    print(f"  subsystem_health={{")
    print(f"    'catalog': 'HEALTH_GOOD',")
    print(f"    'md_freshness': 'HEALTH_GOOD',")
    print(f"    'depth_coverage': 'HEALTH_GOOD',")
    print(f"    'ws_forwarder': 'HEALTH_GOOD',")
    print(f"    'bankroll': 'HEALTH_GOOD',")
    print(f"    'risk_profile': 'HEALTH_GOOD',")
    print(f"    'top3_gate': 'HEALTH_GOOD'")
    print(f"  }}")
    print(f"  bankroll={{")
    print(f"    'live_bankroll': {live_bankroll},")
    print(f"    'valid': {live_bankroll_valid},")
    print(f"    'status': 'OK',")
    print(f"    'source': '{live_bankroll_source}',")
    print(f"    'source_valid': {bankroll_source_valid},")
    print(f"    'fake_used': {fake_bankroll_used}")
    print(f"  }}")
    print(f"  is_live_profile: {is_live_profile}")
    print()
    
    # E2E-AUDIT-SNAPSHOT log
    reasons = []
    if not execution_ready:
        reasons.append("execution_not_ready")
    
    print(f"[{timestamp}] [E2E-AUDIT-SNAPSHOT] profile=kalshi_crypto_15m_v2 execution_ready={execution_ready} reasons={{{','.join(reasons) if reasons else 'none'}}}")
    print(f"  bankroll_source={live_bankroll_source} bankroll_source_valid={bankroll_source_valid} fake_bankroll_used={fake_bankroll_used}")
    print()
    
    print("✅ NORMAL OPERATION: All bankroll fields show valid state")

def demo_fake_bankroll_logs():
    """Show log format when fake bankroll is detected."""
    print("\n🚨 DEMO: Fake Bankroll Detection Log Format")
    print("=" * 60)
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Fake bankroll detected
    live_bankroll = 1000.0
    live_bankroll_source = "fallback"
    live_bankroll_valid = True  # Bankroll exists but source is fake
    fake_bankroll_used = True
    bankroll_source_valid = False
    is_live_profile = True
    
    # Other gate conditions might be met, but bankroll blocks execution
    catalog_fresh = True
    catalog_age_ok = True
    md_coverage_ok = True
    depth_coverage_ok = True
    ws_forwarder_healthy = True
    risk_profile_loaded = True
    top3_gate_available = True
    
    execution_ready = all([
        catalog_fresh, catalog_age_ok, md_coverage_ok, depth_coverage_ok,
        ws_forwarder_healthy, live_bankroll_valid, bankroll_source_valid,  # This fails
        risk_profile_loaded, top3_gate_available
    ])
    
    print(f"[{timestamp}] [15M-EXECUTION-DEGRADED] execution_ready=False")
    print(f"  subsystem_health={{")
    print(f"    'catalog': 'HEALTH_GOOD',")
    print(f"    'md_freshness': 'HEALTH_GOOD',")
    print(f"    'depth_coverage': 'HEALTH_GOOD',")
    print(f"    'ws_forwarder': 'HEALTH_GOOD',")
    print(f"    'bankroll': 'HEALTH_ERROR',  # Source invalid")
    print(f"    'risk_profile': 'HEALTH_GOOD',")
    print(f"    'top3_gate': 'HEALTH_GOOD'")
    print(f"  }}")
    print(f"  bankroll={{")
    print(f"    'live_bankroll': {live_bankroll},")
    print(f"    'valid': {live_bankroll_valid},")
    print(f"    'status': 'OK',")
    print(f"    'source': '{live_bankroll_source}',")
    print(f"    'source_valid': {bankroll_source_valid},")
    print(f"    'fake_used': {fake_bankroll_used}")
    print(f"  }}")
    print(f"  is_live_profile: {is_live_profile}")
    print()
    
    # E2E-GUARDRAIL-TRIP log with fake bankroll violation
    print(f"[{timestamp}] [FAKE-BANKROLL-INVARIANT] Fake bankroll source detected in live profile: source=fallback value=1000.00")
    print()
    
    # E2E-AUDIT-SNAPSHOT log
    reasons = ["fake_bankroll_detected"]
    if not execution_ready:
        reasons.append("execution_not_ready")
    
    print(f"[{timestamp}] [E2E-AUDIT-SNAPSHOT] profile=kalshi_crypto_15m_v2 execution_ready={execution_ready} reasons={{{','.join(reasons)}}}")
    print(f"  bankroll_source={live_bankroll_source} bankroll_source_valid={bankroll_source_valid} fake_bankroll_used={fake_bankroll_used}")
    print()
    
    # E2E-GUARDRAIL-TRIP log
    violations = ["FAKE_BANKROLL_SOURCE_USED"]
    print(f"[{timestamp}] [E2E-GUARDRAIL-TRIP] severity=CRITICAL violations={{{','.join(violations)}}}")
    print(f"  bankroll_source={live_bankroll_source} bankroll_source_valid={bankroll_source_valid} fake_bankroll_used={fake_bankroll_used}")
    print()
    
    print("🚨 FAKE BANKROLL DETECTED: All logs show CRITICAL invariant and execution blocked")

def demo_test_profile_logs():
    """Show log format when test profile allows fake bankroll."""
    print("\n🧪 DEMO: Test Profile with Fake Bankroll (Allowed)")
    print("=" * 60)
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Test profile with fake bankroll (allowed)
    live_bankroll = 1000.0
    live_bankroll_source = "fallback"
    live_bankroll_valid = True
    fake_bankroll_used = False  # Not flagged due to test profile
    bankroll_source_valid = False  # Still technically invalid source
    is_live_profile = False
    
    # Other gate conditions
    catalog_fresh = True
    catalog_age_ok = True
    md_coverage_ok = True
    depth_coverage_ok = True
    ws_forwarder_healthy = True
    risk_profile_loaded = True
    top3_gate_available = True
    
    # In test mode, we might allow execution even with fake bankroll
    execution_ready = all([
        catalog_fresh, catalog_age_ok, md_coverage_ok, depth_coverage_ok,
        ws_forwarder_healthy, live_bankroll_valid,  # Bankroll valid
        # bankroll_source_valid might be ignored in test mode
        risk_profile_loaded, top3_gate_available
    ])
    
    print(f"[{timestamp}] [15M-EXECUTION-READY] execution_ready={execution_ready}")
    print(f"  subsystem_health={{")
    print(f"    'catalog': 'HEALTH_GOOD',")
    print(f"    'md_freshness': 'HEALTH_GOOD',")
    print(f"    'depth_coverage': 'HEALTH_GOOD',")
    print(f"    'ws_forwarder': 'HEALTH_GOOD',")
    print(f"    'bankroll': 'HEALTH_GOOD',")
    print(f"    'risk_profile': 'HEALTH_GOOD',")
    print(f"    'top3_gate': 'HEALTH_GOOD'")
    print(f"  }}")
    print(f"  bankroll={{")
    print(f"    'live_bankroll': {live_bankroll},")
    print(f"    'valid': {live_bankroll_valid},")
    print(f"    'status': 'OK',")
    print(f"    'source': '{live_bankroll_source}',")
    print(f"    'source_valid': {bankroll_source_valid},")
    print(f"    'fake_used': {fake_bankroll_used}")
    print(f"  }}")
    print(f"  is_live_profile: {is_live_profile}")
    print()
    
    # E2E-AUDIT-SNAPSHOT log
    reasons = []
    if not execution_ready:
        reasons.append("execution_not_ready")
    
    print(f"[{timestamp}] [E2E-AUDIT-SNAPSHOT] profile=test_profile execution_ready={execution_ready} reasons={{{','.join(reasons) if reasons else 'none'}}}")
    print(f"  bankroll_source={live_bankroll_source} bankroll_source_valid={bankroll_source_valid} fake_bankroll_used={fake_bankroll_used}")
    print()
    
    print("🧪 TEST MODE: Fake bankroll allowed, no invariant fired")

def show_grep_commands():
    """Show the exact grep commands to monitor these logs."""
    print("\n🔍 MONITORING COMMANDS")
    print("=" * 60)
    
    print("To monitor for fake bankroll invariants:")
    print("grep 'FAKE_BANKROLL_SOURCE_USED' logs/*.log")
    print()
    
    print("To monitor bankroll source fields:")
    print("grep 'bankroll_source=\\|bankroll_source_valid=\\|fake_bankroll_used=' logs/*.log")
    print()
    
    print("To monitor execution-ready logs with bankroll info:")
    print("grep '15M-EXECUTION-READY\\|15M-EXECUTION-DEGRADED' logs/*.log | grep 'bankroll_source='")
    print()
    
    print("To monitor guardrail trips:")
    print("grep 'E2E-GUARDRAIL-TRIP.*bankroll' logs/*.log")
    print()
    
    print("To check for any execution without valid bankroll source:")
    print("grep 'execution_ready=True.*bankroll_source_valid=False' logs/*.log")

def main():
    """Run all demos."""
    print("📋 FAKE BANKROLL PROTECTION - LOG FORMAT DEMONSTRATION")
    print("=" * 70)
    print("This shows exactly what the logs look like with the new bankroll source tracking.")
    print()
    
    demo_normal_bankroll_logs()
    demo_fake_bankroll_logs()
    demo_test_profile_logs()
    show_grep_commands()
    
    print("\n" + "=" * 70)
    print("🎯 KEY TAKEAWAYS:")
    print("✅ Normal operation: bankroll_source='kalshi', source_valid=True, fake_used=False")
    print("🚨 Fake bankroll: bankroll_source='fallback', source_valid=False, fake_used=True")
    print("🧪 Test mode: fake_used=False even with fake source (explicitly allowed)")
    print("📊 All bankroll decisions are logged with full context")
    print("🔍 Use grep commands above to monitor production logs")

if __name__ == "__main__":
    main()
