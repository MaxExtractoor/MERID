#!/usr/bin/env python3
"""Kickoff script for the 7-day pre-scale validation protocol.

This script initializes the protocol, runs baseline checks, and
provides status reporting for the go/no-go decision.

Usage:
    # Initialize and start the protocol
    python scripts/kickoff_pre_scale_protocol.py init

    # Check current status
    python scripts/kickoff_pre_scale_protocol.py status

    # Run daily verification (normally done by CI)
    python scripts/kickoff_pre_scale_protocol.py daily

    # Force a stress test run
    python scripts/kickoff_pre_scale_protocol.py stress-test

    # Final go/no-go report
    python scripts/kickoff_pre_scale_protocol.py final-report

Exit codes:
    0 - Protocol on track / Ready for scale
    1 - Protocol failed / Not ready
    2 - Usage error
"""

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Protocol configuration
PROTOCOL_STATE_FILE = Path("status/pre_scale_protocol.json")
REQUIRED_DAYS = 7
STRESS_TEST_DAYS = [2, 6]  # Run stress tests on day 2 and day 6


@dataclass
class ProtocolDay:
    """Status for a single protocol day."""
    day_number: int
    date: str
    audit_chain_valid: bool
    wiring_validation_passed: bool
    risk_events_ok: bool  # All counts <= 5
    tainted_paths_zero: bool
    stress_test_passed: Optional[bool]  # None if not run this day
    overall_ok: bool


@dataclass
class ProtocolState:
    """Full protocol state."""
    initialized_at: str
    started_at: Optional[str]
    current_day: int
    days: List[ProtocolDay]
    ready_for_scale: bool
    recommendation: str


def load_state() -> Optional[ProtocolState]:
    """Load existing protocol state."""
    if not PROTOCOL_STATE_FILE.exists():
        return None
    
    try:
        with open(PROTOCOL_STATE_FILE) as f:
            data = json.load(f)
        
        days = [ProtocolDay(**d) for d in data.get('days', [])]
        return ProtocolState(
            initialized_at=data.get('initialized_at', ''),
            started_at=data.get('started_at'),
            current_day=data.get('current_day', 0),
            days=days,
            ready_for_scale=data.get('ready_for_scale', False),
            recommendation=data.get('recommendation', 'UNKNOWN')
        )
    except Exception as e:
        print(f"Error loading state: {e}")
        return None


def save_state(state: ProtocolState) -> None:
    """Save protocol state to file."""
    PROTOCOL_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    with open(PROTOCOL_STATE_FILE, 'w') as f:
        json.dump(asdict(state), f, indent=2)


def run_wiring_validation() -> Tuple[bool, Dict]:
    """Run wiring validation checks."""
    try:
        result = subprocess.run(
            ['python', 'scripts/validate_wiring_ci.py', '--json'],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            return False, {'error': 'Validation script failed'}
        
        data = json.loads(result.stdout)
        return data.get('overall_passed', False), data
    except Exception as e:
        return False, {'error': str(e)}


def run_audit_chain_check() -> Tuple[bool, Dict]:
    """Run audit chain verification."""
    try:
        from core.risk_audit_chain import verify_audit_chain
        
        result = verify_audit_chain()
        return result.valid, {
            'records_checked': result.records_checked,
            'broken_at': result.broken_at,
        }
    except Exception as e:
        return False, {'error': str(e)}


def run_stress_test() -> Tuple[bool, Dict]:
    """Run full stress test suite."""
    try:
        result = subprocess.run(
            ['python', 'scripts/stress_test_harness.py', '--suite', 'pre-scale', '--json'],
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout for stress tests
        )
        
        if result.returncode != 0:
            # Try to parse partial output
            try:
                data = json.loads(result.stdout)
                return False, data
            except:
                return False, {'error': 'Stress test failed with no output'}
        
        data = json.loads(result.stdout)
        return data.get('overall_success', False), data
    except subprocess.TimeoutExpired:
        return False, {'error': 'Stress test timed out after 10 minutes'}
    except Exception as e:
        return False, {'error': str(e)}


def check_risk_events() -> Tuple[bool, Dict]:
    """Check if risk event counts are within thresholds."""
    try:
        from core.risk_audit_chain import get_risk_audit_chain
        
        chain = get_risk_audit_chain()
        records = chain.export_proof_bundle()
        
        # Count events in last 24h
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        event_counts = {
            'position_sync_failed': 0,
            'bankroll_unavailable': 0,
            'equity_feed_lost': 0,
            'threshold_changed': 0
        }
        
        for rec in records:
            try:
                rec_time = datetime.fromisoformat(rec['timestamp'].replace('Z', '+00:00'))
                if rec_time >= cutoff:
                    et = rec.get('event_type', '')
                    for key in event_counts:
                        if key in et:
                            event_counts[key] += 1
            except:
                continue
        
        # Check thresholds (all must be <= 5)
        all_ok = all(count <= 5 for count in event_counts.values())
        
        return all_ok, {
            'counts': event_counts,
            'threshold': 5,
        }
    except Exception as e:
        return False, {'error': str(e)}


def check_tainted_paths() -> Tuple[bool, Dict]:
    """Check for tainted path markers."""
    # Scan logs for tainted markers
    log_paths = ['logs/', 'reports/', 'data/audit/']
    tainted_count = 0
    
    for log_dir in log_paths:
        path = Path(log_dir)
        if path.exists():
            for log_file in path.rglob('*.log'):
                try:
                    content = log_file.read_text(encoding='utf-8', errors='ignore')
                    if '[TAINTED_PATH]' in content:
                        tainted_count += content.count('[TAINTED_PATH]')
                except:
                    continue
    
    return tainted_count == 0, {'count': tainted_count}


def cmd_init() -> int:
    """Initialize the pre-scale protocol."""
    print("=" * 60)
    print("PRE-SCALE PROTOCOL INITIALIZATION")
    print("=" * 60)
    print()
    
    # Check if already initialized
    existing = load_state()
    if existing:
        print(f"Protocol already initialized on {existing.initialized_at}")
        response = input("Reset and restart? (yes/no): ")
        if response.lower() != 'yes':
            print("Aborting.")
            return 1
    
    # Run baseline checks
    print("Running baseline validation checks...")
    print()
    
    checks = [
        ('Wiring validation', run_wiring_validation),
        ('Audit chain integrity', run_audit_chain_check),
        ('Risk event counts', check_risk_events),
        ('Tainted path scan', check_tainted_paths),
    ]
    
    all_passed = True
    results = {}
    
    for name, check_func in checks:
        print(f"Checking: {name}...", end=' ')
        passed, data = check_func()
        results[name] = {'passed': passed, 'data': data}
        
        if passed:
            print("✓ PASS")
        else:
            print("✗ FAIL")
            all_passed = False
            print(f"  Details: {data}")
    
    print()
    
    if not all_passed:
        print("✗ BASELINE CHECKS FAILED")
        print("Fix issues before starting protocol.")
        return 1
    
    # Initialize state
    now = datetime.now(timezone.utc).isoformat()
    state = ProtocolState(
        initialized_at=now,
        started_at=now,
        current_day=1,
        days=[],
        ready_for_scale=False,
        recommendation='IN_PROGRESS'
    )
    
    save_state(state)
    
    print("✓ BASELINE CHECKS PASSED")
    print()
    print("Pre-scale protocol initialized!")
    print(f"Start time: {now}")
    print(f"Required duration: {REQUIRED_DAYS} days")
    print()
    print("Next steps:")
    print("1. Run daily: python scripts/kickoff_pre_scale_protocol.py daily")
    print("2. Monitor dashboard: ./monitoring/grafana-dashboards/pre-scale-health.json")
    print(f"3. Stress tests scheduled: Days {STRESS_TEST_DAYS}")
    print("4. Final report: python scripts/kickoff_pre_scale_protocol.py final-report")
    
    return 0


def cmd_daily() -> int:
    """Run daily verification and record results."""
    state = load_state()
    if not state:
        print("Error: Protocol not initialized. Run: init")
        return 2
    
    if state.ready_for_scale:
        print("Protocol already complete. Ready for scale-up.")
        return 0
    
    # Calculate current day
    start = datetime.fromisoformat(state.started_at)
    now = datetime.now(timezone.utc)
    day_number = (now - start).days + 1
    
    if day_number > REQUIRED_DAYS:
        print(f"Day {day_number} exceeds required {REQUIRED_DAYS} days.")
        print("Run: final-report")
        return 0
    
    print(f"=" * 60)
    print(f"DAILY VERIFICATION - Day {day_number}/{REQUIRED_DAYS}")
    print(f"=" * 60)
    print()
    
    # Run all checks
    print("Running daily checks...")
    
    audit_ok, _ = run_audit_chain_check()
    wiring_ok, _ = run_wiring_validation()
    risk_ok, _ = check_risk_events()
    tainted_ok, _ = check_tainted_paths()
    
    # Run stress test if scheduled
    stress_passed = None
    if day_number in STRESS_TEST_DAYS:
        print()
        print(f"Running scheduled stress test (Day {day_number})...")
        stress_passed, stress_data = run_stress_test()
        print(f"Stress test: {'PASS' if stress_passed else 'FAIL'}")
        if not stress_passed:
            print(f"Details: {stress_data}")
    
    # Record day
    day_record = ProtocolDay(
        day_number=day_number,
        date=now.isoformat(),
        audit_chain_valid=audit_ok,
        wiring_validation_passed=wiring_ok,
        risk_events_ok=risk_ok,
        tainted_paths_zero=tainted_ok,
        stress_test_passed=stress_passed,
        overall_ok=all([audit_ok, wiring_ok, risk_ok, tainted_ok])
    )
    
    state.days.append(day_record)
    state.current_day = day_number
    
    # Check if ready for scale
    if day_number >= REQUIRED_DAYS:
        all_days_ok = all(d.overall_ok for d in state.days)
        all_stress_ok = all(
            d.stress_test_passed is None or d.stress_test_passed
            for d in state.days
        )
        
        if all_days_ok and all_stress_ok:
            state.ready_for_scale = True
            state.recommendation = 'READY_FOR_SCALEUP'
        else:
            state.recommendation = 'REMEDIATE_AND_RESTART'
    
    save_state(state)
    
    # Print summary
    print()
    print("Day Summary:")
    print(f"  Audit chain: {'✓' if audit_ok else '✗'}")
    print(f"  Wiring validation: {'✓' if wiring_ok else '✗'}")
    print(f"  Risk events (≤5): {'✓' if risk_ok else '✗'}")
    print(f"  Tainted paths (0): {'✓' if tainted_ok else '✗'}")
    if stress_passed is not None:
        print(f"  Stress test: {'✓' if stress_passed else '✗'}")
    print()
    print(f"Overall: {'✓ PASS' if day_record.overall_ok else '✗ FAIL'}")
    
    if state.ready_for_scale:
        print()
        print("=" * 60)
        print("🎉 PROTOCOL COMPLETE - READY FOR SCALE")
        print("=" * 60)
    else:
        days_remaining = REQUIRED_DAYS - day_number
        print(f"\n{days_remaining} days remaining until scale decision.")
    
    return 0 if day_record.overall_ok else 1


def cmd_status() -> int:
    """Show current protocol status."""
    state = load_state()
    if not state:
        print("Protocol not initialized. Run: init")
        return 2
    
    print("=" * 60)
    print("PRE-SCALE PROTOCOL STATUS")
    print("=" * 60)
    print()
    print(f"Initialized: {state.initialized_at}")
    print(f"Started: {state.started_at}")
    print(f"Current day: {state.current_day}/{REQUIRED_DAYS}")
    print(f"Days recorded: {len(state.days)}")
    print(f"Ready for scale: {'YES' if state.ready_for_scale else 'NO'}")
    print(f"Recommendation: {state.recommendation}")
    
    if state.days:
        print()
        print("Daily Summary:")
        for day in state.days:
            stress = " (S)" if day.stress_test_passed is not None else ""
            status = "✓" if day.overall_ok else "✗"
            print(f"  Day {day.day_number}: {status}{stress}")
    
    return 0


def cmd_stress_test() -> int:
    """Force a stress test run."""
    print("=" * 60)
    print("STRESS TEST (Manual Trigger)")
    print("=" * 60)
    print()
    print("Running full pre-scale stress test suite...")
    print("(This may take up to 10 minutes)")
    print()
    
    passed, data = run_stress_test()
    
    if passed:
        print("✓ STRESS TEST PASSED")
        print(f"Recommendation: {data.get('recommendation', 'N/A')}")
        return 0
    else:
        print("✗ STRESS TEST FAILED")
        print(f"Details: {json.dumps(data, indent=2)}")
        return 1


def cmd_final_report() -> int:
    """Generate final go/no-go report."""
    state = load_state()
    if not state:
        print("Protocol not initialized. Run: init")
        return 2
    
    print("=" * 60)
    print("FINAL GO/NO-GO REPORT")
    print("=" * 60)
    print()
    
    # Compile report
    days_completed = len(state.days)
    days_ok = sum(1 for d in state.days if d.overall_ok)
    days_fail = days_completed - days_ok
    
    stress_tests_run = sum(1 for d in state.days if d.stress_test_passed is not None)
    stress_tests_passed = sum(
        1 for d in state.days
        if d.stress_test_passed is not None and d.stress_test_passed
    )
    
    report = {
        'protocol_complete': days_completed >= REQUIRED_DAYS,
        'days_completed': days_completed,
        'days_passed': days_ok,
        'days_failed': days_fail,
        'stress_tests_run': stress_tests_run,
        'stress_tests_passed': stress_tests_passed,
        'ready_for_scale': state.ready_for_scale,
        'recommendation': state.recommendation,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
    
    print(f"Days Completed: {days_completed}/{REQUIRED_DAYS}")
    print(f"Days Passed: {days_ok}")
    print(f"Days Failed: {days_fail}")
    print(f"Stress Tests: {stress_tests_passed}/{stress_tests_run} passed")
    print()
    print(f"Recommendation: {state.recommendation}")
    print()
    
    if state.ready_for_scale:
        print("🎉 GO FOR SCALE-UP")
        print()
        print("All criteria met:")
        print("  ✓ 7 consecutive OK days")
        print("  ✓ All stress tests passed")
        print("  ✓ Zero tainted path markers")
        print("  ✓ Risk events within thresholds")
        print("  ✓ Audit chain integrity verified")
        print()
        print("Next: Gradually increase position sizing with continued monitoring.")
    else:
        print("⛔ NO-GO FOR SCALE-UP")
        print()
        print("Issues identified:")
        if days_fail > 0:
            print(f"  ✗ {days_fail} days failed checks")
        if stress_tests_run > 0 and stress_tests_passed < stress_tests_run:
            print(f"  ✗ {stress_tests_run - stress_tests_passed} stress test(s) failed")
        if days_completed < REQUIRED_DAYS:
            print(f"  ✗ Only {days_completed} of {REQUIRED_DAYS} days completed")
        print()
        print("Action: Remediate issues and restart protocol.")
    
    # Save report
    report_path = Path('reports/pre_scale_final_report.json')
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    print()
    print(f"Report saved: {report_path}")
    
    return 0 if state.ready_for_scale else 1


def main():
    parser = argparse.ArgumentParser(
        description='Pre-scale protocol management'
    )
    subparsers = parser.add_subparsers(dest='command', help='Command')
    
    subparsers.add_parser('init', help='Initialize the protocol')
    subparsers.add_parser('status', help='Show current status')
    subparsers.add_parser('daily', help='Run daily verification')
    subparsers.add_parser('stress-test', help='Force stress test run')
    subparsers.add_parser('final-report', help='Generate final report')
    
    args = parser.parse_args()
    
    if args.command == 'init':
        return cmd_init()
    elif args.command == 'status':
        return cmd_status()
    elif args.command == 'daily':
        return cmd_daily()
    elif args.command == 'stress-test':
        return cmd_stress_test()
    elif args.command == 'final-report':
        return cmd_final_report()
    else:
        parser.print_help()
        return 2


if __name__ == '__main__':
    sys.exit(main())
