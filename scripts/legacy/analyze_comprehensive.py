#!/usr/bin/env python3
"""Comprehensive deep dive analysis of fills, positions, orders, portfolios."""

import os
import re
from pathlib import Path

def analyze_file(filepath):
    """Analyze a Python file for bugs and issues."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
    except Exception as e:
        return {'error': str(e)}

    results = {
        'lines': len(lines),
        'chars': len(content),
        'classes': len(re.findall(r'^class ', content, re.MULTILINE)),
        'functions': len(re.findall(r'^def ', content, re.MULTILINE)),
        'async_functions': len(re.findall(r'^async def ', content, re.MULTILINE)),
        'issues': []
    }

    # Check for bare excepts
    bare_excepts = [i+1 for i, line in enumerate(lines) if re.match(r'^[ ]*except:', line)]
    if bare_excepts:
        results['issues'].append(f"Bare except: at lines {bare_excepts[:3]}")

    # Check for print statements
    prints = [i+1 for i, line in enumerate(lines) if re.search(r'\bprint\(', line) and 'logger' not in line]
    if prints:
        results['issues'].append(f"print() statements at lines {prints[:3]}")

    # Check thread safety
    if 'threading' in content and 'Lock()' not in content and 'RLock()' not in content:
        results['issues'].append("Uses threading without Lock/RLock")

    # Async/await mismatch
    if results['async_functions'] > 0:
        await_count = len(re.findall(r'\bawait\b', content))
        if await_count < results['async_functions']:
            results['issues'].append(f"Async mismatch: {results['async_functions']} async def but only {await_count} await")

    # Check for specific patterns
    if 'get_fills' in content:
        results['has_get_fills'] = True
    if 'get_positions' in content:
        results['has_get_positions'] = True
    if 'reconcile' in content.lower():
        results['has_reconcile'] = True

    return results

# Files to analyze
files = [
    ('merid/event_venues/kalshi/fills_ledger.py', 'Fills Ledger'),
    ('merid/event_venues/kalshi/fills_poller.py', 'Fills Poller'),
    ('web/api/kalshi_api.py', 'Kalshi API'),
]

print("=" * 70)
print("DEEP DIVE ANALYSIS: FILLS, POSITIONS, ORDERS, PORTFOLIOS")
print("=" * 70)

for filepath, name in files:
    if os.path.exists(filepath):
        results = analyze_file(filepath)
        print(f"\n### {name}: {filepath}")
        if 'error' in results:
            print(f"  ERROR: {results['error']}")
        else:
            print(f"  Lines: {results['lines']}, Functions: {results['functions']}, Async: {results['async_functions']}")
            if results.get('has_get_fills'):
                print(f"  [✓] Has get_fills")
            if results.get('has_get_positions'):
                print(f"  [✓] Has get_positions")
            if results.get('has_reconcile'):
                print(f"  [✓] Has reconciliation")
            if results['issues']:
                print(f"  ISSUES:")
                for issue in results['issues']:
                    print(f"    - {issue}")
            else:
                print(f"  [✓] No obvious issues")
    else:
        print(f"\n### {name}: {filepath}")
        print(f"  [✗] FILE NOT FOUND")

print("\n" + "=" * 70)
print("Analysis complete. Review issues above.")
