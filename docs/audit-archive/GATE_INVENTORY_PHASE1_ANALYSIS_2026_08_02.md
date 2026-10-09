# Phase 1 Static Analysis: Gate Inventory
**Date**: 2026-08-02  
**Scope**: BTC, ETH, SOL, XRP, DOGE 15-minute Kalshi markets  
**Purpose**: Inventory all active gates and feature flags that can veto trades

## Executive Summary

Initial static analysis reveals **8 distinct gate systems** in the codebase that can veto trades. This creates significant risk of shadow rejections, conflicting decisions, and legacy gate interference with the new microstructure gate.

---

# GATE INVENTORY

## 1. Venue Gate (`merid/prediction/venue_gate.py`)

**Purpose**: US compliance and trading mode enforcement  
**Location**: `merid/prediction/venue_gate.py`  
**Class**: `VenueGate`  
**Status**: ✅ ACTIVE  

**Functionality**:
- Blocks non-US-compliant venues (polymarket, augur, predictit, etc.)
- Enforces trading mode (SIM/PAPER/LIVE)
- Only allows Kalshi venue for prediction markets

**Check Points**:
- `check_venue(venue)` - Venue allow-list check
- `check_can_trade()` - Trading mode enforcement
- `check_live_enabled()` - Live trading permission

**Rejection Reasons**:
- `VenueBlockedError` - Non-US-compliant venue
- `ModeBlockedError` - Trading mode doesn't allow live trading

**Impact on 15m Markets**: HIGH - First gate in pipeline, can block all trading

**Legacy Status**: Not legacy - active compliance gate

---

## 2. Lane Enforcement Gate (`merid/prediction/lane_enforcement.py`)

**Purpose**: Production gate for agent lane enforcement  
**Location**: `merid/prediction/lane_enforcement.py`  
**Function**: `gate_production_only()`  
**Status**: ✅ ACTIVE  

**Functionality**:
- Blocks dev/archive agents in production
- Ensures agents stay in declared lanes
- Cross-lane calls only through defined gateways

**Check Points**:
- `gate_production_only(agent_id)` - Production lane check

**Rejection Reasons**:
- Blocks dev/archive agents
- Blocks unknown lanes

**Impact on 15m Markets**: MEDIUM - Agent-level gate, not per-trade

**Legacy Status**: Not legacy - active production safety gate

---

## 3. Order Gate (`merid/event_venues/kalshi/order_gate.py`)

**Purpose**: Pre-trade order store and centralized pre-trade checks  
**Location**: `merid/event_venues/kalshi/order_gate.py`  
**Class**: `PreTradeGate`  
**Status**: ✅ ACTIVE  

**Functionality**:
- Idempotency enforcement (duplicate order prevention)
- Fill awareness (already satisfied position check)
- Risk envelope checks (delegates to KalshiRiskManager)
- Order lifecycle management

**Check Points**:
- `check(intent)` - Main pre-trade check
- Duplicate detection (5-second time buckets)
- Fill awareness check
- Risk envelope validation

**Rejection Reasons**:
- `duplicate` - Order already exists
- `already_satisfied` - Position already satisfied
- Risk envelope violations

**Impact on 15m Markets**: CRITICAL - Last gate before venue submission

**Legacy Status**: Not legacy - active order management gate

---

## 4. Market Regime Gate (`merid/event_venues/kalshi/order_router.py`)

**Purpose**: Block new entries when crypto basket is flat  
**Location**: `merid/event_venues/kalshi/order_router.py:5260`  
**Function**: `_check_market_regime_gate()`  
**Status**: ✅ ACTIVE  

**Functionality**:
- Blocks new entries when crypto basket is flat
- Market regime-based trading suspension

**Check Points**:
- `_check_market_regime_gate(intent, mode, t0)` - Regime check

**Rejection Reasons**:
- Market regime unfavorable (flat basket)

**Impact on 15m Markets**: HIGH - Can block all entries during unfavorable regimes

**Legacy Status**: Not legacy - active market condition gate

---

## 5. Fee-Aware Gate (`merid/event_venues/kalshi/order_router.py`)

**Purpose**: Check if edge clears fee-aware threshold  
**Location**: `merid/event_venues/kalshi/order_router.py:383`  
**Function**: `check_fee_aware_gate()`  
**Status**: ⚠️ LEGACY - Should be replaced by new microstructure gate  

**Functionality**:
- Edge gate: (estimated_probability - market_price) > fees + min_edge_cents
- Fixed minimum edge threshold (default 2c)
- Fee calculation using unified fees module

**Check Points**:
- `check_fee_aware_gate(edge_pct, contract_price_cents, min_edge_cents, fee_per_contract)` - Fee-aware edge check

**Rejection Reasons**:
- `fee_aware_gate: edge < required` - Edge doesn't clear fees + min_edge

**Impact on 15m Markets**: HIGH - Legacy gate that may conflict with new microstructure gate

**Legacy Status**: ⚠️ LEGACY - Should be deprecated in favor of new microstructure gate

---

## 6. Legacy Microstructure Gate (`merid/event_venues/kalshi/order_router.py`)

**Purpose**: Fixed spread threshold (replaced by new edge-aware gate)  
**Location**: `merid/event_venues/kalshi/order_router.py:463`  
**Function**: `check_market_microstructure()`  
**Status**: ⚠️ LEGACY - Has fallback logic in new gate  

**Functionality**:
- Fixed 20c spread threshold (old approach)
- Minimum depth thresholds
- Side conversion (Kalshi format to canonical)

**Check Points**:
- `check_market_microstructure(yes_bid, no_bid, yes_depth, no_depth, ...)` - Legacy microstructure check

**Rejection Reasons**:
- Spread too wide (> 20c)
- Depth too low

**Impact on 15m Markets**: HIGH - Legacy gate with fallback logic in new gate implementation

**Legacy Status**: ⚠️ LEGACY - Fallback in `check_edge_aware_microstructure_gate()` when spread_edge_analytics unavailable

---

## 7. New Microstructure Gate (`merid/event_venues/kalshi/spread_edge_analytics.py`)

**Purpose**: Edge-aware microstructure gate with spread/edge ratio  
**Location**: `merid/event_venues/kalshi/spread_edge_analytics.py`  
**Function**: `edge_aware_microstructure_gate()`  
**Status**: ✅ ACTIVE - Newly implemented with bug fixes  

**Functionality**:
- Spread/edge ratio check (default 40%)
- Asset-specific calibration (BTC, ETH, SOL, XRP, DOGE)
- Time-to-expiry scaling (sigmoid decay)
- Maker/taker economics distinction
- Guardrails: crossed-book, spread cap, depth

**Check Points**:
- `edge_aware_microstructure_gate(edge_metrics, min_executable_edge_frac, max_spread_to_edge_ratio, ...)` - Main gate
- `get_time_scaled_threshold()` - Time-scaled ratio threshold
- `get_time_scaled_spread_cap()` - Time-scaled spread cap
- `check_crossed_book()` - Structural validity
- `check_minimum_depth()` - Liquidity check

**Rejection Reasons**:
- `spread_cost_too_high` - Ratio exceeds threshold
- `spread_too_wide` - Spread exceeds cap
- `insufficient_depth` - Depth below threshold
- `crossed_book` - Structural invalidity
- `stale_quote` - Data quality issue

**Impact on 15m Markets**: CRITICAL - Primary economics gate for 15m markets

**Legacy Status**: Not legacy - newly implemented with comprehensive guardrails

---

## 8. Quantitative Gates (`merid/prediction/quantitative_gates.py`)

**Purpose**: Quality gates for debate participation  
**Location**: `merid/prediction/quantitative_gates.py`  
**Class**: `QuantitativeGates`  
**Status**: ❌ NOT RELEVANT to 15m crypto markets  

**Functionality**:
- Accuracy gate
- Confidence gate
- Activity gate
- Argument quality gate
- Team diversity gate
- Performance gate

**Check Points**:
- `_evaluate_accuracy_gate()` - Historical accuracy check
- `_evaluate_confidence_gate()` - Confidence quality check
- `_evaluate_activity_gate()` - Recent activity check
- `_evaluate_argument_quality_gate()` - Argument quality check
- `_evaluate_team_diversity_gate()` - Team composition check
- `_evaluate_performance_gate()` - Debate performance check

**Rejection Reasons**:
- Various quality threshold violations

**Impact on 15m Markets**: NONE - For debate participation, not crypto trading

**Legacy Status**: Not applicable

---

# CRITICAL FINDINGS

## 🔴 CRITICAL: Legacy Gate Conflicts

### Finding 1: Legacy Microstructure Gate Fallback
**Location**: `order_router.py:610`  
**Issue**: New microstructure gate has fallback to legacy gate if `spread_edge_analytics` unavailable  
**Code**:
```python
except ImportError:
    logger.warning("[EDGE-AWARE-GATE] spread_edge_analytics module not available, falling back to legacy gate")
    return check_market_microstructure(...)  # LEGACY FALLBACK
```

**Risk**: If import fails, system silently falls back to legacy gate with fixed 20c threshold  
**Impact**: HIGH - Can cause unexpected rejections with different logic  
**Recommendation**: Remove fallback, raise explicit error if new gate unavailable

### Finding 2: Fee-Aware Gate Still Active
**Location**: `order_router.py:383`  
**Issue**: Legacy fee-aware gate still in codebase, may be called in parallel with new gate  
**Risk**: Double gate checking can cause conflicting decisions  
**Impact**: HIGH - Can reject orders that new gate would accept  
**Recommendation**: Deprecate `check_fee_aware_gate()`, integrate logic into new microstructure gate

### Finding 3: Multiple Gate Entry Points
**Issue**: Gates are called from multiple locations in the pipeline  
**Entry Points**:
- `order_router.py` - Multiple gate functions
- `order_gate.py` - Pre-trade gate
- `venue_gate.py` - Venue compliance
- `lane_enforcement.py` - Agent lane enforcement

**Risk**: No single gate orchestration point, hard to trace decision flow  
**Impact**: MEDIUM - Makes debugging and shadow replay difficult  
**Recommendation**: Create single gate orchestration function with clear decision flow

---

# GATE CALL STACK ANALYSIS

## Typical 15m Market Order Flow

```
1. Lane Enforcement Gate (lane_enforcement.py)
   └─ gate_production_only(agent_id)
   
2. Venue Gate (venue_gate.py)
   └─ check_venue("kalshi")
   └─ check_can_trade()
   
3. Market Regime Gate (order_router.py)
   └─ _check_market_regime_gate(intent, mode, t0)
   
4. Fee-Aware Gate (order_router.py) ⚠️ LEGACY
   └─ check_fee_aware_gate(edge_pct, contract_price_cents, ...)
   
5. New Microstructure Gate (spread_edge_analytics.py)
   └─ edge_aware_microstructure_gate(edge_metrics, ...)
   └─ get_time_scaled_threshold(asset, time_to_expiry)
   └─ check_crossed_book()
   └─ check_minimum_depth()
   
6. Order Gate (order_gate.py)
   └─ check(intent)
   └─ Duplicate detection
   └─ Fill awareness
   └─ Risk envelope check
```

---

# FEATURE FLAG INVENTORY

## Trading Mode Flags
- `MERID_PM_TRADING_MODE` - Trading mode (mock/paper/live)
- `MERID_PM_LIVE_ENABLED` - Live trading enabled flag
- `MERID_ALLOW_LIVE_TRADES` - Live trades permission flag

## Gate-Specific Flags
- No explicit feature flags found for individual gates
- Gates are controlled by code path, not configuration

## Risk Envelope Flags
- Risk envelope checks delegated to `KalshiRiskManager`
- Per-asset risk limits may be configurable

---

# ASSET-SPECIFIC CODE PATH ANALYSIS

## Shared Code Paths
- All gates use same core functions for BTC, ETH, SOL, XRP, DOGE
- Asset-specific behavior via parameters (ticker, asset name)
- No asset-specific gate implementations found

## Asset-Specific Overrides
- **New microstructure gate**: Asset-specific calibration tables (thresholds, caps, depth)
- **Risk envelope**: May have per-asset risk limits
- **Market regime**: May have per-asset regime conditions

## Risk of Calibration Leakage
- **HIGH**: If asset-specific parameters not passed correctly, BTC/ETH defaults could apply to SOL/XRP/DOGE
- **MEDIUM**: Shared code paths make it easy to miss asset-specific parameter passing

---

# UNIT CONVERSION ANALYSIS

## Probability Conversions
- **Signal generation**: Model probability (0-1 fraction)
- **Edge calculation**: Probability in cents (0-100)
- **Threshold comparison**: Ratio (unitless) vs absolute (cents)

**Risk**: HIGH - Mixed conventions can cause edge miscalculation

## Price Conversions
- **Market data**: Cents (0-100)
- **Edge calculation**: Cents
- **Order submission**: Cents
- **Risk envelope**: USD (cents / 100)

**Risk**: MEDIUM - Generally consistent, but USD conversion points exist

## Side Conversions
- **Kalshi format**: BUY_YES, SELL_YES, BUY_NO, SELL_NO
- **Canonical format**: yes, no
- **Conversion function**: `parse_kalshi_side()` in `binary_price_space.py`

**Risk**: HIGH - Side conversion errors can invert trade direction

---

# IMMEDIATE ACTIONS REQUIRED

## Priority 1: Remove Legacy Gate Fallback
- [ ] Remove fallback to `check_market_microstructure()` in new gate
- [ ] Raise explicit error if `spread_edge_analytics` unavailable
- [ ] Add deployment safety check for new gate availability

## Priority 2: Deprecate Fee-Aware Gate
- [ ] Mark `check_fee_aware_gate()` as deprecated
- [ ] Integrate fee-aware logic into new microstructure gate
- [ ] Remove calls to fee-aware gate from order router

## Priority 3: Create Gate Orchestration
- [ ] Create single gate orchestration function
- [ ] Document gate call order and decision flow
- [ ] Add comprehensive logging for gate decisions

## Priority 4: Asset-Specific Parameter Validation
- [ ] Verify asset-specific parameters passed correctly at all gate calls
- [ ] Add validation for asset ticker/asset name consistency
- [ ] Add logging for asset-specific calibration values

## Priority 5: Unit Conversion Audit
- [ ] Trace probability units from signal to router
- [ ] Verify side conversion consistency across pipeline
- [ ] Add unit conversion validation at gate boundaries

---

# SUCCESS CRITERIA FOR PHASE 1

- [ ] All gates inventoried and classified (active/legacy/shadow)
- [ ] Legacy gate fallbacks removed or explicitly documented
- [ ] Gate call stack documented with decision flow
- [ ] Asset-specific parameter passing verified
- [ ] Unit conversion points identified and validated
- [ ] Feature flags inventoried and documented

---

# NEXT STEPS

1. **Immediate**: Remove legacy gate fallback in new microstructure gate
2. **Short-term**: Deprecate fee-aware gate and integrate logic
3. **Medium-term**: Create gate orchestration function
4. **Long-term**: Implement comprehensive gate decision logging

---

# REFERENCES

- Gate inventory: This document
- New microstructure gate: `MICROSTRUCTURE_GATE_15M_SPEC_2026_08_02.md`
- End-to-end audit checklist: `END_TO_END_PIPELINE_AUDIT_2026_08_02.md`
- Spread edge analytics: `merid/event_venues/kalshi/spread_edge_analytics.py`
- Order router: `merid/event_venues/kalshi/order_router.py`
