# MERID Runtime Startup & Shutdown Map

**Last Updated:** 2026-03-24
**Session:** Runtime Hardening Investigation

---

## Overview

MERID has two runtime entry points:
1. **main.py**: Production entrypoint (363 lines, 14 major components)
2. **web/main.py**: Web shell / router factory (3000+ lines, 40+ services)

After hardening, both use a **unified runtime state machine** (`RuntimeMode`) and centralized task supervision.

---

## Runtime State Machine

**Module:** `core/runtime_state.py`

### States

```
BOOTING → LIVE_TRADING → [OBSERVE_ONLY / DEGRADED] → SHUTTING_DOWN → OFFLINE
                              ↑
                              └── (critical failure / reconciliation issue)
```

| State | Execution Allowed? | Traffic Allowed? | Description |
|-------|-------------------|------------------|-------------|
| **BOOTING** | ❌ No | ⚠️ Limited | Startup in progress |
| **LIVE_TRADING** | ✅ Yes | ✅ Yes | All systems operational |
| **OBSERVE_ONLY** | ❌ No | ✅ Yes | Data feeds OK, execution blocked (e.g., reconciliation failure) |
| **DEGRADED** | ⚠️ Limited | ✅ Yes | Partial service failure |
| **SHUTTING_DOWN** | ❌ No | ❌ No | Shutdown initiated |
| **OFFLINE** | ❌ No | ❌ No | System offline |

### State Transitions

**Automatic:**
- System boot → `BOOTING`
- Startup complete + no critical failures → `LIVE_TRADING`
- Critical service failure → `OBSERVE_ONLY` or `DEGRADED`
- Shutdown initiated → `SHUTTING_DOWN`

**Manual:**
- Kill switch activation → `OBSERVE_ONLY`
- Reconciliation discrepancies → `OBSERVE_ONLY`
- Operator intervention → any state

---

## Startup Sequence (main.py)

**File:** `/home/runner/work/MERID/MERID/main.py`

### Phase 0: Initialization

```python
# Runtime state initialization
task_mgr = get_task_manager()  # Central task supervision
set_runtime_mode(RuntimeMode.BOOTING)  # Block execution during startup
```

### Phase 1: WebSocket Publishers (Lines 62-79)

**Purpose:** Real-time data streams for UI

| Component | Task Name | Description |
|-----------|-----------|-------------|
| Price Publisher | `price-publisher` | Real-time price updates → WebSocket clients |
| Portfolio Publisher | `portfolio-publisher` | Portfolio state → WebSocket clients |

**Dependencies:** None (starts first)

### Phase 2: Core Engine Components (Lines 84-203)

**Order matters:** Dependencies flow downstream

| Order | Component | Task Name | Dependencies | Wiring |
|-------|-----------|-----------|--------------|--------|
| 1 | Agent Orchestrator | `agent-orchestrator` | None | - |
| 2 | Consensus Engine | `consensus-engine` | Agent Orchestrator | - |
| 3 | Simulation Miner | `simulation-miner` | Consensus Engine | - |
| 4 | Audit Trail | `audit-trail` | None (parallel) | - |
| 5 | Execution Engine | `execution-engine` | Consensus | → Live Price Feed (subscription) |
| 6 | Agent Mesh (init) | `agent-mesh-init` | None | - |
| 7 | Agent Mesh (start) | `agent-mesh` | Agent Mesh init | - |
| 8 | Prediction Aggregator | `prediction-aggregator` | None (parallel) | stored in `app.state` |
| 9 | Live Price Feed | `live-price-feed` | None | subscribed by: Execution, Alerts |
| 10 | Intelligence News | `intelligence-news` | None (parallel) | - |
| 11 | API Live Data | `api-live-data` | None (parallel) | - |
| 12 | Alert Manager | `alert-manager` | None | → Live Price Feed (subscription) |
| 13 | Health Monitor | `health-monitor` | None (parallel) | - |

**Key Wiring:**
- **Execution Engine** subscribes to **Live Price Feed** for real-time pricing
- **Alert Manager** subscribes to **Live Price Feed** for price threshold alerts

### Phase 3: Kalshi Subsystems (Lines 209-244)

| Component | Task Name | Description |
|-----------|-----------|-------------|
| Kalshi WS Bridge | `kalshi-ws-bridge` | Kalshi market data → core event bus |
| OrchestratorAgentManager | - | News monitor, Twitter, Telegram agents |
| PortfolioRiskAgent | - | Cross-asset exposure monitoring |

### Phase 4: Completion (Lines 246-255)

```python
# 1. Mark startup complete
mark_startup_complete()  # Transitions to LIVE_TRADING if safe

# 2. Log task manager status
task_status = task_mgr.get_status()
logger.info(f"Task manager: {task_status['total']} tasks ({task_status['active']} active)")
```

**Startup Complete Conditions:**
- All critical services started
- No critical failures logged
- RuntimeState transitions to `LIVE_TRADING`

---

## Startup Sequence (web/main.py - _app_lifespan)

**File:** `/home/runner/work/MERID/MERID/web/main.py`

**Note:** This is the **comprehensive** startup used when running web server directly.
When `main.py` is used, it passes its own lifespan and these services are NOT started
(to avoid duplication).

### Phase 0: Legacy Crypto Publishers (Lines 1705-1711)

**Status:** SKIPPED (Kalshi-only mode)
- Price/portfolio/prediction publishers disabled
- Prevents synthetic crypto data pollution

### Phase 0.5: Kalshi Agent Grid (Lines 1713-1724)

```python
agent_grid = get_agent_grid()
await agent_grid.start()
# Starts all Kalshi trading agents (BTC15m, BTC1h, etc.)
```

### Phase 0.51: Canonical Agent Registry (Lines 1726-1733)

```python
from merid.agents.bootstrap import ensure_bootstrapped
_n_agents = ensure_bootstrapped()
# Loads agent definitions from registry
```

### Phase 0.52: Reality Auditor + Reward Engine (Lines 1735-1753)

- **RealityAuditor**: Loads persistent assertions from store
- **RewardEngine**: Initializes singleton for agent incentives

### Phase 0.53: Portfolio Rebalancer (Lines 1755-1764)

```python
_rebalancer = get_portfolio_rebalancer()
_rebalancer._bootstrap_targets()
# Loads target allocations from paper_config + agent grid
```

### Phase 0.55: MeridLoop (Lines 1766-1770)

**Status:** REMOVED (duplicate)
- Was started here AND in Phase 3
- Now only started in Phase 3 (line 2270-2280)

### Phase 0.6: Orchestrator Agents (Lines 1775-1784)

```python
orchestrator_manager = get_orchestrator_manager()
await orchestrator_manager.start_all()
# Starts: news monitor, Twitter, Telegram
```

### Phase 1: Core Systems (Lines 1786-1956)

**Validation & Fresh Start:**
1. Validate live-only mode
2. Validate production settings
3. **Fresh start mode** (if enabled):
   - Wipes consensus store
   - Resets risk counters
   - Clears equity buffer
   - Resets drift detector
   - Clears signal store
   - Truncates prediction consensus DB
   - Resets paper trading state

**Core Systems:**
- Consensus Engine (singleton check)
- Paper Trading Engine (skipped in Kalshi-only)
- Data Persistence (backup manager)
- Reflection Layer
- Brier Metrics Tracker
- Neo4j Graph Database (if available)

### Phase 3: Streaming & Background Services (Lines 1962-2463)

**60+ services started**, including:

| Service | Purpose | Critical? |
|---------|---------|-----------|
| Event Bus Bridge | core.event_bus → observability.event_stream | ✅ Yes |
| HealthMonitor | System health checks | ✅ Yes |
| AlertManager | Alert notifications | ✅ Yes |
| AuditTrail | Immutable transaction log | ✅ Yes |
| SystemOrchestrator | Inter-system coordination | ✅ Yes |
| KalshiMarketCache | Kalshi API response caching | ⚠️ High |
| **KalshiMarketCatalog** | **Backbone for all Kalshi operations** | ✅ **Critical** |
| KalshiSentimentService | Sentiment scoring | Medium |
| KalshiWebSocketBridge | Real-time Kalshi events → event bus | ✅ Critical |
| TickerCollector | WS tick accumulation | High |
| **KalshiInsightPipeline** | **Kalshi → consensus → insights** | ✅ **Critical** |
| EnhancedConsensusCoordinator | Opinion aggregation | High |
| OrchestratorAgentManager | AgentMesh + NewsMonitor | High |
| WatchdogCoordinator | Liveness checks | Medium |
| MarketMoodBus | Sentiment aggregation | Medium |
| SentimentBus | Twitter/Reddit → MarketMoodBus | Low |
| TwitterStreamHandler | Real-time tweets | Low |
| HashtagMonitor | Hashtag/news scraping | Low |
| CFGI Refresh Loop | Fear & Greed Index | Low |
| WSFeedManager | Coinbase WS → feature service | High |
| **MeridLoop** | **Swarm orchestrator (features → agents → consensus → execution)** | ✅ **Critical** |
| Agent Orchestrator | Agent lifecycle | High |
| Execution Engine | Trade execution | ✅ Critical |
| Agent Mesh | 8 autonomous agents | High |
| Consensus Engine (streaming) | Consensus rounds | ✅ Critical |
| Intelligence News | News aggregation | Medium |
| API Live Data | Live price fetching | High |

### Phase 4: Reconciliation & Readiness (Lines 2476-2550)

1. **Mark Startup Complete** (lines 2482-2487)
   ```python
   mark_startup_complete()  # Transitions to LIVE_TRADING if safe
   ```

2. **Startup Reconciliation** (lines 2489-2514)
   ```python
   if has_critical_discrepancies():
       set_runtime_mode(RuntimeMode.OBSERVE_ONLY, reason="critical_reconciliation_discrepancies")
   else:
       logger.info("✅ Execution gate CLEAR — trades can proceed")
   ```

3. **Periodic Reconciliation** (lines 2516-2540)
   - Paper trading reconciliation (300s interval)
   - Kalshi venue reconciliation (300s interval)

4. **Phase N Cleanup** (lines 2539-2549)
   - Removed duplicate KalshiInsightPipeline start

---

## Shutdown Sequence (main.py)

**File:** `/home/runner/work/MERID/MERID/main.py` (lines 259-367)

### Shutdown Order

**Principle:** Stop consumers before producers, stop services before data sources.

| Order | Component | Timeout | Notes |
|-------|-----------|---------|-------|
| 0 | **RuntimeState** | - | Transition to `SHUTTING_DOWN` (blocks execution) |
| 1 | Price Publisher | 5s | Stop WS data stream |
| 2 | Portfolio Publisher | 5s | Stop WS data stream |
| 3 | Health Monitor | 5s | Stop health checks |
| 4 | Alert Manager | 5s | Stop alert notifications |
| 5 | Prediction Aggregator | 5s | Stop prediction polling |
| 6 | Live Price Feed | - | Stop streaming (sync) |
| 7 | Agent Mesh | 10s | Stop 8 autonomous agents |
| 8 | Execution Engine | 10s | Flush pending orders, stop |
| 9 | Audit Trail | 5s | Flush audit log |
| 10 | Simulation Miner | 5s | Stop mining |
| 11 | Consensus Engine | 5s | Stop consensus rounds |
| 12 | Agent Orchestrator | - | Stop orchestration (sync) |
| 13 | OrchestratorAgentManager | 10s | Stop news/Twitter/Telegram agents |
| 14 | Kalshi WS Bridge | 5s | Close WS connections |
| 15 | Portfolio Risk Agent | 5s | Stop risk monitoring |
| 16 | **Task Manager** | 10s | Cancel remaining background tasks |

**Total Shutdown Time:** ~85 seconds (worst case, all timeouts hit)
**Expected Shutdown Time:** ~5-10 seconds (clean shutdown)

**Timeout Handling:**
- Each component stop wrapped in `shutdown_with_timeout()`
- Logs error if timeout exceeded
- Continues shutdown even if component hangs
- Task Manager force-cancels remaining tasks after 10s

---

## Shutdown Sequence (web/main.py)

**File:** `/home/runner/work/MERID/MERID/web/main.py` (lines 2575-2781)

### Shutdown Order

**Similar principle, but more services:**

| Order | Component | Purpose |
|-------|-----------|---------|
| 0 | **RuntimeState** | Transition to `SHUTTING_DOWN` |
| 1-5 | MeridLoop, KalshiInsightPipeline, MarketMoodBus, WSFeedManager, LiveFeedManager | Stop data generation |
| 6-9 | SentimentBus, TwitterStreamHandler, KalshiWebSocketBridge, KalshiSentimentService | Stop sentiment/social feeds |
| 10-13 | KalshiMarketCatalog, TickerCollector, KalshiMarketCache | Stop Kalshi infrastructure |
| 14-17 | EnhancedConsensusCoordinator, OrchestratorAgentManager, WatchdogCoordinator | Stop coordination |
| 18-21 | SystemOrchestrator, AuditTrail, AlertManager, HealthMonitor | Stop core infrastructure |
| 22-24 | Kalshi Agent Grid, Orchestrator Agents, PortfolioRebalancer | Stop trading agents |
| 25-26 | Final reconciliation, cancel background tasks | Cleanup |

**No timeouts in web/main.py shutdown** - potential hang risk (BUG-14)

---

## Health & Readiness Endpoints

### `/healthz` (Liveness Probe)

**Purpose:** Is the process alive?

**Checks:**
- Main thread alive
- Event loop running
- Startup completed

**Response:**
```json
{
  "status": "healthy" | "unhealthy",
  "timestamp": 1234567890.123,
  "main_thread_alive": true,
  "event_loop_running": true,
  "startup_completed": true,
  "uptime_seconds": 123.45
}
```

### `/readyz` (Readiness Probe) - ENHANCED

**Purpose:** Can the system accept traffic AND execute trades?

**Checks:**
1. ✅ Startup completed
2. ✅ RuntimeMode (LIVE_TRADING or DEGRADED, not BOOTING/OFFLINE)
3. ✅ ExecutionGuard kill switch (not active)
4. ✅ Reconciliation (no critical discrepancies)
5. ✅ Critical services (execution, consensus, kalshi_market_catalog, kalshi_ws_bridge)

**Response:**
```json
{
  "status": "ready" | "not_ready",
  "timestamp": 1234567890.123,
  "runtime_mode": "live_trading",
  "execution_allowed": true,
  "services": {
    "prediction_markets": "running",
    "aggregator_available": true,
    "data_fresh": true,
    "critical_services": {
      "execution": "running",
      "consensus": "running",
      "kalshi_market_catalog": "running",
      "kalshi_ws_bridge": "running"
    }
  },
  "synthetic_mode": false
}
```

**Not Ready Reasons:**
- `startup_not_complete` - Still booting
- `runtime_mode_booting` - System in BOOTING state
- `runtime_mode_observe_only` - Execution blocked (reconciliation failure)
- `execution_blocked_kill_switch` - Kill switch active
- `critical_reconciliation_issues` - Venue discrepancies
- `critical_services_failed` - One or more critical services failed

### `/startup` (Raw State)

**Purpose:** Debug view of startup state

**Response:**
```json
{
  "started_at": 1234567890.123,
  "services": {
    "consensus": {"status": "running", "started_at": 1234567890.5},
    "execution": {"status": "running", "started_at": 1234567891.2},
    ...
  },
  "background_tasks": [...]
}
```

### `/api/v1/health/startup` (Comprehensive Health)

**Purpose:** Detailed service status

**Response:**
```json
{
  "startup_completed": true,
  "started_at": 1234567890.123,
  "uptime_seconds": 123.4,
  "services": {
    "total": 40,
    "running": 38,
    "failed": 2,
    "details": {...}
  },
  "background_tasks": {
    "total": 35,
    "active": 30
  }
}
```

---

## Task Supervision

**Module:** `core/task_supervision.py`

### TaskManager

**Purpose:** Central task supervision with error tracking

**Features:**
- Task registration with names
- Automatic error logging
- Health status reporting
- Graceful shutdown with timeout

**Usage:**
```python
task_mgr = get_task_manager()

# Create supervised task
task = task_mgr.create_task(my_coroutine(), name="my-service")

# Get status
status = task_mgr.get_status()
# {"total": 10, "active": 8, "failed": 1, "cancelled": 1, "errors_by_task": {...}}

# Shutdown all tasks
await task_mgr.shutdown(timeout=10.0)
```

### supervised_task Decorator

**Purpose:** Add error handling and telemetry to background tasks

**Usage:**
```python
@supervised_task("price-feed")
async def price_feed_loop():
    while True:
        # ...
```

**Features:**
- Logs task start/stop/cancel
- Catches exceptions and sends alerts
- Integrates with AlertManager

### shutdown_with_timeout

**Purpose:** Stop components with timeout

**Usage:**
```python
await shutdown_with_timeout(
    component.stop(),
    timeout=5.0,
    component_name="price_feed"
)
```

**Features:**
- Wraps component stop in `asyncio.wait_for()`
- Logs timeout/error
- Returns True/False success

---

## Critical Bugs Fixed

See `docs/RUNTIME_HARDENING_BUGS.md` for full bug report.

**Summary of Fixes:**

| Bug ID | Issue | Fix | File(s) |
|--------|-------|-----|---------|
| BUG-01 | Unsupervised tasks in main.py | TaskManager supervision | main.py |
| BUG-04 | MeridLoop started twice | Removed duplicate start | web/main.py |
| BUG-05 | KalshiInsightPipeline started twice | Removed duplicate start | web/main.py |
| BUG-07 | No central runtime state | Created RuntimeState module | core/runtime_state.py |
| BUG-08 | Health endpoints incomplete | Enhanced /readyz checks | web/main.py |
| BUG-09 | Reconciliation not gated | Wire to RuntimeState | web/main.py |
| BUG-14 | No shutdown timeouts | Added timeout wrappers | main.py |

---

## Remaining Work

### High Priority

1. **BUG-06**: Duplicate component initialization between main.py and web/main.py
   - **Fix:** Consolidate to single lifespan or add detection
   - **Effort:** 4-6 hours

2. **BUG-02**: Tasks not named in web/main.py
   - **Fix:** Add `name=` to all `create_task()` calls
   - **Effort:** 1 hour

3. **Add shutdown timeouts to web/main.py**
   - **Fix:** Apply `shutdown_with_timeout()` wrapper
   - **Effort:** 1 hour

### Medium Priority

4. **BUG-10**: Execution engine not wired to readiness flags
5. **BUG-12**: No circuit breaker on service start failures
6. **BUG-13**: Shutdown order unclear

### Low Priority

7. **BUG-03**: Task cancellation improvements
8. **BUG-11**: ExecutionGuard not consulted everywhere
9. **BUG-15**: Task failure telemetry
10. **BUG-16**: Startup duration logging

---

## Testing Checklist

- [ ] Verify RuntimeState transitions during startup
- [ ] Test `/readyz` with kill switch active
- [ ] Test reconciliation triggering OBSERVE_ONLY mode
- [ ] Verify no duplicate tasks created
- [ ] Test shutdown with component hang
- [ ] Test shutdown with fast exit (<5s)
- [ ] Test critical service failure → OBSERVE_ONLY
- [ ] Verify TaskManager reports correct task counts
- [ ] Test startup with fresh start mode
- [ ] Verify health endpoints return correct status

---

## Deployment Notes

### Environment Variables

- `MERID_PROFILE=kalshi-only` - Enable Kalshi-only mode (suppress legacy crypto)
- `MERID_ENV=production` - Production validation
- `SIMULATION_MODE=synthetic_only` - Synthetic mode (for testing)
- `MERID_FRESH_START=true` - Wipe transient state on startup

### Monitoring

Monitor these metrics:
- RuntimeState mode transitions (log aggregation)
- Task manager active/failed counts (Prometheus)
- Health endpoint status (K8s probes)
- Reconciliation discrepancy counts (logs)
- Shutdown duration (logs)

### Alerts

Set up alerts for:
- RuntimeState transition to OBSERVE_ONLY or DEGRADED
- Critical service failures
- Reconciliation critical discrepancies
- Shutdown timeouts
- Task manager high failure rate

---

**End of Runtime Startup & Shutdown Map**
