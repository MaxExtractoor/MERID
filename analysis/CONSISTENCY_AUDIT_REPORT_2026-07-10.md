# MERID 15m Kalshi Crypto Trading Stack - Consistency Audit Report

**Date**: 2026-07-10  
**Profile**: `kalshi_crypto_15m_v2`  
**Scope**: End-to-end consistency audit across upstream (configuration), midstream (risk envelope), and downstream (sizing/execution) layers

---

## Executive Summary

This audit identified **3 critical inconsistencies** and **2 potential issues** in the risk parameter flow from configuration through to execution. The most significant finding is that the risk envelope's `get_per_trade_risk_pct()` method implements its own tiered logic that bypasses the profile configuration, creating a single point of divergence in the risk stack.

---

## Audit Methodology

**Layers Analyzed**:
1. **Upstream (Configuration Layer)**: `config/profiles/kalshi_crypto_15m_v2.yaml` and `merid/risk/profiles/crypto_15m_profile.py`
2. **Midstream (Risk Envelope Layer)**: `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`
3. **Downstream (Sizing/Execution Layer)**: `merid/prediction/unified_sizing.py` and `merid/prediction/agent_grid_config.py`

**Consistency Checks Performed**:
- Profile values match risk envelope defaults
- Risk envelope defaults match sizing layer behavior
- No scaling multipliers interfere with hard risk limits
- 3% per asset / 5% per 15m window limits are respected
- All 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) are treated consistently

---

## Critical Inconsistencies

### 1. Per-Trade Risk Percentage Divergence

**Severity**: CRITICAL  
**Location**: Risk envelope `get_per_trade_risk_pct()` method

**Issue**:
The risk envelope implements its own tiered per-trade risk logic that ignores the profile's `guardrails.per_trade_risk_pct` configuration:

- **YAML Profile**: `guardrails.per_trade_risk_pct = 0.03` (3%)
- **Risk Envelope**: `get_per_trade_risk_pct()` returns tiered values:
  - Bankroll < $100: 3%
  - Bankroll $100-$1k: 2%
  - Bankroll > $1k: 1.5%
- **Profile Adapter**: Reads `guardrails.per_trade_risk_pct` with default 0.02 (2%)
- **Agent Grid Config**: Uses `getattr(profile, 'per_trade_risk_pct', 0.02)` with default 2%

**Impact**:
- The profile's `per_trade_risk_pct = 0.03` value is effectively ignored
- Risk envelope's tiered logic creates a different risk profile than configured
- Multiple code paths have different defaults (2% vs 3%)

**Code References**:
- `config/profiles/kalshi_crypto_15m_v2.yaml:938-941` (profile value: 3%)
- `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py:207-225` (tiered implementation)
- `merid/risk/profiles/crypto_15m_profile.py:673` (default: 2%)
- `merid/prediction/agent_grid_config.py:105` (default: 2%)

**Recommendation**:
Align the risk envelope to use the profile's `per_trade_risk_pct` value, or remove the tiered logic and document that the profile value is the single source of truth.

---

### 2. Agent Max Notional Percentage Default Mismatch

**Severity**: HIGH  
**Location**: Profile adapter and risk envelope defaults

**Issue**:
The YAML profile specifies `agent_defaults.max_notional_pct = 0.03` (3%), but code defaults use 5%:

- **YAML Profile**: `agent_defaults.max_notional_pct = 0.03` (3%)
- **Profile Adapter**: Default 0.05 (5%) when value is missing
- **Risk Envelope**: Default 0.05 (5%) when value is missing

**Impact**:
- If the YAML value is missing or malformed, the system would use 5% instead of the intended 3%
- This could lead to exceeding the 3% per asset risk limit

**Code References**:
- `config/profiles/kalshi_crypto_15m_v2.yaml:810` (profile value: 3%)
- `merid/risk/profiles/crypto_15m_profile.py:630-632` (default: 5%)
- `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py:495` (default: 5%)

**Recommendation**:
Update code defaults to match the profile value (3%) to ensure consistency.

---

### 3. Profile Adapter Does Not Expose `per_trade_risk_pct`

**Severity**: MEDIUM  
**Location**: `Crypto15mProfile` dataclass

**Issue**:
The profile adapter reads `guardrails.per_trade_risk_pct` from the YAML but does not expose it as a field in the `Crypto15mProfile` dataclass. This means:

- The value is parsed but not accessible to downstream consumers
- Agent grid config falls back to a hardcoded default (2%)
- The profile's 3% configuration is effectively unused in the agent grid

**Impact**:
- Agent grid config uses 2% default instead of profile's 3%
- Inconsistent risk limits between components

**Code References**:
- `merid/risk/profiles/crypto_15m_profile.py:673` (parsed but not exposed)
- `merid/prediction/agent_grid_config.py:105` (uses default 2%)

**Recommendation**:
Add `per_trade_risk_pct` as a field in the `Crypto15mProfile` dataclass and expose the parsed value.

---

## Potential Issues

### 4. Time-of-Day Scaling Configuration vs Implementation

**Severity**: LOW  
**Location**: YAML profile and unified sizing

**Issue**:
Time-of-day scaling is DISABLED in the YAML profile with a warning comment:

- **YAML Profile**: `time_of_day_risk_scaling.enabled = false` with comment "DISABLED: interferes with 3% per asset / 5% per 15m window limits"
- **Unified Sizing**: Accepts `time_of_day_multiplier` parameter but defaults to 1.0
- **Risk Envelope**: Does not apply time-of-day scaling to risk limits

**Impact**:
- If time-of-day scaling is accidentally enabled in the future, it could bypass hard risk limits
- The comment indicates this was intentionally disabled, but the code path still exists

**Code References**:
- `config/profiles/kalshi_crypto_15m_v2.yaml:557-571` (disabled with warning)
- `merid/prediction/unified_sizing.py:699-706` (multiplier application)

**Recommendation**:
Remove the time-of-day scaling code path entirely if it's permanently disabled, or add a runtime check to prevent re-enabling without updating the risk envelope.

---

### 5. Regime and TTE Scaling Disabled but Code Paths Exist

**Severity**: LOW  
**Location**: Unified sizing

**Issue**:
Regime-based and TTE-based position size multipliers are hardcoded to return 1.0 (disabled):

- **Regime Sizing**: `_get_regime_position_size_multiplier()` returns 1.0
- **TTE Sizing**: `_get_tte_position_size_multiplier()` returns 1.0
- Both have comments indicating they are disabled to prevent interference with risk limits

**Impact**:
- If these are accidentally re-enabled, they could bypass hard risk limits
- The code paths exist but are effectively dead code

**Code References**:
- `merid/prediction/unified_sizing.py:708-717` (regime multiplier)
- `merid/prediction/unified_sizing.py:719-728` (TTE multiplier)

**Recommendation**:
If these are permanently disabled, consider removing the code paths or adding runtime checks to prevent re-enabling without proper risk envelope integration.

---

## Consistent Configurations (No Issues Found)

### Per-Asset Max Notional Percentage
- **YAML Profile**: All assets (BTC, ETH, SOL, XRP, DOGE) have `max_notional_pct = 0.03` (3%)
- **Risk Envelope**: Correctly reads and applies 3%
- **Unified Sizing**: Correctly reads and applies 3%
- **Status**: ✅ CONSISTENT

### Venue Max Single Order Percentage
- **YAML Profile**: `venue.max_single_order_pct = 0.05` (5%)
- **Risk Envelope**: Reads with default 0.05 (5%)
- **Unified Sizing**: Reads from profile
- **Status**: ✅ CONSISTENT

### Per-Asset Max Contracts
- **YAML Profile**: BTC/ETH/SOL/XRP = 3 contracts, DOGE = 2 contracts
- **Risk Envelope**: Correctly reads and applies
- **Unified Sizing**: Correctly reads and applies
- **Status**: ✅ CONSISTENT

### Depth Thresholds
- **YAML Profile**: All assets have `min_depth_yes = 1`, `min_depth_no = 1`
- **Risk Envelope**: Correctly reads and applies
- **Status**: ✅ CONSISTENT

### Kelly Fraction
- **YAML Profile**: `kelly.kelly_fraction = 0.02` (2%)
- **Risk Envelope**: Correctly reads and applies
- **Status**: ✅ CONSISTENT

### Drawdown Limits
- **YAML Profile**: `drawdown_halt_pct = 0.20` (20%), `drawdown_unwind_pct = 0.25` (25%)
- **Risk Envelope**: Correctly reads and applies
- **Status**: ✅ CONSISTENT

---

## Asset Consistency Check

All 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) are treated consistently:

- **Per-Asset Max Notional**: All set to 3% ✅
- **Depth Thresholds**: All set to 1 contract ✅
- **Configuration Completeness**: All assets have full configuration ✅
- **No Skipped Assets**: All 5 assets are present and configured ✅

---

## Scaling Multiplier Impact Analysis

The following scaling multipliers are applied in `unified_sizing.py` in order:

1. **Dynamic Sizing Multiplier** (if enabled): Scales based on edge and confidence
2. **Time-of-Day Multiplier** (default 1.0): Currently disabled in YAML
3. **Regime Multiplier** (default 1.0): Currently hardcoded to 1.0
4. **TTE Multiplier** (default 1.0): Currently hardcoded to 1.0

**Risk Limit Interaction**:
- These multipliers are applied to `max_notional_usd` after it's computed from risk percentages
- They do NOT modify the underlying risk caps in the risk envelope
- **Potential Issue**: If multipliers > 1.0 are used, they could cause position sizes to exceed the configured risk caps

**Recommendation**:
Ensure that any multiplier > 1.0 is accompanied by a corresponding increase in the risk envelope caps, or cap the final position size at the risk envelope's `max_single_order_notional_usd`.

---

## Summary of Required Actions

### Critical (Must Fix)
1. **Align risk envelope `get_per_trade_risk_pct()` with profile configuration**
   - Either use the profile's 3% value, or document why tiered logic is needed
   - Remove the tiered logic if it's not required

2. **Update code defaults for `agent_max_notional_pct`**
   - Change defaults from 5% to 3% to match YAML profile
   - Update in both `crypto_15m_profile.py` and `kalshi_crypto_15m_risk_envelope.py`

### High Priority (Should Fix)
3. **Expose `per_trade_risk_pct` in `Crypto15mProfile` dataclass**
   - Add the field to the dataclass
   - Update agent grid config to use the profile value instead of default

### Low Priority (Nice to Have)
4. **Remove or safeguard disabled scaling code paths**
   - Remove time-of-day, regime, and TTE scaling if permanently disabled
   - Or add runtime checks to prevent re-enabling without risk envelope updates

---

## Conclusion

The MERID 15m Kalshi crypto trading stack has a solid foundation with consistent per-asset and venue-level risk limits. However, the per-trade risk percentage has diverged between the profile configuration and the risk envelope implementation, creating a single point of inconsistency that could lead to unexpected trading behavior.

The most critical issue is that the risk envelope's `get_per_trade_risk_pct()` method implements its own tiered logic that ignores the profile's 3% configuration. This should be aligned to ensure that the profile is the single source of truth for all risk parameters.

Overall, the system treats all 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) consistently, and the hard risk limits (3% per asset, 5% per 15m window) are respected in the configuration. The discrepancies are primarily in the code defaults and implementation details rather than the core risk architecture.
