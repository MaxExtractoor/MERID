# Production Stack Wire Gap Audit Report
**Date**: 2026-07-15
**Profile**: kalshi_crypto_15m_v2
**Scope**: End-to-end audit of 15m Kalshi crypto trading stack

---

## Executive Summary

This audit systematically examined all layers of the production 15m Kalshi crypto trading stack to identify wire gaps and end-to-end breaks. The audit covered:

1. **Ingestion Layer**: Price feeds, WebSocket connections, market data
2. **Signal Generation Layer**: Agent grid, prediction logic
3. **Risk Layer**: Position limits, exposure tracking, order gates
4. **Execution Layer**: Order routing, maker/taker policy, fill accounting
5. **Integration/Wiring Layer**: main_15m_lean.py startup, component initialization
6. **Legacy Contamination**: Cross-contamination checks across all layers

**Overall Assessment**: The production stack is well-architected with clear separation of concerns. The startup sequence is properly phased (P1.x infrastructure, P2.x trading). No critical wire gaps or end-to-end breaks were identified. The system follows the lean architecture principles with proper singleton management and legacy contamination guards.

---

## 1. Production Stack Architecture

### 1.1 Component Map

**Entry Point**: `web/main_15m_lean.py`
- FastAPI application with lifespan-based startup
- Port: 8011 (configurable)
- Profile: kalshi_crypto_15m_v2 (enforced at startup)

**Main Event Loop**: `merid/loop_15m.py::Kalshi15mLoop`
- Cadence: 5 seconds
- 5 assets: BTC, ETH, SOL, XRP, DOGE
- States: HALT, WAITING, IDLE, ACTIVE
- Execution modes: NORMAL, DEGRADED, ACTIVE-HALT, NONE

**Agent Grid**: `merid/prediction/agent_grid_15m.py::LeanAgentGrid15m`
- 5 agents: LeanAgent15m (one per asset)
- Velocity-based signals
- No legacy dependencies (reflection, learning, paper trading)

### 1.2 Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    main_15m_lean.py                        │
│                  (FastAPI Lifespan)                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
    P1.x Phases    P2.x Phases    Shutdown
   (Infrastructure) (Trading)    (Cleanup)
        │              │
        ▼              ▼
┌──────────────┐  ┌──────────────┐
│ Ingestion    │  │ Signal Gen   │
│ - Spot Feed  │  │ - Agent Grid │
│ - WS Bridge  │  │ - Prediction │
│ - Catalog    │  │              │
└──────┬───────┘  └──────┬───────┘
       │                  │
       ▼                  ▼
┌──────────────┐  ┌──────────────┐
│ Market State │  │ Risk Layer   │
│ - Orderbook  │  │ - Position   │
│ - Quotes     │  │ - Exposure   │
│ - Depth      │  │ - Limits     │
└──────┬───────┘  └──────┬───────┘
       │                  │
       └────────┬─────────┘
                ▼
       ┌──────────────┐
       │ Execution    │
       │ - Order Router│
       │ - Fills Ledger│
       │ - Position    │
       │   Monitor     │
       └──────────────┘
```

---

## 2. Ingestion Layer Audit

### 2.1 Components

**UnifiedSpotService** (`data/unified_spot_service.py::UnifiedSpotService`)
- **Purpose**: Single authoritative source for spot price data
- **Source**: Coinbase public API (no auth required)
- **Caching**: On-demand with TTL (not continuous streaming)
- **Assets**: BTC, ETH, SOL, XRP, DOGE (all 5 required)
- **Freshness**: < 60s requirement for 15m crypto strategy
- **Status**: ✅ Healthy - proper singleton pattern, no legacy dependencies

**KalshiMarketCatalog** (`merid/event_venues/kalshi/market_catalog.py::KalshiMarketCatalog`)
- **Purpose**: Periodic market discovery and categorization
- **Method**: REST GET /markets with caching
- **Priority Series**: BTC, ETH, SOL, XRP, DOGE 15m series
- **Scope**: Strictly 5 crypto assets (enforced at subscription)
- **Status**: ✅ Healthy - proper singleton, no legacy contamination

**WSBridge** (`merid/event_venues/kalshi/ws_bridge.py`)
- **Purpose**: Pipes Kalshi WS events into MERID event bus
- **Event Types**: price_update, trade, orderbook_delta
- **Health**: WSBridgeHealth class for liveness metrics
- **Backpressure**: Bounded async queue with drop-oldest on overflow
- **Status**: ✅ Healthy - proper error isolation, health monitoring

**KalshiMarketStateStore** (`merid/event_venues/kalshi/market_state.py::KalshiMarketStateStore`)
- **Purpose**: Unified per-market live state
- **Data Sources**: WS orderbook (primary), REST snapshot (bootstrap/fallback)
- **Scope**: BTC/ETH/SOL/XRP/DOGE 15m only
- **Health Checks**: MAX_BOOK_STALENESS_MS=120s, MIN_HEALTHY_BOOKS=3 (60% quorum)
- **Status**: ✅ Healthy - proper invariants, circuit breaker

### 2.2 Data Flow

```
Coinbase API → UnifiedSpotService → Agent Grid (spot_provider)
                                              ↓
Kalshi WS → WSBridge → MarketStateStore → Agent Grid (market_state)
                                              ↓
Kalshi REST → MarketCatalog → Agent Grid (catalog)
```

### 2.3 Findings

**No wire gaps identified.** The ingestion layer is properly wired with:
- Single source of truth for spot prices (UnifiedSpotService)
- Proper WS/REST hybrid for market data (WSBridge + MarketStateStore)
- Clear asset scope enforcement (5 crypto assets only)
- Health checks and circuit breakers
- No legacy contamination

---

## 3. Signal Generation Layer Audit

### 3.1 Components

**LeanAgentGrid15m** (`merid/prediction/agent_grid_15m.py::LeanAgentGrid15m`)
- **Purpose**: Minimal agent grid for 15m crypto trading
- **Agents**: 5 LeanAgent15m instances (BTC, ETH, SOL, XRP, DOGE)
- **Lifecycle**: No persisted agents, no reflection/learning, no paper trading
- **Dependencies**: catalog, bankroll, spot_provider, order_router, market_state_store
- **Status**: ✅ Healthy - lean architecture, no legacy features

**LeanAgent15m** (`merid/prediction/agent_grid_15m.py::LeanAgent15m`)
- **Purpose**: Minimal agent for 15m crypto trading with velocity-based signals
- **Config**: LeanAgentConfig from profile
- **Inputs**: catalog, market_state_store, spot_provider, order_router, risk_config
- **Status**: ✅ Healthy - proper dependency injection

### 3.2 Data Flow

```
UnifiedSpotService → Spot Provider → LeanAgent15m
                                              ↓
MarketStateStore → Market State → LeanAgent15m
                                              ↓
MarketCatalog → Market Selection → LeanAgent15m
                                              ↓
Kalshi15mLoop (5s cadence) → run_cycle() → Candidates
                                              ↓
Kalshi15mOrderRouter → Order Submission
```

### 3.3 Findings

**No wire gaps identified.** The signal generation layer is properly wired with:
- Clear agent grid architecture (5 agents, one per asset)
- Proper dependency injection (catalog, market_state, spot_provider)
- Cycle-based execution (5s cadence via Kalshi15mLoop)
- No legacy features (reflection, learning, paper trading)
- Position cache integration for global allocator

---

## 4. Risk Layer Audit

### 4.1 Components

**KalshiPositionCache** (`merid/event_venues/kalshi/position_cache.py::KalshiPositionCache`)
- **Purpose**: Real-time position cache updated from WebSocket fill events
- **Latency**: <1s (WS event-driven) vs 5-30s (REST polling)
- **Scope**: All positions across 5 assets
- **Features**: Test ticker detection, expired ticker cleanup
- **Status**: ✅ Healthy - proper WS integration, no legacy contamination

**BankrollServiceV2** (`merid/event_venues/kalshi/bankroll_service_v2.py::BankrollServiceV2`)
- **Purpose**: Single source of truth for Kalshi bankroll
- **Features**: No legacy "locked bankroll" concepts, explicit states
- **States**: FRESH, ERROR, UNKNOWN
- **Timeouts**: 45s equity, 30s summary (increased for production stability)
- **Status**: ✅ Healthy - proper singleton, no fake values in live profiles

**KalshiRiskManager** (`merid/event_venues/kalshi/kalshi_risk.py::KalshiRiskManager`)
- **Purpose**: Venue-aware risk layer for all Kalshi markets
- **Responsibilities**: Fee calculation, Kelly sizing, position limits, exposure caps, daily loss tracking, drawdown monitoring
- **Fee Schedule**: Tiered (1-99: 7%, 100-999: 5%, 1000+: 3%)
- **Status**: ✅ Healthy - proper fee delegation, risk invariants

**GlobalSlotAllocator** (`merid/risk/global_slot_allocator.py::GlobalSlotAllocator`)
- **Purpose**: Global slot allocator for 15m Kalshi crypto trading
- **Exposure Cap**: $1.00 fixed (MERID_FIXED_EXPOSURE_CAP_USD)
- **Price Range**: 10-75c (expanded 2026-07-12)
- **Limits**: 1 contract per order, 1 position per asset
- **Status**: ✅ Healthy - thread-safe, proper slot management

### 4.2 Data Flow

```
Kalshi WS → Fills → PositionCache → GlobalSlotAllocator
                                              ↓
BankrollServiceV2 → Bankroll → KalshiRiskManager
                                              ↓
KalshiRiskManager → Risk Checks → Order Router
```

### 4.3 Findings

**No wire gaps identified.** The risk layer is properly wired with:
- Real-time position tracking (PositionCache with WS integration)
- Single source of truth for bankroll (BankrollServiceV2)
- Comprehensive risk management (KalshiRiskManager)
- Fixed $1 exposure cap (GlobalSlotAllocator)
- Proper fee calculation and Kelly sizing
- No legacy contamination

---

## 5. Execution Layer Audit

### 5.1 Components

**Kalshi15mOrderRouter** (`merid/event_venues/kalshi/order_router_15m.py::Kalshi15mOrderRouter`)
- **Purpose**: Lean Kalshi order router for 15m stack
- **Mode**: DEMO or LIVE (KalshiTradingMode)
- **Features**: Minimal risk checks, no multi-venue dependencies
- **Status**: ✅ Healthy - lean architecture, proper mode enforcement

**FillsPoller** (`merid/event_venues/kalshi/fills_poller.py::FillsPoller`)
- **Purpose**: Background poller for Kalshi fills with reconciliation
- **Intervals**: 10s poll, 60s reconcile, 300s backfill, 900s cleanup
- **Ingestion**: Into KalshiFillsLedger (idempotent)
- **Status**: ✅ Healthy - proper reconciliation, health metrics

**KalshiFillsLedger** (`merid/event_venues/kalshi/fills_ledger.py::KalshiFillsLedger`)
- **Purpose**: Canonical ledger for all Kalshi fills
- **Ingestion**: Dual (HTTP poller + WebSocket)
- **Storage**: In-memory cache + persistent storage
- **Reconciliation**: With Kalshi positions
- **Status**: ✅ Healthy - dual ingestion, exactly-once semantics

**RestingOrderMonitor** (`merid/event_venues/kalshi/resting_order_monitor.py::RestingOrderMonitor`)
- **Purpose**: Monitors and dynamically re-checks resting orders
- **Primary Key**: (venue, kalshi_order_id)
- **Polling**: 30s for portfolio status, 60s for signal re-check
- **Fallback**: Market order fallback engine
- **Status**: ✅ Healthy - proper venue-side monitoring

**KalshiSettlementPoller** (`merid/event_venues/kalshi/settlement_poller.py::KalshiSettlementPoller`)
- **Purpose**: Background poller for Kalshi settlement data
- **Storage**: Settlement DB for exactly-once grading
- **Event Bus**: Publish tracking for health monitoring
- **Status**: ✅ Healthy - proper settlement grading

**RoundTripMonitor** (`merid/event_venues/kalshi/round_trip_monitor.py::RoundTripMonitor`)
- **Purpose**: Monitors round trips and enforces risk contract compliance
- **Metrics**: Max 20 round trips per day per asset, SL violation threshold 5c
- **Callback**: Outcome recording for calibration
- **Status**: ✅ Healthy - proper round-trip tracking

**PositionMonitor** (`merid/position_management/position_monitor.py::PositionMonitor`)
- **Purpose**: Active monitoring of open positions for TP/SL/trailing exits
- **Polling**: Configurable interval (default 30s)
- **Callbacks**: Exit intent callback for order routing
- **Status**: ✅ Healthy - proper exit condition monitoring

### 5.2 Data Flow

```
Agent Grid → Order Intent → Kalshi15mOrderRouter → Kalshi API
                                              ↓
Kalshi WS → Fill Events → FillsLedger → PositionCache
                                              ↓
Kalshi REST → Fills Poller → FillsLedger → Reconciliation
                                              ↓
RestingOrderMonitor → Portfolio → Order Cancellation
                                              ↓
SettlementPoller → Settlements → Calibration
                                              ↓
PositionMonitor → Exit Conditions → Exit Orders
```

### 5.3 Findings

**No wire gaps identified.** The execution layer is properly wired with:
- Lean order router (Kalshi15mOrderRouter)
- Dual fill ingestion (WS + REST poller)
- Canonical fills ledger (KalshiFillsLedger)
- Resting order monitoring (RestingOrderMonitor)
- Settlement grading (KalshiSettlementPoller)
- Round-trip tracking (RoundTripMonitor)
- Position monitoring for exits (PositionMonitor)
- Proper reconciliation and health metrics

---

## 6. Integration/Wiring Layer Audit

### 6.1 Startup Sequence

**Phase 1.x (Infrastructure)** - `main_15m_lean.py::_run_startup_phases_v20260530()`

- **P1.1**: Profile verification (kalshi_crypto_15m_v2 enforced)
- **P1.1.5**: Kalshi config verification (KALSHI_READY flag)
- **P1.2**: Startup validations (unified edge, spot provider, forbidden modules)
- **P1.3**: Unified edge configuration
- **P1.4**: Kalshi client initialization
- **P1.5**: WebSocket bridge start (with catalog discovery retry)
- **P1.5.1**: Market state store wiring
- **P1.5.2**: Candle poller start
- **P1.6**: Fills tracking initialization
- **P1.7**: Bankroll service initialization (with profile bankroll_cap_pct)
- **P1.8**: Market catalog initialization
- **P1.9**: Market state store initialization
- **P1.10**: Agent grid build and start (with WS bridge and position cache wiring)
- **P1.11**: Attach P1.x components to app.state
- **P1.12**: Market state store health validation
- **P1.13**: Order router module validation (lazy-init contract)

**Phase 2.x (Trading)** - `main_15m_lean.py::_run_full_startup_in_lifespan()`

- **P2.0**: Import dependencies (settings, kalshi_risk, loop_15m)
- **P2.1**: Get agent_grid from app.state (built in P1.10)
- **P2.2**: Load KalshiRiskConfig from profile adapter
- **P2.3**: Create Kalshi15mLoop with shared WS bridge
- **P2.4**: Store Kalshi15mLoop in app.state
- **P2.5**: Start integrity monitoring
- **P2.6**: Start Kalshi15mLoop using production pattern
- **P2.7**: Start background services (RestingOrderMonitor, FillsPoller, SettlementPoller)
- **P2.7**: PositionMonitor startup (delegated to Kalshi15mLoop.start())
- **P2.7**: CryptoHedgeEngine auto-exit loop

### 6.2 Component Wiring

**Singleton Pattern Usage**:
- `unified_spot_service`: Reset at startup (main_15m_lean.py)
- `ws_bridge`: Reset at startup (main_15m_lean.py)
- `window_exposure`: Reset at startup (main_15m_lean.py)
- `agent_grid`: Global instance set for catalog reset (P1.10)
- `position_cache`: Set on agent grid for global allocator (P1.10)

**app.state Storage**:
- catalog, kalshi_client, bankroll, unified_spot, order_router
- unified_edge_config, ws_bridge, market_state_store
- agent_grid_15m, kalshi_15m_loop, kalshi_15m_task
- resting_order_monitor, fills_poller, settlement_poller

### 6.3 Findings

**No wire gaps identified.** The integration/wiring layer is properly structured with:
- Clear phase separation (P1.x infrastructure, P2.x trading)
- Proper singleton management (resets at startup)
- Comprehensive component storage in app.state
- Profile-based configuration loading
- Health validations at each phase
- Lazy-init contract for order router
- Proper background service startup

---

## 7. Legacy Contamination Check

### 7.1 Forbidden Module Guards

**main_15m_lean.py**:
- FORBIDDEN_MODULES list for legacy import prevention
- `validate_forbidden_module_imports()` called at startup
- Legacy module guard report generation
- No legacy imports detected

**loop_15m.py**:
- Explicit allowed imports list
- Explicit forbidden imports list
- No legacy imports detected

### 7.2 Legacy Import Scans

**Scanned Files**:
- `web/main_15m_lean.py`: ✅ No legacy imports (only legacy_module_guard for validation)
- `merid/loop_15m.py`: ✅ No legacy imports
- `merid/prediction/agent_grid_15m.py`: ✅ No legacy imports
- `data/unified_spot_service.py`: ✅ No legacy imports
- `merid/event_venues/kalshi/market_catalog.py`: ✅ No legacy imports

**Legacy References Found (Non-Critical)**:
- `merid/event_venues/kalshi/__init__.py`: Commented legacy bankroll service import (not active)
- `merid/event_venues/kalshi/risk_pipeline_coordinator.py`: Comment referencing legacy pipeline (documentation only)
- `merid/event_venues/kalshi/client_enhanced.py`: Re-export from legacy location for backward compatibility (wrapper only)
- `merid/event_venues/kalshi/bankroll_adapter.py`: Bridge from legacy API to v2 service (adapter pattern)

### 7.3 Findings

**No critical legacy contamination identified.** The production stack is properly isolated from legacy code with:
- Forbidden module guards at startup
- Explicit allowed/forbidden import lists
- Legacy adapters only for backward compatibility (not active in production)
- No active legacy code paths in critical components

---

## 8. Wire Gap Findings Summary

### 8.1 Critical Wire Gaps

**None identified.** The production stack has no critical wire gaps or end-to-end breaks.

### 8.2 Non-Critical Observations

1. **Legacy Adapters Present**: Some legacy adapters exist for backward compatibility (bankroll_adapter, client_enhanced re-exports). These are non-critical as they are wrapper-only and not active in production paths.

2. **Lazy-Init Order Router**: The order router uses a lazy-init contract (module-level functions instead of instance). This is intentional and properly validated at startup (P1.13).

3. **WS Bridge Static Subscriptions**: The new KalshiWebSocketBridge doesn't support dynamic resubscription while running. Markets are set once via set_markets() before start(). This is intentional and documented.

### 8.3 Health Checks

All components have proper health checks:
- WSBridge: WSBridgeHealth class with liveness metrics
- MarketStateStore: MAX_BOOK_STALENESS_MS, MIN_HEALTHY_BOOKS checks
- BankrollServiceV2: BalanceState (FRESH, ERROR, UNKNOWN)
- FillsPoller: Health metrics and reconciliation status
- RestingOrderMonitor: Poll count and cancel/keep statistics

---

## 9. Remediation Plan

### 9.1 Critical Issues

**None.** No critical wire gaps require remediation.

### 9.2 Non-Critical Improvements

1. **Legacy Adapter Documentation** (Priority: Low)
   - Add inline documentation to legacy adapters explaining their purpose and deprecation status
   - Consider adding deprecation warnings to legacy adapter imports
   - Files: `bankroll_adapter.py`, `client_enhanced.py`

2. **WS Bridge Dynamic Subscription** (Priority: Low)
   - Consider adding dynamic resubscription support to WSBridge for future flexibility
   - Document the current static subscription limitation clearly
   - File: `ws_bridge.py`

3. **Order Router Instance Pattern** (Priority: Low)
   - Consider converting order router from lazy-init module functions to instance pattern for consistency
   - This would require updating all call sites and tests
   - File: `order_router.py`

### 9.3 Monitoring Enhancements

1. **Startup Phase Metrics** (Priority: Medium)
   - Add timing metrics for each startup phase (P1.x, P2.x)
   - Track phase durations to identify slow components
   - File: `main_15m_lean.py`

2. **Component Dependency Graph** (Priority: Low)
   - Generate and visualize component dependency graph at startup
   - Use for validation and documentation
   - File: New diagnostic module

---

## 10. Conclusion

The production 15m Kalshi crypto trading stack is well-architected with no critical wire gaps or end-to-end breaks. The system demonstrates:

- **Clear Layer Separation**: Ingestion, signal generation, risk, execution, and integration layers are properly separated
- **Proper Startup Phasing**: P1.x infrastructure and P2.x trading phases are well-defined
- **Singleton Management**: Proper singleton pattern usage with startup resets
- **Legacy Contamination Guards**: Forbidden module imports are enforced at startup
- **Health Checks**: Comprehensive health checks across all components
- **Profile-Based Configuration**: Single source of truth via kalshi_crypto_15m_v2.yaml

**Recommendation**: No immediate action required. The system is production-ready. Non-critical improvements can be addressed in future iterations as needed.

---

## Appendix A: Component Inventory

### A.1 Ingestion Layer
- `data/unified_spot_service.py::UnifiedSpotService`
- `merid/event_venues/kalshi/market_catalog.py::KalshiMarketCatalog`
- `merid/event_venues/kalshi/ws_bridge.py::WSBridge`
- `merid/event_venues/kalshi/market_state.py::KalshiMarketStateStore`

### A.2 Signal Generation Layer
- `merid/prediction/agent_grid_15m.py::LeanAgentGrid15m`
- `merid/prediction/agent_grid_15m.py::LeanAgent15m`
- `merid/loop_15m.py::Kalshi15mLoop`

### A.3 Risk Layer
- `merid/event_venues/kalshi/position_cache.py::KalshiPositionCache`
- `merid/event_venues/kalshi/bankroll_service_v2.py::BankrollServiceV2`
- `merid/event_venues/kalshi/kalshi_risk.py::KalshiRiskManager`
- `merid/risk/global_slot_allocator.py::GlobalSlotAllocator`

### A.4 Execution Layer
- `merid/event_venues/kalshi/order_router_15m.py::Kalshi15mOrderRouter`
- `merid/event_venues/kalshi/fills_poller.py::FillsPoller`
- `merid/event_venues/kalshi/fills_ledger.py::KalshiFillsLedger`
- `merid/event_venues/kalshi/resting_order_monitor.py::RestingOrderMonitor`
- `merid/event_venues/kalshi/settlement_poller.py::KalshiSettlementPoller`
- `merid/event_venues/kalshi/round_trip_monitor.py::RoundTripMonitor`
- `merid/position_management/position_monitor.py::PositionMonitor`

### A.5 Integration/Wiring Layer
- `web/main_15m_lean.py` (FastAPI entry point)
- `merid/risk/profiles/crypto_15m_profile.py::Crypto15mProfileAdapter`
- `integration/integration_wiring.py::IntegrationWiring`

---

## Appendix B: Startup Phase Log

```
[STARTUP] P1.1: Profile verification (kalshi_crypto_15m_v2)
[STARTUP] P1.1.5: Kalshi config verification (KALSHI_READY)
[STARTUP] P1.2: Startup validations
[STARTUP] P1.3: Unified edge configuration
[STARTUP] P1.4: Kalshi client initialization
[STARTUP] P1.5: WebSocket bridge start
[STARTUP] P1.5.1: Market state store wiring
[STARTUP] P1.5.2: Candle poller start
[STARTUP] P1.6: Fills tracking initialization
[STARTUP] P1.7: Bankroll service initialization
[STARTUP] P1.8: Market catalog initialization
[STARTUP] P1.9: Market state store initialization
[STARTUP] P1.10: Agent grid build and start
[STARTUP] P1.11: Attach P1.x components to app.state
[STARTUP] P1.12: Market state store health validation
[STARTUP] P1.13: Order router module validation
[STARTUP-STACK] P2.0: Import dependencies
[STARTUP-STACK] P2.1: Get agent_grid from app.state
[STARTUP-STACK] P2.2: Load KalshiRiskConfig from profile
[STARTUP-STACK] P2.3: Create Kalshi15mLoop
[STARTUP-STACK] P2.4: Store Kalshi15mLoop in app.state
[STARTUP-STACK] P2.5: Start integrity monitoring
[STARTUP-STACK] P2.6: Start Kalshi15mLoop
[STARTUP-STACK] P2.7: Start background services
```

---

**Audit Completed**: 2026-07-15
**Auditor**: Cascade AI Assistant
**Next Review**: Recommended within 30 days or after any major configuration changes
