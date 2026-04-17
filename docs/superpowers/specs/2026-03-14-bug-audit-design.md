# MERID Bug Audit System — Design Spec
**Date:** 2026-03-14
**Status:** Implemented
**Owner:** Engineering

---

## Overview

A modular, full-stack static analysis tool that scans the MERID codebase for eight
exotic bug categories. Produces a JSON report (machine-readable, CI-consumable) and
a Markdown report (human review). Runs in ~20 seconds on the full codebase.

---

## Architecture

```
tools/
└── audit/
    ├── __init__.py          # package marker (empty)
    ├── run.py               # CLI entry point
    ├── models.py            # Finding, Severity, Layer dataclasses
    ├── report.py            # JSON + Markdown emitter
    └── detectors/
        ├── __init__.py      # BaseDetector ABC + file iteration helpers
        ├── mandelbug.py
        ├── heisenbug.py
        ├── schrodinbug.py
        ├── zombie.py
        ├── race_condition.py
        ├── memory_leak.py
        ├── regression.py
        └── phase_of_moon.py
```

### Key design decisions

- **Each detector is independent.** No shared state between detectors. Fully parallelizable.
- **BaseDetector provides helpers:** `_ts_files()`, `_py_files()`, `_lines()`, `_grep()`, `_rel()`.
- **Layer-aware:** Every finding is tagged `FRONTEND`, `BACKEND`, or `CROSS`.
- **Severity rubric:** `CRITICAL` → fix before next deploy; `HIGH` → fix this sprint; `MEDIUM` → backlog; `LOW` → good hygiene.
- **CI integration:** Exit code 1 if any CRITICAL findings exist.

### Scanned directories

| Helper | Scope |
|--------|-------|
| `_ts_files(root)` | `web/react/src/**/*.{ts,tsx}` |
| `_py_files(root)` | `web/**/*.py`, `agents/**/*.py`, `merid/**/*.py`, `core/**/*.py`, `consensus/**/*.py`, `swarm/**/*.py` — excludes `__pycache__` and `archive/` |
| `_lines(p)` | UTF-8, `errors="ignore"` — non-UTF-8 bytes silently dropped |

Directories intentionally excluded from `_py_files`: `execution/`, `trading/`, `data/`,
`streams/`, `backtesting/`, `scripts/`. Add patterns to `BaseDetector._py_files` to expand coverage.

---

## Usage

```bash
# Full scan (both layers, all 8 detectors)
py tools/audit/run.py

# Single detector
py tools/audit/run.py --only race_condition

# Frontend only
py tools/audit/run.py --layer frontend

# Custom output directory
py tools/audit/run.py --out reports/
```

Output files: `docs/bug_audit_YYYY-MM-DD.json` and `docs/bug_audit_YYYY-MM-DD.md`

---

## Bug Type Definitions

### 1. Mandelbug
**Definition:** Complex, non-deterministic bugs arising from emergent interactions
between multiple independent systems. No single component is obviously wrong.

**MERID signals detected:**
- Component files with ≥6 `useEffect` hooks (combinatorial state space)
- Custom hooks (files starting with `use`) composing ≥8 sub-hooks (deep dependency graph)
- Components merging ≥4 independent async data sources (`useApiData`, `useSWR`,
  `useKalshi*`, `useMeridSocket`, `useKalshiRiskStream`) — 2^N UI states
- Python functions with cyclomatic complexity ≥15 decision points (exponential branch space)
- Async functions awaiting ≥5 services sequentially

**False positive rate:** Low-Medium. High counts in large view files are expected;
manual review required to confirm which exceed acceptable complexity.

---

### 2. Heisenbug
**Definition:** Bugs that disappear when you try to observe or debug them.
Adding a log statement, a breakpoint, or a sleep changes the outcome.

**MERID signals detected:**
- `console.log` inside async/timer code paths
- `setTimeout(fn, 0)` timing hacks (order changes when observed)
- Empty `catch {}` blocks (errors swallowed silently)
- `asyncio.sleep(0)` yield hacks in backend
- `print()` in async Python code paths
- `except: pass` patterns

---

### 3. Schrödinbug
**Definition:** Works fine until you examine the code carefully and realise it
shouldn't. The bug exists in the code but is masked by coincidence.

**MERID signals detected:**
- TypeScript non-null assertions (`!`) on API/response data
- `as SomeType` casts on parsed/fetched data (bypasses type checking)
- `array[0]` access without length guard, scoped to variables named
  `data`, `results`, `items`, `rows` (API response shapes)
- `localStorage.getItem()` without null check
- Mutable Python default arguments (`def f(x=[])`)
- `dict['key']` access on external data without `.get()`, scoped to variables
  named `data`, `request`, `payload`, `msg`, `event`, `body`
- `x or default` clobbering valid falsy values (0, False, '')

**Note:** The `dict['key']` pattern has a non-trivial false positive rate (~30%)
because the variable name heuristic also matches locally-constructed dicts with
those names. Manual triage required.

---

### 4. Zombie Bug
**Definition:** Bugs that were fixed but keep coming back.

**MERID signals detected:**
- `# TODO/FIXME/HACK/BUG` comments in critical execution paths (trade, risk, consensus)
- Commented-out code blocks (re-enable risk)
- `// re-added`, `// restored` markers
- Disabled test cases (`pytest.mark.skip`, `test.skip`, `xtest`)
- Files modified ≥4 times in the last 50 commits via git churn analysis
  (`git log --diff-filter=M` — modifications only, not renames/additions/deletions)

---

### 5. Race Condition / Thread Issue
**Definition:** Two or more async operations competing over shared state,
where the outcome depends on execution order.

**MERID signals detected:**
- `useEffect` with async fetch but no `AbortController` cleanup
- `setState` inside async callback without mounted guard
- Component using both WS stream and HTTP polling for same data
- `asyncio.gather()` with shared mutable container (list/dict)
- `async def` mutating shared state without `asyncio.Lock()`

---

### 6. Memory Leak
**Definition:** Resources allocated but never released; accumulates over the
lifecycle of the application.

**MERID signals detected:**
- `useEffect` with subscription/timer/listener but no cleanup return
- `addEventListener` without paired `removeEventListener`
- `asyncio.create_task()` result not stored (task lost, can't cancel on shutdown)
- `open()` without context manager
- `threading.Thread` without `daemon=True` or `.join()`

---

### 7. Regression
**Definition:** A change to one component breaks previously-working behaviour
in another component that depended on the first.

**MERID signals detected:**
- Shared abstractions modified in last 20 commits:
  - `useApiData`, `useMeridSocket`, `constants.ts` (frontend data layer)
  - `web/main.py`, `auth.py`, `schemas.py` (backend core)
  - `trading_constants.py`, `consensus_coordinator.py`, `execution_gate.py`
- Assertions removed from test files in last 10 commits
- Backend Pydantic fields not reflected in TypeScript types (cross-boundary schema drift)

---

### 8. Phase of the Moon Bug
**Definition:** Bug that only manifests under specific environmental conditions —
time of day, locale, market hours, OS, or environment variable values.

**MERID signals detected:**
- `Date.now()` / `new Date()` in conditional logic (time-window bugs)
- `.toLocaleString()` without explicit locale argument
- Hardcoded timezone offsets (DST-sensitive)
- `import.meta.env.VITE_*` flag checks in conditional branches
- `window.innerWidth` in conditional logic (viewport-sensitive)
- `datetime.now()` without timezone (naive datetime — DST bugs)
- Hardcoded market hours / day-of-week logic
- `os.getenv()` inside request handlers

---

## Extending the Audit

To add a new detector:

```python
# tools/audit/detectors/my_detector.py
from tools.audit.detectors import BaseDetector
from tools.audit.models import Finding, Layer, Severity

class MyDetector(BaseDetector):
    name = "my_detector"

    def detect(self, root: Path) -> list[Finding]:
        findings = []
        for p in self._ts_files(root):
            lines = self._lines(p)
            for i, m in self._grep(lines, r'your_pattern'):
                findings.append(Finding(
                    bug_type="my_detector",
                    severity=Severity.HIGH,
                    layer=Layer.FRONTEND,
                    file=self._rel(root, p), line=i,
                    # column defaults to 0; set to m.start() for intra-line precision
                    snippet=lines[i-1],
                    title="Short title",
                    explanation="Why it matters",
                    suggestion="How to fix",
                ))
        return findings
```

Then register in `tools/audit/run.py`:
```python
from tools.audit.detectors.my_detector import MyDetector
ALL_DETECTORS = [..., MyDetector()]
```

---

## Known Limitations

1. **Regex-based, not AST-based.** Some patterns have 20-30% false positive rates.
   All findings are *candidate sites* for manual review, not confirmed bugs.
2. **Mandelbug Python complexity** is approximated via keyword counting, not true
   cyclomatic complexity (which requires AST traversal).
3. **Schrödinbug dict access** matches variable names `data`/`request`/`payload`/`msg`/
   `event`/`body` — includes locally-constructed dicts with those names. Filter by
   reviewing the actual data source at each site.
4. **Regression detector** uses git history; requires a git repo with at least 20 commits.
5. **Windows encoding — subprocess:** Git output decoded as UTF-8 with `errors="ignore"`;
   non-UTF-8 bytes in commit messages or file paths are silently dropped.
6. **Windows encoding — file reads:** `_lines()` reads all source files as UTF-8 with
   `errors="ignore"`; non-UTF-8 source bytes are silently dropped.
7. **`_py_files` partial coverage:** Only scans six directory trees (see Scanned Directories
   above). Add glob patterns to `BaseDetector._py_files` to include `execution/`,
   `trading/`, etc.
