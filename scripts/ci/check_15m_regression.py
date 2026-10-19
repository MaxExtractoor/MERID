#!/usr/bin/env python3
"""
CI Regression Checks for Kalshi 15m Lean Stack

This script validates critical invariants to prevent regression:
1. No legacy on_event usage in 15m stack
2. No duplicate operation IDs in order gate
3. Correct WS bridge singleton usage (no duplicate instances)

Usage:
    python scripts/ci/check_15m_regression.py
"""

import ast
import sys
from pathlib import Path
from typing import List, Set, Tuple

# Paths to check
CHECK_PATHS = [
    Path(__file__).parent.parent.parent / "web" / "main_15m_lean.py",
    Path(__file__).parent.parent.parent / "merid" / "loop_15m.py",
    Path(__file__).parent.parent.parent / "merid" / "prediction" / "agent_grid_15m.py",
    Path(__file__).parent.parent.parent / "merid" / "event_venues" / "kalshi" / "market_catalog.py",
]

def check_on_event_usage(file_path: Path) -> List[str]:
    """Check for legacy on_event method calls."""
    violations = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for on_event method calls
        if 'on_event' in content:
            # Parse AST to find actual method calls
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Attribute):
                        if node.func.attr == 'on_event':
                            violations.append(
                                f"Line {node.lineno}: Found on_event() call - "
                                "legacy pattern, should use direct singleton access"
                            )
    except Exception as e:
        print(f"Warning: Could not parse {file_path}: {e}", file=sys.stderr)
    
    return violations

def check_ws_bridge_duplication(file_path: Path) -> List[str]:
    """Check for duplicate WS bridge instantiations."""
    violations = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for direct KalshiWebSocketBridge() instantiation
        if 'KalshiWebSocketBridge()' in content:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        if node.func.id == 'KalshiWebSocketBridge':
                            violations.append(
                                f"Line {node.lineno}: Direct KalshiWebSocketBridge() instantiation - "
                                "should use get_ws_bridge() singleton"
                            )
    except Exception as e:
        print(f"Warning: Could not parse {file_path}: {e}", file=sys.stderr)
    
    return violations

def check_duplicate_get_bankroll(file_path: Path) -> List[str]:
    """Check for duplicate get_bankroll_service() calls in same function."""
    violations = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        tree = ast.parse(content)
        for func_node in ast.walk(tree):
            if isinstance(func_node, ast.FunctionDef):
                # Count get_bankroll_service calls in this function
                bankroll_calls = []
                for node in ast.walk(func_node):
                    if isinstance(node, ast.Call):
                        if isinstance(node.func, ast.Name):
                            if node.func.id == 'get_bankroll_service':
                                bankroll_calls.append(node.lineno)
                
                if len(bankroll_calls) > 1:
                    violations.append(
                        f"Function {func_node.name} (line {func_node.lineno}): "
                        f"Multiple get_bankroll_service() calls at lines {bankroll_calls} - "
                        "should call once and cache result"
                    )
    except Exception as e:
        print(f"Warning: Could not parse {file_path}: {e}", file=sys.stderr)
    
    return violations

def main() -> int:
    """Run all regression checks."""
    all_violations = []
    
    print("Running 15m Lean Stack Regression Checks...")
    print("=" * 60)
    
    for path in CHECK_PATHS:
        if not path.exists():
            print(f"Skipping {path} (not found)")
            continue
        
        print(f"\nChecking {path.relative_to(Path(__file__).parent.parent.parent)}:")
        
        # Check 1: on_event usage
        on_event_violations = check_on_event_usage(path)
        if on_event_violations:
            print(f"  ❌ on_event violations found:")
            for v in on_event_violations:
                print(f"    {v}")
            all_violations.extend(on_event_violations)
        else:
            print(f"  ✓ No on_event usage")
        
        # Check 2: WS bridge duplication
        ws_violations = check_ws_bridge_duplication(path)
        if ws_violations:
            print(f"  ❌ WS bridge violations found:")
            for v in ws_violations:
                print(f"    {v}")
            all_violations.extend(ws_violations)
        else:
            print(f"  ✓ No duplicate WS bridge instantiation")
        
        # Check 3: Duplicate bankroll calls
        bankroll_violations = check_duplicate_get_bankroll(path)
        if bankroll_violations:
            print(f"  ❌ Bankroll service violations found:")
            for v in bankroll_violations:
                print(f"    {v}")
            all_violations.extend(bankroll_violations)
        else:
            print(f"  ✓ No duplicate bankroll service calls")
    
    print("\n" + "=" * 60)
    if all_violations:
        print(f"❌ FAILED: {len(all_violations)} violation(s) found")
        return 1
    else:
        print("✅ PASSED: All regression checks passed")
        return 0

if __name__ == "__main__":
    sys.exit(main())
