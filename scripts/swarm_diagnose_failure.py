#!/usr/bin/env python3
"""Swarm CI failure diagnostician — DevSwarm self-healing helper.

Analyses a GitHub Actions run failure and produces a structured diagnosis
to guide autonomous or human remediation.

Usage:
    python swarm_diagnose_failure.py \
        --run-id=12345678 \
        --output=diagnosis.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(description="Swarm CI failure diagnostician")
    p.add_argument("--run-id", required=True, help="GitHub Actions run ID")
    p.add_argument("--output", default="diagnosis.json")
    return p.parse_args()


def collect_local_signals():
    """Gather available local signals (test reports, logs)."""
    signals = {}
    project_root = Path(__file__).parent.parent

    report_dir = project_root / "reports"
    if report_dir.exists():
        reports = list(report_dir.glob("*.xml"))
        signals["test_reports"] = [str(r.name) for r in reports]
    else:
        signals["test_reports"] = []

    log_dir = project_root / "logs"
    signals["log_files"] = [str(f.name) for f in log_dir.glob("*.log")] if log_dir.exists() else []

    return signals


def main():
    args = parse_args()

    signals = collect_local_signals()

    diagnosis = {
        "run_id": args.run_id,
        "diagnosed_at": datetime.now(timezone.utc).isoformat(),
        "status": "stub",
        "note": (
            "Full GitHub API integration not yet implemented. "
            "Attach test reports as artifacts and inspect manually."
        ),
        "local_signals": signals,
        "recommended_actions": [
            "Review failing test output in GitHub Actions logs",
            "Check reports/ artifacts for JUnit XML details",
            "Run locally: python -m pytest tests/ --tb=short -x",
        ],
    }

    output_path = Path(args.output)
    output_path.write_text(json.dumps(diagnosis, indent=2))
    print(f"Diagnosis written to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
