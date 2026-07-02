# Phase 2: Runtime Origin Tracing - Instrumentation Guide

This guide shows exactly where to add origin logging to detect which implementations are actually used at runtime.

---

## Step 1: Add Origin Tracer Import

Add this import at the top of each file you instrument:

```python
from merid.origin_tracer import log_object_origin, log_method_entry, log_call_stack, verify_module_source, log_sys_path, log_environment
```

---

## Step 2: Instrument Startup Environment Logging

**File**: `web/main_15m_lean.py`

**Location**: In `_run_full_startup_in_lifespan()`, immediately after the profile check (around line 1684)

**Add this code**:

```python
# Phase 2: Runtime origin tracing - log environment at startup
from merid.origin_tracer import log_sys_path, log_environment, verify_module_source

log_environment()
log_sys_path()

# Verify critical modules are loaded from expected sources
verify_module_source("merid.prediction.agent_grid_15m", "agent_grid_15m.py")
verify_module_source("merid.loop_15m", "loop_15m.py")
verify_module_source("merid.event_venues.kalshi.market_catalog", "market_catalog.py")
verify_module_source("merid.event_venues.kalshi.bankroll_service_v2", "bankroll_service_v2.py")
```

---

## Step 3: Instrument Agent Grid Creation

**File**: `web/main_15m_lean.py`

**Location**: Immediately after `agent_grid = build_15m_agent_grid(...)` (around line 2428)

**Add this code**:

```python
# Phase 2: Trace agent grid origin
from merid.origin_tracer import log_object_origin

log_object_origin(agent_grid, "agent_grid_instance", context="main_15m_lean.py startup")
log_object_origin(type(agent_grid), "agent_grid_class", context="main_15m_lean.py startup")
```

---

## Step 4: Instrument Kalshi15mLoop Creation

**File**: `web/main_15m_lean.py`

**Location**: Immediately after `kalshi_loop = Kalshi15mLoop(...)` (around line 1337)

**Add this code**:

```python
# Phase 2: Trace Kalshi15mLoop origin
from merid.origin_tracer import log_object_origin

log_object_origin(kalshi_loop, "kalshi_loop_instance", context="main_15m_lean.py startup")
log_object_origin(type(kalshi_loop), "kalshi_loop_class", context="main_15m_lean.py startup")
log_object_origin(agent_grid, "agent_grid_passed_to_loop", context="Kalshi15mLoop.__init__")
```

---

## Step 5: Instrument Catalog Creation

**File**: `web/main_15m_lean.py`

**Location**: Immediately after `catalog = KalshiMarketCatalog(client=kalshi_client)` (around line 1928)

**Add this code**:

```python
# Phase 2: Trace catalog origin
from merid.origin_tracer import log_object_origin

log_object_origin(catalog, "catalog_instance", context="main_15m_lean.py startup")
log_object_origin(type(catalog), "catalog_class", context="main_15m_lean.py startup")
```

---

## Step 6: Instrument Bankroll Service Creation

**File**: `web/main_15m_lean.py`

**Location**: Immediately after bankroll service creation (find where `BankrollServiceV2` is instantiated)

**Add this code**:

```python
# Phase 2: Trace bankroll service origin
from merid.origin_tracer import log_object_origin

log_object_origin(bankroll, "bankroll_service_instance", context="main_15m_lean.py startup")
log_object_origin(type(bankroll), "bankroll_service_class", context="main_15m_lean.py startup")
```

---

## Step 7: Instrument LeanAgentGrid15m.run_cycle Entry

**File**: `merid/prediction/agent_grid_15m.py`

**Location**: At the very beginning of `run_cycle` method (line 7123), immediately after the docstring

**Add this code** (replace or augment your existing diagnostics):

```python
async def run_cycle(self, tick: int, allow_new_entries: bool = True) -> None:
    """
    Run a single cycle across all agents with priority queue scheduling.
    ...
    """
    # Phase 2: Runtime origin tracing - log method entry
    from merid.origin_tracer import log_method_entry, log_object_origin, log_call_stack
    
    log_method_entry(self, "run_cycle", label="LeanAgentGrid15m")
    log_object_origin(self, "agent_grid_instance_in_run_cycle", context=f"tick={tick}")
    log_call_stack(label="run_cycle_caller")
    
    # Your existing diagnostics...
    import sys
    sys.stderr.write(f"[LEAN-GRID-RUN-CYCLE-ENTRY] tick={tick} id={id(self)}\n")
    sys.stderr.flush()
    # ... rest of your existing code
```

---

## Step 8: Instrument Kalshi15mLoop._run_one_cycle

**File**: `merid/loop_15m.py`

**Location**: At the beginning of `_run_one_cycle` method (find the method definition)

**Add this code**:

```python
def _run_one_cycle(self, cycle_id: int) -> None:
    """Run a single 15m trading cycle."""
    # Phase 2: Runtime origin tracing
    from merid.origin_tracer import log_method_entry, log_object_origin
    
    log_method_entry(self, "_run_one_cycle", label="Kalshi15mLoop")
    log_object_origin(self.agent_grid, "agent_grid_in_loop", context=f"cycle_id={cycle_id}")
    
    # Existing code...
```

---

## Step 9: Instrument the Call to agent_grid.run_cycle

**File**: `merid/loop_15m.py`

**Location**: Find where `self.agent_grid.run_cycle()` is called and add logging immediately before it

**Add this code**:

```python
# Phase 2: Trace the actual call to run_cycle
from merid.origin_tracer import log_method_entry, log_object_origin

log_object_origin(self.agent_grid, "agent_grid_before_run_cycle_call", context=f"cycle_id={cycle_id}")
log_method_entry(self.agent_grid, "run_cycle", label="about_to_call_from_loop")

# Then the actual call
await self.agent_grid.run_cycle(tick=self._tick, allow_new_entries=allow_new_entries)

# Log after call
log_object_origin(self.agent_grid, "agent_grid_after_run_cycle_call", context=f"cycle_id={cycle_id}")
```

---

## Step 10: Instrument Candidate Optimizer

**File**: `merid/prediction/agent_grid_15m.py`

**Location**: Find where candidate optimizer is used (search for `get_candidate_optimizer` or `CandidateOptimizer`)

**Add this code**:

```python
# Phase 2: Trace candidate optimizer
from merid.origin_tracer import log_object_origin

optimizer = get_candidate_optimizer()
log_object_origin(optimizer, "candidate_optimizer_instance", context="agent_grid")
log_object_origin(type(optimizer), "candidate_optimizer_class", context="agent_grid")
```

---

## Step 11: Instrument Kalshi Client

**File**: `merid/event_venues/kalshi/client_v2.py`

**Location**: In `KalshiClientV2.__init__` (around line 69)

**Add this code**:

```python
def __init__(self, max_riskable_frac: float = 0.02):
    # Phase 2: Trace client origin
    from merid.origin_tracer import log_object_origin
    
    log_object_origin(self, "kalshi_client_v2_instance", context="KalshiClientV2.__init__")
    
    # Existing initialization code...
```

---

## Step 12: Instrument Market Catalog get_active_markets

**File**: `merid/event_venues/kalshi/market_catalog.py`

**Location**: At the beginning of `get_active_markets` method (around line 2149)

**Add this code**:

```python
def get_active_markets(self, timeframe: str = "15m", max_minutes_to_expiry: float = 30.0) -> List[CatalogMarket]:
    """Get active markets for the given timeframe."""
    # Phase 2: Trace catalog method
    from merid.origin_tracer import log_method_entry, log_object_origin
    
    log_method_entry(self, "get_active_markets", label="KalshiMarketCatalog")
    log_object_origin(self, "catalog_instance_in_get_active_markets", context=f"timeframe={timeframe}")
    
    # Existing code...
```

---

## How to Interpret the Logs

After adding this instrumentation and restarting the system, check:

1. **output/origin_trace.log** - Contains all origin traces
2. **stdout/stderr** - Also contains the traces (flushed immediately)

### What to Look For

**Correct behavior**:
```
[ORIGIN-TRACE] ... | label=agent_grid_instance | class=LeanAgentGrid15m | module=merid.prediction.agent_grid_15m | file=.../agent_grid_15m.py
[METHOD-ENTRY] ... | method=run_cycle | class=LeanAgentGrid15m | module=merid.prediction.agent_grid_15m | file=.../agent_grid_15m.py
```

**Wrong behavior (multiple versions loaded)**:
```
[ORIGIN-TRACE] ... | label=agent_grid_instance | class=LeanAgentGrid15m | module=merid.prediction.agent_grid_15m | file=.../agent_grid_15m.py
[METHOD-ENTRY] ... | method=run_cycle | class=LeanAgentGrid15m | module=merid.prediction.agent_grid | file=.../agent_grid.py  # WRONG MODULE!
```

**Module verification failures**:
```
[VERIFY-MODULE] module=merid.prediction.agent_grid_15m | actual_file=C:/some/site-packages/merid/prediction/agent_grid_15m.py | expected_contains=agent_grid_15m.py | match=False
```

This would indicate the module is loaded from site-packages instead of your local source.

---

## Expected Output Example

When the system starts, you should see logs like:

```
[ENVIRONMENT] 2026-06-13T... | MERID_PROFILE=kalshi_crypto_15m_v2 | KALSHI_ENV=...
[SYS-PATH] 2026-06-13T... | [0] C:\Dev\MERID | [1] ...
[VERIFY-MODULE] module=merid.prediction.agent_grid_15m | actual_file=c:\Dev\MERID\merid\prediction\agent_grid_15m.py | expected_contains=agent_grid_15m.py | match=True
[ORIGIN-TRACE] ... | label=agent_grid_instance | class=LeanAgentGrid15m | module=merid.prediction.agent_grid_15m | file=c:\Dev\MERID\merid\prediction\agent_grid_15m.py
[ORIGIN-TRACE] ... | label=kalshi_loop_instance | class=Kalshi15mLoop | module=merid.loop_15m | file=c:\Dev\MERID\merid\loop_15m.py
[METHOD-ENTRY] ... | method=run_cycle | class=LeanAgentGrid15m | module=merid.prediction.agent_grid_15m | file=c:\Dev\MERID\merid\prediction\agent_grid_15m.py
```

---

## Next Steps After Instrumentation

1. **Restart the system** with the instrumentation in place
2. **Let it run for a few cycles** (wait for the 15m loop to execute)
3. **Check output/origin_trace.log** for the traces
4. **Look for**:
   - Any modules loaded from unexpected paths (site-packages vs local)
   - Multiple different module paths for the same class name
   - Method entries that don't match the class you expect
5. **Report back** with the log output and we'll analyze it together

---

## Quick Test Command

After adding instrumentation, test with:

```powershell
CD C:\Dev\MERID
.\start_15m.ps1 -Port 8011 -Profile kalshi_crypto_15m_v2
```

Then check:
```powershell
Get-Content C:\Dev\MERID\output\origin_trace.log -Tail 50
```
