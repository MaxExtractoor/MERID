"""Regression detector — new code that broke existing behaviour.

Regressions are best caught by:
  1. Finding recently-modified files that touch shared/critical abstractions
  2. Finding callers of recently-changed function signatures
  3. Finding shared constants/types changed without updating all consumers
  4. Test files that were removed or had assertions weakened

This detector uses git log to identify high-risk recent changes.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tools.audit.detectors import BaseDetector
from tools.audit.models import Finding, Layer, Severity


class RegressionDetector(BaseDetector):
    name = "regression"

    # Shared abstractions — changes here ripple widely
    _SHARED_PATTERNS = [
        (r'useApiData|useApiData\.ts',         "Core polling hook — all components depend on this"),
        (r'useMeridSocket|useMeridSocket\.ts',  "Core WS bus — all real-time components depend on this"),
        (r'constants\.ts',                      "Endpoint/polling constants — all hooks read from here"),
        (r'auth\.ts|auth\.py',                 "Auth logic — affects every authenticated request"),
        (r'models\.py|schemas\.py',            "Pydantic models — shape mismatch breaks all consumers"),
        (r'web/main\.py',                      "FastAPI app — router registration, middleware, startup"),
        (r'config/trading_constants\.py',      "Financial magic numbers — affects all position sizing"),
        (r'consensus_coordinator\.py',         "Consensus logic — affects all swarm decisions"),
        (r'execution_gate\.py|execution_subscriber\.py', "Execution gate — affects all trade routing"),
    ]

    def detect(self, root: Path) -> list[Finding]:
        findings: list[Finding] = []
        findings.extend(self._scan_recent_shared_changes(root))
        findings.extend(self._scan_weakened_tests(root))
        findings.extend(self._scan_type_mismatches(root))
        return findings

    def _recent_changed_files(self, root: Path, n: int = 20) -> list[str]:
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", f"HEAD~{n}", "HEAD"],
                cwd=root, capture_output=True, timeout=15,
            )
            if result.returncode == 0:
                return [l.strip() for l in result.stdout.decode("utf-8", errors="ignore").splitlines() if l.strip()]
        except Exception:
            pass
        return []

    def _scan_recent_shared_changes(self, root: Path) -> list[Finding]:
        findings: list[Finding] = []
        changed = self._recent_changed_files(root)
        if not changed:
            return findings

        for path in changed:
            for pattern, description in self._SHARED_PATTERNS:
                if re.search(pattern, path, re.IGNORECASE):
                    # Determine layer
                    if path.startswith("web/react"):
                        layer = Layer.FRONTEND
                    elif any(path.startswith(x) for x in ("web/api", "agents", "merid", "core", "consensus")):
                        layer = Layer.BACKEND
                    else:
                        layer = Layer.CROSS

                    # Test files are HIGH at most — the source file is what matters
                    is_test = path.startswith("tests/") or "/test_" in path or "/__tests__/" in path
                    sev = Severity.HIGH  # default
                    if not is_test and re.search(
                        r'auth|execution_gate|trading_constants|consensus_coordinator|web/main',
                        path, re.IGNORECASE
                    ):
                        sev = Severity.CRITICAL

                    findings.append(Finding(
                        bug_type="regression",
                        severity=sev,
                        layer=layer,
                        file=path, line=1,
                        snippet="",
                        title=f"Shared abstraction modified: `{path}`",
                        explanation=(
                            f"{description}. Recent modification to this file is high-risk: "
                            "all consumers could be affected."
                        ),
                        suggestion=(
                            "Verify all consumers still work correctly. "
                            "Check that any changed signatures/constants are updated everywhere."
                        ),
                    ))
                    break  # one finding per file

        return findings

    def _scan_weakened_tests(self, root: Path) -> list[Finding]:
        """Find test files where assertions were removed or .skip added recently."""
        findings: list[Finding] = []
        try:
            result = subprocess.run(
                ["git", "diff", "HEAD~10", "HEAD", "--", "tests/**/*.py", "web/react/src/**/*.test.*"],
                cwd=root, capture_output=True, timeout=15,
            )
            diff = result.stdout.decode("utf-8", errors="ignore")
        except Exception:
            return findings

        # Lines removed from test files that looked like assertions
        removed_assertions = re.findall(r'^-.*(?:assert|expect\(|toBe|toEqual|toHaveBeenCalled)', diff, re.MULTILINE)
        if removed_assertions:
            findings.append(Finding(
                bug_type="regression",
                severity=Severity.HIGH,
                layer=Layer.CROSS,
                file="tests/ (recent diff)",
                line=1,
                snippet=removed_assertions[0][:120] if removed_assertions else "",
                title=f"{len(removed_assertions)} assertion(s) removed from tests in last 10 commits",
                explanation=(
                    "Removing assertions weakens the test suite — regressions covered by those "
                    "assertions will now pass CI silently."
                ),
                suggestion="Restore removed assertions or replace with equivalent coverage.",
            ))

        return findings

    def _scan_type_mismatches(self, root: Path) -> list[Finding]:
        """Look for TypeScript interfaces/Python models where the TS and Python shapes diverge."""
        findings: list[Finding] = []

        # Find fields defined in Python schemas but not matched in TS types
        # (heuristic: look for fields in schemas.py that don't appear in types/*.ts)
        schemas_path = root / "web" / "api" / "schemas.py"
        types_dir    = root / "web" / "react" / "src" / "types"

        if not schemas_path.exists() or not types_dir.exists():
            return findings

        schema_fields: set[str] = set()
        for line in self._lines(schemas_path):
            m = re.search(r'^\s+(\w+)\s*:', line)
            if m and not line.strip().startswith('#'):
                schema_fields.add(m.group(1).lower())

        ts_fields: set[str] = set()
        for ts_file in types_dir.rglob("*.ts"):
            for line in self._lines(ts_file):
                m = re.search(r'^\s+(\w+)\??:\s', line)
                if m:
                    ts_fields.add(m.group(1).lower())

        # Fields in Python schema not represented in any TS type
        missing_in_ts = schema_fields - ts_fields - {'id', 'type', 'status', 'error', 'message', 'data'}
        if len(missing_in_ts) > 3:
            findings.append(Finding(
                bug_type="regression",
                severity=Severity.MEDIUM,
                layer=Layer.CROSS,
                file="web/api/schemas.py ↔ web/react/src/types/",
                line=1,
                snippet=", ".join(sorted(missing_in_ts)[:10]),
                title=f"{len(missing_in_ts)} backend schema fields not reflected in frontend types",
                explanation=(
                    "Python Pydantic fields that have no corresponding TypeScript type field. "
                    "If the frontend consumes these fields, they silently become `any` — "
                    "a regression waiting to surface."
                ),
                suggestion="Sync TypeScript types with the backend schema; consider auto-generation.",
            ))

        return findings
