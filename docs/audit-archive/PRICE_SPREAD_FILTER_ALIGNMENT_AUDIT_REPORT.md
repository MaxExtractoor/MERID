# Price and Spread Filter Alignment Audit Report

**Date**: 2026-07-11  
**Objective**: Ensure consistency across all price and spread-related filters and parameters within the Kalshi 15m crypto trading system  
**Scope**: Profile YAML, risk parameters, candidate_optimizer, order_router, agent_grid, universe, market_filter, and test files

---

## Executive Summary

This audit identified **critical inconsistencies** between the single source of truth (profile YAML) and various components across the production stack. The primary issues are:

1. **Price range discrepancy**: Profile YAML specifies 5-95 cents (expanded for skewed markets), but multiple components use outdated 10-50 cents fallback values
2. **Spread threshold discrepancy**: Profile YAML specifies 100 cents (relaxed for current market conditions), but multiple components use outdated 30 cents or 75 cents values
3. **Test file inconsistencies**: Many test files assert outdated values, creating false positives/negatives

**Recommended Action**: Update all components to use profile-driven values consistently, with appropriate fallbacks that match the profile defaults.

---

## Target Configuration (Single Source of Truth)

### Profile YAML: `config/profiles/kalshi_crypto_15m_v2.yaml`

```yaml
price_range:
  min_price_cents: 5  # 2026-07-10: Lower bound of expanded range (5-95c) for skewed markets
  max_price_cents: 95  # 2026-07-10: Upper bound of expanded range (5-95c) for skewed markets

guardrails:
  max_spread_cents: 100  # 2026-07-10: RELAXED to 100c - allows trading in current market conditions with wider spreads (60c-96c observed)
  min_contract_price_cents: 5  # 2026-07-10: Lower bound of expanded range (5-95c) for skewed markets
  max_contract_price_cents: 95  # 2026-07-10: Upper bound of expanded range (5-95c) for skewed markets
  min_spread_gate_cents: 30  # 2026-07-10: OPTIMIZED to 30c - harmonizes with 10c-50c entry price sweet spot

market_microstructure:
  enabled: true
  max_spread_cents: 100  # 2026-07-10: RELAXED to 100c - aligned with guardrails.max_spread_cents (single source of truth)
  min_depth_usd: 0.0  # DISABLED: System uses limit orders which wait for fills

universe:
  max_spread_cents: 30  # OUTDATED: Should be 100 to align with guardrails
```

### Risk Parameters: `merid/event_venues/kalshi/risk_parameters.py`

```python
DEEP_OTM_CHEAP_CENTS: Final[int] = 5  # 2026-07-10: Lower bound of expanded range (5-95c) for skewed markets
DEEP_OTM_EXPENSIVE_CENTS: Final[int] = 95  # 2026-07-10: Upper bound of expanded range (5-95c) for skewed markets
MIN_OPEN_PRICE_CENTS: Final[int] = 2
MAX_OPEN_PRICE_CENTS: Final[int] = 50  # 2026-07-08: Upper bound of sweet spot (10-50c)
```

**Status**: ✅ Aligned with profile YAML for DEEP_OTM thresholds  
**Note**: MAX_OPEN_PRICE_CENTS (50c) is for order placement limits, not entry price filtering

---

## Critical Discrepancies

### 1. Price Range Inconsistencies (5-95c vs 10-50c)

| Component | Current Value | Expected Value | Status | File |
|-----------|---------------|----------------|--------|------|
| Profile YAML (price_range) | 5-95c | 5-95c | ✅ Correct | config/profiles/kalshi_crypto_15m_v2.yaml |
| Profile YAML (guardrails) | 5-95c | 5-95c | ✅ Correct | config/profiles/kalshi_crypto_15m_v2.yaml |
| Risk parameters (DEEP_OTM) | 5-95c | 5-95c | ✅ Correct | merid/event_venues/kalshi/risk_parameters.py |
| Profile adapter defaults | 5-95c | 5-95c | ✅ Correct | merid/risk/profiles/crypto_15m_profile.py |
| Agent grid fallback | 10-50c | 5-95c | ❌ OUTDATED | merid/prediction/agent_grid_15m.py:10261-10263 |
| Global allocator defaults | 10-50c | 5-95c | ❌ OUTDATED | merid/risk/profiles/global_allocator.py:77-78 |
| Loop_15m pre-send assertion | 10-50c | 5-95c | ❌ OUTDATED | merid/loop_15m.py:3980-3981 |
| Global execution guard | 10-50c | 5-95c | ❌ OUTDATED | merid/guards/global_execution_guard.py:214-218 |
| Window audit defaults | 10-50c | 5-95c | ❌ OUTDATED | merid/risk/profiles/window_audit.py:214-216 |
| Market filter defaults | 10-70c | 5-95c | ❌ OUTDATED | merid/event_venues/kalshi/market_filter.py (DEFAULT_FILTER_CONFIG) |

**Impact**: Agent grid and execution components may reject valid 5-9c or 51-95c entries that the profile allows, reducing trading opportunities in skewed market conditions.

**Recommended Fix**: Update all fallback values to 5-95c to match profile YAML.

---

### 2. Spread Threshold Inconsistencies (100c vs 30c/75c)

| Component | Current Value | Expected Value | Status | File |
|-----------|---------------|----------------|--------|------|
| Profile YAML (guardrails.max_spread_cents) | 100c | 100c | ✅ Correct | config/profiles/kalshi_crypto_15m_v2.yaml |
| Profile YAML (market_microstructure.max_spread_cents) | 100c | 100c | ✅ Correct | config/profiles/kalshi_crypto_15m_v2.yaml |
| Profile YAML (universe.max_spread_cents) | 30c | 100c | ❌ OUTDATED | config/profiles/kalshi_crypto_15m_v2.yaml |
| Profile YAML (min_spread_gate_cents) | 30c | 30c | ✅ Correct (edge-dependent) | config/profiles/kalshi_crypto_15m_v2.yaml |
| CandidateOptimizer hardcoded | 75c | 100c (from profile) | ❌ OUTDATED | merid/prediction/candidate_optimizer.py:100 |
| CandidateOptimizer profile loading | Profile-driven | Profile-driven | ✅ Correct | merid/prediction/candidate_optimizer.py:110 |
| Universe config | Profile-driven | Profile-driven | ✅ Correct | merid/event_venues/kalshi/universe.py:69 |
| Market filter config | Profile-driven | Profile-driven | ✅ Correct | merid/event_venues/kalshi/market_filter.py |
| Order router default | Profile-driven | Profile-driven | ✅ Correct | merid/event_venues/kalshi/order_router.py |
| SpreadOptimizer MAX_SPREAD_CENTS | 30c | 100c | ❌ OUTDATED | merid/prediction/spread_optimizer.py |

**Impact**: 
- Universe filter may reject markets with 31-100c spreads that guardrails allow
- CandidateOptimizer hardcoded 75c may override profile value in some code paths
- SpreadOptimizer may reject valid spreads that profile allows

**Recommended Fix**: 
1. Update profile YAML universe.max_spread_cents to 100c
2. Remove hardcoded 75c in CandidateOptimizer
3. Update SpreadOptimizer to use profile value

---

### 3. Test File Inconsistencies

Many test files assert outdated values, creating false positives/negatives:

#### Tests expecting 30c spread (should be 100c):
- `tests/test_15m_optimization_regression.py:123` - asserts guardrails.max_spread_cents == 30
- `tests/test_depth_population_fix.py:45` - mock profile uses 30c
- `tests/test_diagnostic_script_fixes.py:348,353` - asserts 30c for guardrails and universe
- `tests/test_dynamic_spread_threshold.py:285` - asserts config.max_spread_cents == 30
- `tests/test_fine_tuning_fixes_20260702.py:157,170` - uses 30c in test calls
- `tests/test_pass2_signal_generation_fixes.py:35,72` - LeanAgentConfig uses 30c
- `tests/test_phase1_strategy_improvements.py:244,292` - asserts 30c
- `tests/test_profile_yaml_config_source.py:72` - mock profile uses 30c
- `tests/test_structural_fixes.py:188` - asserts optimizer.max_spread_cents == 30
- `tests/test_unified_edge_fixes.py:300` - asserts computer.max_spread_cents == 30
- `tests/test_velocity_threshold_fix.py:181,194,201` - asserts 30c
- `tests/test_execution_audit_regressions.py:441,463` - uses 30c in test config
- `tests/test_crypto_threshold_matrix_v2.py:350,351` - uses 30c
- `tests/test_2026_spread_threshold_fixes.py:91,107` - uses 30c in test calls
- `tests/prediction/test_spread_optimizer.py:33` - asserts MAX_SPREAD_CENTS == 30
- `tests/prediction/test_candidate_optimizer.py:371` - comment references 30c

#### Tests expecting 100c spread (correct):
- `tests/test_kalshi_audit_fixes.py:590,601,735,744,753,770,776,786,797,916,964` - correctly asserts 100c
- `tests/test_agent_grid_15m_integration.py:1459,1461` - correctly asserts 100c
- `tests/test_2026_stack_optimizations.py:613,630` - correctly asserts 100c

#### Tests expecting 10-50c price range (should be 5-95c):
- `tests/test_entry_price_band_fix.py:28,44,59,94,96` - asserts 10-50c
- `tests/test_ratchet_profile_loading.py:113,115,143,144` - asserts 10-50c
- `tests/event_venues/kalshi/test_kalshi_market_filter.py:237,247` - asserts 10-70c
- `tests/event_venues/kalshi/test_order_constraints.py:538` - uses 10c custom limit

#### Tests expecting 5-95c price range (correct):
- `tests/test_crypto_15m_profile_fixes.py:236,254,278` - correctly asserts 5-95c
- `tests/test_kalshi_audit_fixes.py:816,830,849,868,940` - correctly asserts 5-95c
- `tests/test_price_filtering_consistency.py:29,40,54,67,102,154,171` - correctly asserts 5-95c

**Impact**: Tests with outdated assertions will fail when code is corrected, blocking deployment.

**Recommended Fix**: Update all test assertions to match profile YAML values (5-95c price range, 100c spread threshold).

---

## Detailed Component Analysis

### Upstream Layer (Profile YAML, Risk Envelope, Configuration)

#### Profile YAML: `config/profiles/kalshi_crypto_15m_v2.yaml`
- **price_range**: ✅ 5-95c (correct)
- **guardrails.max_spread_cents**: ✅ 100c (correct)
- **guardrails.min_contract_price_cents**: ✅ 5c (correct)
- **guardrails.max_contract_price_cents**: ✅ 95c (correct)
- **guardrails.min_spread_gate_cents**: ✅ 30c (correct - edge-dependent)
- **market_microstructure.max_spread_cents**: ✅ 100c (correct)
- **universe.max_spread_cents**: ❌ 30c (should be 100c)

**Fix Required**: Update universe.max_spread_cents from 30c to 100c

#### Risk Parameters: `merid/event_venues/kalshi/risk_parameters.py`
- **DEEP_OTM_CHEAP_CENTS**: ✅ 5c (correct)
- **DEEP_OTM_EXPENSIVE_CENTS**: ✅ 95c (correct)
- **MIN_OPEN_PRICE_CENTS**: ✅ 2c (correct - dust floor)
- **MAX_OPEN_PRICE_CENTS**: ✅ 50c (correct - order placement limit, not entry price)

**Status**: No changes required

#### Profile Adapter: `merid/risk/profiles/crypto_15m_profile.py`
- **price_range defaults**: ✅ 5-95c (correct)
- **guardrails defaults**: ✅ 5-95c (correct)
- **universe defaults**: Profile-driven (correct)

**Status**: No changes required

---

### Midstream Layer (Agent Grid, Candidate Optimizer, Order Router)

#### Agent Grid: `merid/prediction/agent_grid_15m.py`
- **Profile loading**: ✅ Loads from profile (lines 10249-10253)
- **Fallback values**: ❌ 10-50c (lines 10261-10263, 10269-10271)
- **Comment**: ❌ References "Profile YAML: kalshi_crypto_15m_v2.yaml price_range [10, 50]" (line 10259)

**Fix Required**: Update fallback values from 10-50c to 5-95c, update comment

#### Candidate Optimizer: `merid/prediction/candidate_optimizer.py`
- **Profile loading**: ✅ Loads from profile (line 110)
- **Hardcoded value**: ❌ 75c (line 100)
- **Comment**: ❌ "Canonical spread filter (75c)" (line 100)

**Fix Required**: Remove hardcoded 75c, ensure profile value is always used

#### Order Router: `merid/event_venues/kalshi/order_router.py`
- **check_market_microstructure default**: Profile-driven (correct)
- **Profile loading**: Should use profile value (needs verification)

**Status**: Likely correct, needs runtime verification

---

### Downstream Layer (Market Catalog, Market State, Execution)

#### Market Catalog: `merid/event_venues/kalshi/market_catalog.py`
- **Price filtering**: Uses market_filter config (delegated)
- **Spread filtering**: Uses universe config (delegated)

**Status**: Delegates to other components, no direct discrepancies

#### Market State: `merid/event_venues/kalshi/market_state.py`
- **Price/spread thresholds**: Not applicable (state storage only)

**Status**: No discrepancies

#### Execution Components:
- **Position cache**: Uses profile guardrails (correct)
- **Dynamic risk**: Uses profile guardrails (correct)
- **Execution diagnostics**: No price/spread thresholds (correct)

**Status**: No discrepancies

---

### Test Files

See "Test File Inconsistencies" section above for detailed list.

**Recommended Fix**: Batch update all test assertions to match profile YAML values.

---

## Recommended Actions

### Priority 1: Critical Configuration Fixes

1. **Update profile YAML universe.max_spread_cents**
   - File: `config/profiles/kalshi_crypto_15m_v2.yaml`
   - Change: `universe.max_spread_cents: 30` → `universe.max_spread_cents: 100`
   - Rationale: Align with guardrails.max_spread_cents (single source of truth)

2. **Update agent grid fallback values**
   - File: `merid/prediction/agent_grid_15m.py`
   - Change: Lines 10261-10263, 10269-10271
   - From: `ENTRY_MIN_PRICE_CENTS = 10`, `ENTRY_MAX_PRICE_CENTS = 50`
   - To: `ENTRY_MIN_PRICE_CENTS = 5`, `ENTRY_MAX_PRICE_CENTS = 95`
   - Also update comment on line 10259

3. **Update global allocator defaults**
   - File: `merid/risk/profiles/global_allocator.py`
   - Change: Lines 77-78, 302-303
   - From: `min_price_cents = 10`, `max_price_cents = 50`
   - To: `min_price_cents = 5`, `max_price_cents = 95`

4. **Update loop_15m pre-send assertion**
   - File: `merid/loop_15m.py`
   - Change: Line 3980-3981
   - From: `if not (10 <= price_cents <= 50)`
   - To: `if not (5 <= price_cents <= 95)`

5. **Update global execution guard**
   - File: `merid/guards/global_execution_guard.py`
   - Change: Lines 214-218
   - From: `min_price_cents = 10`, `max_price_cents = 50`
   - To: `min_price_cents = 5`, `max_price_cents = 95`

6. **Update window audit defaults**
   - File: `merid/risk/profiles/window_audit.py`
   - Change: Lines 214-216
   - From: `min_price_cents = 10`, `max_price_cents = 50`
   - To: `min_price_cents = 5`, `max_price_cents = 95`

7. **Remove CandidateOptimizer hardcoded spread**
   - File: `merid/prediction/candidate_optimizer.py`
   - Change: Line 100
   - From: `self.max_spread_cents = 75  # 2026-07-11: Canonical spread filter (75c)`
   - To: Remove line, ensure profile value is always used via line 110

8. **Update SpreadOptimizer**
   - File: `merid/prediction/spread_optimizer.py`
   - Change: MAX_SPREAD_CENTS constant
   - From: `MAX_SPREAD_CENTS = 30`
   - To: Load from profile or set to 100

### Priority 2: Test File Updates

9. **Update all test assertions for spread threshold**
   - Change all assertions expecting 30c to 100c
   - Files: See "Test File Inconsistencies" section

10. **Update all test assertions for price range**
    - Change all assertions expecting 10-50c to 5-95c
    - Files: See "Test File Inconsistencies" section

### Priority 3: Documentation Updates

11. **Update inline comments**
    - Remove references to "10-50c sweet spot" where outdated
    - Update to "5-95c expanded range for skewed markets"

12. **Update audit documentation**
    - Update TRADING_CONDITIONS_AUDIT.md with current values
    - Update any other documentation with outdated values

---

## Verification Checklist

After implementing fixes, verify:

- [ ] Profile YAML has consistent values across all sections
- [ ] All components load from profile YAML (no hardcoded magic numbers)
- [ ] Fallback values match profile defaults
- [ ] All test assertions pass with updated values
- [ ] Runtime verification: Start production stack and log actual values used
- [ ] Cross-reference: No component uses 10-50c or 30c where 5-95c or 100c is expected

---

## Conclusion

The audit revealed significant inconsistencies between the profile YAML (single source of truth) and various components across the stack. The primary issues are:

1. **Price range**: Profile specifies 5-95c, but many components use 10-50c
2. **Spread threshold**: Profile specifies 100c, but many components use 30c or 75c
3. **Test files**: Many tests assert outdated values

These discrepancies can cause:
- Reduced trading opportunities (rejecting valid entries)
- Test failures blocking deployment
- Confusion about actual system behavior

Implementing the recommended fixes will ensure consistency across all layers and align the system with the intended configuration for skewed market conditions.
