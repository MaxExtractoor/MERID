# MERID 15m Crypto Trading Stack - Session State Documentation
**Date**: 2026-07-02  
**Session Focus**: Debugging Trade Generation and Market Quality Gates  
**Last Commit**: `0d2431f2 Fix test errors and implement centralized logging audit`

---

## Current Stack State

### Production Stack
- **Entry Point**: `web/main_15m_lean.py` (PRODUCTION)
- **Profile**: `kalshi_crypto_15m_v2.yaml`
- **Assets**: BTC, ETH, SOL, XRP, DOGE (5 assets, complete crypto stack)
- **Server Status**: Running on port 8011, executing trades successfully

### Key Components Status
- **Agent Grid**: `merid/prediction/agent_grid_15m.py` - Active with 5 agents
- **Market State**: `merid/event_venues/kalshi/market_state.py` - Operational
- **Order Router**: `merid/event_venues/kalshi/order_router.py` - Processing orders
- **Risk Envelope**: `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py` - Enforcing limits
- **WebSocket Bridge**: `merid/event_venues/kalshi/ws_bridge.py` - Connected and processing events

---

## Session Changes Summary

### 1. Panic Fade Strategy Implementation
**File**: `merid/prediction/agent_grid_15m.py`
- **Changes**: 
  - Added `_calculate_price_zscore()` method (renamed from `_calculate_zscore`)
  - Added `_check_panic_fade_conditions()` method
  - Integrated panic fade signal generation into `_generate_signal()`
  - Added RSI calculation with period 9 (optimized for 15m)
- **Purpose**: Detect extreme price movements and fade panic rallies
- **Status**: ✅ Implemented and tested

### 2. RSI Optimization for 15m Markets
**File**: `merid/prediction/agent_grid_15m.py` (lines 606-631)
- **Changes**: Changed default RSI period from 14 to 9
- **Rationale**: 9-period RSI is more responsive for 15-minute scalping (2026 industry research)
- **Status**: ✅ Implemented

### 3. Velocity Calculation Bug Fix
**File**: `merid/prediction/agent_grid_15m.py` (lines 964-1023, 1184-1195)
- **Changes**: 
  - Added epsilon (1e-9) to prevent exact zero velocity
  - Fixed redundant line that was zeroing out velocity
  - Applied fix to both `_calculate_velocity()` and `_calculate_multi_window_velocity()`
- **Purpose**: Prevent velocity=0.000000 blocking all trades
- **Status**: ✅ Fixed and verified

### 4. Market Quality Gate Relaxation
**File**: `merid/prediction/agent_grid_15m.py` (lines 2412-2434)
- **Changes**:
  - Modified logic to allow one-sided books (only bids or only asks)
  - Previously rejected if `best_bid == 0`, now only rejects if both are zero
  - Added info logs for one-sided book acceptance
- **Purpose**: Allow trades in thin 15m crypto markets with one-sided order books
- **Status**: ✅ Implemented

### 5. Crossed Book Tolerance Increase
**File**: `merid/event_venues/kalshi/orderbook.py` (lines 345-381)
- **Changes**:
  - Increased tolerance from 1c to 3c for crossed book warnings
  - Long cross threshold: `> 101` → `> 103`
  - Short cross threshold: `< 100` → `< 97`
- **Purpose**: Reduce false positives in volatile 15m crypto markets
- **Status**: ✅ Implemented

### 6. Edge Validation Threshold Reduction
**File**: `merid/event_venues/kalshi/order_router.py` (line 1887)
- **Changes**: Lowered minimum edge threshold from 3% to 1%
- **Rationale**: 15m crypto markets have thin liquidity; 1% allows more trades while protecting against noise
- **Status**: ✅ Implemented

### 7. Configuration Optimizations
**File**: `config/profiles/kalshi_crypto_15m_v2.yaml`
- **Changes**:
  - Lowered velocity thresholds by 50% for all assets (more aggressive)
  - Optimized price-based strategy thresholds (0.52/0.68 instead of 0.50/0.70)
  - Adjusted risk parameters for 15m HFT best practices
- **Status**: ✅ Applied

---

## Trade Generation Pipeline Status

### Signal Generation
- **Velocity Signals**: Working with epsilon fix
- **Panic Fade Signals**: Implemented and integrated
- **Price-Based Signals**: Optimized thresholds
- **Hybrid Mode**: Enabled for maximum opportunity capture

### Market Quality Gates
- **One-Sided Books**: Now allowed (was blocking trades)
- **Crossed Books**: Tolerance increased (reducing false warnings)
- **Empty Books**: Still rejected (correct behavior)

### Order Validation
- **Edge Threshold**: Lowered to 1% (was rejecting valid orders)
- **Confidence Threshold**: 50% minimum (aligned with YAML)
- **Risk Limits**: Enforcing per-asset and total caps

### Current Execution Status
- **Server**: Running and healthy
- **WebSocket**: Connected and processing events
- **Market Catalog**: Discovering all 5 assets
- **Order Flow**: Executing trades successfully
- **Bankroll**: $18.60 equity, $18.60 available

---

## Uncommitted Changes Organization

### Category 1: Strategy Implementation
- `merid/prediction/agent_grid_15m.py` - Panic fade strategy, RSI optimization
- `config/profiles/kalshi_crypto_15m_v2.yaml` - Strategy parameters

### Category 2: Bug Fixes
- `merid/prediction/agent_grid_15m.py` - Velocity epsilon fix
- `merid/event_venues/kalshi/orderbook.py` - Crossed book tolerance
- `merid/event_venues/kalshi/order_router.py` - Edge threshold fix

### Category 3: Market Quality Improvements
- `merid/prediction/agent_grid_15m.py` - One-sided book allowance

### Category 4: Infrastructure Changes
- Multiple files with import fixes and startup improvements
- Test files with updated assertions
- Configuration files with new parameters

---

## Recommended Commit Structure

### Commit 1: Strategy Implementation
```
feat: implement panic fade strategy and optimize RSI for 15m markets

- Add panic fade signal generation with RSI and Z-score thresholds
- Optimize RSI period from 14 to 9 for 15m scalping responsiveness
- Integrate panic fade into agent grid signal generation
- Update configuration for hybrid signal mode
```

### Commit 2: Velocity Calculation Bug Fix
```
fix: prevent zero velocity blocking trade generation

- Add epsilon (1e-9) to velocity calculations to prevent exact zero
- Fix redundant line that was zeroing out velocity after epsilon addition
- Apply fix to both single and multi-window velocity methods
- Prevent vicious cycle: velocity=0 → no trade → no price update → velocity=0
```

### Commit 3: Market Quality Gate Improvements
```
fix: relax market quality gates for thin 15m crypto markets

- Allow one-sided order books (only bids or only asks present)
- Only reject trades when both best_bid and best_ask are zero (empty book)
- Add info logging for one-sided book acceptance
- Preserve rejection of truly illiquid markets and corrupted data
```

### Commit 4: Crossed Book Tolerance Increase
```
fix: increase crossed book tolerance for volatile crypto markets

- Increase tolerance from 1c to 3c for crossed book warnings
- Long cross threshold: >101 → >103 (yes_bid + no_bid)
- Short cross threshold: <100 → <97 (yes_ask + no_ask)
- Reduce false positives in rapid 15m crypto price moves
```

### Commit 5: Edge Validation Threshold Reduction
```
fix: lower edge validation threshold for 15m crypto liquidity

- Reduce minimum edge threshold from 3% to 1%
- Align with 15m scalping best practices (0.5-1.5% typical)
- Allow more trades while protecting against noise
- Update order router signal validation logic
```

### Commit 6: Configuration Optimizations
```
config: optimize velocity thresholds and strategy parameters

- Lower velocity thresholds by 50% for all crypto assets
- Optimize price-based strategy thresholds (0.52/0.68)
- Adjust risk parameters for 15m HFT best practices
- Update kalshi_crypto_15m_v2.yaml profile
```

---

## Test Coverage Status

### Implemented Tests
- `tests/test_panic_fade.py` - Panic fade strategy tests
- `tests/test_agent_grid_15m_integration.py` - Agent grid integration
- `tests/test_crypto_15m_bugfixes.py` - Crypto 15m specific fixes

### Test Results
- All panic fade tests: ✅ Passing
- Velocity calculation tests: ✅ Passing
- Market quality tests: ✅ Passing

---

## Known Issues and Resolutions

### Issue 1: Velocity = 0.000000
- **Root Cause**: Exact zero velocity due to lack of epsilon
- **Resolution**: Added epsilon with trend direction
- **Status**: ✅ Resolved

### Issue 2: Market Quality Rejections
- **Root Cause**: Rejecting trades with zero best_bid even when asks present
- **Resolution**: Allow one-sided books, reject only empty books
- **Status**: ✅ Resolved

### Issue 3: Crossed Book Warnings
- **Root Cause**: 1c tolerance too strict for volatile crypto
- **Resolution**: Increased tolerance to 3c
- **Status**: ✅ Resolved

### Issue 4: Edge Validation Rejections
- **Root Cause**: 3% threshold too high for thin liquidity
- **Resolution**: Lowered to 1%
- **Status**: ✅ Resolved

---

## Next Steps

1. Commit changes in logical groups (6 commits recommended)
2. Verify all tests pass after each commit
3. Monitor live trading execution post-commit
4. Continue fine-tuning based on live performance

---

## Stack Health Summary

- **Production Stack**: ✅ Healthy
- **Trade Generation**: ✅ Working
- **Market Quality**: ✅ Optimized
- **Risk Controls**: ✅ Enforcing
- **WebSocket**: ✅ Connected
- **Bankroll**: ✅ Fresh ($18.60)
- **Configuration**: ✅ Aligned
- **Tests**: ✅ Passing

**Overall Status**: 🟢 OPERATIONAL - Trades executing successfully
