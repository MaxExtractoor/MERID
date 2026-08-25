#!/usr/bin/env python3
"""
Fast Inversion Bug & Side Conflict Detector

Optimized version that scans for critical inversion bugs and side conflicts.
Focuses on high-impact patterns that have caused real issues in production.
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


@dataclass
class BugFinding:
    category: str
    severity: BugSeverity
    file_path: str
    line_number: int
    description: str
    code_snippet: str


class FastInversionBugDetector:
    """Fast detector for critical inversion bugs."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.findings: List[BugFinding] = []

    def scan_critical_files(self) -> List[BugFinding]:
        """Scan only critical files known to have inversion bugs."""
        critical_files = [
            "merid/event_venues/kalshi/fills_ledger.py",
            "merid/event_venues/kalshi/client.py",
            "merid/event_venues/kalshi/order_router.py",
            "merid/event_venues/kalshi/position_cache.py",
            "merid/event_venues/kalshi/ws_bridge.py",
            "merid/event_venues/kalshi/book_freshness.py",
            "merid/event_venues/kalshi/market_state.py",
            "merid/event_venues/kalshi/orderbook.py",
            "merid/loop_15m.py",
            "merid/prediction/agent_grid_15m.py",
            "merid/execution/executors/kalshi.py",
            "merid/event_venues/kalshi/spread_edge_analytics.py",
            "merid/event_venues/kalshi/binary_price_space.py",
            "merid/position_management/position.py",
            "merid/position_management/position_monitor.py",
            "merid/position_management/unified_exit_policy_engine.py",
        ]

        print(f"Scanning {len(critical_files)} critical files for inversion bugs...")

        for rel_path in critical_files:
            file_path = self.root_dir / rel_path
            if file_path.exists():
                self._scan_file(file_path)
            else:
                print(f"Warning: {rel_path} not found")

        return self.findings

    def _scan_file(self, file_path: Path):
        """Scan a single file for critical patterns."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            lines = content.split("\n")

            # Remove comments for pattern matching (but keep line numbers)
            code_lines = []
            for line in lines:
                # Strip inline comments
                code_line = re.sub(r'#.*$', '', line).strip()
                code_lines.append(code_line)

            # Run critical pattern checks on code only
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
            # Pattern: NO-side order without YES-space conversion
            if re.search(r'(BUY_NO|SELL_NO|outcome.*==.*["\']no["\'])', code_line, re.IGNORECASE):
                # Check context for conversion - look for conversion functions or 100 - price
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
            # Pattern: Inverted calculations for NO positions
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
                # Skip PositionSide enum and PositionMonitor
                if "PositionSide" in code_line or "PositionMonitor" in code_line:
                    continue
                # Look for thesis_side field definition in the next 100 lines (dataclasses can be long)
                context = "\n".join(lines[i:min(len(lines), i+100)])
                # Check for actual field definition (not just comments)
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
                # Only flag if this is in a context where re-entrancy is likely
                # (e.g., methods that call other methods that might acquire the same lock)
                # Skip lock creation in dicts (like _position_exit_locks[position_id] = threading.Lock())
                # since those are per-key locks, not re-entrant
                if "get_state" in context or ("update" in context and "with" in context):
                    # Skip if this is creating a per-key lock in a dict
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
            # Only flag direct comparisons without .state property
            if re.search(r'book_state\s*==\s*BookState\.|BookState\.\w+\s*==\s*book_state', code_line, re.IGNORECASE):
                # Check if .state is used in the comparison
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
            # Only flag actual assignments, not comments or explanations
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
        # Check if math is used but not imported
        math_used = any(re.search(r'math\.', code_line) for code_line in code_lines)
        # Check entire file for math import (not just first 50 lines)
        math_imported = any(re.match(r'^import\s+math|^from\s+math\s+import', line) for line in lines)
        
        if math_used and not math_imported:
            for i, (line, code_line) in enumerate(zip(lines, code_lines), 1):
                if re.search(r'math\.', code_line):
                    # Double-check this isn't in a comment
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
                # This is a field declaration
                context = "\n".join(lines[max(0, i-5):min(len(lines), i+10)])
                if "edge_pct" not in context and "entry_edge" not in context:
                    self._add_finding(
                        "UNINITIALIZED_FIELD",
                        BugSeverity.MEDIUM,
                        file_path, i,
                        "Position.entry_edge_pct field may not be initialized from signal edge",
                        line.strip()
                    )

    def print_summary(self):
        """Print summary of findings."""
        if not self.findings:
            print("[OK] No critical inversion bugs detected!")
            return

        print("\n" + "=" * 80)
        print("INVERSION BUG DETECTION RESULTS")
        print("=" * 80)

        # Group by severity
        critical = [f for f in self.findings if f.severity == BugSeverity.CRITICAL]
        high = [f for f in self.findings if f.severity == BugSeverity.HIGH]
        medium = [f for f in self.findings if f.severity == BugSeverity.MEDIUM]

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

        print("\n" + "=" * 80)
        print(f"Total: {len(self.findings)} findings ({len(critical)} critical, {len(high)} high, {len(medium)} medium)")
        print("=" * 80)


def main():
    detector = FastInversionBugDetector(PROJECT_ROOT)
    findings = detector.scan_critical_files()
    detector.print_summary()

    # Exit with error if critical findings
    critical_count = sum(1 for f in findings if f.severity == BugSeverity.CRITICAL)
    if critical_count > 0:
        print(f"\n[ERROR] {critical_count} CRITICAL findings detected!")
        sys.exit(1)
    else:
        print("\n[OK] No critical findings detected.")
        sys.exit(0)


if __name__ == "__main__":
    main()
