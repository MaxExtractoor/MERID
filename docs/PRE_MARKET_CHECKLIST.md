# Pre-Market Checklist

Production audit-driven pre-market checklist for MERID Kalshi crypto trading.

**Purpose**: Ensure all production invariants are verified before enabling live trading for BTC/ETH/SOL/XRP/DOGE 15m markets.

**Reference**: PRODUCTION_AUDIT_SUMMARY_2026-04-15.md

---

## 1. Code and CI Gate

### Verify Deploy Branch
- Confirm you are on the intended deploy branch (usually `main` or a specific release branch)
  ```bash
  git branch --show-current
  git log -1 --oneline
  ```

### Run Production Audit Suite
- Run the audit suite or confirm CI already ran it for this commit:
  ```bash
  pytest -m production_audit -v
  ```

**Expected Result**:
- **19 passed** (10 regression + 9 integration)
- **0 failed**
- **0 xfailed**

**If tests fail**: Do not deploy or start live trading until the test is fixed and passing.

---

## 2. Scope and Bankroll Invariants

### Confirm Trading Scope
- Verify trading scope is unchanged: only BTC, ETH, SOL, XRP, DOGE on the 15m timeframe
- Check scope constants in `tests/test_production_scope.py`:
  ```bash
  python -c "from tests.test_production_scope import ALLOWED_SYMBOLS, ALLOWED_TIMEFRAMES; print(f'Symbols: {ALLOWED_SYMBOLS}'); print(f'Timeframes: {ALLOWED_TIMEFRAMES}')"
  ```

**Expected Result**:
- `ALLOWED_SYMBOLS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]`
- `ALLOWED_TIMEFRAMES = ["15m"]`

### Verify Bankroll Fail-Closed Configuration
- Confirm bankroll configuration is present and loaded with **fail-closed** behavior
- Check environment variables and configuration files for:
  - `KALSHI_EMAIL` and `KALSHI_PASSWORD` (or API key)
  - No default fallback equity values if environment/config is missing
  - Bankroll service configured to return 0 equity on errors

**If you intend to change scope, bankroll logic, or guards**:
1. First edit the corresponding `production_audit` test(s) in `tests/test_production_scope.py` or `tests/event_venues/kalshi/test_production_integration_vertical_slice.py`
2. Rerun `pytest -m production_audit`
3. Only proceed if tests pass

---

## 3. Orderbook Health Before Enabling Trading

### Start Services and Check Health Logs
- Start the MERID services (systemd, docker-compose, or your chosen orchestration)
- Check health logs for all 5 symbols' 15m markets

**Expected log patterns**:
```
[WS-BOOT] bridge started with tickers: KXBTC15M-T, KXETH15M-T, KXSOL15M-T, KXXRP15M-T, KXDOGE15M-T
[SNAPSHOT-BOOTSTRAP] started markets=5
[SNAPSHOT-BOOTSTRAP] complete market=KXBTC15M-T levels=2 bid=60 ask=40 mid=50
[SNAPSHOT-BOOTSTRAP] complete market=KXETH15M-T levels=2 bid=60 ask=40 mid=50
[SNAPSHOT-BOOTSTRAP] complete market=KXSOL15M-T levels=2 bid=60 ask=40 mid=50
[SNAPSHOT-BOOTSTRAP] complete market=KXXRP15M-T levels=2 bid=60 ask=40 mid=50
[SNAPSHOT-BOOTSTRAP] complete market=KXDOGE15M-T levels=2 bid=60 ask=40 mid=50
[HEALTH-CIRCUIT-BREAKER] trading enabled: 5/5 markets healthy
```

### Verify Book Initialization
- Confirm each book is set to `initialized=True` with non-null bid/ask
- Check `/internal/kalshi_health` endpoint or logs:
  ```bash
  curl http://localhost:8000/internal/kalshi_health | jq .
  ```

**Expected Result**: All 5 markets show `initialized: true` with valid `best_bid_cents` and `best_ask_cents`

### Check WS Delta Flow
- Confirm `last_update_age_ms` is low and decreasing for each symbol
- This indicates WS delta messages are flowing and being applied

**Expected Result**: `last_update_age_ms < 30000` (30s staleness threshold) for all markets

### Verify Circuit Breaker Status
- Ensure orderbook health/circuit breaker is not tripped
- No "uninitialized" or "stale" state for more than configured thresholds
  - Staleness threshold: 30s
  - Minimum healthy books: 3/5 (60% quorum)

**If any book is stuck uninitialized or stale**:
- Treat it as a blocker
- Fix the issue or add a regression/vertical slice test reproducing it before trading

---

## 4. WS Schema and Guards Sanity Checks

### Verify WS Delta Schema
- Check one or two recent WS delta log lines
- Confirm they match the **new delta schema** with `bids`/`asks` fields

**Expected log pattern**:
```
[WS-DELTA] ticker=KXBTC15M-T bids=[[60, 5], [55, 10]] asks=[[40, 8], [45, 3]] side=yes price=60 size_delta=-3
```

### Check for Schema Errors
- Verify there are no schema mismatch or parsing errors in logs
- Any such error should be treated as "no WS = no trading"

**If parsing errors appear**:
- Stop trading immediately
- Fix the schema mismatch
- Add regression test to prevent recurrence

### Verify Guards Configuration
- Confirm global guards and circuit breakers are configured and active:
  - Risk guards (GlobalRiskGuard)
  - Staleness guards (30s threshold)
  - "No WS/no book" guards
- They should be ready to block trading if invariants break

**Expected log pattern**:
```
[RISK-GUARD] GlobalRiskGuard initialized with max_cycle_risk_pct=0.02
[HEALTH-CIRCUIT-BREAKER] staleness_threshold_ms=30000 min_healthy_books=3
```

---

## 5. Vertical Slice Canary Check

### Run Vertical Slice Tests
- Run (or at least spot-check in CI) the 9 vertical slice tests
- They should all pass, validating full-cycle behavior for BTC, ETH, SOL, XRP, and DOGE on 15m

```bash
pytest tests/event_venues/kalshi/test_production_integration_vertical_slice.py -v
```

**Expected Result**:
- **9 passed** (5 asset vertical slices + 2 scope violation + 2 bankroll fail-closed)

### Canary Test Behavior
- Treat these vertical slices as canaries
- If any one fails, assume there is a real risk of orderbook or pipeline regression in production
- Pause deployment until the issue is resolved

### Add New Regression Tests
- When you discover a new class of production issue (e.g., a specific orderbook edge case):
  1. Encode it as an additional regression or slice test
  2. Add it under the `@pytest.mark.production_audit` marker
  3. Rerun `pytest -m production_audit`
  4. It becomes part of tomorrow's pre-market gate

---

## Quick Reference Commands

```bash
# Full production audit suite
pytest -m production_audit -v

# Vertical slice tests only
pytest tests/event_venues/kalshi/test_production_integration_vertical_slice.py -v

# Scope constants verification
python -c "from tests.test_production_scope import ALLOWED_SYMBOLS, ALLOWED_TIMEFRAMES; print(f'Symbols: {ALLOWED_SYMBOLS}'); print(f'Timeframes: {ALLOWED_TIMEFRAMES}')"

# Health endpoint check
curl http://localhost:8000/internal/kalshi_health | jq .

# Git status
git branch --show-current
git log -1 --oneline
```

---

## Failure Modes and Actions

| Failure Mode | Action | Block Trading? |
|--------------|--------|----------------|
| `production_audit` tests fail | Fix tests, rerun, only proceed if passing | **YES** |
| Scope constants changed | Verify intended change, update tests if needed | **YES** |
| Bankroll config missing | Configure bankroll with fail-closed behavior | **YES** |
| Book not initialized | Check WS connection, REST snapshot bootstrap | **YES** |
| Book stale (>30s) | Check WS delta flow, network connectivity | **YES** |
| WS schema parsing errors | Fix schema mismatch, add regression test | **YES** |
| Circuit breaker tripped | Investigate cause, fix underlying issue | **YES** |
| Vertical slice test fails | Debug orderbook/pipeline regression | **YES** |

---

## Total Expected Time

**60 seconds** when all checks pass:
- Code/CI gate: 10s
- Scope/bankroll invariants: 5s
- Orderbook health verification: 15s
- WS schema/guards check: 10s
- Vertical slice canary: 20s (if CI already ran, spot-check only)

**Note**: If any check fails, additional time will be required for investigation and remediation. Do not skip checks to save time.
