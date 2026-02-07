"""Enforce per-file coverage floors for safety/risk-critical modules."""

from __future__ import annotations

import json
import sys
from pathlib import Path

THRESHOLDS = {
    "swarm/anti_silent_failure.py": 0.90,
    "swarm/security_defense_system.py": 0.85,
    "core/automated_risk_controls.py": 0.92,
    "analytics/onboarding_metrics.py": 0.90,
    "analytics/network_analytics.py": 0.90,
    "analytics/revenue_risk.py": 0.88,
    "analytics/health_score.py": 0.90,
}


def _load_report(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Coverage report not found: {path}")
    return json.loads(path.read_text())


def _lookup_file(report: dict, rel_path: str) -> dict | None:
    files = report.get("files", {})
    for filename, data in files.items():
        if filename.endswith(rel_path):
            return data
    return None


def main() -> int:
    report_path = Path(".coverage/coverage.json")
    try:
        report = _load_report(report_path)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    failures: list[str] = []
    for rel_path, threshold in THRESHOLDS.items():
        data = _lookup_file(report, rel_path)
        if not data:
            failures.append(f"{rel_path}: missing from coverage report")
            continue
        summary = data.get("summary") or {}
        covered = summary.get("percent_covered")
        if covered is None:
            failures.append(f"{rel_path}: coverage data missing")
            continue
        pct = covered / 100 if covered > 1 else covered
        if pct < threshold:
            failures.append(f"{rel_path}: {pct:.2%} < {threshold:.0%}")

    if failures:
        print("Per-file coverage thresholds failed:")
        for failure in failures:
            print(f" - {failure}")
        return 2

    print("Per-file coverage thresholds satisfied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
