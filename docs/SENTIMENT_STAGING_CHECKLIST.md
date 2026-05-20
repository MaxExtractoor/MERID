# Sentiment Staging Checklist — Hard-Fail Scenario

**Purpose:** Verify that the 15m Kalshi crypto trading path (BTC/ETH/SOL/XRP/DOGE) operates correctly when sentiment services fail completely.

**Context:** Per `SENTIMENT_ISOLATION_15M.md`, sentiment is telemetry-only and must not gate execution. This checklist provides a temporary stand-in for a proper staging environment until full staging infrastructure is available.

**Last Updated:** 2026-05-14

---

## Pre-Flight Setup

### 1. Environment Configuration

Set the following environment variables to force sentiment service to fail immediately:

```bash
# Force sentiment service constructor to raise on initialization
export MERID_SENTIMENT_FORCE_FAIL=true

# Ensure 15m profile is active
export MERID_PM_PROFILE=kalshi_crypto_15m_v2

# Verify sentiment execution is disabled (should be set by profile)
export ENABLE_SENTIMENT_TRUTH=false
```

### 2. Kalshi API Configuration

Ensure Kalshi API credentials are set for demo or live mode:

```bash
# Demo mode (recommended for testing)
export KALSHI_ENV=demo
export KALSHI_API_BASE_URL=https://demo-api.kalshi.co/trade-api/v2

# Or live mode (only for production staging)
export KALSHI_ENV=live
export KALSHI_API_BASE_URL=https://api.elections.kalshi.com/trade-api/v2
```

---

## Verification Steps

### Step 1: Startup Validation

**Expected:** System starts successfully despite sentiment service failure.

```bash
# Start the 15m crypto agents
python -m merid.prediction.agent_grid --profile kalshi_crypto_15m_v2
```

**Checklist:**
- ✅ AgentGrid initializes without blocking on sentiment service
- ✅ Logs contain `[SENTIMENT-BUS-ERROR]` tag for sentiment service failure
- ✅ Agents reach ready state
- ✅ No startup failures related to sentiment

**Expected Log Output:**
```
[SENTIMENT-BUS-ERROR] Sentiment service start failed: Forced failure via MERID_SENTIMENT_FORCE_FAIL
[SENTIMENT-BUS-ERROR] Market Mood Bus start failed: Forced failure via MERID_SENTIMENT_FORCE_FAIL
AgentGrid initialized successfully with 15m crypto agents
```

---

### Step 2: Catalog Refresh Validation

**Expected:** Catalog refresh completes and filters to exactly 5 allowed markets.

**Checklist:**
- ✅ Catalog refresh completes without sentiment dependency
- ✅ Exactly 5 markets returned: BTC, ETH, SOL, XRP, DOGE (15m timeframe)
- ✅ AllowedMarketPolicy filters correctly (asset, ticker, category only)
- ✅ SignalUniverseService initialized with filtered universe

**Expected Log Output:**
```
[ALLOWED-MARKET-POLICY] Filtered markets: 5 allowed out of N total
[SIGNAL-UNIVERSE-SERVICE] Initialized with 5 markets, 5 assets
```

---

### Step 3: Agent Tick Validation

**Expected:** Agents tick and produce orders when EV/risk allow.

**Checklist:**
- ✅ At least one agent tick completes successfully
- ✅ Orders are emitted when EV > threshold and risk constraints satisfied
- ✅ Order router processes orders without sentiment scaling
- ✅ No sentiment-related order rejections

**Expected Log Output:**
```
[order-router] 15m CRYPTO ORDER: KXBTC15M-... — sentiment scaling disabled per isolation contract
[order-router] 15m CRYPTO ORDER: KXBTC15M-... — sentiment cap check skipped per isolation contract
[KALSHI_ORDER_RESULT] ticker=KXBTC15M-... status=accepted
```

---

### Step 4: Portfolio Validation

**Expected:** Portfolio tracking works correctly without sentiment.

**Checklist:**
- ✅ Fills ledger records fills correctly
- ✅ Position cache updates from fills ledger
- ✅ PnL calculation is sentiment-free
- ✅ Portfolio reconciliation completes without errors

**Expected Log Output:**
```
[fills_ledger] http_ingest fill_id=... order_id=... ticker=KXBTC15M-... side=YES action=FILL
[position_cache] Reconciled with fills_ledger: N positions updated
```

---

## Failure Mode Testing

### Test A: Sentiment Bus Hard-Fail

**Setup:** `MERID_SENTIMENT_FORCE_FAIL=true`

**Expected:** All steps above succeed.

### Test B: Sentiment Bus Disabled

**Setup:** `ENABLE_SENTIMENT_TRUTH=false` (default for 15m profile)

**Expected:** All steps above succeed (same as hard-fail).

### Test C: Sentiment Bus Slow/Timeout

**Setup:** Mock sentiment service with 30s delay

**Expected:** All steps above succeed (non-blocking timeout handling).

---

## Success Criteria

The staging validation passes if:

1. ✅ System starts successfully with sentiment service failure
2. ✅ Catalog refresh returns exactly 5 markets (BTC/ETH/SOL/XRP/DOGE 15m)
3. ✅ Agents tick and produce orders when EV/risk allow
4. ✅ Orders are routed without sentiment scaling or cap checks
5. ✅ Portfolio tracking works correctly
6. ✅ All sentiment failures are logged with `[SENTIMENT-BUS-ERROR]` tag

---

## Transition to Full Staging

When proper staging infrastructure is available:

1. Replace this local checklist with automated staging tests
2. Integrate with CI/CD pipeline for pre-production validation
3. Add automated regression tests for sentiment isolation
4. Monitor sentiment bus health separately (telemetry only, not gating)

---

## References

- `SENTIMENT_ISOLATION_15M.md` — Sentiment isolation contract
- `tests/test_sentiment_isolation_15m.py` — Unit tests for sentiment isolation
- `merid/prediction/startup_validations.py` — Startup validation checks
- `merid/event_venues/kalshi/order_router.py` — Order router sentiment bypass logic
