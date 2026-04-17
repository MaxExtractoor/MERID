#!/usr/bin/env python3
"""Lightweight triage greps for cap-safety and exposure drift (optional CI/orchestrator hook).

Examples:
  python scripts/egg_hunter.py
  python scripts/egg_hunter.py --roots merid web

Does not modify the tree; prints findings to stdout.
"""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

# (regex, hint)
PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"CategoryExposureTracker[^\n]{0,120}non-blocking", re.I),
        "Verify fail-closed: tracker errors must not proceed to live orders",
    ),
    (
        re.compile(r"get_category_exposure_tracker\(\)[\s\S]{0,200}except[\s\S]{0,80}pass", re.M),
        "Bare pass after tracker fetch — confirm intentional",
    ),
]

# Narrow defaults for speed; pass --roots merid web core tests for full triage.
DEFAULT_ROOTS = ("merid", "web")


def _git_diff_names() -> list[str] | None:
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if r.returncode != 0:
            return None
        return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--roots",
        nargs="*",
        default=list(DEFAULT_ROOTS),
        help="Subdirectories under repo root to scan (default: merid web core tests)",
    )
    ap.add_argument(
        "--diff-only",
        action="store_true",
        help="Restrict scan to paths changed vs HEAD (falls back to full scan if git unavailable)",
    )
    args = ap.parse_args()
    repo = Path(__file__).resolve().parent.parent
    diff_set: set[str] | None = None
    if args.diff_only:
        names = _git_diff_names()
        if names is not None:
            diff_set = set(names)

    hits = 0
    for root in args.roots:
        base = repo / root
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if diff_set is not None:
                try:
                    rel = path.relative_to(repo).as_posix()
                except ValueError:
                    continue
                if rel not in diff_set:
                    continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for pat, hint in PATTERNS:
                if pat.search(text):
                    print(f"{path.relative_to(repo)}: {hint}")
                    hits += 1
                    break

    print(f"egg_hunter: scan complete ({hits} file(s) matched a pattern)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
