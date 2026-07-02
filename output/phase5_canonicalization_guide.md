# Phase 5: Canonicalization of 15m Pipeline

This guide defines the single source of truth for the 15m crypto trading pipeline and provides enforcement steps.

---

## Canonical 15m Pipeline Map

### Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. STARTUP: web/main_15m_lean.py                                │
│    - Validates MERID_PROFILE=kalshi_crypto_15m_v2              │
│    - Checks environment variables                               │
│    - Initializes components                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. KALSHI CLIENT: KalshiClientV2                                │
│    Module: merid.event_venues.kalshi.client_v2                  │
│    Class: KalshiClientV2                                        │
│    Singleton: (created per component, not global)               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. MARKET CATALOG: KalshiMarketCatalog                          │
│    Module: merid.event_venues.kalshi.market_catalog              │
│    Class: KalshiMarketCatalog                                   │
│    Singleton: get_market_catalog()                              │
│    Method: get_active_markets(timeframe="15m")                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. BANKROLL SERVICE: BankrollServiceV2                          │
│    Module: merid.event_venues.kalshi.bankroll_service_v2        │
│    Class: BankrollServiceV2                                     │
│    Singleton: get_bankroll_service_v2()                         │
│    Method: get_equity_for_risk_calc_sync()                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. SPOT PRICE SERVICE: UnifiedSpotService                       │
│    Module: data.unified_spot_service                             │
│    Class: UnifiedSpotService                                    │
│    Singleton: get_unified_spot_service()                        │
│    Assets: BTC, ETH, SOL, XRP, DOGE (all 5 required)             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. AGENT GRID: LeanAgentGrid15m                                 │
│    Module: merid.prediction.agent_grid_15m                      │
│    Class: LeanAgentGrid15m                                      │
│    Singleton: get_agent_grid_15m()                              │
│    Method: run_cycle(tick, allow_new_entries)                   │
│    Agents: BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 7. CANDIDATE OPTIMIZER: CandidateOptimizer                      │
│    Module: merid.prediction.candidate_optimizer                 │
│    Class: CandidateOptimizer                                    │
│    Singleton: get_candidate_optimizer()                         │
│    Method: generate_candidates()                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 8. ORDER ROUTER: route_order_async()                            │
│    Module: merid.event_venues.kalshi.order_router                │
│    Function: route_order_async(intent: OrderIntent)              │
│    Authorization: Only from authorized modules                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 9. 15m LOOP: Kalshi15mLoop                                      │
│    Module: merid.loop_15m                                       │
│    Class: Kalshi15mLoop                                         │
│    Method: run_forever()                                        │
│    Method: _run_one_cycle(cycle_id)                             │
│    Cadence: 5 seconds                                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 10. SCHEDULER: Crypto15mScheduler                               │
│     Module: merid.event_venues.kalshi.crypto_15m_scheduler       │
│     Class: Crypto15mScheduler                                   │
│     Singleton: get_crypto_15m_scheduler()                       │
│     Method: get_current_window()                                │
└─────────────────────────────────────────────────────────────────┘
```

---

## Canonical Component Specifications

### 1. Startup Entrypoint

**Canonical Implementation**:
- **File**: `web/main_15m_lean.py`
- **Function**: `_run_full_startup_in_lifespan()`
- **Profile Check**: Must validate `MERID_PROFILE=kalshi_crypto_15m_v2`
- **Component Creation Order**:
  1. KalshiClientV2
  2. KalshiMarketCatalog
  3. BankrollServiceV2
  4. UnifiedSpotService
  5. LeanAgentGrid15m
  6. Kalshi15mLoop

**Verification**:
```python
# At startup, log component origins
from merid.origin_tracer import log_object_origin
log_object_origin(kalshi_loop, "kalshi_loop_instance", "startup")
log_object_origin(agent_grid, "agent_grid_instance", "startup")
```

**Alternatives to Remove**:
- `web/main_15m.py` (legacy main)
- Any other startup scripts

---

### 2. Kalshi Client

**Canonical Implementation**:
- **Module**: `merid.event_venues.kalshi.client_v2`
- **Class**: `KalshiClientV2`
- **Location**: `merid/event_venues/kalshi/client_v2.py:69`

**Usage Pattern**:
```python
from merid.event_venues.kalshi.client_v2 import KalshiClientV2
client = KalshiClientV2()
```

**Alternatives to Remove/Block**:
- `KalshiVenueClient` (legacy) - Block in kalshi_crypto_15m_v2
- `EnhancedKalshiClient` - Determine if needed, else block
- `RobustKalshiClient` - Determine if needed, else block

**Verification**:
```python
from merid.origin_tracer import verify_module_source
verify_module_source("merid.event_venues.kalshi.client_v2", "client_v2.py")
```

---

### 3. Market Catalog

**Canonical Implementation**:
- **Module**: `merid.event_venues.kalshi.market_catalog`
- **Class**: `KalshiMarketCatalog`
- **Location**: `merid/event_venues/kalshi/market_catalog.py:430`
- **Singleton**: `get_market_catalog()`

**Usage Pattern**:
```python
from merid.event_venues.kalshi.market_catalog import get_market_catalog
catalog = get_market_catalog()
markets = catalog.get_active_markets(timeframe="15m", max_minutes_to_expiry=30.0)
```

**Helper**:
- **Module**: `merid.event_venues.kalshi.crypto_catalog`
- **Class**: `KalshiCryptoCatalog`
- **Purpose**: Crypto-specific filtering over KalshiMarketCatalog
- **Status**: OK to use (helper, not duplicate)

**Alternatives to Remove**:
- None (KalshiCryptoCatalog is a helper, not a duplicate)

**Verification**:
```python
from merid.origin_tracer import verify_module_source
verify_module_source("merid.event_venues.kalshi.market_catalog", "market_catalog.py")
```

---

### 4. Bankroll Service

**Canonical Implementation**:
- **Module**: `merid.event_venues.kalshi.bankroll_service_v2`
- **Class**: `BankrollServiceV2`
- **Location**: `merid/event_venues/kalshi/bankroll_service_v2.py:116`
- **Singleton**: `get_bankroll_service_v2()`

**Usage Pattern**:
```python
from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service_v2
bankroll = get_bankroll_service_v2()
equity = bankroll.get_equity_for_risk_calc_sync()
```

**Alternatives to Remove/Block**:
- `KalshiBankrollService` (deprecated) - Block in kalshi_crypto_15m_v2
- `get_bankroll_service()` (legacy getter) - Block in kalshi_crypto_15m_v2

**Verification**:
```python
from merid.origin_tracer import verify_module_source
verify_module_source("merid.event_venues.kalshi.bankroll_service_v2", "bankroll_service_v2.py")
```

---

### 5. Spot Price Service

**Canonical Implementation**:
- **Module**: `data.unified_spot_service`
- **Class**: `UnifiedSpotService`
- **Location**: `data/unified_spot_service.py`
- **Singleton**: `get_unified_spot_service()`

**Required Assets**:
- BTC/USD
- ETH/USD
- SOL/USD
- XRP/USD
- DOGE/USD

**Usage Pattern**:
```python
from data.unified_spot_service import get_unified_spot_service
spot_service = get_unified_spot_service()
price = spot_service.get_price("BTC/USD")
```

**Verification**:
```python
# Verify all 5 assets are tracked
assets = spot_service.get_supported_assets()
assert set(assets) == {"BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "DOGE/USD"}
```

---

### 6. Agent Grid

**Canonical Implementation**:
- **Module**: `merid.prediction.agent_grid_15m`
- **Class**: `LeanAgentGrid15m`
- **Location**: `merid/prediction/agent_grid_15m.py:6997`
- **Singleton**: `get_agent_grid_15m()`
- **Critical Method**: `run_cycle(tick: int, allow_new_entries: bool = True)` at line 7123

**Required Agents**:
- BTC_15M
- ETH_15M
- SOL_15M
- XRP_15M
- DOGE_15M

**Usage Pattern**:
```python
from merid.prediction.agent_grid_15m import get_agent_grid_15m
agent_grid = get_agent_grid_15m()
await agent_grid.run_cycle(tick=1, allow_new_entries=True)
```

**Alternatives to Remove/Block**:
- `merid.prediction.agent_grid` (legacy) - Block import in kalshi_crypto_15m_v2
- `AgentGrid` class (legacy) - Block instantiation in kalshi_crypto_15m_v2

**CRITICAL ISSUE TO RESOLVE**:
- There are TWO `run_cycle` methods in `LeanAgentGrid15m` (lines 3781 and 7123)
- **Action**: Determine which is correct and remove the other, or merge them

**Verification**:
```python
from merid.origin_tracer import verify_module_source
verify_module_source("merid.prediction.agent_grid_15m", "agent_grid_15m.py")

# Verify only one run_cycle method
import inspect
run_cycle_methods = [
    m for m in dir(LeanAgentGrid15m) 
    if m == "run_cycle" or "run_cycle" in m
]
assert len(run_cycle_methods) == 1, f"Multiple run_cycle methods found: {run_cycle_methods}"
```

---

### 7. Candidate Optimizer

**Canonical Implementation**:
- **Module**: `merid.prediction.candidate_optimizer`
- **Class**: `CandidateOptimizer`
- **Location**: `merid/prediction/candidate_optimizer.py:95`
- **Singleton**: `get_candidate_optimizer()`

**Usage Pattern**:
```python
from merid.prediction.candidate_optimizer import get_candidate_optimizer
optimizer = get_candidate_optimizer()
candidates = optimizer.generate_candidates(...)
```

**Verification**:
```python
from merid.origin_tracer import verify_module_source
verify_module_source("merid.prediction.candidate_optimizer", "candidate_optimizer.py")
```

---

### 8. Order Router

**Canonical Implementation**:
- **Module**: `merid.event_venues.kalshi.order_router`
- **Function**: `route_order_async(intent: OrderIntent)`
- **Location**: `merid/event_venues/kalshi/order_router.py:4843`

**Authorization**:
- Only callable from: `merid.loop_15m`, `merid.prediction.agent_grid_15m`, `web.api.*`

**Usage Pattern**:
```python
from merid.event_venues.kalshi.order_router import route_order_async
result = await route_order_async(intent)
```

**Alternatives to Remove/Block**:
- `execution/order_router.py` - Determine if needed for other venues, else block for Kalshi

**Verification**:
```python
from merid.origin_tracer import verify_module_source
verify_module_source("merid.event_venues.kalshi.order_router", "order_router.py")
```

---

### 9. 15m Loop

**Canonical Implementation**:
- **Module**: `merid.loop_15m`
- **Class**: `Kalshi15mLoop`
- **Location**: `merid/loop_15m.py:378`
- **Singleton**: `get_kalshi_15m_loop()`

**Critical Methods**:
- `run_forever()` - Main loop entry
- `_run_one_cycle(cycle_id)` - Single cycle execution
- `_on_tick_async()` - Tick handler

**Usage Pattern**:
```python
from merid.loop_15m import Kalshi15mLoop
loop = Kalshi15mLoop(
    agent_grid=agent_grid,
    bankroll_service=bankroll,
    risk_config=risk_config,
    catalog=catalog,
    ws_bridge=ws_bridge
)
await loop.run_forever()
```

**Alternatives to Remove/Block**:
- `merid.loop` (legacy loop) - Block import in kalshi_crypto_15m_v2

**Verification**:
```python
from merid.origin_tracer import verify_module_source
verify_module_source("merid.loop_15m", "loop_15m.py")
```

---

### 10. Scheduler

**Canonical Implementation**:
- **Module**: `merid.event_venues.kalshi.crypto_15m_scheduler`
- **Class**: `Crypto15mScheduler`
- **Location**: `merid/event_venues/kalshi/crypto_15m_scheduler.py:56`
- **Singleton**: `get_crypto_15m_scheduler()`

**Usage Pattern**:
```python
from merid.event_venues.kalshi.crypto_15m_scheduler import get_crypto_15m_scheduler
scheduler = get_crypto_15m_scheduler()
window = scheduler.get_current_window()
```

**Verification**:
```python
from merid.origin_tracer import verify_module_source
verify_module_source("merid.event_venues.kalshi.crypto_15m_scheduler", "crypto_15m_scheduler.py")
```

---

## Enforcement Steps

### Step 1: Add Canonical Module Verification

Create a verification script that checks all canonical modules:

```python
# scripts/verify_canonical_pipeline.py
from merid.origin_tracer import verify_module_source

canonical_modules = [
    ("merid.loop_15m", "loop_15m.py"),
    ("merid.prediction.agent_grid_15m", "agent_grid_15m.py"),
    ("merid.event_venues.kalshi.market_catalog", "market_catalog.py"),
    ("merid.event_venues.kalshi.bankroll_service_v2", "bankroll_service_v2.py"),
    ("merid.event_venues.kalshi.client_v2", "client_v2.py"),
    ("merid.event_venues.kalshi.crypto_15m_scheduler", "crypto_15m_scheduler.py"),
    ("merid.prediction.candidate_optimizer", "candidate_optimizer.py"),
    ("merid.event_venues.kalshi.order_router", "order_router.py"),
    ("data.unified_spot_service", "unified_spot_service.py"),
]

all_valid = True
for module, expected_file in canonical_modules:
    if not verify_module_source(module, expected_file):
        all_valid = False
        print(f"FAIL: {module} not loaded from expected source")

if all_valid:
    print("✓ All canonical modules loaded from correct sources")
else:
    print("✗ Some canonical modules failed verification")
```

### Step 2: Add Runtime Pipeline Verification

Add this check in the 15m loop to verify the pipeline at runtime:

```python
# In Kalshi15mLoop._run_one_cycle()
def verify_pipeline(self):
    """Verify that all components are from canonical sources."""
    from merid.origin_tracer import log_object_origin
    
    log_object_origin(self.agent_grid, "agent_grid_in_loop", "pipeline_verify")
    log_object_origin(self.bankroll_service, "bankroll_in_loop", "pipeline_verify")
    log_object_origin(self.catalog, "catalog_in_loop", "pipeline_verify")
    
    # Verify agent grid is LeanAgentGrid15m
    assert type(self.agent_grid).__name__ == "LeanAgentGrid15m", \
        f"Wrong agent grid type: {type(self.agent_grid).__name__}"
    
    # Verify bankroll is BankrollServiceV2
    assert type(self.bankroll_service).__name__ == "BankrollServiceV2", \
        f"Wrong bankroll type: {type(self.bankroll_service).__name__}"
```

### Step 3: Remove Duplicate Implementations

**Priority 1: Fix dual run_cycle methods**
- Investigate `LeanAgentGrid15m.run_cycle` at lines 3781 and 7123
- Determine which is the correct implementation
- Remove or merge the duplicate

**Priority 2: Remove legacy imports**
- Convert all `from merid.prediction.agent_grid import` to `from merid.prediction.agent_grid_15m import`
- Convert all `from merid.loop import` to `from merid.loop_15m import`
- Convert all `KalshiBankrollService` to `BankrollServiceV2`

**Priority 3: Block legacy modules**
- Add import guards to legacy modules
- Add instantiation guards to deprecated classes

### Step 4: Add Pipeline Health Check

Create an endpoint that verifies the pipeline:

```python
# In web/api/health.py
@router.get("/api/health/pipeline")
async def pipeline_health():
    """Verify the 15m trading pipeline is using canonical components."""
    from merid.loop_15m import get_kalshi_15m_loop
    from merid.prediction.agent_grid_15m import get_agent_grid_15m
    from merid.origin_tracer import verify_module_source
    
    checks = {
        "loop_15m": verify_module_source("merid.loop_15m", "loop_15m.py"),
        "agent_grid_15m": verify_module_source("merid.prediction.agent_grid_15m", "agent_grid_15m.py"),
        "market_catalog": verify_module_source("merid.event_venues.kalshi.market_catalog", "market_catalog.py"),
        "bankroll_v2": verify_module_source("merid.event_venues.kalshi.bankroll_service_v2", "bankroll_service_v2.py"),
    }
    
    all_valid = all(checks.values())
    
    return {
        "status": "healthy" if all_valid else "degraded",
        "checks": checks,
    }
```

---

## Pre-Shipment Checklist

Before calling the code "production-grade and shippable", verify:

- [ ] No legacy modules imported under kalshi_crypto_15m_v2 profile
- [ ] All "double-named" classes (like multiple `*AgentGrid15m`) either removed or never instantiated in v2
- [ ] Origin logs show exactly one module per role
- [ ] `LeanAgentGrid15m` has only ONE `run_cycle` method
- [ ] All imports from `merid.prediction.agent_grid` converted to `agent_grid_15m`
- [ ] All imports from `merid.loop` converted to `loop_15m`
- [ ] All `KalshiBankrollService` references converted to `BankrollServiceV2`
- [ ] All 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) are present in agent grid
- [ ] All 5 crypto assets are tracked in spot service
- [ ] All 5 crypto assets are discovered in market catalog
- [ ] Environment verification passes (no site-packages shadowing)
- [ ] Profile validation passes (MERID_PROFILE=kalshi_crypto_15m_v2)
- [ ] Legacy module guard passes (no legacy modules loaded)
- [ ] Pipeline health check passes (all canonical modules verified)
- [ ] Origin tracing shows correct module sources for all components
- [ ] No warnings or errors in startup logs related to module loading

---

## Summary

The canonical 15m pipeline is:

1. **Startup**: `web/main_15m_lean.py` → validates profile
2. **Client**: `KalshiClientV2` → API communication
3. **Catalog**: `KalshiMarketCatalog` → market discovery
4. **Bankroll**: `BankrollServiceV2` → risk capital
5. **Spot**: `UnifiedSpotService` → price feeds (5 assets)
6. **Grid**: `LeanAgentGrid15m` → agents (5 agents)
7. **Optimizer**: `CandidateOptimizer` → order selection
8. **Router**: `route_order_async` → order execution
9. **Loop**: `Kalshi15mLoop` → orchestration
10. **Scheduler**: `Crypto15mScheduler` → window management

All other implementations should be removed, blocked, or clearly marked as legacy.
