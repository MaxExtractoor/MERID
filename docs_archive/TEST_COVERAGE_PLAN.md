# MERID Test Coverage Enhancement Plan

## 1) Module Classification & Coverage Targets

### Tier 1: Runtime-Critical (Target: ≥95-100%)
| Module | Lines | Current | Target | Priority |
|--------|-------|---------|--------|----------|
| **trading/execution.py** | 525 | 44% | 95% | Critical - Core engine |
| **trading/guards/trading_guard.py** | 247 | 98% | 100% | ✅ Near target |
| **trading/execution/defense.py** | 419 | 93% | 100% | ✅ Near target |
| **trading/execution/optimal.py** | 321 | 96% | 100% | ✅ Near target |
| **trading/execution_engine.py** | 214 | 94% | 100% | ✅ Near target |
| **merid/event_venues/base.py** | 185 | 86% | 100% | High - Abstract contracts |
| **merid/event_venues/kalshi/client.py** | 242 | 21% | 95% | Critical - Gateway |
| **merid/event_venues/kalshi/ws.py** | 110 | 36% | 95% | Critical - Gateway |
| **merid/event_venues/polymarket/client.py** | 194 | 23% | 95% | Critical - Gateway |
| **merid/event_venues/polymarket/ws.py** | 106 | 37% | 95% | Critical - Gateway |
| **trading/merid_adapter.py** | 190 | 51% | 95% | Critical - Gateway/Translation |
| **trading/router.py** | 25 | 88% | 100% | Critical - Trust boundary |
| **trading/polymarket_trading_layer.py** | 104 | 67% | 95% | High |
| **core/persistence_manager.py** | ~200 | ~60% | 95% | High |
| **core/state.py** | ~300 | ~70% | 95% | High |
| **core/error_handling.py** | ~400 | ~40% | 95% | High |

### Tier 2: Important (Target: ≥80-90%)

| Module | Lines | Current | Target | Priority |
|--------|-------|---------|--------|----------|
| **trading/spectator.py** | 46 | 91% | 95% | ✅ Near target |
| **core/agent_orchestrator.py** | ~400 | 69% | 90% | Medium |
| **core/cache_manager.py** | ~150 | ~50% | 85% | Medium |
| **core/observability_manager.py** | ~200 | ~30% | 85% | Medium |
| **core/health_monitoring.py** | ~200 | ~40% | 85% | Medium |
| **core/telemetry_manager.py** | ~150 | ~30% | 85% | Medium |
| **core/x402_payments.py** | 153 | 50% | 85% | Medium |
| **trading/paper_trading.py** | 343 | 77% | 90% | Medium |

### Tier 3: Experimental/Legacy (Best Effort)

| Module | Lines | Current | Decision |
|--------|-------|---------|----------|
| phase0_* | ~5000 | 0-10% | Exclude - Legacy code |
| drift_monitor*.py | ~800 | 0-20% | Exclude - Experimental |
| social_sentiment/ | ~1000 | 0-10% | Exclude - Experimental |
| memecoin_safety/ | ~500 | 0-10% | Exclude - Experimental |
| treasury/ | ~2000 | 0% | Exclude - Not in active use |
| wallet/ | ~1000 | 0% | Exclude - Not in active use |
| training/*.py | ~2000 | 0-20% | Exclude - ML pipeline |

**Note:** For Tier 3 modules, explicitly add `# pragma: no cover` to dead/legacy paths to keep coverage denominator honest and avoid incentivizing meaningless tests.

---

## 2) Batching Strategy

### Batch A: Event Venues & Adapters (Current)

**Modules:**

- `merid/event_venues/base.py` (86% → 100%)
- `merid/event_venues/kalshi/client.py` (21% → 95%)
- `merid/event_venues/kalshi/trading.py` (41% → 95%)
- `merid/event_venues/kalshi/ws.py` (36% → 95%)
- `merid/event_venues/polymarket/client.py` (23% → 95%)
- `merid/event_venues/polymarket/trading.py` (98% → 100%)
- `merid/event_venues/polymarket/ws.py` (37% → 95%)
- `trading/merid_adapter.py` (51% → 95%)
- `trading/polymarket_trading_layer.py` (67% → 95%)
- `trading/router.py` (88% → 100%)

**Test Types:** Unit tests with mocked HTTP/WebSocket clients
**Estimated New Tests:** ~80-100 tests

### Batch B: Orchestration & Agents

**Modules:**

- `core/agent_orchestrator.py` (69% → 90%)
- `core/system_orchestrator.py` (~50% → 90%)
- `trading/agents/execution_agent.py` (27% → 90%)
- `trading/agents/arbitrage_agent.py` (72% → 95%)
- `trading/agents/bookie_agent.py` (99% → 100%)
- `trading/agents/slippage_agent.py` (98% → 100%)

**Test Types:** Unit + property-based (Hypothesis)
**Estimated New Tests:** ~60-80 tests

### Batch C: Core Safety & State

**Modules:**

- `core/error_handling.py` (~40% → 95%)
- `core/persistence_manager.py` (~60% → 95%)
- `core/state.py` (~70% → 95%)
- `core/state_recovery.py` (~50% → 90%)
- `core/cache_manager.py` (~50% → 85%)
- `core/tracing.py` (~40% → 85%)

**Test Types:** Unit + integration with mocked I/O
**Estimated New Tests:** ~50-70 tests

### Batch D: Health, Telemetry & Dashboards

**Modules:**

- `core/health_monitoring.py` (~40% → 85%)
- `core/health_dashboard.py` (~30% → 85%)
- `core/telemetry_manager.py` (~30% → 85%)
- `core/merid_dashboard.py` (~20% → 85%)
- `core/merid_metrics.py` (~30% → 85%)
- `core/observability_manager.py` (~30% → 85%)

**Test Types:** Unit + lightweight integration
**Estimated New Tests:** ~40-60 tests

### Batch E: Remaining Tier 2

**Modules:**

- `core/x402_payments.py` (50% → 85%)
- `core/xstocks_adapters.py` (59% → 85%)
- `core/validation/*.py` (38-93% → 90%)
- `trading/paper_trading.py` (77% → 90%)

**Test Types:** Unit tests
**Estimated New Tests:** ~30-50 tests

---

## 3) Batch A Implementation (In Progress)

See generated test files in:

- `tests/merid/event_venues/test_base_batch_a.py`
- `tests/merid/event_venues/kalshi/test_client_batch_a.py`
- `tests/merid/event_venues/kalshi/test_ws_batch_a.py`
- `tests/merid/event_venues/polymarket/test_client_batch_a.py`
- `tests/merid/event_venues/polymarket/test_ws_batch_a.py`
- `tests/trading/test_merid_adapter_batch_a.py`
- `tests/trading/test_polymarket_trading_layer_batch_a.py`
- `tests/trading/test_router_batch_a.py`
