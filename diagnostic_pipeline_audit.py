#!/usr/bin/env python3
"""
Diagnostic script to expose contradictions and gaps in the trading pipeline.

This script audits:
1. Staleness threshold consistency across all config files
2. Hardcoded thresholds that conflict with config
3. Health check logic contradictions
4. Pipeline blocking conditions
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

def find_hardcoded_thresholds(file_path: Path) -> List[Tuple[str, int, str]]:
    """Find hardcoded staleness thresholds in a file."""
    results = []
    content = file_path.read_text()
    
    # Find patterns like: > 30, > 15, < 30, < 15, etc.
    patterns = [
        (r'>\s*(\d+)', 'greater_than'),
        (r'<\s*(\d+)', 'less_than'),
        (r'==\s*(\d+)', 'equals'),
        (r'>=\s*(\d+)', 'greater_or_equal'),
        (r'<=\s*(\d+)', 'less_or_equal'),
    ]
    
    for pattern, comparison in patterns:
        matches = re.finditer(pattern, content)
        for match in matches:
            value = int(match.group(1))
            # Only care about small numbers (likely seconds thresholds)
            if 1 <= value <= 300:
                line_num = content[:match.start()].count('\n') + 1
                context = content[max(0, match.start()-50):match.end()+50]
                results.append((comparison, value, f"Line {line_num}: {context.strip()}"))
    
    return results

def find_config_thresholds(file_path: Path) -> Dict[str, int]:
    """Find threshold values in config files."""
    results = {}
    content = file_path.read_text()
    
    # YAML-like patterns
    patterns = [
        r'max_book_staleness_s:\s*(\d+)',
        r'max_quote_staleness_s:\s*(\d+)',
        r'block_threshold_ms:\s*(\d+)',
        r'ok_threshold_ms:\s*(\d+)',
        r'warn_threshold_ms:\s*(\d+)',
        r'max_md_staleness_sec:\s*(\d+)',
    ]
    
    for pattern in patterns:
        matches = re.finditer(pattern, content)
        for match in matches:
            key = pattern.split(':')[0].replace('\\s*', '')
            value = int(match.group(1))
            results[key] = value
    
    return results

def audit_sla_config() -> List[str]:
    """Audit SLA config for consistency."""
    issues = []
    sla_path = Path('merid/event_venues/kalshi/sla_config.py')
    
    if not sla_path.exists():
        issues.append(f"SLA config not found: {sla_path}")
        return issues
    
    content = sla_path.read_text()
    
    # Check if timing-aware thresholds are disabled
    if 'if minutes_to_expiry is not None:' in content:
        # Check if it returns base_threshold
        if 'return base_threshold' in content:
            issues.append("✓ Timing-aware thresholds disabled (using base_threshold)")
        else:
            issues.append("⚠ Timing-aware thresholds still active - may cause false positives")
    
    # Check base threshold value
    block_match = re.search(r'block_threshold_ms\s*=\s*(\d+)', content)
    if block_match:
        block_ms = int(block_match.group(1))
        block_s = block_ms / 1000
        if block_s < 60:
            issues.append(f"⚠ Block threshold too strict: {block_s}s (should be >= 60s)")
        else:
            issues.append(f"✓ Block threshold: {block_s}s")
    
    return issues

def audit_threshold_config() -> List[str]:
    """Audit threshold config for consistency."""
    issues = []
    threshold_path = Path('merid/event_venues/kalshi/threshold_config.py')
    
    if not threshold_path.exists():
        issues.append(f"Threshold config not found: {threshold_path}")
        return issues
    
    content = threshold_path.read_text()
    
    # Check default staleness value
    default_match = re.search(r'max_book_staleness_s.*?(\d+)', content)
    if default_match:
        default_s = int(default_match.group(1))
        if default_s < 60:
            issues.append(f"⚠ Default max_book_staleness too strict: {default_s}s (should be >= 60s)")
        else:
            issues.append(f"✓ Default max_book_staleness: {default_s}s")
    
    return issues

def audit_loop_15m() -> List[str]:
    """Audit loop_15m for hardcoded thresholds."""
    issues = []
    loop_path = Path('merid/loop_15m.py')
    
    if not loop_path.exists():
        issues.append(f"loop_15m not found: {loop_path}")
        return issues
    
    content = loop_path.read_text()
    
    # Check for hardcoded 30s
    if 'md_age > 30.0' in content:
        issues.append("⚠ HARDCODED: md_age > 30.0 found in loop_15m.py")
    elif 'md_age > max_age_seconds' in content:
        issues.append("✓ Using SLA config threshold for md_age check")
    
    # Check for hardcoded 15s
    if 'age > 15' in content or 'age < 15' in content:
        issues.append("⚠ HARDCODED: 15s threshold found in loop_15m.py")
    
    return issues

def audit_market_state() -> List[str]:
    """Audit market_state for hardcoded thresholds."""
    issues = []
    ms_path = Path('merid/event_venues/kalshi/market_state.py')
    
    if not ms_path.exists():
        issues.append(f"market_state not found: {ms_path}")
        return issues
    
    content = ms_path.read_text()
    
    # Check MAX_BOOK_STALENESS_MS
    staleness_match = re.search(r'MAX_BOOK_STALENESS_MS\s*=\s*(\d+)', content)
    if staleness_match:
        staleness_ms = int(staleness_match.group(1))
        staleness_s = staleness_ms / 1000
        if staleness_s < 60:
            issues.append(f"⚠ MAX_BOOK_STALENESS_MS too strict: {staleness_s}s (should be >= 60s)")
        else:
            issues.append(f"✓ MAX_BOOK_STALENESS_MS: {staleness_s}s")
    
    # Check if it reads from threshold_config
    if 'get_threshold_config' in content:
        issues.append("✓ Using threshold_config for staleness")
    else:
        issues.append("⚠ Not using threshold_config - may have hardcoded values")
    
    return issues

def audit_agent_grid() -> List[str]:
    """Audit agent_grid for staleness thresholds."""
    issues = []
    agent_path = Path('merid/prediction/agent_grid_15m.py')
    
    if not agent_path.exists():
        issues.append(f"agent_grid_15m not found: {agent_path}")
        return issues
    
    content = agent_path.read_text()
    
    # Check for hardcoded staleness
    if 'max_md_staleness_sec = 120.0' in content or 'max_md_staleness_sec=120.0' in content:
        issues.append("✓ Using 120s staleness threshold in agent_grid")
    elif 'max_md_staleness_sec = 30.0' in content or 'max_md_staleness_sec=30.0' in content:
        issues.append("⚠ Using 30s staleness threshold in agent_grid (too strict)")
    elif 'max_md_staleness_sec = 15.0' in content or 'max_md_staleness_sec=15.0' in content:
        issues.append("⚠ Using 15s staleness threshold in agent_grid (too strict)")
    
    return issues

def main():
    """Run all audits."""
    print("=" * 80)
    print("TRADING PIPELINE DIAGNOSTIC AUDIT")
    print("=" * 80)
    print()
    
    all_issues = []
    
    # Audit each component
    print("1. SLA Config Audit")
    print("-" * 40)
    sla_issues = audit_sla_config()
    all_issues.extend(sla_issues)
    for issue in sla_issues:
        print(f"  {issue}")
    print()
    
    print("2. Threshold Config Audit")
    print("-" * 40)
    threshold_issues = audit_threshold_config()
    all_issues.extend(threshold_issues)
    for issue in threshold_issues:
        print(f"  {issue}")
    print()
    
    print("3. Loop 15m Audit")
    print("-" * 40)
    loop_issues = audit_loop_15m()
    all_issues.extend(loop_issues)
    for issue in loop_issues:
        print(f"  {issue}")
    print()
    
    print("4. Market State Audit")
    print("-" * 40)
    ms_issues = audit_market_state()
    all_issues.extend(ms_issues)
    for issue in ms_issues:
        print(f"  {issue}")
    print()
    
    print("5. Agent Grid Audit")
    print("-" * 40)
    agent_issues = audit_agent_grid()
    all_issues.extend(agent_issues)
    for issue in agent_issues:
        print(f"  {issue}")
    print()
    
    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    warnings = [i for i in all_issues if i.startswith('⚠')]
    checks = [i for i in all_issues if i.startswith('✓')]
    errors = [i for i in all_issues if i.startswith('ERROR')]
    
    print(f"Checks passed: {len(checks)}")
    print(f"Warnings: {len(warnings)}")
    print(f"Errors: {len(errors)}")
    
    if warnings:
        print()
        print("WARNINGS (need attention):")
        for w in warnings:
            print(f"  {w}")
    
    if errors:
        print()
        print("ERRORS (must fix):")
        for e in errors:
            print(f"  {e}")
    
    if not warnings and not errors:
        print()
        print("✓ No issues found - pipeline is consistent!")
    
    return 1 if errors else 0

if __name__ == '__main__':
    sys.exit(main())
