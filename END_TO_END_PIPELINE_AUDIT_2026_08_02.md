# End-to-End Pipeline Audit Checklist
**Date**: 2026-08-02  
**Scope**: BTC, ETH, SOL, XRP, DOGE 15-minute Kalshi markets  
**Purpose**: Hunt for remaining design flaws that can silently suppress trades or distort edge  
**Method**: Structured shadow replay with upstream/midstream/downstream verification

## Executive Summary

The microstructure gate bug has been fixed and comprehensive guardrails implemented. This audit focuses on pipeline-wide alignment to ensure no upstream or downstream component silently contradicts the new microstructure policy.

## Audit Strategy

**Approach**: End-to-end shadow replay with immutable candidate tracing  
**Assets**: BTC, ETH, SOL, XRP, DOGE (one candidate per asset)  
**Method**: Trace from signal generation to execution with single immutable record  
**Goal**: Verify canonical side basis, unit conversions, and gate consistency across pipeline

---

# UPSTREAM AUDIT

## 1. Signal Generation Verification

### 1.1 Canonical Probability Convention
**Objective**: Verify signal generation uses one canonical probability convention end-to-end.

**Checklist**:
- [ ] **BTC**: Verify `p_hat_yes` is in consistent units (0-1 fraction vs 0-100 percent) across:
  - Signal generation (`agent_grid_15m.py`)
  - Allocator (`order_router.py`)
  - Gate (`spread_edge_analytics.py`)
  - Router (`order_router.py`)
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: All components use same convention (0-1 fraction or 0-100 percent) consistently.

**Failure Mode**: Mixed conventions cause edge miscalculation (e.g., 0.6 vs 60c treated as same value).

### 1.2 Side Mapping Consistency
**Objective**: Confirm side mapping for YES/NO cannot flip between allocator and router.

**Checklist**:
- [ ] **BTC**: Trace `order_side` ("yes"/"no") through:
  - Signal generation output
  - Allocator side assignment
  - Gate side parameter
  - Router execution side
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: Side mapping is immutable from signal to execution.

**Failure Mode**: Side flip causes YES order to execute as NO (or vice versa), inverting edge.

### 1.3 Normalization and Rounding
**Objective**: Recheck any normalization, rounding, or percent-vs-fraction conversions.

**Checklist**:
- [ ] **BTC**: Verify all price/edge conversions:
  - Model probability → cents conversion
  - Bid/ask normalization
  - Edge calculation rounding
  - Threshold comparison precision
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: Consistent rounding rules (e.g., always round to nearest cent, never truncate).

**Failure Mode**: Rounding errors cause valid edges to fall below threshold by 0.01c.

### 1.4 Feature Contract Consistency
**Objective**: Audit whether BTC/ETH/SOL/XRP/DOGE signals are generated from same feature contract.

**Checklist**:
- [ ] **BTC**: Verify feature engineering:
  - Input features (price, volume, orderbook depth)
  - Feature normalization
  - Model input format
- [ ] **ETH**: Compare feature contract to BTC
- [ ] **SOL**: Compare feature contract to BTC
- [ ] **XRP**: Compare feature contract to BTC
- [ ] **DOGE**: Compare feature contract to BTC

**Expected**: All assets use same feature contract structure (asset-specific values, same structure).

**Failure Mode**: Different feature contracts cause model bias or inconsistent signal quality.

---

# MIDSTREAM AUDIT

## 2. Gate Structure Separation

### 2.1 Eligibility Module
**Objective**: Separate eligibility checks (data quality, structural validity).

**Checklist**:
- [ ] **BTC**: Verify eligibility checks are isolated:
  - Crossed-book detection
  - Quote freshness
  - Data validation
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: Eligibility checks are in separate module/function, not mixed with economics.

**Failure Mode**: Eligibility failures misclassified as economics failures (confusing debug).

### 2.2 Economics Module
**Objective**: Separate economics checks (edge, spread cost, maker/taker).

**Checklist**:
- [ ] **BTC**: Verify economics checks are isolated:
  - Edge calculation
  - Spread cost calculation
  - Maker/taker economics mode
  - Ratio calculation
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: Economics checks are in separate module/function with clear maker/taker distinction.

**Failure Mode**: Economics failures misclassified or maker/taker mode overwritten.

### 2.3 Policy Module
**Objective**: Separate policy checks (intent, aggressiveness, risk limits).

**Checklist**:
- [ ] **BTC**: Verify policy checks are isolated:
  - Maker/taker intent
  - Aggressiveness settings
  - Risk limits
  - Position sizing
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: Policy checks are in separate module/function, not mixed with economics.

**Failure Mode**: Policy decisions silently overridden by downstream heuristics.

### 2.4 Threshold Module
**Objective**: Separate threshold checks (ratio, spread cap, depth).

**Checklist**:
- [ ] **BTC**: Verify threshold checks are isolated:
  - Time-to-expiry scaling
  - Asset-specific thresholds
  - Ratio comparison
  - Spread cap comparison
  - Depth comparison
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: Threshold checks are in separate module/function with asset-specific calibration.

**Failure Mode**: Threshold failures misclassified or asset calibration leaking between assets.

## 3. Gate Decision Composability

### 3.1 Composable and Traceable Decisions
**Objective**: Ensure gate decisions are composable and traceable instead of one opaque reject path.

**Checklist**:
- [ ] **BTC**: Verify gate decision structure:
  - Each check returns explicit decision (accept/reject + reason)
  - Decision reasons are distinct and deterministic
  - Decision trace is logged end-to-end
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: Gate decisions are composable (can add/remove checks without breaking) and traceable (clear rejection reason).

**Failure Mode**: Opaque reject path makes debugging impossible; cannot tell which check failed.

### 3.2 Maker/Taker Intent Preservation
**Objective**: Verify maker/taker intent is carried forward without being overwritten.

**Checklist**:
- [ ] **BTC**: Trace `use_maker_economics` parameter:
  - Policy decision (maker vs taker)
  - Gate parameter passing
  - Edge calculation mode
  - Order submission type (limit vs market)
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: Maker/taker intent is immutable from policy to execution.

**Failure Mode**: Maker order executed as taker (or vice versa), causing unexpected fees/spread costs.

## 4. Legacy Gate Detection

### 4.1 Active Gate Inventory
**Objective**: Inventory all active gates for 15-minute stack and disable/tag legacy ones.

**Checklist**:
- [ ] **BTC**: Inventory all gate functions:
  - New microstructure gate (`spread_edge_analytics.py`)
  - Legacy gates (if any)
  - Shadow gates (if any)
  - Tag each as active/legacy/shadow
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: Only new microstructure gate is active for 15-minute markets; legacy gates disabled or tagged.

**Failure Mode**: Legacy shadow gate still active, silently suppressing trades despite new gate passing.

### 4.2 Gate Consistency
**Objective**: Confirm new microstructure gate is the only active gate for 15-minute markets.

**Checklist**:
- [ ] **BTC**: Verify gate execution flow:
  - Only one gate function called
  - No duplicate gate checks
  - No gate bypass logic
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: Single gate execution path with clear entry/exit points.

**Failure Mode**: Multiple gates create conflicting decisions or unexpected rejections.

---

# DOWNSTREAM AUDIT

## 5. Execution Routing Consistency

### 5.1 Economics Mode Consistency
**Objective**: Confirm order-router edge calculation uses same economics mode that policy chose.

**Checklist**:
- [ ] **BTC**: Verify economics mode consistency:
  - Policy decision: `use_maker_economics=True/False`
  - Gate parameter: `use_maker_economics=True/False`
  - Router edge calculation: same mode
  - Order submission: limit (maker) vs market (taker)
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: Economics mode is consistent from policy to execution.

**Failure Mode**: Policy chooses maker, but router executes as taker (or vice versa).

### 5.2 Reject Handling
**Objective**: Audit execution routing, order submission, and reject handling for consistent state transitions.

**Checklist**:
- [ ] **BTC**: Verify reject handling:
  - Gate reject → router reject → order not submitted
  - Reject reason is preserved
  - State transition is consistent (candidate → rejected)
  - No retry on gate reject (unless explicitly configured)
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: Reject handling is deterministic with clear state transitions.

**Failure Mode**: Rejects cause inconsistent state or unexpected retries.

## 6. Lifecycle and Counter Consistency

### 6.1 Lifecycle Events
**Objective**: Check that lifecycle events, counters, and alerting reconcile under partial rejects and retries.

**Checklist**:
- [ ] **BTC**: Verify lifecycle event consistency:
  - Counter increments on accept/reject
  - Alerting triggers on expected conditions
  - Partial rejects don't corrupt counters
  - Retry logic doesn't double-count
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: Lifecycle events and counters are consistent under all conditions.

**Failure Mode**: Counters drift or alerting misfires due to inconsistent state handling.

### 6.2 ID Consistency
**Objective**: Make sure terminal outcomes are all stamped with same `tick_id` and `candidate_id`.

**Checklist**:
- [ ] **BTC**: Verify ID consistency:
  - Signal generation: `tick_id` assigned
  - Candidate creation: `candidate_id` assigned
  - Gate decision: both IDs preserved
  - Execution: both IDs preserved
  - Terminal outcome: both IDs stamped
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: IDs are immutable from signal to terminal outcome.

**Failure Mode**: ID mismatch makes tracing impossible; cannot correlate signal with outcome.

---

# SHADOW REPLAY EXECUTION

## 7. Per-Asset Shadow Replay

### 7.1 Candidate Selection
**Objective**: Trace one candidate per asset from signal to execution with single immutable record.

**Checklist**:
- [ ] **BTC**: Select representative candidate:
  - Recent (within last 24 hours)
  - Representative market conditions
  - Clear outcome (accept or reject)
- [ ] **ETH**: Same selection criteria as BTC
- [ ] **SOL**: Same selection criteria as BTC
- [ ] **XRP**: Same selection criteria as BTC
- [ ] **DOGE**: Same selection criteria as BTC

### 7.2 Rejected Candidate Replay
**Objective**: Replay a rejected BTC, ETH, SOL, XRP, and DOGE candidate and verify exact reject reason.

**Checklist**:
- [ ] **BTC**: Replay rejected candidate:
  - Capture full pipeline state
  - Verify reject reason matches expectation
  - Check if reject was correct (false positive?)
  - Document any discrepancies
- [ ] **ETH**: Same replay as BTC
- [ ] **SOL**: Same replay as BTC
- [ ] **XRP**: Same replay as BTC
- [ ] **DOGE**: Same replay as BTC

**Expected**: Reject reasons are accurate and consistent with gate logic.

**Failure Mode**: Reject reason mismatch indicates gate logic or pipeline bug.

### 7.3 Accepted Candidate Replay
**Objective**: Replay an accepted candidate to verify no silent rejections downstream.

**Checklist**:
- [ ] **BTC**: Replay accepted candidate:
  - Capture full pipeline state
  - Verify no silent rejections
  - Check execution matches expectation
  - Document any discrepancies
- [ ] **ETH**: Same replay as BTC
- [ ] **SOL**: Same replay as BTC
- [ ] **XRP**: Same replay as BTC
- [ ] **DOGE**: Same replay as BTC

**Expected**: Accepted candidates execute successfully without silent failures.

**Failure Mode**: Silent rejection downstream causes accepted candidate to not execute.

---

# HIGH-LEVERAGE BUG CLASS DETECTION

## 8. Bug Class Detection Matrix

| Bug Class | Detection Method | BTC | ETH | SOL | XRP | DOGE |
|-----------|------------------|-----|-----|-----|-----|------|
| **Signal path** | Sign/unit/side mismatch | [ ] | [ ] | [ ] | [ ] | [ ] |
| **Gate path** | Hidden legacy gate active | [ ] | [ ] | [ ] | [ ] | [ ] |
| **Economics path** | Maker/taker override drift | [ ] | [ ] | [ ] | [ ] | [ ] |
| **State path** | Counter/lifecycle scope drift | [ ] | [ ] | [ ] | [ ] | [ ] |
| **Asset path** | BTC/ETH calibration leaking | [ ] | [ ] | [ ] | [ ] | [ ] |

## 9. Unit Conversion Verification

### 9.1 Unit Conversion Audit
**Objective**: Check all unit conversions: fraction, percent, cents, and basis-like quantities.

**Checklist**:
- [ ] **BTC**: Verify all unit conversions:
  - Model probability (0-1) → cents (0-100)
  - Edge calculation (cents)
  - Spread calculation (cents)
  - Threshold comparison (ratio vs absolute)
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: All unit conversions are explicit and consistent.

**Failure Mode**: Unit conversion error causes edge miscalculation (e.g., 0.6 treated as 60c).

### 9.2 Canonical Side Basis
**Objective**: Assert one canonical side basis across signal, allocator, gate, and router.

**Checklist**:
- [ ] **BTC**: Verify side basis consistency:
  - Signal: YES/NO side convention
  - Allocator: same convention
  - Gate: same convention
  - Router: same convention
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: Side basis is canonical and immutable across pipeline.

**Failure Mode**: Side basis flip causes YES order to execute as NO (or vice versa).

---

# AUDIT EXECUTION PLAN

## Phase 1: Static Analysis (1-2 hours)
- [ ] Review code for unit conversion patterns
- [ ] Inventory all gate functions
- [ ] Trace side mapping through code
- [ ] Verify feature contract consistency

## Phase 2: Shadow Replay Setup (2-3 hours)
- [ ] Select 5 candidates (1 per asset)
- [ ] Set up shadow replay environment
- [ ] Configure logging for full pipeline trace
- [ ] Create immutable record template

## Phase 3: Shadow Replay Execution (3-4 hours)
- [ ] Execute replay for BTC candidate
- [ ] Execute replay for ETH candidate
- [ ] Execute replay for SOL candidate
- [ ] Execute replay for XRP candidate
- [ ] Execute replay for DOGE candidate

## Phase 4: Analysis and Documentation (2-3 hours)
- [ ] Analyze replay results
- [ ] Document any discrepancies
- [ ] Classify bugs by severity
- [ ] Create remediation plan

## Phase 5: Remediation (variable)
- [ ] Fix critical bugs
- [ ] Fix high-priority bugs
- [ ] Fix medium-priority bugs
- [ ] Update documentation

---

# SUCCESS CRITERIA

## Critical Success Criteria
- [ ] No sign/unit/side mismatches found
- [ ] No hidden legacy gates active
- [ ] No maker/taker override drift
- [ ] No counter/lifecycle scope drift
- [ ] No asset calibration leakage

## High-Priority Success Criteria
- [ ] All unit conversions verified
- [ ] Canonical side basis established
- [ ] Gate decisions composable and traceable
- [ ] Reject reasons accurate and consistent
- [ ] IDs immutable from signal to outcome

## Medium-Priority Success Criteria
- [ ] Gate structure separated (eligibility, economics, policy, threshold)
- [ ] Lifecycle events consistent
- [ ] Documentation updated
- [ ] Monitoring/alerting configured

---

# REFERENCES

- Microstructure gate specification: `MICROSTRUCTURE_GATE_15M_SPEC_2026_08_02.md`
- Original audit plan: `MICROSTRUCTURE_GATE_AUDIT_2026_08_02.md`
- Spread edge analytics: `merid/event_venues/kalshi/spread_edge_analytics.py`
- Order router: `merid/event_venues/kalshi/order_router.py`
- Agent grid: `merid/prediction/agent_grid_15m.py`
