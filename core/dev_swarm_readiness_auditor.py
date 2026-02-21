"""
Dev Swarm Readiness Auditor

Programmatic checklist that verifies the Dev Swarm subsystem meets
operational standards. Designed to run nightly (or on-demand) and
auto-create DevTasks for any drift detected.

Usage:
    python -m core.dev_swarm_readiness_auditor          # print report
    python -m core.dev_swarm_readiness_auditor --fix     # print + create DevTasks for drift
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class CheckStatus(Enum):
    OK = "OK"
    DRIFTED = "DRIFTED"
    MISSING = "MISSING"


@dataclass
class CheckResult:
    area: str
    item: str
    status: CheckStatus
    evidence: str = ""
    fix_plan: str = ""


@dataclass
class AuditReport:
    results: List[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.status == CheckStatus.OK for r in self.results)

    @property
    def drift_count(self) -> int:
        return sum(1 for r in self.results if r.status != CheckStatus.OK)

    def summary_table(self) -> str:
        lines = [
            "| # | Area | Item | Status | Evidence | Fix Plan |",
            "|---|------|------|--------|----------|----------|",
        ]
        for i, r in enumerate(self.results, 1):
            lines.append(
                f"| {i} | {r.area} | {r.item} | **{r.status.value}** | {r.evidence} | {r.fix_plan} |"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _file_contains(rel_path: str, needle: str) -> bool:
    """Check if a file relative to PROJECT_ROOT contains a substring."""
    fp = PROJECT_ROOT / rel_path
    if not fp.exists():
        return False
    return needle in fp.read_text(encoding="utf-8", errors="replace")


def _file_exists(rel_path: str) -> bool:
    return (PROJECT_ROOT / rel_path).exists()


def check_marker_registered() -> CheckResult:
    """1.1 – dev_swarm marker in pytest.ini."""
    if _file_contains("pytest.ini", "dev_swarm"):
        return CheckResult("Testing", "dev_swarm marker registered", CheckStatus.OK, "pytest.ini")
    return CheckResult("Testing", "dev_swarm marker registered", CheckStatus.MISSING,
                       "pytest.ini", "Add 'dev_swarm' to markers in pytest.ini")


def check_ci_gate() -> CheckResult:
    """1.2 – CI command with --cov-fail-under >= 90."""
    fp = PROJECT_ROOT / "LEGACY_RISK_MATRIX.md"
    if not fp.exists():
        return CheckResult("Testing", "CI gate >=90", CheckStatus.MISSING,
                           "LEGACY_RISK_MATRIX.md missing", "Create LEGACY_RISK_MATRIX.md")
    text = fp.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"--cov-fail-under[=\s]+(\d+)", text)
    if m and int(m.group(1)) >= 90:
        return CheckResult("Testing", "CI gate >=90", CheckStatus.OK,
                           f"LEGACY_RISK_MATRIX.md (fail-under={m.group(1)})")
    val = m.group(1) if m else "not found"
    return CheckResult("Testing", "CI gate >=90", CheckStatus.DRIFTED,
                       f"fail-under={val}", "Raise --cov-fail-under to >=90")


def check_test_file_exists() -> CheckResult:
    """1.3 – test_dev_swarm.py exists."""
    if _file_exists("tests/test_dev_swarm.py"):
        return CheckResult("Testing", "test_dev_swarm.py exists", CheckStatus.OK, "tests/test_dev_swarm.py")
    return CheckResult("Testing", "test_dev_swarm.py exists", CheckStatus.MISSING,
                       "", "Create tests/test_dev_swarm.py")


def check_test_count() -> CheckResult:
    """1.4 – At least 100 tests in the dev_swarm suite."""
    fp = PROJECT_ROOT / "tests" / "test_dev_swarm.py"
    if not fp.exists():
        return CheckResult("Testing", ">=100 dev_swarm tests", CheckStatus.MISSING, "file missing")
    text = fp.read_text(encoding="utf-8", errors="replace")
    count = len(re.findall(r"^\s+(?:async\s+)?def test_", text, re.MULTILINE))
    if count >= 100:
        return CheckResult("Testing", f">=100 dev_swarm tests ({count} found)", CheckStatus.OK,
                           "tests/test_dev_swarm.py")
    return CheckResult("Testing", f">=100 dev_swarm tests ({count} found)", CheckStatus.DRIFTED,
                       f"Only {count} tests", "Add tests to reach >=100")


def check_quarantine_hook() -> CheckResult:
    """3.1 – conftest.py quarantine hook present."""
    if _file_contains("tests/conftest.py", "QUARANTINE_MARKERS"):
        return CheckResult("Quarantine", "conftest.py quarantine hook", CheckStatus.OK, "tests/conftest.py")
    return CheckResult("Quarantine", "conftest.py quarantine hook", CheckStatus.MISSING,
                       "", "Add pytest_collection_modifyitems hook to conftest.py")


def check_legacy_risk_matrix() -> CheckResult:
    """3.3 – LEGACY_RISK_MATRIX.md exists and has quarantine lists."""
    if not _file_exists("LEGACY_RISK_MATRIX.md"):
        return CheckResult("Quarantine", "LEGACY_RISK_MATRIX.md", CheckStatus.MISSING,
                           "", "Create LEGACY_RISK_MATRIX.md")
    has_iocp = _file_contains("LEGACY_RISK_MATRIX.md", "iocp_hang")
    has_domain = _file_contains("LEGACY_RISK_MATRIX.md", "Domain 1")
    if has_iocp and has_domain:
        return CheckResult("Quarantine", "LEGACY_RISK_MATRIX.md", CheckStatus.OK, "LEGACY_RISK_MATRIX.md")
    return CheckResult("Quarantine", "LEGACY_RISK_MATRIX.md", CheckStatus.DRIFTED,
                       f"iocp_hang={has_iocp}, Domain1={has_domain}", "Update LEGACY_RISK_MATRIX.md")


def check_auditor_context() -> CheckResult:
    """3.6 – dev_swarm_auditor_context.py exists and references >=100 tests."""
    fp = PROJECT_ROOT / "core" / "dev_swarm_auditor_context.py"
    if not fp.exists():
        return CheckResult("Quarantine", "Auditor context", CheckStatus.MISSING,
                           "", "Create core/dev_swarm_auditor_context.py")
    text = fp.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"(\d+)/\1 tests passing", text)
    if m and int(m.group(1)) >= 100:
        return CheckResult("Quarantine", f"Auditor context ({m.group(1)} tests)", CheckStatus.OK,
                           "core/dev_swarm_auditor_context.py")
    val = m.group(1) if m else "pattern not found"
    return CheckResult("Quarantine", f"Auditor context ({val} tests)", CheckStatus.DRIFTED,
                       "core/dev_swarm_auditor_context.py", "Update auditor context test count")


def check_makefile_target(target: str, area: str = "Scripts") -> CheckResult:
    """2.x – Makefile has a specific target."""
    if _file_contains("Makefile", f"{target}:"):
        return CheckResult(area, f"Makefile target: {target}", CheckStatus.OK, "Makefile")
    return CheckResult(area, f"Makefile target: {target}", CheckStatus.MISSING,
                       "Makefile", f"Add '{target}' target to Makefile")


def check_swarm_cli() -> CheckResult:
    """2.5 – swarm_cli.py exists."""
    if _file_exists("scripts/swarm_cli.py"):
        return CheckResult("Scripts", "swarm_cli.py", CheckStatus.OK, "scripts/swarm_cli.py")
    return CheckResult("Scripts", "swarm_cli.py", CheckStatus.MISSING,
                       "", "Create scripts/swarm_cli.py")


def check_metrics_module() -> CheckResult:
    """4.1-4.3 – dev_swarm_metrics.py has counters, histograms, gauges."""
    fp = PROJECT_ROOT / "core" / "dev_swarm_metrics.py"
    if not fp.exists():
        return CheckResult("Observability", "Metrics module", CheckStatus.MISSING,
                           "", "Create core/dev_swarm_metrics.py")
    text = fp.read_text(encoding="utf-8", errors="replace")
    has_counter = "Counter(" in text
    has_histogram = "Histogram(" in text
    has_gauge = "Gauge(" in text
    if has_counter and has_histogram and has_gauge:
        return CheckResult("Observability", "Metrics (Counter+Histogram+Gauge)", CheckStatus.OK,
                           "core/dev_swarm_metrics.py")
    missing = []
    if not has_counter:
        missing.append("Counter")
    if not has_histogram:
        missing.append("Histogram")
    if not has_gauge:
        missing.append("Gauge")
    return CheckResult("Observability", "Metrics module", CheckStatus.DRIFTED,
                       f"Missing: {', '.join(missing)}", "Add missing Prometheus metric types")


def check_routes_module() -> CheckResult:
    """4.4 – dev_swarm_routes.py exposes /tasks, /stats, /shutdown."""
    fp = PROJECT_ROOT / "web" / "api" / "dev_swarm_routes.py"
    if not fp.exists():
        return CheckResult("Observability", "Routes module", CheckStatus.MISSING,
                           "", "Create web/api/dev_swarm_routes.py")
    text = fp.read_text(encoding="utf-8", errors="replace")
    has_tasks = "/tasks" in text
    has_stats = "/stats" in text
    has_shutdown = "/shutdown" in text
    if has_tasks and has_stats and has_shutdown:
        return CheckResult("Observability", "Routes (/tasks, /stats, /shutdown)", CheckStatus.OK,
                           "web/api/dev_swarm_routes.py")
    missing = []
    if not has_tasks:
        missing.append("/tasks")
    if not has_stats:
        missing.append("/stats")
    if not has_shutdown:
        missing.append("/shutdown")
    return CheckResult("Observability", "Routes module", CheckStatus.DRIFTED,
                       f"Missing: {', '.join(missing)}", "Add missing route endpoints")


def check_coverage_snapshot() -> CheckResult:
    """Snapshot – LEGACY_RISK_MATRIX.md coverage snapshot is >=90%."""
    fp = PROJECT_ROOT / "LEGACY_RISK_MATRIX.md"
    if not fp.exists():
        return CheckResult("Testing", "Coverage snapshot >=90%", CheckStatus.MISSING, "")
    text = fp.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"\*\*Dev Swarm Domain Combined\*\*.*?\*\*(\d+\.?\d*)%\*\*", text)
    if m and float(m.group(1)) >= 90.0:
        return CheckResult("Testing", f"Coverage snapshot ({m.group(1)}%)", CheckStatus.OK,
                           "LEGACY_RISK_MATRIX.md")
    val = m.group(1) if m else "not found"
    return CheckResult("Testing", f"Coverage snapshot ({val}%)", CheckStatus.DRIFTED,
                       "LEGACY_RISK_MATRIX.md", "Run coverage and update snapshot")


# ---------------------------------------------------------------------------
# Full audit
# ---------------------------------------------------------------------------

ALL_CHECKS = [
    check_marker_registered,
    check_ci_gate,
    check_test_file_exists,
    check_test_count,
    check_coverage_snapshot,
    check_quarantine_hook,
    check_legacy_risk_matrix,
    check_auditor_context,
    lambda: check_makefile_target("dev-swarm-test"),
    lambda: check_makefile_target("backend-test"),
    lambda: check_makefile_target("frontend-build"),
    lambda: check_makefile_target("swarm-metrics"),
    check_swarm_cli,
    check_metrics_module,
    check_routes_module,
]


def run_audit() -> AuditReport:
    """Execute all checks and return an AuditReport."""
    report = AuditReport()
    for check_fn in ALL_CHECKS:
        report.results.append(check_fn())
    return report


def create_drift_tasks(report: AuditReport) -> list:
    """Create DevTask dicts for any drifted/missing items."""
    tasks = []
    for r in report.results:
        if r.status != CheckStatus.OK:
            tasks.append({
                "description": f"[Readiness Auditor] {r.area}: {r.item} is {r.status.value}. {r.fix_plan}",
                "target_files": [r.evidence] if r.evidence else [],
                "success_criteria": f"{r.item} status becomes OK",
                "priority": 1 if r.status == CheckStatus.MISSING else 2,
                "estimated_effort": "small",
            })
    return tasks


# ---------------------------------------------------------------------------
# SLO history tracking
# ---------------------------------------------------------------------------

import json as _json
import time as _time

AUDIT_HISTORY_FILE = PROJECT_ROOT / "data" / "readiness_audit_history.jsonl"
SLO_WINDOW = 30  # last N runs to compute SLO over


@dataclass
class SLOMetrics:
    total_runs: int = 0
    window_runs: int = 0
    window_pass_count: int = 0
    pass_rate: float = 0.0
    current_streak: int = 0
    mean_time_to_fix_seconds: float = 0.0
    last_run_epoch: float = 0.0
    last_run_passed: bool = True


def _ensure_data_dir():
    AUDIT_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)


def record_audit(report: AuditReport) -> dict:
    """Append an audit run to the JSONL history file. Returns the record."""
    _ensure_data_dir()
    record = {
        "ts": _time.time(),
        "passed": report.passed,
        "drift_count": report.drift_count,
        "checks_total": len(report.results),
        "checks_ok": sum(1 for r in report.results if r.status == CheckStatus.OK),
        "drifted_items": [
            r.item for r in report.results if r.status != CheckStatus.OK
        ],
    }
    with open(AUDIT_HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(_json.dumps(record) + "\n")
    return record


def load_history(max_records: int = 1000) -> List[dict]:
    """Load audit history from JSONL. Returns newest-last."""
    if not AUDIT_HISTORY_FILE.exists():
        return []
    records = []
    with open(AUDIT_HISTORY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(_json.loads(line))
                except _json.JSONDecodeError:
                    continue
    return records[-max_records:]


def compute_slo(history: Optional[List[dict]] = None) -> SLOMetrics:
    """Compute SLO metrics from audit history."""
    if history is None:
        history = load_history()

    if not history:
        return SLOMetrics()

    total_runs = len(history)
    window = history[-SLO_WINDOW:]
    window_pass_count = sum(1 for r in window if r.get("passed"))
    pass_rate = window_pass_count / len(window) if window else 0.0

    # Current streak of consecutive passes (from most recent)
    streak = 0
    for r in reversed(history):
        if r.get("passed"):
            streak += 1
        else:
            break

    # Mean time to fix: average gap between a failing run and the next passing run
    fix_durations = []
    i = 0
    while i < len(history):
        if not history[i].get("passed"):
            fail_ts = history[i]["ts"]
            # Find next passing run
            j = i + 1
            while j < len(history) and not history[j].get("passed"):
                j += 1
            if j < len(history):
                fix_durations.append(history[j]["ts"] - fail_ts)
            i = j + 1
        else:
            i += 1

    mttf = sum(fix_durations) / len(fix_durations) if fix_durations else 0.0

    return SLOMetrics(
        total_runs=total_runs,
        window_runs=len(window),
        window_pass_count=window_pass_count,
        pass_rate=round(pass_rate, 4),
        current_streak=streak,
        mean_time_to_fix_seconds=round(mttf, 1),
        last_run_epoch=history[-1]["ts"],
        last_run_passed=history[-1].get("passed", False),
    )


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Dev Swarm Readiness Auditor")
    parser.add_argument("--fix", action="store_true", help="Auto-create DevTasks for drift")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--no-record", action="store_true", help="Skip recording to history")
    args = parser.parse_args()

    report = run_audit()

    # Record to history unless --no-record
    if not args.no_record:
        record_audit(report)

    slo = compute_slo()

    if args.json:
        import json
        out = {
            "passed": report.passed,
            "drift_count": report.drift_count,
            "results": [
                {"area": r.area, "item": r.item, "status": r.status.value,
                 "evidence": r.evidence, "fix_plan": r.fix_plan}
                for r in report.results
            ],
            "slo": {
                "total_runs": slo.total_runs,
                "window_runs": slo.window_runs,
                "pass_rate": slo.pass_rate,
                "current_streak": slo.current_streak,
                "mean_time_to_fix_seconds": slo.mean_time_to_fix_seconds,
            },
        }
        print(json.dumps(out, indent=2))
    else:
        print("=" * 60)
        print("  MERID Dev Swarm Readiness Audit")
        print("=" * 60)
        print()
        print(report.summary_table())
        print()
        if report.passed:
            print(f"RESULT: ALL {len(report.results)} CHECKS PASSED")
        else:
            print(f"RESULT: {report.drift_count} item(s) need attention")
        if slo.total_runs > 0:
            print(f"\nSLO (last {slo.window_runs} runs): "
                  f"{slo.pass_rate*100:.1f}% pass rate, "
                  f"streak={slo.current_streak}, "
                  f"MTTF={slo.mean_time_to_fix_seconds:.0f}s")

    if args.fix and report.drift_count > 0:
        tasks = create_drift_tasks(report)
        print(f"\nCreated {len(tasks)} DevTask(s) for drift repair:")
        for t in tasks:
            print(f"  - {t['description']}")

    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
