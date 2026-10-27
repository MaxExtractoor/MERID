# Kalshi Orderbook Pre-Session Checklist

**Purpose:** Verify Kalshi orderbook system readiness before enabling trading (2-3 minutes)

**Scope:** 5 crypto 15m markets (BTC, ETH, SOL, XRP, DOGE)

---

## Quick Verification (2 minutes)

### 1. Snapshot Bootstrap Complete
**Log Pattern:** `[SNAPSHOT-BOOTSTRAP] completed markets=5/5 succeeded=5 failed=0`

**Verification:**
```bash
# Grep for snapshot bootstrap completion
grep "SNAPSHOT-BOOTSTRAP.*completed" <log_file>
```

**Expected Output:**
```
[SNAPSHOT-BOOTSTRAP] completed markets=5/5 succeeded=5 failed=0
```

**Pass Criteria:** ✅ `succeeded=5 failed=0`

---

### 2. Production Invariant - Trading Ready
**Log Pattern:** `[PRODUCTION-INVARIANT] All 5 crypto 15m markets have snapshots - trading ready`

**Verification:**
```bash
# Grep for production invariant check
grep "PRODUCTION-INVARIANT.*trading ready" <log_file>
```

**Expected Output:**
```
[PRODUCTION-INVARIANT] All 5 crypto 15m markets have snapshots - trading ready
```

**Pass Criteria:** ✅ Log shows "trading ready" (NOT "Trading NOT ready")

---

### 3. Market Health - All Markets Initialized
**Log Pattern:** `[MARKET-STATE] health market=... initialized=True last_update_age_ms=<30000`

**Verification:**
```bash
# Grep for market health logs
grep "MARKET-STATE.*health" <log_file> | tail -5
```

**Expected Output (5 markets, one per line):**
```
[MARKET-STATE] health market=KXBTC15M-... initialized=True last_update_age_ms=16 bid=0.1 ask=99.999 mid=50.049499999999995 spread=99.899
[MARKET-STATE] health market=KXETH15M-... initialized=True last_update_age_ms=47 bid=0.097 ask=99.999 mid=50.047999999999995 spread=99.902
[MARKET-STATE] health market=KXSOL15M-... initialized=True last_update_age_ms=94 bid=0.011 ask=99.999 mid=50.004999999999995 spread=99.988
[MARKET-STATE] health market=KXXRP15M-... initialized=True last_update_age_ms=0 bid=0.15 ask=99.999 mid=50.0745 spread=99.84899999999999
[MARKET-STATE] health market=KXDOGE15M-... initialized=True last_update_age_ms=16 bid=0.71 ask=99.999 mid=50.354499999999994 spread=99.289
```

**Pass Criteria:**
- ✅ All 5 markets show `initialized=True`
- ✅ All `last_update_age_ms < 30000` (30 second threshold)
- ✅ All markets have valid `bid`, `ask`, `mid`, `spread` values

---

## Alternative: Health Endpoint Check

**Endpoint:** `GET /internal/kalshi_health`

**Verification:**
```bash
curl http://localhost:8011/internal/kalshi_health
```

**Expected Response:**
```json
{
  "status": "healthy",
  "markets": {
    "KXBTC15M-...": {"initialized": true, "last_update_age_ms": 16, "bid": 0.1, "ask": 99.999, "mid": 50.049499999999995},
    "KXETH15M-...": {"initialized": true, "last_update_age_ms": 47, "bid": 0.097, "ask": 99.999, "mid": 50.047999999999995},
    "KXSOL15M-...": {"initialized": true, "last_update_age_ms": 94, "bid": 0.011, "ask": 99.999, "mid": 50.004999999999995},
    "KXXRP15M-...": {"initialized": true, "last_update_age_ms": 0, "bid": 0.15, "ask": 99.999, "mid": 50.0745},
    "KXDOGE15M-...": {"initialized": true, "last_update_age_ms": 16, "bid": 0.71, "ask": 99.999, "mid": 50.354499999999994}
  },
  "trading_enabled": true,
  "healthy_count": 5,
  "total_count": 5
}
```

**Pass Criteria:**
- ✅ `status: "healthy"`
- ✅ All 5 markets show `initialized: true`
- ✅ All `last_update_age_ms < 30000`
- ✅ `trading_enabled: true`
- ✅ `healthy_count: 5`

---

## Failure Modes

### If Snapshot Bootstrap Failed
**Symptom:** `succeeded < 5` or `failed > 0`

**Action:**
1. Check Kalshi REST API connectivity
2. Verify API key credentials
3. Check rate limiting (10 tickers per batch with 100ms delay)
4. Review error logs for specific ticker failures

---

### If Production Invariant Shows "Trading NOT Ready"
**Symptom:** `Trading NOT ready - missing snapshots for markets: [...]`

**Action:**
1. Identify missing markets from log
2. Manually trigger snapshot fetch for missing markets
3. Re-run snapshot bootstrap if needed
4. Verify all 5 markets have `book_initialized=True`

---

### If Market Health Shows Stale Books
**Symptom:** `last_update_age_ms >= 30000` for any market

**Action:**
1. Check WebSocket connection status
2. Verify WS subscription to `orderbook_delta` channel
3. Check for WS connection errors in logs
4. If WS down, system will fall back to REST (but will show degraded health)

---

### If Health Endpoint Returns 500 or Errors
**Symptom:** HTTP 500 or error response from `/internal/kalshi_health`

**Action:**
1. Check server logs for exception
2. Verify market_state store is initialized
3. Check for circular import errors (should be fixed in v3.0.0+)
4. Restart server if needed

---

## Production Thresholds (Immutable)

- **MAX_BOOK_STALENESS_MS:** 30000 (30 seconds)
- **MIN_HEALTHY_BOOKS_FOR_TRADING:** 3 (out of 5)
- **ALLOWED_UNDERLYINGS:** BTC, ETH, SOL, XRP, DOGE
- **ALLOWED_TIMEFRAMES:** 15m only

---

## Staged Rollout Procedure

1. **Phase 1:** Paper/live no orders - verify all checks pass
2. **Phase 2:** Micro orders (1-2 contracts) - monitor for 30 minutes
3. **Phase 3:** Gradual scaling - increase size based on performance

**Before each phase escalation:** Re-run this checklist to confirm continued health.

---

## Related Documentation

- [KALSHI_PRODUCTION_INVARIANTS.md](./KALSHI_PRODUCTION_INVARIANTS.md) - Full production invariants specification
- [kalshi_workflow.md](./UI/kalshi_workflow.md) - Kalshi integration workflow
- Git tag: `v3.0.0-kalshi-orderbook-baseline` - Baseline release with all hardening
