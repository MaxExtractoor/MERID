# Kalshi 15M Final Sweep Report

**Date:** 2026-05-28
**Scope:** Upstream→Midstream→Downstream structural coherence verification
**Objective:** Confirm stack is structurally coherent on spot, indicators, edge, risk, exits, and order book microstructure

---

## Executive Summary

**Overall Assessment:** ✅ **STRUCTURALLY COHERENT**

The stack is now structurally coherent with single canonical sources for spot, indicators, edge, risk, exits, and order book microstructure. All major consolidation work is complete. Remaining items are primarily defensive-in-depth checks and intentional legacy fallback paths.

---

## 1) Upstream: Data and State Sanity

### 1.1 Single Spot Source per Asset per Strip

**Status:** ✅ **CONFIRMED**

**Canonical Source:** `SpotProvider` abstraction in `merid/prediction/spot_provider.py`
- `UnifiedSpotProvider` - Canonical source for 15m crypto
- `MeridRtiSpotProvider` - RTI HTTP API (legacy, optional)
- `CfbSpotProvider` - CFB RTI proxy (legacy, optional)

**Usage in 15m Crypto:**
- `agent_grid_15m.py` uses `SpotProvider` abstraction (lines 2655, 4464, 4497)
- All spot data flows through `get_spot_provider(provider_type="unified")`
- No legacy spot paths active in 15m crypto path

**Verification:** ✅ Only one spot source per asset per strip in 15m crypto

---

### 1.2 Single Book State Source per Market per Strip

**Status:** ✅ **CONFIRMED**

**Canonical Source:** `LocalOrderbook` + `OrderbookSnapshot` in `unified_market_state.py`
- `LocalOrderbook` - Live mutable state from WS updates
- `OrderbookSnapshot` - Immutable L2 snapshot (canonical definition)
- `KalshiMarketStateStore` - Single source of truth for market state

**Consolidation Completed:**
- ✅ Removed local `OrderBookSnapshot` from `unified_edge.py`
- ✅ Removed custom `OrderBookSnapshot` from `liquidity_monitor.py`
- ✅ Created canonical microstructure utilities in `microstructure.py`
- ✅ All components now use canonical `OrderbookSnapshot`

**Verification:** ✅ Only one book state source per market per strip

---

### 1.3 Invariants: Spot Non-Stale, Book YES/NO Duality

**Status:** ⚠️ **NEEDS IMPLEMENTATION**

**Spot Staleness Check:**
- `agent_grid_15m.py` has staleness check (line 3709) but it's warning-only in debug mode
- Should be hardened to blocking in production mode

**Book YES/NO Duality:**
- ✅ Canonical microstructure utilities enforce YES/NO duality
- ✅ Unit tests verify YES + NO = 100 cents invariant
- ⚠️ No runtime invariant check in production path

**Recommendation:** Add production invariants:
```python
# In KalshiMarketStateStore or market state update path
assert state.best_yes_bid + state.best_no_ask == 100, "YES/NO duality violation"
assert state.best_no_bid + state.best_yes_ask == 100, "YES/NO duality violation"
```

---

## 2) Midstream: Gates, Edge, and Strategy Alignment

### 2.1 No Double-Gating on Same Condition

**Status:** ✅ **CLEANED UP**

**Double-Gating Found and Fixed:**
- ✅ Removed duplicate depth check in `agent_grid_15m.py` (line 3726-3729)
  - Was checking `depth_yes < 100 or depth_no < 50` separately
  - Now delegated to unified edge microstructure utilities

**Spread Checks:**
- `agent_grid_15m.py` has legacy spread check (line 3718) - now warning-only, delegated to unified edge
- `unified_edge.py` has canonical spread checks using microstructure utilities
- `order_router.py` has A5 market condition spread check - this is defense-in-depth at router level (appropriate)

**Depth Checks:**
- `unified_edge.py` has canonical depth checks using microstructure utilities
- `order_router.py` has depth thresholds for A5 market condition - defense-in-depth (appropriate)

**Verification:** ✅ No duplicate gating on same condition in decision path

---

### 2.2 Edge vs Strategy Consistency

**Status:** ⚠️ **NEEDS VERIFICATION WITH LIVE DATA**

**Current State:**
- Unified edge returns `EdgeCheckResult` with detailed reason
- Strategy layer uses edge result for side/TP/SL/sizing decisions
- Shadow mode logs comparison between legacy and unified edge

**Verification Needed:**
- Sample trades to verify edge allowed them with clear `EdgeCheckResult.reason="OK"`
- Strategy truth tables show rationales matching edge result
- No trades where strategy overrides edge rejection

**Recommendation:** Add integration test with synthetic data to verify edge→strategy consistency

---

### 2.3 TTE & Regime Interplay

**Status:** ⚠️ **NEEDS VERIFICATION**

**TTE Regimes:**
- `NORMAL` / `CRITICAL` / `TERMINAL` regimes defined
- Dynamic risk and exits use TTE regimes
- Time traps in edge should be consistent with TTE regimes

**Regime Cooldown:**
- Performance-based regime cooldown in edge
- Should be orthogonal to TA chop filters

**Verification Needed:**
- Confirm time trap thresholds match TTE regime boundaries
- Confirm regime cooldown doesn't conflict with TA chop filters

---

## 3) Downstream: Routing, Fills, Exits, and PnL

### 3.1 Router and Position Cache Book View

**Status:** ✅ **ALIGNED**

**Book View Consistency:**
- Router uses `KalshiMarketStateStore` for market data
- Position cache subscribes to `KalshiMarketStateStore` for price updates
- Both now use canonical `OrderbookSnapshot` with YES/NO duality
- Cents/dollars conversion handled by microstructure utilities

**Verification:** ✅ Router and position cache see same book view as unified edge

---

### 3.2 Exit Policy and TP/SL

**Status:** ⚠️ **NEEDS VERIFICATION WITH LIVE DATA**

**Exit Logic:**
- `ExitPolicy` + `dynamic_risk` + TTE regimes govern TP/SL
- Position cache monitors positions and forces exits near expiry
- TP/SL levels should use canonical microstructure for spread calculation

**Verification Needed:**
- For filled trades, verify TP/SL hits correspond to YES/NO bids crossing thresholds
- Verify exit type (TP, SL, forced TTE, expiry) matches exit_policy logic

---

### 3.3 PnL Audit

**Status:** ⚠️ **PENDING NEXT BATCH**

**Metrics to Track:**
- TP vs SL vs expiry counts
- Slippage vs implied spread
- Effectiveness of winrate guard and regime cooldown

**Recommendation:** Implement PnL audit with exit audit spec on next live batch

---

## 4) Tests and "Eggs" Checklist

### 4.1 Missing Coverage at Integration Boundaries

**Status:** ⚠️ **PENDING**

**End-to-End Test Path Needed:**
- Spot + order book snapshot → indicator stack snapshot → unified edge → check_edge → strategy → risk → router OrderIntent (with TP/SL)
- Given synthetic spot + book, assert consistent OrderIntent with all rationales populated

**Recommendation:** Create golden path integration test fixture (see section 5)

---

### 4.2 Dead Code / Hidden Eggs

**Status:** ✅ **CLEANED UP**

**Legacy Code Found:**
- Many LEGACY REMOVAL comments indicating cleanup has been done
- Legacy edge path exists as fallback in `agent_grid_15m.py` - intentional for shadow mode
- Legacy RTI/CFB spot providers exist but not used in 15m crypto path
- Legacy sizing path exists as fallback when canonical sizing fails

**No Active Legacy Paths in 15m Crypto:**
- ✅ No legacy order book parsers
- ✅ No legacy spot sources (unified provider used)
- ✅ No legacy edge computation (unified edge used, legacy only as shadow mode fallback)

**Verification:** ✅ No hidden legacy paths that could re-enter 15m crypto

---

### 4.3 Config Invariants

**Status:** ⚠️ **NEEDS VERIFICATION**

**15m Profile Config:**
- Guardrail fields: price floor, spread caps, same-side caps, TTE windows, regime cooldown thresholds, depth multipliers
- Need to verify all fields present and within sane ranges

**Startup Validations:**
- Need to confirm `MERID_UNIFIED_EDGE_ENABLED`, `SPOT_PROVIDER_TYPE`, and risk caps aligned with 15m config

**Recommendation:** Add config validation in startup_validations.py

---

## 5) Golden Path Integration Test Fixture

**Status:** ⚠️ **PENDING**

**Proposed Fixture:**
- Synthetic Kalshi 15m BTC strip with handcrafted:
  - Spot price (e.g., $50,000)
  - Order book snapshot (YES bids at 40c, NO bids at 65c)
  - Indicator state (EMA, ATR, trend regime)
  - Expected edge result (edge > threshold, passes all checks)
  - Expected strategy decision (side=BUY YES, TP=45c, SL=35c, size=10)
  - Expected OrderIntent with all rationales populated

**Purpose:** Canonical regression test for the whole 15m stack

---

## 6) Next Live Run Recommendations

### 6.1 Constrained Live Window

**Configuration:**
- Small size (e.g., 1-2 contracts per trade)
- All guards active
- Shadow mode enabled (compare legacy vs unified edge)

### 6.2 Diagnostics to Watch

**Strip Diagnostics:**
- Indicator vs edge vs strategy vs risk rejections
- Track candidate counts at each gate

**Microstructure Diagnostics:**
- Best bids/asks at entry/exit
- Depth and effective spread at entry/exit
- Verify YES/NO duality holds in production

**Strategy Truth Tables:**
- Side/TP/SL/sizing rationales for a handful of trades
- Verify rationales match edge result

**Exit Audit Fields:**
- Exit type (TP, SL, forced TTE, expiry)
- Rationale matching exit_policy / position_cache logic

### 6.3 Patterns to Watch For

**Over-Filtering:**
- Too few candidates reaching unified edge
- Revisit TA gates vs edge thresholds if needed

**Systematic Slippage:**
- Slippage consistently higher than implied spread
- May indicate depth aggregation or order splitting needed

**Exits Not Triggering:**
- TP/SL not hitting despite price crossing thresholds
- May indicate wrong side of book being monitored

---

## 7) Summary of Remaining Work

### High Priority

1. **Add production invariants** for spot staleness and YES/NO duality
2. **Create golden path integration test** with synthetic BTC strip
3. **Verify TTE regimes vs time traps consistency**
4. **Add config validation** for 15m profile guardrail fields

### Medium Priority

1. **Verify edge vs strategy consistency** with sample trades
2. **Verify exit logic** with live TP/SL data
3. **Implement PnL audit** with exit audit spec

### Low Priority

1. **Add depth-aware order splitting** for large orders
2. **Add risk cap vs depth min logic** (min of both constraints)

---

## 8) Conclusion

**Overall Assessment:** ✅ **STRUCTURALLY COHERENT**

The Kalshi 15M stack is now structurally coherent with:
- ✅ Single canonical spot source (`SpotProvider`)
- ✅ Single canonical book state (`LocalOrderbook` + `OrderbookSnapshot`)
- ✅ Single canonical microstructure utilities (`microstructure.py`)
- ✅ Unified edge as single place for all guardrails
- ✅ No duplicate gating on same condition
- ✅ No hidden legacy paths in 15m crypto

**Next Steps:**
1. Run constrained live window with diagnostics
2. Verify edge vs strategy consistency with live data
3. Add production invariants for YES/NO duality
4. Create golden path integration test fixture

**Estimated Effort:** 1-2 days for remaining high-priority items, 2-3 days for full verification with live data.
