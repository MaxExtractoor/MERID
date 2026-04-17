"""Utilities to run swarm pytest suite with coverage and structured results."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

_PYTEST_COMMAND = [
    sys.executable,
    "-m",
    "pytest",
    "tests/swarm",
    "--cov=swarm",
    "--cov-report=term-missing",
    "--cov-fail-under=0",
    "-q",
]

# Coverage table sample:
# Name                          Stmts   Miss  Cover   Missing
# -----------------------------------------------------------
# swarm/module.py                  10      1    90%   10
# TOTAL                           100      5    95%
_FILE_LINE_REGEX = re.compile(
    r"^(?P<name>\S[^\s]*)\s+"  # file name
    r"(?P<stmts>\d+)\s+"         # statements
    r"(?P<miss>\d+)\s+"          # misses
    r"(?P<cover>\d+(?:\.\d+)?)%"  # coverage percent
    r"\s*(?P<missing>.*)$"        # missing line info (optional)
)
_TOTAL_LINE_REGEX = re.compile(r"^TOTAL\s+\d+\s+\d+\s+(?P<cover>\d+(?:\.\d+)?)%")


def _parse_coverage_table(output: str) -> Tuple[List[Dict[str, object]], float]:
    """Extract per-file coverage rows and total coverage from pytest output."""
    lines = output.splitlines()
    header_idx = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("Name") and "Stmts" in stripped and "Cover" in stripped:
            header_idx = idx
            break
    if header_idx is None:
        return [], 0.0

    files: List[Dict[str, object]] = []
    total_coverage = 0.0

    for line in lines[header_idx + 1 :]:
        stripped = line.strip()
        if not stripped or set(stripped) == {"-"}:
            continue
        total_match = _TOTAL_LINE_REGEX.match(stripped)
        if total_match:
            total_coverage = float(total_match.group("cover"))
            break

        match = _FILE_LINE_REGEX.match(line)
        if not match:
            continue

        missing_raw = match.group("missing").strip()
        missing_lines = [seg.strip() for seg in missing_raw.split(",") if seg.strip()]

        files.append(
            {
                "name": match.group("name"),
                "stmts": int(match.group("stmts")),
                "miss": int(match.group("miss")),
                "coverage": float(match.group("cover")),
                "missing_lines": missing_lines,
            }
        )

    return files, total_coverage


def run_swarm_tests(timeout_seconds: int = 300) -> Dict[str, object]:
    """Run pytest+coverage for tests/swarm and return structured coverage details."""
    repo_root = Path(__file__).resolve().parents[2]

    try:
        completed = subprocess.run(
            _PYTEST_COMMAND,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        combined_output = stdout + ("\n" + stderr if stderr else "")
        tests_passed = completed.returncode == 0
    except subprocess.TimeoutExpired as exc:
        captured_out = exc.stdout or ""
        captured_err = exc.stderr or ""
        combined_output = (
            (captured_out or "") + ("\n" + captured_err if captured_err else "") + "\n[run_swarm_tests] Timeout"
        )
        tests_passed = False

    files, total_cov = _parse_coverage_table(combined_output)

    return {
        "total_coverage": total_cov,
        "tests_passed": tests_passed,
        "files": files,
        "raw_output": combined_output,
    }
