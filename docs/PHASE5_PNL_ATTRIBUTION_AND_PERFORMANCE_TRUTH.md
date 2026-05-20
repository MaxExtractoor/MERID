# Phase 5: PnL, Attribution, and Performance Truth

**Date:** 2026-05-12  
**Scope:** MERID Kalshi Trading System (15m BTC/ETH/SOL/XRP/DOGE)  
**Purpose:** Validate canonical PnL engine, reconciliation correctness, and strategy attribution accuracy

---

## Executive Summary

This document defines validation checks for PnL, attribution, and performance truth. All PnL calculations must use a canonical engine, reconciliation must be accurate and complete, and strategy attribution must correctly attribute performance to sources.

---

## Canonical PnL Engine

### Requirement 1: Single Source of Truth for PnL

**Statement:** All PnL calculations must use a single canonical source of truth.

**Current Implementation:**
- `fills_ledger.py` - Canonical fills ledger (Kalshi is the ONLY source of truth)
- `portfolio_pnl_computer.py` - Real-time PnL computation from positions + marks
- `pnl_attribution.py` - Post-trade PnL attribution for debate system
- `hedging/pnl_tracker.py` - Hedge PnL attribution
- Multiple PnL calculation paths (fills_ledger, position_cache, portfolio_engine)

**Validation:**
- Fills ledger is the ONLY source of truth for realized PnL
- Position cache PnL must match fills_ledger PnL (within tolerance)
- Portfolio engine PnL must match fills_ledger PnL (within tolerance)
- No other PnL calculation sources allowed
- All PnL queries must route through canonical engine

**Thresholds:**
- PnL drift tolerance: 10 cents
- Alert threshold: 1 cent drift
- Kill threshold: 100 cents drift

**Enforcement Point:** Reconciliation checks, PnL drift validation

**Violation Action:** Log error, alert operator, investigate drift source

---

### Requirement 2: PnL Calculation Correctness

**Statement:** PnL calculations must be mathematically correct and consistent.

**Current Implementation:**
- `portfolio_pnl_computer.py` computes: `(mark - entry) * quantity` for long, `(entry - mark) * abs(quantity)` for short
- `fills_ledger.py` stores fill data with `fee_cost`, `proceeds_dollars`
- `pnl_attribution.py` calculates debate sizing impact

**Validation:**
- Realized PnL formula: `(exit_price - entry_price) * quantity - fees`
- Unrealized PnL formula: `(mark_price - entry_price) * quantity`
- Fee calculations match Kalshi fee schedule
- PnL calculations use integer arithmetic in cents (avoid float drift)
- Long vs short PnL calculations are correct

**Enforcement Point:** Unit tests, invariant checks, reconciliation

**Violation Action:** Log error, alert operator, fix calculation

---

### Requirement 3: PnL Consistency Across Sources

**Statement:** PnL must be consistent across all calculation sources.

**Current Implementation:**
- Portfolio reconciliation compares: position_cache vs fills_ledger PnL
- Accounting equation validation: `equity = initial + deposits - withdrawals + realized + unrealized`

**Validation:**
- Position cache realized PnL == fills_ledger realized PnL (within tolerance)
- Portfolio engine PnL == fills_ledger PnL (within tolerance)
- Bankroll service equity == calculated equity (within tolerance)
- Accounting equation holds (within tolerance)

**Thresholds:**
- PnL tolerance: 10 cents
- Equity tolerance: 50 cents
- Alert on drift > 1 cent

**Enforcement Point:** Portfolio reconciliation loop (every 5 minutes)

**Violation Action:** Log warning, alert operator, investigate drift

---

### Requirement 4: Real-Time vs End-of-Day PnL

**Statement:** Real-time PnL must match end-of-day PnL when markets close.

**Current Implementation:**
- `portfolio_pnl_computer.py` updates on every price tick
- Fills ledger stores canonical fill data
- Settlement poller handles market settlements

**Validation:**
- Real-time unrealized PnL recomputed on every price update
- At market close, unrealized PnL becomes realized
- Realized PnL from settlement matches fills_ledger PnL
- No PnL jump at settlement (smooth transition)

**Thresholds:**
- PnL jump tolerance: 10 cents at settlement
- Alert on jump > 1 cent

**Enforcement Point:** Settlement validation, reconciliation

**Violation Action:** Log error, alert operator, investigate settlement

---

## Reconciliation

### Requirement 1: Position Reconciliation

**Statement:** Internal positions must match venue-reported positions.

**Current Implementation:**
- `reconciliation.py` - Compares MERID positions vs venue positions
- `portfolio_reconciliation.py` - Continuous reconciliation loop against Kalshi API
- PositionDiscrepancy dataclass for mismatch reporting

**Validation:**
- MERID position count == Kalshi position count
- MERID position quantity == Kalshi position quantity (exact match)
- MERID entry price == Kalshi entry price (within 1 cent tolerance)
- No positions in MERID but not in Kalshi (critical)
- No positions in Kalshi but not in MERID (critical)

**Thresholds:**
- Quantity tolerance: 0 contracts (exact match required)
- Price tolerance: 1 cent
- Critical: Missing position on either side
- Warning: Quantity mismatch > 0

**Enforcement Point:** Reconciliation loop (every 5 minutes), execution gate

**Violation Action:** Log warning, alert operator, kill switch if critical

---

### Requirement 2: Cash Reconciliation

**Statement:** Internal cash balance must match venue-reported cash.

**Current Implementation:**
- `portfolio_reconciliation.py` compares: internal cash vs Kalshi balance
- Bankroll service v2 provides canonical bankroll
- Tolerance configured via env var

**Validation:**
- MERID cash available == Kalshi cash available (within tolerance)
- MERID portfolio value == Kalshi portfolio value (within tolerance)
- MERID equity == Kalshi equity (within tolerance)

**Thresholds:**
- Cash tolerance: 1 cent (configurable via `MERID_PORTFOLIO_CASH_TOLERANCE_CENTS`)
- Equity tolerance: 50 cents
- Alert on drift > tolerance

**Enforcement Point:** Reconciliation loop (every 5 minutes)

**Violation Action:** Log warning, alert operator, investigate cash drift

---

### Requirement 3: PnL Reconciliation

**Statement:** Internal PnL must match venue-reported PnL.

**Current Implementation:**
- `portfolio_reconciliation.py` compares: internal PnL vs Kalshi PnL
- PnL calculated from: portfolio_value - cash
- Tolerance configured via env var

**Validation:**
- MERID realized PnL == Kalshi realized PnL (within tolerance)
- MERID unrealized PnL == Kalshi unrealized PnL (within tolerance)
- Total PnL matches (within tolerance)

**Thresholds:**
- PnL tolerance: 10 cents (configurable via `MERID_PORTFOLIO_PNL_TOLERANCE_CENTS`)
- Alert on drift > tolerance

**Enforcement Point:** Reconciliation loop (every 5 minutes)

**Violation Action:** Log warning, alert operator, investigate PnL drift

---

### Requirement 4: Accounting Equation Validation

**Statement:** Fundamental accounting equation must hold.

**Current Implementation:**
- `portfolio_reconciliation.py` validates: `equity = initial + deposits - withdrawals + realized + unrealized`
- Cash ledger tracks deposits/withdrawals
- Fills ledger tracks realized PnL
- Position cache tracks unrealized PnL

**Validation:**
- Accounting equation holds (within tolerance)
- Deposits/withdrawals tracked correctly
- Realized PnL from fills_ledger used
- Unrealized PnL from position_cache used

**Thresholds:**
- Accounting tolerance: 10 cents
- Alert on violation > tolerance

**Enforcement Point:** Reconciliation loop (every 5 minutes)

**Violation Action:** Log warning, alert operator, investigate accounting error

---

### Requirement 5: Reconciliation Frequency

**Statement:** Reconciliation must run frequently enough to catch discrepancies quickly.

**Current Implementation:**
- Reconciliation interval: 5 minutes (configurable via `MERID_PORTFOLIO_RECONCILIATION_INTERVAL_SECONDS`)
- Discrepancy persistence: 2 cycles before alert (configurable)

**Validation:**
- Reconciliation runs at configured interval
- Discrepancies persist for N cycles before alerting (avoid false positives)
- Critical discrepancies alert immediately
- Reconciliation results stored for investigation

**Thresholds:**
- Reconciliation interval: 5 minutes (default)
- Discrepancy persistence: 2 cycles (default)
- Critical alert: immediate

**Enforcement Point:** Reconciliation loop configuration

**Violation Action:** Log warning, alert operator, adjust frequency

---

## Strategy Attribution

### Requirement 1: Trade-to-Strategy Mapping

**Statement:** Every trade must be attributed to the correct strategy/agent.

**Current Implementation:**
- `pnl_attribution.py` tracks: agent_id, debate_multiplier, debate_recommendation
- `fills_ledger.py` stores: agent_id, intent_id, decision_trace_id
- Order router tracks caller module for audit

**Validation:**
- Every fill has agent_id populated
- Every fill has intent_id populated (links to original signal)
- Every fill has decision_trace_id (end-to-end audit trail)
- Agent attribution is correct (no misattribution)

**Enforcement Point:** Fill ingestion validation

**Violation Action:** Log error, alert operator, investigate attribution

---

### Requirement 2: PnL Attribution by Strategy

**Statement:** PnL must be correctly attributed to each strategy.

**Current Implementation:**
- `pnl_attribution.py` calculates: base_pnl, debate_pnl_impact, exit_pnl_impact
- `agent_performance_tracker.py` tracks per-agent metrics
- Attribution records stored in database

**Validation:**
- Realized PnL attributed to correct strategy
- Debate sizing impact calculated correctly
- Debate exit impact calculated correctly
- Total debate contribution = sizing + exit impact
- Attribution records stored persistently

**Thresholds:**
- Attribution accuracy: 100%
- Alert on misattribution

**Enforcement Point:** Attribution calculation, database storage

**Violation Action:** Log error, alert operator, fix attribution logic

---

### Requirement 3: Hedge PnL Attribution

**Statement:** Hedge PnL must be tracked separately from alpha PnL.

**Current Implementation:**
- `hedging/pnl_tracker.py` tracks: hedge_pnl, alpha_pnl, effectiveness_ratio
- HedgePnLRecord links hedge fill to originating alpha fill
- Separate metrics for hedge performance

**Validation:**
- Hedge positions marked with fill_source = "hedge"
- Alpha positions marked with fill_source = "alpha"
- Hedge PnL calculated separately
- Alpha PnL calculated separately
- Effectiveness ratio calculated correctly

**Thresholds:**
- Hedge attribution accuracy: 100%
- Alert on hedge misattribution

**Enforcement Point:** Hedge fill ingestion, PnL calculation

**Violation Action:** Log error, alert operator, fix hedge attribution

---

### Requirement 4: Attribution Aggregation

**Statement:** Attribution metrics must be aggregated correctly.

**Current Implementation:**
- `pnl_attribution.py` provides: AttributionSummary with agent/tier/symbol contributions
- `agent_performance_tracker.py` aggregates per-agent metrics
- Attribution summaries stored in database

**Validation:**
- Agent contributions sum to total PnL
- Tier contributions sum to total PnL
- Symbol contributions sum to total PnL
- Win rates calculated correctly
- Contribution percentages calculated correctly

**Thresholds:**
- Aggregation accuracy: 100%
- Sum tolerance: 1 cent

**Enforcement Point:** Attribution aggregation calculation

**Violation Action:** Log error, alert operator, fix aggregation logic

---

### Requirement 5: Attribution Time Window

**Statement:** Attribution must be calculated over appropriate time windows.

**Current Implementation:**
- `pnl_attribution.py` supports: lookback periods, max attribution period
- Attribution calculated for completed trades
- Unrealized PnL calculated for open trades

**Validation:**
- Attribution calculated for completed trades (entry + exit)
- Unrealized attribution for open trades (current mark)
- Time windows configured correctly (daily, weekly, monthly)
- Attribution period limits enforced (max 30 days)

**Thresholds:**
- Attribution period: max 30 days
- Min holding period: 0.1 hours

**Enforcement Point:** Attribution calculation configuration

**Violation Action:** Log warning, alert operator, adjust time window

---

## Automated Test Plan

### Test Suite: `tests/pnl/test_pnl_attribution_and_performance_truth.py`

**Test Classes:**

1. `TestCanonicalPnLEngine`
   - Test: single source of truth enforcement
   - Test: PnL calculation correctness
   - Test: PnL consistency across sources
   - Test: real-time vs end-of-day PnL
   - Test: integer arithmetic in cents

2. `TestPositionReconciliation`
   - Test: position count match
   - Test: position quantity match
   - Test: position entry price match
   - Test: missing position detection
   - Test: extra position detection

3. `TestCashReconciliation`
   - Test: cash balance match
   - Test: portfolio value match
   - Test: equity match
   - Test: tolerance enforcement
   - Test: drift alerting

4. `TestPnLReconciliation`
   - Test: realized PnL match
   - Test: unrealized PnL match
   - Test: total PnL match
   - Test: PnL drift detection
   - Test: PnL drift alerting

5. `TestAccountingEquationValidation`
   - Test: equation holds
   - Test: deposits tracked correctly
   - Test: withdrawals tracked correctly
   - Test: realized PnL from fills_ledger
   - Test: unrealized PnL from position_cache

6. `TestTradeToStrategyMapping`
   - Test: agent_id populated
   - Test: intent_id populated
   - Test: decision_trace_id populated
   - Test: attribution correctness
   - Test: audit trail completeness

7. `TestPnLAttributionByStrategy`
   - Test: realized PnL attribution
   - Test: debate sizing impact
   - Test: debate exit impact
   - Test: total debate contribution
   - Test: attribution persistence

8. `TestHedgePnLAttribution`
   - Test: hedge fill_source marking
   - Test: alpha fill_source marking
   - Test: hedge PnL calculation
   - Test: alpha PnL calculation
   - Test: effectiveness ratio

9. `TestAttributionAggregation`
   - Test: agent contributions sum
   - Test: tier contributions sum
   - Test: symbol contributions sum
   - Test: win rate calculation
   - Test: contribution percentage calculation

**Total Target:** 80+ PnL/attribution tests

---

## Implementation Roadmap

### Step 1: Document Current State (DONE)
- ✅ Identify PnL calculation sources (fills_ledger, position_cache, portfolio_engine)
- ✅ Identify reconciliation modules (reconciliation.py, portfolio_reconciliation.py)
- ✅ Identify attribution modules (pnl_attribution.py, hedging/pnl_tracker.py)
- ✅ Identify PnL computer (portfolio_pnl_computer.py)
- ✅ Document current implementation

### Step 2: Define Validation Checks (DONE)
- ✅ Define canonical PnL engine requirements
- ✅ Define reconciliation requirements
- ✅ Define strategy attribution requirements

### Step 3: Implement Canonical PnL Engine Enhancements (NEXT)
- [ ] Enforce fills_ledger as single source of truth
- [ ] Add PnL drift validation (position_cache vs fills_ledger)
- [ ] Add PnL drift validation (portfolio_engine vs fills_ledger)
- [ ] Add accounting equation validation
- [ ] Add PnL drift alerting

### Step 4: Implement Reconciliation Enhancements
- [ ] Add position reconciliation validation
- [ ] Add cash reconciliation validation
- [ ] Add PnL reconciliation validation
- [ ] Add accounting equation validation
- [ ] Add reconciliation frequency monitoring

### Step 5: Implement Strategy Attribution Enhancements
- [ ] Add trade-to-strategy mapping validation
- [ ] Add PnL attribution by strategy validation
- [ ] Add hedge PnL attribution validation
- [ ] Add attribution aggregation validation
- [ ] Add attribution time window validation

### Step 6: Implement Test Suite
- [ ] Create `tests/pnl/test_pnl_attribution_and_performance_truth.py`
- [ ] Implement all 9 test classes
- [ ] Target: 80+ tests passing
- [ ] Wire into CI pipeline

### Step 7: Add Monitoring and Alerting
- [ ] Add Prometheus metrics for PnL drift
- [ ] Add alerting for PnL drift
- [ ] Add alerting for reconciliation discrepancies
- [ ] Add alerting for attribution errors
- [ ] Add dashboard for PnL truth

---

## Success Criteria

Phase 5 is complete when:

1. ✅ This design document is approved
2. [ ] Canonical PnL engine is enforced and validated
3. [ ] Reconciliation is accurate and complete
4. [ ] Strategy attribution is correct and validated
5. [ ] All 80+ PnL/attribution tests are implemented and passing
6. [ ] Monitoring and alerting are wired
7. [ ] CI pipeline includes PnL/attribution test suite
8. [ ] No PnL drift detected in production
9. [ ] No reconciliation discrepancies in production
10. [ ] No attribution errors in production

---

## References

- `merid/event_venues/kalshi/fills_ledger.py` - Canonical fills ledger
- `merid/event_venues/kalshi/portfolio_pnl_computer.py` - Real-time PnL computation
- `merid/event_venues/kalshi/portfolio_reconciliation.py` - Continuous reconciliation
- `merid/reconciliation.py` - Position reconciliation
- `merid/prediction/pnl_attribution.py` - Strategy PnL attribution
- `merid/hedging/pnl_tracker.py` - Hedge PnL attribution
- `merid/prediction/agent_performance_tracker.py` - Agent performance metrics
- `merid/event_venues/kalshi/position_cache.py` - Position cache
- `merid/event_venues/kalshi/portfolio_engine.py` - Portfolio engine
- `merid/event_venues/kalshi/bankroll_service_v2.py` - Bankroll service

---

**Next Phase:** Phase 6 - Reliability, kill switches, and monitoring (global/per-venue kill switches, strategy throttles, monitoring/alerting)
