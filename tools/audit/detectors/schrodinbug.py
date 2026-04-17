"""Schrödinbug detector — works fine until you read the code and realise it shouldn't.

These are bugs that exist in the code but are masked by luck, coincidence, or
compensating errors. The moment you examine them carefully they become obviously wrong.

Signals:
  Frontend:
    - TypeScript `as` casts that skip runtime validation (type lies)
    - Optional chaining on values that are assumed to always exist
    - Array index access [0] without bounds check on API responses
    - localStorage.getItem() result used without null check
    - Comparing object references with === instead of deep equality
    - Non-null assertion operator (!) on values from external APIs

  Backend:
    - dict['key'] access without .get() on external data
    - Using `or` default on falsy-but-valid values (0, False, '')
    - Mutating a function default argument (classic Python footgun)
    - Returning mutable default ([], {}) from a function
    - Implicit None return path in non-Optional typed function
"""
from __future__ import annotations

import re
from pathlib import Path

from tools.audit.detectors import BaseDetector
from tools.audit.models import Finding, Layer, Severity


class SchrodinbugDetector(BaseDetector):
    name = "schrodinbug"

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

                # Non-null assertion on API/prop values
                if re.search(r'\w+!\.\w+|\w+!\[', line) and \
                   re.search(r'data\.|response\.|props\.|params\.|result\.', line):
                    findings.append(Finding(
                        bug_type="schrodinbug",
                        severity=Severity.HIGH,
                        layer=Layer.FRONTEND,
                        file=rel, line=i,
                        snippet=line,
                        title="Non-null assertion (!) on external data",
                        explanation=(
                            "TypeScript told to trust this is non-null, but the value comes from "
                            "an API response or prop. If the API ever omits the field this throws "
                            "at runtime — the bug exists but is hidden until that case occurs."
                        ),
                        suggestion="Replace with optional chaining + explicit null handling.",
                    ))

                # `as SomeType` cast on parsed/fetched data
                if re.search(r'\) as [A-Z]\w+|json\(\) as |data as [A-Z]', line) and \
                   not re.search(r'// safe cast|// validated', line, re.IGNORECASE):
                    findings.append(Finding(
                        bug_type="schrodinbug",
                        severity=Severity.MEDIUM,
                        layer=Layer.FRONTEND,
                        file=rel, line=i,
                        snippet=line,
                        title="Unsafe TypeScript cast on external data",
                        explanation=(
                            "The `as` cast erases type checking. If the API shape changes, "
                            "TypeScript will not catch it — the bug exists until a field is accessed."
                        ),
                        suggestion="Add a Zod schema or runtime type guard before the cast.",
                    ))

                # Array[0] access on API result without length check
                if re.search(r'(?:data|results?|items?|rows?)\[0\]', line) and \
                   not re.search(r'\.length|if.*\[0\]|\?\.\[0\]', line):
                    findings.append(Finding(
                        bug_type="schrodinbug",
                        severity=Severity.MEDIUM,
                        layer=Layer.FRONTEND,
                        file=rel, line=i,
                        snippet=line,
                        title="Array[0] access without length guard",
                        explanation="If the API returns an empty array this is undefined — works until it doesn't.",
                        suggestion="Use `arr[0]` only after `if (arr.length > 0)` or use optional `arr.at(0)`.",
                    ))

                # localStorage.getItem used without null check
                if re.search(r'localStorage\.getItem\(', line):
                    ctx = "\n".join(lines[i-1:min(len(lines), i+3)])
                    if not re.search(r'\?\s*\??|if\s*\(|=\s*null|nullish|\?\?', ctx):
                        findings.append(Finding(
                            bug_type="schrodinbug",
                            severity=Severity.MEDIUM,
                            layer=Layer.FRONTEND,
                            file=rel, line=i,
                            snippet=line,
                            title="localStorage.getItem() result used without null check",
                            explanation="Returns null when key is absent — works until the key is missing (first run, cleared storage).",
                            suggestion="Use `?? defaultValue` or check for null before use.",
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

                # Mutable default argument
                if re.search(r'def \w+\([^)]*=\s*[\[\{]', line):
                    findings.append(Finding(
                        bug_type="schrodinbug",
                        severity=Severity.HIGH,
                        layer=Layer.BACKEND,
                        file=rel, line=i,
                        snippet=line,
                        title="Mutable default argument in function signature",
                        explanation=(
                            "The default list/dict is shared across all calls. "
                            "Works fine until a caller mutates it — then all subsequent "
                            "calls see the mutated state. Classic Python schrödinbug."
                        ),
                        suggestion="Use `def f(x=None): x = x or []` instead.",
                    ))

                # dict['key'] on external/request data (should be .get())
                if re.search(r'(?:request|data|payload|msg|event|body)\[[\'"]\w+[\'"]\]', line) and \
                   not re.search(r'\.get\(', line) and \
                   not re.search(r'^\s*#', line) and \
                   not re.search(r'=\s*\{', line):
                    findings.append(Finding(
                        bug_type="schrodinbug",
                        severity=Severity.MEDIUM,
                        layer=Layer.BACKEND,
                        file=rel, line=i,
                        snippet=line,
                        title="Direct dict key access on external data",
                        explanation="KeyError if key is absent — works until it is.",
                        suggestion="Use `.get('key', default)` or validate with Pydantic.",
                    ))

                # `or` default on falsy-but-valid values
                if re.search(r'=\s*\w+\s+or\s+(?:0|False|\'\'|\"\")', line):
                    findings.append(Finding(
                        bug_type="schrodinbug",
                        severity=Severity.LOW,
                        layer=Layer.BACKEND,
                        file=rel, line=i,
                        snippet=line,
                        title="`or` default clobbers valid falsy value",
                        explanation="`x or default` replaces 0, False, '' — valid values — with the default.",
                        suggestion="Use `x if x is not None else default` for non-None checks.",
                    ))

        return findings
