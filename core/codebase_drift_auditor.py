"""
Codebase Drift Auditor

Compares the current state of the MERID repository against
CODEBASE_BASELINE.json and detects drift in coverage, structure,
security, and risk zone status.

Usage:
    python -m core.codebase_drift_auditor              # print report
    python -m core.codebase_drift_auditor --json        # JSON output for CI
    python -m core.codebase_drift_auditor --fix         # auto-create DevTasks for drift
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = PROJECT_ROOT / "CODEBASE_BASELINE.json"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class DriftSeverity(Enum):
    OK = "OK"
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class DriftItem:
    id: str
    domain: str
    category: str  # coverage, security, arch, risk_zone
    severity: DriftSeverity
    summary: str
    current_value: Any = None
    baseline_value: Any = None
    fix_plan: str = ""


@dataclass
class DriftReport:
    timestamp: float = field(default_factory=time.time)
    items: List[DriftItem] = field(default_factory=list)
    baseline_version: str = ""

    @property
    def passed(self) -> bool:
        return not any(i.severity == DriftSeverity.CRITICAL for i in self.items)

    @property
    def drift_count(self) -> int:
        return sum(1 for i in self.items if i.severity != DriftSeverity.OK)

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.items if i.severity == DriftSeverity.CRITICAL)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "passed": self.passed,
            "drift_count": self.drift_count,
            "critical_count": self.critical_count,
            "baseline_version": self.baseline_version,
            "items": [
                {
                    "id": i.id,
                    "domain": i.domain,
                    "category": i.category,
                    "severity": i.severity.value,
                    "summary": i.summary,
                    "current_value": i.current_value,
                    "baseline_value": i.baseline_value,
                    "fix_plan": i.fix_plan,
                }
                for i in self.items
            ],
        }


# ---------------------------------------------------------------------------
# Baseline loader
# ---------------------------------------------------------------------------

def load_baseline() -> dict:
    """Load CODEBASE_BASELINE.json."""
    if not BASELINE_PATH.exists():
        return {}
    with open(BASELINE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Individual drift checks
# ---------------------------------------------------------------------------

def _count_py_files(rel_path: str) -> int:
    """Count non-empty .py files under a path relative to PROJECT_ROOT."""
    target = PROJECT_ROOT / rel_path
    if not target.exists():
        return 0
    count = 0
    for root, _dirs, files in os.walk(target):
        for fn in files:
            if fn.endswith(".py"):
                fp = os.path.join(root, fn)
                if os.path.getsize(fp) > 0:
                    count += 1
    return count


def _count_empty_test_files() -> int:
    """Count 0-byte .py files in tests/."""
    tests_dir = PROJECT_ROOT / "tests"
    if not tests_dir.exists():
        return 0
    count = 0
    for root, _dirs, files in os.walk(tests_dir):
        for fn in files:
            if fn.endswith(".py"):
                fp = os.path.join(root, fn)
                if os.path.getsize(fp) == 0:
                    count += 1
    return count


def _count_root_md_files() -> int:
    """Count .md files at repo root."""
    return len(list(PROJECT_ROOT.glob("*.md")))


def _file_size_kb(rel_path: str) -> float:
    """Get file size in KB."""
    fp = PROJECT_ROOT / rel_path
    if not fp.exists():
        return 0.0
    return fp.stat().st_size / 1024


def _git_tracks_file(rel_path: str) -> bool:
    """Check if a file is tracked by git."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", rel_path],
            capture_output=True, text=True,
            cwd=str(PROJECT_ROOT),
        )
        return result.returncode == 0
    except Exception:
        return False


def _count_test_functions(rel_path: str) -> int:
    """Count test functions in a file."""
    fp = PROJECT_ROOT / rel_path
    if not fp.exists():
        return 0
    text = fp.read_text(encoding="utf-8", errors="replace")
    return len(re.findall(r"^\s+(?:async\s+)?def test_", text, re.MULTILINE))


GOD_CLASS_THRESHOLD_KB = 40


def check_secrets_in_git(report: DriftReport):
    """RG-01/RG-02: Check if secrets are still tracked in git."""
    sensitive_files = ["kalshi_private_key.pem", ".env.backup"]
    for f in sensitive_files:
        tracked = _git_tracks_file(f)
        if tracked:
            report.items.append(DriftItem(
                id=f"SEC-{f.replace('.', '_')}",
                domain="security",
                category="security",
                severity=DriftSeverity.CRITICAL,
                summary=f"{f} is still tracked in git",
                current_value="tracked",
                baseline_value="should not be tracked",
                fix_plan=f"Remove {f} from git history and .gitignore it",
            ))
        else:
            report.items.append(DriftItem(
                id=f"SEC-{f.replace('.', '_')}",
                domain="security",
                category="security",
                severity=DriftSeverity.OK,
                summary=f"{f} not tracked in git",
            ))


def check_gitignore_size(report: DriftReport):
    """RG-03: Check .gitignore has enough entries."""
    fp = PROJECT_ROOT / ".gitignore"
    if not fp.exists():
        report.items.append(DriftItem(
            id="SEC-gitignore",
            domain="security",
            category="security",
            severity=DriftSeverity.CRITICAL,
            summary=".gitignore is missing",
            fix_plan="Create comprehensive .gitignore",
        ))
        return
    lines = [l.strip() for l in fp.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    if len(lines) < 15:
        report.items.append(DriftItem(
            id="SEC-gitignore",
            domain="security",
            category="security",
            severity=DriftSeverity.WARNING,
            summary=f".gitignore has only {len(lines)} entries (target >=15)",
            current_value=len(lines),
            baseline_value=15,
            fix_plan="Expand .gitignore to cover secrets, build artifacts, IDE configs",
        ))
    else:
        report.items.append(DriftItem(
            id="SEC-gitignore",
            domain="security",
            category="security",
            severity=DriftSeverity.OK,
            summary=f".gitignore has {len(lines)} entries",
            current_value=len(lines),
        ))


def check_domain_coverage_gates(report: DriftReport, baseline: dict):
    """Check enforced coverage gates haven't been removed."""
    gates = baseline.get("ci_gates", {}).get("enforced", [])
    for gate in gates:
        name = gate.get("name", "unknown")
        cmd = gate.get("command", "")
        # Check if the Makefile target still exists
        target = cmd.replace("make ", "") if cmd.startswith("make ") else None
        if target:
            makefile = PROJECT_ROOT / "Makefile"
            if makefile.exists():
                text = makefile.read_text(encoding="utf-8", errors="replace")
                if f"{target}:" in text:
                    report.items.append(DriftItem(
                        id=f"GATE-{target}",
                        domain="ci",
                        category="coverage",
                        severity=DriftSeverity.OK,
                        summary=f"CI gate '{name}' (make {target}) present",
                    ))
                else:
                    report.items.append(DriftItem(
                        id=f"GATE-{target}",
                        domain="ci",
                        category="coverage",
                        severity=DriftSeverity.CRITICAL,
                        summary=f"CI gate '{name}' (make {target}) MISSING from Makefile",
                        fix_plan=f"Re-add 'make {target}' to Makefile",
                    ))


def check_dev_swarm_test_count(report: DriftReport, baseline: dict):
    """Check Dev Swarm test count hasn't dropped."""
    for domain in baseline.get("domains", []):
        if domain.get("id") == "dev_swarm":
            baseline_count = domain.get("test_count", 0)
            break
    else:
        return

    current_count = _count_test_functions("tests/test_dev_swarm.py")
    if current_count < baseline_count:
        report.items.append(DriftItem(
            id="DS-test-count",
            domain="dev_swarm",
            category="coverage",
            severity=DriftSeverity.CRITICAL,
            summary=f"Dev Swarm test count dropped: {current_count} < {baseline_count}",
            current_value=current_count,
            baseline_value=baseline_count,
            fix_plan="Restore deleted tests or add replacements",
        ))
    else:
        report.items.append(DriftItem(
            id="DS-test-count",
            domain="dev_swarm",
            category="coverage",
            severity=DriftSeverity.OK,
            summary=f"Dev Swarm tests: {current_count} (baseline: {baseline_count})",
            current_value=current_count,
            baseline_value=baseline_count,
        ))


def check_empty_test_files(report: DriftReport, baseline: dict):
    """RG-11: Check empty test file count hasn't grown."""
    baseline_empty = baseline.get("stats", {}).get("test_files", {}).get("empty", 177)
    current_empty = _count_empty_test_files()
    if current_empty > baseline_empty:
        report.items.append(DriftItem(
            id="RG-11-empty-tests",
            domain="tests",
            category="arch",
            severity=DriftSeverity.WARNING,
            summary=f"Empty test files grew: {current_empty} > {baseline_empty}",
            current_value=current_empty,
            baseline_value=baseline_empty,
            fix_plan="Delete or populate new empty test files",
        ))
    else:
        report.items.append(DriftItem(
            id="RG-11-empty-tests",
            domain="tests",
            category="arch",
            severity=DriftSeverity.OK if current_empty <= baseline_empty else DriftSeverity.INFO,
            summary=f"Empty test files: {current_empty} (baseline: {baseline_empty})",
            current_value=current_empty,
            baseline_value=baseline_empty,
        ))


def check_god_classes(report: DriftReport, baseline: dict):
    """LRZ-5: Check god classes haven't grown or new ones appeared."""
    known_gods = []
    for lrz in baseline.get("legacy_risk_zones", []):
        if lrz.get("id") == "LRZ-5":
            known_gods = lrz.get("files", [])
            break

    for f in known_gods:
        size = _file_size_kb(f)
        if size > GOD_CLASS_THRESHOLD_KB:
            report.items.append(DriftItem(
                id=f"GOD-{Path(f).stem}",
                domain="multiple",
                category="arch",
                severity=DriftSeverity.INFO,
                summary=f"God class still large: {f} ({size:.0f}KB)",
                current_value=f"{size:.0f}KB",
                baseline_value=f">{GOD_CLASS_THRESHOLD_KB}KB",
            ))


def check_root_doc_sprawl(report: DriftReport, baseline: dict):
    """RG-15: Check root .md file count hasn't grown."""
    baseline_count = baseline.get("stats", {}).get("root_md_files", 323)
    current_count = _count_root_md_files()
    if current_count > baseline_count + 5:
        report.items.append(DriftItem(
            id="RG-15-doc-sprawl",
            domain="docs",
            category="arch",
            severity=DriftSeverity.WARNING,
            summary=f"Root .md files grew: {current_count} > {baseline_count}",
            current_value=current_count,
            baseline_value=baseline_count,
            fix_plan="Archive new stale docs to docs_archive/",
        ))
    else:
        report.items.append(DriftItem(
            id="RG-15-doc-sprawl",
            domain="docs",
            category="arch",
            severity=DriftSeverity.OK,
            summary=f"Root .md files: {current_count} (baseline: {baseline_count})",
            current_value=current_count,
            baseline_value=baseline_count,
        ))


def check_baseline_files_exist(report: DriftReport):
    """Verify baseline files themselves exist."""
    for f in ["CODEBASE_BASELINE.md", "CODEBASE_BASELINE.json"]:
        if (PROJECT_ROOT / f).exists():
            report.items.append(DriftItem(
                id=f"BASE-{f.replace('.', '_')}",
                domain="baseline",
                category="arch",
                severity=DriftSeverity.OK,
                summary=f"{f} exists",
            ))
        else:
            report.items.append(DriftItem(
                id=f"BASE-{f.replace('.', '_')}",
                domain="baseline",
                category="arch",
                severity=DriftSeverity.CRITICAL,
                summary=f"{f} is MISSING",
                fix_plan=f"Regenerate {f}",
            ))


# ---------------------------------------------------------------------------
# Full audit
# ---------------------------------------------------------------------------

ALL_CHECKS = [
    check_baseline_files_exist,
    check_secrets_in_git,
    check_gitignore_size,
]

BASELINE_CHECKS = [
    check_domain_coverage_gates,
    check_dev_swarm_test_count,
    check_empty_test_files,
    check_god_classes,
    check_root_doc_sprawl,
]


def run_drift_audit() -> DriftReport:
    """Execute all drift checks and return a DriftReport."""
    baseline = load_baseline()
    report = DriftReport(baseline_version=baseline.get("version", "unknown"))

    for check_fn in ALL_CHECKS:
        check_fn(report)

    for check_fn in BASELINE_CHECKS:
        check_fn(report, baseline)

    return report


def create_drift_tasks(report: DriftReport) -> list:
    """Create DevTask dicts for any drift items."""
    tasks = []
    for item in report.items:
        if item.severity in (DriftSeverity.CRITICAL, DriftSeverity.WARNING):
            tasks.append({
                "description": f"[Drift Auditor] {item.id}: {item.summary}. {item.fix_plan}",
                "target_files": [],
                "success_criteria": f"{item.id} status becomes OK",
                "priority": 0 if item.severity == DriftSeverity.CRITICAL else 2,
                "estimated_effort": "small",
            })
    return tasks


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Codebase Drift Auditor")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--fix", action="store_true", help="Auto-create DevTasks for drift")
    args = parser.parse_args()

    report = run_drift_audit()

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print("=" * 60)
        print("  MERID Codebase Drift Audit")
        print(f"  Baseline version: {report.baseline_version}")
        print("=" * 60)
        print()

        for item in report.items:
            icon = {"OK": "✓", "INFO": "ℹ", "WARNING": "⚠", "CRITICAL": "✗"}.get(item.severity.value, "?")
            print(f"  [{icon}] {item.id}: {item.summary}")

        print()
        ok = sum(1 for i in report.items if i.severity == DriftSeverity.OK)
        total = len(report.items)
        print(f"RESULT: {ok}/{total} checks OK, {report.drift_count} drift, {report.critical_count} critical")

    if args.fix and report.drift_count > 0:
        tasks = create_drift_tasks(report)
        print(f"\nCreated {len(tasks)} DevTask(s) for drift repair:")
        for t in tasks:
            print(f"  - {t['description']}")

    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
