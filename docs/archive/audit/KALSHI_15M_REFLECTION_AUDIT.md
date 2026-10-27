# Kalshi 15m Reflection Subsystem Audit

## Reflection System Overview

The reflection subsystem has two implementations:
- **v1**: `agents/reflection_layer.py` - Legacy reflection layer
- **v2**: `agents/reflection/integration.py` - New unified reflection system

### Reflection Data

- **Storage**: `logs/agent_reflections_v2.json` (v2) or `logs/agent_reflections.json` (v1)
- **Current state**: 4364 reflections for 664 unique agents
- **Log source**: `agents/reflection_layer.py:344`

### Agent IDs in Reflection Data

The reflection file contains two categories of agent IDs:

#### 1. Legacy Mesh Agents (5 agents)
- `strategy-agent-01`
- `synthesizer-01`
- `analyst-llama-01`
- `skeptic-01`
- `risk-agent-01`

These are from the AgentMesh system (`agents/agent_mesh.py`), which runs 4 streaming LLM agents (MarketAnalystAgent, RiskAgent, SkepticAgent, StrategyAgent). These agents are **research_only** and not used in Kalshi 15m production.

#### 2. Historical KalshiTradingAgent Instances (659 agents)
Pattern: `kalshi-{asset}_{timeframe}_{hash}`

Examples:
- `kalshi-btc_15m_11bdd75e`
- `kalshi-eth_15m_413471ea`
- `kalshi-sol_15m_177eecc9`
- `kalshi-xrp_15m_0daba8de`
- `kalshi-doge_15m_d60eeea6`
- `kalshi-btc_hourly_55fbbed9`
- `kalshi-eth_hourly_90546b36`
- `kalshi-sol_hourly_...`
- `kalshi-xrp_hourly_...`
- `kalshi-doge_hourly_99c04dce`
- `kalshi-sports_directional_f1293d74`
- `kalshi-kalshi_catch_all_1b1a7a8e`

These appear to be historical instances of `KalshiTradingAgent` with unique hashes. The hash likely represents a unique session or configuration ID.

### Reflection System Initialization

The reflection system is initialized in multiple locations:

1. **web/startup_agents.py:165-167** - Main startup path
```python
from agents.reflection.integration import get_reflection_system
self.reflection_system = get_reflection_system()
```

2. **merid/prediction/agent_grid.py:651-652** - Agent grid initialization
```python
from agents.reflection.integration import get_reflection_system
_rs = get_reflection_system()
```

3. **agents/reflection_layer.py:78-79** - Legacy v1 system
```python
from agents.reflection.integration import get_reflection_system
return get_reflection_system()
```

### Reflection System Overlap with Kalshi 15m

| Agent Type | Count in Reflections | Classification | Relevance to 15m |
|------------|---------------------|----------------|-------------------|
| Legacy mesh agents | 5 | research_only | None - not used in 15m |
| Kalshi 15m agents | ~500+ | prod_15m_core | Historical instances, not needed |
| Kalshi hourly agents | ~100+ | research_only | Not 15m timeframe |
| Sports agents | ~10+ | research_only | Not crypto |
| Catch-all agents | ~10+ | remove | Not functional |

### Reflection Policy for Kalshi 15m

**Recommendation**: DISABLE the reflection system completely for `MERID_PROFILE=kalshi_crypto_15m_v2`

**Justification**:
1. The reflection system is designed for LLM-based agents (AgentMesh), not for deterministic KalshiTradingAgent
2. Kalshi 15m trading uses microstructure signals, not LLM learning
3. Loading 4364 reflections for 664 agents at startup is unnecessary overhead
4. The reflection data contains historical instances that are not needed for production
5. The reflection system adds complexity without benefit for the 15m use case

**Implementation**:
- Add profile guard in `agents/reflection/integration.py::get_reflection_system()`
- Add profile guard in `web/startup_agents.py::start_all()`
- Add profile guard in `merid/prediction/agent_grid.py::__init__()`
- Log: `INFO | agents.reflection | Reflection disabled for profile=kalshi_crypto_15m_v2 (prod)`

---

## Agent Mesh Analysis

### AgentMesh Components

**File**: `agents/agent_mesh.py`

**Active Agents** (4):
1. MarketAnalystAgent - TA + momentum
2. RiskAgent - Exposure & liquidation (VETO)
3. SkepticAgent - Adversarial check (can force re-round)
4. StrategyAgent - Trade structuring

**Legacy Agents** (moved to legacy/):
- NewsAnalystAgent
- SynthesizerAgent
- ArchivistAgent
- MetaAuditAgent

### AgentMesh Initialization

**Location**: `web/startup_agents.py:147-152`

```python
try:
    from agents.agent_mesh import start_agent_mesh
    await start_agent_mesh()
    logger.info("✅ AgentMesh started (8 streaming agents operational)")
except Exception as exc:
    logger.warning(f"AgentMesh not started (non-fatal): {exc}")
```

**Profile Gating**: Already has VALIDATION_MODE check, but no profile check for kalshi_crypto_15m_v2

### AgentMesh Policy for Kalshi 15m

**Recommendation**: DISABLE AgentMesh for `MERID_PROFILE=kalshi_crypto_15m_v2`

**Justification**:
1. AgentMesh runs LLM-based streaming agents, not used in Kalshi 15m
2. Kalshi 15m uses deterministic signal generators (Btc15mAgent, etc.)
3. AgentMesh adds unnecessary LLM overhead
4. Already skipped in VALIDATION_MODE, should also skip for 15m profile

**Implementation**:
- Add profile guard in `web/startup_agents.py::start_all()`
- Log: `INFO | agents.mesh | AgentMesh skipped for profile=kalshi_crypto_15m_v2 (LLM agents not required)`

---

## Reflection Data Cleanup

### Current State

The reflection file `logs/agent_reflections_v2.json` contains:
- 4364 reflections
- 664 unique agent IDs
- Mix of legacy mesh agents, historical KalshiTradingAgent instances, and non-15m agents

### Cleanup Options

**Option 1**: Delete the reflection file and start fresh
- Simple, but loses all historical data
- May be acceptable for 15m profile since reflection is not used

**Option 2**: Archive the reflection file
- Move to `logs/archive/agent_reflections_v2.json.backup`
- Preserves data for research/backtest profiles
- Starts fresh for 15m profile

**Option 3**: Filter reflections by profile
- Keep only reflections for prod_15m_core agents
- Complex, requires parsing and filtering logic
- May not be worth the effort since reflection is disabled

**Recommendation**: Option 2 - Archive the reflection file

### Implementation

```python
# In agents/reflection/integration.py::ReflectionSystem.__init__()
import os
from pathlib import Path

profile = os.environ.get('MERID_PROFILE', '')
if profile in ('kalshi_crypto_15m', 'kalshi_crypto_15m_v2'):
    # Archive existing reflection file
    storage = storage_path or Path("logs/agent_reflections_v2.json")
    if storage.exists():
        archive_path = storage.parent / "archive" / f"{storage.name}.backup"
        storage.parent.mkdir(parents=True, exist_ok=True)
        storage.rename(archive_path)
        logger.info(f"Archived reflection file to {archive_path}")
```

---

## Startup Log Analysis

### Current Startup Sequence

```
[AGENT-GRID] Loading config from config/kalshi_agent_grid.yaml
[AGENT-GRID] 5 agents enabled: BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M
[REFLECTION-SYSTEM] Loaded 4364 reflections for 664 agents (source: v2, deferred load)
[AGENT-MESH] AgentMesh started (8 streaming agents operational)
```

### Desired Startup Sequence for kalshi_crypto_15m_v2

```
[AGENT-GRID] Loading config from config/kalshi_agent_grid.yaml
[AGENT-GRID] 5 agents enabled: BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M
[REFLECTION-SYSTEM] Reflection disabled for profile=kalshi_crypto_15m_v2 (prod)
[AGENT-MESH] AgentMesh skipped for profile=kalshi_crypto_15m_v2 (LLM agents not required)
[AGENT-REGISTRY-SUMMARY] total=6 (5 signal agents + 1 portfolio risk agent)
[PROFILE-VALIDATION] kalshi_crypto_15m_v2 profile validated
```

### Startup Invariants

For `MERID_PROFILE=kalshi_crypto_15m_v2`:

1. **Agent Registry Size**: `total <= 10` (5 signal agents + 1 portfolio risk + optional monitoring)
2. **No Research Agents**: No agents classified as `research_only` or `remove` in registry
3. **Reflection Disabled**: Reflection system must report "disabled"
4. **AgentMesh Disabled**: AgentMesh must not start
5. **No LLM Agents**: No LLM-based agents (MarketAnalystAgent, BullAnalyst, etc.) in logs
6. **Profile Validation**: Profile config must pass validation checks

### Violation Handling

- **Critical violations** (reflection enabled, AgentMesh started): Log error, continue (non-blocking for now)
- **Warning violations** (agent count > 10, research agents present): Log warning, continue
- **Test violations**: Fail test suite

