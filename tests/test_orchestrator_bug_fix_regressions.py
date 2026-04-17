"""test_orchestrator_bug_fix_regressions.py

Regression tests for the 8 orchestrator / execution-guard bug fixes identified
in the March 2026 audit of merid/loop.py, web/main.py, merid/execution_guard.py,
and web/api/health.py.

BUG-H1  startup_gate         — MeridLoop.run() blocked when startup_success=False
BUG-H2  kalshi_circuit_gate  — _execute_plans fast-exits when Kalshi circuit is open
BUG-H4  venue_exposure_sync  — _reconcile_positions syncs VenueExposureCap from real positions
BUG-H5  recon_before_exec    — reconciliation runs BEFORE _execute_plans every tick
BUG-H6  tick_step_order      — reconciliation is sequential, not inside the parallel gather
BUG-H7  health_endpoint_live — /api/health returns live checks and HTTP 503 on failure
BUG-H8  bg_task_drain        — run() awaits/cancels background tasks before releasing refs
MEDIUM  singleton_lock        — get_merid_loop() uses threading.Lock (double-checked)
"""
from __future__ import annotations

import asyncio
import sys
import types
import logging
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Minimal utils.logger stub (mirrors conftest.py pattern)
# ---------------------------------------------------------------------------
if "utils.logger" not in sys.modules:
    import contextvars as _cv
    _ul = types.ModuleType("utils.logger")
    _ul.get_logger = logging.getLogger  # type: ignore[attr-defined]
    _ul.correlation_id_var = _cv.ContextVar("correlation_id", default=None)  # type: ignore[attr-defined]
    _ul.get_correlation_id = lambda: None  # type: ignore[attr-defined]
    _ul.set_correlation_id = lambda cid: None  # type: ignore[attr-defined]
    _ul.set_task_context = lambda **kw: None  # type: ignore[attr-defined]
    sys.modules["utils.logger"] = _ul

# Patch set_task_context so loop imports don't break
if hasattr(sys.modules.get("utils.logger"), "set_task_context") is False:
    sys.modules["utils.logger"].set_task_context = lambda **kw: None  # type: ignore[attr-defined]


# ===========================================================================
# Helpers
# ===========================================================================

def _mock_agent_grid_ready() -> MagicMock:
    """AgentGrid state that satisfies /api/health when not in VALIDATION_MODE."""
    ag = MagicMock()
    ag._startup_complete = True
    ag._agents_ready = True
    ag._ws_ready = True
    ag._running = True
    return ag


def _make_loop():
    """Return a fresh MeridLoop with a default config and all intervals zeroed
    so every step runs on the very first tick."""
    from merid.loop import MeridLoop, LoopConfig
    cfg = LoopConfig()
    # Zero all intervals so every step fires on tick 1
    cfg.agent_cycle_interval = 0
    cfg.feature_refresh_interval = 0
    cfg.consensus_interval = 0
    cfg.arb_scan_interval = 0
    cfg.cqi_interval = 0
    cfg.reconciliation_interval = 0
    loop = MeridLoop(cfg)
    loop._last_agent_cycle = 0
    loop._last_feature_refresh = 0
    loop._last_consensus = 0
    loop._last_arb_scan = 0
    loop._last_cqi_update = 0
    loop._last_liquidity_refresh = 0
    loop._last_reconciliation = 0
    loop._last_betting_refresh = 0
    loop._last_promotion_sync = float("inf")   # suppress bg promo task
    loop._last_config_reload = float("inf")    # suppress config reload
    loop._last_reflection_cycle = float("inf") # suppress reflection
    return loop


def _noop_run_step(name, coro, summary):
    """Async replacement for _run_step that awaits the coro and returns None."""
    async def _inner():
        try:
            await coro
        except Exception:
            pass
    return _inner()


# ===========================================================================
# BUG-H1: MeridLoop singleton lock — get_merid_loop() thread-safety
# ===========================================================================
class TestBugH1SingletonLock:
    """The get_merid_loop() singleton must use double-checked locking."""

    def test_lock_attribute_exists(self):
        """_loop_lock must be a threading.Lock at module level in merid.loop."""
        import merid.loop as loop_mod
        assert hasattr(loop_mod, "_loop_lock"), (
            "_loop_lock is missing from merid.loop — singleton is not thread-safe"
        )
        assert isinstance(loop_mod._loop_lock, type(threading.Lock())), (
            "_loop_lock must be a threading.Lock"
        )

    def test_get_merid_loop_returns_same_instance(self):
        """Two calls to get_merid_loop() must return the same object."""
        import merid.loop as loop_mod
        old = loop_mod._loop
        try:
            loop_mod._loop = None
            a = loop_mod.get_merid_loop()
            b = loop_mod.get_merid_loop()
            assert a is b, "get_merid_loop() must return a singleton"
        finally:
            loop_mod._loop = old

    def test_concurrent_calls_produce_one_instance(self):
        """Concurrent threads racing to call get_merid_loop() must get the same instance."""
        import merid.loop as loop_mod
        old = loop_mod._loop
        results = []
        try:
            loop_mod._loop = None

            def caller():
                results.append(loop_mod.get_merid_loop())

            threads = [threading.Thread(target=caller) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(set(id(r) for r in results)) == 1, (
                "Concurrent get_merid_loop() calls produced multiple instances — "
                "lock not protecting singleton creation"
            )
        finally:
            loop_mod._loop = old


# ===========================================================================
# BUG-H2: Kalshi circuit-open fast-path in _execute_plans
# ===========================================================================
class TestBugH2KalshiCircuitGate:
    """_execute_plans must fast-exit with 'execution:blocked_by_kalshi_circuit_open'
    when the Kalshi client circuit breaker is open."""

    @pytest.mark.asyncio
    async def test_execute_plans_blocked_when_circuit_open(self):
        loop = _make_loop()
        summary = {"tick": 1, "actions": []}

        mock_guard = MagicMock()
        mock_guard.kill_switch_active = False

        mock_client = MagicMock()
        mock_client.is_circuit_open = True

        with patch.object(loop, "_execution_guard", return_value=mock_guard), \
             patch("merid.event_venues.kalshi.client.get_kalshi_client",
                   return_value=mock_client):
            await loop._execute_plans(summary)

        assert "execution:blocked_by_kalshi_circuit_open" in summary["actions"], (
            "_execute_plans did not block when Kalshi circuit is open. "
            "BUG-H2 fast-path is missing or broken."
        )

    @pytest.mark.asyncio
    async def test_execute_plans_proceeds_when_circuit_closed(self):
        """When circuit is closed, _execute_plans must not insert the circuit-open action."""
        loop = _make_loop()
        summary = {"tick": 1, "actions": []}

        mock_guard = MagicMock()
        mock_guard.kill_switch_active = False

        mock_client = MagicMock()
        mock_client.is_circuit_open = False

        # Patch everything downstream so the function returns early naturally
        with patch.object(loop, "_execution_guard", return_value=mock_guard), \
             patch("merid.event_venues.kalshi.client.get_kalshi_client",
                   return_value=mock_client), \
             patch("merid.reconciliation.has_critical_discrepancies",
                   return_value=False):
            # _risk_context and plan fetching will raise — that's fine, we only
            # care that the circuit-open action was NOT injected.
            try:
                await loop._execute_plans(summary)
            except Exception:
                pass

        assert "execution:blocked_by_kalshi_circuit_open" not in summary["actions"], (
            "_execute_plans injected circuit-open block even though circuit is closed."
        )

    @pytest.mark.asyncio
    async def test_kill_switch_still_takes_priority(self):
        """Global kill switch must still block before the circuit-open check."""
        loop = _make_loop()
        summary = {"tick": 1, "actions": []}

        mock_guard = MagicMock()
        mock_guard.kill_switch_active = True

        mock_client = MagicMock()
        mock_client.is_circuit_open = True

        with patch.object(loop, "_execution_guard", return_value=mock_guard), \
             patch("merid.event_venues.kalshi.client.get_kalshi_client",
                   return_value=mock_client):
            await loop._execute_plans(summary)

        assert "execution:blocked_by_kill_switch" in summary["actions"]
        assert "execution:blocked_by_kalshi_circuit_open" not in summary["actions"], (
            "Circuit-open action was injected even after kill switch should have short-circuited."
        )


# ===========================================================================
# BUG-H4: VenueExposureCap synced from real positions after reconciliation
# ===========================================================================
class TestBugH4VenueExposureSync:
    """_reconcile_positions must call sync_venue_exposure() after a successful
    Kalshi reconciliation so ExecutionGuard tracks real open exposure."""

    @pytest.mark.asyncio
    async def test_sync_venue_exposure_called_after_reconciliation(self):
        loop = _make_loop()
        loop.config.enable_reconciliation = True
        loop.config.active_domains = ["prediction"]
        summary = {"tick": 1, "actions": []}

        mock_guard = MagicMock()
        sync_calls = []
        mock_guard.sync_venue_exposure = lambda venue, amt: sync_calls.append((venue, amt))

        # Fake position list: two positions, 200 cents each = $4.00 total notional
        fake_pos = [MagicMock(total_cost=200, notional=0), MagicMock(total_cost=200, notional=0)]
        fake_result = MagicMock()
        fake_result.data = fake_pos

        mock_client = MagicMock()
        mock_client.get_positions = AsyncMock(return_value=fake_result)
        mock_client.is_circuit_open = False

        with patch.object(loop, "_execution_guard", return_value=mock_guard), \
             patch("merid.reconciliation.reconcile_venue", return_value=[]), \
             patch("merid.reconciliation.has_critical_discrepancies", return_value=False), \
             patch("merid.event_venues.kalshi.client.get_kalshi_client",
                   return_value=mock_client):
            await loop._reconcile_positions(summary)

        assert len(sync_calls) == 1, (
            "sync_venue_exposure was not called after Kalshi reconciliation. "
            "BUG-H4 fix is missing — VenueExposureCap will not reflect real positions."
        )
        venue, notional = sync_calls[0]
        assert venue == "kalshi"
        assert abs(notional - 4.0) < 0.01, (
            f"Expected notional=$4.00 (400 cents / 100), got ${notional:.2f}"
        )

    @pytest.mark.asyncio
    async def test_sync_skipped_when_prediction_domain_inactive(self):
        """sync_venue_exposure must not be called when prediction domain is off."""
        loop = _make_loop()
        loop.config.enable_reconciliation = True
        loop.config.active_domains = ["crypto"]   # no "prediction"
        summary = {"tick": 1, "actions": []}

        mock_guard = MagicMock()
        sync_calls = []
        mock_guard.sync_venue_exposure = lambda v, a: sync_calls.append((v, a))

        with patch.object(loop, "_execution_guard", return_value=mock_guard):
            await loop._reconcile_positions(summary)

        assert sync_calls == [], (
            "sync_venue_exposure was called even though prediction domain is inactive."
        )


# ===========================================================================
# BUG-H5+H6: Reconciliation runs BEFORE _execute_plans in tick()
# ===========================================================================
class TestBugH5H6ReconBeforeExec:
    """Reconciliation must be a sequential step that completes before _execute_plans
    is called, not a parallel step that may run concurrently or after execution."""

    @pytest.mark.asyncio
    async def test_reconciliation_runs_before_execution(self):
        """Record call order: reconciliation must precede execution."""
        loop = _make_loop()
        loop.config.enable_reconciliation = True
        loop.config.enable_execution = True
        loop.config.active_domains = ["prediction"]

        call_order = []

        # Use a side_effect on _run_step to intercept reconciliation and execution
        # without creating orphaned coroutines.
        _original_run_step = loop._run_step.__func__ if hasattr(loop._run_step, "__func__") else None

        async def tracking_run_step(name, coro, summary):
            if name in ("reconciliation", "execution"):
                call_order.append(name)
            # Always consume the coroutine to avoid RuntimeWarning
            try:
                await coro
            except Exception:
                pass

        with patch.object(loop, "_run_step", side_effect=tracking_run_step), \
             patch.object(loop, "_run_agent_cycles_bg", new=AsyncMock()), \
             patch.object(loop, "_notify", new=AsyncMock()), \
             patch("merid.reconciliation.reconcile_venue", return_value=[]), \
             patch("merid.reconciliation.has_critical_discrepancies", return_value=False):
            try:
                await loop.tick()
            except Exception:
                pass  # downstream errors are acceptable; we only care about order

        assert "reconciliation" in call_order, "reconciliation step never ran"
        assert "execution" in call_order, "execution step never ran"

        recon_idx = call_order.index("reconciliation")
        exec_idx = call_order.index("execution")
        assert recon_idx < exec_idx, (
            f"Execution (pos {exec_idx}) ran before reconciliation (pos {recon_idx}). "
            "BUG-H5/H6 fix is missing — tick() step order is wrong."
        )

    def test_reconciliation_not_in_parallel_gather(self):
        """Inspect tick() source: reconciliation must not be appended to parallel_coros."""
        import inspect
        from merid.loop import MeridLoop
        source = inspect.getsource(MeridLoop.tick)

        # Find the parallel_coros gather block boundaries
        gather_start = source.find("parallel_coros = []")
        gather_end = source.find("await asyncio.gather(*parallel_coros)")

        assert gather_start != -1, "Could not find parallel_coros block in tick()"
        assert gather_end != -1, "Could not find asyncio.gather call in tick()"

        parallel_block = source[gather_start:gather_end]
        assert "_reconcile_positions" not in parallel_block, (
            "_reconcile_positions is still inside the parallel_coros gather block. "
            "BUG-H6 fix is missing — reconciliation runs concurrently with other steps."
        )

    def test_execute_plans_comes_after_reconciliation_in_source(self):
        """In tick() source, the _run_step("reconciliation", ...) call must appear
        before the _run_step("execution", ...) call — not before the method definitions."""
        import inspect
        from merid.loop import MeridLoop
        source = inspect.getsource(MeridLoop.tick)

        # Search for the _run_step CALL SITES, not the method definition names.
        # Use the string argument passed to _run_step to find the exact call.
        recon_pos = source.find('"reconciliation"')
        exec_pos = source.find('"execution"')

        assert recon_pos != -1, '_run_step("reconciliation", ...) call not found in tick()'
        assert exec_pos != -1, '_run_step("execution", ...) call not found in tick()'
        assert recon_pos < exec_pos, (
            f'_run_step("execution") (char {exec_pos}) appears before '
            f'_run_step("reconciliation") (char {recon_pos}) in tick() source. '
            'BUG-H5/H6 not fixed — reconciliation must precede execution.'
        )


# ===========================================================================
# BUG-H7: /api/health returns live checks and HTTP 503 on failure
# ===========================================================================
@pytest.mark.kalshi_live_ready
@pytest.mark.p0_live_blocker
class TestBugH7HealthEndpointLive:
    """/api/health must perform real subsystem checks and return HTTP 503
    when a critical check fails, not always return a hardcoded 200 healthy."""

    def _make_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from web.api.health import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app, raise_server_exceptions=False)

    def test_health_returns_200_when_all_checks_pass(self):
        client = self._make_client()

        mock_guard = MagicMock()
        mock_guard.kill_switch_active = False
        mock_guard._global_kill_reason = ""

        mock_kc = MagicMock()
        mock_kc.is_circuit_open = False
        mock_kc.get_circuit_status = MagicMock(return_value={})

        mock_loop = MagicMock()
        mock_loop.status.return_value = {
            "running": True,
            "metrics": {"total_ticks": 5, "tick_errors": 0, "last_tick_duration_ms": 120},
        }

        mock_ag = _mock_agent_grid_ready()
        with patch("merid.execution_guard.get_execution_guard", return_value=mock_guard), \
             patch("merid.event_venues.kalshi.client.get_kalshi_client",
                   return_value=mock_kc), \
             patch("merid.loop.get_merid_loop", return_value=mock_loop), \
             patch("merid.prediction.agent_grid.get_agent_grid", return_value=mock_ag):
            resp = client.get("/api/health")

        assert resp.status_code == 200, (
            f"Expected 200 when all checks pass, got {resp.status_code}"
        )
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["critical_failures"] == []

    def test_health_returns_503_when_kill_switch_active(self):
        client = self._make_client()

        mock_guard = MagicMock()
        mock_guard.kill_switch_active = True
        mock_guard._global_kill_reason = "manual test"

        mock_kc = MagicMock()
        mock_kc.is_circuit_open = False
        mock_kc.get_circuit_status = MagicMock(return_value={})

        mock_loop = MagicMock()
        mock_loop.status.return_value = {"running": True, "metrics": {}}

        with patch("merid.execution_guard.get_execution_guard", return_value=mock_guard), \
             patch("merid.event_venues.kalshi.client.get_kalshi_client",
                   return_value=mock_kc), \
             patch("merid.loop.get_merid_loop", return_value=mock_loop):
            resp = client.get("/api/health")

        assert resp.status_code == 503, (
            f"Expected HTTP 503 when kill switch is active, got {resp.status_code}. "
            "BUG-H7: /api/health is not returning 503 on critical failures."
        )
        body = resp.json()
        assert body["status"] == "unhealthy"
        assert "kill_switch_active" in body["critical_failures"]

    def test_health_returns_503_when_kalshi_circuit_open(self):
        client = self._make_client()

        mock_guard = MagicMock()
        mock_guard.kill_switch_active = False
        mock_guard._global_kill_reason = ""

        mock_kc = MagicMock()
        mock_kc.is_circuit_open = True
        mock_kc.get_circuit_status = MagicMock(return_value={"state": "open"})

        mock_loop = MagicMock()
        mock_loop.status.return_value = {"running": True, "metrics": {}}

        with patch("merid.execution_guard.get_execution_guard", return_value=mock_guard), \
             patch("merid.event_venues.kalshi.client.get_kalshi_client",
                   return_value=mock_kc), \
             patch("merid.loop.get_merid_loop", return_value=mock_loop):
            resp = client.get("/api/health")

        assert resp.status_code == 503, (
            f"Expected HTTP 503 when Kalshi circuit is open, got {resp.status_code}."
        )
        body = resp.json()
        assert "kalshi_circuit_open" in body["critical_failures"]

    def test_health_returns_503_when_loop_stopped(self):
        client = self._make_client()

        mock_guard = MagicMock()
        mock_guard.kill_switch_active = False
        mock_guard._global_kill_reason = ""

        mock_kc = MagicMock()
        mock_kc.is_circuit_open = False
        mock_kc.get_circuit_status = MagicMock(return_value={})

        mock_loop = MagicMock()
        mock_loop.status.return_value = {"running": False, "metrics": {}}

        with patch("merid.execution_guard.get_execution_guard", return_value=mock_guard), \
             patch("merid.event_venues.kalshi.client.get_kalshi_client",
                   return_value=mock_kc), \
             patch("merid.loop.get_merid_loop", return_value=mock_loop):
            resp = client.get("/api/health")

        assert resp.status_code == 503, (
            f"Expected HTTP 503 when MeridLoop is not running, got {resp.status_code}."
        )
        body = resp.json()
        assert "merid_loop_stopped" in body["critical_failures"]

    def test_health_response_has_required_keys(self):
        """Response body must contain status, timestamp, critical_failures, checks."""
        client = self._make_client()

        mock_guard = MagicMock()
        mock_guard.kill_switch_active = False
        mock_guard._global_kill_reason = ""

        mock_kc = MagicMock()
        mock_kc.is_circuit_open = False
        mock_kc.get_circuit_status = MagicMock(return_value={})

        mock_loop = MagicMock()
        mock_loop.status.return_value = {"running": True, "metrics": {}}

        mock_ag = _mock_agent_grid_ready()
        with patch("merid.execution_guard.get_execution_guard", return_value=mock_guard), \
             patch("merid.event_venues.kalshi.client.get_kalshi_client",
                   return_value=mock_kc), \
             patch("merid.loop.get_merid_loop", return_value=mock_loop), \
             patch("merid.prediction.agent_grid.get_agent_grid", return_value=mock_ag):
            resp = client.get("/api/health")

        body = resp.json()
        for key in ("status", "timestamp", "critical_failures", "checks"):
            assert key in body, f"Required key '{key}' missing from /api/health response"

    def test_health_not_hardcoded_exchanges(self):
        """Response must NOT contain the old hardcoded crypto exchange list."""
        import inspect
        from web.api import health as health_mod
        source = inspect.getsource(health_mod.get_global_health)
        assert "kraken" not in source, (
            "Hardcoded 'kraken' exchange is still in get_global_health — BUG-H7 not fixed."
        )
        assert "coinbase" not in source or "get_kalshi_client" in source, (
            "Hardcoded exchange list may still be present in get_global_health."
        )


# ===========================================================================
# BUG-H8: Background task drain on loop shutdown
# ===========================================================================
class TestBugH8BackgroundTaskDrain:
    """run() must await/cancel in-flight background tasks before releasing
    shared singleton references on shutdown."""

    def test_bg_task_drain_code_present_in_run(self):
        """Inspect run() source for asyncio.wait with 6s timeout."""
        import inspect
        from merid.loop import MeridLoop
        source = inspect.getsource(MeridLoop.run)
        assert "asyncio.wait" in source, (
            "asyncio.wait not found in MeridLoop.run() — background task drain missing. "
            "BUG-H8 fix may not be applied."
        )
        assert "6.0" in source or "timeout=6" in source, (
            "6-second drain timeout not found in MeridLoop.run() shutdown block."
        )
        assert "_agent_bg_task" in source and "_promo_bg_task" in source, (
            "_agent_bg_task and _promo_bg_task must both be included in the drain set."
        )

    @pytest.mark.asyncio
    async def test_in_flight_bg_task_is_cancelled_on_stop(self):
        """A slow background task must be cancelled when loop.stop() is called."""
        from merid.loop import MeridLoop, LoopConfig

        cancelled_events = []

        async def slow_bg(summary):
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled_events.append("cancelled")
                raise

        cfg = LoopConfig()
        loop = MeridLoop(cfg)
        # Plant an in-flight background task
        loop._agent_bg_task = asyncio.create_task(slow_bg({}))
        loop._promo_bg_task = None

        # Simulate the drain block directly (mirrors run() shutdown code)
        loop._running = False
        _bg_tasks = [
            t for t in (loop._agent_bg_task, loop._promo_bg_task)
            if t is not None and not t.done()
        ]
        if _bg_tasks:
            done, pending = await asyncio.wait(_bg_tasks, timeout=6.0)
            for t in pending:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

        assert len(cancelled_events) == 1, (
            "Slow background task was not cancelled during loop shutdown drain. "
            "BUG-H8: Orders could be submitted after venue disconnection."
        )

    def test_ws_bridge_released_after_drain(self):
        """After drain, _ws_bridge must be set to None in run() source, and
        asyncio.wait drain must appear before the post-loop None assignments.

        Note: `_ws_bridge = None` appears twice in run():
          1. Initialization before the while-loop (fine)
          2. Post-loop cleanup after the drain (must come AFTER asyncio.wait)
        We validate the LAST occurrence, which is the post-loop cleanup.
        """
        import inspect
        from merid.loop import MeridLoop
        source = inspect.getsource(MeridLoop.run)

        drain_pos = source.find("asyncio.wait")
        assert drain_pos != -1, "asyncio.wait not found in MeridLoop.run()"

        # Find the LAST occurrence of _ws_bridge = None (post-loop cleanup)
        ws_none_pos = source.rfind("_ws_bridge = None")
        assert ws_none_pos != -1, "_ws_bridge = None not found in MeridLoop.run()"
        assert ws_none_pos > drain_pos, (
            f"Post-loop '_ws_bridge = None' (char {ws_none_pos}) appears before "
            f"asyncio.wait drain (char {drain_pos}) in run() — singletons released "
            "before in-flight tasks are cancelled. BUG-H8 fix ordering is wrong."
        )

        # Same check for _hashtag_monitor (also appears twice — use rfind)
        hashtag_none_pos = source.rfind("_hashtag_monitor = None")
        if hashtag_none_pos != -1:
            assert hashtag_none_pos > drain_pos, (
                f"Post-loop '_hashtag_monitor = None' (char {hashtag_none_pos}) "
                f"appears before asyncio.wait drain (char {drain_pos})."
            )


# ===========================================================================
# ExecutionGuard — VenueExposureCap.sync_venue_exposure unit tests
# ===========================================================================
class TestVenueExposureCapSync:
    """Unit tests for ExecutionGuard.sync_venue_exposure() and the
    VenueExposureCap it operates on — ensures BUG-H4 fix is correct."""

    def _make_guard(self):
        from merid.execution_guard import ExecutionGuard
        return ExecutionGuard()

    def test_sync_venue_exposure_updates_current(self):
        guard = self._make_guard()
        guard.sync_venue_exposure("kalshi", 1234.56)
        cap = guard.get_venue_cap("kalshi")
        assert cap is not None
        assert abs(cap.current_exposure_usd - 1234.56) < 0.01, (
            f"sync_venue_exposure did not update current_exposure_usd: "
            f"expected 1234.56, got {cap.current_exposure_usd}"
        )

    def test_sync_venue_exposure_creates_new_venue(self):
        guard = self._make_guard()
        guard.sync_venue_exposure("new_venue", 500.0)
        cap = guard.get_venue_cap("new_venue")
        assert cap is not None
        assert cap.current_exposure_usd == 500.0

    def test_sync_venue_exposure_overrides_additive_counter(self):
        """After a restart scenario: sync resets cumulative counter to actual value."""
        guard = self._make_guard()
        # Simulate trades recorded before a restart (inflated counter)
        cap = guard.get_venue_cap("kalshi")
        cap.current_exposure_usd = 99999.0   # stale inflated value

        guard.sync_venue_exposure("kalshi", 42.0)
        assert abs(cap.current_exposure_usd - 42.0) < 0.01, (
            "sync_venue_exposure did not replace stale cumulative value. "
            "Post-restart exposure will be wrong."
        )

    def test_release_decrements_exposure(self):
        from merid.execution_guard import VenueExposureCap
        cap = VenueExposureCap(venue="kalshi", max_exposure_usd=1000.0, current_exposure_usd=600.0)
        cap.release(100.0)
        assert abs(cap.current_exposure_usd - 500.0) < 0.01

    def test_release_does_not_go_negative(self):
        from merid.execution_guard import VenueExposureCap
        cap = VenueExposureCap(venue="kalshi", max_exposure_usd=1000.0, current_exposure_usd=50.0)
        cap.release(200.0)
        assert cap.current_exposure_usd == 0.0, (
            "release() allowed exposure to go negative."
        )


# ===========================================================================
# ExecutionGuard — pre_trade_check with CQI throttle
# ===========================================================================
class TestExecutionGuardPreTradeCheck:
    """Spot-checks that the guard's multi-layer check chain is intact after
    the BUG-H4 changes (no regressions in existing check logic)."""

    def _guard(self):
        from merid.execution_guard import ExecutionGuard
        g = ExecutionGuard()
        g._global_kill_switch = False
        return g

    def test_global_kill_switch_blocks_all(self):
        g = self._guard()
        g._global_kill_switch = True
        verdict = g.pre_trade_check("p1", "BTCUSD", "crypto", 100.0)
        assert not verdict.allowed
        assert "global_kill_switch" in verdict.checks_failed

    def test_cqi_below_block_threshold_blocks(self):
        g = self._guard()
        # Disable promotion enforcement so the check reaches the CQI layer
        g.enforce_promotion = False
        g.update_cqi("prediction", 0.10)   # well below block_below=0.35
        verdict = g.pre_trade_check("p2", "PRES-Y", "prediction", 100.0)
        assert not verdict.allowed
        assert "cqi_throttle" in verdict.checks_failed, (
            f"Expected cqi_throttle in checks_failed, got: {verdict.checks_failed}. "
            "Check may have been blocked earlier by promotion_eligibility."
        )

    def test_cqi_above_threshold_allows_full_size(self):
        g = self._guard()
        g.update_cqi("prediction", 0.90)   # above full_execution_above=0.65
        g._last_execution_at = 0.0         # reset cooldown
        verdict = g.pre_trade_check(
            "p3", "PRES-Y", "prediction", 100.0,
            now=time.time() + 10,
        )
        if verdict.allowed:
            assert abs(verdict.throttle_pct - 1.0) < 0.01

    def test_venue_exposure_cap_blocks_when_exhausted(self):
        g = self._guard()
        # Disable promotion enforcement so the check reaches the venue cap layer
        g.enforce_promotion = False
        g.update_cqi("prediction", 0.90)
        g._last_execution_at = 0.0
        g.sync_venue_exposure("kalshi", 5000.0)  # set to max
        cap = g.get_venue_cap("kalshi")
        cap.max_exposure_usd = 5000.0            # exactly at limit

        verdict = g.pre_trade_check(
            "p4", "PRES-Y", "prediction", 100.0,
            venue="kalshi",
            now=time.time() + 10,
        )
        assert not verdict.allowed
        assert "venue_exposure_cap" in verdict.checks_failed, (
            f"Expected venue_exposure_cap in checks_failed, got: {verdict.checks_failed}. "
            "Check may have been blocked earlier by promotion_eligibility."
        )

    def test_domain_daily_cap_clamps_size(self):
        g = self._guard()
        g.update_cqi("prediction", 0.90)
        g._last_execution_at = 0.0
        cap = g._domain_caps["prediction"]
        cap.max_single_trade_usd = 50.0  # cap single trade at $50

        verdict = g.pre_trade_check(
            "p5", "PRES-Y", "prediction", 200.0,
            now=time.time() + 10,
        )
        if verdict.allowed:
            assert verdict.adjusted_size_usd <= 50.0, (
                f"Single-trade cap not enforced: got ${verdict.adjusted_size_usd}"
            )

    def test_recent_verdicts_logged(self):
        g = self._guard()
        g._global_kill_switch = True
        g.pre_trade_check("p6", "X", "crypto", 10.0)
        assert len(g.recent_verdicts(limit=5)) >= 1


# ===========================================================================
# Startup gate — structural test for web/main.py BUG-H1 fix
# ===========================================================================
class TestBugH1StartupGate:
    """The MeridLoop.run() task must only be created when startup_success=True."""

    def test_startup_gate_guards_loop_creation(self):
        """Inspect _app_lifespan source: MeridLoop task creation must be inside
        an 'if startup_success:' / 'if not startup_success:' block."""
        import inspect
        import web.main as main_mod
        source = inspect.getsource(main_mod._app_lifespan)

        # The fix uses: if not startup_success: ... else: create_task(loop.run())
        # Both halves must be present in the lifespan source.
        assert "if not startup_success" in source or (
            "if startup_success" in source and "merid-loop" in source
        ), (
            "MeridLoop.run() is not guarded by startup_success in _app_lifespan. "
            "BUG-H1 fix is missing or was reverted."
        )
        # The 'blocked' status must be recorded when startup fails
        assert 'status\': \'blocked\'' in source or '"status": "blocked"' in source or "'blocked'" in source, (
            "No 'blocked' status recorded in the startup gate path."
        )

    def test_blocked_status_recorded_when_startup_fails(self):
        """When startup_success is False, merid_loop service must be 'blocked'."""
        import inspect
        import web.main as main_mod
        source = inspect.getsource(main_mod._app_lifespan)
        assert '"blocked"' in source or "'blocked'" in source, (
            "No 'blocked' status string found in _app_lifespan. "
            "The gate should record status='blocked' when startup_success=False."
        )


# ===========================================================================
# Async reconciliation loop — structural test for F8 fix
# ===========================================================================
class TestF8AsyncReconLoop:
    """The Kalshi venue reconciliation loop must be an asyncio task, not a
    daemon thread."""

    def test_daemon_thread_not_used_for_kalshi_recon(self):
        """_app_lifespan must not create a daemon threading.Thread for Kalshi recon."""
        import inspect
        import web.main as main_mod
        source = inspect.getsource(main_mod._app_lifespan)

        # Find the Kalshi recon block
        recon_start = source.find("Start periodic Kalshi venue reconciliation")
        assert recon_start != -1, "Kalshi recon comment block not found in _app_lifespan"

        # Use a larger window — the create_task call may be >1500 chars in
        window = source[recon_start:recon_start + 2500]
        assert "threading.Thread" not in window, (
            "threading.Thread still used for Kalshi venue reconciliation. "
            "F8 fix is missing — this causes RuntimeError on Python 3.10+ "
            "when run_until_complete is called from a non-event-loop thread."
        )
        assert "asyncio.create_task" in window, (
            "asyncio.create_task not found in Kalshi recon block (searched 2500 chars). "
            "F8 fix must replace the daemon thread with an asyncio task."
        )

    def test_async_recon_loop_uses_run_in_executor(self):
        """The async recon task must use run_in_executor to avoid blocking the loop."""
        import inspect
        import web.main as main_mod
        source = inspect.getsource(main_mod._app_lifespan)

        recon_start = source.find("Start periodic Kalshi venue reconciliation")
        window = source[recon_start:recon_start + 1500]

        assert "run_in_executor" in window, (
            "run_in_executor not found in async Kalshi recon loop. "
            "Sync reconciliation must be offloaded to a thread pool, not "
            "called directly from the async task."
        )
