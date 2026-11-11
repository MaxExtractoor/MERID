"""Regression tests: promotion-report gauntlet must never freeze the server.

Production incident (2026-11-10): ``GET /api/v1/operator/promotion-report``
(and the loop's periodic ``sync_promotion_report``) call
``get_cached_promotion_report`` synchronously.  When the 5-minute cache was
stale it ran ``generate_promotion_report`` -> ``_run_paper_matrix`` ->
``subprocess.run(pytest, timeout=120)``.  ``subprocess.run`` only kills the
direct child; the venv python launcher re-execs the real interpreter as a
grandchild that inherits the capture pipes, so ``communicate()`` blocked on
pipe EOF forever after the timeout fired.  The entire uvicorn event loop —
trading loop, API, WS forwards — froze with CPU flat until manual intervention.

Fixes covered here:
- ``_run_capture`` kills the whole process tree on timeout (taskkill /T).
- ``_run_agent_gauntlet`` uses ``shutdown(wait=False)`` so its result()
  timeout is real (a ``with ThreadPoolExecutor`` block waits for the
  unkillable asyncio.run worker forever).
- ``get_cached_promotion_report`` serializes regeneration under a lock.
- ``MERID_PROMOTION_REPORT_FAST`` bypasses all subprocess rings.
"""

import os
import subprocess
import sys
import threading
import time

import pytest

from merid import promotion_report
from merid.promotion_report import (
    PromotionReport,
    _run_capture,
    get_cached_promotion_report,
    invalidate_cache,
)


# ── _run_capture: tree-kill on timeout ────────────────────────────────

def test_run_capture_returns_completed_process() -> None:
    result = _run_capture(
        [sys.executable, "-c", "print('ok')"], timeout=30
    )
    assert result.returncode == 0
    assert "ok" in result.stdout


def test_run_capture_timeout_raises_promptly_with_grandchild() -> None:
    """Reproduces the production deadlock shape: child spawns a grandchild
    that inherits the capture pipes, then both sleep.  subprocess.run's
    timeout kills only the direct child — communicate() then blocks on the
    grandchild-held pipe forever.  _run_capture must raise TimeoutExpired
    in bounded time."""
    child_code = (
        "import subprocess,sys,time;"
        "subprocess.Popen([sys.executable,'-c','import time;time.sleep(300)']);"
        "time.sleep(300)"
    )
    t0 = time.time()
    with pytest.raises(subprocess.TimeoutExpired):
        _run_capture([sys.executable, "-c", child_code], timeout=2)
    elapsed = time.time() - t0
    # Tree-kill + drain must finish promptly — the old code path never
    # returned at all (observed >15min freeze in production).
    assert elapsed < 60, f"tree-kill took {elapsed:.1f}s — pipe still held"


def test_run_capture_timeout_kills_grandchild_processes() -> None:
    """Verify no sleeper grandchild survives the timeout kill.

    The production freeze happened because the grandchild (real interpreter
    behind the venv launcher) inherited the capture pipes and outlived the
    killed direct child.  Embed a unique token in the grandchild cmdline and
    assert no process carrying it remains after _run_capture returns.
    """
    import psutil

    token = f"merid_pr_gc_{os.getpid()}_{int(time.time())}"
    child_code = (
        "import subprocess,sys,time;"
        f"subprocess.Popen([sys.executable,'-c',"
        f"'import time;time.sleep(300) # {token}']);"
        "time.sleep(300)"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        _run_capture([sys.executable, "-c", child_code], timeout=5)

    # taskkill /T is asynchronous-ish; give it a moment then scan.
    deadline = time.time() + 10
    survivors = []
    while time.time() < deadline:
        survivors = [
            p.pid
            for p in psutil.process_iter(["cmdline"])
            if p.info["cmdline"]
            and any(token in part for part in p.info["cmdline"])
        ]
        if not survivors:
            break
        time.sleep(0.25)
    assert not survivors, f"grandchild processes survived tree-kill: {survivors}"


# ── Cache regeneration lock ──────────────────────────────────────────

def test_get_cached_promotion_report_serializes_regeneration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent stale-cache callers must share ONE regeneration, not
    stampede the subprocess gauntlet."""
    calls = []
    call_lock = threading.Lock()

    def _slow_generate(gauntlet_cycles: int = 10):
        with call_lock:
            calls.append(1)
        time.sleep(0.3)
        return PromotionReport(timestamp=time.time())

    monkeypatch.setattr(promotion_report, "generate_promotion_report", _slow_generate)
    invalidate_cache()
    results = []
    threads = [
        threading.Thread(
            target=lambda: results.append(get_cached_promotion_report(gauntlet_cycles=1))
        )
        for _ in range(6)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert len(results) == 6
    assert len(calls) == 1, f"expected 1 regeneration, got {len(calls)}"
    invalidate_cache()


def test_get_cached_promotion_report_uses_cache_within_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def _gen(gauntlet_cycles: int = 10):
        calls.append(1)
        return PromotionReport(timestamp=time.time())

    monkeypatch.setattr(promotion_report, "generate_promotion_report", _gen)
    invalidate_cache()
    first = get_cached_promotion_report(gauntlet_cycles=1)
    second = get_cached_promotion_report(gauntlet_cycles=1)
    assert first is second
    assert len(calls) == 1
    invalidate_cache()


# ── FAST mode: no subprocess rings in production ─────────────────────

def test_fast_mode_skips_all_subprocess_rings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MERID_PROMOTION_REPORT_FAST", "1")

    def _boom(*a, **k):
        raise AssertionError("subprocess ring must not run in FAST mode")

    monkeypatch.setattr(promotion_report, "_run_blueprint_checks", _boom)
    monkeypatch.setattr(promotion_report, "_run_paper_matrix", _boom)
    monkeypatch.setattr(promotion_report, "_run_agent_gauntlet", _boom)

    report = promotion_report.generate_promotion_report(gauntlet_cycles=5)
    assert len(report.rings) == 3
    assert all(r.passed for r in report.rings)
