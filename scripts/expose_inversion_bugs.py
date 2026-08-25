#!/usr/bin/env python3
"""
Inversion Bug & Side Conflict Detector

This script systematically scans the MERID codebase for known inversion bugs,
side conflicts, and related issues that have been fixed historically.
It serves as a regression guard to prevent these bugs from reappearing.

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
"""

import ast
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
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
    """Represents a potential bug finding."""
    category: str
    severity: BugSeverity
    file_path: str
    line_number: int
    description: str
    code_snippet: str
    pattern_matched: str
    context: str = ""

    def __str__(self):
        return f"[{self.severity.value}] {self.category}: {self.description}\n  File: {self.file_path}:{self.line_number}\n  Pattern: {self.pattern_matched}\n  Code: {self.code_snippet}\n"


class InversionBugDetector:
    """Main detector class for inversion bugs and side conflicts."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.findings: List[BugFinding] = []
        self.scanned_files: Set[str] = set()

    def scan_all(self) -> List[BugFinding]:
        """Run all detection patterns."""
        print(f"Scanning {self.root_dir} for inversion bugs and side conflicts...")

        # Get all Python files
        python_files = list(self.root_dir.rglob("*.py"))
        print(f"Found {len(python_files)} Python files to scan")

        for py_file in python_files:
            if self._should_skip_file(py_file):
                continue
            self._scan_file(py_file)

        print(f"\nScan complete. Scanned {len(self.scanned_files)} files.")
        print(f"Found {len(self.findings)} potential issues.\n")

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

        # Check if any parent directory is in skip_dirs
        for part in file_path.parts:
            if part in skip_dirs:
                return True

        # Check filename patterns
        if any(file_path.name.startswith(p) for p in skip_patterns):
            return True

        return False

    def _scan_file(self, file_path: Path):
        """Scan a single Python file for all bug patterns."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            self.scanned_files.add(str(file_path))

            # Parse AST for structural analysis
            try:
                tree = ast.parse(content, filename=str(file_path))
            except SyntaxError:
                # Skip files with syntax errors
                return

            # Run all detection patterns
            self._detect_price_space_inversion(file_path, content, tree)
            self._detect_side_price_inversion(file_path, content, tree)
            self._detect_ofi_depth_errors(file_path, content, tree)
            self._detect_no_space_probability_usage(file_path, content, tree)
            self._detect_thesis_side_issues(file_path, content, tree)
            self._detect_tp_zone_config_issues(file_path, content, tree)
            self._detect_entry_edge_pct_issues(file_path, content, tree)
            self._detect_year_rollover_issues(file_path, content, tree)
            self._detect_strike_validation_issues(file_path, content, tree)
            self._detect_deadlock_patterns(file_path, content, tree)
            self._detect_type_comparison_bugs(file_path, content, tree)
            self._detect_ws_rest_divergence_issues(file_path, content, tree)
            self._detect_canonical_duality_violations(file_path, content, tree)
            self._detect_outcome_side_conflicts(file_path, content, tree)
            self._detect_missing_imports(file_path, content, tree)
            self._detect_uninitialized_fields(file_path, content, tree)

        except Exception as e:
            print(f"Error scanning {file_path}: {e}")

    def _add_finding(
        self,
        category: str,
        severity: BugSeverity,
        file_path: Path,
        line_number: int,
        description: str,
        code_snippet: str,
        pattern_matched: str,
        context: str = "",
    ):
        """Add a bug finding to the results."""
        finding = BugFinding(
            category=category,
            severity=severity,
            file_path=str(file_path.relative_to(self.root_dir)),
            line_number=line_number,
            description=description,
            code_snippet=code_snippet,
            pattern_matched=pattern_matched,
            context=context,
        )
        self.findings.append(finding)

    def _detect_price_space_inversion(self, file_path: Path, content: str, tree: ast.AST):
        """
        Detect price-space inversion bugs where NO-side orders use NO-space prices
        instead of YES-space prices (Kalshi V2 requires YES-space wire prices).
        """
        lines = content.split("\n")

        # Pattern 1: Direct NO price usage without conversion
        pattern1 = re.compile(
            r'(price.*=.*outcome.*==.*["\']no["\']|price.*=.*side.*==.*["\']no["\'])',
            re.IGNORECASE,
        )

        # Pattern 2: Missing conversion when outcome is "no"
        pattern2 = re.compile(
            r'if\s+outcome\s*==\s*["\']no["\'][^}]*price\s*=',
            re.IGNORECASE | re.DOTALL,
        )

        # Pattern 3: Order construction with NO price without 100 - price
        pattern3 = re.compile(
            r'(BUY_NO|SELL_NO).*price.*=.*[0-9]+(?!\s*\+\s*100\s*-\s*price)',
            re.IGNORECASE,
        )

        for i, line in enumerate(lines, 1):
            for pattern in [pattern1, pattern2, pattern3]:
                if pattern.search(line):
                    # Check if there's a conversion nearby (100 - price)
                    context_start = max(0, i - 3)
                    context_end = min(len(lines), i + 3)
                    context = "\n".join(lines[context_start:context_end])

                    if "100 -" not in context and "100-" not in context:
                        self._add_finding(
                            category="PRICE_SPACE_INVERSION",
                            severity=BugSeverity.CRITICAL,
                            file_path=file_path,
                            line_number=i,
                            description="Potential NO-side price-space inversion - NO price used without YES-space conversion (100 - price)",
                            code_snippet=line.strip(),
                            pattern_matched="NO price without conversion",
                            context=context,
                        )

    def _detect_side_price_inversion(self, file_path: Path, content: str, tree: ast.AST):
        """
        Detect side/price inversion for NO-side fills, PnL, TP/SL calculations.
        """
        lines = content.split("\n")

        # Pattern 1: Inverted PnL calculation for NO positions
        pattern1 = re.compile(
            r'(entry.*-.*close|close.*-.*entry).*side.*==.*["\']no["\']',
            re.IGNORECASE,
        )

        # Pattern 2: TP below entry for NO positions
        pattern2 = re.compile(
            r'take_profit.*<.*entry.*side.*==.*["\']no["\']',
            re.IGNORECASE,
        )

        # Pattern 3: SL above entry for NO positions
        pattern3 = re.compile(
            r'stop_loss.*>.*entry.*side.*==.*["\']no["\']',
            re.IGNORECASE,
        )

        for i, line in enumerate(lines, 1):
            for pattern in [pattern1, pattern2, pattern3]:
                if pattern.search(line):
                    self._add_finding(
                        category="SIDE_PRICE_INVERSION",
                        severity=BugSeverity.CRITICAL,
                        file_path=file_path,
                        line_number=i,
                        description="Potential side/price inversion in PnL or TP/SL calculation for NO positions",
                        code_snippet=line.strip(),
                        pattern_matched="Inverted NO-side calculation",
                    )

    def _detect_ofi_depth_errors(self, file_path: Path, content: str, tree: ast.AST):
        """
        Detect OFI (Order Flow Imbalance) calculation errors where dual ladders
        are passed instead of single-book depths.
        """
        lines = content.split("\n")

        # Pattern: OFI calculation with total_bid == total_ask (dual ladder bug)
        pattern = re.compile(
            r'ofi.*=.*\(.*total_bid.*-.*total_ask.*\)',
            re.IGNORECASE,
        )

        for i, line in enumerate(lines, 1):
            if pattern.search(line):
                # Check if this is using dual ladders (both yes and no depths)
                context_start = max(0, i - 5)
                context_end = min(len(lines), i + 5)
                context = "\n".join(lines[context_start:context_end])

                if "yes_bid" in context and "no_bid" in context:
                    self._add_finding(
                        category="OFI_DEPTH_ERROR",
                        severity=BugSeverity.HIGH,
                        file_path=file_path,
                        line_number=i,
                        description="OFI calculation using dual ladders - should use single-book depths (yes_depth - no_depth)",
                        code_snippet=line.strip(),
                        pattern_matched="Dual ladder OFI",
                        context=context,
                    )

    def _detect_no_space_probability_usage(self, file_path: Path, content: str, tree: ast.AST):
        """
        Detect NO-side edge calculation using NO-space probability instead of
        canonical YES-space probability.
        """
        lines = content.split("\n")

        # Pattern: Edge calculation with NO-space probability
        pattern = re.compile(
            r'(edge|p_hat|probability).*no.*cents(?!\s*\|\|\s*yes)',
            re.IGNORECASE,
        )

        for i, line in enumerate(lines, 1):
            if pattern.search(line):
                # Check if this is in an edge calculation context
                context_start = max(0, i - 3)
                context_end = min(len(lines), i + 3)
                context = "\n".join(lines[context_start:context_end])

                if "edge" in context.lower() and "no" in context.lower():
                    self._add_finding(
                        category="NO_SPACE_PROBABILITY",
                        severity=BugSeverity.HIGH,
                        file_path=file_path,
                        line_number=i,
                        description="Edge calculation potentially using NO-space probability instead of canonical YES-space",
                        code_snippet=line.strip(),
                        pattern_matched="NO-space probability in edge calc",
                        context=context,
                    )

    def _detect_thesis_side_issues(self, file_path: Path, content: str, tree: ast.AST):
        """
        Detect exit policy issues related to thesis_side field.
        """
        lines = content.split("\n")

        # Pattern 1: Missing thesis_side field in Position class
        pattern1 = re.compile(r'class\s+Position.*:', re.IGNORECASE)

        # Pattern 2: Exit order logic without thesis_side check
        pattern2 = re.compile(
            r'execute.*exit.*order(?![^}]*thesis_side)',
            re.IGNORECASE | re.DOTALL,
        )

        # Pattern 3: Position construction without thesis_side
        pattern3 = re.compile(
            r'Position\([^)]*\)(?![^}]*thesis_side)',
            re.IGNORECASE | re.DOTALL,
        )

        for i, line in enumerate(lines, 1):
            if pattern1.search(line):
                # Check if thesis_side is defined in the class
                context_start = i
                context_end = min(len(lines), i + 30)
                context = "\n".join(lines[context_start:context_end])

                if "thesis_side" not in context:
                    self._add_finding(
                        category="THESIS_SIDE_MISSING",
                        severity=BugSeverity.CRITICAL,
                        file_path=file_path,
                        line_number=i,
                        description="Position class missing thesis_side field (required for exit policy)",
                        code_snippet=line.strip(),
                        pattern_matched="Position without thesis_side",
                        context=context,
                    )

            if pattern2.search(line):
                context_start = max(0, i - 5)
                context_end = min(len(lines), i + 5)
                context = "\n".join(lines[context_start:context_end])

                if "thesis_side" not in context:
                    self._add_finding(
                        category="THESIS_SIDE_CHECK_MISSING",
                        severity=BugSeverity.HIGH,
                        file_path=file_path,
                        line_number=i,
                        description="Exit order execution without thesis_side validation",
                        code_snippet=line.strip(),
                        pattern_matched="Exit without thesis_side check",
                        context=context,
                    )

    def _detect_tp_zone_config_issues(self, file_path: Path, content: str, tree: ast.AST):
        """
        Detect dynamic TP zone configuration issues where targets are below entry range.
        """
        lines = content.split("\n")

        # Pattern: TP zone with exit_target below entry range
        pattern = re.compile(
            r'exit_target.*:.*\d+.*entry.*:.*\d+.*\d+',
            re.IGNORECASE,
        )

        for i, line in enumerate(lines, 1):
            if pattern.search(line):
                # Extract numbers to check if target < entry_max
                numbers = re.findall(r'\d+', line)
                if len(numbers) >= 3:
                    try:
                        entry_max = max(int(numbers[1]), int(numbers[2]))
                        exit_target = int(numbers[0])
                        if exit_target < entry_max:
                            self._add_finding(
                                category="TP_ZONE_CONFIG",
                                severity=BugSeverity.CRITICAL,
                                file_path=file_path,
                                line_number=i,
                                description=f"TP zone exit_target ({exit_target}) below entry_max ({entry_max}) - will trigger immediately at breakeven",
                                code_snippet=line.strip(),
                                pattern_matched="Invalid TP zone target",
                            )
                    except (ValueError, IndexError):
                        pass

    def _detect_entry_edge_pct_issues(self, file_path: Path, content: str, tree: ast.AST):
        """
        Detect Position.entry_edge_pct not being populated from signal edge.
        """
        lines = content.split("\n")

        # Pattern: Position construction without entry_edge_pct
        pattern = re.compile(
            r'Position\([^)]*\)(?![^}]*entry_edge_pct)',
            re.IGNORECASE | re.DOTALL,
        )

        for i, line in enumerate(lines, 1):
            if pattern.search(line):
                context_start = max(0, i - 3)
                context_end = min(len(lines), i + 3)
                context = "\n".join(lines[context_start:context_end])

                if "edge_pct" not in context and "entry_edge" not in context:
                    self._add_finding(
                        category="ENTRY_EDGE_PCT_MISSING",
                        severity=BugSeverity.MEDIUM,
                        file_path=file_path,
                        line_number=i,
                        description="Position construction without entry_edge_pct population",
                        code_snippet=line.strip(),
                        pattern_matched="Position without entry_edge_pct",
                        context=context,
                    )

    def _detect_year_rollover_issues(self, file_path: Path, content: str, tree: ast.AST):
        """
        Detect year rollover bugs in ticker parsing where current year is assumed.
        """
        lines = content.split("\n")

        # Pattern: Using datetime.now().year for ticker expiry
        pattern = re.compile(
            r'datetime\.now\(\)\.year|\.year.*=.*\d{4}',
            re.IGNORECASE,
        )

        for i, line in enumerate(lines, 1):
            if pattern.search(line):
                # Check if this is in a ticker parsing context
                context_start = max(0, i - 5)
                context_end = min(len(lines), i + 5)
                context = "\n".join(lines[context_start:context_end])

                if "ticker" in context.lower() or "expiry" in context.lower():
                    self._add_finding(
                        category="YEAR_ROLLOVER",
                        severity=BugSeverity.HIGH,
                        file_path=file_path,
                        line_number=i,
                        description="Ticker parsing using current year assumption - will fail at year boundaries",
                        code_snippet=line.strip(),
                        pattern_matched="Hardcoded year assumption",
                        context=context,
                    )

    def _detect_strike_validation_issues(self, file_path: Path, content: str, tree: ast.AST):
        """
        Detect strike price validation issues, particularly missing imports.
        """
        lines = content.split("\n")

        # Pattern: Using math functions without import
        pattern = re.compile(
            r'math\.(floor|ceil|abs|sqrt|min|max)',
            re.IGNORECASE,
        )

        # Check if math is imported
        math_imported = False
        for line in lines[:50]:  # Check imports at top of file
            if re.match(r'^import\s+math|^from\s+math\s+import', line):
                math_imported = True
                break

        if not math_imported:
            for i, line in enumerate(lines, 1):
                if pattern.search(line):
                    self._add_finding(
                        category="MISSING_IMPORT",
                        severity=BugSeverity.CRITICAL,
                        file_path=file_path,
                        line_number=i,
                        description="Using math functions without 'import math' - will cause NameError",
                        code_snippet=line.strip(),
                        pattern_matched="math without import",
                    )

    def _detect_deadlock_patterns(self, file_path: Path, content: str, tree: ast.AST):
        """
        Detect potential deadlock patterns, particularly in BookFreshnessTracker.
        """
        lines = content.split("\n")

        # Pattern: Lock re-acquisition in same function
        pattern = re.compile(
            r'with\s+self\._lock.*:.*\n.*get_state\(\)',
            re.IGNORECASE | re.DOTALL,
        )

        # Pattern: Regular Lock instead of RLock for re-entrant needs
        pattern2 = re.compile(
            r'threading\.Lock\(\)(?![^}]*RLock)',
            re.IGNORECASE,
        )

        for i, line in enumerate(lines, 1):
            if pattern.search(line):
                self._add_finding(
                    category="DEADLOCK_RISK",
                    severity=BugSeverity.CRITICAL,
                    file_path=file_path,
                    line_number=i,
                    description="Potential lock re-acquisition deadlock - lock held then get_state() re-acquires it",
                    code_snippet=line.strip(),
                    pattern_matched="Lock re-acquisition",
                )

            if pattern2.search(line):
                context_start = max(0, i - 5)
                context_end = min(len(lines), i + 5)
                context = "\n".join(lines[context_start:context_end])

                if "get_state" in context or "update" in context:
                    self._add_finding(
                        category="DEADLOCK_RISK",
                        severity=BugSeverity.HIGH,
                        file_path=file_path,
                        line_number=i,
                        description="Using threading.Lock() instead of RLock() for re-entrant locking - may deadlock",
                        code_snippet=line.strip(),
                        pattern_matched="Lock instead of RLock",
                        context=context,
                    )

    def _detect_type_comparison_bugs(self, file_path: Path, content: str, tree: ast.AST):
        """
        Detect type comparison bugs, particularly BookFreshnessState objects compared to enums.
        """
        lines = content.split("\n")

        # Pattern: Comparing object to enum
        pattern = re.compile(
            r'book_state.*==.*BookState|BookState.*==.*book_state',
            re.IGNORECASE,
        )

        for i, line in enumerate(lines, 1):
            if pattern.search(line):
                self._add_finding(
                    category="TYPE_COMPARISON_BUG",
                    severity=BugSeverity.HIGH,
                    file_path=file_path,
                    line_number=i,
                    description="Comparing BookFreshnessState object to BookState enum - should use .state or .is_tradable()",
                    code_snippet=line.strip(),
                    pattern_matched="Object to enum comparison",
                )

    def _detect_ws_rest_divergence_issues(self, file_path: Path, content: str, tree: ast.AST):
        """
        Detect WS-REST divergence guard issues that veto orders in REST-fallback mode.
        """
        lines = content.split("\n")

        # Pattern: Divergence check without REST-fallback exemption
        pattern = re.compile(
            r'divergence.*ws.*rest(?![^}]*REST_FALLBACK|rest_fallback)',
            re.IGNORECASE | re.DOTALL,
        )

        for i, line in enumerate(lines, 1):
            if pattern.search(line):
                context_start = max(0, i - 5)
                context_end = min(len(lines), i + 5)
                context = "\n".join(lines[context_start:context_end])

                if "REST_FALLBACK" not in context and "rest_fallback" not in context:
                    self._add_finding(
                        category="WS_REST_DIVERGENCE",
                        severity=BugSeverity.HIGH,
                        file_path=file_path,
                        line_number=i,
                        description="WS-REST divergence check without REST-fallback exemption - may veto valid orders",
                        code_snippet=line.strip(),
                        pattern_matched="Divergence without fallback exemption",
                        context=context,
                    )

    def _detect_canonical_duality_violations(self, file_path: Path, content: str, tree: ast.AST):
        """
        Detect violations of canonical duality (YES + NO = 1.0, bid ≡ yes, ask ≡ no).
        """
        lines = content.split("\n")

        # Pattern: NO bid/ask inversion (should be: no_bid = yes_ask, no_ask = yes_bid)
        pattern1 = re.compile(
            r'no_bid.*=.*yes_bid|no_ask.*=.*yes_ask',
            re.IGNORECASE,
        )

        # Pattern: Missing duality conversion
        pattern2 = re.compile(
            r'no_.*price.*=.*yes_.*price(?!\s*\|\|\s*1\s*-\s*)',
            re.IGNORECASE,
        )

        for i, line in enumerate(lines, 1):
            if pattern1.search(line):
                self._add_finding(
                    category="CANONICAL_DUALITY_VIOLATION",
                    severity=BugSeverity.CRITICAL,
                    file_path=file_path,
                    line_number=i,
                    description="Canonical duality violation - NO bid should equal YES ask, NO ask should equal YES bid",
                    code_snippet=line.strip(),
                    pattern_matched="NO bid/ask inversion",
                )

            if pattern2.search(line):
                context_start = max(0, i - 3)
                context_end = min(len(lines), i + 3)
                context = "\n".join(lines[context_start:context_end])

                if "1 -" not in context and "1-" not in context:
                    self._add_finding(
                        category="CANONICAL_DUALITY_VIOLATION",
                        severity=BugSeverity.HIGH,
                        file_path=file_path,
                        line_number=i,
                        description="NO price without duality conversion (1 - YES price)",
                        code_snippet=line.strip(),
                        pattern_matched="NO price without 1- conversion",
                        context=context,
                    )

    def _detect_outcome_side_conflicts(self, file_path: Path, content: str, tree: ast.AST):
        """
        Detect outcome_side / book_side conflicts in fill parsing.
        """
        lines = content.split("\n")

        # Pattern: Using deprecated 'side' field instead of outcome_side/book_side
        pattern = re.compile(
            r'fill\[["\']side["\']\](?![^}]*outcome_side|book_side)',
            re.IGNORECASE,
        )

        for i, line in enumerate(lines, 1):
            if pattern.search(line):
                context_start = max(0, i - 5)
                context_end = min(len(lines), i + 5)
                context = "\n".join(lines[context_start:context_end])

                if "outcome_side" not in context and "book_side" not in context:
                    self._add_finding(
                        category="OUTCOME_SIDE_CONFLICT",
                        severity=BugSeverity.HIGH,
                        file_path=file_path,
                        line_number=i,
                        description="Using deprecated 'side' field instead of outcome_side/book_side - may invert NO fills",
                        code_snippet=line.strip(),
                        pattern_matched="Deprecated side field usage",
                        context=context,
                    )

    def _detect_missing_imports(self, file_path: Path, content: str, tree: ast.AST):
        """
        Detect critical missing imports based on usage patterns.
        """
        lines = content.split("\n")

        # Common imports that are often missing
        import_patterns = {
            r'math\.': 'import math',
            r'datetime\.': 'from datetime import datetime',
            r'Decimal\(': 'from decimal import Decimal',
            r'Optional\[': 'from typing import Optional',
            r'List\[': 'from typing import List',
            r'Dict\[': 'from typing import Dict',
        }

        for pattern, required_import in import_patterns.items():
            # Check if the pattern is used
            pattern_used = False
            for line in lines:
                if re.search(pattern, line):
                    pattern_used = True
                    break

            if pattern_used:
                # Check if import exists
                import_exists = False
                for line in lines[:50]:  # Check imports at top
                    if required_import in line:
                        import_exists = True
                        break

                if not import_exists:
                    for i, line in enumerate(lines, 1):
                        if re.search(pattern, line):
                            self._add_finding(
                                category="MISSING_IMPORT",
                                severity=BugSeverity.CRITICAL,
                                file_path=file_path,
                                line_number=i,
                                description=f"Missing import: '{required_import}'",
                                code_snippet=line.strip(),
                                pattern_matched=f"Missing {required_import}",
                            )
                            break

    def _detect_uninitialized_fields(self, file_path: Path, content: str, tree: ast.AST):
        """
        Detect dataclass fields that are not initialized in __post_init__.
        """
        # Find all dataclass definitions
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Check if it's a dataclass
                is_dataclass = False
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Name) and decorator.id == "dataclass":
                        is_dataclass = True
                        break
                    elif isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name):
                        if decorator.func.id == "dataclass":
                            is_dataclass = True
                            break

                if is_dataclass:
                    # Get all field assignments
                    fields = []
                    for item in node.body:
                        if isinstance(item, ast.AnnAssign) and item.target:
                            if isinstance(item.target, ast.Name):
                                fields.append(item.target.id)

                    # Check if __post_init__ exists
                    has_post_init = any(
                        item.name == "__post_init__"
                        for item in node.body
                        if isinstance(item, ast.FunctionDef)
                    )

                    if has_post_init and fields:
                        # Check if all fields are initialized in __post_init__
                        lines = content.split("\n")
                        for i, line in enumerate(lines, 1):
                            if "__post_init__" in line:
                                # Get the method body
                                context_start = i
                                context_end = min(len(lines), i + 30)
                                context = "\n".join(lines[context_start:context_end])

                                for field in fields:
                                    if field not in context and field not in ["self", "cls"]:
                                        self._add_finding(
                                            category="UNINITIALIZED_FIELD",
                                            severity=BugSeverity.MEDIUM,
                                            file_path=file_path,
                                            line_number=i,
                                            description=f"Dataclass field '{field}' may not be initialized in __post_init__",
                                            code_snippet=line.strip(),
                                            pattern_matched=f"Uninitialized field: {field}",
                                        )
                                break

    def print_summary(self):
        """Print a summary of findings grouped by severity and category."""
        if not self.findings:
            print("✅ No inversion bugs or side conflicts detected!")
            return

        # Group by severity
        by_severity = {
            BugSeverity.CRITICAL: [],
            BugSeverity.HIGH: [],
            BugSeverity.MEDIUM: [],
            BugSeverity.LOW: [],
        }

        for finding in self.findings:
            by_severity[finding.severity].append(finding)

        # Print summary
        print("\n" + "=" * 80)
        print("INVERSION BUG & SIDE CONFLICT DETECTION SUMMARY")
        print("=" * 80)

        for severity in [BugSeverity.CRITICAL, BugSeverity.HIGH, BugSeverity.MEDIUM, BugSeverity.LOW]:
            findings = by_severity[severity]
            if findings:
                print(f"\n{severity.value} ({len(findings)} findings):")
                print("-" * 80)

                # Group by category
                by_category = {}
                for f in findings:
                    if f.category not in by_category:
                        by_category[f.category] = []
                    by_category[f.category].append(f)

                for category, cat_findings in sorted(by_category.items()):
                    print(f"\n  {category} ({len(cat_findings)}):")
                    for f in cat_findings:
                        print(f"    • {f.file_path}:{f.line_number}")
                        print(f"      {f.description}")

        # Print category breakdown
        print("\n" + "=" * 80)
        print("CATEGORY BREAKDOWN")
        print("=" * 80)

        by_category = {}
        for finding in self.findings:
            if finding.category not in by_category:
                by_category[finding.category] = []
            by_category[finding.category].append(finding)

        for category, findings in sorted(by_category.items()):
            severity_counts = {}
            for f in findings:
                severity_counts[f.severity.value] = severity_counts.get(f.severity.value, 0) + 1
            print(f"\n{category}: {len(findings)} total")
            for sev, count in sorted(severity_counts.items()):
                print(f"  {sev}: {count}")

        print("\n" + "=" * 80)

    def export_findings(self, output_path: Path):
        """Export findings to a JSON file."""
        import json

        findings_dict = [
            {
                "category": f.category,
                "severity": f.severity.value,
                "file_path": f.file_path,
                "line_number": f.line_number,
                "description": f.description,
                "code_snippet": f.code_snippet,
                "pattern_matched": f.pattern_matched,
                "context": f.context,
            }
            for f in self.findings
        ]

        with open(output_path, "w") as f:
            json.dump(findings_dict, f, indent=2)

        print(f"Findings exported to {output_path}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Detect inversion bugs and side conflicts in MERID codebase"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output path for JSON export of findings",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print detailed findings",
    )

    args = parser.parse_args()

    # Run detector
    detector = InversionBugDetector(PROJECT_ROOT)
    findings = detector.scan_all()

    # Print summary
    detector.print_summary()

    # Print detailed findings if requested
    if args.verbose:
        print("\n" + "=" * 80)
        print("DETAILED FINDINGS")
        print("=" * 80)
        for finding in findings:
            print(finding)
            print("-" * 80)

    # Export if requested
    if args.output:
        detector.export_findings(args.output)

    # Exit with error code if critical findings
    critical_count = sum(1 for f in findings if f.severity == BugSeverity.CRITICAL)
    if critical_count > 0:
        print(f"\n❌ {critical_count} CRITICAL findings detected!")
        sys.exit(1)
    else:
        print("\n✅ No critical findings detected.")
        sys.exit(0)


if __name__ == "__main__":
    main()
