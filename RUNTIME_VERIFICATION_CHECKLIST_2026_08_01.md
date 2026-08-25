# Runtime Verification Checklist - 2026-08-01

## Purpose
Verify that live-path fixes are actually loaded in the running process and eliminate alternate execution paths that could bypass the new semantics.

## Critical Verification Points

### 1. ✅ Confirm `release_slot_by_ticker` Method is Loaded

**Expected Log Signature:**
```
[SLOT-ALLOCATOR] Released slot by ticker: slot_id=xxx agent=BTC_15M asset=BTC ticker=KXXBTC15M-26JUL312200-00 entry_price=50dc exit_price=80dc pnl=30dc total_exposure=$0.50 available=$0.50 slot_count=1
```

**Failure Signature (OLD CODE):**
```
Failed to release entry slot for exit order (non-critical): error='GlobalSlotAllocator' object has no attribute 'release_slot_by_ticker'
```

**Verification Steps:**
1. Trigger an exit order (bracket TP/SL or manual exit)
2. Check logs for `[SLOT-ALLOCATOR] Released slot by ticker` message
3. Confirm no `'GlobalSlotAllocator' object has no attribute 'release_slot_by_ticker'` errors
4. Verify slot_count decreases after release

**Pass Condition:** Exit orders show successful slot release with detailed logging

---

### 2. ✅ Confirm Bracket Orders Marked as Exit Orders

**Expected Log Signature:**
```
[BRACKET-CREATION-DEBUG] TP intent created: side=yes action=sell price=80c count=1 entry_or_exit=exit
[order-router] EXIT ORDER FAST-PATH: KXXBTC15M-26JUL312200-00 sell — bypassing execution gate
```

**Failure Signature (OLD CODE):**
```
[ENTRY-ORDER-INVARIANT-VIOLATION] ticker=KXXBTC15M-26JUL312200-00 side=yes action=sell kalshi_side=SELL_YES
```

**Verification Steps:**
1. Open a position that triggers bracket order creation
2. Check logs for `entry_or_exit=exit` in bracket creation debug
3. Verify `EXIT ORDER FAST-PATH` message appears
4. Confirm no `ENTRY-ORDER-INVARIANT-VIOLATION` messages

**Pass Condition:** Bracket orders show exit markers and bypass entry guards

---

### 3. ✅ Confirm Candidate Block Diagnostics Emitted

**Expected Log Signature:**
```
[CANDIDATE-BLOCK] asset=BTC reason=cooldown count=5
[CANDIDATE-BLOCK] asset=ETH reason=no_spot_price count=3
[CANDIDATE-BLOCK] asset=SOL reason=no_contract_in_entry_window count=2
```

**Failure Signature (OLD CODE):**
```
[AGENT-GRID-RUN-CYCLE-NO-CANDIDATE] agent=BTC_15M
```

**Verification Steps:**
1. Run a full trading cycle with all agents
2. Check logs for `[CANDIDATE-BLOCK]` messages
3. Verify each NO-CANDIDATE has an associated block reason
4. Confirm block reason counts increment across cycles

**Pass Condition:** Every candidate block has a documented reason with count tracking

---

### 4. ✅ Confirm Fail-Closed Market State Policy

**Expected Log Signature (Entry Orders):**
```
[order-router] Live order rejected — market state not found (fail-closed): ticker=KXXBTC15M-26JUL312200-00
[ORDER-BLOCKED] ticker=KXXBTC15M-26JUL312200-00 reason=STATE_NOT_FOUND side=yes count=1 detail=fail_closed_policy
```

**Expected Log Signature (Exit Orders):**
```
[order-router] EXIT ORDER: market state missing for KXXBTC15M-26JUL312200-00 - proceeding without state gates (exit must not be trapped)
```

**Failure Signature (OLD CODE):**
```
Book timestamp missing, assuming fresh (graceful degradation): ticker=KXXBTC15M-26JUL312200-00
```

**Verification Steps:**
1. Submit entry order with missing/stale market state
2. Verify rejection with `fail_closed_policy` reason
3. Submit exit order with missing/stale market state
4. Verify exit order proceeds with override message
5. Confirm no "assuming fresh" messages

**Pass Condition:** Entry orders rejected on stale state, exit orders proceed with override

---

## Alternate Path Sweep

### 5. 🔍 Search for Alternate Intent Builders

**Pattern:** `OrderIntent(` without `entry_or_exit="exit"`

**Files to Check:**
- `merid/prediction/agent_grid_15m.py` - Signal generation
- `merid/prediction/strategy.py` - Strategy intent builders
- `merid/event_venues/kalshi/position_cache.py` - Bracket orders ✅ (already fixed)
- `merid/position_management/position_monitor.py` - Position monitor exits
- `merid/event_venues/kalshi/order_gate.py` - Order gate intents

**Search Command:**
```bash
grep -r "OrderIntent(" merid/ --include="*.py" | grep -v "entry_or_exit" | grep "action.*sell"
```

**Expected Result:** All sell intents should have `entry_or_exit="exit"` or be from exit-marked sources

---

### 6. 🔍 Search for Remaining Stale-State Bypasses

**Patterns:**
- `assuming fresh`
- `graceful degradation`
- `proceeding without` (exit-specific only)
- `fallback` (in market state context)

**Search Command:**
```bash
grep -r "assuming fresh\|graceful degradation" merid/ --include="*.py"
```

**Expected Result:** Only exit orders should have bypass logic, entry orders should be fail-closed

---

### 7. 🔍 Search for Old Range Constants

**Patterns:**
- `10c-75c` (in code, not comments)
- `MIN_OPEN_PRICE_CENTS.*10`
- `MAX_OPEN_PRICE_CENTS.*75`
- Hardcoded range checks `[10, 75]` or `(10, 75)`

**Search Command:**
```bash
grep -r "10.*75\|10c.*75c" merid/ --include="*.py" | grep -v "# " | grep -v "\""
```

**Expected Result:** No hardcoded 10c-75c ranges in live code paths

---

### 8. 🔍 Audit Order Router Fast Paths

**Fast Path Locations:**
- `EXIT ORDER FAST-PATH` - Should check `entry_or_exit` or source markers
- Early returns before invariant checks - Should validate exit status
- Slot allocation bypass - Should only apply to true exit orders

**Verification:**
1. Check all early return paths in `order_router.py`
2. Verify each has `_is_exit_gate` check
3. Confirm exit detection uses updated `is_exit_order_from_intent()`

---

### 9. 🔍 Verify Block Reason Return Handling

**Pattern:** `return None` in `agent_grid_15m.py` signal generation

**Search Command:**
```bash
grep -n "return None" merid/prediction/agent_grid_15m.py | head -20
```

**Expected Result:** All `return None` should be replaced with `return {"block_reason": "reason"}`

**Files to Update:**
- Market validation failures
- Time window filter failures
- Price range filter failures
- Session limit failures
- Portfolio heat failures

---

## Live-Path Regression Tests

### Test 1: Bracket Exit No Entry Invariant

**Purpose:** Prove bracket orders bypass entry guards

**Test Steps:**
1. Create a position with TP/SL enabled
2. Wait for bracket order submission
3. Verify logs show `entry_or_exit=exit`
4. Verify no `ENTRY-ORDER-INVARIANT-VIOLATION` message
5. Confirm order is accepted and routed

**Expected Logs:**
```
[BRACKET-CREATION-DEBUG] TP intent created: entry_or_exit=exit
[order-router] EXIT ORDER FAST-PATH: ... sell — bypassing execution gate
```

**Failure Condition:** `ENTRY-ORDER-INVARIANT-VIOLATION` appears

---

### Test 2: Stale-Book Entry Rejection

**Purpose:** Prove entry path is fail-closed

**Test Steps:**
1. Simulate missing market state for a ticker
2. Submit entry order for that ticker
3. Verify rejection with `fail_closed_policy` reason
4. Confirm no "assuming fresh" message

**Expected Logs:**
```
[order-router] Live order rejected — market state not found (fail-closed)
[ORDER-BLOCKED] reason=STATE_NOT_FOUND detail=fail_closed_policy
```

**Failure Condition:** Order proceeds or shows "assuming fresh"

---

### Test 3: Candidate Diagnostics Populated

**Purpose:** Prove block reasons are tracked

**Test Steps:**
1. Force each blocker condition (cooldown, no spot, no market, etc.)
2. Run signal generation cycle
3. Verify `[CANDIDATE-BLOCK]` logs appear for each blocker
4. Confirm block reason counts are accurate

**Expected Logs:**
```
[CANDIDATE-BLOCK] asset=BTC reason=cooldown count=1
[CANDIDATE-BLOCK] asset=ETH reason=no_spot_price count=1
[CANDIDATE-BLOCK] asset=SOL reason=no_contract_in_entry_window count=1
```

**Failure Condition:** NO-CANDIDATE without block reason

---

### Test 4: Slot Release Method Invoked

**Purpose:** Prove allocator method is called on exit fill

**Test Steps:**
1. Open a position
2. Trigger exit order (bracket or manual)
3. Mock or verify `GlobalSlotAllocator.release_slot_by_ticker()` is called
4. Confirm slot is removed from allocator

**Expected Logs:**
```
[SLOT-ALLOCATOR] Released slot by ticker: slot_id=xxx ticker=KXXBTC15M-26JUL312200-00
```

**Failure Condition:** Missing method error or slot not released

---

## Runtime Confirmation Steps

### Before Deployment
1. **Backup current running code** (process image, config files)
2. **Document current log signatures** for baseline comparison
3. **Note current candidate generation rate** and rejection patterns

### After Deployment
1. **Restart trading process** to ensure new code is loaded
2. **Verify process startup logs** show no import errors
3. **Check method availability** by inspecting loaded modules
4. **Run single test cycle** with controlled conditions

### During Verification
1. **Monitor logs in real-time** for new log signatures
2. **Trigger each test case** individually
3. **Document any deviations** from expected signatures
4. **Roll back immediately** if critical failures appear

### Post-Verification
1. **Compare candidate generation rates** before/after
2. **Verify rejection patterns** changed as expected
3. **Check slot leak metrics** (if available)
4. **Validate monitoring alerts** still fire appropriately

---

## Pass/Fail Conditions

### Critical Pass Conditions
- ✅ No `'GlobalSlotAllocator' object has no attribute 'release_slot_by_ticker'` errors
- ✅ No `ENTRY-ORDER-INVARIANT-VIOLATION` for bracket orders
- ✅ All NO-CANDIDATE messages have associated block reasons
- ✅ Entry orders rejected on stale state with `fail_closed_policy`
- ✅ Exit orders proceed on stale state with override message

### Critical Fail Conditions
- ❌ Missing method errors persist after restart
- ❌ Entry invariant violations for bracket orders
- ❌ NO-CANDIDATE without block reason
- ❌ Entry orders proceed on stale state
- ❌ Exit orders blocked on stale state

### Warning Conditions
- ⚠️ Some `return None` still present (not converted to block reasons)
- ⚠️ Alternate intent builders found without exit markers
- ⚠️ Old range constants in utility code
- ⚠️ Stale-state bypasses in non-critical paths

---

## Rollback Criteria

**Immediate Rollback Required If:**
- Missing method errors after restart
- Entry orders proceed on clearly stale market data
- Exit orders blocked when they should proceed
- Candidate generation drops to zero unexpectedly
- Position accounting inconsistencies appear

**Investigate Before Rollback:**
- Minor log format changes
- Additional diagnostic messages
- Slight changes in rejection patterns
- New warning messages (non-critical)

---

## Next Steps After Verification

1. **Fix any alternate intent builders** found during sweep
2. **Remove remaining stale-state bypasses** in non-critical paths
3. **Update old range constants** in utility code
4. **Add missing block reason returns** for all `return None` paths
5. **Implement live-path regression tests** in test suite
6. **Add runtime monitoring** for key log signatures
7. **Document expected log signatures** in operations runbook
