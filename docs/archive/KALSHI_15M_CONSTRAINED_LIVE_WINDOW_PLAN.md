# Kalshi 15M Constrained Live Window Plan

**Date:** 2026-05-28
**Purpose:** First live validation of consolidated 15M stack with production invariants
**Duration:** 2-3 strips (30-45 minutes total)
**Risk Level:** Constrained (small size, all guards active)

---

## Executive Summary

This plan outlines the first constrained live window for validating the consolidated Kalshi 15M stack. The goal is to verify that the structural coherence improvements (canonical data sources, unified edge, production invariants) translate to correct behavior on live data.

**Key Objectives:**
1. Verify production invariants (spot staleness, YES/NO duality) work correctly in production
2. Confirm no duplicate gating or conflicting logic in live data path
3. Validate edge vs strategy consistency on actual trades
4. Collect diagnostic data for exit audit and PnL analysis

---

## 1) Configuration

### 1.1 Position Sizing

**Constrained Size:**
- 1-2 contracts per trade (minimum viable size)
- Override profile sizing to use fixed small size
- This limits exposure while still exercising the full stack

**Implementation:**
```python
# In agent_grid_15m.py or profile override
max_contracts_per_trade = 2  # Hard cap for constrained window
```

### 1.2 Guardrails - All Active

**All Guardrails Enabled:**
- ✅ Spread guard (max_spread_cents = 40c)
- ✅ Depth guard (min_depth_contracts = 5)
- ✅ Edge guard (min_post_fee_edge = 2%)
- ✅ Distance guard (max_dist_pct_trade = 0.75%)
- ✅ Price floor (min_contract_price_cents = 35c)
- ✅ Same-side cap (max_same_side_per_strip = 2)
- ✅ Time trap prevention (min_entry_mins = 2min, max_entry_mins = 12min)
- ✅ Regime cooldown (enabled with 10-trade minimum)
- ✅ Drawdown halt (15% drawdown threshold)
- ✅ Daily loss cap (5% daily loss limit)

**No Guardrail Overrides:**
- Do not disable any guardrails for this window
- If guardrails are too restrictive, that's valuable diagnostic data
- Record which guardrails are blocking entry most frequently

### 1.3 Environment Variables

**Required Settings:**
```bash
MERID_PROFILE=kalshi_crypto_15m_v2
MERID_UNIFIED_EDGE_ENABLED=true
MERID_SPOT_PROVIDER_TYPE=unified
MERID_TRADE_MODE=paper  # Start with paper, then switch to live if paper passes
```

**Optional for Shadow Mode:**
```bash
MERID_UNIFIED_EDGE_SHADOW_MODE=true  # Compare legacy vs unified edge
```

---

## 2) Diagnostics to Watch

### 2.1 Strip Diagnostics

**Where Candidates Die:**
- Track candidate counts at each gate:
  - Catalog selection (how many markets match series/entry window)
  - Indicator filters (TA chop, trend regime)
  - Unified edge (spread, depth, distance, TTE, edge threshold)
  - Strategy (side selection, TP/SL)
  - Risk (budget, winrate guard)
  - Router (A5 market conditions)

**Expected Pattern:**
- Most candidates should die at unified edge (spread/depth/edge threshold)
- Few should die at router (A5 should rarely reject if edge passed)
- If many die at indicator filters, may need to relax TA gates

**Logging:**
```python
# In agent_grid_15m.py, add per-gate rejection tracking
strip_diagnostics = {
    "catalog_selected": 0,
    "indicator_filtered": 0,
    "edge_rejected": 0,
    "strategy_rejected": 0,
    "risk_rejected": 0,
    "router_rejected": 0,
    "orders_submitted": 0,
}
```

### 2.2 Microstructure Diagnostics

**Book State at Entry/Exit:**
- Best YES bid/ask at entry
- Best NO bid/ask at entry
- Spread at entry (cents and %)
- Depth at best (YES and NO)
- Effective spread for order size

**Expected Pattern:**
- Spread should be ≤ 40c (guardrail threshold)
- Depth should be ≥ 5 contracts (guardrail threshold)
- YES/NO duality should hold (YES_bid + NO_ask ≈ 100c)

**Logging:**
```python
# In order_router.py, log microstructure at order submission
logger.info(
    "[MICROSTRUCTURE-ENTRY] ticker=%s yes_bid=%sc yes_ask=%sc spread=%sc depth_yes=%d depth_no=%d duality_error=%sc",
    ticker, best_yes_bid, best_yes_ask, spread, depth_yes, depth_no, duality_error
)
```

**YES/NO Duality Monitoring:**
- Watch for `[DUALITY-VIOLATION]` errors in logs
- If violations occur, investigate Kalshi API drift or parsing bug
- Violations should be rare (≤ 1% of book updates)

### 2.3 Strategy Truth Tables

**Sample 5-10 Trades:**
For each trade, record:
- Edge result (edge_pct, confidence, reason)
- Strategy decision (side, TP, SL, size)
- Strategy rationale (side_choice_reason, tp_sl_rationale)
- Risk rationale (why this size)
- TTE rationale (why these TP/SL levels)

**Expected Pattern:**
- Side should match edge argmax (YES if YES edge > NO edge)
- TP should be > best bid (profit target)
- SL should be < best ask (stop loss)
- Size should respect risk budget and winrate guard
- Rationales should be consistent with edge result

**Logging:**
```python
# In agent_grid_15m.py, log strategy truth table for each trade
logger.info(
    "[STRATEGY-TRUTH] ticker=%s edge_pct=%.2f side=%s tp=%sc sl=%sc size=%d "
    "edge_reason=%s strategy_reason=%s risk_reason=%s tte_reason=%s",
    ticker, edge_pct, side, tp_cents, sl_cents, size,
    edge_reason, strategy_reason, risk_reason, tte_reason
)
```

### 2.4 Exit Audit Fields

**For Each Filled Trade:**
- Exit type (TP hit, SL hit, forced TTE, expiry)
- Exit rationale (why it exited this way)
- Exit price (cents)
- Slippage vs entry price
- Time held (seconds)
- Realized PnL

**Expected Pattern:**
- Most exits should be TP or SL (not forced TTE or expiry)
- Slippage should be ≤ 3c (guardrail threshold)
- TP hits should have positive PnL
- SL hits should have negative PnL (limited loss)

**Logging:**
```python
# In position_cache.py or exit policy, log exit audit fields
logger.info(
    "[EXIT-AUDIT] ticker=%s exit_type=%s exit_price=%sc slippage=%sc time_held=%s pnl=%.2f "
    "exit_reason=%s",
    ticker, exit_type, exit_price_cents, slippage_cents, time_held, pnl, exit_reason
)
```

---

## 3) Patterns to Watch For

### 3.1 Over-Filtering

**Symptom:** Too few candidates reaching unified edge
- Catalog selects 10 markets, but only 1-2 reach edge check
- Most rejections at indicator filters (TA chop, trend regime)

**Diagnosis:**
- TA gates may be too tight
- Entry window may be too narrow
- Distance guard may be too restrictive

**Remediation:**
- Relax TA gates if they're blocking valid opportunities
- Widen entry window if experimental TTE band is too narrow
- Increase max_dist_pct_trade if distance guard is too tight

### 3.2 Systematic Slippage

**Symptom:** Slippage consistently higher than implied spread
- Entry slippage > 3c on most orders
- Exit slippage > 3c on most exits
- Realized PnL consistently lower than expected

**Diagnosis:**
- Order size may be too large for book depth
- Market may be moving fast (high volatility)
- Order routing may be suboptimal (not using maker orders)

**Remediation:**
- Reduce order size if depth is insufficient
- Add depth-aware order splitting for large orders
- Use post_only maker orders to avoid crossing spread

### 3.3 Exits Not Triggering

**Symptom:** TP/SL not hitting despite price crossing thresholds
- Price crosses TP level but TP not hit
- Price crosses SL level but SL not hit
- Many forced TTE exits or expiry exits

**Diagnosis:**
- Wrong side of book being monitored (YES vs NO)
- TP/SL levels set on wrong side (YES vs NO)
- Order book snapshot stale or incorrect

**Remediation:**
- Verify TP/SL are set on correct side (YES for YES positions, NO for NO positions)
- Verify book updates are fresh (check staleness logs)
- Verify YES/NO duality is holding (check duality violation logs)

### 3.4 YES/NO Duality Violations

**Symptom:** Frequent `[DUALITY-VIOLATION]` errors
- YES_bid + NO_ask ≠ 100c by more than 1c tolerance
- Book updates rejected due to duality violations

**Diagnosis:**
- Kalshi API drift (API changed response format)
- Parsing bug (incorrectly parsing YES/NO prices)
- Data race (book updated mid-parsing)

**Remediation:**
- Investigate Kalshi API response format changes
- Review orderbook parsing logic in orderbook.py
- Add more defensive parsing with validation

---

## 4) Success Criteria

### 4.1 Structural Coherence

**Pass Criteria:**
- ✅ No duplicate gating (spread/depth checked only in unified edge)
- ✅ Single spot source (SpotProvider unified provider used)
- ✅ Single book source (canonical OrderbookSnapshot used)
- ✅ Production invariants work (spot staleness, YES/NO duality)

**Fail Criteria:**
- ❌ Duplicate gating detected (same condition checked twice)
- ❌ Legacy spot path active (RTI/CFB providers used)
- ❌ Legacy book parser active (non-canonical snapshot used)
- ❌ Invariants violated (stale spot traded, duality violations accepted)

### 4.2 Behavioral Correctness

**Pass Criteria:**
- ✅ Edge vs strategy consistent (side matches edge argmax)
- ✅ TP/SL set correctly (TP > bid, SL < ask)
- ✅ Exits trigger correctly (TP/SL hit when price crosses)
- ✅ Slippage within guardrails (≤ 3c)

**Fail Criteria:**
- ❌ Strategy overrides edge rejection
- ❌ TP/SL set on wrong side (YES vs NO)
- ❌ Exits don't trigger despite price crossing
- ❌ Slippage exceeds guardrails (> 3c)

### 4.3 Diagnostic Quality

**Pass Criteria:**
- ✅ Strip diagnostics show where candidates die
- ✅ Microstructure diagnostics capture book state at entry/exit
- ✅ Strategy truth tables show rationales for decisions
- ✅ Exit audit fields show exit type and rationale

**Fail Criteria:**
- ❌ Cannot determine why candidates are rejected
- ❌ No book state data at entry/exit
- ❌ No rationales for strategy decisions
- ❌ No exit type or rationale data

---

## 5) Rollback Plan

### 5.1 When to Roll Back

**Immediate Rollback:**
- Production invariants violated (stale spot traded, duality violations accepted)
- Duplicate gating detected (same condition checked twice)
- Legacy paths active (RTI/CFB spot, non-canonical book)
- Structural coherence broken

**Diagnostic Rollback:**
- Over-filtering (no trades for 2+ strips)
- Systematic slippage (> 5c on most orders)
- Exits not triggering (TP/SL not hit despite price crossing)
- YES/NO duality violations (> 5% of book updates)

### 5.2 Rollback Steps

1. **Stop Trading:**
   - Set `MERID_TRADE_MODE=paper` (if live)
   - Kill any pending orders
   - Close all positions (if safe to do so)

2. **Investigate:**
   - Review logs for invariant violations
   - Review diagnostics for patterns
   - Identify root cause

3. **Fix:**
   - Fix code if bug found
   - Adjust config if misconfiguration
   - Add more logging if diagnostic gap

4. **Re-Validate:**
   - Run golden-path integration test
   - Run paper mode with fixes
   - Re-approve for live if fixes validated

---

## 6) Post-Window Analysis

### 6.1 PnL Audit

**After 2-3 strips, run PnL audit:**
- Total PnL
- Win rate
- Avg win vs avg loss
- TP vs SL vs expiry counts
- Slippage distribution
- Per-asset performance

**Compare to baseline:**
- Previous 357-trade audit: 1.4% win rate, -$0.649 avg PnL
- Expected improvement: higher win rate, positive avg PnL

### 6.2 Exit Audit

**Use exit audit spec:**
- Exit type distribution (TP/SL/forced TTE/expiry)
- Exit rationale distribution
- Time held distribution
- Slippage vs exit type

**Identify patterns:**
- Which exit type is most common?
- Are exits happening at expected times?
- Is slippage correlated with exit type?

### 6.3 Edge vs Strategy Consistency

**Sample 5-10 trades:**
- Verify side matches edge argmax
- Verify TP/SL are reasonable given edge
- Verify size respects risk budget
- Verify rationales are consistent

**Document any inconsistencies:**
- Strategy overrides edge rejection (should not happen)
- TP/SL don't match edge (may need calibration)
- Size doesn't respect risk (may need adjustment)

---

## 7) Next Steps After Constrained Window

### 7.1 If Successful

**Expand to Normal Size:**
- Increase position size to profile defaults
- Continue monitoring diagnostics
- Collect more data for PnL analysis

**Identify Profitable Regimes:**
- Analyze per-asset performance
- Analyze per-price-band performance
- Analyze per-distance performance
- Analyze per-TTE performance

**Optimize:**
- Tighten guardrails if too loose
- Relax guardrails if too tight
- Adjust TP/SL levels based on exit audit
- Adjust sizing based on PnL distribution

### 7.2 If Unsuccessful

**Investigate Root Cause:**
- Review logs for invariant violations
- Review diagnostics for patterns
- Identify structural vs behavioral issues

**Fix and Re-Test:**
- Fix structural issues (canonical sources, invariants)
- Fix behavioral issues (edge vs strategy, exits)
- Re-run constrained window with fixes

**Consider Alternative:**
- If structural issues persist, may need deeper refactoring
- If behavioral issues persist, may need strategy redesign
- If both persist, may need to revisit architecture

---

## 8) Conclusion

This constrained live window is the first validation of the consolidated 15M stack. The goal is to verify that structural coherence improvements translate to correct behavior on live data.

**Key Success Metrics:**
- Production invariants work correctly
- No duplicate gating or conflicting logic
- Edge vs strategy consistent
- Exits trigger correctly
- Diagnostics capture all needed data

**Expected Outcome:**
- 2-3 strips of live data
- 5-10 trades executed
- Complete diagnostic data
- Clear picture of stack health

**Timeline:**
- 30-45 minutes of live trading
- 1-2 hours of post-window analysis
- Decision on next steps (expand or fix)
