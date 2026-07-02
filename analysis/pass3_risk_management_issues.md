# Pass 3: Risk Management and Position Sizing Issues

## High-Leverage Issues Found

### BUG #16: Missing get_base_position_size() method
**Location**: `merid/loop_15m.py` line 2837 calls `self._risk_envelope.get_base_position_size()`
**Issue**: `KalshiCrypto15mRiskEnvelope` class does not have a `get_base_position_size()` method, but it's called in `_execute_candidate()`.
**Impact**: Will raise `AttributeError` when trying to execute a candidate, preventing all trading.
**Fix**: Add `get_base_position_size()` method to `KalshiCrypto15mRiskEnvelope` that returns the base position size based on profile configuration.

### BUG #17: Risk envelope uses two different initialization paths
**Location**: `merid/loop_15m.py` lines 907-908 and 662-667
**Issue**: Risk envelope is initialized in two different ways:
1. At startup: `get_kalshi_crypto_15m_risk_envelope()` which returns a `KalshiCrypto15mRiskEnvelope` object
2. During runtime: `_get_cached_envelope()` which returns a `RiskEnvelopeConfig` object from `RiskEnvelopeService`
**Impact**: The two objects have different interfaces and methods, causing confusion and potential errors.
**Fix**: Unify the risk envelope initialization to use a single source of truth.

### BUG #18: Depth thresholds duplicated between config and agent
**Location**: `merid/prediction/agent_grid_15m.py` (LeanAgentConfig) and `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`
**Issue**: Depth thresholds are defined in two places:
1. `LeanAgentConfig.min_depth_yes` and `min_depth_no` (hardcoded defaults)
2. `KalshiCrypto15mRiskEnvelope.asset_depth_thresholds` (from profile YAML)
**Impact**: Inconsistent depth thresholds - agent uses its own config instead of the authoritative profile values.
**Fix**: Remove depth thresholds from `LeanAgentConfig` and have agent read from risk envelope or profile.

### BUG #19: Position sizing uses risk multiplier but no base size calculation
**Location**: `merid/loop_15m.py` lines 2836-2840
**Issue**: Position sizing calls `get_base_position_size()` which doesn't exist, so the calculation will fail. Even if it existed, there's no clear logic for how base size is derived from bankroll and profile.
**Impact**: Position sizing is broken, preventing order execution.
**Fix**: Implement proper base position size calculation based on profile's `max_single_order_notional_usd` and contract price.

### BUG #20: No per-asset position tracking
**Location**: Risk management system
**Issue**: While there are per-asset notional caps in the risk envelope, there's no tracking of current positions per asset to enforce these caps.
**Impact**: Could exceed per-asset notional limits, leading to concentrated risk.
**Fix**: Implement per-asset position tracking and enforce caps before order execution.

### BUG #21: No concurrent trade limit enforcement
**Location**: Risk management system
**Issue**: Risk envelope has `max_concurrent_trades` but there's no tracking of active trades to enforce this limit.
**Impact**: Could exceed concurrent trade limit, increasing risk exposure.
**Fix**: Implement active trade tracking and enforce concurrent trade limit.

### BUG #22: Risk envelope drawdown tracking may be stale
**Location**: `merid/loop_15m.py` line 2564
**Issue**: `safe_update_envelope_equity()` is called but it's unclear if this properly updates drawdown based on real-time P&L.
**Impact**: Drawdown-based risk scaling may not reflect actual losses, leading to incorrect risk multipliers.
**Fix**: Ensure drawdown is calculated from real-time P&L, not just bankroll snapshots.

### BUG #23: No position size validation against min/max notional
**Location**: Order execution path
**Issue**: Position size is calculated but not validated against `min_notional_usd` and `max_single_order_notional_usd` from profile.
**Impact**: Could execute orders that violate profile constraints.
**Fix**: Add validation to ensure position size notional is within profile limits.

## Priority Fixes
1. BUG #16: Missing get_base_position_size() method (critical - blocks trading)
2. BUG #17: Unify risk envelope initialization paths (high - interface confusion)
3. BUG #18: Remove duplicate depth thresholds (medium - consistency)
4. BUG #19: Implement proper base position size calculation (critical - blocks trading)
5. BUG #20: Implement per-asset position tracking (high - risk enforcement)
