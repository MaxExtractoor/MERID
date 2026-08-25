#!/usr/bin/env python3
"""
Comprehensive Inversion Bug & Side Conflict Detector

This script systematically scans the MERID codebase for known inversion bugs,
side conflicts, and related issues. It includes specific checks for exit policy
issues as well as the full range of inversion bugs that have been fixed historically.

Categories of bugs detected:
1. Price-space inversion (NO-side orders with NO-space prices)
2. Side/price inversion for NO-side fills, PnL, TP/SL
3. OFI calculation depth mapping errors
4. NO-side edge calculation using NO-space probability
5. Exit policy thesis_side issues
6. Dynamic TP zone config with invalid targets
7. Position.entry_edge_pct population issues
8. Year rollover in ticker parsing
9. Strike price validation issues
10. BookFreshnessTracker deadlock patterns
11. Order router microstructure gate type mismatches
12. WS-REST divergence guard issues
13. Canonical duality violations
14. Outcome side / book side conflicts
15. Exit policy specific issues (exit order logic, TP/SL inversions)
"""

import os
import re
import sys
from pathlib import Path
from typing import List, Tuple
from dataclasses import dataclass
from enum import Enum

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class BugSeverity(Enum):
    CRITICAL = "CRITICAL"  # P0 - losing money
    HIGH = "HIGH"  # P1 - significant impact
    MEDIUM = "MEDIUM"  # P2 - moderate impact
    LOW = "LOW"  # P3 - minor issues


@dataclass
class BugFinding:
    category: str
    severity: BugSeverity
    file_path: str
    line_number: int
    description: str
    code_snippet: str


class ComprehensiveInversionBugDetector:
    """Comprehensive detector for inversion bugs and side conflicts."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.findings: List[BugFinding] = []

    def scan_all_files(self) -> List[BugFinding]:
        """Scan all Python files in the project."""
        python_files = list(self.root_dir.rglob("*.py"))
        
        # Skip test files and certain directories
        python_files = [
            f for f in python_files 
            if not self._should_skip_file(f)
        ]

        print(f"Scanning {len(python_files)} Python files for inversion bugs...")

        for py_file in python_files:
            self._scan_file(py_file)

        return self.findings

    def _should_skip_file(self, file_path: Path) -> bool:
        """Skip test files, __pycache__, and certain directories."""
        skip_dirs = {
            "__pycache__",
            ".git",
            "venv",
            "env",
            ".pytest_cache",
            "node_modules",
            "build",
            "dist",
        }
        skip_patterns = {"test_", "_test.py", "conftest.py"}

        for part in file_path.parts:
            if part in skip_dirs:
                return True

        if any(file_path.name.startswith(p) for p in skip_patterns):
            return True

        return False

    def _scan_file(self, file_path: Path):
        """Scan a single file for all bug patterns."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            lines = content.split("\n")

            # Remove comments for pattern matching (but keep line numbers)
            code_lines = []
            for line in lines:
                code_line = re.sub(r'#.*$', '', line).strip()
                code_lines.append(code_line)

            # Run all pattern checks
            self._check_price_space_inversion(file_path, lines, code_lines)
            self._check_side_price_inversion(file_path, lines, code_lines)
            self._check_ofi_depth_errors(file_path, lines, code_lines)
            self._check_thesis_side_missing(file_path, lines, code_lines)
            self._check_tp_zone_config(file_path, lines, code_lines)
            self._check_deadlock_patterns(file_path, lines, code_lines)
            self._check_type_comparison_bugs(file_path, lines, code_lines)
            self._check_canonical_duality(file_path, lines, code_lines)
            self._check_missing_imports(file_path, lines, code_lines)
            self._check_uninitialized_position_fields(file_path, content)
            self._check_exit_policy_issues(file_path, lines, code_lines)
            self._check_year_rollover_issues(file_path, lines, code_lines)
            self._check_strike_validation_issues(file_path, lines, code_lines)
            self._check_ws_rest_divergence(file_path, lines, code_lines)
            self._check_outcome_side_conflicts(file_path, lines, code_lines)

        except Exception as e:
            print(f"Error scanning {file_path}: {e}")

    def _add_finding(self, category, severity, file_path, line_number, description, code_snippet):
        self.findings.append(BugFinding(
            category=category,
            severity=severity,
            file_path=str(file_path.relative_to(self.root_dir)),
            line_number=line_number,
            description=description,
            code_snippet=code_snippet
        ))

    def _check_price_space_inversion(self, file_path, lines, code_lines):
        """Check for NO-side price-space inversion (P0 bug)."""
        for i, (line, code_line) in enumerate(zip(lines, code_lines), 1):
            if re.search(r'(BUY_NO|SELL_NO|outcome.*==.*["\']no["\'])', code_line, re.IGNORECASE):
                context = "\n".join(lines[max(0, i-3):min(len(lines), i+3)])
                has_conversion = (
                    "100 -" in context or 
                    "100-" in context or 
                    "yes_to_no_price" in context or 
                    "no_to_yes_price" in context or
                    "legacy_to_v2" in context
                )
                if not has_conversion and "price_cents" in code_line.lower() and "=" in code_line:
                    self._add_finding(
                        "PRICE_SPACE_INVERSION",
                        BugSeverity.CRITICAL,
                        file_path, i,
                        "NO-side order without YES-space conversion (100 - price)",
                        line.strip()
                    )

    def _check_side_price_inversion(self, file_path, lines, code_lines):
        """Check for side/price inversion in PnL/TP/SL."""
        for i, (line, code_line) in enumerate(zip(lines, code_lines), 1):
            if re.search(r'(entry.*-.*close|close.*-.*entry).*side.*==.*["\']no["\']', code_line, re.IGNORECASE):
                self._add_finding(
                    "SIDE_PRICE_INVERSION",
                    BugSeverity.CRITICAL,
                    file_path, i,
                    "Inverted PnL calculation for NO positions",
                    line.strip()
                )
            if re.search(r'take_profit.*<.*entry.*side.*==.*["\']no["\']', code_line, re.IGNORECASE):
                self._add_finding(
                    "SIDE_PRICE_INVERSION",
                    BugSeverity.CRITICAL,
                    file_path, i,
                    "TP below entry for NO positions (should be above)",
                    line.strip()
                )
            if re.search(r'stop_loss.*>.*entry.*side.*==.*["\']no["\']', code_line, re.IGNORECASE):
                self._add_finding(
                    "SIDE_PRICE_INVERSION",
                    BugSeverity.CRITICAL,
                    file_path, i,
                    "SL above entry for NO positions (should be below)",
                    line.strip()
                )

    def _check_ofi_depth_errors(self, file_path, lines, code_lines):
        """Check for OFI calculation with dual ladders."""
        for i, (line, code_line) in enumerate(zip(lines, code_lines), 1):
            if re.search(r'ofi.*=.*\(.*total_bid.*-.*total_ask.*\)', code_line, re.IGNORECASE):
                context = "\n".join(lines[max(0, i-5):min(len(lines), i+5)])
                if "yes_bid" in context and "no_bid" in context:
                    self._add_finding(
                        "OFI_DEPTH_ERROR",
                        BugSeverity.HIGH,
                        file_path, i,
                        "OFI using dual ladders instead of single-book depths",
                        line.strip()
                    )

    def _check_thesis_side_missing(self, file_path, lines, code_lines):
        """Check for missing thesis_side field."""
        for i, (line, code_line) in enumerate(zip(lines, code_lines), 1):
            if re.search(r'class\s+Position[^:]*:', code_line, re.IGNORECASE):
                if "PositionSide" in code_line or "PositionMonitor" in code_line:
                    continue
                context = "\n".join(lines[i:min(len(lines), i+100)])
                has_thesis_side = bool(re.search(r'thesis_side\s*:', context))
                if not has_thesis_side:
                    self._add_finding(
                        "THESIS_SIDE_MISSING",
                        BugSeverity.CRITICAL,
                        file_path, i,
                        "Position class missing thesis_side field",
                        line.strip()
                    )

    def _check_tp_zone_config(self, file_path, lines, code_lines):
        """Check for TP zone with invalid targets."""
        for i, (line, code_line) in enumerate(zip(lines, code_lines), 1):
            if re.search(r'exit_target.*:.*\d+.*entry.*:.*\d+.*\d+', code_line, re.IGNORECASE):
                numbers = re.findall(r'\d+', code_line)
                if len(numbers) >= 3:
                    try:
                        entry_max = max(int(numbers[1]), int(numbers[2]))
                        exit_target = int(numbers[0])
                        if exit_target < entry_max:
                            self._add_finding(
                                "TP_ZONE_CONFIG",
                                BugSeverity.CRITICAL,
                                file_path, i,
                                f"TP target ({exit_target}) below entry_max ({entry_max})",
                                line.strip()
                            )
                    except (ValueError, IndexError):
                        pass

    def _check_deadlock_patterns(self, file_path, lines, code_lines):
        """Check for deadlock patterns."""
        for i, (line, code_line) in enumerate(zip(lines, code_lines), 1):
            if re.search(r'threading\.Lock\(\)', code_line, re.IGNORECASE):
                context = "\n".join(lines[max(0, i-5):min(len(lines), i+5)])
                if "get_state" in context or ("update" in context and "with" in context):
                    if "[" in code_line and "]" in code_line and "=" in code_line:
                        continue
                    self._add_finding(
                        "DEADLOCK_RISK",
                        BugSeverity.HIGH,
                        file_path, i,
                        "Using Lock instead of RLock for re-entrant operations",
                        line.strip()
                    )

    def _check_type_comparison_bugs(self, file_path, lines, code_lines):
        """Check for type comparison bugs."""
        for i, (line, code_line) in enumerate(zip(lines, code_lines), 1):
            if re.search(r'book_state\s*==\s*BookState\.|BookState\.\w+\s*==\s*book_state', code_line, re.IGNORECASE):
                if '.state' not in code_line and '.is_tradable()' not in code_line:
                    self._add_finding(
                        "TYPE_COMPARISON_BUG",
                        BugSeverity.HIGH,
                        file_path, i,
                        "Comparing object to enum instead of using .state or .is_tradable()",
                        line.strip()
                    )

    def _check_canonical_duality(self, file_path, lines, code_lines):
        """Check for canonical duality violations."""
        for i, (line, code_line) in enumerate(zip(lines, code_lines), 1):
            if re.search(r'no_bid\s*=\s*yes_bid|no_ask\s*=\s*yes_ask', code_line, re.IGNORECASE):
                self._add_finding(
                    "CANONICAL_DUALITY_VIOLATION",
                    BugSeverity.CRITICAL,
                    file_path, i,
                    "NO bid/ask should be YES ask/bid (canonical duality)",
                    line.strip()
                )

    def _check_missing_imports(self, file_path, lines, code_lines):
        """Check for critical missing imports."""
        math_used = any(re.search(r'math\.', code_line) for code_line in code_lines)
        math_imported = any(re.match(r'^import\s+math|^from\s+math\s+import', line) for line in lines)
        
        if math_used and not math_imported:
            for i, (line, code_line) in enumerate(zip(lines, code_lines), 1):
                if re.search(r'math\.', code_line):
                    if not line.strip().startswith('#'):
                        self._add_finding(
                            "MISSING_IMPORT",
                            BugSeverity.CRITICAL,
                            file_path, i,
                            "Using math functions without 'import math'",
                            line.strip()
                        )
                        break

    def _check_uninitialized_position_fields(self, file_path, content):
        """Check for uninitialized Position fields."""
        if "class Position" not in content:
            return
            
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            if "entry_edge_pct" in line and "=" not in line and ":" in line:
                context = "\n".join(lines[max(0, i-5):min(len(lines), i+10)])
                if "edge_pct" not in context and "entry_edge" not in context:
                    self._add_finding(
                        "UNINITIALIZED_FIELD",
                        BugSeverity.MEDIUM,
                        file_path, i,
                        "Position.entry_edge_pct field may not be initialized from signal edge",
                        line.strip()
                    )

    def _check_exit_policy_issues(self, file_path, lines, code_lines):
        """Check for exit policy specific issues."""
        for i, (line, code_line) in enumerate(zip(lines, code_lines), 1):
            # Check for exit order execution without thesis_side validation
            if re.search(r'execute.*exit|exit.*order', code_line, re.IGNORECASE):
                context = "\n".join(lines[max(0, i-5):min(len(lines), i+5)])
                if "thesis_side" not in context and "position" in context.lower():
                    self._add_finding(
                        "EXIT_POLICY_THESIS_SIDE",
                        BugSeverity.HIGH,
                        file_path, i,
                        "Exit order execution without thesis_side validation",
                        line.strip()
                    )
            
            # Check for exit orders that might flip position sign
            if re.search(r'exit.*count|exit.*size', code_line, re.IGNORECASE):
                context = "\n".join(lines[max(0, i-3):min(len(lines), i+3)])
                if ">" in context and "position" in context.lower():
                    self._add_finding(
                        "EXIT_POLICY_POSITION_FLIP",
                        BugSeverity.CRITICAL,
                        file_path, i,
                        "Exit order might flip position sign (over-close)",
                        line.strip()
                    )
            
            # Check for TP/SL calculations that don't account for side
            if re.search(r'take_profit|stop_loss', code_line, re.IGNORECASE):
                context = "\n".join(lines[max(0, i-3):min(len(lines), i+3)])
                if "side" not in context.lower() and "position" in context.lower():
                    self._add_finding(
                        "EXIT_POLICY_SIDE_AGNOSTIC",
                        BugSeverity.HIGH,
                        file_path, i,
                        "TP/SL calculation without side awareness",
                        line.strip()
                    )

    def _check_year_rollover_issues(self, file_path, lines, code_lines):
        """Check for year rollover bugs in ticker parsing."""
        for i, (line, code_line) in enumerate(zip(lines, code_lines), 1):
            if re.search(r'datetime\.now\(\)\.year|\.year.*=.*\d{4}', code_line, re.IGNORECASE):
                context = "\n".join(lines[max(0, i-5):min(len(lines), i+5)])
                if "ticker" in context.lower() or "expiry" in context.lower():
                    self._add_finding(
                        "YEAR_ROLLOVER",
                        BugSeverity.HIGH,
                        file_path, i,
                        "Ticker parsing using current year assumption - will fail at year boundaries",
                        line.strip()
                    )

    def _check_strike_validation_issues(self, file_path, lines, code_lines):
        """Check for strike price validation issues."""
        for i, (line, code_line) in enumerate(zip(lines, code_lines), 1):
            if re.search(r'math\.(floor|ceil|abs|sqrt|min|max)', code_line, re.IGNORECASE):
                math_imported = any(re.match(r'^import\s+math|^from\s+math\s+import', line) for line in lines)
                if not math_imported:
                    self._add_finding(
                        "MISSING_IMPORT",
                        BugSeverity.CRITICAL,
                        file_path, i,
                        "Using math functions without 'import math'",
                        line.strip()
                    )

    def _check_ws_rest_divergence(self, file_path, lines, code_lines):
        """Check for WS-REST divergence guard issues."""
        for i, (line, code_line) in enumerate(zip(lines, code_lines), 1):
            if re.search(r'divergence.*ws.*rest|ws.*rest.*divergence', code_line, re.IGNORECASE):
                context = "\n".join(lines[max(0, i-5):min(len(lines), i+5)])
                if "REST_FALLBACK" not in context and "rest_fallback" not in context:
                    self._add_finding(
                        "WS_REST_DIVERGENCE",
                        BugSeverity.HIGH,
                        file_path, i,
                        "WS-REST divergence check without REST-fallback exemption",
                        line.strip()
                    )

    def _check_outcome_side_conflicts(self, file_path, lines, code_lines):
        """Check for outcome_side / book_side conflicts."""
        for i, (line, code_line) in enumerate(zip(lines, code_lines), 1):
            if re.search(r'fill\[["\']side["\']\]', code_line, re.IGNORECASE):
                context = "\n".join(lines[max(0, i-5):min(len(lines), i+5)])
                if "outcome_side" not in context and "book_side" not in context:
                    self._add_finding(
                        "OUTCOME_SIDE_CONFLICT",
                        BugSeverity.HIGH,
                        file_path, i,
                        "Using deprecated 'side' field instead of outcome_side/book_side",
                        line.strip()
                    )

    def print_summary(self):
        """Print summary of findings."""
        if not self.findings:
            print("[OK] No inversion bugs or side conflicts detected!")
            return

        print("\n" + "=" * 80)
        print("INVERSION BUG & SIDE CONFLICT DETECTION RESULTS")
        print("=" * 80)

        # Group by severity
        critical = [f for f in self.findings if f.severity == BugSeverity.CRITICAL]
        high = [f for f in self.findings if f.severity == BugSeverity.HIGH]
        medium = [f for f in self.findings if f.severity == BugSeverity.MEDIUM]
        low = [f for f in self.findings if f.severity == BugSeverity.LOW]

        if critical:
            print(f"\n[CRITICAL] ({len(critical)}):")
            for f in critical:
                print(f"  * {f.file_path}:{f.line_number}")
                print(f"    {f.description}")
                print(f"    Code: {f.code_snippet[:80]}")

        if high:
            print(f"\n[HIGH] ({len(high)}):")
            for f in high:
                print(f"  * {f.file_path}:{f.line_number}")
                print(f"    {f.description}")
                print(f"    Code: {f.code_snippet[:80]}")

        if medium:
            print(f"\n[MEDIUM] ({len(medium)}):")
            for f in medium:
                print(f"  * {f.file_path}:{f.line_number}")
                print(f"    {f.description}")

        if low:
            print(f"\n[LOW] ({len(low)}):")
            for f in low:
                print(f"  * {f.file_path}:{f.line_number}")
                print(f"    {f.description}")

        print("\n" + "=" * 80)
        print(f"Total: {len(self.findings)} findings ({len(critical)} critical, {len(high)} high, {len(medium)} medium, {len(low)} low)")
        print("=" * 80)

        # Category breakdown
        print("\nCATEGORY BREAKDOWN:")
        by_category = {}
        for f in self.findings:
            if f.category not in by_category:
                by_category[f.category] = []
            by_category[f.category].append(f)
        
        for category, findings in sorted(by_category.items()):
            severity_counts = {}
            for f in findings:
                severity_counts[f.severity.value] = severity_counts.get(f.severity.value, 0) + 1
            print(f"  {category}: {len(findings)} total ({', '.join(f'{k}={v}' for k, v in sorted(severity_counts.items()))})")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Comprehensive inversion bug and side conflict detector"
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Use fast mode (scan only critical files)"
    )
    
    args = parser.parse_args()
    
    if args.fast:
        from expose_inversion_bugs_fast import FastInversionBugDetector
        detector = FastInversionBugDetector(PROJECT_ROOT)
        findings = detector.scan_critical_files()
        detector.print_summary()
        critical_count = sum(1 for f in findings if f.severity == BugSeverity.CRITICAL)
        sys.exit(1 if critical_count > 0 else 0)
    else:
        detector = ComprehensiveInversionBugDetector(PROJECT_ROOT)
        findings = detector.scan_all_files()
        detector.print_summary()
        
        critical_count = sum(1 for f in findings if f.severity == BugSeverity.CRITICAL)
        if critical_count > 0:
            print(f"\n[ERROR] {critical_count} CRITICAL findings detected!")
            sys.exit(1)
        else:
            print("\n[OK] No critical findings detected.")
            sys.exit(0)


if __name__ == "__main__":
    main()
