# MERID System Architecture

> Generated: 2026-03-07. Branch: develop. Status: Live audit.

---

## System Purpose

MERID is a 24/7 AI swarm-intelligence prediction market trading platform. Primary venue: **Kalshi** (crypto prediction markets, event markets). The system orchestrates a swarm of AI agents that produce probabilistic trade proposals; a consensus layer aggregates them into order decisions; an execution gate applies risk rules before placement.

---

## Startup & Entry Points

| File | Role |
|------|------|
| `web/main.py` | **Canonical entry point.** FastAPI app factory (`create_app()`). Mounts all routers. Lifespan starts MeridLoop, KalshiVenueAdapter, VenueRegistry, ExecutionGuard, AgentGrid, crypto lanes, OrchestratorAgentManager. |
| `main.py` | **Legacy heavy startup.** Starts streaming workers, agent mesh, consensus engine, simulation miner, audit trail, price/portfolio publishers. Currently coexists with `web/main.py`; callers should be migrated to `web/main.py`. |
| `web/main.py::lifespan()` | Async context manager; runs on `uvicorn` startup. Initializes all subsystems in sequence; failures are logged but do NOT block startup (all wrapped in try/except). |

---

## Backend Module Map

### Core Loop & Orchestration

| Module | Path | Responsibility |
|--------|------|----------------|
| `MeridLoop` | `merid/loop.py` | Main async orchestrator. Drives 6 cadenced intervals: feature refresh (30s), agent cycles (60s), consensus (15s), arb scan (10s), CQI (300s), reconciliation (120s). Feature flags: `enable_execution`, `enable_arb_execution`. |
| `LoopConfig` | `merid/loop.py` | Dataclass controlling all cadences and feature flags. Built from `LoopConfig.from_paper_config()`. `enable_execution=False` by default — must be explicitly set. |
| `AgentGrid` | `merid/prediction/agent_grid.py` | Grid of prediction agents (5×4: assets × timeframes). Started via `get_agent_grid()`. |
| `OrchestratorAgentManager` | `web/startup_agents.py` | Starts supporting agents at launch (sentiment, signal daemons, etc.). |
| `VenueRegistry` | `merid/venue_registry.py` | Registers and retrieves venue adapters by ID (e.g., `"kalshi"`). |

### Kalshi Integration

| Module | Path | Responsibility |
|--------|------|----------------|
| `KalshiClient` | `merid/event_venues/kalshi/client.py` | Canonical REST client. Implements `EventVenueClient`. Circuit breaker + retry with backoff. RSA key auth. `OperationResult` returns. |
| `KalshiVenueAdapter` | `merid/event_venues/kalshi/venue_adapter.py` | Higher-level adapter. Singleton via `get_kalshi_venue_adapter(mode=)`. Supports `paper`/`live`. |
| `KalshiWebSocketService` | `merid/event_venues/kalshi/websocket_service.py` | Background WS to Kalshi feed. Started at lifespan, stopped at shutdown. Singleton. |
| `KalshiOrderRouter` | `merid/event_venues/kalshi/order_router.py` | Routes order placement through paper/live paths. |
| `KalshiOrderGroupManager` | `merid/event_venues/kalshi/order_group_manager.py` | Manages batched/grouped orders with lifecycle tracking. |
| `KalshiReconciler` | `merid/reconciliation/kalshi_reconciler.py` | Reconciles in-memory positions against Kalshi REST at startup + interval. |
| `KalshiMarketCatalog` | `merid/event_venues/kalshi/market_catalog.py` | Market discovery and caching. |
| `MarketClassifier` | `merid/event_venues/kalshi/market_classifier.py` | Classifies markets as crypto vs. event vs. other. |

### Risk & Safety

| Module | Path | Responsibility |
|--------|------|----------------|
| `RiskManager` | `merid/pipeline/risk_manager.py` | Cross-domain limits (max notional, daily loss, positions, single order). Enforces per-domain allocation caps. |
| `ExecutionGuard` | `merid/execution_guard.py` | Top-level gate before any real order hits Kalshi. Checks kill switch, live-unlock flag, exposure caps. |
| `CircuitBreaker` | `merid/circuit_breaker.py` | Per-venue circuit breaker. Used by `KalshiClient`. |
| `KalshiRisk` | `merid/event_venues/kalshi/kalshi_risk.py` | Kalshi-specific risk calculations (Kelly sizing, exposure). |

### Prediction & Consensus

| Module | Path | Responsibility |
|--------|------|----------------|
| `PredictionConsensusStore` | `merid/prediction/consensus.py` | SQLite-backed store for agent opinions, Brier scoring, stance aggregation. |
| `DebateOrchestrator` | `merid/prediction/debate_orchestrator.py` | Runs structured debate between agents before finalizing a trade proposal. |
| `EdgeModel` | `merid/prediction/edge_model.py` | Computes edge (predicted prob - market prob). Gates position sizing. |
| `AgentPerformanceTracker` | `merid/prediction/agent_performance_tracker.py` | Tracks per-agent win rate, PnL, Brier. |
| `ForecasterRegistry` | `merid/prediction/forecasters/registry.py` | Plugin registry of signal forecasters (momentum, sentiment, macro, mean-reversion, time-series). |

### Sentiment & Data

| Module | Path | Responsibility |
|--------|------|----------------|
| `SentimentBus` | `merid/sentiment/sentiment_bus.py` | Aggregates signals from Twitter, Reddit, news into a single bus. |
| `NewsIngestionAgent` | `merid/sentiment/news_ingestion_agent.py` | Ingests news and produces sentiment signals. |
| `LivePriceFeed` | `data/live_price_feed.py` | Real-time price feed, polled by agents. |
| `SignalStore` | `merid/signals/store.py` | SQLite-backed signal persistence. |

### Settings & Config

| File | Role |
|------|------|
| `merid/settings.py` | **Single source of truth.** Pydantic `BaseSettings`. Reads from `.env`. All service credentials, trading mode, caps. Key flags: `KALSHI_USE_DEMO=True` (safe default), `MERID_PM_LIVE_ENABLED=False` (safe default), `MERID_LIVE_TRADING_UNLOCKED=False` (safe default). |
| `config/settings.py` | Legacy settings shim — delegates to `merid/settings.py`. |
| `merid/paper_config.py` | Paper trading domain matrix — drives `LoopConfig.from_paper_config()`. |

---

## Backend API Layer

`web/main.py::create_app()` mounts **~86 routers**. Key groups:

### Kalshi-first routers (critical path)
| Router | Module | Prefix |
|--------|--------|--------|
| `kalshi_router` | `web/api/kalshi_api.py` | (root, ~6065 LOC — main trading API) |
| `kalshi_venue_router` | `web/api/kalshi_venue_routes.py` | `/api/v1` |
| `kalshi_grid_router` | `web/api/kalshi_grid_api.py` | — |
| `kalshi_agent_grid_router` | `web/api/kalshi_agent_grid_api.py` | — |
| `kalshi_dashboard_router` | `web/api/kalshi_dashboard_api.py` | — |
| `kalshi_wiring_router` | `web/api/kalshi_wiring_api.py` | — |
| `kalshi_metrics_router` | `web/api/kalshi_metrics_api.py` | — |
| `kalshi_deployment_router` | `web/api/kalshi_deployment.py` | — |
| `kalshi_agent_performance_router` | `web/api/kalshi_agent_performance_api.py` | — |
| `kalshi_crypto_signals_router` | `web/api/kalshi_crypto_signals_api.py` (or stub) | — |

### Core operational routers
| Group | Routers |
|-------|---------|
| Risk & Safety | `risk_routes`, `risk_metrics_api`, `guardrails_api`, `resilience` |
| Trading | `paper_trading`, `orders_api`, `trading`, `loop_api`, `paper_ladder_api`, `paper_session_api` |
| Agents & Consensus | `agents`, `consensus_api`, `swarm`, `swarm_bus_api`, `signals_api`, `orchestrator_api` |
| Debate | `debate_api`, `debate_health_api`, `debate_backtest_api`, `debate_integration_api`, `debate_data_api` |
| WebSockets | `ws_paper`, `ws_trade_events`, `ws_dedicated_streams`, `streams`, `dashboard_ws`, `market_data (ws_router)` |
| Data & Analytics | `live_data`, `market_data`, `analytics`, `correlation_api`, `brier_metrics`, `benchmarks_api` |
| System | `health`, `system_endpoints`, `system_observability`, `observability`, `slo_api`, `telemetry`, `api_status`, `production_status` |

### Crypto / Stub zone
| Router | Status |
|--------|--------|
| `crypto_router` | `web/api/crypto_status_authoritative.py` |
| `crypto_lanes_router` | `web/api/crypto_lanes_api.py` |
| `kalshi_crypto_signals_router` | Falls back to `web/api/kalshi_crypto_stub_api.py` if real module missing |
| `flow_router` | `web/api/flow_api.py` — all endpoints return `"source": "stub"` |
| `debate_data_router` | Mounted **twice** (lines 425 and 451 of `web/main.py`) |
| `health_router` | Mounted **twice** (root + `/api/v1`) |

---

## Frontend

### Tech Stack
- React 18 + TypeScript + Tailwind CSS
- Vite build (`web/react/vite.config.ts`)
- No Redux/Zustand — state via `useApiData` polling + `useMeridSocket` WS + local state

### Views (22 routes in `web/react/src/views/`)
| View | Purpose |
|------|---------|
| `Overview.tsx` | System overview / health |
| `KalshiDashboardView.tsx` | Main Kalshi market dashboard (includes former "enhanced" safeguards) |
| `KalshiGridView.tsx` | 5×4 agent grid |
| `KalshiPortfolioView.tsx` | Portfolio & positions |
| `KalshiAgentPerformanceView.tsx` | Per-agent performance (now includes debate metrics) |
| `KalshiSentimentView.tsx` | Sentiment signals |
| `KalshiVolDashboardView.tsx` | Volatility dashboard |
| `KalshiTerminalView.tsx` | Order terminal |
| `KalshiAllMarketsView.tsx` | Full market catalog |
| `KalshiRiskScreen.tsx` | Risk monitoring |
| `KillSwitchView.tsx` | Kill switch controls |
| `SwarmConsensusMatrix.tsx` | Swarm vote matrix |
| `CalibrationDashboardView.tsx` | Calibration/Brier |
| `LaneControlDashboard.tsx` | Lane (asset/timeframe) control |
| `OperatorDashboard.tsx` | Operator home |
| `OperatorControlPlane.tsx` | Operator controls |
| `OperatorActivityStream.tsx` | Live event stream |
| `OperatorStatusBar.tsx` | Status bar |
| `Logs.tsx` | Log viewer |
| `Settings.tsx` | User settings (localStorage) |

### Key Hooks
| Hook | Purpose |
|------|---------|
| `useApiData` | Canonical HTTP polling hook — all REST fetches |
| `useMeridSocket` | WS at `/ws/trades` — swarm events |
| `useKalshiRiskStream` | WS at `/ws/risk` — risk feed |
| `useOrderGroupStream` | WS for order group updates |
| `useRiskProtections` | Polls `/api/v1/risk/protections` |
| `useDashboard` | Aggregates dashboard state |

### Auth
- Bearer token + `X-Session-ID` from `localStorage["merid-v1-access"]`
- Dev bypass auto-ON when `MERID_ENV=development`

### Config
- `web/react/src/config/constants.ts` — all endpoints and polling intervals
- `VITE_API_BASE` / `VITE_WS_URL` / `VITE_WS_PORTFOLIO_URL` — required env vars; throw in PROD if missing

---

## Environment Model

| Env Var | Default | Effect |
|---------|---------|--------|
| `MERID_TRADING_MODE` | `paper` | `paper`=simulated, `live`=real |
| `KALSHI_USE_DEMO` | `true` | `true`=Kalshi sandbox, `false`=production |
| `MERID_PM_LIVE_ENABLED` | `false` | Must be `true` for PM live trading |
| `MERID_LIVE_TRADING_UNLOCKED` | `false` | Hard unlock for live order placement |
| `MERID_ENV` | `development` | Controls auth bypass, log verbosity |
| `KALSHI_API_KEY_ID` | unset | Required for any Kalshi API call |
| `KALSHI_PRIVATE_KEY_PATH` | unset | Path to RSA private key for Kalshi auth |

---

## Observability

| Component | Details |
|-----------|---------|
| Logging | `utils/logger.py` — structured logger, used universally |
| Health endpoint | `GET /health` — returns subsystem status (venues, loop) |
| SLO monitor | `core/slo_monitor.py`, exposed via `/api/v1/slo` |
| Metrics | `web/api/metrics.py` — per-request latency via middleware |
| Prometheus | Config at `monitoring/prometheus.yml`; dashboards at `monitoring/grafana/` |
| Alertmanager | Config at `monitoring/alertmanager.yml`, rules at `monitoring/alert_rules.yml` |
| Audit trail | `data/audit/audit_log.jsonl` — immutable append log |
| Session log | `data/session_log.jsonl` |

---

## WebSocket Endpoints (Backend)

27 WS endpoints total — **none have authentication**. Key ones consumed by frontend:

| Endpoint | Consumer |
|----------|---------|
| `/ws/trades` | `useMeridSocket` |
| `/ws/risk` | `useKalshiRiskStream` |
| `/ws/paper` | `ws_paper` router |
| `/ws/trade-events` | `ws_trade_events` router |
| `/ws/market-data` | `market_data` ws_router |
