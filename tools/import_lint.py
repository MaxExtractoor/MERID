"""
Lightweight import linter for MERID.

Implements the "import linting" recommendation from DUPLICATES_COLLISIONS_REPORT.md §6.3.3.

Rules (enforced best-effort, non-fatal):
  1. New code should prefer `merid.*` namespaces over legacy top-level packages:
     - discouraged: `agents.*`, `core.*`, `trading.*`, `web.api.*`
     - preferred:   `merid.*`
  2. No production code may import from `archive.legacy_scripts.*`.

This script is intentionally conservative: it prints warnings to stdout and exits
with code 1 if violations are found, so it can be wired into CI, but it will not
attempt to auto-fix anything.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Iterable, List, Tuple


ROOT = Path(__file__).resolve().parents[1]

DISCOURAGED_PREFIXES = (
    "from agents.",
    "import agents.",
    "from core.",
    "import core.",
    "from trading.",
    "import trading.",
    "from web.api.",
    "import web.api.",
)

FORBIDDEN_PREFIXES = (
    "from archive.legacy_scripts",
    "import archive.legacy_scripts",
)

IGNORE_DIRS = {
    ".git",
    ".ruff_cache",
    ".mypy_cache",
    "node_modules",
    "archive/legacy_scripts",
    "venv",
    ".venv",
}


def iter_py_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        # Prune ignored directories
        pruned_dirnames: List[str] = []
        for d in list(dirnames):
            rel_dir = (rel / d).as_posix()
            if any(rel_dir.startswith(ig) for ig in IGNORE_DIRS):
                continue
            pruned_dirnames.append(d)
        dirnames[:] = pruned_dirnames

        for fname in filenames:
            if fname.endswith(".py"):
                yield Path(dirpath) / fname


def check_file(path: Path) -> List[Tuple[int, str]]:
    """Return list of (line_number, message) violations."""
    violations: List[Tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return violations

    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        for pref in FORBIDDEN_PREFIXES:
            if stripped.startswith(pref):
                violations.append(
                    (
                        lineno,
                        f"FORBIDDEN import from archived legacy scripts: `{stripped}`",
                    )
                )
                break

        for pref in DISCOURAGED_PREFIXES:
            if stripped.startswith(pref):
                # Heuristic: allow explicit legacy comments to suppress
                if "# legacy-ok" in line:
                    break
                violations.append(
                    (
                        lineno,
                        f"Discouraged legacy import (prefer `merid.*`): `{stripped}`",
                    )
                )
                break

    return violations


def main(argv: List[str]) -> int:
    root = ROOT
    if len(argv) > 1:
        root = Path(argv[1]).resolve()

    all_violations: List[Tuple[Path, int, str]] = []
    for path in iter_py_files(root):
        v = check_file(path)
        for lineno, msg in v:
            all_violations.append((path, lineno, msg))

    if not all_violations:
        print("import_lint: no violations found")
        return 0

    print("import_lint: found import violations:", file=sys.stderr)
    for path, lineno, msg in all_violations:
        rel = path.relative_to(root)
        print(f"  {rel}:{lineno}: {msg}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

