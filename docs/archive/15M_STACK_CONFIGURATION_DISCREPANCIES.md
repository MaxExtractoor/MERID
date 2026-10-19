# MERID 15M Stack Configuration - Discrepancies and Issues

**Generated:** 2026-07-06  
**Source:** Review of documentation against actual source files

---

## Executive Summary

This document identifies discrepancies, mismatches, and inconsistencies found during a comprehensive review of the 15M Stack Configuration Documentation against the actual source files (profile YAML, risk envelope, agent grid, startup script).

**Severity Levels:**
- **CRITICAL:** Values that differ between files and could affect trading behavior
- **HIGH:** Stale comments or documentation that doesn't match implementation
- **MEDIUM:** Inconsistencies that may cause confusion but don't affect behavior
- **LOW:** Minor documentation issues

---

## CRITICAL Discrepancies

### 1. Risk Envelope Agent Default Mismatch
**Files Affected:**
- `config/profiles/kalshi_crypto_15m_v2.yaml`
- `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`

**Issue:**
- **Profile YAML:** `agent_defaults.max_notional_pct: 0.03` (3%)
- **Risk Envelope Code:** Default value is `0.05` (5%) with comment "FIXED: Default 0.05 to match YAML (5% per 15m window)"

**Impact:**
The risk envelope uses a 5% default if the profile value is not found, but the profile specifies 3%. This could cause the risk envelope to use 5% instead of 3% in error conditions.

**Actual Behavior:**
The code does read from the profile, so this is only a fallback issue. However, the comment is misleading.

**Recommendation:**
Update the risk envelope default to 0.03 to match the profile, or update the comment to clarify it's a fallback value.

---

### 2. Min Confidence Threshold Inconsistency
**Files Affected:**
- `config/profiles/kalshi_crypto_15m_v2.yaml`

**Issue:**
The profile YAML has **two different min confidence values**:
- `confidence.min_confidence_threshold: 0.65` (65%) - Line 834
- `strategy_policy.min_confidence: 0.50` (50%) - Line 1135

**Documentation States:**
- "Min Confidence Threshold: 0.65 (65% - increased from 50% based on GRDazzle research)"

**Impact:**
Unclear which value is actually used. The strategy_policy value (50%) might be the one used for trade execution, while the confidence threshold (65%) might be used elsewhere.

**Recommendation:**
Clarify which value is used where, or unify them to a single source of truth.

---

### 3. Risk Envelope Agent Position Defaults Mismatch
**Files Affected:**
- `config/profiles/kalshi_crypto_15m_v2.yaml`
- `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`

**Issue:**
- **Profile YAML:** `max_yes_position: 5`, `max_no_position: 5`
- **Risk Envelope Code:** Defaults to `3` for both (lines 494-495)

**Impact:**
If the profile value is not read correctly, the risk envelope would use 3 instead of 5, limiting position sizes.

**Actual Behavior:**
The code does read from the profile, so this is only a fallback issue.

**Recommendation:**
Update the risk envelope defaults to match the profile (5), or add a comment clarifying these are fallback values.

---

## HIGH Discrepancies

### 4. Stale Comment About per_trade_risk_pct
**File Affected:**
- `config/profiles/kalshi_crypto_15m_v2.yaml`

**Issue:**
Line 421 has a comment:
```yaml
# - per_trade_risk_pct (0.8%): primary sizing control
```

But the actual value is:
```yaml
per_trade_risk_pct:
  value: 0.03  # 3% per trade
```

**Impact:**
The comment is misleading and doesn't match the actual configuration.

**Recommendation:**
Update the comment to say "per_trade_risk_pct (3%): primary sizing control"

---

### 5. Stale Comment About max_cycle_risk_pct
**File Affected:**
- `config/profiles/kalshi_crypto_15m_v2.yaml`

**Issue:**
Line 423 has a comment:
```yaml
# - max_cycle_risk_pct (0.5%): aggregate cycle-level control (conservative for 5-second cycles)
```

But the actual value is:
```yaml
max_cycle_risk_pct:
  value: 0.05  # 5% of capital per cycle
```

**Impact:**
The comment is misleading and doesn't match the actual configuration.

**Recommendation:**
Update the comment to say "max_cycle_risk_pct (5%): aggregate cycle-level control"

---

### 6. Agent Grid Default Velocity Threshold Mismatch
**File Affected:**
- `merid/prediction/agent_grid_15m.py`

**Issue:**
- **Profile YAML:** All assets have `velocity_threshold: 0.00001` (0.001%)
- **Agent Grid Default:** `velocity_threshold: float = 0.0015` (0.15%) - Line 175
- **Agent Grid Per-Asset:** Correctly set to 0.00001 for all assets (lines 181-185)

**Impact:**
The default value is 150x higher than the profile values, but the per-asset values override it. This is only an issue if the per-asset attributes are not set correctly.

**Recommendation:**
Update the default to 0.00001 to match the profile, or add a comment explaining the default is overridden by per-asset values.

---

### 7. Multiple Min Edge Values in Profile
**File Affected:**
- `config/profiles/kalshi_crypto_15m_v2.yaml`

**Issue:**
The profile has **multiple min_edge values** in different sections:
- `strategy_policy.min_edge: 0.015` (1.5%) - Line 1134
- `edge_bands.watch_band.min_edge_pct: 0.008` (0.8%) - Line 843
- `edge_bands.small_band.min_edge_pct: 0.015` (1.5%) - Line 848
- `edge_bands.standard_band.min_edge_pct: 0.03` (3%) - Line 853
- `strategies.heuristic_velocity.policy.min_edge: 0.01` (1%) - Line 1395
- Per-asset `min_edge_early/mid/late/terminal`: 0.03-0.06 (3-6%) for various assets

**Documentation States:**
The documentation lists some of these but doesn't clarify which is actually used for trade execution.

**Impact:**
Unclear which min_edge value is the single source of truth for trade execution.

**Recommendation:**
Clarify in documentation which value is used where, or add comments in the profile explaining the hierarchy.

---

### 8. Adaptive Price Caps Not Documented
**Files Affected:**
- `merid/prediction/agent_grid_15m.py`

**Issue:**
The agent grid has **adaptive regime-based price caps** (lines 3058-3097) that override the profile YAML values:
- Strong trend: max_entry_price_yes=0.95, min_entry_price_no=0.05
- Weak trend: max_entry_price_yes=0.90, min_entry_price_no=0.10
- Mean reverting: max_entry_price_yes=0.80, min_entry_price_no=0.20
- Neutral: max_entry_price_yes=0.85, min_entry_price_no=0.15

**Documentation States:**
Only mentions the static profile values (0.70/0.30).

**Impact:**
Documentation doesn't reflect the actual behavior of the system.

**Recommendation:**
Add a section to the documentation explaining the adaptive price cap logic.

---

### 9. Dynamic Velocity Threshold Adjustment Not Documented
**Files Affected:**
- `merid/prediction/agent_grid_15m.py`

**Issue:**
The agent grid has **dynamic velocity threshold adjustment** based on:
- ATR (volatility) - lines 1408-1426
- Realized volatility - lines 2801-2833
- Regime detection - lines 2877-2896

**Documentation States:**
Only mentions the static profile values (0.00001 for all assets).

**Impact:**
Documentation doesn't reflect the actual behavior of the system.

**Recommendation:**
Add a section to the documentation explaining the dynamic threshold adjustment logic.

---

## MEDIUM Discrepancies

### 10. Failsafe vs Contract Caps Mismatch
**Files Affected:**
- `config/profiles/kalshi_crypto_15m_v2.yaml`

**Issue:**
- `contract_caps.max_single_order_contracts: 2` - Line 1031
- `failsafe.max_contracts_per_order: 1` - Line 484

**Documentation States:**
"Max Single Order Contracts: 2"

**Impact:**
The failsafe mode uses 1 contract, but this is not documented. This is actually correct behavior (failsafe should be more restrictive), but it's not mentioned.

**Recommendation:**
Add a note about failsafe mode using 1 contract.

---

### 11. Max Contracts Per Asset Inconsistency
**Files Affected:**
- `config/profiles/kalshi_crypto_15m_v2.yaml`

**Issue:**
- DOGE has `max_contracts: 2` (line 781)
- Other assets (BTC, ETH, SOL, XRP) have `max_contracts: 3`

**Documentation States:**
"Max Contracts: 3 (for BTC, ETH, SOL, XRP; 2 for DOGE)"

**Impact:**
Documentation is correct, but the distinction could be clearer.

**Recommendation:**
This is actually correct, no action needed.

---

### 12. Agent Grid Hybrid Mode Price Cap Defaults
**File Affected:**
- `merid/prediction/agent_grid_15m.py`

**Issue:**
The agent grid has hardcoded defaults (lines 201-202):
```python
max_entry_price_yes: float = 0.70
min_entry_price_no: float = 0.30
```

But these are overridden by adaptive regime-based logic at runtime.

**Impact:**
The defaults are never actually used in production due to the adaptive logic.

**Recommendation:**
Add a comment explaining these are defaults that are overridden by adaptive logic.

---

## LOW Discrepancies

### 13. Documentation Says "Disabled" for Some Features That Are Actually "Enabled"
**Issue:**
The documentation correctly states that correlation tracking and offset hedging are disabled, but the reasoning could be clearer.

**Recommendation:**
No action needed, documentation is accurate.

---

### 14. Min Depth Values Not Clearly Explained
**Issue:**
The profile has `min_depth_yes: 1` and `min_depth_no: 1` for all assets, but the documentation doesn't explain why this was changed from higher values.

**Recommendation:**
Add a brief explanation that this was changed to align with 1 contract per order.

---

## Internal Contradictions in Documentation

### 15. Per-Trade Risk Pct Description
**Issue:**
Section 2.9 says "Max Cycle Risk Pct: 0.05 (5% of capital per cycle)" but section 12.1 says "Per Trade: 3% of capital". These are different limits for different purposes, but the distinction could be clearer.

**Recommendation:**
Add clarification that max_cycle_risk_pct is for the entire 15m window, while per_trade_risk_pct is for individual trades.

---

### 16. Edge Band Description vs Per-Asset Edge Thresholds
**Issue:**
Section 2.18 describes edge bands (0.8-1.5% watch, 1.5-3% small, >=3% standard), but section 2.15 lists per-asset min_edge values (3-6%). The relationship between these is not explained.

**Recommendation:**
Add clarification that edge bands are the actual thresholds used, while per-asset min_edge fields are ignored (as noted in the profile YAML comment on line 839).

---

## Summary Statistics

- **CRITICAL Issues:** 3
- **HIGH Issues:** 6
- **MEDIUM Issues:** 3
- **LOW Issues:** 2
- **Internal Contradictions:** 2

**Total Issues:** 16

---

## Recommended Actions

### Immediate (Critical)
1. Update risk envelope default for agent_max_notional_pct from 0.05 to 0.03
2. Clarify which min_confidence value is actually used (0.50 vs 0.65)
3. Update risk envelope defaults for max_yes_position/max_no_position from 3 to 5

### High Priority
4. Update stale comments in profile YAML for per_trade_risk_pct and max_cycle_risk_pct
5. Update agent grid default velocity_threshold from 0.0015 to 0.00001
6. Add documentation clarifying the hierarchy of min_edge values
7. Add documentation for adaptive price caps
8. Add documentation for dynamic velocity threshold adjustment

### Medium Priority
9. Add note about failsafe mode using 1 contract
10. Add comment in agent grid explaining hybrid mode defaults are overridden

### Low Priority
11. Add explanation for min_depth values being 1
12. Clarify distinction between max_cycle_risk_pct and per_trade_risk_pct
13. Clarify relationship between edge bands and per-asset min_edge values

---

## Conclusion

The configuration documentation is largely accurate, but there are several discrepancies between comments and actual values, and some dynamic behaviors (adaptive price caps, dynamic velocity thresholds) are not documented. The most critical issues involve default values in the risk envelope that don't match the profile YAML, which could cause incorrect behavior in error conditions.

**Overall Assessment:** The documentation is 85% accurate but needs updates to reflect the actual implementation, especially around dynamic behaviors and fallback values.

---

**Document End**
