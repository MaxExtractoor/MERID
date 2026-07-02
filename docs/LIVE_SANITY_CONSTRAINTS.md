# Live Trading Safety Rails

**Objective:** Document current safety constraints and propose strong safety rails for first live trading.

---

## Current State Analysis

### 1. Existing Safety Mechanisms

**Components with Safety Mechanisms:**
- `kalshi_risk.py` - Risk caps, drawdown tiers, breach counting
- `global_execution_guard.py` - Global execution guard (last line of defense)
- `policy_sanity_harness.py` - Policy validation and fee validation
- `position_sanity_checker.py` - Position sanity checks
- `startup_validations.py` - Startup validation checks

**Status:** ⚠️ Safety mechanisms exist but are scattered

**Issues:**
- 🚨 **No kill-switch:** No global kill-switch to stop all trading
- 🚨 **No position caps:** No per-market position caps for first live trading
- 🚨 **No notional caps:** No total notional exposure cap
- 🚨 **No daily loss cap:** No daily loss cap for first live trading
- 🚨 **No rate limiting:** No order rate limiting

---

### 2. Risk Manager Caps

**File:** `kalshi_risk.py`

```python
# Risk caps from profile
class KalshiRiskConfig:
    max_position_contracts: int = 10000  # Kalshi limit
    max_order_contracts: int = 10000  # Kalshi limit
    max_open_positions: int = 100  # Kalshi limit
    
    # Profile-specific caps
    category_contracts: Dict[str, int]  # Per-category caps
    venue_contracts: int  # Total venue cap
```

**Status:** ✅ Risk caps exist

**Issues:**
- ⚠️ **Too high for first live trading:** 10,000 contracts is too high for first live
- ⚠️ **No conservative mode:** No conservative mode for first live trading
- ⚠️ **No kill-switch:** No way to quickly disable all trading

---

### 3. Global Execution Guard

**File:** `guards/global_execution_guard.py`

```python
class GlobalExecutionGuard:
    """Last line of defense for order execution."""
    
    def check_order(
        self,
        ticker: str,
        contracts: int,
        price_cents: int,
        source: str,
        asset: Optional[str] = None,
        action: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Check if order should be allowed."""
        # Check various safety conditions
        # Return (allowed, reason)
```

**Status:** ✅ Global execution guard exists

**Issues:**
- ⚠️ **No kill-switch:** No global kill-switch to disable all orders
- ⚠️ **No per-asset caps:** No per-asset position caps
- ⚠️ **No notional cap:** No total notional exposure cap

---

### 4. Drawdown Tiers

**File:** `kalshi_risk.py`

```python
# Drawdown tiers
DRAWDOWN_TIER_NORMAL = "normal"
DRAWDOWN_TIER_WARNING = "warning"
DRAWDOWN_TIER_DOWNSIZE = "downsize"
DRAWDOWN_TIER_HALT = "halt"

# Tier thresholds
DRAWDOWN_WARNING_PCT = 0.05  # 5%
DRAWDOWN_DOWNSIZE_PCT = 0.10  # 10%
DRAWDOWN_HALT_PCT = 0.20  # 20%
```

**Status:** ✅ Drawdown tiers exist

**Issues:**
- ⚠️ **Too high for first live trading:** 20% halt is too high for first live
- ⚠️ **No aggressive mode:** No aggressive mode for first live trading

---

## Required Fixes

### Fix 1: Add Global Kill-Switch

**Create:** `merid/guards/kill_switch.py`

```python
class KillSwitch:
    """Global kill-switch to stop all trading."""
    
    def __init__(self):
        self._enabled = False
        self._reason: Optional[str] = None
        self._enabled_at: Optional[datetime] = None
        self._lock = asyncio.Lock()
    
    async def enable(self, reason: str) -> None:
        """Enable kill-switch (stop all trading)."""
        async with self._lock:
            self._enabled = True
            self._reason = reason
            self._enabled_at = datetime.now(timezone.utc)
            logger.critical(f"[KILL-SWITCH] ENABLED: {reason}")
    
    async def disable(self) -> None:
        """Disable kill-switch (resume trading)."""
        async with self._lock:
            self._enabled = False
            self._reason = None
            self._enabled_at = None
            logger.critical("[KILL-SWITCH] DISABLED")
    
    def is_enabled(self) -> bool:
        """Check if kill-switch is enabled."""
        return self._enabled
    
    def get_status(self) -> Dict[str, Any]:
        """Get kill-switch status."""
        return {
            "enabled": self._enabled,
            "reason": self._reason,
            "enabled_at": self._enabled_at.isoformat() if self._enabled_at else None,
        }
    
    async def check_order(self) -> Tuple[bool, Optional[str]]:
        """Check if order should be allowed (kill-switch check)."""
        if self._enabled:
            return False, f"Kill-switch enabled: {self._reason}"
        return True, None
```

**Implementation:**
1. Create kill-switch
2. Add enable/disable methods
3. Add status method
4. Integrate into order routing

---

### Fix 2: Add Conservative Mode Caps

**File:** `merid/risk/conservative_caps.py`

```python
@dataclass(frozen=True)
class ConservativeCaps:
    """Conservative caps for first live trading."""
    
    # Per-market position caps (very conservative)
    max_position_contracts_per_market: int = 10  # 10 contracts per market
    max_order_contracts_per_market: int = 5  # 5 contracts per order
    
    # Total notional caps
    max_total_notional_usd: float = 1000.0  # $1000 total notional
    max_per_asset_notional_usd: float = 200.0  # $200 per asset
    
    # Daily loss cap
    max_daily_loss_usd: float = 100.0  # $100 daily loss cap
    
    # Order rate limiting
    max_orders_per_minute: int = 10  # 10 orders per minute
    max_orders_per_hour: int = 100  # 100 orders per hour
    
    # Drawdown tiers (aggressive)
    drawdown_warning_pct: float = 0.02  # 2%
    drawdown_downsize_pct: float = 0.05  # 5%
    drawdown_halt_pct: float = 0.10  # 10%
    
    @classmethod
    def default(cls) -> "ConservativeCaps":
        """Return default conservative caps."""
        return cls()
    
    @classmethod
    def aggressive(cls) -> "ConservativeCaps":
        """Return aggressive conservative caps (for testing)."""
        return cls(
            max_position_contracts_per_market=5,
            max_order_contracts_per_market=3,
            max_total_notional_usd=500.0,
            max_per_asset_notional_usd=100.0,
            max_daily_loss_usd=50.0,
        )
```

**Implementation:**
1. Create conservative caps dataclass
2. Add default and aggressive modes
3. Add validation methods
4. Integrate into risk manager

---

### Fix 3: Add Conservative Mode Toggle

**File:** `settings.py`

**Add:**
```python
MERID_CONSERVATIVE_MODE: bool = Field(default=False, description="Conservative mode for first live trading")
```

**Implementation:**
1. Add conservative mode configuration
2. Document conservative mode usage
3. Add validation

---

### Fix 4: Integrate Conservative Caps into Risk Manager

**File:** `merid/event_venues/kalshi/kalshi_risk.py`

**Add:**
```python
class KalshiRiskManager:
    def __init__(self, conservative_mode: bool = False):
        self._conservative_mode = conservative_mode
        if conservative_mode:
            from merid.risk.conservative_caps import ConservativeCaps
            self._conservative_caps = ConservativeCaps.default()
        else:
            self._conservative_caps = None
    
    def check_order_conservative(
        self,
        ticker: str,
        contracts: int,
        price_cents: int,
        asset: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Check order against conservative caps."""
        if not self._conservative_mode:
            return True, None
        
        caps = self._conservative_caps
        
        # Check per-market position cap
        current_position = self._get_position_contracts(ticker)
        if current_position + contracts > caps.max_position_contracts_per_market:
            return False, f"Exceeds per-market position cap: {current_position + contracts} > {caps.max_position_contracts_per_market}"
        
        # Check per-order cap
        if contracts > caps.max_order_contracts_per_market:
            return False, f"Exceeds per-order cap: {contracts} > {caps.max_order_contracts_per_market}"
        
        # Check total notional cap
        notional_usd = (contracts * price_cents) / 100.0
        current_notional = self._get_total_notional_usd()
        if current_notional + notional_usd > caps.max_total_notional_usd:
            return False, f"Exceeds total notional cap: ${current_notional + notional_usd:.2f} > ${caps.max_total_notional_usd:.2f}"
        
        # Check per-asset notional cap
        if asset:
            asset_notional = self._get_asset_notional_usd(asset)
            if asset_notional + notional_usd > caps.max_per_asset_notional_usd:
                return False, f"Exceeds per-asset notional cap: ${asset_notional + notional_usd:.2f} > ${caps.max_per_asset_notional_usd:.2f}"
        
        return True, None
```

**Implementation:**
1. Add conservative mode to risk manager
2. Add conservative caps check
3. Integrate into order routing
4. Log conservative mode violations

---

### Fix 5: Add Order Rate Limiting

**Create:** `merid/guards/rate_limiter.py`

```python
class OrderRateLimiter:
    """Order rate limiting."""
    
    def __init__(self, max_per_minute: int = 10, max_per_hour: int = 100):
        self._max_per_minute = max_per_minute
        self._max_per_hour = max_per_hour
        self._orders_minute: List[datetime] = []
        self._orders_hour: List[datetime] = []
        self._lock = asyncio.Lock()
    
    async def check_order(self) -> Tuple[bool, Optional[str]]:
        """Check if order should be allowed (rate limit check)."""
        async with self._lock:
            now = datetime.now(timezone.utc)
            
            # Clean old orders
            self._orders_minute = [t for t in self._orders_minute if (now - t).total_seconds() < 60]
            self._orders_hour = [t for t in self._orders_hour if (now - t).total_seconds() < 3600]
            
            # Check minute limit
            if len(self._orders_minute) >= self._max_per_minute:
                return False, f"Rate limit exceeded: {len(self._orders_minute)} orders/minute > {self._max_per_minute}"
            
            # Check hour limit
            if len(self._orders_hour) >= self._max_per_hour:
                return False, f"Rate limit exceeded: {len(self._orders_hour)} orders/hour > {self._max_per_hour}"
            
            # Record order
            self._orders_minute.append(now)
            self._orders_hour.append(now)
            
            return True, None
    
    def get_status(self) -> Dict[str, Any]:
        """Get rate limiter status."""
        return {
            "orders_minute": len(self._orders_minute),
            "orders_hour": len(self._orders_hour),
            "max_per_minute": self._max_per_minute,
            "max_per_hour": self._max_per_hour,
        }
```

**Implementation:**
1. Create rate limiter
2. Add per-minute and per-hour limits
3. Integrate into order routing
4. Add status method

---

### Fix 6: Add Daily Loss Cap

**File:** `merid/event_venues/kalshi/kalshi_risk.py`

**Add:**
```python
class KalshiRiskManager:
    def __init__(self, conservative_mode: bool = False):
        self._conservative_mode = conservative_mode
        if conservative_mode:
            from merid.risk.conservative_caps import ConservativeCaps
            self._conservative_caps = ConservativeCaps.default()
        else:
            self._conservative_caps = None
        
        self._daily_pnl_start = 0.0
        self._daily_pnl_current = 0.0
        self._daily_pnl_date = datetime.now(timezone.utc).date()
    
    def check_daily_loss_cap(self) -> Tuple[bool, Optional[str]]:
        """Check if daily loss cap is exceeded."""
        if not self._conservative_mode:
            return True, None
        
        # Reset daily PnL if new day
        today = datetime.now(timezone.utc).date()
        if today != self._daily_pnl_date:
            self._daily_pnl_start = self._daily_pnl_current
            self._daily_pnl_date = today
        
        daily_pnl = self._daily_pnl_current - self._daily_pnl_start
        max_loss = self._conservative_caps.max_daily_loss_usd
        
        if daily_pnl < -max_loss:
            return False, f"Daily loss cap exceeded: ${daily_pnl:.2f} < -${max_loss:.2f}"
        
        return True, None
```

**Implementation:**
1. Add daily loss cap check
2. Track daily PnL
3. Reset on new day
4. Integrate into order routing

---

### Fix 7: Integrate All Safety Rails into Order Router

**File:** `merid/event_venues/kalshi/order_router.py`

**Add:**
```python
class OrderRouter:
    def __init__(self, conservative_mode: bool = False):
        self._conservative_mode = conservative_mode
        
        if conservative_mode:
            from merid.guards.kill_switch import KillSwitch
            from merid.guards.rate_limiter import OrderRateLimiter
            self._kill_switch = KillSwitch()
            self._rate_limiter = OrderRateLimiter()
        else:
            self._kill_switch = None
            self._rate_limiter = None
    
    async def route_order(self, order: VenueOrder) -> OperationResult[PlacedOrder]:
        """Route order with all safety checks."""
        # Kill-switch check
        if self._kill_switch:
            allowed, reason = await self._kill_switch.check_order()
            if not allowed:
                return OperationResult.fail(f"Kill-switch: {reason}")
        
        # Rate limit check
        if self._rate_limiter:
            allowed, reason = await self._rate_limiter.check_order()
            if not allowed:
                return OperationResult.fail(f"Rate limit: {reason}")
        
        # Conservative caps check
        if self._conservative_mode:
            allowed, reason = self._risk_manager.check_order_conservative(
                order.market_id,
                int(order.size),
                int(order.price * 100),
                order.metadata.get("asset"),
            )
            if not allowed:
                return OperationResult.fail(f"Conservative cap: {reason}")
        
        # Daily loss cap check
        if self._conservative_mode:
            allowed, reason = self._risk_manager.check_daily_loss_cap()
            if not allowed:
                return OperationResult.fail(f"Daily loss cap: {reason}")
        
        # Route order normally
        return await self._route_live(order)
```

**Implementation:**
1. Integrate kill-switch
2. Integrate rate limiter
3. Integrate conservative caps
4. Integrate daily loss cap
5. Log all safety check failures

---

## Audit Checklist

- [ ] Document existing safety mechanisms (✅ documented)
- [ ] Document risk manager caps (✅ documented)
- [ ] Document global execution guard (✅ documented)
- [ ] Document drawdown tiers (✅ documented)
- [ ] Identify no kill-switch (🚨 no global kill-switch)
- [ ] Identify no position caps (🚨 no per-market caps)
- [ ] Identify no notional caps (🚨 no total notional cap)
- [ ] Identify no daily loss cap (🚨 no daily loss cap)
- [ ] Identify no rate limiting (🚨 no order rate limiting)
- [ ] Plan migration path (7 fixes)
- [ ] Add global kill-switch
- [ ] Add conservative mode caps
- [ ] Add conservative mode toggle
- [ ] Integrate conservative caps into risk manager
- [ ] Add order rate limiting
- [ ] Add daily loss cap
- [ ] Integrate all safety rails into order router

---

## Next Steps

1. **Immediate:** Add global kill-switch
2. **Immediate:** Add conservative mode caps
3. **Short-term:** Add conservative mode toggle
4. **Short-term:** Integrate conservative caps into risk manager
5. **Medium-term:** Add order rate limiting
6. **Medium-term:** Add daily loss cap
7. **Medium-term:** Integrate all safety rails into order router

**Priority:** HIGH - Safety rails are critical for first live trading

**Risk:** Without strong safety rails, first live trading could result in significant losses due to bugs or misconfigurations.

**Note:** Current safety mechanisms are scattered and not conservative enough for first live trading. Need to add a global kill-switch, conservative mode with tight caps, rate limiting, and daily loss cap.
