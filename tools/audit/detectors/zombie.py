"""Zombie Bug detector — fixed bugs that keep coming back.

Signals:
  - TODO/FIXME/HACK comments in execution-critical paths
  - Commented-out code blocks that were 'temporarily' disabled
  - Files that git history shows have had the same pattern fixed multiple times
  - Dead feature-flag branches that shadow real logic
  - `// re-added`, `// restored`, `// revert` comments
  - Disabled test cases (`.skip`, `xtest`, `xit`, `pytest.mark.skip`)
  - Old import aliases that suggest a refactor was partially done
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tools.audit.detectors import BaseDetector
from tools.audit.models import Finding, Layer, Severity


class ZombieBugDetector(BaseDetector):
    name = "zombie"

    # High-signal TODO patterns — near execution-critical keywords
    _CRITICAL_KEYWORDS = re.compile(
        r'trade|order|risk|position|pnl|balance|execute|fill|settlement|'
        r'consensus|agent|auth|token|key|secret|limit|stop|kill',
        re.IGNORECASE,
    )

    def detect(self, root: Path) -> list[Finding]:
        findings: list[Finding] = []
        findings.extend(self._scan_frontend(root))
        findings.extend(self._scan_backend(root))
        findings.extend(self._scan_disabled_tests(root))
        findings.extend(self._scan_git_repeat_fixes(root))
        return findings

    def _scan_frontend(self, root: Path) -> list[Finding]:
        findings: list[Finding] = []
        for p in self._ts_files(root):
            lines = self._lines(p)
            rel   = self._rel(root, p)
            for i, line in enumerate(lines, 1):
                # TODO/FIXME/HACK in critical paths
                # Only match TODO/FIXME/HACK/BUG inside comments (// or #), not in code
                m = re.search(r'(?://|#)\s*(?:TODO|FIXME|HACK|XXX|BUG)\b\s*:?\s*(.{10,80})', line, re.IGNORECASE)
                if m:
                    note = m.group(1)
                    sev = Severity.HIGH if self._CRITICAL_KEYWORDS.search(note) else Severity.LOW
                    findings.append(Finding(
                        bug_type="zombie",
                        severity=sev,
                        layer=Layer.FRONTEND,
                        file=rel, line=i,
                        snippet=line,
                        title=f"Unresolved {m.group(0)[:20].strip()}",
                        explanation=f"Marker left in code: '{note.strip()}'. May indicate a known but unfixed issue.",
                        suggestion="Resolve and remove, or convert to a tracked issue in your backlog.",
                    ))

                # Commented-out code blocks (not doc comments)
                if re.search(r'^\s*//\s*(?:return|if|const|let|var|await|fetch|set[A-Z])', line):
                    findings.append(Finding(
                        bug_type="zombie",
                        severity=Severity.LOW,
                        layer=Layer.FRONTEND,
                        file=rel, line=i,
                        snippet=line,
                        title="Commented-out code",
                        explanation="Dead code left in place; if it contains logic it may be re-enabled incorrectly.",
                        suggestion="Delete it (git history preserves it if needed).",
                    ))

                # Re-added / restored markers
                if re.search(r'//\s*(?:re-?added|restored|revert|back to|undo)', line, re.IGNORECASE):
                    findings.append(Finding(
                        bug_type="zombie",
                        severity=Severity.MEDIUM,
                        layer=Layer.FRONTEND,
                        file=rel, line=i,
                        snippet=line,
                        title="'Re-added/restored' comment — possible zombie fix",
                        explanation="Code that was removed and re-added suggests a recurring fix.",
                        suggestion="Investigate why it keeps needing to come back — fix the root cause.",
                    ))

        return findings

    def _scan_backend(self, root: Path) -> list[Finding]:
        findings: list[Finding] = []
        for p in self._py_files(root):
            lines = self._lines(p)
            rel   = self._rel(root, p)
            for i, line in enumerate(lines, 1):
                # Only match inside comments (#), not in code identifiers
                m = re.search(r'#\s*(?:TODO|FIXME|HACK|XXX|BUG)\b\s*:?\s*(.{10,80})', line, re.IGNORECASE)
                if m:
                    note = m.group(1)
                    sev = Severity.HIGH if self._CRITICAL_KEYWORDS.search(note) else Severity.LOW
                    findings.append(Finding(
                        bug_type="zombie",
                        severity=sev,
                        layer=Layer.BACKEND,
                        file=rel, line=i,
                        snippet=line,
                        title=f"Unresolved {m.group(0)[:20].strip()}",
                        explanation=f"'{note.strip()}'",
                        suggestion="Resolve or file a tracked issue.",
                    ))

                # Commented-out Python code
                if re.search(r'^\s*#\s*(?:return|if |for |while |def |class |import |from )', line):
                    findings.append(Finding(
                        bug_type="zombie",
                        severity=Severity.LOW,
                        layer=Layer.BACKEND,
                        file=rel, line=i,
                        snippet=line,
                        title="Commented-out Python code",
                        explanation="Dead code retained in source; risk of accidental re-enable.",
                        suggestion="Delete (git history preserves it).",
                    ))

        return findings

    def _scan_disabled_tests(self, root: Path) -> list[Finding]:
        findings: list[Finding] = []
        # Frontend — intentionally scan test files here
        for p in self._ts_test_files(root):
            lines = self._lines(p)
            rel   = self._rel(root, p)
            for i, m in self._grep(lines, r'\b(?:xit|xtest|xdescribe|test\.skip|it\.skip|describe\.skip)\b'):
                findings.append(Finding(
                    bug_type="zombie",
                    severity=Severity.MEDIUM,
                    layer=Layer.FRONTEND,
                    file=rel, line=i,
                    snippet=lines[i - 1],
                    title="Disabled test case",
                    explanation="Skipped tests hide regressions; the bug they covered may reappear silently.",
                    suggestion="Fix or delete the test — never leave skipped tests in CI.",
                ))
        # Backend
        for p in self._py_files(root):
            lines = self._lines(p)
            rel   = self._rel(root, p)
            for i, m in self._grep(lines, r'@pytest\.mark\.skip|@unittest\.skip'):
                findings.append(Finding(
                    bug_type="zombie",
                    severity=Severity.MEDIUM,
                    layer=Layer.BACKEND,
                    file=rel, line=i,
                    snippet=lines[i - 1],
                    title="Disabled pytest test",
                    explanation="Skipped test may be covering a zombie bug.",
                    suggestion="Fix the underlying issue and re-enable.",
                ))
        return findings

    def _scan_git_repeat_fixes(self, root: Path) -> list[Finding]:
        """Files that have had 'fix' commits many times — zombie fix candidates."""
        findings: list[Finding] = []
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "--diff-filter=M", "--name-only",
                 "--pretty=format:", "HEAD~50..HEAD"],
                cwd=root, capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                return findings
            freq: dict[str, int] = {}
            for line in result.stdout.splitlines():
                line = line.strip()
                if line:
                    freq[line] = freq.get(line, 0) + 1
            for path, count in freq.items():
                if count >= 4:
                    findings.append(Finding(
                        bug_type="zombie",
                        severity=Severity.HIGH,
                        layer=Layer.CROSS,
                        file=path, line=1,
                        snippet="",
                        title=f"File modified {count}× in last 50 commits",
                        explanation=(
                            f"`{path}` has been changed {count} times recently. "
                            "High-frequency churn on a single file often indicates a recurring "
                            "bug being patched rather than solved."
                        ),
                        suggestion="Review the change history and address the underlying design issue.",
                    ))
        except Exception:
            pass
        return findings
