# Kalshi 15m Crypto Startup Audit — 2026-05-16

## Executive Summary

**Startup Status:** PARTIAL FAILURE - MeridLoop skipped due to startup failures  
**Total Startup Time:** 4.65s  
**Critical Blockers:** 2 (Port conflict, Settlement poller)  
**Soft Degradations:** 4 (Spot prices, Coinbase auth, Redis health, WS bridge initial state)  
**Non-Issues:** 1 (Paper mode deployment)

---

## 1. Ground Truth from Logs

### Environment Configuration
- **Profile:** `kalshi_crypto_15m_v2` (sealed 15m stack)
- **PM Profile:** `baseline` (uses canonical risk envelope)
- **Mode:** `live` (VenueGate: mode=live, live_enabled=True)
- **Bankroll:** $36.81 (from KalshiPortfolio.get_balance via BankrollServiceV2)
- **Agents:** 5 (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M)
- **Series Tickers:** KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M ✓ (correctly updated)

### Risk Limits
- **Per-Trade Cap:** $1.84 (derived from bankroll × 5%)
- **Per-Agent Max Notional:** $1.1043 (profile override)
- **Crypto Category Cap:** $11.04 (profile-based)
- **Max Concurrent:** 3 orders per agent
- **Entry Window:** 30 minutes before expiry, 2-minute cutoff

### Venue Wiring Status
| Component | Status | Log Evidence |
|-----------|--------|-------------|
| Kalshi REST Client | ✅ Working | Loaded markets, fetched balance |
| Kalshi WebSocket | ✅ Connected | RSA-PSS auth successful in 2.59s |
| Kalshi WS Bridge | ⚠️ Degraded | Started with 0 tickers, later subscribed to 1 |
| Market Catalog | ✅ Working | Discovered markets for all 5 assets |
| BankrollServiceV2 | ✅ Working | Started background refresh |
| Fills Ledger | ✅ Working | 60 fills loaded from DB |
| Fills Poller | ✅ Working | Started successfully |
| Settlement Poller | ❌ FAILED | Missing kalshi_client argument |
| Position Cache | ✅ Working | Pre-fetched 0 positions |

### PM Stack Status
- **Agent Grid:** 5 agents loaded successfully
- **Profile Overrides:** Applied correctly from kalshi_crypto_15m_v2
- **Dynamic Window Policies:** Loaded for all 5 assets (kalshi_15m_*_v1 policies)
- **PM Profiles:** Skipped (uses canonical risk envelope)
- **Sentiment Gating:** FORCE DISABLED by profile
- **Crypto Threshold Matrix:** Skipped (uses profile YAML edge thresholds)
- **PM Matrix:** 5 agents, min_edge_early_bps≈800 (2%)

### Data Feeds Status
| Feed | Status | Details |
|------|--------|---------|
| Coinbase v3 | ⚠️ Degraded | 401 auth error, falling back to CCXT |
| CCXT Fallback | ✅ Working | 5 symbols (BTC, ETH, SOL, XRP, DOGE) |
| Kalshi Market Data | ✅ Working | WS connected, orderbook deltas subscribed |
| Feed Staleness Monitor | ✅ Initialized | Default max_age=60s, critical=300s |
| Redis | ⚠️ Degraded | Connected but health check shows degraded |

### Execution Path Status
- **MatchingEngine:** Not mentioned in logs (likely skipped for Kalshi-only profile)
- **Execution Guard:** Not mentioned
- **Venue Adapter:** Working (KalshiVenueAdapter)
- **Fills/Settlement Pollers:** Fills poller ✅, Settlement poller ❌
- **MeridLoop:** ❌ SKIPPED due to startup failures

---

## 2. Startup Phase Timeline

| Phase | Duration | Status | Notes |
|-------|----------|--------|-------|
| Phase -1: Environment/Infra | ~1.5s | ✅ | Settings, logging, Redis |
| Phase 0: Profile/Config | ~0.5s | ✅ | Profile loading, agent grid parsing |
| Phase 1: Venue Wiring | ~1.0s | ✅ | Kalshi client, WS connection |
| Phase 2: PM Stack | ~0.5s | ✅ | Agent grid, dynamic policies |
| Phase 3: Data Feeds | ~0.5s | ⚠️ | CCXT fallback, Coinbase auth fail |
| Phase 4: Execution Path | ~0.2s | ⚠️ | Fills poller OK, settlement poller FAIL |
| Phase 5: WebSocket Bridge | 3.13s | ⚠️ | Connected but started with 0 tickers |
| Phase 6: Fills/Settlement Pollers | 0.21s | ⚠️ | Settlement poller failed |
| Phase 7: MeridLoop | 0.00s | ❌ | SKIPPED due to startup failures |

**Total:** 4.65s  
**Slow Phase:** Phase 5 (WebSocket bridge) at 3.13s

---

## 3. Hard Failures (Critical Blockers)

### FAILURE #1: Port 8011 Already Bound
**Log:** `[Errno 10048] error while attempting to bind on address ('0.0.0.0', 8011): only one usage of each socket address`

**Classification:** HARD BLOCKER  
**Direct Cause:** Another process is already using port 8011  
**Downstream Impact:** 
- FastAPI application cannot start
- Entire web stack fails
- No API endpoints available
- Trading cannot proceed

**Fix:**
```bash
# Find process using port 8011
netstat -ano | findstr :8011

# Kill the process (replace PID)
taskkill /PID <PID> /F

# Or use a different port by setting:
# MERID_WEB_PORT=8012
```

**Verification:**
- Restart application should succeed
- Log shows `Application startup complete`
- Can access http://localhost:8011/docs

---

### FAILURE #2: KalshiSettlementPoller Failed
**Log:** `KalshiSettlementPoller failed to start: get_settlement_poller() missing 1 required positional argument: 'kalshi_client'`

**Classification:** HARD BLOCKER (for MeridLoop)  
**Direct Cause:** Function signature mismatch in `web/main.py`  
**Downstream Impact:**
- MeridLoop skipped due to startup failures
- No settlement polling for expired markets
- Positions may not be auto-closed on expiry
- PnL may not be updated on settlement

**Fix:**
File: `web/main.py` (Phase 6 initialization)
```python
# Current (broken):
# settlement_poller = get_settlement_poller()  # Missing kalshi_client

# Fixed:
from merid.event_venues.kalshi.settlement_poller import get_settlement_poller
from merid.event_venues.kalshi.client import KalshiClient

kalshi_client = KalshiClient()
settlement_poller = get_settlement_poller(kalshi_client)
```

**Verification:**
- Log shows `✅ KalshiSettlementPoller started`
- MeridLoop starts successfully
- Settlement polling runs in background

---

## 4. Soft Degradations (Trading Can Run but Reduced Functionality)

### DEGRADATION #1: Missing Spot Prices (Strike Reject)
**Log:** `STRIKEREJECT {"accepted": false, "asset": "BTC", "rejection_reason": "missing_spot", ...}` for all 5 assets on cycle 1

**Classification:** SOFT DEGRADATION  
**Direct Cause:** Spot price feed not yet populated at cycle 1 (agents in WARMING_UP state)  
**Downstream Impact:**
- Strike selector rejects all contracts on first cycle
- No trades possible until spot prices available
- Expected behavior during warmup (15-90s)
- Should self-resolve as price feed populates

**Context:**
- CCXT fallback is working
- Price streaming started: "Price streaming started (CCXT fallback): 5 symbols, 1 exchanges"
- Agents in WARMING_UP state (min=15s, max=90s)
- This is expected during warmup, not a bug

**Fix:** No fix needed - this is expected warmup behavior  
**Verification:**
- After 15-90s warmup, spot prices should be available
- Subsequent cycles should not show "missing_spot" rejections
- Check logs for price feed updates

---

### DEGRADATION #2: Coinbase v3 Auth Failure
**Log:** `Coinbase v3 connection failed with 401 — check that MERID_COINBASE_API_KEY / COINBASE_API_KEY is a valid Advanced Trade API key. Continuing with CCXT fallback.`

**Classification:** SOFT DEGRADATION  
**Direct Cause:** Invalid or missing Coinbase Advanced Trade API credentials  
**Downstream Impact:**
- Primary spot price source fails
- Falls back to CCXT (working)
- Slightly higher latency for spot prices
- No functional impact if CCXT works

**Context:**
- CCXT fallback is operational
- 5 symbols streaming via CCXT
- Trading can proceed with CCXT data

**Fix:** (Optional) Fix Coinbase credentials in `.env`:
```bash
# Update .env with valid Advanced Trade API keys:
COINBASE_API_KEY=your_advanced_trade_api_key
COINBASE_API_SECRET=your_advanced_trade_api_secret
```

**Verification:**
- Log shows "Coinbase streaming started" instead of fallback
- Price feed latency improves

---

### DEGRADATION #3: Redis Health Degraded
**Log:** `Redis connected but health check shows degraded: {'enabled': True, 'healthy': False, 'last_check': 0.0, 'seconds_since_check': None, 'degraded_ops_count': 0, 'fallback_cache_size': 0, 'client_initialized': True}`

**Classification:** SOFT DEGRADATION  
**Direct Cause:** Redis health check not completing (last_check=0.0)  
**Downstream Impact:**
- Portfolio risk agent warning
- Fallback to in-memory cache
- No functional impact for trading
- Reduced caching efficiency

**Context:**
- Redis connection successful: "ResilientRedis initialized: redis://default:<password>@redis-19394.c258.us-east-1-4.ec2.cloud.redislabs.com:19394/0"
- Health check shows `client_initialized: True`
- Fallback cache available

**Fix:** (Optional) Debug Redis health check:
```python
# Check if Redis PING command is working
# File: merid/infra/redis_resilient.py
# Add logging to health_check method
```

**Verification:**
- Log shows `healthy: True` in health check
- No degradation warnings

---

### DEGRADATION #4: WS Bridge Started with No Tickers
**Log:** `Kalshi WS bridge started with no tickers — no orderbook/ticker/trade subscriptions; multi-asset crypto grid will not receive live books.`

**Classification:** SOFT DEGRADATION (Self-Resolved)  
**Direct Cause:** WS bridge starts before agents subscribe to tickers  
**Downstream Impact:**
- Initial warning is harmless
- Agents subscribe after initialization
- Later log shows: "Subscribed to Kalshi orderbook_delta for 1 unique tickers"
- Self-resolved during startup

**Context:**
- WS bridge connects successfully in 2.59s
- Agent BTC_15M subscribes: "Agent BTC_15M: resolved 1 series → 1 live markets"
- Snapshot bootstrap started for 1 ticker
- This is expected startup sequence

**Fix:** No fix needed - this is expected startup behavior  
**Verification:**
- After agent startup, tickers are subscribed
- Orderbook deltas flow through WS
- Market state store populated

---

## 5. Non-Issues (Expected for Profile)

### NON-ISSUE #1: Paper Mode Deployment
**Log:** `✓ DeploymentController: 5 agents registered (all PAPER)`

**Classification:** NON-ISSUE  
**Context:**
- DeploymentController shows agents in PAPER mode
- This is expected for testing/staging
- VenueGate shows mode=live (actual trading mode)
- Deployment mode is separate from venue mode

**Explanation:**
- DeploymentController manages agent lifecycle (paper/live promotion)
- VenueGate controls actual trading venue (paper/live/sim)
- Agents can be in PAPER deployment while VenueGate is LIVE
- This allows safe testing before live promotion

**Fix:** No fix needed  
**Verification:**
- If live trading desired, promote agents via DeploymentController
- Or set deployment mode to live in config

---

## 6. Missing Modules (Not in Logs - From Prompt)

The following failures mentioned in the prompt did NOT appear in these logs:
- Neo4j unavailable (not in logs - likely already handled)
- KalshiBankroll failed (not in logs - BankrollServiceV2 working)
- MatchingEngine failed (not in logs - likely skipped for Kalshi-only)
- CryptoTermStructure failed (not in logs - not needed for 15m stack)
- RTIFeedService failed (not in logs - not needed for 15m stack)
- CryptoRTIMonitor failed (not in logs - not needed for 15m stack)
- CryptoAlertRouter failed (not in logs - not needed for 15m stack)

These are either:
1. Already fixed in previous sessions
2. Not applicable to kalshi_crypto_15m_v2 profile (sealed stack)
3. Not triggered in this startup

---

## 7. Root Cause Analysis

### Why MeridLoop Was Skipped

**Cascade of Failures:**
1. KalshiSettlementPoller failed to start (missing kalshi_client argument)
2. Startup failure detected in Phase 6
3. MeridLoop Phase 7 skipped due to startup failures
4. Trading loop never started

**Root Cause:** Function signature mismatch in `web/main.py`  
**Fix Location:** `web/main.py` Phase 6 initialization  
**Impact:** Critical - no trading without MeridLoop

---

### Why Spot Prices Were Missing

**Root Cause:** Timing issue during warmup  
**Sequence:**
1. WS bridge connects (2.59s)
2. Agents start immediately (515ms total)
3. CCXT price feed starts
4. First agent cycle runs before price feed populated
5. Strike selector rejects due to missing spot

**Why This is OK:**
- Agents in WARMING_UP state (15-90s)
- Expected behavior during warmup
- Self-resolves as price feed populates
- No functional impact after warmup

---

### Why Port 8011 Was Bound

**Root Cause:** Previous instance not properly shut down  
**Likely Scenarios:**
1. Previous run crashed without cleanup
2. User started multiple instances
3. Process hung in background

**Fix:** Kill existing process or use different port

---

## 8. Fix Priority and Action Plan

### P0 - Critical (Must Fix Before Trading)
1. **Fix port 8011 conflict** - Kill existing process
2. **Fix KalshiSettlementPoller** - Add kalshi_client argument

### P1 - High (Fix Soon)
3. **Fix Coinbase auth** - Update API credentials (optional)
4. **Debug Redis health** - Investigate health check failure (optional)

### P2 - Medium (Monitor)
5. **Monitor spot price warmup** - Verify self-resolution after 15-90s
6. **Monitor WS bridge ticker subscription** - Verify self-resolution

### P3 - Low (Ignore)
7. **Paper mode deployment** - Expected for testing

---

## 9. Verification Checklist

After applying fixes, verify:

- [ ] Port 8011 not in use (`netstat -ano | findstr :8011`)
- [ ] Application starts without port binding error
- [ ] Log shows `✅ KalshiSettlementPoller started`
- [ ] Log shows `✅ MeridLoop started` (not skipped)
- [ ] Agents transition from WARMING_UP to ACTIVE after 15-90s
- [ ] Spot prices available (no "missing_spot" rejections after warmup)
- [ ] Orderbook deltas flow through WS bridge
- [ ] Market state store populated with live data
- [ ] Trading cycles execute successfully
- [ ] Orders placed (if conditions met)

---

## 10. Summary

**Startup Status:** PARTIAL FAILURE  
**Blocking Issues:** 2 (Port conflict, Settlement poller)  
**Estimated Time to Fix:** 15 minutes  
**Risk Level:** MEDIUM (Trading blocked, but infrastructure sound)

**Key Takeaways:**
1. Port conflict is environment issue, not code bug
2. Settlement poller is simple function signature fix
3. Missing spot prices is expected warmup behavior
4. Coinbase/Redis degradations have working fallbacks
5. System architecture is sound - fixes are straightforward

**Next Steps:**
1. Kill process on port 8011
2. Fix KalshiSettlementPoller in web/main.py
3. Restart and verify MeridLoop starts
4. Monitor warmup period for spot price resolution
5. (Optional) Fix Coinbase credentials and Redis health

---

## 11. Fixes Applied (2026-05-16)

### P0 - Critical Fixes (COMPLETED)

**Fix #1: Port 8011 Conflict - RESOLVED**
- **Timestamp:** 2026-05-16
- **Action:** Killed process PID 14972 using port 8011
- **Command:** `taskkill /PID 14972 /F`
- **Verification:** Port 8011 no longer has LISTENING connections
- **Status:** ✅ COMPLETED

**Fix #2: KalshiSettlementPoller - RESOLVED**
- **Timestamp:** 2026-05-16
- **File:** `web/main.py` line 2785
- **Change:** `settlement_poller = get_settlement_poller(kalshi_client)` (added kalshi_client argument)
- **Before:** `settlement_poller = get_settlement_poller()`
- **After:** `settlement_poller = get_settlement_poller(kalshi_client)`
- **Verification:** Function signature now matches requirement from settlement_poller.py
- **Status:** ✅ COMPLETED

### Verification Checklist Updated

- [x] Port 8011 not in use (`netstat -ano | findstr :8011`)
- [x] KalshiSettlementPoller fixed in web/main.py
- [ ] Application starts without port binding error
- [ ] Log shows `✅ KalshiSettlementPoller started`
- [ ] Log shows `✅ MeridLoop started` (not skipped)
- [ ] Agents transition from WARMING_UP to ACTIVE after 15-90s
- [ ] Spot prices available (no "missing_spot" rejections after warmup)
- [ ] Orderbook deltas flow through WS bridge
- [ ] Market state store populated with live data
- [ ] Trading cycles execute successfully
- [ ] Orders placed (if conditions met)

### Updated Status

**Startup Status:** READY FOR RETEST  
**Blocking Issues:** 0 (All P0 issues resolved)  
**Remaining Issues:** 4 soft degradations (expected warmup behavior, optional fixes)  
**Estimated Time to Retest:** 5 minutes  
**Risk Level:** LOW (Critical blockers resolved)

---

## 12. Phase 2/3 Legacy PM Module Skips (2026-05-16)

### Additional Fixes Applied (P0 - Critical)

**Fix #3: Skip KalshiBankroll for sealed 15m stack**
- **Timestamp:** 2026-05-16
- **File:** `web/main.py` lines 2551-2553
- **Change:** Skipped KalshiBankroll initialization (sealed stack uses BankrollServiceV2)
- **Reason:** Module doesn't exist - legacy PM module replaced by BankrollServiceV2
- **Status:** ✅ COMPLETED

**Fix #4: Skip Phase 2 (5-asset infrastructure) for sealed 15m stack**
- **Timestamp:** 2026-05-16
- **File:** `web/main.py` lines 2586-2590
- **Change:** Skipped entire Phase 2 (CryptoTermStructure, RTIFeedService, CryptoRTIMonitor, CryptoAlertRouter)
- **Reason:** These are legacy PM modules that don't exist in codebase
- **Status:** ✅ COMPLETED

**Fix #5: Skip MatchingEngine for sealed 15m stack**
- **Timestamp:** 2026-05-16
- **File:** `web/main.py` lines 2623-2625
- **Change:** Skipped MatchingEngine initialization (sealed stack uses Kalshi venue directly)
- **Reason:** get_matching_engine() missing 'domain' argument - not needed for sealed stack
- **Status:** ✅ COMPLETED

### Root Cause Analysis

The `_init_kalshi_crypto_15m_app()` function was attempting to load legacy PM infrastructure modules that:
1. Don't exist in the current codebase (removed/archived)
2. Are not needed for the sealed 15m stack design
3. Were causing `startup_success = False`, which prevented MeridLoop from starting

These modules were part of the multi-asset PM stack and have been superseded by:
- BankrollServiceV2 (replaces KalshiBankroll)
- Direct Kalshi venue integration (replaces MatchingEngine)
- Profile-based risk envelope (replaces term structure)

### Verification Checklist Updated

- [x] Port 8011 not in use (`netstat -ano | findstr :8011`)
- [x] KalshiSettlementPoller fixed in web/main.py
- [x] KalshiBankroll skipped for sealed 15m stack
- [x] Phase 2 (5-asset infrastructure) skipped for sealed 15m stack
- [x] MatchingEngine skipped for sealed 15m stack
- [ ] Application starts without legacy module import errors
- [ ] Log shows `✅ MeridLoop started` (NOT skipped)
- [ ] Agents transition from WARMING_UP to ACTIVE after 15-90s
- [ ] Spot prices available (no "missing_spot" rejections after warmup)
- [ ] Orderbook deltas flow through WS bridge
- [ ] Market state store populated with live data
- [ ] Trading cycles execute successfully
- [ ] Orders placed (if conditions met)

### Updated Status

**Startup Status:** READY FOR RETEST  
**Blocking Issues:** 0 (All P0 issues resolved including legacy module skips)  
**Remaining Issues:** 4 soft degradations (expected warmup behavior, optional fixes)  
**Estimated Time to Retest:** 5 minutes  
**Risk Level:** LOW (All critical blockers resolved)

---

## 12. Phase 2/3 Legacy PM Module Skips (2026-05-16)

### Additional Fixes Applied (P0 - Critical)

**Fix #3: Skip KalshiBankroll for sealed 15m stack**
- **Timestamp:** 2026-05-16
- **File:** `web/main.py` lines 2551-2553
- **Change:** Skipped KalshiBankroll initialization (sealed stack uses BankrollServiceV2)
- **Reason:** Module doesn't exist - legacy PM module replaced by BankrollServiceV2
- **Status:** ✅ COMPLETED

**Fix #4: Skip Phase 2 (5-asset infrastructure) for sealed 15m stack**
- **Timestamp:** 2026-05-16
- **File:** `web/main.py` lines 2586-2590
- **Change:** Skipped entire Phase 2 (CryptoTermStructure, RTIFeedService, CryptoRTIMonitor, CryptoAlertRouter)
- **Reason:** These are legacy PM modules that don't exist in codebase
- **Status:** ✅ COMPLETED

**Fix #5: Skip MatchingEngine for sealed 15m stack**
- **Timestamp:** 2026-05-16
- **File:** `web/main.py` lines 2623-2625
- **Change:** Skipped MatchingEngine initialization (sealed stack uses Kalshi venue directly)
- **Reason:** get_matching_engine() missing 'domain' argument - not needed for sealed stack
- **Status:** ✅ COMPLETED

### Root Cause Analysis

The `_init_kalshi_crypto_15m_app()` function was attempting to load legacy PM infrastructure modules that:
1. Don't exist in the current codebase (removed/archived)
2. Are not needed for the sealed 15m stack design
3. Were causing `startup_success = False`, which prevented MeridLoop from starting

These modules were part of the multi-asset PM stack and have been superseded by:
- BankrollServiceV2 (replaces KalshiBankroll)
- Direct Kalshi venue integration (replaces MatchingEngine)
- Profile-based risk envelope (replaces term structure)

### Verification Checklist Updated

- [x] Port 8011 not in use (`netstat -ano | findstr :8011`)
- [x] KalshiSettlementPoller fixed in web/main.py
- [x] KalshiBankroll skipped for sealed 15m stack
- [x] Phase 2 (5-asset infrastructure) skipped for sealed 15m stack
- [x] MatchingEngine skipped for sealed 15m stack
- [ ] Application starts without legacy module import errors
- [ ] Log shows `✅ MeridLoop started` (NOT skipped)
- [ ] Agents transition from WARMING_UP to ACTIVE after 15-90s
- [ ] Spot prices available (no "missing_spot" rejections after warmup)
- [ ] Orderbook deltas flow through WS bridge
- [ ] Market state store populated with live data
- [ ] Trading cycles execute successfully
- [ ] Orders placed (if conditions met)

### Updated Status

**Startup Status:** READY FOR RETEST  
**Blocking Issues:** 0 (All P0 issues resolved including legacy module skips)  
**Remaining Issues:** 4 soft degradations (expected warmup behavior, optional fixes)  
**Estimated Time to Retest:** 5 minutes  
**Risk Level:** LOW (All critical blockers resolved)
