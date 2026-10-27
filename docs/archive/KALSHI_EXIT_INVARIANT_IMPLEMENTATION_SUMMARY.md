# Kalshi Exit Invariant — Implementation Summary

## Overview

This document summarizes the implementation of the "no trade without exit" invariant for Kalshi 15-minute crypto trading. The invariant ensures that all entry orders (buy) on 15m crypto contracts have attached exit targets (take-profit and/or stop-loss) before routing.

**Implementation Date:** 2026-01-11
**Status:** Complete
**Feature Flag:** `KALSHI_ENFORCE_EXIT_INVARIANT` (default: `true`)

---

## Invariant Definition

**Statement:** All entry orders (action="buy") on 15-minute crypto contracts must have exit targets (TP and/or SL) before routing.

**Scope:**
- **Markets:** BTC, ETH, SOL, XRP, DOGE 15-minute contracts
- **Ticker patterns:** `KX{COIN}15M-*` (e.g., KXBTC15M-26APR191645-45)
- **Entry orders:** `action="buy"` for opening positions
- **Exempt:** Exit orders (action="sell"), orders with source markers (take_profit, stop_loss, micro_scalp, exit, close), non-15m orders, non-crypto orders

---

## Implementation Changes

### 1. Central Enforcement (order_router.py)

**File:** `merid/event_venues/kalshi/order_router.py`

**Changes:**
- Added `_is_15m_crypto_entry_order(intent: OrderIntent) -> bool` — checks if order is an entry order for 15m crypto requiring exit targets
- Added `_has_exit_target(intent: OrderIntent) -> bool` — checks if order has TP/SL information
- Added `_check_exit_target_invariant(intent: OrderIntent, t0: float, mode: TradingMode) -> Optional[OrderResult]` — enforces invariant, returns rejection if violated
- Wired invariant check into `route_order_async()` at line 2591, before any side effects
- Added audit logging for compliance (`[INVARIANT] exit_target_check`) and violations (`[INVARIANT_VIOLATION]`)
- Integrated Prometheus metrics for compliance and violations

**Key Design Decisions:**
- Invariant check runs BEFORE any API calls or state mutations (fail-fast)
- Feature flag allows disablement: `KALSHI_ENFORCE_EXIT_INVARIANT` (default true)
- Metrics use truncated labels (50 chars) for cardinality safety
- Structured audit logs provide full context for debugging

### 2. Prometheus Metrics (kalshi_metrics.py)

**File:** `merid/metrics/kalshi_metrics.py`

**Changes:**
- Added `kalshi_exit_invariant_compliant_total` — Counter for compliant orders
  - Labels: `ticker` (truncated to 50 chars)
- Added `kalshi_exit_invariant_violations` — Counter for invariant violations
  - Labels: `ticker`, `source` (both truncated to 50 chars)

**Alerting Guidance:**
- CRITICAL: `kalshi_exit_invariant_violations > 0` in any 5-minute window
- WARNING: `rate(kalshi_exit_invariant_compliant_total[30m]) == 0` (no compliant orders)

### 3. Bypass Path Fixes

#### 3.1 Web API (kalshi_api.py)

**File:** `web/api/kalshi_api.py`

**Changes:**
- Added optional TP/SL parameters to `place_order()` endpoint:
  - `take_profit_price_cents: Optional[int] = None`
  - `take_profit_r_multiple: Optional[float] = None`
  - `stop_loss_price_cents: Optional[int] = None`
  - `confidence: Optional[float] = None`
- Added automatic default TP computation for 15m crypto entry orders (lines 3233-3269)
- Default SL: 5 cents below entry (conservative)
- Default confidence: 0.5 (medium) → computes 1.0-1.5R TP
- Fallback: 1R if TP computation fails
- Updated OrderIntent creation to include TP/SL fields (lines 3284-3286)

**Backward Compatibility:**
- Existing API calls without TP/SL parameters will have defaults computed automatically
- No breaking changes to existing clients

#### 3.2 Kalshi Executor (kalshi.py)

**File:** `merid/execution/executors/kalshi.py`

**Changes:**
- Added TP/SL parameters to `KalshiExecutor.place_order()` method
- Added automatic default TP computation for 15m crypto entry orders (lines 58-87)
- Same defaults as API endpoint
- Updated OrderIntent creation to include TP/SL fields (lines 95-97)

**Backward Compatibility:**
- Existing executor calls without TP/SL parameters will have defaults computed automatically

#### 3.3 Kalshi Tools (kalshi_tools.py)

**File:** `merid/prediction/kalshi_tools.py`

**Changes:**
- Added TP/SL parameters to `build_live_route_order_intent()` function (lines 802-804)
- Added automatic default TP computation for 15m crypto entry orders (lines 821-845)
- Same defaults as API endpoint
- Updated OrderIntent creation to include TP/SL fields (lines 856-858)

**Backward Compatibility:**
- Existing tool calls without TP/SL parameters will have defaults computed automatically

#### 3.4 CT Execution Adapter (ct_execution_adapter.py)

**File:** `merid/trading/ct_execution_adapter.py`

**Changes:**
- Added automatic default TP computation in `_order_dict_to_intent()` method (lines 100-130)
- Same defaults as API endpoint
- Updated OrderIntent creation to include TP/SL fields (lines 150-152)

**Backward Compatibility:**
- CT orders without explicit TP/SL will have defaults computed automatically

### 4. Regression Test Suite (NEW)

**File:** `tests/test_kalshi_exit_invariant.py`

**Coverage:**
- `TestInvariantScope` (11 tests) — scope detection functions
- `TestInvariantEnforcement` (7 tests) — central enforcement in route_order_async
- `TestBypassPathCoverage` (4 tests) — bypass path default TP computation
- `TestMetrics` (2 tests) — metrics emission verification

**Total:** 24 test cases

**Test Scenarios:**
- Entry orders with TP/SL pass invariant check
- Entry orders without exit targets are rejected
- Exit orders (sell) exempt from invariant
- Non-15m orders exempt from invariant
- Feature flag can disable enforcement
- All bypass paths compute default TP correctly
- Metrics emitted for compliance and violations

---

## Default TP/SL Computation

### Algorithm

All bypass paths use the same default computation logic:

```python
if action == "buy" and ticker.startswith(("KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M")):
    if take_profit_price_cents is None and take_profit_r_multiple is None:
        try:
            from merid.prediction.dynamic_takeprofit import DynamicTakeProfitEngine
            engine = DynamicTakeProfitEngine()
            
            # Default SL: 5 cents below entry (conservative)
            if stop_loss_price_cents is None:
                stop_loss_price_cents = max(1, price_cents - 5)
            
            # Compute dynamic TP with default confidence
            tp_plan = engine.compute_tp(
                entry_price=price_cents / 100.0,
                stop_price=stop_loss_price_cents / 100.0,
                direction="LONG" if side == "yes" else "SHORT",
                confidence=0.5,  # Default medium confidence
            )
            
            take_profit_r_multiple = tp_plan.tp_r_multiple
        except Exception:
            # Fallback to 1R if TP computation fails
            take_profit_r_multiple = 1.0
            if stop_loss_price_cents is None:
                stop_loss_price_cents = max(1, price_cents - 5)
```

### Defaults

- **Stop Loss:** 5 cents below entry (conservative)
- **Confidence:** 0.5 (medium) → computes 1.0-1.5R TP
- **Fallback:** 1R if TP computation fails
- **R-multiple range:** 1.0-3.0R based on confidence (per DynamicTakeProfitEngine)

---

## Audit Logging

### Compliance Log

```
[INVARIANT] exit_target_check | ticker=KXBTC15M-... | action=buy | has_tp=true | has_sl=true | source=api | status=PASS
```

### Violation Log

```
[INVARIANT_VIOLATION] Entry order without exit target rejected: 
ticker=KXBTC15M-... action=buy source=api client_tag=... | 
has_tp=false has_sl=false | 
reason=invariant_violation:no_trade_without_exit
```

### Log Levels

- Compliance: `INFO` level
- Violation: `ERROR` level
- Metric emission failures: `DEBUG` level

---

## Operator Notes

### Feature Flag Control

**Enable enforcement (default):**
```bash
export KALSHI_ENFORCE_EXIT_INVARIANT=true
```

**Disable enforcement (emergency rollback):**
```bash
export KALSHI_ENFORCE_EXIT_INVARIANT=false
```

### Monitoring

**Check compliance rate:**
```bash
# Prometheus query
rate(kalshi_exit_invariant_compliant_total[5m])
```

**Check for violations:**
```bash
# Prometheus query
kalshi_exit_invariant_violations
```

**Grafana dashboard:**
- Add panels for `kalshi_exit_invariant_compliant_total` and `kalshi_exit_invariant_violations`
- Set alert for violations > 0 (CRITICAL)
- Set alert for no compliant orders in 30m (WARNING)

### Troubleshooting

**Issue: Orders rejected with "invariant_violation:no_trade_without_exit"**

**Diagnosis:**
1. Check if order is 15m crypto entry order (action="buy", ticker matches KX{COIN}15M-*)
2. Check if order has TP/SL parameters
3. Check if bypass path is computing default TP correctly
4. Check if feature flag is enabled (`KALSHI_ENFORCE_EXIT_INVARIANT=true`)

**Resolution:**
- If bypass path is missing TP computation: add default TP logic
- If feature flag should be disabled: set `KALSHI_ENFORCE_EXIT_INVARIANT=false`
- If order should be exempt: ensure action="sell" or source contains exit marker

**Issue: Metrics not emitting**

**Diagnosis:**
1. Check if Prometheus metrics server is running
2. Check if metric imports are successful
3. Check for metric cardinality limits

**Resolution:**
- Restart metrics server
- Verify metric imports in order_router.py
- Reduce label cardinality if needed

**Issue: Default TP computation failing**

**Diagnosis:**
1. Check if `DynamicTakeProfitEngine` is importable
2. Check if entry price and stop price are valid
3. Check for exceptions in TP computation logs

**Resolution:**
- Fallback to 1R should prevent order rejection
- Verify DynamicTakeProfitEngine is installed and working
- Check log for specific exception details

---

## Testing

### Run Regression Tests

```bash
pytest tests/test_kalshi_exit_invariant.py -v
```

### Expected Output

All 24 tests should pass:
- TestInvariantScope: 11 tests
- TestInvariantEnforcement: 7 tests
- TestBypassPathCoverage: 4 tests
- TestMetrics: 2 tests

### Test Coverage

- Scope detection (entry vs exit, 15m vs non-15m)
- Invariant enforcement (with TP/SL, without TP/SL, feature flag)
- Bypass path coverage (API, executor, tools, CT adapter)
- Metrics emission (compliance, violations)

---

## Rollout Checklist

### Pre-Rollout

- [ ] Review all code changes in modified files
- [ ] Run regression test suite: `pytest tests/test_kalshi_exit_invariant.py -v`
- [ ] Verify feature flag behavior with `KALSHI_ENFORCE_EXIT_INVARIANT=false`
- [ ] Verify feature flag behavior with `KALSHI_ENFORCE_EXIT_INVARIANT=true`
- [ ] Set up Grafana alerts for invariant violations
- [ ] Set up Grafana alerts for no compliant orders
- [ ] Review audit log patterns with operations team
- [ ] Document rollback procedure

### During Rollout (Paper Mode)

- [ ] Deploy changes to paper trading environment
- [ ] Monitor `kalshi_exit_invariant_compliant_total` metric
- [ ] Monitor `kalshi_exit_invariant_violations` metric (expect 0)
- [ ] Review audit logs for `[INVARIANT]` patterns
- [ ] Verify bypass paths compute default TP correctly
- [ ] Run regression tests in paper environment

### During Rollout (Live Mode)

- [ ] Deploy changes to live environment
- [ ] Reduce position sizing temporarily (e.g., 50%)
- [ ] Monitor `kalshi_exit_invariant_compliant_total` metric
- [ ] Monitor `kalshi_exit_invariant_violations` metric (expect 0)
- [ ] Review audit logs for `[INVARIANT]` patterns
- [ ] Verify bypass paths compute default TP correctly
- [ ] Check for any unexpected order rejections

### Post-Rollout

- [ ] Verify zero invariant violations in production logs
- [ ] Verify compliance metric incrementing regularly
- [ ] Restore normal position sizing
- [ ] Review audit logs for any unexpected patterns
- [ ] Update runbooks with invariant enforcement procedures
- [ ] Document any lessons learned

---

## Files Modified

1. `merid/event_venues/kalshi/order_router.py` — Central enforcement, audit logging
2. `merid/metrics/kalshi_metrics.py` — Prometheus metrics
3. `web/api/kalshi_api.py` — API bypass path fix
4. `merid/execution/executors/kalshi.py` — Executor bypass path fix
5. `merid/prediction/kalshi_tools.py` — Tools bypass path fix
6. `merid/trading/ct_execution_adapter.py` — CT adapter bypass path fix
7. `tests/test_kalshi_exit_invariant.py` — NEW: Regression test suite
8. `docs/KALSHI_EXIT_INVARIANT_ROLLOUT_PLAN.md` — NEW: Rollout plan
9. `docs/KALSHI_EXIT_INVARIANT_IMPLEMENTATION_SUMMARY.md` — NEW: This document

---

## References

- **Rollout Plan:** `docs/KALSHI_EXIT_INVARIANT_ROLLOUT_PLAN.md`
- **Test Suite:** `tests/test_kalshi_exit_invariant.py`
- **Order Router:** `merid/event_venues/kalshi/order_router.py`
- **Metrics:** `merid/metrics/kalshi_metrics.py`
- **Dynamic TP Engine:** `merid/prediction/dynamic_takeprofit.py`

---

## Summary

The "no trade without exit" invariant has been successfully implemented for Kalshi 15-minute crypto trading. All entry orders on 15m crypto contracts must now have exit targets (TP and/or SL) before routing. The implementation includes:

- Central enforcement in `route_order_async()` with fail-fast checking
- Automatic default TP/SL computation in all bypass paths
- Comprehensive audit logging for compliance and violations
- Prometheus metrics for monitoring and alerting
- Regression test suite with 24 test cases
- Detailed rollout plan with phase-based deployment
- Feature flag for emergency rollback

The implementation is production-ready and can be deployed following the rollout plan in `docs/KALSHI_EXIT_INVARIANT_ROLLOUT_PLAN.md`.
