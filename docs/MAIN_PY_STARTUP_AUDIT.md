# main.py Process Root Audit - Complete Report

**Date**: 2026-04-07
**Scope**: main.py, web/main.py, MERID-Kalshi integration surfaces

## TL;DR

✅ **Running `python main.py` starts AgentGrid (30 trading agents), NOT KalshiContinuousTrader**
✅ **All Kalshi infrastructure components are wired and operational**
❌ **KalshiContinuousTrader is orphaned (not started, deprecated)**
⚠️  **No single SystemController coordinates MeridLoop + AgentGrid startup**

---

## 1. Entrypoint Mapping

### Primary Entrypoint

**File**: `/home/runner/work/MERID/MERID/main.py:356-362`
```python
if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
```

### App Creation Chain

```
main.py:350
  → app = create_app(lifespan=lifespan)
    → where lifespan is from main.py:30-347 (UNUSED, never passed)

web/main.py:264-267
  → create_app(lifespan=None) defaults to _app_lifespan
    → _app_lifespan is at web/main.py:1707

**ACTUAL LIFESPAN**: web/main.py:1707 `_app_lifespan(application: FastAPI)`
```

### Alternative Entrypoints

None found. No Procfiles, gunicorn scripts, or systemd units that bypass main.py.

---

## 2. Startup Contract Table

| Component | File / Symbol | How it should be started | Where actually started | Status |
|-----------|---------------|-------------------------|------------------------|--------|
| **Kalshi Agent Grid** | merid/prediction/agent_grid.py | Background task in lifespan | web/main.py:1741-1746 (Phase 0.5) | ✅ OK |
| **30 KalshiTradingAgents** | merid/prediction/trading_agent.py | By AgentGrid.start() | AgentGrid.start() → line 1743 | ✅ OK |
| **PortfolioRiskAgent** | merid/prediction/portfolio_risk_agent.py | By AgentGrid | AgentGrid.start() | ✅ OK |
| **KalshiMarketCatalog** | merid/event_venues/kalshi/market_catalog.py | Background task | web/main.py:2077-2085 | ✅ OK |
| **KalshiWebSocketBridge** | merid/event_venues/kalshi/ws_bridge.py | Background task | web/main.py:2100-2113 | ✅ OK |
| **TickerCollector** | merid/event_venues/kalshi/ticker_collector.py | Background task | web/main.py:2117-2124 | ✅ OK |
| **KalshiSettlementPoller** | merid/event_venues/kalshi/settlement_poller.py | Background task | web/main.py:2166-2175 | ✅ OK |
| **KalshiSentimentService** | merid/event_venues/kalshi/sentiment.py | Background task | web/main.py:2089-2096 | ✅ OK |
| **KalshiInsightPipeline** | merid/publishing/kalshi_insight_pipeline.py | Background task | web/main.py:2129-2161 | ✅ OK |
| **MeridLoop** | merid/loop.py | Background task | web/main.py:1791-1796 (Phase 0.55) | ✅ OK |
| **LaneOrchestrator (BTC 15m)** | merid/lanes/btc15m_lane.py | By OrchestratorAgentManager | web/startup_agents.py:161-169 | ✅ OK |
| **KalshiContinuousTrader** | merid/trading/kalshi_continuous_trader.py | Should be deprecated or started | **NOWHERE** | ❌ Orphaned |
| **Kalshi API Client** | merid/event_venues/kalshi/client.py | Singleton via DI | Lazy import (on-demand) | ⚠️ Inconsistent |
| **Promotion Engine** | merid/risk/promotion_engine.py | Singleton init | Lazy import | ⚠️ Inconsistent |
| **Web API Kalshi Routers** | web/api/kalshi_*.py | Mounted in create_app | Routers mounted | ✅ OK |

---

## 3. What main.py Actually Boots

### Phase 0.5: AgentGrid (Line 1741-1746)

```python
from merid.prediction.agent_grid import get_agent_grid
agent_grid = get_agent_grid()
await agent_grid.start()
```

**What this does**:
1. Loads `config/kalshi_agent_grid.yaml`
2. Creates 30 KalshiTradingAgent instances (5 assets × 6 timeframes)
3. Creates PortfolioRiskAgent (cross-asset exposure caps)
4. Registers Kalshi tools in guardrails ToolRegistry
5. Starts each agent's async decision loop (staggered by 0.5s)

**Each agent**:
- Runs expiry-window-based cycle (e.g., BTC 15m trades 10 min before expiry)
- Fetches markets from KalshiMarketCatalog
- Evaluates OpinionStrategy signal
- Checks SessionGuard, VenueGate, portfolio risk
- Routes orders via typed Kalshi tools

**No conditional flags** that disable this in production.

### Phase 0.55: MeridLoop (Line 1791-1796)

```python
from merid.loop import get_merid_loop
_merid_loop = get_merid_loop()
asyncio.create_task(_merid_loop.run())
```

**What this does**:
- Runs background loop with feature refresh, consensus, arb scans, CQI updates
- **`enable_execution=false` by default** — MeridLoop doesn't execute trades
- Operates independently of AgentGrid

### Phase 3: Kalshi Data Infrastructure (Line 2065+)

All started as `asyncio.create_task()` or `await component.start()`:

- KalshiMarketCache (TTL cleanup loop)
- KalshiMarketCatalog (market discovery)
- KalshiSentimentService (sentiment refresh)
- KalshiWebSocketBridge (real-time WS → event bus)
- TickerCollector (WS tick accumulation)
- KalshiInsightPipeline (consensus → InsightObject)
- KalshiSettlementPoller (polls settlements, fires reconciliation)
- EnhancedConsensusCoordinator (opinion subscriber)

---

## 4. What main.py Does NOT Boot

### KalshiContinuousTrader (merid/trading/kalshi_continuous_trader.py)

**Status**: ❌ **ORPHANED**

**Evidence**:
- `grep -r "get_continuous_trader" web/main.py` → No matches
- `grep -r "KalshiContinuousTrader.*start()" web/main.py` → No matches
- CT singleton exists but `start()` never called

**Impact**:
1. CT trade cycle never runs → no orders via CT
2. `config/strategy_catalog.yaml` ignored (30-cell config with kelly_fraction, min_edge_bps, etc.)
3. CT canary mode (`MERID_CT_CANARY_MODE`) non-functional
4. Edge calibration tracker partially wired (forecasts never recorded)
5. Daily loss limit enforcement never triggers
6. CT grid logging never emits (`CT-GRID-SUMMARY`, `CT-ASSET-SUMMARY`)

**Why it still exists**:
- API endpoints `/api/v1/ct/*` query singleton (now marked deprecated)
- Reconciliation hooks call `get_continuous_trader()` for bankroll reads
- Manual/CLI usage (scripts, debugging)

**Fix applied**: Deprecation warning added to `CT.start()` (merid/trading/kalshi_continuous_trader.py:776-791)

---

## 5. Upstream/Downstream Bug List

### [P0] No Single SystemController

**Issue**: MeridLoop and AgentGrid start independently with no shared supervisor

**Impact**:
- No startup ordering enforcement (AgentGrid happens to start before MeridLoop)
- No shared "safe to trade" invariant checks
- No coordinated shutdown

**Proposed Fix**:
```python
# In web/main.py _app_lifespan Phase 0.4
class SystemController:
    def __init__(self):
        self.merid_loop = get_merid_loop()
        self.agent_grid = get_agent_grid()

    async def start(self):
        # 1. Validate configs match
        # 2. Check all prerequisites (catalog ready, WS connected, etc.)
        # 3. Start AgentGrid
        # 4. Start MeridLoop
        # 5. Validate safe-to-trade invariants
        pass
```

### [P1] KalshiContinuousTrader Orphaned

**Issue**: CT singleton exists but never starts

**Impact**: strategy_catalog.yaml ignored, CT features non-functional

**Fix Applied**:
- ✅ Deprecation warning added to `CT.start()` (line 776-791)
- ✅ API endpoint `/api/v1/ct/status` now returns `deprecated: true`
- ✅ Documentation created (docs/KALSHI_ARCHITECTURE.md)

**Next Steps**:
- Remove CT from reconciliation hooks (migrate to AgentGrid)
- Delete strategy_catalog.yaml or merge into kalshi_agent_grid.yaml

### [P1] Dual Config System

**Issue**: `kalshi_agent_grid.yaml` vs `strategy_catalog.yaml`

**Impact**: Operators may edit wrong file

**Fix**: Add validation at AgentGrid init:
```python
# In merid/prediction/agent_grid_config.py
def validate_config_consistency():
    grid_agents = load_kalshi_agent_grid_yaml()
    catalog_cells = load_strategy_catalog_yaml()
    assert set(grid_agents.keys()) == set(catalog_cells.keys())
```

### [P2] MeridLoop Execution Disabled by Default

**Issue**: `enable_execution=false` in LoopConfig

**Impact**: MeridLoop runs but doesn't execute (AgentGrid still does)

**Fix**: Document in KALSHI_ARCHITECTURE.md (✅ done)

### [P2] Misleading CT API Endpoints

**Issue**: `/api/v1/ct/status` returns as if CT were active

**Fix Applied**: ✅ Added deprecation metadata to response (web/api/ct_api.py:62-68, 75-81)

---

## 6. Advertised vs Actual Behavior

### main.py Header Claims (Line 4-14)

```python
"""
Boots:
1. Streaming data workers (market + news)
2. Agent mesh (8 autonomous agents)
3. Consensus engine (voting + trust + veto)
4. Simulation mining (PoUS blocks)
5. Audit trail (immutable log)
6. Web API + WebSocket streams
7. Execution engine
8. Alert manager
9. Health monitor
"""
```

### Reality Check

| Item | Status | Location |
|------|--------|----------|
| 1. Streaming data workers | ✅ WIRED | KalshiWebSocketBridge (2100), TickerCollector (2115), WSFeedManager (2293+) |
| 2. Agent mesh | ✅ WIRED | OrchestratorAgentManager → AgentMesh (2189-2200) |
| 3. Consensus engine | ✅ WIRED | consensus engine (1907), EnhancedConsensusCoordinator (2177) |
| 4. Simulation mining | ❌ NOT WIRED | Mentioned in main.py:100 but not in web/main.py lifespan |
| 5. Audit trail | ✅ WIRED | AuditTrail (2046-2054) |
| 6. Web API + WS | ✅ WIRED | FastAPI routers, WS endpoints |
| 7. Execution engine | ⚠️ PARTIAL | AgentGrid provides Kalshi execution; optimal_executor not wired |
| 8. Alert manager | ✅ WIRED | AlertManager (2036-2044) |
| 9. Health monitor | ✅ WIRED | HealthMonitor (2026-2034) |

**Discrepancy**: The root `main.py` has a different lifespan function (lines 30-347) that's NEVER used. Actual lifespan is in `web/main.py`.

---

## 7. Production Statement

### Current Reality

> Running `python main.py` starts: **(a) AgentGrid with 30 KalshiTradingAgents** across BTC/ETH/SOL/XRP/DOGE and 15m/1h/daily/weekly/monthly/annual timeframes (Phase 0.5), **(b) PortfolioRiskAgent** enforcing cross-asset exposure caps (started by AgentGrid), **(c) KalshiMarketCatalog, KalshiWebSocketBridge, TickerCollector, KalshiSentimentService, KalshiInsightPipeline, KalshiSettlementPoller** providing data backbone (Phase 3), **(d) MeridLoop** orchestrator with `enable_execution=false` by default (Phase 0.55), **(e) Web API + WebSocket + metrics** for UI, and **(f) HealthMonitor, AlertManager, AuditTrail** core infrastructure. **KalshiContinuousTrader is NOT started** and exists only for API compatibility. **No single SystemController enforces startup ordering or validates safe-to-trade invariants.**

---

## 8. File:Line References

### Key Startup Locations

- `main.py:356-362` — uvicorn.run() entrypoint
- `main.py:350` — create_app(lifespan=lifespan) [lifespan unused]
- `web/main.py:264-267` — create_app() defaults to _app_lifespan
- `web/main.py:1707` — _app_lifespan() function definition
- `web/main.py:1741-1746` — AgentGrid startup (Phase 0.5)
- `web/main.py:1791-1796` — MeridLoop startup (Phase 0.55)
- `web/main.py:2065-2175` — Kalshi infrastructure (catalog, WS, sentiment, settlement)
- `merid/prediction/agent_grid.py:116` — AgentGrid.start()
- `merid/prediction/agent_grid.py:147` — await agent.start() (for each of 30 agents)
- `merid/prediction/trading_agent.py:150` — agent._run_loop() background task
- `merid/trading/kalshi_continuous_trader.py:775` — CT.start() (NEVER CALLED)

### Configuration

- `config/kalshi_agent_grid.yaml` — ✅ Loaded by AgentGrid (30 agent definitions)
- `config/strategy_catalog.yaml` — ❌ NOT loaded (CT not started)
- `config/crypto_universe.py` — ✅ Asset/timeframe constants
- `config/consensus.yaml` — ✅ Consensus engine config
- `config/settings.yaml` — ✅ Global settings

---

## 9. Next Steps

### Immediate (✅ Done)

- [x] Add deprecation warning to `KalshiContinuousTrader.start()`
- [x] Update `/api/v1/ct/status` to return deprecation metadata
- [x] Create `docs/KALSHI_ARCHITECTURE.md` documenting system hierarchy
- [x] Create `docs/MAIN_PY_STARTUP_AUDIT.md` (this file)

### Short-Term

- [ ] Add config validation between kalshi_agent_grid.yaml and strategy_catalog.yaml
- [ ] Migrate reconciliation hooks from CT to AgentGrid
- [ ] Create SystemController to coordinate MeridLoop + AgentGrid startup
- [ ] Update all docs/tutorials referencing CT to use AgentGrid

### Long-Term

- [ ] Remove KalshiContinuousTrader entirely
- [ ] Deprecate or merge strategy_catalog.yaml into kalshi_agent_grid.yaml
- [ ] Implement unified "safe to trade" invariant checks in SystemController

---

## 10. Validation Commands

**Check AgentGrid is running**:
```bash
curl localhost:8000/api/v1/kalshi-agent-grid/status
# Should show 30 agents, running=true
```

**Verify CT is NOT running**:
```bash
curl localhost:8000/api/v1/ct/status
# Should show running=false, deprecated=true
```

**Check all Kalshi infrastructure**:
```bash
curl localhost:8000/api/health
# Should show kalshi_market_catalog, kalshi_ws_bridge, etc. all "running"
```

**View startup logs**:
```bash
python main.py 2>&1 | grep -E "(AgentGrid|KalshiContinuousTrader|Phase 0\.|MeridLoop)"
```

**Expected log sequence**:
```
Phase 0.5: AgentGrid (30 KalshiTradingAgent + PortfolioRiskAgent)
✅ Kalshi Agent Grid started: 30 trading agents
Phase 0.55: MeridLoop
✅ MeridLoop started
Phase 3: Kalshi infrastructure
✅ KalshiMarketCatalog started
✅ KalshiWebSocketBridge started
✅ KalshiSettlementPoller started
...
[NO "KalshiContinuousTrader starting" message]
```

---

## Appendix A: Full Startup Timeline

```
Phase -1  (1713-1726): Event Loop Monitor
Phase 0   (1728-1734): [SKIPPED] Legacy WS publishers
Phase 0.5 (1736-1746): ✅ AgentGrid (30 agents + PortfolioRisk)
Phase 0.51(1748-1756): ✅ Canonical agent registry
Phase 0.52(1758-1776): ✅ RealityAuditor + RewardEngine
Phase 0.53(1778-1787): ✅ PortfolioRebalancer
Phase 0.55(1789-1796): ✅ MeridLoop
Phase 0.6 (1798-1807): ✅ OrchestratorAgentManager
Phase 1   (1809-1980): ✅ Core (consensus, paper trading, Neo4j, etc.)
Phase 2   (1981-1983): [SKIPPED] Legacy prediction markets
Phase 3   (1985-2500): ✅ Streaming (WS bridge, catalog, sentiment, etc.)
```

---

## Appendix B: Kalshi Component Inventory

**Core Infrastructure**:
- client.py, ws.py, ws_bridge.py, market_catalog.py, market_cache.py, venue_adapter.py

**Trading & Execution**:
- trading_agent.py (MODERN), agent_grid.py (ORCHESTRATOR)
- kalshi_continuous_trader.py (DEPRECATED)
- order_router.py, order_manager.py, trading.py
- btc15m_lane.py (lane orchestrator)

**Risk & Position**:
- crypto_kalshi_risk.py, kalshi_risk.py, bracket_risk.py
- portfolio_risk_agent.py, position_cache.py, position_sizer.py

**Strategy & Signals**:
- strategy_grid.py, pipeline_audit.py, strategy.py, model.py

**Data & Monitoring**:
- sentiment.py, ticker_collector.py, metrics.py
- liquidity_monitor.py, volume_monitor.py
- settlement_poller.py, fills_ledger.py
- reconciliation.py

**Config & Promotion**:
- kalshi_agent_grid.yaml (ACTIVE)
- strategy_catalog.yaml (IGNORED)
- auto_promoter.py, promotion_engine.py

---

**Audit Complete**: 2026-04-07
**Audited By**: Claude (Main.py Process Root Audit)
**Next Review**: After SystemController implementation
