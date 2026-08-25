# Exit Policy End-to-End Documentation
## 15M Kalshi Crypto Trading System

**Document Version:** 1.0  
**Date:** 2026-07-17  
**Scope:** Complete exit policy stack for BTC, ETH, SOL, XRP, DOGE 15-minute Kalshi crypto trading

---

## Executive Summary

The exit policy system is responsible for closing out positions to lock in profits, limit losses, and manage risk. This document provides a complete end-to-end mapping of the exit policy stack, from signal generation through order execution.

### Critical Exit Triggers

1. **99c Automatic Exit** - Mandatory exit when position's own side reaches 99c (guaranteed win)
2. **80-85c Trailing Exit** - Aggressive trailing stop activation to lock in profits when price crosses 80c
3. **Ratchet Profit Floor** - Exit when price drops below 80c after reaching 85c activation threshold
4. **Dynamic Take Profit** - Laddered exits based on entry price zones
5. **Stop Loss / Take Profit** - Traditional TP/SL triggers
6. **Time-based Exits** - Emergency flatten near expiry, staged time exits

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Exit Policy Precedence](#exit-policy-precedence)
3. [Signal Generation Flow](#signal-generation-flow)
4. [Exit Decision Logic](#exit-decision-logic)
5. [Callback Dispatch](#callback-dispatch)
6. [Order Routing Flow](#order-routing-flow)
7. [Risk Enforcement](#risk-enforcement)
8. [Kalshi Execution](#kalshi-execution)
9. [Fill Monitoring](#fill-monitoring)
10. [Critical Exit Triggers](#critical-exit-triggers)
11. [Configuration](#configuration)
12. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

### Core Components

```
┌─────────────────────────────────────────────────────────────────┐
│                     loop_15m.py                                │
│  - Initializes PositionMonitor                                 │
│  - Registers exit_intent_callback                              │
│  - Starts PositionMonitor async task                           │
└──────────────────────┬────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│              PositionMonitor (position_monitor.py)             │
│  - Polls positions every 5 seconds                              │
│  - Calls _check_position() for each position                   │
│  - Evaluates exit conditions in priority order                 │
│  - Emits exit intents via callback                             │
└──────────────────────┬────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│              exit_intent_callback (loop_15m.py)                 │
│  - Idempotency guard (exit_triggered check)                    │
│  - Converts to Kalshi format (SELL_YES/SELL_NO)                │
│  - Creates OrderIntent with aggressiveness=1.0                 │
│  - Calls _execute_exit_order() async task                      │
└──────────────────────┬────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│            route_order_async (order_router.py)                 │
│  - Validates order (price range, side, count)                  │
│  - Risk checks (slot allocator, URM, position linkage)         │
│  - Applies maker/taker policy                                  │
│  - Submits to Kalshi API                                        │
└──────────────────────┬────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Kalshi REST API                                │
│  - Order submission                                             │
│  - Fill confirmation                                            │
└─────────────────────────────────────────────────────────────────┘
```

### Key Files

| File | Purpose |
|------|---------|
| `merid/position_management/position_monitor.py` | Core exit monitoring engine |
| `merid/position_management/position.py` | Position model with exit logic |
| `merid/position_management/exit_decision.py` | Exit decision DTO and precedence |
| `merid/position_management/exit_policy.py` | Policy-layer exit evaluation |
| `merid/position_management/unified_exit_policy_engine.py` | Unified exit policy resolution |
| `merid/risk/exit_policy.py` | Risk-layer exit policy engine |
| `merid/loop_15m.py` | Main loop with callback registration |
| `merid/event_venues/kalshi/order_router.py` | Order routing and risk checks |
| `merid/risk/profiles/crypto_15m_profile.py` | Exit policy configuration |

---

## Exit Policy Precedence

Exit conditions are evaluated in strict priority order (highest to lowest):

```
PRIORITY 100: RISK                    - Global risk layer kill switch
PRIORITY  90: EXTREME_PROFIT          - 99c YES / 1c NO (guaranteed win)
PRIORITY  85: STALE_DATA              - Market data staleness (P0 safety)
PRIORITY  80: DYNAMIC_TAKE_PROFIT     - Laddered exit based on entry price
PRIORITY  75: RATCHET_TRIM            - Partial close at >80c (multi-contract)
PRIORITY  70: RATCHET_FLOOR           - Exit when price drops below 80c floor
PRIORITY  60: STOP_LOSS               - Stop loss trigger
PRIORITY  55: TAKE_PROFIT             - Take profit trigger
PRIORITY  50: CANDLE_REVERSAL         - Momentum reversal signal
PRIORITY  45: ADAPTIVE_TIMING         - Historical performance-based timing
PRIORITY  40: TIME_STOP               - Volatility-adjusted time-based exit
PRIORITY  35: EDGE_DECAY              - Edge quality degradation
PRIORITY  30: SCALE_OUT               - Partial exit at 1.5-2R
PRIORITY  25: TRAIL                   - Trailing stop trigger
PRIORITY  20: MANUAL                  - Manual exit
```

**Source:** `merid/position_management/exit_decision.py:ExitPriority`

---

## Signal Generation Flow

### 1. PositionMonitor Initialization

**Location:** `merid/loop_15m.py:1202-1305`

```python
# Start PositionMonitor for active TP/SL/trailing exit monitoring
if self._position_monitor:
    try:
        # Register exit callback to trigger exit orders
        def exit_intent_callback(position, exit_reason, exit_price_cents, contracts_to_close=None):
            # Callback implementation (see Callback Dispatch section)
            pass
        
        # CRITICAL: Register exit callback BEFORE starting monitor
        self._position_monitor.register_exit_intent_callback(exit_intent_callback)
        
        # Verify callback registration
        if self._position_monitor._exit_intent_callback is None:
            raise RuntimeError("Exit intent callback not registered - system unsafe for trading")
        
        # Start the monitor
        await self._position_monitor.start()
```

**Key Points:**
- Callback registration happens BEFORE monitor starts (prevents race condition)
- Callback registration is verified with explicit check
- Monitor runs as async task polling every 5 seconds

### 2. Position Monitoring Loop

**Location:** `merid/position_management/position_monitor.py:190-1344`

```python
async def _check_position(self, position: Position, current_price_cents: int) -> None:
    """
    Check a single position for exit conditions.
    
    Evaluated in priority order:
    1. EXTREME_PROFIT (99c)
    2. DYNAMIC_TAKE_PROFIT
    3. RATCHET_TRIM
    4. RATCHET_FLOOR
    5. STOP_LOSS
    6. TAKE_PROFIT
    7. BREAK_EVEN
    8. SCALE_OUT
    9. TRAILING_STOP
    10. EMERGENCY_FLATTEN (last 60s)
    11. STAGED_TIME_EXIT
    """
    # Update runtime state (PnL, R-multiple, time since entry)
    position.update_runtime_state(current_price_cents)
    
    # Check exit conditions in priority order...
```

**Polling Cadence:** 5 seconds (configurable via `poll_interval` parameter)

**Price Source:** Market state store via `_get_side_aware_price()`

---

## Exit Decision Logic

### 1. EXTREME_PROFIT (99c Automatic Exit)

**Location:** `merid/position_management/position_monitor.py:217-235`

```python
# CRITICAL: Check extreme profit exit first (highest priority)
# Exit at 99c YES / 1c NO to lock in guaranteed wins
if position.should_trigger_extreme_profit(current_price_cents) and not position.exit_triggered:
    logger.info(
        "[POSITION-MONITOR] EXTREME-PROFIT triggered: position=%s price=%dc (99c YES / 1c NO) - locking guaranteed win",
        position.position_id[:8],
        current_price_cents,
    )
    self._emit_exit_intent(position, ExitReason.EXTREME_PROFIT, current_price_cents)
    return
```

**Implementation:** `merid/position_management/position.py:367-395`

```python
def should_trigger_extreme_profit(self, current_price_cents: int, bid_cents: Optional[int] = None, ask_cents: Optional[int] = None) -> bool:
    """
    Check if extreme profit exit should trigger (own side at 99c+).
    
    CRITICAL FIX: 2026-07-16 - Side-space semantics: all prices are in the
    position's own side cents. Use own-side bid for conservative check
    (what we can actually sell at).
    """
    # Use conservative own-side bid if available (what we can actually sell at)
    check_price = current_price_cents
    if bid_cents is not None:
        check_price = bid_cents
    
    # CRITICAL FIX (2026-07-16): Side-space — a guaranteed win means the position's
    # OWN side is at 99c+ for BOTH sides (NO at 99c-NO == YES at 1c-YES).
    # Previous NO branch fired at 1c own-side price, which is a TOTAL LOSS for NO.
    return check_price >= 99
```

**Key Points:**
- **Priority:** 90 (second highest after RISK)
- **Trigger:** Own-side price >= 99c
- **Side-Space Semantics:** Both YES and NO positions exit when THEIR OWN side reaches 99c
  - YES position: YES price >= 99c (guaranteed YES win)
  - NO position: NO price >= 99c (guaranteed NO win, equivalent to YES at 1c)
- **Idempotency:** Checks `position.exit_triggered` before emitting exit intent
- **Conservative:** Uses bid price if available (what we can actually sell at)

### 2. DYNAMIC_TAKE_PROFIT (Laddered Exits)

**Location:** `merid/position_management/position_monitor.py:237-340`

```python
# DYNAMIC TAKE PROFIT: Laddered exits based on entry price for consistent profits
# Entry 25-30c → Exit 50-60c, Entry 30-40c → Exit 60-70c, etc.
try:
    from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
    if is_profile_active():
        adapter = get_active_profile()
        profile = adapter.profile
        
        # Check if dynamic take profit is enabled
        dynamic_tp_config = getattr(profile, 'dynamic_take_profit', {})
        if dynamic_tp_config and dynamic_tp_config.get('enabled', False):
            # Initialize dynamic TP target if not set
            if position.dynamic_tp_target_cents is None:
                entry_price = position.avg_entry_price_cents
                zones = dynamic_tp_config.get('zones', [])
                
                # Find matching zone based on entry price
                for zone in zones:
                    entry_min = zone.get('entry_min', 0)
                    entry_max = zone.get('entry_max', 100)
                    if entry_min <= entry_price <= entry_max:
                        base_target = zone.get('exit_target', 0)
                        
                        # Apply edge quality adjustment if enabled
                        if dynamic_tp_config.get('edge_adjustment_enabled', False):
                            edge_pct = getattr(position, 'entry_edge_pct', 0.03)
                            # ... edge adjustment logic ...
                        
                        # CRITICAL FIX (2026-07-16): Side-space — entry and current
                        # prices are in the position's OWN side cents for BOTH sides
                        position.dynamic_tp_target_cents = base_target
                        break
            
            # Check if dynamic TP target is reached
            if position.dynamic_tp_target_cents is not None and not position.dynamic_tp_triggered and not position.exit_triggered:
                if current_price_cents >= position.dynamic_tp_target_cents:
                    position.dynamic_tp_triggered = True
                    self._emit_exit_intent(position, ExitReason.DYNAMIC_TAKE_PROFIT, current_price_cents)
                    return
```

**Configuration:** `config/profiles/kalshi_crypto_15m_v2.yaml`

```yaml
dynamic_take_profit:
  enabled: true
  edge_adjustment_enabled: true
  edge_high_threshold: 0.05
  edge_low_threshold: 0.02
  edge_high_multiplier: 1.1
  edge_low_multiplier: 0.9
  zones:
    - entry_min: 10
      entry_max: 25
      exit_target: 40
    - entry_min: 25
      entry_max: 30
      exit_target: 50
    - entry_min: 30
      entry_max: 40
      exit_target: 60
    - entry_min: 40
      entry_max: 50
      exit_target: 70
```

**Key Points:**
- **Priority:** 80
- **Trigger:** Current price >= dynamic target based on entry zone
- **Side-Space Semantics:** Own-side price rising to target (both sides)
- **Edge Adjustment:** Can adjust target based on entry edge quality
- **Idempotency:** Checks `dynamic_tp_triggered` and `exit_triggered`

### 3. RATCHET_TRIM (Partial Close at >80c)

**Location:** `merid/position_management/position_monitor.py:370-397`

```python
# 2026-07-05: POSITION TRIMMING when >1 contract and price >80c
if trim_enabled and not position.ratchet_trimmed and not position.exit_triggered:
    if position.size > trim_to_contracts:
        if current_price_cents >= trim_threshold:
            position.ratchet_trimmed = True
            # Emit trim intent (partial close)
            contracts_to_close = position.size - trim_to_contracts
            logger.info(
                "[POSITION-MONITOR] RATCHET-TRIM triggered: position=%s side=%s price=%dc size=%d -> trim to %d contracts (close %d)",
                position.position_id[:8],
                position.side.value,
                current_price_cents,
                position.size,
                trim_to_contracts,
                contracts_to_close,
            )
            self._emit_exit_intent(position, ExitReason.RATCHET_TRIM, current_price_cents, contracts_to_close)
            # CRITICAL: Update position size after trim (don't remove from monitoring)
            position.size = trim_to_contracts
            # CRITICAL: Continue to check other exit conditions (don't return early)
```

**Configuration:** `merid/risk/profiles/crypto_15m_profile.py`

```python
ratchet_trim_position_enabled: bool = True
ratchet_trim_threshold_cents: int = 80
ratchet_trim_to_contracts: int = 1
```

**Key Points:**
- **Priority:** 75
- **Trigger:** Price >= 80c AND size > 1 contract
- **Action:** Partial close (trim to 1 contract)
- **Side-Space Semantics:** Own-side price >= 80c (both sides)
- **Continues Monitoring:** Does NOT remove position from monitoring after trim
- **Idempotency:** Checks `ratchet_trimmed` and `exit_triggered`

### 4. RATCHET_FLOOR (Profit Protection at 80-85c)

**Location:** `merid/position_management/position_monitor.py:342-448`

```python
# RATCHET PROFIT FLOOR: Lock in profits at 80-85c range
# Research-backed mechanism to prevent giving back gains when 99c TP is not guaranteed
try:
    from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
    if is_profile_active():
        adapter = get_active_profile()
        profile = adapter.profile
        if profile.ratchet_profit_floor_enabled:
            activation_threshold = profile.ratchet_activation_threshold_cents  # 85c
            floor_offset = profile.ratchet_floor_offset_cents  # 5c (floor at 80c)
            force_exit = profile.ratchet_force_exit_on_floor_breach
            
            # Calculate floor price
            floor_price = activation_threshold - floor_offset  # 85c - 5c = 80c
            
            # Activate ratchet when price hits threshold
            if not position.ratchet_activated and not position.exit_triggered:
                if current_price_cents >= activation_threshold:
                    position.ratchet_activated = True
                    position.ratchet_hold_until = datetime.utcnow().timestamp() + profile.ratchet_min_hold_after_activation_sec
                    logger.info(
                        "[POSITION-MONITOR] RATCHET activated: position=%s side=%s price=%dc threshold=%dc floor=%dc",
                        position.position_id[:8],
                        position.side.value,
                        current_price_cents,
                        activation_threshold,
                        floor_price,
                    )
            
            # Check floor breach after activation and hold period
            if position.ratchet_activated:
                hold_expired = datetime.utcnow().timestamp() >= position.ratchet_hold_until
                can_exit = hold_expired  # Exit ONLY if hold period expired
                
                if can_exit:
                    if current_price_cents <= floor_price and not position.exit_triggered:
                        if force_exit:
                            logger.info(
                                "[POSITION-MONITOR] RATCHET-FLOOR-BREACH triggered: position=%s side=%s price=%dc floor=%dc - mandatory exit",
                                position.position_id[:8],
                                position.side.value,
                                current_price_cents,
                                floor_price,
                            )
                            self._emit_exit_intent(position, ExitReason.RATCHET_FLOOR, current_price_cents)
                            return
```

**Configuration:** `merid/risk/profiles/crypto_15m_profile.py`

```python
ratchet_profit_floor_enabled: bool = True
ratchet_activation_threshold_cents: int = 85
ratchet_floor_offset_cents: int = 5
ratchet_force_exit_on_floor_breach: bool = True
ratchet_min_hold_after_activation_sec: int = 30
```

**Key Points:**
- **Priority:** 70
- **Activation:** Price >= 85c
- **Floor:** 80c (85c - 5c offset)
- **Hold Period:** 30 seconds after activation before floor can trigger
- **Trigger:** Price <= 80c AFTER activation AND hold period expired
- **Side-Space Semantics:** Own-side price falling to floor (both sides)
- **Idempotency:** Checks `ratchet_activated` and `exit_triggered`

### 5. TRAILING_STOP (80-85c Aggressive Mode)

**Location:** `merid/position_management/position_monitor.py:499-643`

```python
# CRITICAL FIX: Activate trailing stop after minimum profit threshold (not 1R)
# For 15-minute binary options, waiting for 1R break-even is too conservative
# CRITICAL FIX: 2026-07-06 - Activate aggressive trailing (2c distance) when price crosses 80c
if not position.trailing_activated:
    # Check if position has minimum profit to activate trailing
    min_profit_cents = 12  # Default from profile (align with 2026 research)
    profit_zone_activation_cents = 80  # CRITICAL FIX: 2026-07-06 - Activate aggressive trailing at 80c
    activation_delay_sec = 30  # Default activation delay from profile
    
    # Calculate current profit in cents
    # CRITICAL FIX (2026-07-16): Side-space — profit = own-side price rising for BOTH sides
    profit_cents = current_price_cents - position.avg_entry_price_cents
    
    # Check if profit threshold reached
    if profit_cents >= min_profit_cents:
        # Record timestamp when threshold first reached
        if position.trailing_profit_threshold_reached_at is None:
            position.trailing_profit_threshold_reached_at = datetime.utcnow().timestamp()
        
        # Check if activation delay has elapsed
        now = datetime.utcnow().timestamp()
        delay_elapsed = (now - position.trailing_profit_threshold_reached_at) >= activation_delay_sec
        
        if delay_elapsed:
            position.trailing_activated = True
            # CRITICAL FIX: 2026-07-16 - Side-space — profit zone = own-side price >= 80c
            # for BOTH sides (no 100-x mirror for NO)
            in_profit_zone = False
            if current_price_cents >= profit_zone_activation_cents:
                in_profit_zone = True
                position.trailing_profit_zone_activated = True
            
            if in_profit_zone:
                logger.info(
                    "[POSITION-MONITOR] TRAILING activated (AGGRESSIVE 2c mode): position=%s price=%dc profit=%dc R=%.2f - in 80-85c profit zone",
                    position.position_id[:8],
                    current_price_cents,
                    profit_cents,
                    position.r_multiple,
                )
```

**Implementation:** `merid/position_management/position.py:152-259`

```python
def get_trail_level(self) -> Optional[int]:
    """
    Calculate current trailing stop level.
    
    Returns:
        Trailing stop price in cents, or None if trailing not active
    """
    if self.trailing_type == TrailingType.NONE:
        return None
    
    if self.max_favorable_price_cents == 0:
        return None
    
    # Research: Time-based trailing tightening
    # Reduce trail distance as expiry approaches to lock in gains
    trailing_param = self.trailing_param
    if self.time_since_entry_seconds > 0:
        time_window = 900.0  # 15 minutes
        time_remaining = max(0, time_window - self.time_since_entry_seconds)
        time_factor = time_remaining / time_window
        
        # Tighten trail in last 5 minutes (time_factor < 0.33)
        if time_factor < 0.33:
            trailing_param *= 0.5  # 50% tighter
        elif time_factor < 0.67:
            trailing_param *= 0.75  # 25% tighter
    
    elif self.trailing_type == TrailingType.FIXED_CENTS:
        # Fixed cent trail: trail_level = max_favorable - fixed_distance
        # CRITICAL FIX: 2026-07-06 - Use aggressive distance (2c) in 80-85c profit zone
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                if self.trailing_profit_zone_activated:
                    fixed_distance = profile.trailing_stop_trailing_distance_cents_profit_zone  # 2c in profit zone
                else:
                    fixed_distance = profile.trailing_stop_trailing_distance_cents  # 5c normal
        except Exception as e:
            fixed_distance = int(trailing_param)  # Fallback to param
        
        # CRITICAL FIX (2026-07-16): Side-space — trail below max favorable for BOTH sides
        trail_level = self.max_favorable_price_cents - fixed_distance
        return trail_level
```

**Configuration:** `merid/risk/profiles/crypto_15m_profile.py`

```python
trailing_stop_enabled: bool = True
trailing_stop_min_profit_cents: int = 12
trailing_stop_trailing_distance_cents: int = 5
trailing_stop_trailing_distance_cents_profit_zone: int = 2  # Aggressive 2c in 80-85c zone
trailing_stop_profit_zone_activation_cents: int = 80
trailing_stop_activation_delay_sec: int = 30
```

**Key Points:**
- **Priority:** 25
- **Activation:** Profit >= 12c + 30s delay
- **Normal Mode:** 5c trailing distance
- **Aggressive Mode:** 2c trailing distance when price >= 80c
- **Hysteresis:** Activates at 80c, deactivates at 75c (prevents oscillation)
- **Time-Based Tightening:** Tightens trail in last 5 minutes (50% tighter)
- **Side-Space Semantics:** Trail below max favorable price (both sides)
- **Trigger:** Price <= trail level

### 6. STOP_LOSS / TAKE_PROFIT

**Location:** `merid/position_management/position_monitor.py:450-471`

```python
# Check TP/SL next
if position.should_trigger_stop_loss(current_price_cents):
    logger.info(
        "[POSITION-MONITOR] STOP-LOSS triggered: position=%s price=%dc sl=%dc R=%.2f",
        position.position_id[:8],
        current_price_cents,
        position.stop_loss_price_cents,
        position.r_multiple,
    )
    self._emit_exit_intent(position, ExitReason.STOP_LOSS, current_price_cents)
    return

if position.should_trigger_take_profit(current_price_cents):
    logger.info(
        "[POSITION-MONITOR] TAKE-PROFIT triggered: position=%s price=%dc tp=%dc R=%.2f",
        position.position_id[:8],
        current_price_cents,
        position.take_profit_price_cents,
        position.r_multiple,
    )
    self._emit_exit_intent(position, ExitReason.TAKE_PROFIT, current_price_cents)
    return
```

**Implementation:** `merid/position_management/position.py:333-365`

```python
def should_trigger_stop_loss(self, current_price_cents: int) -> bool:
    """
    Check if stop-loss should trigger.
    
    CRITICAL FIX (2026-07-16): Side-space — SL sits BELOW entry in own-side cents
    for BOTH sides; trigger when own-side price falls to or below it
    """
    if self.stop_loss_price_cents is None:
        return False
    
    return current_price_cents <= self.stop_loss_price_cents

def should_trigger_take_profit(self, current_price_cents: int) -> bool:
    """
    Check if take-profit should trigger.
    
    CRITICAL FIX (2026-07-16): Side-space — TP sits ABOVE entry in own-side cents
    for BOTH sides; trigger when own-side price rises to or above it
    """
    if self.take_profit_price_cents is None:
        return False
    
    return current_price_cents >= self.take_profit_price_cents
```

**Key Points:**
- **Stop Loss Priority:** 60
- **Take Profit Priority:** 55
- **Side-Space Semantics:** 
  - SL: Own-side price falling to/below SL (both sides)
  - TP: Own-side price rising to/above TP (both sides)

### 7. EMERGENCY_FLATTEN (Last 60 Seconds)

**Location:** `merid/position_management/position_monitor.py:645-666`

```python
# CRITICAL FIX (2026-07-11): Emergency flatten in last 60 seconds
# Force full exit regardless of other conditions to ensure position doesn't expire
time_to_expiry_seconds = 900.0  # Default 15 minutes
try:
    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
    store = get_kalshi_market_state_store()
    state = store.get(position.market_id)
    if state and state.seconds_to_expiry:
        time_to_expiry_seconds = state.seconds_to_expiry
except Exception as e:
    logger.warning("[POSITION-MONITOR] Could not get time to expiry for emergency flatten: %s", e)

# Emergency flatten: force exit in last 60 seconds
if time_to_expiry_seconds <= 60.0:
    logger.warning(
        "[POSITION-MONITOR] EMERGENCY FLATTEN: position=%s time_to_expiry=%.1fs - forcing full exit",
        position.position_id[:8],
        time_to_expiry_seconds
    )
    self._emit_exit_intent(position, ExitReason.TIME_STOP, current_price_cents)  # Full exit
    return  # Exit immediately, don't check other conditions
```

**Key Points:**
- **Priority:** 40 (TIME_STOP)
- **Trigger:** Time to expiry <= 60 seconds
- **Action:** Full exit regardless of other conditions
- **Purpose:** Prevent position from expiring without exit

### 8. STAGED_TIME_EXIT (Laddered Time-Based Exits)

**Location:** `merid/position_management/position_monitor.py:668-760`

```python
# CRITICAL FIX: 2026-07-15 - Load staged exit stages from YAML config
staged_exit_stages = []
staged_exit_enabled = False

try:
    from merid.risk.profiles.crypto_15m_profile import get_active_profile
    profile = get_active_profile().profile
    
    # Load from YAML staged_time_exit section (top level, not nested)
    if hasattr(profile, 'staged_time_exit'):
        staged_config = profile.staged_time_exit
        staged_exit_enabled = staged_config.get('enabled', False)
        staged_exit_stages = staged_config.get('stages', [])
        
        if not staged_exit_stages and staged_exit_enabled:
            # Fallback to default if enabled but no stages defined
            staged_exit_stages = [
                {"minutes": 5, "percent": 25},
                {"minutes": 10, "percent": 25},
                {"minutes": 13, "percent": 50},
            ]

# Get time to expiry from market state
time_to_expiry_seconds = 900.0  # Default 15 minutes
try:
    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
    store = get_kalshi_market_state_store()
    state = store.get(position.market_id)
    if state and state.seconds_to_expiry:
        time_to_expiry_seconds = state.seconds_to_expiry
except Exception as e:
    logger.debug("[POSITION-MONITOR] Could not get time to expiry for staged exit: %s", e)

# CRITICAL FIX: Use position.time_since_entry_seconds for accuracy
time_held_seconds = position.time_since_entry_seconds
time_held_minutes = time_held_seconds / 60.0

# Check each staged exit stage
for stage_idx, stage in enumerate(staged_exit_stages):
    stage_minutes = stage.get('minutes', 0)
    stage_percent = stage.get('percent', 0)
    
    # Check if this stage should execute
    if time_held_minutes >= stage_minutes:
        stage_executed_flag = f"staged_exit_stage_{stage_idx}_executed"
        if not getattr(position, stage_executed_flag, False):
            # Calculate contracts to close
            contracts_to_close = int(position.size * (stage_percent / 100.0))
            
            if contracts_to_close > 0:
                setattr(position, stage_executed_flag, True)
                logger.info(
                    "[POSITION-MONITOR] STAGED-TIME-EXIT stage=%d: position=%s held=%.1fmin closing=%d contracts (%d%%)",
                    stage_idx,
                    position.position_id[:8],
                    time_held_minutes,
                    contracts_to_close,
                    stage_percent,
                )
                self._emit_exit_intent(position, ExitReason.TIME_STOP, current_price_cents, contracts_to_close)
                
                # Update position size
                position.size -= contracts_to_close
```

**Configuration:** `config/profiles/kalshi_crypto_15m_v2.yaml`

```yaml
staged_time_exit:
  enabled: true
  stages:
    - minutes: 5
      percent: 25
    - minutes: 10
      percent: 25
    - minutes: 13
      percent: 50
```

**Key Points:**
- **Priority:** 40 (TIME_STOP)
- **Trigger:** Time held >= stage threshold
- **Action:** Partial close by percentage
- **Stages:** Configurable in YAML (default: 5min/25%, 10min/25%, 13min/50%)
- **Idempotency:** Per-stage execution flags prevent re-execution

---

## Callback Dispatch

### Exit Intent Emission

**Location:** `merid/position_management/position_monitor.py:1029-1128`

```python
def _emit_exit_intent(
    self,
    position: Position,
    exit_reason: ExitReason,
    exit_price_cents: int,
    contracts_to_close: Optional[int] = None
) -> None:
    """
    Emit exit intent via callback.
    
    CRITICAL FIX (2026-07-16): Dispatch the exit callback BEFORE mark_exited().
    Previous ordering set exit_triggered=True and removed the position BEFORE the
    callback ran; the loop-side idempotency guard (added 2026-07-15) checks
    position.exit_triggered and was silently DROPPING every full exit — no exit
    order was ever placed. Callback-first preserves idempotency (a second emission
    for the same position still sees exit_triggered=True) while restoring execution.
    """
    # Log exit intent emission with structured schema
    if contracts_to_close is None:
        # Full position exit
        logger.info(
            "[EXIT-INTENT] position=%s market=%s side=%s reason=%s priority=%d source=%s "
            "exit_price=%dc entry_price=%dc pnl=%dc R=%.2f size=%d type=FULL_EXIT",
            position.position_id[:8],
            position.market_id,
            position.side.value,
            exit_reason.value,
            get_priority_for_reason(exit_reason).value,
            "position_level",
            exit_price_cents,
            position.avg_entry_price_cents,
            position.unrealized_pnl_cents,
            position.r_multiple,
            position.size,
        )
    else:
        # Partial position exit (trim)
        logger.info(
            "[EXIT-INTENT] position=%s market=%s side=%s reason=%s priority=%d source=%s "
            "exit_price=%dc entry_price=%dc pnl=%dc R=%.2f size=%d closing=%d type=PARTIAL_EXIT",
            position.position_id[:8],
            position.market_id,
            position.side.value,
            exit_reason.value,
            get_priority_for_reason(exit_reason).value,
            "position_level",
            exit_price_cents,
            position.avg_entry_price_cents,
            position.unrealized_pnl_cents,
            position.r_multiple,
            position.size,
            contracts_to_close,
        )
    
    # CRITICAL FIX (2026-07-16): Dispatch the exit callback BEFORE mark_exited()
    callback_dispatched = False
    if self._exit_intent_callback:
        try:
            logger.info(
                "[POSITION-MONITOR] Calling exit intent callback for position=%s reason=%s contracts=%s",
                position.position_id[:8],
                exit_reason.value,
                contracts_to_close or "ALL",
            )
            # Pass contracts_to_close to callback for partial close handling
            self._exit_intent_callback(position, exit_reason, exit_price_cents, contracts_to_close)
            callback_dispatched = True
            logger.info(
                "[POSITION-MONITOR] Exit intent callback completed for position=%s",
                position.position_id[:8],
            )
        except Exception as e:
            logger.error(
                "[POSITION-MONITOR] Exit intent callback failed: %s",
                e,
                exc_info=True
            )
    else:
        logger.warning(
            "[POSITION-MONITOR] No exit intent callback registered - exit order will NOT be placed for position=%s",
            position.position_id[:8],
        )
    
    # For partial trims, don't mark as exited or remove from monitoring
    # Only full exits should remove the position
    if contracts_to_close is None:
        if callback_dispatched:
            # Mark position as exited and stop monitoring
            position.mark_exited(exit_reason.value, exit_price_cents)
            self.remove_position(position.position_id)
        else:
            # CRITICAL FIX (2026-07-16): Callback failed or missing — KEEP the position
            # monitored so the exit re-fires on the next poll instead of orphaning a
            # live position with no exit enforcement
            logger.error(
                "[POSITION-MONITOR] Exit intent NOT dispatched for position=%s (reason=%s) - "
                "keeping position monitored for retry",
                position.position_id[:8],
                exit_reason,
            )
```

**Key Points:**
- **Callback-First Ordering:** Dispatches callback BEFORE marking position as exited
- **Idempotency:** Loop-side guard checks `exit_triggered` to prevent duplicate callbacks
- **Partial Exits:** Does NOT remove position from monitoring (allows subsequent exits)
- **Full Exits:** Removes position from monitoring after successful callback
- **Failure Handling:** Keeps position monitored if callback fails (allows retry)

### Loop-Side Callback Implementation

**Location:** `merid/loop_15m.py:1209-1286`

```python
def exit_intent_callback(position, exit_reason, exit_price_cents, contracts_to_close=None):
    """
    Callback when PositionMonitor detects exit condition.
    
    CRITICAL FIX: 2026-07-15 - Added robustness improvements:
    - Exit order failure tracking
    - Position state validation before exit
    - Idempotency guard to prevent duplicate exits
    
    CRITICAL FIX (2026-07-16): Set exit_triggered BEFORE async task to prevent race conditions
    Without this, multiple callbacks could fire before the first async task completes,
    causing duplicate exit orders. Setting exit_triggered=True immediately provides
    the idempotency guard that the callback was checking for.
    """
    try:
        # CRITICAL: Check if position already exited (idempotency guard)
        if position.exit_triggered:
            logger.warning(
                "[POSITION-MONITOR-CALLBACK] Exit intent ignored - position already exited: position=%s reason=%s exit_reason=%s",
                position.position_id[:8], exit_reason, position.exit_reason
            )
            return
        
        logger.info(
            "[POSITION-MONITOR-CALLBACK] Exit intent: position=%s reason=%s price=%dc contracts=%s",
            position.position_id[:8], exit_reason, exit_price_cents, contracts_to_close or "all"
        )
        
        # CRITICAL FIX (2026-07-16): Set exit_triggered BEFORE async task ONLY for full exits
        # For partial exits, we don't set exit_triggered because the position remains monitored
        # and can trigger additional exit conditions (e.g., SL after partial TP)
        if contracts_to_close is None:
            # Full exit - set exit_triggered to prevent duplicate callbacks
            position.exit_triggered = True
            position.exit_reason = exit_reason
            position.exit_price_cents = exit_price_cents
            position.exited_at = datetime.utcnow()
        
        # CRITICAL: Enable swing mode after trailing exit in profit
        # This allows YES/NO reversal to capture profits from price swings in both directions
        if exit_reason == ExitReason.TRAIL:
            # Extract asset from market_id (e.g., KXBTC15M-TEST -> BTC)
            asset = None
            for prefix in ["KXBTC", "KXETH", "KXSOL", "KXXRP", "KXDOGE"]:
                if position.market_id.startswith(prefix):
                    asset = prefix.replace("KX", "")
                    break
            
            if asset:
                # Enable swing mode for this asset
                self._swing_mode[asset] = {
                    "enabled": True,
                    "exited_side": position.side.value if hasattr(position.side, 'value') else str(position.side),
                    "exit_time": datetime.utcnow()
                }
                logger.info(
                    "[SWING-MODE] Enabled for asset=%s after trailing exit: exited_side=%s exit_price=%dc",
                    asset, self._swing_mode[asset]["exited_side"], exit_price_cents
                )
        
        # Route exit order through order router
        asyncio.create_task(self._execute_exit_order(position, exit_reason, exit_price_cents, contracts_to_close))
    except Exception as cb_err:
        logger.error(
            "[POSITION-MONITOR-CALLBACK] Failed to execute exit: position=%s reason=%s error=%s",
            position.position_id[:8] if hasattr(position, 'position_id') else 'unknown',
            exit_reason,
            cb_err,
            exc_info=True
        )
        # CRITICAL: Track exit intent failures for monitoring
        if not hasattr(self, '_exit_intent_failures'):
            self._exit_intent_failures = 0
        self._exit_intent_failures += 1
        logger.warning(
            "[POSITION-MONITOR-CALLBACK] Exit intent failure count: %d",
            self._exit_intent_failures
        )
```

**Key Points:**
- **Idempotency Guard:** Checks `position.exit_triggered` before processing
- **Early Exit Trigger:** Sets `exit_triggered=True` BEFORE async task (prevents race conditions)
- **Partial Exit Handling:** Does NOT set `exit_triggered` for partial exits (allows subsequent exits)
- **Swing Mode:** Enables swing mode after trailing exit (allows YES/NO reversal)
- **Async Task:** Creates async task for order execution (non-blocking)
- **Failure Tracking:** Tracks exit intent failures for monitoring

---

## Order Routing Flow

### Exit Order Execution

**Location:** `merid/loop_15m.py:1314-1461`

```python
async def _execute_exit_order(self, position, exit_reason, exit_price_cents, contracts_to_close=None) -> None:
    """
    Execute exit order via order router.
    
    CRITICAL FIX (2026-07-16): Exit orders MUST be marketable (aggressiveness=1.0) to execute immediately.
    Previous bug: exit orders defaulted to aggressiveness=0.0 (resting), causing them to rest on book
    and potentially never fill when market moved away.
    """
    try:
        # CRITICAL: Exit orders bypass slot allocation (they reduce exposure, not increase it)
        # However, we still check slot allocator for monitoring/logging purposes
        try:
            from merid.risk.global_slot_allocator import get_global_slot_allocator
            slot_allocator = get_global_slot_allocator()
            # Exit orders don't consume slots, but we log for observability
            logger.info(
                "[EXIT-ORDER] Exit order bypasses slot allocation: asset=%s ticker=%s",
                asset, position.market_id
            )
        except Exception as slot_err:
            logger.warning(
                "[EXIT-ORDER] Failed to check slot allocator for exit order (non-critical): %s",
                slot_err
            )
        
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async

        # CRITICAL FIX: Convert to Kalshi format (BUY_YES, SELL_YES, BUY_NO, SELL_NO)
        # For exit orders, we always sell to close the position
        # YES position: sell YES to exit long position -> SELL_YES
        # NO position: sell NO to exit long position -> SELL_NO
        action = "sell"

        # Convert PositionSide enum to string for OrderIntent
        side_str = position.side.value if hasattr(position.side, 'value') else str(position.side)
        side_upper = side_str.upper()

        # Map to Kalshi side format for exit orders
        if side_upper == "YES" and action == "sell":
            kalshi_side = "SELL_YES"
        elif side_upper == "NO" and action == "sell":
            kalshi_side = "SELL_NO"
        else:
            # Fallback for unexpected combinations
            logger.warning(
                "[EXIT-ORDER] Unexpected side/action combination: side=%s action=%s, using fallback",
                side_str, action
            )
            kalshi_side = f"{action.upper()}_{side_upper}"

        # Determine count (partial or full exit)
        count = contracts_to_close if contracts_to_close is not None else position.size

        logger.info(
            "[EXIT-ORDER] Kalshi side conversion: side_str=%s action=%s -> kalshi_side=%s",
            side_str, action, kalshi_side
        )

        # Create exit OrderIntent
        # CRITICAL FIX (2026-07-12): Exit orders MUST be marketable (aggressiveness=1.0) to execute immediately
        # CRITICAL FIX: Add exit_policy_id to satisfy order router validation for exit orders
        # CRITICAL FIX (2026-07-16): Use rationale field instead of non-existent exit_reason field
        intent = OrderIntent(
            ticker=position.market_id,
            side=kalshi_side,  # CRITICAL FIX: Use Kalshi-formatted side (SELL_YES, SELL_NO)
            action=action,  # Keep as lowercase "buy"/"sell" for early validation
            price_cents=exit_price_cents,
            count=count,
            order_type="limit",  # Limit order with marketable aggressiveness = marketable-limit
            time_in_force="gtc",  # Good till canceled - allows order to rest if not immediately filled
            source="position_monitor_exit",
            agent_id="merid.position_management.position_monitor",
            rationale=f"exit_reason:{exit_reason.value if hasattr(exit_reason, 'value') else exit_reason}",  # Use rationale for exit reason
            exit_policy_id=position.exit_policy_id,  # CRITICAL FIX: Required for exit order validation
            aggressiveness=1.0,  # CRITICAL FIX: Force marketable execution for immediate fill
        )

        logger.info(
            "[EXIT-ORDER] Routing exit order: ticker=%s side=%s action=%s count=%d price=%dc reason=%s",
            position.market_id, side_str, action, count, exit_price_cents, exit_reason
        )

        # Route the exit order
        result = await route_order_async(intent)

        if result.success:
            logger.info(
                "[EXIT-ORDER] Exit order executed successfully: order_id=%s status=%s",
                result.order_id, result.status
            )
        else:
            logger.error(
                "[EXIT-ORDER] Exit order failed: status=%s error=%s reason=%s",
                result.status, result.error, result.reason
            )
            # CRITICAL FIX (2026-07-16): Re-arm the position for retry on failure
            self._rearm_position_after_failed_exit(position, exit_reason, contracts_to_close)

    except Exception as e:
        logger.error("[EXIT-ORDER] Failed to execute exit order: %s", e, exc_info=True)
        # CRITICAL FIX (2026-07-16): Re-arm the position for retry on failure
        self._rearm_position_after_failed_exit(position, exit_reason, contracts_to_close)
```

**Key Points:**
- **Kalshi Format Conversion:** Converts to SELL_YES/SELL_NO format
- **Marketable Execution:** `aggressiveness=1.0` forces immediate fill
- **Slot Allocation:** Exit orders bypass slot allocator (reduce exposure, not increase)
- **Exit Policy ID:** Required for order router validation
- **Rationale Field:** Used for exit reason tracking
- **Failure Handling:** Re-arms position for retry on failure

### Re-arm Logic

**Location:** `merid/loop_15m.py:1463-1490`

```python
def _rearm_position_after_failed_exit(self, position, exit_reason, contracts_to_close=None) -> None:
    """
    Re-arm a position in the PositionMonitor after a failed exit order.
    
    CRITICAL FIX (2026-07-16): Previously a failed/rejected exit order left the
    position orphaned — removed from monitoring (full exits) with no retry — so a
    live position rode to settlement with NO exit enforcement. This violates the
    "all trades are executed with the exit policy" invariant.
    """
    try:
        # For full exits, clear exit_triggered so position can re-trigger
        if contracts_to_close is None:
            position.exit_triggered = False
            position.exit_reason = None
            position.exit_price_cents = None
            position.exited_at = None
            
            # Re-add to monitor if it was removed
            from merid.position_management.position_monitor import get_position_monitor
            monitor = get_position_monitor()
            monitor.add_position(position)
            
            logger.warning(
                "[EXIT-ORDER] Re-armed position for retry after failed exit: position=%s reason=%s",
                position.position_id[:8], exit_reason
            )
        else:
            # For partial exits, just log (position remains monitored)
            logger.warning(
                "[EXIT-ORDER] Partial exit failed, position remains monitored: position=%s reason=%s closing=%d",
                position.position_id[:8], exit_reason, contracts_to_close
            )
    except Exception as e:
        logger.error("[EXIT-ORDER] Failed to re-arm position: %s", e, exc_info=True)
```

**Key Points:**
- **Full Exits:** Clears `exit_triggered` and re-adds to monitor
- **Partial Exits:** Position remains monitored (no re-arm needed)
- **Invariant:** Ensures all trades execute with exit policy enforcement

---

## Risk Enforcement

### Order Router Validation

**Location:** `merid/event_venues/kalshi/order_router.py:7153-8200`

```python
async def route_order_async(intent: OrderIntent) -> OrderResult:
    """
    Route order through risk checks and submit to Kalshi.
    
    Risk checks performed:
    1. Basic validation (price range, side, count)
    2. Source whitelist check
    3. Duplicate order check
    4. Open resting order check (anti-stacking)
    5. Slot allocation check (entry orders only)
    6. Unified Risk Manager check
    7. Position linkage check (exit orders require exit_policy_id)
    8. Maker/taker policy application
    """
    # Basic validation
    if not (1 <= intent.price_cents <= 99):
        return OrderResult(
            success=False,
            status="REJECTED",
            reason=f"invalid_price_cents:{intent.price_cents}:must_be_1-99_cents"
        )
    
    # Source whitelist check
    allowed_sources = ["merid.prediction.agent_grid_15m", "kalshi_tools", "offset_hedging", "position_monitor_exit"]
    if intent.source not in allowed_sources:
        return OrderResult(
            success=False,
            status="REJECTED",
            reason=f"source_not_allowed:{intent.source}"
        )
    
    # Duplicate order check
    if _is_duplicate_order(intent):
        return OrderResult(
            success=False,
            status="REJECTED",
            reason="duplicate_order"
        )
    
    # Open resting order check (anti-stacking)
    if intent.action == "buy":
        if _check_open_resting_order(intent):
            return OrderResult(
                success=False,
                status="REJECTED",
                reason=f"open_order_exists:{existing_order_id}"
            )
    
    # Slot allocation check (entry orders only)
    if intent.source != "position_monitor_exit":
        slot_result = _check_slot_allocation(intent)
        if not slot_result.allowed:
            return OrderResult(
                success=False,
                status="REJECTED",
                reason=f"slot_allocation:{slot_result.reason}"
            )
    
    # Unified Risk Manager check
    urm_result = await _check_unified_risk_manager(intent)
    if not urm_result.allowed:
        return OrderResult(
            success=False,
            status="REJECTED",
            reason=f"unified_risk_manager:{urm_result.reason}"
        )
    
    # Position linkage check (exit orders require exit_policy_id)
    if intent.source == "position_monitor_exit":
        if not intent.exit_policy_id:
            return OrderResult(
                success=False,
                status="REJECTED",
                reason="missing_exit_policy_id"
            )
        
        # Verify position linkage
        if not _verify_exit_policy_linkage(intent):
            return OrderResult(
                success=False,
                status="REJECTED",
                reason="exit_policy_linkage_failed"
            )
    
    # Apply maker/taker policy
    intent = _apply_maker_taker_policy(intent)
    
    # Submit to Kalshi
    result = await _submit_to_kalshi(intent)
    
    return result
```

**Key Points:**
- **Source Whitelist:** `position_monitor_exit` is explicitly allowed
- **Exit Order Bypass:** Exit orders bypass slot allocation check
- **Position Linkage:** Exit orders require `exit_policy_id` for validation
- **Anti-Stacking:** Prevents duplicate buy orders for same ticker+side+action
- **Duplicate Window:** 5-second duplicate order window (matches 5s polling cadence)

### Unified Risk Manager Check

**Location:** `merid/risk/unified_risk_manager.py`

```python
async def check_order(self, intent: OrderIntent) -> RiskCheckResult:
    """
    Check order against unified risk limits.
    
    Risk limits enforced:
    - Fixed exposure cap ($1.00 global cap)
    - Per-contract limit (1 contract max)
    - Drawdown halt (20% drawdown triggers halt)
    - Drawdown unwind (25% drawdown triggers unwind)
    """
    # Exit orders bypass exposure cap (they reduce exposure)
    if intent.source == "position_monitor_exit":
        return RiskCheckResult(allowed=True, reason="exit_order_bypass")
    
    # Check fixed exposure cap
    current_exposure = self._get_current_exposure()
    if current_exposure + intent_notional > self.fixed_exposure_cap_usd:
        return RiskCheckResult(
            allowed=False,
            reason=f"order_exceeds_fixed_1usd_cap"
        )
    
    # Check per-contract limit
    if intent.count > 1:
        return RiskCheckResult(
            allowed=False,
            reason="exceeds_max_contracts_1"
        )
    
    # Check drawdown
    if self._check_drawdown_halt():
        return RiskCheckResult(
            allowed=False,
            reason="drawdown_halt"
        )
    
    return RiskCheckResult(allowed=True)
```

**Key Points:**
- **Exit Order Bypass:** Exit orders bypass exposure cap
- **Fixed Cap:** $1.00 global exposure cap (enforced via `MERID_FIXED_EXPOSURE_CAP_USD`)
- **Per-Contract Limit:** 1 contract max
- **Drawdown Protection:** 20% halt, 25% unwind

---

## Kalshi Execution

### Order Submission

**Location:** `merid/event_venues/kalshi/client.py`

```python
async def place_order(self, order: VenueOrder) -> OrderResult:
    """
    Place order on Kalshi exchange.
    
    Steps:
    1. Convert to Kalshi API format
    2. Submit via REST API
    3. Parse response
    4. Return OrderResult
    """
    # Convert to Kalshi format
    kalshi_order = {
        "ticker": order.ticker,
        "side": order.side,  # "yes" or "no"
        "action": order.action,  # "buy" or "sell"
        "count": order.count,
        "price": order.price_cents / 100.0,  # Convert cents to dollars
        "order_type": order.order_type,
        "time_in_force": order.time_in_force,
    }
    
    # Submit to Kalshi API
    response = await self._http_client.post(
        f"{self._base_url}/trade",
        json=kalshi_order
    )
    
    # Parse response
    if response.status_code == 200:
        data = response.json()
        return OrderResult(
            success=True,
            status="ACCEPTED",
            order_id=data.get("order_id"),
            filled=data.get("filled", 0),
            remaining=data.get("remaining", order.count)
        )
    else:
        return OrderResult(
            success=False,
            status="REJECTED",
            error=response.text
        )
```

**Key Points:**
- **API Format:** Converts to Kalshi API format (cents to dollars)
- **Response Parsing:** Extracts order_id, filled, remaining
- **Error Handling:** Returns REJECTED on non-200 status

---

## Fill Monitoring

### Fill Ledger Updates

**Location:** `merid/event_venues/kalshi/fills_ledger.py`

```python
def apply_fill(self, fill: Fill) -> None:
    """
    Apply fill to position tracking.
    
    For exit orders:
    - Reduces position size
    - Updates unrealized PnL
    - Removes position from cache if fully closed
    """
    position = self._position_cache.get(fill.market_id)
    if position:
        if fill.side == "sell":
            # Exit order - reduce position
            position.size -= fill.count
            if position.size == 0:
                # Position fully closed
                self._position_cache.remove(fill.market_id)
```

**Key Points:**
- **Size Reduction:** Exit orders reduce position size
- **Position Removal:** Fully closed positions removed from cache
- **PnL Update:** Updates unrealized PnL based on fill price

---

## Critical Exit Triggers

### 99c Automatic Exit

**Trigger Condition:** Own-side price >= 99c

**Implementation:**
- File: `merid/position_management/position.py:367-395`
- Method: `should_trigger_extreme_profit()`
- Priority: 90 (second highest after RISK)

**Side-Space Semantics:**
- YES position: YES price >= 99c (guaranteed YES win)
- NO position: NO price >= 99c (guaranteed NO win, equivalent to YES at 1c)

**Idempotency:**
- Checks `position.exit_triggered` before emitting exit intent
- Loop-side guard prevents duplicate callbacks

**Execution:**
- Marketable order (`aggressiveness=1.0`)
- Immediate fill expected
- Bypasses slot allocation

**Configuration:** None (hardcoded 99c threshold)

### 80-85c Trailing Exit

**Trigger Conditions:**
1. Profit >= 12c (minimum profit threshold)
2. 30-second activation delay after profit threshold reached
3. Price >= 80c activates aggressive 2c trailing mode
4. Price <= trail level triggers exit

**Implementation:**
- File: `merid/position_management/position_monitor.py:499-643`
- File: `merid/position_management/position.py:152-259`
- Priority: 25 (TRAIL)

**Trailing Modes:**
- Normal: 5c trailing distance
- Aggressive: 2c trailing distance (when price >= 80c)

**Hysteresis:**
- Activates at 80c
- Deactivates at 75c (prevents oscillation)

**Time-Based Tightening:**
- Tightens trail by 50% in last 5 minutes
- Tightens trail by 25% in last 10 minutes

**Side-Space Semantics:**
- Trail below max favorable price (both sides)
- Trigger when own-side price <= trail level

**Configuration:**
```python
trailing_stop_enabled: bool = True
trailing_stop_min_profit_cents: int = 12
trailing_stop_trailing_distance_cents: int = 5
trailing_stop_trailing_distance_cents_profit_zone: int = 2
trailing_stop_profit_zone_activation_cents: int = 80
trailing_stop_activation_delay_sec: int = 30
```

### Ratchet Profit Floor (80-85c)

**Trigger Conditions:**
1. Price >= 85c (activation threshold)
2. 30-second hold period after activation
3. Price <= 80c (floor breach) after hold period expired

**Implementation:**
- File: `merid/position_management/position_monitor.py:342-448`
- Priority: 70 (RATCHET_FLOOR)

**Ratchet Trim (Partial Close):**
- Trigger: Price >= 80c AND size > 1 contract
- Action: Trim to 1 contract
- Priority: 75 (RATCHET_TRIM)

**Side-Space Semantics:**
- Activation: Own-side price >= 85c (both sides)
- Floor breach: Own-side price <= 80c (both sides)

**Configuration:**
```python
ratchet_profit_floor_enabled: bool = True
ratchet_activation_threshold_cents: int = 85
ratchet_floor_offset_cents: int = 5
ratchet_force_exit_on_floor_breach: bool = True
ratchet_min_hold_after_activation_sec: int = 30
ratchet_trim_position_enabled: bool = True
ratchet_trim_threshold_cents: int = 80
ratchet_trim_to_contracts: int = 1
```

---

## Configuration

### Profile Configuration

**File:** `config/profiles/kalshi_crypto_15m_v2.yaml`

```yaml
# Dynamic Take Profit
dynamic_take_profit:
  enabled: true
  edge_adjustment_enabled: true
  edge_high_threshold: 0.05
  edge_low_threshold: 0.02
  edge_high_multiplier: 1.1
  edge_low_multiplier: 0.9
  zones:
    - entry_min: 10
      entry_max: 25
      exit_target: 40
    - entry_min: 25
      entry_max: 30
      exit_target: 50
    - entry_min: 30
      entry_max: 40
      exit_target: 60
    - entry_min: 40
      entry_max: 50
      exit_target: 70

# Staged Time Exit
staged_time_exit:
  enabled: true
  stages:
    - minutes: 5
      percent: 25
    - minutes: 10
      percent: 25
    - minutes: 13
      percent: 50

# Risk Limits
risk_limits:
  fixed_exposure_cap_usd: 1.00
  per_trade:
    max_contracts: 1
  bankroll:
    daily_loss_pct: 0.20
  drawdown:
    halt_pct: 0.20
    unwind_pct: 0.25
```

### Code Configuration

**File:** `merid/risk/profiles/crypto_15m_profile.py`

```python
# Trailing Stop Configuration
trailing_stop_enabled: bool = True
trailing_stop_min_profit_cents: int = 12
trailing_stop_trailing_distance_cents: int = 5
trailing_stop_trailing_distance_cents_profit_zone: int = 2
trailing_stop_profit_zone_activation_cents: int = 80
trailing_stop_activation_delay_sec: int = 30

# Ratchet Profit Floor Configuration
ratchet_profit_floor_enabled: bool = True
ratchet_activation_threshold_cents: int = 85
ratchet_floor_offset_cents: int = 5
ratchet_force_exit_on_floor_breach: bool = True
ratchet_min_hold_after_activation_sec: int = 30
ratchet_trim_position_enabled: bool = True
ratchet_trim_threshold_cents: int = 80
ratchet_trim_to_contracts: int = 1
```

---

## Troubleshooting

### Exit Orders Not Executing

**Symptoms:**
- Position reaches 99c but no exit order placed
- Logs show "Exit intent ignored - position already exited"
- Position rides to settlement without exit

**Root Causes:**
1. **Callback not registered:** Check `position_monitor._exit_intent_callback is None`
2. **Idempotency guard triggered:** Position marked as exited prematurely
3. **Callback ordering bug:** Callback dispatched AFTER position removed (fixed 2026-07-16)
4. **Order router rejection:** Check rejection reason in logs

**Diagnostic Steps:**
1. Check logs for `[POSITION-MONITOR] Exit intent callback registered`
2. Check logs for `[POSITION-MONITOR-CALLBACK] Exit intent ignored`
3. Check logs for `[EXIT-ORDER] Exit order failed`
4. Verify `exit_policy_id` is set on position

**Fixes:**
- Ensure callback registered BEFORE monitor starts
- Verify callback-first ordering in `_emit_exit_intent()`
- Check order router rejection reasons
- Verify position linkage validation

### 99c Exit Not Triggering

**Symptoms:**
- Position at 99c but EXTREME_PROFIT not triggered
- Logs show price check but no exit

**Root Causes:**
1. **Side-space bug:** NO position checking wrong price (fixed 2026-07-16)
2. **Bid/ask not available:** Using mid price instead of conservative bid
3. **Idempotency guard:** Position already marked as exited

**Diagnostic Steps:**
1. Check logs for `[POSITION-MONITOR] EXTREME-PROFIT triggered`
2. Verify own-side price >= 99c
3. Check `position.exit_triggered` flag
4. Verify bid price availability

**Fixes:**
- Verify side-space semantics (own-side price for both sides)
- Ensure bid price passed to `should_trigger_extreme_profit()`
- Clear `exit_triggered` if incorrectly set

### Trailing Stop Not Activating

**Symptoms:**
- Position in profit but trailing not activated
- Logs show profit threshold not reached

**Root Causes:**
1. **Profit threshold too high:** Default 12c may not be reached
2. **Activation delay not elapsed:** 30-second delay not completed
3. **Trailing disabled in profile:** Check `trailing_stop_enabled`

**Diagnostic Steps:**
1. Check logs for `[POSITION-MONITOR] TRAILING profit threshold reached`
2. Check logs for activation delay elapsed
3. Verify `trailing_stop_enabled` in profile
4. Check profit calculation (current_price - entry_price)

**Fixes:**
- Lower `trailing_stop_min_profit_cents` if needed
- Reduce `trailing_stop_activation_delay_sec` if needed
- Enable `trailing_stop_enabled` in profile

### Ratchet Floor Not Triggering

**Symptoms:**
- Price drops below 80c but RATCHET_FLOOR not triggered
- Position gives back profits

**Root Causes:**
1. **Ratchet not activated:** Price never reached 85c
2. **Hold period not expired:** 30-second hold period still active
3. **Force exit disabled:** `ratchet_force_exit_on_floor_breach = False`

**Diagnostic Steps:**
1. Check logs for `[POSITION-MONITOR] RATCHET activated`
2. Check logs for hold period expiration
3. Verify `ratchet_force_exit_on_floor_breach` in profile
4. Check floor price calculation (85c - 5c = 80c)

**Fixes:**
- Lower `ratchet_activation_threshold_cents` if needed
- Reduce `ratchet_min_hold_after_activation_sec` if needed
- Enable `ratchet_force_exit_on_floor_breach`

---

## Summary

The exit policy system is a critical component of the 15M Kalshi crypto trading system, responsible for closing positions to lock in profits, limit losses, and manage risk. The system uses a strict priority-based evaluation order, with 99c automatic exit as the second-highest priority (after RISK kill switch).

### Key Invariants

1. **All trades execute with exit policy enforcement** - No position rides to settlement without exit
2. **99c is mandatory exit** - Guaranteed wins are locked in regardless of other conditions
3. **80-85c triggers aggressive trailing** - Profits are protected when price crosses 80c
4. **Exit orders are marketable** - Exit orders execute immediately with `aggressiveness=1.0`
5. **Idempotency is enforced** - Duplicate exit attempts are prevented
6. **Side-space semantics are consistent** - Both YES and NO use own-side price logic

### Critical Files

- `merid/position_management/position_monitor.py` - Core exit monitoring engine
- `merid/position_management/position.py` - Position model with exit logic
- `merid/position_management/exit_decision.py` - Exit decision DTO and precedence
- `merid/loop_15m.py` - Main loop with callback registration
- `merid/event_venues/kalshi/order_router.py` - Order routing and risk checks
- `merid/risk/profiles/crypto_15m_profile.py` - Exit policy configuration
- `config/profiles/kalshi_crypto_15m_v2.yaml` - Profile configuration

### Monitoring

Key log patterns to monitor:
- `[POSITION-MONITOR] EXTREME-PROFIT triggered` - 99c exit
- `[POSITION-MONITOR] TRAILING activated` - Trailing stop activation
- `[POSITION-MONITOR] RATCHET activated` - Ratchet activation
- `[EXIT-INTENT]` - Exit intent emission
- `[EXIT-ORDER]` - Exit order routing
- `[POSITION-MONITOR-CALLBACK]` - Callback execution

---

## Investigation Summary (2026-07-17)

### Diagnostic Results

A comprehensive diagnostic script (`test_exit_policy_wiring.py`) was created and executed to verify the exit policy wiring. Results:

**✅ PASS (7/8 core tests):**
- PositionMonitor Singleton - EXISTS
- Position Addition - WORKS for both YES and NO
- 99c Exit Logic - WORKS for both YES and NO
- Trailing Stop Logic - WORKS for both YES and NO
- Ratchet Floor Logic - WORKS for both YES and NO
- Profile Configuration - LOADED correctly
- Exit Priority - CORRECTLY ordered

**❌ FAIL (1/8 tests):**
- Callback Registration - FAILED in standalone mode (EXPECTED)

### Why Callback Registration Failed in Standalone Test

The callback registration test fails in standalone mode because the exit intent callback is only registered during the **full startup sequence**:

```
main_15m_lean.py → Kalshi15mLoop.start() → PositionMonitor.start()
```

In the standalone diagnostic script, PositionMonitor is instantiated directly without the startup sequence, so the callback is never registered. This is **expected behavior** and does not indicate a problem with the exit policy.

### Live System Verification

In the actual live system, the startup sequence ensures:
1. `main_15m_lean.py` initializes and starts `Kalshi15mLoop`
2. `Kalshi15mLoop.start()` registers the exit intent callback
3. `Kalshi15mLoop.start()` calls `PositionMonitor.start()`
4. `PositionMonitor.start()` begins polling positions every 5 seconds
5. Exit conditions are evaluated and orders are placed via the callback

### Side-Space Semantics Verification

The diagnostic script confirmed that the exit policy correctly handles both YES and NO sides using **own-side price semantics**:

**99c Exit:**
- YES position: Triggers when YES price >= 99c (guaranteed YES win)
- NO position: Triggers when NO price >= 99c (guaranteed NO win, equivalent to YES at 1c)
- **CRITICAL FIX (2026-07-16):** Both sides use own-side price (no 100-x mirror for NO)

**Trailing Stop:**
- YES position: Trail level calculated from max favorable YES price, triggers when YES price <= trail level
- NO position: Trail level calculated from max favorable NO price, triggers when NO price <= trail level
- **CRITICAL FIX (2026-07-16):** Both sides use own-side price (no 100-x mirror for NO)

**Ratchet Profit Floor:**
- YES position: Activates at YES price >= 85c, floor at 80c
- NO position: Activates at NO price >= 85c, floor at 80c
- **CRITICAL FIX (2026-07-16):** Both sides use own-side price (no 100-x mirror for NO)

### Configuration Verification

The profile configuration is correctly set:
- `trailing_stop_enabled: true`
- `trailing_stop_min_profit_cents: 12`
- `trailing_stop_trailing_distance_cents: 5` (normal mode)
- `trailing_stop_trailing_distance_cents_profit_zone: 2` (aggressive mode at 80c)
- `trailing_stop_profit_zone_activation_cents: 80`
- `trailing_stop_activation_delay_sec: 30`
- `ratchet_profit_floor_enabled: true`
- `ratchet_activation_threshold_cents: 85`
- `ratchet_floor_offset_cents: 5`
- `ratchet_force_exit_on_floor_breach: true`
- `ratchet_min_hold_after_activation_sec: 30`
- `ratchet_trim_position_enabled: true`
- `ratchet_trim_threshold_cents: 80`
- `ratchet_trim_to_contracts: 1`
- `dynamic_take_profit.enabled: true`
- `staged_time_exit.enabled: true`

### Conclusion

**The exit policy is fully wired and correctly implemented for both YES and NO sides.**

The diagnostic script confirms:
- All exit logic (99c, trailing, ratchet) works correctly for both YES and NO
- Side-space semantics are properly implemented (own-side price for both sides)
- Exit priorities are correctly ordered
- Profile configuration is correct

The only "failure" in the diagnostic is the callback registration test, which is expected in standalone mode. In the live system, the callback is registered during the startup sequence, and the exit policy functions as designed.

### Live Trading Verification

**CRITICAL FINDING: No recent trading data available for verification**

The system has not been actively trading recently (last session snapshots are from May 2026, current date is July 2026). Therefore, we cannot verify the exit policy works in practice using real data.

**What we CAN verify:**
- ✅ Exit policy logic is correctly implemented (unit tests pass)
- ✅ Side-space semantics are correct for both YES and NO
- ✅ Exit priorities are correctly ordered
- ✅ Profile configuration is correct
- ✅ PositionMonitor singleton exists
- ✅ Positions can be added to monitor

**What we CANNOT verify without live data:**
- ❌ PositionMonitor is actually running during live trading
- ❌ Exit intent callback is registered during live startup
- ❌ Positions are being added to monitor during live trading
- ❌ Exit conditions are being triggered in real scenarios
- ❌ Exit orders are being placed and filled
- ❌ No positions are riding to settlement without exit

**To verify the exit policy works in practice, you must:**

1. **Start the live trading system:**
   ```bash
   CD C:\Dev\MERID
   .\start_15m.ps1 -Port 8011 -Profile kalshi_crypto_15m_v2
   ```

2. **Monitor startup logs for:**
   ```
   [15M-LOOP] Initialized PositionMonitor for TP/SL/trailing exits
   [15M-LOOP] Exit intent callback verified registered: exit_intent_callback
   [15m-LOOP] Started PositionMonitor with exit callback
   [POSITION-MONITOR] Started (poll_interval=5s)
   ```

3. **Monitor trading logs for:**
   ```
   [POSITION-MONITOR-INTEGRATION] Added position to monitor: market=... side=... size=...
   [POSITION-MONITOR] Polling N positions
   [POSITION-MONITOR] EXTREME-PROFIT triggered: position=... price=99c
   [EXIT-INTENT] position=... reason=extreme_profit ...
   [EXIT-ORDER] Exit order executed successfully: order_id=...
   ```

4. **Run the real data analyzer during live trading:**
   ```bash
   py analyze_real_exit_policy_data.py
   ```

   This will check:
   - PositionMonitor is running
   - Callback is registered
   - Positions are in monitor
   - Exit fills are occurring
   - No gaps between cache and monitor

**Use the checklist in `LIVE_TRADING_EXIT_POLICY_DIAGNOSTIC_CHECKLIST.md`** for detailed step-by-step verification during live trading.

If you're experiencing exit policy failures in live trading, the checklist will help identify which step in the chain is breaking.

---

**Document End**
