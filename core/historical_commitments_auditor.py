"""
Historical Commitments Auditor

Parses HISTORICAL_AUDIT_GAP_REPORT.md and surfaces any UNTOUCHED or
PARTIALLY_COMPLETED items with high/critical severity as failing checks.
Designed to run alongside the Dev Swarm Readiness Auditor to enforce
promises made in older audits.

Usage:
    python -m core.historical_commitments_auditor          # print report
    python -m core.historical_commitments_auditor --json   # JSON output
    python -m core.historical_commitments_auditor --fix    # auto-create DevTasks
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GAP_REPORT_PATH = PROJECT_ROOT / "HISTORICAL_AUDIT_GAP_REPORT.md"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class CommitmentStatus(Enum):
    COMPLETED = "COMPLETED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    UNTOUCHED = "UNTOUCHED"
    OBSOLETE = "OBSOLETE"


class Severity(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class HistoricalCommitment:
    id: str
    section: str
    description: str
    status: CommitmentStatus
    severity: Severity = Severity.MEDIUM
    evidence: str = ""

    @property
    def is_overdue(self) -> bool:
        """A commitment is overdue if it is UNTOUCHED or PARTIALLY_COMPLETED
        and has high or critical severity."""
        return (
            self.status in (CommitmentStatus.UNTOUCHED, CommitmentStatus.PARTIALLY_COMPLETED)
            and self.severity in (Severity.CRITICAL, Severity.HIGH)
        )


@dataclass
class CommitmentsReport:
    commitments: List[HistoricalCommitment] = field(default_factory=list)
    parse_errors: List[str] = field(default_factory=list)

    @property
    def overdue_count(self) -> int:
        return sum(1 for c in self.commitments if c.is_overdue)

    @property
    def passed(self) -> bool:
        return self.overdue_count == 0

    @property
    def overdue_items(self) -> List[HistoricalCommitment]:
        return [c for c in self.commitments if c.is_overdue]

    def summary_table(self) -> str:
        lines = [
            "| # | ID | Section | Description | Status | Severity | Overdue? |",
            "|---|-----|---------|-------------|--------|----------|----------|",
        ]
        for i, c in enumerate(self.commitments, 1):
            overdue = "**YES**" if c.is_overdue else "no"
            lines.append(
                f"| {i} | {c.id} | {c.section} | {c.description[:60]} | "
                f"**{c.status.value}** | {c.severity.value} | {overdue} |"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

# Matches table rows like: | RRG-01 | description | **UNTOUCHED** | evidence |
_TABLE_ROW_RE = re.compile(
    r"^\|\s*(?P<id>[A-Z]{2,5}-\d{1,3})\s*\|"  # ID column
    r"\s*(?P<desc>[^|]+?)\s*\|"                  # description
    r"\s*\*{0,2}(?P<status>[A-Z_]+)\*{0,2}\s*\|",  # status (may be bold)
    re.MULTILINE,
)

# Section headers we care about
_SECTION_HEADERS = {
    "Part 2": "Risk & Readiness Gaps",
    "Part 3": "UI Wiring Gaps",
    "Part 5": "Critical Coverage Gaps",
    "Part 7": "System Audit Issues",
    "Part 8": "CI Gate Discrepancies",
}

# Severity mapping by ID prefix
_SEVERITY_MAP = {
    "RRG": Severity.CRITICAL,  # Risk & Readiness Gaps are critical/high
    "UW": Severity.HIGH,       # UI Wiring gaps
    "SD": Severity.HIGH,       # Silent downgrades
}

# Override specific IDs to more precise severities
_ID_SEVERITY_OVERRIDES = {
    "RRG-07": Severity.MEDIUM,   # Organizational gap, not code-addressable
    "RRG-08": Severity.MEDIUM,   # Tier 2
    "RRG-09": Severity.MEDIUM,   # Tier 2
    "RRG-10": Severity.MEDIUM,   # Tier 2
}


def _status_from_str(s: str) -> Optional[CommitmentStatus]:
    """Parse a status string, tolerating bold markers."""
    cleaned = s.strip().strip("*").upper().replace(" ", "_")
    try:
        return CommitmentStatus(cleaned)
    except ValueError:
        return None


def _severity_for_id(item_id: str) -> Severity:
    """Determine severity based on ID prefix and overrides."""
    if item_id in _ID_SEVERITY_OVERRIDES:
        return _ID_SEVERITY_OVERRIDES[item_id]
    prefix = re.match(r"^[A-Z]+", item_id)
    if prefix and prefix.group() in _SEVERITY_MAP:
        return _SEVERITY_MAP[prefix.group()]
    return Severity.MEDIUM


def parse_gap_report(path: Optional[Path] = None) -> CommitmentsReport:
    """Parse HISTORICAL_AUDIT_GAP_REPORT.md and extract commitments."""
    path = path or GAP_REPORT_PATH
    report = CommitmentsReport()

    if not path.exists():
        report.parse_errors.append(f"Gap report not found: {path}")
        return report

    text = path.read_text(encoding="utf-8", errors="replace")

    # Determine current section from headers
    current_section = "Unknown"
    lines = text.split("\n")

    for line in lines:
        # Track section headers
        header_match = re.match(r"^##\s+Part\s+(\d+)", line)
        if header_match:
            part_num = f"Part {header_match.group(1)}"
            current_section = _SECTION_HEADERS.get(part_num, part_num)
            continue

        # Parse table rows with IDs
        row_match = _TABLE_ROW_RE.match(line)
        if row_match:
            item_id = row_match.group("id").strip()
            desc = row_match.group("desc").strip()
            status_str = row_match.group("status").strip()

            status = _status_from_str(status_str)
            if status is None:
                continue  # Skip rows where status doesn't parse

            severity = _severity_for_id(item_id)

            report.commitments.append(HistoricalCommitment(
                id=item_id,
                section=current_section,
                description=desc,
                status=status,
                severity=severity,
            ))

    return report


# ---------------------------------------------------------------------------
# DevTask generation
# ---------------------------------------------------------------------------

def create_overdue_tasks(report: CommitmentsReport) -> list:
    """Create DevTask dicts for overdue commitments."""
    tasks = []
    for c in report.overdue_items:
        tasks.append({
            "description": (
                f"[Historical Commitment {c.id}] {c.section}: {c.description} "
                f"— status is {c.status.value}, severity {c.severity.value}"
            ),
            "target_files": [],
            "success_criteria": f"{c.id} status becomes COMPLETED in HISTORICAL_AUDIT_GAP_REPORT.md",
            "priority": 0 if c.severity == Severity.CRITICAL else 1,
            "estimated_effort": "large",
        })
    return tasks


# ---------------------------------------------------------------------------
# Integration with readiness auditor
# ---------------------------------------------------------------------------

def check_historical_commitments():
    """Readiness check: are there overdue historical commitments?

    Returns a CheckResult-compatible dict for integration with
    dev_swarm_readiness_auditor.
    """
    report = parse_gap_report()
    overdue = report.overdue_count
    if overdue == 0:
        return {
            "area": "Historical",
            "item": "No overdue historical commitments",
            "status": "OK",
            "evidence": str(GAP_REPORT_PATH.name),
            "fix_plan": "",
        }
    ids = ", ".join(c.id for c in report.overdue_items[:5])
    suffix = f" (+{overdue - 5} more)" if overdue > 5 else ""
    return {
        "area": "Historical",
        "item": f"{overdue} overdue historical commitment(s)",
        "status": "DRIFTED",
        "evidence": f"{ids}{suffix}",
        "fix_plan": "Address overdue items or update their status in HISTORICAL_AUDIT_GAP_REPORT.md",
    }


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Historical Commitments Auditor")
    parser.add_argument("--fix", action="store_true", help="Auto-create DevTasks for overdue items")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    report = parse_gap_report()

    if args.json:
        out = {
            "total_commitments": len(report.commitments),
            "overdue_count": report.overdue_count,
            "passed": report.passed,
            "parse_errors": report.parse_errors,
            "overdue_items": [
                {
                    "id": c.id,
                    "section": c.section,
                    "description": c.description,
                    "status": c.status.value,
                    "severity": c.severity.value,
                }
                for c in report.overdue_items
            ],
            "all_items": [
                {
                    "id": c.id,
                    "section": c.section,
                    "description": c.description,
                    "status": c.status.value,
                    "severity": c.severity.value,
                    "overdue": c.is_overdue,
                }
                for c in report.commitments
            ],
        }
        print(json.dumps(out, indent=2))
    else:
        print("=" * 60)
        print("  MERID Historical Commitments Audit")
        print("=" * 60)
        print()
        print(f"Total commitments parsed: {len(report.commitments)}")
        print(f"Overdue (UNTOUCHED/PARTIAL + high/critical): {report.overdue_count}")
        print()
        if report.commitments:
            print(report.summary_table())
        if report.parse_errors:
            print(f"\nParse errors: {report.parse_errors}")
        print()
        if report.passed:
            print("RESULT: NO OVERDUE COMMITMENTS")
        else:
            print(f"RESULT: {report.overdue_count} overdue commitment(s) need attention")

    if args.fix and report.overdue_count > 0:
        tasks = create_overdue_tasks(report)
        print(f"\nCreated {len(tasks)} DevTask(s) for overdue commitments:")
        for t in tasks:
            print(f"  - {t['description'][:100]}...")

    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
