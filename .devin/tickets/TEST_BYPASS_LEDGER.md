# Test Bypass Ledger

This ledger documents all temporary test overrides added to verify the trading pipeline.
Each entry must be either:
- **REMOVED**: Code deleted and replaced with proper fix
- **FEATURE_FLAGGED**: Wrapped under a named feature flag that defaults to OFF
- **CONFIG_PARAMETERIZED**: Made configurable via profile/env with safe defaults

## Bypass Entries

### 1. Market State Store Skip
**File**: `merid/prediction/agent_grid_15m.py`
**Lines**: 489-533
**Description**: Commented out entire market state store read to force fallback path
**Reason**: Testing pipeline verification when market state had high prices (99c) that broke consistency checks
**Status**: REMOVED
**Fix Applied**: Restored market state store read, executable check now enforces live data requirement

### 2. Fallback Price Changed to 30c
**File**: `merid/prediction/agent_grid_15m.py`
**Lines**: 535-544
**Description**: Changed fallback from 50c to 30c to avoid model_prob clamp to 0.95
**Reason**: 99c market prices + 5% edge = 1.04 → clamped to 0.95 broke consistency check
**Status**: REMOVED
**Fix Applied**: Restored 50c fallback, fixed probability consistency logic to drop orders when edge is invalid

### 3. Entry Thresholds Lowered
**File**: `merid/prediction/agent_grid_15m.py`
**Lines**: 551-562
**Description**: Lowered spot price thresholds (BTC: 70000→60000, ETH: 3000→2000, etc.)
**Reason**: To ensure signals generate during testing with fallback spot prices
**Status**: REMOVED
**Fix Applied**: Restored production thresholds (BTC: 70000, ETH: 3000, SOL: 100, XRP: 1.5, DOGE: 0.15)

### 4. Forced Count Override
**File**: `merid/prediction/agent_grid_15m.py`
**Lines**: 591-599
**Description**: Forced count=10 when compute_order_size returns <= 0
**Reason**: Small bankroll ($36.58) caused sizing to return 0
**Status**: REMOVED
**Fix Applied**: Fixed compute_order_size call to use Decimal types, now returns count=0 for insufficient bankroll (proper fail-closed)

### 5. Model Prob Clamping with Edge
**File**: `merid/prediction/agent_grid_15m.py`
**Lines**: 273-277
**Description**: Added 5% edge then clamped to [0.05, 0.95]
**Reason**: To pass router validation while maintaining edge semantics
**Status**: REMOVED
**Fix Applied**: Implemented proper probability consistency: compute model_prob with edge, validate range [0.05, 0.95], drop order if out of range or no meaningful edge

### 6. Fallback Price Source Check Bypass
**File**: `merid/prediction/agent_grid_15m.py`
**Lines**: 691-716
**Description**: Commented out rejection for FALLBACK_50C price source
**Reason**: To allow trades on fallback data for pipeline verification
**Status**: REMOVED
**Fix Applied**: Restored check, now properly rejects trades on fallback data with "non_executable_fallback" reason

### 7. Notional Minimum Check Bypass
**File**: `merid/prediction/agent_grid_15m.py`
**Lines**: 749-763
**Description**: Commented out rejection for notional_below_minimum
**Reason**: DOGE_15M failed with 30c × 4 = $0.60 < $1.00 minimum
**Status**: REMOVED
**Fix Applied**: Restored check, now properly rejects trades below $1.00 minimum notional

## Root Causes Fixed

### Layer 1: Signal Generation & Sizing ✅
- **compute_order_size**: Was passing float bankroll instead of Decimal, causing incorrect sizing
- **Fix Applied**: Convert bankroll to Decimal before passing to compute_order_size
- **Result**: Function now correctly returns count=0 for insufficient bankroll (proper fail-closed behavior)

### Layer 2: Model Probability & Price Alignment ✅
- **model_prob computation**: Clamping broke consistency with implied_prob
- **Fix Applied**: Compute model_prob with edge, validate range [0.05, 0.95], drop order if out of range or no meaningful edge
- **Result**: Orders dropped cleanly when edge is invalid instead of being clamped and rejected by router

### Layer 3: Market Data & Fallback Paths ✅
- **executable check**: Was disabled to force trades
- **Fix Applied**: Restored check, now properly rejects trades when market not executable
- **fallback check**: Was disabled to allow trades on stale data
- **Fix Applied**: Restored check, now properly rejects trades on fallback data with "non_executable_fallback" reason

### Layer 4: Order Router Constraints ✅
- **min_notional sanity check**: Was bypassed in agent pre-trade validation
- **Fix Applied**: Restored check, now properly rejects trades below $1.00 minimum notional
- **Result**: Sizing must respect minimum notional before reaching router

## CI Check Plan

Add script to grep for test bypass patterns:
- `TESTING-OVERRIDE`
- `TEMPORARILY DISABLED`
- `TEMPORARY: Force`
- `FORCING MINIMUM FOR TESTING`

This script should fail in production builds if any patterns are found.
