#!/usr/bin/env python3
"""
CI Check: Prevent test bypass patterns in production code.

This script scans the codebase for temporary test override patterns that
should never be present in production builds. It fails if any patterns are found.

Usage:
    python scripts/ci/check_test_bypasses.py

Exit codes:
    0: No test bypass patterns found
    1: Test bypass patterns found
"""
import os
import re
import sys
from pathlib import Path
from typing import List, Tuple

# Patterns that indicate temporary test bypasses
BYPASS_PATTERNS = [
    r"TESTING-OVERRIDE",
    r"TEMPORARILY DISABLED",
    r"TEMPORARY: Force",
    r"FORCING MINIMUM FOR TESTING",
    r"# TEMPORARY:",
    r"# HACK:",
    r"# FIXME.*test",
    r"# TODO.*remove.*test",
]

# Directories to scan
SCAN_DIRS = [
    "merid",
    "web",
    "agents",
    "core",
]

# File extensions to scan
SCAN_EXTENSIONS = {".py", ".ts", ".tsx", ".yaml", ".yml"}


def scan_file(filepath: Path) -> List[Tuple[int, str, str]]:
    """Scan a single file for bypass patterns.
    
    Returns:
        List of (line_number, pattern, line_content) tuples
    """
    matches = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(filepath.read_text(encoding="utf-8").splitlines(), 1):
                for pattern in BYPASS_PATTERNS:
                    if re.search(pattern, line, re.IGNORECASE):
                        matches.append((line_num, pattern, line.strip()))
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
    return matches


def main() -> int:
    """Main entry point."""
    repo_root = Path(__file__).parent.parent.parent
    all_matches = []
    
    print("Scanning for test bypass patterns...")
    print(f"Repository root: {repo_root}")
    print(f"Scan directories: {SCAN_DIRS}")
    print(f"Scan extensions: {SCAN_EXTENSIONS}")
    print()
    
    for scan_dir in SCAN_DIRS:
        dir_path = repo_root / scan_dir
        if not dir_path.exists():
            print(f"Skipping {scan_dir} (not found)")
            continue
        
        print(f"Scanning {scan_dir}...")
        for filepath in dir_path.rglob("*"):
            if filepath.is_file() and filepath.suffix in SCAN_EXTENSIONS:
                # Skip test files (they may have legitimate test patterns)
                if "test" in filepath.name.lower() or filepath.parent.name == "tests":
                    continue
                
                matches = scan_file(filepath)
                if matches:
                    all_matches.extend([(filepath, *m) for m in matches])
    
    if all_matches:
        print("\n❌ TEST BYPASS PATTERNS FOUND")
        print("=" * 80)
        for filepath, line_num, pattern, line_content in all_matches:
            print(f"\n{filepath}:{line_num}")
            print(f"  Pattern: {pattern}")
            print(f"  Line: {line_content}")
        print("\n" + "=" * 80)
        print(f"\nTotal matches: {len(all_matches)}")
        print("\nThese patterns indicate temporary test overrides that should be removed")
        print("before deploying to production. See .windsurf/tickets/TEST_BYPASS_LEDGER.md")
        return 1
    else:
        print("\n✅ No test bypass patterns found")
        print("Code is clean of temporary test overrides")
        return 0


if __name__ == "__main__":
    sys.exit(main())
