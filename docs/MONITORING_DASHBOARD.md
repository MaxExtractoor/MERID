# Monitoring Dashboard - Compact Health Snapshot

**Objective:** Document current monitoring and propose compact health snapshot log block.

---

## Current State Analysis

### 1. Existing Health Checks

**Components with Health Checks:**
- `bankroll_service_v2.py` - `bankroll_health()` method
- `ws_bridge.py` - Periodic health log every 30s
- `kalshi_risk.py` - Risk manager health checks
- `position_cache.py` - Position cache reconciliation
- `fills_ledger.py` - Fills ledger summary

**Status:** ⚠️ Scattered health checks

**Issues:**
- 🚨 **No unified health snapshot:** Health checks are scattered across components
- 🚨 **No periodic summary:** No single periodic health log block
- 🚨 **No aggregation:** Health metrics not aggregated
- 🚨 **No alerting:** No alerting on health degradation

---

### 2. Current Health Logging

**File:** `ws_bridge.py`

```python
# Periodic health log every 30s
async def _periodic_health_log(self):
    while self._running:
        logger.info(
            "[WS-BRIDGE-HEALTH] subscribed=%d received=%d dropped=%d duplicate=%d qsize=%d",
            len(self._subscribed_tickers),
            self._fills_received,
            self._fills_dropped,
            self._fills_duplicate,
            self._message_queue.qsize(),
        )
        await asyncio.sleep(30)
```

**Status:** ⚠️ Component-specific health log

**Issues:**
- 🚨 **Only WS bridge:** Only logs WS bridge health
- 🚨 **No aggregation:** Doesn't include other components
- 🚨 **No alerting:** No alerting on degradation

---

### 3. Bankroll Health Check

**File:** `bankroll_service_v2.py`

```python
def bankroll_health(self) -> Dict[str, Any]:
    """Return health status of bankroll service."""
    return {
        "state": self._current.state.name if self._current else "UNKNOWN",
        "last_success": self._last_success.isoformat() if self._last_success else None,
        "last_error": self._last_error,
        "fetch_count": self._fetch_count,
        "error_count": self._error_count,
        "equity_usd": float(self._current.equity_usd) if self._current else None,
    }
```

**Status:** ✅ Bankroll health check exists

**Issues:**
- ⚠️ **Not called periodically:** Only called on demand
- ⚠️ **No alerting:** No alerting on state changes

---

### 4. Risk Manager Health Checks

**File:** `kalshi_risk.py`

```python
def health_check(self) -> Dict[str, Any]:
    """Return health status of risk manager."""
    return {
        "active": self._active,
        "category_contracts": self._category_contracts,
        "daily_pnl_cents": self._daily_pnl_cents,
        "drawdown_tier": self._drawdown_tier,
        "breach_count": self._breach_count,
    }
```

**Status:** ✅ Risk manager health check exists

**Issues:**
- ⚠️ **Not called periodically:** Only called on demand
- ⚠️ **No alerting:** No alerting on breach count changes

---

## Required Fixes

### Fix 1: Create Unified Health Snapshot

**Create:** `merid/monitoring/health_snapshot.py`

```python
class HealthSnapshot:
    """Unified health snapshot for all components."""
    
    def __init__(self):
        self._components: Dict[str, Any] = {}
    
    def register_component(self, name: str, component: Any) -> None:
        """Register a component for health monitoring."""
        self._components[name] = component
    
    async def get_snapshot(self) -> Dict[str, Any]:
        """Get unified health snapshot."""
        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": {},
        }
        
        for name, component in self._components.items():
            if hasattr(component, "health_check"):
                snapshot["components"][name] = await component.health_check()
            elif hasattr(component, "bankroll_health"):
                snapshot["components"][name] = component.bankroll_health()
            else:
                snapshot["components"][name] = {"status": "no_health_check"}
        
        return snapshot
    
    def format_compact(self, snapshot: Dict[str, Any]) -> str:
        """Format snapshot as compact log block."""
        lines = [
            f"[HEALTH-SNAPSHOT] {snapshot['timestamp']}",
        ]
        
        for name, health in snapshot["components"].items():
            if "state" in health:
                lines.append(f"  {name}: state={health['state']}")
            elif "active" in health:
                lines.append(f"  {name}: active={health['active']}")
            else:
                lines.append(f"  {name}: {health.get('status', 'unknown')}")
        
        return "\n".join(lines)
```

**Implementation:**
1. Create unified health snapshot
2. Register all components
3. Aggregate health checks
4. Format as compact log block

---

### Fix 2: Add Periodic Health Logger

**Create:** `merid/monitoring/health_logger.py`

```python
class HealthLogger:
    """Periodic health logger with compact snapshot."""
    
    def __init__(self, snapshot: HealthSnapshot, interval_seconds: int = 60):
        self._snapshot = snapshot
        self._interval_seconds = interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        """Start periodic health logging."""
        self._running = True
        self._task = asyncio.create_task(self._log_loop())
    
    async def stop(self) -> None:
        """Stop periodic health logging."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
    
    async def _log_loop(self) -> None:
        """Periodic health logging loop."""
        while self._running:
            try:
                snapshot = await self._snapshot.get_snapshot()
                compact = self._snapshot.format_compact(snapshot)
                logger.info(compact)
            except Exception as e:
                logger.error(f"[HEALTH-LOGGER] Failed to log health: {e}")
            
            await asyncio.sleep(self._interval_seconds)
```

**Implementation:**
1. Create health logger
2. Start periodic logging
3. Format compact snapshot
4. Handle errors gracefully

---

### Fix 3: Register Components

**File:** `merid/monitoring/__init__.py`

**Add:**
```python
from merid.monitoring.health_snapshot import HealthSnapshot
from merid.monitoring.health_logger import HealthLogger

_snapshot: Optional[HealthSnapshot] = None
_logger: Optional[HealthLogger] = None

def get_health_snapshot() -> HealthSnapshot:
    """Get global health snapshot."""
    global _snapshot
    if _snapshot is None:
        _snapshot = HealthSnapshot()
    return _snapshot

def get_health_logger() -> HealthLogger:
    """Get global health logger."""
    global _logger
    if _logger is None:
        _logger = HealthLogger(get_health_snapshot())
    return _logger

async def start_health_monitoring() -> None:
    """Start health monitoring."""
    logger = get_health_logger()
    await logger.start()

async def stop_health_monitoring() -> None:
    """Stop health monitoring."""
    logger = get_health_logger()
    await logger.stop()
```

**Implementation:**
1. Create global instances
2. Add getter functions
3. Add start/stop functions
4. Register components on startup

---

### Fix 4: Register Components on Startup

**File:** `merid/prediction/agent_grid_15m.py`

**Add:**
```python
async def start(self) -> None:
    """Start agent grid with health monitoring."""
    # Register components for health monitoring
    from merid.monitoring import get_health_snapshot
    snapshot = get_health_snapshot()
    
    snapshot.register_component("bankroll", self._bankroll_service)
    snapshot.register_component("ws_bridge", self._ws_bridge)
    snapshot.register_component("risk_manager", self._risk_manager)
    snapshot.register_component("position_cache", self._position_cache)
    snapshot.register_component("fills_ledger", self._fills_ledger)
    
    # Start health monitoring
    from merid.monitoring import start_health_monitoring
    await start_health_monitoring()
    
    # Continue with normal startup
    ...
```

**Implementation:**
1. Register components on startup
2. Start health monitoring
3. Stop health monitoring on shutdown

---

### Fix 5: Add Health Alerting

**Create:** `merid/monitoring/health_alerting.py`

```python
class HealthAlerter:
    """Health alerting with thresholds."""
    
    def __init__(self, snapshot: HealthSnapshot):
        self._snapshot = snapshot
        self._thresholds: Dict[str, Dict[str, Any]] = {
            "bankroll": {"error_count": 5},
            "ws_bridge": {"fills_dropped": 10},
            "risk_manager": {"breach_count": 3},
        }
    
    async def check_alerts(self) -> List[Dict[str, Any]]:
        """Check for health alerts."""
        snapshot = await self._snapshot.get_snapshot()
        alerts = []
        
        for name, health in snapshot["components"].items():
            if name in self._thresholds:
                for metric, threshold in self._thresholds[name].items():
                    if metric in health and health[metric] > threshold:
                        alerts.append({
                            "component": name,
                            "metric": metric,
                            "value": health[metric],
                            "threshold": threshold,
                            "severity": "warning" if health[metric] < threshold * 2 else "critical",
                        })
        
        return alerts
    
    async def start_alerting(self, interval_seconds: int = 60) -> None:
        """Start periodic alert checking."""
        while True:
            alerts = await self.check_alerts()
            for alert in alerts:
                logger.warning(
                    f"[HEALTH-ALERT] {alert['component']}.{alert['metric']} "
                    f"={alert['value']} (threshold={alert['threshold']}, severity={alert['severity']})"
                )
            await asyncio.sleep(interval_seconds)
```

**Implementation:**
1. Create health alerter
2. Define thresholds
3. Check alerts periodically
4. Log alerts

---

## Audit Checklist

- [ ] Document existing health checks (✅ documented)
- [ ] Document current health logging (✅ documented)
- [ ] Document bankroll health check (✅ documented)
- [ ] Document risk manager health checks (✅ documented)
- [ ] Identify no unified health snapshot (🚨 scattered checks)
- [ ] Identify no periodic summary (🚨 no single log block)
- [ ] Identify no aggregation (🚨 metrics not aggregated)
- [ ] Identify no alerting (🚨 no alerting on degradation)
- [ ] Plan migration path (5 fixes)
- [ ] Create unified health snapshot
- [ ] Add periodic health logger
- [ ] Register components
- [ ] Register components on startup
- [ ] Add health alerting

---

## Next Steps

1. **Immediate:** Create unified health snapshot
2. **Immediate:** Add periodic health logger
3. **Short-term:** Register components
4. **Short-term:** Register components on startup
5. **Medium-term:** Add health alerting
6. **Medium-term:** Add health dashboard UI
7. **Long-term:** Add automated recovery on alerts

**Priority:** MEDIUM - Health monitoring is important but not critical for initial live trading

**Risk:** Without unified health monitoring, it's difficult to detect system-wide issues quickly.

**Note:** Current health checks are scattered and not aggregated. Need to create a unified health snapshot with periodic logging and alerting.
