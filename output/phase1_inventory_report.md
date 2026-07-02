# Phase 1: Inventory and Duplication Scan Report

**Generated**: 2026-06-13  
**Scope**: Critical components for kalshi_crypto_15m_v2 production profile

---

## Executive Summary

**CRITICAL FINDINGS**:
1. **Mixed imports**: Code imports from both legacy `merid.prediction.agent_grid` and production `merid.prediction.agent_grid_15m`
2. **Multiple Kalshi client implementations**: At least 6 different client classes exist
3. **Multiple run_cycle implementations**: The method you edited (`LeanAgentGrid15m.run_cycle`) is one of 13+ implementations
4. **Legacy bankroll service still referenced**: `KalshiBankrollService` (deprecated) still has 40+ references

---

## 1. Agent Grid Classes

### Production Path
- **Class**: `LeanAgentGrid15m`
- **Location**: `merid/prediction/agent_grid_15m.py:6997`
- **Instantiation**: `merid/prediction/agent_grid_15m.py:9105` (single site)
- **Status**: PRODUCTION - This is the canonical implementation for kalshi_crypto_15m_v2

### Test Path
- **Class**: `TestAgentGrid15mMetrics`
- **Location**: `tests/test_observability_metrics.py:9`
- **Status**: TEST

### Import Analysis
**Production imports** (30+ sites):
```python
from merid.prediction.agent_grid_15m import get_agent_grid
from merid.prediction.agent_grid_15m import build_15m_agent_grid
from merid.prediction.agent_grid_15m import LeanAgent15m
```

**Legacy imports** (45+ sites - PROBLEMATIC):
```python
from merid.prediction.agent_grid import get_agent_grid  # LEGACY
from merid.prediction.agent_grid import AgentGrid  # LEGACY
```

**Files with legacy imports that should be reviewed**:
- `web/api/risk_metrics_api.py`
- `web/api/real_data_endpoints.py`
- `web/api/operator.py`
- `web/api/missing_endpoints.py`
- `web/api/kalshi_ui_state_api.py`
- `web/api/kalshi_agent_performance_api.py`
- `web/api/auto_promoter_api.py`
- `merid/loop.py` (legacy loop)
- `merid/swarm/execution_subscriber.py`
- `merid/prediction/edge_recalibrator.py`
- `merid/event_venues/kalshi/auto_promoter.py`
- `merid/event_venues/kalshi/rebalancer.py`
- `core/reality_auditor.py`
- `bots/bot_integration.py`

---

## 2. Scheduler Classes

### Production Path
- **Class**: `Crypto15mScheduler`
- **Location**: `merid/event_venues/kalshi/crypto_15m_scheduler.py:56`
- **Singleton**: `get_crypto_15m_scheduler()` at line 260
- **Status**: PRODUCTION

### Test Usage
- **Location**: `tests/test_catalog_window_behavior.py:36,48`
- **Status**: TEST

### Missing Patterns
- No `getkalshi15mwindow` or `getcurrentutcwindow` functions found (may be inline or renamed)

---

## 3. Catalog Classes

### Production Path
- **Class**: `KalshiMarketCatalog`
- **Location**: `merid/event_venues/kalshi/market_catalog.py:430`
- **Singleton**: `get_market_catalog()` at line 2747
- **Status**: PRODUCTION - Canonical catalog implementation

### Specialized Catalog
- **Class**: `KalshiCryptoCatalog`
- **Location**: `merid/event_venues/kalshi/crypto_catalog.py:109`
- **Purpose**: Crypto-specific view over KalshiMarketCatalog
- **Status**: PRODUCTION - Helper for crypto filtering

### Instantiation Sites (50+)
**Production usage**:
- `web/main_15m_lean.py:1928` - Main entrypoint
- `merid/event_venues/kalshi/market_catalog.py:2753` - Singleton creation

**Test usage** (40+ sites):
- Multiple test files in `tests/` and `tests/event_venues/kalshi/`

**Script usage** (10+ sites):
- `scripts/validate_kalshi_15m_config.py`
- `scripts/validate_invariants.py`
- `scripts/validate_contract_metadata.py`
- `scripts/trace_one_market.py`
- `scripts/validate_btc_wiring.py`

**Legacy usage**:
- `archive/legacy/strategies/sentiment_swarm_execution.py`
- `archive/legacy/trading_agent.py`
- `legacy/lanes/btc15m_lane.py`

---

## 4. Bankroll Services

### Production Path
- **Class**: `BankrollServiceV2`
- **Location**: `merid/event_venues/kalshi/bankroll_service_v2.py:116`
- **Singleton**: `get_bankroll_service_v2()` at line 886
- **Status**: PRODUCTION - Single source of truth for bankroll

### Deprecated Path
- **Class**: `KalshiBankrollService`
- **Location**: `merid/event_venues/kalshi/bankroll_service.py:94`
- **Status**: DEPRECATED - Marked as deprecated in code
- **Warning**: Still has 40+ references across codebase

### References to Deprecated Service
**Problematic files still importing deprecated service**:
- `merid/event_venues/kalshi/bankroll_adapter.py`
- `merid/event_venues/kalshi/bankroll_resolver.py`
- `archive/legacy/agent_grid.py`
- `archive/legacy/crypto_15m_strategy.py`
- `archive/legacy/kalshi_continuous_trader.py`

---

## 5. Kalshi Clients (MAJOR DUPLICATION)

### Production Client
- **Class**: `KalshiClientV2`
- **Location**: `merid/event_venues/kalshi/client_v2.py:69`
- **Status**: PRODUCTION - Current canonical client

### Other Client Implementations
1. **KalshiVenueClient** - `merid/event_venues/kalshi/client.py:369` (older venue client)
2. **KalshiPublicDataClient** - `merid/event_venues/kalshi/client_public.py:40` (public data only)
3. **EnhancedKalshiClient** - `merid/event_venues/kalshi/client_enhanced.py` (enhanced version)
4. **RobustKalshiClient** - `merid/event_venues/kalshi/kalshi_robustness.py:52` (robustness wrapper)
5. **KalshiRestClient** - `merid/event_venues/kalshi/kalshi_rest_client.py:17` (REST wrapper)
6. **KalshiResponsibleTradingClient** - `merid/event_venues/kalshi/responsible_trading.py:71`

### Client Usage Analysis
**Production usage of KalshiClientV2**:
- `merid/event_venues/kalshi/bankroll_service_v2.py:141` - Bankroll service
- `merid/event_venues/kalshi/client.py:394` - Venue client wraps it

**Legacy usage of KalshiVenueClient**:
- `scripts/shadow_session.py:30`
- `scripts/kalshi_live_drift_monitor.py:28`
- `scripts/trace_one_market.py:23`
- `scripts/validate_contract_metadata.py:22`
- `scripts/validate_btc_wiring.py:24`
- `merid/event_venues/kalshi/portfolio_reconciliation.py:39`

---

## 6. Run Cycle Methods (CRITICAL)

### The Method You Edited
- **Class**: `LeanAgentGrid15m`
- **Method**: `run_cycle(tick: int, allow_new_entries: bool = True)`
- **Location**: `merid/prediction/agent_grid_15m.py:7123`
- **Status**: PRODUCTION - This is the method you added diagnostics to

### Other Run Cycle Implementations (13+ total)
1. `LeanAgentGrid15m.run_cycle` - `merid/prediction/agent_grid_15m.py:3781` (another overload?)
2. `Kalshi15mLoop` orchestrates cycles - `merid/loop_15m.py:378`
3. `CryptoBot.run_cycle` - `merid/event_venues/kalshi/crypto_bot.py:117`
4. `CryptoScheduler.run_cycle` - `merid/event_venues/kalshi/crypto_scheduler.py:47`
5. `Btc15mAgent.run_cycle` - `merid/agents/btc_15m_agent.py:103`
6. `AgentOrchestrator.run_cycle` - `merid/agents/orchestrator.py:189`
7. **LEGACY**: `AgentGrid.run_cycle` - `archive/legacy/agent_grid.py:1771`
8. **LEGACY**: `TradingAgent.run_cycle` - `archive/legacy/trading_agent.py:1222`
9. **LEGACY**: `CryptoTopEdge.run_cycle` - `archive/legacy/crypto_top_edge.py:566`
10. `KalshiOrchestrator.run_cycle` - `core/kalshi_orchestrator.py:67`
11. `Orchestrator.run_cycle` - `core/orchestrator.py:50`
12. `ContinuousTrader.run_cycle` - `scripts/kalshi_continuous_trader.py:846`
13. `DriftMonitor.run_cycle` - `scripts/kalshi_live_drift_monitor.py:319`

### CRITICAL ISSUE
**Multiple `run_cycle` methods in the same class**:
- `LeanAgentGrid15m` has TWO `run_cycle` methods at lines 3781 and 7123
- This suggests method overloading or a code merge issue

---

## 7. 15m Loop Entry Points

### Production Path
- **Class**: `Kalshi15mLoop`
- **Location**: `merid/loop_15m.py:378`
- **Singleton**: `get_kalshi_15m_loop()` at line 2923
- **Entrypoint**: `web/main_15m_lean.py:1261` (imports and creates Kalshi15mLoop)
- **Status**: PRODUCTION - Canonical 15m loop

### Startup Script
- **Script**: `start_15m.ps1`
- **Location**: Root of repo
- **Command**: `.\start_15m.ps1 -Port 8011 -Profile kalshi_crypto_15m_v2`

### Main Web Entrypoint
- **File**: `web/main_15m_lean.py`
- **Profile check**: Line 1682-1684 validates `kalshi_crypto_15m_v2`
- **Status**: PRODUCTION - FastAPI entrypoint

---

## 8. Signal Generation

### Multiple Signal Generator Classes
1. `SignalGenerator` - `ops/signal_generator.py:122`
2. `AISignalGenerator` - `ai_signals/signal_generator.py:106`
3. `TechnicalSignalGenerator` - `monitoring/intelligence_layer.py:312`
4. `SentimentSignalGenerator` - `core/sentiment_nlp.py:372`
5. `KalshiSignalGenerator` - `archive/legacy/kalshi_signals.py:299` (LEGACY)
6. `ConsensusGatedSignalGenerator` - `archive/legacy/kalshi_signals.py:535` (LEGACY)
7. `Btc15mSignalGenerator` - `config/kalshi_btc_15m_agent_spec.py:93`
8. `Sol15mSignalGenerator` - `config/kalshi_sol_15m_agent_spec.py:62`

### Agent Grid Signal Generation
- **Method**: `LeanAgentGrid15m._generate_signal`
- **Location**: `merid/prediction/agent_grid_15m.py:4885`
- **Status**: PRODUCTION - Used by agent grid

---

## 9. Order Routing

### Production Path
- **Function**: `route_order(intent: OrderIntent)` - `merid/event_venues/kalshi/order_router.py:4136`
- **Async**: `route_order_async(intent: OrderIntent)` - `merid/event_venues/kalshi/order_router.py:4843`
- **15m-specific**: `Kalshi15mOrderRouter` - `merid/event_venues/kalshi/order_router_15m.py:85`
- **Status**: PRODUCTION

### Alternative Router
- **Class**: `OrderRouter` - `execution/order_router.py:73`
- **Status**: Unknown - may be legacy or for other venues

---

## 10. Candidate Optimizer

### Production Path
- **Class**: `CandidateOptimizer`
- **Location**: `merid/prediction/candidate_optimizer.py:95`
- **Singleton**: `get_candidate_optimizer()` at line 801
- **Status**: PRODUCTION

---

## Classification Template

Add this header to each Python file to indicate its status:

```python
# PROFILE: kalshi_crypto_15m_v2-only
# STATUS: PRODUCTION
# ROLE: [description of role]
```

For legacy files:
```python
# PROFILE: NOT kalshi_crypto_15m_v2
# STATUS: LEGACY
# ROLE: [description of original role]
# WARNING: Do not import in kalshi_crypto_15m_v2 profile
```

For test files:
```python
# PROFILE: test-only
# STATUS: TEST
# ROLE: [description of what is being tested]
```

---

## Next Steps

1. **Phase 2**: Add runtime origin logging to detect which implementations are actually used
2. **Phase 3**: Verify sys.path and environment configuration
3. **Phase 4**: Add guardrails to prevent legacy imports in production
4. **Phase 5**: Canonicalize and remove duplicates

---

## Immediate Actions Required

1. **Investigate dual `run_cycle` methods in `LeanAgentGrid15m`** (lines 3781 and 7123)
2. **Audit all files importing from `merid.prediction.agent_grid`** (legacy) and convert to `agent_grid_15m`
3. **Remove or guard all references to `KalshiBankrollService`** (deprecated)
4. **Consolidate Kalshi client implementations** - determine which is canonical for v2
