# Duplicate Crypto Lane/Grid Audit (2026-05-15)

## Critical Finding: Duplicate BTC Lane Implementations

### Lane Classes Found

| Lane Class | File | Asset | Status | Classification |
|------------|------|-------|--------|----------------|
| **BTC15MLane** | merid/lanes/btc15m_lane.py | BTC | Legacy | ANCIENT_EXPERIMENTAL |
| **Crypto15MLane** | merid/lanes/crypto15m_lane.py | All assets (BTC/ETH/SOL/XRP/DOGE) | Current | PROD_15M_CORE |

### BTC15MLane (Legacy) - ⚠️ ACTIVELY USED IN PRODUCTION

**Location**: `merid/lanes/btc15m_lane.py`

**Key Features**:
- BTC-specific implementation
- Has BTC15MLaneConfig dataclass
- Has LaneOrchestrator that manages BTC15MLane fleet
- Orchestrates BTC 15m trading cycle

**Status**: **ANCIENT_EXPERIMENTAL** - BUT ACTIVELY USED IN PRODUCTION CODE PATHS

**Active Usage Found**:
- `web/api/kalshi_api.py` - Lines 6795, 7280, 7370, 7387, 7406 - Multiple imports for lane control
- `web/startup_agents.py` - Line 173 - LaneOrchestrator startup
- `merid/lanes/__init__.py` - Line 11 - Exported from lanes package

**Risk**: **HIGH** - This legacy lane is actively used in Kalshi API and startup code:
- Different behavior between BTC and other assets
- Blocking calls in legacy code paths could cause main loop hangs
- Maintenance burden (two implementations to maintain)
- Btc15mAgent uses btc_lane (Crypto15MLane) but Kalshi API uses BTC15MLane
- Potential for inconsistent state between the two lane implementations

### Crypto15MLane (Current)

**Location**: `merid/lanes/crypto15m_lane.py`

**Key Features**:
- Generic implementation for all crypto assets
- Has Crypto15MLaneConfig dataclass
- Supports BTC, ETH, SOL, XRP, DOGE via CryptoSymbol enum
- Orchestrates crypto 15m trading cycle
- Integrated with RCK (Risk-Constrained Kelly) and Bayesian parameters

**Status**: **PROD_15M_CORE** - This is the canonical implementation

### Lane Registry

**Location**: `merid/lanes/registry.py`

**Key Features**:
- LaneRegistry class manages Crypto15MLane instances
- Registry pattern for lane lifecycle
- get_lane() method to retrieve lanes by ID

**Status**: Uses Crypto15MLane (current)

## Grid Classes Found

### AgentGrid

**Location**: `merid/prediction/agent_grid.py`

**Key Features**:
- Manages Kalshi trading agent grid
- Loads config from YAML
- Creates KalshiTradingAgent per (asset, timeframe) cell
- Not a duplicate - single canonical implementation

**Status**: **PROD_15M_CORE**

### Other Grid-Related Classes

- `grid_validator.py` - Kalshi grid validation
- `grid_context.py` - Grid context management
- No duplicate grid implementations found

## Agent Classes Per Asset

### BTC Agents

| Agent Class | File | Status | Classification |
|-------------|------|--------|----------------|
| **Btc15mAgent** | merid/agents/btc_15m_agent.py | Current | PROD_15M_CORE |
| **Btc1hAgent** | (archived 2026-01-15) | Archived | REMOVE |
| **Btc15mMakerAgent** | merid/agents/ (research_only) | Research | RESEARCH_ONLY |

### ETH Agents

| Agent Class | File | Status | Classification |
|-------------|------|--------|----------------|
| **Eth15mAgent** | merid/agents/eth_15m_agent.py | Current | PROD_15M_CORE |
| **Eth1hAgent** | (archived 2026-01-15) | Archived | REMOVE |

### SOL Agents

| Agent Class | File | Status | Classification |
|-------------|------|--------|----------------|
| **Sol15mAgent** | merid/agents/sol_15m_agent.py | Current | PROD_15M_CORE |
| **Sol1hAgent** | (archived 2026-01-15) | Archived | REMOVE |

### XRP Agents

| Agent Class | File | Status | Classification |
|-------------|------|--------|----------------|
| **Xrp15mAgent** | merid/agents/xrp_15m_agent.py | Current | PROD_15M_CORE |
| **Xrp1hAgent** | (archived 2026-01-15) | Archived | REMOVE |

### DOGE Agents

| Agent Class | File | Status | Classification |
|-------------|------|--------|----------------|
| **Doge15mAgent** | merid/agents/doge_15m_agent.py | Current | PROD_15M_CORE |
| **Doge1hAgent** | (archived 2026-01-15) | Archived | REMOVE |

## Canonical vs Duplicate Analysis

### Per-Asset Canonical Components

| Asset | Canonical Agent | Canonical Lane | Duplicates to Remove |
|-------|----------------|----------------|---------------------|
| **BTC** | Btc15mAgent | Crypto15MLane | BTC15MLane (legacy), Btc1hAgent (archived), Btc15mMakerAgent (research) |
| **ETH** | Eth15mAgent | Crypto15MLane | Eth1hAgent (archived) |
| **SOL** | Sol15mAgent | Crypto15MLane | Sol1hAgent (archived) |
| **XRP** | Xrp15mAgent | Crypto15MLane | Xrp1hAgent (archived) |
| **DOGE** | Doge15mAgent | Crypto15MLane | Doge1hAgent (archived) |

### Classification Summary

| Component | Count | PROD_15M_CORE | RESEARCH_ONLY | REMOVE | ANCIENT_EXPERIMENTAL |
|-----------|-------|--------------|--------------|--------|---------------------|
| **Agents** | 15 | 5 (Btc/Eth/Sol/Xrp/Doge 15m) | 1 (Btc15mMakerAgent) | 9 (archived 1h agents) | 0 |
| **Lanes** | 2 | 1 (Crypto15MLane) | 0 | 0 | 1 (BTC15MLane) |
| **Grids** | 1 | 1 (AgentGrid) | 0 | 0 | 0 |

## Recommended Actions

### Immediate Actions (High Priority)

1. **⚠️ CRITICAL: BTC15MLane is actively used in Kalshi API**:
   - `web/api/kalshi_api.py` uses BTC15MLane for lane control operations
   - `web/startup_agents.py` uses LaneOrchestrator which manages BTC15MLane instances
   - This is a DIFFERENT implementation than Crypto15MLane used by Btc15mAgent
   - **This inconsistency is a high-risk source of main loop hangs**

2. **Verify which lane Btc15mAgent actually uses**:
   - Btc15mAgent.configure_dependencies() receives btc_lane parameter
   - registry.get_lane("BTC_15M") returns Crypto15MLane instance (from registry.py)
   - **Btc15mAgent uses Crypto15MLane (canonical)**
   - **Kalshi API uses BTC15MLane (legacy)**
   - **Two different lane implementations are in use simultaneously**

3. **Mark BTC15MLane as ANCIENT_EXPERIMENTAL with deprecation warning**:
   - Add deprecation warning at top of btc15m_lane.py
   - Add comment that Crypto15MLane is the canonical implementation
   - Add warning in Kalshi API that it's using legacy lane

4. **Verify archived agents are not imported**:
   - Check that Btc1hAgent, Eth1hAgent, Sol1hAgent, Xrp1hAgent, Doge1hAgent are not imported
   - Verify they're not in agent grid config for kalshi_crypto_15m_v2
   - Add deprecation warnings if they still exist

### Medium-Term Actions

1. **Remove BTC15MLane**:
   - Once verified it's not used, delete btc15m_lane.py
   - Remove any references to BTC15MLane
   - Update documentation to reference Crypto15MLane only

2. **Remove archived agents**:
   - Delete archived 1h agent files
   - Remove from agent inventory
   - Update documentation

3. **Normalize to single lane type**:
   - Ensure all 5 assets use Crypto15MLane
   - Remove any asset-specific lane logic
   - Move asset-specific logic to agent level if needed

## Verification Steps

1. **Search for BTC15MLane imports**:
   ```bash
   grep -r "BTC15MLane" --include="*.py" c:/Dev/MERID
   ```

2. **Search for archived agent imports**:
   ```bash
   grep -r "1hAgent" --include="*.py" c:/Dev/MERID
   ```

3. **Check agent grid config**:
   - Verify kalshi_agent_grid.yaml only has 15m agents
   - Verify no 1h agents are referenced

4. **Run system and check logs**:
   - Start with MERID_PROFILE=kalshi_crypto_15m_v2
   - Check [MAIN-LOOP] logs for any ancient_experimental agents
   - Verify only Crypto15MLane is used, not BTC15MLane

## Next Steps

1. Search for BTC15MLane imports to verify it's not used
2. Search for archived agent imports to verify they're not used
3. Mark BTC15MLane as ANCIENT_EXPERIMENTAL with deprecation warning
4. Verify agent grid config only has 15m agents
5. Run system and check logs for legacy paths
