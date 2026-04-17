# MERID Kalshi Continuous Trader Fixes - April 4, 2026

## Summary of Changes

This patch addresses three critical issues in the MERID Kalshi Continuous Trader (CT) system:

1. **Execution Gate False-Positive Reconciliation Discrepancies**
2. **SOL Wiring Bug - Enhanced Diagnostics**
3. **Event Loop Lag Warning-Only Behavior**

---

## 1. Execution Gate Reconciliation Fix

**File Modified:** `c:\Dev\MERID\core\execution_gate.py`

**Problem:** The execution gate was marking reconciliation discrepancies as "critical" even when both MERID and the venue had zero positions (fresh start scenario). This caused the gate to enter BLOCKED state unnecessarily, preventing legitimate trading.

**Solution:** Added logic to distinguish between:
- **Benign discrepancies**: Both sides report zero positions (fresh start, no fills) → Downgrade to `warning` severity
- **Genuine discrepancies**: Actual position mismatches between MERID and venue → Keep as `critical` severity

**Code Changes:**
```python
# Lines 202-238 in core/execution_gate.py
if kalshi_has_critical():
    # Distinguish genuine discrepancies from benign states (CT fresh start, no positions)
    discrepancies = get_last_discrepancies()
    genuine_critical = []
    
    for d in discrepancies:
        if d.severity != "critical":
            continue
        # Check if this is a "both sides zero" benign case
        if d.merid_qty == 0.0 and d.venue_qty == 0.0:
            # Both sides have no position - this is benign, not critical
            continue
        genuine_critical.append(d)
    
    # If all critical discrepancies were benign, downgrade to warning
    if not genuine_critical and discrepancies:
        reasons.append(BlockReason(
            source="reconciliation",
            severity="warning",  # Downgraded from critical
            message="Kalshi venue reconciliation: no positions to reconcile (fresh start)",
            details="Both MERID and venue report zero positions - benign state",
            ...
        ))
```

**Impact:** 
- Fresh start scenarios no longer block execution
- Reconciliation alone only blocks new entries (reduce-only mode), never disables exits
- Genuine accounting divergences still trigger appropriate severity levels

---

## 2. SOL Wiring Bug - Enhanced Diagnostics

**File Modified:** `c:\Dev\MERID\merid\trading\kalshi_continuous_trader.py`

**Problem:** SOL markets were discovered but resulted in 0 candidates/tradeable with no logged explanation. The CRYPTO-WIRING-BUG error fired without actionable diagnostic information.

**Solution:** Added detailed filter stats logging at two key points:

### A. Filter Pipeline Entry Debug Logging (Line ~269)
```python
# DEBUG: Log detailed filter stats for SOL diagnostics
if asset_u == "SOL" or os.getenv("KALSHI_CT_DEBUG_FILTER", "").lower() in ("1", "true", "yes"):
    _fp_logger.info(
        "[FILTER-DEBUG] asset=%s raw=%d spot=%s spot_price=%s",
        asset_u, len(markets), spot is not None,
        float(spot) if spot else None
    )
```

### B. CRYPTO-WIRING-BUG Enhanced Logging (Lines ~3365-3383)
```python
# DEBUG: Log detailed filter stats for SOL diagnostics
_fp_stats = fp_result.per_asset.get(asset) if fp_result else None
if _fp_stats:
    logger.error(
        "[CRYPTO-WIRING-BUG] asset=%s cycle=%d discovered=%s candidates=0 tradeable=0 "
        "| filter_stats: raw=%d no_spot=%d parsed_strike=%d directional=%d "
        "unknown_type=%d illiquid=%d expiry_out=%d rti_q=%d pre_cap=%d post_cap=%d",
        asset, self._cycle, _asset_discovered,
        _fp_stats.raw, _fp_stats.no_spot, _fp_stats.parsed_strike,
        _fp_stats.directional, _fp_stats.unknown_type, _fp_stats.illiquid,
        _fp_stats.expiry_out_of_bounds, _fp_stats.rti_quarantined,
        _fp_stats.candidates_pre_cap, _fp_stats.candidates_post_cap
    )
```

**Impact:**
- SOL-specific debug logging helps identify which filter step drops markets
- Environment variable `KALSHI_CT_DEBUG_FILTER=true` enables verbose logging for all assets
- Filter stats show: raw count, no_spot drops, strike parsing failures, liquidity drops, expiry drops, RTI quarantines, and per-asset caps

---

## 3. Event Loop Lag Warning-Only Behavior

**File Modified:** `c:\Dev\MERID\core\execution_gate.py`

**Problem:** Event loop lag above the halt threshold (`KALSHI_LOOP_LAG_HALT_CONSECUTIVE`) was setting severity to `critical` and blocking execution entirely. This violated the principle that lag should be observed and warned about but never hard-block trading.

**Solution:** Changed the lag halt behavior from `critical` (blocking) to `warning` (non-blocking):

**Code Changes:**
```python
# Lines 388-401 in core/execution_gate.py
if _lag_halt_consecutive >= halt_consecutive_needed:
    # WARNING ONLY: Event loop lag should never hard-block trading
    # Log critical warning but keep gate in LIMITED state, not BLOCKED
    reasons.append(BlockReason(
        source="loop_lag",
        severity="warning",  # Changed from "critical" to "warning"
        message=f"Event-loop lag CRITICAL (but not blocking): {lag_ms:.0f}ms ({_lag_halt_consecutive} consecutive samples ≥ {halt_ms:.0f}ms)",
        details=f"p95={p95_ms:.0f}ms; threshold={halt_ms:.0f}ms × {halt_consecutive_needed} consecutive — trading continues with warning",
        hint=REMEDIATION_HINTS["loop_lag"],
    ))
    logger.critical(
        "Event-loop lag at %sms for %s consecutive samples — WARN only, trading continues",
        lag_ms, _lag_halt_consecutive
    )
```

**Impact:**
- Event loop lag now logs at `CRITICAL` level in the log file but returns `warning` severity to the gate
- Gate remains in `LIMITED` state (reduce-only for new entries) rather than `BLOCKED`
- Existing positions can still be closed/exited regardless of lag
- No new kill switch paths introduced

---

## Test Coverage

Tests added in `c:\Dev\MERID\tests\test_execution_gate_reconciliation_lag_fixed.py`:

1. `test_benign_zero_positions_downgraded_to_warning` - Verifies fresh start scenarios produce warnings
2. `test_genuine_mismatch_stays_critical` - Verifies genuine discrepancies maintain appropriate severity
3. `test_no_discrepancies_gate_clear` - Verifies clean reconciliation clears the gate
4. `test_lag_above_halt_threshold_is_warning_not_critical` - Verifies lag never blocks
5. `test_lag_degrade_threshold_is_warning` - Verifies elevated lag produces warnings
6. `test_reset_lag_halt_counter` - Verifies lag counter reset functionality
7. `test_filter_stats_structure` - Verifies filter pipeline produces per-asset stats
8. `test_sol_debug_logging_env_flag` - Verifies debug flag enables verbose logging
9. `test_filter_stats_include_all_drop_reasons` - Verifies stats capture all drop reasons
10. `test_ct_respects_execution_gate_limited` - Verifies CT respects limited gate state
11. `test_ct_blocked_when_gate_blocked` - Verifies CT stops when gate is genuinely blocked

---

## Operational Notes

### Environment Variables
- `KALSHI_CT_DEBUG_FILTER=1` - Enable verbose filter pipeline logging
- `KALSHI_LOOP_LAG_HALT_CONSECUTIVE=3` - Configurable consecutive lag samples before warning
- `KALSHI_PRICE_FEED_CRITICAL_THRESHOLD_S=120` - Price feed staleness threshold

### Log Categories Added/Modified
- `[CRYPTO-WIRING-BUG]` - Now includes detailed filter stats
- `[FILTER-DEBUG]` - New debug category for asset-level filter diagnostics
- `execution_gate: state=%s blocked=%s` - Enhanced gate state logging
- `Event-loop lag at %sms — WARN only, trading continues` - New lag warning log

### Behavior Changes
| Scenario | Before | After |
|----------|--------|-------|
| Fresh start (0 positions both sides) | Critical → Blocked | Warning → Limited |
| Event loop lag ≥ halt threshold | Critical → Blocked | Warning → Limited |
| SOL 0 candidates with discovered markets | [CRYPTO-WIRING-BUG] generic | [CRYPTO-WIRING-BUG] + filter_stats |
| Reconciliation only discrepancy | Could block exits | Never blocks exits |

---

## Files Modified

1. `c:\Dev\MERID\core\execution_gate.py` - Reconciliation benign state detection, lag warning-only
2. `c:\Dev\MERID\merid\trading\kalshi_continuous_trader.py` - SOL debug logging, filter stats
3. `c:\Dev\MERID\tests\test_execution_gate_reconciliation_lag_fixed.py` - New test coverage

---

## Verification Commands

```bash
# Run the new tests
py -m pytest tests/test_execution_gate_reconciliation_lag_fixed.py -v

# Run CT in dry-run mode with debug logging
$env:KALSHI_CT_DEBUG_FILTER="true"
$env:MERID_TRADE_MODE="paper"
py -m merid.trading.kalshi_continuous_trader

# Check logs for expected patterns
grep "FILTER-DEBUG" logs/merid.log
grep "Event-loop lag.*WARN only" logs/merid.log
grep "fresh start.*warning" logs/merid.log
```
