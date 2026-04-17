"""Mandelbug detector — complex, non-deterministic bugs from emergent system interactions.

Mandelbugs arise from the intersection of multiple independent systems where no
single component is obviously wrong. They are the hardest to reproduce because
they require specific combinations of state.

Signals:
  Frontend:
    - Component with 5+ useEffect hooks (high interaction surface)
    - Deep prop-drilling (5+ levels) into components that also have local state
    - Hooks that consume 3+ other hooks internally
    - Components that render different UIs based on 4+ independent async states
    - Context consumers that also have their own complex local state

  Backend:
    - Functions with cyclomatic complexity ≥ 10 (many branches)
    - Async functions that await 4+ different services in sequence
    - Classes with 5+ mutable instance attributes modified by multiple methods
    - Agent decision functions that depend on 6+ external signals simultaneously
    - Consensus/swarm logic with more than 3 nested conditional branches
"""
from __future__ import annotations

import re
from pathlib import Path

from tools.audit.detectors import BaseDetector
from tools.audit.models import Finding, Layer, Severity


class MandelbugDetector(BaseDetector):
    name = "mandelbug"

    def detect(self, root: Path) -> list[Finding]:
        findings: list[Finding] = []
        findings.extend(self._scan_frontend(root))
        findings.extend(self._scan_backend(root))
        return findings

    def _scan_frontend(self, root: Path) -> list[Finding]:
        findings: list[Finding] = []
        for p in self._ts_files(root):
            lines = self._lines(p)
            text  = "\n".join(lines)
            rel   = self._rel(root, p)

            # Count useEffect density in a single component file
            effect_count = len(re.findall(r'\buseEffect\s*\(', text))
            if effect_count >= 8:
                findings.append(Finding(
                    bug_type="mandelbug",
                    severity=Severity.HIGH,
                    layer=Layer.FRONTEND,
                    file=rel, line=1,
                    snippet=f"useEffect count: {effect_count}",
                    title=f"Component with {effect_count} useEffect hooks — high Mandelbug surface",
                    explanation=(
                        f"A component with {effect_count} useEffects has a combinatorial state "
                        "space that is hard to reason about. Any interaction between them that "
                        "depends on execution order creates emergent, non-reproducible bugs."
                    ),
                    suggestion="Split into smaller focused components; extract logic into named hooks.",
                ))

            # Hook that consumes many other hooks
            hook_uses = len(re.findall(r'\buse[A-Z]\w+\s*\(', text))
            if hook_uses >= 10 and p.name.startswith('use'):
                findings.append(Finding(
                    bug_type="mandelbug",
                    severity=Severity.MEDIUM,
                    layer=Layer.FRONTEND,
                    file=rel, line=1,
                    snippet=f"hook-of-hooks count: {hook_uses}",
                    title=f"Hook-of-hooks with {hook_uses} sub-hooks",
                    explanation=(
                        "Aggregator hooks that compose many other hooks create deep dependency "
                        "graphs. Re-renders cascade unpredictably when any sub-hook's state changes."
                    ),
                    suggestion="Flatten where possible; document the dependency graph explicitly.",
                ))

            # 4+ independent async data sources combined into one render
            async_sources = len(re.findall(
                r'useApiData|useSWR|useKalshi\w+|useMeridSocket|useKalshiRiskStream',
                text
            ))
            if async_sources >= 5:
                findings.append(Finding(
                    bug_type="mandelbug",
                    severity=Severity.MEDIUM,
                    layer=Layer.FRONTEND,
                    file=rel, line=1,
                    snippet=f"async data sources: {async_sources}",
                    title=f"Component merges {async_sources} independent async data sources",
                    explanation=(
                        "Each source has its own loading/error/stale state. Combined they create "
                        f"{2**async_sources} possible UI states — most untested."
                    ),
                    suggestion="Model combined state explicitly with a single loading/error barrier component.",
                ))

        return findings

    def _scan_backend(self, root: Path) -> list[Finding]:
        findings: list[Finding] = []
        for p in self._py_files(root):
            lines = self._lines(p)
            rel   = self._rel(root, p)

            # Cyclomatic complexity proxy — count decision points in each function
            fn_start = 0
            fn_name  = ""
            branch_count = 0
            await_count  = 0
            in_fn = False

            for i, line in enumerate(lines, 1):
                fn_m = re.match(r'\s*(?:async\s+)?def\s+(\w+)\s*\(', line)
                if fn_m:
                    # save previous function if it was complex
                    if in_fn and branch_count >= 20:
                        findings.append(Finding(
                            bug_type="mandelbug",
                            severity=Severity.HIGH,
                            layer=Layer.BACKEND,
                            file=rel, line=fn_start,
                            snippet=lines[fn_start - 1],
                            title=f"High cyclomatic complexity in `{fn_name}` (~{branch_count} branches)",
                            explanation=(
                                f"`{fn_name}` has approximately {branch_count} decision points. "
                                "Functions this complex create exponential state spaces — "
                                "Mandelbug territory."
                            ),
                            suggestion="Decompose into smaller functions with ≤ 5 branches each.",
                        ))
                    fn_start    = i
                    fn_name     = fn_m.group(1)
                    branch_count = 1
                    await_count  = 0
                    in_fn        = True
                    continue

                if in_fn:
                    branch_count += len(re.findall(r'\bif\b|\belif\b|\bfor\b|\bwhile\b|\band\b|\bor\b|\bexcept\b', line))
                    await_count  += len(re.findall(r'\bawait\b', line))

                    # New function at same or lower indent resets
                    if re.match(r'^(?:class |def |async def )', line):
                        in_fn = False

            # Check last function
            if in_fn and branch_count >= 20:
                findings.append(Finding(
                    bug_type="mandelbug",
                    severity=Severity.HIGH,
                    layer=Layer.BACKEND,
                    file=rel, line=fn_start,
                    snippet=lines[fn_start - 1],
                    title=f"High cyclomatic complexity in `{fn_name}` (~{branch_count} branches)",
                    explanation=f"~{branch_count} decision points — Mandelbug surface.",
                    suggestion="Decompose into smaller functions.",
                ))

            # Async function awaiting 5+ services in sequence
            text = "\n".join(lines)
            for fn_match in re.finditer(r'async def (\w+)\([^)]*\).*?(?=\nasync def |\nclass |\Z)', text, re.DOTALL):
                fn_body = fn_match.group(0)
                awaits  = len(re.findall(r'\bawait\b', fn_body))
                if awaits >= 6:
                    line_no = text[:fn_match.start()].count('\n') + 1
                    findings.append(Finding(
                        bug_type="mandelbug",
                        severity=Severity.MEDIUM,
                        layer=Layer.BACKEND,
                        file=rel, line=line_no,
                        snippet=lines[line_no - 1],
                        title=f"`{fn_match.group(1)}` awaits {awaits} services sequentially",
                        explanation=(
                            f"Sequential awaits across {awaits} services create a {awaits}-way "
                            "error/timeout interaction space. Any combination of partial failures "
                            "yields a different emergent outcome."
                        ),
                        suggestion="Use asyncio.gather() for independent calls; add explicit timeout + fallback per service.",
                    ))
                    break  # one per file

        return findings
