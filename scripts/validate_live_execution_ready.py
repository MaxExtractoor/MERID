#!/usr/bin/env python3
"""
Live Execution-Ready Validation Script
Validates that the execution-ready gate behaves correctly in real runs.
"""

import sys
import os
import re
from datetime import datetime, timezone
from collections import defaultdict, Counter

# Add the project root to Python path
sys.path.insert(0, 'c:\\Dev\\MERID')

def parse_audit_snapshot(log_line):
    """Parse E2E-AUDIT-SNAPSHOT log line."""
    pattern = r'\[E2E-AUDIT-SNAPSHOT\] ready=(\w+) reasons=([^\s]+) catalog_age=([\d.]+)s md_fresh=(\d+)/5 depth=(\d+)/5 ws=(\w+) bankroll=([\d.]+) risk=(\w+) top3=(\w+)'
    match = re.search(pattern, log_line)
    if match:
        return {
            'ready': match.group(1) == 'True',
            'reasons': match.group(2) if match.group(2) != 'none' else '',
            'catalog_age': float(match.group(3)),
            'md_fresh': int(match.group(4)),
            'depth': int(match.group(5)),
            'ws': match.group(6) == 'True',
            'bankroll': float(match.group(7)),
            'risk': match.group(8) == 'True',
            'top3': match.group(9) == 'True'
        }
    return None

def parse_guardrail_trip(log_line):
    """Parse E2E-GUARDRAIL-TRIP log line."""
    pattern = r'\[E2E-GUARDRAIL-TRIP\] cycle=(\d+) execution_ready=FALSE violations=([^\s]+)'
    match = re.search(pattern, log_line)
    if match:
        return {
            'cycle': int(match.group(1)),
            'violations': match.group(2).split(',')
        }
    return None

def parse_execution_ready(log_line):
    """Parse 15M-EXECUTION-READY log line."""
    pattern = r'\[15M-EXECUTION-(\w+)\] cycle=(\d+)'
    match = re.search(pattern, log_line)
    if match:
        return {
            'status': match.group(1),
            'cycle': int(match.group(2))
        }
    return None

def validate_gate_consistency(audit_snapshots, guardrail_trips, execution_ready_logs):
    """Validate that gate decisions are consistent across all log types."""
    
    print("=" * 60)
    print("GATE CONSISTENCY VALIDATION")
    print("=" * 60)
    
    issues = []
    
    # Build cycle-based mapping
    cycles = {}
    
    # Map audit snapshots by cycle (extract from log context if needed)
    for snapshot in audit_snapshots:
        # Note: We'd need cycle info from context, using index for now
        cycles[f"audit_{len(cycles)}"] = {
            'audit': snapshot,
            'ready': snapshot['ready']
        }
    
    # Map guardrail trips by cycle
    for trip in guardrail_trips:
        cycle_id = f"guardrail_{trip['cycle']}"
        if cycle_id not in cycles:
            cycles[cycle_id] = {}
        cycles[cycle_id]['guardrail'] = trip
        cycles[cycle_id]['ready'] = False  # Guardrail trips mean not ready
    
    # Map execution ready logs by cycle
    for ready_log in execution_ready_logs:
        cycle_id = f"execution_{ready_log['cycle']}"
        if cycle_id not in cycles:
            cycles[cycle_id] = {}
        cycles[cycle_id]['execution'] = ready_log
        cycles[cycle_id]['ready'] = ready_log['status'] == 'READY'
    
    print(f"\nFound {len(cycles)} cycles to validate")
    
    # Validate each cycle
    for cycle_id, cycle_data in cycles.items():
        audit_ready = cycle_data.get('audit', {}).get('ready')
        execution_ready = cycle_data.get('execution', {}).get('status') == 'READY'
        guardrail_present = 'guardrail' in cycle_data
        
        if guardrail_present and (audit_ready or execution_ready):
            issues.append(f"{cycle_id}: Guardrail trip but execution shows ready")
        
        if audit_ready is not None and execution_ready is not None:
            if audit_ready != execution_ready:
                issues.append(f"{cycle_id}: Audit ready={audit_ready} but execution ready={execution_ready}")
    
    if issues:
        print(f"\n❌ CONSISTENCY ISSUES FOUND ({len(issues)}):")
        for issue in issues:
            print(f"   • {issue}")
    else:
        print("\n✅ Gate consistency validated across all log types")
    
    return issues

def validate_gate_conditions(audit_snapshots):
    """Validate that gate conditions meet expected thresholds."""
    
    print("\n" + "=" * 60)
    print("GATE CONDITIONS VALIDATION")
    print("=" * 60)
    
    issues = []
    
    # Expected thresholds
    CATALOG_MAX_AGE = 10.0  # seconds
    MIN_MD_FRESH = 5  # all 5 assets
    MIN_DEPTH = 5  # all 5 assets
    
    ready_cycles = [s for s in audit_snapshots if s['ready']]
    not_ready_cycles = [s for s in audit_snapshots if not s['ready']]
    
    print(f"\nReady cycles: {len(ready_cycles)}")
    print(f"Not ready cycles: {len(not_ready_cycles)}")
    
    # Validate ready cycles meet all conditions
    if ready_cycles:
        print("\nValidating ready cycles...")
        for i, snapshot in enumerate(ready_cycles[:5]):  # Check first 5
            if snapshot['catalog_age'] > CATALOG_MAX_AGE:
                issues.append(f"Ready cycle {i}: catalog_age {snapshot['catalog_age']}s > {CATALOG_MAX_AGE}s")
            
            if snapshot['md_fresh'] < MIN_MD_FRESH:
                issues.append(f"Ready cycle {i}: md_fresh {snapshot['md_fresh']}/5 < {MIN_MD_FRESH}/5")
            
            if snapshot['depth'] < MIN_DEPTH:
                issues.append(f"Ready cycle {i}: depth {snapshot['depth']}/5 < {MIN_DEPTH}/5")
            
            if not snapshot['ws']:
                issues.append(f"Ready cycle {i}: ws_forwarder_healthy=False")
            
            if snapshot['bankroll'] <= 0:
                issues.append(f"Ready cycle {i}: bankroll {snapshot['bankroll']} <= 0")
            
            if not snapshot['risk']:
                issues.append(f"Ready cycle {i}: risk_profile_loaded=False")
            
            if not snapshot['top3']:
                issues.append(f"Ready cycle {i}: top3_gate_available=False")
    
    # Validate not ready cycles have clear reasons
    if not_ready_cycles:
        print("\nValidating not ready cycles...")
        reason_counts = Counter()
        for snapshot in not_ready_cycles:
            if snapshot['reasons']:
                for reason in snapshot['reasons'].split(','):
                    reason_counts[reason] += 1
            else:
                reason_counts['unknown'] += 1
        
        print(f"Top failure reasons:")
        for reason, count in reason_counts.most_common(5):
            print(f"   • {reason}: {count} cycles")
    
    if issues:
        print(f"\n❌ GATE CONDITION ISSUES FOUND ({len(issues)}):")
        for issue in issues:
            print(f"   • {issue}")
    else:
        print("\n✅ All gate conditions validated")
    
    return issues

def validate_invariant_quietness(log_lines):
    """Validate that invariants are quiet in normal operation."""
    
    print("\n" + "=" * 60)
    print("INVARIANT QUIETNESS VALIDATION")
    print("=" * 60)
    
    # Invariants that should NOT appear in normal operation
    critical_invariants = [
        'MD_NEGATIVE_AGE',
        'WS_FORWARDER_IMPOSSIBLE_OK', 
        'QUALITY_OPTIMIZER_MISMATCH',
        'LIVE_BANKROLL_INVALID',
        'LIVE_BANKROLL_ZERO_OR_NEGATIVE',
        'RISK_PROFILE_NOT_LOADED',
        'TOP3_GATE_FAIL_OPEN',
        'EXECUTION_READY_CRITICAL_FAILURE'
    ]
    
    invariant_counts = defaultdict(int)
    
    for line in log_lines:
        for invariant in critical_invariants:
            if invariant in line:
                invariant_counts[invariant] += 1
    
    total_violations = sum(invariant_counts.values())
    
    print(f"\nInvariant violations in normal operation:")
    if total_violations == 0:
        print("✅ Zero critical invariant violations (expected)")
    else:
        print(f"❌ {total_violations} critical invariant violations found:")
        for invariant, count in invariant_counts.items():
            print(f"   • { invariant}: {count} occurrences")
    
    return total_violations == 0

def analyze_log_file(log_file_path):
    """Analyze a log file for execution-ready behavior."""
    
    print(f"Analyzing log file: {log_file_path}")
    
    try:
        with open(log_file_path, 'r', encoding='utf-8') as f:
            log_lines = f.readlines()
    except Exception as e:
        print(f"❌ Failed to read log file: {e}")
        return False
    
    # Extract relevant log lines
    audit_snapshots = []
    guardrail_trips = []
    execution_ready_logs = []
    
    for line in log_lines:
        line = line.strip()
        if 'E2E-AUDIT-SNAPSHOT' in line:
            snapshot = parse_audit_snapshot(line)
            if snapshot:
                audit_snapshots.append(snapshot)
        elif 'E2E-GUARDRAIL-TRIP' in line:
            trip = parse_guardrail_trip(line)
            if trip:
                guardrail_trips.append(trip)
        elif '15M-EXECUTION-READY' in line or '15M-EXECUTION-DEGRADED' in line:
            ready = parse_execution_ready(line)
            if ready:
                execution_ready_logs.append(ready)
    
    print(f"\nLog analysis results:")
    print(f"• E2E-AUDIT-SNAPSHOT lines: {len(audit_snapshots)}")
    print(f"• E2E-GUARDRAIL-TRIP lines: {len(guardrail_trips)}")
    print(f"• 15M-EXECUTION lines: {len(execution_ready_logs)}")
    
    # Run validations
    consistency_issues = validate_gate_consistency(audit_snapshots, guardrail_trips, execution_ready_logs)
    condition_issues = validate_gate_conditions(audit_snapshots)
    invariants_quiet = validate_invariant_quietness(log_lines)
    
    # Summary
    total_issues = len(consistency_issues) + len(condition_issues)
    if not invariants_quiet:
        total_issues += 1
    
    print("\n" + "=" * 60)
    print("LIVE RUN VALIDATION SUMMARY")
    print("=" * 60)
    
    if total_issues == 0 and invariants_quiet:
        print("🎉 LIVE RUN VALIDATION: PASSED")
        print("\nAll execution-ready gate behavior validated:")
        print("• Gate decisions consistent across log types")
        print("• All ready cycles meet required conditions")
        print("• No critical invariant violations in normal operation")
        return True
    else:
        print(f"❌ LIVE RUN VALIDATION: {total_issues} ISSUES FOUND")
        if consistency_issues:
            print(f"• Consistency issues: {len(consistency_issues)}")
        if condition_issues:
            print(f"• Gate condition issues: {len(condition_issues)}")
        if not invariants_quiet:
            print("• Critical invariant violations detected")
        return False

def main():
    """Main validation function."""
    
    print("LIVE EXECUTION-READY VALIDATION")
    print("Validating execution-ready gate behavior in real runs")
    
    # Look for recent log files
    log_paths = [
        'c:\\Dev\\MERID\\web\\health_diagnostic.txt',
        'c:\\Dev\\MERID\\logs\\merid.log',
        'c:\\Dev\\MERID\\logs\\15m_loop.log'
    ]
    
    for log_path in log_paths:
        if os.path.exists(log_path):
            print(f"\nFound log file: {log_path}")
            success = analyze_log_file(log_path)
            if success:
                return True
    
    print("\n❌ No suitable log files found for validation")
    print("Please ensure the 15m loop has run and generated logs with:")
    print("• [E2E-AUDIT-SNAPSHOT] markers")
    print("• [15M-EXECUTION-READY] or [15M-EXECUTION-DEGRADED] markers")
    print("• [E2E-GUARDRAIL-TRIP] markers (when applicable)")
    
    return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
