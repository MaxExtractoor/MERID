"""Convenience runner for full test + coverage workflow."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def run_step(label: str, command: list[str], env: dict[str, str]) -> int:
    print(f"\n=== {label} ===")
    result = subprocess.run(command, cwd=REPO_ROOT, env=env)
    if result.returncode != 0:
        print(f"{label} failed with exit code {result.returncode}")
    return result.returncode


def main() -> int:
    env = os.environ.copy()
    env.setdefault("COVERAGE_FILE", ".coverage/coverage.data")
    env.setdefault("MERID_RUN_PROD_TESTS", "0")
    legacy_file = REPO_ROOT / ".coverage"
    if legacy_file.is_file():
        legacy_file.unlink()
    pytest_cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-m",
        "not prod_integration",
        "--maxfail=1",
        "--cov=analytics",
        "--cov=swarm",
        "--cov=core",
        "--cov-report=term",
        "--cov-report=xml:.coverage/coverage.xml",
        "--cov-report=json:.coverage/coverage.json",
        "--cov-fail-under=18",
    ]
    steps = [
        ("Pytest Suite", pytest_cmd),
        ("Coverage Analyzer", [sys.executable, "scripts/run_coverage_analysis.py"]),
    ]
    exit_code = 0
    for label, cmd in steps:
        code = run_step(label, cmd, env)
        if code != 0 and exit_code == 0:
            exit_code = code
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
