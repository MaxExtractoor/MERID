# Kalshi Orderbook Production Invariants

**Document Version:** 1.0  
**Last Updated:** 2026-05-12  
**Status:** LOCKED - Changes require risk committee approval

---

## Overview

This document defines the NON-NEGOTIABLE production invariants for the Kalshi orderbook bootstrap system. These invariants represent the canonical behavior that must be preserved in production to ensure safe, reliable trading.

**Any changes to these invariants require:**
1. Risk committee approval
2. Staged rollout testing
3. Updated regression tests

---

## 1. Data Flow Invariants

### Invariant 1.1: WebSocket Subscription Scope
- **Rule:** Only subscribe to `orderbook_delta` on Kalshi WebSocket
- **Enforcement Point:** `ws_bridge.py` - subscription method
- **Rationale:** Kalshi WS does NOT send snapshots automatically - only deltas. Snapshots must come from REST.
- **Reference:** https://docs.kalshi.com/websockets/orderbook-updates

### Invariant 1.2: REST Snapshot Source
- **Rule:** Snapshots come from REST `GET /markets/{ticker}/orderbook` ONLY
- **Enforcement Point:** `ws_bridge.py` - snapshot bootstrap in subscribe() method
- **Rationale:** Ensures deterministic bootstrap with complete orderbook state
- **Reference:** https://docs.kalshi.com/api-reference/market/get-market-orderbook

### Invariant 1.3: Bootstrap Before Deltas
- **Rule:** Every traded market MUST be bootstrapped via REST `orderbook_fp` before accepting WS deltas
- **Enforcement Point:** `market_state.py` - apply_orderbook_message() queues deltas if book not initialized
- **Rationale:** Prevents partial book state from WS deltas without full context

### Invariant 1.4: Market Scope Enforcement
- **Rule:** Scope is strictly BTC/ETH/SOL/XRP/DOGE 15m timeframe
- **Enforcement Points:**
  - Subscription: `ws_bridge.py` - filters by allowed underlyings/timeframes
  - Snapshot bootstrap: `ws_bridge.py` - only processes allowed markets
  - Message processing: `market_state.py` - apply_orderbook_message() rejects unsupported markets
  - Router selection: Order router only selects from allowed markets
- **Rationale:** Prevents trading on unsupported or untested markets
- **Reference:** https://help.kalshi.com/en/articles/13823838-crypto-markets

---

## 2. Single Source of Truth

### Invariant 2.1: Centralized Orderbook Authority
- **Rule:** `market_state.py` + `LocalOrderbook` are the ONLY authoritative source of bid/ask/mid
- **Enforcement Point:** Architecture - all consumers (agents, router, UI/API) MUST read from market_state
- **Rationale:** Prevents subtle divergences between what router sees and what UI/API thinks the book is
- **Reference:** https://hackingthemarkets.com/building-a-live-order-book-watcher-for-kalshi/

### Invariant 2.2: No Duplicate Orderbook Logic
- **Rule:** No duplicate orderbook logic outside market_state module
- **Enforcement Point:** Code review - no other modules should maintain bid/ask state
- **Rationale:** Single source of truth eliminates sync bugs and inconsistencies

---

## 3. Health & Circuit Breaker Invariants

### Invariant 3.1: Staleness Threshold
- **Rule:** `MAX_BOOK_STALENESS_MS = 30000` (30 seconds maximum staleness)
- **Enforcement Point:** `market_state.py` - is_trading_enabled() checks last_update_age_ms
- **Rationale:** 15m markets update frequently; 30s allows transient network issues while preventing stale trading
- **Location:** `market_state.py` line 61

### Invariant 3.2: Healthy Books Quorum
- **Rule:** `MIN_HEALTHY_BOOKS_FOR_TRADING = 3` (60% quorum for 5 markets)
- **Enforcement Point:** `market_state.py` - is_trading_enabled() requires 3/5 markets healthy
- **Rationale:** Prevents trading on degraded data when majority of markets are unhealthy
- **Location:** `market_state.py` line 66

### Invariant 3.3: Initialization Check
- **Rule:** `HEALTH_CHECK_INITIALIZED = True` - book must have REST snapshot applied
- **Enforcement Point:** `market_state.py` - is_trading_enabled() checks book_initialized flag
- **Rationale:** Ensures book has complete state before trading
- **Location:** `market_state.py` line 70

### Invariant 3.4: Freshness Check
- **Rule:** `HEALTH_CHECK_FRESH = True` - book must be within staleness threshold
- **Enforcement Point:** `market_state.py` - is_trading_enabled() checks age_ms < MAX_BOOK_STALENESS_MS
- **Rationale:** Ensures data is not stale
- **Location:** `market_state.py` line 71

### Invariant 3.5: Bid/Ask Validation
- **Rule:** `HEALTH_CHECK_BID_ASK = True` - book must have valid bid < ask with non-zero sizes
- **Enforcement Point:** `market_state.py` - is_trading_enabled() checks bid/ask presence and ordering
- **Rationale:** Prevents trading on invalid or crossed books
- **Location:** `market_state.py` line 72

### Invariant 3.6: Circuit Breaker Enforcement
- **Rule:** Trading disabled if any market fails health checks
- **Enforcement Point:** `market_state.py` - is_trading_enabled() returns False if thresholds violated
- **Rationale:** Primary guard against silent data degradation
- **Log:** `[HEALTH-CIRCUIT-BREAKER] TRADING DISABLED` logged when blocking

---

## 4. Startup Sequence Invariants

### Invariant 4.1: WS Boot Logging
- **Rule:** `[WS-BOOT]` log must show bridge started with tickers and channels
- **Enforcement Point:** `ws_bridge.py` - start() method
- **Log Format:** `[WS-BOOT] bridge started tickers=N channels=['orderbook_delta', 'ticker', 'trade', 'fill'] env=...`
- **Rationale:** Provides deterministic start-of-day behavior visibility

### Invariant 4.2: Snapshot Bootstrap Start Logging
- **Rule:** `[SNAPSHOT-BOOTSTRAP] started markets=N` must be logged
- **Enforcement Point:** `ws_bridge.py` - subscribe() method
- **Log Format:** `[SNAPSHOT-BOOTSTRAP] started for N new tickers`
- **Rationale:** Confirms bootstrap process initiated

### Invariant 4.3: Snapshot Bootstrap Completion Logging
- **Rule:** `[SNAPSHOT-BOOTSTRAP] complete market=... levels=... bid=... ask=... mid=... source=REST` must be logged
- **Enforcement Point:** `ws_bridge.py` - subscribe() method after apply_orderbook_message
- **Log Format:** `[SNAPSHOT-BOOTSTRAP] complete market=KXBTC15M-... levels=213 bid=0.76 ask=99.999 mid=50.38 source=REST`
- **Rationale:** Confirms each market has valid bid/ask/mid after bootstrap

### Invariant 4.4: Trading Readiness Enforcement
- **Rule:** Trading only enabled after ALL configured markets have snapshots or marked unsupported
- **Enforcement Point:** `ws_bridge.py` - subscribe() method checks book_initialized for all markets
- **Log:** `[PRODUCTION-INVARIANT] All 5 crypto 15m markets have snapshots - trading ready` or warning if missing
- **Rationale:** Prevents trading on partial bootstrap

---

## 5. Monitoring Invariants

### Invariant 5.1: Health Logging
- **Rule:** `log_book_health()` must run every 60s logging initialized, last_update_age_ms, bid/ask/mid/spread
- **Enforcement Point:** `market_state.py` - background task calls log_book_health()
- **Log Format:** `[MARKET-STATE] health market=KXBTC15M-... initialized=True last_update_age_ms=100 bid=76 ask=9999 mid=5038 spread=9923`
- **Rationale:** Provides visibility into book health and freshness

### Invariant 5.2: Production Self-Test Endpoint
- **Rule:** `/internal/kalshi_health` endpoint must return detailed metrics for all markets
- **Enforcement Point:** `kalshi_api.py` - production_kalshi_health() endpoint
- **Response Format:**
  ```json
  {
    "trading_enabled": true,
    "market_count": 5,
    "expected_market_count": 5,
    "markets": [
      {
        "ticker": "KXBTC15M-26MAY121445-45",
        "underlying": "BTC",
        "timeframe": "15m",
        "initialized": true,
        "last_update_age_ms": 100,
        "best_bid_cents": 76,
        "best_ask_cents": 9999,
        "mid_cents": 5038,
        "spread_cents": 9923
      },
      ...
    ],
    "timestamp": "2026-05-12T18:33:00Z"
  }
  ```
- **Rationale:** Moves from log-only debugging to systematic production health check

### Invariant 5.3: Circuit Breaker Logging
- **Rule:** Circuit breaker must log `[HEALTH-CIRCUIT-BREAKER]` when trading state changes
- **Enforcement Point:** `market_state.py` - is_trading_enabled() logs on state change
- **Log Format:** `[HEALTH-CIRCUIT-BREAKER] TRADING DISABLED: healthy=2/5, threshold=3, reasons=[...]` or `TRADING ENABLED`
- **Rationale:** Provides alerting on trading state changes

---

## 6. Baseline Health State (Golden Path)

As of 2026-05-12 14:33 UTC, the verified baseline health state is:

### Snapshot Bootstrap Results
- **KXBTC15M-26MAY121445-45:** levels=213, bid=0.76, ask=99.999, mid=50.38
- **KXETH15M-26MAY121445-45:** levels=199, bid=0.72, ask=99.999, mid=50.36
- **KXSOL15M-26MAY121445-45:** levels=213, bid=0.66, ask=99.999, mid=50.33
- **KXXRP15M-26MAY121445-45:** levels=213, bid=0.61, ask=99.999, mid=50.30
- **KXDOGE15M-26MAY121445-45:** levels=63, bid=0.46, ask=99.999, mid=50.23

### WS Delta Freshness
- All markets show `initialized=True`
- `last_update_age_ms` decreasing (63ms-19407ms range)
- Confirms WS deltas keep books fresh

### Circuit Breaker State
- Trading enabled: 5/5 markets healthy
- No stale books (>30s)
- All books have valid bid/ask with bid < ask

---

## 7. Staged Rollout Checklist

Before production deployment, verify:

- [ ] All 5 markets complete snapshot bootstrap with valid bid/ask/mid
- [ ] WS deltas arrive within 30s of bootstrap
- [ ] `/internal/kalshi_health` returns all markets with initialized=True
- [ ] Circuit breaker shows trading_enabled=True
- [ ] Health logs show last_update_age_ms < 30000 for all markets
- [ ] No `[HEALTH-CIRCUIT-BREAKER] TRADING DISABLED` logs
- [ ] All production invariants verified in logs

---

## 8. Rollback Criteria

Immediate rollback required if:

- Any market shows `initialized=False` for >60s after bootstrap
- `last_update_age_ms` > 60000ms (60s) for any market
- Circuit breaker logs `TRADING DISABLED` for >5 minutes
- `/internal/kalshi_health` returns unexpected market_count (<5 or >5)
- Any production invariant violation detected in logs

---

## 9. Contact

For questions about these invariants or approval for changes:

- **Risk Committee:** [contact]
- **Engineering Lead:** [contact]
- **Kalshi Integration Owner:** [contact]
