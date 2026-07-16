# Canonical Order of Risk Checks

**Document Version**: 2026-07-16  
**Purpose**: Define the single canonical order of risk checks for order routing in the 15m Kalshi crypto trading system.

## Overview

All orders must pass through risk checks in a specific, deterministic order. This document defines that canonical sequence to ensure consistent risk enforcement across all order routing paths.

## Canonical Risk Check Sequence

### Phase 1: Pre-Route Validation (OrderIntent Creation)

1. **Intent Validation** (`order_router.py`)
   - `_validate_price_band()` - Price must be in 10-75c canonical range
   - `_validate_signal_metadata()` - Signal metadata must be valid
   - `_validate_prob_price_consistency()` - Probability and price must be consistent
   - `_validate_deep_otm_policy()` - Deep OTM policy validation
   - `_validate_underlying_plausibility()` - Underlying asset must be plausible
   - `_validate_position_lifecycle()` - Position lifecycle must be valid
   - `_validate_deployment_safety()` - Deployment safety checks

### Phase 2: Midstream Risk Checks (Order Gate)

2. **Order Gate Checks** (`order_gate.py`)
   - Idempotency check (duplicate detection via `OrderDeduplicationCache`)
   - Fill awareness check (prevent stacking on same contract)
   - Lease check (if applicable)
   - Pre-trade risk gate checks

### Phase 3: Router-Level Risk Checks

3. **Router-Level Checks** (`order_router.py`)
   - `_check_duplicate_order()` - Duplicate order detection (DEPRECATED, use OrderDeduplicationCache)
   - `_check_open_resting_order()` - Anti-stacking guard for resting orders
   - `_check_toxicity_kill_switch()` - Toxicity kill switch check
   - `_check_intent_risk()` - Intent-level risk validation
   - `_check_bankroll_risk_cap()` - Bankroll risk cap check
   - `_check_market_regime_gate()` - Market regime gate check

### Phase 4: Unified Risk Manager (Single Source of Truth)

4. **Unified Risk Manager** (`unified_risk_manager.py`)
   - `check_order()` - Single entry point for all risk validation
   - Fixed $1 exposure cap enforcement (via `GlobalSlotAllocator`)
   - Per-trade limits (max 1 contract)
   - Drawdown checks (halt/unwind)
   - Rate limiting

### Phase 5: Slot Allocation

5. **Global Slot Allocator** (`global_slot_allocator.py`)
   - Slot allocation for $1 fixed exposure cap
   - Price range validation (10-75c)
   - Sequential trading rules per asset
   - Max contracts per order (1)

### Phase 6: Execution Path

6. **Execution-Specific Checks**
   - `_route_live()` - Live execution path checks
   - `_route_sync_non_live()` - Mock/paper execution path checks
   - Staleness checks for market data
   - Exposure tracking updates

## Risk Check Hierarchy

```
Intent Validation (Phase 1)
    ↓
Order Gate (Phase 2)
    ↓
Router-Level Checks (Phase 3)
    ↓
Unified Risk Manager (Phase 4) ← SINGLE SOURCE OF TRUTH
    ↓
Global Slot Allocator (Phase 5)
    ↓
Execution Path (Phase 6)
```

## Critical Invariants

1. **Unified Risk Manager is Single Source of Truth**: All risk checks must ultimately delegate to `UnifiedRiskManager.check_order()`
2. **Fixed $1 Exposure Cap**: Enforced via `GlobalSlotAllocator`, never percentage-based
3. **Canonical Price Range**: 10-75c enforced at multiple levels
4. **Max 1 Contract Per Order**: Enforced by slot allocator and risk manager
5. **5-Second Duplicate Window**: Aligned across `order_router.py` and `order_deduplication.py`

## Deprecated Components

The following components are deprecated and should not be used for new risk checks:

- `KalshiRiskManager` in `kalshi_risk.py` - Use `UnifiedRiskManager` instead
- `_check_duplicate_order()` in `order_router.py` - Use `OrderDeduplicationCache` instead
- Percentage-based allocation caps - Use fixed $1 exposure cap instead

## Entry Points

All order routing must go through one of these canonical entry points:

1. `route_order_async(intent: OrderIntent)` - Live execution (production)
2. `route_order(intent: OrderIntent)` - Mock/paper execution (testing)

Direct calls to internal functions are discouraged unless explicitly documented.

## Validation

To verify risk check order is maintained:

```python
# Test that all paths go through UnifiedRiskManager
from merid.risk.unified_risk_manager import get_unified_risk_manager

risk_mgr = get_unified_risk_manager()
allowed, reason = risk_mgr.check_order(
    ticker="KXBTC15M-...",
    contracts=1,
    price_cents=50,
    category="crypto",
    underlying="BTC"
)
```

## References

- `merid/risk/unified_risk_manager.py` - Single source of truth for risk
- `merid/risk/global_slot_allocator.py` - $1 exposure cap enforcement
- `merid/event_venues/kalshi/order_router.py` - Order routing logic
- `merid/event_venues/kalshi/order_gate.py` - Pre-trade gate
- `merid/event_venues/kalshi/order_deduplication.py` - Duplicate detection
