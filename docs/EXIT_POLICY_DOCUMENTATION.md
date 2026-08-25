# Exit Policy Code Documentation

## Overview

This document provides a comprehensive end-to-end trace of the exit policy code in the MERID 15-minute Kalshi crypto trading system. The exit policy handles closing positions through various mechanisms including take profit, stop loss, trailing stops, ratchet profit floors, and policy-layer exits.

## Architecture

The exit policy is organized into three layers:

1. **Upstream (Exit Signal Generation)**: Detects when positions should exit
2. **Midstream (Exit Routing and Risk Checks)**: Routes exit orders through risk checks
3. **Downstream (Exit Execution and Fill Handling)**: Executes exit orders and processes fills

---

## 1. Upstream: Exit Signal Generation

### 1.1 PositionMonitor (`merid/position_management/position_monitor.py`)

**Purpose**: Main exit signal generator that monitors open positions and triggers exit conditions.

**Key Components**:
- `_check_position()`: Main position evaluation loop (line 202)
- `_emit_exit_intent()`: Emits exit intent via callback (line 1136)
- `_poll_loop()`: Main polling loop checking all positions (line 1305)

**Exit Triggers (evaluated in order of priority)**:

1. **AUTO_EXIT_99C** (Priority 95) - Cash out at 99c YES / 1c NO (near-settlement)
   - Location: line 255
   - Trigger: `position.should_trigger_auto_exit_99c(current_price_cents)`
   - Purpose: Lock in guaranteed wins near settlement

2. **DYNAMIC_TAKE_PROFIT** (Priority 80) - Laddered exits based on entry price zones
   - Location: line 308
   - Trigger: Configurable zones from profile (e.g., 25-30c → 50-60c)
   - Purpose: Frequent small wins strategy

3. **RATCHET_TRIM** (Priority 75) - Partial close at >80c
   - Location: line 458
   - Trigger: Price >= trim_threshold (80c) and size > trim_to_contracts
   - Purpose: Reduce position size while in profit zone

4. **RATCHET_FLOOR** (Priority 70) - Profit protection floor
   - Location: line 509
   - Trigger: Price <= floor_price (80c) after ratchet activation
   - Purpose: Lock in profits after reaching activation threshold

5. **STOP_LOSS** (Priority 60) - Stop loss trigger
   - Location: line 532
   - Trigger: `position.should_trigger_stop_loss(current_price_cents)`
   - Purpose: Limit losses

6. **TAKE_PROFIT** (Priority 55) - Take profit trigger
   - Location: line 556
   - Trigger: `position.should_trigger_take_profit(current_price_cents)`
   - Purpose: Lock in profits at target

7. **TRAIL** (Priority 25) - Trailing stop
   - Location: line 739
   - Trigger: `position.should_trigger_trail(current_price_cents)`
   - Purpose: Trail profits with market movement

8. **TIME_STOP** (Priority 40) - Volatility-adjusted time-based exit
   - Location: line 766 (emergency flatten), line 836 (staged exits)
   - Trigger: Time to expiry <= 60s (emergency) or staged time intervals
   - Purpose: Force exit before expiry

9. **Policy-Layer Exits** (via ExitPolicyResolver):
   - RISK (Priority 100) - Global risk kill switch
   - STALE_DATA (Priority 85) - Market data staleness
   - CANDLE_REVERSAL (Priority 50) - Momentum reversal
   - ADAPTIVE_TIMING (Priority 45) - Historical performance-based
   - EDGE_DECAY (Priority 35) - Edge threshold

**Callback Registration**:
- `register_exit_intent_callback()`: Register callback for exit intents (line 46)
- Callback signature: `callback(position, exit_reason, exit_price_cents, contracts_to_close)`

### 1.2 ExitPolicy (`merid/position_management/exit_policy.py`)

**Purpose**: Defines exit conditions and policy evaluation logic for policy-layer exits.

**Key Components**:
- `ExitReason` enum: All exit reason types (line 19)
- `ExitPolicy` class: Policy evaluation inputs and outputs (line 64)
- `evaluate()`: Main policy evaluation method (line 273)

**Exit Policy Precedence** (evaluated in this order):
1. RISK - Global risk layer kill switch (highest priority)
2. STALE_DATA - Exit when market data becomes stale (P0 safety fix)
3. CANDLE_REVERSAL - Momentum reversal signal
4. ADAPTIVE_TIMING - Historical performance-based optimal exit timing
5. TIME_STOP - Volatility-adjusted time-based exit
6. EDGE_DECAY - Exit when computed edge drops below threshold

**Policy Parameters**:
- `max_hold_seconds`: Default 900s (15 minutes)
- `min_edge_threshold`: Minimum edge to hold position
- `risk_kill_switch`: Global risk layer kill switch
- `volatility_hold_multipliers`: Volatility-based hold time adjustment

### 1.3 ExitDecision (`merid/position_management/exit_decision.py`)

**Purpose**: Unified exit decision DTO with single source of truth for precedence.

**Key Components**:
- `ExitPriority` enum: Exit precedence priority (line 19)
- `ExitDecision` dataclass: Exit decision DTO (line 62)
- `get_priority_for_reason()`: Map ExitReason to ExitPriority (line 103)

**Exit Priority Order** (highest to lowest):
1. RISK (100)
2. AUTO_EXIT_99C (95)
3. EXTREME_PROFIT (90) - deprecated
4. STALE_DATA (85)
5. DYNAMIC_TAKE_PROFIT (80)
6. RATCHET_TRIM (75)
7. RATCHET_FLOOR (70)
8. STOP_LOSS (60)
9. TAKE_PROFIT (55)
10. CANDLE_REVERSAL (50)
11. ADAPTIVE_TIMING (45)
12. TIME_STOP (40)
13. EDGE_DECAY (35)
14. SCALE_OUT (30)
15. TRAIL (25)
16. MANUAL (20)

### 1.4 ExitPolicyResolver (`merid/position_management/exit_policy_resolver.py`)

**Purpose**: Resolves exit policies and evaluates position exit conditions.

**Key Components**:
- `ExitPolicyResolver` class: Policy evaluation with configurable parameters (line 16)
- `resolve()`: Resolve exit policy (backward compatible) (line 54)
- `resolve_with_decision()`: Resolve and return ExitDecision directly (line 121)
- `set_risk_kill_switch()`: Set global risk kill switch (line 39)

**Singleton**: `get_exit_policy_resolver()` returns global singleton (line 175)

---

## 2. Midstream: Exit Routing and Risk Checks

### 2.1 loop_15m.py - Exit Intent Callback

**Purpose**: Main event loop that registers exit intent callback and executes exit orders.

**Key Components**:
- Exit intent callback registration (line 1230)
- `_execute_exit_order()`: Execute exit order when PositionMonitor triggers (line 1369)

**Exit Order Execution Flow**:

1. **Slot Allocation Bypass** (line 1392):
   ```python
   exit_request = AllocationRequest(
       agent_id="position_monitor",
       asset=asset or "unknown",
       ticker=position.market_id,
       entry_price_cents=exit_price_cents,
       edge_pct=0.0,
       spread_cents=0,
       confidence=0.5,
       is_exit_order=True  # CRITICAL: Mark as exit order to bypass allocation
   )
   ```
   - Exit orders bypass slot allocation via `is_exit_order=True`
   - Ensures positions can be closed even at full $1 capacity

2. **Thesis Side Invariant** (line 1441):
   ```python
   if hasattr(position, 'thesis_side'):
       thesis_side_str = position.thesis_side
       thesis_side = ThesisSide.from_outcome_side(thesis_side_str)
   ```
   - Uses immutable `thesis_side` instead of mutable `position.side`
   - Prevents side inversion bugs from REST API contamination
   - Falls back to `position.side` for legacy positions with warning

3. **Pure Function Exit Order Generation** (line 1468):
   ```python
   if not USE_LEGACY_DIRECTION_MAPPING and thesis_side:
       temp_position = StrategyPosition(
           ticker=position.market_id,
           thesis_side=thesis_side,
           size_fp=position.size,
           avg_entry_price_cents=int(position.avg_entry_price_cents)
       )
       exit_order = build_exit_order(temp_position, count, exit_price_cents)
   ```
   - Uses pure function from `strategy_positions.py` domain layer
   - Encapsulates direction mapping in one spot
   - Deterministic mapping from thesis to Kalshi format

4. **Order Routing** (line 1433):
   ```python
   from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
   ```

### 2.2 exit_order_utils.py - Centralized Exit Order Detection

**Purpose**: Provides shared exit order detection logic to ensure consistency across components.

**Key Components**:
- `EXIT_ORDER_MARKERS`: List of exit order source markers (line 15)
- `is_exit_order_from_source()`: Check if order is exit based on source (line 31)
- `is_exit_order_from_intent()`: Check if OrderIntent is exit (line 56)
- `is_exit_order_from_action()`: Check if order is exit based on action/source (line 73)

**Exit Order Markers**:
```python
EXIT_ORDER_MARKERS = [
    "take_profit",
    "stop_loss",
    "micro_scalp",
    "exit",
    "close",
    "ratchet",
    "trim",
    "scale_out",
    "hedge",  # Hedge orders reduce net exposure
    "hedge_engine",
    "offset_hedging",
    "position_monitor_exit",  # PositionMonitor exit orders
]
```

**Critical Fix (2026-07-15)**: Consolidated exit order detection to prevent divergence between `order_router._is_exit_order()` and `position_cache._is_exit_order_from_action()`.

### 2.3 order_router.py - Order Routing with Exit Order Bypass

**Purpose**: Routes orders through risk checks and execution paths with exit order bypass logic.

**Key Components**:
- `_is_exit_order()`: Check if intent is exit order (line 1574)
- Exit order bypasses at multiple risk checkpoints

**Exit Order Bypass Points**:

1. **Market Condition Checks** (line 5422):
   ```python
   if _is_exit:
       logger.info("[order-router] EXIT ORDER: %s — bypassing A5 market condition checks", intent.ticker)
   ```
   - Exit orders bypass market condition checks
   - Should execute even in bad market conditions to secure profits

2. **Order Group Risk Check** (line 5499):
   ```python
   # EXIT ORDERS BYPASS: Order group checks for exits - they REDUCE exposure
   ```

3. **Multiple Other Bypass Points**:
   - Line 1647: Slot allocation bypass
   - Line 2259: Category exposure bypass
   - Line 2277: Window exposure bypass
   - Line 2319: Global exposure bypass
   - Line 2347: Resting order bypass
   - Line 2399: Duplicate order bypass
   - Line 2410: Price repeat bypass

**Source Marker** (line 7835):
```python
allowed_sources = ["merid.prediction.agent_grid_15m", "kalshi_tools", "offset_hedging", "position_monitor_exit"]
```
- `position_monitor_exit` is used by PositionMonitor for exit orders

### 2.4 global_slot_allocator.py - Exit Orders Bypass Slot Allocation

**Purpose**: Manages global slot allocation for risk with exit order bypass.

**Key Components**:
- `AllocationRequest`: Request for slot allocation (line 60)
- `is_exit_order`: CRITICAL field - Exit orders bypass slot allocation (line 69)
- `request_allocation()`: Request slot allocation (line 203)

**Exit Order Bypass Logic** (line 221):
```python
if request.is_exit_order:
    logger.info(
        "[SLOT-ALLOCATOR] Exit order bypasses allocation: agent=%s asset=%s ticker=%s",
        request.agent_id, request.asset, request.ticker
    )
    return True, "EXIT_ORDER_BYPASS", None
```

**Key Rules**:
- Max 1 contract per trade (hard enforcement)
- Entry price must be 10-75c (hard enforcement)
- Total exposure across all 5 assets ≤ $1 (hard enforcement)
- Exit orders bypass all allocation checks

### 2.5 order_gate.py - Pre-trade Checks with Exit Order Handling

**Purpose**: Provides pre-trade checks and idempotent order store.

**Key Components**:
- `IdempotentOrderStore`: Manages idempotent order records
- `blocked_exit_policy`: Block orders without exit policy metadata (line 135)
- `check_price_repeat()`: Block repeat price executions (line 243)

**Exit Order Handling**:
- Exit orders bypass certain pre-trade checks
- Price repeat window: 60 seconds (reduced from 900s on 2026-07-12)
- Duplicate order window: 5 seconds (reduced from 60s on 2026-07-12)

### 2.6 strategy_positions.py - Pure Function Exit Order Generation

**Purpose**: Domain model for strategy positions with thesis_side as immutable invariant.

**Key Components**:
- `ThesisSide` enum: Strategy thesis side - immutable per position (line 22)
- `StrategyPosition` dataclass: Strategy position with thesis_side (line 80)
- `build_exit_order()`: Build exit order dict from strategy position (line 208)

**Thesis Side Invariant**:
- **Thesis side is immutable per position** - Set from entry intent and never changed
- **Exchange side is derived, not authoritative** - REST/WebSocket data used for quantity/price only
- **Exit orders are generated strictly as "flatten thesis"** - Computed from thesis_side at exit time

**Exit Order Generation** (line 208):
```python
def build_exit_order(position: StrategyPosition, qty_fp: int, price_cents: int) -> dict:
    # Exit invariants
    if position.size_fp <= 0:
        raise ValueError(f"Position size_fp must be positive for exit")
    
    outcome_side = thesis_to_outcome_side(position.thesis_side)
    
    # Deterministic mapping from thesis_side to Kalshi format
    if position.thesis_side == ThesisSide.YES:
        kalshi_side = "SELL_YES"  # Sell YES to close long YES
    else:
        kalshi_side = "SELL_NO"  # Sell NO to close long NO
    
    return {
        "market_ticker": position.ticker,
        "outcome_side": outcome_side,
        "action": "sell",
        "side": outcome_side,
        "kalshi_side": kalshi_side,
        "size_fp": qty_fp,
        "price_cents": price_cents,
        "thesis_side": position.thesis_side.value,
    }
```

---

## 3. Downstream: Exit Execution and Fill Handling

### 3.1 position_cache.py - Position Cache with Exit Fill Handling

**Purpose**: Real-time position cache updated from WebSocket fill events with exit fill handling.

**Key Components**:
- `KalshiPositionCache`: Main position cache class
- `on_fill()`: Handle fill events from WebSocket (line 400)
- `apply_fill()`: Update position state on fills (line 185)
- `_is_exit_order_from_action()`: Check if order is exit (line 400)

**Exit Fill Handling**:

1. **Exit Fill Detection** (line 824):
   ```python
   from merid.event_venues.kalshi.exit_order_utils import is_exit_order_from_action
   is_exit_fill = is_exit_order_from_action(action, source=client_order_id)
   ```

2. **Exit Fill Without Existing Position** (line 827):
   ```python
   if is_exit_fill:
       # Exit fill without existing position - desynchronized state
       logger.critical(
           "[POSITION-CACHE-EXIT-FILL-ERROR] market=%s side=%s action=%s contracts=%d price=%dc "
           "client_order_id=%s fill_id=%s - EXIT FILL WITHOUT EXISTING POSITION. "
           "This indicates a desynchronized state. Rejecting fill to prevent creating phantom position.",
           market_id, side, action, contracts, price_cents, client_order_id, fill_id
       )
       return  # Do NOT create a new position
   ```
   - **CRITICAL FIX (2026-07-21)**: Prevents creating phantom positions from exit fills
   - Prevents side inversion bugs where SELL_NO exit orders are treated as BUY_NO entry orders

3. **Exposure Release on Exit Fills** (line 666):
   ```python
   if agent_id and self._is_exit_order_from_action(action, source=client_order_id):
       envelope.record_position_closure(
           agent_id=agent_id,
           position_notional_usd=position_notional_usd,
           asset=asset
       )
   ```
   - Releases window exposure on exit fills
   - Releases global slot allocator slot on position closure (line 684)

4. **Exit Fill Invariant Check** (line 1215):
   ```python
   if action == "sell" and fill_id and self._fills_ledger:
       fill_record = self._fills_ledger.get_fill_by_id(fill_id)
       intent_side = payload.get('side', '')
       if intent_side and intent_side.lower() != position.thesis_side.lower():
           logger.critical(
               "[POSITION-CACHE-INVARIANT-ALARM] Exit fill side inversion detected! "
               "fill_id=%s market=%s thesis_side=%s but exit fill intent_side=%s",
               fill_id, market_id, position.thesis_side, intent_side
           )
   ```
   - **CRITICAL FIX (2026-07-21)**: Validates exit fill side matches thesis_side
   - Catches side inversion bugs at exit time

5. **Position Removal on Full Close** (line 1274):
   ```python
   if position.contracts == 0:
       from merid.position_management.position_monitor import get_position_monitor
       monitor = get_position_monitor()
       monitor.remove_position(market_id)
       del self._positions[market_id]
   ```
   - Removes position from PositionMonitor when fully closed
   - Deletes position from cache when fully closed

### 3.2 fills_ledger.py - Fill Ledger with Position Monitor Integration

**Purpose**: Records fills and integrates with PositionMonitor for exit policy enforcement.

**Key Components**:
- `_create_new_position()`: Create new position from fill (line 3020)
- PositionMonitor integration (line 3028)

**PositionMonitor Integration** (line 3028):
```python
from merid.position_management.position_monitor import get_position_monitor
monitor = get_position_monitor()

# CRITICAL FIX (2026-07-19): Validate position age before adding to PositionMonitor
if expiry_ts > 0 and now_ts > expiry_ts + 1800:  # 30 minutes
    logger.warning(
        "[FILLS-LEDGER-POSITION-MONITOR] Skipping stale position for monitor: "
        "market=%s expired %d seconds ago (>30m threshold)",
        market_id, int(now_ts - expiry_ts)
    )
    return  # Skip adding to monitor

monitor.add_position(monitor_position)
```
- Adds positions to PositionMonitor for exit policy enforcement
- Validates position age to prevent stale positions from triggering exits
- Only adds positions from current or recent 15-minute windows

### 3.3 apply_fill Methods - Fill Application Logic

**Purpose**: Update position state on fills with exit fill handling.

**Location**: 
- `position_cache.py`: `CachedPosition.apply_fill()` (line 185)
- `position_sanity_checker.py`: `PositionSanityChecker.apply_fill()` (line 108)

**Fill Logic**:
- Distinguishes between opening and closing fills based on action and side
- Correctly handles partial and full closes
- Updates realized PnL
- Logs reconciliation audits

---

## 4. Critical Invariants and Fixes

### 4.1 Thesis Side Invariant (2026-07-21)

**Problem**: Exit orders were being placed on the wrong side due to position cache side being overwritten by Kalshi's REST API.

**Root Cause**: Kalshi's REST API always reports `side="yes"` because they quote from the YES side perspective, which inverted NO positions to YES positions.

**Core Invariants Enforced**:
1. **Thesis side is immutable per position** - Set from entry intent and never changed by REST sync
2. **Exchange side is derived, not authoritative** - REST/WebSocket data used for quantity/price only, never for side
3. **Exit orders are generated strictly as "flatten thesis"** - Computed from thesis_side at exit time, not from mutable cache

**Implementation**:
- `CachedPosition` model: Added `thesis_side` field as immutable strategy thesis invariant
- Position creation: Set `thesis_side` from entry intent during position creation
- REST sync: Preserves existing positions before clearing cache, uses preserved `thesis_side`
- Exit order logic: Uses `thesis_side` (immutable) instead of mutable `position.side`
- Runtime invariant checks: Entry fill validation, exit fill validation, REST sync validation

**Files Modified**:
- `merid/event_venues/kalshi/position_cache.py`
- `merid/loop_15m.py`
- `merid/event_venues/kalshi/strategy_positions.py`
- `tests/test_thesis_side_invariant.py` (new test harness)
- `merid/event_venues/kalshi/thesis_side_monitor.py` (new monitoring module)

### 4.2 Exit Order Detection Consolidation (2026-07-15)

**Problem**: Duplicate logic in `order_router._is_exit_order()` and `position_cache._is_exit_order_from_action()` could diverge.

**Solution**: Created `exit_order_utils.py` to centralize exit order detection logic.

**Files Modified**:
- `merid/event_venues/kalshi/exit_order_utils.py` (new module)
- `merid/event_venues/kalshi/order_router.py` (uses exit_order_utils)
- `merid/event_venues/kalshi/position_cache.py` (uses exit_order_utils)

### 4.3 Duplicate Order Detection Fix (2026-07-12)

**Problem**: Orders were being rejected as duplicates within a 60-second window, causing 65.4% rejection rate.

**Fixes**:
- `order_router.py`: Reduced `_DUPLICATE_ORDER_WINDOW_SECONDS` from 60s to 5s
- `order_gate.py`: Reduced `_price_repeat_window_s` from 900s to 60s

### 4.4 Percentage-Based Allocation Pruning (2026-07-16)

**Directive**: All percentage-based ALLOCATION caps (3% per-trade, 5% cycle, 15% total, 25% category) are PRUNED. The $1 global slot allocator is the SINGLE SOURCE OF TRUTH for exposure.

**Convention**: `pct == 0.0` means DISABLED → component defers to fixed_exposure_cap_usd ($1).

---

## 5. Exit Order Flow Diagram

```
PositionMonitor (Upstream)
    |
    | 1. Poll positions every 5 seconds
    | 2. Check exit conditions (99c, TP, SL, ratchet, etc.)
    | 3. Emit exit intent via callback
    v
loop_15m.py (Midstream)
    |
    | 1. Receive exit intent callback
    | 2. Bypass slot allocation (is_exit_order=True)
    | 3. Use thesis_side for exit order generation
    | 4. Build exit order via pure function
    v
order_router.py (Midstream)
    |
    | 1. Check if exit order via is_exit_order_from_intent()
    | 2. Bypass market condition checks
    | 3. Bypass order group risk checks
    | 4. Bypass slot allocation
    | 5. Route to venue
    v
Kalshi Venue (Execution)
    |
    | 1. Submit exit order
    | 2. Receive fill confirmation
    v
position_cache.py (Downstream)
    |
    | 1. Receive fill event via WebSocket
    | 2. Detect exit fill via is_exit_order_from_action()
    | 3. Validate exit fill has existing position
    | 4. Validate exit fill side matches thesis_side
    | 5. Apply fill to position
    | 6. Release window exposure
    | 7. Release global slot allocator slot
    | 8. Remove position from PositionMonitor
    | 9. Delete position from cache if fully closed
    v
Position Closed
```

---

## 6. Exit Reason Reference

### Position-Level Exits (handled in position_monitor before policy evaluation):
- **AUTO_EXIT_99C** (95) - Cash out at 99c (near-settlement)
- **EXTREME_PROFIT** (90) - Deprecated - use AUTO_EXIT_99C
- **DYNAMIC_TAKE_PROFIT** (80) - Laddered exits
- **RATCHET_TRIM** (75) - Partial close at >80c
- **RATCHET_FLOOR** (70) - Profit protection
- **STOP_LOSS** (60) - Stop loss trigger
- **TAKE_PROFIT** (55) - Take profit trigger
- **TRAIL** (25) - Trailing stop

### Policy-Layer Exits (evaluated by ExitPolicy.evaluate()):
- **RISK** (100) - Global risk layer kill switch (highest priority)
- **STALE_DATA** (85) - Exit when market data becomes stale (P0 safety fix)
- **CANDLE_REVERSAL** (50) - Momentum reversal signal
- **ADAPTIVE_TIMING** (45) - Historical performance-based optimal exit timing
- **TIME_STOP** (40) - Volatility-adjusted time-based exit
- **EDGE_DECAY** (35) - Exit when computed edge drops below threshold

### Other Exits:
- **SCALE_OUT** (30) - Partial exit at 1.5-2R
- **MANUAL** (20) - Manual exit

---

## 7. Configuration

### Profile Configuration (`config/profiles/kalshi_crypto_15m_v2.yaml`)

Key exit-related configuration:
- `trailing_stop_enabled`: Enable trailing stops
- `trailing_stop_trailing_distance_cents`: Trailing distance (default 5c)
- `trailing_stop_min_profit_cents`: Minimum profit before trailing (default 12c)
- `trailing_stop_activation_delay_sec`: Activation delay (default 30s)
- `ratchet_profit_floor_enabled`: Enable ratchet profit floor
- `ratchet_activation_threshold_cents`: Activation threshold (default 85c)
- `ratchet_floor_offset_cents`: Floor offset (default 5c)
- `ratchet_force_exit_on_floor_breach`: Force exit on floor breach
- `ratchet_trim_position_enabled`: Enable position trimming
- `ratchet_trim_threshold_cents`: Trim threshold (default 80c)
- `ratchet_trim_to_contracts`: Trim to contracts (default 1)
- `dynamic_take_profit`: Dynamic take profit configuration
- `staged_time_exit`: Staged time exit configuration

### Risk Limits

- `MERID_FIXED_EXPOSURE_CAP_USD`: $1.00 (fixed dollar exposure cap)
- Exit orders bypass all allocation checks
- Entry price must be 10-75c (canonical range)

---

## 8. Testing

### Test Harnesses

1. **test_thesis_side_invariant.py**: Validates thesis_side invariant across kalshi_fills database
   - Checks for entry/exit side inversions per market
   - Checks for fill/intent side mismatches
   - Returns exit code 1 if failures detected

2. **test_robustness_fixes_2026.py**: Tests duplicate order detection fixes
   - TestDuplicateOrderDetectionFix (3 tests)
   - TestPriceRepeatWindowFix (3 tests)

### Running Tests

```bash
# Thesis side invariant test
py tests/test_thesis_side_invariant.py [limit]

# Robustness fixes
pytest tests/test_robustness_fixes_2026.py
```

---

## 9. Monitoring

### Thesis Side Monitor (`merid/event_venues/kalshi/thesis_side_monitor.py`)

**Purpose**: Tracks side inversion incidents and REST sync errors.

**Metrics**:
- Per-market and per-asset metrics
- Inversion rate calculation over time windows
- Threshold-based alerting

**Singleton**: `get_thesis_side_monitor()`

### Logging

Key log prefixes for exit policy:
- `[POSITION-MONITOR]` - Position monitor events
- `[EXIT-INTENT]` - Exit intent emission
- `[EXIT-ORDER]` - Exit order execution
- `[EXIT-TRIGGER-AUDIT]` - Exit trigger evaluation
- `[POSITION-CACHE]` - Position cache events
- `[POSITION-CACHE-EXIT-FILL-ERROR]` - Exit fill errors
- `[POSITION-CACHE-INVARIANT-ALARM]` - Invariant violations
- `[SLOT-ALLOCATOR]` - Slot allocator events

---

## 10. Key Files Reference

### Upstream (Exit Signal Generation)
- `merid/position_management/position_monitor.py` - Main exit signal generator
- `merid/position_management/exit_policy.py` - Policy-layer exit conditions
- `merid/position_management/exit_decision.py` - Exit decision DTO
- `merid/position_management/exit_policy_resolver.py` - Policy evaluation

### Midstream (Exit Routing and Risk Checks)
- `merid/loop_15m.py` - Exit intent callback and order execution
- `merid/event_venues/kalshi/order_router.py` - Order routing with exit bypass
- `merid/event_venues/kalshi/exit_order_utils.py` - Centralized exit detection
- `merid/risk/global_slot_allocator.py` - Slot allocation with exit bypass
- `merid/event_venues/kalshi/order_gate.py` - Pre-trade checks
- `merid/event_venues/kalshi/strategy_positions.py` - Pure function exit generation

### Downstream (Exit Execution and Fill Handling)
- `merid/event_venues/kalshi/position_cache.py` - Position cache with exit fill handling
- `merid/event_venues/kalshi/fills_ledger.py` - Fill ledger with monitor integration
- `merid/event_venues/kalshi/position_sanity_checker.py` - Fill sanity checks

### Monitoring and Testing
- `merid/event_venues/kalshi/thesis_side_monitor.py` - Thesis side monitoring
- `tests/test_thesis_side_invariant.py` - Thesis side invariant test harness
- `tests/test_robustness_fixes_2026.py` - Duplicate order detection tests

---

## 11. Summary

The exit policy system is a comprehensive end-to-end mechanism for closing positions in the MERID 15-minute Kalshi crypto trading system. It consists of:

1. **Upstream**: PositionMonitor generates exit signals based on price structure (99c, TP, SL, ratchet, trailing) and policy-layer conditions (risk, stale data, timing, edge decay)

2. **Midstream**: Exit orders are routed through risk checks with bypass logic to ensure positions can be closed even at full capacity. The thesis_side invariant ensures exit orders are generated correctly regardless of REST API side representation.

3. **Downstream**: Exit fills are processed with invariant checks to prevent phantom positions and side inversion bugs. Exposure is released and positions are removed from monitoring upon closure.

**Critical Invariants**:
- Thesis side is immutable per position
- Exit orders bypass slot allocation
- Exit fills must have existing positions
- Exit fill side must match thesis_side

**Key Fixes**:
- Thesis side invariant (2026-07-21) - Prevents side inversion bugs
- Exit order detection consolidation (2026-07-15) - Prevents logic divergence
- Duplicate order detection fix (2026-07-12) - Reduces rejection rate
- Percentage-based allocation pruning (2026-07-16) - $1 fixed exposure cap
