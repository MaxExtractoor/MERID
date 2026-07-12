# Edge Stack End-to-End Audit Report
**Date**: 2026-07-12  
**Scope**: Complete edge calculation, routing, and execution pipeline for 15m Kalshi crypto trading system  
**Assets**: BTC, ETH, SOL, XRP, DOGE

---

## Executive Summary

Deep audit of the edge stack revealed **critical misalignments** across upstream, midstream, and downstream components. The system has **no single source of truth** for edge values, leading to:

1. **Edge field name confusion** (edge vs edge_pct vs edgepct)
2. **Unit mismatches** (PERCENT vs FRACTION) with dual normalization points
3. **Three conflicting edge threshold systems** (0.01% vs 1.75% vs 2.0%)
4. **Edge data loss** in fills ledger (edgepct=0.0, netedgecents=0.0)
5. **No centralized edge validation** - checks scattered across components

**Risk Level**: SEV-1 - These misalignments directly impact which trades execute and may cause:
- Over-trading (loop_15m executes trades agent_grid would reject)
- Under-trading (unit conversion errors block valid trades)
- Data loss (edge values not recorded in fills ledger)
- Unpredictable behavior (which threshold applies is ambiguous)

---

## Component Map

### Upstream (Signal Generation)
- **merid/prediction/edge_computer.py**: Edge computation (LegacyEdgeBackend, UnifiedEdgeBackend)
- **merid/prediction/agent_grid_15m.py**: Signal generation, dual-side edge selection
- **merid/prediction/strategy.py**: Edge thresholds, position sizing
- **merid/loop_15m.py**: Best-edge selection, candidate execution

### Midstream (Order Routing)
- **merid/event_venues/kalshi/order_router.py**: OrderIntent creation, aggressiveness computation
- **merid/event_venues/kalshi/maker_taker_policy.py**: Maker/taker role decision based on edge
- **merid/event_venues/kalshi/maker_taker_integration.py**: Policy application to intents
- **merid/event_venues/kalshi/risk_parameters.py**: Edge thresholds, aggressiveness computation
- **merid/event_venues/kalshi/order_gate.py**: Pre-trade checks (no edge validation)

### Downstream (Execution & Fills)
- **merid/event_venues/kalshi/fills_ledger.py**: Fill recording, edge tracking
- **merid/event_venues/kalshi/resting_order_monitor.py**: Resting order tracking
- **merid/event_venues/kalshi/position_cache.py**: Position state with edge data

---

## Critical Findings

### 1. Edge Field Name Inconsistency

**Problem**: Edge values stored in multiple field names with no clear source of truth.

| Component | Field Name | Line | Notes |
|-----------|-----------|------|-------|
| agent_grid_15m.py | `edge` | 11789 | For loop_15m validation |
| agent_grid_15m.py | `edge_pct` | 11791 | BUG #36 FIX: Carry edge from signal |
| loop_15m.py | `edge` | 1487 | Fallback field |
| loop_15m.py | `edge_pct` | 1487 | Primary field |
| OrderIntent | `edge_pct` | 1232 | Router intent field |
| FillsLedger OrderIntent | `edgepct` | 385 | Ledger intent field (different name!) |
| OrderIntent | `edgepct` | 1275 | Router intent field (always 0.0) |
| OrderIntent | `netedgecents` | 1286 | Router intent field (always 0.0) |

**Impact**:
- Confusion about which field to read/write
- Data loss when converting between field names
- Inconsistent logging (some use edgepct, some use edge_pct)

**Evidence**:
```python
# agent_grid_15m.py lines 11789-11791
"edge": signal.get("edge_pct", 0.0),  # CRITICAL: Use "edge" field for loop_15m validation
"edge_pct": signal.get("edge_pct", 0.0),  # BUG #36 FIX: Carry edge from signal

# loop_15m.py line 1487
edge = candidate.get("edge", 0.0) or candidate.get("edge_pct", 0.0)

# fills_ledger.py line 1082
intent.edgepct if intent else 0.0,  # But OrderIntent.edgepct is never set!
```

---

### 2. Edge Unit Mismatch (PERCENT vs FRACTION)

**Problem**: Edge values expressed in different units (PERCENT vs FRACTION) with dual normalization points.

| Component | Unit | Value Example | Normalization | Line |
|-----------|------|--------------|---------------|------|
| agent_grid_15m.py | PERCENT | 5.2 (5.2%) | None | 4655 |
| loop_15m.py | PERCENT | 5.2 (5.2%) | /100.0 if >1.0 | 4077 |
| compute_order_aggressiveness | FRACTION | 0.052 (5.2%) | Expects fraction | 117 |
| maker_taker_policy.py | PERCENT | 5.2 (5.2%) | None | 216 |
| risk_parameters.py thresholds | FRACTION | 0.0175 (1.75%) | Constants | 65 |

**Dual Normalization Points**:
```python
# loop_15m.py line 4077
edge_fraction = edge_pct / 100.0 if edge_pct > 1.0 else edge_pct

# order_router.py line 6951
edge_fraction = intent.edge_pct / 100.0 if intent.edge_pct > 1.0 else intent.edge_pct
```

**Impact**:
- If normalization fails at either point, wrong aggressiveness computed
- Orders with edge > 0.04% incorrectly marked marketable (if not normalized)
- Confusion about which component owns the normalization logic

**Evidence**:
```python
# order_router.py line 6947-6951
# CRITICAL UNIT FIX (2026-07-05): agent candidates carry edge_pct in PERCENT
# units (e.g., 5.2 = 5.2%) while compute_order_aggressiveness thresholds
# (EDGE_RESTING_ENTRY/EDGE_MARKET_ENTRY = 0.02/0.04) are FRACTIONS.
# Without normalization every order with edge > 0.04% was marked marketable.
edge_fraction = intent.edge_pct / 100.0 if intent.edge_pct > 1.0 else intent.edge_pct
```

---

### 3. Three Conflicting Edge Threshold Systems

**Problem**: Three different edge threshold systems with NO single source of truth.

#### System 1: Per-Asset Thresholds (risk_parameters.py)
```python
EDGE_MARKET_ENTRY_BTC: Final[float] = 0.0175  # 1.75%
EDGE_MARKET_ENTRY_ETH: Final[float] = 0.02    # 2.0%
EDGE_MARKET_ENTRY_SOL: Final[float] = 0.025   # 2.5%
EDGE_MARKET_ENTRY_XRP: Final[float] = 0.03    # 3.0%
EDGE_MARKET_ENTRY_DOGE: Final[float] = 0.035  # 3.5%
```

#### System 2: Per-Asset Thresholds (agent_grid_15m.py)
```python
per_asset_min_edge_threshold = {
    "BTC": 1.75,   # EDGE_MARKET_ENTRY_BTC
    "ETH": 2.0,    # EDGE_MARKET_ENTRY_ETH
    "SOL": 2.5,    # EDGE_MARKET_ENTRY_SOL
    "XRP": 3.0,    # EDGE_MARKET_ENTRY_XRP
    "DOGE": 3.5,   # EDGE_MARKET_ENTRY_DOGE
}
```

#### System 3: Confidence-Based Dynamic Threshold (loop_15m.py)
```python
# Base threshold: 0.01% (0.0001)
# Confidence multiplier: 0.5 (low confidence) to 2.0 (high confidence)
min_edge_threshold = 0.0001 * confidence_multiplier
```

**Threshold Comparison**:
| Asset | System 1 (risk_parameters) | System 2 (agent_grid) | System 3 (loop_15m base) | Ratio |
|-------|---------------------------|----------------------|--------------------------|-------|
| BTC | 1.75% | 1.75% | 0.01% | 175x |
| ETH | 2.0% | 2.0% | 0.01% | 200x |
| SOL | 2.5% | 2.5% | 0.01% | 250x |
| XRP | 3.0% | 3.0% | 0.01% | 300x |
| DOGE | 3.5% | 3.5% | 0.01% | 350x |

**Impact**:
- loop_15m threshold is 175-350x LOWER than agent_grid thresholds
- loop_15m will execute trades that agent_grid would reject
- No clear hierarchy: which threshold wins?
- Over-trading risk due to extremely low loop_15m threshold

**Evidence**:
```python
# loop_15m.py lines 1511-1517
min_edge_threshold = 0.0001 * confidence_multiplier  # Dynamic threshold based on confidence

# agent_grid_15m.py lines 4621-4631
if selected_edge < min_edge_threshold_pct:
    logger.info("[MOMENTUM-FVG-EDGE-THRESHOLD] asset=%s selected_edge=%.2f%% < per_asset_threshold=%.2f%% -> NO TRADE")
    return None
```

---

### 4. Edge Validation Gaps

**Problem**: Edge validation scattered across components with no single source of truth.

| Component | Validation Logic | Line | Notes |
|-----------|------------------|------|-------|
| agent_grid_15m.py | Per-asset threshold check | 4621-4631 | Rejects if edge < threshold |
| loop_15m.py | Confidence-based threshold | 1511-1522 | Can be skipped via rationale |
| loop_15m.py | Best-edge improvement check | 1572-1592 | Only if position exists |
| order_router.py | NO edge validation | N/A | Routes regardless of edge |
| order_gate.py | NO edge validation | N/A | Checks dedup, exposure, not edge |
| maker_taker_policy.py | Uses edge for role decision | 216 | Does not validate edge |

**Validation Skip Vulnerability**:
```python
# loop_15m.py lines 3684-3694
# Velocity-based signals: skip edge validation (validated by velocity threshold in agent_grid)
if "velocity" in candidate:
    logger.info(
        "[EDGE-VALIDATION] Skipping edge check for velocity-based signal: ticker=%s rationale=%s",
        ticker, candidate.get("rationale")
    )
    return True  # Skip validation
```

**Impact**:
- No centralized edge validation guard
- Validation can be bypassed via "rationale" field
- Different components use different thresholds
- No audit trail of which validation was applied

---

### 5. Edge Data Flow Breaks

**Problem**: Edge values flow through multiple field names with no clear mapping, causing data loss.

**Data Flow Trace**:
```
1. agent_grid_15m.py generates signal
   - signal["edge_pct"] = 5.2 (PERCENT)
   
2. agent_grid_15m.py creates candidate
   - candidate["edge"] = signal["edge_pct"] (line 11789)
   - candidate["edge_pct"] = signal["edge_pct"] (line 11791)
   
3. loop_15m.py reads candidate
   - edge = candidate.get("edge", 0.0) or candidate.get("edge_pct", 0.0) (line 1487)
   
4. loop_15m.py creates OrderIntent
   - intent.edge_pct = edge_pct (line 4102)
   - intent.edgepct = 0.0 (default, never set) (line 1275)
   - intent.netedgecents = 0.0 (default, never set) (line 1286)
   
5. order_router.py routes OrderIntent
   - Uses intent.edge_pct for aggressiveness (line 6931)
   
6. fills_ledger.py records fill
   - Logs intent.edgepct (always 0.0) (line 1082)
   - Logs intent.netedgecents (always 0.0) (line 1083)
   
RESULT: Edge value LOST in fills ledger (shows 0.0)
```

**Impact**:
- Edge values not recorded in fills ledger
- No audit trail of edge at execution time
- Cannot analyze realized edge vs expected edge
- Performance attribution broken

**Evidence**:
```python
# fills_ledger.py lines 1080-1083
logger.info(
    "[FILL-INGEST] fill_id=%s ticker=%s side=%s count=%d price_cents=%d notional_usd=%.2f "
    "edgepct=%.4f netedgecents=%.2f band=%s regime=%s source=%s",
    fill.fill_id, fill.market_ticker, fill.side, fill.count_fp, fill.price_cents, float(fill.notional_usd),
    intent.edgepct if intent else 0.0,  # ALWAYS 0.0 - never populated!
    intent.netedgecents if intent else 0.0,  # ALWAYS 0.0 - never populated!
    intent.band if intent else "",
    intent.regime if intent else "",
    fill.fill_source
)
```

---

### 6. Maker/Taker Policy Edge Usage

**Problem**: Maker/taker policy expects edge_pct in PERCENT units, but this conflicts with compute_order_aggressiveness (expects FRACTION).

**Policy Edge Usage**:
```python
# maker_taker_policy.py line 216
edge_net_of_taker = edge_pct - taker_fee_pct  # Expects PERCENT (e.g., 5.2)
```

**Aggressiveness Computation**:
```python
# compute_order_aggressiveness line 117
def compute_order_aggressiveness(asset: str, edge_pct: float, seconds_to_expiry: int) -> float:
    # Expects FRACTION (e.g., 0.052)
    market_threshold = market_thresholds.get(asset, EDGE_MARKET_ENTRY_BTC)  # 0.0175
    if edge_pct >= market_threshold:  # Compares FRACTION to FRACTION
        return min(0.5 + excess_edge * 2.0, 1.0)
```

**Impact**:
- Policy and aggressiveness use different units
- Normalization must happen before calling each
- Dual normalization points increase error risk
- No validation that edge_pct is in expected units

---

### 7. Best Edge Selection Logic

**Problem**: loop_15m.py uses extremely low confidence-based threshold (0.01%) which may cause over-trading.

**Threshold Calculation**:
```python
# loop_15m.py lines 1511-1517
confidence = candidate.get("confidence", 0.5)
confidence_multiplier = 0.5 + (confidence * 1.5)  # Maps 0.0→0.5, 0.5→1.25, 1.0→2.0
min_edge_threshold = 0.0001 * confidence_multiplier  # 0.01% base

# Examples:
# confidence=0.5 → multiplier=1.25 → threshold=0.0125% (0.000125)
# confidence=0.7 → multiplier=1.55 → threshold=0.0155% (0.000155)
# confidence=1.0 → multiplier=2.0 → threshold=0.02% (0.0002)
```

**Comparison with Agent Grid Thresholds**:
| Confidence | loop_15m Threshold | agent_grid BTC Threshold | Ratio |
|------------|-------------------|------------------------|-------|
| 0.5 | 0.0125% | 1.75% | 140x |
| 0.7 | 0.0155% | 1.75% | 113x |
| 1.0 | 0.02% | 1.75% | 87.5x |

**Impact**:
- loop_15m threshold is 87-140x LOWER than agent_grid
- Massive over-trading risk
- Best-edge logic may execute trades with negligible edge
- No alignment between signal generation and execution thresholds

**Evidence**:
```python
# loop_15m.py lines 1537-1538
if abs(edge) > min_edge_threshold or abs(edge) > abs(current_best_edge) or is_swing_reversal:
    should_execute = True
```

---

### 8. Edge in Fills Ledger - Data Loss

**Problem**: FillsLedger OrderIntent has edgepct and netedgecents fields, but they are never populated from OrderIntent.edge_pct.

**Field Definitions**:
```python
# order_router.py lines 1275-1286
edgepct: float = 0.0  # OrderIntent field (always 0.0 default)
netedgecents: float = 0.0  # OrderIntent field (always 0.0 default)
```

**Fill Logging**:
```python
# fills_ledger.py lines 1080-1083
logger.info(
    "[FILL-INGEST] ... edgepct=%.4f netedgecents=%.2f ...",
    intent.edgepct if intent else 0.0,  # Always 0.0!
    intent.netedgecents if intent else 0.0,  # Always 0.0!
)
```

**Impact**:
- Edge values not recorded in fills ledger
- Cannot analyze realized edge vs expected edge
- Performance attribution broken
- Audit trail incomplete

**Root Cause**:
- OrderIntent has TWO edge fields: edge_pct (used) and edgepct (unused)
- FillsLedger OrderIntent has edgepct field (different from OrderIntent.edge_pct)
- No code populates edgepct from edge_pct
- Data loss at fills ledger boundary

---

## Discrepancy Summary

| Issue | Severity | Components Affected | Risk |
|-------|----------|---------------------|------|
| Edge field name confusion | SEV-1 | agent_grid, loop_15m, order_router, fills_ledger | Data loss, confusion |
| Unit mismatch (PERCENT vs FRACTION) | SEV-1 | loop_15m, order_router, maker_taker_policy, risk_parameters | Wrong aggressiveness, over/under-trading |
| Three conflicting threshold systems | SEV-1 | agent_grid, loop_15m, risk_parameters | Over-trading, unpredictable behavior |
| Edge validation gaps | SEV-2 | loop_15m, agent_grid, order_router, order_gate | Bypassable validation, no audit trail |
| Edge data flow breaks | SEV-1 | agent_grid, loop_15m, order_router, fills_ledger | Data loss, broken attribution |
| Maker/taker policy edge usage | SEV-2 | maker_taker_policy, compute_order_aggressiveness | Unit confusion, dual normalization |
| Best edge selection logic | SEV-1 | loop_15m | Over-trading (87-140x lower threshold) |
| Edge data loss in fills ledger | SEV-1 | order_router, fills_ledger | No audit trail, broken attribution |

---

## Remediation Plan

### Phase 1: Establish Single Source of Truth (Immediate)

1. **Standardize edge field name to `edge_pct` everywhere**
   - Remove `edge` field from agent_grid candidates
   - Remove `edgepct` field from OrderIntent (or populate from edge_pct)
   - Update all reads to use `edge_pct` only
   - Files: agent_grid_15m.py, loop_15m.py, order_router.py, fills_ledger.py

2. **Standardize edge unit to FRACTION everywhere**
   - Convert all thresholds to FRACTION (0.0175 instead of 1.75%)
   - Remove dual normalization points
   - Normalize at signal generation only
   - Files: risk_parameters.py, agent_grid_15m.py, loop_15m.py, order_router.py, maker_taker_policy.py

### Phase 2: Unify Edge Threshold System (High Priority)

3. **Establish single edge threshold authority**
   - Move all thresholds to risk_parameters.py (single source of truth)
   - Remove duplicate thresholds from agent_grid_15m.py
   - Remove confidence-based threshold from loop_15m.py (or align with per-asset thresholds)
   - Add threshold hierarchy document

4. **Implement centralized edge validation**
   - Create `validate_edge(edge_pct, asset, confidence)` function
   - Call at single point (agent_grid signal generation)
   - Remove scattered validation logic
   - Add audit trail of validation decision

### Phase 3: Fix Edge Data Flow (High Priority)

5. **Populate edge fields in OrderIntent**
   - Set OrderIntent.edgepct = edge_pct at creation
   - Set OrderIntent.netedgecents = edge_pct * price_cents / 100
   - Remove unused edgepct field from FillsLedger OrderIntent
   - Files: order_router.py, fills_ledger.py

6. **Add edge audit trail**
   - Log edge_pct at every pipeline stage
   - Record edge_pct in fills ledger (currently shows 0.0)
   - Add edge validation decision to fill metadata
   - Files: loop_15m.py, order_router.py, fills_ledger.py

### Phase 4: Align Best-Edge Logic (Medium Priority)

7. **Align loop_15m threshold with agent_grid**
   - Remove confidence-based threshold (0.01%)
   - Use per-asset thresholds from risk_parameters.py
   - Add threshold multiplier for confidence (optional)
   - Test impact on trade frequency

8. **Add edge improvement threshold guard**
   - Validate 20% relative improvement is appropriate
   - Consider absolute improvement threshold (e.g., 0.5%)
   - Add guard against over-trading on tiny edges

### Phase 5: Testing & Validation (Required)

9. **Add edge flow integration tests**
   - Test edge field name consistency
   - Test edge unit conversion
   - Test threshold alignment
   - Test fills ledger edge recording

10. **Add edge audit tests**
    - Test edge validation decision logging
    - Test edge audit trail completeness
    - Test edge data loss detection

---

## Recommended Immediate Actions

1. **STOP**: Do not deploy any changes to edge logic until remediation complete
2. **AUDIT**: Review recent trades to assess impact of threshold misalignment
3. **ALIGN**: Decide on single threshold system (recommend per-asset from risk_parameters.py)
4. **FIX**: Implement Phase 1 (field name + unit standardization) immediately
5. **TEST**: Add integration tests before deploying Phase 2-5

---

## Questions for User

1. **Threshold Authority**: Should loop_15m use per-asset thresholds (1.75-3.5%) or confidence-based threshold (0.01-0.02%)?
2. **Edge Unit**: Should we standardize to FRACTION (0.0175) or PERCENT (1.75%)?
3. **Validation Point**: Should edge validation happen at signal generation (agent_grid) or execution (loop_15m)?
4. **Edge Recording**: Should we populate edgepct/netedgecents in fills ledger for audit trail?
5. **Rollback**: Should we revert confidence-based threshold to per-asset thresholds immediately?

---

## Web Research: Best Practices for Edge Calculation (2026)

### Industry Standards from Prediction Market Research

Based on 2026 research from Turbine Blog, ClawArbs, Arbitrage Agent, and DEV Community:

**1. Edge Unit Standardization**
- **Fraction (0.0-1.0)** is the industry standard for internal calculations
- **Percentage (0-100)** is used for display/logging only
- **Basis points (bps)** are used for thresholds (1 bps = 0.01%)
- Our system should use FRACTION internally, convert to PERCENT for logging

**2. Edge Calculation Best Practices**
- Edge must be **fee-adjusted** before any decision
- Formula: `net_edge = gross_edge - (fee_tier * price * (1 - price))`
- Kalshi fee peaks at 50c (max spread), lower at extremes
- Never trade if net edge < ~1% after fees

**3. Threshold Systems**
- **Volatility-based**: Higher vol = higher threshold (sqrt(vol_ratio adjustment)
- **Liquidity-based**: Lower depth = higher threshold
- **Sentiment-based**: Fear = lower threshold (opportunity), Greed = higher threshold (caution)
- **Per-asset**: Different assets have different risk multipliers (BTC=1.0, DOGE=1.6)
- **Time-based**: Closer to expiry = higher threshold (terminal phase)

**4. Kelly Criterion for Sizing**
- Full Kelly is mathematically optimal but brutally volatile
- **Half Kelly** is the sane default (75% growth, 50% volatility)
- **Quarter Kelly** for noisy probability estimates
- Start with Quarter Kelly, scale to Half Kelly after 30+ consistent resolutions

**5. Risk Management**
- Daily drawdown limit: 5-10% hard stop
- Per-market position cap: 10-15% of portfolio
- Correlation management: Treat correlated positions as single position
- Edge ratio > 1.0 confirms structural edge, > 1.5 is tradeable

### Recommended Approach for MERID

Based on industry best practices and our current stack:

**1. Standardize to FRACTION (0.0-1.0) everywhere**
- Convert all thresholds to fraction (0.0175 instead of 1.75%)
- Normalize at signal generation only (single point)
- Use percentage only for logging/display

**2. Use per-asset thresholds from risk_parameters.py as single source of truth**
- Remove confidence-based threshold from loop_15m.py (0.01% is too low)
- Align with EdgeThresholdMatrix (bps-based) for dynamic adjustments
- Implement volatility/liquidity/sentiment adjustments via EdgeThresholdMatrix

**3. Implement centralized edge validation**
- Create `validate_edge(edge_pct, asset, confidence)` in risk_parameters.py
- Call at signal generation (agent_grid_15m.py)
- Add audit trail of validation decision

**4. Fix edge data flow**
- Populate OrderIntent.edgepct from edge_pct at creation
- Populate OrderIntent.netedgecents = edge_pct * price_cents / 100
- Remove unused edgepct field from FillsLedger OrderIntent

**5. Add edge audit trail**
- Log edge_pct at every pipeline stage
- Record edge_pct in fills ledger (currently shows 0.0)
- Add edge validation decision to fill metadata

### Additional Components Discovered

The audit revealed **4 additional edge-related components** not in original scope:

1. **merid/risk/edge_thresholds.py**: EdgeThresholdMatrix with bps-based thresholds, volatility/liquidity/sentiment adjustments
2. **merid/prediction/dynamic_edge_calibrator.py**: Dynamic edge computation based on market conditions
3. **merid/prediction/edge_recalibrator.py**: Threshold recalibration based on realized edge data
4. **merid/trading/top3_edge_allocator.py**: EdgeCandidate with edge field for top-3 selection

**Impact**: These components add **4 MORE edge threshold systems** to the existing 3, making the problem worse. They are NOT integrated with the 15m stack and create additional divergence.

---

## Appendix: File References

### Upstream Files
- merid/prediction/edge_computer.py (lines 63-235: LegacyEdgeBackend)
- merid/prediction/agent_grid_15m.py (lines 4603-4631: per-asset thresholds, 11789-11791: edge fields)
- merid/prediction/strategy.py (lines 64-73: min_edge_for_phase)
- merid/loop_15m.py (lines 1487: edge field read, 1511-1522: confidence threshold, 4077: unit normalization)
- merid/risk/edge_thresholds.py (lines 50-55: EdgeThresholdMatrix with bps thresholds - ADDITIONAL COMPONENT)
- merid/prediction/dynamic_edge_calibrator.py (lines 172-234: dynamic edge computation - ADDITIONAL COMPONENT)
- merid/prediction/edge_recalibrator.py (lines 123-214: threshold recalibration - ADDITIONAL COMPONENT)

### Midstream Files
- merid/event_venues/kalshi/order_router.py (lines 1232: edge_pct field, 1275: edgepct field, 1286: netedgecents field, 6931-6966: aggressiveness computation)
- merid/event_venues/kalshi/maker_taker_policy.py (lines 65-75: edge thresholds, 216: edge usage)
- merid/event_venues/kalshi/maker_taker_integration.py (lines 80: edge_pct read, 98: edge_net_of_fees_pct set)
- merid/event_venues/kalshi/risk_parameters.py (lines 65-75: EDGE_MARKET_ENTRY constants, 117-169: compute_order_aggressiveness)
- merid/event_venues/kalshi/order_gate.py (no edge validation)
- merid/trading/top3_edge_allocator.py (lines 42-62: EdgeCandidate with edge field - ADDITIONAL COMPONENT)

### Downstream Files
- merid/event_venues/kalshi/fills_ledger.py (lines 385: edgepct field, 386: netedgecents field, 1080-1083: edge logging)
- merid/event_venues/kalshi/resting_order_monitor.py (no edge tracking)
- merid/event_venues/kalshi/position_cache.py (line 669: edge_pct read from fill)

---

**Report Generated**: 2026-07-12  
**Auditor**: Cascade AI System  
**Status**: AWAITING USER DECISION ON REMEDIATION PRIORITIES
