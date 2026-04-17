# LIVE ROLLOUT PLAN

**Purpose**: Phased transition from paper to live trading with progressive risk exposure.

## Phase 0: Pre-Live Hardening (Paper Only)

**Objective**: Prove safety rails work before any live exposure.

**Configuration**:
- `MERID_TRADE_MODE=paper`
- `MERID_ALLOW_LIVE_TRADES=false`
- Kill switch threshold: **300ms lag**
- Position caps: ≤ **$10/market**, ≤ **$50 global**, **5% Kelly**
- Market restriction: **BTC-daily-only**

**Verification**:
1. Start backend with Phase 0 config
2. Confirm via `/api/health` and `/health/event_loop`:
   - New thresholds are active
   - Auto-halt wiring behaves (simulated lag > 300ms triggers block)
3. Run 5-minute paper test with BTC-daily agent
4. Document results in `fix_history.md`

**Completion Criteria**:
- [ ] Safety rails active and tested
- [ ] No live trades executed (paper only)
- [ ] Phase 0 sign-off in `fix_history.md`

---

## Phase 1: First Live Gate (Minimal Exposure)

**Objective**: First live trades with extremely tight risk limits.

**Prerequisites**:
- Phase 0 completed
- `PRE_LIVE_CHECKLIST.md` fully signed off
- All 4 paper gates passed

**Configuration**:
- `MERID_TRADE_MODE=paper` (start)
- Manual flip to: `MERID_TRADE_MODE=live`, `MERID_ALLOW_LIVE_TRADES=true`
- Kill switch threshold: **300ms lag** (tight)
- Position caps: ≤ **$5/market**, ≤ **$25 global**, **3% Kelly** (tighter than Phase 0)
- Market restriction: **BTC-daily-only**
- Duration: **15-minute live gate**

**Execution Steps**:
1. Complete `PRE_LIVE_CHECKLIST.md` sign-off
2. Start backend in paper mode with Phase 1 config
3. Verify health endpoints responding
4. **Manual transition**: Flip env vars to live mode
5. Confirm live mode active (check logs, health endpoint)
6. Monitor continuously for 15 minutes:
   - Event-loop lag P95 < 500ms
   - `degraded=false` throughout
   - Position fills correct
   - No errors in execution
7. **At 15 minutes or on any anomaly**: Flip back to paper mode
8. Document results in `fix_history.md`

**Rollback Conditions (Immediate)**:
- P95 lag ≥ 500ms for 2+ consecutive samples
- `degraded=true` persists > 30 seconds
- Any live trade error or unexpected behavior
- Operator discretion (any concern)

**Completion Criteria**:
- [ ] 15-minute live gate completed without rollback
- [ ] All trades executed correctly
- [ ] No anomalies in `fix_history.md`

---

## Phase 2: Extended Live (Moderate Exposure)

**Objective**: Longer live sessions with slightly relaxed limits.

**Prerequisites**:
- Phase 1 completed successfully
- No anomalies from Phase 1

**Configuration**:
- Kill switch threshold: **500ms lag**
- Position caps: ≤ **$15/market**, ≤ **$100 global**, **8% Kelly**
- Market restriction: **BTC-daily + BTC-4hour** (expanded)
- Duration: **1-hour live session**

**Completion Criteria**:
- [ ] 1-hour live session completed
- [ ] Performance metrics within expected bounds

---

## Phase 3: Full Production (Normal Exposure)

**Objective**: Normal trading operations with standard risk limits.

**Prerequisites**:
- Phase 2 completed successfully
- Multiple 1-hour sessions without issues

**Configuration**:
- Kill switch threshold: **1000ms lag** (production default)
- Position caps: ≤ **$50/market**, ≤ **$500 global**, **15% Kelly** (full)
- Market restriction: **All supported markets**
- Duration: **Continuous operation**

**Ongoing Requirements**:
- Daily review of `fix_history.md`
- Weekly validation gate (30-minute paper)
- Immediate rollback on any anomaly

---

## Emergency Procedures

### Immediate Halt (Any Phase)

```bash
# 1. Flip to paper (stops new live trades)
export MERID_TRADE_MODE=paper
export MERID_ALLOW_LIVE_TRADES=false

# 2. Trigger emergency halt
curl -X POST http://127.0.0.1:8011/api/v1/operator/emergency-halt \
  -H "Authorization: Bearer $MERID_OPERATOR_TOKEN"

# 3. Activate kill switch
curl -X POST http://127.0.0.1:8011/api/v1/kalshi-grid/kill-switch \
  -H "Authorization: Bearer $MERID_OPERATOR_TOKEN"
```

### Post-Halt Actions

1. **Document**: Open ANOMALY entry in `fix_history.md`
2. **Investigate**: Root cause analysis
3. **Fix**: Apply fix and test in paper
4. **Re-validate**: Run 30-minute paper gate
5. **Re-enter**: Only at appropriate phase level

---

*This plan is append-only. Any phase can be repeated or extended based on validation results.*
