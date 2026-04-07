# Kalshi Trading System Architecture

## Executive Summary

MERID's Kalshi integration uses **AgentGrid** as the production trading system, NOT KalshiContinuousTrader. Running `python main.py` starts AgentGrid with 30 trading agents (5 assets × 6 timeframes).

## Trading System Hierarchy

### 1. AgentGrid (Production System)

**Location**: `merid/prediction/agent_grid.py`
**Started**: web/main.py `_app_lifespan` Phase 0.5 (line 1741-1746)
**Configuration**: `config/kalshi_agent_grid.yaml`

**Architecture**:
```
AgentGrid (Orchestrator)
├── 30× KalshiTradingAgent (5 assets × 6 timeframes)
│   ├── BTC: 15m, 1h, daily, weekly, monthly, annual
│   ├── ETH: 15m, 1h, daily, weekly, monthly, annual
│   ├── SOL: 15m, 1h, daily, weekly, monthly, annual
│   ├── XRP: 15m, 1h, daily, weekly, monthly, annual
│   └── DOGE: 15m, 1h, daily, weekly, monthly, annual
├── PortfolioRiskAgent (cross-asset exposure caps)
├── SessionGuard (trading hours enforcement)
├── VenueGate (PAPER/LIVE mode gating)
└── KalshiMarketCatalog (market discovery)
```

**Each KalshiTradingAgent**:
- Runs an async decision loop per entry window (expiry-based timing)
- Fetches active markets from KalshiMarketCatalog
- Evaluates strategy signal (OpinionStrategy subclasses)
- Checks risk gates (SessionGuard, VenueGate, portfolio limits)
- Routes orders via typed Kalshi tools (guardrails-protected)
- Enforces per-agent risk limits (max_yes_position, max_no_position, max_notional_usd)

**Key Features**:
- Phase-gated promotion (PromotionEngine) based on realized PnL
- Deployment controller (PAPER → OBSERVATION → LIVE progression)
- Stop-loss rules per position
- Real-time settlement reconciliation via KalshiSettlementPoller

### 2. KalshiContinuousTrader (DEPRECATED)

**Location**: `merid/trading/kalshi_continuous_trader.py`
**Started**: **NEVER** (not called from main.py)
**Configuration**: `config/strategy_catalog.yaml` (NOT loaded in production)

**Status**:
- ⚠️  **DEPRECATED** — `start()` method emits deprecation warning
- Singleton exists for API compatibility and reconciliation hooks
- NOT part of production trading flow
- strategy_catalog.yaml parameters are IGNORED

**Why it still exists**:
1. **API compatibility**: `/api/v1/ct/*` endpoints query CT singleton (read-only)
2. **Reconciliation hooks**: `merid/reconciliation.py` calls CT for bankroll updates
3. **Manual/CLI usage**: Scripts and debugging tools may instantiate CT directly

**Migration Path**:
- All production trading happens via AgentGrid
- CT will be fully removed in a future release once reconciliation is migrated
- Operators should NOT tune CT environment variables (e.g., `MERID_CT_CANARY_MODE`)

### 3. MeridLoop (Top-Level Orchestrator)

**Location**: `merid/loop.py`
**Started**: web/main.py `_app_lifespan` Phase 0.55 (line 1791-1796)
**Configuration**: `LoopConfig.from_paper_config()`

**Purpose**:
```
MeridLoop.run() [async background task]
├── 1. Refresh features (news, macro, onchain, social) with decay
├── 2. Run agent cycles per domain (crypto, prediction)
├── 3. Run consensus aggregation (decay-aware)
├── 4. Run arb/dislocation scans
├── 5. Generate plans → risk checks → pass to execution
├── 6. Update CQI / drift metrics
├── 7. Reconcile positions with venues
└── 8. Push events to subscribers
```

**Key Configuration**:
- `enable_execution: false` (default) — MeridLoop does NOT execute trades by default
- `active_domains: ["crypto", "prediction"]`
- Operates independently of AgentGrid's execution path

**Relationship to AgentGrid**:
- MeridLoop and AgentGrid run in parallel
- No shared supervisor or coordination layer (yet)
- AgentGrid provides Kalshi execution; MeridLoop handles crypto/other domains
- Both started independently in different phases of _app_lifespan

## Startup Sequence

**File**: `web/main.py` → `_app_lifespan()` function (line 1707)

### Timeline

```
Phase -1  (1713-1726): Event Loop Monitor
Phase 0   (1728-1734): [SKIPPED] Legacy WS publishers
Phase 0.5 (1736-1746): ✅ AgentGrid (30 KalshiTradingAgent + PortfolioRiskAgent)
Phase 0.51(1748-1756): ✅ Canonical agent registry bootstrap
Phase 0.52(1758-1776): ✅ RealityAuditor + RewardEngine
Phase 0.53(1778-1787): ✅ PortfolioRebalancer
Phase 0.55(1789-1796): ✅ MeridLoop (enable_execution=false)
Phase 0.6 (1798-1807): ✅ OrchestratorAgentManager (AgentMesh, LaneOrchestrator, etc.)
Phase 1   (1809-1980): ✅ Core systems (consensus, paper trading, data persistence)
Phase 2   (1981-1983): [SKIPPED] Legacy prediction markets
Phase 3   (1985-2500): ✅ Streaming services (full list below)
```

### Phase 3: Kalshi Data Infrastructure

All started as background tasks in _app_lifespan:

| Component | Line | Purpose |
|-----------|------|---------|
| **KalshiMarketCache** | 2065-2074 | TTL-based cache with cleanup loop |
| **KalshiMarketCatalog** | 2077-2085 | Market discovery & caching backbone |
| **KalshiSentimentService** | 2089-2096 | Sentiment refresh loop |
| **KalshiWebSocketBridge** | 2100-2113 | Real-time WS events → internal event bus |
| **TickerCollector** | 2117-2124 | WS tick accumulator (in-memory DataFrame) |
| **KalshiInsightPipeline** | 2129-2161 | Kalshi → swarm consensus → InsightObject |
| **KalshiSettlementPoller** | 2166-2175 | Polls /portfolio/settlements, fires reconciliation |
| **EnhancedConsensusCoordinator** | 2177-2187 | Opinion subscriber, triggers consensus rounds |

### What main.py Actually Starts for Kalshi

**Direct from main.py lifespan**:
- AgentGrid.start() → 30 KalshiTradingAgent async loops
- PortfolioRiskAgent monitoring loop
- All Phase 3 data infrastructure (catalog, WS bridge, settlement poller, etc.)

**NOT started**:
- KalshiContinuousTrader (orphaned, deprecated)

## Configuration Files

### kalshi_agent_grid.yaml (PRODUCTION)

**Location**: `config/kalshi_agent_grid.yaml`
**Loaded by**: `merid/prediction/agent_grid_config.py:get_agent_grid_config()`
**When**: AgentGrid.__init__() (Phase 0.5)

**Schema**:
```yaml
venue:
  name: kalshi
  use_demo: false  # PRODUCTION = true
  max_notional_per_expiry_usd: 5000

session:
  maintenance_day: 3  # Thursday
  maintenance_start_et: "03:00"
  maintenance_end_et: "05:00"

agents:
  - name: BTC_15M
    assets: [BTC]
    timeframes: [15m]
    archetype: directional
    market_filter:
      category: crypto
      frequency: fifteen_min
    risk_limits:
      max_yes_position: 2000
      max_no_position: 2000
      max_orders_per_window: 20
      max_notional_usd: 500
    entry_window:
      minutes_before_expiry: 10
      cutoff_minutes_before_expiry: 1
  # ... (29 more agents)
```

### strategy_catalog.yaml (IGNORED)

**Location**: `config/strategy_catalog.yaml`
**Loaded by**: KalshiContinuousTrader (which is NOT started)
**Status**: ⚠️  **NOT USED IN PRODUCTION**

**Contains**: 30-cell grid with `kelly_fraction`, `min_edge_bps`, `max_risk_per_trade_pct` — all ignored because CT never starts.

**Action Required**: Migrate relevant parameters to kalshi_agent_grid.yaml or deprecate file.

## API Endpoints

### Production System

- `GET /api/v1/kalshi-agent-grid/status` — Live AgentGrid status
- `GET /api/v1/kalshi-agent-grid/agents` — List all 30 agents
- `GET /api/v1/kalshi-agent-grid/agents/{agent_id}` — Per-agent detail
- `GET /api/v1/kalshi-deployment/status` — Deployment controller (PAPER/LIVE modes)

### Legacy/Deprecated

- `GET /api/v1/ct/status` — ⚠️  Returns CT singleton status (NOT running)
  - Now includes `deprecated: true` and `production_system` pointer
- `GET /api/v1/ct/market-states` — ⚠️  Returns empty (CT not running)

## Risk & Safety

### Multi-Layer Risk Gates

**Per-Agent Limits** (from kalshi_agent_grid.yaml):
- max_yes_position, max_no_position (contracts)
- max_orders_per_window (count)
- max_notional_usd (per expiry)

**Portfolio-Level Limits** (PortfolioRiskAgent):
- max_total_exposure_usd (cross-asset)
- max_drawdown_pct
- max_margin_utilization

**Session-Level Gates** (SessionGuard):
- Trading hours enforcement (24/7 except Thu 3-5 AM ET maintenance)

**Venue-Level Gates** (VenueGate):
- PAPER/OBSERVATION/LIVE mode progression
- Kill switch support

**Phase-Gated Promotion** (PromotionEngine):
- Unlocks assets, timeframes, and live execution based on realized PnL
- Tracks equity, drawdown, Sharpe, trade count
- Enforces conservative progression (Phase 0 → 1 → 2 → 3)

### Invariant Checks

**PipelineAudit** (merid/event_venues/kalshi/pipeline_audit.py):
- UPSTREAM: scan_by_asset_timeframe coverage
- CORE: candidate quality (edge, volume, spread)
- DOWNSTREAM: order submission success rates

**Bankroll Invariant**:
- Tracked by PortfolioRiskAgent
- CT singleton used for reconciliation hooks only (not for live trading)

## Common Pitfalls

### ❌ DON'T: Start KalshiContinuousTrader in Production

**Wrong**:
```python
# In web/main.py _app_lifespan
from merid.trading.kalshi_continuous_trader import get_continuous_trader
ct = get_continuous_trader()
asyncio.create_task(ct.start())  # ❌ DEPRECATED
```

**Right**:
```python
# Already done in Phase 0.5
from merid.prediction.agent_grid import get_agent_grid
agent_grid = get_agent_grid()
await agent_grid.start()  # ✅ Production system
```

### ❌ DON'T: Edit strategy_catalog.yaml for Production

**Wrong**:
```yaml
# config/strategy_catalog.yaml
BTC_15M:
  kelly_fraction: 0.05  # ❌ Ignored (CT not started)
```

**Right**:
```yaml
# config/kalshi_agent_grid.yaml
- name: BTC_15M
  risk_limits:
    max_notional_usd: 500  # ✅ Used by AgentGrid
```

### ❌ DON'T: Query `/api/v1/ct/status` for Live System

**Wrong**:
```javascript
// Dashboard expecting live data
fetch('/api/v1/ct/status')  // ❌ Always shows running=false
```

**Right**:
```javascript
// Query production system
fetch('/api/v1/kalshi-agent-grid/status')  // ✅ Live AgentGrid status
```

## Migration Checklist

If you're migrating from docs/tutorials referencing KalshiContinuousTrader:

- [ ] Replace CT imports with AgentGrid
- [ ] Update config edits from strategy_catalog.yaml to kalshi_agent_grid.yaml
- [ ] Change API endpoint calls from `/api/v1/ct/*` to `/api/v1/kalshi-agent-grid/*`
- [ ] Remove CT environment variables (MERID_CT_CANARY_MODE, etc.)
- [ ] Update monitoring dashboards to query AgentGrid endpoints

## Further Reading

- `merid/prediction/agent_grid.py` — AgentGrid implementation
- `merid/prediction/trading_agent.py` — KalshiTradingAgent (per-cell agent)
- `merid/prediction/portfolio_risk_agent.py` — Cross-asset risk
- `config/kalshi_agent_grid.yaml` — Full agent configuration
- `docs/SETTLEMENT_POLLER_VERIFICATION.md` — Settlement reconciliation guide
