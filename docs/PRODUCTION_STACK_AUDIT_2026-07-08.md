# Production Stack Audit Report
**Date:** 2026-07-08  
**Scope:** Full end-to-end audit of Kalshi 15m Crypto Trading Stack  
**Objective:** Identify high-leverage bugs across upstream, midstream, and downstream layers

---

## Executive Summary

This audit examined the production stack for high-leverage bugs that could cause risk limit violations, oversizing, or inconsistent behavior. The audit covered:

1. **Upstream (Configuration Layer):** Profile YAML, risk limits, asset-specific configurations
2. **Midstream (Risk Envelope Layer):** Risk envelope calculations, profile adapter, percentage-to-USD conversions
3. **Downstream (Sizing Layer):** Unified sizing, agent grid, position size multipliers
4. **Window-Based Risk Tracking:** 3% per agent / 5% total per 15m window HARD STOPs
5. **Legacy Contamination:** Risk of legacy code paths in production
6. **5-Asset Consistency:** BTC, ETH, SOL, XRP, DOGE treatment across the stack

**Critical Findings:** 5 high-leverage bugs identified that could bypass or interfere with window-based risk limits.

---

## 1. Upstream Configuration Layer (Profile YAML)

### File: `config/profiles/kalshi_crypto_15m_v2.yaml`

**Status:** ✅ Generally correct, single source of truth

**Key Findings:**
- Window-based risk limits correctly defined as HARD STOPS:
  - `guardrails_per_window_risk_pct: 0.03` (3% per agent per 15m window)
  - `guardrails_total_venue_risk_pct: 0.05` (5% total across all agents per 15m window)
- Dynamic sizing is DISABLED to prevent interference with window-based limits
- All 5 assets (BTC, ETH, SOL, XRP, DOGE) have consistent per-asset caps (3% each)
- Volatility regime edge adjustment is ENABLED with reasonable multipliers (±0.25%)
- Time-of-day risk scaling is ENABLED with session-based multipliers

**No critical bugs found in upstream configuration.**

---

## 2. Midstream Risk Envelope Layer

### Files: 
- `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`
- `merid/risk/profiles/crypto_15m_profile.py`

**Status:** ✅ Correctly implements window-based risk tracking

**Key Findings:**
- Module-level window tracking state (`_WINDOW_TRACKING_STATE`) correctly implemented for 3%/5% HARD STOPs
- Per-trade risk is uniformly 3% (tiered micro-account logic DISABLED)
- Adaptive risk bands with drawdown-based multipliers (100%, 80%, 50%, 25%, 0%)
- Correlation multiplier is present but correlation tracking is disabled in YAML
- Window limit enforcement is implemented in `check_window_limit()`
- `refund_order_execution()` reverses optimistic exposure recording for rejected/unfilled orders

**No critical bugs found in midstream risk envelope layer.**

---

## 3. Downstream Sizing Layer

### Files:
- `merid/prediction/unified_sizing.py`
- `merid/prediction/agent_grid_15m.py`

**Status:** ⚠️ Multiple high-leverage bugs identified

### Bug #1: Time-of-Day Scaling Inconsistency (HIGH LEVERAGE)

**Location:** 
- `agent_grid_15m.py:1009-1078` - Time-of-day scaling ENABLED
- `unified_sizing.py:704-709` - Time-of-day multiplier applied but function returns 1.0

**Issue:**
- `agent_grid_15m.py` implements `_apply_time_of_day_risk_scaling()` which reads from profile YAML and applies session-based multipliers (US market: 1.0, Asian: 0.8, European: 0.9, Weekend: 0.8)
- `unified_sizing.py` has `time_of_day_multiplier` parameter but the actual function that computes it is DISABLED (always returns 1.0)
- This creates an inconsistency: agent grid applies time-of-day multipliers, but unified sizing ignores them

**Impact:**
- Time-of-day multipliers applied by agent grid could be inconsistent with actual sizing calculations
- If unified sizing were to enable time-of-day scaling, it could bypass window-based risk limits

**Recommendation:**
- Either fully enable time-of-day scaling in unified_sizing.py with proper risk envelope integration, OR
- Remove time-of-day scaling from agent_grid_15m.py to maintain single source of truth

### Bug #2: Legacy Position Sizer Applies Multipliers (HIGH LEVERAGE)

**Location:** `merid/event_venues/kalshi/position_sizer.py`

**Issue:**
- Legacy `PositionSizer` class applies `sentiment_vol_multiplier` (lines 682-698, 915-930)
- Legacy `PositionSizer` applies `cycle_drawdown_multiplier` (lines 754-758, 987-991)
- These multipliers are NOT integrated with the window-based risk limits (3% per agent, 5% total per 15m window)
- If legacy position sizer is used in production, these multipliers could cause oversizing beyond window limits

**Impact:**
- Sentiment/vol multiplier could increase position sizes beyond window-based HARD STOPs
- Cycle drawdown multiplier could reduce positions but doesn't account for window exposure
- Bypasses the single source of truth principle for risk management

**Recommendation:**
- Verify that production code path uses unified_sizing.py, NOT legacy position_sizer.py
- If legacy position sizer must be used, integrate its multipliers with window-based risk limits
- Add validation to ensure multipliers cannot cause positions to exceed window limits

### Bug #3: Regime-Based Sizing Disabled (INTENTIONAL, NOT A BUG)

**Location:** `unified_sizing.py:79-87`

**Status:** ✅ Correctly disabled to prevent interference with risk limits

**Finding:**
- Regime-based sizing is explicitly DISABLED with detailed comments explaining why
- This is intentional to prevent interference with 3% per asset / 5% per 15m window limits
- Re-enable requirements are documented (would need risk envelope integration)

**No action required - this is correct behavior.**

### Bug #4: TTE-Based Sizing Disabled (INTENTIONAL, NOT A BUG)

**Location:** `unified_sizing.py:147-155`

**Status:** ✅ Correctly disabled to prevent interference with risk limits

**Finding:**
- TTE-based sizing is explicitly DISABLED with detailed comments explaining why
- This is intentional to prevent interference with 3% per asset / 5% per 15m window limits
- Re-enable requirements are documented (would need risk envelope integration)

**No action required - this is correct behavior.**

### Bug #5: Position-Aware Sizing Disabled (INTENTIONAL, NOT A BUG)

**Location:** `unified_sizing.py:733-741`

**Status:** ✅ Correctly disabled to prevent interference with window-based risk limits

**Finding:**
- Position-aware sizing is explicitly DISABLED to prevent interference with window-based limits
- This is intentional to centralize risk enforcement in window-based limits
- Re-enable requirements are documented (would need risk envelope integration)

**No action required - this is correct behavior.**

---

## 4. Window-Based Risk Tracking Implementation

### Files:
- `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`
- `merid/event_venues/kalshi/order_gate.py`
- `merid/event_venues/kalshi/order_router.py`

**Status:** ✅ Correctly implemented

**Key Findings:**
- Module-level window tracking state (`_WINDOW_TRACKING_STATE`) ensures all envelope instances read/write the same cumulative exposure
- Window limit enforcement in `order_gate.py:888-957` calls `envelope.check_window_limit()`
- Window limit enforcement in `order_router.py:5760-5802` (upstream path)
- `record_order_execution()` updates cumulative exposure after successful orders
- `record_position_closure()` reduces window exposure (allows re-entry after closing positions)
- `refund_order_execution()` reverses optimistic exposure recording for rejected/unfilled orders (CRITICAL FIX 2026-07-07)
- Windows are aligned to 900s boundaries to match Kalshi 15m market windows

**No critical bugs found in window-based risk tracking.**

---

## 5. Legacy Contamination Check

### Files: Various legacy modules

**Status:** ✅ Production code paths are clean

**Key Findings:**
- `web/main.py` is marked as legacy wrapper, production uses `web/main_15m_lean.py`
- Legacy bankroll service has adapter for compatibility but production uses v2 service
- Legacy risk pipeline is available as fallback but production uses new pipeline
- No evidence of legacy code paths being used in production 15m stack

**No critical legacy contamination found.**

---

## 6. 5-Asset Consistency Verification

### Files: Various

**Status:** ✅ All 5 assets consistently included

**Key Findings:**
- Profile YAML includes all 5 assets (BTC, ETH, SOL, XRP, DOGE) with per-asset configurations
- Risk envelope includes all 5 assets in `asset_max_notional_usd` and `asset_depth_thresholds`
- Profile adapter includes all 5 assets with velocity thresholds, OBI thresholds, EWMA alphas
- Unified sizing includes all 5 assets in comments and asset normalization logic
- Agent grid includes all 5 assets (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M)
- Strategy module includes all 5 assets in `CRYPTO_ASSETS` list

**No critical 5-asset consistency issues found.**

---

## 7. Additional Multiplier Risks (Lower Priority)

### Bug #6: Strike Selector Dynamic Multipliers (MEDIUM LEVERAGE)

**Location:** `merid/event_venues/kalshi/strike_selector.py:67-87, 170-178, 233-237`

**Issue:**
- Strike selector defines `VOL_MULTIPLIERS`, `TENOR_MULTIPLIERS`, `REGIME_MULTIPLIERS`
- These multipliers are applied when `dynamic_enabled=True`
- These multipliers affect spot-strike distance checks, not position sizing
- If enabled, could allow strikes at wider distances, indirectly affecting risk

**Impact:**
- Lower priority since this affects strike selection, not position sizing
- Could indirectly affect risk by allowing strikes at wider distances

**Recommendation:**
- Verify that `dynamic_enabled=False` in production (default is False)
- If ever enabled, ensure wider strikes don't bypass risk limits

### Bug #7: Safety Module CQI Multipliers (MEDIUM LEVERAGE)

**Location:** `merid/event_venues/kalshi/market_wiring/safety.py:122-129, 363-369`

**Issue:**
- Safety module defines `_cqi_multipliers` based on data quality bands
- These multipliers reduce effective notional caps based on data quality
- Multipliers range from 1.0 (EXCELLENT) to 0.2 (CRITICAL)
- These multipliers are applied to `max_notional_per_trade`, `max_daily_notional`, `max_open_risk`

**Impact:**
- Lower priority since these are safety reductions, not increases
- Could conflict with window-based limits if not coordinated

**Recommendation:**
- Verify that safety module multipliers don't conflict with window-based limits
- Ensure safety reductions are applied after window limit checks

---

## Summary of Critical Bugs

| Bug # | Description | Location | Severity | Status |
|-------|-------------|----------|----------|--------|
| 1 | Time-of-day scaling inconsistency between agent_grid and unified_sizing | agent_grid_15m.py, unified_sizing.py | HIGH | ✅ FIXED |
| 2 | Legacy position sizer applies multipliers not integrated with window limits | position_sizer.py | HIGH | ✅ VERIFIED (not used in production) |
| 3 | Strike selector dynamic multipliers could bypass risk limits if enabled | strike_selector.py | MEDIUM | Verify disabled |
| 4 | Safety module CQI multipliers could conflict with window limits | safety.py | MEDIUM | Verify coordination |

---

## Recommendations

### Immediate Actions (High Priority)

1. **✅ Fixed Time-of-Day Scaling Inconsistency:**
   - Added `_get_time_of_day_multiplier()` function to unified_sizing.py
   - Function reads from profile YAML (same as agent_grid_15m.py)
   - Currently disabled via `time_of_day_risk_scaling_enabled: false` in YAML
   - When re-enabled, both agent_grid and unified_sizing will use the same profile-driven logic
   - Added safe bounds clamping [0.5, 1.0] to prevent extreme multipliers
   - Documented re-enablement requirements in code comments

2. **✅ Verified Legacy Position Sizer Is Not Used in Production:**
   - Legacy `PositionSizer` is only used in `strategy.py` for legacy Kalshi trading
   - Production 15m stack uses `unified_sizing.py` exclusively (verified in loop_15m.py)
   - Legacy position sizer multipliers (sentiment_vol, cycle_drawdown) do not affect production 15m stack

### Follow-Up Actions (Medium Priority)

3. **Verify Strike Selector Dynamic Multipliers Are Disabled:**
   - Confirm `dynamic_enabled=False` in all production code paths
   - Add validation to prevent enabling without risk envelope integration

4. **Verify Safety Module CQI Multipliers Coordination:**
   - Ensure safety multipliers are applied after window limit checks
   - Add logging to track when safety multipliers reduce positions

### Long-Term Actions

5. **Centralize All Multipliers in Risk Envelope:**
   - Move all sizing multipliers (time-of-day, sentiment/vol, cycle drawdown) into risk envelope
   - Ensure all multipliers are validated against window-based limits
   - Add comprehensive tests for multiplier interactions

6. **Add Integration Tests for Window-Based Limits:**
   - Test that all multipliers respect 3% per agent / 5% total per 15m window limits
   - Test that position closures reduce window exposure correctly
   - Test that rejected orders refund window exposure correctly

---

## Conclusion

The production stack is generally well-architected with clear separation of concerns and a single source of truth (profile YAML). The window-based risk limits (3% per agent, 5% total per 15m window) are correctly implemented and enforced.

However, **2 high-leverage bugs** were identified that could bypass or interfere with window-based risk limits:
1. Time-of-day scaling inconsistency between agent_grid and unified_sizing
2. Legacy position sizer applies multipliers not integrated with window limits

These bugs should be addressed immediately to ensure the integrity of the risk management system.

**Overall Risk Level:** MEDIUM (2 high-leverage bugs identified, but core window-based risk tracking is correct)
