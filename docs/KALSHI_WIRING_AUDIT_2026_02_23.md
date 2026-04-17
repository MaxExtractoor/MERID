# MERID Kalshi Trading System — Wiring Audit

**Date**: 2026-02-23  
**Verification script**: `scripts/_verify_kalshi_wiring.py`  
**Result**: 109/114 checks passing (5 infra-dependent: Neo4j offline, Redis offline)

---

## Trade Flow (end-to-end verified)

```
MeridLoop.tick()
  │
  ├─► _run_agent_cycles()
  │     └─► AgentGrid.agents[].start()
  │           └─► KalshiTradingAgent._run_cycle()
  │                 │
  │                 ├─ 0. _check_stop_losses()     → StopLossRules
  │                 ├─ 1. SessionGuard check        → is_trading_allowed()
  │                 ├─ 2. _resolve_markets()        → MarketCatalog → KalshiClient
  │                 ├─ 3. _filter_active_contracts() → 1 per asset/timeframe
  │                 ├─ 4. _build_snapshot()          → PredictionMarketModel
  │                 │     ├─ SentimentService enrichment
  │                 │     ├─ MarketMoodBus context
  │                 │     └─ Edge computation (model vs implied)
  │                 ├─ 5. KalshiStrategy.evaluate()  → StrategySignal
  │                 ├─ 6. _submit_to_consensus()     → SwarmConsensusAggregator
  │                 │     └─ Wait for consensus alignment or conflict
  │                 ├─ 7. PredictionMarketRisk.check_order()
  │                 │     └─ 10-point pre-trade check
  │                 └─ 8. _execute_signal()
  │                       ├─ BTC15m risk layer (CryptoSwarmRiskBTC15m)
  │                       └─ _kalshi_place_order()
  │                             │
  │                             ├─ VenueGate.check_order("kalshi")
  │                             ├─ DeploymentController mode check
  │                             ├─ ExecutionGate (kill switch + recon)
  │                             ├─ SessionGuard
  │                             │
  │                             ├─ [PAPER] → simulated fill (orderbook-based)
  │                             ├─ [SHADOW] → real order + parallel paper fill
  │                             └─ [LIVE] → KalshiClient.place_order_result()
  │
  ├─► _run_consensus()          → TacoConsensus + DebateSession
  ├─► _run_arb_scan()           → DislocationScanner
  ├─► _refresh_liquidity()      → LiquidityMonitor + orderbook snapshots
  ├─► _execute_plans()          → ExecutionGuard → matching engine / venue adapter
  ├─► _update_cqi()             → DriftDetector → CQI scores → guard throttle
  ├─► _reconcile_positions()    → KalshiReconciler → discrepancy detection
  ├─► _sync_order_groups()      → OrderGroupLifecycleManager
  └─► _reload_config()          → RealityAuditor + PortfolioRebalancer
```

## Mode Routing (all 3 modes verified)

| Mode | VenueGate | DeploymentController | Order Routing |
|------|-----------|---------------------|---------------|
| **PAPER** | `should_simulate_fill()=True` | `AgentMode.PAPER` | Simulated fill using live orderbook data |
| **SHADOW** | `should_simulate_fill()=False` | `AgentMode.SHADOW` | Real order submitted + parallel paper fill recorded |
| **LIVE** | `should_simulate_fill()=False` | `AgentMode.LIVE` | Real order submitted, live fill tracking |

### Safety chain (6 layers before any order reaches venue):
1. `VenueGate.check_order("kalshi")` — US compliance, mode gating
2. `DeploymentController` — per-agent HALTED check
3. `ExecutionGate` — kill switch, reconciliation, PnL consistency
4. `SessionGuard` — trading hours, maintenance windows
5. `PredictionMarketRisk.check_order()` — 10-point pre-trade
6. `CryptoSwarmRiskBTC15m` — per-lane risk (BTC 15m only)

## Risk Pipeline (verified)

```
KillSwitchState (global)
  └─► ExecutionGuard (aggregates: kill switch + recon + price feed + PnL)
        └─► PredictionMarketRisk (per-market: notional, daily loss, spread, slippage)
              └─► PositionSizer (Kelly fraction, vol-scaled, drawdown-aware)
                    └─► CategoryExposureTracker (per-category USD caps)
                          └─► OrderSanityChecker (final validation)
```

## Data Pipeline (verified)

```
LiveFeedManager (Finnhub, FRED, CoinGecko)
  └─► FeatureService (news, social, onchain, macro)
        └─► SignalStore (store_feature_snapshot)
              └─► KalshiSignalGenerator (Kalshi-specific signals)
                    └─► DriftDetector (CQI per domain)
                          └─► ConsensusCoordinator (decay-aware aggregation)
                                └─► DebateSession (high-conviction signal debates)
```

## Critical Fix Applied This Session

**27 files** were missing `import threading` — causing `NameError` that cascaded through the import chain and broke 57+ module imports. Root cause: `agents/reflection/__init__.py` line 46 used `threading.Lock()` without the import.

### Import cascade path:
```
merid.prediction.venue_gate
  → trading.trade_mode
    → trading.__init__
      → trading.execution
        → core.events
          → core.__init__
            → core.consensus_graph
              → agents.interface
                → agents.__init__
                  → agents.base_agent
                    → agents.reflection.__init__  ← NameError: threading
```

### Files fixed (27 total):
`agents/reflection/__init__.py`, `agents/llm_roles.py`, `agents/meta_market_agent.py`,
`agents/reflection/runtime.py`, `core/error_handling.py`, `merid/paper_config.py`,
`merid/venue_registry.py`, `merid/backtesting/bot_lifecycle.py`,
`merid/blockchain/compliance.py`, `merid/guardrails/capabilities.py`,
`merid/prediction/alerts.py`, `merid/prediction/session_guard.py`,
`merid/risk/multi_tf_drawdown.py`, `merid/sentiment/btc_risk_dial.py`,
`merid/sentiment/fg_filter.py`, `merid/sentiment/kalman_sentiment.py`,
`merid/sentiment/sentiment_regime.py`, `merid/sentiment/sentiment_roadmap.py`,
`merid/sentiment/sentiment_stops.py`, `governance/agent_reputation_system.py`,
`governance/board_reporting.py`, `governance/capability_gating.py`,
`governance/quadratic_funding.py`, `observability/neo4j_integration.py`,
`latency_optimizer/policies.py`, `security/agi_safety_rails.py`,
`security/ai_rug_detection.py`

## Module Inventory (all verified importable)

| Module | Purpose | Status |
|--------|---------|--------|
| `merid.prediction.agent_grid` | Grid orchestrator | ✅ |
| `merid.prediction.trading_agent` | Per-cell trading agent | ✅ |
| `merid.prediction.kalshi_tools` | Typed tool wrappers | ✅ |
| `merid.prediction.strategy` | Edge/sizing decisions | ✅ |
| `merid.prediction.risk` | Pre-trade risk checks | ✅ |
| `merid.prediction.model` | Implied probabilities | ✅ |
| `merid.prediction.venue_gate` | Mode gating | ✅ |
| `merid.prediction.session_guard` | Trading hours | ✅ |
| `merid.prediction.paper_session` | PnL tracking | ✅ |
| `merid.prediction.consensus` | Swarm consensus | ✅ |
| `merid.prediction.debate` | Debate protocol | ✅ |
| `merid.prediction.edge_model` | Edge computation | ✅ |
| `merid.prediction.alerts` | Alert management | ✅ |
| `merid.event_venues.kalshi.client` | REST client + auth | ✅ |
| `merid.event_venues.kalshi.trading` | Order management | ✅ |
| `merid.event_venues.kalshi.ws` | WebSocket feed | ✅ |
| `merid.event_venues.kalshi.kalshi_risk` | Venue risk manager | ✅ |
| `merid.event_venues.kalshi.position_sizer` | Kelly/vol sizing | ✅ |
| `merid.event_venues.kalshi.stop_loss` | Stop-loss rules | ✅ |
| `merid.event_venues.kalshi.deployment` | PAPER→SHADOW→LIVE | ✅ |
| `merid.event_venues.kalshi.market_catalog` | Market discovery | ✅ |
| `merid.event_venues.kalshi.liquidity_monitor` | Orderbook health | ✅ |
| `merid.execution_guard` | 4-source safety gate | ✅ |
| `merid.matching_engine` | Internal paper fills | ✅ |
| `merid.loop` | Main orchestrator | ✅ |
| `merid.risk.kill_switches` | Global kill switch | ✅ |
| `merid.risk.promotion_engine` | Phase promotion | ✅ |
| `merid.risk.crypto_swarm_risk_btc15m` | BTC 15m lane risk | ✅ |
| `merid.signals.drift` | CQI / drift detection | ✅ |
| `merid.reconciliation` | Venue reconciliation | ✅ |
| `merid.metrics.calibration` | Brier score tracking | ✅ |
| `merid.rag.service` | RAG pipeline | ✅ |
| `consensus.taco_consensus` | TACO consensus engine | ✅ |
| `trading.trade_mode` | Canonical mode enum | ✅ |
