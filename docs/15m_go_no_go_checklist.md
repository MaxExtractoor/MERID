# 15m Stack Go/No-Go Checklist

**Purpose:** Define the criteria for enabling real money trading on the 15m Kalshi crypto stack for each new version.

**Principle:** The 15m stack must pass all safety, functionality, and operational checks before being approved for live trading with real capital.

**Runtime Mode:** All checks run under `MERID_RUNTIME_MODE=15m_live`.

---

## Checklist Overview

The go/no-go checklist is organized into five categories:

1. **Test Validation** - All tests must pass
2. **Health Snapshot** - System health must be clean
3. **CI Validation** - Stack integrity must be verified
4. **Operational Readiness** - Soak testing and monitoring
5. **Risk Management** - Risk parameters and limits

Each category has specific criteria that must be met before the version is approved for real money.

---

## 1. Test Validation

### 1.1 Scenario Tests (18 tests)

**Status:** ✅ PASS / ❌ FAIL

**Command:**
```bash
pytest tests/15m_scenario_tests/ -v
```

**Criteria:**
- All 18 scenario tests must pass
- No skipped tests
- No warnings or errors

**Test Coverage:**
- 4 WebSocket scenarios (down, high latency, reconnect, healthy)
- 6 Spot scenarios (stale, fresh, boundary, restart, missing)
- 8 Orderbook scenarios (dual-sided, one-sided, SUSPECT, stale, low liquidity, wide spread)

**Approval:** Approved if all 18 tests pass.

---

### 1.2 Trade Path Tests (40 tests)

**Status:** ✅ PASS / ❌ FAIL

**Command:**
```bash
pytest tests/15m_trade_path_tests/ -v
```

**Criteria:**
- All 40 trade path tests must pass
- No skipped tests
- No warnings or errors

**Test Coverage:**
- 8 Signal generation tests
- 8 Order placement tests
- 9 Fill confirmation tests
- 9 PnL calculation tests
- 5 Happy path end-to-end tests

**Approval:** Approved if all 40 tests pass.

---

### 1.3 Test Coverage

**Status:** ✅ PASS / ❌ FAIL

**Command:**
```bash
pytest tests/15m_scenario_tests/ tests/15m_trade_path_tests/ --cov=merid --cov-report=term-missing
```

**Criteria:**
- Code coverage for 15m modules ≥ 80%
- No critical paths uncovered

**Approval:** Approved if coverage ≥ 80%.

---

## 2. Health Snapshot

### 2.1 Health Snapshot Clean (30-minute soak)

**Status:** ✅ PASS / ❌ FAIL

**Command:**
```bash
# Start 15m stack
./start_15m.ps1

# Monitor health snapshot
curl http://localhost:8000/api/v1/health-snapshot/summary
```

**Criteria:**
- Run 15m stack for 30 minutes in paper trading mode
- Health snapshot must show:
  - WS state: CONNECTED
  - Spot age: < 30s
  - Book freshness: < 10s
  - Book consistency: GOOD
  - Liquidity: PASS (dual-sided)
  - Data quality: PASS
  - Edge: PASS (≥ 1%)
  - Risk: PASS (has capacity)
  - Overall gate: PASS

**Approval:** Approved if all health metrics remain healthy for 30 minutes.

---

### 2.2 Health Snapshot API Accessible

**Status:** ✅ PASS / ❌ FAIL

**Command:**
```bash
curl http://localhost:8000/api/v1/health-snapshot/
curl http://localhost:8000/api/v1/health-snapshot/summary
curl http://localhost:8000/health-snapshot/scenario
```

**Criteria:**
- All health snapshot endpoints return 200 OK
- Response time < 100ms
- JSON structure is valid

**Approval:** Approved if all endpoints accessible and responsive.

---

### 2.3 Scenario Mapping

**Status:** ✅ PASS / ❌ FAIL

**Command:**
```bash
curl http://localhost:8000/api/v1/health-snapshot/scenario
```

**Criteria:**
- Scenario mapping returns no matched scenarios (no failure conditions)
- If scenarios are matched, they must be resolved before approval

**Approval:** Approved if no failure scenarios are matched.

---

## 3. CI Validation

### 3.1 Stack Integrity Check

**Status:** ✅ PASS / ❌ FAIL

**Command:**
```bash
python scripts/validate_15m_stack.py
```

**Criteria:**
- No forbidden legacy modules loaded
- Profile is `kalshi_crypto_15m_v2`
- Runtime mode is `15m_live`
- Required environment variables present

**Forbidden Modules:**
- `merid.main`
- `merid.loop`
- `merid.prediction.agent_grid`
- `web.main`
- `merid.core`

**Approval:** Approved if all checks pass.

---

### 3.2 Import Kill-Switch

**Status:** ✅ PASS / ❌ FAIL

**Criteria:**
- Import kill-switch in `main_15m_lean.py` is active
- No legacy module imports detected at runtime

**Approval:** Approved if kill-switch is active and no legacy imports detected.

---

### 3.3 Mode Guards

**Status:** ✅ PASS / ❌ FAIL

**Criteria:**
- Mode guards in `settings.py` and `startup_validations.py` are active
- No warnings logged for legacy settings access in 15m mode

**Approval:** Approved if mode guards are active and no warnings.

---

## 4. Operational Readiness

### 4.1 30-Minute Soak Test

**Status:** ✅ PASS / ❌ FAIL

**Procedure:**
1. Start 15m stack in paper trading mode
2. Monitor for 30 minutes
3. Check logs for errors or warnings
4. Verify no crashes or restarts

**Criteria:**
- No errors in logs
- No crashes or restarts
- Stable memory usage (no leaks)
- Stable CPU usage (no spikes)

**Approval:** Approved if soak test passes without issues.

---

### 4.2 Monitoring Setup

**Status:** ✅ PASS / ❌ FAIL

**Criteria:**
- Health snapshot API is monitored
- Alerts configured for:
  - WS disconnection
  - Spot staleness (> 30s)
  - Book staleness (> 10s)
  - Book SUSPECT state
  - Risk budget exhaustion
  - Gate decision REJECT

**Approval:** Approved if monitoring and alerts are configured.

---

### 4.3 Logging Setup

**Status:** ✅ PASS / ❌ FAIL

**Criteria:**
- Structured logging is enabled
- Health snapshot logging is enabled
- Logs are stored with retention policy
- Log aggregation is configured

**Approval:** Approved if logging is properly configured.

---

### 4.4 Rollback Plan

**Status:** ✅ PASS / ❌ FAIL

**Criteria:**
- Previous version is tagged and accessible
- Rollback procedure is documented
- Rollback can be executed within 5 minutes

**Approval:** Approved if rollback plan is in place.

---

## 5. Risk Management

### 5.1 Risk Budget Configuration

**Status:** ✅ PASS / ❌ FAIL

**Criteria:**
- Risk budget is configured appropriately for real money
- Risk limits are enforced
- Risk budget utilization is monitored

**Approval:** Approved if risk budget is properly configured.

---

### 5.2 Position Limits

**Status:** ✅ PASS / ❌ FAIL

**Criteria:**
- Position limits are configured
- Position limits are enforced
- Position size respects risk budget

**Approval:** Approved if position limits are properly configured.

---

### 5.3 Edge Thresholds

**Status:** ✅ PASS / ❌ FAIL

**Criteria:**
- Edge threshold is ≥ 1%
- Edge calculation is validated
- Edge is monitored for anomalies

**Approval:** Approved if edge thresholds are properly configured.

---

### 5.4 Market Selection

**Status:** ✅ PASS / ❌ FAIL

**Criteria:**
- Only approved markets are traded (BTC, ETH, SOL, XRP, DOGE)
- Market liquidity is sufficient
- Market volatility is within acceptable range

**Approval:** Approved if market selection is appropriate.

---

## Approval Process

### Step 1: Run All Checks

Execute all checklist items in order:

1. Test Validation
2. Health Snapshot
3. CI Validation
4. Operational Readiness
5. Risk Management

### Step 2: Document Results

Record results for each checklist item:

```markdown
## Go/No-Go Checklist Results - Version X.Y.Z

### 1. Test Validation
- Scenario Tests: ✅ PASS (18/18)
- Trade Path Tests: ✅ PASS (40/40)
- Test Coverage: ✅ PASS (85%)

### 2. Health Snapshot
- Health Snapshot Clean: ✅ PASS (30-minute soak)
- Health Snapshot API: ✅ PASS
- Scenario Mapping: ✅ PASS (no failures)

### 3. CI Validation
- Stack Integrity: ✅ PASS
- Import Kill-Switch: ✅ PASS
- Mode Guards: ✅ PASS

### 4. Operational Readiness
- 30-Minute Soak: ✅ PASS
- Monitoring Setup: ✅ PASS
- Logging Setup: ✅ PASS
- Rollback Plan: ✅ PASS

### 5. Risk Management
- Risk Budget: ✅ PASS
- Position Limits: ✅ PASS
- Edge Thresholds: ✅ PASS
- Market Selection: ✅ PASS

### Overall Decision: ✅ GO
```

### Step 3: Approval

**Go Decision:** All checklist items pass.

**No-Go Decision:** Any checklist item fails.

**Conditional Go:** Minor issues that can be mitigated with additional monitoring or safeguards.

---

## Emergency Stop Criteria

If any of the following conditions occur during live trading, immediately stop trading:

1. **WS Disconnection:** WS state is DISCONNECTED for > 60 seconds
2. **Spot Staleness:** Spot age > 60 seconds
3. **Book Staleness:** Book age > 30 seconds
4. **Book SUSPECT:** Book consistency is SUSPECT for > 30 seconds
5. **Risk Exhaustion:** Risk budget utilization > 95%
6. **Gate Reject:** Overall gate decision is REJECT for > 5 consecutive cycles
7. **Order Failure:** Order placement fails for > 3 consecutive attempts
8. **Fill Failure:** Fill confirmation fails for > 3 consecutive attempts
9. **PnL Anomaly:** PnL exceeds expected range by > 50%
10. **System Error:** Any unhandled exception or crash

---

## Version History

| Version | Date | Decision | Notes |
|---------|------|----------|-------|
| v1.0.0 | 2026-06-05 | ✅ GO | Initial production deployment |
| v1.0.1 | TBD | TBD | TBD |

---

## Related Documentation

- `docs/kalshi_15m_stack.md` - Canonical 15m stack definition
- `tests/15m_scenario_tests/README.md` - Scenario test documentation
- `tests/15m_trade_path_tests/README.md` - Trade path test documentation
- `docs/15m_health_snapshot.md` - Health snapshot documentation
- `scripts/validate_15m_stack.py` - CI validation script

---

**End of Go/No-Go Checklist**
