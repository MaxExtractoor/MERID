"""Utility runner for the swarm coverage improvement loop."""

from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from swarm.coverage_loop import run_coverage_improvement_loop

RUNS_DIR = Path("artifacts/coverage_loop_runs")


def _utc_timestamp() -> str:
    """Return a filesystem-safe UTC timestamp string."""
    return datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")


def run_once(
    max_rounds_without_improvement: int = 1,
    max_test_fix_attempts: int = 1,
) -> Dict[str, Any]:
    """Run a single coverage-improvement loop and persist the result."""

    start_ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[coverage-loop-runner] Starting coverage loop at {start_ts}")
    result = run_coverage_improvement_loop(
        max_rounds_without_improvement=max_rounds_without_improvement,
        max_test_fix_attempts=max_test_fix_attempts,
    )

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = _utc_timestamp()

    run_path = RUNS_DIR / f"{timestamp}.json"
    run_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")

    backlog_payload = {
        "generated_at": timestamp,
        "targets": result.get("remaining_targets", []),
    }
    backlog_path = RUNS_DIR / "coverage_backlog.json"
    backlog_path.write_text(json.dumps(backlog_payload, indent=2, sort_keys=True), encoding="utf-8")

    history_count = len(result.get("history", []) or [])
    remaining_count = len(result.get("remaining_targets", []) or [])
    print(
        "[coverage-loop-runner] Completed coverage loop:"\
        f" history={history_count}, remaining_targets={remaining_count}"
    )

    return result


def run_daemon(
    interval_seconds: int = 900,
    max_rounds_without_improvement: int = 1,
    max_test_fix_attempts: int = 1,
) -> None:
    """Periodically run the coverage-improvement loop forever (or until stopped)."""

    base_interval = max(1, int(interval_seconds))
    next_interval = base_interval
    max_interval = max(base_interval, 3600)
    while True:
        try:
            result = run_once(
                max_rounds_without_improvement=max_rounds_without_improvement,
                max_test_fix_attempts=max_test_fix_attempts,
            )
            remaining = len(result.get("remaining_targets", []) or [])
            if remaining == 0:
                next_interval = min(next_interval * 2, max_interval)
            else:
                next_interval = base_interval
        except Exception as exc:  # pragma: no cover - diagnostic path
            print(
                f"[coverage-loop-runner] Error during coverage loop: {exc}",
                file=sys.stderr,
            )
            traceback.print_exc()
            next_interval = base_interval
        time.sleep(next_interval)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Drive the MERID coverage loop.")
    parser.add_argument("--daemon", action="store_true", help="Run continuously")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=900,
        help="Sleep interval between daemon iterations (seconds)",
    )
    parser.add_argument(
        "--max-rounds-without-improvement",
        type=int,
        default=1,
        help="Forwarded to run_once",
    )
    parser.add_argument(
        "--max-test-fix-attempts",
        type=int,
        default=1,
        help="Forwarded to run_once",
    )
    args = parser.parse_args()

    if args.daemon:
        run_daemon(
            interval_seconds=args.interval_seconds,
            max_rounds_without_improvement=args.max_rounds_without_improvement,
            max_test_fix_attempts=args.max_test_fix_attempts,
        )
    else:
        run_once(
            max_rounds_without_improvement=args.max_rounds_without_improvement,
            max_test_fix_attempts=args.max_test_fix_attempts,
        )
