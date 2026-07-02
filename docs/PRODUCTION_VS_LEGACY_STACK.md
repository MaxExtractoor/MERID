# Production vs Legacy Stack Documentation

**Profile:** `kalshi_crypto_15m_v2`  
**Purpose:** 15-minute crypto trading on Kalshi (BTC, ETH, SOL, XRP, DOGE)  
**Date:** 2026-06-05

---

## Executive Summary

The MERID codebase contains two distinct trading stacks:

1. **Production Stack (15m Live Trading)** - Actively used for `kalshi_crypto_15m_v2` profile
2. **Legacy Stack** - Deprecated for 15m trading, still present for other profiles/tests

This document clarifies which components are actively used, which are deprecated, and what needs migration.

---

## Production Stack Components

### Core Trading Components

| Component | File | Purpose | Status |
|-----------|------|---------|--------|
| **Event Loop** | `merid/loop_15m.py` | Lean event loop for 15m crypto trading | ✓ ACTIVE |
| **Agent Grid** | `merid/prediction/agent_grid_15m.py` | LeanAgentGrid15m with velocity-based signals | ✓ ACTIVE |
| **BTC Agent** | `merid/agents/btc_15m_agent.py` | BTC 15m trading agent | ✓ ACTIVE |
| **ETH Agent** | `merid/agents/eth_15m_agent.py` | ETH 15m trading agent | ✓ ACTIVE |
| **SOL Agent** | `merid/agents/sol_15m_agent.py` | SOL 15m trading agent | ✓ ACTIVE |
| **XRP Agent** | `merid/agents/xrp_15m_agent.py` | XRP 15m trading agent | ✓ ACTIVE |
| **DOGE Agent** | `merid/agents/doge_15m_agent.py` | DOGE 15m trading agent | ✓ ACTIVE |
| **Edge Computation** | `merid/prediction/unified_edge.py` | Unified edge computation | ✓ ACTIVE |
| **Risk Envelope** | `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py` | Risk envelope | ✓ ACTIVE |
| **Candidate Optimizer** | `merid/prediction/candidate_optimizer.py` | Market selection and ranking | ✓ ACTIVE |
| **Order Router** | `merid/event_venues/kalshi/order_router.py` | Order routing with security checks | ✓ ACTIVE |

### Configuration

| Component | File | Purpose | Status |
|-----------|------|---------|--------|
| **Risk Profile** | `config/profiles/kalshi_crypto_15m_v2.yaml` | Single source of truth for risk config | ✓ ACTIVE |
| **Environment** | `merid/config/environment.py` | Environment configuration | ✓ ACTIVE |

### Web/API Components

| Component | File | Purpose | Status |
|-----------|------|---------|--------|
| **FastAPI App** | `web/main_15m_lean.py` | FastAPI app for 15m stack | ✓ ACTIVE |
| **Startup Script** | `start_15m.ps1` | Startup script | ✓ ACTIVE |
| **Startup Agents** | `web/startup_agents.py` | Orchestrator startup (with profile guards) | ✓ ACTIVE |

### Venue Components

| Component | File | Purpose | Status |
|-----------|------|---------|--------|
| **Kalshi Client** | `merid/event_venues/kalshi/client.py` | Kalshi REST client | ✓ ACTIVE |
| **Market State Store** | `merid/event_venues/kalshi/market_state.py` | KalshiMarketStateStore (single source of truth) | ✓ ACTIVE |
| **Market Registry** | `merid/kalshi/market_registry.py` | Active market tracking | ✓ ACTIVE |
| **Fills Poller** | `merid/event_venues/kalshi/fills_poller.py` | Background fills polling | ✓ ACTIVE |
| **Bankroll Service** | `merid/event_venues/kalshi/bankroll_service_v2.py` | Bankroll service v2 | ✓ ACTIVE |
| **Executor** | `merid/execution/executors/kalshi.py` | Kalshi executor | ✓ ACTIVE |

### Import Policy (15m_live mode)

**Allowed imports:**
- `merid.loop_15m` (this module)
- `merid.prediction.agent_grid_15m`
- `merid.prediction.candidate_optimizer`
- `merid.event_venues.kalshi.*` (venue adapter, market_state, risk)
- `data.unified_spot_service`
- `config.kalshi_*` (15m-specific configs only)
- Generic utilities (logging, metrics, datetime, typing, dataclasses)

**Forbidden imports:**
- PM runtime controllers
- Paper trading engine
- Reflection/learning systems
- Social broadcasters
- Cross-venue logic
- Deprecated config modules (kalshi_15m_crypto_config.py)

---

## Legacy Stack Components

### Deprecated Trading Components

| Component | File | Purpose | Status | Note |
|-----------|------|---------|--------|------|
| **Continuous Trader** | `merid/trading/kalshi_continuous_trader.py` | Continuous trader | ✗ DEPRECATED | Not used in 15m loop, used only in tests |
| **Lane System** | `merid/lanes/crypto15m_lane.py` | Lane orchestration | ✗ DEPRECATED | Comment: "LEGACY REMOVAL: lane system moved to archive/legacy/" |
| **Lane Registry** | `merid/lanes/registry.py` | Lane registry | ✗ DEPRECATED | Comment: "LEGACY REMOVAL" |
| **Hourly Agents** | `merid/agents/btc_1h_agent.py` | Hourly agents | ✗ SIGNAL-ONLY | Signal-only mode, not live trading |
| **Legacy Agent Grid** | `config/kalshi_agent_grid.yaml` | Legacy agent grid config | ✗ DEPRECATED | Replaced by agent_grid_15m.py |

### Deprecated Orchestration Components

| Component | File | Purpose | Status | Note |
|-----------|------|---------|--------|------|
| **Social Broadcaster** | `merid/prediction/social_broadcaster.py` | Social broadcasting | ✗ DEPRECATED | Moved to archive/legacy/ |
| **Reflection System** | `merid/agents/reflection/` | Reflection/learning systems | ✗ DISABLED | Disabled for 15m stack |
| **Consensus Engine** | `core.consensus_engine` | Consensus module | ✗ DELETED | Module deleted, endpoints disabled |
| **AgentMesh** | `agents/` | LLM agents | ✗ DISABLED | Profile guard blocks startup for kalshi_crypto_15m_v2 |

### Deprecated Configuration

| Component | File | Purpose | Status | Note |
|-----------|------|---------|--------|------|
| **Legacy Config** | `config/kalshi_15m_crypto_config.py` | Legacy 15m crypto config | ✗ DEPRECATED | Forbidden import in 15m_live mode |
| **Crypto Threshold Matrix** | `config/crypto_threshold_matrix.yaml` | Edge thresholds | ✗ PROFILE-GATED | Disabled by profile guard for 15m stack |
| **Legacy Agent Grid** | `config/kalshi_agent_grid.yaml` | Legacy agent grid | ✗ DEPRECATED | Replaced by agent_grid_15m.py |

### Deprecated Web Components

| Component | File | Purpose | Status | Note |
|-----------|------|---------|--------|------|
| **Run 15m Lean** | `web/run_15m_lean.py` | Startup script | ✗ DEPRECATED | Comment: "DEPRECATED: Use start_15m.ps1 instead" |
| **Incentive API** | `web/api/incentive_api.py` | Incentive endpoints | ✗ DISABLED | Consensus module deleted |
| **Crypto Signals API** | `web/api/kalshi_crypto_signals_api.py` | Consensus signals | ✗ DISABLED | Consensus module deleted |

### Archived Components

| Component | File | Purpose | Status |
|-----------|------|---------|--------|
| **Legacy Lane** | `archive/legacy/crypto15m_lane.py` | Archived lane implementation | ARCHIVED |
| **Legacy Registry** | `archive/legacy/registry.py` | Archived lane registry | ARCHIVED |

---

## Dependency Mapping

### Production Stack Dependencies

```
start_15m.ps1
    ↓
web/main_15m_lean.py
    ↓
web/startup_agents.py (with profile guards)
    ↓
├── merid.loop_15m (production event loop)
│   └── merid.prediction.agent_grid_15m
│       ├── merid.agents.btc_15m_agent.py
│       ├── merid.agents.eth_15m_agent.py
│       ├── merid.agents.sol_15m_agent.py
│       ├── merid.agents.xrp_15m_agent.py
│       └── merid.agents.doge_15m_agent.py
├── merid.event_venues.kalshi.* (venue components)
├── merid.risk.profiles.kalshi_crypto_15m_risk_envelope
└── config.profiles.kalshi_crypto_15m_v2.yaml
```

### Legacy Stack Dependencies (Still Referenced)

**Test Dependencies:**
- `merid.trading.kalshi_continuous_trader.py` - Used in 20+ test files
- `merid.lanes.crypto15m_lane.py` - Used in test_lane_invariants.py
- `merid.lanes.registry.py` - Used in startup_validations.py

**API Dependencies (Profile-Guarded):**
- `merid.lanes.registry.py` - Used in startup_agents.py (Crypto15MLane startup)
- `merid.lanes.crypto15m_lane.py` - Used in startup_agents.py (Crypto15MLane startup)

**Note:** The lane system is still started in startup_agents.py despite the "LEGACY REMOVAL" comment. This appears to be a contradiction that needs clarification.

---

## Migration Status

### Components That Need Migration

| Component | Current State | Migration Needed | Priority |
|-----------|---------------|------------------|----------|
| **Lane System** | Still started in startup_agents.py | Clarify if needed or remove | HIGH |
| **Continuous Trader** | Used in tests only | Remove from production code paths | MEDIUM |
| **Legacy Config Files** | Still present | Archive or document as deprecated | LOW |
| **Test Dependencies** | Tests still import legacy | Update tests to use production components | MEDIUM |

### Components That Are Already Migrated

| Component | Migration Status | Notes |
|-----------|------------------|-------|
| **Event Loop** | ✓ Migrated to loop_15m.py | Replaces legacy merid.loop |
| **Agent Grid** | ✓ Migrated to agent_grid_15m.py | Replaces legacy agent grid |
| **Risk Configuration** | ✓ Migrated to kalshi_crypto_15m_v2.yaml | Single source of truth |
| **Web App** | ✓ Migrated to main_15m_lean.py | Replaces legacy web app |
| **Startup Script** | ✓ Migrated to start_15m.ps1 | Replaces run_15m_lean.py |

---

## Profile Guards

### Profile-Guarded Components (Disabled for kalshi_crypto_15m_v2)

The following components are explicitly disabled via profile guards in `web/startup_agents.py`:

1. **Kalshi Insight Pipeline** - Insight/news publishing not needed for 15m crypto
2. **AgentMesh** - LLM agents not needed for 15m crypto (raises RuntimeError if started)
3. **Social Broadcaster** - Social broadcasting not needed for 15m crypto
4. **Reflection System** - Reflection/learning not needed for 15m crypto

### Profile-Guarded API Endpoints

The following API endpoints are disabled for `kalshi_crypto_15m_v2`:

1. **Agent Mode Routing** - Disabled (sealed 15m profile uses direct agent grid)
2. **Sentiment Decision** - Disabled (sentiment is research-only)
3. **Paper vs Shadow Comparison** - Disabled (sealed 15m profile uses direct trading)
4. **Incentive Endpoints** - Disabled (consensus module deleted)
5. **Consensus Signals** - Disabled (consensus module deleted)

---

## Contradictions and Ambiguities

### 1. Lane System Status

**Contradiction:**
- `web/startup_agents.py` line 212: "LEGACY REMOVAL: lane system (registry, paper_session) moved to archive/legacy/ during 15m stack cleanup"
- `web/startup_agents.py` line 213: "The 15m stack uses loop_15m.py and agent_grid_15m.py instead of lanes"
- **BUT** lines 215-286 still import and start Crypto15MLane via lane registry

**Resolution Needed:**
- Either remove lane system startup entirely (if truly not needed)
- Or update comments to reflect that lane system is still needed for some functionality

### 2. Continuous Trader Status

**Contradiction:**
- Tests still import and use `KalshiContinuousTrader`
- API endpoints still reference `KalshiContinuousTrader` (e.g., reset_continuous_trader)
- But continuous trader is not used in production 15m loop

**Resolution Needed:**
- Clarify if continuous trader is needed for any production functionality
- If not, remove from production code paths and keep only for tests
- If yes, document why it's still needed

### 3. Legacy Config Files

**Contradiction:**
- `config/kalshi_15m_crypto_config.py` is forbidden in import policy
- But file still exists in codebase
- Other legacy config files still present (crypto_threshold_matrix.yaml, kalshi_agent_grid.yaml)

**Resolution Needed:**
- Archive or delete truly deprecated config files
- Document which config files are still needed and why

---

## End-to-End Audit Findings

### Critical Issue: Two Agent Systems Exist

**Finding**: The codebase contains TWO completely different agent systems for 15m crypto trading:

1. **Production Agent System** (ACTIVELY USED):
   - Location: `merid/prediction/agent_grid_15m.py`
   - Class: `LeanAgent15m`
   - Grid: `LeanAgentGrid15m`
   - Builder: `build_15m_agent_grid()`
   - Used by: `merid/loop_15m.py` (production event loop)
   - Signal Strategy: Velocity-based (Coinbase 1-minute velocity)
   - Assets: BTC, ETH, SOL, XRP, DOGE (hardcoded in build function)
   - Import Policy: Strict - no legacy imports allowed

2. **Legacy Agent System** (NOT USED IN PRODUCTION):
   - Location: `merid/agents/btc_15m_agent.py`, `eth_15m_agent.py`, `sol_15m_agent.py`, `xrp_15m_agent.py`, `doge_15m_agent.py`
   - Classes: `Btc15mAgent`, `Eth15mAgent`, `Sol15mAgent`, `Xrp15mAgent`, `Doge15mAgent`
   - Signal Strategy: RTI-based (regime-aware)
   - Used by: Tests only, legacy code
   - Import Issue: Imports deprecated `config.kalshi_15m_crypto_config`

**Impact**: The legacy agents are NOT used in production, so their deprecated imports are not a production issue. However, this creates confusion and potential for accidental use.

### Issue: Deprecated Config Import in Legacy Agents

**Finding**: The legacy agents (`Btc15mAgent`, `Eth15mAgent`, etc.) import:
```python
from config.kalshi_15m_crypto_config import log_risk_limits_for_agent
```

**Status**: 
- This is forbidden in the 15m import policy (loop_15m.py line 36)
- However, `profile_resolver.py` notes that `kalshi_15m_crypto_config.py` is NOT deprecated for universe constants, only for risk-related parts
- The agents use it for logging risk limits, which is risk-related

**Impact**: 
- NOT a production issue (legacy agents not used in production)
- Confusing for developers
- Should be fixed to prevent accidental use

### Issue: Lane System Contradiction

**Finding**: `web/startup_agents.py` has contradictory comments:
- Line 212: "LEGACY REMOVAL: lane system (registry, paper_session) moved to archive/legacy/"
- Line 213: "The 15m stack uses loop_15m.py and agent_grid_15m.py instead of lanes"
- BUT lines 215-286 still import and start Crypto15MLane

**Impact**: 
- Confusing documentation
- Unclear if lane system is actually needed
- Potential resource waste if not needed

## Recommendations

### High Priority

1. **Clarify Lane System Status**
   - Determine if Crypto15MLane is actually needed for 15m production
   - If not needed: Remove lane system startup from startup_agents.py
   - If needed: Update comments to reflect actual usage

2. **Fix Legacy Agent Deprecated Imports**
   - Remove `from config.kalshi_15m_crypto_config import log_risk_limits_for_agent` from legacy agents
   - Replace with profile-based logging or remove entirely (agents not used in production)
   - Add deprecation warning to legacy agents

3. **Document Two Agent Systems**
   - Add clear documentation explaining the two agent systems
   - Mark legacy agents as "DO NOT USE IN PRODUCTION"
   - Consider moving legacy agents to archive/legacy/

### Medium Priority

4. **Update Test Dependencies**
   - Update tests to use production components where possible
   - Create test doubles for legacy components if needed
   - Document which tests require legacy components and why

5. **Add Deprecation Warnings**
   - Add deprecation warnings to legacy components still in use
   - Add warnings when legacy components are imported in production mode
   - Document migration path for each deprecated component

### Low Priority

6. **Document Migration History**
   - Create migration timeline document
   - Document reasons for each migration decision
   - Archive old documentation

---

## Conclusion

The production 15m stack is well-defined with clear separation from legacy components. However, there are some contradictions and ambiguities that need resolution:

1. **Lane system** is marked as "LEGACY REMOVAL" but still started in production
2. **Continuous trader** is not used in production but still referenced in API endpoints
3. **Legacy config files** are forbidden but still present in codebase

Resolving these contradictions will provide clarity on what's actually being used and what needs migration.

**Overall Assessment:** Production stack is production-ready, but legacy cleanup is incomplete.

---

**Document End**
