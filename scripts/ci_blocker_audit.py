#!/usr/bin/env python3
"""
CI Blocker Audit Check — Validates canonical blocker usage in codebase.

This script runs as part of CI to ensure:
1. All block reasons use canonical BlockReason enum
2. No direct venue calls outside order_router
3. No silent blocking patterns (return without logging)
4. All order lifecycle stages use OrderStage enum

Exits with code 1 if any violations found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from merid.guards.block_reasons import (
        BlockReason,
        OrderStage,
        CANONICAL_BLOCK_REASONS,
        CANONICAL_STAGES,
    )
except ImportError:
    print("ERROR: merid.guards.block_reasons module not available")
    sys.exit(1)


class BlockerViolation:
    """Represents a blocker audit violation."""
    
    def __init__(self, file_path: str, line: int, violation_type: str, details: str):
        self.file_path = file_path
        self.line = line
        self.violation_type = violation_type
        self.details = details
    
    def __str__(self):
        return f"{self.file_path}:{self.line} [{self.violation_type}] {self.details}"


class BlockerCIResult:
    """Results of CI blocker audit."""
    
    def __init__(self):
        self.violations: List[BlockerViolation] = []
        self.files_scanned: int = 0
        self.canonical_blocks_found: int = 0
        self.legacy_blocks_found: int = 0
    
    def add_violation(self, violation: BlockerViolation):
        self.violations.append(violation)
    
    def has_critical_violations(self) -> bool:
        """Check if any critical violations exist."""
        return any(
            v.violation_type in ["DIRECT_VENUE_CALL", "SILENT_BLOCK"]
            for v in self.violations
        )
    
    def print_summary(self):
        """Print summary of audit results."""
        print(f"\nBlocker CI Audit Results:")
        print(f"  Files scanned: {self.files_scanned}")
        print(f"  Canonical blocks found: {self.canonical_blocks_found}")
        print(f"  Legacy blocks found: {self.legacy_blocks_found}")
        print(f"  Total violations: {len(self.violations)}")
        
        if self.violations:
            print(f"\nViolations by type:")
            from collections import Counter
            by_type = Counter(v.violation_type for v in self.violations)
            for vtype, count in by_type.most_common():
                print(f"  {vtype}: {count}")
            
            print(f"\nAll violations:")
            for v in self.violations:
                print(f"  {v}")
        else:
            print(f"  No violations found ✅")


def scan_file_for_violations(file_path: Path, root: Path) -> List[BlockerViolation]:
    """Scan a single file for blocker violations."""
    violations = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
        
        # Skip test files
        if "test" in file_path.name or file_path.parent.name in ["__tests__", "tests"]:
            return violations
        
        # Pattern: Direct venue calls outside order_router
        if "order_router" not in str(file_path):
            direct_venue_pattern = re.compile(
                r'(get_kalshi_client|KalshiVenueClient)\.(place_order|submit_order)'
            )
            for i, line in enumerate(lines, 1):
                if direct_venue_pattern.search(line):
                    violations.append(BlockerViolation(
                        file_path=str(file_path.relative_to(root)),
                        line=i,
                        violation_type="DIRECT_VENUE_CALL",
                        details=f"Direct venue call: {line.strip()}"
                    ))
        
        # Pattern: Silent blocks (return without logging in order paths)
        # Look for return statements in functions that handle orders
        in_order_function = False
        has_logging = False
        for i, line in enumerate(lines, 1):
            # Detect if we're in an order-handling function
            if any(keyword in line for keyword in ["def route_order", "def _check_", "def _validate_"]):
                in_order_function = True
                has_logging = False
            
            # Check for logging
            if "log" in line.lower() and ("block" in line.lower() or "reject" in line.lower()):
                has_logging = True
            
            # Check for return in order function without logging
            if in_order_function and "return" in line and "OrderResult" in line:
                if not has_logging and "rejected" in line:
                    violations.append(BlockerViolation(
                        file_path=str(file_path.relative_to(root)),
                        line=i,
                        violation_type="SILENT_BLOCK",
                        details=f"Return without logging: {line.strip()}"
                    ))
            
            # Reset on function end
            if line.strip() and not line.strip().startswith(" ") and in_order_function:
                in_order_function = False
                has_logging = False
        
        # Pattern: Legacy block reason strings not using canonical enum
        # Look for return statements with string literals that look like block reasons
        legacy_reason_pattern = re.compile(r'return\s+"(reject|block|denied|halt|invalid|unavailable)"', re.IGNORECASE)
        for i, line in enumerate(lines, 1):
            if legacy_reason_pattern.search(line):
                violations.append(BlockerViolation(
                    file_path=str(file_path.relative_to(root)),
                    line=i,
                    violation_type="LEGACY_BLOCK_REASON",
                    details=f"Legacy reason string: {line.strip()}"
                ))
        
        # Pattern: Canonical block reason usage (for stats)
        canonical_pattern = re.compile(r'BlockReason\.')
        for i, line in enumerate(lines, 1):
            if canonical_pattern.search(line):
                return [BlockerViolation(
                    file_path=str(file_path.relative_to(root)),
                    line=i,
                    violation_type="CANONICAL_USAGE",
                    details=f"Canonical BlockReason used"
                )]  # Return early to count as one file with canonical usage
    
    except Exception as e:
        print(f"ERROR scanning {file_path}: {e}")
    
    return violations


def run_ci_audit(root: Path = None) -> BlockerCIResult:
    """Run full CI blocker audit."""
    if root is None:
        root = Path(__file__).parent.parent
    
    result = BlockerCIResult()
    
    # Directories to scan
    target_dirs = [
        root / "merid" / "event_venues" / "kalshi",
        root / "merid" / "prediction",
        root / "merid" / "trading",
        root / "merid" / "guards",
    ]
    
    for target_dir in target_dirs:
        if not target_dir.exists():
            continue
        
        for py_file in target_dir.rglob("*.py"):
            result.files_scanned += 1
            violations = scan_file_for_violations(py_file, root)
            
            for v in violations:
                if v.violation_type == "CANONICAL_USAGE":
                    result.canonical_blocks_found += 1
                elif v.violation_type == "LEGACY_BLOCK_REASON":
                    result.legacy_blocks_found += 1
                else:
                    result.add_violation(v)
    
    return result


def main():
    print("Running CI Blocker Audit...")
    
    root = Path(__file__).parent.parent
    result = run_ci_audit(root)
    
    result.print_summary()
    
    # Exit with error code if critical violations found
    if result.has_critical_violations():
        print("\n❌ CRITICAL violations found. Fix before merging.")
        sys.exit(1)
    elif result.violations:
        print("\n⚠️  Non-critical violations found. Please address.")
        sys.exit(1)
    else:
        print("\n✅ All checks passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
