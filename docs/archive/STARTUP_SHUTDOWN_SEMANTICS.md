# Startup and Shutdown Semantics Audit

**Objective:** Document current startup/shutdown behavior and identify issues.

---

## Current State Analysis

### 1. Startup Methods

**Count:** 32 async def start() methods found across the codebase

**Key Components:**
- `agent_grid_15m.py` - Agent grid startup
- `ws_bridge.py` - WebSocket bridge startup
- `market_catalog.py` - Market catalog startup
- `fills_ledger.py` - Fills ledger startup
- `bankroll_service_v2.py` - Bankroll service startup
- `settlement_poller.py` - Settlement poller startup
- `resting_order_monitor.py` - Resting order monitor startup
- `portfolio_reconciliation.py` - Portfolio reconciliation startup
- `order_group_manager.py` - Order group manager startup
- `crypto_scheduler.py` - Crypto scheduler startup
- `candle_poller.py` - Candle poller startup
- `auto_promoter.py` - Auto promoter startup
- `edge_recalibrator.py` - Edge recalibrator startup
- `portfolio_risk_agent.py` - Portfolio risk agent startup
- `execution_queue_handler.py` - Execution queue handler startup
- `kalshi_robustness.py` - Kalshi robustness startup
- `loop_robustness.py` - Loop robustness startup
- `risk_monitor.py` - Risk monitor startup
- `ws_price_feed.py` - WS price feed startup
- `backtest_scheduler.py` - Backtest scheduler startup
- `band_strategy_agent.py` - Band strategy agent startup
- `outcome_resolver.py` - Outcome resolver startup
- `mcp_market_feed.py` - MCP market feed startup
- `pipeline_integration.py` - Pipeline integration startup
- `market_cache.py` - Market cache startup
- `wiring_service.py` - Wiring service startup
- `ticker_collector.py` - Ticker collector startup
- `order_group_lifecycle.py` - Order group lifecycle startup
- `universal_agent.py` - Universal agent startup
- `loop_15m.py` - Loop 15m startup
- `whales.py` - Whales startup
- `crypto_term_structure.py` - Crypto term structure startup
- `critic_agent.py` - Critic agent startup
- `execution_subscriber.py` - Execution subscriber startup
- `rti_feed_service.py` - RTI feed service startup

**Status:** ⚠️ Many independent startup methods

**Issues:**
- 🚨 **No centralized startup coordinator:** Each component starts independently
- 🚨 **No dependency management:** No explicit startup sequence
- 🚨 **No startup validation:** No health checks after startup
- 🚨 **No startup timeout:** Components can hang indefinitely

---

### 2. Shutdown Methods

**Count:** 3 async def shutdown() methods found

**Key Components:**
- `loop.py` - Main loop shutdown
- `pipeline/robustness.py` - Pipeline robustness shutdown
- `fills_ledger.py` - Fills ledger shutdown

**Status:** 🚨 Most components lack shutdown methods

**Issues:**
- 🚨 **No shutdown for most components:** 32 start() methods vs 3 shutdown() methods
- 🚨 **No graceful shutdown:** Components may be killed abruptly
- 🚨 **No resource cleanup:** May leave open connections, tasks, files
- 🚨 **No shutdown sequence:** No explicit shutdown order

---

### 3. Startup Sequence (Current)

**Current Behavior:**
```
1. Agent Grid starts
2. WS Bridge starts (independent)
3. Market Catalog starts (independent)
4. Fills Ledger starts (independent)
5. Bankroll Service starts (independent)
6. ... (other components start independently)
```

**Status:** ⚠️ No explicit sequence

**Issues:**
- 🚨 **Race conditions:** Components may start before dependencies are ready
- 🚨 **No validation:** No health checks to confirm components are ready
- 🚨 **No rollback:** If startup fails, no cleanup of partially started components

---

### 4. Shutdown Sequence (Current)

**Current Behavior:**
```
1. Main loop shutdown called
2. Pipeline robustness shutdown called
3. Fills ledger shutdown called
4. ... (other components not shut down)
```

**Status:** 🚨 Incomplete shutdown

**Issues:**
- 🚨 **Lingering tasks:** Most components not shut down
- 🚨 **Resource leaks:** Open connections, tasks, files not cleaned up
- 🚨 **No timeout:** Shutdown can hang indefinitely

---

## Required Fixes

### Fix 1: Add Shutdown Methods to All Components

**Action:** Add async def shutdown() to all components with start() methods

**Template:**
```python
async def shutdown(self, timeout: float = 10.0) -> None:
    """Shutdown component gracefully.
    
    Args:
        timeout: Maximum time to wait for shutdown (seconds)
    """
    logger.info(f"[{self.__class__.__name__}] Shutting down...")
    
    # Cancel background tasks
    if hasattr(self, "_task") and self._task:
        self._task.cancel()
        try:
            await asyncio.wait_for(self._task, timeout=timeout)
        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError:
            logger.warning(f"[{self.__class__.__name__}] Shutdown timeout")
    
    # Close connections
    if hasattr(self, "_client"):
        await self._client.close()
    
    # Flush state
    if hasattr(self, "_save_state"):
        await self._save_state()
    
    logger.info(f"[{self.__class__.__name__}] Shutdown complete")
```

**Implementation:**
1. Add shutdown() to all 32 components
2. Implement graceful shutdown logic
3. Add timeout handling
4. Add resource cleanup

---

### Fix 2: Create Startup Coordinator

**Create:** `merid/lifecycle/startup_coordinator.py`

```python
class StartupCoordinator:
    """Coordinates startup sequence with dependency management."""
    
    def __init__(self):
        self._components: Dict[str, Any] = {}
        self._dependencies: Dict[str, List[str]] = {}
        self._startup_order: List[str] = []
    
    def register_component(
        self,
        name: str,
        component: Any,
        dependencies: Optional[List[str]] = None
    ) -> None:
        """Register a component with its dependencies."""
        self._components[name] = component
        self._dependencies[name] = dependencies or []
    
    def _resolve_startup_order(self) -> List[str]:
        """Resolve startup order using topological sort."""
        # Topological sort based on dependencies
        order = []
        visited = set()
        
        def visit(name: str):
            if name in visited:
                return
            visited.add(name)
            for dep in self._dependencies.get(name, []):
                visit(dep)
            order.append(name)
        
        for name in self._components:
            visit(name)
        
        return order
    
    async def startup(self, timeout: float = 30.0) -> Dict[str, bool]:
        """Startup all components in dependency order."""
        self._startup_order = self._resolve_startup_order()
        results = {}
        
        for name in self._startup_order:
            component = self._components[name]
            logger.info(f"[STARTUP] Starting {name}...")
            
            try:
                await asyncio.wait_for(component.start(), timeout=timeout)
                results[name] = True
                logger.info(f"[STARTUP] {name} started successfully")
            except Exception as e:
                results[name] = False
                logger.error(f"[STARTUP] {name} failed to start: {e}")
                # Rollback: shutdown already started components
                await self.shutdown()
                raise RuntimeError(f"Startup failed at {name}: {e}")
        
        return results
    
    async def shutdown(self, timeout: float = 10.0) -> Dict[str, bool]:
        """Shutdown all components in reverse startup order."""
        results = {}
        
        for name in reversed(self._startup_order):
            component = self._components[name]
            logger.info(f"[SHUTDOWN] Shutting down {name}...")
            
            try:
                if hasattr(component, "shutdown"):
                    await asyncio.wait_for(component.shutdown(timeout=timeout), timeout=timeout)
                results[name] = True
                logger.info(f"[SHUTDOWN] {name} shut down successfully")
            except Exception as e:
                results[name] = False
                logger.error(f"[SHUTDOWN] {name} failed to shutdown: {e}")
        
        return results
```

**Implementation:**
1. Create startup coordinator
2. Register all components with dependencies
3. Implement topological sort for startup order
4. Implement rollback on startup failure
5. Implement reverse-order shutdown

---

### Fix 3: Add Startup Validation

**Add:** Health check after each component startup

```python
async def startup(self, timeout: float = 30.0) -> Dict[str, bool]:
    """Startup all components with health validation."""
    self._startup_order = self._resolve_startup_order()
    results = {}
    
    for name in self._startup_order:
        component = self._components[name]
        logger.info(f"[STARTUP] Starting {name}...")
        
        try:
            await asyncio.wait_for(component.start(), timeout=timeout)
            
            # Health check
            if hasattr(component, "health_check"):
                health = await component.health_check()
                if not health.get("healthy", False):
                    raise RuntimeError(f"{name} health check failed: {health}")
            
            results[name] = True
            logger.info(f"[STARTUP] {name} started successfully")
        except Exception as e:
            results[name] = False
            logger.error(f"[STARTUP] {name} failed to start: {e}")
            await self.shutdown()
            raise RuntimeError(f"Startup failed at {name}: {e}")
    
    return results
```

**Implementation:**
1. Add health_check() method to all components
2. Call health check after startup
3. Fail startup if health check fails
4. Log health status

---

### Fix 4: Add Startup Timeout

**Add:** Timeout for each component startup

```python
async def startup(self, timeout: float = 30.0, component_timeout: float = 10.0) -> Dict[str, bool]:
    """Startup all components with per-component timeout."""
    self._startup_order = self._resolve_startup_order()
    results = {}
    
    for name in self._startup_order:
        component = self._components[name]
        logger.info(f"[STARTUP] Starting {name}...")
        
        try:
            await asyncio.wait_for(component.start(), timeout=component_timeout)
            
            # Health check
            if hasattr(component, "health_check"):
                health = await asyncio.wait_for(
                    component.health_check(),
                    timeout=component_timeout
                )
                if not health.get("healthy", False):
                    raise RuntimeError(f"{name} health check failed: {health}")
            
            results[name] = True
            logger.info(f"[STARTUP] {name} started successfully")
        except asyncio.TimeoutError:
            results[name] = False
            logger.error(f"[STARTUP] {name} startup timeout")
            await self.shutdown()
            raise RuntimeError(f"Startup timeout at {name}")
        except Exception as e:
            results[name] = False
            logger.error(f"[STARTUP] {name} failed to start: {e}")
            await self.shutdown()
            raise RuntimeError(f"Startup failed at {name}: {e}")
    
    return results
```

**Implementation:**
1. Add per-component timeout
2. Add health check timeout
3. Fail on timeout
4. Rollback on timeout

---

### Fix 5: Add Shutdown Timeout

**Add:** Timeout for each component shutdown

```python
async def shutdown(self, timeout: float = 10.0, component_timeout: float = 5.0) -> Dict[str, bool]:
    """Shutdown all components with per-component timeout."""
    results = {}
    
    for name in reversed(self._startup_order):
        component = self._components[name]
        logger.info(f"[SHUTDOWN] Shutting down {name}...")
        
        try:
            if hasattr(component, "shutdown"):
                await asyncio.wait_for(
                    component.shutdown(timeout=component_timeout),
                    timeout=component_timeout
                )
            results[name] = True
            logger.info(f"[SHUTDOWN] {name} shut down successfully")
        except asyncio.TimeoutError:
            results[name] = False
            logger.error(f"[SHUTDOWN] {name} shutdown timeout")
        except Exception as e:
            results[name] = False
            logger.error(f"[SHUTDOWN] {name} failed to shutdown: {e}")
    
    return results
```

**Implementation:**
1. Add per-component shutdown timeout
2. Log timeout failures
3. Continue shutdown on timeout (best effort)
4. Return shutdown results

---

## Audit Checklist

- [ ] Document startup methods (✅ documented)
- [ ] Document shutdown methods (✅ documented)
- [ ] Document startup sequence (✅ documented)
- [ ] Document shutdown sequence (✅ documented)
- [ ] Identify missing shutdown methods (🚨 32 start vs 3 shutdown)
- [ ] Identify no centralized coordinator (🚨 independent startup)
- [ ] Identify no dependency management (🚨 no sequence)
- [ ] Identify no startup validation (🚨 no health checks)
- [ ] Identify no startup timeout (🚨 can hang indefinitely)
- [ ] Plan migration path (5 fixes)
- [ ] Add shutdown methods to all components
- [ ] Create startup coordinator
- [ ] Add startup validation
- [ ] Add startup timeout
- [ ] Add shutdown timeout

---

## Next Steps

1. **Immediate:** Add shutdown methods to all components
2. **Immediate:** Create startup coordinator
3. **Short-term:** Add startup validation
4. **Short-term:** Add startup timeout
5. **Medium-term:** Add shutdown timeout
6. **Medium-term:** Add startup/shutdown monitoring
7. **Long-term:** Add automatic recovery on startup failure

**Priority:** HIGH - Missing shutdown methods can cause resource leaks and lingering tasks

**Risk:** Components without shutdown methods may leave open connections, tasks, and files, causing resource leaks and potential data corruption.

**Note:** Current startup/shutdown is ad-hoc with no coordination. Need to implement a proper lifecycle manager with dependency management, validation, and timeouts.
