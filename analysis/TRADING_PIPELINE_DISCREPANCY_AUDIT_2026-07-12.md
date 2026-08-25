# Trading Pipeline Discrepancy Audit
**Date**: 2026-07-12  
**Scope**: End-to-end audit of all layers (upstream, midstream, downstream)  
**System**: 15m Kalshi Crypto Trading System (BTC, ETH, SOL, XRP, DOGE)

---

## Executive Summary

This audit identified **significant discrepancies** across the trading pipeline, particularly in:
- **Edge thresholds** (8 different values ranging from 0.5% to 3.5%)
- **Spread thresholds** (4 different values: 10c, 30c, 75c, 100c)
- **Depth thresholds** (5 different values: 1, 5, 20, 25, 100)
- **Confidence thresholds** (4 different values: 0.50, 0.60, 0.65, 0.75)
- **TTE regime thresholds** (inconsistent definitions across 3 files)

**Critical Finding**: The canonical 10-75c price range is well-aligned across most components, but some legacy code still references 10-50c or 5-95c ranges.

---

## 1. Price Range Thresholds

### Canonical Range: 10-75c (Aligned)

**Status**: ✅ **WELL ALIGNED** across most components

| Component | File | Min | Max | Status |
|-----------|------|-----|-----|--------|
| Profile YAML | kalshi_crypto_15m_v2.yaml | 10 | 75 | ✅ Aligned |
| Strategy | prediction/strategy.py | 10 | 75 | ✅ Aligned |
| Agent Grid | prediction/agent_grid_15m.py | 10 | 75 | ✅ Aligned |
| Kalshi Tools | prediction/kalshi_tools.py | 10 | 75 | ✅ Aligned |
| Loop 15m | loop_15m.py | 10 | 75 | ✅ Aligned |
| Risk Parameters | event_venues/kalshi/risk_parameters.py | 10 | 75 | ✅ Aligned |
| Market Filter | event_venues/kalshi/market_filter.py | 10 | 75 | ✅ Aligned |
| Global Slot Allocator | risk/global_slot_allocator.py | 10 | 75 | ✅ Aligned |
| Order Router | event_venues/kalshi/order_router.py | 10 | 75 | ✅ Aligned |
| Dynamic Risk | event_venues/kalshi/dynamic_risk.py | 10 | 75 | ✅ Aligned |
| Execution Pipeline | merid_core/kalshi/execution_pipeline.py | 10 | 75 | ✅ Aligned |
| Intent Schema | merid_core/schemas/intent.py | 10 | 75 | ✅ Aligned |

### ⚠️ DISCREPANCIES FOUND

| Component | File | Min | Max | Issue |
|-----------|------|-----|-----|-------|
| Unified Edge | prediction/unified_edge.py | 10 | **50** | ❌ Uses 50c max (should be 75c) |
| Crisis Regime | event_venues/kalshi/regime_detector.py | 5 | 95 | ⚠️ Crisis regime (separate from canonical) |
| Loop 15m (fallback) | loop_15m.py | - | 50 | ⚠️ Fallback placeholder at 50c |
| Market Filter (fallback) | event_venues/kalshi/market_filter.py | - | 75 | ✅ Correct fallback |

**Recommendation**: Update `prediction/unified_edge.py` line 452 to use 75c max instead of 50c.

---

## 2. Edge Thresholds

### ⚠️ CRITICAL DISCREPANCY: 8 Different Edge Values

| Value | Location | Context | Status |
|-------|----------|---------|--------|
| **0.5%** | unified_edge.py | Distance-based min edge (near expiry) | ⚠️ Very low |
| **1.25%** | trade_hold_config.py | BTC base edge (moltbook research) | ✅ Intentional |
| **1.5%** | unified_edge.py | Distance-based min edge (mid-range) | ⚠️ Different from profile |
| **1.75%** | risk_parameters.py | BTC marketable entry (taker) | ✅ Intentional |
| **2.0%** | Multiple files | Default min edge (industry standard) | ✅ Standard |
| **2.5%** | risk_parameters.py | SOL marketable entry (taker) | ✅ Intentional |
| **3.0%** | risk_parameters.py | XRP marketable entry (taker) | ✅ Intentional |
| **3.5%** | risk_parameters.py | DOGE marketable entry (taker) | ✅ Intentional |

### Per-Asset Edge Thresholds (from risk_parameters.py)

| Asset | Resting (Maker) | Marketable (Taker) | Source |
|-------|-----------------|-------------------|--------|
| BTC | 1.25% | 1.75% | Moltbook research |
| ETH | 1.25% | 2.0% | Profile override |
| SOL | 1.25% | 2.5% | Profile override |
| XRP | 1.25% | 3.0% | Profile override |
| DOGE | 1.25% | 3.5% | Profile override |

### Profile Edge Bands (from kalshi_crypto_15m_v2.yaml)

| Regime | Min Edge | Source |
|-------|----------|--------|
| Early | 1.25% (BTC) | Per-asset override |
| Mid | 1.25% (BTC) | Per-asset override |
| Late | 1.25% (BTC) | Per-asset override |
| Terminal | 1.75% (BTC) | Per-asset override |

**Recommendation**: 
- Document the intentional per-asset differences in a central location
- Consider consolidating the 0.5% and 1.5% distance-based edges into the profile system
- Ensure unified_edge.py respects profile edge bands instead of hardcoded values

---

## 3. Spread Thresholds

### ⚠️ DISCREPANCY: 4 Different Spread Values

| Value | Location | Context | Status |
|-------|----------|---------|--------|
| **10c** | tte_regime.py | Normal regime max spread | ⚠️ Too restrictive |
| **30c** | trade_hold_config.py | Default max spread | ✅ Canonical |
| **30c** | kalshi_crypto_15m_v2.yaml | Canonical spread threshold | ✅ Source of truth |
| **75c** | order_router.py | Microstructure gate fallback | ⚠️ Very loose |
| **75c** | crypto_15m_profile.py | Market microstructure max | ⚠️ Very loose |
| **100c** | kalshi_crypto_15m_v2.yaml | Crisis regime spread | ✅ Intentional (crisis) |

### TTE Regime Spread Thresholds (tte_regime.py)

| Regime | Max Spread | Status |
|--------|-----------|--------|
| Normal | 10c | ⚠️ Too restrictive (should be 30c) |
| Approaching | 8c | ⚠️ Too restrictive |
| Critical | 6c | ⚠️ Too restrictive |
| Terminal | 5c | ⚠️ Too restrictive |

**Recommendation**: 
- Update tte_regime.py to use 30c canonical spread for normal regime
- Consider whether TTE-based spread tightening is still needed with 15m markets
- Document the relationship between canonical spread (30c) and TTE regime spreads

---

## 4. Depth Thresholds

### ⚠️ DISCREPANCY: 5 Different Depth Values

| Value | Location | Context | Status |
|-------|----------|---------|--------|
| **1** | order_router.py | Min YES/NO depth (microstructure) | ✅ Minimal |
| **1** | threshold_config.py | Default min depth | ✅ Minimal |
| **5** | tte_regime.py | Normal regime min depth | ⚠️ Different from profile |
| **5** | trade_hold_config.py | Default min depth | ⚠️ Different from profile |
| **20** | threshold_config.py | Default min depth (from profile) | ✅ Profile default |
| **25** | loop_15m.py | Depth threshold for ready state | ⚠️ Different |
| **100** | loop_15m.py | Depth threshold for ready state (alternative) | ⚠️ Different |

### Profile Depth Thresholds (kalshi_crypto_15m_v2.yaml)

| Tier | Threshold | Context |
|------|-----------|---------|
| High | 200 contracts | High liquidity (BTC 15m) |
| Medium | 80 contracts | Medium liquidity |
| Low | 40 contracts | Low liquidity |
| Ultra Low | 25 contracts | Ultra low liquidity |
| Min | 25 contracts | Minimum threshold |

**Recommendation**:
- Consolidate depth thresholds to use profile tier-based system
- Update tte_regime.py to use profile min_depth_contracts (5) instead of hardcoded 5
- Document the relationship between microstructure depth (1) and profile depth (20+)

---

## 5. Confidence Thresholds

### ⚠️ DISCREPANCY: 4 Different Confidence Values

| Value | Location | Context | Status |
|-------|----------|---------|--------|
| **0.50** | trade_hold_config.py | Min confidence for trade | ⚠️ Too low |
| **0.60** | risk_parameters.py | Min model probability (DEPRECATED) | ⚠️ Deprecated |
| **0.65** | kalshi_crypto_15m_v2.yaml | Primary confidence threshold | ✅ Source of truth |
| **0.75** | risk_parameters.py | Deprecated confidence bands | ⚠️ Deprecated |

### Profile Confidence (kalshi_crypto_15m_v2.yaml)

| Parameter | Value | Status |
|-----------|-------|--------|
| min_confidence_threshold | 0.65 | ✅ Primary threshold |

**Recommendation**:
- Remove deprecated confidence thresholds from risk_parameters.py
- Update trade_hold_config.py to use 0.65 instead of 0.50
- Ensure all code paths use profile min_confidence_threshold (0.65)

---

## 6. Time-to-Expiry (TTE) Regime Thresholds

### ⚠️ CRITICAL DISCREPANCY: Inconsistent Definitions Across 7 Files

| File | Max Entry | Min Entry | Approaching | Critical | Terminal | Status |
|------|-----------|----------|-----------|----------|----------|--------|
| tte_regime.py | - | - | 10.0 min | 5.0 min | 2.0 min | ✅ Primary definition |
| kalshi_crypto_15m_v2.yaml | 15.0 min | 0.5 min | - | - | - | ⚠️ Full 15m window |
| unified_edge.py | 12.0 min | 2.0 min | - | - | - | ⚠️ Uses 12 not 10 |
| order_router.py | 12.0 min | 2.5 min | - | - | - | ⚠️ Uses 12 not 10 |
| agent_grid_15m.py | 15.0 min | 3.0 min | - | - | - | ⚠️ Uses 15 not 10 |
| crypto_15m_profile.py | 15.0 min | 2.0 min | - | - | - | ⚠️ Uses 15 not 10 |
| resting_order_monitor.py | - | - | - | - | 2.0 min | ✅ Aligned for terminal |

### User Intent: Full 15-Minute Window Trading

**User Statement**: "I thought we were supposed to be have the whole 15 min window open except for the last 30s or whatever."

**Current State Analysis**:
- Profile YAML (kalshi_crypto_15m_v2.yaml) is configured for **full 15m window trading**:
  - `max_entry_mins: 15.0` (entire 15-minute duration)
  - `min_entry_mins: 0.5` (only last 30 seconds blocked)
  - `cutoff_minutes_before_expiry: 0` (no hard cutoff)
  - `min_decision_minute: 0` for all assets (start trading immediately)

- However, **TTE regime definitions** (tte_regime.py) use a **different model**:
  - Approaching: < 10 minutes (tightens constraints)
  - Critical: < 5 minutes (very tight constraints)
  - Terminal: < 2 minutes (blocks entry)

- **Code inconsistencies**:
  - `unified_edge.py` uses 12.0 min max entry (not 10 or 15)
  - `order_router.py` uses 12.0 min max entry (not 10 or 15)
  - `agent_grid_15m.py` uses 15.0 min max entry (matches profile)
  - `crypto_15m_profile.py` uses 15.0 min max entry (matches profile)

### The Conflict: Two Different TTE Models

**Model A: Full Window Trading (Profile YAML)**
- Trade entire 15-minute window (0 to 15 minutes to expiry)
- Only block last 30 seconds (min_entry_mins: 0.5)
- No regime-based tightening
- Used by: Profile YAML, agent_grid_15m.py, crypto_15m_profile.py

**Model B: Regime-Based Tightening (tte_regime.py)**
- Normal: > 10 minutes (full constraints)
- Approaching: 5-10 minutes (tighter constraints)
- Critical: 2-5 minutes (very tight constraints)
- Terminal: < 2 minutes (block entry)
- Used by: tte_regime.py, unified_edge.py, order_router.py

### Discrepancy Summary

| Component | Model Used | Max Entry | Min Entry | Status |
|-----------|-----------|-----------|-----------|--------|
| Profile YAML | Full Window | 15.0 min | 0.5 min | ✅ User intent |
| agent_grid_15m.py | Full Window | 15.0 min | 3.0 min | ⚠️ Min too high |
| crypto_15m_profile.py | Full Window | 15.0 min | 2.0 min | ⚠️ Min too high |
| unified_edge.py | Mixed | 12.0 min | 2.0 min | ❌ Wrong max |
| order_router.py | Mixed | 12.0 min | 2.5 min | ❌ Wrong max |
| tte_regime.py | Regime-Based | - | - | ⚠️ Different model |

### TTE Regime Edge Multipliers (tte_regime.py)

| Regime | Edge Multiplier | Size Multiplier | Spread Multiplier |
|--------|---------------|----------------|------------------|
| Normal | 1.0x | 1.0x | 1.0x |
| Approaching | 1.2x | 1.0x | 0.8x |
| Critical | 1.5x | 1.0x | 0.6x |
| Terminal | 2.0x | 0.25x | 0.5x |

**Recommendation**:
- **DECISION NEEDED**: Choose between two models:
  - **Option A (User Intent)**: Full 15-minute window trading (0-15 min, block last 30s only)
    - Disable TTE regime-based tightening for 15m markets
    - Update all components to use profile max_entry_mins: 15.0, min_entry_mins: 0.5
    - Update agent_grid_15m.py min_entry from 3.0 to 0.5
    - Update crypto_15m_profile.py min_entry from 2.0 to 0.5
    - Update unified_edge.py max_entry from 12.0 to 15.0, min_entry from 2.0 to 0.5
    - Update order_router.py max_entry from 12.0 to 15.0, min_entry from 2.5 to 0.5
  
  - **Option B (Current Implementation)**: Regime-based tightening
    - Keep tte_regime.py approach (approaching at 10min, critical at 5min, terminal at 2min)
    - Update unified_edge.py to use 10.0 min (not 12.0)
    - Update order_router.py to use 10.0 min (not 12.0)
    - Document that TTE regime tightening is intentional for risk management

- **RECOMMENDATION**: Option A (User Intent) - Full 15-minute window trading
  - Profile YAML is already configured for this (max_entry_mins: 15.0, min_entry_mins: 0.5)
  - TTE regime-based tightening was designed for longer-term markets, not 15-minute binaries
  - For 15-minute markets, the entire window is the "normal" regime

---

## 7. Duplicate Detection Windows

### ✅ WELL ALIGNED

| Component | Window | Context | Status |
|-----------|--------|---------|--------|
| order_router.py | 5s | Duplicate order detection | ✅ Aligned with 5s cadence |
| order_gate.py | 60s | Price repeat detection | ✅ Allows legitimate re-execution |

**Historical Context** (from memory):
- 2026-07-12: Reduced from 60s to 5s (order_router) to fix 65% rejection rate
- 2026-07-12: Reduced from 900s to 60s (order_gate) to allow legitimate re-execution

**Status**: ✅ No discrepancies found

---

## 8. Risk Exposure Limits

### ✅ FIXED $1 EXPOSURE CAP (Aligned)

| Component | Cap | Status |
|-----------|-----|--------|
| Global Slot Allocator | $1.00 MAX_EXPOSURE_USD | ✅ Aligned |
| Unified Risk Manager | $1.00 correlated_stack_max_usd | ✅ Aligned |
| Profile YAML | Fixed $1 model (percentage-based disabled) | ✅ Aligned |

### Percentage-Based Limits (DISABLED in Production)

| Limit | Value | Status |
|-------|-------|--------|
| max_cycle_risk_pct | 0.0 (disabled) | ✅ Disabled for fixed $1 model |
| max_total_risk_pct | 0.0 (disabled) | ✅ Disabled for fixed $1 model |
| venue_max_total_notional_pct | 0.0 (disabled) | ✅ Disabled for fixed $1 model |

**Status**: ✅ Well aligned with fixed $1 exposure model

---

## 9. Velocity Thresholds (Per-Asset)

### ✅ WELL ALIGNED (Profile-Driven)

| Asset | Threshold | Profile YAML | Code Default | Status |
|-------|-----------|-------------|-------------|--------|
| BTC | 0.00015 (0.015%) | ✅ | ✅ | ✅ Aligned |
| ETH | 0.00015 (0.015%) | ✅ | ✅ | ✅ Aligned |
| SOL | 0.000225 (0.0225%) | ✅ | ✅ | ✅ Aligned |
| XRP | 0.000225 (0.0225%) | ✅ | ✅ | ✅ Aligned |
| DOGE | 0.0003 (0.03%) | ✅ | ✅ | ✅ Aligned |

**Status**: ✅ No discrepancies found

---

## 10. WebSocket and Infrastructure Thresholds

### ⚠️ DISCREPANCIES: Multiple Lag Thresholds

| Component | Threshold | Context | Status |
|-----------|-----------|---------|--------|
| ws.py | 6000ms | Reconnect lag threshold | ⚠️ May be too aggressive |
| ws.py | 30000ms | Lag warn threshold | ✅ Reasonable |
| ws_bridge.py | 60s | Dead threshold | ✅ Reasonable |
| ws_bridge.py | 30s | Stale threshold | ✅ Reasonable |

### WebSocket Queue Thresholds

| Component | Threshold | Context | Status |
|-----------|-----------|---------|--------|
| ws_bridge.py | 5000 | Queue warn threshold | ✅ Reasonable |
| ws_bridge.py | 200 | Queue hard limit (deprecated) | ⚠️ Increased to 5000 |

**Recommendation**:
- Consider whether 6000ms reconnect threshold is too aggressive for production
- Document the relationship between reconnect lag (6000ms) and warn lag (30000ms)

---

## 11. Order Rate Limits

### ✅ WELL ALIGNED

| Component | Per Minute | Per Hour | Status |
|-----------|-----------|----------|--------|
| order_router.py | 30 | 300 | ✅ Aligned |
| Profile YAML | 30 | 300 | ✅ Source of truth |
| Unified Risk Manager | 20 | - | ⚠️ Different (20/hour) |

**Recommendation**: 
- Update unified_risk_manager.py to use 30/hour to match profile
- Or document why 20/hour is used in risk manager vs 30/hour in profile

---

## 12. Test File Consistency

### ✅ MOSTLY ALIGNED

| Test File | Price Range | Duplicate Window | Status |
|-----------|-------------|------------------|--------|
| test_ratchet_profile_loading.py | 10-75c | - | ✅ Aligned |
| test_kalshi_audit_fixes.py | 10-75c | - | ✅ Aligned |
| test_entry_price_band_fix.py | 10-75c | - | ✅ Aligned |
| test_robustness_fixes_2026.py | - | 5s, 60s | ✅ Aligned |
| test_edge_threshold_consistency.py | - | - | ✅ Aligned |
| test_edge_threshold_alignment.py | - | - | ✅ Aligned |

**Status**: ✅ Test files are well-aligned with production code

---

## 13. Critical Discrepancies Summary

### HIGH PRIORITY FIXES

1. **unified_edge.py line 452**: Uses 50c max instead of 75c
   - Impact: May reject valid 60-75c candidates
   - Fix: Change `max_price_cents = 50` to `max_price_cents = 75`

2. **tte_regime.py spread thresholds**: Uses 10c instead of 30c canonical
   - Impact: Overly restrictive spread filtering
   - Fix: Update normal_max_spread_cents from 10 to 30

3. **tte_regime.py approaching threshold**: Uses 12.0 min instead of 10.0 min
   - Impact: Inconsistent TTE regime definitions
   - Fix: Update unified_edge.py to use 10.0 min

4. **trade_hold_config.py confidence**: Uses 0.50 instead of 0.65
   - Impact: May allow low-confidence trades
   - Fix: Update min_confidence from 0.50 to 0.65

5. **unified_risk_manager.py rate limit**: Uses 20/hour instead of 30/hour
   - Impact: More restrictive than profile
   - Fix: Update rate_limit_max_trades_per_hour from 20 to 30

### MEDIUM PRIORITY FIXES

6. **Depth threshold consolidation**: Multiple values (1, 5, 20, 25, 100)
   - Impact: Inconsistent depth filtering across components
   - Fix: Consolidate to use profile tier-based system

7. **Edge threshold documentation**: 8 different values without central documentation
   - Impact: Confusion about which edge threshold to use
   - Fix: Document intentional per-asset differences in central location

8. **WebSocket lag threshold**: 6000ms may be too aggressive
   - Impact: Frequent reconnections during normal operation
   - Fix: Consider increasing to 10000ms or document rationale

---

## 14. Recommendations

### Immediate Actions (Within 24 Hours)

1. Fix unified_edge.py max_price_cents (50 → 75)
2. Fix tte_regime.py normal_max_spread_cents (10 → 30)
3. Fix trade_hold_config.py min_confidence (0.50 → 0.65)
4. Fix unified_risk_manager.py rate_limit (20 → 30)

### Short-Term Actions (Within 1 Week)

5. Consolidate depth thresholds to use profile tier-based system
6. Standardize TTE thresholds across all files
7. Document intentional per-asset edge differences
8. Review WebSocket lag threshold appropriateness

### Long-Term Actions (Within 1 Month)

9. Create central threshold configuration registry
10. Implement threshold validation tests
11. Add threshold change audit trail
12. Document threshold rationale in code comments

---

## 15. Conclusion

The trading pipeline is **generally well-aligned** for critical parameters:
- ✅ Price range (10-75c) is consistent across most components
- ✅ Duplicate detection windows are properly aligned
- ✅ Fixed $1 exposure cap is enforced consistently
- ✅ Velocity thresholds are profile-driven and consistent

However, **significant discrepancies exist** in:
- ⚠️ Edge thresholds (8 different values)
- ⚠️ Spread thresholds (4 different values)
- ⚠️ Depth thresholds (5 different values)
- ⚠️ Confidence thresholds (4 different values)
- ⚠️ TTE regime thresholds (inconsistent definitions)

**Overall Assessment**: The system is functional but would benefit from threshold consolidation and better documentation to prevent future drift.

---

## Appendix A: Files Audited

### Prediction Layer
- merid/prediction/strategy.py
- merid/prediction/agent_grid_15m.py
- merid/prediction/kalshi_tools.py
- merid/prediction/unified_edge.py
- merid/prediction/trade_hold_config.py
- merid/prediction/tiered_profit_config.py
- merid/prediction/universal_agent.py
- merid/prediction/unified_sizing.py

### Execution Layer
- merid/loop_15m.py
- merid/event_venues/kalshi/order_router.py
- merid/event_venues/kalshi/order_gate.py
- merid/event_venues/kalshi/resting_order_monitor.py
- merid/event_venues/kalshi/maker_taker_integration.py
- merid/event_venues/kalshi/dynamic_risk.py
- merid_core/kalshi/execution_pipeline.py
- merid_core/schemas/intent.py

### Risk Layer
- merid/risk/global_slot_allocator.py
- merid/risk/unified_risk_manager.py
- merid/risk/tte_regime.py
- merid/risk/profiles/crypto_15m_profile.py
- merid/risk/profiles/window_audit.py
- merid/event_venues/kalshi/risk_parameters.py
- merid/event_venues/kalshi/kalshi_risk.py
- merid/event_venues/kalshi/market_filter.py
- merid/event_venues/kalshi/threshold_config.py
- merid/event_venues/kalshi/regime_detector.py
- merid/event_venues/kalshi/dynamic_thresholds.py
- merid/event_venues/kalshi/invariants.py

### Configuration
- config/profiles/kalshi_crypto_15m_v2.yaml

### Infrastructure
- merid/event_venues/kalshi/ws.py
- merid/event_venues/kalshi/ws_bridge.py
- merid/event_venues/kalshi/timestamp_manager.py
- merid/event_venues/kalshi/timeout_config.py

### Test Files
- tests/test_ratchet_profile_loading.py
- tests/test_kalshi_audit_fixes.py
- tests/test_entry_price_band_fix.py
- tests/test_robustness_fixes_2026.py
- tests/test_edge_threshold_consistency.py
- tests/test_edge_threshold_alignment.py

---

## Appendix B: Threshold Registry (Proposed)

A proposed central threshold registry to prevent future drift:

```yaml
# proposed: config/thresholds_registry.yaml
canonical:
  price_range:
    min_cents: 10
    max_cents: 75
  spread:
    normal_cents: 30
    crisis_cents: 100
  depth:
    minimal: 1
    profile_default: 20
  confidence:
    primary: 0.65
  
per_asset:
  BTC:
    edge_resting_pct: 0.0125
    edge_marketable_pct: 0.0175
  ETH:
    edge_resting_pct: 0.0125
    edge_marketable_pct: 0.02
  SOL:
    edge_resting_pct: 0.0125
    edge_marketable_pct: 0.025
  XRP:
    edge_resting_pct: 0.0125
    edge_marketable_pct: 0.03
  DOGE:
    edge_resting_pct: 0.0125
    edge_marketable_pct: 0.035

tte_regime:
  approaching_min: 10.0
  critical_min: 5.0
  terminal_min: 2.0

duplicate_detection:
  order_window_seconds: 5
  price_repeat_window_seconds: 60

risk_limits:
  fixed_exposure_cap_usd: 1.00
```

---

**Audit Completed**: 2026-07-12  
**Auditor**: Cascade AI System  
**Next Review**: 2026-08-12 (30 days)
