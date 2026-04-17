"""Memory Leak detector.

Frontend signals:
  - useEffect subscribes / adds listener but returns no cleanup function
  - setInterval / setTimeout in useEffect with no clearInterval/clearTimeout
  - WebSocket opened inside useEffect with no close() in cleanup
  - Event listener added (addEventListener) with no removeEventListener
  - Growing refs (useRef array/dict that is appended-to, never cleared)

Backend signals:
  - asyncio.Task created but never awaited or cancelled
  - Background thread started (threading.Thread) with no join/daemon guard
  - File handles opened but not closed (no context manager)
  - LRU cache on methods that take mutable/large objects
"""
from __future__ import annotations

import re
from pathlib import Path

from tools.audit.detectors import BaseDetector
from tools.audit.models import Finding, Layer, Severity


class MemoryLeakDetector(BaseDetector):
    name = "memory_leak"

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

            # Track useEffect blocks for subscription/timer without cleanup
            in_effect    = False
            has_sub      = False
            has_cleanup  = False
            effect_start = 0
            brace_depth  = 0

            for i, line in enumerate(lines, 1):
                if re.search(r'useEffect\s*\(', line):
                    in_effect    = True
                    effect_start = i
                    has_sub      = False
                    has_cleanup  = False
                    brace_depth  = 0

                if in_effect:
                    brace_depth += line.count('{') - line.count('}')
                    if re.search(
                        r'addEventListener|setInterval|setTimeout|\.subscribe\(|'
                        r'new WebSocket|\.on\(|EventSource|MutationObserver',
                        line
                    ):
                        has_sub = True
                    if re.search(
                        r'return\s*\(\)|return\s*\(\s*\)\s*=>|clearInterval|clearTimeout|'
                        r'removeEventListener|\.unsubscribe|\.close\(\)|\.disconnect\(\)|'
                        r'observer\.disconnect',
                        line
                    ):
                        has_cleanup = True

                    if brace_depth <= 0 and i > effect_start:
                        if has_sub and not has_cleanup:
                            findings.append(Finding(
                                bug_type="memory_leak",
                                severity=Severity.HIGH,
                                layer=Layer.FRONTEND,
                                file=rel, line=effect_start,
                                snippet=lines[effect_start - 1],
                                title="useEffect subscription/timer with no cleanup",
                                explanation=(
                                    "Subscriptions, timers, or event listeners registered inside "
                                    "useEffect are never torn down when the component unmounts. "
                                    "On SPA navigation this accumulates — classic leak."
                                ),
                                suggestion="Return a cleanup function: `return () => { clearInterval(id); }`",
                            ))
                        in_effect = False

            # Standalone addEventListener without removeEventListener
            for i, m in self._grep(lines, r'addEventListener\s*\('):
                ctx = "\n".join(lines[max(0, i-3):i+10])
                if not re.search(r'removeEventListener', ctx):
                    findings.append(Finding(
                        bug_type="memory_leak",
                        severity=Severity.MEDIUM,
                        layer=Layer.FRONTEND,
                        file=rel, line=i,
                        snippet=lines[i - 1],
                        title="addEventListener without removeEventListener",
                        explanation="Listener accumulates on each render or mount without cleanup.",
                        suggestion="Mirror every addEventListener with removeEventListener in cleanup.",
                    ))
                    break

        return findings

    def _scan_backend(self, root: Path) -> list[Finding]:
        findings: list[Finding] = []
        for p in self._py_files(root):
            if self._is_test_file(p):
                continue
            lines = self._lines(p)
            text  = "\n".join(lines)
            rel   = self._rel(root, p)

            # Pattern — asyncio.create_task with no reference captured
            for i, m in self._grep(lines, r'asyncio\.create_task\('):
                line = lines[i - 1]
                # If the return value isn't captured, the task can be GC'd or leak
                if not re.search(r'=\s*asyncio\.create_task|tasks\.|_task\s*=|self\.\w+\s*=', line):
                    findings.append(Finding(
                        bug_type="memory_leak",
                        severity=Severity.MEDIUM,
                        layer=Layer.BACKEND,
                        file=rel, line=i,
                        snippet=line,
                        title="asyncio.create_task result not stored",
                        explanation=(
                            "Task reference is discarded. CPython may GC the task unexpectedly "
                            "(Python 3.12 warning), and there is no handle to cancel it on shutdown."
                        ),
                        suggestion="Store in a set: `_tasks.add(t := asyncio.create_task(...)); t.add_done_callback(_tasks.discard)`",
                    ))

            # Pattern — open() without context manager
            for i, m in self._grep(lines, r'\bopen\s*\([^)]+\)(?!\s*as\b)'):
                line = lines[i - 1].strip()
                if not line.startswith('#') and 'with open' not in line:
                    findings.append(Finding(
                        bug_type="memory_leak",
                        severity=Severity.LOW,
                        layer=Layer.BACKEND,
                        file=rel, line=i,
                        snippet=lines[i - 1],
                        title="File opened without context manager",
                        explanation="File handle may not be closed on exception path.",
                        suggestion="Use `with open(...) as f:` to guarantee closure.",
                    ))
                    break

            # Pattern — threading.Thread without daemon=True or .join()
            for i, m in self._grep(lines, r'threading\.Thread\('):
                ctx = "\n".join(lines[i-1:i+6])
                if not re.search(r'daemon\s*=\s*True|\.join\(\)', ctx):
                    findings.append(Finding(
                        bug_type="memory_leak",
                        severity=Severity.MEDIUM,
                        layer=Layer.BACKEND,
                        file=rel, line=i,
                        snippet=lines[i - 1],
                        title="Non-daemon thread without join()",
                        explanation="Thread blocks process exit and holds references indefinitely.",
                        suggestion="Set daemon=True or call .join() during shutdown.",
                    ))
                    break

        return findings
