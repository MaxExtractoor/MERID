"""Race Condition / Thread Issue detector.

Frontend signals:
  - useEffect with async fetch but missing AbortController cleanup
  - setState called after component might be unmounted (no isMounted guard)
  - Parallel WebSocket + polling hook for the same endpoint/data
  - Missing dependency in useEffect [] that references mutable closure var

Backend signals:
  - asyncio.gather() branches that write the same shared dict/list
  - Missing asyncio.Lock() on shared mutable state mutated in async fns
  - FastAPI background tasks that access request-scoped singletons
"""
from __future__ import annotations

import re
from pathlib import Path

from tools.audit.detectors import BaseDetector
from tools.audit.models import Finding, Layer, Severity


class RaceConditionDetector(BaseDetector):
    name = "race_condition"

    def detect(self, root: Path) -> list[Finding]:
        findings: list[Finding] = []
        findings.extend(self._scan_frontend(root))
        findings.extend(self._scan_backend(root))
        return findings

    # ── frontend ───────────────────────────────────────────────────────

    def _scan_frontend(self, root: Path) -> list[Finding]:
        findings: list[Finding] = []
        for p in self._ts_files(root):
            if self._is_test_file(p):
                continue
            lines = self._lines(p)
            text  = "\n".join(lines)
            rel   = self._rel(root, p)

            # Pattern 1 — async useEffect without AbortController
            in_effect = False
            has_fetch  = False
            has_abort  = False
            effect_start = 0
            brace_depth  = 0
            for i, line in enumerate(lines, 1):
                if re.search(r'useEffect\s*\(', line):
                    in_effect   = True
                    effect_start = i
                    has_fetch    = False
                    has_abort    = False
                    brace_depth  = 0
                if in_effect:
                    brace_depth += line.count('{') - line.count('}')
                    if re.search(r'\bfetch\b|axios\.|httpClient\.|useApiData', line):
                        has_fetch = True
                    if re.search(r'AbortController|abort\(\)|signal\.aborted', line):
                        has_abort = True
                    if brace_depth <= 0 and i > effect_start:
                        if has_fetch and not has_abort:
                            findings.append(Finding(
                                bug_type="race_condition",
                                severity=Severity.HIGH,
                                layer=Layer.FRONTEND,
                                file=rel, line=effect_start,
                                snippet=lines[effect_start - 1],
                                title="Async fetch in useEffect without AbortController",
                                explanation=(
                                    "If the component unmounts or deps change before the fetch "
                                    "resolves, the callback still fires and calls setState on an "
                                    "unmounted component — classic race condition."
                                ),
                                suggestion="Add AbortController; return () => controller.abort() in cleanup.",
                            ))
                        in_effect = False

            # Pattern 2 — dual data sources for same concept (WS + poll)
            has_ws   = bool(re.search(r'useKalshiRiskStream|useMeridSocket|useWebSocket|useResilientWebSocket|useTickStream|useOrderGroupStream', text))
            has_poll = bool(re.search(r'useApiData.*pollingInterval|setInterval.*fetch', text))
            if has_ws and has_poll:
                # Find first line that has polling
                for i, line in enumerate(lines, 1):
                    if re.search(r'pollingInterval|setInterval.*fetch', line):
                        findings.append(Finding(
                            bug_type="race_condition",
                            severity=Severity.MEDIUM,
                            layer=Layer.FRONTEND,
                            file=rel, line=i,
                            snippet=line,
                            title="Dual data sources: WebSocket + polling for same component",
                            explanation=(
                                "Component uses both a WS stream and HTTP polling. "
                                "Both can update state concurrently — last writer wins, "
                                "causing flicker or stale overwrite."
                            ),
                            suggestion="Gate polling behind `!wsConnected`; one source of truth per data domain.",
                        ))
                        break

            # Pattern 3 — setState inside async callback with no mounted guard
            for i, m in self._grep(lines, r'set[A-Z]\w+\s*\(', re.MULTILINE):
                ctx = "\n".join(lines[max(0, i-8):i+2])
                if re.search(r'\basync\b|\bawait\b|\.then\(', ctx) and \
                   not re.search(r'isMounted|mountedRef|AbortController|signal\.aborted|return\s*;', ctx):
                    findings.append(Finding(
                        bug_type="race_condition",
                        severity=Severity.MEDIUM,
                        layer=Layer.FRONTEND,
                        file=rel, line=i,
                        snippet=lines[i - 1],
                        title="setState inside async callback without mounted guard",
                        explanation="setState after an await may run after component unmounts.",
                        suggestion="Track mounted state with a ref: `if (!mountedRef.current) return;`",
                    ))
                    break  # one per file to avoid spam

        return findings

    # ── backend ────────────────────────────────────────────────────────

    def _scan_backend(self, root: Path) -> list[Finding]:
        findings: list[Finding] = []
        for p in self._py_files(root):
            if self._is_test_file(p):
                continue
            lines = self._lines(p)
            text  = "\n".join(lines)
            rel   = self._rel(root, p)

            # Pattern — asyncio.gather with shared mutable default dict/list
            if 'asyncio.gather' in text or 'gather(' in text:
                for i, m in self._grep(lines, r'asyncio\.gather|await gather\('):
                    ctx = "\n".join(lines[max(0, i-5):i+15])
                    if re.search(r'\[\]\s*=|\{\}\s*=|\.append\(|\.update\(|dict\[', ctx):
                        findings.append(Finding(
                            bug_type="race_condition",
                            severity=Severity.HIGH,
                            layer=Layer.BACKEND,
                            file=rel, line=i,
                            snippet=lines[i - 1],
                            title="asyncio.gather with shared mutable container",
                            explanation=(
                                "Coroutines launched via gather() all write to the same list/dict "
                                "with no Lock. In CPython the GIL doesn't protect asyncio tasks."
                            ),
                            suggestion="Accumulate results from gather() return values, not a shared container.",
                        ))
                        break

            # Pattern — async def that writes module-level dict without Lock
            if re.search(r'^async def ', text, re.MULTILINE):
                for i, m in self._grep(lines, r'^\s{0,4}async def \w+', re.MULTILINE):
                    fn_body = "\n".join(lines[i:i+30])
                    if re.search(r'\w+\[.+\]\s*=|\.append\(|\.update\(', fn_body) and \
                       not re.search(r'asyncio\.Lock|async with.*lock|self\._lock', fn_body):
                        findings.append(Finding(
                            bug_type="race_condition",
                            severity=Severity.MEDIUM,
                            layer=Layer.BACKEND,
                            file=rel, line=i,
                            snippet=lines[i - 1],
                            title="Async function mutates shared state without Lock",
                            explanation="Multiple concurrent callers can interleave writes.",
                            suggestion="Protect shared mutations with asyncio.Lock().",
                        ))
                        break

        return findings
