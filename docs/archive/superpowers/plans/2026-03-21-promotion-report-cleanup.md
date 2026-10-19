# Promotion Report Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 6 bugs in the promotion report system that cause every domain to be permanently blocked, clean up dead/broken files, and wire up missing functions so all features actually work.

**Architecture:** The promotion report runs three validation rings (blueprint CI, paper matrix SLOs, agent gauntlet) and produces a domain/agent eligibility verdict consumed by `ExecutionGuard`. Currently Ring 1 always fails because `run_all_checks()` is missing from `ci_blueprint_checks.py` and the subprocess fallback can't parse its own mixed-text stdout as JSON. Ring 3 vacuously passes with 0 agents. Three functions referenced from live code (`run_promotion_check`, `get_effective_domain_status`, `get_effective_agent_status`) don't exist. Two dead files have broken imports.

**Tech Stack:** Python 3.12, FastAPI, asyncio, pytest

---

## File Map

| File | Action | What changes |
|------|--------|--------------|
| `scripts/ci_blueprint_checks.py` | Modify | Add `run_all_checks()` returning structured data |
| `merid/promotion_report.py` | Modify | Fix 6 bugs; add 3 missing functions |
| `merid/execution_guard_backup.py` | Archive | Move to `archive/` — no imports anywhere |
| `web/api/operator_api.py` | Archive | Move to `archive/` — not mounted in `main.py`, broken imports |

**Files NOT touched** (they work correctly once the above are fixed):
- `merid/execution_guard.py` — promotion check correctly gated by `is_live=True`
- `merid/loop.py` — uses `asyncio.to_thread` for the 5-min sync, correct
- `merid/prediction/agent_performance_tracker.py:310` — try/except already wraps the broken import; works once `run_promotion_check` exists

---

## Task 1: Add `run_all_checks()` to `ci_blueprint_checks.py`

**Files:**
- Modify: `scripts/ci_blueprint_checks.py`

**Root cause:** `merid/promotion_report.py:450` tries `from scripts.ci_blueprint_checks import run_all_checks` — this function doesn't exist. The `ImportError` falls through to a subprocess fallback that tries `json.loads(result.stdout)` on mixed human-readable + JSON stdout, which always raises `JSONDecodeError`, returning `RingResult(passed=False)`. Ring 1 has never passed.

- [ ] **Step 1: Add `run_all_checks()` to `ci_blueprint_checks.py`**

Add this function directly above `main()` in `scripts/ci_blueprint_checks.py`:

```python
import io
import contextlib

def run_all_checks() -> list:
    """Return structured results for all checks.

    Each item: {"name": str, "status": "pass"/"fail"/"warn", "detail": str}
    Used by merid.promotion_report._run_blueprint_checks() for programmatic access.
    """
    checks = [
        ("paper_config", check_paper_config),
        ("ts_manifest", check_ts_manifest),
        ("manifest_audit", check_manifest_audit_crosscheck),
        ("form_fields", check_form_fields),
        ("matching_engines", check_matching_engines),
    ]
    results = []
    for name, fn in checks:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            passed = fn()
        results.append({
            "name": name,
            "status": "pass" if passed else "fail",
            "detail": buf.getvalue().strip(),
        })
    return results
```

Note: `import io` and `import contextlib` go at the top of the `ci_blueprint_checks.py` module (not inside the loop). The block above shows the correct placement — add both imports at the top of the file alongside the existing `import json`, `import os`, etc.

- [ ] **Step 2: Verify it's importable and returns the right shape**

```bash
cd /c/Dev/MERID && python -c "
from scripts.ci_blueprint_checks import run_all_checks
r = run_all_checks()
assert isinstance(r, list)
assert all('name' in x and 'status' in x for x in r)
print('OK:', [(x['name'], x['status']) for x in r])
"
```

Expected: prints list of `(name, "pass"/"fail")` tuples with no exception.

- [ ] **Step 3: Commit**

```bash
git add scripts/ci_blueprint_checks.py
git commit -m "fix: add run_all_checks() to ci_blueprint_checks — was missing, caused Ring 1 to always fail"
```

---

## Task 2: Fix `_run_blueprint_checks()` — subprocess fallback

**Files:**
- Modify: `merid/promotion_report.py` (lines 446–500)

Even with `run_all_checks()` now importable, the subprocess fallback still has two bugs if the import somehow fails: (a) parses mixed stdout as raw JSON, (b) looks for key `"checks"` but the script outputs key `"results"`. Fix the fallback to be robust.

- [ ] **Step 1: Replace `_run_blueprint_checks()` in `merid/promotion_report.py`**

Replace the entire function (lines 446–500):

```python
def _run_blueprint_checks() -> RingResult:
    """Run CI blueprint checks and parse results."""
    t0 = time.time()
    try:
        # Direct import — fast path (run_all_checks() added in Task 1)
        from scripts.ci_blueprint_checks import run_all_checks
        results = run_all_checks()

        passed = sum(1 for r in results if r["status"] == "pass")
        total = len(results)
        failures = [r["name"] for r in results if r["status"] == "fail"]
        warnings = [r["name"] for r in results if r["status"] == "warn"]

        return RingResult(
            name="blueprint",
            passed=len(failures) == 0,
            checks_passed=passed,
            checks_total=total,
            failures=failures,
            warnings=warnings,
            elapsed_s=time.time() - t0,
        )
    except Exception as e:
        # Subprocess fallback — use returncode only, not stdout parsing
        try:
            result = subprocess.run(
                [sys.executable, "scripts/ci_blueprint_checks.py"],
                capture_output=True, text=True, timeout=60,
            )
            return RingResult(
                name="blueprint",
                passed=result.returncode == 0,
                checks_passed=0,
                checks_total=0,
                failures=[] if result.returncode == 0 else [f"subprocess exit {result.returncode}"],
                warnings=[],
                elapsed_s=time.time() - t0,
            )
        except Exception as sub_e:
            return RingResult(
                name="blueprint", passed=False,
                failures=[f"blueprint checks unavailable: {sub_e}"],
                elapsed_s=time.time() - t0,
            )
```

- [ ] **Step 2: Quick smoke test**

```bash
cd /c/Dev/MERID && python -c "
from merid.promotion_report import _run_blueprint_checks
r = _run_blueprint_checks()
print('passed:', r.passed, 'checks:', r.checks_passed, '/', r.checks_total)
print('failures:', r.failures)
"
```

Expected: `passed: True` (or `False` with named failures, not a JSON parse error).

- [ ] **Step 3: Commit**

```bash
git add merid/promotion_report.py
git commit -m "fix: _run_blueprint_checks subprocess fallback — use returncode, not json.loads on mixed stdout"
```

---

## Task 3: Fix `_run_agent_gauntlet()` — asyncio + vacuous pass

**Files:**
- Modify: `merid/promotion_report.py` (lines 564–607)

Two bugs:
1. `asyncio.get_event_loop()` raises `RuntimeError` in Python 3.12+ background threads (the guard startup thread), causing Ring 3 to always return `passed=False`.
2. When the agent registry is empty, `summary["failed"] == 0` is vacuously `True` → ring passes with zero agents evaluated.

- [ ] **Step 1: Replace the asyncio section and vacuous-pass guard in `_run_agent_gauntlet()`**

Replace lines 564–607:

```python
def _run_agent_gauntlet(cycles: int = 10) -> tuple:
    """Run agent gauntlet and return (RingResult, List[AgentPromotion])."""
    t0 = time.time()
    try:
        from merid.agent_gauntlet import run_gauntlet, gauntlet_summary, GauntletResult

        # Python 3.12+ raises RuntimeError in non-async threads for get_event_loop().
        # Use get_running_loop() to detect, fall back to asyncio.run().
        try:
            asyncio.get_running_loop()
            # A loop IS running (we're inside an async context) — use thread pool.
            # IMPORTANT: pass a lambda so the coroutine is created inside the worker
            # thread, not in the calling thread. Coroutines are not thread-safe objects.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                verdicts = pool.submit(
                    lambda: asyncio.run(run_gauntlet(cycles=cycles))
                ).result(timeout=120)
        except RuntimeError:
            # No running loop — safe to call asyncio.run() directly
            verdicts = asyncio.run(run_gauntlet(cycles=cycles))

        summary = gauntlet_summary(verdicts)

        agent_promotions = []
        for v in verdicts:
            agent_promotions.append(AgentPromotion(
                agent_id=v.agent_id,
                category=v.category,
                promoted=v.promoted,
                slo_pass_rate=v.pass_rate,
                failed_slos=[c.name for c in v.checks if not c.passed],
            ))

        failures = [v.agent_id for v in verdicts if v.result == GauntletResult.FAIL]

        # Require at least one agent evaluated — empty registry is not a pass
        total_agents = summary["total_agents"]
        ring_passed = summary["failed"] == 0 and total_agents > 0

        ring = RingResult(
            name="gauntlet",
            passed=ring_passed,
            checks_passed=summary["passed"],
            checks_total=total_agents,
            failures=failures if failures else (["no_agents_registered"] if total_agents == 0 else []),
            elapsed_s=time.time() - t0,
        )
        return ring, agent_promotions

    except Exception as e:
        ring = RingResult(
            name="gauntlet", passed=False,
            failures=[str(e)],
            elapsed_s=time.time() - t0,
        )
        return ring, []
```

- [ ] **Step 2: Verify the fix**

```bash
cd /c/Dev/MERID && python -c "
from merid.promotion_report import _run_agent_gauntlet
ring, agents = _run_agent_gauntlet(cycles=1)
print('ring.passed:', ring.passed)
print('ring.failures:', ring.failures)
print('agents:', len(agents))
# Should be: passed=False, failures=['no_agents_registered'], agents=0
# (unless real agents are registered, in which case passed depends on SLOs)
"
```

- [ ] **Step 3: Commit**

```bash
git add merid/promotion_report.py
git commit -m "fix: _run_agent_gauntlet — fix asyncio.get_event_loop() in Py3.12 threads; require >0 agents to pass ring"
```

---

## Task 4: Fix `_assess_domains()` — mode check blocks already-live domains

**Files:**
- Modify: `merid/promotion_report.py` (lines 612–658)

Bug: `if dc.mode.value != "paper": blockers.append(...)` means a domain already in live mode is marked `blocked`. Only SIM mode should be a blocker; live-mode domains are already promoted.

- [ ] **Step 1: Fix the mode check in `_assess_domains()`**

Find this block (around line 627):
```python
        if dc.mode.value != "paper":
            blockers.append(f"mode is {dc.mode.value}, not paper")
```

Replace with:
```python
        if dc.mode.value == "sim":
            blockers.append("domain in sim mode, not ready for paper promotion")
        # Note: live-mode domains are already promoted — no blocker needed
```

- [ ] **Step 2: Verify**

```bash
cd /c/Dev/MERID && python -c "
from merid.promotion_report import _assess_domains
domains = _assess_domains(rings_pass=True)
for d in domains:
    print(d.domain, 'eligible:', d.eligible, 'blockers:', d.blockers)
"
```

Expected: `crypto` and `equity` should show `eligible: True` (they have instruments + reconciliation venue). `prediction`/`betting`/`macro` will still show `no instruments registered` until those are seeded at runtime.

- [ ] **Step 3: Commit**

```bash
git add merid/promotion_report.py
git commit -m "fix: _assess_domains mode check — only block sim mode; live-mode domains are already promoted"
```

---

## Task 5: Add three missing functions to `promotion_report.py`

**Files:**
- Modify: `merid/promotion_report.py`

Three functions are called from live code but don't exist:
- `run_promotion_check(agent_id)` — called from `agent_performance_tracker.py:311`
- `get_effective_domain_status(domain)` — imported in `web/api/operator_api.py`
- `get_effective_agent_status(agent_id)` — imported in `web/api/operator_api.py`

- [ ] **Step 1: Add the three functions to `merid/promotion_report.py`**

Add after the `invalidate_cache()` function (around line 727):

```python
def run_promotion_check(agent_id: str) -> None:
    """Trigger a promotion eligibility re-check for a specific agent.

    Called by agent_performance_tracker after a market settles.
    Invalidates the cached report so the next poll regenerates it,
    ensuring the agent's latest metrics are reflected.
    """
    invalidate_cache()
    logger.info("promotion_check: triggered for agent '%s' (cache invalidated)", agent_id)


def get_effective_domain_status(domain: str) -> dict:
    """Return the current promotion status for a domain.

    Returns a dict with keys: domain, eligible, mode, blockers, instruments.
    Uses the cached report (5-min TTL) to avoid regenerating on every call.
    """
    report = get_cached_promotion_report(gauntlet_cycles=5)
    match = next((d for d in report.domains if d.domain == domain), None)
    if match is None:
        return {"domain": domain, "eligible": False, "blockers": ["domain_not_found"]}
    return match.to_dict()


def get_effective_agent_status(agent_id: str) -> dict:
    """Return the current promotion status for an agent.

    Returns a dict with keys: agent_id, promoted, slo_pass_rate, failed_slos.
    Uses the cached report (5-min TTL).
    """
    report = get_cached_promotion_report(gauntlet_cycles=5)
    match = next((a for a in report.agents if a.agent_id == agent_id), None)
    if match is None:
        return {"agent_id": agent_id, "promoted": False, "slo_pass_rate": 0.0,
                "failed_slos": ["agent_not_in_report"]}
    return match.to_dict()
```

- [ ] **Step 2: Verify imports work from all call sites**

```bash
cd /c/Dev/MERID && python -c "
from merid.promotion_report import (
    run_promotion_check,
    get_effective_domain_status,
    get_effective_agent_status,
)
print('run_promotion_check:', run_promotion_check)
print('get_effective_domain_status:', get_effective_domain_status)
print('get_effective_agent_status:', get_effective_agent_status)
print('All imports OK')
"
```

- [ ] **Step 3: Verify `agent_performance_tracker.py` no longer silently swallows the error**

```bash
cd /c/Dev/MERID && python -c "
from merid.prediction.agent_performance_tracker import AgentPerformanceTracker
t = AgentPerformanceTracker()
# record_settlement calls run_promotion_check — patch the DB call so it doesn't need a real DB
print('tracker instantiated OK')
"
```

- [ ] **Step 4: Add basic tests for the three new functions in `tests/test_promotion_report.py`**

```python
def test_run_promotion_check_invalidates_cache(monkeypatch):
    from merid import promotion_report as pr
    calls = []
    monkeypatch.setattr(pr, "invalidate_cache", lambda: calls.append(1))
    pr.run_promotion_check("some_agent")
    assert len(calls) == 1

def test_get_effective_domain_status_known_domain(monkeypatch):
    from merid import promotion_report as pr
    from merid.promotion_report import DomainEligibility
    fake_report = type("R", (), {
        "domains": [DomainEligibility(domain="crypto", eligible=True)],
        "agents": [],
    })()
    monkeypatch.setattr(pr, "get_cached_promotion_report", lambda **_: fake_report)
    result = pr.get_effective_domain_status("crypto")
    assert result["domain"] == "crypto"
    assert result["eligible"] is True

def test_get_effective_domain_status_unknown_domain(monkeypatch):
    from merid import promotion_report as pr
    fake_report = type("R", (), {"domains": [], "agents": []})()
    monkeypatch.setattr(pr, "get_cached_promotion_report", lambda **_: fake_report)
    result = pr.get_effective_domain_status("nonexistent")
    assert result["eligible"] is False
    assert "domain_not_found" in result["blockers"]

def test_get_effective_agent_status_unknown_agent(monkeypatch):
    from merid import promotion_report as pr
    fake_report = type("R", (), {"domains": [], "agents": []})()
    monkeypatch.setattr(pr, "get_cached_promotion_report", lambda **_: fake_report)
    result = pr.get_effective_agent_status("ghost_agent")
    assert result["promoted"] is False
    assert "agent_not_in_report" in result["failed_slos"]
```

Run: `pytest tests/test_promotion_report.py -v -k "effective or promotion_check" --tb=short`
Expected: all 4 new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add merid/promotion_report.py tests/test_promotion_report.py
git commit -m "fix: add run_promotion_check, get_effective_domain_status, get_effective_agent_status — were imported but never defined"
```

---

## Task 6: Archive dead files

**Files:**
- Archive: `merid/execution_guard_backup.py` → `archive/`
- Archive: `web/api/operator_api.py` → `archive/legacy_api/`

Both confirmed safe:
- `execution_guard_backup.py`: zero imports found anywhere in production code
- `web/api/operator_api.py`: not mounted in `web/main.py`; additionally has a pre-existing `AttributeError` bug — lines 153–197 call `log.manual_promote()` / `log.manual_demote()` as `PromotionLog` instance methods, but those are module-level functions in `promotion_report.py`, not methods on the class. Any call to those endpoints would crash. The equivalent functions `manual_promote()` / `manual_demote()` are already exposed correctly via `web/api/operator.py`. This file is not recoverable without a rewrite.

- [ ] **Step 1: Move the files**

```bash
mv /c/Dev/MERID/merid/execution_guard_backup.py /c/Dev/MERID/archive/
mv /c/Dev/MERID/web/api/operator_api.py /c/Dev/MERID/archive/legacy_api/operator_api_web.py
```

- [ ] **Step 2: Verify nothing broke**

```bash
cd /c/Dev/MERID && python -c "
from merid.execution_guard import get_execution_guard
from web.api.operator import router
print('execution_guard OK')
print('operator router OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: archive execution_guard_backup.py and unmounted operator_api.py — confirmed no live imports"
```

---

## Task 7: End-to-end verification

- [ ] **Step 1: Run the full promotion report**

```bash
cd /c/Dev/MERID && python -m merid.promotion_report --fast
```

Expected output:
```
[PASS] blueprint        X/5 checks  (Xs)
[PASS/FAIL] paper_matrix  X/X tests   (Xs)
[PASS/FAIL] gauntlet    X/X agents  (Xs)
...
domains: N/5 eligible
agents:  N/N promoted
```

Ring 1 should now show actual check names and counts instead of a JSON parse error. Ring 3 should show `failures: ['no_agents_registered']` if no agents are registered (not silently pass).

- [ ] **Step 2: Run the paper trading matrix tests**

```bash
cd /c/Dev/MERID && python -m pytest tests/test_paper_trading_matrix.py -v --tb=short 2>&1 | tail -20
```

- [ ] **Step 3: Run all promotion-related tests**

```bash
cd /c/Dev/MERID && python -m pytest tests/test_promotion_report.py tests/test_promotion_log.py tests/test_guard_promotion.py -v --tb=short 2>&1 | tail -30
```

- [ ] **Step 4: Confirm no broken imports in the operator API**

```bash
cd /c/Dev/MERID && python -c "from web.api.operator import router; print('operator router OK')"
```

- [ ] **Step 5: Final commit if any fixes needed from above**

```bash
git add -A && git commit -m "fix: promotion report system — all 6 bugs fixed, dead files archived, missing functions added"
```
