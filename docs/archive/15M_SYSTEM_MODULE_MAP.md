# 15m Kalshi Crypto System Module Map

**Purpose**: Complete module dependency map for `web.main_15m:app` (kalshi_crypto_15m_v2 profile)

**Entry Point**: `web.main_15m.py` → FastAPI app on port 8011

**Uvicorn Command**:
```bash
MERID_PROFILE=kalshi_crypto_15m_v2 uvicorn web.main_15m:app --host 0.0.0.0 --port 8011 --log-level info
```

---

## Module Dependency Tree

```
web.main_15m (FastAPI app)
├── Lifespan: _app_lifespan
│   ├── Profile validation: MERID_PROFILE == "kalshi_crypto_15m_v2"
│   ├── Config snapshot: scripts.capture_config_snapshot
│   │
│   ├── Phase 0: Core Infrastructure (_start_core_infrastructure)
│   │   ├── _validate_environment
│   │   │   ├── Environment: KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH (live)
│   │   │   └── Demo mode: MERID_DEMO_MODE (mock credentials if set)
│   │   │
│   │   ├── _start_redis
│   │   │   └── core.cache.CacheAdapter
│   │   │
│   │   ├── _start_auth (skipped for 15m - Kalshi API keys primary)
│   │   │
│   │   └── _start_risk_limits
│   │       └── merid.guards.global_risk_guard
│   │           └── get_global_risk_guard()
│   │
│   ├── Phase 1: Kalshi Venue Services (_start_kalshi_venue)
│   │   ├── _start_kalshi_client
│   │   │   └── merid.event_venues.kalshi.client
│   │   │       └── get_kalshi_client()
│   │   │
│   │   ├── _start_bankroll_service
│   │   │   └── merid.event_venues.kalshi
│   │   │       └── get_bankroll_service()
│   │   │
│   │   ├── _start_market_catalog
│   │   │   └── merid.event_venues.kalshi.market_catalog
│   │   │       └── get_market_catalog()
│   │   │       ├── Allowed series: KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M
│   │   │       └── Internal: config.kalshi_universe.kalshi_agent_grid_catalog_series_tickers()
│   │   │
│   │   ├── _start_market_state
│   │   │   └── merid.event_venues.kalshi.market_state
│   │   │       └── get_kalshi_market_state_store()
│   │   │
│   │   ├── _start_ws_bridge
│   │   │   ├── merid.event_venues.kalshi.ws_bridge
│   │   │   │   └── get_ws_bridge()
│   │   │   └── merid.event_venues.kalshi.market_selector
│   │   │       └── get_agent_market_tickers(agent_name, series_tickers)
│   │   │       ├── Series → Agent mapping: KXBTC15M→BTC_15M, KXETH15M→ETH_15M, etc.
│   │   │       └── Catalog resolution via market_catalog
│   │   │
│   │   ├── _start_fills_poller
│   │   │   └── merid.event_venues.kalshi.fills_poller
│   │   │       └── get_fills_poller()
│   │   │
│   │   ├── _start_settlement_poller
│   │   │   └── merid.event_venues.kalshi.settlement_poller
│   │   │       └── get_settlement_poller(kalshi_client)
│   │   │
│   │   ├── _start_rti_feed_service (SKIPPED for kalshi_crypto_15m_v2)
│   │   │   └── Profile guard prevents RTI feed startup
│   │   │
│   │   ├── _start_live_price_feed
│   │   │   └── data.live_price_feed
│   │   │       └── get_live_price_feed()
│   │   │       ├── Coinbase streaming disabled (feed.disable_coinbase())
│   │   │       ├── CCXT fallback enabled
│   │   │       ├── Symbols: BTC/USD, ETH/USD, SOL/USD, XRP/USD, DOGE/USD
│   │   │       └── Background task: feed.start_streaming()
│   │   │
│   │   └── _start_term_structure (SKIPPED for kalshi_crypto_15m_v2)
│   │       └── Profile guard prevents term structure startup
│   │
│   ├── Phase 2: Agent Grid (_load_agent_grid)
│   │   ├── merid.prediction.agent_grid_config
│   │   │   └── load_agent_grid_config()
│   │   │       └── Source: config/kalshi_agent_grid.yaml
│   │   │
│   │   ├── merid.prediction.agent_grid
│   │   │   └── AgentGrid(config=config)
│   │   │
│   │   └── merid.prediction.trading_agent
│   │       └── LifecycleState.ACTIVE (manually set for 15m)
│   │       └── 5 agents: BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M
│   │
│   └── Phase 3: 15m Loop (_start_15m_loop)
│       ├── merid.loop_15m
│       │   └── get_kalshi_15m_loop(agent_grid, venue_adapter, bankroll_service, risk_config, cadence_seconds=5.0)
│       │       ├── Kalshi15mLoop.run_forever()
│       │       │   └── while self._running:
│       │       │       └── await _run_one_cycle(tick)
│       │       │           ├── merid.risk.profiles.kalshi_crypto_15m_risk_envelope
│       │       │           │   └── safe_update_envelope_equity(self._risk_envelope)
│       │       │           ├── Drawdown halt check (skip cycle if halted)
│       │       │           ├── agent_grid.run_cycle(tick)
│       │       │           │   └── Each agent: agent.run_cycle(tick) or agent.step(tick)
│       │       │           └── Heartbeat: logger.info("[15m-LOOP] HEARTBEAT cycle=%d", tick)
│       │       └── Kalshi15mLoop.summary() → tick, cycle_count, error_count, uptime, last_cycle_at
│       │
│       ├── merid.event_venues.kalshi.venue_adapter
│       │   └── get_kalshi_venue_adapter()
│       │
│       └── merid.event_venues.kalshi.kalshi_risk
│           └── KalshiRiskConfig()
│
├── API Endpoints
│   ├── GET / → Root endpoint (name, profile, version, status)
│   ├── GET /api/health → Health check (app, profile, loop.summary(), services)
│   ├── GET /status → Detailed status (loop, agents, services)
│   └── GET /metrics → Prometheus metrics (risk envelope bands)
│       └── merid.risk.profiles.kalshi_crypto_15m_risk_envelope
│           └── get_kalshi_crypto_15m_risk_envelope()
│
└── Shutdown (_stop_all)
    ├── loop.stop()
    ├── agent_grid.stop()
    ├── settlement_poller.stop()
    ├── fills_poller.stop()
    ├── ws_bridge.stop()
    ├── bankroll_service.stop()
    └── Cancel all background_tasks
```

---

## Core Runtime Services (7 services)

| Service | Module | Purpose | Startup Phase |
|---------|--------|---------|---------------|
| kalshi_client | merid.event_venues.kalshi.client | Kalshi API client | Phase 1 |
| bankroll_service | merid.event_venues.kalshi.get_bankroll_service | Balance tracking | Phase 1 |
| market_catalog | merid.event_venues.kalshi.market_catalog | Market discovery (5 series) | Phase 1 |
| market_state | merid.event_venues.kalshi.market_state | Orderbook/trade cache | Phase 1 |
| ws_bridge | merid.event_venues.kalshi.ws_bridge | Real-time WebSocket data | Phase 1 |
| fills_poller | merid.event_venues.kalshi.fills_poller | Fill reconciliation | Phase 1 |
| settlement_poller | merid.event_venues.kalshi.settlement_poller | Settlement polling | Phase 1 |
| live_price_feed | data.live_price_feed | Spot prices (CCXT fallback) | Phase 1 |
| agent_grid | merid.prediction.agent_grid | 5 crypto agents | Phase 2 |
| loop | merid.loop_15m.Kalshi15mLoop | 5s event loop | Phase 3 |

---

## Skipped Components (28 components)

The following legacy components are intentionally **NOT** started in the 15m app:

- core.systemorchestrator
- Governance, treasury
- Graph memory, macro overlay
- Cross-sectional PM metrics
- Legacy lane orchestration
- Reflection/learning systems
- KalshiContinuousTrader
- Legacy PM agent mesh / continuous trader
- RTI feed service (profile guard)
- Term structure (profile guard)

---

## Configuration Sources

| Component | Config File | Key Settings |
|-----------|-------------|--------------|
| Agent grid | config/kalshi_agent_grid.yaml | 5 agents, series_tickers, assets, timeframes |
| Risk envelope | config/profiles/kalshi_crypto_15m.yaml | Capital, caps, drawdown_halt_pct, adaptive_risk_bands |
| Entry window policies | config/kalshi_15m_crypto_config.py | DEFAULT_ENTRY_POLICIES (BTC, ETH, SOL, XRP, DOGE) |
| Universe | config/kalshi_universe.py | kalshi_agent_grid_catalog_series_tickers() |
| Environment | .env | KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH, MERID_PROFILE |

---

## Profile Guards

The following profile guards enforce the 15m-only behavior:

1. **web.main_15m startup**: Raises if `MERID_PROFILE != "kalshi_crypto_15m_v2"`
2. **RTI feed service**: Skipped if profile == "kalshi_crypto_15m_v2"
3. **Term structure**: Skipped if profile == "kalshi_crypto_15m_v2"
4. **Agent grid validation**: Enforces exactly 5 agents: BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M
5. **Market catalog**: Enforces 5 allowed series: KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M

---

## Data Flow

```
Kalshi WebSocket (ws_bridge)
    ↓
Market State Store (market_state)
    ↓
Agent Grid (5 agents)
    ↓
Trading Agent (resolve_markets, window_filter, strike_selector)
    ↓
Venue Adapter (order routing)
    ↓
Kalshi Client (order execution)
    ↓
Fills Poller (reconciliation)
    ↓
Bankroll Service (balance tracking)
    ↓
Risk Envelope (drawdown monitoring)
```

---

## Next Steps for Audit

1. **Layer A - Kalshi Access & Risk Envelope**: Audit client, bankroll, fills, settlement, risk envelope
2. **Layer B - Market Discovery, State, WS Bridge**: Audit catalog, market state, ws_bridge, market_selector
3. **Layer C - Spot Price Feed**: Audit live_price_feed, CCXT fallback, symbol mapping
4. **Layer D - Agent Grid, Policies, Loop**: Audit agent grid config, trading agents, loop execution
