# 15m Trading Gate Audit Report

**Date**: 2026-06-08  
**Profile**: kalshi_crypto_15m_v2  
**Scope**: All gates that can block trading for 15m crypto markets (BTC/ETH/SOL/XRP/DOGE)

---

## Executive Summary

**Kill Switch Status**: ✅ Cleared - `data/risk_kill_switch.json` reset to inactive state

**Gate Centralization Status**: 
- ✅ Spread caps: Profile-driven (guardrails_max_spread_cents: 70)
- ✅ Depth thresholds: Profile-driven (per-asset min_depth_yes/min_depth_no)
- ✅ Time to expiry: Profile-driven (guardrails_min_time_to_expiry_min: 2.5)
- ❌ Position limit: **HARDCODED** (max_position_value: 100000.0 in kill_switches.py)
- ⚠️ DOGE spot logging: Missing visibility (same as BTC/ETH/SOL/XRP)

---

## 1. Market Discovery / Scheduler Gates

### Entry Window (Time to Expiry)

**Profile Source**: `config/profiles/kalshi_crypto_15m.yaml`
```yaml
guardrails:
  min_time_to_expiry_min: 2.5  # 150 seconds
  max_entry_mins: 15.0  # Maximum time to expiry for entry
  min_entry_mins: 2.0   # Minimum time to expiry for entry
```

**Code Implementation**: `merid/prediction/agent_grid_15m.py`
- Line 1362: `MIN_TIME_TO_EXPIRY_FOR_ENTRY_MIN: int = 3` (default)
- Line 1383: Loads from profile: `MIN_TIME_TO_EXPIRY_FOR_ENTRY_MIN = int(profile.guardrails_min_time_to_expiry_min)`

**Status**: ✅ Profile-driven, but default (3) doesn't match profile (2.5)

**Issue**: Default value of 3 minutes in code conflicts with profile value of 2.5 minutes

**Fix Required**: Update default to match profile or remove default entirely

---

### Maintenance Windows / Trading Hours

**Profile Source**: Not in kalshi_crypto_15m.yaml (uses SessionConfig from agent grid)

**Code Implementation**: `merid/guard/trading_hours.py`
- Uses SessionConfig from kalshi_agent_grid.yaml

**Status**: ⚠️ Not profile-driven for 15m specifically

**Issue**: Trading hours guard may not be aligned with 15m market schedule

**Fix Required**: Add trading hours configuration to profile or verify SessionConfig is appropriate

---

## 2. Market Quality Gates

### Spread Cap

**Profile Source**: `config/profiles/kalshi_crypto_15m.yaml`
```yaml
guardrails:
  max_spread_cents: 70  # Increased from 40 to 70c for current market conditions
```

**Code Implementations**:
1. `merid/prediction/candidate_optimizer.py` line 105:
   ```python
   self.max_spread_cents = adapter.profile.guardrails_max_spread_cents
   ```
2. `merid/event_venues/kalshi/dynamic_window.py` line 141:
   ```python
   max_spread_cents = adapter.profile.guardrails_max_spread_cents
   ```

**Status**: ✅ Profile-driven, consistent across scheduler and optimizer

**Real Market Data**: Spreads observed at 45-61c on 15m crypto markets

**Assessment**: 70c cap is realistic for current conditions

---

### Depth Thresholds

**Profile Source**: `config/profiles/kalshi_crypto_15m.yaml` (per-asset)
```yaml
assets:
  BTC:
    min_depth_yes: 30
    min_depth_no: 30
  ETH:
    min_depth_yes: 30
    min_depth_no: 30
  SOL:
    min_depth_yes: 20
    min_depth_no: 20
  XRP:
    min_depth_yes: 10
    min_depth_no: 10
  DOGE:
    min_depth_yes: 5
    min_depth_no: 5
```

**Code Implementation**: `merid/prediction/agent_grid_15m.py`
- Line 1524: `_get_effective_depth_thresholds(asset, regime)` function
- Line 1564: Called during market eligibility check
- Reads from profile per-asset thresholds with regime multipliers

**Status**: ✅ Profile-driven with regime-based dynamic adjustment

**Assessment**: Tiered depth thresholds (Tier 1: 30, Tier 2: 10-20) are appropriate for liquidity differences

---

### Liquidity Score / TWO_SIDED Requirements

**Profile Source**: Not explicitly in kalshi_crypto_15m.yaml

**Code Implementation**: Likely in order router or venue adapter

**Status**: ⚠️ Needs investigation

**Issue**: TWO_SIDED requirements may be hardcoded

**Fix Required**: Audit TWO_SIDED logic and add to profile if needed

---

## 3. Spot Alignment Gates

### Spot Staleness SLA

**Profile Source**: Not in kalshi_crypto_15m.yaml

**Code Implementation**: Likely in spot service or alignment tracker

**Status**: ⚠️ Needs investigation

**Issue**: 30s staleness threshold may be hardcoded, not timing-aware

**Fix Required**: Add spot staleness configuration to profile with per-asset sensitivity

---

### Contract-Spot Alignment Tolerances

**Profile Source**: Not in kalshi_crypto_15m.yaml

**Code Implementation**: Likely in spot basis tracker

**Status**: ⚠️ Needs investigation

**Issue**: Max abs diff, max bps, max time skew may be hardcoded

**Fix Required**: Add alignment tolerances to profile with per-asset configuration

---

### DOGE Spot Visibility

**Current Status**: DOGE is in SUPPORTED_ASSETS and mapped to "DOGE-USD", but lacks explicit logging

**Code Gap**: No structured `SPOT-PRICE-VALID` logs for DOGE like BTC/ETH/SOL/XRP

**Fix Required**: Add DOGE spot logging in same locations as other assets

---

## 4. Edge / Strategy Gates

### Dynamic Minimum Edge Threshold

**Profile Source**: `config/profiles/kalshi_crypto_15m.yaml` (per-asset, tiered)
```yaml
assets:
  BTC:
    min_edge_early: 0.03  # 3%
    min_edge_mid: 0.03
    min_edge_late: 0.03
    min_edge_terminal: 0.04  # 4%
  ETH:
    min_edge_early: 0.03
    min_edge_mid: 0.03
    min_edge_late: 0.03
    min_edge_terminal: 0.04
  SOL:
    min_edge_early: 0.04  # 4%
    min_edge_mid: 0.04
    min_edge_late: 0.04
    min_edge_terminal: 0.05  # 5%
  XRP:
    min_edge_early: 0.04
    min_edge_mid: 0.04
    min_edge_late: 0.04
    min_edge_terminal: 0.05
  DOGE:
    min_edge_early: 0.04
    min_edge_mid: 0.04
    min_edge_late: 0.04
    min_edge_terminal: 0.05
```

**Code Implementation**: Profile-driven via crypto_15m_profile.py

**Status**: ✅ Profile-driven with tiered structure

**Assessment**: Tiered edge thresholds (3-4% for majors, 4-5% for alts) are appropriate

---

### Strategy-Specific Filters

**Profile Source**: Not in kalshi_crypto_15m.yaml

**Code Implementation**: Likely in individual agent specs or strategy modules

**Status**: ⚠️ Needs investigation

**Issue**: Patience filter, pullback, entry-timing filters may be hardcoded

**Fix Required**: Audit strategy filters and add to profile if needed

---

## 5. Risk & Sizing Gates

### Per-Trade Risk Budget

**Profile Source**: `config/profiles/kalshi_crypto_15m.yaml`
```yaml
guardrails:
  per_trade_risk_pct:
    value: 0.008  # 0.8% of capital per trade
    dynamic: bankroll
```

**Code Implementation**: Profile-driven via RiskEnvelopeService

**Status**: ✅ Profile-driven, bankroll-aware

**Assessment**: 0.8% per trade allows surviving 15-20 consecutive full-risk losses

---

### Per-Strip and Per-Cycle Limits

**Profile Source**: `config/profiles/kalshi_crypto_15m.yaml`
```yaml
throttling:
  per_strip_order_limit: 3  # Max 3 orders per 15-minute strip
  max_trades_per_cycle_global: 4  # Max 4 trades per 15m cycle across all assets
  max_trades_per_cycle_asset: 2  # Max 2 trades per 15m cycle per asset
  cooldown_after_loss_cycles: 2  # No new entry for 2 cycles after loss
```

**Code Implementation**: Profile-driven

**Status**: ✅ Profile-driven

**Assessment**: Conservative limits appropriate for 15m scalping

---

### Cooldown After Loss, Max Hold Seconds

**Profile Source**: Partially in kalshi_crypto_15m.yaml (cooldown_after_loss_cycles)

**Code Implementation**: Max hold seconds may be hardcoded

**Status**: ⚠️ Max hold seconds needs investigation

**Issue**: Max hold seconds invariant may be hardcoded

**Fix Required**: Add max hold seconds to profile

---

## 6. Execution / Kill Switch Gates

### Daily Loss Caps

**Profile Source**: `config/profiles/kalshi_crypto_15m.yaml`
```yaml
guardrails:
  daily_loss_enabled: true
  max_daily_loss_pct:
    test: 0.08  # 8% for test mode
    prod: 0.04  # 4% for prod mode
```

**Code Implementation**: `merid/risk/kill_switches.py`
- Lines 87-102: `get_profile_daily_loss_limit()` reads from profile
- Lines 504-537: Daily loss check in `can_trade()`

**Status**: ✅ Profile-driven

**Assessment**: 4% daily loss for prod is conservative, appropriate

---

### Position Limit (max_position_value)

**Profile Source**: ❌ **NOT IN PROFILE**

**Code Implementation**: `merid/risk/kill_switches.py`
- Line 182: `max_position_value: float = 100000.0` **HARDCODED**
- Lines 549-568: Position limit check in `can_trade()`

**Status**: ❌ **HARDCODED - CRITICAL GAP**

**Issue**: 
- $100k position limit is hardcoded in code
- Not profile-driven or bankroll-aware
- May be too restrictive or too loose depending on bankroll
- No per-asset or cluster-based limits

**Fix Required**: 
1. Add `max_position_value_usd` to profile
2. Make it bankroll-aware (percentage of capital)
3. Replace hardcoded 100000.0 with profile value
4. Consider per-asset or cluster-based limits

---

### Kill Switch Triggers

**Profile Source**: Partially in profile (daily loss, drawdown)

**Code Implementation**: `merid/risk/kill_switches.py`
- Position limit: Hardcoded (see above)
- Stale MD: Likely hardcoded
- Reconciliation failures: Likely hardcoded

**Status**: ⚠️ Some triggers are hardcoded

**Issue**: Kill switch triggers not all profile-driven

**Fix Required**: Audit all kill switch triggers and add to profile

---

### Execution Gate Decisions

**Profile Source**: Not in kalshi_crypto_15m.yaml

**Code Implementation**: `merid/execution_guard.py`

**Status**: ⚠️ Needs investigation

**Issue**: Execution gate decisions may use hardcoded thresholds

**Fix Required**: Audit execution gate and add profile-driven thresholds

---

## 7. Contradictions and Double-Gates

### Spread: Scheduler vs Optimizer vs Autonomous Gate

**Scheduler**: `merid/event_venues/kalshi/dynamic_window.py` line 141
- Uses: `adapter.profile.guardrails_max_spread_cents`

**Optimizer**: `merid/prediction/candidate_optimizer.py` line 105
- Uses: `adapter.profile.guardrails_max_spread_cents`

**Autonomous Gate**: Needs investigation

**Status**: ✅ No contradiction found (both use same profile value)

---

### Depth: Scheduler vs Risk Checks

**Scheduler**: `merid/prediction/agent_grid_15m.py` line 1564
- Uses: `_get_effective_depth_thresholds(asset, regime)` from profile

**Risk Checks**: Needs investigation

**Status**: ⚠️ Risk check depth logic needs verification

**Issue**: May have conflicting depth thresholds

**Fix Required**: Verify risk checks use same depth thresholds as scheduler

---

### Min Time to Expiry: Multiple Gates

**Scheduler**: `merid/prediction/agent_grid_15m.py` line 1362
- Uses: `MIN_TIME_TO_EXPIRY_FOR_ENTRY_MIN` (default 3, loads from profile 2.5)

**Other Gates**: Needs investigation

**Status**: ⚠️ Default (3) conflicts with profile (2.5)

**Issue**: Default value in code doesn't match profile

**Fix Required**: Update default to match profile or remove default

---

## 8. Real Market Comparison

### Spread: 45-61c observed vs 70c cap

**Assessment**: ✅ 70c cap is realistic, allows current market spreads

**Recommendation**: Monitor spreads, adjust if market conditions change

---

### Depth: Typical depths vs thresholds

**Data Needed**: Real orderbook depth logs for each asset

**Assessment**: Tiered thresholds (30/20/10/5) seem reasonable but need validation

**Recommendation**: Add depth logging to validate thresholds against real conditions

---

### Spot Staleness: Update frequency vs threshold

**Data Needed**: Spot update frequency for each asset

**Assessment**: 30s threshold may be too strict for DOGE during quiet periods

**Recommendation**: Add per-asset staleness thresholds with time-to-expiry sensitivity

---

## 9. Funnel Metrics Validation

**Metrics Available**:
- markets_seen
- markets_with_md
- markets_with_spot
- markets_passing_filters
- final_candidates
- signal_calls
- orders_submitted

**Status**: ⚠️ Metrics exist but not systematically monitored

**Issue**: No automated alerting on funnel drop-offs

**Fix Required**: Add funnel monitoring with alerts on abnormal drop-offs

---

## 10. Required Fixes (Priority Order)

### P0 - Critical (blocks 15m trading)

1. **Replace hardcoded max_position_value with profile-driven value**
   - File: `merid/risk/kill_switches.py` line 182
   - Add to profile: `guardrails.max_position_value_usd` or make bankroll-aware
   - Remove hardcoded 100000.0

### P1 - High (confusion, over-engineering)

2. **Fix MIN_TIME_TO_EXPIRY_FOR_ENTRY_MIN default mismatch**
   - File: `merid/prediction/agent_grid_15m.py` line 1362
   - Change default from 3 to 2.5 to match profile
   - Or remove default entirely

3. **Add DOGE spot visibility logging**
   - Add `SPOT-PRICE-VALID` logs for DOGE in same locations as BTC/ETH/SOL/XRP
   - Ensure DOGE appears in SIGNAL-INPUT/SIGNAL-EDGE logs

4. **Audit and add spot staleness configuration to profile**
   - Add per-asset staleness thresholds
   - Add time-to-expiry sensitivity

5. **Audit and add contract-spot alignment tolerances to profile**
   - Add max abs diff, max bps, max time skew
   - Make per-asset configurable

### P2 - Medium (cleanup, maintenance)

6. **Audit TWO_SIDED requirements**
   - Verify logic is appropriate for 15m markets
   - Add to profile if needed

7. **Audit strategy-specific filters**
   - Verify patience filter, pullback, entry-timing filters
   - Add to profile if needed

8. **Add max hold seconds to profile**
   - Make configurable instead of hardcoded

9. **Audit all kill switch triggers**
   - Ensure all are profile-driven
   - Add missing ones to profile

10. **Audit execution gate decisions**
    - Ensure thresholds are profile-driven
    - Add missing ones to profile

### P3 - Low (validation, monitoring)

11. **Verify risk checks use same depth thresholds as scheduler**
    - Ensure no contradictions

12. **Add depth logging to validate thresholds**
    - Monitor real orderbook depths
    - Adjust thresholds if needed

13. **Add funnel monitoring with alerts**
    - Alert on abnormal drop-offs
    - Track funnel health over time

---

## 11. Next Steps

1. Implement P0 fix (max_position_value)
2. Implement P1 fixes (TTE default, DOGE logging, spot staleness, alignment tolerances)
3. Run 15-30 minute monitoring session
4. Validate with funnel metrics
5. Adjust thresholds based on real market data
6. Implement P2/P3 fixes as needed

---

## 12. Notes for Re-enabling Kill Switches

**Current State**: Kill switch file cleared to inactive state

**Re-enabling**: When ready to re-enable manual kill switches:
1. Ensure all thresholds are profile-driven
2. Validate thresholds against real market data
3. Test with paper mode first
4. Monitor for spurious triggers
5. Adjust thresholds before enabling in live mode

**Configuration**: Kill switch will auto-reset for derived states (daily loss, position limit) but manual halts require explicit operator acknowledgment.
