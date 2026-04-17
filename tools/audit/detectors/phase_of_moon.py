"""Phase of the Moon Bug detector — only reproduces under specific environmental conditions.

These bugs require exact alignment of external factors: time of day, market open/close,
specific environment variable values, OS locale, or data volume thresholds.

Signals:
  Frontend:
    - Date.now() / new Date() used in conditional logic (time-sensitive UI paths)
    - toLocaleDateString / toLocaleTimeString without explicit locale (locale-sensitive)
    - Timezone assumptions (hardcoded UTC offsets, no timezone parameter)
    - Window size / viewport checks that affect data display logic
    - Feature-flag env checks (import.meta.env.VITE_*) in conditional branches

  Backend:
    - datetime.now() without timezone (naive datetime — DST bugs)
    - time.time() used in business logic conditionals
    - os.environ checks inside request handlers (env-state-dependent bugs)
    - Hard-coded market hours or day-of-week logic
    - Behaviour that differs between Python versions (sys.version checks)
"""
from __future__ import annotations

import re
from pathlib import Path

from tools.audit.detectors import BaseDetector
from tools.audit.models import Finding, Layer, Severity


class PhaseOfMoonDetector(BaseDetector):
    name = "phase_of_moon"

    def detect(self, root: Path) -> list[Finding]:
        findings: list[Finding] = []
        findings.extend(self._scan_frontend(root))
        findings.extend(self._scan_backend(root))
        return findings

    def _scan_frontend(self, root: Path) -> list[Finding]:
        findings: list[Finding] = []
        for p in self._ts_files(root):
            if self._is_test_file(p):
                continue
            lines = self._lines(p)
            rel   = self._rel(root, p)

            for i, line in enumerate(lines, 1):

                # Date.now() / new Date() in conditional
                if re.search(r'Date\.now\(\)|new Date\(\)', line):
                    ctx = "\n".join(lines[max(0, i-2):i+2])
                    if re.search(r'if\s*\(|&&|\?\s|>\s*|<\s*|>=|<=', ctx):
                        findings.append(Finding(
                            bug_type="phase_of_moon",
                            severity=Severity.HIGH,
                            layer=Layer.FRONTEND,
                            file=rel, line=i,
                            snippet=line,
                            title="Date.now() used in conditional logic",
                            explanation=(
                                "Behaviour changes depending on wall-clock time. "
                                "This path may only be reachable during specific time windows "
                                "(market hours, session expiry, daily reset) — classic phase-of-moon."
                            ),
                            suggestion="Pass time as a prop/parameter; use a time-provider hook for testability.",
                        ))

                # toLocaleString / toLocaleDateString without locale argument
                if re.search(r'\.toLocaleString\(\)|\.toLocaleDateString\(\)|\.toLocaleTimeString\(\)', line):
                    findings.append(Finding(
                        bug_type="phase_of_moon",
                        severity=Severity.MEDIUM,
                        layer=Layer.FRONTEND,
                        file=rel, line=i,
                        snippet=line,
                        title="Locale-sensitive date format without explicit locale",
                        explanation=(
                            "Output depends on the user's OS locale. A user in a non-US locale "
                            "may see different date ordering — bugs only surface on specific machines."
                        ),
                        suggestion="Pass explicit locale: `.toLocaleDateString('en-US', { ... })`",
                    ))

                # Hardcoded timezone offsets
                if re.search(r'[+-]\d{2}:00|UTC[+-]\d|GMT[+-]\d', line):
                    findings.append(Finding(
                        bug_type="phase_of_moon",
                        severity=Severity.MEDIUM,
                        layer=Layer.FRONTEND,
                        file=rel, line=i,
                        snippet=line,
                        title="Hardcoded timezone offset",
                        explanation="Breaks during DST transitions; wrong for users in other zones.",
                        suggestion="Use Intl.DateTimeFormat with `timeZone: 'UTC'` or a timezone library.",
                    ))

                # import.meta.env checks in conditional branches (env-dependent paths)
                if re.search(r'import\.meta\.env\.VITE_\w+', line):
                    ctx = "\n".join(lines[max(0, i-2):i+2])
                    if re.search(r'if\s*\(|&&|\?\s*:', ctx):
                        findings.append(Finding(
                            bug_type="phase_of_moon",
                            severity=Severity.MEDIUM,
                            layer=Layer.FRONTEND,
                            file=rel, line=i,
                            snippet=line,
                            title="Feature flag / env var gates UI code path",
                            explanation=(
                                "This code path only executes when the env var has a specific value. "
                                "Bugs in this branch only appear in specific deployment environments."
                            ),
                            suggestion="Ensure this path has test coverage for both flag states.",
                        ))

                # window.innerWidth / screen size in logic
                if re.search(r'window\.innerWidth|window\.innerHeight|screen\.width', line):
                    ctx = "\n".join(lines[max(0, i-1):i+2])
                    if re.search(r'if|&&|<|>', ctx):
                        findings.append(Finding(
                            bug_type="phase_of_moon",
                            severity=Severity.LOW,
                            layer=Layer.FRONTEND,
                            file=rel, line=i,
                            snippet=line,
                            title="Viewport-size conditional logic",
                            explanation="Bug only appears at specific window dimensions — depends on user's screen size.",
                            suggestion="Use CSS media queries or a ResizeObserver hook instead of raw pixel conditionals.",
                        ))

        return findings

    def _scan_backend(self, root: Path) -> list[Finding]:
        findings: list[Finding] = []
        for p in self._py_files(root):
            if self._is_test_file(p):
                continue
            lines = self._lines(p)
            rel   = self._rel(root, p)

            for i, line in enumerate(lines, 1):

                # datetime.now() without timezone (naive — DST bug)
                if re.search(r'datetime\.now\(\s*\)', line) and \
                   not re.search(r'datetime\.now\(tz|datetime\.now\(timezone|utcnow', line):
                    findings.append(Finding(
                        bug_type="phase_of_moon",
                        severity=Severity.HIGH,
                        layer=Layer.BACKEND,
                        file=rel, line=i,
                        snippet=line,
                        title="datetime.now() without timezone (naive datetime)",
                        explanation=(
                            "Naive datetimes are ambiguous during DST transitions. "
                            "Comparisons with timezone-aware datetimes raise TypeError at runtime "
                            "— only during DST changeover hours."
                        ),
                        suggestion="Use `datetime.now(timezone.utc)` or `datetime.utcnow().replace(tzinfo=timezone.utc)`",
                    ))

                # Hard-coded market hours / day-of-week logic
                if re.search(r'weekday\(\)\s*[<>]=?\s*[45]|hour\s*[<>]=?\s*\d+|9:30|16:00|market.?open|market.?close', line, re.IGNORECASE):
                    findings.append(Finding(
                        bug_type="phase_of_moon",
                        severity=Severity.MEDIUM,
                        layer=Layer.BACKEND,
                        file=rel, line=i,
                        snippet=line,
                        title="Hardcoded market hours / day-of-week logic",
                        explanation="Only executes during specific times — bugs are invisible outside those windows.",
                        suggestion="Extract market hours to config; test with mocked time.",
                    ))

                # os.getenv inside a request handler (env-dependent at request time)
                if re.search(r'os\.getenv\(|os\.environ\[', line):
                    ctx = "\n".join(lines[max(0, i-10):i])
                    if re.search(r'@router\.|@app\.|async def \w+\(.*Request', ctx):
                        findings.append(Finding(
                            bug_type="phase_of_moon",
                            severity=Severity.MEDIUM,
                            layer=Layer.BACKEND,
                            file=rel, line=i,
                            snippet=line,
                            title="os.getenv() inside request handler",
                            explanation=(
                                "Env vars read at request time can change between deployments "
                                "without a restart — behaviour differs depending on when the request arrives."
                            ),
                            suggestion="Read env vars once at module/startup level and inject via dependency.",
                        ))
                        break

        return findings
