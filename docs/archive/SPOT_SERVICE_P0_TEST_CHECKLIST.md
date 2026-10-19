# Spot Service P0 Test Checklist

**Purpose:** Validate P0 spot service refactor changes in live 15m stack before proceeding to P1 tasks.

**Date:** 2026-06-08
**Context:** After implementing centralized SLA config, SpotError, and caller consistency updates.

---

## Test 1: Unified Spot Behavior Per Asset

### Objective
Verify `UnifiedSpotService.get()` returns `SpotPrice | SpotError` with proper age and reason for each asset.

### Expected Behavior

**For BTC, ETH, XRP, DOGE (5s SLA):**
- Freshness ≤ 5s → Returns `SpotPrice` with age in seconds
- Freshness > 5s → Returns `SpotError(reason="stale", age_s=X.X, message="...")`

**For SOL (10s SLA):**
- Freshness ≤ 10s → Returns `SpotPrice` with age in seconds
- Freshness > 10s → Returns `SpotError(reason="stale", age_s=X.X, message="...")`

### Log Patterns to Grep

```bash
# Check for SpotPrice returns (fresh data)
grep "UNIFIED-SPOT.*Returning spot price" logs/merid.log

# Check for SpotError returns (degraded data)
grep "UNIFIED-SPOT.*Stale spot price" logs/merid.log

# Check for degradation/recovery events
grep "SPOT-DEGRADED-ACTION" logs/merid.log
grep "SPOT-RECOVERED-ACTION" logs/merid.log

# Check freshness logging
grep "SPOT-HEALTH-FRESHNESS" logs/merid.log
```

### Pass Criteria
- ✅ All 5 assets (BTC, ETH, SOL, XRP, DOGE) show `SPOT-HEALTH-FRESHNESS` logs with `freshness_s` values
- ✅ When fresh, logs show "Returning spot price for {asset}: price=X, age=X.Xs"
- ✅ When degraded, logs show "Stale spot price for {asset} (age=X.Xs > X.Xs threshold)"
- ✅ SOL uses 10s threshold, others use 5s threshold
- ✅ Degraded assets trigger `SPOT-DEGRADED-ACTION` log with "suppressing {asset} trading"
- ✅ Recovered assets trigger `SPOT-RECOVERED-ACTION` log with "resuming {asset} trading"

### How to Simulate Degradation
To test SpotError behavior:
1. Stop the spot service fetch loop (comment out or pause)
2. Wait for freshness to exceed SLA (5s for majors, 10s for SOL)
3. Observe SpotError logs and trading suppression

---

## Test 2: Caller Consistency

### Objective
Verify all callers use `service.get()` API instead of direct `_cache` access.

### Files to Check
- `merid/loop_15m.py`
- `merid/prediction/agent_grid_15m.py`
- `merid/prediction/candidate_optimizer.py`
- `merid/event_venues/kalshi/health_snapshot.py`

### Log Patterns to Grep

```bash
# Check for SpotError handling in loop_15m
grep "15M-LOOP.*Spot degraded" logs/merid.log

# Check for SpotError handling in agent_grid
grep "SIGNAL-GATE.*spot_error" logs/merid.log

# Check for SpotError handling in E2E watchdog
grep "E2E-ASSET-COVERAGE.*spot_error" logs/merid.log

# Verify no direct _cache access remains (should return nothing)
grep "spot_service\._cache" logs/merid.log
```

### Pass Criteria
- ✅ `grep "spot_service\._cache"` returns **zero** results (no direct cache access)
- ✅ Loop 15m logs show "Spot degraded for {asset}: reason={reason}" when degraded
- ✅ Agent grid logs show "spot_error reason={reason} message={message}" when degraded
- ✅ E2E watchdog logs show "{asset} spot_error reason={reason} message={message}" when degraded
- ✅ All spot decisions use the same `SpotPrice | SpotError` path

### Code Verification
Run this grep to verify no remaining direct cache access:

```bash
grep -r "spot_service\._cache" merid/ --include="*.py"
```

**Expected:** Only results in `unified_spot_service.py` itself (internal use), not in callers.

---

## Test 3: WS Bridge DEGRADED Mode

### Objective
Verify `ws_forwarder_healthy` flag is surfaced and triggers DEGRADED mode (not HALT).

### Expected Behavior

**WS Healthy:**
- `ws_forwarder_healthy=true`
- System runs in NORMAL/DEGRADED based on asset readiness
- No WS-related degradation

**WS Outage (simulated or actual):**
- `ws_forwarder_healthy=false`
- `ws_stalled=true`
- System switches to DEGRADED mode (not HALT)
- Logs explicitly state reason: "ws_unhealthy: stalled=true"
- Trading continues but with tighter MD staleness thresholds

### Log Patterns to Grep

```bash
# Check WS health in health snapshot
grep "ws_healthy" logs/merid.log

# Check WS stall detection
grep "WS-FORWARD-HEALTH" logs/merid.log

# Check DEGRADED mode triggered by WS
grep "ws_unhealthy" logs/merid.log

# Check execution mode changes
grep "execution_mode.*DEGRADED" logs/merid.log
```

### Pass Criteria
- ✅ Health snapshot includes `ws_healthy`, `ws_stalled`, `ws_events_per_sec`, `ws_time_since_last_event`
- ✅ When WS healthy: `ws_healthy=true`, no "ws_unhealthy" reason in snapshot
- ✅ When WS stalled: `ws_healthy=false`, `ws_stalled=true`, reason "ws_unhealthy: stalled=true"
- ✅ System status changes to DEGRADED (not UNHEALTHY/HALT) when WS unhealthy
- ✅ Trading continues in DEGRADED mode (fail-open approach)

### How to Simulate WS Outage
To test WS degradation:
1. Stop the WS bridge or wait for natural stall (>30s without events)
2. Observe `WS-FORWARD-HEALTH` logs showing "STALLED"
3. Verify health snapshot shows `ws_healthy=false`
4. Verify system status = DEGRADED (not HALT)

---

## Test 4: End-to-End Sanity

### Objective
Verify no generic "spot is broken" errors; all failures have structured SpotError with reason.

### Log Patterns to Grep

```bash
# Check for generic spot errors (should not exist)
grep -i "spot is broken" logs/merid.log

# Check for structured SpotError logs
grep "spot_error reason=" logs/merid.log

# Check for spot availability with reasons
grep "spot_unavailable" logs/merid.log

# Check for spot degradation with reasons
grep "spot_stale" logs/merid.log
```

### Pass Criteria
- ✅ `grep -i "spot is broken"` returns **zero** results
- ✅ All spot failures include structured error reason: `reason={timeout|stale|no_data|rate_limited|no_provider}`
- ✅ SpotError logs include `age_s` when reason is "stale"
- ✅ SpotError logs include `message` with human-readable explanation
- ✅ No components use different spot ages/thresholds for the same asset

### Consistency Check
Verify all components use the same SLA thresholds:

```bash
# Check for hard-coded thresholds (should be minimal/none)
grep -r "freshness.*5\|freshness.*10" merid/ --include="*.py" | grep -v "spot_sla_config"
```

**Expected:** Only results in `spot_sla_config.py` (centralized config), not scattered across codebase.

---

## Quick Validation Script

Run this script to quickly validate P0 changes:

```bash
#!/bin/bash
echo "=== P0 Spot Service Validation ==="
echo ""

echo "1. Checking for direct _cache access in callers..."
CACHE_ACCESS=$(grep -r "spot_service\._cache" merid/ --include="*.py" | grep -v "unified_spot_service.py")
if [ -z "$CACHE_ACCESS" ]; then
    echo "✅ PASS: No direct _cache access in callers"
else
    echo "❌ FAIL: Found direct _cache access:"
    echo "$CACHE_ACCESS"
fi
echo ""

echo "2. Checking for generic 'spot is broken' errors..."
GENERIC_ERRORS=$(grep -i "spot is broken" logs/merid.log)
if [ -z "$GENERIC_ERRORS" ]; then
    echo "✅ PASS: No generic 'spot is broken' errors"
else
    echo "❌ FAIL: Found generic errors:"
    echo "$GENERIC_ERRORS"
fi
echo ""

echo "3. Checking for SpotError logs with reasons..."
SPOT_ERRORS=$(grep "spot_error reason=" logs/merid.log | head -5)
if [ -n "$SPOT_ERRORS" ]; then
    echo "✅ PASS: Found SpotError logs with reasons:"
    echo "$SPOT_ERRORS"
else
    echo "⚠️  WARN: No SpotError logs found (may be normal if all fresh)"
fi
echo ""

echo "4. Checking for WS health logs..."
WS_HEALTH=$(grep "ws_healthy" logs/merid.log | head -3)
if [ -n "$WS_HEALTH" ]; then
    echo "✅ PASS: Found WS health logs:"
    echo "$WS_HEALTH"
else
    echo "⚠️  WARN: No WS health logs found"
fi
echo ""

echo "=== Validation Complete ==="
```

---

## Summary Checklist

- [ ] **Test 1:** Unified spot behavior per asset (SpotPrice/SpotError with age and reason)
- [ ] **Test 2:** Caller consistency (no direct _cache access, all use service.get())
- [ ] **Test 3:** WS bridge DEGRADED mode (ws_forwarder_healthy flag, not HALT)
- [ ] **Test 4:** End-to-end sanity (no generic 'spot is broken', structured errors)

**All tests must pass before proceeding to P1 tasks.**

---

## Next Steps After P0 Validation

Once all P0 tests pass:

1. **Unit tests for spot service** (P1)
   - Cover fresh vs stale vs degraded per SLA
   - SOL edge cases (longer timeout)
   - Structured error reasons

2. **Rename "stuck" → "lagging"** (P1)
   - Update `market_catalog` and log messages
   - Keep behavior same, improve naming

3. **Align agent grid with catalog semantics** (P1)
   - Explicit in code/logs: `catalog_lagging` + MD fresh → allowed
   - `no_active_tickers` or `lagging` + MD stale → block

4. **Add tests for catalog_lagging vs MD stale** (P1)
   - Simulate no ticker advancement + fresh MD → non-blocking
   - Simulate no ticker advancement + stale MD → blocking
