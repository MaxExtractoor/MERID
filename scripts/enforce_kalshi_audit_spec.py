#!/usr/bin/env python3
"""CLI gate — enforces the Kalshi sentiment audit spec as policy-as-code.

Checks performed
----------------
1. **Invariants** — calls ``merid.formulas.check_invariants()`` to verify that
   ``COMPONENT_WEIGHTS`` sum to 1.0, band boundaries are ordered, and R/A/G
   thresholds are consistent.

2. **No-custom-math** — scans all ``*.py`` files in the Kalshi sentiment pipeline
   and flags any module that defines its own math functions instead of importing
   from ``merid.formulas``.  The exact set of banned patterns is ``_rolling_std``,
   ``_normalize_vol``, ``_normalize_volume``, ``_book_imbalance``, and
   ``_score_to_100`` (the legacy private helpers that were retired when
   ``merid/formulas.py`` was introduced).

3. **Version tags** — verifies that ``FORMULAS_VERSION`` and
   ``AUDIT_SPEC_VERSION`` are present and non-empty in ``merid/formulas.py``.

4. **Audit spec doc** — confirms ``AGENT_AUDIT_KALSHI_SENTIMENT.md`` exists and
   contains the current version strings.

Usage
-----
    python scripts/enforce_kalshi_audit_spec.py [--strict] [--output-json <path>]

Exit codes
----------
- 0  all checks passed (or --no-strict with warnings)
- 1  one or more violations found and --strict is set (default)
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── Paths ─────────────────────────────────────────────────────────────────────

FORMULAS_MODULE = PROJECT_ROOT / "merid" / "formulas.py"
AUDIT_SPEC_DOC  = PROJECT_ROOT / "AGENT_AUDIT_KALSHI_SENTIMENT.md"

# Files that are part of the Kalshi sentiment pipeline (must not define custom math)
SENTIMENT_PIPELINE_FILES = [
    PROJECT_ROOT / "merid" / "event_venues" / "kalshi" / "sentiment.py",
    PROJECT_ROOT / "merid" / "event_venues" / "kalshi" / "discovery_validator.py",
    PROJECT_ROOT / "merid" / "event_venues" / "kalshi" / "protection_enhancements.py",
]

# Legacy private helpers that must NOT be re-defined outside merid/formulas.py
BANNED_DEFINITIONS = {
    "_rolling_std",
    "_normalize_vol",
    "_normalize_volume",
    "_book_imbalance",
    "_score_to_100",
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _check_invariants() -> list[str]:
    """Run merid.formulas.check_invariants() and return any violations."""
    try:
        from merid.formulas import check_invariants
        return check_invariants()
    except Exception as exc:
        return [f"Could not import merid.formulas: {exc}"]


def _check_no_custom_math() -> list[str]:
    """Scan pipeline files for re-definitions of banned math helpers."""
    violations: list[str] = []
    for path in SENTIMENT_PIPELINE_FILES:
        if not path.exists():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            violations.append(f"{path.relative_to(PROJECT_ROOT)}: SyntaxError — {exc}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in BANNED_DEFINITIONS:
                    # Allow shims that only contain a single `return` delegating
                    # to the canonical function — detect by checking if the body
                    # is just a return statement (possibly with a docstring first).
                    body = [
                        n for n in node.body
                        if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))
                    ]
                    if len(body) == 1 and isinstance(body[0], ast.Return):
                        # One-liner shim → allowed
                        continue
                    violations.append(
                        f"{path.relative_to(PROJECT_ROOT)}:{node.lineno} — "
                        f"'{node.name}' must not be re-defined outside merid/formulas.py"
                    )
    return violations


def _check_version_tags() -> list[str]:
    """Verify FORMULAS_VERSION and AUDIT_SPEC_VERSION are defined and non-empty."""
    violations: list[str] = []
    try:
        from merid.formulas import AUDIT_SPEC_VERSION, FORMULAS_VERSION
        if not FORMULAS_VERSION:
            violations.append("FORMULAS_VERSION is empty in merid/formulas.py")
        if not AUDIT_SPEC_VERSION:
            violations.append("AUDIT_SPEC_VERSION is empty in merid/formulas.py")
    except ImportError as exc:
        violations.append(f"Could not import version constants: {exc}")
    return violations


def _check_audit_spec_doc() -> list[str]:
    """Confirm AGENT_AUDIT_KALSHI_SENTIMENT.md exists and contains version strings."""
    violations: list[str] = []
    if not AUDIT_SPEC_DOC.exists():
        violations.append(
            f"{AUDIT_SPEC_DOC.name} not found — create it from the template in the PR description"
        )
        return violations

    try:
        from merid.formulas import AUDIT_SPEC_VERSION, FORMULAS_VERSION
    except ImportError:
        return violations  # version check already failed above

    content = AUDIT_SPEC_DOC.read_text(encoding="utf-8")
    if FORMULAS_VERSION not in content:
        violations.append(
            f"{AUDIT_SPEC_DOC.name} does not mention FORMULAS_VERSION={FORMULAS_VERSION!r} — "
            "update the document version table"
        )
    if AUDIT_SPEC_VERSION not in content:
        violations.append(
            f"{AUDIT_SPEC_DOC.name} does not mention AUDIT_SPEC_VERSION={AUDIT_SPEC_VERSION!r} — "
            "update the document version table"
        )
    return violations


# ── Main ──────────────────────────────────────────────────────────────────────


def run_gate() -> dict[str, Any]:
    """Run all checks and return a machine-readable report dict."""
    report: dict[str, Any] = {
        "ok": True,
        "checks": {},
        "violations": [],
    }

    checks = {
        "invariants":       _check_invariants,
        "no_custom_math":   _check_no_custom_math,
        "version_tags":     _check_version_tags,
        "audit_spec_doc":   _check_audit_spec_doc,
    }

    for name, fn in checks.items():
        issues = fn()
        report["checks"][name] = {"ok": len(issues) == 0, "issues": issues}
        if issues:
            report["ok"] = False
            report["violations"].extend(issues)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Kalshi audit-spec policy gate",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        help="Write machine-readable report to this path",
    )
    default_strict = os.getenv("KALSHI_AUDIT_STRICT", "1").strip().lower() in {
        "1", "true", "yes", "on"
    }
    parser.set_defaults(strict=default_strict)
    parser.add_argument("--strict",    dest="strict", action="store_true")
    parser.add_argument("--no-strict", dest="strict", action="store_false")
    args = parser.parse_args()

    report = run_gate()

    print("MERID Kalshi Audit-Spec Gate")
    print("=" * 40)
    for name, result in report["checks"].items():
        status = "OK" if result["ok"] else "FAIL"
        print(f"  [{status}] {name}")
        for issue in result["issues"]:
            print(f"        • {issue}")

    if report["ok"]:
        print("\nAll checks passed.")
    else:
        print(f"\n{len(report['violations'])} violation(s) found.")

    if args.output_json:
        out = Path(args.output_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report written to {args.output_json}")

    if not report["ok"] and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
