# Order Flow and Execution Path Deep Audit Report
**Date**: 2026-07-14  
**Scope**: 15m Kalshi crypto trading system order flow, execution paths, and leverage controls  
**Assets**: BTC, ETH, SOL, XRP, DOGE (complete crypto stack)

---

## Executive Summary

**Overall Assessment**: ✅ **NO CRITICAL LEVERAGE BUGS FOUND**

The order flow and execution paths are well-structured with comprehensive risk controls. Recent fixes (2026-07-12 execution disconnect fix, duplicate order window fixes) have addressed historical issues. The system uses a conservative fixed $1 exposure cap with hard limits on position sizes.

**Key Findings**:
- ✅ Fixed $1 global exposure cap enforced across all assets
- ✅ Hard limit: max 1 contract per order
- ✅ Anti-stacking guard prevents order accumulation
- ✅ Marketable orders never forced to post_only (execution disconnect fix)
- ✅ Price repeat window reduced to 60s (from 900s)
- ✅ Duplicate order window at 5s (matches 15m cadence)
- ✅ Kelly hard cap at 2% (conservative)
- ✅ Crisis regime reduces position sizes by 50%
- ⚠️ Execution pipeline is quarantined (intentional, not a bug)

---

## 1. Order Router Audit (`merid/event_venues/kalshi/order_router.py`)

### 1.1 Duplicate Detection
**Status**: ✅ CORRECT

- **Duplicate Order Window**: 5 seconds (line ~110)
  - Reduced from 60s on 2026-07-12
  - Matches 15m crypto agent 5s cadence
  - Allows legitimate re-submissions after market moves

- **Implementation**: `_check_duplicate_order()` (lines 352-392)
  - Key: (ticker, side, action, price_cents)
  - Thread-safe with `_duplicate_order_lock`
  - Rejects if time_since_last < 5s

### 1.2 Anti-Stacking Guard
**Status**: ✅ CORRECT

- **Implementation**: `_check_open_resting_order()` (lines 310-349)
  - Rejects BUY orders when live resting order exists for same ticker+side+action
  - SELL/exit orders never blocked (positions can always be closed)
  - Fail-closed on monitor errors (rejects new orders if monitor unavailable)
  - Uses `resting_order_monitor.find_open_order()` for detection

- **Rationale**: With 5s duplicate window, 15m loop could stack new GTC orders on every window expiry. This structural guard prevents accumulation.

### 1.3 Post-Only Logic
**Status**: ✅ CORRECT (2026-07-12 fix)

- **Implementation**: `_effective_post_only()` (lines 299-307)
  - Marketable orders (aggressiveness > 0) always have post_only=False
  - Only resting orders (aggressiveness == 0) honor post_only from policy
  - Belt-and-suspenders check at VenueOrder construction

- **Historical Bug**: Previously, `apply_maker_taker_policy` forced post_only=True for marketable intents when edge_net_of_taker < 2.0%, causing orders to rest unfilled or trigger "post-only cross" rejections.

### 1.4 Fill Accounting
**Status**: ✅ CORRECT (2026-07-12 fix)

- **Implementation**: `_resolve_requested_count()` (lines 285-296)
  - Fallback when Kalshi API returns size=0 or None on accepted orders
  - Uses intent_count if placed_size <= 0
  - Prevents corrupt fill-pct and filled/partial status classification

### 1.5 Price Clamping
**Status**: ✅ CORRECT

- **Paper fills**: Clamped to 10-75c range (lines 1659, 1669)
- **Intent construction**: 10-75c assertion in loop_15m.py
- **Canonical range**: 10-75c expanded from 10-50c on 2026-07-12

---

## 2. Order Gate Audit (`merid/event_venues/kalshi/order_gate.py`)

### 2.1 Exposure Model
**Status**: ✅ CORRECT - Fixed $1 Cap

- **Global Exposure Cap**: $1.00 (MERID_FIXED_EXPOSURE_CAP_USD)
  - Enforced via `kalshi_crypto_15m_risk_envelope.py`
  - Percentage-based limits DISABLED (lines 970-976)
  - Risk enforced via sequential trading + slot-based position management

- **Window-based limits**: DISABLED (line 970)
  - Old 3% per agent / 5% total venue limits removed
  - Replaced by fixed $1 model for small bankroll optimization

### 2.2 Price Repeat Detection
**Status**: ✅ CORRECT

- **Price Repeat Window**: 60 seconds (line 243)
  - Reduced from 900s (15 min) on 2026-07-12
  - Allows legitimate re-execution at same price after market returns
  - Forces scaling in at lower prices (cheaper entry)

- **Implementation**: `check_price_repeat()` (lines 563-623)
  - Blocks exact price repeat within 60s window
  - Blocks higher price if same ticker+side executed recently (scale-in enforcement)
  - Records execution history for future checks

### 2.3 Exit Policy Validation
**Status**: ✅ CORRECT

- **Entry orders**: Require exit_policy_id, window_resolution_id, risk_tier, max_hold_seconds (lines 985-996)
- **Exit orders**: Require exit_policy_id for tracking (lines 1057-1069)
- **Validation**: max_hold_seconds must be 60-3600s (lines 1013-1016)
- **Metadata validation**: TP/SL price validation when metadata provided (lines 1018-1030)

### 2.4 Position Existence Check
**Status**: ✅ CORRECTLY MOVED

- **Location**: Moved from order_gate to order_router (2026-07-13)
- **Reason**: order_gate.check() lacks source field needed to distinguish exit orders
- **Current**: Handled in order_router where source is available

---

## 3. Maker/Taker Integration Audit (`merid/event_venues/kalshi/maker_taker_integration.py`)

### 3.1 Post-Only Policy
**Status**: ✅ CORRECT (2026-07-12 fix)

- **Implementation**: `apply_maker_taker_policy()` (lines 27-154)
  - Lines 106-116: post_only only applied when aggressiveness == 0.0
  - Marketable intents (aggressiveness > 0) keep post_only=False
  - Logs override when policy recommends maker but intent is marketable

- **Policy mode**: AGGRESSIVE_CONVICTION (default for 15m crypto)
- **Fallback**: Sets expected_role/fee_type to "unknown" on failure (safe)

---

## 4. Resting Order Monitor Audit (`merid/event_venues/kalshi/resting_order_monitor.py`)

### 4.1 Order Tracking
**Status**: ✅ CORRECT

- **Primary key**: (venue, kalshi_order_id) - server-side ID from Kalshi
- **Status source**: Kalshi portfolio endpoint (not intent inference)
- **Polling**: Every 30 seconds for status sync
- **Terminal statuses**: filled, canceled, expired, rejected, executed

### 4.2 Anti-Stacking Support
**Status**: ✅ CORRECT

- **Implementation**: `find_open_order()` (lines 237-273)
  - Case-insensitive ticker/side/action matching
  - Skips TERMINAL_STATUSES
  - Skips remaining_size <= 0 records
  - Returns kalshi_order_id of first matching live order

### 4.3 Max Hold Time
**Status**: ✅ CORRECT

- **15m markets**: 180 seconds (3 minutes) max hold (line 42)
- **Detection**: Ticker pattern "15M" or "-15M" (lines 202-206)
- **Enforcement**: Cancels orders when elapsed > max_hold_seconds (lines 431-441)

---

## 5. Execution Pipeline Audit (`merid_core/kalshi/execution_pipeline.py`)

### 5.1 Quarantine Status
**Status**: ✅ INTENTIONALLY DISABLED

- **Hardening**: Raises RuntimeError unless MERID_ALLOW_EXECUTION_PIPELINE_BYPASS=1 (lines 46-53)
- **Reason**: Bypasses ALL safety gates (order_router, GlobalRiskGuard, Top-3 batch, PreTradeGate, kill switches)
- **Production path**: Uses order_router.route_order_async() instead
- **NATS execution**: Requires MERID_NATS_EXECUTION_ENABLED=true (line 58)

### 5.2 Risk Controls (if enabled)
**Status**: ⚠️ NOT APPLICABLE (module disabled)

- Position limits: 100 per market, 300 per asset
- Kalshi-native limits: 25,000 contracts (with 80% accountability threshold)
- Daily loss limit: Derived from bankroll
- Total notional limit: Derived from bankroll

**Note**: These controls are NOT used in production. Production uses order_router + risk envelope.

---

## 6. Loop 15m Intent Construction Audit (`merid/loop_15m.py`)

### 6.1 Position Sizing
**Status**: ✅ CORRECT

- **Hard limit**: max 1 contract per order (line 4243)
- **Sizing path**: Uses `unified_sizing.compute_order_size()` (line 1704)
- **Fallback**: Default count=1 if sizing fails (line 1816)
- **Notional calculation**: (count * price_cents) / 100.0 (line 4037)

### 6.2 Price Clamping
**Status**: ✅ CORRECT

- **Canonical range**: 10-75c (lines 3988, 3993, 4005, 4011)
- **Assertion**: Pre-send assert for price range [10,75] (lines 4184-4191)
- **Fallback**: 50c if market state unavailable (lines 3997, 4015, 4018, 4021)

### 6.3 Aggressiveness
**Status**: ✅ CORRECT

- **Computation**: `compute_order_aggressiveness()` from edge (lines 4204-4236)
- **Default**: 0.5 (marketable) if computation fails (line 4236)
- **Exit orders**: Forced to aggressiveness=1.0 (line 1293)
- **Intent field**: aggressiveness passed to OrderIntent (line 4267)

### 6.4 Post-Only
**Status**: ✅ CORRECT

- **Explicit**: post_only=False (line 4265)
- **Rationale**: Prevents "Post_only_but_execution_type_can't_rest" errors
- **Router check**: `_effective_post_only()` enforces marketable rule

---

## 7. Risk Parameters Audit

### 7.1 Kelly Sizing
**Status**: ✅ CONSERVATIVE

- **Kelly hard cap**: 2% (0.02) in profile (crypto_15m_profile.py line 1124)
- **Kelly global notional cap**: 2% (line 1129)
- **Min edge**: 1% (line 1125)
- **Max edge**: 7% (line 1126)
- **Position sizer**: Uses profile kelly_hard_cap (position_sizer.py line 73)

### 7.2 Contract Caps
**Status**: ✅ STRICT

- **Max single order**: 1 contract (crypto_15m_profile.py line 1136)
- **Max total**: 5,000 contracts (line 1132)
- **Max per asset**: 1,750 contracts (line 1133)
- **Max per cluster**: 750 contracts (line 1134)
- **Failsafe**: 1 contract per order (line 1188)

### 7.3 Dynamic Sizing
**Status**: ✅ DISABLED

- **Legacy disable**: `legacy_disable_dynamic_contract_caps=True` (line 1205)
- **Profile self-check**: Enforces True (lines 1958-1960)
- **Rationale**: Fixed $1 exposure cap replaces percentage-based sizing

### 7.4 Exposure Cap
**Status**: ✅ FIXED $1 MODEL

- **Fixed cap**: $1.00 (MERID_FIXED_EXPOSURE_CAP_USD)
- **Enforcement**: 
  - Risk envelope (kalshi_crypto_15m_risk_envelope.py)
  - Global slot allocator (global_slot_allocator.py)
  - Per-asset upper bounds are NOT individual caps (line 1203)
- **Total cap**: $1 across ALL 5 assets (BTC+ETH+SOL+XRP+DOGE)

---

## 8. Leverage Multipliers Audit

### 8.1 Regime Detector
**Status**: ✅ CORRECT

- **Normal regime**: position_size_multiplier = 1.0 (regime_detector.py line 302)
- **Crisis regime**: position_size_multiplier = 0.5 (line 312)
- **Impact**: Crisis reduces position sizes by 50%
- **Price range**: Crisis expands to 5-95c (multiplier 1.9x)

### 8.2 Strike Selector
**Status**: ✅ ISOLATED TO STRIKE SELECTION

- **VOL_MULTIPLIERS**: Low=0.7, Medium=1.0, High=1.3 (strike_selector.py lines 67-71)
- **TENOR_MULTIPLIERS**: LT_6H=0.5, 6H_2D=0.75, 2D_14D=1.0, GT_14D=1.3 (lines 74-77)
- **REGIME_MULTIPLIERS**: Trending=1.2, MeanReversion=0.8, Choppy=0.6 (lines 82-85)
- **Usage**: Multipliers affect strike selection distance, NOT position sizing

### 8.3 Profile Position Size Multiplier
**Status**: ✅ DEFAULT 1.0

- **Default**: position_size_multiplier = 1.0 (crypto_15m_profile.py line 629)
- **Loading**: From regime factors (line 1557)
- **Impact**: Currently unused (fixed $1 model replaces percentage sizing)

---

## 9. Global Slot Allocator Audit (`merid/risk/global_slot_allocator.py`)

### 9.1 Exposure Management
**Status**: ✅ CORRECT

- **Max exposure**: $1.00 (line 95)
- **Max entry price**: 75c (line 97, expanded from 50c on 2026-07-12)
- **Min entry price**: 10c (line 96)
- **Max contracts per order**: 1 (line 98)

### 9.2 Slot Allocation
**Status**: ✅ CORRECT

- **Per-asset slots**: One slot per asset (BTC, ETH, SOL, XRP, DOGE)
- **Exposure tracking**: Sum of slot.exposure_usd (line 123)
- **Available exposure**: MAX_EXPOSURE_USD - total_exposure (line 124)
- **Entry check**: Requires sufficient exposure (lines 173-180)

### 9.3 Phantom Slot Clearing
**Status**: ✅ CORRECT (2026-07-13 fix)

- **Implementation**: `clear_slots_on_empty_positions()` (lines 389-412)
- **Trigger**: When position_count=0 but slots exist
- **Rationale**: Prevents phantom exposure from previous sessions

---

## 10. Risk Envelope Audit (`merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`)

### 10.1 Exposure Caps
**Status**: ✅ FIXED $1 MODEL

- **Fixed cap**: $1.00 (MERID_FIXED_EXPOSURE_CAP_USD, line 404)
- **Max single order**: $1.00 (line 918)
- **Max total**: $1.00 (line 919)
- **Per-asset upper bounds**: $1.00 each (NOT individual caps, line 946)

### 10.2 Position Sizing
**Status**: ✅ CONSERVATIVE

- **Base position size**: Derived from max_single_order_notional_usd (line 441)
- **Assumed contract price**: $0.42 (midpoint of 10-75c range)
- **Kelly fraction**: From profile kelly_hard_cap (line 383)
- **Dynamic sizing max contracts**: 1 (line 386)

### 10.3 Window Tracking
**Status**: ✅ CORRECT

- **Executed exposure**: Tracked per agent and total (lines 32-33)
- **Resting exposure**: Tracked per agent and total (line 34)
- **Asset exposure**: Tracked per asset (line 37)
- **Recording**: On fills, resting order placement, cancel, reject

---

## 11. Historical Bug Fixes Verified

### 11.1 Execution Disconnect Fix (2026-07-12)
**Status**: ✅ VERIFIED IN PLACE

- **post_only contradiction**: Fixed in maker_taker_integration.py
- **Order stacking risk**: Fixed with `_check_open_resting_order()` guard
- **Dead fill accounting**: Fixed with `_resolve_requested_count()` fallback
- **requested_C=0**: Fixed with fallback to intent_count

### 11.2 Duplicate Order Window Fix (2026-07-12)
**Status**: ✅ VERIFIED IN PLACE

- **order_router.py**: 5s window (line ~110)
- **order_gate.py**: 60s price repeat window (line 243)
- **Rationale**: Matches 15m cadence, allows legitimate re-executions

### 11.3 10-75c Price Range Expansion (2026-07-12)
**Status**: ✅ VERIFIED IN PLACE

- **Canonical range**: 10-75c across all execution paths
- **Crisis regime**: 5-95c (separate multiplier)
- **Profile YAML**: Source of truth for range limits
- **Test coverage**: All tests updated to 75c max

---

## 12. Potential Issues (Non-Critical)

### 12.1 Execution Pipeline Quarantine
**Severity**: ℹ️ INFORMATIONAL (not a bug)

- **Issue**: execution_pipeline.py is quarantined and disabled
- **Impact**: None - production uses order_router
- **Rationale**: Module bypasses all safety gates
- **Recommendation**: Keep quarantined, document clearly

### 12.2 Legacy Percentage-Based Limits
**Severity**: ℹ️ INFORMATIONAL (intentionally disabled)

- **Issue**: Old percentage-based limits still in code but disabled
- **Examples**: PER_MARKET_EXPOSURE_CAP_PCT, PER_STRATEGY_EXPOSURE_CAP_PCT
- **Impact**: None - fixed $1 model replaces them
- **Recommendation**: Consider cleanup in future refactoring

### 12.3 Strike Selector Multipliers
**Severity**: ℹ️ LOW (isolated impact)

- **Issue**: Multipliers (volatility, tenor, regime) affect strike selection only
- **Impact**: May affect strike distance but not position sizing
- **Recommendation**: Monitor for unintended leverage effects

---

## 13. Recommendations

### 13.1 No Critical Issues
**Action**: ✅ NO ACTION REQUIRED

The order flow and execution paths are well-protected with comprehensive risk controls. No critical leverage bugs found.

### 13.2 Monitoring Recommendations
**Action**: CONSIDER ENHANCED MONITORING

1. **Regime transitions**: Monitor for crisis regime activation (position_size_multiplier=0.5)
2. **Slot allocator**: Monitor for phantom slot accumulation (already has clearing logic)
3. **Price repeat blocks**: Monitor frequency of price_repeat rejections (may indicate market conditions)
4. **Anti-stacking guard**: Monitor frequency of open_order_exists rejections

### 13.3 Documentation Recommendations
**Action**: CONSIDER CLEANUP

1. **Legacy limits**: Remove or clearly document disabled percentage-based limits
2. **Execution pipeline**: Add prominent warning that module is quarantined
3. **Strike selector**: Document that multipliers affect strike selection, not position sizing

---

## 14. Conclusion

The 15m Kalshi crypto trading system has robust order flow and execution paths with comprehensive risk controls:

- ✅ **Fixed $1 exposure cap** enforced across all assets
- ✅ **Hard limit of 1 contract per order** prevents oversized positions
- ✅ **Anti-stacking guard** prevents order accumulation
- ✅ **Marketable order protection** prevents execution disconnect
- ✅ **Conservative Kelly sizing** at 2% hard cap
- ✅ **Crisis regime** reduces position sizes by 50%
- ✅ **Price repeat window** allows legitimate trading while preventing abuse
- ✅ **Duplicate order window** matches 15m cadence

**No critical leverage bugs found.** The system is well-designed with multiple layers of protection against excessive leverage and position accumulation.

---

**Audit Completed**: 2026-07-14  
**Auditor**: Cascade AI Assistant  
**Next Audit**: Recommended after major changes to order flow or risk model
