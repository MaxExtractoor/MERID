# Exit Policy Code and Config Changes
## MERID 15M Kalshi Crypto Trading System

**Created:** 2026-07-06  
**Purpose:** Prioritized list of code and config changes to achieve full "No Trade Without Exit" compliance.

---

## Priority Classification

- **P0 (Critical):** Must fix before production deployment. Violates core invariants.
- **P1 (High):** Should fix soon. Affects system reliability or observability.
- **P2 (Medium):** Nice to have. Improves code quality or test coverage.

---

## P0 Changes (Critical)

### #1: Remove Hardcoded `sl_cents=5` in `order_router.py`

**Location:** `merid/event_venues/kalshi/order_router.py:609-610`

**Current Code:**
```python
sl_mode=StopLossMode.FIXED_CENTS,  # CRITICAL FIX: Use fixed cent SL for binary options
sl_cents=5,  # 5 cent fixed stop loss (conservative for 15m crypto)
```

**Issue:** Hardcoded magic number violates Invariant #7 (No Magic Numbers). SL should be computed from actual entry and SL prices.

**Fix:**
```python
# Compute sl_cents from actual prices
sl_cents=abs(entry_price_cents - sl_price_cents) if sl_price_cents else 5,  # Computed from actual SL level
```

**Invariant:** #2 (Exit Policy Resolution), #7 (No Magic Numbers)

**Testing:**
- Verify SL is correctly computed for various entry/SL price combinations
- Test edge cases where sl_price_cents is None (should fallback to 5 or reject)

---

### #2: Remove Hardcoded Fallback SL in `kalshi_api.py`

**Location:** `web/api/kalshi_api.py:3223-3224`

**Current Code:**
```python
if stop_loss_price_cents is None:
    stop_loss_price_cents = max(1, price_cents - 5)
```

**Issue:** Hardcoded fallback allows orders without proper SL resolution. Violates Invariant #3 (Exit Metadata Attachment).

**Fix:**
```python
if stop_loss_price_cents is None:
    logger.error(
        "[KALSHI-API] Missing stop_loss_price_cents for order %s - "
        "cannot proceed without exit policy",
        client_order_id
    )
    raise HTTPException(
        status_code=400,
        detail="Missing stop_loss_price_cents - exit policy resolution failed"
    )
```

**Invariant:** #3 (Exit Metadata Attachment), #7 (No Magic Numbers)

**Testing:**
- Verify API rejects orders without SL
- Test error response is clear and actionable

---

### #3: Remove Hardcoded Policy Resolution in `main_15m_lean.py`

**Location:** `web/main_15m_lean.py:1475-1491`

**Current Code:**
```python
# Default values for 15m crypto trading
window_resolution_id = "15m"

# Exit policy based on edge
edge_pct = edge_result.get("edge_pct", 0.0)
if edge_pct >= 3.0:
    exit_policy_id = "aggressive"
    risk_tier = "aggressive"
    max_hold_seconds = 600  # 10 minutes
elif edge_pct >= 2.0:
    exit_policy_id = "standard"
    risk_tier = "moderate"
    max_hold_seconds = 900  # 15 minutes
else:
    exit_policy_id = "conservative"
    risk_tier = "conservative"
    max_hold_seconds = 900  # 15 minutes
```

**Issue:** Hardcoded policy resolution logic bypasses the proper `resolve_exit_policy()` function. Violates Invariant #2 (Exit Policy Resolution).

**Fix:**
```python
# Use proper exit policy resolver
from merid.event_venues.kalshi.order_router import resolve_exit_policy
from merid.event_venues.kalshi.order_router import resolve_window_policy

# Resolve window policy
window_resolution = resolve_window_policy(asset=asset, regime=regime)
window_resolution_id = window_resolution.window_resolution_id

# Resolve exit policy
edge_result = {"edge_pct": edge_pct}  # Build edge result dict
exit_policy_resolution = resolve_exit_policy(
    edge_result=edge_result,
    asset=asset,
    regime=regime
)
exit_policy_id = exit_policy_resolution.exit_policy_id
risk_tier = exit_policy_resolution.risk_tier
max_hold_seconds = exit_policy_resolution.max_hold_seconds
```

**Invariant:** #2 (Exit Policy Resolution), #7 (No Magic Numbers)

**Testing:**
- Verify policy resolution uses the proper resolver
- Test that edge-based selection still works through the resolver

---

### #4: Remove Hardcoded Fallback SL in `position_cache.py`

**Location:** `merid/event_venues/kalshi/position_cache.py:586`

**Current Code:**
```python
sl_price = tp_targets.get("sl_price", price_cents - 5)
```

**Issue:** Hardcoded fallback allows positions without proper SL to be monitored. Violates Invariant #3 (Exit Metadata Attachment).

**Fix:**
```python
sl_price = tp_targets.get("sl_price")
if sl_price is None:
    logger.error(
        "[POSITION-CACHE] Missing SL price for order %s - "
        "cannot monitor position for exits",
        client_order_id
    )
    # Option 1: Reject the position (strict)
    raise ValueError("Missing stop_loss_price_cents - cannot monitor position")
    # Option 2: Flag as unhealthy and skip monitoring (permissive)
    # self._unhealthy_positions.add(market_id)
    # return
```

**Invariant:** #3 (Exit Metadata Attachment), #7 (No Magic Numbers)

**Testing:**
- Verify positions without SL are rejected or flagged
- Test that monitoring loop skips unhealthy positions

---

### #5: Add Exit Policy Validation to `PreTradeGate.check()`

**Location:** `merid/event_venues/kalshi/order_gate.py:PreTradeGate.check()`

**Current Code:**
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
) -> GateVerdict:
    # Existing checks (idempotency, fill awareness, etc.)
    # ...
```

**Issue:** Pre-trade gate does not validate exit policy metadata. Violates Invariant #6 (Risk Guard Exit Policy Check).

**Fix:**
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
    from merid.event_venues.kalshi.order_router import _is_crypto_15m_market
    
    if _is_crypto_15m_market(contract_id):
        if action == "buy":  # Entry order
            missing_fields = []
            if not exit_policy_id:
                missing_fields.append("exit_policy_id")
            if not window_resolution_id:
                missing_fields.append("window_resolution_id")
            if not risk_tier:
                missing_fields.append("risk_tier")
            if not max_hold_seconds:
                missing_fields.append("max_hold_seconds")
            
            if missing_fields:
                return GateVerdict(
                    allowed=False,
                    reason=f"Missing exit policy metadata: {', '.join(missing_fields)}"
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

**Invariant:** #6 (Risk Guard Exit Policy Check)

**Testing:**
- Verify gate rejects entry orders without exit policy metadata
- Verify gate rejects exit orders without exit_policy_id
- Test that non-crypto markets are not affected

---

### #6: Refactor `sl_cents_map` in `dynamic_risk.py` to Use Config

**Location:** `merid/event_venues/kalshi/dynamic_risk.py:495-497`

**Current Code:**
```python
sl_cents_map = {
    VolatilityRegime.LOW: 6,      # Tight SL in low vol (was 4c)
    VolatilityRegime.NORMAL: 8,   # Standard SL (was 6c)
    VolatilityRegime.HIGH: 10,    # Wide SL in high vol (was 8c)
}
```

**Issue:** Hardcoded SL values per volatility regime. Should come from profile config. Violates Invariant #7 (No Magic Numbers).

**Fix:**
```python
# Load SL cents from profile config
try:
    from merid.risk.profiles.crypto_15m_profile import get_active_profile
    profile = get_active_profile().profile
    
    sl_cents_map = {
        VolatilityRegime.LOW: profile.sl_cents_low_vol,
        VolatilityRegime.NORMAL: profile.sl_cents_normal_vol,
        VolatilityRegime.HIGH: profile.sl_cents_high_vol,
    }
except Exception as e:
    logger.warning("[DYNAMIC-RISK] Failed to load SL config from profile: %s", e)
    # Fallback to hardcoded values (temporary)
    sl_cents_map = {
        VolatilityRegime.LOW: 6,
        VolatilityRegime.NORMAL: 8,
        VolatilityRegime.HIGH: 10,
    }
```

**Add to Profile YAML:**
```yaml
# In config/profiles/kalshi_crypto_15m_v2.yaml
dynamic_risk:
  sl_cents_low_vol: 6
  sl_cents_normal_vol: 8
  sl_cents_high_vol: 10
```

**Add to Profile Adapter:**
```python
# In merid/risk/profiles/crypto_15m_profile.py
@dataclass
class Crypto15mProfile:
    # ... existing fields ...
    sl_cents_low_vol: int = 6
    sl_cents_normal_vol: int = 8
    sl_cents_high_vol: int = 10
```

**Invariant:** #2 (Exit Policy Resolution), #7 (No Magic Numbers)

**Testing:**
- Verify SL values are loaded from profile
- Test fallback to hardcoded values if profile load fails

---

## P1 Changes (High)

### #7: Add Monitoring Loop Health Alerts

**Location:** `merid/event_venues/kalshi/position_cache.py:_monitor_positions_loop()`

**Current Code:**
```python
async def _monitor_positions_loop(self) -> None:
    while self._monitoring_enabled:
        try:
            # Monitor positions
            # ...
            await asyncio.sleep(self._monitoring_interval_seconds)
        except Exception as e:
            logger.error("[TRAIL-MONITOR] Loop error: %s", e)
            await asyncio.sleep(self._monitoring_interval_seconds)
```

**Issue:** Monitoring loop errors are logged but do not trigger alerts or trading halt. Violates Invariant #5 (Monitoring Loop Health).

**Fix:**
```python
async def _monitor_positions_loop(self) -> None:
    last_tick_time = time.time()
    consecutive_errors = 0
    max_consecutive_errors = 5  # Halt after 5 consecutive errors
    
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
                # ... existing monitoring logic ...
            
            consecutive_errors = 0  # Reset on success
            await asyncio.sleep(self._monitoring_interval_seconds)
            
        except Exception as e:
            consecutive_errors += 1
            logger.error("[TRAIL-MONITOR] Loop error (%d/%d): %s", consecutive_errors, max_consecutive_errors, e)
            
            # Emit health alert
            self._emit_health_alert("monitoring_loop_error", str(e))
            
            # Halt trading if too many consecutive errors
            if consecutive_errors >= max_consecutive_errors:
                logger.critical(
                    "[TRAIL-MONITOR] Too many consecutive errors (%d) - halting monitoring",
                    consecutive_errors
                )
                self._monitoring_enabled = False
                # Trigger trading halt
                self._trigger_trading_halt("monitoring_loop_failure")
                return
            
            await asyncio.sleep(self._monitoring_interval_seconds)

def _emit_health_alert(self, alert_type: str, details: str) -> None:
    """Emit health alert for monitoring."""
    try:
        from monitoring.metrics import get_metrics_registry
        reg = get_metrics_registry()
        counter = reg.counter(
            "merid_position_monitor_health_alerts_total",
            help_text="Position monitor health alerts",
            label_names=["alert_type"]
        )
        counter.labels(alert_type=alert_type).inc()
    except Exception as e:
        logger.debug("[TRAIL-MONITOR] Failed to emit health alert: %s", e)

def _trigger_trading_halt(self, reason: str) -> None:
    """Trigger trading halt due to monitoring failure."""
    try:
        from merid.governance.adaptive_risk_limits import get_adaptive_risk_limits
        risk_limits = get_adaptive_risk_limits()
        risk_limits.emergency_halt = True
        risk_limits.emergency_halt_reason = f"Position monitoring failure: {reason}"
        logger.critical("[TRAIL-MONITOR] Trading halt triggered: %s", reason)
    except Exception as e:
        logger.critical("[TRAIL-MONITOR] Failed to trigger trading halt: %s", e)
```

**Invariant:** #5 (Monitoring Loop Health)

**Testing:**
- Simulate monitoring loop errors and verify alerts are emitted
- Verify trading halt is triggered after max consecutive errors
- Test that loop recovers after transient errors

---

### #8: Add Unhealthy Position Tracking

**Location:** `merid/event_venues/kalshi/position_cache.py`

**Current Code:**
```python
class PositionCache:
    def __init__(self):
        self._positions: Dict[str, CachedPosition] = {}
        # ... other fields ...
```

**Issue:** No tracking of positions without proper exit metadata. Violates Invariant #3 (Exit Metadata Attachment).

**Fix:**
```python
class PositionCache:
    def __init__(self):
        self._positions: Dict[str, CachedPosition] = {}
        self._unhealthy_positions: Set[str] = set()  # NEW: Track unhealthy positions
        # ... other fields ...
    
    def is_position_healthy(self, market_id: str) -> bool:
        """Check if position has proper exit metadata."""
        return market_id not in self._unhealthy_positions
    
    def get_unhealthy_positions(self) -> List[str]:
        """Get list of unhealthy positions for alerting."""
        return list(self._unhealthy_positions)
    
    def log_unhealthy_positions(self) -> None:
        """Log unhealthy positions for audit."""
        if self._unhealthy_positions:
            logger.warning(
                "[POSITION-CACHE] Unhealthy positions (missing exit metadata): %s",
                self._unhealthy_positions
            )
```

**Invariant:** #3 (Exit Metadata Attachment)

**Testing:**
- Verify positions without TP/SL are added to unhealthy set
- Test that unhealthy positions are logged periodically
- Verify unhealthy positions are skipped in monitoring loop

---

## P2 Changes (Medium)

### #9: Add Bypass Invariant Markers to Tests

**Location:** `tests/kalshi_alignment/test_order_router.py`

**Current Code:**
```python
@pytest.mark.asyncio
async def test_multiple_contracts_rejected(self, valid_order_intent):
    valid_order_intent.count = 2
    valid_order_intent.exit_policy_id = "test_policy"  # Bypass invariant check
    
    with patch('merid.event_venues.kalshi.order_router._validate_risk_contract_linkage') as mock:
        mock.return_value = (True, None)  # Bypass invariant check
        # ... test logic
```

**Issue:** Tests bypass invariant checks without explicit markers. Violates Invariant #10 (Test Logic Bypass Prevention).

**Fix:**
```python
@pytest.mark.asyncio
@pytest.mark.bypass_invariant  # Explicit marker
async def test_multiple_contracts_rejected(self, valid_order_intent):
    """Test requires invariant bypass - reviewed and approved."""
    valid_order_intent.count = 2
    valid_order_intent.exit_policy_id = "test_policy"
    
    with patch('merid.event_venues.kalshi.order_router._validate_risk_contract_linkage') as mock:
        mock.return_value = (True, None)  # Bypass with explicit marker
        # ... test logic
```

**Add to conftest.py:**
```python
def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "bypass_invariant: Test bypasses exit policy invariant (reviewed and approved)"
    )
```

**Invariant:** #10 (Test Logic Bypass Prevention)

**Testing:**
- Verify tests with bypass markers are properly identified
- Add CI check to warn about unmarked bypasses

---

### #10: Add Exit Policy Compliance Test

**Location:** New file `tests/test_exit_policy_compliance.py`

**Current Code:** N/A

**Issue:** No comprehensive test for exit policy compliance across all invariants.

**Fix:**
```python
"""Test exit policy compliance across all invariants."""

import pytest
from merid.event_venues.kalshi.order_router import OrderIntent, _validate_risk_contract_linkage, _is_crypto_15m_market

class TestExitPolicyCompliance:
    """Test suite for exit policy invariant compliance."""
    
    def test_entry_order_requires_full_risk_contract(self):
        """Entry orders must have all risk contract fields."""
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL051900-00",
            side="yes",
            action="buy",
            price_cents=50,
            count=5,
            window_resolution_id="15m",
            exit_policy_id="standard",
            risk_tier="moderate",
            max_hold_seconds=900,
        )
        
        valid, reason = _validate_risk_contract_linkage(intent)
        assert valid, f"Valid intent should pass: {reason}"
    
    def test_entry_order_missing_window_resolution_rejected(self):
        """Entry orders without window_resolution_id are rejected."""
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL051900-00",
            side="yes",
            action="buy",
            price_cents=50,
            count=5,
            window_resolution_id=None,  # Missing
            exit_policy_id="standard",
            risk_tier="moderate",
            max_hold_seconds=900,
        )
        
        valid, reason = _validate_risk_contract_linkage(intent)
        assert not valid
        assert "window_resolution_id" in reason
    
    def test_entry_order_missing_exit_policy_rejected(self):
        """Entry orders without exit_policy_id are rejected."""
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL051900-00",
            side="yes",
            action="buy",
            price_cents=50,
            count=5,
            window_resolution_id="15m",
            exit_policy_id=None,  # Missing
            risk_tier="moderate",
            max_hold_seconds=900,
        )
        
        valid, reason = _validate_risk_contract_linkage(intent)
        assert not valid
        assert "exit_policy_id" in reason
    
    def test_exit_order_requires_exit_policy_id(self):
        """Exit orders must have exit_policy_id for tracking."""
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL051900-00",
            side="yes",
            action="sell",  # Exit order
            price_cents=50,
            count=5,
            exit_policy_id="standard",
        )
        
        valid, reason = _validate_risk_contract_linkage(intent)
        assert valid, f"Exit order with exit_policy_id should pass: {reason}"
    
    def test_exit_order_missing_exit_policy_rejected(self):
        """Exit orders without exit_policy_id are rejected."""
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL051900-00",
            side="yes",
            action="sell",  # Exit order
            price_cents=50,
            count=5,
            exit_policy_id=None,  # Missing
        )
        
        valid, reason = _validate_risk_contract_linkage(intent)
        assert not valid
        assert "exit_policy_id" in reason
    
    def test_non_crypto_markets_exempt(self):
        """Non-crypto markets are exempt from exit policy requirements."""
        intent = OrderIntent(
            ticker="KXTEST-26JUL051900-00",  # Non-crypto ticker
            side="yes",
            action="buy",
            price_cents=50,
            count=5,
            # No exit policy fields
        )
        
        valid, reason = _validate_risk_contract_linkage(intent)
        assert valid, f"Non-crypto markets should be exempt: {reason}"
```

**Invariant:** All invariants

**Testing:**
- Run test suite to verify all invariants are enforced
- Add to CI pipeline for continuous compliance checking

---

## Implementation Order

**Phase 1 (P0 - Critical):**
1. #1: Remove hardcoded `sl_cents=5` in `order_router.py`
2. #2: Remove hardcoded fallback SL in `kalshi_api.py`
3. #3: Remove hardcoded policy resolution in `main_15m_lean.py`
4. #4: Remove hardcoded fallback SL in `position_cache.py`
5. #5: Add exit policy validation to `PreTradeGate.check()`
6. #6: Refactor `sl_cents_map` in `dynamic_risk.py` to use config

**Phase 2 (P1 - High):**
7. #7: Add monitoring loop health alerts
8. #8: Add unhealthy position tracking

**Phase 3 (P2 - Medium):**
9. #9: Add bypass invariant markers to tests
10. #10: Add exit policy compliance test

---

## Rollback Plan

If any change causes issues:
1. Revert the specific change using git
2. Document the issue in `docs/EXIT_POLICY_ROLLBACK.md`
3. Escalate to team for review
4. Implement alternative fix if needed

---

## Validation Checklist

After implementing all changes:
- [ ] All P0 changes implemented and tested
- [ ] All P1 changes implemented and tested
- [ ] All P2 changes implemented and tested
- [ ] Exit policy compliance test passes
- [ ] No hardcoded magic numbers in exit logic
- [ ] Monitoring loop health alerts working
- [ ] Unhealthy position tracking working
- [ ] Pre-trade gate validates exit policy metadata
- [ ] All tests with bypass markers properly identified
- [ ] Documentation updated

---

## Next Steps

See `docs/EXIT_POLICY_TEST_TELEMETRY.md` for test and telemetry plan.
