#!/usr/bin/env python3
"""Deep dive analysis of fills, positions, orders, and portfolios."""

import os
import re
from pathlib import Path

def analyze_file(filepath, name):
    """Analyze a Python file for common bugs and issues."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        return [f"Error reading file: {e}"]

    issues = []
    lines = content.split('\n')

    # Check for TODO/FIXME comments
    todo_lines = [i+1 for i, line in enumerate(lines) if 'TODO' in line or 'FIXME' in line]
    if todo_lines:
        issues.append(f"TODO/FIXME at lines: {todo_lines[:5]}{'...' if len(todo_lines) > 5 else ''}")

    # Check for bare excepts
    bare_except = [i+1 for i, line in enumerate(lines) if re.match(r'^[ ]*except:', line)]
    if bare_except:
        issues.append(f"Bare except: at lines: {bare_except[:3]}")

    # Check for print statements
    prints = [i+1 for i, line in enumerate(lines) if re.search(r'\bprint\(', line)]
    if prints:
        issues.append(f"print() statements at lines: {prints[:3]}")

    # Check for mutable default arguments
    mutable_defaults = [i+1 for i, line in enumerate(lines) if re.search(r'def .*\(.*=\s*\[.*\]', line)]
    if mutable_defaults:
        issues.append(f"Mutable default args at lines: {mutable_defaults[:3]}")

    # Check thread safety
    if 'threading' in content:
        has_lock = 'Lock()' in content or 'RLock()' in content
        if not has_lock:
            issues.append("Uses threading but no Lock/RLock found")

    # Check async/await consistency
    async_count = len(re.findall(r'\basync def\b', content))
    await_count = len(re.findall(r'\bawait\b', content))
    if async_count > 0 and await_count < async_count:
        issues.append(f"Async mismatch: {async_count} async def but only {await_count} await")

    # Check for hardcoded values
    hardcoded = re.findall(r'["\'][^"\']*api\.kalshi\.com[^"\']*["\']', content)
    if hardcoded:
        issues.append(f"Hardcoded URLs: {len(hardcoded)} instances")

    # Check for potential infinite loops
    while_loops = [i+1 for i, line in enumerate(lines) if re.match(r'^[ ]*while (True|1):', line)]
    if while_loops:
        issues.append(f"Potential infinite loops at: {while_loops[:3]}")

    return issues

# Analyze key files
files_to_analyze = [
    ('merid/event_venues/kalshi/fills_ledger.py', 'Fills Ledger'),
    ('merid/event_venues/kalshi/fills_poller.py', 'Fills Poller'),
    ('web/api/kalshi_api.py', 'Kalshi API'),
]

print("=" * 60)
print("DEEP DIVE: FILLS, POSITIONS, ORDERS, PORTFOLIO")
print("=" * 60)

for filepath, name in files_to_analyze:
    full_path = Path(filepath)
    if full_path.exists():
        print(f"\n=== {name}: {filepath} ===")
        issues = analyze_file(full_path, name)
        if issues:
            for issue in issues:
                print(f"  - {issue}")
        else:
            print("  No obvious issues found")
    else:
        print(f"\n=== {name}: {filepath} ===")
        print(f"  File not found!")

print("\n" + "=" * 60)
