# Production Stack Architecture - 15m Kalshi Crypto Trading System

## Overview

This document describes the production stack for the 15-minute Kalshi crypto trading system. The production stack is designed to be isolated from legacy code paths to ensure reliable operation.

## Critical Assets

The production stack supports exactly 5 crypto assets:
- **BTC/USD** - Bitcoin
- **ETH/USD** - Ethereum
- **SOL/USD** - Solana
- **XRP/USD** - Ripple
- **DOGE/USD** - Dogecoin

**IMPORTANT**: All 5 assets must always be included. Never skip, comment out, or disable any of these assets.

## Production Components

### Entry Point
- **Script**: `start_15m.ps1`
- **Command**: `.\start_15m.ps1 -Port 8011 -Profile kalshi_crypto_15m_v2`
- **Application**: `web/main_15m_lean:app`

### Core Modules

#### Agent Grid
- **Production**: `merid/prediction/agent_grid_15m.py` (LeanAgentGrid15m)
- **Singleton**: `get_agent_grid()` returns LeanAgentGrid15m
- **Legacy**: `archive/legacy/agent_grid.py` (DEPRECATED - raises RuntimeError if imported in production profile)

#### Loop
- **Production**: `merid/loop_15m.py`
- **Function**: `get_merid_loop_15m()`
- **Legacy**: `merid/loop.py` (not used by 15m stack)

#### Configuration
- **Production Profile**: `config/profiles/kalshi_crypto_15m_v2.yaml`
- **Profile Resolver**: `merid/profile_resolver.py` (checks MERID_PROFILE env var)
- **Legacy Config**: `config/kalshi_agent_grid.yaml` (DEPRECATED - still used by agent_grid_15m for compatibility)

#### Market Catalog
- **Production**: `merid/event_venues/kalshi/market_catalog.py` (KalshiMarketCatalog)
- **Singleton**: `get_market_catalog()`
- **No legacy version exists**

#### Market State Store
- **Production**: `merid/event_venues/kalshi/market_state.py`
- **Singleton**: `get_kalshi_market_state_store()`
- **No legacy version exists**

#### WebSocket Bridge
- **Production**: `merid/event_venues/kalshi/crypto_catalog.py` (CryptoWsBridgePrep)
- **Function**: `prepare_crypto_ws_bridge_subscription()`
- **No legacy version exists**

#### Order Routing
- **Production**: `merid/event_venues/kalshi/order_router.py` (KalshiOrderRouter)
- **Function**: `route_order_async()`
- **No legacy version exists**

#### Risk Enforcement
- **Production**: `merid/event_venues/kalshi/kalshi_risk.py` (KalshiRiskConfig)
- **Function**: `get_kalshi_risk()`
- **Profile**: `merid/risk/profiles/crypto_15m_profile.py` (Crypto15mProfileAdapter)
- **No legacy version exists**

#### Kalshi Client
- **Production**: `merid/event_venues/kalshi/client.py` (KalshiVenueClient)
- **Singleton**: `get_kalshi_client()`
- **No legacy version exists**

#### RTI Monitor
- **Production**: `merid/risk/crypto_rti_monitor.py`
- **Function**: `get_global_crypto_rti_monitor()`
- **No legacy version exists**

#### Signal Generation
- **Production**: Integrated into LeanAgent15m within agent_grid_15m.py
- **No separate legacy version exists**

### Supporting Components (Shared)

These components are used by both production and legacy stacks:
- **Candidate Optimizer**: `merid/prediction/candidate_optimizer.py`
- **Spot Provider**: `merid/prediction/spot_provider.py`
- **Bankroll Service**: Integrated into risk profile system
- **Position Tracking**: Integrated into trading modules
- **Execution Subscriber**: `merid/swarm/execution_subscriber.py` (updated to use production agent grid)

### Startup Sequence

The production startup sequence is defined in `web/main_15m_lean.py`:
1. **Lifespan Context**: FastAPI lifespan manages startup/shutdown
2. **Profile Guard**: Validates MERID_PROFILE is `kalshi_crypto_15m_v2`
3. **Phase 1**: Initialize infrastructure (logging, config, clients)
4. **Phase 2**: Build and start LeanAgentGrid15m
5. **Phase 3**: Start WebSocket subscriptions
6. **Phase 4**: Start loop_15m execution

### Health Diagnostics

Health checks are defined in `web/api/health.py`:
- **Kill Switch**: ExecutionGuard status
- **Kalshi Circuit**: Circuit breaker status
- **Merid Loop**: loop_15m liveness
- **Agent Grid**: LeanAgentGrid15m readiness
- **Fills Ledger**: Circuit breaker and DLQ status
- **Event Loop Lag**: Diagnostic profiling

All health checks use production components.

## Legacy Code

### Archive Location
- **Directory**: `archive/legacy/`
- **README**: `archive/legacy/README.md` (documents deprecation)

### Legacy Agent Grid
- **File**: `archive/legacy/agent_grid.py`
- **Protection**: Raises RuntimeError if imported in `kalshi_crypto_15m_v2` profile
- **Purpose**: Historical reference and regression testing

### Legacy Config Loader
- **File**: `merid/prediction/agent_grid_config.py`
- **Status**: DEPRECATED warning in docstring
- **Usage**: Still used by agent_grid_15m for compatibility (requires future refactoring)

## Known Contamination Points

### Configuration Loading
The production `build_15m_agent_grid()` still uses `load_agent_grid_config()` which loads the deprecated `config/kalshi_agent_grid.yaml`. This is a compatibility shim that requires future refactoring to use the production profile directly.

### Test Files
Some test files import legacy AgentGrid for regression testing. This is intentional and acceptable for testing purposes.

## Migration Path

### Completed
- ✅ All production code paths use production components
- ✅ Legacy agent grid has runtime guard
- ✅ Archive directory marked as deprecated
- ✅ Deprecation warnings added to legacy config loader
- ✅ Health diagnostics use production stack

### Future Work
- ⏳ Refactor agent_grid_15m to use production profile directly instead of legacy config loader
- ⏳ Remove config/kalshi_agent_grid.yaml after refactoring
- ⏳ Add integration tests for production stack isolation
- ⏳ Add runtime checks to detect legacy contamination

## Verification

To verify the production stack is running correctly:

1. **Check Profile**: Ensure `MERID_PROFILE=kalshi_crypto_15m_v2`
2. **Check Entry Point**: Ensure using `web/main_15m_lean:app`
3. **Check Agent Grid**: Verify `get_agent_grid()` returns LeanAgentGrid15m
4. **Check Loop**: Verify using `loop_15m.py` not `merid/loop.py`
5. **Check Health**: All health checks should pass
6. **Check Assets**: All 5 assets (BTC, ETH, SOL, XRP, DOGE) should be active

## Startup Command

```powershell
CD C:\Dev\MERID
.\start_15m.ps1 -Port 8011 -Profile kalshi_crypto_15m_v2
```

## Contact

For questions about the production stack architecture, refer to:
- This document
- `archive/legacy/README.md` for legacy code status
- `config/profiles/kalshi_crypto_15m_v2.yaml` for production configuration
