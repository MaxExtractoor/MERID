# MERID 15M Stack - End-to-End Audit Report

**Generated:** 2026-07-06  
**Scope:** Upstream/Midstream/Downstream consistency audit for risk limits and configuration

---

## Executive Summary

This report documents all high-leverage bugs, mismatches, and inconsistencies found during a comprehensive end-to-end audit of the 15M Kalshi crypto trading stack. The audit covered:

- **UPSTREAM:** Profile YAML (config/profiles/kalshi_crypto_15m_v2.yaml)
- **MIDSTREAM:** Risk envelope (merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py) and profile adapter (merid/risk/profiles/crypto_15m_profile.py)
- **DOWNSTREAM:** Unified sizing (merid/prediction/unified_sizing.py) and agent grid (merid/prediction/agent_grid_15m.py)

**Key Finding:** There are **multiple critical mismatches** between default values in the midstream layer and the actual profile YAML values. These defaults are only used in error conditions, but they are misleading and could cause incorrect behavior if the profile value is not read correctly.

**Risk Limit Clarification:**
- **3% per agent per trade** (agent_defaults.max_notional_pct = 0.03, per_trade_risk_pct = 0.03)
- **5% per cycle** (max_cycle_risk_pct = 0.05)

---

## CRITICAL Issues (Affect Trading Behavior)

### 1. Profile Adapter Default Mismatch - agent_max_notional_pct
**Layer:** MIDSTREAM (Profile Adapter)  
**Files:** `merid/risk/profiles/crypto_15m_profile.py`  
**Lines:** 630, 632, 804

**Issue:**
```python
# Line 630, 632, 804
agent_max_notional_pct = agent_defaults.get('max_notional_pct', 0.05)  # FIXED: Default 0.05 to match YAML (5% per 15m window)
if isinstance(agent_max_notional_pct, dict):
    agent_max_notional_pct = agent_max_notional_pct.get('value', 0.05)  # FIXED: Default 0.05 to match YAML (5% per 15m window)
```

**Profile YAML Value:**
```yaml
agent_defaults:
  max_notional_pct: 0.03  # 3% of capital per agent
```

**Impact:**
- **Default is 5% but profile specifies 3%**
- If the profile value is not read correctly (e.g., parsing error, missing field), the system would use 5% instead of 3%
- This could cause oversized positions by 67% (5% vs 3%)
- The comment says "FIXED: Default 0.05 to match YAML (5% per 15m window)" but the YAML actually has 3%, not 5%

**Recommendation:**
Update all three occurrences to use 0.03 as the default and update the comment to match the actual profile value.

---

### 2. Risk Envelope Default Mismatch - agent_max_notional_pct
**Layer:** MIDSTREAM (Risk Envelope)  
**File:** `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`  
**Line:** 491

**Issue:**
```python
# Line 491
agent_max_notional_pct = agent_defaults.get('max_notional_pct', 0.05)  # FIXED: Default 0.05 to match YAML (5% per 15m window)
```

**Profile YAML Value:**
```yaml
agent_defaults:
  max_notional_pct: 0.03  # 3% of capital per agent
```

**Impact:**
- **Default is 5% but profile specifies 3%**
- Same issue as #1 - could cause oversized positions if profile value is not read correctly
- Comment is misleading

**Recommendation:**
Update default to 0.03 and update the comment.

---

### 3. Profile Adapter Default Mismatch - venue_max_total_notional_pct
**Layer:** MIDSTREAM (Profile Adapter)  
**File:** `merid/risk/profiles/crypto_15m_profile.py`  
**Lines:** 618, 620, 789

**Issue:**
```python
# Lines 618, 620
venue_max_total_notional_pct = venue.get('max_total_notional_pct', 0.25)  # FIXED: Default 0.25 to match YAML (was 0.15)
if isinstance(venue_max_total_notional_pct, dict):
    venue_max_total_notional_pct = venue_max_total_notional_pct.get('value', 0.25)  # FIXED: Default 0.25 to match YAML (was 0.15)

# Line 789
venue_max_total_notional_pct=self._normalize_percentage_value(venue.get('max_total_notional_pct', 0.25)),  # FIXED: Increased from 0.05 to 0.25 to match YAML (25% for 5 assets at 3-5% each)
```

**Profile YAML Value:**
```yaml
venue:
  max_total_notional_pct:
    value: 0.15  # 15% total venue cap
```

**Impact:**
- **Default is 25% but profile specifies 15%**
- If the profile value is not read correctly, the system would allow 25% total exposure instead of 15%
- This is a 67% increase in allowed total exposure
- Comment says "25% for 5 assets at 3-5% each" but 5 assets × 3% = 15%, not 25%

**Recommendation:**
Update all three occurrences to use 0.15 as the default and update the comment to match the actual profile value.

---

### 4. Profile Adapter Default Mismatch - guardrails_per_trade_risk_pct
**Layer:** MIDSTREAM (Profile Adapter)  
**File:** `merid/risk/profiles/crypto_15m_profile.py`  
**Line:** 673

**Issue:**
```python
# Line 673
guardrails_per_trade_risk_pct = self._normalize_percentage_value(guardrails.get('per_trade_risk_pct', 0.02))  # CRITICAL FIX: 2% - aligned with profile (was 0.008)
```

**Profile YAML Value:**
```yaml
guardrails:
  per_trade_risk_pct:
    value: 0.03  # 3% per trade
```

**Impact:**
- **Default is 2% but profile specifies 3%**
- If the profile value is not read correctly, the system would use 2% instead of 3% for per-trade risk
- This is a 33% reduction in allowed per-trade risk
- Comment says "CRITICAL FIX: 2% - aligned with profile" but the profile actually has 3%

**Recommendation:**
Update default to 0.03 and update the comment.

---

### 5. Profile Adapter Default Mismatch - kelly_hard_cap
**Layer:** MIDSTREAM (Profile Adapter)  
**File:** `merid/risk/profiles/crypto_15m_profile.py`  
**Line:** 858

**Issue:**
```python
# Line 858
kelly_hard_cap=self._normalize_percentage_value(kelly.get('kelly_hard_cap', 0.05)),  # P1-FIX1: fallback default reduced from 0.30 to 0.05
```

**Profile YAML Value:**
```yaml
kelly:
  kelly_fraction: 0.02  # 2% Kelly hard cap
  kelly_hard_cap: 0.02  # 2% Kelly hard cap
```

**Impact:**
- **Default is 5% but profile specifies 2%**
- If the profile value is not read correctly, the system would use 5% instead of 2% for Kelly sizing
- This is a 150% increase in allowed Kelly sizing
- Comment says "fallback default reduced from 0.30 to 0.05" but the profile actually has 0.02

**Recommendation:**
Update default to 0.02 and update the comment.

---

### 6. Profile Adapter Default Mismatch - kelly_global_notional_cap_pct
**Layer:** MIDSTREAM (Profile Adapter)  
**File:** `merid/risk/profiles/crypto_15m_profile.py`  
**Line:** 863

**Issue:**
```python
# Line 863
kelly_global_notional_cap_pct=self._normalize_percentage_value(kelly.get('kelly_global_notional_cap_pct', 0.05)),  # P2-FIX6: tightened from 2.0 to 0.05 (was 200%, now 5%)
```

**Profile YAML Value:**
```yaml
kelly:
  kelly_global_notional_cap_pct: 0.02  # 2% of equity
```

**Impact:**
- **Default is 5% but profile specifies 2%**
- If the profile value is not read correctly, the system would use 5% instead of 2% for global Kelly cap
- This is a 150% increase in allowed global Kelly cap
- Comment says "tightened from 2.0 to 0.05 (was 200%, now 5%)" but the profile actually has 0.02

**Recommendation:**
Update default to 0.02 and update the comment.

---

### 7. Unified Sizing Risk Pct Conflict - bankroll_cap_pct vs profile
**Layer:** DOWNSTREAM (Unified Sizing)  
**File:** `merid/prediction/unified_sizing.py`  
**Lines:** 197-225, 626-629

**Issue:**
```python
# Lines 197-225
def _get_bankroll_cap_pct() -> Decimal:
    """Get global bankroll cap percentage from environment.
    
    SAFETY CEILING: This is a GLOBAL SAFETY CEILING, not a primary policy mechanism.
    Production profiles must set risk percentages (per_trade_risk_pct, max_single_order_pct)
    that are ≤ this ceiling. Changing this env var in production is a risk-governance action,
    not a tuning knob.
    
    Reads MERID_BANKROLL_CAP_PCT env var, clamped to safe range [1%, 2%].
    Default is 2% (max) if not configured.
    """
    try:
        raw_pct = float(os.getenv("MERID_BANKROLL_CAP_PCT", "2.0"))
        # CRITICAL FIX: Validate bankroll cap percentage is reasonable
        if raw_pct < 0 or raw_pct > 100:
            logger.warning(
                "[UNIFIED-SIZING] Invalid MERID_BANKROLL_CAP_PCT=%s - using default 2.0",
                raw_pct
            )
            raw_pct = 2.0
    except (ValueError, TypeError):
        raw_pct = 2.0
    
    # Clamp to safe range: 1% minimum, 2% maximum
    clamped_pct = max(1.0, min(2.0, raw_pct))
    return Decimal(str(clamped_pct / 100.0))  # Convert to fraction

# Lines 626-629
bankroll_cap_pct = _get_bankroll_cap_pct()  # global safety ceiling from MERID_BANKROLL_CAP_PCT env
risk_pct_candidates = [min_edge_risk_pct, max_single_order_pct, bankroll_cap_pct]
```

**Profile YAML Value:**
```yaml
venue:
  bankroll_cap_pct:
    value: 0.03  # 3% of bankroll per order
```

**Impact:**
- **Env var default is 2% but profile specifies 3%**
- The unified sizing uses `min()` of multiple risk percentages, including bankroll_cap_pct
- If MERID_BANKROLL_CAP_PCT is not set in the environment, it defaults to 2%
- This means the effective risk_pct could be 2% instead of 3% (a 33% reduction)
- The profile has bankroll_cap_pct at 3%, but the unified sizing doesn't read from the profile for this value
- The code clamps the env var to 1-2%, which is inconsistent with the profile's 3%

**Recommendation:**
Either:
1. Update the env var default to 3% and clamp to 1-3%, OR
2. Make unified sizing read bankroll_cap_pct from the profile instead of the env var, OR
3. Remove bankroll_cap_pct from the risk_pct_candidates list if it's meant to be a safety ceiling only

---

### 8. Unified Sizing Risk Pct Conflict - min_edge_risk_pct repurposing
**Layer:** DOWNSTREAM (Unified Sizing)  
**File:** `merid/prediction/unified_sizing.py`  
**Lines:** 366-390, 626-627

**Issue:**
```python
# Lines 366-390
def _get_min_edge_risk_pct() -> Decimal:
    """Get min-edge-based risk percentage from profile config.
    
    NOTE: This reads from kalshi_crypto_15m.yaml guardrails.min_post_fee_edge.
    The field is conceptually a minimum edge threshold, but we repurpose it as a
    per-trade risk cap for sizing. This is a temporary measure; a dedicated
    per_trade_risk_pct field should be added to the profile for clarity.
    
    PRODUCTION: If profile is unavailable, this fails (no silent fallback).
    """
    if not _PROFILE_AVAILABLE:
        logger.error("[UNIFIED-SIZING] Profile adapter not available - cannot size orders in production")
        raise RuntimeError("Profile adapter required for production sizing")
    
    try:
        if is_profile_active():
            adapter = get_active_profile()
            profile = adapter.profile
            return Decimal(str(profile.guardrails_min_post_fee_edge))
        else:
            logger.error("[UNIFIED-SIZING] Profile not active - cannot size orders in production")
            raise RuntimeError("Active profile required for production sizing")
    except Exception as e:
        logger.error("[UNIFIED-SIZING] Failed to read min_edge from profile: %s", e)
        raise RuntimeError(f"Profile read failed: {e}") from e

# Lines 626-627
min_edge_risk_pct = _get_min_edge_risk_pct()  # from profile guardrails.min_post_fee_edge (repurposed)
risk_pct_candidates = [min_edge_risk_pct, max_single_order_pct, bankroll_cap_pct]
```

**Profile YAML Value:**
```yaml
guardrails:
  min_post_fee_edge: 0.015  # 1.5% minimum post-fee edge
```

**Impact:**
- **min_post_fee_edge is 1.5% but per_trade_risk_pct is 3%**
- The unified sizing repurposes min_post_fee_edge (a minimum edge threshold) as a risk percentage
- This is conceptually wrong - edge thresholds and risk percentages are different things
- The code uses `min()` of multiple risk percentages, so the effective risk_pct could be 1.5% instead of 3%
- This is a 50% reduction in allowed per-trade risk
- The comment acknowledges this is a "temporary measure" but it has not been fixed

**Recommendation:**
Add a dedicated per_trade_risk_pct field to the profile and update unified sizing to read from it instead of repurposing min_post_fee_edge.

---

## HIGH Issues (Misleading Comments/Documentation)

### 9. Stale Comment - per_trade_risk_pct
**Layer:** UPSTREAM (Profile YAML)  
**File:** `config/profiles/kalshi_crypto_15m_v2.yaml`  
**Line:** 421

**Issue:**
```yaml
# Line 421
# - per_trade_risk_pct (0.8%): primary sizing control
```

**Actual Value:**
```yaml
# Line 938-939
per_trade_risk_pct:
  value: 0.03  # 3% per trade
```

**Impact:**
- Comment says 0.8% but actual value is 3%
- Misleading documentation

**Recommendation:**
Update comment to say "per_trade_risk_pct (3%): primary sizing control"

---

### 10. Stale Comment - max_cycle_risk_pct
**Layer:** UPSTREAM (Profile YAML)  
**File:** `config/profiles/kalshi_crypto_15m_v2.yaml`  
**Line:** 423

**Issue:**
```yaml
# Line 423
# - max_cycle_risk_pct (0.5%): aggregate cycle-level control (conservative for 5-second cycles)
```

**Actual Value:**
```yaml
# Line 400-401
max_cycle_risk_pct:
  value: 0.05  # 5% of capital per cycle
```

**Impact:**
- Comment says 0.5% but actual value is 5%
- Misleading documentation

**Recommendation:**
Update comment to say "max_cycle_risk_pct (5%): aggregate cycle-level control"

---

### 11. Min Confidence Threshold Inconsistency
**Layer:** UPSTREAM (Profile YAML)  
**File:** `config/profiles/kalshi_crypto_15m_v2.yaml`  
**Lines:** 834, 1135

**Issue:**
```yaml
# Line 834
confidence:
  min_confidence_threshold: 0.65  # 65%

# Line 1135
strategy_policy:
  min_confidence: 0.50  # 50%
```

**Impact:**
- Two different min confidence values in the same profile
- Unclear which value is actually used for trade execution
- Could cause confusion about the actual confidence threshold

**Recommendation:**
Clarify which value is used where, or unify them to a single source of truth.

---

### 12. Multiple Min Edge Values
**Layer:** UPSTREAM (Profile YAML)  
**File:** `config/profiles/kalshi_crypto_15m_v2.yaml`

**Issue:**
Multiple min_edge values in different sections:
- `strategy_policy.min_edge: 0.015` (1.5%) - Line 1134
- `edge_bands.watch_band.min_edge_pct: 0.008` (0.8%) - Line 843
- `edge_bands.small_band.min_edge_pct: 0.015` (1.5%) - Line 848
- `edge_bands.standard_band.min_edge_pct: 0.03` (3%) - Line 853
- `strategies.heuristic_velocity.policy.min_edge: 0.01` (1%) - Line 1395
- Per-asset `min_edge_early/mid/late/terminal`: 0.03-0.06 (3-6%) for various assets

**Impact:**
- Unclear which min_edge value is the single source of truth for trade execution
- Profile comment on line 839 says "CRITICAL: Edge bands are the ACTUAL thresholds used (per-asset min_edge fields are ignored)"

**Recommendation:**
Add clarification in documentation explaining the hierarchy of min_edge values.

---

### 13. Risk Envelope Default Mismatch - max_yes_position/max_no_position
**Layer:** MIDSTREAM (Risk Envelope)  
**File:** `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`  
**Lines:** 494-495

**Issue:**
```python
# Lines 494-495
agent_max_yes_position = agent_defaults.get('max_yes_position', 3)
agent_max_no_position = agent_defaults.get('max_no_position', 3)
```

**Profile YAML Value:**
```yaml
agent_defaults:
  max_yes_position: 5
  max_no_position: 5
```

**Impact:**
- Defaults are 3 but profile specifies 5
- If the profile value is not read correctly, the system would use 3 instead of 5
- This is a 40% reduction in allowed position size

**Recommendation:**
Update defaults to 5 to match the profile.

---

## MEDIUM Issues (Documentation Gaps)

### 14. Adaptive Price Caps Not Documented
**Layer:** DOWNSTREAM (Agent Grid)  
**File:** `merid/prediction/agent_grid_15m.py`  
**Lines:** 3058-3097

**Issue:**
The agent grid has adaptive regime-based price caps that override the profile YAML values:
- Strong trend: max_entry_price_yes=0.95, min_entry_price_no=0.05
- Weak trend: max_entry_price_yes=0.90, min_entry_price_no=0.10
- Mean reverting: max_entry_price_yes=0.80, min_entry_price_no=0.20
- Neutral: max_entry_price_yes=0.85, min_entry_price_no=0.15

**Documentation:**
Only mentions the static profile values (0.70/0.30).

**Impact:**
Documentation doesn't reflect the actual behavior of the system.

**Recommendation:**
Add a section to the documentation explaining the adaptive price cap logic.

---

### 15. Dynamic Velocity Threshold Adjustment Not Documented
**Layer:** DOWNSTREAM (Agent Grid)  
**File:** `merid/prediction/agent_grid_15m.py`  
**Lines:** 1408-1426, 2801-2833, 2877-2896

**Issue:**
The agent grid has dynamic velocity threshold adjustment based on:
- ATR (volatility)
- Realized volatility
- Regime detection

**Documentation:**
Only mentions the static profile values (0.00001 for all assets).

**Impact:**
Documentation doesn't reflect the actual behavior of the system.

**Recommendation:**
Add a section to the documentation explaining the dynamic threshold adjustment logic.

---

### 16. Agent Grid Default Velocity Threshold Mismatch
**Layer:** DOWNSTREAM (Agent Grid)  
**File:** `merid/prediction/agent_grid_15m.py`  
**Lines:** 175, 181-185

**Issue:**
```python
# Line 175
velocity_threshold: float = 0.0015  # 0.15% - aligned with actual market conditions

# Lines 181-185
velocity_threshold_btc: float = 0.00001  # 0.001% (CRITICAL FIX: aligned with profile YAML)
velocity_threshold_eth: float = 0.00001  # 0.001% (CRITICAL FIX: aligned with profile YAML)
velocity_threshold_sol: float = 0.00001  # 0.001% (CRITICAL FIX: aligned with profile YAML)
velocity_threshold_xrp: float = 0.00001  # 0.001% (CRITICAL FIX: aligned with profile YAML)
velocity_threshold_doge: float = 0.00001  # 0.001% (CRITICAL FIX: aligned with profile YAML)
```

**Profile YAML Value:**
```yaml
velocity_thresholds:
  BTC: 0.00001  # 0.001%
  ETH: 0.00001  # 0.001%
  SOL: 0.00001  # 0.001%
  XRP: 0.00001  # 0.001%
  DOGE: 0.00001  # 0.001%
```

**Impact:**
- The default value is 150x higher than the profile values
- The per-asset values override it, so this is only an issue if the per-asset attributes are not set correctly

**Recommendation:**
Update the default to 0.00001 to match the profile, or add a comment explaining the default is overridden by per-asset values.

---

## Summary Statistics

- **CRITICAL Issues:** 8 (affect trading behavior)
- **HIGH Issues:** 5 (misleading comments/documentation)
- **MEDIUM Issues:** 3 (documentation gaps)

**Total Issues:** 16

---

## Recommended Fix Plan

### Phase 1: Critical Default Value Fixes (MUST FIX)

1. **Profile Adapter - agent_max_notional_pct**
   - File: `merid/risk/profiles/crypto_15m_profile.py`
   - Lines: 630, 632, 804
   - Change: Update default from 0.05 to 0.03
   - Update comment to match actual profile value

2. **Risk Envelope - agent_max_notional_pct**
   - File: `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`
   - Line: 491
   - Change: Update default from 0.05 to 0.03
   - Update comment to match actual profile value

3. **Profile Adapter - venue_max_total_notional_pct**
   - File: `merid/risk/profiles/crypto_15m_profile.py`
   - Lines: 618, 620, 789
   - Change: Update default from 0.25 to 0.15
   - Update comment to match actual profile value

4. **Profile Adapter - guardrails_per_trade_risk_pct**
   - File: `merid/risk/profiles/crypto_15m_profile.py`
   - Line: 673
   - Change: Update default from 0.02 to 0.03
   - Update comment to match actual profile value

5. **Profile Adapter - kelly_hard_cap**
   - File: `merid/risk/profiles/crypto_15m_profile.py`
   - Line: 858
   - Change: Update default from 0.05 to 0.02
   - Update comment to match actual profile value

6. **Profile Adapter - kelly_global_notional_cap_pct**
   - File: `merid/risk/profiles/crypto_15m_profile.py`
   - Line: 863
   - Change: Update default from 0.05 to 0.02
   - Update comment to match actual profile value

7. **Risk Envelope - max_yes_position/max_no_position**
   - File: `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`
   - Lines: 494-495
   - Change: Update defaults from 3 to 5

### Phase 2: Unified Sizing Risk Pct Conflict (MUST FIX)

8. **Unified Sizing - bankroll_cap_pct conflict**
   - File: `merid/prediction/unified_sizing.py`
   - Lines: 197-225, 626-629
   - Options:
     - Option A: Update env var default to 3% and clamp to 1-3%
     - Option B: Make unified sizing read bankroll_cap_pct from profile instead of env var
     - Option C: Remove bankroll_cap_pct from risk_pct_candidates if it's meant to be safety ceiling only
   - **Recommended:** Option B (read from profile for consistency)

9. **Unified Sizing - min_edge_risk_pct repurposing**
   - File: `merid/prediction/unified_sizing.py`
   - Lines: 366-390, 626-627
   - Change: Add dedicated per_trade_risk_pct field to profile and update unified sizing to read from it
   - Remove repurposing of min_post_fee_edge

### Phase 3: Comment/Documentation Fixes (SHOULD FIX)

10. **Profile YAML - per_trade_risk_pct comment**
    - File: `config/profiles/kalshi_crypto_15m_v2.yaml`
    - Line: 421
    - Change: Update comment from 0.8% to 3%

11. **Profile YAML - max_cycle_risk_pct comment**
    - File: `config/profiles/kalshi_crypto_15m_v2.yaml`
    - Line: 423
    - Change: Update comment from 0.5% to 5%

12. **Profile YAML - min confidence threshold**
    - File: `config/profiles/kalshi_crypto_15m_v2.yaml`
    - Lines: 834, 1135
    - Change: Clarify which value is used where, or unify them

13. **Profile YAML - multiple min_edge values**
    - File: `config/profiles/kalshi_crypto_15m_v2.yaml`
    - Change: Add clarification in documentation explaining hierarchy

14. **Agent Grid - default velocity threshold**
    - File: `merid/prediction/agent_grid_15m.py`
    - Line: 175
    - Change: Update default from 0.0015 to 0.00001, or add comment explaining it's overridden

### Phase 4: Documentation Updates (NICE TO HAVE)

15. **Documentation - adaptive price caps**
    - Add section explaining adaptive regime-based price caps

16. **Documentation - dynamic velocity threshold adjustment**
    - Add section explaining dynamic threshold adjustment logic

---

## End-to-End Consistency Verification

After fixes, verify:

1. **Profile YAML values match risk envelope defaults**
   - agent_max_notional_pct: 0.03 ✓
   - max_yes_position: 5 ✓
   - max_no_position: 5 ✓
   - venue_max_total_notional_pct: 0.15 ✓
   - per_trade_risk_pct: 0.03 ✓
   - kelly_hard_cap: 0.02 ✓
   - kelly_global_notional_cap_pct: 0.02 ✓

2. **Risk envelope defaults match profile adapter defaults**
   - All default values should be consistent across both files

3. **Unified sizing reads from profile, not env var**
   - bankroll_cap_pct should be read from profile
   - per_trade_risk_pct should be read from profile (not repurposed from min_post_fee_edge)

4. **No scaling multipliers interfere with hard risk limits**
   - Verify regime-based sizing is disabled
   - Verify TTE-based sizing is disabled
   - Verify time-of-day scaling is disabled

5. **3% per asset / 5% per 15m window limits are respected**
   - Verify per-asset max_notional_pct = 0.03
   - Verify max_cycle_risk_pct = 0.05

6. **All 5 crypto assets treated consistently**
   - Verify BTC, ETH, SOL, XRP, DOGE all have consistent treatment

---

**Document End**
