# Error Budget System - Operators Guide

## Overview

The MERID Error Budget System is a centralized mechanism for tracking critical errors (P0/P1) and ensuring trading halts only when truly dangerous conditions occur. Advisory and "noisy" issues (P2/P3) never consume the error budget.

## Severity Classes

| Severity | Description | Budget Impact | Example |
|----------|-------------|---------------|---------|
| **P0** (Critical) | Data corruption, invariant violations, auth failures | **Counts fully (1.0)** | `KALSHI_AUTH_FAIL`, `RISK_VIOLATION` |
| **P1** (Serious) | Recoverable issues, rate limits, venue errors | **Counts half (0.5)** | `RATE_LIMIT`, `TIMEOUT`, `EXCHANGE_ERROR` |
| **P2** (Warning) | Operational concerns, non-critical degradations | **Does NOT count** | `VALIDATION_ERROR`, `STALE_SNAPSHOT` |
| **P3** (Info) | Expected retries, minor validation issues, noise | **Does NOT count** | `WS_RECONNECT`, `GATE_BLOCKED`, `NO_POSITION` |

## Budget States

| State | Meaning | Trading Impact |
|-------|---------|----------------|
| **HEALTHY** | Budget well within limits | Normal trading |
| **DEGRADED** | Approaching budget limit (>70%) | Reduce new positions |
| **EXHAUSTED** | Budget exceeded (>100%) | **Halt trading** |

## Configuration

Environment variables for tuning the error budget:

```bash
# P0/P1 thresholds
MERID_ERROR_BUDGET_P0_MAX=10              # P0 events to trigger EXHAUSTED
MERID_ERROR_BUDGET_P1_MAX=20              # P1 weighted events to trigger EXHAUSTED
MERID_ERROR_BUDGET_WARN_PCT=0.70          # Warning threshold (70%)

# Time windows
MERID_ERROR_BUDGET_WINDOW_SECS=3600       # Rolling window (default 1 hour)
MERID_ERROR_DEDUP_WINDOW_SECS=300         # Deduplication window (default 5 min)
MERID_ERROR_BUDGET_STARTUP_GRACE_SECS=300 # Startup grace period (default 5 min)
```

## Deduplication

Repeated errors of the same **code + context** (e.g., venue, agent) within the dedup window only count once toward the budget. This prevents a single broken venue from exhausting the budget with repeated identical errors.

Example:
```python
# These count as ONE toward budget (same code, same venue)
KALSHI_TIMEOUT (venue=kalshi) - 12:00:00
KALSHI_TIMEOUT (venue=kalshi) - 12:02:00

# These count as SEPARATE toward budget (different venues)
KALSHI_TIMEOUT (venue=kalshi) - 12:00:00
KALSHI_TIMEOUT (venue=kalshi-prod) - 12:00:00
```

## Operator Commands

### Check Budget Status

```python
from merid.core.error_budget import get_budget_status

status = get_budget_status()
print(f"State: {status['state']}")
print(f"P0 count: {status['budget_consuming_counts']['p0_count']}")
print(f"P1 weighted: {status['budget_consuming_counts']['p1_weighted']}")
print(f"Window remaining: {status['window']['remaining_seconds']}s")
```

### Reset Budget (After Root Cause Fix)

**WARNING**: Only reset the budget after investigating and fixing the root cause.

```python
from merid.core.error_budget import reset_budget

# Requires explicit operator acknowledgment
reset_budget(
    operator="ops@merid.io",
    reason="Fixed Kalshi auth credentials, verified connectivity"
)
```

### View Recent Events

```python
status = get_budget_status()
for event in status['recent_events'][-5:]:
    print(f"{event['timestamp']}: [{event['severity']}] {event['code']}")
```

## Kill Switch Integration

The error budget system is integrated with the existing kill switch (`RiskController`). When the budget becomes EXHAUSTED:

1. Budget state transitions to EXHAUSTED
2. Callback triggers kill switch via `record_error_classified()`
3. Trading is halted until:
   - Budget window expires (auto-reset), OR
   - Operator manually resets budget after fixing root cause

## Runbook Scenarios

### Scenario 1: Budget DEGRADED (70-99%)

**Symptoms**: Dashboard shows "DEGRADED" state, warning alerts firing

**Actions**:
1. Check `top_codes` in status to identify main error sources
2. Review recent P0/P1 events
3. If errors are from known issue (e.g., venue maintenance), consider preemptive halt
4. Otherwise, monitor closely

### Scenario 2: Budget EXHAUSTED (100%+)

**Symptoms**: Trading halted, "EXHAUSTED" state, critical alerts firing

**Actions**:
1. **Confirm trading is halted** (check kill switch status)
2. Identify root cause from top error codes
3. Fix the underlying issue
4. Verify fix with test trades (if possible)
5. **Reset budget** when confident:
   ```python
   reset_budget(operator="ops@merid.io", reason="Fixed [specific issue]")
   ```

### Scenario 3: Budget Auto-Reset After Window

**Symptoms**: Budget was EXHAUSTED but now shows HEALTHY without operator action

**Explanation**: The 1-hour rolling window expired, clearing all counters.

**Caution**: This is a safety feature, not a fix. If errors persist, budget will exhaust again.

**Actions**:
1. Check if errors have actually stopped
2. If errors continue, root cause not fixed
3. If errors stopped, system has self-recovered

### Scenario 4: Startup Grace Period

**Symptoms**: Budget shows EXHAUSTED but trading continues

**Explanation**: During first 5 minutes after startup, EXHAUSTED doesn't halt trading.

**Actions**:
1. Check grace period remaining in status
2. If grace period ending soon and budget exhausted, prepare for halt
3. Investigate errors causing exhaustion

## API Quick Reference

### Recording Errors

```python
from merid.core.error_budget import record_p0, record_p1, record_p2, record_p3

# P0 - Critical (halts trading)
record_p0("KALSHI_AUTH_FAIL", "Authentication failed", venue="kalshi")

# P1 - Serious (degrades trading)
record_p1("RATE_LIMIT", "Rate limit hit", venue="kalshi")

# P2 - Warning (logged, no budget impact)
record_p2("VALIDATION_WARN", "Input validation warning")

# P3 - Info (logged, no budget impact)
record_p3("WS_RECONNECT", "WebSocket reconnected")
```

### Checking State

```python
from merid.core.error_budget import ErrorBudget, is_budget_exhausted

budget = ErrorBudget.get_instance()
state = budget.current_state()

if budget.can_halt_trading():
    print("Trading should halt!")
```

## Migration from Legacy System

Existing code using `RiskController.record_error()` or `record_error_classified()` continues to work. The integration bridge maps legacy severities:

- `CRITICAL` → P0
- `HIGH` → P1
- `MEDIUM` → P2
- `LOW` → P3

## Troubleshooting

### Budget not incrementing

- Check if events are P2/P3 (these don't count)
- Check if events are duplicates within dedup window
- Check if `MERID_ERROR_BUDGET_*` env vars are set correctly

### Budget exhausted too quickly

- Review P0/P1 thresholds (may need tuning)
- Check if dedup window is too short
- Identify noisy P0/P1 codes that should be reclassified

### Budget not triggering kill switch

- Check if in startup grace period
- Verify `setup_error_budget_kill_switch_bridge()` was called
- Check RiskController integration logs

## Contact

For issues or questions about the error budget system, contact:
- SRE On-Call: #sre-alerts
- Risk Engineering: #risk-systems
