# MERID Expiry Chaos Test Plan

**Purpose:** Define concrete test scenarios for final-5-minute expiry behavior validation.  
**Date:** 2026-03-28  
**Prerequisites:** `docs/KALSHI_RTI_SETTLEMENT_WINDOW_REFERENCE.md`, `docs/EXPIRY_BEHAVIOR_MAP.md`

---

## Test Harness Requirements

### Execution Methods (in order of preference)

1. **High-Fidelity Replay** (preferred for most scenarios)
   - Recorded market data from real Kalshi + CF Benchmarks feeds
   - Deterministic replay with chaos injection points
   - Location: `tests/replay/expiry_chaos/`

2. **Mock Integration Test** (for restart/clock-skew scenarios)
   - Fully mocked Kalshi API + RTI feed
   - Controlled timing injection
   - Location: `tests/test_expiry_chaos_*.py`

3. **Staging Environment** (for normal/high-vol scenarios)
   - Paper trading mode on Kalshi
   - Real WebSocket feeds
   - Low capital exposure

---

## Scenario 1: Normal Expiry (Baseline)

### Overview
Smooth RTI ticks, normal spreads, no outages. Validates that the system correctly exits positions before the settlement window and maintains ledger consistency.

### Preconditions
| Parameter | Value |
|-----------|-------|
| Target Market | KXBTC-15M-20260328-180000 |
| Expiration Time | 2026-03-28 18:00:00 UTC |
| Current Time | 2026-03-28 17:54:00 UTC (T-6min) |
| MERID Position | 5 YES contracts @ 55¢ |
| Bankroll State | $100.00, no drawdown |
| Agent Config | BTC_15M_Agent enabled, `MERID_RTI_SETTLEMENT_FINAL_SECONDS=60` |
| RTI Feed | 60 samples recorded, complete, valid |
| Kalshi State | Market open, normal spread (2-3¢), order book depth > 100 |

### Expected Behavior Timeline

| Time | Event | Expected MERID Behavior |
|------|-------|------------------------|
| T-6:00 | Test start | Agent scanning markets, position open |
| T-5:00 | Normal evaluation | No action (position already optimal) |
| T-4:00 | Position check | Stop-loss rules evaluated, no exit triggered |
| T-3:00 | Filter applied | Markets still passing filter (180s > 61s) |
| T-2:00 | No-trade buffer | Filter still passing (120s > 61s) |
| T-1:00 | Settlement guard zone | **Filter excludes market** (60s ≤ 61s threshold) |
| T-1:00 | Position remains | No new buys allowed, existing position held |
| T-0:30 | TIF check | Any orders would be IOC (not applicable, no orders) |
| T-0:00 | Expiration | Trading stops, market closes |
| T+1:00 | Settlement | Kalshi announces settlement price |

### Constraints to Validate
- ✅ No new BUY orders placed after T-61s
- ✅ Existing position remains open through expiry
- ✅ No SELL orders triggered (stop-loss not hit)
- ✅ Ledger shows position closed at settlement
- ✅ Final PnL correctly calculated

### Evidence Requirements
```yaml
logs:
  - level: INFO
    pattern: "Filter excluded: KXBTC-15M-20260328-180000, seconds_to_expiry=60"
    required: true
  - level: DEBUG
    pattern: "rti_settlement_window:no_new_buys"
    required: true
  - level: INFO
    pattern: "Position settled: ticker=KXBTC-15M-20260328-180000, pnl_cents=X"
    required: true

snapshots:
  - type: portfolio
    time: T-0
    content: positions, bankroll, exposure
  - type: market_state
    time: T-30s, T-60s, T-90s
    content: orderbook, spread, seconds_to_expiry
  - type: rti_buffer
    time: T-0 to T+1
    content: 60 samples, avg price, settlement_grade=true

final_state:
  merid_position: CLOSED
  kalshi_position: CLOSED
  pnl_reconciled: true
  trading_enabled: true  # Other markets still active
```

---

## Scenario 2: High-Volatility Expiry

### Overview
Large price swings (±5%) and spread widening (5→15¢) inside the final minute. Tests that MERID:
1. Does not panic-exit on volatility noise
2. Respects stop-loss only on sustained moves
3. Maintains position through expiry if stop-loss not hit

### Preconditions
| Parameter | Value |
|-----------|-------|
| Target Market | KXETH-15M-20260328-190000 |
| Expiration Time | 2026-03-28 19:00:00 UTC |
| Volatility Profile | Spot ETH swings 5% in final 90s |
| Spread Profile | Normal 2¢ → Widened 15¢ at T-45s → Normal 3¢ at T-15s |
| MERID Position | 3 YES contracts @ 52¢ |
| Stop-Loss Config | 10% trailing stop |
| Bankroll State | $50.00 |

### Simulated Price Timeline

| Time | Spot ETH | Market YES Price | Spread | Expected Agent Action |
|------|----------|------------------|--------|----------------------|
| T-5:00 | $3500 | 52¢ bid / 55¢ ask | 3¢ | Hold |
| T-3:00 | $3480 (-0.6%) | 50¢ bid / 53¢ ask | 3¢ | Hold (stop not hit) |
| T-2:00 | $3450 (-1.4%) | 48¢ bid / 51¢ ask | 3¢ | Evaluate stop-loss |
| T-1:30 | $3350 (-4.3%) | 42¢ bid / 45¢ ask | 3¢ | **Stop-loss triggered** |
| T-1:00 | $3400 (-2.9%) | 45¢ bid / 48¢ ask | 3¢ | **Filter excludes market** |
| T-0:45 | $3300 (-5.7%) | 35¢ bid / 50¢ ask | 15¢ | No action (buffer) |
| T-0:30 | $3450 (-1.4%) | 45¢ bid / 48¢ ask | 3¢ | No action (buffer) |
| T-0:00 | $3550 (+1.4%) | 55¢ bid / 58¢ ask | 3¢ | Expiration |

### Expected Behavior
1. **T-1:30:** Stop-loss triggered at 42¢ bid (10% trailing stop from 52¢ entry)
2. **T-1:00:** Filter pipeline excludes market — no new positions
3. **Position:** Closed via stop-loss at ~42¢ (loss: 10¢ × 3 = 30¢)
4. **No action during:** Spread widening panic (system remains calm)

### Constraints to Validate
- ✅ Stop-loss executes before expiry buffer activates
- ✅ No orders during spread-widening period
- ✅ Loss correctly limited to 10%
- ✅ System does not double-trade or panic-exit

### Evidence Requirements
```yaml
logs:
  - pattern: "Stop-loss triggered: ticker=KXETH-15M*, stop_price=42, exit_price=42"
    required: true
  - pattern: "Filter excluded: seconds_to_expiry=60"
    required: true
  - pattern: "Spread widened to 15¢"
    required: false  # Informational only
  - pattern: "Order filled: side=SELL, price=42, count=3"
    required: true

snapshots:
  - time: T-90s
    type: stop_loss_evaluation
    trigger: true
    reason: "trailing_stop_hit"
  - time: T-60s
    type: filter_exclusion
    reason: "min_seconds_to_expiry_rti_crypto"
```

---

## Scenario 3: RTI Gaps / Degraded Data

### Overview
Missing or delayed RTI ticks during the last 60 seconds. Tests MERID's ability to detect degraded settlement data and halt new trading while preserving existing positions.

### Preconditions
| Parameter | Value |
|-----------|-------|
| Target Market | KXSOL-15M-20260328-200000 |
| RTI Samples | 35 of 60 received (25 missing) |
| Missing Pattern | T-45s to T-20s: no samples |
| MERID Position | 2 YES contracts @ 50¢ |
| Config | `MERID_RTI_ALLOW_BUY_IF_SETTLEMENT_GRADE=0` (strict) |

### Simulated RTI Timeline

| Time | RTI Sample # | Sample Received? | Buffer State | Expected Behavior |
|------|-------------|------------------|--------------|-------------------|
| T-60s | 1-20 | ✅ Yes | Filling (20/60) | Normal trading |
| T-45s | 21-35 | ❌ No | Stalled (20/60) | **Warning logged** |
| T-30s | 36-45 | ❌ No | Stalled (20/60) | **Degraded mode** |
| T-20s | 46-50 | ✅ Yes | Resuming (25/60) | Hold position |
| T-10s | 51-55 | ✅ Yes | Filling (30/60) | Hold position |
| T-0s | 56-60 | ✅ Yes | Incomplete (35/60) | **Settlement grade: FALSE** |

### Expected Behavior
1. **T-45s:** Gap detected — log warning
2. **T-30s:** System enters degraded mode for this market
3. **T-20s:** Data resumes but buffer incomplete
4. **T-0s:** Only 35/60 samples — `is_settlement_grade() = False`
5. **Action:** Existing position held (can't close after expiry), flagged for review

### Constraints to Validate
- ✅ Gap detected within 5 seconds of first missing sample
- ✅ Warning logged with severity=WARNING
- ✅ No new positions opened during degraded period
- ✅ Existing position preserved (not liquidated)
- ✅ Post-settlement reconciliation flags incomplete data

### Evidence Requirements
```yaml
logs:
  - level: WARNING
    pattern: "RTI gap detected: ticker=KXSOL-15M*, missing_samples=5, last_received=T-45s"
    required: true
  - level: INFO
    pattern: "Settlement buffer incomplete: filled=35/60, grade=false"
    required: true
  - pattern: "rti_settlement_window:no_new_buys"
    required: true
    reason: "Missing RTI samples, not settlement-grade"

final_state:
  merid_position: "SETTLED_WITH_INCOMPLETE_DATA"
  reconciliation_flag: "RTI_INCOMPLETE"
  pnl_status: pending_review  # Requires manual review
```

---

## Scenario 4: Venue/API Issues During Final 5 Minutes

### Overview
Kalshi REST or WebSocket partial outage during the critical final 5 minutes. Tests failover behavior and graceful position management.

### Preconditions
| Parameter | Value |
|-----------|-------|
| Target Markets | KXXRP-15M, KXDOGE-15M |
| Outage Type | Kalshi WS disconnect + intermittent REST 503s |
| Outage Window | T-4:00 to T-1:00 (3-minute outage) |
| MERID Positions | XRP: 4 YES, DOGE: 3 YES |
| Config | Auto-reconnect enabled, 5 retries, 10s backoff |

### Simulated Event Timeline

| Time | Kalshi State | MERID State | Expected Action |
|------|-------------|-------------|-----------------|
| T-5:00 | Normal | Active | Normal trading |
| T-4:30 | WS drops | Stale data | Detect disconnect, pause new orders |
| T-4:15 | REST 503 | Circuit breaker open | Queue orders, log warning |
| T-3:30 | Still 503 | Degraded mode | Continue with cached data, tighter limits |
| T-2:45 | REST recovers | Reconnecting | Validate state, resume if consistent |
| T-1:30 | WS reconnects | Syncing | Reconcile positions |
| T-1:00 | Fully online | Active | **Settlement guard active** — no new buys |
| T-0:00 | Expiration | Expired | Positions settled |

### Expected Behavior
1. **T-4:30:** WebSocket disconnect detected
2. **T-4:15:** REST 503 triggers circuit breaker (3 failures)
3. **Degraded mode:**
   - Existing positions held
   - New orders queued (not submitted)
   - Position reconciliation deferred
4. **T-2:45:** Recovery begins
5. **T-1:30:** Full sync, positions validated
6. **T-1:00:** Settlement guard activates normally

### Constraints to Validate
- ✅ No orders lost during outage (queued and retry)
- ✅ No panic position closure (positions held)
- ✅ Circuit breaker opens within 3 failures
- ✅ Graceful recovery with state validation
- ✅ Settlement guard still works post-recovery

### Evidence Requirements
```yaml
logs:
  - level: WARNING
    pattern: "WebSocket disconnected: kalshi, will reconnect"
    required: true
  - level: ERROR
    pattern: "Kalshi API error: 503, circuit_breaker=OPEN"
    required: true
  - level: INFO
    pattern: "Entering degraded mode: reason=api_unavailable"
    required: true
  - level: INFO
    pattern: "Circuit breaker closed, resuming normal operation"
    required: true
  - pattern: "Position reconciliation: XRP matches, DOGE matches"
    required: true

snapshots:
  - time: T-4:30
    type: connectivity
    ws_status: disconnected
    rest_status: degraded
  - time: T-1:30
    type: connectivity
    ws_status: connected
    rest_status: normal
    position_divergence: 0
```

---

## Scenario 5: Process Restart During Final Minute

### Overview
MERID process restart at T-45s, testing ledger reload and reconciliation before any new orders are allowed.

### Preconditions
| Parameter | Value |
|-----------|-------|
| Target Market | KXBTC-15M-20260328-210000 |
| Restart Time | T-45s (45 seconds before expiry) |
| Persisted State | `paper_positions.json` has 3 YES @ 54¢ |
| Kalshi State | Actual position: 3 YES (matches persisted) |
| Config | `MERID_FRESH_START=0` (preserve state) |

### Event Sequence

| Time | Event | Expected Behavior |
|------|-------|-------------------|
| T-5:00 | Normal operation | Position open, trading active |
| T-1:00 | Filter excludes market | No new buys |
| T-45s | **Process restart** | Graceful shutdown initiated |
| T-44s | Shutdown | Positions persisted to disk |
| T-43s | Startup begins | Lifespan initialization |
| T-40s | Ledger reload | Load from `paper_positions.json` |
| T-38s | Kalshi sync | Fetch live positions, compare |
| T-35s | Reconciliation | **Positions match: 3 YES** |
| T-30s | Settlement guard active | No trading (T-30s < 60s) |
| T-0s | Expiration | Position settles |

### Critical Validation Points
1. **During restart:** No orders can be submitted
2. **After reload:** Position count matches (3 YES = 3 YES)
3. **Post-reconcile:** Divergence = 0
4. **Expiry handling:** Position correctly settled

### Constraints to Validate
- ✅ Process restart completes within 10 seconds
- ✅ Ledger reload successful
- ✅ Position reconciliation shows zero divergence
- ✅ No orders submitted until reconciliation passes
- ✅ Settlement proceeds normally after restart

### Evidence Requirements
```yaml
logs:
  - pattern: "Persisting positions to disk: count=1"
    required: true
  - pattern: "Loading positions from disk: count=1"
    required: true
  - pattern: "Reconciling with Kalshi: local=3, remote=3, divergence=0"
    required: true
  - pattern: "Reconciliation passed, enabling trading"
    required: true
  - pattern: "Settlement guard active: blocking buys, seconds_to_expiry=30"
    required: true

final_state:
  restart_completed: true
  reconciliation_divergence: 0
  positions_preserved: true
  settlement_correct: true
```

---

## Scenario 6: Clock Skew and Stale Config

### Overview
MERID server clock skewed +5 seconds ahead of Kalshi time, combined with stale risk limits not reloaded. Tests time handling and config refresh.

### Preconditions
| Parameter | Value |
|-----------|-------|
| Target Market | KXETH-15M-20260328-220000 |
| MERID Clock | T-55s (thinks it's 55s to expiry) |
| Kalshi Clock | T-60s (actual 60s to expiry) |
| Skew | +5s MERID ahead |
| Risk Limit | Old: `max_position_per_market=5` |
| New Config | `max_position_per_market=3` (not reloaded) |
| Position | Currently 4 YES (would violate new limit) |

### Behavior Analysis

| Source | Time Calculation | Action | Correct? |
|--------|-----------------|--------|----------|
| MERID (skewed) | T-55s | Thinks settlement window starts in 5s | ❌ Wrong |
| Kalshi (ground truth) | T-60s | Settlement window starts in 60s | ✅ Correct |
| Old config | max_position=5 | Allows 4 position | ✅ By old rules |
| New config | max_position=3 | Would reject | ✅ By new rules |

### Expected Behavior
1. **MERID calculates:** T-55s → Allows buys for 5 more seconds
2. **Kalshi reality:** T-60s → Should allow buys for 60 more seconds
3. **Risk:** MERID might enter settlement window 5s early (conservative) or late (dangerous)

### Risk Scenario: Skewed Clock Makes MERID Late
If MERID clock is **-5s behind** (thinks T-65s when actually T-60s):
- MERID would allow buys during the first 5s of settlement window
- **This is dangerous** — buys during RTI averaging

### Constraints to Validate
- ✅ Config reload on restart (or periodic)
- ✅ Position limits enforced with latest config
- ✅ Clock skew detection (compare Kalshi time vs local)
- ✅ Conservative behavior: if uncertain, assume earlier expiry

### Evidence Requirements
```yaml
logs:
  - level: WARNING
    pattern: "Clock skew detected: local=17:59:05, kalshi_time=17:59:00, skew=+5s"
    required: true
  - pattern: "Config reloaded: max_position_per_market=3"
    required: true
  - pattern: "Position violates new limit: current=4, max=3, flagging for reduction"
    required: true

metrics:
  clock_skew_seconds: 5
  config_reload_time: "2026-03-28T17:59:05Z"
  position_compliance: false
```

---

## Execution Checklist

For each scenario:

- [ ] **Setup:** Configure environment, reset state
- [ ] **Pre-flight:** Verify all systems operational
- [ ] **Execute:** Run scenario with logging enabled
- [ ] **Capture:** Collect all required evidence
- [ ] **Validate:** Check constraints against actual behavior
- [ ] **Report:** Write scenario report to `docs/expiry_chaos_runs/`
- [ ] **Review:** Flag any deviations from expected behavior

---

## Success Criteria

| Scenario | Success Condition |
|----------|-------------------|
| Normal Expiry | No new buys after T-61s, position settled correctly |
| High-Vol Expiry | Stop-loss respected, no panic during spread widening |
| RTI Gaps | Degraded mode entered, no trades on incomplete data |
| Venue Issues | Graceful degradation, recovery with reconciliation |
| Process Restart | State preserved, reconciliation passes, expiry correct |
| Clock Skew | Skew detected, conservative action taken |

**Overall:** 6/6 scenarios pass = Go for live trading.

---

**Next Steps:**
1. Implement test harness infrastructure
2. Create scenario data files
3. Execute scenarios
4. Document results in `docs/expiry_chaos_runs/`
