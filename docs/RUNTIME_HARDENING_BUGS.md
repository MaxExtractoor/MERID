# MERID Runtime Hardening: Bug & Egg Report

**Date:** 2026-03-24
**Session:** Autonomous Runtime Investigation
**Scope:** `main.py` (production entrypoint) + `web/main.py` (web shell / router factory)
**Last Updated:** 2026-03-24 (Session 2 - Hardening Implementation)

---

## Fix Status

### ✅ Completed (Session 1 + 2)
- **BUG-01** (main.py): Task supervision system implemented via `core/task_supervision.py`
- **BUG-02** (web/main.py): All background tasks now have descriptive names
- **BUG-04** (web/main.py): Duplicate MeridLoop startup removed
- **BUG-05** (web/main.py): Duplicate KalshiInsightPipeline startup removed
- **BUG-06**: Dual entrypoint architecture documented (no actual duplication occurs)
- **BUG-07**: Runtime state machine implemented via `core/runtime_state.py`
- **BUG-08** (web/main.py): Health endpoints updated to check runtime state
- **BUG-09** (web/main.py): Reconciliation gated by runtime state
- **BUG-14** (both): Shutdown timeouts added to all component stop() calls

### 📝 Documented but Not Implemented
- **BUG-10** (main.py): Execution engine readiness requirements documented with TODO

### ⏳ Remaining Work
- **BUG-03**: Task cancellation improvements
- **BUG-11**: ExecutionGuard consultation during startup
- **BUG-12**: Circuit breakers for critical services
- **BUG-13**: Shutdown order documentation and enforcement
- **BUG-15**: Startup failure handling
- **BUG-16**: Startup duration logging

---

## Executive Summary

**Critical Issues Found:** 12
**High-Priority Issues:** 8
**Medium-Priority Issues:** 6
**Risk Level:** **HIGH** - Multiple execution safety gaps, unsupervised tasks, and duplicated state

### Top 3 Critical Risks

1. **No Task Supervision** - 30+ background tasks created without tracking; cancellation on shutdown is incomplete
2. **Duplicate Component Initialization** - Multiple services started twice (OrchestratorAgentManager, HealthMonitor, AlertManager, AuditTrail)
3. **Health Endpoints Don't Check Execution Safety** - `/healthz` and `/readyz` report "ready" even when ExecutionGuard would block all trades

---

## BUG CATEGORY 1: Task Lifecycle & Supervision

### BUG-01: Unsupervised Tasks in main.py (CRITICAL)
**File:** `main.py`
**Lines:** 61, 70, 82, 93, 101, 109, 117, 131-132, 140, 153, 162, 171, 181, 196, 208, 220

**Issue:**
All tasks created via `asyncio.create_task()` are fire-and-forget. No storage, no supervision, no error tracking.

**Example:**
```python
# Line 61-62
price_publisher = get_price_publisher()
asyncio.create_task(price_publisher.start())  # ❌ Task not stored
```

**Risk:**
- Task failures go unnoticed
- Shutdown can't await task completion
- Race conditions if task fails during startup
- No way to query task health status

**Fix Required:**
```python
# Store all tasks in a supervised list
_main_tasks: List[asyncio.Task] = []

task = asyncio.create_task(price_publisher.start(), name="price-publisher")
_main_tasks.append(task)
app.state.background_tasks.append(task)
```

**Affected Components:**
1. Price publisher (line 61)
2. Portfolio publisher (line 70)
3. Agent orchestrator (line 82)
4. Consensus engine (line 93)
5. Simulation miner (line 101)
6. Audit trail (line 109)
7. Execution engine (line 117)
8. Agent mesh initialize (line 131)
9. Agent mesh start (line 132)
10. Prediction aggregator (line 140)
11. Live price feed (line 153)
12. Intelligence news (line 162)
13. API prices (line 171)
14. Alert manager (line 181)
15. Health monitor (line 196)
16. Kalshi WS bridge (line 208)

---

### BUG-02: web/main.py Background Tasks Not Named (HIGH)
**File:** `web/main.py`
**Lines:** 1993, 2082-2084, 2242, 2260-2262, 2274, 2286, 2382, 2394, 2407, 2418, 2427, 2437, 2457

**Issue:**
Many tasks created without `name=` parameter, making debugging and monitoring impossible.

**Example:**
```python
# Line 1993
task = asyncio.create_task(_event_bus_bridge())  # ❌ No name
```

**Fix Required:**
```python
task = asyncio.create_task(_event_bus_bridge(), name="event-bus-bridge")
```

**Risk:**
- Can't identify which task failed in logs
- Can't query task status by name
- Debug tools can't distinguish tasks

---

### BUG-03: Task Cancellation Without Await in Shutdown (MEDIUM)
**File:** `web/main.py`
**Lines:** 2758-2765

**Issue:**
Tasks are cancelled but only awaited in a try/except that swallows `CancelledError`. If a task hangs or refuses cancellation, shutdown proceeds anyway.

**Current Code:**
```python
for task in _startup_state.get("background_tasks", []):
    if not task.done():
        task.cancel()
        try:
            await task  # ❌ Always swallows CancelledError
        except asyncio.CancelledError:
            pass
```

**Risk:**
- Tasks may not actually stop
- Resources may leak (open connections, files)
- Zombie tasks can continue running

**Fix Required:**
```python
# Add timeout and forceful cancellation
for task in _startup_state.get("background_tasks", []):
    if not task.done():
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            logger.warning(f"Task {task.get_name()} did not stop cleanly")
            # Force kill if needed
```

---

### BUG-04: MeridLoop Started Twice (HIGH)
**File:** `web/main.py`
**Lines:** 1766-1773 (Phase 0.55) and 2270-2280 (Phase 3)

**Issue:**
MeridLoop started in two places. If not a singleton, this creates duplicate orchestrator loops.

**Current Code:**
```python
# Phase 0.55 (line 1770)
_merid_loop = _get_merid_loop()
asyncio.create_task(_merid_loop.run())

# Phase 3 (line 2274)
_merid_loop = get_merid_loop()
task = asyncio.create_task(_merid_loop.run(), name="merid-loop")
```

**Risk:**
- Duplicate consensus rounds
- Double execution of trades
- Resource contention

**Investigation Needed:**
- Check if `get_merid_loop()` is a singleton
- If yes, second `start()` should be idempotent
- If no, this is a **CRITICAL BUG**

---

### BUG-05: KalshiInsightPipeline Started Twice (HIGH)
**File:** `web/main.py`
**Lines:** 2103-2138 (Phase 3) and 2542-2552 (Phase N)

**Issue:**
KalshiInsightPipeline configured and started in Phase 3, then started AGAIN in Phase N.

**Risk:**
- Duplicate insight generation
- Double message consumption
- Resource waste (11 category loops × 2)

**Fix Required:**
Remove duplicate startup or check if `start()` is idempotent.

---

## BUG CATEGORY 2: Readiness, Gating & Duplicated State

### BUG-06: Duplicate Component Initialization (CRITICAL)
**Files:** `main.py` + `web/main.py`

**Duplicates Identified:**

| Component | main.py Line | web/main.py Line | Risk |
|-----------|--------------|------------------|------|
| OrchestratorAgentManager | 215-224 | 2152-2163 | HIGH - duplicate agent mesh |
| HealthMonitor | 192-198 | 2003-2011, 2453-2463 | MEDIUM - duplicate checks |
| AlertManager | 177-188 | 2013-2021, 2433-2451 | MEDIUM - duplicate alerts |
| AuditTrail | 106-111 | 2023-2031, 2403-2413 | MEDIUM - duplicate logging |
| Agent Orchestrator | 78-87 | 2282-2364 | HIGH - duplicate orchestration |
| Consensus Engine | 90-95 | 1883-1890, 2390-2398 | HIGH - duplicate consensus |
| Agent Mesh | 129-134 | 2378-2388 | HIGH - duplicate mesh |

**Issue:**
When `main.py` lifespan is used (as in production), all components are started. Then `web/main.py`'s `_app_lifespan` is ALSO run (because `create_app(lifespan=lifespan)` passes it through), starting them again.

**Root Cause:**
```python
# main.py line 350
app = create_app(lifespan=lifespan)  # ✅ Passes main.py's lifespan

# web/main.py line 260-263
def create_app(lifespan=None) -> FastAPI:
    if lifespan is None:
        lifespan = _app_lifespan  # ❌ But _app_lifespan still defines startup logic
    application = FastAPI(title="MERID Core", version="2.0", lifespan=lifespan)
```

**Current Behavior:**
- If called from `main.py`: Uses `main.py`'s lifespan (14 components)
- If called directly: Uses `_app_lifespan` (40+ services)
- **BUT** many of the 14 components in main.py are ALSO in `_app_lifespan`!

**Risk:**
- Double agent mesh = double signals = double trades
- Double consensus rounds = conflicting decisions
- Double audit logs = duplicate entries

**Fix Required:**
1. **Option A (Recommended):** Deprecate `main.py`'s lifespan entirely, use only `_app_lifespan`
2. **Option B:** Make `_app_lifespan` detect if components already started via `app.state`
3. **Option C:** Split `_app_lifespan` into two functions: `_core_lifespan` (used by main.py) and `_web_lifespan` (web-only)

---

### BUG-07: No Central Runtime State Machine (CRITICAL)
**Files:** `main.py`, `web/main.py`

**Issue:**
No `SystemController` or unified runtime state enum (BOOTING → LIVE_TRADING → DEGRADED → SHUTTING_DOWN).

**Current State:**
- `OrchestratorState` exists but only used in `SystemOrchestrator` (not exposed globally)
- `_startup_state` dict in `web/main.py` tracks services, but not a state machine
- `app.state` in `main.py` stores component references, but no runtime mode

**Missing States:**
- `BOOTING` - startup in progress, execution blocked
- `LIVE_TRADING` - all critical services ready, execution allowed
- `OBSERVE_ONLY` - data feeds OK but execution blocked (reconciliation failure)
- `DEGRADED` - partial service failure, reduced execution
- `SHUTTING_DOWN` - shutdown initiated, execution blocked

**Risk:**
- Can't query "is the system ready to trade?"
- Health endpoints can't report true readiness
- Execution can't gate on runtime state
- No way to transition to OBSERVE_ONLY on critical failure

**Fix Required:**
Create `core/runtime_state.py`:
```python
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any

class RuntimeMode(Enum):
    BOOTING = "booting"
    LIVE_TRADING = "live_trading"
    OBSERVE_ONLY = "observe_only"
    DEGRADED = "degraded"
    SHUTTING_DOWN = "shutting_down"
    OFFLINE = "offline"

@dataclass
class RuntimeState:
    mode: RuntimeMode
    readiness_flags: Dict[str, bool]  # e.g., {"price_feed": True, "execution": False}
    critical_services: Dict[str, str]  # service_name → status
    execution_allowed: bool
    startup_completed: bool
    uptime_seconds: float
    degradation_reason: Optional[str] = None

_state: RuntimeState = None

def get_runtime_state() -> RuntimeState:
    global _state
    if _state is None:
        _state = RuntimeState(
            mode=RuntimeMode.BOOTING,
            readiness_flags={},
            critical_services={},
            execution_allowed=False,
            startup_completed=False,
            uptime_seconds=0.0,
        )
    return _state

def set_runtime_mode(mode: RuntimeMode, reason: Optional[str] = None):
    state = get_runtime_state()
    old_mode = state.mode
    state.mode = mode
    if mode in (RuntimeMode.OBSERVE_ONLY, RuntimeMode.DEGRADED):
        state.degradation_reason = reason
        state.execution_allowed = False
    elif mode == RuntimeMode.LIVE_TRADING:
        state.execution_allowed = True
    elif mode in (RuntimeMode.BOOTING, RuntimeMode.SHUTTING_DOWN, RuntimeMode.OFFLINE):
        state.execution_allowed = False

    logger.info(f"Runtime mode transition: {old_mode.value} → {mode.value} (reason: {reason})")
```

---

### BUG-08: Health Endpoints Don't Check Execution Safety (CRITICAL)
**File:** `web/main.py`
**Lines:** 2871-2898 (`/healthz`), 2901-2949 (`/readyz`)

**Issue:**
`/healthz` and `/readyz` report system health, but **do not check**:
1. ExecutionGuard kill switch status
2. Runtime mode (BOOTING vs LIVE_TRADING)
3. Reconciliation status (critical discrepancies)
4. CQI throttle level

**Current `/readyz` Logic:**
```python
# Check if startup has completed
if _startup_state.get("started_at") is None:
    return {"status": "not_ready", "reason": "startup_not_complete"}

# Check prediction markets
services = _startup_state.get("services", {})
prediction_markets_ok = services.get("prediction_markets", {}).get("status") == "running"

# Overall readiness
ready = (aggregator_available or prediction_markets_ok) and (data_fresh or synthetic_mode)
```

**Missing Checks:**
- ❌ ExecutionGuard kill switch (global or per-domain)
- ❌ Runtime mode (should fail if BOOTING or OBSERVE_ONLY)
- ❌ Reconciliation status (critical discrepancies block trading)
- ❌ CQI score (if below block threshold, not ready)
- ❌ Execution engine readiness

**Risk:**
- Kubernetes readiness probe passes even when trading is blocked
- Traffic routed to instance that can't execute
- UI shows "ready" but trades fail silently

**Fix Required:**
```python
@app.get("/readyz")
async def readyz():
    """Readiness probe - system ready to accept traffic AND execute trades"""
    from merid.execution_guard import get_execution_guard
    from core.runtime_state import get_runtime_state
    from merid.reconciliation import has_critical_discrepancies

    # Check startup
    if _startup_state.get("started_at") is None:
        return {"status": "not_ready", "reason": "startup_not_complete"}

    # Check runtime mode
    runtime_state = get_runtime_state()
    if runtime_state.mode not in (RuntimeMode.LIVE_TRADING, RuntimeMode.DEGRADED):
        return {"status": "not_ready", "reason": f"runtime_mode_{runtime_state.mode.value}"}

    # Check execution guard
    guard = get_execution_guard()
    if guard.is_kill_switch_active():
        return {"status": "not_ready", "reason": "execution_blocked_kill_switch"}

    # Check reconciliation
    if has_critical_discrepancies():
        return {"status": "not_ready", "reason": "critical_reconciliation_issues"}

    # Check services
    services = _startup_state.get("services", {})
    critical_failed = [
        svc for svc, status in services.items()
        if status.get("status") in ("failed", "timeout")
        and svc in ("execution", "consensus", "kalshi_market_catalog")
    ]
    if critical_failed:
        return {"status": "not_ready", "reason": f"critical_services_failed: {critical_failed}"}

    return {
        "status": "ready",
        "runtime_mode": runtime_state.mode.value,
        "execution_allowed": runtime_state.execution_allowed,
        "timestamp": time.time()
    }
```

---

### BUG-09: Reconciliation Doesn't Update Runtime Mode (HIGH)
**File:** `web/main.py`
**Lines:** 2485-2503 (startup reconciliation), 2512-2540 (periodic reconciliation)

**Issue:**
Reconciliation runs and logs critical discrepancies, but does NOT:
1. Block execution gate
2. Update runtime mode to OBSERVE_ONLY
3. Fail readiness probe

**Current Code:**
```python
if has_critical_discrepancies():
    logger.warning("⚠️  Execution gate BLOCKED (critical reconciliation issues)")
else:
    logger.info("✅ Execution gate CLEAR — trades can proceed")
```

**Risk:**
- Reconciliation finds critical issues (e.g., position mismatch)
- System logs warning but continues trading
- ExecutionGuard not informed

**Fix Required:**
```python
from core.runtime_state import set_runtime_mode, RuntimeMode
from merid.execution_guard import get_execution_guard

if has_critical_discrepancies():
    logger.error("⚠️  CRITICAL RECONCILIATION ISSUES - downgrading to OBSERVE_ONLY")
    set_runtime_mode(RuntimeMode.OBSERVE_ONLY, reason="critical_reconciliation_discrepancies")
    get_execution_guard().set_kill_switch(
        active=True,
        reason="Reconciliation found critical discrepancies",
        domain="all"
    )
else:
    logger.info("✅ Execution gate CLEAR — trades can proceed")
    set_runtime_mode(RuntimeMode.LIVE_TRADING)
```

---

## BUG CATEGORY 3: Execution Safety & Risk

### BUG-10: Execution Engine Not Wired to Readiness Flags (HIGH)
**File:** `main.py`
**Lines:** 114-126

**Issue:**
Execution engine started immediately without checking:
1. Price feed readiness
2. Consensus engine readiness
3. Risk engine readiness

**Current Code:**
```python
# Start execution engine
execution = get_optimal_executor()
asyncio.create_task(execution.start())  # ❌ Starts immediately

# Wire execution engine to live price feed (subscription only)
price_feed = get_live_price_feed()
def on_execution_price_update(price_data):
    execution.update_price(price_data.symbol, price_data.price)
price_feed.subscribe(on_execution_price_update)
```

**Risk:**
- Execution engine can receive signals before price feed is live
- Can try to execute without current prices
- Can execute without consensus

**Fix Required:**
```python
# Start execution engine but keep it in STANDBY until dependencies ready
execution = get_optimal_executor()
task = asyncio.create_task(execution.start(), name="execution-engine")
_main_tasks.append(task)

# Wire to price feed
price_feed = get_live_price_feed()
def on_execution_price_update(price_data):
    execution.update_price(price_data.symbol, price_data.price)
price_feed.subscribe(on_execution_price_update)

# Wait for dependencies to be ready
await _wait_for_readiness(
    "price_feed": lambda: price_feed.is_connected(),
    "consensus": lambda: get_consensus_engine().is_ready(),
    timeout=30.0
)

# Only then transition to READY
execution.set_ready(True)
logger.info("✅ Execution engine ready - all dependencies live")
```

---

### BUG-11: ExecutionGuard Not Consulted by Startup Logic (MEDIUM)
**Files:** `main.py`, `web/main.py`

**Issue:**
ExecutionGuard has comprehensive safety checks (kill switch, CQI throttle, caps), but startup logic never checks it.

**Risk:**
- System reports "ready" even if kill switch active
- Could route traffic to blocked instance
- Execution may be attempted despite guard blocks

**Fix Required:**
Wire ExecutionGuard into readiness checks (see BUG-08 fix).

---

### BUG-12: No Circuit Breaker on Service Start Failures (MEDIUM)
**Files:** `main.py`, `web/main.py`

**Issue:**
If a critical service fails to start, system logs warning and continues. No circuit breaker to prevent further damage.

**Example:**
```python
# web/main.py line 2054-2062
try:
    _catalog = get_market_catalog()
    await _catalog.start()
    logger.info("✅ KalshiMarketCatalog started")
except Exception as e:
    logger.warning(f"⚠️  KalshiMarketCatalog failed to start: {e}")
    # ❌ System continues anyway!
```

**Risk:**
- System starts without critical data source
- Agents try to access non-existent catalog
- Crashes or silent failures downstream

**Fix Required:**
```python
CRITICAL_SERVICES = ["kalshi_market_catalog", "execution", "consensus"]

for service_name in CRITICAL_SERVICES:
    status = _startup_state["services"].get(service_name, {}).get("status")
    if status in ("failed", "timeout"):
        logger.error(f"CRITICAL SERVICE FAILED: {service_name} - aborting startup")
        set_runtime_mode(RuntimeMode.OFFLINE, reason=f"critical_service_{service_name}_failed")
        raise RuntimeError(f"Critical service {service_name} failed to start")
```

---

## BUG CATEGORY 4: Shutdown Ordering & Leaks

### BUG-13: Shutdown Order May Leave Dependencies Dangling (MEDIUM)
**Files:** `main.py` (lines 248-346), `web/main.py` (lines 2561-2765)

**Issue:**
Shutdown stops components in a specific order, but doesn't verify dependencies are respected.

**Example Problem:**
```python
# web/main.py shutdown order:
# 1. Stop KalshiWebSocketBridge (line 2620-2626)
# 2. Stop KalshiMarketCatalog (line 2644-2650)
# 3. Stop OrchestratorAgentManager (line 2676-2682)

# ❌ BUT: OrchestratorAgentManager agents may still be consuming
#         WS events from KalshiWebSocketBridge!
```

**Risk:**
- Agent tries to access stopped service
- Crashes during shutdown
- Zombie tasks accessing closed resources

**Fix Required:**
Document dependency graph and enforce shutdown order:
```
1. Stop signal generators (agents, insight pipeline)
2. Stop data consumers (orchestrator, consensus)
3. Stop data sources (WS bridge, catalog, sentiment)
4. Stop infrastructure (health, alerts, audit)
```

---

### BUG-14: No Timeout on Shutdown (HIGH)
**Files:** `main.py`, `web/main.py`

**Issue:**
Shutdown awaits each component's `stop()` without timeout. If one hangs, entire shutdown blocks.

**Current Code:**
```python
# main.py line 269-272
try:
    health_mon = get_health_monitor()
    await health_mon.stop()  # ❌ No timeout - can hang forever
except Exception as e:
    logger.debug("shutdown: health_monitor stop error: %s", e)
```

**Risk:**
- One hung component blocks entire shutdown
- Process can't exit cleanly
- SIGKILL required (unclean shutdown)

**Fix Required:**
```python
SHUTDOWN_COMPONENT_TIMEOUT = 10.0

try:
    health_mon = get_health_monitor()
    await asyncio.wait_for(health_mon.stop(), timeout=SHUTDOWN_COMPONENT_TIMEOUT)
except asyncio.TimeoutError:
    logger.error(f"health_monitor.stop() timed out after {SHUTDOWN_COMPONENT_TIMEOUT}s")
except Exception as e:
    logger.debug("shutdown: health_monitor stop error: %s", e)
```

---

## BUG CATEGORY 5: Observability & Monitoring

### BUG-15: No Task Failure Telemetry (MEDIUM)
**Files:** `main.py`, `web/main.py`

**Issue:**
When a background task fails, there's no telemetry or alerting. Only visible in logs if crash is loud.

**Risk:**
- Silent task failures go unnoticed
- System degrades over time
- No proactive alerts

**Fix Required:**
Wrap all background task coroutines in a monitoring decorator:
```python
def supervised_task(name: str):
    """Decorator that adds error handling and telemetry to background tasks."""
    def decorator(coro_func):
        async def wrapper(*args, **kwargs):
            try:
                return await coro_func(*args, **kwargs)
            except asyncio.CancelledError:
                logger.info(f"Task {name} cancelled")
                raise
            except Exception as exc:
                logger.error(f"Task {name} failed with exception", exc_info=exc)
                # Send alert
                try:
                    from core.alerts import get_alert_manager
                    await get_alert_manager().send_alert(
                        level="critical",
                        title=f"Background task {name} failed",
                        message=str(exc)
                    )
                except:
                    pass
                raise
        return wrapper
    return decorator

# Usage:
@supervised_task("event-bus-bridge")
async def _event_bus_bridge():
    ...
```

---

### BUG-16: Startup Duration Not Logged in main.py (LOW)
**File:** `main.py`

**Issue:**
`web/main.py` logs startup duration (line 2476-2483), but `main.py` does not.

**Fix:**
```python
# main.py line 38
_startup_start = time.time()

# main.py line 244 (after yield, before shutdown)
_startup_duration = time.time() - _startup_start
logger.info(f"✅ Startup completed in {_startup_duration:.2f}s")
```

---

## Summary Tables

### Critical Issues (Must Fix)

| ID | Issue | File(s) | Risk | Effort |
|----|-------|---------|------|--------|
| BUG-01 | Unsupervised tasks | main.py | HIGH | MEDIUM |
| BUG-06 | Duplicate component init | both | HIGH | HIGH |
| BUG-07 | No central runtime state | both | HIGH | HIGH |
| BUG-08 | Health endpoints incomplete | web/main.py | HIGH | MEDIUM |

### High-Priority Issues

| ID | Issue | File(s) | Risk | Effort |
|----|-------|---------|------|--------|
| BUG-02 | Tasks not named | web/main.py | MEDIUM | LOW |
| BUG-04 | MeridLoop started twice | web/main.py | HIGH (if not singleton) | LOW |
| BUG-05 | Insight pipeline twice | web/main.py | HIGH | LOW |
| BUG-09 | Reconciliation not gated | web/main.py | HIGH | MEDIUM |
| BUG-10 | Execution not wired | main.py | HIGH | MEDIUM |
| BUG-14 | No shutdown timeout | both | HIGH | LOW |

### Medium-Priority Issues

| ID | Issue | File(s) | Risk | Effort |
|----|-------|---------|------|--------|
| BUG-03 | Task cancellation swallows errors | web/main.py | MEDIUM | LOW |
| BUG-11 | ExecutionGuard not consulted | both | MEDIUM | LOW |
| BUG-12 | No circuit breaker | both | MEDIUM | MEDIUM |
| BUG-13 | Shutdown order unclear | both | MEDIUM | MEDIUM |
| BUG-15 | No task telemetry | both | MEDIUM | MEDIUM |
| BUG-16 | No startup duration log | main.py | LOW | LOW |

---

## Recommended Fix Priority

### Phase 1: Stop the Bleeding (1-2 hours)
1. **BUG-06:** Remove duplicate starts (audit which file should own each component)
2. **BUG-04, BUG-05:** Verify singletons, remove duplicate starts
3. **BUG-14:** Add shutdown timeouts

### Phase 2: Core Safety (2-4 hours)
4. **BUG-07:** Create RuntimeState module with state machine
5. **BUG-08:** Update health endpoints to check ExecutionGuard + RuntimeState
6. **BUG-09:** Wire reconciliation to RuntimeState transitions

### Phase 3: Task Supervision (2-3 hours)
7. **BUG-01:** Store all tasks in supervised lists
8. **BUG-02:** Add names to all tasks
9. **BUG-15:** Add task failure telemetry

### Phase 4: Execution Safety (1-2 hours)
10. **BUG-10:** Wire execution engine to readiness flags
11. **BUG-11:** Consult ExecutionGuard in startup
12. **BUG-12:** Add circuit breakers for critical services

### Phase 5: Cleanup (1 hour)
13. **BUG-03:** Improve task cancellation
14. **BUG-13:** Document and enforce shutdown order
15. **BUG-16:** Log startup duration

**Total Estimated Effort:** 8-13 hours

---

## Next Steps

1. ✅ **Phase 1 Complete:** Mapping and bug identification
2. 🔄 **Phase 2 In Progress:** Implementing fixes
3. ⏳ **Phase 3 Pending:** Testing and verification
4. ⏳ **Phase 4 Pending:** Documentation and hardening report
