#!/usr/bin/env python3
"""
CI Check: Verify canonical risk primitive sources

This script enforces that:
1. All Kalshi fee calculations use the canonical fees.py module
2. No duplicate fee implementations exist outside fees.py
3. No hardcoded drawdown thresholds in 15m crypto strategies

Usage:
    python scripts/check_risk_canonical_sources.py

Exit codes:
    0: All checks passed
    1: One or more checks failed
"""

import os
import re
import sys
from pathlib import Path
from typing import List, Tuple


def check_no_duplicate_fee_functions(root_dir: Path) -> List[str]:
    """
    Check that no kalshi_fee_* functions exist outside the canonical fees.py module.
    
    Allowed locations:
    - merid/event_venues/kalshi/fees.py (canonical)
    - merid/event_venues/kalshi/position_sizer.py (delegates to canonical)
    - merid/event_venues/kalshi/kalshi_risk.py (delegates to canonical)
    - merid/event_venues/kalshi/order_router.py (delegates to canonical)
    - merid/event_venues/kalshi/parabolic_fees.py (delegates to canonical)
    - tests/ (test files)
    """
    violations = []
    
    # Canonical fee module
    canonical_fee_file = root_dir / "merid/event_venues/kalshi/fees.py"
    
    # Files that are allowed to have kalshi_fee_* (they delegate to canonical)
    allowed_files = {
        canonical_fee_file,
        root_dir / "merid/event_venues/kalshi/position_sizer.py",
        root_dir / "merid/event_venues/kalshi/kalshi_risk.py",
        root_dir / "merid/event_venues/kalshi/order_router.py",
        root_dir / "merid/event_venues/kalshi/parabolic_fees.py",
    }
    
    # Search for kalshi_fee_* function definitions
    for py_file in root_dir.rglob("*.py"):
        # Skip test files
        if "tests" in py_file.parts or "test" in py_file.name:
            continue
        
        # Skip allowed files
        if py_file in allowed_files:
            continue
        
        # Skip __pycache__ and virtual environments
        if "__pycache__" in py_file.parts or "venv" in py_file.parts or ".venv" in py_file.parts:
            continue
        
        try:
            content = py_file.read_text()
            # Look for function definitions: def kalshi_fee_*
            if re.search(r"def kalshi_fee_\w+\s*\(", content):
                violations.append(f"Duplicate fee function found in {py_file.relative_to(root_dir)}")
        except Exception:
            continue
    
    return violations


def check_no_hardcoded_fee_formula(root_dir: Path) -> List[str]:
    """
    Check that the parabolic fee formula is not reimplemented outside canonical modules.
    
    Pattern to catch: 0.07 * price * (1 - price) or similar
    Allowed locations:
    - merid/event_venues/kalshi/fees.py (canonical)
    - merid/event_venues/kalshi/parabolic_fees.py (canonical parabolic)
    - tests/ (test files)
    """
    violations = []
    
    allowed_files = {
        root_dir / "merid/event_venues/kalshi/fees.py",
        root_dir / "merid/event_venues/kalshi/parabolic_fees.py",
    }
    
    # Pattern for parabolic formula (catches common variations)
    patterns = [
        r"0\.07\s*\*\s*\w+\s*\*\s*\(\s*1\s*-\s*\w+\s*\)",  # 0.07 * price * (1 - price)
        r"0\.05\s*\*\s*\w+\s*\*\s*\(\s*1\s*-\s*\w+\s*\)",  # 0.05 tier
        r"0\.03\s*\*\s*\w+\s*\*\s*\(\s*1\s*-\s*\w+\s*\)",  # 0.03 tier
    ]
    
    for py_file in root_dir.rglob("*.py"):
        # Skip test files
        if "tests" in py_file.parts or "test" in py_file.name:
            continue
        
        # Skip allowed files
        if py_file in allowed_files:
            continue
        
        # Skip __pycache__ and virtual environments
        if "__pycache__" in py_file.parts or "venv" in py_file.parts or ".venv" in py_file.parts:
            continue
        
        try:
            content = py_file.read_text()
            for pattern in patterns:
                if re.search(pattern, content):
                    violations.append(f"Hardcoded fee formula in {py_file.relative_to(root_dir)}")
                    break
        except Exception:
            continue
    
    return violations


def check_no_hardcoded_drawdown_in_15m_strategies(root_dir: Path) -> List[str]:
    """
    Check that 15m crypto strategies don't have hardcoded drawdown thresholds.
    
    They should use profile-driven values from kalshi_crypto_15m.yaml
    """
    violations = []
    
    # 15m crypto agent files
    agent_files = [
        root_dir / "config/kalshi_btc_15m_agent_spec.py",
        root_dir / "config/eth_15m_agent_spec.py",
        root_dir / "config/sol_15m_agent_spec.py",
        root_dir / "config/xrp_15m_agent_spec.py",
        root_dir / "config/doge_15m_agent_spec.py",
    ]
    
    # Patterns for hardcoded drawdown
    drawdown_patterns = [
        r"daily_dd_limit\s*=\s*-0\.\d+",  # e.g., daily_dd_limit = -0.02
        r"drawdown_limit\s*=\s*-0\.\d+",  # e.g., drawdown_limit = -0.10
        r"dd_limit\s*=\s*-0\.\d+",  # e.g., dd_limit = -0.15
    ]
    
    for agent_file in agent_files:
        if not agent_file.exists():
            continue
        
        try:
            content = agent_file.read_text()
            for pattern in drawdown_patterns:
                if re.search(pattern, content):
                    violations.append(f"Hardcoded drawdown in {agent_file.relative_to(root_dir)}")
                    break
        except Exception:
            continue
    
    return violations


def main() -> int:
    """Run all checks and report results."""
    root_dir = Path(__file__).parent.parent
    
    print("=" * 70)
    print("CI Check: Canonical Risk Primitive Sources")
    print("=" * 70)
    
    all_violations = []
    
    # Check 1: No duplicate fee functions
    print("\n1. Checking for duplicate fee functions...")
    fee_violations = check_no_duplicate_fee_functions(root_dir)
    if fee_violations:
        print("   FAILED:")
        for v in fee_violations:
            print(f"   - {v}")
        all_violations.extend(fee_violations)
    else:
        print("   PASSED")
    
    # Check 2: No hardcoded fee formula
    print("\n2. Checking for hardcoded fee formulas...")
    formula_violations = check_no_hardcoded_fee_formula(root_dir)
    if formula_violations:
        print("   FAILED:")
        for v in formula_violations:
            print(f"   - {v}")
        all_violations.extend(formula_violations)
    else:
        print("   PASSED")
    
    # Check 3: No hardcoded drawdown in 15m strategies
    print("\n3. Checking for hardcoded drawdown in 15m crypto strategies...")
    dd_violations = check_no_hardcoded_drawdown_in_15m_strategies(root_dir)
    if dd_violations:
        print("   FAILED:")
        for v in dd_violations:
            print(f"   - {v}")
        all_violations.extend(dd_violations)
    else:
        print("   PASSED")
    
    # Summary
    print("\n" + "=" * 70)
    if all_violations:
        print(f"FAILED: {len(all_violations)} violation(s) found")
        print("=" * 70)
        return 1
    else:
        print("PASSED: All checks passed")
        print("=" * 70)
        return 0


if __name__ == "__main__":
    sys.exit(main())
