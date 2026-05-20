# No Magic Numbers Audit Report

**Date**: 2026-01-11
**Scope**: Kalshi trading pipeline
**Policy**: All numeric thresholds must come from centralized named constants or config files

## Executive Summary

This audit identified **45+ violations** of the no-magic-numbers policy across the Kalshi trading modules. The most critical violations involve hardcoded price fallbacks (50¢), quantity limits, and probability thresholds embedded in trading logic.

## Critical Violations (Trading Logic)

### 1. 50¢ Price Fallback (Most Severe)

**Impact**: 20+ instances across 8 files

The hardcoded 50¢ fallback is the most pervasive violation. This value should be replaced with `DEFAULT_KALSHI_PRICE_CENTS` from `risk_parameters.py`.

**Files affected:**
- `venue_adapter.py:282` - `avg_price_cents = 50`
- `trading.py:172,182,189,197,207,213,221,231,237,245,255,261,291` - `price or 50` fallbacks
- `trading_enhanced.py:232,257` - similar fallbacks
- `kalshi_risk.py:312,336,470,485,2011` - multiple 50¢ fallbacks
- `client.py:1575,1660` - midpoint fallback 50¢
- `fills_ledger.py:1552,2591` - `avg_price_cents or 50`
- `collector.py:311,342` - trade price fallbacks
- `backtest.py:203` - backtest price fallback
- `rebalancer.py:157,259` - rebalancing price fallbacks
- `sentiment.py:455` - sentiment price fallback

**Remediation**: Replace all `50` with `DEFAULT_KALSHI_PRICE_CENTS` from `risk_parameters.py`

### 2. Price Difference Threshold (50¢)

**File**: `kalshi_risk.py:571`
```python
if price_diff > 50:
    # Detect unrealistic price jumps
```

**Remediation**: Replace with `MAX_PRICE_DIFFERENCE_CENTS` from `risk_parameters.py`

### 3. Universe Filtering Thresholds

**File**: `universe.py:57-60`
```python
min_volume: int = int(os.getenv("MERID_UNIVERSE_MIN_VOLUME", "50"))
min_open_interest: int = int(os.getenv("MERID_UNIVERSE_MIN_OI", "10"))
max_per_agent: int = int(os.getenv("MERID_UNIVERSE_MAX_PER_AGENT", "50"))
```

**Status**: These use env vars with defaults, but the defaults should be in `risk_parameters.py`

**Remediation**: Move default values to `risk_parameters.py` and reference them

### 4. Order Book Depth Thresholds

**File**: `unified_market_state.py:254`
```python
def depth_within_10_cents(self) -> int:
    return self.book.depth_within(10) if self.book else 0
```

**Remediation**: Replace `10` with `BOOK_DEPTH_WINDOW_CENTS` from `risk_parameters.py`

## Medium Priority Violations (Infrastructure)

### 5. Circuit Breaker Thresholds

**File**: `ws_bridge.py:165`
```python
self._CIRCUIT_BREAKER_THRESHOLD: int = 20  # v9: was 10, now 20 failures
```

**Remediation**: Move to `risk_parameters.py` as `WS_CIRCUIT_BREAKER_THRESHOLD`

### 6. Batch Size Limits

**File**: `ws_bridge.py:824`
```python
_MAX_BATCH_SIZE = 50
```

**File**: `ws.py:717`
```python
_BATCH_SIZE_HIGH_PRESSURE = 50
```

**Remediation**: Move to `risk_parameters.py` as `WS_MAX_BATCH_SIZE`

### 7. Time-Based Thresholds

**File**: `ws.py:126`
```python
self._drop_log_interval_s: float = 5.0
```

**File**: `unified_market_state.py:276`
```python
max_book_age_s: float = 5.0
```

**Remediation**: Move to `risk_parameters.py` as `DROP_LOG_INTERVAL_S` and `MAX_BOOK_AGE_S`

## Low Priority Violations (Non-Trading)

The following numeric literals are acceptable as they are:
- Array/list indices (e.g., `[:10]`, `[-50:]`)
- Loop counters (e.g., `for _ in range(50)`)
- Time constants in seconds (e.g., `time.sleep(0.5)`)
- Retry counts (e.g., `range(1, 4)`)
- Percentages for logging/display (e.g., `round(utilization * 100, 1)`)

These are considered "infrastructure constants" rather than "trading parameters."

## Remediation Plan

### Phase 1: Critical Trading Parameters (High Priority)
1. Add `DEFAULT_KALSHI_PRICE_CENTS = 50` to `risk_parameters.py`
2. Replace all 50¢ price fallbacks with the constant
3. Add `MAX_PRICE_DIFFERENCE_CENTS = 50` to `risk_parameters.py`
4. Replace price diff > 50 checks

### Phase 2: Universe Filtering (Medium Priority)
1. Move universe defaults to `risk_parameters.py`:
   - `UNIVERSE_MIN_VOLUME_DEFAULT = 50`
   - `UNIVERSE_MIN_OI_DEFAULT = 10`
   - `UNIVERSE_MAX_PER_AGENT_DEFAULT = 50`
2. Update `universe.py` to reference these constants

### Phase 3: WebSocket Infrastructure (Low Priority)
1. Add WebSocket-specific constants to `risk_parameters.py`
2. Update ws_bridge.py and ws.py to use them

## Validation Functions Added

The following validation functions have been implemented in `order_router.py` to enforce the no-magic-numbers policy at runtime:

1. `_validate_prob_price_consistency()` - Ensures model probability supports the order price
2. `_validate_deep_otm_policy()` - Rejects deep OTM "lotto tickets" (1-5¢ or 95-99¢)
3. `_validate_underlying_plausibility()` - Rejects implausible required moves
4. `_validate_position_lifecycle()` - Ensures every entry has an exit plan

These are wired into both `route_order()` (sync) and `route_order_async()` (async) paths.

## Policy Enforcement Going Forward

### Static Analysis
- Run `grep -r "50" merid/event_venues/kalshi/*.py` periodically to catch new violations
- Consider adding a pre-commit hook for magic number detection

### Code Review Checklist
- [ ] No hardcoded prices in trading logic (use `risk_parameters.py`)
- [ ] No hardcoded quantities (use `risk_parameters.py`)
- [ ] No hardcoded probabilities (use `risk_parameters.py`)
- [ ] All thresholds are configurable via env vars or constants
- [ ] New validation functions are called in order router

## Conclusion

The Kalshi pipeline has significant technical debt regarding magic numbers, with the 50¢ price fallback being the most critical issue. The centralized `risk_parameters.py` module provides the foundation for remediation, and the new validation functions provide runtime enforcement. Phase 1 remediation should be prioritized as it directly impacts trading logic.
