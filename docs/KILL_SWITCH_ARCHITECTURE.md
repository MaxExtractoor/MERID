# Kill Switch Architecture Documentation

## Production Fix: Error Counts Never Trigger Kills

**Date:** April 15, 2026  
**Status:** PRODUCTION READY  
**JIRA/Tracker:** Kill-Switch-Refactor-2026-04-15

---

## Summary

This document describes the production-grade fix that **completely removes error-count-based kill logic** from the MERID trading system. After this fix, automatic halts are **only** triggered by explicit risk/policy violations or manual operator intervention.

### Key Principle

```
┌─────────────────────────────────────────────────────────┐
│  HALT CONDITIONS (Automatic Triggers)                   │
├─────────────────────────────────────────────────────────┤
│  ✓ Daily Loss Limit Breach (kalshi_risk.py)            │
│  ✓ Max Drawdown Breach (kalshi_risk.py)                │
│  ✓ Manual Operator Emergency Stop (kill_switches.py)   │
├─────────────────────────────────────────────────────────┤
│  ✗ Error Count in Last Hour (REMOVED)                  │
│  ✗ P0/P1 Error Budget Exhaustion (REMOVED)               │
│  ✗ Unclassified Error Threshold (REMOVED)                │
└─────────────────────────────────────────────────────────┘
```

---

## Architecture Changes

### 1. RiskController (merid/risk/kill_switches.py)

#### record_error()
**Before:** Legacy behavior counted all errors toward threshold, could trigger kill  
**After:** Always returns `True`, errors never counted toward threshold

```python
def record_error(self, error_hint: str = "") -> bool:
    """
    PRODUCTION FIX: Error counts NEVER trigger kill switches.
    Returns True always (trading can continue - errors never kill).
    """
    # Classification still happens for proper logging
    # But NO counting toward threshold
    logger.debug("[risk] record_error: error from %s - NOT counting toward threshold")
    return True
```

#### record_error_classified()
**Before:** Could trigger `KillSwitchReason.ERROR_THRESHOLD`  
**After:** Tracks errors for observability only, returns `True` always

```python
def record_error_classified(...):
    # Track for observability/metrics only (no kill switch triggering)
    if classification.counts_toward_budget and should_count:
        self._weighted_error_count += weighted_increment
        self._error_count += 1
    
    # Log tier for observability but DO NOT act on it
    tier, pct = self._check_error_tier_locked()
    
    # CRITICAL: Error counts can NEVER trigger kill switches
    return True, log_data
```

### 2. ErrorBudget (merid/core/error_budget.py)

#### can_halt_trading()
**Before:** Returned `True` if state == EXHAUSTED  
**After:** Always returns `False`

```python
def can_halt_trading(self) -> bool:
    """
    PRODUCTION FIX: Error budget can NEVER halt trading.
    Returns False always (error counts never halt trading).
    """
    return False
```

---

## Kill Switch Hierarchy

### Valid Kill Reasons (Post-Fix)

| Reason | Source | Trigger Condition |
|--------|--------|-------------------|
| `MANUAL` | kill_switches.py | Operator emergency stop button |
| `DAILY_LOSS` | kalshi_risk.py | daily_pnl <= -daily_loss_limit |
| `MAX_DRAWDOWN` | kalshi_risk.py | drawdown_pct >= drawdown_halt_pct |

### Removed Kill Reasons

| Reason | Original Source | Status |
|--------|---------------|--------|
| `ERROR_THRESHOLD` | kill_switches.py | **DISABLED** |
| `ERROR_BUDGET_EXHAUSTED` | error_budget.py | **DISABLED** |

---

## Data Flow

### Observability Path (Still Active)

```
Error Occurs
    ↓
record_error() / record_error_classified()
    ↓
Classification (log level determination)
    ↓
Counter Increment (metrics only)
    ↓
Tier Calculation (dashboard display)
    ↓
Logs / Dashboards / Metrics
```

### Kill Switch Path (Risk-Only)

```
Risk Check (PnL / Drawdown)
    ↓
Breach Detected
    ↓
_fire_kill_switch() / _trigger_kill_locked()
    ↓
KillSwitchState.ACTIVE
    ↓
Trading Halted
```

---

## UI/UX Changes

### KillSwitchView.tsx

**Before:**
```tsx
{/* Error rate warning with circuit breaker hint */}
{source: 'error_rate', 
 severity: 'warning',
 hint: 'Circuit breaker may trip if errors continue'}

{/* Errors with threshold comparison */}
<p>{count_1h} / {threshold}</p>
<p>{near_limit ? 'Near threshold' : 'Within limits'}</p>
```

**After:**
```tsx
{/* Informational only */}
{source: 'error_rate',
 severity: 'info',
 hint: 'Error counts are observability-only; only risk/drawdown/manual kills halt trading'}

{/* Simple count without threshold */}
<p>{count_1h} logged</p>
<p>Observability only — never blocks trading</p>
```

---

## Testing

### Unit Tests: `tests/test_error_count_never_kills.py`

**TestErrorCountsNeverKill**
- `test_record_error_1000_times_no_kill` - Verify 1000 errors don't kill
- `test_record_error_classified_critical_no_kill` - Classified CRITICAL errors don't kill
- `test_error_budget_never_halts_trading` - ErrorBudget.can_halt_trading() always False

**TestRiskViolationsStillKill**
- `test_daily_loss_limit_triggers_kill` - Daily loss kills still work
- `test_drawdown_triggers_kill` - Drawdown kills still work

**TestManualKillsStillWork**
- `test_manual_emergency_stop_works` - Emergency stop still works
- `test_manual_reset_works` - Reset functionality preserved

**TestRegressionScenarios**
- `test_websocket_reconnects_never_kill` - WS reconnects are safe
- `test_winerror_995_never_kills` - Windows errors are safe
- `test_gate_blocked_never_kills` - Gate blocks are safe

### Run Tests
```bash
python -m pytest tests/test_error_count_never_kills.py -v
```

---

## Operational Notes

### What Still Triggers Kills

1. **Manual Emergency Stop** - Operator clicks "Emergency Stop" button
2. **Daily Loss Limit** - `daily_pnl <= -daily_loss_limit_usd`
3. **Max Drawdown** - `(peak_equity - current_equity) / peak_equity >= drawdown_halt_pct`

### What Never Triggers Kills (Observability Only)

1. Error counts in 1 hour / 24 hours
2. P0/P1 error budget exhaustion
3. WebSocket disconnects/reconnects
4. Windows asyncio errors (WinError 995)
5. Gate blocks / order rejections
6. Rate limiting events
7. Unclassified/unexpected errors

### Dashboard Indicators

- **Red "KILL SWITCH ACTIVE" banner**: Only for risk/drawdown/manual kills
- **Error count display**: Observational only, gray text, no threshold warnings
- **"Circuit breaker" language**: Removed from UI

---

## Configuration

No configuration changes required. The fix is hardcoded in the logic:

- `MERID_ERROR_THRESHOLD_KILL_ENABLED` env var still exists but is now **redundant**
- Error threshold values in config are now **observational only**

---

## Rollback Plan

This fix is **deliberately permanent**. If you need to re-enable error-count kills:

1. Revert changes to `merid/risk/kill_switches.py`
2. Revert changes to `merid/core/error_budget.py`
3. Revert changes to `web/react/src/views/KillSwitchView.tsx`
4. Delete `tests/test_error_count_never_kills.py`

**WARNING**: Re-enabling error-count kills is strongly discouraged and may result in PnL loss due to non-critical errors halting profitable trading.

---

## Verification Checklist

After deployment, verify:

- [ ] 1000 test errors don't trigger kill
- [ ] Manual emergency stop still works
- [ ] Daily loss limit still triggers kill
- [ ] Drawdown limit still triggers kill
- [ ] Error count displays in UI (observational)
- [ ] No "Circuit breaker" warnings in UI
- [ ] All tests pass: `pytest tests/test_error_count_never_kills.py -v`

---

## Contact

For questions about this fix:
- **System**: MERID Trading Platform
- **Component**: Risk Management / Kill Switches
- **Last Updated**: April 15, 2026
