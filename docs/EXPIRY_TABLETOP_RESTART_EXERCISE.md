# EXPIRY_TABLETOP_RESTART_EXERCISE.md

**Purpose:** Concrete tabletop exercise checklist for "restart near expiry" scenario.

**Part of:** Kalshi Expiry Chaos Audit - Follow-on Phase

**Exercise Type:** Walkthrough / simulation (no live trading)

---

## Executive Summary

This document provides a step-by-step tabletop exercise to verify that restart procedures work correctly during the critical expiry window. It combines `EXPIRY_LEDGER_INVARIANTS.md` and `EXPIRY_CHAOS_GO_NO_GO.md` into an operational checklist with explicit pass/fail states.

**Exercise Duration:** 45-60 minutes  
**Participants:** System Operator, Risk Manager, Technical Lead (minimum)  
**Prerequisites:** All 5 pre-session gates passed (see `EXPIRY_CHAOS_GO_NO_GO.md`)

---

## 1. Exercise Setup

### 1.1 Scenario Definition

**Scenario:** KXBTC-20250127-15M (BTC 15-minute market)  
**Trigger Time:** T-45 seconds before expiry  
**Failure Type:** Simulated process crash (SIGKILL to trading agent)  
**Recovery Goal:** Correct handling without ghost trades or position resurrection

### 1.2 Required Artifacts

| Artifact | Location | Purpose |
|----------|----------|---------|
| Last checkpoint | `/data/checkpoints/expiry/KXBTC-20250127-15M_T-60.json` | Recovery state |
| Venue positions | Kalshi API `/positions` endpoint | Reconciliation |
| Ledger state | Database query | Position verification |
| Log tail | `logs/trading_agent.log` | Event sequence |

### 1.3 Mock Data Setup

```python
# Simulated checkpoint state (created at T-60s)
MOCK_CHECKPOINT = {
    "timestamp_utc": "2025-01-27T14:59:00.000Z",
    "market_id": "KXBTC-20250127-15M",
    "seconds_to_expiry": 60.0,
    "positions": {
        "long_contracts": 5,
        "short_contracts": 0,
        "avg_entry_cents": 4850,
        "unrealized_pnl_cents": 75
    },
    "pending_orders": [
        {
            "order_id": "ord_pending_001",
            "side": "sell",
            "count": 5,
            "status": "pending",
            "placed_at": "2025-01-27T14:58:55.000Z"
        }
    ],
    "settlement_buffer": {
        "filled_count": 58,
        "is_grade": False,
        "last_sample_ts": "2025-01-27T14:58:58.000Z"
    },
    "agent_state": {
        "enabled": True,
        "lifecycle": "ACTIVE",
        "consecutive_errors": 0
    },
    "checksum": "sha256:abc123..."
}

# Simulated venue state (at T-30s, after restart)
MOCK_VENUE_STATE = {
    "positions": [
        {
            "ticker": "KXBTC-20250127-15M",
            "side": "yes",
            "count": 5,  # Matches checkpoint - good
            "avg_entry_price_cents": 4850
        }
    ],
    "orders": [
        {
            "order_id": "ord_pending_001",
            "status": "filled",  # Changed from pending!
            "filled_count": 5,
            "avg_fill_cents": 4925
        }
    ]
}
```

---

## 2. Phase-by-Phase Exercise Checklist

### Phase 0: Pre-Crash Baseline (T-5m to T-60s)

**Objective:** Establish normal operation baseline before simulated crash.

| Step | Action | Evidence | Pass/Fail |
|------|--------|----------|-----------|
| 0.1 | Verify agent running in paper mode | `mode: "paper"` in logs | ⬜ |
| 0.2 | Confirm checkpoint system writing every 30s | `checkpoint_written` events at :00, :30 | ⬜ |
| 0.3 | Verify buffer filling (>50/60 at T-5m) | `buffer_status: {filled_count: 52}` | ⬜ |
| 0.4 | Place test position (5 contracts long) | `order_routing_decision: {routed_to: "paper", count: 5}` | ⬜ |
| 0.5 | Confirm position tracked in ledger | `positions` table shows 5 contracts | ⬜ |
| 0.6 | Wait until T-60s checkpoint written | Last checkpoint shows `seconds_to_expiry: 60.0` | ⬜ |

**Phase 0 Status:** ⬜ **COMPLETE** / ⬜ **BLOCKED**

---

### Phase 1: Simulated Crash (T-45s)

**Objective:** Trigger controlled failure and observe immediate state.

| Step | Action | Evidence | Pass/Fail |
|------|--------|----------|-----------|
| 1.1 | Send SIGKILL to trading agent process | `kill -9 <pid>` executed | ⬜ |
| 1.2 | Record exact crash timestamp | Log shows abrupt stop, no shutdown sequence | ⬜ |
| 1.3 | Verify no checkpoint written between T-60s and crash | Last checkpoint remains at T-60s | ⬜ |
| 1.4 | Note pending order state at crash time | `ord_pending_001` was pending at T-60s checkpoint | ⬜ |

**Phase 1 Status:** ⬜ **CRASH COMPLETE** / ⬜ **ISSUE**

---

### Phase 2: Immediate Post-Crash (T-45s to T-30s)

**Objective:** Assess state without recovery attempt.

| Step | Action | Evidence | Pass/Fail |
|------|--------|----------|-----------|
| 2.1 | Query venue positions (do not act) | API response saved to `venue_state_T-30.json` | ⬜ |
| 2.2 | Query venue orders | `ord_pending_001` status noted | ⬜ |
| 2.3 | Read last checkpoint | `KXBTC-20250127-15M_T-60.json` loaded | ⬜ |
| 2.4 | Calculate time since last checkpoint | 15 seconds elapsed (T-60s to T-45s crash) | ⬜ |
| 2.5 | **DECISION POINT**: Is auto-restart safe? | See decision matrix below | ⬜ |

**Decision Matrix 2.5:**

| Condition | Threshold | Decision |
|-----------|-----------|----------|
| Time to expiry | >90s | May attempt restart |
| Time to expiry | 60-90s | **BLOCK - Extended guard only** |
| Time to expiry | <60s | **BLOCK - Settlement window active** |
| Pending orders | Any | **BLOCK - Reconciliation required** |
| Buffer status | <60 slots | **BLOCK - Incomplete data** |

**Our scenario:** T-45s, pending order exists → **BLOCK auto-restart**

**Phase 2 Status:** ⬜ **ANALYSIS COMPLETE** / ⬜ **RECOVERY BLOCKED** ⬜

---

### Phase 3: Manual Recovery Assessment (T-30s to T-15s)

**Objective:** Complete full reconciliation before any restart decision.

| Step | Action | Expected | Actual | Match |
|------|--------|----------|--------|-------|
| 3.1 | **LI-4: Exposure consistency** | | | |
| | Checkpoint exposure | 5 contracts long | __ | ⬜ |
| | Venue exposure | 5 contracts long | __ | ⬜ |
| | Mismatch? | None expected | __ | ⬜ |
| 3.2 | **LI-1: Ghost order check** | | | |
| | Checkpoint pending orders | 1 order (ord_pending_001) | __ | ⬜ |
| | Venue order status | Check if filled/cancelled | __ | ⬜ |
| | If venue shows filled | Update checkpoint | __ | ⬜ |
| | If venue shows cancelled | Clear from pending | __ | ⬜ |
| 3.3 | **LI-3: Position resurrection check** | | | |
| | Checkpoint position closed? | No | __ | ⬜ |
| | Venue position open? | Yes (5 contracts) | __ | ⬜ |
| | Resurrection risk? | No (both agree open) | __ | ⬜ |
| 3.4 | **LI-5: Timestamp sanity** | | | |
| | Checkpoint time | T-60s | __ | ⬜ |
| | Current time | T-30s | __ | ⬜ |
| | Settlement time | T-0s | __ | ⬜ |
| | Monotonic? | Yes (T-60 < T-30 < T-0) | __ | ⬜ |

**Phase 3 Status:** ⬜ **RECONCILIATION PASS** / ⬜ **RECONCILIATION FAIL**

**If FAIL:** Document discrepancy, operator must resolve manually before proceeding.

---

### Phase 4: Recovery Decision (T-15s)

**Objective:** Make explicit go/no-go decision for restart.

| Criterion | Gate | Status | Evidence |
|-----------|------|--------|----------|
| R1 | Reconciliation clean? | ⬜ | Phase 3 all checks passed |
| R2 | Time to expiry >90s? | ⬜ **NO** | T-15s remaining |
| R3 | Extended guard acceptable? | ⬜ **YES** | 120s window, buffer will fill |
| R4 | No pending orders? | ⬜ **DEPENDS** | ord_pending_001 status resolved? |
| R5 | Operator approval? | ⬜ | Manual sign-off |

**Recovery Decision:**

With T-15s remaining, we have 3 options:

1. **NO-RESTART (Recommended):** Let expiry complete, reconcile post-settlement
2. **MONITOR-ONLY RESTART:** Start agent with `enabled: false`, observe only
3. **EMERGENCY CLOSE:** Manual market-order close via Kalshi UI, no agent restart

**Exercise Decision for This Run:** ⬜ **Option 1 - No Restart** / ⬜ **Option 2 - Monitor** / ⬜ **Option 3 - Emergency Close**

---

### Phase 5: Post-Settlement Reconciliation (T+5m)

**Objective:** Verify ledger integrity after settlement.

| Step | Action | Expected | Actual | Pass |
|------|--------|----------|--------|------|
| 5.1 | **LI-2: Settlement price verification** | | | |
| | Fetch announced settlement | From Kalshi API | __ | ⬜ |
| | Calculate expected from buffer | RTI average | __ | ⬜ |
| | Match within 1 cent? | Yes | __ | ⬜ |
| 5.2 | **Position closure verification** | | | |
| | Venue position closed? | Yes | __ | ⬜ |
| | Ledger position marked settled? | Yes | __ | ⬜ |
| | PnL calculated correctly? | (4925 - 4850) × 5 = $3.75 | __ | ⬜ |
| 5.3 | **Final checkpoint** | | | |
| | Write post-settlement checkpoint | `status: "settled"` | __ | ⬜ |
| | Include settlement price | In checkpoint | __ | ⬜ |

**Phase 5 Status:** ⬜ **SETTLEMENT VERIFIED** / ⬜ **SETTLEMENT ISSUE**

---

## 3. Evidence Capture Checklist

**All artifacts must be saved for post-exercise review:**

- [ ] `phase_0_baseline_logs.txt` - Pre-crash log extract
- [ ] `checkpoint_T-60.json` - Last valid checkpoint
- [ ] `crash_timestamp.txt` - Exact crash time
- [ ] `venue_state_T-30.json` - Post-crash venue query
- [ ] `reconciliation_report_phase3.md` - Step 3.1-3.4 results
- [ ] `recovery_decision_record.txt` - Phase 4 decision with rationale
- [ ] `settlement_price_verification.json` - Phase 5 settlement check
- [ ] `exercise_signoff.txt` - All participants signed

---

## 4. Pass/Fail Criteria

### Exercise Pass Criteria (all must pass)

| # | Criterion | Verification |
|---|-----------|--------------|
| P1 | Checkpoint system working | Checkpoints written at 30s intervals pre-crash |
| P2 | Crash detection | Abrupt stop logged, no graceful shutdown |
| P3 | Reconciliation procedure followed | Phase 3 completed before any restart attempt |
| P4 | Correct restart decision | Decision blocked due to T-45s < 90s threshold |
| P5 | No ghost orders | ord_pending_001 correctly resolved (not double-counted) |
| P6 | Ledger consistent | Pre- and post-crash exposure matched within tolerance |
| P7 | Settlement verified | Price matched calculation, positions closed correctly |

### Exercise Fail Criteria (any is a fail)

| # | Criterion | Consequence |
|---|-----------|-------------|
| F1 | Auto-restart without reconciliation | Position resurrection risk |
| F2 | Ghost order in final ledger | Double-counting, incorrect PnL |
| F3 | Settlement price mismatch | Trading against wrong price |
| F4 | Reconciliation skipped | Unknown state at settlement |
| F5 | Checkpoint corruption | Unreliable recovery state |

---

## 5. Post-Exercise Review Questions

**For all participants to answer before sign-off:**

1. **Timing:** Did the T-45s crash timing feel realistic? Would earlier/later be more valuable?

2. **Reconciliation:** Was the 3-step reconciliation (3.1-3.4) clear and executable under pressure?

3. **Decision:** Did the T-15s decision matrix provide clear guidance, or was judgment still required?

4. **Documentation:** Were evidence capture steps realistic to complete during the exercise?

5. **Gaps:** What other restart scenarios should we tabletop? (e.g., multi-agent restart, venue API unavailable)

---

## 6. Sign-Off Sheet

**Exercise completed:** _______________  
**Scenario:** KXBTC-20250127-15M crash at T-45s

| Role | Name | Date | Pass/Fail | Signature |
|------|------|------|-----------|-----------|
| System Operator | | | ⬜ | |
| Risk Manager | | | ⬜ | |
| Technical Lead | | | ⬜ | |
| QA Observer | | | ⬜ | |

**Overall Exercise Result:** ⬜ **PASS** / ⬜ **FAIL** (see criteria above)

**Notes/Deviations:**

_______________________________________________

_______________________________________________

---

## 7. Quick Reference: Exercise Commands

```bash
# Pre-exercise: Setup
export EXERCISE_DATE=2025-01-27
export EXERCISE_MARKET=KXBTC-20250127-15M
mkdir -p /data/exercise/$EXERCISE_DATE

# Phase 0: Verify checkpoint system
tail -f logs/trading_agent.log | grep checkpoint_written

# Phase 1: Simulate crash
pkill -9 -f "kalshi_trading_agent.*$EXERCISE_MARKET"
echo "$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ) CRASH SIMULATED" >> /data/exercise/$EXERCISE_DATE/crash_timestamp.txt

# Phase 2: Query venue state
curl -s https://api.elections.kalshi.com/trade-api/v2/positions > /data/exercise/$EXERCISE_DATE/venue_state_T-30.json
curl -s https://api.elections.kalshi.com/trade-api/v2/orders > /data/exercise/$EXERCISE_DATE/orders_T-30.json

# Phase 3: Load checkpoint
python3 -c "import json; cp = json.load(open('/data/checkpoints/expiry/${EXERCISE_MARKET}_T-60.json')); print(json.dumps(cp, indent=2))"

# Phase 5: Verify settlement
curl -s "https://api.elections.kalshi.com/trade-api/v2/markets/$EXERCISE_MARKET" | jq '{ticker, settlement_price, status}'
```

---

## Related Documents

- `EXPIRY_LEDGER_INVARIANTS.md` — Ledger consistency rules referenced throughout
- `EXPIRY_CHAOS_GO_NO_GO.md` — Decision framework for pre-session gates
- `EXPIRY_DRY_RUN_LOG_SPEC.md` — Log format specification for evidence capture
- `EXPIRY_CHAOS_TEST_PLAN.md` — Scenario C5 covers this restart case

---

*Document Version: 1.0*
*Last Updated: 2025-01-26*
*Part of: Kalshi Expiry Chaos Audit*
