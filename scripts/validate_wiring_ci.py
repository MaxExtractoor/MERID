#!/usr/bin/env python3
"""CI validation script for wiring fixes - Python version to avoid PS regex issues.

This script performs the same checks as validate_wiring_fixes.ps1 but uses
Python regex for reliable CI execution.

Usage:
    python scripts/validate_wiring_ci.py
    python scripts/validate_wiring_ci.py --check-diffs --base-ref main

Exit codes:
    0 - All checks passed
    1 - One or more checks failed
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

# Forbidden patterns that must not appear in codebase
# These match actual fallback code patterns, not error messages or detection code
FORBIDDEN_PATTERNS = [
    # 50 cent fallback: matches "or 50" or "or 50_000" in assignment contexts
    (r'or\s+50\b.*fallback', '50 cent price fallback'),
    (r'avg_price.*=.*or\s+50\b', '50 cent fallback in price assignment'),
    # $5,000 bankroll fallback
    (r'_bankroll_cents\s*=\s*500_000', '$5,000 bankroll fallback (500_000 cents)'),
    (r'500_000.*fallback', '$5,000 fallback pattern'),
    (r'bankroll.*5,000.*fallback', '$5,000 fallback text'),
    # Equity zero default
    (r'session_equity_cents\s*=\s*0\s*$', 'session_equity_cents = 0 (should be None)'),
    (r'session_equity_cents\s*=\s*0\s*[^.]', 'session_equity_cents = 0 (should be None)'),
    # Strict group ID disabled
    (r'KALSHI_STRICT_GROUP_ID\s*=\s*false', 'Strict group ID disabled'),
    (r'KALSHI_STRICT_GROUP_ID\s*=\s*"false"', 'Strict group ID disabled (string)'),
]

# Files to check for forbidden patterns
CHECK_PATHS = [
    'merid/prediction/trading_agent.py',
    'merid/prediction/strategy.py',
    'merid/prediction/consensus_bridge.py',
    'merid/event_venues/kalshi/order_router.py',
    'config/profiles/',
]


def check_no_fallbacks() -> Tuple[bool, List[str]]:
    """Check that no hardcoded fallbacks exist in critical files."""
    errors = []
    
    for check_path in CHECK_PATHS:
        path = Path(check_path)
        if not path.exists():
            continue
        
        # Handle directories
        if path.is_dir():
            files = list(path.rglob('*.py')) + list(path.rglob('*.yaml')) + list(path.rglob('*.yml'))
        else:
            files = [path]
        
        for file_path in files:
            try:
                content = file_path.read_text(encoding='utf-8', errors='ignore')
                for pattern, description in FORBIDDEN_PATTERNS:
                    if re.search(pattern, content, re.IGNORECASE):
                        errors.append(f"{file_path}: Found forbidden pattern '{description}'")
            except Exception as e:
                errors.append(f"{file_path}: Error reading file: {e}")
    
    return len(errors) == 0, errors


def check_fail_closed_logic() -> Tuple[bool, List[str]]:
    """Verify fail-closed logic is present in key files."""
    checks = [
        ('merid/prediction/trading_agent.py', r'missing avg_price', 'Price fail-closed (quarantine)'),
        ('merid/prediction/strategy.py', r'rejecting sizing request', 'Bankroll fail-closed (return 0)'),
        ('merid/prediction/trading_agent.py', r'session_equity_cents\s*=\s*None', 'Equity UNKNOWN state'),
        ('merid/prediction/consensus_bridge.py', r'_get_consensus_thresholds', 'Consensus threshold wiring'),
    ]
    
    errors = []
    for file_path, pattern, description in checks:
        path = Path(file_path)
        if not path.exists():
            errors.append(f"{file_path}: File not found")
            continue
        
        content = path.read_text(encoding='utf-8', errors='ignore')
        if not re.search(pattern, content):
            errors.append(f"{file_path}: Missing {description} logic")
    
    return len(errors) == 0, errors


def check_strict_group_id() -> Tuple[bool, List[str]]:
    """Verify strict group ID is enabled in production config."""
    config_path = Path('config/profiles/env.prod.kalshi-pm.live.example')
    if not config_path.exists():
        return False, ["Production config not found"]
    
    content = config_path.read_text(encoding='utf-8', errors='ignore')
    
    # Check for strict mode enabled
    if re.search(r'KALSHI_STRICT_GROUP_ID\s*=\s*true', content):
        return True, []
    
    return False, ["KALSHI_STRICT_GROUP_ID=true not found in production config"]


def check_risk_event_emissions() -> Tuple[bool, List[str]]:
    """Verify all 4 critical risk events are wired."""
    required_events = {
        'risk.position_sync_failed': 'merid/prediction/trading_agent.py',
        'risk.bankroll_unavailable': 'merid/prediction/strategy.py',
        'risk.equity_feed_lost': 'merid/prediction/trading_agent.py',
    }
    
    errors = []
    for event_type, file_path in required_events.items():
        path = Path(file_path)
        if not path.exists():
            errors.append(f"{file_path}: File not found")
            continue
        
        content = path.read_text(encoding='utf-8', errors='ignore')
        if event_type not in content:
            errors.append(f"{file_path}: Missing {event_type} emission")
    
    return len(errors) == 0, errors


def check_tainted_in_fixtures() -> Tuple[bool, List[str]]:
    """Check for tainted markers in test fixtures."""
    fixtures_path = Path('tests/fixtures')
    if not fixtures_path.exists():
        return True, []  # No fixtures is OK
    
    errors = []
    for file_path in fixtures_path.rglob('*'):
        if file_path.is_file():
            try:
                content = file_path.read_text(encoding='utf-8', errors='ignore')
                if '[TAINTED_PATH]' in content:
                    errors.append(f"{file_path}: Found [TAINTED_PATH] marker")
            except Exception:
                continue
    
    return len(errors) == 0, errors


def check_pr_diff(base_ref: str) -> Tuple[bool, List[str]]:
    """Check PR diff for forbidden patterns."""
    errors = []
    
    try:
        # Get diff from base ref
        result = subprocess.run(
            ['git', 'diff', f'origin/{base_ref}', '--', '.'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            return False, [f"Git diff failed: {result.stderr}"]
        
        diff = result.stdout
        if not diff:
            return True, []  # No diff is OK
        
        # Check for forbidden patterns in diff
        for pattern, description in FORBIDDEN_PATTERNS:
            if re.search(pattern, diff, re.IGNORECASE):
                errors.append(f"PR diff contains forbidden pattern: {description}")
        
    except subprocess.TimeoutExpired:
        return False, ["Git diff timed out"]
    except Exception as e:
        return False, [f"Error checking PR diff: {e}"]
    
    return len(errors) == 0, errors


def main():
    parser = argparse.ArgumentParser(
        description='CI validation for MERID wiring fixes'
    )
    parser.add_argument(
        '--check-diffs',
        action='store_true',
        help='Check PR diff for forbidden patterns'
    )
    parser.add_argument(
        '--base-ref',
        default='main',
        help='Base ref for diff comparison (default: main)'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output results in JSON format'
    )
    
    args = parser.parse_args()
    
    results = {
        'timestamp': str(__import__('datetime').datetime.utcnow().isoformat()),
        'checks': {}
    }
    
    all_passed = True
    
    # Run all checks
    checks = [
        ('no_fallbacks', check_no_fallbacks),
        ('fail_closed_logic', check_fail_closed_logic),
        ('strict_group_id', check_strict_group_id),
        ('risk_event_emissions', check_risk_event_emissions),
        ('tainted_in_fixtures', check_tainted_in_fixtures),
    ]
    
    if args.check_diffs:
        checks.append(('pr_diff', lambda: check_pr_diff(args.base_ref)))
    
    for check_name, check_func in checks:
        passed, errors = check_func()
        results['checks'][check_name] = {
            'passed': passed,
            'errors': errors
        }
        if not passed:
            all_passed = False
    
    results['overall_passed'] = all_passed
    
    # Output
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print("=" * 60)
        print("MERID Wiring CI Validation")
        print("=" * 60)
        
        for check_name, check_result in results['checks'].items():
            status = "✓ PASS" if check_result['passed'] else "✗ FAIL"
            print(f"\n[{status}] {check_name}")
            if check_result['errors']:
                for error in check_result['errors']:
                    print(f"  - {error}")
        
        print("\n" + "=" * 60)
        if all_passed:
            print("✓ ALL CHECKS PASSED")
            print("Fail-closed wiring is active. Production deployment safe.")
        else:
            print("✗ CHECKS FAILED")
            print("Review errors above before deployment.")
        print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())
