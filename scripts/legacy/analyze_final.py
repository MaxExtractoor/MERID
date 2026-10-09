#!/usr/bin/env python3
"""Comprehensive analysis of fills, positions, orders, portfolios."""

import os
import re

def analyze_fills_ledger():
    """Analyze fills_ledger.py for bugs and wiring issues."""
    filepath = 'merid/event_venues/kalshi/fills_ledger.py'
    if not os.path.exists(filepath):
        return {'error': 'File not found'}
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        lines = content.split('\n')
    
    issues = []
    
    # Check for bare excepts
    for i, line in enumerate(lines, 1):
        if re.match(r'^[ ]*except:$', line.strip()):
            issues.append(f"Line {i}: Bare except clause")
    
    # Check for print statements
    for i, line in enumerate(lines, 1):
        if 'print(' in line and 'logger' not in line.lower():
            issues.append(f"Line {i}: print() statement instead of logger")
    
    # Check for async/await mismatch
    async_count = len(re.findall(r'async def ', content))
    await_count = len(re.findall(r'await ', content))
    if async_count > await_count:
        issues.append(f"Async mismatch: {async_count} async def but only {await_count} await")
    
    # Check for mutable default arguments - fixed regex
    for i, line in enumerate(lines, 1):
        if re.search(r'def \w+\(.*=\s*\[', line) or re.search(r'def \w+\(.*=\s*\{', line):
            issues.append(f"Line {i}: Mutable default argument")
    
    return {
        'lines': len(lines),
        'issues': issues,
        'classes': len(re.findall(r'^class ', content, re.MULTILINE)),
        'functions': len(re.findall(r'^def |^async def ', content, re.MULTILINE))
    }

def analyze_fills_poller():
    """Analyze fills_poller.py."""
    filepath = 'merid/event_venues/kalshi/fills_poller.py'
    if not os.path.exists(filepath):
        return {'error': 'File not found'}
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        lines = content.split('\n')
    
    issues = []
    
    for i, line in enumerate(lines, 1):
        if re.match(r'^[ ]*except:$', line.strip()):
            issues.append(f"Line {i}: Bare except clause")
        if 'print(' in line and 'logger' not in line.lower():
            issues.append(f"Line {i}: print() statement")
    
    return {
        'lines': len(lines),
        'issues': issues,
        'functions': len(re.findall(r'^def |^async def ', content, re.MULTILINE))
    }

def analyze_kalshi_api():
    """Analyze kalshi_api.py endpoints."""
    filepath = 'web/api/kalshi_api.py'
    if not os.path.exists(filepath):
        return {'error': 'File not found'}
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        lines = content.split('\n')
    
    issues = []
    
    for i, line in enumerate(lines, 1):
        if re.match(r'^[ ]*except:$', line.strip()):
            issues.append(f"Line {i}: Bare except clause")
    
    # Find fills/positions/orders endpoints
    fills_endpoints = [i for i, line in enumerate(lines, 1) if '@router' in line and 'fills' in line.lower()]
    positions_endpoints = [i for i, line in enumerate(lines, 1) if '@router' in line and 'positions' in line.lower()]
    orders_endpoints = [i for i, line in enumerate(lines, 1) if '@router' in line and 'orders' in line.lower()]
    
    return {
        'lines': len(lines),
        'issues': issues,
        'fills_endpoints': len(fills_endpoints),
        'positions_endpoints': len(positions_endpoints),
        'orders_endpoints': len(orders_endpoints)
    }

# Run analysis
print("=" * 70)
print("DEEP DIVE: FILLS, POSITIONS, ORDERS, PORTFOLIOS - BUG ANALYSIS")
print("=" * 70)

print("\n## 1. FILLS LEDGER (merid/event_venues/kalshi/fills_ledger.py)")
result = analyze_fills_ledger()
if 'error' in result:
    print(f"   ERROR: {result['error']}")
else:
    print(f"   Lines: {result['lines']}, Classes: {result['classes']}, Functions: {result['functions']}")
    if result['issues']:
        print(f"   Issues found ({len(result['issues'])}):")
        for issue in result['issues'][:10]:
            print(f"      - {issue}")
        if len(result['issues']) > 10:
            print(f"      ... and {len(result['issues']) - 10} more")
    else:
        print("   No obvious issues found")

print("\n## 2. FILLS POLLER (merid/event_venues/kalshi/fills_poller.py)")
result = analyze_fills_poller()
if 'error' in result:
    print(f"   ERROR: {result['error']}")
else:
    print(f"   Lines: {result['lines']}, Functions: {result['functions']}")
    if result['issues']:
        print(f"   Issues found ({len(result['issues'])}):")
        for issue in result['issues'][:5]:
            print(f"      - {issue}")
    else:
        print("   No obvious issues found")

print("\n## 3. KALSHI API (web/api/kalshi_api.py)")
result = analyze_kalshi_api()
if 'error' in result:
    print(f"   ERROR: {result['error']}")
else:
    print(f"   Lines: {result['lines']}")
    print(f"   Fills endpoints: {result['fills_endpoints']}")
    print(f"   Positions endpoints: {result['positions_endpoints']}")
    print(f"   Orders endpoints: {result['orders_endpoints']}")
    if result['issues']:
        print(f"   Issues found ({len(result['issues'])}):")
        for issue in result['issues'][:5]:
            print(f"      - {issue}")
    else:
        print("   No obvious issues found")

print("\n" + "=" * 70)
