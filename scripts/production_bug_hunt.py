#!/usr/bin/env python3
"""
Focused production bug hunts for unified edge system.

This script checks for high-risk bug classes:
- Clock/expiry mismatches
- NaN/None propagation
- Inconsistent units
- Env/config drift

Usage:
    python scripts/production_bug_hunt.py --log-dir /path/to/logs
"""

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple


def check_config_drift() -> Dict:
    """
    Check for env/config drift.
    
    Returns:
        Dict with config drift issues
    """
    print("=" * 80)
    print("CONFIG DRIFT CHECK")
    print("=" * 80)
    
    issues = []
    
    # Check unified edge enabled
    unified_edge_enabled = os.getenv('MERID_UNIFIED_EDGE_ENABLED', 'false').lower() == 'true'
    print(f"\nMERID_UNIFIED_EDGE_ENABLED: {unified_edge_enabled}")
    
    # Check calibration version
    calibration_version = os.getenv('MERID_CALIBRATION_VERSION', 'placeholder')
    print(f"MERID_CALIBRATION_VERSION: {calibration_version}")
    
    if unified_edge_enabled and calibration_version == 'placeholder':
        issues.append({
            'type': 'config_drift',
            'severity': 'CRITICAL',
            'message': 'Unified edge enabled with placeholder calibration - blocked in code but config drift risk',
        })
    
    # Check profile consistency
    merid_profile = os.getenv('MERID_PROFILE', 'full')
    merid_pm_profile = os.getenv('MERID_PM_PROFILE', 'baseline')
    print(f"MERID_PROFILE: {merid_profile}")
    print(f"MERID_PM_PROFILE: {merid_pm_profile}")
    
    # Check for dangerous combinations
    if merid_profile == 'kalshi-only' and merid_pm_profile == 'production':
        issues.append({
            'type': 'config_drift',
            'severity': 'HIGH',
            'message': 'Dangerous profile combination: kalshi-only + production',
        })
    
    # Check risk caps consistency
    total_risk_budget = os.getenv('MERID_LIVE_SESSION_MAX_RISK_USD', '300')
    print(f"MERID_LIVE_SESSION_MAX_RISK_USD: {total_risk_budget}")
    
    try:
        risk_budget_float = float(total_risk_budget)
        if risk_budget_float > 1000:
            issues.append({
                'type': 'config_drift',
                'severity': 'MEDIUM',
                'message': f'High risk budget: {risk_budget_float} USD',
            })
    except ValueError:
        issues.append({
            'type': 'config_drift',
            'severity': 'HIGH',
            'message': f'Invalid risk budget: {total_risk_budget}',
        })
    
    return {'issues': issues}


def check_nan_propagation(log_dir: Path) -> Dict:
    """
    Check for NaN/None propagation in logs.
    
    Returns:
        Dict with NaN/None issues
    """
    print("\n" + "=" * 80)
    print("NAN/NONE PROPAGATION CHECK")
    print("=" * 80)
    
    issues = []
    log_files = list(log_dir.glob("*.log")) + list(log_dir.glob("*.txt"))
    
    for log_file in log_files:
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    # Check for NaN in edge logs
                    if 'edge=nan' in line.lower() or 'edge_r=nan' in line.lower():
                        issues.append({
                            'type': 'nan_propagation',
                            'severity': 'CRITICAL',
                            'message': f'NaN in edge computation: {line.strip()}',
                            'file': log_file.name,
                        })
                    
                    # Check for None in critical fields
                    if 'spot_price=None' in line or 'price_cents=None' in line:
                        issues.append({
                            'type': 'none_propagation',
                            'severity': 'HIGH',
                            'message': f'None in critical field: {line.strip()}',
                            'file': log_file.name,
                        })
                    
                    # Check for invalid values
                    if 'edge=-' in line and 'edge_R' in line:
                        issues.append({
                            'type': 'invalid_value',
                            'severity': 'MEDIUM',
                            'message': f'Negative edge: {line.strip()}',
                            'file': log_file.name,
                        })
        except Exception as e:
            print(f"Error processing {log_file}: {e}")
    
    return {'issues': issues, 'files_checked': len(log_files)}


def check_clock_mismatches(log_dir: Path) -> Dict:
    """
    Check for clock/expiry mismatches in logs.
    
    Returns:
        Dict with clock mismatch issues
    """
    print("\n" + "=" * 80)
    print("CLOCK/EXPIRY MISMATCH CHECK")
    print("=" * 80)
    
    issues = []
    log_files = list(log_dir.glob("*.log")) + list(log_dir.glob("*.txt"))
    
    for log_file in log_files:
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    # Check for negative time_to_expiry
                    if 'time_to_expiry' in line and ('negative' in line.lower() or '< 0' in line):
                        issues.append({
                            'type': 'clock_mismatch',
                            'severity': 'CRITICAL',
                            'message': f'Negative time_to_expiry: {line.strip()}',
                            'file': log_file.name,
                        })
                    
                    # Check for excessive time_to_expiry
                    if 'time_to_expiry' in line and '> 900' in line:
                        issues.append({
                            'type': 'clock_mismatch',
                            'severity': 'HIGH',
                            'message': f'Excessive time_to_expiry: {line.strip()}',
                            'file': log_file.name,
                        })
                    
                    # Check for clock skew warnings
                    if 'clock skew' in line.lower() or 'clock mismatch' in line.lower():
                        issues.append({
                            'type': 'clock_mismatch',
                            'severity': 'MEDIUM',
                            'message': f'Clock skew detected: {line.strip()}',
                            'file': log_file.name,
                        })
        except Exception as e:
            print(f"Error processing {log_file}: {e}")
    
    return {'issues': issues, 'files_checked': len(log_files)}


def check_unit_consistency(log_dir: Path) -> Dict:
    """
    Check for inconsistent units in logs.
    
    Returns:
        Dict with unit consistency issues
    """
    print("\n" + "=" * 80)
    print("UNIT CONSISTENCY CHECK")
    print("=" * 80)
    
    issues = []
    log_files = list(log_dir.glob("*.log")) + list(log_dir.glob("*.txt"))
    
    for log_file in log_files:
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    # Check for edge in wrong units (should be probability 0-1)
                    if 'edge=' in line and 'edge_pct' not in line:
                        edge_match = re.search(r'edge=([0-9.]+)', line)
                        if edge_match:
                            edge_val = float(edge_match.group(1))
                            if edge_val > 1.0:
                                issues.append({
                                    'type': 'unit_inconsistency',
                                    'severity': 'HIGH',
                                    'message': f'Edge > 1.0 (should be probability): {edge_val} in {line.strip()}',
                                    'file': log_file.name,
                                })
                    
                    # Check for price in wrong units (should be cents)
                    if 'price_cents=' in line:
                        price_match = re.search(r'price_cents=([0-9.]+)', line)
                        if price_match:
                            price_val = float(price_match.group(1))
                            if price_val < 1 or price_val > 10000:
                                issues.append({
                                    'type': 'unit_inconsistency',
                                    'severity': 'MEDIUM',
                                    'message': f'Unusual price_cents: {price_val} in {line.strip()}',
                                    'file': log_file.name,
                                })
        except Exception as e:
            print(f"Error processing {log_file}: {e}")
    
    return {'issues': issues, 'files_checked': len(log_files)}


def print_bug_hunt_summary(results: Dict):
    """Print bug hunt summary."""
    print("\n" + "=" * 80)
    print("BUG HUNT SUMMARY")
    print("=" * 80)
    
    total_issues = 0
    critical_issues = 0
    high_issues = 0
    
    for check_name, check_result in results.items():
        issues = check_result.get('issues', [])
        total_issues += len(issues)
        critical_issues += sum(1 for i in issues if i.get('severity') == 'CRITICAL')
        high_issues += sum(1 for i in issues if i.get('severity') == 'HIGH')
        
        print(f"\n{check_name.upper()}:")
        print(f"  Issues found: {len(issues)}")
        
        for issue in issues:
            severity = issue.get('severity', 'UNKNOWN')
            message = issue.get('message', 'No message')
            print(f"  [{severity}] {message}")
    
    print(f"\n" + "=" * 80)
    print(f"TOTAL: {total_issues} issues ({critical_issues} CRITICAL, {high_issues} HIGH)")
    
    if critical_issues > 0:
        print("\n⚠️  CRITICAL ISSUES FOUND - IMMEDIATE ACTION REQUIRED")
    elif high_issues > 0:
        print("\n⚠️  HIGH SEVERITY ISSUES FOUND - INVESTIGATE SOON")
    else:
        print("\n✅ No critical or high severity issues found")


def main():
    parser = argparse.ArgumentParser(description="Production bug hunt")
    parser.add_argument("--log-dir", type=Path, required=True, help="Directory containing log files")
    
    args = parser.parse_args()
    
    if not args.log_dir.exists():
        print(f"Error: Log directory {args.log_dir} does not exist")
        return 1
    
    results = {}
    
    # Run all checks
    results['config_drift'] = check_config_drift()
    results['nan_propagation'] = check_nan_propagation(args.log_dir)
    results['clock_mismatches'] = check_clock_mismatches(args.log_dir)
    results['unit_consistency'] = check_unit_consistency(args.log_dir)
    
    # Print summary
    print_bug_hunt_summary(results)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
