# Kalshi 15m Profile Contract

**Profile**: `kalshi_crypto_15m_v2`
**Entrypoint**: `web.main_15m:app`
**Loop**: `merid.loop_15m.Kalshi15mLoop`
**Effective Date**: 2026-05-15

---

## Purpose

This contract defines the sealed product surface for the Kalshi 15-minute crypto trading profile. Only the minimal core services + 5 agents + trading/risk are allowed to affect this profile. Everything else must be profile-guarded off or made read-only/telemetry.

---

## Allowed Modules (Core 15m Stack)

### Core Infrastructure
- **`utils.logger`** - Logging
- **`core.redis_client`** - Redis connection (optional, non-fatal if unavailable)
- **`merid.guards.global_risk_guard`** - Global risk limit enforcement

### Kalshi Venue Services
- **`merid.event_venues.kalshi.client`** - Kalshi API client
- **`merid.event_venues.kalshi.bankroll`** - Bankroll service for balance tracking
- **`merid.event_venues.kalshi.market_catalog`** - Market catalog with 5 allowed series
- **`merid.event_venues.kalshi.market_state`** - Market state store (KalshiMarketState)
- **`merid.event_venues.kalshi.ws_bridge`** - WebSocket bridge for real-time data
- **`merid.event_venues.kalshi.fills_poller`** - Fills polling service
- **`merid.event_venues.kalshi.settlement_poller`** - Settlement polling service
- **`merid.event_venues.kalshi.rti_feed_service`** - RTI feed service
- **`merid.event_venues.kalshi.venue_adapter`** - Venue adapter for order routing
- **`merid.event_venues.kalshi.kalshi_risk`** - KalshiRiskConfig (venue config, canonical)
- **`merid.term_structure`** - Crypto term structure model

### Agent System
- **`merid.prediction.agent_grid_config`** - Agent grid configuration loader
- **`merid.prediction.agent_grid`** - AgentGrid with `run_cycle()` method (NOT `start()`)
- **`merid.loop_15m`** - Kalshi15mLoop (5-second cadence, drives agent cycles)

### Allowed Agents (Exactly 5)
- **`BTC_15M`** - Bitcoin 15-minute agent
- **`ETH_15M`** - Ethereum 15-minute agent
- **`SOL_15M`** - Solana 15-minute agent
- **`XRP_15M`** - Ripple 15-minute agent
- **`DOGE_15M`** - Dogecoin 15-minute agent

### Allowed Series Tickers (Exactly 5)
- **`KXBTC15M`** - Bitcoin 15-minute series
- **`KXETH15M`** - Ethereum 15-minute series
- **`KXSOL15M`** - Solana 15-minute series
- **`KXXRP15M`** - Ripple 15-minute series
- **`KXDOGE15M`** - Dogecoin 15-minute series

### Configuration Files (Single Source of Truth)
- **`config/profiles/kalshi_crypto_15m.yaml`** - Profile configuration (risk envelope, bankroll, assets)
- **`config/kalshi_agent_grid.yaml`** - Agent grid configuration (5 agents, series_tickers)
- **`config/kalshi_universe.py`** - KALSHI_CRYPTO_PRODUCTS dictionary (series ticker mapping)

### API Endpoints (web.main_15m - Read-Only Telemetry)
- **`GET /`** - Root endpoint (basic info)
- **`GET /health`** - Health check (loop summary, services status)
- **`GET /status`** - Detailed status (agents, services, loop summary)

**Note**: All endpoints are GET requests (read-only). No POST/PUT/DELETE/PATCH endpoints exist.

---

## Forbidden Modules (Cross-Product Hooks)

### Orchestrator
- **`core.systemorchestrator`** - Legacy orchestrator
- **`core.agent_orchestrator`** - Agent orchestrator (legacy)
- **`merid.pipelines.orchestrator`** - Pipeline orchestrator
- **`merid.pipelines.execution_pipeline`** - Execution pipeline orchestrator

### Governance
- **`merid.core.merid_governance_cadence`** - Governance cadence
- **`governance.*`** - All governance modules

### Treasury
- **`merid.treasury.*`** - All treasury modules
- **`portfolio.*`** - Portfolio management (cross-asset)

### Graph Memory
- **`memory.neo4j_graph`** - Neo4j graph memory
- **`memory.federated_memory_bus`** - Federated memory bus
- **`memory.long_term_knowledge_base`** - Long-term knowledge base

### Macro Overlay
- **`merid.macro_overlay.*`** - Macro overlay modules

### Cross-Sectional PM Metrics
- **`merid.prediction.pm_profiles`** - PM profile manager (sentiment override logic only)
- **`merid.prediction.pm_crypto_ops`** - PM crypto operations
- **`merid.prediction.pm_agent_cycle_execution_path`** - PM agent cycle execution

### Legacy Lane Orchestration
- **`merid.lanes.*`** - Lane orchestration (except Crypto15MLane via registry)
- **`merid.swarm.emergent_behavior_safeguards`** - Emergent behavior safeguards

### Reflection/Learning Systems
- **`merid.agents.reflection.*`** - Reflection agents
- **`merid.prediction.reflection.*`** - Prediction reflection
- **`merid.swarm.adversarial_robustness`** - Adversarial robustness
- **`merid.swarm.agent_benchmarking`** - Agent benchmarking

### Agent Mesh
- **`merid.agents.polymarket.*`** - Polymarket agents
- **`merid.agents.core.mesh.*`** - Agent mesh
- **`merid.agents.core.regime.*`** - Regime agents
- **`merid.agents.core.intelligence.*`** - Intelligence agents
- **`merid.agents.core.news.*`** - News agents
- **`merid.agents.core.sentiment.*`** - Sentiment agents

### KalshiContinuousTrader (Legacy/Research)
- **`merid.trading.kalshi_continuous_trader`** - Continuous trader (legacy/research-only)

### PM Agents
- **`merid.prediction.agent.pm_*`** - PM-specific agents

### Regime Agents
- **`merid.prediction.agent.regime_*`** - Regime-specific agents

---

## Profile Guards (Must Be Enforced)

### Existing Guards (Verified in Code)
- **`web/startup_agents.py`**:
  - Skip insight pipeline for `kalshi_crypto_15m_v2` (line 138)
  - Skip AgentMesh for `kalshi_crypto_15m_v2` (line 161)
  - Skip social broadcaster for `kalshi_crypto_15m_v2` (line 182)
  - Skip reflection system for `kalshi_crypto_15m_v2` (line 194)

- **`web/main.py`**:
  - Skip Kalshi Agent Grid startup for non-15m profiles (line 2636)
  - Skip reflection layer for `kalshi_crypto_15m_v2` (line 2978)
  - Skip core.agent_orchestrator for `kalshi_crypto_15m_v2` (line 3998)
  - Skip agent mesh for `kalshi_crypto_15m_v2` (line 4110)

### Required Guards (To Be Added)
- **`strategy_dashboard.py`**: Skip when `MERID_PROFILE=kalshi_crypto_15m_v2`
- **`services/crypto_surface_loader.py`**: Skip when `MERID_PROFILE=kalshi_crypto_15m_v2`
- **`scripts/analyze_entry_window.py`**: Skip when `MERID_PROFILE=kalshi_crypto_15m_v2`
- **`web/api/kalshi_api.py`**: Add 403 for `decide_btc_15m_endpoint` when profile is `kalshi_crypto_15m_v2`
- **`web/api/kalshi_grid_api.py`**: Add 403 for btc_15m endpoints when profile is `kalshi_crypto_15m_v2`
- **`web/api/kalshi_paper_portfolio_api.py`**: Add 403 for crypto_agents endpoints when profile is `kalshi_crypto_15m_v2`

---

## UI/UX Contract (Read-Only Telemetry)

### Allowed UI Behaviors
- **Read-only telemetry display**: UI can display 15m agent performance, market state, positions, P&L
- **Read-only configuration display**: UI can display risk caps, strategy parameters, allowed assets
- **Real-time updates**: UI can receive WebSocket updates for market state and agent activity

### Forbidden UI Behaviors
- **Mutation of risk caps**: UI cannot change max position, max notional, or stop-loss settings
- **Mutation of strategy parameters**: UI cannot change edge thresholds, conviction levels, or entry windows
- **Mutation of asset lists**: UI cannot add or remove assets from the 5 allowed 15m assets
- **Mutation of profile settings**: UI cannot change profile configuration or enable/disable agents
- **Manual order placement**: UI cannot manually place orders for 15m profile (only auto-trading allowed)

### UI Components (Current State)
- **`web/react/src/constants/api.ts`**: BTC_15M endpoint (read-only, safe)
- **`web/react/src/components/KalshiPaperVsShadowPanel.tsx`**: btc_15m_regime display (read-only, safe)

**Note**: React/JS files do NOT reference `kalshi_crypto_15m_v2` directly. UI components are read-only and safe.

---

## Configuration Contract

### Single Source of Truth
- **`config/profiles/kalshi_crypto_15m.yaml`** is the ONLY source for:
  - Risk envelope (max position, max notional, stop-loss)
  - Bankroll configuration
  - Asset list (BTC, ETH, SOL, XRP, DOGE)
  - Timeframe (15m)
  - Trading mode (paper/live)

### Deprecated Configuration Files
- **`config/kalshi_15m_crypto_config.py`**: Superseded by profile YAML (add deprecation warning)
- **`merid/prediction/risk/kalshi_risk_engine.py`**: Superseded by venue config (add deprecation warning)

### Risk Config
- **Venue config is canonical**: `merid.event_venues.kalshi.kalshi_risk.KalshiRiskConfig`
- **PM config is deprecated**: `merid.prediction.risk.kalshi_risk_engine.KalshiRiskConfig` (test-only)

---

## Test Contract

### Required Tests
- **`tests/test_kalshi_15m_entrypoint.py`**: Regression tests for new entrypoint
  - Profile validation (rejects non-15m profiles)
  - No legacy imports (orchestrator, governance, treasury, reflection, mesh)
  - AgentGrid loads exactly 5 agents
  - Kalshi15mLoop instantiation and cycling
  - Risk envelope YAML exists

- **`tests/test_kalshi_15m_constants.py`**: Market allowlist and risk caps tests (to be created)
  - Assert exactly 5 15m series tickers are allowed
  - Assert risk caps match profile YAML values
  - Assert no other series tickers are referenced in production code without guards

### Test-Only Modules (Safe)
- All test files referencing 15m assets are safe (test isolation)
- Research sentiment tests are marked as research-only for this profile

---

## Deployment Contract

### Entrypoint Selection
- **`kalshi_crypto_15m_v2` profile** → `web.main_15m:app` (new thin entrypoint)
- **All other profiles** → `web.main:app` (legacy entrypoint)

### Startup Scripts
- **`start.bat`**: Profile-based entrypoint selection (Windows)
- **`start.sh`**: Profile-based entrypoint selection (Unix)

### Environment Variables (Required for 15m Profile)
- **`MERID_PROFILE=kalshi_crypto_15m_v2`** (required)
- **`KALSHI_BASE_URL`** (required)
- **`KALSHI_EMAIL`** (required)
- **`KALSHI_PASSWORD`** (required)
- **`KALSHI_API_KEY_ID`** (required)
- **`KALSHI_API_KEY_SECRET`** (required)

### Optional Environment Variables
- **`REDIS_URL`** (optional, non-fatal if unavailable)
- **`MERID_15M_DOCS`** (default: "1", set to "0" to disable /docs and /redoc)

---

## Violation Handling

### Contract Violations
If any forbidden module is imported or any forbidden behavior is detected in the 15m profile:
1. **Startup validation** should fail with clear error message
2. **Runtime guards** should skip or disable the component with warning
3. **Tests** should fail if violations are introduced

### Enforcement Mechanisms
1. **Profile validation** in `web.main_15m` startup (rejects non-15m profiles)
2. **Profile guards** in legacy code (skip when profile is 15m)
3. **Import validation** in tests (assert no forbidden imports)
4. **Runtime validation** in startup_validations.py

---

## Change Control

### Contract Changes
Any changes to this contract must:
1. Be documented with justification
2. Update the audit compilation document
3. Add corresponding tests
4. Update profile guards if needed

### Version History
- **v1.0 (2026-05-15)**: Initial contract definition
  - Core 15m stack defined
  - Forbidden modules listed
  - Profile guards documented
  - UI/UX contract specified

---

## Sign-Off

**Approved by**: MERID Core Team
**Effective Date**: 2026-05-15
**Review Date**: 2026-06-15
