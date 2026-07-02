# Dry-Run (Paper) Execution Mode

**Objective:** Document current paper trading infrastructure and propose dry-run harness.

---

## Current State Analysis

### 1. Existing Paper Trading Infrastructure

**Components Found:**
- `testing.py` - `run_paper_scenario()` and `get_paper_metrics()`
- `strategies/production_strategy_15m.py` - `paper_mode` parameter and `_simulate_paper_trades()`
- `settings.py` - `MERID_TRADING_MODE` with default "paper"
- `startup_validations.py` - Paper mode validation
- `reconciliation.py` - Paper engine reconciliation
- `swarm/matrix.py` - Paper session and promotion stages

**Status:** ⚠️ Fragmented paper trading infrastructure

**Issues:**
- 🚨 **No unified dry-run harness:** Paper trading is scattered across multiple modules
- 🚨 **No order logging:** Orders are simulated, not logged for analysis
- 🚨 **No replay capability:** Cannot replay logged orders
- 🚨 **No comparison:** Cannot compare paper vs live execution

---

### 2. Current Paper Mode Implementation

**File:** `strategies/production_strategy_15m.py`

```python
def __init__(self, capital_usd: float = 100000.0, paper_mode: bool = True):
    self.paper_mode = paper_mode

def execute_trades(self, positions: Dict) -> List[Dict]:
    if not self.paper_mode:
        # Live execution
        trades_executed = self._execute_live_trades(positions)
    else:
        # Paper trading simulation
        trades_executed = self._simulate_paper_trades(positions)
    return trades_executed

def _simulate_paper_trades(self, positions: Dict) -> List[Dict]:
    """Simulate paper trades for testing."""
    # Simple simulation without actual execution
    return [{"paper_mode": True, ...}]
```

**Status:** ⚠️ Basic simulation without logging

**Issues:**
- 🚨 **No order logging:** Orders are not logged to file/database
- 🚨 **No fill simulation:** Fills are not realistically simulated
- 🚨 **No PnL tracking:** Paper PnL is not tracked accurately
- 🚨 **No slippage:** No slippage simulation

---

### 3. Testing Harness

**File:** `testing.py`

```python
def run_paper_scenario(
    initial_capital: int = 1000,
    ticks: int = 50000,
    strategy: Optional[Callable] = None,
) -> PaperMetrics:
    """Run a full paper-trading scenario and return metrics."""
    engine = PaperTradingEngine.__new__(PaperTradingEngine)
    # Feed synthetic price data
    # Run strategy
    # Return metrics
```

**Status:** ⚠️ Limited to synthetic data

**Issues:**
- 🚨 **Synthetic data only:** Cannot use real market data
- 🚨 **No real-time:** Not suitable for real-time paper trading
- 🚨 **No order logging:** Orders are not logged
- 🚨 **No replay:** Cannot replay scenarios

---

### 4. Configuration

**File:** `settings.py`

```python
MERID_TRADING_MODE: str = Field(default="paper", description="Trading mode: paper or live")

def is_paper_trading(self) -> bool:
    """Check if running in paper trading mode."""
    return self.MERID_TRADING_MODE.lower() == "paper"
```

**Status:** ✅ Configuration exists

**Issues:**
- ⚠️ **No dry-run mode:** Only paper vs live, no dry-run (log-only) mode
- ⚠️ **No validation:** No validation that paper mode is actually being used

---

## Required Fixes

### Fix 1: Create Dry-Run Harness

**Create:** `merid/execution/dry_run_harness.py`

```python
class DryRunHarness:
    """Dry-run execution harness - logs orders instead of executing."""
    
    def __init__(self, log_file: str = "dry_run_orders.jsonl"):
        self._log_file = log_file
        self._orders: List[Dict[str, Any]] = []
        self._fills: List[Dict[str, Any]] = []
        self._pnl: float = 0.0
        self._lock = asyncio.Lock()
    
    async def place_order(
        self,
        market_id: str,
        side: str,
        size: int,
        price: float,
        order_type: str = "limit",
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Log order instead of executing."""
        order = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "market_id": market_id,
            "side": side,
            "size": size,
            "price": price,
            "order_type": order_type,
            "client_order_id": client_order_id or f"dry_run_{uuid4().hex}",
            "status": "logged",
        }
        
        async with self._lock:
            self._orders.append(order)
            await self._log_order(order)
        
        logger.info(f"[DRY-RUN] Order logged: {side} {size} @ {price} on {market_id}")
        return order
    
    async def simulate_fill(
        self,
        order: Dict[str, Any],
        fill_price: float,
        fill_size: int,
    ) -> Dict[str, Any]:
        """Simulate a fill for a logged order."""
        fill = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "order_id": order["client_order_id"],
            "fill_price": fill_price,
            "fill_size": fill_size,
            "fee": self._calculate_fee(fill_price, fill_size),
        }
        
        async with self._lock:
            self._fills.append(fill)
            await self._log_fill(fill)
            self._pnl += self._calculate_pnl(order, fill)
        
        logger.info(f"[DRY-RUN] Fill simulated: {fill_size} @ {fill_price}")
        return fill
    
    def _calculate_fee(self, price: float, size: int) -> float:
        """Calculate fee using Kalshi parabolic formula."""
        from merid.event_venues.kalshi.parabolic_fees import kalshi_fee_cents_parabolic
        fee_cents = kalshi_fee_cents_parabolic(price, size, role="taker")
        return fee_cents / 100.0
    
    def _calculate_pnl(self, order: Dict[str, Any], fill: Dict[str, Any]) -> float:
        """Calculate PnL for a fill."""
        # Simplified PnL calculation
        if order["side"] == "buy":
            return (fill["fill_price"] - order["price"]) * fill["fill_size"] - fill["fee"]
        else:
            return (order["price"] - fill["fill_price"]) * fill["fill_size"] - fill["fee"]
    
    async def _log_order(self, order: Dict[str, Any]) -> None:
        """Log order to file."""
        with open(self._log_file, "a") as f:
            f.write(json.dumps(order) + "\n")
    
    async def _log_fill(self, fill: Dict[str, Any]) -> None:
        """Log fill to file."""
        with open(self._log_file.replace("orders", "fills"), "a") as f:
            f.write(json.dumps(fill) + "\n")
    
    def get_summary(self) -> Dict[str, Any]:
        """Get dry-run summary."""
        return {
            "total_orders": len(self._orders),
            "total_fills": len(self._fills),
            "total_pnl": self._pnl,
            "orders": self._orders,
            "fills": self._fills,
        }
    
    async def replay(self, log_file: str) -> Dict[str, Any]:
        """Replay logged orders."""
        orders = []
        with open(log_file, "r") as f:
            for line in f:
                orders.append(json.loads(line))
        
        # Replay orders
        for order in orders:
            logger.info(f"[DRY-RUN-REPLAY] Replaying: {order}")
            # Simulate fills based on historical data
        
        return {"replayed_orders": len(orders)}
```

**Implementation:**
1. Create dry-run harness
2. Log orders to JSONL file
3. Simulate fills
4. Calculate PnL
5. Add replay capability

---

### Fix 2: Integrate Dry-Run into Order Router

**File:** `merid/event_venues/kalshi/order_router.py`

**Add:**
```python
class OrderRouter:
    def __init__(self, dry_run: bool = False):
        self._dry_run = dry_run
        if dry_run:
            from merid.execution.dry_run_harness import DryRunHarness
            self._dry_run_harness = DryRunHarness()
    
    async def route_order(self, order: VenueOrder) -> OperationResult[PlacedOrder]:
        """Route order to venue or dry-run harness."""
        if self._dry_run:
            return await self._route_dry_run(order)
        else:
            return await self._route_live(order)
    
    async def _route_dry_run(self, order: VenueOrder) -> OperationResult[PlacedOrder]:
        """Route order to dry-run harness."""
        logged_order = await self._dry_run_harness.place_order(
            market_id=order.market_id,
            side=order.side,
            size=int(order.size),
            price=float(order.price),
            order_type=order.order_type,
            client_order_id=order.client_order_id,
        )
        
        # Simulate fill immediately (for simplicity)
        fill = await self._dry_run_harness.simulate_fill(
            logged_order,
            fill_price=float(order.price),
            fill_size=int(order.size),
        )
        
        return OperationResult.ok(
            PlacedOrder(
                order_id=logged_order["client_order_id"],
                status="filled",
                filled_size=int(order.size),
                avg_price=float(order.price),
            )
        )
```

**Implementation:**
1. Add dry_run parameter to OrderRouter
2. Integrate dry-run harness
3. Route orders to dry-run when enabled
4. Simulate fills

---

### Fix 3: Add Dry-Run Configuration

**File:** `settings.py`

**Add:**
```python
MERID_DRY_RUN_MODE: bool = Field(default=False, description="Dry-run mode: log orders instead of executing")
MERID_DRY_RUN_LOG_FILE: str = Field(default="dry_run_orders.jsonl", description="Dry-run log file path")
```

**Implementation:**
1. Add dry-run mode configuration
2. Add log file path configuration
3. Document dry-run usage

---

### Fix 4: Add Dry-Run Validation

**File:** `startup_validations.py`

**Add:**
```python
def validate_dry_run_mode() -> Tuple[bool, str]:
    """Validate dry-run mode configuration."""
    from merid.settings import get_settings
    settings = get_settings()
    
    if settings.MERID_DRY_RUN_MODE:
        if settings.MERID_TRADING_MODE != "paper":
            return False, "MERID_DRY_RUN_MODE requires MERID_TRADING_MODE=paper"
        
        if not settings.MERID_DRY_RUN_LOG_FILE:
            return False, "MERID_DRY_RUN_LOG_FILE must be set when dry-run mode is enabled"
    
    return True, "OK"
```

**Implementation:**
1. Add dry-run validation
2. Check trading mode compatibility
3. Check log file configuration
4. Add to startup validations

---

### Fix 5: Add Dry-Run Monitoring

**Create:** `merid/execution/dry_run_monitor.py`

```python
class DryRunMonitor:
    """Monitor dry-run execution and report metrics."""
    
    def __init__(self, harness: DryRunHarness):
        self._harness = harness
    
    async def start_monitoring(self, interval_seconds: int = 60) -> None:
        """Start periodic monitoring."""
        while True:
            summary = self._harness.get_summary()
            logger.info(
                "[DRY-RUN-MONITOR] Orders: %d, Fills: %d, PnL: $%.2f",
                summary["total_orders"],
                summary["total_fills"],
                summary["total_pnl"],
            )
            await asyncio.sleep(interval_seconds)
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate dry-run report."""
        summary = self._harness.get_summary()
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_orders": summary["total_orders"],
            "total_fills": summary["total_fills"],
            "total_pnl": summary["total_pnl"],
            "fill_rate": summary["total_fills"] / summary["total_orders"] if summary["total_orders"] > 0 else 0,
            "avg_pnl_per_order": summary["total_pnl"] / summary["total_orders"] if summary["total_orders"] > 0 else 0,
        }
```

**Implementation:**
1. Create dry-run monitor
2. Add periodic monitoring
3. Generate reports
4. Log metrics

---

## Audit Checklist

- [ ] Document existing paper trading infrastructure (✅ documented)
- [ ] Document current paper mode implementation (✅ documented)
- [ ] Document testing harness (✅ documented)
- [ ] Document configuration (✅ documented)
- [ ] Identify no unified dry-run harness (🚨 scattered infrastructure)
- [ ] Identify no order logging (🚨 orders not logged)
- [ ] Identify no replay capability (🚨 cannot replay)
- [ ] Identify no comparison (🚨 cannot compare paper vs live)
- [ ] Plan migration path (5 fixes)
- [ ] Create dry-run harness
- [ ] Integrate dry-run into order router
- [ ] Add dry-run configuration
- [ ] Add dry-run validation
- [ ] Add dry-run monitoring

---

## Next Steps

1. **Immediate:** Create dry-run harness
2. **Immediate:** Integrate dry-run into order router
3. **Short-term:** Add dry-run configuration
4. **Short-term:** Add dry-run validation
5. **Medium-term:** Add dry-run monitoring
6. **Medium-term:** Add replay capability
7. **Long-term:** Add paper vs live comparison

**Priority:** HIGH - Dry-run mode is essential for testing before live trading

**Risk:** Without a proper dry-run harness, testing before live trading is difficult and error-prone.

**Note:** Current paper trading infrastructure is fragmented and lacks order logging. Need to create a unified dry-run harness that logs orders and enables replay.
