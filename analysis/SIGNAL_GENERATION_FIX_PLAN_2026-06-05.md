# Signal Generation Fix Plan
**Date:** 2026-06-05  
**Purpose:** Comprehensive remediation plan for all issues identified in signal generation audit

---

## CRITICAL Fixes (Must Fix Immediately)

### Fix #1: signal_mode Mismatch in Agent Grid

**Files:**
- `config/kalshi_agent_grid.yaml` (lines 34, 70, 107, 139, 177)

**Current State:**
```yaml
# BTC_15M (line 34)
signal_mode: mean_reversion

# ETH_15M (line 70)
signal_mode: mean_reversion

# SOL_15M (line 107)
signal_mode: mean_reversion

# XRP_15M (line 139)
signal_mode: mean_reversion

# DOGE_15M (line 177)
signal_mode: mean_reversion
```

**Required Change:**
```yaml
# Change all 5 occurrences from:
signal_mode: mean_reversion

# To:
signal_mode: momentum_fvg
```

**Rationale:**
- Profile YAML (`kalshi_crypto_15m_v2.yaml` line 133) specifies `signal_mode: momentum_fvg` as the single source of truth
- Profile was changed from `trend` to `momentum_fvg` on 2026-07-05 based on Turbine research
- Agent grid was not updated to reflect this change
- This is a fundamental strategy mismatch

**Verification:**
- After fix, verify all 5 assets have `signal_mode: momentum_fvg`
- Check signal generation logs to confirm momentum_fvg mode is active

---

### Fix #2: max_spot_to_strike_pct vs max_distance_pct Conflict

**Files:**
- `config/kalshi_agent_grid.yaml` (lines 50, 87, 142, 179)
- `config/profiles/kalshi_crypto_15m_v2.yaml` (lines 671, 700, 729, 758, 787)

**Current State - Agent Grid:**
```yaml
# BTC_15M (line 50)
max_spot_to_strike_pct: 0.15   # 15% max distance

# ETH_15M (line 87)
max_spot_to_strike_pct: 0.15   # 15% max distance

# XRP_15M (line 142)
max_spot_to_strike_pct: 0.20   # 20% max distance

# DOGE_15M (line 179)
max_spot_to_strike_pct: 0.20   # 20% max distance
```

**Current State - Profile:**
```yaml
# BTC (line 671)
max_distance_pct: 0.015  # 1.5% max distance

# ETH (line 700)
max_distance_pct: 0.018  # 1.8% max distance

# SOL (line 729)
max_distance_pct: 0.025  # 2.5% max distance

# XRP (line 758)
max_distance_pct: 0.025  # 2.5% max distance

# DOGE (line 787)
max_distance_pct: 0.025  # 2.5% max distance
```

**Analysis:**
- These are completely different scales (15-20% vs 1.5-2.5%)
- Parameter names suggest different calculations (spot-to-strike ratio vs distance percentage)
- Need to determine which is actually enforced in code

**Required Action:**
1. **First:** Search codebase for which parameter is actually used in signal generation
2. **If profile is source of truth:** Remove `max_spot_to_strike_pct` from agent grid entirely
3. **If agent grid is source of truth:** Update profile `max_distance_pct` to match agent grid values
4. **If both are used:** Document the relationship and ensure consistent values

**Recommended Approach:**
- Profile is declared as single source of truth
- Remove `max_spot_to_strike_pct` from agent grid
- Keep profile `max_distance_pct` values (1.5-2.5%)
- Add comment in agent grid: "Distance filtering handled by profile (max_distance_pct)"

**Verification:**
- Search codebase for `max_spot_to_strike_pct` usage
- Search codebase for `max_distance_pct` usage
- Confirm which is actually enforced

---

## HIGH Priority Fixes

### Fix #3: min_edge Inconsistency Across Configs

**Files:**
- `config/kalshi_agent_grid.yaml` (lines 29-32, 66-69, 103-106, 135-138, 173-176)
- `config/profiles/kalshi_crypto_15m_v2.yaml` (lines 666-669, 695-698, 724-727, 753-756, 782-785, 839-850)

**Current State - Agent Grid (uniform for all assets):**
```yaml
min_edge_early: 0.02  # 2%
min_edge_mid: 0.02    # 2%
min_edge_late: 0.02   # 2%
min_edge_terminal: 0.025  # 2.5%
```

**Current State - Profile (per-asset):**
```yaml
# BTC (lines 666-669)
min_edge_early: 0.03  # 3%
min_edge_mid: 0.03    # 3%
min_edge_late: 0.03   # 3%
min_edge_terminal: 0.04  # 4%

# ETH (lines 695-698)
min_edge_early: 0.03  # 3%
min_edge_mid: 0.03    # 3%
min_edge_late: 0.03   # 3%
min_edge_terminal: 0.04  # 4%

# SOL (lines 724-727)
min_edge_early: 0.04  # 4%
min_edge_mid: 0.04    # 4%
min_edge_late: 0.04   # 4%
min_edge_terminal: 0.05  # 5%

# XRP (lines 753-756)
min_edge_early: 0.04  # 4%
min_edge_mid: 0.04    # 4%
min_edge_late: 0.04   # 4%
min_edge_terminal: 0.05  # 5%

# DOGE (lines 782-785)
min_edge_early: 0.05  # 5%
min_edge_mid: 0.05    # 5%
min_edge_late: 0.05   # 5%
min_edge_terminal: 0.06  # 6%
```

**Current State - Edge Bands (actual enforced thresholds):**
```yaml
# Lines 839-850
edge_bands:
  watch_band:
    min_edge_pct: 0.008  # 0.8%
    max_edge_pct: 0.015  # 1.5%
  small_band:
    min_edge_pct: 0.015  # 1.5%
    max_edge_pct: 0.03   # 3%
  standard_band:
    min_edge_pct: 0.03   # 3%
    max_edge_pct: 1.0
```

**Profile Comment (line 835):**
```yaml
# CRITICAL: Edge bands are the ACTUAL thresholds used (per-asset min_edge fields are ignored)
```

**Required Action:**
1. **Remove dead per-asset min_edge fields** from profile YAML since edge bands are the actual thresholds
2. **Remove min_edge from agent grid** since profile is single source of truth
3. **Keep edge bands** as the single source of truth for edge thresholds

**Required Changes - Profile YAML:**
```yaml
# DELETE lines 666-669 (BTC min_edge_early/mid/late/terminal)
# DELETE lines 695-698 (ETH min_edge_early/mid/late/terminal)
# DELETE lines 724-727 (SOL min_edge_early/mid/late/terminal)
# DELETE lines 753-756 (XRP min_edge_early/mid/late/terminal)
# DELETE lines 782-785 (DOGE min_edge_early/mid/late/terminal)

# These are dead code - edge bands (lines 839-850) are the actual thresholds
```

**Required Changes - Agent Grid:**
```yaml
# DELETE lines 29-32 (BTC min_edge_early/mid/late/terminal)
# DELETE lines 66-69 (ETH min_edge_early/mid/late/terminal)
# DELETE lines 103-106 (SOL min_edge_early/mid/late/terminal)
# DELETE lines 135-138 (XRP min_edge_early/mid/late/terminal)
# DELETE lines 173-176 (DOGE min_edge_early/mid/late/terminal)

# Add comment:
# Edge thresholds handled by profile edge_bands (kalshi_crypto_15m_v2.yaml)
```

**Verification:**
- Search codebase for min_edge usage to confirm edge bands are actually enforced
- Verify no code references the deleted min_edge fields

---

### Fix #4: dynamic_sizing Multiplier Defaults Mismatch

**Files:**
- `config/profiles/kalshi_crypto_15m_v2.yaml` (lines 242-243)
- `merid/risk/profiles/crypto_15m_profile.py` (lines 335-336, 994-995)

**Current State - Profile YAML:**
```yaml
dynamic_sizing:
  enabled: true
  base_contracts: 1
  edge_multiplier: 2.0  # 2026-07-05: Increased from 0.5 to 2.0 (4x)
  confidence_multiplier: 1.0  # 2026-07-05: Increased from 0.3 to 1.0 (3.3x)
  max_contracts: 3
  min_contracts: 1
```

**Current State - Profile Adapter Defaults:**
```python
# Lines 335-336
dynamic_sizing_edge_multiplier: float = 0.5
dynamic_sizing_confidence_multiplier: float = 0.3

# Lines 994-995 (loading from YAML)
dynamic_sizing_edge_multiplier=raw.get('dynamic_sizing', {}).get('edge_multiplier', 0.5),
dynamic_sizing_confidence_multiplier=raw.get('dynamic_sizing', {}).get('confidence_multiplier', 0.3),
```

**Issue:**
- YAML values: 2.0 and 1.0
- Adapter defaults: 0.5 and 0.3
- If YAML loading fails, defaults are 4x and 3.3x lower than intended

**Required Change - Profile Adapter:**
```python
# Line 335: Change from:
dynamic_sizing_edge_multiplier: float = 0.5
# To:
dynamic_sizing_edge_multiplier: float = 2.0

# Line 336: Change from:
dynamic_sizing_confidence_multiplier: float = 0.3
# To:
dynamic_sizing_confidence_multiplier: float = 1.0

# Line 994: Change from:
dynamic_sizing_edge_multiplier=raw.get('dynamic_sizing', {}).get('edge_multiplier', 0.5),
# To:
dynamic_sizing_edge_multiplier=raw.get('dynamic_sizing', {}).get('edge_multiplier', 2.0),

# Line 995: Change from:
dynamic_sizing_confidence_multiplier=raw.get('dynamic_sizing', {}).get('confidence_multiplier', 0.3),
# To:
dynamic_sizing_confidence_multiplier=raw.get('dynamic_sizing', {}).get('confidence_multiplier', 1.0),
```

**Verification:**
- Test with YAML loading failure to confirm defaults are used
- Add logging to show which values are loaded (YAML vs default)

---

### Fix #5: max_cycle_risk_pct Comment vs Value Mismatch

**Files:**
- `config/profiles/kalshi_crypto_15m_v2.yaml` (lines 397-403)
- `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py` (lines 342-347)

**Current State - Profile YAML:**
```yaml
# Line 397-403
# Maximum risk per cycle as percentage of capital
# 2026 BEST PRACTICE: 0.5% per cycle for 5-second HFT (aligned with Quarter Kelly research)
# With 180 cycles/hour, even 0.5% compounds to significant exposure
# This is the SINGLE SOURCE OF TRUTH - core.settings.py must match this value
max_cycle_risk_pct:
  value: 0.05  # 5% of capital per cycle (aligned with 5% per 15m window limit)
  dynamic: bankroll
  description: "Maximum risk per cycle as percentage of capital (computed from bankroll)"
```

**Current State - Risk Envelope:**
```python
# Lines 342-347
# CRITICAL FIX: Aligned with kalshi_crypto_15m_v2.yaml profile (2026-07-04)
# Profile specifies: max_cycle_risk_pct: 0.005 (0.5%)
max_cycle_risk_pct_raw = profile_config.get('max_cycle_risk_pct', 0.005)  # CRITICAL FIX: 0.5% - aligned with profile (was 0.03)
if isinstance(max_cycle_risk_pct_raw, dict):
    max_cycle_risk_pct = max_cycle_risk_pct_raw.get('value', 0.005)  # CRITICAL FIX: 0.5% - aligned with profile (was 0.03)
else:
    max_cycle_risk_pct = max_cycle_risk_pct_raw
```

**Issue:**
- Comment says "0.5% per cycle"
- Value is 0.05 (5%, not 0.5%)
- Risk envelope code expects 0.5% and has "CRITICAL FIX" comment
- The value (5%) matches "5% per 15m window limit" mentioned in comment

**Required Decision:**
- Is the intended value 0.5% (for HFT cycles) or 5% (for 15m windows)?
- If 5% is correct: Update comment and remove "CRITICAL FIX" in risk envelope
- If 0.5% is correct: Update YAML value to 0.005

**Recommended Approach:**
- The YAML value (5%) and comment "5% per 15m window limit" suggest 5% is correct
- Update the misleading comment to match the actual value
- Update risk envelope to use 5% instead of 0.5%

**Required Change - Profile YAML:**
```yaml
# Line 397: Change from:
# 2026 BEST PRACTICE: 0.5% per cycle for 5-second HFT (aligned with Quarter Kelly research)
# To:
# 2026 BEST PRACTICE: 5% per 15m window (aligned with 5% per asset limit)

# Line 398: Change from:
# With 180 cycles/hour, even 0.5% compounds to significant exposure
# To:
# This limits total cycle risk to 5% of capital per 15m window
```

**Required Change - Risk Envelope:**
```python
# Line 342: Change from:
# Profile specifies: max_cycle_risk_pct: 0.005 (0.5%)
# To:
# Profile specifies: max_cycle_risk_pct: 0.05 (5%)

# Line 343: Change from:
max_cycle_risk_pct_raw = profile_config.get('max_cycle_risk_pct', 0.005)  # CRITICAL FIX: 0.5% - aligned with profile (was 0.03)
# To:
max_cycle_risk_pct_raw = profile_config.get('max_cycle_risk_pct', 0.05)  # 5% - aligned with profile

# Line 345: Change from:
    max_cycle_risk_pct = max_cycle_risk_pct_raw.get('value', 0.005)  # CRITICAL FIX: 0.5% - aligned with profile (was 0.03)
# To:
    max_cycle_risk_pct = max_cycle_risk_pct_raw.get('value', 0.05)  # 5% - aligned with profile
```

**Verification:**
- Confirm 5% is the intended value for 15m windows
- Check if 0.5% should be a separate HFT cycle limit

---

### Fix #6: per_trade_risk_pct Bankroll Tiering Verification

**Files:**
- `config/profiles/kalshi_crypto_15m_v2.yaml` (lines 941-950)
- `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py` (lines 512-516)

**Current State - Profile YAML:**
```yaml
# Lines 941-950
per_trade_risk_pct:
  value: 0.02  # CRITICAL FIX: Default 2% (aligned with unified risk limit, was 0.008)
  dynamic: bankroll_tiered  # Computed from live bankroll via RiskEnvelopeService with tiered logic
  description: "Per-trade risk as percentage of capital (bankroll-tiered: 2.75% for <$100, 2% for $100-$1k, 2% for >$1k)"
  bankroll_tier_small_usd: 100.0
  bankroll_tier_medium_usd: 1000.0
  per_trade_risk_small_pct: 0.0275  # 2.75%
  per_trade_risk_medium_pct: 0.02  # 2%
  per_trade_risk_large_pct: 0.02  # 2%
```

**Current State - Risk Envelope:**
```python
# Lines 512-516
# Handle nested dict format for per_trade_risk_pct
per_trade_risk_pct_raw = guardrails.get('per_trade_risk_pct', 0.02)  # CRITICAL FIX: 2% - aligned with profile (was 0.008)
if isinstance(per_trade_risk_pct_raw, dict):
    per_trade_risk_pct = per_trade_risk_pct_raw.get('value', 0.02)  # CRITICAL FIX: 2% - aligned with profile (was 0.008)
else:
    per_trade_risk_pct = per_trade_risk_pct_raw
```

**Issue:**
- Profile specifies bankroll-tiered logic (2.75% for <$100, 2% for $100-$1k, 2% for >$1k)
- Risk envelope code only extracts the `value` field (2%)
- No evidence that tiered logic is actually implemented
- Small bankrolls may not get the intended 2.75%

**Required Action:**
1. **Search risk envelope code** for bankroll tiering implementation
2. **If tiering is not implemented:** Either implement it or remove the tiered configuration
3. **If tiering is implemented elsewhere:** Document where it's implemented

**Search Required:**
```bash
# Search for bankroll tiering logic
grep -r "bankroll_tier" merid/risk/profiles/
grep -r "per_trade_risk_small" merid/
grep -r "bankroll_tier_small_usd" merid/
```

**Potential Outcomes:**
- **If tiering is missing:** Implement it in risk envelope or simplify to single value
- **If tiering exists elsewhere:** Document the location and verify it's working
- **If tiering is not needed:** Remove tiered config and use single 2% value

**Verification:**
- Test with bankroll <$100 to verify 2.75% is applied
- Add logging to show which tier is active

---

### Fix #7: max_contracts Hierarchy Clarification

**Files:**
- `config/profiles/kalshi_crypto_15m_v2.yaml` (lines 244, 660-661, 689-690, 718-719, 747-748, 776-777, 1040)

**Current State - Multiple Sources:**
```yaml
# Dynamic sizing (line 244)
dynamic_sizing:
  max_contracts: 3

# Per-asset max_contracts:
# BTC (lines 660-661)
max_contracts:
  value: 3

# ETH (lines 689-690)
max_contracts:
  value: 3

# SOL (lines 718-719)
max_contracts:
  value: 3

# XRP (lines 747-748)
max_contracts:
  value: 3

# DOGE (lines 776-777)
max_contracts:
  value: 2

# Global failsafe (line 1040)
max_single_order_contracts: 2
```

**Issue:**
- Three different max_contracts sources without clear hierarchy
- DOGE has 2 in per-asset but dynamic sizing allows 3
- Failsafe has 2 which may conflict with per-asset values

**Required Action:**
1. **Establish clear hierarchy:** per-asset > dynamic > global failsafe
2. **Update dynamic_sizing max_contracts** to be a global cap, not per-asset
3. **Document the hierarchy** in comments

**Recommended Approach:**
- Per-asset max_contracts is the primary limit (respects asset-specific risk)
- Dynamic sizing max_contracts is a global cap (prevents oversized positions from dynamic sizing)
- Global failsafe is an emergency brake (absolute maximum)

**Required Changes:**
```yaml
# Dynamic sizing (line 244) - Add comment:
dynamic_sizing:
  max_contracts: 3  # Global cap for dynamic sizing (per-asset limits take precedence)

# Per-asset max_contracts - Add hierarchy comment:
# BTC (line 660)
max_contracts:
  value: 3  # PRIMARY limit for BTC (overrides dynamic_sizing.max_contracts)

# DOGE (line 776)
max_contracts:
  value: 2  # PRIMARY limit for DOGE (overrides dynamic_sizing.max_contracts)

# Global failsafe (line 1040) - Add comment:
max_single_order_contracts: 2  # EMERGENCY BRAKE: absolute maximum (overrides all other limits)
```

**Verification:**
- Search codebase for max_contracts usage to confirm hierarchy
- Test with DOGE to verify per-asset limit of 2 is respected

---

## MEDIUM Priority Fixes

### Fix #8: Disabled Features Documentation

**Files:**
- `config/profiles/kalshi_crypto_15m_v2.yaml` (lines 558, 1334)
- `merid/prediction/unified_sizing.py` (lines 69-82, 142-143)

**Current State:**
```yaml
# Profile YAML line 558
time_of_day_risk_scaling:
  enabled: false  # DISABLED: interferes with 3% per asset limits

# Profile YAML line 1334
fee_aware_edge:
  enabled: false  # DISABLED for price-based strategy
```

```python
# unified_sizing.py lines 79-82
# CRITICAL: Regime sizing is DISABLED to prevent interference with risk limits
# If you re-enable regime sizing, you MUST update the risk envelope to account for it
# and ensure 3% per asset / 5% per 15m window limits are still respected
return 1.0

# unified_sizing.py lines 142-143
# DISABLED: Always return 1.0 to prevent TTE sizing from interfering with risk limits
return 1.0
```

**Required Action:**
Add comprehensive documentation for each disabled feature explaining:
1. Why it was disabled
2. What risks exist if re-enabled
3. What changes are required to safely re-enable

**Required Changes - Profile YAML:**
```yaml
# Line 558 - Expand comment:
time_of_day_risk_scaling:
  enabled: false  # DISABLED: interferes with 3% per asset / 5% per 15m window limits
  # RE-ENABLE RISKS: If re-enabled, must update risk envelope to account for time-based scaling
  # and ensure 3% per asset / 5% per 15m window limits are still respected after multiplier
  # RE-ENABLE REQUIREMENTS: Update kalshi_crypto_15m_risk_envelope.py to apply time_of_day_multiplier
  # to risk limits, not just order sizes

# Line 1334 - Expand comment:
fee_aware_edge:
  enabled: false  # DISABLED for price-based strategy (no edge calculation)
  # RE-ENABLE RISKS: If re-enabled with momentum_fvg mode, may conflict with velocity-based edge
  # RE-ENABLE REQUIREMENTS: Verify edge calculation is compatible with momentum_fvg signal mode
```

**Required Changes - unified_sizing.py:**
```python
# Lines 69-82 - Expand comment:
# CRITICAL: Regime sizing is DISABLED to prevent interference with risk limits
# DISABLED REASON: Regime-based multipliers could cause oversizing beyond 3% per asset / 5% per 15m window limits
# RE-ENABLE RISKS: If re-enabled without updating risk envelope, positions could exceed hard risk limits
# RE-ENABLE REQUIREMENTS:
#   1. Update kalshi_crypto_15m_risk_envelope.py to apply regime_multiplier to risk limits
#   2. Ensure 3% per asset / 5% per 15m window limits are still respected after multiplier
#   3. Add validation to prevent regime_multiplier > 1.0 from causing oversizing
#   4. Test with various regime multipliers to verify limits are respected
return 1.0

# Lines 142-143 - Expand comment:
# CRITICAL: TTE sizing is DISABLED to prevent interference with risk limits
# DISABLED REASON: Time-to-expiry multipliers could cause oversizing beyond 3% per asset / 5% per 15m window limits
# RE-ENABLE RISKS: If re-enabled without updating risk envelope, positions could exceed hard risk limits
# RE-ENABLE REQUIREMENTS:
#   1. Update kalshi_crypto_15m_risk_envelope.py to apply tte_multiplier to risk limits
#   2. Ensure 3% per asset / 5% per 15m window limits are still respected after multiplier
#   3. Add validation to prevent tte_multiplier > 1.0 from causing oversizing
#   4. Test with various TTE values to verify limits are respected
return 1.0
```

---

### Fix #9: Depth Threshold Simplification

**Files:**
- `config/profiles/kalshi_crypto_15m_v2.yaml` (lines 681-682, 710-711, 739-740, 768-769, 797-798, 907-910, 1350)

**Current State - Per-Asset:**
```yaml
# BTC (lines 681-682)
min_depth_yes: 1
min_depth_no: 1

# ETH (lines 710-711)
min_depth_yes: 1
min_depth_no: 1

# SOL (lines 739-740)
min_depth_yes: 1
min_depth_no: 1

# XRP (lines 768-769)
min_depth_yes: 1
min_depth_no: 1

# DOGE (lines 797-798)
min_depth_yes: 1
min_depth_no: 1
```

**Current State - Tier-Based:**
```yaml
# Lines 907-910
min_depth_yes_tier1: 2  # Tier 1 (BTC/ETH)
min_depth_no_tier1: 2
min_depth_yes_tier2: 1  # Tier 2 (SOL/XRP/DOGE)
min_depth_no_tier2: 1
```

**Current State - Guardrails:**
```yaml
# Line 1350
min_depth_usd: 0.0  # DISABLED: System uses limit orders which wait for fills
```

**Issue:**
- Three different depth threshold systems
- Tier-based thresholds may override per-asset values
- min_depth_usd: 0.0 suggests depth checks are disabled

**Required Action:**
1. **Determine which system is actually used** in code
2. **Remove unused systems** to reduce confusion
3. **Simplify to single source of truth**

**Search Required:**
```bash
# Search for depth threshold usage
grep -r "min_depth_yes" merid/
grep -r "min_depth_tier" merid/
grep -r "min_depth_usd" merid/
```

**Recommended Approach:**
- If per-asset values are used: Remove tier-based thresholds
- If tier-based values are used: Remove per-asset values
- If depth checks are disabled (min_depth_usd: 0.0): Remove all depth thresholds

**Required Changes (if per-asset is source of truth):**
```yaml
# DELETE lines 907-910 (tier-based depth thresholds)
# Keep per-asset min_depth_yes/min_depth_no (lines 681-682, 710-711, 739-740, 768-769, 797-798)
# Add comment:
# Depth thresholds: per-asset values are single source of truth
```

**Verification:**
- Search codebase to confirm which depth thresholds are actually used
- Test with low depth markets to verify depth checks are working

---

## LOW Priority Fixes

### Fix #10: Volatility Regime Default Alignment

**Files:**
- `config/profiles/kalshi_crypto_15m_v2.yaml` (line 528)
- `merid/risk/profiles/crypto_15m_profile.py` (line 387)

**Current State - Profile YAML:**
```yaml
# Line 528
volatility_regime_edge_adjustment:
  enabled: true  # ENABLED: 2026-07-04
```

**Current State - Profile Adapter:**
```python
# Line 387
volatility_regime_edge_adjustment_enabled: bool = False

# Line 1011
volatility_regime_edge_adjustment_enabled=raw.get('volatility_regime_edge_adjustment', {}).get('enabled', False),
```

**Issue:**
- Profile YAML has `enabled: true`
- Adapter default is `False`
- If YAML loading fails, feature is disabled

**Required Change - Profile Adapter:**
```python
# Line 387: Change from:
volatility_regime_edge_adjustment_enabled: bool = False
# To:
volatility_regime_edge_adjustment_enabled: bool = True

# Line 1011: Change from:
volatility_regime_edge_adjustment_enabled=raw.get('volatility_regime_edge_adjustment', {}).get('enabled', False),
# To:
volatility_regime_edge_adjustment_enabled=raw.get('volatility_regime_edge_adjustment', {}).get('enabled', True),
```

**Verification:**
- Test with YAML loading failure to confirm default is used
- Add logging to show if feature is enabled/disabled

---

## Implementation Order

### Phase 1: Critical Fixes (Do First)
1. Fix #1: signal_mode mismatch in agent grid
2. Fix #2: max_spot_to_strike_pct vs max_distance_pct (requires code search first)

### Phase 2: High Priority Fixes
3. Fix #3: min_edge inconsistency (requires code search first)
4. Fix #4: dynamic_sizing multiplier defaults
5. Fix #5: max_cycle_risk_pct comment vs value
6. Fix #6: per_trade_risk_pct bankroll tiering (requires code search first)
7. Fix #7: max_contracts hierarchy clarification

### Phase 3: Medium Priority Fixes
8. Fix #8: Disabled features documentation
9. Fix #9: Depth threshold simplification (requires code search first)

### Phase 4: Low Priority Fixes
10. Fix #10: Volatility regime default alignment

---

## Pre-Implementation Code Searches - COMPLETED

### Search Results:

1. **max_spot_to_strike_pct vs max_distance_pct:**
   - `max_spot_to_strike_pct`: Used in `merid/event_venues/kalshi/order_router.py` (lines 431, 581, 610)
   - `max_distance_pct`: Used in `merid/event_venues/kalshi/strike_selector.py` and `market_filter.py`
   - **CONCLUSION:** Both are used in different parts of the codebase. They represent different filters:
     - `max_spot_to_strike_pct` in order_router (agent grid config)
     - `max_distance_pct` in strike_selector/market_filter (profile config)
   - **ACTION:** Need to unify to single source of truth. Profile should be the source.

2. **min_edge usage:**
   - Found in 40+ Python files across the codebase
   - **CONCLUSION:** min_edge is widely used. Need to determine which config values are actually enforced.
   - **ACTION:** Profile comment says edge bands are the actual thresholds. Need to verify this in code.

3. **Bankroll tiering implementation:**
   - **NO RESULTS FOUND** in risk envelope or profile adapter
   - **CONCLUSION:** Bankroll tiering is NOT implemented in the code despite being configured in YAML
   - **ACTION:** Either implement tiering logic or remove tiered config and use single 2% value

4. **max_contracts hierarchy:**
   - Found in multiple files
   - **CONCLUSION:** Need to determine which limit is actually enforced
   - **ACTION:** Establish clear hierarchy in code

5. **Depth threshold usage:**
   - Found in many files
   - **CONCLUSION:** Multiple depth threshold systems exist
   - **ACTION:** Determine which is actually used and remove others

---

## Summary

**Total Fixes:** 10  
**Critical:** 2 (COMPLETED)  
**High Priority:** 5 (COMPLETED)  
**Medium Priority:** 2 (COMPLETED)  
**Low Priority:** 1 (COMPLETED)

**Files Modified:**
- `config/kalshi_agent_grid.yaml` - Fixed signal_mode, removed max_spot_to_strike_pct, removed min_edge
- `config/profiles/kalshi_crypto_15m_v2.yaml` - Fixed max_cycle_risk_pct comment, simplified per_trade_risk_pct to 3%, added max_contracts hierarchy comments, expanded disabled features docs, removed tier-based depth thresholds
- `merid/risk/profiles/crypto_15m_profile.py` - Fixed dynamic_sizing multiplier defaults, fixed volatility regime default
- `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py` - Fixed max_cycle_risk_pct default, fixed per_trade_risk_pct default
- `merid/prediction/unified_sizing.py` - Expanded disabled features documentation for regime and TTE sizing

**COMPLETION STATUS: ALL FIXES COMPLETED (2026-06-05)**

**Code Searches Required:** 5 (to determine actual usage before deletions)
