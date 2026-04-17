---
description: MERID Backend Diagnostic Runbook - Paper Mode Event Loop Lag Investigation
---

# MERID Backend Diagnostic Runbook

**Purpose**: Start MERID in paper mode and run 30-minute gate as diagnostic, not trading readiness check. **DO NOT enable live trades** until event-loop lag is fixed.

## Pre-flight Safety

```bash
cd /opt/merid

# Safety: paper only
export MERID_TRADE_MODE=paper
export MERID_ALLOW_LIVE_TRADES=false

./ops/live_start_and_monitor.sh --live --confirm LIVE
```

## Continuous Monitoring Checklist

### 1. Health / Readiness Semantics

Confirm `/api/v1/health` returns:
- `status=healthy` with HTTP 200 only after `startup_complete=true` and `agents_ready=true`
- `degraded=true` whenever P95 event-loop lag is elevated — **treat as hard "not ready" signal even if HTTP is 200**

> Never treat "200 OK" alone as sufficient; readiness requires both green flags and acceptable lag metrics.

### 2. Event-Loop Lag and Task Pressure

Monitor lag metrics continuously:
- **Target**: P95 lag < 500ms in steady state
- **Current issue**: Profiles show 6–8s P95 (unacceptable)

Inspect diagnostics:
- `lag_profiles.json` — high-lag profile captures
- `steady_state_report_*.json` — verification results

**Current findings**:
- ~166+ active tasks
- Dominant coroutines: `KalshiTradingAgent._run_loop`, `_category_loop`, `_monitor_loop`, WebSocket transfer

### 3. Active Log Watching

**Agent logs**:
- Long `_run_loop` stretches without await points
- Heartbeats delayed by multiple seconds
- 35 Kalshi agent loops running as tight loops (not event-driven)

**Insight/pipeline logs**:
- `_category_loop` continuous processing without `await asyncio.sleep(...)`
- No visible I/O waits

**Diagnostics**:
- `_monitor_loop` lag threshold warnings
- "High-lag profile captured" notices = multi-second pauses

### 4. Investigation Posture: Upstream/Downstream

For each high-lag profile:
- **Inside** `_run_loop`, `_category_loop`, `_monitor_loop`:
  - CPU work without yielding
  - Sync functions, blocking I/O, heavy computations on event loop
- **Upstream**: What triggers long-running coroutines (signals, WS messages, timers)
- **Downstream**: Which tasks starve (heartbeats, risk checks, reconciliation, UI)

### 5. Required Fixes Before Live Consideration

**Explicit yielding**:
- Every `while True` / recurring coroutine needs guaranteed `await` per iteration
- Heavy loops: add `await asyncio.sleep(0)` for fair scheduling

**Remove/isolate blocking work**:
- Audit Kalshi WebSocket for blocking client/sync waits
- Move blocking code to separate thread/process, feed via queues
- Eliminate `time.sleep`, blocking DB drivers, sync HTTP calls

**Reduce task fan-out**:
- Limit concurrent insight/notification tasks
- Prefer small worker pool over many tiny coroutines

### 6. Stop Condition (Explicit Actions)

**If P95 > 2s sustained for 3+ consecutive samples OR `degraded=true` persists > 30 seconds:**

1. **Ensure paper mode** (if not already): `MERID_TRADE_MODE=paper`
2. **Trigger emergency halt**: POST `/api/v1/operator/emergency-halt`
3. **Activate kill switch**: POST `/api/v1/kalshi-grid/kill-switch`  
4. **Open ANOMALY entry** in `fix_history.md`:
   - Timestamp, lag profile, active task count
   - Suspected root cause (tight loop, blocking I/O, etc.)
   - Attach `lag_profiles.json` excerpt

**Do not resume** until root cause identified and fix validated in new paper gate.

---

### 7. Gate Criteria: "Acceptable" (Still Paper)

Acceptable only when all hold:
- [ ] Steady-state P95 event-loop lag < 500ms under realistic load
- [ ] `/health` remains `healthy` with `degraded=false` during normal operation
- [ ] Total active task count stable, no single coroutine dominates lag profiles

Treat "healthy but degraded" as **not acceptable** for live trading.

---

### 8. Green Light Checklist (Pre-Live Gate)

**ALL must pass for 30-minute paper gate under realistic load:**

```
✅ P95 lag < 500ms sustained for full 30 minutes
✅ degraded=false for entire gate duration  
✅ Zero high-lag profiles captured (no samples > 2s)
✅ AgentGrid reports healthy (startup_complete=true, agents_ready=true)
✅ Kalshi WS client connected with no missed heartbeats
✅ All background tasks (reconciliation, sentiment, mood) reporting healthy
```

**Only after ALL boxes checked** → may consider live gate with tight caps.

---

### 9. Absolute Safety Rule

**DO NOT** flip `MERID_ALLOW_LIVE_TRADES=true` or run live-mode gate until:
- At least one complete 30-minute paper gate with sub-threshold steady-state lag
- Clean profiling (no recurring high-lag captures)
- All known tight loops and blocking operations audited and fixed

---

## Critical Context

Multi-second event-loop lag is a **critical correctness and risk bug**, not a performance nuisance. It can delay:
- Risk checks
- Order cancellations
- State updates

These delays materially affect trading behavior. **Must be fully resolved in paper mode.**
