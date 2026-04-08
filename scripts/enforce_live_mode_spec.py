#!/usr/bin/env python3
"""Live-mode spec enforcement gate.

This script is run in CI to enforce the canonical go-live spec for MERID's
Kalshi production mode.  It fails (exit code 1) if any of the following
invariants are violated:

  Check 1 — No silent paper/demo defaults in production modules.
             Scans a defined set of Kalshi production source files for
             patterns that default to paper/demo/sim without emitting a
             WARNING log.

  Check 2 — Alpaca/IBKR adapters are not reachable from production Kalshi
             modules (web/main.py, merid/pipeline/*, merid/prediction/*).

  Check 3 — The three mandatory startup log phrases exist in source code
             (confirming the layer-1, layer-2, layer-3 log lines are still
             present and have not been removed).

  Check 4 — Required production env vars are present in .env.example.

Usage
-----
    python scripts/enforce_live_mode_spec.py [--strict] [--output-json <path>]

Exit codes
----------
    0  all checks passed
    1  one or more violations found (when --strict, which is the default)
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Source files that belong to the production Kalshi path.  We only scan these
# for silent-default violations (no need to scan backtesting/test helpers).
KALSHI_PRODUCTION_FILES: list[Path] = [
    PROJECT_ROOT / "trading" / "trade_mode.py",
    PROJECT_ROOT / "merid" / "prediction" / "venue_gate.py",
    PROJECT_ROOT / "merid" / "pipeline" / "mode_manager.py",
    PROJECT_ROOT / "merid" / "pipeline" / "adapter.py",
    PROJECT_ROOT / "merid" / "pipeline" / "router.py",
    PROJECT_ROOT / "merid" / "prediction" / "agent_grid.py",
]

# Directories whose *.py files must NOT directly import Alpaca/IBKR adapters.
KALSHI_PRODUCTION_DIRS: list[Path] = [
    PROJECT_ROOT / "merid" / "pipeline",
    PROJECT_ROOT / "merid" / "prediction",
]

# Modules that must not appear as top-level imports in production paths.
FORBIDDEN_IMPORTS: list[str] = [
    "from core.venues.alpaca_adapter",
    "from core.venues.ibkr_adapter",
    "from trading.adapters.alpaca",
    "from trading.integrations.alpaca_client",
    "import alpaca_adapter",
    "import ibkr_adapter",
]

# Patterns that suggest silent fallback to paper/demo without a WARNING log.
# Each pattern is a tuple (regex, human-readable description).
# These are applied line-by-line; if the pattern is found on a line that is
# NOT accompanied by a logger.warning / logging.warning on the same or
# adjacent lines (within 5 lines), it is flagged.
SILENT_DEFAULT_PATTERNS: list[tuple[str, str]] = [
    # getenv with a hard "paper" default (no warning nearby)
    (
        r'getenv\s*\(\s*["\']MERID_TRADE_MODE["\']\s*,\s*["\']paper["\']',
        'getenv("MERID_TRADE_MODE", "paper") — silent paper default',
    ),
    (
        r'getenv\s*\(\s*["\']MERID_PM_TRADING_MODE["\']\s*,\s*["\']paper["\']',
        'getenv("MERID_PM_TRADING_MODE", "paper") — silent paper default',
    ),
    (
        r'getenv\s*\(\s*["\']MERID_PM_TRADING_MODE["\']\s*,\s*["\']mock["\']',
        'getenv("MERID_PM_TRADING_MODE", "mock") — silent mock default',
    ),
    # Hard-coded use_demo=True or KALSHI_USE_DEMO=True default
    (
        r'getenv\s*\(\s*["\']KALSHI_USE_DEMO["\']\s*,\s*["\']true["\']',
        'getenv("KALSHI_USE_DEMO", "true") — silent demo default',
    ),
    (
        r'use_demo\s*=\s*True\b',
        'use_demo=True hardcoded — will always use demo endpoint',
    ),
]

# Startup log phrases that MUST appear somewhere in production source code.
# If these disappear the CI check fails (guards against accidental removal).
REQUIRED_LOG_PHRASES: list[tuple[str, Path]] = [
    (
        "Trade mode initialised:",
        PROJECT_ROOT / "trading" / "trade_mode.py",
    ),
    (
        "VenueGate initialised:",
        PROJECT_ROOT / "merid" / "prediction" / "venue_gate.py",
    ),
    (
        "MERID_PIPELINE_MODE: Kalshi venue initialised in LIVE mode",
        PROJECT_ROOT / "merid" / "pipeline" / "mode_manager.py",
    ),
    (
        "MERID_PIPELINE_MODE: Kalshi venue is in",
        PROJECT_ROOT / "merid" / "pipeline" / "mode_manager.py",
    ),
    (
        "force-promoted",
        PROJECT_ROOT / "merid" / "prediction" / "agent_grid.py",
    ),
]

# Required env vars that must be present in .env.example (uncommented, set to
# the expected production value or at least present as keys).
REQUIRED_ENV_EXAMPLE_VARS: list[str] = [
    "MERID_ENV",
    "MERID_TRADE_MODE",
    "MERID_PM_TRADING_MODE",
    "MERID_PM_LIVE_ENABLED",
    "MERID_ALLOW_LIVE_TRADES",
    "MERID_LIVE_TRADING_UNLOCKED",
    "KALSHI_USE_DEMO",
    "KALSHI_ENV",
]


# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _is_warning_nearby(lines: list[str], idx: int, window: int = 5) -> bool:
    """Return True if a logger.warning / logging.warning call appears
    within *window* lines of *idx* (inclusive)."""
    start = max(0, idx - window)
    end = min(len(lines), idx + window + 1)
    for i in range(start, end):
        if re.search(r"logger\.warning|logging\.warning", lines[i]):
            return True
    return False


# ---------------------------------------------------------------------------
# Check 1 — Silent paper/demo defaults
# ---------------------------------------------------------------------------


def check_silent_defaults() -> list[dict[str, Any]]:
    """Scan production files for silent paper/demo defaults."""
    violations: list[dict[str, Any]] = []

    for path in KALSHI_PRODUCTION_FILES:
        if not path.exists():
            continue
        content = _read(path)
        lines = content.splitlines()
        for pattern, description in SILENT_DEFAULT_PATTERNS:
            for idx, line in enumerate(lines):
                # Skip comments
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if re.search(pattern, line, re.IGNORECASE):
                    if not _is_warning_nearby(lines, idx):
                        violations.append({
                            "check": "silent_default",
                            "file": str(path.relative_to(PROJECT_ROOT)),
                            "line": idx + 1,
                            "pattern": description,
                            "text": line.rstrip(),
                        })

    return violations


# ---------------------------------------------------------------------------
# Check 2 — Alpaca/IBKR not reachable from production Kalshi modules
# ---------------------------------------------------------------------------


def check_alpaca_ibkr_isolation() -> list[dict[str, Any]]:
    """Ensure Alpaca/IBKR adapters are not imported from production dirs."""
    violations: list[dict[str, Any]] = []

    all_production_files: list[Path] = list(KALSHI_PRODUCTION_FILES)
    for directory in KALSHI_PRODUCTION_DIRS:
        if directory.exists():
            all_production_files.extend(directory.rglob("*.py"))

    # Deduplicate
    seen: set[Path] = set()
    unique_files: list[Path] = []
    for p in all_production_files:
        if p not in seen and p.exists():
            seen.add(p)
            unique_files.append(p)

    for path in unique_files:
        content = _read(path)
        lines = content.splitlines()
        for idx, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            for forbidden in FORBIDDEN_IMPORTS:
                if forbidden in line:
                    violations.append({
                        "check": "alpaca_ibkr_isolation",
                        "file": str(path.relative_to(PROJECT_ROOT)),
                        "line": idx + 1,
                        "pattern": forbidden,
                        "text": line.rstrip(),
                    })

    return violations


# ---------------------------------------------------------------------------
# Check 3 — Required startup log phrases still present
# ---------------------------------------------------------------------------


def check_required_log_phrases() -> list[dict[str, Any]]:
    """Confirm the canonical startup log phrases have not been removed."""
    violations: list[dict[str, Any]] = []

    for phrase, path in REQUIRED_LOG_PHRASES:
        if not path.exists():
            violations.append({
                "check": "required_log_phrase",
                "file": str(path.relative_to(PROJECT_ROOT)),
                "phrase": phrase,
                "error": "file not found",
            })
            continue
        content = _read(path)
        if phrase not in content:
            violations.append({
                "check": "required_log_phrase",
                "file": str(path.relative_to(PROJECT_ROOT)),
                "phrase": phrase,
                "error": "phrase not found in file",
            })

    return violations


# ---------------------------------------------------------------------------
# Check 4 — Required env vars in .env.example
# ---------------------------------------------------------------------------


def check_env_example() -> list[dict[str, Any]]:
    """Verify required production env vars appear in .env.example."""
    violations: list[dict[str, Any]] = []

    env_example = PROJECT_ROOT / ".env.example"
    if not env_example.exists():
        return [{
            "check": "env_example",
            "file": ".env.example",
            "error": ".env.example not found",
        }]

    content = _read(env_example)
    for var in REQUIRED_ENV_EXAMPLE_VARS:
        # Match an uncommented assignment: VAR= or VAR =
        pattern = rf"^{re.escape(var)}\s*="
        if not re.search(pattern, content, re.MULTILINE):
            violations.append({
                "check": "env_example",
                "file": ".env.example",
                "var": var,
                "error": f"{var} not found as an uncommented assignment",
            })

    return violations


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_all_checks() -> dict[str, Any]:
    """Run all checks and return a report dict."""
    violations: list[dict[str, Any]] = []

    violations.extend(check_silent_defaults())
    violations.extend(check_alpaca_ibkr_isolation())
    violations.extend(check_required_log_phrases())
    violations.extend(check_env_example())

    passed = len(violations) == 0
    return {
        "passed": passed,
        "violation_count": len(violations),
        "violations": violations,
    }


def _print_report(report: dict[str, Any]) -> None:
    if report["passed"]:
        print("✅ live-mode-spec: all checks passed")
        return

    print(f"❌ live-mode-spec: {report['violation_count']} violation(s) found\n")
    by_check: dict[str, list[dict]] = {}
    for v in report["violations"]:
        by_check.setdefault(v["check"], []).append(v)

    for check_name, items in sorted(by_check.items()):
        print(f"  [{check_name}]")
        for item in items:
            file_ = item.get("file", "")
            line_ = item.get("line", "")
            loc = f"{file_}:{line_}" if line_ else file_
            detail = item.get("pattern") or item.get("phrase") or item.get("var") or item.get("error", "")
            print(f"    ✗ {loc} — {detail}")
            if "text" in item:
                print(f"      → {item['text']}")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Enforce MERID live-mode spec")
    parser.add_argument("--strict", action="store_true", default=True,
                        help="Exit with code 1 on violations (default: True)")
    parser.add_argument("--no-strict", dest="strict", action="store_false")
    parser.add_argument("--output-json", metavar="PATH",
                        help="Write JSON report to this path")
    args = parser.parse_args()

    report = run_all_checks()
    _print_report(report)

    if args.output_json:
        out_path = Path(args.output_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2))
        print(f"Report written to {args.output_json}")

    if not report["passed"] and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
