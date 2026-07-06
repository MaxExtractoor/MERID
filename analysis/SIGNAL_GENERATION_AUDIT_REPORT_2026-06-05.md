# Signal Generation Audit Report
**Date:** 2026-06-05  
**Scope:** End-to-end audit of signal generation across all layers (upstream, midstream, downstream) and all assets (BTC, ETH, SOL, XRP, DOGE)  
**Objective:** Identify high-leverage bugs, discrepancies, mismatches, and misalignments within the stack

---

## Executive Summary

This audit identified **7 high-leverage discrepancies** across the signal generation stack, with **2 critical issues** that could materially impact trading behavior. The most significant finding is a **signal_mode mismatch** between the agent grid and the single source of truth profile, which could cause the system to use the wrong signal generation strategy.

---

## Critical Findings

### 1. CRITICAL: signal_mode Mismatch Between Agent Grid and Profile

**Location:** 
- `config/kalshi_agent_grid.yaml` (lines 34, 70, 107, 139, 177)
- `config/profiles/kalshi_crypto_15m_v2.yaml` (line 133)

**Issue:**
- `kalshi_agent_grid.yaml` specifies `signal_mode: mean_reversion` for all 5 assets (BTC, ETH, SOL, XRP, DOGE)
- `kalshi_crypto_15m_v2.yaml` (the declared "SINGLE SOURCE OF TRUTH") specifies `signal_mode: momentum_fvg`
- The profile YAML was changed from `trend` to `momentum_fvg` on 2026-07-05 based on Turbine research
- The agent grid was not updated to reflect this change

**Impact:**
- The system may be using `mean_reversion` mode instead of the intended `momentum_fvg` mode
- This represents a fundamental strategy mismatch that could explain poor performance
- The override mechanism between agent grid and profile is unclear

**Recommendation:**
- Update `kalshi_agent_grid.yaml` to specify `signal_mode: momentum_fvg` for all assets
- OR remove `signal_mode` from agent grid entirely if the profile is truly the single source of truth
- Document the override hierarchy clearly (which config takes precedence)

---

### 2. CRITICAL: max_spot_to_strike_pct vs max_distance_pct Scale Mismatch

**Location:**
- `config/kalshi_agent_grid.yaml` (lines 50, 87, 142, 179)
- `config/profiles/kalshi_crypto_15m_v2.yaml` (lines 671, 700, 729, 758, 787)

**Issue:**
- `kalshi_agent_grid.yaml` uses `max_spot_to_strike_pct` with values: 15% for BTC/ETH, 20% for XRP/DOGE
- `kalshi_crypto_15m_v2.yaml` uses `max_distance_pct` with values: 1.5% for BTC, 1.8% for ETH, 2.5% for SOL/XRP/DOGE
- These are **completely different scales** (15-20% vs 1.5-2.5%)
- The parameter names suggest different calculations (spot-to-strike ratio vs distance percentage)

**Impact:**
- Unclear which threshold is actually enforced
- If both are checked, the tighter profile values (1.5-2.5%) would dominate
- If only agent grid is checked, the profile values are dead code
- Potential for confusion about which filter is active

**Recommendation:**
- Clarify the relationship between these two parameters
- If they represent the same concept, unify them to a single source of truth
- If they represent different concepts, document the difference clearly
- Ensure the tighter threshold (profile) is actually enforced if that's the intent

---

## High-Severity Findings

### 3. min_edge Values Inconsistent Across Configs

**Location:**
- `config/kalshi_agent_grid.yaml` (lines 29-32, 66-69, 103-106, 135-138, 173-176)
- `config/profiles/kalshi_crypto_15m_v2.yaml` (lines 666-669, 695-698, 724-727, 753-756, 782-785, 839-850)

**Issue:**
- `kalshi_agent_grid.yaml` has uniform min_edge: 2% early/mid/late, 2.5% terminal for all assets
- `kalshi_crypto_15m_v2.yaml` has per-asset min_edge:
  - BTC/ETH: 3% early/mid/late, 4% terminal
  - SOL/XRP: 4% early/mid/late, 5% terminal
  - DOGE: 5% early/mid/late, 6% terminal
- Profile YAML states: "CRITICAL: Edge bands are the ACTUAL thresholds used (per-asset min_edge fields are ignored)"
- Edge bands define: 0.8% watch, 1.5% small, 3% standard minimum edges

**Impact:**
- Three different edge threshold systems exist (agent grid, per-asset profile, edge bands)
- Unclear which is actually enforced
- The comment suggests per-asset min_edge fields are ignored, but they're still present
- Potential for dead code or misconfiguration

**Recommendation:**
- Remove dead min_edge fields from profile YAML if edge bands are the single source of truth
- Update agent grid to match the actual enforced thresholds
- Document the edge band hierarchy clearly
- Verify which thresholds are actually used in signal generation code

---

### 4. dynamic_sizing Multiplier Mismatch

**Location:**
- `config/profiles/kalshi_crypto_15m_v2.yaml` (lines 242-243)
- `merid/risk/profiles/crypto_15m_profile.py` (lines 335-336, 994-995)

**Issue:**
- Profile YAML specifies: `edge_multiplier: 2.0`, `confidence_multiplier: 1.0`
- Profile adapter defaults: `edge_multiplier: 0.5`, `confidence_multiplier: 0.3`
- The adapter loads from YAML but has different defaults if YAML values are missing

**Impact:**
- If YAML loading fails or values are missing, the adapter uses much lower multipliers
- This could cause dynamic sizing to be under-activated
- The discrepancy between YAML (2.0/1.0) and defaults (0.5/0.3) is significant (4x and 3.3x difference)

**Recommendation:**
- Ensure YAML values are always loaded correctly
- Update adapter defaults to match YAML values to prevent silent failures
- Add validation to warn if YAML values differ significantly from expected ranges

---

### 5. max_cycle_risk_pct Comment vs Value Mismatch

**Location:**
- `config/profiles/kalshi_crypto_15m_v2.yaml` (lines 397-403)
- `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py` (lines 342-347)

**Issue:**
- Profile YAML comment says: "0.5% per cycle for 5-second HFT"
- Profile YAML value is: `value: 0.05` (5%, not 0.5%)
- Risk envelope code expects 0.5% and has a "CRITICAL FIX" comment aligning to 0.5%
- The YAML value (5%) matches the "5% per 15m window limit" mentioned in the comment

**Impact:**
- Comment is misleading (says 0.5% but value is 5%)
- Risk envelope code may be overriding the YAML value with 0.5%
- Unclear whether the intended value is 0.5% or 5%

**Recommendation:**
- Clarify the intended value (0.5% for HFT cycles or 5% for 15m windows)
- Update the comment to match the actual value
- Ensure risk envelope code respects the YAML value without silent override
- If 5% is correct, remove the "CRITICAL FIX" comment in risk envelope that aligns to 0.5%

---

### 6. per_trade_risk_pct Bankroll Tiering Complexity

**Location:**
- `config/profiles/kalshi_crypto_15m_v2.yaml` (lines 941-950)
- `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py` (lines 512-516)

**Issue:**
- Profile YAML specifies bankroll-tiered per_trade_risk_pct: 2.75% for <$100, 2% for $100-$1k, 2% for >$1k
- Risk envelope code has a "CRITICAL FIX" comment aligning to 2% (was 0.8%)
- The code may not be implementing the tiered logic correctly
- The adapter defaults to 2% if YAML loading fails

**Impact:**
- Small bankrolls (<$100) may not get the intended 2.75% risk
- Complex tiering logic may have bugs
- If tiering fails, all accounts get 2% regardless of bankroll

**Recommendation:**
- Verify the tiered logic is actually implemented in risk envelope computation
- Add logging to confirm which tier is active for a given bankroll
- Test with small bankrolls (<$100) to verify 2.75% is applied
- Simplify to a single value if tiering is not working correctly

---

### 7. max_contracts Inconsistency

**Location:**
- `config/profiles/kalshi_crypto_15m_v2.yaml` (lines 660-661, 689-690, 718-719, 747-748, 776-777, 1040)
- `config/profiles/kalshi_crypto_15m_v2.yaml` (line 244 - dynamic_sizing max_contracts)

**Issue:**
- Per-asset max_contracts: BTC=3, ETH=3, SOL=3, XRP=3, DOGE=2
- Dynamic sizing max_contracts: 3
- Global max_single_order_contracts: 2 (failsafe mode)
- Multiple sources for max contracts without clear hierarchy

**Impact:**
- Unclear which limit is actually enforced
- DOGE has 2 in per-asset but dynamic sizing allows 3
- Failsafe mode has 2 which may conflict with per-asset values
- Potential for confusion about sizing limits

**Recommendation:**
- Establish clear hierarchy: per-asset > dynamic > global failsafe
- Ensure DOGE's per-asset limit of 2 is respected even if dynamic sizing allows 3
- Document which limit applies in which scenario
- Consider unifying to a single max_contracts per asset

---

## Medium-Severity Findings

### 8. Disabled Features with Potential Impact

**Location:**
- `config/profiles/kalshi_crypto_15m_v2.yaml` (lines 558, 1334)
- `merid/prediction/unified_sizing.py` (lines 79-82, 142-143)

**Issue:**
- `time_of_day_risk_scaling.enabled: false` - interferes with 3% per asset limits
- `fee_aware_edge.enabled: false` - disabled for price-based strategy
- Regime sizing DISABLED in unified_sizing.py (returns 1.0)
- TTE sizing DISABLED in unified_sizing.py (returns 1.0)

**Impact:**
- These features are disabled to prevent interference with risk limits
- If re-enabled without updating risk envelope, could cause oversizing
- Dead code that could be confusing for future developers

**Recommendation:**
- Document why these are disabled and the risks of re-enabling
- Consider removing dead code if it will never be used
- Add warnings if someone tries to re-enable without updating risk envelope

---

### 9. Depth Threshold Complexity

**Location:**
- `config/profiles/kalshi_crypto_15m_v2.yaml` (lines 681-682, 710-711, 739-740, 768-769, 797-798, 907-910)

**Issue:**
- Per-asset min_depth_yes/min_depth_no: all set to 1
- Tier-based depth thresholds: tier1=2, tier2=1
- Comment says "CRITICAL FIX: Set to 1 contract since we only trade 1 contract per 15m window"
- Guardrails section says "min_depth_usd: 0.0 DISABLED"

**Impact:**
- Multiple depth threshold systems exist
- Tier-based thresholds may override per-asset values
- Unclear which is actually enforced

**Recommendation:**
- Unify to a single depth threshold system
- Remove tier-based thresholds if per-asset values are the source of truth
- Clarify whether depth checks are actually performed (min_depth_usd: 0.0 suggests no)

---

## Low-Severity Findings

### 10. Volatility Regime Edge Adjustment Enabled in Profile but Disabled in Adapter

**Location:**
- `config/profiles/kalshi_crypto_15m_v2.yaml` (line 528)
- `merid/risk/profiles/crypto_15m_profile.py` (line 387)

**Issue:**
- Profile YAML: `volatility_regime_edge_adjustment.enabled: true`
- Profile adapter default: `volatility_regime_edge_adjustment_enabled: bool = False`

**Impact:**
- If YAML loading fails, feature is disabled by default
- Could cause inconsistent behavior

**Recommendation:**
- Update adapter default to match YAML (True)
- Add validation to warn if feature is disabled when YAML says enabled

---

## Cross-Asset Consistency Check

### Asset Tiering
- **Tier 1 (BTC, ETH):** Lower min_edge (3-4%), lower max_distance (1.5-1.8%), higher max_contracts (3)
- **Tier 2 (SOL, XRP, DOGE):** Higher min_edge (4-6%), higher max_distance (2.5%), lower max_contracts (2-3)
- **Rationale:** Consistent with volatility differences (BTC/ETH more stable, alts more volatile)

### Velocity Thresholds
- All assets have identical velocity_threshold: 0.00001 (effectively zero)
- This is intentional to enable trading in calm markets
- **Consistent across all 5 assets** ✓

### Velocity Model Alpha
- BTC/ETH: alpha_1 = 200.0
- SOL/XRP: alpha_1 = 300.0
- DOGE: alpha_1 = 500.0
- **Progressive sensitivity by volatility** ✓

### Min Decision Minute
- BTC/ETH: 2 minutes
- SOL/XRP: 3 minutes
- DOGE: 5 minutes
- **Longer wait for thinner books** ✓

### Max Notional Percentage
- All assets: 3% of capital
- **Consistent risk allocation** ✓

---

## Configuration Hierarchy Analysis

The audit revealed unclear configuration hierarchy:

1. **kalshi_crypto_15m_v2.yaml** - Declared as "SINGLE SOURCE OF TRUTH"
2. **kalshi_agent_grid.yaml** - Contains agent-specific overrides
3. **crypto_15m_profile.py** - Adapter that loads and validates profile
4. **kalshi_crypto_15m_risk_envelope.py** - Computes risk envelope from profile
5. **unified_sizing.py** - Uses profile for sizing decisions

**Issues:**
- Agent grid contains values that conflict with profile (signal_mode, min_edge, max_spot_to_strike_pct)
- Unclear override mechanism (which config takes precedence?)
- Profile adapter has defaults that differ from YAML values
- Risk envelope has "CRITICAL FIX" comments suggesting it overrides profile values

**Recommendation:**
- Document clear configuration hierarchy
- Implement validation to detect conflicts between configs
- Consider removing agent grid overrides if profile is truly the single source of truth
- Add warnings when defaults are used instead of YAML values

---

## Recommendations Summary

### Immediate Actions (Critical)
1. **Fix signal_mode mismatch** - Update agent grid to match profile (momentum_fvg)
2. **Resolve max_spot_to_strike_pct vs max_distance_pct** - Unify to single source of truth

### High Priority
3. **Clean up min_edge fields** - Remove dead per-asset min_edge if edge bands are used
4. **Align dynamic_sizing defaults** - Update adapter defaults to match YAML values
5. **Clarify max_cycle_risk_pct** - Fix comment or value to match (0.5% vs 5%)
6. **Verify bankroll tiering logic** - Test with small bankrolls to confirm 2.75% is applied
7. **Unify max_contracts hierarchy** - Establish clear precedence rules

### Medium Priority
8. **Document disabled features** - Add clear warnings about risks of re-enabling
9. **Simplify depth thresholds** - Remove redundant tier-based system
10. **Fix volatility regime default** - Update adapter default to match YAML

### Low Priority
11. **Add config validation** - Detect conflicts between configs at startup
12. **Improve logging** - Log which configuration values are actually used
13. **Remove dead code** - Clean up unused fields and parameters

---

## Conclusion

The signal generation stack has **solid cross-asset consistency** for most parameters (velocity thresholds, max notional, tier-based differentiation). However, there are **critical configuration conflicts** between the agent grid and the profile YAML that could cause the system to use incorrect signal generation strategies.

The most urgent issue is the **signal_mode mismatch** (mean_reversion vs momentum_fvg), which represents a fundamental strategy difference. The second most urgent is the **max_spot_to_strike_pct vs max_distance_pct scale mismatch**, which could cause confusion about which distance filter is actually enforced.

Overall, the stack would benefit from:
1. Clearer configuration hierarchy documentation
2. Removal of dead/unused configuration fields
3. Validation to detect config conflicts at startup
4. Alignment of defaults with YAML values to prevent silent failures
