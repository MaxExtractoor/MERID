# Kalshi 15m Crypto Agent Upstream-Downstream Audit

**Date**: 2026-05-15
**Profile**: kalshi_crypto_15m_v2
**Agents**: BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M

## Executive Summary

**Critical Finding**: Agent grid only imports 4 of 5 agents - Btc15mAgent is missing from agent_grid.py regime agents list.

**Overall Assessment**:
- Upstream wiring is partially broken (missing BTC agent)
- No profile guards on agent instantiation
- Dead code in kalshi_crypto/__init__.py (CRYPTO_AGENTS dict not used)
- Downstream dependencies include experimental components (signal_fusion, grid_context)
- Main loop has no profile-specific filtering
- Legacy BTC15MLane still referenced in code despite migration to Crypto15MLane

---

## 1. Upstream Audit: Imports and Instantiations

### 1.1 Agent Grid (merid/prediction/agent_grid.py)

**Location**: Lines 184-194

```python
from merid.agents.eth_15m_agent import Eth15mAgent
from merid.agents.sol_15m_agent import Sol15mAgent
from merid.agents.xrp_15m_agent import Xrp15mAgent
from merid.agents.doge_15m_agent import Doge15mAgent
# Btc1hAgent archived 2026-01-15 - focus on 15m timeframe only
self._regime_agents = [
    Eth15mAgent(_market_reg, _rti_monitor, self._portfolio_risk),
    Sol15mAgent(_market_reg, _rti_monitor, self._portfolio_risk),
    Xrp15mAgent(_market_reg, _rti_monitor, self._portfolio_risk),
    Doge15mAgent(_market_reg, _rti_monitor, self._portfolio_risk),
]
```

**Issues**:
- ❌ **CRITICAL**: Btc15mAgent NOT imported or instantiated
- ❌ **No profile guard**: Imports happen unconditionally in __init__
- ❌ **No wrappers**: Direct instantiation without mesh/reflection layers
- ℹ️ Comment mentions "Btc1hAgent archived" but doesn't explain missing Btc15mAgent

**Classification**: **KEEP for 15m** (after adding Btc15mAgent import)
**Action Required**: Add Btc15mAgent import and instantiation

---

### 1.2 Kalshi Crypto Module (merid/agents/kalshi_crypto/__init__.py)

**Location**: Lines 30-67

```python
CRYPTO_AGENTS: dict = {}

try:
    from merid.agents.btc_15m_agent import Btc15mAgent
    CRYPTO_AGENTS["btc_15m"] = Btc15mAgent
except Exception as _e:
    _logger.debug("kalshi_crypto: Btc15mAgent unavailable: %s", _e)
    Btc15mAgent = None
# ... similar for ETH, SOL, XRP, DOGE
```

**Issues**:
- ❌ **DEAD CODE**: CRYPTO_AGENTS dict is never imported anywhere in production code
- ❌ **No profile guard**: Imports happen unconditionally
- ℹ️ Defensive exception handling is good pattern

**Classification**: **REMOVE** (dead code)
**Action Required**: Remove entire file or mark as deprecated

---

### 1.3 Main Loop Startup (web/main.py)

**Location**: Lines 2629-2631

```python
from merid.prediction.agent_grid import get_agent_grid
agent_grid = get_agent_grid()
await agent_grid.start()
```

**Issues**:
- ❌ **No profile guard**: Agent grid starts unconditionally
- ❌ **No profile check**: Doesn't verify MERID_PROFILE=kalshi_crypto_15m_v2 before starting
- ℹ️ Grid startup happens in deferred startup block

**Classification**: **KEEP for 15m** (needs profile guard)
**Action Required**: Add profile guard: `if os.getenv("MERID_PROFILE") == "kalshi_crypto_15m_v2"`

---

### 1.4 Lane Startup (web/startup_agents.py)

**Location**: Lines 171-199

```python
# Start Crypto15MLane — BTC 15m primary lane via registry (MIGRATION 2026-05-15)
# Get BTC_15M lane from registry (canonical Crypto15MLane)
```

**Issues**:
- ✅ **Correct**: Uses Crypto15MLane via registry (canonical)
- ✅ **Migration complete**: No references to legacy BTC15MLane
- ❌ **No profile guard**: Lane starts unconditionally

**Classification**: **KEEP for 15m** (needs profile guard)
**Action Required**: Add profile guard check

---

## 2. Downstream Audit: Call Graphs

### 2.1 Btc15mAgent (merid/agents/btc_15m_agent.py)

**Method**: `run_cycle()` → `_build_inputs()`

**Call Graph**:
```
run_cycle()
  → _build_inputs()
    → rti_stream.get_current_metrics("BTC")
    → portfolio_risk_agent.get_exposure_pct(venue="kalshi", category="crypto", product="btc_15m")
    → portfolio_risk_agent.is_crypto_vol_elevated("BTC")
    → kalshi_market_registry.get_active_btc_15m()
    → btc_lane.get_regime_signal("BTC_15M_KALSHI") ⚠️ MISSING METHOD
    → signal_fusion_agent.get_history(limit=1) ⚠️ EXPERIMENTAL
  → signal_generator.generate_signal(inputs)
  → risk_rules.pre_trade_check(signal, inputs)
  → _create_opinion(signal, risk_check)
```

**Issues**:
- ⚠️ **btc_lane.get_regime_signal()**: Method doesn't exist on Crypto15MLane (defensively handled with try/except)
- ⚠️ **signal_fusion_agent**: Experimental microstructure signals (orderflow_bias, onchain_velocity)
- ℹ️ All other dependencies are core Kalshi infrastructure (RTI, portfolio risk, market registry)

**Classification**: 
- btc_lane: **KEEP for 15m** (needs method implementation or removal)
- signal_fusion_agent: **RESEARCH_ONLY** (not used by other 4 agents)

**Action Required**: 
1. Implement get_regime_signal() on Crypto15MLane OR remove call
2. Remove signal_fusion_agent dependency (BTC-only experimental feature)

---

### 2.2 Eth15mAgent (merid/agents/eth_15m_agent.py)

**Method**: `get_opinion()`

**Call Graph**:
```
get_opinion()
  → _build_inputs()
    → rti_stream.get_current_metrics("ETH")
    → portfolio_risk_agent.get_exposure_pct(venue="kalshi", category="crypto", product=product)
    → portfolio_risk_agent.is_crypto_vol_elevated("ETH")
    → kalshi_market_registry.get_active_eth_15m()
  → get_grid_context().is_winner(market.ticker) ⚠️ ARBITER CHECK
  → should_trade_eth_15m(inputs, params)
  → portfolio_risk_agent.get_kelly_size_pct()
```

**Issues**:
- ⚠️ **get_grid_context()**: GridContext singleton for arbiter winner list (used by all 4 non-BTC agents)
- ℹ️ No signal_fusion_agent dependency (cleaner than BTC)
- ℹ️ No btc_lane dependency (uses market_registry directly)

**Classification**: 
- grid_context: **KEEP for 15m** (core arbiter alignment mechanism)

**Action Required**: None (this is intentional design for winner alignment)

---

### 2.3 Sol15mAgent, Xrp15mAgent, Doge15mAgent

**Pattern**: Same as Eth15mAgent (use grid_context for arbiter winner check)

**Call Graph**: Identical to Eth15mAgent (symbol-specific)

**Issues**: Same as Eth15mAgent

**Classification**: **KEEP for 15m**

---

## 3. Main Loop Integration

### 3.1 Loop Scheduling (merid/loop.py)

**Location**: Lines 1126-1169

```python
from merid.prediction.agent_grid import get_agent_grid
grid = get_agent_grid()
# Check if grid is running
if not grid.is_running:
    logger.debug("Kalshi agent grid not running, skipping agent cycle")
    return
for agent in grid.agents:
    # ... signal scanning
```

**Issues**:
- ❌ **No profile guard**: Loops over all agents unconditionally
- ❌ **No agent filtering**: Doesn't filter to only 15m crypto agents
- ❌ **No classification check**: Doesn't verify agents are prod_15m_core
- ℹ️ Has 2.0s timeout on signal scan to prevent executor saturation

**Classification**: **KEEP for 15m** (needs filtering)
**Action Required**: Add profile guard + agent classification filter

---

### 3.2 Agent Mesh (web/main.py)

**Location**: Lines 4063-4087

```python
# Agent mesh
if os.getenv("MERID_VALIDATION_MODE") != "1":
    from agents.agent_mesh import agent_mesh
    _init_task = asyncio.create_task(agent_mesh.initialize(), name="agent-mesh-init")
    task = asyncio.create_task(agent_mesh.start(), name="agent-mesh-start")
```

**Issues**:
- ⚠️ **Agent mesh starts unconditionally** (no profile guard)
- ⚠️ **Agent mesh wraps "all agents"** - may include non-15m agents
- ℹ️ Skipped in validation mode

**Classification**: **RESEARCH_ONLY** (not needed for lean 15m)
**Action Required**: Add profile guard to disable for kalshi_crypto_15m_v2

---

### 3.3 Reflection Layer (web/main.py)

**Location**: Lines 2950-2957

```python
from agents.reflection_layer import reflection_layer
reflection_count = len(getattr(reflection_layer, 'reflections', ...))
agent_count = len(getattr(reflection_layer, 'agent_stats', ...))
```

**Issues**:
- ⚠️ **Reflection layer starts unconditionally**
- ⚠️ **May iterate over all agents** (including non-15m)
- ℹ️ Used for LLM-powered reflection

**Classification**: **RESEARCH_ONLY** (not needed for lean 15m)
**Action Required**: Add profile guard to disable for kalshi_crypto_15m_v2

---

## 4. Series Mappings Audit

### 4.1 AGENT_SERIES_MAP (merid/event_venues/kalshi/market_selector.py)

**Status**: ✅ Validated (35 mappings all correct per memory)

**Consumers**:
- KalshiTradingAgent._resolve_markets() (Path 1: series_tickers)
- AgentGrid.start() → enable_kalshi_agent()

**Issues**:
- ℹ️ No profile guard on series resolution
- ℹ️ All 35 agents can resolve series regardless of profile

**Classification**: **KEEP for 15m** (needs profile guard)
**Action Required**: Add profile guard to only resolve series for 15m crypto agents

---

### 4.2 Lane Consumption

**Current State**:
- Crypto15MLane: Used by all 5 assets (BTC/ETH/SOL/XRP/DOGE)
- BTC15MLane: Legacy (marked as ANCIENT_EXPERIMENTAL, but still referenced)

**Issues**:
- ⚠️ **BTC15MLane still in code**: merid/lanes/btc15m_lane.py exists
- ⚠️ **Migration incomplete**: Some comments still reference BTC15MLane
- ✅ **Runtime uses Crypto15MLane**: web/api/kalshi_api.py migrated to Crypto15MLane

**Classification**: 
- Crypto15MLane: **KEEP for 15m**
- BTC15MLane: **REMOVE** (dead code)

**Action Required**: Delete merid/lanes/btc15m_lane.py

---

## 5. Legacy and Experimental Components

### 5.1 SignalFusionAgent

**Location**: agents/signal_fusion_agent.py

**Usage**: Only by Btc15mAgent

**Issues**:
- ⚠️ **Experimental**: Microstructure signals (orderflow, onchain)
- ⚠️ **BTC-only**: Other 4 agents don't use it
- ⚠️ **Heavy I/O**: get_history() may be slow

**Classification**: **RESEARCH_ONLY**
**Action Required**: Remove from Btc15mAgent (or profile-guard)

---

### 5.2 GridContext (Arbiter Winner List)

**Location**: merid/prediction/grid_context.py

**Usage**: Eth15mAgent, Sol15mAgent, Xrp15mAgent, Doge15mAgent

**Issues**:
- ℹ️ Core arbiter alignment mechanism
- ℹ️ Used by 4 of 5 agents (not BTC)
- ℹ️ No profile guard

**Classification**: **KEEP for 15m** (core design)
**Action Required**: None (intentional)

---

### 5.3 Agent Mesh

**Location**: agents/agent_mesh.py

**Usage**: Wraps "all agents" generically

**Issues**:
- ⚠️ **Generic wrapper**: No profile awareness
- ⚠️ **May include non-15m agents**
- ⚠️ **Starts unconditionally**

**Classification**: **RESEARCH_ONLY**
**Action Required**: Profile-guard to disable for kalshi_crypto_15m_v2

---

### 5.4 Reflection Layer

**Location**: agents/reflection_layer.py

**Usage**: LLM-powered reflection over all agents

**Issues**:
- ⚠️ **Generic iteration**: May include non-15m agents
- ⚠️ **Heavy compute**: LLM calls
- ⚠️ **Starts unconditionally**

**Classification**: **RESEARCH_ONLY**
**Action Required**: Profile-guard to disable for kalshi_crypto_15m_v2

---

## 6. Hang Source Candidates

### 6.1 Blocking Calls in Downstream Dependencies

**High Priority**:
1. **signal_fusion_agent.get_history()** (BTC only)
   - Location: btc_15m_agent.py line 177
   - Risk: Heavy I/O, may block event loop
   - Mitigation: Already defensively handled with try/except

2. **btc_lane.get_regime_signal()** (BTC only)
   - Location: btc_15m_agent.py line 163
   - Risk: Method doesn't exist (AttributeError caught)
   - Mitigation: Already defensively handled with try/except

3. **grid_context.is_winner()** (ETH/SOL/XRP/DOGE)
   - Location: All 4 agents
   - Risk: Singleton access, may block if locked
   - Mitigation: Has threading lock in GridContext

**Medium Priority**:
4. **portfolio_risk_agent.get_exposure_pct()**
   - Location: All 5 agents
   - Risk: Database query, may be slow
   - Mitigation: Core infrastructure, expected to be fast

5. **kalshi_market_registry.get_active_*_15m()**
   - Location: All 5 agents
   - Risk: Market lookup, may be slow
   - Mitigation: In-memory cache expected

---

### 6.2 Legacy Components Still Running

**Potential Hang Sources**:
1. **Agent mesh** (starts unconditionally)
   - May iterate over non-15m agents
   - May have slow initialization
   - No profile guard

2. **Reflection layer** (starts unconditionally)
   - LLM calls may be slow
   - May iterate over non-15m agents
   - No profile guard

3. **KalshiContinuousTrader** (if enabled)
   - Has profile block for kalshi_crypto_15m_v2 (hard assertion)
   - But may be enabled for other profiles
   - Legacy component

---

## 7. Recommendations

### 7.1 Critical Fixes (P0)

1. **Add Btc15mAgent to agent_grid.py regime agents**
   ```python
   from merid.agents.btc_15m_agent import Btc15mAgent
   self._regime_agents = [
       Btc15mAgent(_market_reg, _rti_monitor, self._portfolio_risk),
       Eth15mAgent(_market_reg, _rti_monitor, self._portfolio_risk),
       Sol15mAgent(_market_reg, _rti_monitor, self._portfolio_risk),
       Xrp15mAgent(_market_reg, _rti_monitor, self._portfolio_risk),
       Doge15mAgent(_market_reg, _rti_monitor, self._portfolio_risk),
   ]
   ```

2. **Add profile guard to agent grid startup in main.py**
   ```python
   _profile = os.getenv("MERID_PROFILE", "full").lower().strip()
   if _profile == "kalshi_crypto_15m_v2":
       from merid.prediction.agent_grid import get_agent_grid
       agent_grid = get_agent_grid()
       await agent_grid.start()
   ```

3. **Add profile guard to main loop agent iteration**
   ```python
   _profile = os.getenv("MERID_PROFILE", "full").lower().strip()
   if _profile == "kalshi_crypto_15m_v2":
       for agent in grid.agents:
           # Filter to only 15m crypto agents
           if agent.config.category == "crypto" and agent.config.timeframe == "15m":
               # ... process agent
   ```

---

### 7.2 High Priority (P1)

4. **Remove signal_fusion_agent from Btc15mAgent**
   - Experimental feature not used by other 4 agents
   - Potential hang source (heavy I/O)
   - Or add profile guard to disable for kalshi_crypto_15m_v2

5. **Implement get_regime_signal() on Crypto15MLane OR remove call**
   - Currently defensively handled with try/except
   - Method doesn't exist on Crypto15MLane
   - Decide: implement or remove

6. **Add profile guard to agent mesh startup**
   ```python
   _profile = os.getenv("MERID_PROFILE", "full").lower().strip()
   if _profile != "kalshi_crypto_15m_v2" and os.getenv("MERID_VALIDATION_MODE") != "1":
       from agents.agent_mesh import agent_mesh
       # ... start agent mesh
   ```

7. **Add profile guard to reflection layer startup**
   ```python
   _profile = os.getenv("MERID_PROFILE", "full").lower().strip()
   if _profile != "kalshi_crypto_15m_v2":
       from agents.reflection_layer import reflection_layer
       # ... start reflection layer
   ```

---

### 7.3 Medium Priority (P2)

8. **Remove dead code: merid/agents/kalshi_crypto/__init__.py**
   - CRYPTO_AGENTS dict never used
   - Imports never used in production

9. **Delete legacy BTC15MLane**
   - merid/lanes/btc15m_lane.py
   - Migration to Crypto15MLane complete
   - Dead code

10. **Add profile guard to series resolution**
    - KalshiTradingAgent._resolve_markets()
    - AgentGrid.enable_kalshi_agent()
    - Only resolve for 15m crypto agents under kalshi_crypto_15m_v2

---

### 7.4 Low Priority (P3)

11. **Add agent classification filter to main loop**
    - Only process agents with classification=prod_15m_core
    - Use agent_metadata.py classification

12. **Add startup validation for agent surface**
    - Assert only 5 agents registered under kalshi_crypto_15m_v2
    - Check in startup_validations.py

---

## 8. Summary Table

| Component | Status | Classification | Action | Priority |
|-----------|--------|----------------|--------|----------|
| Btc15mAgent import (agent_grid.py) | ❌ Missing | KEEP for 15m | Add import/instantiation | P0 |
| Agent grid startup (main.py) | ❌ No profile guard | KEEP for 15m | Add profile guard | P0 |
| Main loop agent iteration | ❌ No profile guard | KEEP for 15m | Add profile guard | P0 |
| signal_fusion_agent | ⚠️ Experimental | RESEARCH_ONLY | Remove from BTC or profile-guard | P1 |
| get_regime_signal() | ⚠️ Missing method | KEEP for 15m | Implement or remove | P1 |
| Agent mesh | ⚠️ Unconditional | RESEARCH_ONLY | Profile-guard to disable | P1 |
| Reflection layer | ⚠️ Unconditional | RESEARCH_ONLY | Profile-guard to disable | P1 |
| CRYPTO_AGENTS dict | ❌ Dead code | REMOVE | Delete file | P2 |
| BTC15MLane | ⚠️ Legacy | REMOVE | Delete file | P2 |
| GridContext | ✅ Core | KEEP for 15m | None | - |
| Crypto15MLane | ✅ Canonical | KEEP for 15m | None | - |

---

## 9. Next Steps

1. **Immediate**: Fix P0 issues (missing BTC agent, profile guards)
2. **Short-term**: Fix P1 issues (experimental components, profile guards)
3. **Medium-term**: Clean up P2 dead code
4. **Long-term**: Add P3 validation and classification filters

**Verification**: After fixes, run main loop with tracing enabled and capture MAIN-LOOP logs to verify only 5 agents + KalshiTradingAgent + PortfolioRiskAgent appear as classification=prod_15m_core.
