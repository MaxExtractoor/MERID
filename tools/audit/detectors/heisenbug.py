"""Heisenbug detector — bugs that disappear when you observe them.

Signals (observation changes behavior):
  - console.log / print inside conditional or timing-sensitive code path
  - Logging that introduces async delay (logger.debug with heavy serialisation)
  - setTimeout(fn, 0) used as a timing hack — adding a log changes ordering
  - React StrictMode double-invoke side effects that mask real bugs
  - Debugger-only code paths (typeof window !== 'undefined' checks that differ in test vs prod)
  - asyncio.sleep(0) used as a yield point whose removal changes ordering
  - try/except that swallows exceptions silently (bug disappears when observed)
"""
from __future__ import annotations

import re
from pathlib import Path

from tools.audit.detectors import BaseDetector
from tools.audit.models import Finding, Layer, Severity


class HeisenBugDetector(BaseDetector):
    name = "heisenbug"

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

            for i, m in self._grep(lines, r'\bconsole\.(log|warn|error|debug)\b'):
                line = lines[i - 1]
                if re.search(r'if\s*\(|&&|\?\?|ternary|condition', lines[max(0, i-3):i+1][-1]):
                    pass  # skip pure guard logs
                # console.log inside render / return path is observation-sensitive
                ctx = "\n".join(lines[max(0, i-5):i+1])
                if re.search(r'setTimeout|setInterval|\.then\(|async|await|useEffect', ctx):
                    findings.append(Finding(
                        bug_type="heisenbug",
                        severity=Severity.MEDIUM,
                        layer=Layer.FRONTEND,
                        file=rel, line=i,
                        snippet=line,
                        title="console.log inside async/timer path",
                        explanation=(
                            "Adding or removing this log changes micro-task scheduling. "
                            "The bug may only reproduce without the log statement."
                        ),
                        suggestion="Remove the log, use React DevTools or a proper debug trace instead.",
                    ))

            # setTimeout(fn, 0) timing hacks
            for i, m in self._grep(lines, r'setTimeout\s*\(\s*\w+\s*,\s*0\s*\)'):
                findings.append(Finding(
                    bug_type="heisenbug",
                    severity=Severity.HIGH,
                    layer=Layer.FRONTEND,
                    file=rel, line=i,
                    snippet=lines[i - 1],
                    title="setTimeout(fn, 0) timing hack",
                    explanation=(
                        "Delays fn by one event-loop tick to 'fix' ordering. This is "
                        "observation-sensitive — adding any async work before this call "
                        "can break the assumed ordering. Classic heisenbug factory."
                    ),
                    suggestion="Identify why ordering breaks without the delay and fix the root cause.",
                ))

            # Silent error swallowing
            for i, m in self._grep(lines, r'\}\s*catch\s*\([^)]*\)\s*\{?\s*\}'):
                findings.append(Finding(
                    bug_type="heisenbug",
                    severity=Severity.HIGH,
                    layer=Layer.FRONTEND,
                    file=rel, line=i,
                    snippet=lines[i - 1],
                    title="Empty catch block swallows exception silently",
                    explanation="Error disappears under observation (DevTools shows nothing). Bug only manifests via wrong UI state.",
                    suggestion="Log the error or set error state: `catch (e) { setError(e); }`",
                ))

        return findings

    def _scan_backend(self, root: Path) -> list[Finding]:
        findings: list[Finding] = []
        for p in self._py_files(root):
            if self._is_test_file(p):
                continue
            lines = self._lines(p)
            rel   = self._rel(root, p)

            # asyncio.sleep(0) timing yield hacks
            for i, m in self._grep(lines, r'asyncio\.sleep\s*\(\s*0\s*\)'):
                findings.append(Finding(
                    bug_type="heisenbug",
                    severity=Severity.MEDIUM,
                    layer=Layer.BACKEND,
                    file=rel, line=i,
                    snippet=lines[i - 1],
                    title="asyncio.sleep(0) used as ordering yield",
                    explanation=(
                        "Yields control to let other tasks run. Removing it (or adding any "
                        "await before it) may break assumed ordering — heisenbug behaviour."
                    ),
                    suggestion="Use an explicit asyncio.Event or Queue to coordinate instead.",
                ))

            # Bare except / except Exception: pass
            for i, m in self._grep(lines, r'except\s*(Exception\s*[^:]*)?\s*:\s*$'):
                if i < len(lines) and re.search(r'^\s*pass\s*$', lines[i]):
                    findings.append(Finding(
                        bug_type="heisenbug",
                        severity=Severity.HIGH,
                        layer=Layer.BACKEND,
                        file=rel, line=i,
                        snippet=lines[i - 1] + "\n" + lines[i],
                        title="Silent exception swallow (except: pass)",
                        explanation="Exception disappears; bug only visible via missing state or wrong output.",
                        suggestion="At minimum: `logger.warning('Unexpected error', exc_info=True)`",
                    ))

            # print() in hot path (changes timing under observation)
            for i, m in self._grep(lines, r'^\s*print\s*\('):
                ctx = "\n".join(lines[max(0, i-4):i+1])
                if re.search(r'async def|await|asyncio', ctx):
                    findings.append(Finding(
                        bug_type="heisenbug",
                        severity=Severity.LOW,
                        layer=Layer.BACKEND,
                        file=rel, line=i,
                        snippet=lines[i - 1],
                        title="print() in async code path",
                        explanation="Stdout flushing changes async scheduling; removing the print can reveal or hide timing bugs.",
                        suggestion="Replace with logger.debug(); remove from production paths.",
                    ))
                    break

        return findings
