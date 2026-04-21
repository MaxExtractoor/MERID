# Validation Plan — Event-Loop Hardening

**Date:** 2026-04-18  
**Scope:** WebSocket robustness + pipeline action budgets  
**Deployment:** Full production (no staged rollout, no feature flags)  

---

## Overview

This validation plan covers the hardening changes from Phases 2–3:

1. **WebSocket circuit breaker** (500ms stability gate + failure tracking)
2. **Pipeline action budgets** (liquidity: 1000ms, arb_scan: 200ms lag threshold, order_groups: 1000ms + 5s start timeout)
3. **Yield points** in CPU-heavy loops
4. **Read-only profiling** (via `MERID_PROFILING` env var)

All changes are **always-on** — no feature flags, no staged rollout.

---

## Success Criteria

### Primary Metrics

| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| Event-loop lag (p95) | < 100ms | > 250ms |
| Event-loop lag (max) | < 500ms | > 1000ms |
| WS reconnect rate | < 1/min | > 3/min |
| `liquidity` duration | < 1000ms | > 1500ms |
| `arb_scan` duration | < 2000ms | > 3000ms |
| `order_groups` duration | < 1000ms | > 1500ms |

### Secondary Metrics

| Metric | Expected Behavior |
|--------|-------------------|
| `liquidity_budget_exceeded` events | Rare (< 1/hour during stress) |
| `order_groups:start_timeout` events | Zero (5s timeout prevents hangs) |
| `arb_scan_skipped_due_to_lag` events | Occasional during high load (acceptable) |
| Circuit breaker trips | Rare (< 1/day) |

---

## Validation Procedure

### Step 1: Pre-Deploy Baseline (5 minutes)

Before deploying, capture 5 minutes of logs:

```bash
# Terminal 1: Capture baseline metrics
python -c "
import asyncio
from merid.diagnostics.loop_lag import get_loop_lag_monitor

async def baseline():
    monitor = get_loop_lag_monitor()
    await asyncio.sleep(300)  # 5 min
    print('Baseline:', monitor.get_health())

asyncio.run(baseline())
" 2>&1 | tee /tmp/baseline_lag.json
```

Check for:
- `[LAG-SKIP]` patterns — note frequency
- `Slow action` warnings — note which actions, note durations
- `Kalshi WebSocket closed — 0 msgs` — note reconnect rate

### Step 2: Deploy Changes

Standard deploy — no special flags required (all changes are always-on).

### Step 3: Immediate Smoke Test (2 minutes)

After deploy, verify system starts:

```bash
# Check for startup logs
tail -f /var/log/merid/server.log | grep -E "(bridge started|CIRCUIT-BREAKER|liquidity_sweep|arb_scan)"
```

Expected within 30s:
- `KalshiWebSocketBridge started`
- `Kalshi WebSocket: subscribed orderbook_delta+ticker+trade+fill`
- No `[CIRCUIT-BREAKER] TRIPPED` during startup

### Step 4: Profiling Run (10 minutes)

Enable profiling to collect detailed metrics:

```bash
# Enable profiling for 10 minutes
MERID_PROFILING=1 python -m merid.loop 2>&1 | tee /tmp/profiling_run.log
```

Or if running under supervisor:
```bash
# Set env and restart
MERID_PROFILING=1 supervisorctl restart merid
# Collect 10 min of logs, then unset and restart
```

Look for `[PROF]` log lines — these contain structured timings.

### Step 5: Normal Operations Validation (1 hour)

Run without profiling to verify no regression:

```bash
# Ensure profiling is OFF
unset MERID_PROFILING

# Collect 1 hour of logs
tail -f /var/log/merid/server.log 2>&1 | tee /tmp/hour_run.log &
```

Monitor for:

#### 5a. Event-Loop Lag

```bash
grep "Event-loop lag" /tmp/hour_run.log | awk '{print $NF}' | sort -n | tail -20
```

**Pass:** 95th percentile < 100ms, max < 500ms

#### 5b. Action Durations

```bash
grep "liquidity_sweep timings" /tmp/hour_run.log | grep -o "total=[0-9]*ms" | cut -d= -f2 | sort -n | tail -20
```

**Pass:** 95th percentile < 1000ms

```bash
grep "arb_scan total" /tmp/hour_run.log | awk '{print $3}' | cut -d= -f2 | sort -n | tail -20
```

**Pass:** 95th percentile < 2000ms

#### 5c. Circuit Breaker State

```bash
grep "CIRCUIT-BREAKER" /tmp/hour_run.log | tail -50
```

**Pass:** No trips during normal ops, occasional trips during Kalshi maintenance acceptable

#### 5d. Budget Enforcement

```bash
grep "liquidity_budget_exceeded" /tmp/hour_run.log | wc -l
grep "order_groups:budget_exceeded" /tmp/hour_run.log | wc -l
grep "order_groups:start_timeout" /tmp/hour_run.log | wc -l
```

**Pass:** Budget exceeded events < 5/hour, start_timeout events = 0

---

## Known Expected Behaviors

These are **NOT bugs** — verify they still occur:

| Behavior | Why It Happens | Verification |
|----------|----------------|------------|
| Drawdown halt at 10% | Risk system working correctly | Look for `[RISK] decision=deny reason=Drawdown` |
| `arb_scan:skipped_due_to_lag` | Lag throttling working | Expected during high load |
| `liquidity: reduced scope to 1 market` | Lag-based scope reduction | Expected when lag > 500ms |
| WS reconnects during Kalshi maintenance | Circuit breaker should trip, then recover | `[CIRCUIT-BREAKER] TRIPPED` followed by `[CIRCUIT-BREAKER] Resetting` |

---

## Rollback Triggers

**Immediate rollback if:**

1. Event-loop lag consistently > 2000ms (worse than pre-deploy)
2. Orders are not being submitted when they should be (strategy regression)
3. Risk denials stop firing (safety system regression)
4. `[CIRCUIT-BREAKER]` in tight loop (> 1 trip per minute)

**Rollback procedure:**
```bash
git revert HEAD~3..HEAD  # Revert all 4 phases
supervisorctl restart merid
```

---

## Post-Validation Sign-Off

Checklist before declaring validation complete:

- [ ] Baseline metrics captured
- [ ] Deploy successful, no startup errors
- [ ] 10-minute profiling run completed, metrics reviewed
- [ ] 1-hour normal ops run completed, no regression
- [ ] Event-loop lag p95 < 100ms verified
- [ ] `liquidity` duration p95 < 1000ms verified
- [ ] `arb_scan` duration p95 < 2000ms verified
- [ ] `order_groups:start_timeout` = 0 verified
- [ ] Drawdown halt still functioning (check recent logs)
- [ ] No orders malformed or missing (check execution logs)

---

## Long-Term Monitoring

After validation, set up alerts for:

```yaml
alerts:
  - name: event_loop_lag_critical
    condition: lag_p95 > 250ms for 5m
    severity: warning
    
  - name: liquidity_budget_exceeded
    condition: count("liquidity_budget_exceeded") > 10 per hour
    severity: warning
    
  - name: ws_circuit_breaker_frequent
    condition: count("CIRCUIT-BREAKER TRIPPED") > 5 per hour
    severity: critical
    
  - name: order_groups_timeout
    condition: count("order_groups:start_timeout") > 0
    severity: warning
```

---

## Log Patterns Reference

### Success Patterns
```
[PROF] liquidity action=liquidity_sweep duration_ms=450.2 lag_ms=12.3 markets=3 alerts=0
[BUDGET] liquidity: reduced scope to 2 markets due to lag 320ms
[CIRCUIT-BREAKER] Approaching threshold: 8/10 failures in 60s
[CIRCUIT-BREAKER] Resetting after cooldown period
```

### Warning Patterns (Acceptable)
```
[LAG-SKIP] action=arb_scan reason=elevated_lag lag_ms=245
[BUDGET] order_groups: insufficient budget for state retrieval (150ms remaining)
```

### Critical Patterns (Investigate)
```
[BUDGET] liquidity_budget_exceeded: aborting after 1200.5ms
[CIRCUIT-BREAKER] TRIPPED — 10 failures in 60s
[PROF] order_groups action=order_groups duration_ms=2500.0 lag_ms=1800.0
```
