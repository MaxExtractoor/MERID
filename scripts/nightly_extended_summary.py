"""Summarize the nightly report-only extended suite and check its baseline.

Reads the junit written by the report-only ``pytest tests/`` step
(``results/extended_tests.xml`` by default) and publishes the counts to
``$GITHUB_STEP_SUMMARY``.  When ``config/nightly_extended_baseline.json``
carries a numeric ``failures_plus_errors`` baseline, a run exceeding it emits
a ``::warning::`` annotation — the suite is report-only, so this ratchet
surfaces backlog regressions without gating the job.  Always exits 0.
"""
from __future__ import annotations

import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JUNIT_PATH = Path(os.environ.get("EXTENDED_JUNIT", "results/extended_tests.xml"))
BASELINE_PATH = Path(
    os.environ.get("EXTENDED_BASELINE", "config/nightly_extended_baseline.json")
)


def _junit_counts(path: Path) -> dict[str, int] | None:
    if not path.is_file():
        return None
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return None
    for suite in root.iter("testsuite"):
        for key in counts:
            counts[key] += int(suite.get(key, "0"))
    return counts


def _baseline(path: Path) -> int | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = data.get("failures_plus_errors")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def main() -> int:
    counts = _junit_counts(JUNIT_PATH)
    bad = None if counts is None else counts["failures"] + counts["errors"]
    baseline = _baseline(BASELINE_PATH)

    lines = ["### Extended suite (report-only)", ""]
    if counts is None:
        lines.append(
            f"Junit `{JUNIT_PATH}` missing or unparsable — the run was killed "
            "before pytest could finish the session (watchdog/timeout)."
        )
    else:
        lines += [
            f"- tests run: **{counts['tests']}**",
            f"- failures: **{counts['failures']}**, "
            f"errors: **{counts['errors']}** "
            f"(not-passing total: **{bad}**)",
            f"- skipped: {counts['skipped']}",
        ]
        if baseline is None:
            lines.append(
                "- baseline: _unset_ — set `failures_plus_errors` in "
                f"`{BASELINE_PATH}` to the observed count to arm the ratchet."
            )
        elif bad > baseline:
            lines.append(
                f"- baseline: **{baseline}** — EXCEEDED by {bad - baseline}; "
                "backlog regressed."
            )
            print(
                f"::warning::Extended suite not-passing total {bad} exceeds "
                f"baseline {baseline} — backlog regression (report-only, "
                "not gating)"
            )
        else:
            lines.append(f"- baseline: {baseline} — within tolerance.")

    text = "\n".join(lines) + "\n"
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text)
    print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
