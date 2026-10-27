# Instrumentation Summary - Main Loop Hang Investigation

## Completed Tasks

### 1. Agent Metadata Helper ✅
**File**: `merid/agents/agent_metadata.py`

Provides:
- `classification` (prod_15m_core, prod_15m_optional, research_only, remove)
- `age_bucket` (recent <30 days, stale 30-120 days, ancient_experimental >120 days)
- `tag` (e.g., llm_mesh_v1)
- `module_path` and `last_modified` timestamp

### 2. Main Loop Tracing Wrapper ✅
**File**: `merid/agents/loop_tracing.py`

Provides:
- `@trace_agent_step()` decorator for agent step/tick calls
- `@trace_generic_step()` decorator for generic functions
- Logs entry/exit with classification, age_bucket, tag, duration_ms, status

### 3. Reflection Load Instrumentation ✅
**File**: `agents/reflection_layer.py`

Added:
- Timing start at line 293-294
- Instrumentation logs at lines 354-368 (duration_ms, sampled_agents)
- Tick counter data structures at lines 58-63
- Read/write tracking in record_decision(), get_agent_context(), get_agent_stats()
- Periodic tick stats logging every 60s for kalshi_crypto_15m profiles

### 4. AgentMesh Initialization Instrumentation ✅
**File**: `agents/agent_mesh.py`

Added:
- Timing and profile logging in `initialize()` at lines 60-80
- Logs agent count, profile, and duration_ms

### 5. Startup Invariants (WARN-only) ✅
**File**: `merid/startup_validations.py`

Added:
- `validate_agent_registry_for_profile()` - checks agent count <= 10
- `validate_ancient_agents_in_registry()` - scans for ancient_experimental agents
- Both are WARN-only, do not fail startup

### 6. Loop Tracing Applied to All 5 Asset Agents ✅
**Files**: 
- `merid/agents/btc_15m_agent.py`
- `merid/agents/eth_15m_agent.py`
- `merid/agents/sol_15m_agent.py`
- `merid/agents/xrp_15m_agent.py`
- `merid/agents/doge_15m_agent.py`

Added `@trace_agent_step(agent_instance=self)` decorators to main execution methods.

### 7. Agent Structural Asymmetry Analysis ✅
**File**: `docs/audit/KALSHI_15M_AGENT_NORMALIZATION.md`

Found:
- **Btc15mAgent** uses custom spec pattern, unique dependencies (btc_lane, signal_fusion_agent)
- **Eth/Sol/Xrp/Doge** use BaseKalshiAgent with container.resolve() pattern
- Different base classes, different dependency injection patterns

### 8. btc_lane and signal_fusion_agent Investigation ✅
**File**: `docs/audit/BTC_LANE_SIGNAL_FUSION_INVESTIGATION.md`

**Critical Finding**: `get_regime_signal()` method does NOT exist on Crypto15MLane
- Btc15mAgent calls `self.btc_lane.get_regime_signal("BTC_15M_KALSHI")` at line 160
- This method is not defined in Crypto15MLane class
- Would cause AttributeError, potentially hanging the loop

### 9. Fixed Missing get_regime_signal() Call ✅
**File**: `merid/agents/btc_15m_agent.py`

Added defensive exception handling:
```python
try:
    btc_15m_regime_signal = self.btc_lane.get_regime_signal("BTC_15M_KALSHI")
except AttributeError as exc:
    logger.warning("[BTC-LANE-MISSING-METHOD] btc_lane.get_regime_signal() not found: %s - using None", exc)
    btc_15m_regime_signal = None
except Exception as exc:
    logger.warning("[BTC-LANE-ERROR] btc_lane.get_regime_signal() failed: %s - using None", exc)
    btc_15m_regime_signal = None
```

## Remaining Tasks

### High Priority
- Capture one bad run and identify last MAIN-LOOP entering step with metadata
- Enumerate all WARNs from validate_agent_registry_for_profile and validate_ancient_agents_in_registry

### Medium Priority
- Add defensive wrappers with soft timeouts/watchdogs for non-core agents
- Tighten Kalshi-only universe to only 15m crypto markets/agents
- Write prioritized suspect list from ancient_experimental agents appearing in MAIN-LOOP

## Next Steps for User

1. **Run the system** with the new instrumentation enabled
2. **Capture logs** around a stall (last 500-1000 lines)
3. **Identify the last `[MAIN-LOOP] entering step ...` line** and its metadata
4. **Check for `[BTC-LANE-MISSING-METHOD]` warnings** - this should now be logged instead of hanging
5. **Review `[REFLECTION-TRACE]` logs** for extreme load durations
6. **Review `[REFLECTION-TICK]` logs** for which agents are using reflection heavily

## Key Findings

1. **Btc15mAgent has unique dependencies** (btc_lane, signal_fusion_agent) that other agents don't have
2. **Missing method bug**: `get_regime_signal()` doesn't exist on Crypto15MLane - now handled defensively
3. **Structural asymmetry**: Btc15mAgent uses different base class and DI pattern than other 4 agents
4. **Instrumentation ready**: All agents now have tracing decorators to identify which one is causing hangs

## Logging Format

When the system runs, you'll see logs like:

```
[MAIN-LOOP] entering step agent=Btc15mAgent classification=prod_15m_core age=recent tag=...
[MAIN-LOOP] exiting step agent=Btc15mAgent duration_ms=123.45 status=success
[REFLECTION-TRACE] load_complete profile=kalshi_crypto_15m_v2 duration_ms=456.78 reflection_count=4364
[AGENT-MESH] init profile=kalshi_crypto_15m_v2 agents=4 duration_ms=789.01
[BTC-LANE-MISSING-METHOD] btc_lane.get_regime_signal() not found: ... - using None
[REFLECTION-TICK] agent_type=... classification=research_only reads=5 writes=2 in last_window=60 sec
```

This will help pinpoint exactly what's hanging the loop.
