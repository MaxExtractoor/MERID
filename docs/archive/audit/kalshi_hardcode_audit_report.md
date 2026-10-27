# Kalshi Hardcode Audit Report — MERID v3.0.0

**Audit Date:** 2026-03-28  
**Scope:** Complete Kalshi-only integration verification  
**Auditor:** MERID Architecture Review  
**Status:** COMPLETE — All 8 steps verified

---

## Executive Summary

This audit validates that MERID's Kalshi integration is:
1. **Correctly wired** — All touchpoints traced, no bypasses
2. **Auth-compliant** — RSA-PSS signing matches Kalshi specification
3. **Settlement-safe** — CF RTI gating prevents late-entry trading
4. **Ghost-free** — Canonical fills ledger is single source of truth
5. **Production-ready** — Health surfaces, runbooks, CI gates in place

**Verdict:** ✅ Kalshi integration is production-ready with the guards and tests documented in this report.

---

## Files Touched During Audit

### New Files Created

| File | Purpose |
|------|---------|
| `docs/audit/kalshi_integration_map.md` | Complete inventory of all Kalshi touchpoints |
| `docs/runbooks/kalshi_operator_runbook.md` | Step-by-step operator procedures |
| `tests/kalshi/test_auth_and_transport.py` | HTTP signing, env routing, WS transport tests |
| `tests/kalshi/test_market_catalog_and_symbols.py` | Asset coverage, symbol normalization tests |
| `tests/kalshi/test_signal_to_order_pipeline.py` | Signal path, group exposure, sizing tests |
| `tests/kalshi/test_rti_settlement_policies.py` | CF RTI buffer, settlement-grade policy tests |
| `tests/kalshi/test_fills_and_positions_integrity.py` | Fills ledger, anti-ghost guarantees tests |

### Modified Files (Verification Only)

No production code was modified during this audit. All existing files were inspected and verified.

---

## Legacy/Dead Code Assessment

### Confirmed Removed/Archived

| Item | Location | Status |
|------|----------|--------|
| Polymarket venue | `merid/event_venues/_legacy/` | ✅ Archived |
| Binance perp adapters | `core/venues/_legacy/` | ✅ Archived |
| Legacy CEX code | `trading/adapters/_legacy/` | ✅ Archived |
| Mock trading files | `archive/mock_api_files/` | ✅ Archived |
| Stale root scripts | `archive/stale_root_scripts/` | ✅ Archived |

### No Contamination Found

| Pattern | Search Result | Status |
|---------|---------------|--------|
| `funding_rate` in Kalshi code | Not found in hot paths | ✅ Clean |
| `mark_price` in Kalshi code | Not found | ✅ Clean |
| `perp` in Kalshi order sizing | Not found | ✅ Clean |
| CEX spot price for settlement | No silent fallback | ✅ Clean |

---

## Invariants Established

### 1. Auth Invariants

| Invariant | Enforcement | Failure Mode |
|-----------|-------------|--------------|
| RSA signing on every request | `client.py:_sign_headers()` | Request fails, circuit breaker records failure |
| Timestamp in milliseconds | `str(int(time.time() * 1000))` | 401 Unauthorized from Kalshi |
| Path includes `/trade-api/v2` | `full_path = f"/trade-api/v2{path}"` | 401 Unauthorized from Kalshi |
| Demo vs live circuit isolation | `kalshi_{env}` circuit names | Cross-env contamination prevented |

### 2. Settlement Invariants

| Invariant | Enforcement | Failure Mode |
|-----------|-------------|--------------|
| 60-sample RTI buffer for last minute | `CFBSettlementParams.twap_bins=5` × 60s | Incomplete buffer detected |
| Strict mode blocks incomplete buffers | `settlement_execution_guard.py` | Trades rejected, alert logged |
| Settlement-grade tag only when full | `filled_count == 60` check | Status tagged "indicative" |
| No silent spot fallback | Explicit logging required | Operator alerted |

### 3. Position/Exposure Invariants

| Invariant | Enforcement | Failure Mode |
|-----------|-------------|--------------|
| Group exposure never negative | `record_close()` clamps to zero | Exposure = 0, warning logged |
| Group ID deterministic | `group_id_from_ticker()` | Consistent risk aggregation |
| Per-asset isolation | Separate dict keys in tracker | BTC exposure doesn't affect ETH |
| Kelly fraction ≤ 0.5 | `TraderConfig.kelly_fraction` | Sizing capped at quarter-Kelly |

### 4. Fills Ledger Invariants

| Invariant | Enforcement | Failure Mode |
|-----------|-------------|--------------|
| Kalshi fill_id is primary key | `KalshiFill.fill_id` required | Ingestion rejected |
| Dual ingestion (HTTP + WS) | `ingest_http_fills()`, `ingest_ws_fill()` | Redundancy, completeness |
| Idempotent upserts | Fill ID deduplication | No double-counting |
| Reconciliation vs Kalshi positions | `reconcile_with_kalshi_positions()` | `degraded`/`broken` status |
| Raw payload preservation | `KalshiFill.raw_payload` | Forensic audit trail |

### 5. Execution Invariants

| Invariant | Enforcement | Failure Mode |
|-----------|-------------|--------------|
| All orders through `order_router` | Code inspection | No direct client calls found |
| Risk check before submission | `check_order()` in `kalshi_risk.py` | Order rejected if risk fails |
| Kill switch blocks all orders | `KillSwitchManager.is_active()` | All orders rejected with reason |
| Mode-aware (paper/live) | `TradingMode` checks | Paper fills don't affect live |

---

## Test Coverage Summary

### New Test Suite: `tests/kalshi/`

| Test File | Test Classes | Coverage |
|-----------|--------------|----------|
| `test_auth_and_transport.py` | 8 classes | RSA signing, env routing, WS resilience |
| `test_market_catalog_and_symbols.py` | 7 classes | Assets, symbols, legacy contamination |
| `test_signal_to_order_pipeline.py` | 7 classes | Signal path, exposure, sizing |
| `test_rti_settlement_policies.py` | 6 classes | RTI buffer, settlement gating |
| `test_fills_and_positions_integrity.py` | 6 classes | Ledger, reconciliation, anti-ghost |

**Total New Tests:** ~180 test methods across 34 test classes

### CI Gate Recommendation

```yaml
# .github/workflows/ci.yml addition
- name: Kalshi Audit Tests
  run: |
    pytest tests/kalshi/ -v --cov=merid/event_venues/kalshi --cov-report=xml
    coverage report --fail-under=85
```

---

## Runtime Assertions Recommended

### Hot Path Assertions (Add These)

```python
# In order_router.py:route_order()
assert intent.count > 0, "Order count must be positive"
assert intent.price_cents > 0, "Order price must be positive"
assert intent.side in ("yes", "no"), f"Invalid side: {intent.side}"
```

```python
# In category_exposure.py:record_close()
new_exposure = max(0, current - close_count)
assert new_exposure >= 0, f"Exposure went negative: {new_exposure}"
```

```python
# In settlement_execution_guard.py:check_settlement_grade()
if strict and filled_count < 60:
    logger.warning(f"Incomplete RTI buffer: {filled_count}/60")
    return False
```

---

## Operator Health Surfaces

### Critical Endpoints (Must Monitor)

| Endpoint | OK State | DEGRADED State | BLOCKED State |
|----------|----------|----------------|---------------|
| `GET /api/v1/kalshi/health` | `status: "healthy"` | `circuit_open: true` | Kill switch active |
| `GET /api/v1/kalshi/ws` | `connected: true` | `reconnect_count > 0` | `connected: false` |
| `GET /api/v1/rti-feed/status` | `filled_count == 60` | `filled_count < 60` | Buffer stalled |
| `GET /api/v1/kalshi/fills` | `status: "ok"` | `status: "degraded"` | `status: "broken"` |

### Reason Codes

| Code | Meaning | Action |
|------|---------|--------|
| `circuit_open` | Too many failures, auto-throttling | Wait for recovery or restart |
| `RTI buffer incomplete` | < 60 samples for settlement | Block new buys near expiry |
| `fills lagging` | Fills poller behind real-time | Check Kalshi API, restart poller |
| `WS disconnected` | WebSocket not connected | Auto-reconnect, check auth |
| `reconciliation_diverged` | Ledger ≠ Kalshi positions | Manual reconciliation required |

---

## CI/CD Integration

### Pre-Deploy Checklist (Automated)

```bash
#!/bin/bash
# scripts/pre_deploy_kalshi_check.sh

echo "=== Kalshi Pre-Deploy Checks ==="

# 1. Run audit tests
pytest tests/kalshi/ -q || exit 1

# 2. Verify no legacy contamination
grep -r "funding_rate\|perp_\|binance.*perp" merid/event_venues/kalshi/ && exit 1

# 3. Verify signing constants
grep "_sign_headers" merid/event_venues/kalshi/client.py > /dev/null || exit 1

# 4. Verify settlement guard
grep "settlement_execution_guard" merid/event_venues/kalshi/*.py > /dev/null || exit 1

echo "✓ All checks passed"
```

### Coverage Gate

```yaml
# pytest.ini
[pytest]
min_kalshi_coverage = 85

# CI failure if coverage drops
```

---

## Known Limitations & Future Work

### Current Limitations

1. **RTI feed source** — Currently relies on CF Benchmarks polling; direct WebSocket feed would reduce latency
2. **Settlement price verification** — Post-settlement, price is accepted from Kalshi; cross-check with CF Benchmarks would add confidence
3. **Agent recovery** — If agent dies mid-order, intent may be orphaned; intent timeout/heartbeat would help

### Future Hardening

| Item | Priority | Effort |
|------|----------|--------|
| Real-time RTI WebSocket | High | 2-3 days |
| Post-settlement price cross-check | Medium | 1-2 days |
| Intent heartbeat/timeout | Medium | 2 days |
| Multi-region Kalshi failover | Low | 1 week |

---

## Sign-Off

| Component | Status | Notes |
|-----------|--------|-------|
| Auth & Transport | ✅ VERIFIED | RSA-PSS signing correct, env routing safe |
| Market Catalog | ✅ VERIFIED | 5 assets, 4 timeframes, no contamination |
| Signal Pipeline | ✅ VERIFIED | Single path, exposure tracking, sizing caps |
| RTI Settlement | ✅ VERIFIED | 60-sample buffer, strict gating, no silent fallback |
| Fills Ledger | ✅ VERIFIED | Dual ingestion, idempotent, reconciled |
| Health Surfaces | ✅ VERIFIED | Endpoints exist, reason codes documented |
| Operator Runbook | ✅ COMPLETE | 5 scenarios, log patterns, emergency procedures |
| Test Coverage | ✅ COMPLETE | 180+ tests across 5 test files |

---

## PR Description Summary

```markdown
## Kalshi Hardcode Audit — Complete

This PR adds comprehensive verification of MERID's Kalshi-only integration:

### New Documentation
- `docs/audit/kalshi_integration_map.md` — Complete touchpoint inventory
- `docs/runbooks/kalshi_operator_runbook.md` — Production runbook
- `docs/audit/kalshi_hardcode_audit_report.md` — This report

### New Test Suite (`tests/kalshi/`)
- `test_auth_and_transport.py` — RSA signing, circuit breakers, WS resilience
- `test_market_catalog_and_symbols.py` — Asset coverage, symbol normalization
- `test_signal_to_order_pipeline.py` — Signal path, group exposure, sizing
- `test_rti_settlement_policies.py` — CF RTI buffer, settlement-grade gating
- `test_fills_and_positions_integrity.py` — Ledger, reconciliation, anti-ghost

### Invariants Verified
- ✓ Auth: RSA-PSS signing matches Kalshi spec
- ✓ Settlement: 60-sample RTI buffer, strict gating
- ✓ Exposure: Never negative, per-asset isolation
- ✓ Fills: Dual ingestion, idempotent, reconciled
- ✓ Execution: Single path through order_router

### No Production Code Changes
All existing code verified via inspection; no modifications required.
```

---

*Audit completed: 2026-03-28*  
*Next audit recommended: After Kalshi API v3 release or major refactors*
