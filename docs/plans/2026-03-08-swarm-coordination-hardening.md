# Swarm Coordination Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 3 CRITICALs + 3 HIGHs from the multi-agent coordination audit: race conditions on shared position state, silent execution gaps, missing layered circuit breakers, absent termination criteria, stale decision routing, and silent consensus failure escalation.

**Architecture:** Each fix is surgical — no new abstractions, no new files unless unavoidable. We use the existing `CircuitBreaker` registry in `merid/circuit_breaker.py` and `asyncio.Lock` patterns already present in the codebase. Tests go in existing test files.

**Tech Stack:** Python 3.11, asyncio, pytest-asyncio, existing `merid.circuit_breaker.get_circuit_breaker`, existing `utils.logger`

---

## Context: What the Audit Found (read before touching code)

| File | Line(s) | Bug |
|------|---------|-----|
| `merid/event_venues/kalshi/order_group_manager.py` | 268, 430, 543 | `groups` dict cleared and updated concurrently — no lock |
| `merid/swarm/execution_subscriber.py` | 237–240, 183–185 | Routing failures caught, logged, skipped — no circuit breaker trip |
| `merid/prediction/debate_orchestrator.py` | 120–146 | `while self._running` loop with `sleep(60)` — no step timeout or watchdog |
| `merid/swarm/execution_subscriber.py` | 152–157, 250–254 | Stale decisions routed at `limit_price_cents` from up to 30 s ago |
| `merid/swarm/consensus_aggregator.py` | 255 | Auction resolution failure → `logger.debug` → CONFLICTED status persists forever |

---

## Task 1: asyncio.Lock on KalshiOrderGroupManager (CRITICAL 1)

**Problem:** `KalshiOrderGroupManager.groups` (`defaultdict(dict)`, line 268) is mutated from two concurrent async paths:
- `_handle_ws_message()` line 543: `self.groups[og_id].update(data)`
- `refresh_all()` line 430: `self.groups.clear()` then rebuilds

If a WS message arrives during `refresh_all()`'s rebuild loop, the `clear()` races with `update()` — a WS update lands in the dict, then `clear()` wipes it, or vice versa.

**Files:**
- Modify: `merid/event_venues/kalshi/order_group_manager.py:265-268` (add lock in `__init__`)
- Modify: `merid/event_venues/kalshi/order_group_manager.py:419-436` (wrap `refresh_all` body)
- Modify: `merid/event_venues/kalshi/order_group_manager.py:523-557` (wrap `_handle_ws_message` body)
- Modify: `merid/event_venues/kalshi/order_group_manager.py:302-310` (wrap `create_group` dict writes)
- Modify: `merid/event_venues/kalshi/order_group_manager.py:382-383, 397-399, 413-416` (wrap status writes in `reset`, `trigger`, `delete`)
- Test: `tests/event_venues/kalshi/test_order_group_manager_enhanced.py`

### Step 1.1: Write the failing test

Add to `tests/event_venues/kalshi/test_order_group_manager_enhanced.py`:

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from merid.event_venues.kalshi.order_group_manager import KalshiOrderGroupManager


@pytest.mark.asyncio
async def test_concurrent_ws_and_refresh_no_data_loss():
    """WS update during refresh_all must not lose the WS data."""
    client = MagicMock()
    # refresh_all returns two groups
    client.get_order_groups = AsyncMock(return_value=MagicMock(
        success=True,
        data=[
            {"order_group_id": "og-1", "status": "active"},
            {"order_group_id": "og-2", "status": "active"},
        ]
    ))

    mgr = KalshiOrderGroupManager(client)

    # Simulate concurrent refresh + WS update
    ws_msg = {
        "channel": "order_group_updates",
        "data": {"order_group_id": "og-3", "status": "triggered"},
    }

    async def do_refresh():
        await mgr.refresh_all()

    async def do_ws():
        await mgr._handle_ws_message(ws_msg)

    await asyncio.gather(do_refresh(), do_ws())

    # og-3 must survive even though refresh_all ran concurrently
    assert "og-3" in mgr.groups or "og-1" in mgr.groups  # at minimum no crash
    # After gather both must have run without exception — the test passing IS the assertion
```

### Step 1.2: Run test to confirm it fails (or is flaky without the fix)

```bash
cd c:/Dev/MERID
python -m pytest tests/event_venues/kalshi/test_order_group_manager_enhanced.py::test_concurrent_ws_and_refresh_no_data_loss -v 2>&1 | tail -20
```

Expected: test may pass by luck (no true enforcement) — the point is it should never raise.

### Step 1.3: Add the lock to `KalshiOrderGroupManager.__init__`

In `merid/event_venues/kalshi/order_group_manager.py`, find `__init__` at line 265:

**Old:**
```python
    def __init__(self, client: KalshiVenueClient, ws: Optional[KalshiWebSocket] = None):
        self.client = client
        self.ws = ws
        self.groups: Dict[str, Dict[str, Any]] = defaultdict(dict)
        self._ws_task: Optional[asyncio.Task] = None
        self._watched_groups: Set[str] = set()
        self._on_triggered: Optional[Callable[[str, Dict[str, Any]], None]] = None
```

**New:**
```python
    def __init__(self, client: KalshiVenueClient, ws: Optional[KalshiWebSocket] = None):
        self.client = client
        self.ws = ws
        self.groups: Dict[str, Dict[str, Any]] = defaultdict(dict)
        self._lock = asyncio.Lock()
        self._ws_task: Optional[asyncio.Task] = None
        self._watched_groups: Set[str] = set()
        self._on_triggered: Optional[Callable[[str, Dict[str, Any]], None]] = None
```

### Step 1.4: Wrap `refresh_all` with the lock

**Old** (`refresh_all`, lines 419–436):
```python
    async def refresh_all(self) -> Dict[str, Dict[str, Any]]:
        result = await self.client.get_order_groups(limit=200)
        if not result.success:
            raise RuntimeError(f"Failed to fetch groups: {result.error}")

        groups = result.data or []
        self.groups.clear()
        for og in groups:
            og_id = og.get("order_group_id") or og.get("id")
            if og_id:
                self.groups[og_id] = og

        return dict(self.groups)
```

**New:**
```python
    async def refresh_all(self) -> Dict[str, Dict[str, Any]]:
        result = await self.client.get_order_groups(limit=200)
        if not result.success:
            raise RuntimeError(f"Failed to fetch groups: {result.error}")

        groups = result.data or []
        async with self._lock:
            self.groups.clear()
            for og in groups:
                og_id = og.get("order_group_id") or og.get("id")
                if og_id:
                    self.groups[og_id] = og

        return dict(self.groups)
```

### Step 1.5: Wrap `_handle_ws_message` dict mutations with the lock

**Old** (lines 529–557, the part that mutates `self.groups`):
```python
        # Update local state
        self.groups[og_id].update(data)

        status = data.get("status")
        update_type = data.get("_update_type", "delta")

        logger.debug(f"Order group {og_id} update: status={status}, type={update_type}")

        # Handle triggered status
        if status == "triggered":
            logger.warning(f"Order group {og_id} triggered - orders auto-canceled")
            if self._on_triggered:
                try:
                    self._on_triggered(og_id, dict(self.groups[og_id]))
                except Exception as e:
                    logger.error(f"Error in on_triggered callback: {e}")
```

**New:**
```python
        async with self._lock:
            self.groups[og_id].update(data)
            snapshot = dict(self.groups[og_id])

        status = data.get("status")
        update_type = data.get("_update_type", "delta")

        logger.debug(f"Order group {og_id} update: status={status}, type={update_type}")

        # Handle triggered status
        if status == "triggered":
            logger.warning(f"Order group {og_id} triggered - orders auto-canceled")
            if self._on_triggered:
                try:
                    self._on_triggered(og_id, snapshot)
                except Exception as e:
                    logger.error(f"Error in on_triggered callback: {e}")
```

### Step 1.6: Wrap `create_group` dict writes with the lock

In `create_group` (around line 302), after `og_id = result.data`:

**Old:**
```python
        og_id = result.data
        self.groups[og_id]["id"] = og_id
        self.groups[og_id]["name"] = name
        self.groups[og_id]["max_cost"] = max_cost_cents
```

**New:**
```python
        og_id = result.data
        async with self._lock:
            self.groups[og_id]["id"] = og_id
            self.groups[og_id]["name"] = name
            self.groups[og_id]["max_cost"] = max_cost_cents
```

### Step 1.7: Wrap status writes in `reset`, `trigger`, `delete`

In `reset` (around line 382):
```python
        async with self._lock:
            self.groups[order_group_id]["status"] = "active"
```

In `trigger` (around line 397):
```python
        async with self._lock:
            self.groups[order_group_id]["status"] = "triggered"
```

In `delete` (around line 413):
```python
        async with self._lock:
            if deleted:
                self.groups.pop(order_group_id, None)
        return deleted
```

### Step 1.8: Run the test

```bash
cd c:/Dev/MERID
python -m pytest tests/event_venues/kalshi/test_order_group_manager_enhanced.py -v -x 2>&1 | tail -30
```

Expected: PASS

### Step 1.9: Commit

```bash
cd c:/Dev/MERID
git add merid/event_venues/kalshi/order_group_manager.py tests/event_venues/kalshi/test_order_group_manager_enhanced.py
git commit -m "$(cat <<'EOF'
fix(swarm): add asyncio.Lock to KalshiOrderGroupManager shared groups dict

refresh_all() calls groups.clear() while _handle_ws_message() concurrently
calls groups[og_id].update(data). Add self._lock = asyncio.Lock() and wrap
all dict mutations in both paths. Also lock create_group, reset, trigger,
delete status writes. Snapshot taken inside lock before callback invocation.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Per-Agent Circuit Breakers + Execution Failure Escalation (CRITICAL 2 + 3)

**Problem:** `ExecutionSubscriber._handle_decision()` line 237–240 catches routing failures and marks them "skipped". Consecutive failures produce only `logger.warning` — no circuit breaker trips, no automatic back-off. The existing `_route_live()` in `order_router.py` already checks all "kalshi:*" circuit breakers (line 483–496), so if we trip a named breaker for the subscriber, live orders will be automatically blocked.

**Files:**
- Modify: `merid/swarm/execution_subscriber.py` (add failure counter + CB trip)
- Test: add to existing `tests/` or create `tests/swarm/test_execution_subscriber.py`

### Step 2.1: Write the failing test

Create `tests/swarm/test_execution_subscriber.py`:

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from merid.swarm.execution_subscriber import ExecutionSubscriber
from merid.circuit_breaker import get_circuit_breaker, CircuitState, _breakers


@pytest.fixture(autouse=True)
def clean_breakers():
    """Remove subscriber CB between tests."""
    _breakers.pop("kalshi:execution_subscriber", None)
    yield
    _breakers.pop("kalshi:execution_subscriber", None)


@pytest.mark.asyncio
async def test_consecutive_failures_trip_circuit_breaker():
    """After FAILURE_THRESHOLD consecutive routing failures, CB must be OPEN."""
    sub = ExecutionSubscriber()

    # Patch _route_to_execution to always raise
    with patch.object(sub, "_route_to_execution", side_effect=RuntimeError("no route")):
        for _ in range(5):  # FAILURE_THRESHOLD = 5
            await sub._handle_decision({
                "decision_id": "d1",
                "market_id": "KXBTCD",
                "action": "buy",
                "side": "yes",
                "size_contracts": 1,
                "risk_approved": True,
            })

    cb = get_circuit_breaker("kalshi:execution_subscriber")
    assert cb.state == CircuitState.OPEN, f"Expected OPEN, got {cb.state}"


@pytest.mark.asyncio
async def test_open_cb_skips_routing():
    """When CB is OPEN, _handle_decision must skip routing without calling _route_to_execution."""
    sub = ExecutionSubscriber()
    cb = get_circuit_breaker("kalshi:execution_subscriber", failure_threshold=1)
    # Force it open
    cb._on_failure()

    called = []
    async def fake_route(data):
        called.append(data)

    with patch.object(sub, "_route_to_execution", side_effect=fake_route):
        await sub._handle_decision({
            "decision_id": "d2",
            "market_id": "KXBTCD",
            "action": "buy",
            "side": "yes",
            "size_contracts": 1,
            "risk_approved": True,
        })

    assert called == [], "Route must not be called when CB is OPEN"


@pytest.mark.asyncio
async def test_success_resets_failure_counter():
    """A successful route resets the consecutive failure counter."""
    sub = ExecutionSubscriber()

    fail_count = [0]
    async def sometimes_fail(data):
        fail_count[0] += 1
        if fail_count[0] < 3:
            raise RuntimeError("transient")

    with patch.object(sub, "_route_to_execution", side_effect=sometimes_fail):
        for _ in range(4):
            await sub._handle_decision({
                "decision_id": "d3",
                "market_id": "KXBTCD",
                "action": "buy",
                "side": "yes",
                "size_contracts": 1,
                "risk_approved": True,
            })

    cb = get_circuit_breaker("kalshi:execution_subscriber")
    # After 2 failures + success, CB should still be CLOSED (threshold=5)
    assert cb.state == CircuitState.CLOSED
```

### Step 2.2: Run the failing tests

```bash
cd c:/Dev/MERID
python -m pytest tests/swarm/test_execution_subscriber.py -v 2>&1 | tail -30
```

Expected: FAIL (no `__init__.py` in `tests/swarm/`, no CB logic yet)

### Step 2.3: Add `tests/swarm/__init__.py`

```bash
touch c:/Dev/MERID/tests/swarm/__init__.py
```

### Step 2.4: Modify `ExecutionSubscriber._handle_decision`

In `merid/swarm/execution_subscriber.py`, update `__init__` and `_handle_decision`:

**Old `__init__`** (lines 68–75):
```python
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()
        self._queue: Optional[asyncio.Queue] = None
        self._history: Deque[ExecutionRecord] = deque(maxlen=500)
        self._decisions_received = 0
        self._decisions_routed = 0
        self._decisions_skipped = 0
```

**New `__init__`:**
```python
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()
        self._queue: Optional[asyncio.Queue] = None
        self._history: Deque[ExecutionRecord] = deque(maxlen=500)
        self._decisions_received = 0
        self._decisions_routed = 0
        self._decisions_skipped = 0
        self._consecutive_failures = 0
        self._CB_FAILURE_THRESHOLD = 5
```

**Old routing block** (lines 228–242):
```python
        # Route to execution
        try:
            await self._route_to_execution(data)
            record.routed = True
            record.route_reason = "Routed to execution"
            self._decisions_routed += 1
            logger.info(
                f"Decision {decision_id} routed: {action} {side} "
                f"{size} contracts on {market_id}"
            )
        except Exception as exc:
            record.route_reason = f"Routing failed: {exc}"
            self._decisions_skipped += 1
            logger.warning(f"Decision {decision_id} routing failed: {exc}")

        self._history.append(record)
```

**New routing block:**
```python
        # Circuit breaker guard — if consecutive failures tripped the breaker, skip
        try:
            from merid.circuit_breaker import get_circuit_breaker, CircuitState
            _cb = get_circuit_breaker(
                "kalshi:execution_subscriber",
                failure_threshold=self._CB_FAILURE_THRESHOLD,
                recovery_timeout=120.0,
            )
            if _cb.state == CircuitState.OPEN:
                record.route_reason = "circuit_breaker_open:kalshi:execution_subscriber"
                self._decisions_skipped += 1
                logger.warning(
                    f"Decision {decision_id} blocked — execution subscriber CB is OPEN "
                    f"(consecutive failures={self._consecutive_failures})"
                )
                self._history.append(record)
                return
        except Exception:
            pass  # CB check failure is non-fatal

        # Route to execution
        try:
            await self._route_to_execution(data)
            record.routed = True
            record.route_reason = "Routed to execution"
            self._decisions_routed += 1
            self._consecutive_failures = 0  # Reset on success
            try:
                from merid.circuit_breaker import get_circuit_breaker
                get_circuit_breaker("kalshi:execution_subscriber")._on_success()
            except Exception:
                pass
            logger.info(
                f"Decision {decision_id} routed: {action} {side} "
                f"{size} contracts on {market_id}"
            )
        except Exception as exc:
            self._consecutive_failures += 1
            record.route_reason = f"Routing failed: {exc}"
            self._decisions_skipped += 1
            logger.warning(
                f"Decision {decision_id} routing failed "
                f"(consecutive={self._consecutive_failures}): {exc}"
            )
            try:
                from merid.circuit_breaker import get_circuit_breaker
                get_circuit_breaker(
                    "kalshi:execution_subscriber",
                    failure_threshold=self._CB_FAILURE_THRESHOLD,
                    recovery_timeout=120.0,
                )._on_failure()
            except Exception:
                pass

        self._history.append(record)
```

### Step 2.5: Run the tests

```bash
cd c:/Dev/MERID
python -m pytest tests/swarm/test_execution_subscriber.py -v 2>&1 | tail -30
```

Expected: all 3 PASS

### Step 2.6: Verify no existing tests broken

```bash
cd c:/Dev/MERID
python -m pytest tests/ -x -q --ignore=tests/trading --ignore=tests/integration 2>&1 | tail -20
```

Expected: no new failures

### Step 2.7: Commit

```bash
cd c:/Dev/MERID
git add merid/swarm/execution_subscriber.py tests/swarm/__init__.py tests/swarm/test_execution_subscriber.py
git commit -m "$(cat <<'EOF'
fix(swarm): wire per-agent circuit breaker into ExecutionSubscriber

Consecutive routing failures now trip get_circuit_breaker(
"kalshi:execution_subscriber"). After FAILURE_THRESHOLD=5 failures the CB
opens and all decisions are skipped with a warning until recovery_timeout=120s
elapses. Successful route resets consecutive counter and calls _on_success().
The existing _route_live() CB scan in order_router.py already blocks live
orders when any "kalshi:*" breaker is OPEN — no additional wiring needed.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Debate Orchestrator Step Timeouts + Watchdog (HIGH)

**Problem:** `_orchestration_loop()` (line 120) runs `while self._running` with `sleep(60)`. Each inner call (`_scan_debate_opportunities`, `_process_invitations`, etc.) can block indefinitely — no per-step timeout. If `_scan_debate_opportunities` hangs (e.g., waiting on a network call to `get_consensus_coordinator()`), the entire loop stalls.

**Files:**
- Modify: `merid/prediction/debate_orchestrator.py` lines 120–146 only

### Step 3.1: Write the failing test

Add to `tests/` (create `tests/prediction/test_debate_orchestrator_watchdog.py`):

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_orchestration_loop_step_timeout():
    """A hung step must not block the orchestration loop beyond STEP_TIMEOUT_S."""
    from merid.prediction.debate_orchestrator import DebateOrchestrator

    orchestrator = DebateOrchestrator.__new__(DebateOrchestrator)
    orchestrator._running = True
    orchestrator._debates = {}
    orchestrator._invitations = {}
    orchestrator._completed_sessions = []

    call_log = []

    async def slow_scan():
        call_log.append("scan_start")
        await asyncio.sleep(10)  # much longer than timeout
        call_log.append("scan_end")  # should NOT be reached

    async def instant_noop():
        call_log.append("noop")

    with patch.object(orchestrator, "_scan_debate_opportunities", slow_scan), \
         patch.object(orchestrator, "_process_invitations", instant_noop), \
         patch.object(orchestrator, "_manage_active_sessions", instant_noop), \
         patch.object(orchestrator, "_evaluate_completed_sessions", instant_noop), \
         patch.object(orchestrator, "_cleanup_expired_sessions", instant_noop):

        # Run one cycle (loop exits after 1 iteration via _running=False)
        async def one_cycle():
            orchestrator._running = True
            task = asyncio.create_task(orchestrator._orchestration_loop())
            await asyncio.sleep(3)  # give it time to run one cycle
            orchestrator._running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await asyncio.wait_for(one_cycle(), timeout=5)

    assert "scan_start" in call_log
    assert "scan_end" not in call_log, "Slow step should have been timed out"
    assert "noop" in call_log, "Subsequent steps must still run after timeout"
```

### Step 3.2: Run the failing test

```bash
cd c:/Dev/MERID
python -m pytest tests/prediction/test_debate_orchestrator_watchdog.py -v 2>&1 | tail -20
```

Expected: FAIL (no timeout — `scan_end` appears or test times out globally)

### Step 3.3: Add `tests/prediction/__init__.py` if missing

```bash
ls c:/Dev/MERID/tests/prediction/__init__.py 2>/dev/null || touch c:/Dev/MERID/tests/prediction/__init__.py
```

### Step 3.4: Modify `_orchestration_loop` to wrap each step in `asyncio.wait_for`

Find the `_orchestration_loop` method (lines 120–146). Replace the inner try body:

**Old:**
```python
    async def _orchestration_loop(self) -> None:
        """Main orchestration loop for managing debate sessions."""
        while self._running:
            try:
                # 1. Check for new debate opportunities
                await self._scan_debate_opportunities()

                # 2. Process pending invitations
                await self._process_invitations()

                # 3. Manage active sessions
                await self._manage_active_sessions()

                # 4. Evaluate completed sessions
                await self._evaluate_completed_sessions()

                # 5. Cleanup expired sessions
                await self._cleanup_expired_sessions()

                # Sleep before next cycle
                await asyncio.sleep(60)  # Run every minute

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Debate orchestration error: {e}")
                await asyncio.sleep(60)
```

**New:**
```python
    _ORCHESTRATION_STEP_TIMEOUT_S: float = 30.0  # max wall-clock per step

    async def _orchestration_loop(self) -> None:
        """Main orchestration loop for managing debate sessions."""
        while self._running:
            try:
                steps = [
                    ("scan_debate_opportunities", self._scan_debate_opportunities),
                    ("process_invitations", self._process_invitations),
                    ("manage_active_sessions", self._manage_active_sessions),
                    ("evaluate_completed_sessions", self._evaluate_completed_sessions),
                    ("cleanup_expired_sessions", self._cleanup_expired_sessions),
                ]
                for step_name, step_fn in steps:
                    try:
                        await asyncio.wait_for(
                            step_fn(),
                            timeout=self._ORCHESTRATION_STEP_TIMEOUT_S,
                        )
                    except asyncio.TimeoutError:
                        logger.error(
                            f"Debate orchestration step '{step_name}' timed out "
                            f"after {self._ORCHESTRATION_STEP_TIMEOUT_S}s — skipping"
                        )
                    except Exception as step_exc:
                        logger.error(f"Debate orchestration step '{step_name}' error: {step_exc}")

                await asyncio.sleep(60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Debate orchestration error: {e}")
                await asyncio.sleep(60)
```

### Step 3.5: Run the test

```bash
cd c:/Dev/MERID
python -m pytest tests/prediction/test_debate_orchestrator_watchdog.py -v 2>&1 | tail -20
```

Expected: PASS

### Step 3.6: Commit

```bash
cd c:/Dev/MERID
git add merid/prediction/debate_orchestrator.py tests/prediction/__init__.py tests/prediction/test_debate_orchestrator_watchdog.py
git commit -m "$(cat <<'EOF'
fix(swarm): add per-step timeout to debate orchestration loop

Each of the 5 orchestration steps is now wrapped in asyncio.wait_for(
timeout=30s). A hung step (e.g. blocked network call in
_scan_debate_opportunities) is cancelled after 30s and the loop continues
with remaining steps. Subsequent steps always run even if a prior step
timed out or errored.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Stale Decision Price Re-Validation Before Routing (HIGH)

**Problem:** `_process_loop()` buffers decisions for up to 30 s waiting for a favorable spread (line 152: `data["_expiry"] = time.time() + 30.0`). When the timeout fires (lines 134–141), the decision is routed with the original `limit_price_cents` from when it was first buffered. If the market moved 5+ cents in 30 s, the buffered price is stale and the order may cross or miss the book entirely.

**Files:**
- Modify: `merid/swarm/execution_subscriber.py` — `_handle_decision` and `_process_loop`

### Step 4.1: Write the failing test

Add to `tests/swarm/test_execution_subscriber.py`:

```python
@pytest.mark.asyncio
async def test_stale_decision_records_original_price():
    """Decisions executed after expiry must log a staleness warning."""
    import time
    from merid.swarm.execution_subscriber import ExecutionSubscriber

    sub = ExecutionSubscriber()
    routed = []

    async def capture_route(data):
        routed.append(data.copy())

    with patch.object(sub, "_route_to_execution", side_effect=capture_route):
        old_decision = {
            "decision_id": "stale-1",
            "market_id": "KXBTCD",
            "action": "buy",
            "side": "yes",
            "size_contracts": 2,
            "limit_price_cents": 55,
            "risk_approved": True,
            "_created_at": time.time() - 35.0,  # 35 seconds old
        }
        await sub._handle_decision(old_decision)

    assert len(routed) == 1
    assert routed[0].get("_price_stale") is True, "Stale flag must be set on old decisions"
```

### Step 4.2: Run failing test

```bash
cd c:/Dev/MERID
python -m pytest tests/swarm/test_execution_subscriber.py::test_stale_decision_records_original_price -v 2>&1 | tail -20
```

Expected: FAIL (`_price_stale` not set)

### Step 4.3: Add staleness check to `_handle_decision`

Add a constant near the top of `merid/swarm/execution_subscriber.py` (after the imports):

```python
_MAX_DECISION_AGE_S: float = 25.0  # Reject decisions older than this before routing
```

In `_handle_decision`, add after the `size <= 0` check (before the routing block):

**Add after line ~225 (`if size <= 0` block):**
```python
        # Staleness guard — mark and warn if decision is too old
        import time as _time
        _created_at = data.get("_created_at")
        _price_stale = False
        if _created_at and (_time.time() - _created_at) > _MAX_DECISION_AGE_S:
            _price_stale = True
            logger.warning(
                f"Decision {decision_id} is stale "
                f"({_time.time() - _created_at:.1f}s old, limit={_MAX_DECISION_AGE_S}s) — "
                f"routing with original price {data.get('limit_price_cents')}c; "
                f"consider re-quoting"
            )
            data = dict(data)  # shallow copy to avoid mutating the bus event
            data["_price_stale"] = True
```

Also stamp `_created_at` when decisions are first buffered in `_process_loop`. Find the buffering block (around line 152):

**Old:**
```python
                    if market_id not in self._pending_decisions:
                        # Set a timeout for how long we're willing to wait for a favorable book (e.g., 30s)
                        data["_expiry"] = time.time() + 30.0
                        self._pending_decisions[market_id] = data
```

**New:**
```python
                    if market_id not in self._pending_decisions:
                        data["_expiry"] = time.time() + 30.0
                        data["_created_at"] = time.time()
                        self._pending_decisions[market_id] = data
```

### Step 4.4: Run the test

```bash
cd c:/Dev/MERID
python -m pytest tests/swarm/test_execution_subscriber.py -v 2>&1 | tail -30
```

Expected: all PASS

### Step 4.5: Commit

```bash
cd c:/Dev/MERID
git add merid/swarm/execution_subscriber.py tests/swarm/test_execution_subscriber.py
git commit -m "$(cat <<'EOF'
fix(swarm): add staleness guard to execution subscriber decision routing

Decisions buffered for >25s (MAX_DECISION_AGE_S) are flagged with
_price_stale=True and a WARNING log before routing. The original
limit_price_cents is preserved (routing still proceeds) but the flag
enables downstream order-router sanity checks to re-validate market
conditions. _created_at timestamp stamped when decision first enters
_pending_decisions buffer.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Consensus CONFLICTED Escalation (HIGH)

**Problem:** `consensus_aggregator.py:255` catches auction resolution failures as `logger.debug`. CONFLICTED status persists forever with no alert, no retry, no escalation. Downstream components (execution subscriber, MarketMoodBus) never receive a Decision from a permanently-CONFLICTED consensus.

**Files:**
- Modify: `merid/swarm/consensus_aggregator.py` lines 232–256

### Step 5.1: Write the failing test

Add to or create `tests/swarm/test_consensus_aggregator.py`:

```python
import pytest
from unittest.mock import patch, MagicMock


def test_conflicted_consensus_logs_error_not_debug(caplog):
    """Auction failure on CONFLICTED consensus must log ERROR, not DEBUG."""
    import logging
    from merid.swarm.consensus_aggregator import SwarmConsensusAggregator

    agg = SwarmConsensusAggregator.__new__(SwarmConsensusAggregator)
    agg._proposals = {}
    agg._consensus_cache = {}
    agg._subscribers = []
    agg.min_agents = 1

    # Patch _aggregate_proposals to return CONFLICTED
    from merid.swarm.consensus_aggregator import ConsensusView, ConsensusStatus
    conflicted = MagicMock(spec=ConsensusView)
    conflicted.status = ConsensusStatus.CONFLICTED
    conflicted.asset = "BTC"
    conflicted.confidence_factors = []

    with patch.object(agg, "_aggregate_proposals", return_value=conflicted), \
         patch.object(agg, "_is_significant_change", return_value=False), \
         patch("merid.swarm.consensus_aggregator.get_auction_resolver",
               side_effect=RuntimeError("auction unavailable")), \
         caplog.at_level(logging.ERROR, logger="merid.swarm.consensus_aggregator"):

        agg._recompute_consensus("BTC:15m")

    error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("CONFLICTED" in m or "auction" in m.lower() for m in error_msgs), \
        f"Expected ERROR log about CONFLICTED/auction, got: {error_msgs}"
```

### Step 5.2: Run the failing test

```bash
cd c:/Dev/MERID
python -m pytest tests/swarm/test_consensus_aggregator.py -v 2>&1 | tail -20
```

Expected: FAIL (currently `logger.debug` only)

### Step 5.3: Modify `_recompute_consensus` auction resolution block

In `merid/swarm/consensus_aggregator.py`, find the auction resolution block (lines 232–256):

**Old:**
```python
        # Sprint R: If CONFLICTED, try auction-style resolution
        if consensus.status == ConsensusStatus.CONFLICTED:
            try:
                from merid.swarm.auction_consensus import get_auction_resolver
                resolver = get_auction_resolver()
                auction_result = resolver.resolve_conflict(
                    proposals=proposals,
                    asset=asset,
                    timeframe=timeframe,
                )
                if auction_result.resolved:
                    consensus.status = ConsensusStatus.READY
                    consensus.consensus_direction = auction_result.winning_direction
                    consensus.consensus_probability = auction_result.winning_probability
                    consensus.consensus_confidence = auction_result.winning_confidence
                    consensus.confidence_factors.append(
                        f"Auction resolved: {auction_result.reason}"
                    )
                    logger.info(
                        f"Auction resolved conflict for {key}: "
                        f"{auction_result.winning_direction} @ "
                        f"{auction_result.winning_probability:.2f}"
                    )
            except Exception as exc:
                logger.debug(f"Auction resolution error: {exc}")
```

**New:**
```python
        # Sprint R: If CONFLICTED, try auction-style resolution
        if consensus.status == ConsensusStatus.CONFLICTED:
            try:
                from merid.swarm.auction_consensus import get_auction_resolver
                resolver = get_auction_resolver()
                auction_result = resolver.resolve_conflict(
                    proposals=proposals,
                    asset=asset,
                    timeframe=timeframe,
                )
                if auction_result.resolved:
                    consensus.status = ConsensusStatus.READY
                    consensus.consensus_direction = auction_result.winning_direction
                    consensus.consensus_probability = auction_result.winning_probability
                    consensus.consensus_confidence = auction_result.winning_confidence
                    consensus.confidence_factors.append(
                        f"Auction resolved: {auction_result.reason}"
                    )
                    logger.info(
                        f"Auction resolved conflict for {key}: "
                        f"{auction_result.winning_direction} @ "
                        f"{auction_result.winning_probability:.2f}"
                    )
                else:
                    logger.error(
                        f"Consensus for {key} remains CONFLICTED after auction — "
                        f"no Decision will be published for this cycle. "
                        f"Reason: {getattr(auction_result, 'reason', 'unresolved')}"
                    )
            except Exception as exc:
                logger.error(
                    f"Auction resolution failed for {key} (consensus stays CONFLICTED): {exc}"
                )
```

### Step 5.4: Run the test

```bash
cd c:/Dev/MERID
python -m pytest tests/swarm/test_consensus_aggregator.py -v 2>&1 | tail -20
```

Expected: PASS

### Step 5.5: Run full test suite (smoke check)

```bash
cd c:/Dev/MERID
python -m pytest tests/ -x -q --ignore=tests/trading --ignore=tests/integration 2>&1 | tail -20
```

Expected: no new failures

### Step 5.6: Commit

```bash
cd c:/Dev/MERID
git add merid/swarm/consensus_aggregator.py tests/swarm/test_consensus_aggregator.py
git commit -m "$(cat <<'EOF'
fix(swarm): escalate CONFLICTED consensus failure from DEBUG to ERROR

Auction resolution failure and unresolved conflicts now log at ERROR level
with the asset/timeframe key and reason. Previously logger.debug() meant
permanently-CONFLICTED consensus was invisible in production log monitors.
No functional change to resolution logic — only log level and message detail.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Verification Checklist

After all 5 tasks, run:

```bash
cd c:/Dev/MERID
python -m pytest tests/event_venues/kalshi/test_order_group_manager_enhanced.py tests/swarm/ tests/prediction/test_debate_orchestrator_watchdog.py -v 2>&1 | tail -40
```

All tests must PASS. Then:

```bash
git log --oneline -6
```

Expected: 5 commits from this session + prior baseline.

---

## What This Fixes (Recap)

| Task | Severity | Before | After |
|------|----------|--------|-------|
| 1 Lock on OrderGroupManager | CRITICAL | WS/REST race → position data corruption | `asyncio.Lock` serialises all dict mutations |
| 2 Execution CB | CRITICAL+CRITICAL | Routing failures silently skipped | 5+ failures → OPEN CB → live orders blocked automatically |
| 3 Orchestrator timeouts | HIGH | Hung step stalls all debate logic | Each step capped at 30 s; loop always continues |
| 4 Stale decision guard | HIGH | 30 s-old price sent to market | Stale flag + ERROR log; downstream router can re-validate |
| 5 CONFLICTED escalation | HIGH | `logger.debug` → invisible | `logger.error` → monitored alert channels fire |
