# MERID Task Backlog

**Generated**: 2026-02-04
**Status**: Active development

## Completed Recently

- [x] Coverage sprint (fail_under raised to 22% → 25%)
- [x] Resilience layer (`merid/resilience/` - 61 tests)
- [x] Kalshi client resilience wiring (105 tests)
- [x] Polymarket client resilience wiring (120 tests)
- [x] Risk kill switches (`merid/risk/` - 27 tests)
- [x] Chaos tests for risk + resilience (30 tests)
- [x] Risk controller integrated with paper trading
- [x] Go-live checklist and validation commands
- [x] Operator day-in-the-life test

---

## Priority 1: Production Safety ~~(This Week)~~ ✅ COMPLETE

### ~~1. Wire Resilience to Polymarket Client~~ ✅
**Status**: Complete (2026-02-04)
- Added circuit breaker, `_request_with_resilience`, `_result` methods

### ~~2. Integrate Risk Controller with Trading Engine~~ ✅
**Status**: Complete (2026-02-04)
- `can_trade()` check before orders, `record_pnl()` on position close

### ~~3. Add Chaos/Failure Tests~~ ✅
**Status**: Complete (2026-02-04)
- 13 risk chaos tests, 17 resilience chaos tests

---

## Priority 2: Coverage & Quality ~~(Next Week)~~ ✅ COMPLETE

### ~~4. Raise Coverage Floor to 25%~~ ✅
**Status**: Complete (2026-02-04)
- Updated `.coveragerc` fail_under from 22 to 25

### ~~5. Fix pytest Marker Warnings~~ ✅
**Status**: Complete (2026-02-04)
- No warnings found, markers properly registered in `pytest.ini`

### ~~6. Add WebSocket Reconnection Tests~~ ✅
**Status**: Complete (2026-02-04)
- 13 Kalshi reconnection tests (`test_ws_reconnect.py`)
- 15 Polymarket reconnection tests (`test_ws_reconnect.py`)

---

## Priority 3: Documentation & Ops ~~(Ongoing)~~ ✅ COMPLETE

### ~~7. Create Operator Training Runbook~~ ✅
**Status**: Complete (2026-02-04)
- Created `docs/OPERATOR_RUNBOOK.md` with emergency commands, daily ops, failure scenarios
- Monitoring dashboard walkthrough
- Escalation procedures

**Files**: `docs/OPERATOR_RUNBOOK.md`

### ~~8. Add API Documentation for Risk Module~~ ✅
**Status**: Complete (2026-02-04)
- Created `docs/RISK_API.md` with full API reference, examples, integration patterns
- Integration patterns
- Troubleshooting guide

**Files**: `docs/RISK_API.md`

---

## Priority 4: Future Enhancements ✅ COMPLETE

### ~~9. Implement Bulkhead Pattern~~ ✅
**Status**: Complete (2026-02-04)
- Created `merid/resilience/bulkhead.py` with Bulkhead class, registry
- 16 tests in `tests/merid/resilience/test_bulkhead.py`

### ~~10. Add Prometheus Metrics~~ ✅
**Status**: Complete (2026-02-04)
- Created `merid/resilience/metrics.py` with MetricsCollector
- Prometheus text + JSON export for circuit breakers, bulkheads, risk
- 16 tests in `tests/merid/resilience/test_metrics.py`

---

## Archive: Original Task Descriptions

### 9. Implement Bulkhead Pattern (Original)
**Effort**: 4-5 hours | **Risk**: Medium

Isolate venue failures to prevent cascading:
- Separate thread pools per venue
- Rate limiting per venue
- Resource quotas

**Files**: `merid/resilience/bulkhead.py`

### 10. Add Prometheus Metrics
**Effort**: 3-4 hours | **Risk**: Low

Export metrics for monitoring:
- Circuit breaker state (open/closed/half-open)
- Daily P&L
- Kill switch events
- Request latency histograms

**Files**: `merid/observability/metrics.py`

---

## Quick Reference

| Task | Priority | Effort | Risk |
|------|----------|--------|------|
| Wire Polymarket resilience | P1 | 2-3h | Medium |
| Integrate risk controller | P1 | 1-2h | High |
| Add chaos tests | P1 | 2-3h | Medium |
| Raise coverage to 25% | P2 | 3-4h | Low |
| Fix pytest warnings | P2 | 30m | None |
| WebSocket reconnect tests | P2 | 2-3h | Medium |
| Operator training runbook | P3 | 2h | None |
| API documentation | P3 | 1h | None |
| Bulkhead pattern | P4 | 4-5h | Medium |
| Prometheus metrics | P4 | 3-4h | Low |

---

## Notes

- **P1 tasks** should be completed before any live trading
- **P2 tasks** are quality improvements, not blockers
- **P3/P4 tasks** are nice-to-have for production maturity

See also:
- `docs/GO_LIVE_CHECKLIST.md` - Go-live procedure
- `docs/RESILIENCE_MAP.md` - Failure point analysis
- `tests/MERID_COVERAGE_BACKLOG.md` - Coverage details
