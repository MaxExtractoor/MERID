# Kalshi Idempotency Hardening — Go-Live Runbook

**Version:** 1.0  
**Date:** 2026-04-12  
**Status:** STAGING REQUIRED BEFORE LIVE  

---

## Pre-Flight Checklist

### 1. Environment Verification

```powershell
# Verify production environment variables
$env:MERID_ENV  # Should be "production"
$env:KALSHI_USE_DEMO  # Should be "false" for live
$env:MERID_ERROR_THRESHOLD_KILL_ENABLED  # Should be "true" for production

# Verify code compiled successfully
py -m py_compile merid/event_venues/kalshi/order_router.py
py -m py_compile merid/event_venues/kalshi/client.py
py -m py_compile merid/event_venues/kalshi/position_sanity_checker.py
py -m py_compile merid/risk/kill_switches.py
py -m py_compile merid/prediction/kalshi_tools.py
```

---

## Phase 1: Staging / Sandbox Run (REQUIRED)

### Duration
Minimum: 1 full trading session (4+ hours)  
Target: Exercise at least 20 order placements with various scenarios

### Scenarios to Exercise

| # | Scenario | Expected Log Pattern | Verification |
|---|----------|---------------------|--------------|
| 1 | Normal order placement | `[KALSHI_ORDER_INTENT]` → `[KALSHI_ORDER_RESULT] status=filled_live` | Position matches intended |
| 2 | Network timeout + retry | `timeout, retrying in X.XXs` → `KALSHI_DUPLICATE_SUCCESS` | No duplicate position |
| 3 | Rapid duplicate intent (within 60s) | `Pre-trade gate blocked: duplicate:SUBMITTED` | Order blocked locally |
| 4 | Restart during in-flight order | Same `client_order_id` on restart, lookup success | Order reconciled, no resend |
| 5 | Partial fill | `fill_reconcile | partial=true` | Unfilled portion released from exposure |
| 6 | Stop-loss trigger | `[STRATEGY_HALT]` on sanity violation (if testable) | Strategy halted, alerts fired |

### Staging Commands

```powershell
# Start MERID in staging mode
$env:MERID_ENV="staging"
$env:KALSHI_SANDBOX="true"
python -m merid --mode=staging --venue=kalshi

# In another terminal, tail logs
Get-Content $env:USERPROFILE\.merid\logs\merid.log -Wait | 
    Select-String "KALSHI|GATE|SANITY|DUPLICATE|HALT"
```

### Staging Success Criteria

- [ ] Zero occurrences of `order_router not available, falling back`
- [ ] All `client_order_id` values match pattern `merid-[a-f0-9]{16}-\d+`
- [ ] Duplicate orders handled via `gate:duplicate` or `KALSHI_DUPLICATE_SUCCESS`
- [ ] No `SANITY_VIOLATION` during normal operation
- [ ] Jittered backoff observed (variable wait times: 2.1s, 3.4s, 4.2s, etc.)
- [ ] Position tracking matches expected after each scenario

---

## Phase 2: Runtime Log Checks (Staging → Live Dry-Run)

### Command Reference

```powershell
# 1. Verify deterministic client_order_id generation
Get-Content $env:USERPROFILE\.merid\logs\merid.log -Tail 1000 | 
    Select-String "merid-[a-f0-9]{16}-\d+" | 
    Measure-Object
# EXPECTED: > 0 matches (all orders should have deterministic IDs)

# 2. Check duplicate success handling
Get-Content $env:USERPROFILE\.merid\logs\merid.log -Tail 10000 | 
    Select-String "KALSHI_DUPLICATE_SUCCESS"
# EXPECTED: May be 0+ (depends on retry frequency)
# IF > 0: Verify each was handled as success, not error

# 3. Verify pre-trade gate blocks (expected, not errors)
Get-Content $env:USERPROFILE\.merid\logs\merid.log -Tail 10000 | 
    Select-String "Pre-trade gate blocked"
# EXPECTED: May be 0+ (race condition protection)

# 4. Check for sanity violations (should be ZERO)
Get-Content $env:USERPROFILE\.merid\logs\merid.log -Tail 10000 | 
    Select-String "SANITY_VIOLATION|STRATEGY_HALT"
# EXPECTED: 0 occurrences in staging
# IF > 0: Investigate immediately, do not proceed to live

# 5. Verify no fallback path usage (should be ZERO)
Get-Content $env:USERPROFILE\.merid\logs\merid.log -Tail 10000 | 
    Select-String "order_router not available, falling back"
# EXPECTED: 0 (fail-closed path should never trigger for live orders)
# IF > 0: Abort go-live, investigate import issues

# 6. Verify jittered backoff
Get-Content $env:USERPROFILE\.merid\logs\merid.log -Tail 10000 | 
    Select-String "retrying in [0-9]+\.[0-9]+s" | 
    ForEach-Object { $_ -match "retrying in ([0-9]+\.[0-9]+)s" | Out-Null; $matches[1] }
# EXPECTED: Variable times (1.8, 2.3, 4.1, etc.) not uniform

# 7. Check error threshold exclusions working
Get-Content $env:USERPROFILE\.merid\logs\merid.log -Tail 10000 | 
    Select-String "ERROR THRESHOLD KILL"
# EXPECTED: 0 (unless genuine infrastructure failures)
# IF triggered by gate:duplicate or client error: 404 → BUG
```

### Log Pattern Reference

| Pattern | Level | Meaning | Action Required |
|---------|-------|---------|-----------------|
| `[KALSHI_ORDER_INTENT]` | INFO | Order admitted to router | None |
| `[KALSHI_DUPLICATE_SUCCESS]` | INFO | Retry succeeded via idempotency | None |
| `[GATE] duplicate blocked` | WARNING | Local dedup prevented send | None |
| `[SANITY_VIOLATION]` | CRITICAL | Duplicate fill or overfill detected | **HALT, INVESTIGATE** |
| `[STRATEGY_HALT]` | CRITICAL | Strategy halted due to violation | **MONITOR** |
| `order_router not available` | ERROR | Fallback would have triggered | **BUG** — should never happen |

---

## Phase 3: Go-Live Gate

### Prerequisites (ALL MUST BE GREEN)

- [ ] Staging run completed (4+ hours)
- [ ] All 6 scenarios from Phase 1 exercised
- [ ] Zero `SANITY_VIOLATION` in staging
- [ ] Zero fallback path usage in staging
- [ ] Deterministic IDs confirmed in logs
- [ ] Duplicate handling confirmed working
- [ ] Error threshold NOT triggered by policy errors

### Canary Deployment (First 20-50 Cycles)

```powershell
# 1. Start with minimal sizing
$env:MERID_MAX_ORDER_SIZE="10"        # Max 10 contracts per order
$env:MERID_MAX_POSITION_VALUE="1000"  # $1000 max position

# 2. Enable all alerts
$env:MERID_ALERT_WEBHOOK="https://hooks.slack.com/..."
$env:MERID_ALERT_ON_SANITY="true"
$env:MERID_LOG_LEVEL="DEBUG"  # Verbose logging for first hour

# 3. Start with kill switch armed
$env:MERID_ERROR_THRESHOLD_KILL_ENABLED="true"

# 4. Launch with monitoring
python -m merid --mode=live --venue=kalshi --profile=canary
```

### Canary Monitoring (First Hour)

Watch these in real-time:

```powershell
# Terminal 1: Critical events
Get-Content $env:USERPROFILE\.merid\logs\merid.log -Wait | 
    Select-String "CRITICAL|ERROR|SANITY|HALT|KILL"

# Terminal 2: Order flow
Get-Content $env:USERPROFILE\.merid\logs\merid.log -Wait | 
    Select-String "KALSHI_ORDER|DUPLICATE_SUCCESS|gate blocked"

# Terminal 3: Metrics export
curl http://localhost:8080/metrics | 
    Select-String "kalshi_|error_threshold|sanity_"
```

### Canary Kill Switch Criteria

**IMMEDIATE KILL if any of:**

1. `SANITY_VIOLATION` appears in logs
2. `STRATEGY_HALT` fires unexpectedly
3. Position size exceeds intended by >1 order
4. `ERROR_THRESHOLD KILL` triggered
5. Any order missing `merid-*` client_order_id pattern
6. Fallback path log appears

**Kill Command:**
```powershell
# Emergency stop
python -c "from merid.risk.kill_switches import emergency_stop; emergency_stop('Canary abort: <reason>')"
```

---

## Phase 4: Full Production

### After Canary Success (50 clean cycles)

```powershell
# Gradually increase limits
$env:MERID_MAX_ORDER_SIZE="100"       # Normal size
$env:MERID_MAX_POSITION_VALUE="10000" # Normal limit
$env:MERID_LOG_LEVEL="INFO"           # Reduce verbosity

# Continue monitoring
```

### Ongoing Monitoring

| Check | Frequency | Command |
|-------|-----------|---------|
| Deterministic IDs | Hourly | `Select-String "merid-[a-f0-9]{16}-\d+"` |
| Sanity violations | Real-time | `Select-String "SANITY_VIOLATION"` |
| Error threshold | Hourly | `Select-String "ERROR THRESHOLD"` |
| Fallback path | Daily | `Select-String "order_router not available"` |
| Duplicate success | Daily | `Select-String "KALSHI_DUPLICATE_SUCCESS"` |

---

## Rollback Plan

### If Issues Detected

```powershell
# 1. Immediate halt
curl -X POST http://localhost:8080/admin/kill-switch \
    -d '{"reason": "idempotency anomaly detected"}'

# 2. Disable live trading
$env:MERID_LIVE_ENABLED="false"

# 3. Reset to last known good commit
git checkout HEAD~1 -- merid/event_venues/kalshi/order_router.py

# 4. Verify position integrity
python -c "
from merid.event_venues.kalshi.position_sanity_checker import get_position_sanity_checker
sc = get_position_sanity_checker()
print(sc.get_metrics())
"

# 5. Restart in paper mode for validation
$env:MERID_ENV="staging"
python -m merid --mode=paper
```

---

## Sign-Off Log

| Phase | Date | Operator | Result | Notes |
|-------|------|----------|--------|-------|
| Staging Run | | | ⬜ PASS / ⬜ FAIL | |
| Log Verification | | | ⬜ PASS / ⬜ FAIL | |
| Canary Deploy | | | ⬜ PASS / ⬜ FAIL | |
| Full Production | | | ⬜ PASS / ⬜ FAIL | |

**Production Go-Live Approved By:** _________________ **Date:** _______

---

## Quick Reference: Key Log Patterns

```
# Good patterns (expected)
[KALSHI_ORDER_INTENT] ticker=X side=yes action=buy count=10
[KALSHI_ORDER_RESULT] ticker=X status=filled_live
[KALSHI_DUPLICATE_SUCCESS] ticker=X client_tag=merid-abc123-2814 — order already accepted
[GATE] allowed coid=merid-abc123-2814 contract=X count=10

# Bad patterns (investigate)
[SANITY_VIOLATION] fill_rejected ticker=X error=duplicate_fill:order-123-0
[STRATEGY_HALT] strategy=agent-1 halted due to sanity_violation:duplicate_fill
order_router not available, falling back to direct client call  # SHOULD NEVER HAPPEN
ERROR THRESHOLD KILL  # Only if genuine failures, not policy errors
```
