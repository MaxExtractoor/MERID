# Kalshi Exit Invariant — Safety and Rollout Plan

## Invariant Summary

**Invariant:** "No trade without exit" — All entry orders (buy) on 15-minute crypto contracts must have attached exit targets (take-profit and/or stop-loss) before routing.

**Scope:**
- **Markets:** BTC, ETH, SOL, XRP, DOGE 15-minute contracts
- **Ticker patterns:** `KX{COIN}15M-*` (e.g., KXBTC15M-26APR191645-45)
- **Entry orders:** `action="buy"` for opening positions
- **Exit orders:** `action="sell"` or source markers (take_profit, stop_loss, micro_scalp, exit, close) — exempt from invariant

**Feature flag:** `KALSHI_ENFORCE_EXIT_INVARIANT` (default: `true`)

---

## Implementation Summary

### Files Modified

1. **`merid/event_venues/kalshi/order_router.py`**
   - Added `_is_15m_crypto_entry_order()` — checks if order is entry order for 15m crypto
   - Added `_has_exit_target()` — checks if order has TP/SL information
   - Added `_check_exit_target_invariant()` — central enforcement guard
   - Wired invariant check into `route_order_async()` before any side effects
   - Added audit logging for compliance and violations
   - Integrated Prometheus metrics for monitoring

2. **`merid/metrics/kalshi_metrics.py`**
   - Added `kalshi_exit_invariant_compliant_total` — Counter for compliant orders
   - Added `kalshi_exit_invariant_violations` — Counter for invariant violations
   - Labels: ticker, source (truncated to 50 chars for cardinality safety)

3. **`web/api/kalshi_api.py`**
   - Added optional TP/SL parameters to `place_order()` endpoint
   - Added automatic default TP computation for 15m crypto entry orders using `DynamicTakeProfitEngine`
   - Default SL: 5 cents below entry (conservative)
   - Default confidence: 0.5 (medium)
   - Fallback: 1R if TP computation fails

4. **`merid/execution/executors/kalshi.py`**
   - Added TP/SL parameters to `KalshiExecutor.place_order()`
   - Added automatic default TP computation for 15m crypto entry orders
   - Same defaults as API endpoint

5. **`merid/prediction/kalshi_tools.py`**
   - Added TP/SL parameters to `build_live_route_order_intent()`
   - Added automatic default TP computation for 15m crypto entry orders
   - Same defaults as API endpoint

6. **`merid/trading/ct_execution_adapter.py`**
   - Added automatic default TP computation in `_order_dict_to_intent()`
   - Same defaults as API endpoint

7. **`tests/test_kalshi_exit_invariant.py`** (NEW)
   - Comprehensive regression test suite
   - Tests scope detection, invariant enforcement, bypass path coverage, and metrics
   - 30+ test cases covering all scenarios

---

## Rollout Plan

### Phase 1: Paper Mode Validation (Recommended: 1-2 days)

**Objective:** Validate invariant in paper mode without risking live funds.

**Steps:**
1. Deploy changes to paper trading environment
2. Set `KALSHI_ENFORCE_EXIT_INVARIANT=true` (default)
3. Monitor metrics dashboard for compliance and violations
4. Review audit logs for any unexpected rejections
5. Run regression test suite: `pytest tests/test_kalshi_exit_invariant.py -v`

**Success criteria:**
- All regression tests pass
- Zero invariant violations in paper mode
- Orders with exit targets route successfully
- Exit orders (sell) route without requiring exit targets

**Rollback procedure:**
- Set `KALSHI_ENFORCE_EXIT_INVARIANT=false` to disable enforcement
- Revert code changes if needed

---

### Phase 2: Live Mode Canary (Recommended: 1 day)

**Objective:** Validate invariant in live mode with small position sizes.

**Steps:**
1. Deploy changes to live environment
2. Set `KALSHI_ENFORCE_EXIT_INVARIANT=true`
3. Reduce position sizing temporarily (e.g., 50% of normal)
4. Monitor metrics dashboard for compliance and violations
5. Review audit logs for any unexpected rejections
6. Verify that all bypass paths compute default TP correctly

**Success criteria:**
- Zero invariant violations in live mode
- Orders with exit targets route successfully
- Metrics show compliance counter incrementing
- No unexpected order rejections

**Rollback procedure:**
- Set `KALSHI_ENFORCE_EXIT_INVARIANT=false` to disable enforcement
- Revert code changes if needed
- Restore normal position sizing

---

### Phase 3: Full Production Rollout (Recommended: Immediate after canary success)

**Objective:** Full production deployment with invariant enforcement enabled.

**Steps:**
1. Deploy changes to production
2. Set `KALSHI_ENFORCE_EXIT_INVARIANT=true` (default)
3. Restore normal position sizing
4. Monitor metrics dashboard for compliance and violations
5. Review audit logs for any unexpected rejections
6. Verify that all bypass paths compute default TP correctly

**Success criteria:**
- Zero invariant violations in production
- Orders with exit targets route successfully
- Metrics show compliance counter incrementing
- No unexpected order rejections

**Rollback procedure:**
- Set `KALSHI_ENFORCE_EXIT_INVARIANT=false` to disable enforcement
- Revert code changes if needed

---

## Monitoring and Alerting

### Prometheus Metrics

**Compliance metric:**
```
kalshi_exit_invariant_compliant_total{ticker="KXBTC15M-..."}
```
- Expected: Incrementing regularly when 15m crypto entry orders with exit targets are routed
- Alert: `rate(kalshi_exit_invariant_compliant_total[5m]) == 0` for extended periods

**Violation metric:**
```
kalshi_exit_invariant_violations{ticker="KXBTC15M-...", source="api"}
```
- Expected: Zero
- Alert: `kalshi_exit_invariant_violations > 0` in any 5-minute window (CRITICAL)

### Log Patterns

**Compliance log:**
```
[INVARIANT] exit_target_check | ticker=KXBTC15M-... | action=buy | has_tp=true | has_sl=true | source=api | status=PASS
```

**Violation log:**
```
[INVARIANT_VIOLATION] Entry order without exit target rejected: ticker=KXBTC15M-... action=buy source=api client_tag=... | has_tp=false has_sl=false | reason=invariant_violation:no_trade_without_exit
```

### Grafana Alerts

**Alert 1: Invariant Violation (CRITICAL)**
- Condition: `kalshi_exit_invariant_violations > 0`
- Severity: CRITICAL
- Action: Immediate operator attention, investigate bypass path

**Alert 2: No Compliant Orders (WARNING)**
- Condition: `rate(kalshi_exit_invariant_compliant_total[30m]) == 0`
- Severity: WARNING
- Action: Check if trading system is stuck or no 15m crypto orders being placed

---

## Backward Compatibility

### Feature Flag

The invariant can be disabled via environment variable:
```bash
export KALSHI_ENFORCE_EXIT_INVARIANT=false
```

This allows:
- Emergency rollback without code deployment
- Gradual rollout by enabling enforcement incrementally
- Testing with enforcement disabled to compare behavior

### API Changes

The `POST /api/v1/kalshi/orders` endpoint now accepts optional TP/SL parameters:
- `take_profit_price_cents` (optional int)
- `take_profit_r_multiple` (optional float)
- `stop_loss_price_cents` (optional int)
- `confidence` (optional float, for default TP computation)

**Backward compatibility:**
- Existing API calls without TP/SL parameters will have defaults computed automatically
- No breaking changes to existing clients
- Clients can opt-in to explicit TP/SL control

### Executor Changes

`KalshiExecutor.place_order()` now accepts optional TP/SL parameters:
- `take_profit_price_cents` (optional int)
- `take_profit_r_multiple` (optional float)
- `stop_loss_price_cents` (optional int)

**Backward compatibility:**
- Existing calls without TP/SL parameters will have defaults computed automatically
- No breaking changes to existing executor clients

---

## Risk Mitigation

### Risk 1: Bypass Path Missed

**Mitigation:**
- Comprehensive audit of all OrderIntent creation points
- Regression tests verify each bypass path computes default TP
- Code review checklist for any new order creation code

### Risk 2: Default TP Too Aggressive

**Mitigation:**
- Default TP uses conservative confidence (0.5 → 1.0-1.5R)
- Default SL is 5 cents below entry (conservative)
- Fallback to 1R if TP computation fails
- Operators can override defaults by providing explicit TP/SL

### Risk 3: Invariant Blocking Legitimate Orders

**Mitigation:**
- Feature flag allows immediate disablement
- Audit logs provide detailed context for violations
- Exit orders (sell) explicitly exempt from invariant
- Non-15m orders explicitly exempt from invariant

### Risk 4: Metrics Cardinality Explosion

**Mitigation:**
- Ticker labels truncated to 50 characters
- Source labels truncated to 50 characters
- Consider using low-cardinality labels for high-volume environments

---

## Operator Notes

### Pre-Rollout Checklist

- [ ] Review all code changes in modified files
- [ ] Run regression test suite: `pytest tests/test_kalshi_exit_invariant.py -v`
- [ ] Verify feature flag behavior with `KALSHI_ENFORCE_EXIT_INVARIANT=false`
- [ ] Verify feature flag behavior with `KALSHI_ENFORCE_EXIT_INVARIANT=true`
- [ ] Set up Grafana alerts for invariant violations
- [ ] Set up Grafana alerts for no compliant orders
- [ ] Review audit log patterns with operations team
- [ ] Document rollback procedure

### During Rollout

- Monitor `kalshi_exit_invariant_compliant_total` metric
- Monitor `kalshi_exit_invariant_violations` metric
- Review audit logs for `[INVARIANT]` and `[INVARIANT_VIOLATION]` patterns
- Verify that bypass paths compute default TP correctly
- Check for any unexpected order rejections

### Post-Rollout

- Verify zero invariant violations in production logs
- Verify compliance metric incrementing regularly
- Review audit logs for any unexpected patterns
- Update runbooks with invariant enforcement procedures
- Document any lessons learned for future invariants

### Troubleshooting

**Issue: Orders rejected with "invariant_violation:no_trade_without_exit"**
- Check if order is 15m crypto entry order (action="buy", ticker matches KX{COIN}15M-*)
- Check if order has TP/SL parameters
- Check if bypass path is computing default TP correctly
- Check if feature flag is enabled (`KALSHI_ENFORCE_EXIT_INVARIANT=true`)

**Issue: Metrics not emitting**
- Check if Prometheus metrics server is running
- Check if metric imports are successful
- Check for metric cardinality limits

**Issue: Default TP computation failing**
- Check if `DynamicTakeProfitEngine` is importable
- Check if entry price and stop price are valid
- Check for exceptions in TP computation logs
- Fallback to 1R should prevent order rejection

---

## Future Enhancements

### Potential Expansions

1. **Global Invariant:** Expand to all crypto timeframes (1h, daily, weekly)
2. **Asset Expansion:** Add other asset classes (macro, sports, etc.)
3. **Dynamic SL:** Compute default SL using volatility-based models
4. **Adaptive TP:** Adjust TP based on market conditions
5. **Exit Target Validation:** Validate TP/SL prices against current market

### Configuration Options

Consider adding configuration options for:
- Default confidence level for TP computation
- Default SL distance (currently fixed at 5 cents)
- Minimum required R-multiple
- Maximum allowed R-multiple
- Per-asset TP/SL overrides

---

## References

- **Audit Report:** `docs/audit/kalshi_exit_invariant_audit_report.md` (hypothetical)
- **Test Suite:** `tests/test_kalshi_exit_invariant.py`
- **Order Router:** `merid/event_venues/kalshi/order_router.py`
- **Metrics:** `merid/metrics/kalshi_metrics.py`
- **Dynamic TP Engine:** `merid/prediction/dynamic_takeprofit.py`

---

## Approval

**Implementation Date:** 2026-01-11
**Approved By:** [Operator Name]
**Rollout Date:** [To be determined]
**Feature Flag Status:** Enabled by default (true)
