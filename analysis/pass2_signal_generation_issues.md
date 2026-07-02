# Pass 2: Signal Generation and Agent Grid Issues

## High-Leverage Issues Found

### BUG #7: Spread gate missing
**Location**: `merid/prediction/agent_grid_15m.py` - `_validate_market_state()` and `_generate_signal()`
**Issue**: Config has `max_spread_cents = 100` but spread is never checked in validation or signal generation. Comment says "Kept only: liquidity, spread, staleness" but spread gate is not implemented.
**Impact**: May trade on markets with excessive spread, leading to poor execution prices.
**Fix**: Add spread check using best_bid/ask from market_state_store.

### BUG #8: Time to expiry gate missing
**Location**: `merid/prediction/agent_grid_15m.py` - `_generate_signal()`
**Issue**: Config has `min_time_to_expiry_s = 180` and `max_time_to_expiry_s = 900` but these are never validated. minutes_to_expiry is calculated but not checked against thresholds.
**Impact**: May trade on markets too close to expiry (high theta decay) or too far from expiry (low time value).
**Fix**: Add time-to-expiry validation in `_validate_market_state()` or `_generate_signal()`.

### BUG #9: min_edge_pct not used
**Location**: `merid/prediction/agent_grid_15m.py` - `LeanAgentConfig`
**Issue**: Config has `min_edge_pct = 0.02` but this is never used. Signal is purely velocity-based without any edge threshold.
**Impact**: May trade without sufficient edge, leading to negative expected value trades.
**Fix**: Either remove unused config or implement edge-based filtering.

### BUG #10: per_strip_order_limit not enforced
**Location**: `merid/prediction/agent_grid_15m.py` - `LeanAgentConfig`
**Issue**: Config has `per_strip_order_limit = 5` but there's no tracking of orders per 15m strip.
**Impact**: Could exceed intended position density per strip, increasing risk.
**Fix**: Implement order tracking per strip and enforce limit.

### BUG #11: per_asset_cooldown not enforced
**Location**: `merid/prediction/agent_grid_15m.py` - `LeanAgentConfig`
**Issue**: Config has `per_asset_cooldown_s = 30` but there's no cooldown tracking logic.
**Impact**: Could over-trade on the same asset, increasing transaction costs and slippage.
**Fix**: Implement last trade timestamp tracking and enforce cooldown.

### BUG #12: Hardcoded depth threshold
**Location**: `merid/prediction/agent_grid_15m.py` - `_validate_market_state()` line 171
**Issue**: Depth check uses hardcoded `< 1` instead of configurable values.
**Impact**: Cannot adjust depth requirements per asset or market conditions.
**Fix**: Add depth thresholds to config and use them in validation.

### BUG #13: Hardcoded velocity threshold
**Location**: `merid/prediction/agent_grid_15m.py` - `_generate_signal()` line 225
**Issue**: Velocity threshold is hardcoded to `0.0002` instead of being configurable.
**Impact**: Cannot adjust sensitivity per asset or market regime.
**Fix**: Add velocity_threshold to config and use it in signal generation.

### BUG #14: No spread calculation
**Location**: `merid/prediction/agent_grid_15m.py` - `_generate_signal()`
**Issue**: best_bid and best_ask are read but spread is never calculated or validated.
**Impact**: Cannot enforce spread limits even if config has max_spread_cents.
**Fix**: Calculate spread = best_ask - best_bid and validate against max_spread_cents.

### BUG #15: Asset extraction is fragile
**Location**: `merid/prediction/agent_grid_15m.py` - `_generate_signal()` lines 190-204
**Issue**: Asset extraction uses string matching on ticker which could fail if ticker format changes.
**Impact**: Could fail to identify asset correctly, leading to wrong signal routing.
**Fix**: Use more robust asset identification (e.g., from market object or series ticker).

## Priority Fixes
1. BUG #7: Spread gate (high impact - execution quality)
2. BUG #8: Time to expiry gate (high impact - theta decay)
3. BUG #12: Hardcoded depth threshold (medium impact - flexibility)
4. BUG #13: Hardcoded velocity threshold (medium impact - flexibility)
5. BUG #11: per_asset_cooldown (medium impact - over-trading)
