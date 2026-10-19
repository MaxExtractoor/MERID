# Targeted Remaining Bugs Checklist - 2026-08-01

## Critical Issues Identified from Log Analysis

### 1. Candidate Generation Failure (NO-CANDIDATE)

**Symptom:** System generates zero candidates in live loop despite "all bugs fixed" narrative.

**Log Evidence:**
- `[AGENT-GRID-RUN-CYCLE-NO-CANDIDATE] agent=BTC_15M`
- `candidates=0 signals_generated=0 reasons=no_candidates_evaluated`

**Root Cause Analysis:**
The signal generation path in `agent_grid_15m.py` has **44+ return None statements** that can block candidate generation. Key failure points:

**File:** `merid/prediction/agent_grid_15m.py`

**Critical Failure Points:**
1. **Line 12306-12316:** Cooldown check blocking trades
   ```python
   if time_since_last_trade < cooldown_seconds:
       logger.info("[COOLDOWN-CHECK] ... skipping")
       return None
   ```

2. **Line 12349-12361:** Consecutive loss pause
   ```python
   if current_time < pause_until:
       logger.info("[CONSECUTIVE-LOSS-PAUSE] ... -> SKIP")
       return None
   ```

3. **Line 12367-12377:** Session risk cap
   ```python
   if self._session_risk_usd >= self._session_risk_cap_usd:
       logger.info("[SESSION-RISK-CAP] ... -> SKIP")
       return None
   ```

4. **Line 12668-12672:** Spot price unavailability
   ```python
   if not spot_price:
       logger.warning("[SPOT-ERROR] ... no spot price available")
       return None
   ```

5. **Line 12940-12952:** No contract in entry window
   ```python
   if not best_ticker:
       logger.info("[MARKET-SELECTION] ... no contract in entry window ... skipping")
       return None
   ```

6. **Line 13158-13162:** Market validation failure
   ```python
   if not self._validate_market_state(market):
       logger.info("[MARKET-VALIDATION-FAILED] ...")
       return None
   ```

7. **Line 13176-13188:** Warmup blocking
   ```python
   if price_history_len < 1:
       logger.warning("[MARKET-VALIDATION-SKIP] ... BLOCKING TRADE during warmup")
       return None
   ```

8. **Line 8725-8749:** Time window filter (too early/too late)
   ```python
   if minutes_to_expiry > max_entry_mins:
       logger.info("[TIME-WINDOW-FILTER] ... -> SKIP (too early)")
       return None
   ```

9. **Line 8961-8989:** Price filter reject (both sides outside canonical ranges)
   ```python
   if not yes_in_range and not no_in_range:
       logger.info("[PRICE-FILTER-REJECT] ... both sides outside canonical ranges -> SKIP")
       return None
   ```

**Action Required:**
- Add diagnostic logging to track which filter is blocking candidates
- Review cooldown settings, session risk caps, and time window filters
- Verify spot price availability and market state freshness
- Check if price range filters are too restrictive

---

### 2. Position Cache Contract Limit Rejection

**Symptom:** `POSITION-CACHE-CONTRACT-LIMIT-REJECTION` messages with 1 contract per position rule enforcement.

**Log Evidence:**
```
[POSITION-CACHE-CONTRACT-LIMIT-REJECTION] ticker=KXSOL15M-26AUG010415-15 side=yes action=buy pre_size=1 fill_size=1 would_post_size=2 - REJECTING FILL to enforce 1 CONTRACT PER POSITION RULE
```

**Root Cause Analysis:**
The position cache is correctly rejecting fills that would exceed the 1 contract per position limit, but this suggests:
- Orders are being submitted for positions that already exist
- Entry/exit lifecycle may not be properly synchronized
- Position accounting may have race conditions

**File:** `merid/event_venues/kalshi/position_cache.py` (need to inspect)

**Action Required:**
- Audit position cache fill handling logic
- Verify entry order generation checks existing positions before submission
- Check for race conditions in position accounting
- Review position lifecycle from entry → fill → exit

---

### 3. Old 10c-75c Price Range Language

**Symptom:** Logs and code still reference old 10c-75c ranges instead of canonical 5c-85c ranges.

**Evidence Found:**

**File:** `merid/prediction/strategy.py`
- **Line 535:** `# Previous 10c-75c range was too restrictive...`
- **Line 556:** `# Previous 10c-75c range was too restrictive...`

**File:** `merid/prediction/agent_grid_15m.py`
- **Line 5571:** `# Previous 10c-75c range was too restrictive...`
- **Line 6481:** `# Previous 10c-75c range was too restrictive...`
- **Line 6542:** `# CRITICAL FIX (2026-08-01): Expanded from 10c-75c to 5c-85c...`
- **Line 6592:** `# CRITICAL FIX (2026-08-01): Expanded from 10c-75c to 15c-99c...`
- **Line 11673:** `# Previous 10c-75c range was too restrictive...`

**File:** `merid/event_venues/kalshi/order_gate.py`
- **Line 1075:** `# CRITICAL FIX (2026-08-01): Updated fallback from 10c-75c to 5c-85c...`
- **Line 1409:** `# CRITICAL FIX (2026-08-01): Updated fallback from 10c-75c to 5c-85c...`

**File:** `merid/risk/profiles/crypto_15m_profile.py`
- **Line 485:** `# 2026-07-12: Canonical price band (10c-75c)...`
- **Line 493:** `description='Valid price range in cents for order execution (10c-75c canonical band...'`

**File:** `merid/metrics/canonical_buckets.py`
- **Line 8:** `Canonical Price Range: 10c-75c (enforced across trading system)`
- **Line 14:** `# ── Canonical Price Buckets (aligned with 10c-75c trading range) ──`
- **Line 16:** `# 1. Cover the full canonical trading range (10c-75c)`
- **Line 109:** `Check if a price is within the canonical trading range (10c-75c).`

**File:** `merid/risk/risk_parameters.py`
- **Line 108:** `# Rationale: Sweet spot for optimal sizing is 10c-75c...`

**Action Required:**
- Update all comments and documentation to reference 5c-85c canonical range
- Update `canonical_buckets.py` to use 5c-85c range
- Update profile configuration to reflect 5c-85c range
- Verify all logging strings use updated ranges

---

### 4. Entry/Exit Order Routing Invariant Violations

**Symptom:** `ENTRY-ORDER-INVARIANT-VIOLATION` messages showing SELL actions being used for entry orders.

**Log Evidence:**
```
[ENTRY-ORDER-INVARIANT-VIOLATION] ticker=KXXRP15M-26AUG011315-15 side=yes action=sell kalshi_side=SELL_YES - Entry orders must use BUY actions only. SELL actions are for exit trades only.
```

**File:** `merid/event_venues/kalshi/order_router.py`
- **Line 6445-6450:** Invariant check rejecting SELL entry orders

**Root Cause Analysis:**
Exit orders are being misclassified as entry orders, or entry orders are incorrectly using SELL actions. The log shows:
- Exit orders are taking fast-path: `EXIT ORDER FAST-PATH: KXXRP15M-26AUG011315-15 sell`
- But then failing invariant check: `ENTRY-ORDER-INVARIANT-VIOLATION`

**Action Required:**
- Audit exit order detection logic in order_router.py
- Verify `is_exit_order` flag is properly set
- Check entry/exit classification in signal generation
- Review intent contract building for exit orders

---

### 5. Missing release_slot_by_ticker Method

**Symptom:** `Failed to release entry slot for exit order (non-critical): error='GlobalSlotAllocator' object has no attribute 'release_slot_by_ticker'`

**Log Evidence:**
```
[order-router] Exit order filled - releasing entry slot by ticker: ticker=KXXRP15M-26AUG011315-15
WARNING [order-router] Failed to release entry slot for exit order (non-critical): ticker=KXXRP15M-26AUG011315-15 error='GlobalSlotAllocator' object has no attribute 'release_slot_by_ticker'
```

**File:** `merid/event_venues/kalshi/order_router.py`
- **Line 5483-5484:** Calls `slot_allocator.release_slot_by_ticker(intent.ticker)`

**File:** `merid/risk/global_slot_allocator.py`
- **MISSING:** `release_slot_by_ticker` method does not exist
- **Existing methods:** `release_slot()`, `release_by_agent()`, `release_by_asset()`

**Action Required:**
- Add `release_slot_by_ticker()` method to `GlobalSlotAllocator`
- Method should find slot by ticker and release it
- Update test file to validate the new method
- Ensure proper slot cleanup on exit order fills

---

### 6. Stale Market State Handling

**Symptom:** Market state freshness issues with "graceful degradation" that may lead to silent bad behavior.

**Log Evidence from current_cycle_logs.txt:**
- `market state missing`
- `Book timestamp missing, assuming fresh`
- `market data stale infs`

**Root Cause Analysis:**
The system is using graceful degradation for stale market data instead of fail-closed policy, which can lead to:
- Trading on stale prices
- Incorrect edge calculations
- Phantom liquidity

**Action Required:**
- Implement strict fail-closed policy for stale market state
- Add maximum staleness thresholds (e.g., reject if data > 5s old)
- Remove "assuming fresh" fallback logic
- Add market state freshness monitoring and alerts

---

### 7. Bracket Order Submission Failures

**Symptom:** Bracket orders submitted with `okFalse` and entry slot release failures.

**Log Evidence:**
- `bracket orders submitted okFalse`
- `failed to release entry slot due to missing method`

**Action Required:**
- Audit bracket order submission logic
- Verify bracket order slot allocation
- Check bracket order fill handling
- Review entry slot release on bracket order completion

---

## Priority Order for Fixes

### SEV-0 (Immediate Action Required)
1. **Add missing `release_slot_by_ticker` method** - Breaking exit order flow
2. **Fix entry/exit order classification** - Causing invariant violations
3. **Implement fail-closed stale market policy** - Prevents trading on bad data

### SEV-1 (High Priority)
4. **Investigate candidate generation failure** - System not generating trades
5. **Audit position cache lifecycle** - Contract limit rejections suggest accounting issues
6. **Update old price range language** - Documentation/code consistency

### SEV-2 (Medium Priority)
7. **Audit bracket order submission** - Lifecycle cleanup issues

---

## Recommended Next Steps

1. **Add `release_slot_by_ticker` to GlobalSlotAllocator:**
   ```python
   def release_slot_by_ticker(self, ticker: str, exit_price_cents: Optional[int] = None) -> bool:
       """Release slot by ticker (for exit orders)."""
       with self._lock:
           for slot_id, slot in list(self._slots.items()):
               if slot.ticker == ticker:
                   return self.release_slot(slot_id, exit_price_cents)
       return False
   ```

2. **Add diagnostic logging to candidate generation:**
   - Track which filter is blocking each agent
   - Log cooldown state, session limits, market availability
   - Add "candidate generation blocked by: X" summary log

3. **Audit entry/exit classification:**
   - Check `is_exit_order` flag propagation
   - Verify intent contract building for exits
   - Review order router fast-path logic

4. **Implement fail-closed market state policy:**
   - Add max staleness threshold (5s)
   - Reject trades if market state is stale
   - Remove "assuming fresh" fallbacks

5. **Update price range documentation:**
   - Replace all 10c-75c references with 5c-85c
   - Update canonical_buckets.py range definition
   - Verify profile configuration matches

---

## Files Requiring Changes

1. `merid/risk/global_slot_allocator.py` - Add `release_slot_by_ticker` method
2. `merid/event_venues/kalshi/order_router.py` - Fix entry/exit classification
3. `merid/prediction/agent_grid_15m.py` - Add diagnostic logging
4. `merid/event_venues/kalshi/market_state.py` - Implement fail-closed staleness checks
5. `merid/metrics/canonical_buckets.py` - Update range to 5c-85c
6. `merid/risk/profiles/crypto_15m_profile.py` - Update documentation
7. Multiple files - Update 10c-75c comments to 5c-85c

---

## Testing Checklist

- [ ] Test `release_slot_by_ticker` method with various scenarios
- [ ] Verify exit orders no longer cause "missing method" errors
- [ ] Confirm entry orders use BUY actions only
- [ ] Confirm exit orders use SELL actions only
- [ ] Test candidate generation with diagnostic logging enabled
- [ ] Verify stale market state rejection works correctly
- [ ] Confirm price range documentation is consistent
- [ ] Test position cache lifecycle end-to-end
- [ ] Verify bracket order submission and slot cleanup
