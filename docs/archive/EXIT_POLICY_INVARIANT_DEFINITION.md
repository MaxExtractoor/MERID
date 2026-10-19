# Exit Policy Invariant Definition
## MERID 15M Kalshi Crypto Trading System

**Created:** 2026-07-06  
**Purpose:** Define explicit, code-enforceable invariants for the exit policy pipeline to ensure "No Trade Without Exit" compliance.

---

## Core Invariant: No Trade Without Exit

**Invariant Statement:**
> Every trade entry order MUST have a valid, enforceable exit policy attached before submission to the venue. Exit policies MUST be enforced through a monitoring loop that triggers exit orders when conditions are met.

**Formal Definition:**
```
∀ order ∈ EntryOrders:
  order.exit_policy_id ≠ NULL ∧
  order.window_resolution_id ≠ NULL ∧
  order.risk_tier ≠ NULL ∧
  order.max_hold_seconds ≠ NULL ∧
  ∃ exit_monitor: exit_monitor.check_position(order) → ExitIntent
```

---

## Invariant #1: Risk Contract Linkage

**Location:** `merid/event_venues/kalshi/order_router.py:_validate_risk_contract_linkage()`

**Invariant:**
All crypto 15m entry orders MUST have complete risk contract linkage. Exit orders MUST have at least an exit_policy_id for tracking.

**Code-Enforceable Rules:**
```python
def _validate_risk_contract_linkage(intent: OrderIntent) -> tuple[bool, Optional[str]]:
    if not _is_crypto_15m_market(intent.ticker):
        return True, None
    
    if _is_exit_order(intent):
        # Exit orders require exit_policy_id for tracking
        if not intent.exit_policy_id:
            return False, "Exit order missing exit_policy_id"
        return True, None
    
    # Entry orders require full risk contract linkage
    missing_fields = []
    if not intent.window_resolution_id:
        missing_fields.append("window_resolution_id")
    if not intent.exit_policy_id:
        missing_fields.append("exit_policy_id")
    if not intent.risk_tier:
        missing_fields.append("risk_tier")
    if not intent.max_hold_seconds:
        missing_fields.append("max_hold_seconds")
    
    if missing_fields:
        return False, f"Missing risk contract fields: {', '.join(missing_fields)}"
    
    return True, None
```

**Enforcement Point:** `route_order_async()` and `route_order()` in `order_router.py` MUST call `_validate_risk_contract_linkage()` before any order submission.

**Current Status:** ✅ ENFORCED - The invariant is enforced in order routing.

---

## Invariant #2: Exit Policy Resolution

**Location:** `merid/event_venues/kalshi/order_router.py:resolve_exit_policy()`

**Invariant:**
Exit policies MUST be resolved from configuration, not hardcoded. All exit parameters (TP, SL, trailing, time exit) MUST be derived from the profile YAML or computed by the dynamic risk engine.

**Code-Enforceable Rules:**
```python
def resolve_exit_policy(
    edge_result: Optional[Dict[str, Any]],
    asset: str,
    regime: str = "normal"
) -> ExitPolicyResolution:
    # CRITICAL: All parameters MUST come from config or dynamic computation
    # NO hardcoded values allowed
    
    # Load from profile YAML
    from merid.risk.profiles.crypto_15m_profile import get_active_profile
    profile = get_active_profile().profile
    
    # TP/SL from dynamic risk engine (NOT hardcoded)
    from merid.event_venues.kalshi.dynamic_risk import DynamicRiskEngine
    engine = DynamicRiskEngine()
    tp_price, sl_price = engine.compute_tp_sl(...)
    
    # Trailing from profile (NOT hardcoded)
    trailing_enabled = profile.trailing_stop_enabled
    trailing_distance = profile.trailing_stop_trailing_distance_cents
    
    # Time exit from profile (NOT hardcoded)
    max_hold_seconds = profile.time_exit_max_hold_minutes * 60
    
    return ExitPolicyResolution(
        tp_price_cents=tp_price,
        sl_price_cents=sl_price,
        sl_mode=StopLossMode.FIXED_CENTS,
        sl_cents=abs(entry_price - sl_price),  # Computed, not hardcoded
        trailing_enabled=trailing_enabled,
        trailing_distance_cents=trailing_distance,
        max_hold_seconds=max_hold_seconds,
        # ... other fields from config
    )
```

**Current Status:** ⚠️ PARTIALLY COMPLIANT - `sl_cents=5` is hardcoded in `resolve_exit_policy()`. This MUST be computed from entry price and SL price.

**Required Fix:**
```python
# In order_router.py line 609-610
# BEFORE (hardcoded):
sl_cents=5,  # 5 cent fixed stop loss (conservative for 15m crypto)

# AFTER (computed):
sl_cents=abs(entry_price_cents - sl_price_cents),  # Computed from actual SL level
```

---

## Invariant #3: Exit Metadata Attachment

**Location:** `merid/event_venues/kalshi/position_cache.py:register_tp_targets()`

**Invariant:**
All fills MUST register TP/SL targets with the position cache before monitoring begins. Positions without TP/SL targets MUST be rejected or flagged as unhealthy.

**Code-Enforceable Rules:**
```python
def register_tp_targets(
    self,
    client_order_id: str,
    take_profit_price_cents: Optional[int] = None,
    take_profit_r_multiple: Optional[float] = None,
    stop_loss_price_cents: Optional[int] = None,
) -> None:
    # CRITICAL: TP/SL targets MUST be provided
    if take_profit_price_cents is None or stop_loss_price_cents is None:
        logger.error(
            "[POSITION-CACHE] Missing TP/SL targets for order %s - "
            "position cannot be monitored for exits",
            client_order_id
        )
        # Option 1: Reject the fill (strict)
        # raise ValueError("Missing TP/SL targets")
        # Option 2: Flag as unhealthy (permissive)
        self._unhealthy_positions.add(client_order_id)
        return
    
    # Store targets for monitoring
    self._tp_sl_targets[client_order_id] = {
        "tp": take_profit_price_cents,
        "sl": stop_loss_price_cents,
        "tp_r": take_profit_r_multiple,
    }
```

**Current Status:** ⚠️ PARTIALLY COMPLIANT - `position_cache.py` uses fallback values (`sl_price = price_cents - 5`) when TP/SL are not provided. This violates the invariant.

**Required Fix:**
```python
# In position_cache.py line 586
# BEFORE (fallback):
sl_price = tp_targets.get("sl_price", price_cents - 5)

# AFTER (strict):
sl_price = tp_targets.get("sl_price")
if sl_price is None:
    logger.error("[POSITION-CACHE] Missing SL price - cannot monitor position")
    # Reject or flag as unhealthy
```

---

## Invariant #4: Exit Intent Callback

**Location:** `merid/position_management/position_monitor.py:_emit_exit_intent()`

**Invariant:**
All exit triggers MUST emit an exit intent through the registered callback. Direct order submission from monitoring loops is FORBIDDEN.

**Code-Enforceable Rules:**
```python
def _emit_exit_intent(
    self,
    position: Position,
    exit_reason: ExitReason,
    exit_price_cents: int,
    contracts_to_close: Optional[int] = None
) -> None:
    # CRITICAL: All exits MUST go through callback
    # Direct route_order_async() calls are FORBIDDEN
    if self._exit_intent_callback is None:
        logger.error(
            "[POSITION-MONITOR] Exit intent callback not registered - "
            "cannot emit exit for position %s (reason=%s)",
            position.position_id[:8],
            exit_reason
        )
        # Fail closed: do not emit exit without callback
        return
    
    self._exit_intent_callback(
        position=position,
        exit_reason=exit_reason,
        exit_price_cents=exit_price_cents,
        contracts_to_close=contracts_to_close
    )
```

**Current Status:** ✅ ENFORCED - `PositionMonitor` uses callback correctly. `PositionCache._monitor_positions_loop()` has staged exit logic DISABLED to prevent direct order submission.

**Required Fix:** None (staged exits are already disabled).

---

## Invariant #5: Monitoring Loop Health

**Location:** `merid/event_venues/kalshi/position_cache.py:_monitor_positions_loop()`

**Invariant:**
The monitoring loop MUST be running for all open positions. If the loop stops, the system MUST halt trading or enter degraded mode.

**Code-Enforceable Rules:**
```python
async def _monitor_positions_loop(self) -> None:
    last_tick_time = time.time()
    
    while self._monitoring_enabled:
        try:
            # Check loop health
            current_time = time.time()
            tick_interval = current_time - last_tick_time
            last_tick_time = current_time
            
            if tick_interval > self._monitoring_interval_seconds * 2:
                logger.error(
                    "[TRAIL-MONITOR] Loop health degraded: tick interval=%.1fs (expected=%.1fs)",
                    tick_interval,
                    self._monitoring_interval_seconds
                )
                # Emit health alert
                self._emit_health_alert("monitoring_loop_slow", tick_interval)
            
            # Monitor positions
            positions_snapshot = list(self._positions.values())
            for position in positions_snapshot:
                if position.contracts <= 0:
                    continue
                if position.take_profit_price_cents is None or position.stop_loss_price_cents is None:
                    logger.error(
                        "[TRAIL-ERROR] Position %s missing TP/SL - cannot monitor",
                        position.market_id
                    )
                    self._unhealthy_positions.add(position.market_id)
                    continue
                
                # Check exit conditions
                # ... (existing logic)
            
            await asyncio.sleep(self._monitoring_interval_seconds)
            
        except Exception as e:
            logger.error("[TRAIL-MONITOR] Loop error: %s", e)
            # Emit health alert
            self._emit_health_alert("monitoring_loop_error", str(e))
            await asyncio.sleep(self._monitoring_interval_seconds)
```

**Current Status:** ⚠️ PARTIALLY COMPLIANT - The loop logs errors but does not halt trading on failure.

**Required Fix:** Add health alert mechanism and trading halt on persistent monitoring failures.

---

## Invariant #6: Risk Guard Exit Policy Check

**Location:** `merid/event_venues/kalshi/order_gate.py:PreTradeGate.check()`

**Invariant:**
The pre-trade gate MUST verify that exit policies are attached before allowing orders. This is a fail-safe check in addition to order router validation.

**Code-Enforceable Rules:**
```python
def check(
    self,
    agent_id: str,
    strategy_group: str,
    contract_id: str,
    side: str,
    action: str,
    target_count: int,
    price_cents: int,
    decision_ts: float,
    intent_id: Optional[str] = None,
    existing_filled: Optional[int] = None,
    # NEW: Exit policy metadata
    exit_policy_id: Optional[str] = None,
    window_resolution_id: Optional[str] = None,
    risk_tier: Optional[str] = None,
    max_hold_seconds: Optional[int] = None,
) -> GateVerdict:
    # Existing checks (idempotency, fill awareness, etc.)
    # ...
    
    # NEW: Exit policy check for crypto 15m markets
    if _is_crypto_15m_market(contract_id):
        if action == "buy":  # Entry order
            if not exit_policy_id or not window_resolution_id or not risk_tier or not max_hold_seconds:
                return GateVerdict(
                    allowed=False,
                    reason="Missing exit policy metadata (exit_policy_id, window_resolution_id, risk_tier, max_hold_seconds)"
                )
        else:  # Exit order
            if not exit_policy_id:
                return GateVerdict(
                    allowed=False,
                    reason="Exit order missing exit_policy_id"
                )
    
    # Continue with existing checks
    # ...
```

**Current Status:** ❌ NOT ENFORCED - `PreTradeGate.check()` does not validate exit policy metadata.

**Required Fix:** Add exit policy validation to `PreTradeGate.check()`.

---

## Invariant #7: No Magic Numbers in Exit Logic

**Location:** All exit-related code

**Invariant:**
All exit parameters (TP, SL, trailing distances, time thresholds) MUST come from configuration or be computed from market data. Hardcoded magic numbers are FORBIDDEN.

**Code-Enforceable Rules:**
```python
# FORBIDDEN:
sl_cents = 5  # Magic number
trailing_distance = 5  # Magic number
min_profit_cents = 12  # Magic number (unless from config)
cutoff_minutes = 2  # Magic number (unless from config)

# REQUIRED:
from merid.risk.profiles.crypto_15m_profile import get_active_profile
profile = get_active_profile().profile

sl_cents = abs(entry_price_cents - sl_price_cents)  # Computed
trailing_distance = profile.trailing_stop_trailing_distance_cents  # From config
min_profit_cents = profile.trailing_stop_min_profit_cents  # From config
cutoff_minutes = profile.time_exit_cutoff_minutes_before_expiry  # From config
```

**Current Status:** ⚠️ VIOLATIONS FOUND:
- `order_router.py:609-610`: `sl_cents=5` hardcoded
- `dynamic_risk.py:495-497`: `sl_cents_map` with hardcoded values
- `web/main_15m_lean.py:1476-1491`: Hardcoded policy resolution logic
- `web/api/kalshi_api.py:3223-3224`: `stop_loss_price_cents = max(1, price_cents - 5)` hardcoded fallback

**Required Fixes:** Replace all hardcoded values with config-driven or computed values.

---

## Invariant #8: Exit Trigger Precedence

**Location:** `merid/position_management/position_monitor.py:_check_position()`

**Invariant:**
Exit triggers MUST be evaluated in a strict precedence order to ensure the highest-priority exits fire first. The order is:

1. EXTREME_PROFIT (99c YES / 1c NO) - Highest priority
2. DYNAMIC_TAKE_PROFIT - Laddered exits based on entry price
3. RATCHET_PROFIT_FLOOR - Lock in profits at 80-85c
4. STOP_LOSS - Risk management
5. TAKE_PROFIT - Target hit
6. BREAK_EVEN - Capital preservation (move SL to entry)
7. SCALE_OUT - Partial exit at 1.5-2R
8. TRAILING - Trailing stop
9. ExitPolicy (time stop, edge decay, risk, candle reversal) - Lowest priority

**Code-Enforceable Rules:**
```python
def _check_position(self, position: Position, current_price_cents: int) -> None:
    # CRITICAL: Maintain strict precedence order
    
    # 1. EXTREME_PROFIT (highest priority)
    if position.should_trigger_extreme_profit(current_price_cents):
        self._emit_exit_intent(position, ExitReason.EXTREME_PROFIT, current_price_cents)
        return
    
    # 2. DYNAMIC_TAKE_PROFIT
    if position.dynamic_tp_triggered:
        self._emit_exit_intent(position, ExitReason.DYNAMIC_TAKE_PROFIT, current_price_cents)
        return
    
    # 3. RATCHET_PROFIT_FLOOR
    if position.ratchet_activated and should_exit_ratchet_floor:
        self._emit_exit_intent(position, ExitReason.RATCHET_FLOOR, current_price_cents)
        return
    
    # 4. STOP_LOSS
    if position.should_trigger_stop_loss(current_price_cents):
        self._emit_exit_intent(position, ExitReason.STOP_LOSS, current_price_cents)
        return
    
    # 5. TAKE_PROFIT
    if position.should_trigger_take_profit(current_price_cents):
        self._emit_exit_intent(position, ExitReason.TAKE_PROFIT, current_price_cents)
        return
    
    # 6. BREAK_EVEN (non-terminal)
    if position.should_trigger_break_even(current_price_cents):
        position.trigger_break_even()
        # Continue monitoring
    
    # 7. SCALE_OUT (non-terminal)
    if position.should_trigger_scale_out(current_price_cents):
        contracts_to_close = position.trigger_scale_out()
        self._emit_scale_out_intent(position, contracts_to_close, current_price_cents)
        # Continue monitoring
    
    # 8. TRAILING
    if position.trailing_activated and position.should_trigger_trail(current_price_cents):
        self._emit_exit_intent(position, ExitReason.TRAIL, current_price_cents)
        return
    
    # 9. ExitPolicy (lowest priority)
    resolver = get_exit_policy_resolver()
    exit_policy = resolver.resolve(position)
    if exit_policy.should_exit:
        self._emit_exit_intent(position, exit_policy.exit_reason, current_price_cents)
        return
```

**Current Status:** ✅ ENFORCED - The precedence order is correctly implemented in `position_monitor.py`.

---

## Invariant #9: Position Closure Tracking

**Location:** `merid/event_venues/kalshi/position_cache.py:close_position()`

**Invariant:**
All position closures MUST be tracked in:
1. Position cache (remove from open positions)
2. Position monitor (remove from monitoring)
3. Risk envelope (decrement window exposure)
4. KalshiRiskManager (decrement per-asset notional)

**Code-Enforceable Rules:**
```python
async def close_position(
    self,
    market_id: str,
    price_cents: int,
    contracts: int,
    # ...
) -> None:
    # 1. Remove from position cache
    if market_id in self._positions:
        del self._positions[market_id]
    
    # 2. Remove from PositionMonitor
    try:
        from merid.position_management.position_monitor import get_position_monitor
        monitor = get_position_monitor()
        monitor.remove_position(market_id)
    except Exception as e:
        logger.warning("Failed to remove from PositionMonitor: %s", e)
    
    # 3. Decrement window exposure
    try:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
        envelope = get_kalshi_crypto_15m_risk_envelope()
        envelope.record_position_closure(agent_id=..., position_notional_usd=...)
    except Exception as e:
        logger.warning("Failed to record window exposure reduction: %s", e)
    
    # 4. Decrement per-asset notional
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        risk_mgr = get_kalshi_risk()
        risk_mgr.record_close(category="crypto", contracts=contracts, price_cents=price_cents, asset=...)
    except Exception as e:
        logger.warning("Failed to record position close in risk manager: %s", e)
```

**Current Status:** ✅ ENFORCED - All four tracking mechanisms are implemented in `position_cache.py`.

---

## Invariant #10: Test Logic Bypass Prevention

**Location:** All test files

**Invariant:**
Test code MUST NOT bypass exit policy validation. Tests that mock out `_validate_risk_contract_linkage()` or other exit checks MUST be explicitly marked as "BYPASS_INVARIANT" and reviewed for safety.

**Code-Enforceable Rules:**
```python
# FORBIDDEN (unless explicitly marked):
@pytest.mark.asyncio
async def test_something():
    with patch('merid.event_venues.kalshi.order_router._validate_risk_contract_linkage') as mock:
        mock.return_value = (True, None)  # BYPASS - NOT ALLOWED
        # ... test logic

# REQUIRED (if bypass is necessary):
@pytest.mark.asyncio
@pytest.mark.bypass_invariant  # Explicit marker
async def test_something_with_bypass():
    """Test requires invariant bypass - reviewed and approved."""
    with patch('merid.event_venues.kalshi.order_router._validate_risk_contract_linkage') as mock:
        mock.return_value = (True, None)  # BYPASS - EXPLICITLY MARKED
        # ... test logic
```

**Current Status:** ⚠️ VIOLATIONS FOUND:
- `tests/kalshi_alignment/test_order_router.py:518,540`: Tests bypass invariant checks without explicit markers

**Required Fix:** Add `@pytest.mark.bypass_invariant` markers to all tests that bypass exit policy validation.

---

## Summary of Invariant Compliance

| Invariant | Status | Priority |
|-----------|--------|----------|
| #1: Risk Contract Linkage | ✅ ENFORCED | P0 |
| #2: Exit Policy Resolution | ⚠️ PARTIALLY COMPLIANT | P0 |
| #3: Exit Metadata Attachment | ⚠️ PARTIALLY COMPLIANT | P0 |
| #4: Exit Intent Callback | ✅ ENFORCED | P0 |
| #5: Monitoring Loop Health | ⚠️ PARTIALLY COMPLIANT | P1 |
| #6: Risk Guard Exit Policy Check | ❌ NOT ENFORCED | P0 |
| #7: No Magic Numbers | ⚠️ VIOLATIONS FOUND | P0 |
| #8: Exit Trigger Precedence | ✅ ENFORCED | P1 |
| #9: Position Closure Tracking | ✅ ENFORCED | P1 |
| #10: Test Logic Bypass Prevention | ⚠️ VIOLATIONS FOUND | P2 |

---

## Next Steps

See `docs/EXIT_POLICY_CODE_CHANGES.md` for prioritized code and config changes to achieve full invariant compliance.
