# Kalshi Production Wiring Audit

> Generated: 2026-03-19  
> Scope: Every agent, engine, pipeline, bus, and swarm component in the codebase  
> Goal: Only Kalshi-production-critical components stay wired; everything else is ARCHIVE or FUTURE

---

## 0. Enforcement Policies

This section defines mechanically enforceable rules. `tests/test_archive_import_guard.py` validates these automatically.

### Classification Semantics

| Label | Meaning | Rule |
|-------|---------|------|
| **KEEP** | Wires exist and are used in the Kalshi production loop | Must have start + stop in `_app_lifespan` (or be stateless) |
| **ARCHIVE** | Must not be imported in Kalshi prod | Must physically live under `archive/`. Cannot be imported from `web.main` or any router used in Kalshi-only mode. Grep for `archive.` imports as an invariant. |
| **FUTURE** | Allowed in tree but explicitly non-prod | Must be gated behind `not _kalshi_only` in `create_app()`. Must NOT start background tasks or consume event-loop time. Must contain `# NOT_WIRED_NON_PROD` in first 5 lines. |

### FUTURE Banner

Every `.py` file classified as **FUTURE** must contain the exact token `# NOT_WIRED_NON_PROD` within its first 5 lines. This is enforced by `tests/test_future_banner_guard.py`. The token makes it trivially greppable and CI-verifiable.

### Shim Policy

> **No new shims may be added to `kalshi_shims.py`.** New endpoints must be added directly to their owning router. `kalshi_shims.py` is a shrinking surface — promote existing shims to proper routers and delete them here.

### Legend

- 🔒 = Gated by `MERID_PROFILE=kalshi-only` — **never started in production**
- ✅ = Proper lifecycle (start + stop)
- ⚠️ = Missing explicit stop (cancelled via task sweep)

---

## 1. Lifespan Wiring Matrix

Every long-lived service must be started **and** stopped in `_app_lifespan` (`web/main.py`).  
🔒 = gated by `MERID_PROFILE=kalshi-only` and thus **never started in production**.

| # | Component | Module | Started In | Stopped In | Failure Impact | Used By (UI/API) | Status |
|---|-----------|--------|-----------|-----------|---------------|-----------------|--------|
| 1 | **KalshiAgentGrid** | `merid.prediction.agent_grid` | Phase 0.5 (deferred task) | Shutdown §4 `grid.stop()` | No trading — all agents dead | kalshi_grid_api, kalshi_agent_grid_api | **KEEP** |
| 2 | **CanonicalAgentRegistry** | `merid.agents.bootstrap` | Phase 0.51 `ensure_bootstrapped()` | — (stateless) | Agent health UI empty | agents_health, agents_real | **KEEP** |
| 3 | **RealityAuditor** | `core.reality_auditor` | Phase 0.52 | — (stateless) | No assertion tracking | reality API | **KEEP** |
| 4 | **RewardEngine** | `merid.rewards.engine` | Phase 0.52 | — (singleton) | Rewards API 500s | rewards API | **FUTURE** |
| 5 | **PortfolioRebalancer** | `merid.event_venues.kalshi.rebalancer` | Phase 0.53 | Shutdown flush | Unbalanced position sizing | kalshi_grid_api | **KEEP** |
| 6 | **NotificationManager** | `notifications.notification_manager` | Phase 0.54 (deferred) | Shutdown §5 | No Telegram alerts | notification_api, kalshi_shims | **KEEP** |
| 7 | **OrchestratorAgentManager** | `web.startup_agents` | Phase 0.6 🔒 | Shutdown §3 `stop_all()` | Sub-services not managed | — (manages sub-services) | **KEEP** (Kalshi sub-services only) |
| 8 | **ConsensusEngine** | `core.consensus_engine` | Phase 1 + streaming task | Shutdown via SystemOrchestrator | No consensus — agents trade solo | consensus API, prediction_consensus | **KEEP** |
| 9 | **PaperTradingEngine** | `trading.paper_trading` | Phase 1 🔒 (skipped) | — | N/A (not started) | paper_trading API | **ARCHIVE** |
| 10 | **ReflectionLayer** | `agents.reflection_layer` | Phase 1 (singleton) | — | Reflection UI empty | reflection API | **FUTURE** |
| 11 | **BrierTracker** | `monitoring.brier_metrics` | Phase 1 | — | Calibration metrics gone | brier_metrics API | **KEEP** |
| 12 | **Neo4jGraph** | `memory.neo4j_graph` | Phase 1 (if available) | — | Graph memory unavailable | neo4j_memory API | **FUTURE** |
| 13 | **EventBusBridge** | inline in `_app_lifespan` | Phase 3 (task) | Cancelled on shutdown | /ws WebSocket dead | /ws WebSocket | **KEEP** |
| 14 | **HealthMonitor** | `core.health` | Phase 3 | Shutdown §5 | Health API returns stale | health API, system_endpoints | **KEEP** |
| 15 | **AlertManager** | `core.alerts` | Phase 3 | Shutdown §5 | No price alerts fire | operator_endpoints | **KEEP** |
| 16 | **AuditTrail** | `core.audit_trail` | Phase 3 | Shutdown §5 | No audit logging | operator_endpoints, archive | **KEEP** |
| 17 | **SystemOrchestrator** | `core.system_orchestrator` | Phase 3 `start_merid()` | Shutdown `stop_merid()` | No inter-system API | system_endpoints | **KEEP** |
| 18 | **KalshiVenueClient** | `merid.event_venues.kalshi.client` | Phase 3 `connect()` | — (persistent) | **No orders, no quotes** | kalshi_api (all endpoints) | **KEEP** |
| 19 | **KalshiMarketCache** | `merid.event_venues.kalshi.market_cache` | Phase 3 `start()` | Shutdown §5 | Stale market data | kalshi_api | **KEEP** |
| 20 | **KalshiMarketCatalog** | `merid.event_venues.kalshi.market_catalog` | Phase 3 `start()` | Shutdown §5 | **No markets visible** | kalshi_api, lanes, agents | **KEEP** |
| 21 | **KalshiSentimentService** | `merid.event_venues.kalshi.sentiment` | Phase 3 `start()` | Shutdown §5 | Sentiment scores stale | kalshi_api /sentiment | **KEEP** |
| 22 | **KalshiWebSocketBridge** | `merid.event_venues.kalshi.ws_bridge` | Phase 3 (task) | Shutdown §5 | No real-time price updates | MarketStateStore → UI | **KEEP** |
| 23 | **TickerCollector** | `merid.event_venues.kalshi.ticker_collector` | Phase 3 `start()` | Shutdown §5 | No tick history | kalshi_api /tickers | **KEEP** |
| 24 | **KalshiInsightPipeline** | `merid.publishing.kalshi_insight_pipeline` | Phase 3 `start()` | — (via OrchestratorMgr) | No insights published | kalshi_api /insights | **KEEP** |
| 25 | **KalshiNewsAgent** | `merid.publishing.kalshi_news_agent` | Phase 3 (consumer wired) | — | News not generated | insight pipeline consumer | **KEEP** |
| 26 | **EnhancedConsensusCoord** | `consensus.consensus_coordinator` | Phase 3 `start_opinion_subscriber()` | Shutdown §2 | No opinion aggregation | consensus_api, prediction_consensus | **KEEP** |
| 27 | **WatchdogCoordinator** | `agents.watchdog_agents` | Phase 3 `start()` | Shutdown §5 | No liveness checks | system health | **KEEP** |
| 28 | **MarketMoodBus** | `merid.swarm.market_mood_bus` | Phase 3 `start()` | Shutdown §5 (via OrchestratorMgr) | No sentiment context for agents | sentiment_api | **KEEP** |
| 29 | **SentimentBus** | `merid.sentiment.sentiment_bus` | Phase 3 🔒 (skipped) | Shutdown §5 | N/A (not started) | — | **ARCHIVE** |
| 30 | **TwitterStreamHandler** | `merid.sentiment.twitter_fetcher` | Phase 3 🔒 (skipped) | Shutdown (sync stop) | N/A (not started) | — | **ARCHIVE** |
| 31 | **HashtagMonitor** | `merid.sentiment.hashtag_monitor` | Phase 3 `start()` | Shutdown §5 | No hashtag/news ingestion | — (feeds MarketMoodBus) | **KEEP** |
| 32 | **CFGIRefreshLoop** | inline in `_app_lifespan` | Phase 3 (task) | Cancelled on shutdown | Fear/greed index stale | MarketMoodBus fear/greed | **KEEP** |
| 33 | **WSFeedManager** | `merid.signals.ws_price_feed` | Phase 3 🔒 (skipped) | Shutdown §5 | N/A (not started) | — | **ARCHIVE** |
| 34 | **MeridLoop** | `merid.loop` | Phase 3 (gated on startup_success) | Shutdown §1 `stop()` | **Swarm tick cycle stops** | loop_api | **KEEP** |
| 35 | **AgentOrchestrator** | `core.agent_orchestrator` | Phase 3 🔒 (skipped) | — | N/A (not started) | — | **ARCHIVE** |
| 36 | **AgentMesh** | `agents.agent_mesh` | Phase 3 🔒 (skipped) | — | N/A (not started) | — | **ARCHIVE** |
| 37 | **ExecutionEngine** | `trading.execution` | Phase 3 `get_optimal_executor()` | — | No execution plans | execution endpoints | **KEEP** |
| 38 | **IntelligenceNewsAgg** | `web.api.intelligence.aggregate_news` | Phase 3 (task) | Cancelled on shutdown | Intelligence API empty | intelligence API | **FUTURE** |
| 39 | **APILivePriceFeed** | `web.api.live_data.fetch_live_prices` | Phase 3 (task) | Cancelled on shutdown | Live data API stale | live_data API | **FUTURE** |
| 40 | **SignalMetricsCache** | `web.api.signal_layer_api` | Phase 3 `warm_signal_metrics_cache()` | — (one-shot) | Signal layer cold start | signal_layer_api | **FUTURE** |
| 41 | **ReconciliationLoop** | inline in `_app_lifespan` | Deferred (task) | Cancelled on shutdown | Execution gate may stay blocked | kalshi_shims /reconciliation | **KEEP** |
| 42 | **KalshiReconLoop** | inline in `_app_lifespan` | Deferred (async task, 300s) | Cancelled on shutdown | Drift undetected until manual check | operator_endpoints | **KEEP** |
| 43 | **EventLoopWatchdog** | inline in `_app_lifespan` | After yield (daemon thread) | — (daemon) | No block detection (diag only) | diagnostic only | **KEEP** |

---

## 2. Agents — KEEP / ARCHIVE / FUTURE

### `merid/agents/` (Kalshi-specific agents)

| File | Class/Function | Status | Reason |
|------|---------------|--------|--------|
| `bootstrap.py` | `ensure_bootstrapped()` | **KEEP** | Started Phase 0.51 |
| `base.py` | `KalshiAgentBase` | **KEEP** | Base class for all Kalshi agents |
| `btc_15m_agent.py` | `Btc15mAgent` | **KEEP** | Grid agent |
| `btc_1h_agent.py` | `Btc1hAgent` | **KEEP** | Grid agent |
| `eth_15m_agent.py` | `Eth15mAgent` | **KEEP** | Grid agent |
| `sol_15m_agent.py` | `Sol15mAgent` | **KEEP** | Grid agent |
| `xrp_15m_agent.py` | `Xrp15mAgent` | **KEEP** | Grid agent |
| `kalshi_crypto/` | Crypto agent package | **KEEP** | Re-exports above |
| `kalshi_event/` | Event agent package | **KEEP** | Sports/event agents |
| `orchestrator.py` | `AgentOrchestrator` | **KEEP** | Manages agent grid lifecycle |
| `coordination.py` | Agent coordination logic | **KEEP** | Multi-agent coordination |
| `wiring.py` | Agent wiring/bootstrap | **KEEP** | Wires agents at startup |
| `hybrid.py` | Hybrid agent | **FUTURE** | Not wired in grid |
| `ops.py` | Ops agent | **FUTURE** | Not wired in grid |
| `publisher_agent.py` | PublisherAgent | **FUTURE** | Stub |
| `research.py` | ResearchAgent | **FUTURE** | Not wired in grid |
| `risk_agents.py` | Risk agents | **KEEP** | Used by PortfolioRiskAgent |
| `sentiment_agent.py` | SentimentAgent | **FUTURE** | Not wired in grid |
| `social_ingestion.py` | SocialIngestionAgent | **FUTURE** | Not wired |
| `sports_odds.py` | SportsOddsAgent | **FUTURE** | Not wired in grid |
| `strategy.py` | StrategyAgent | **FUTURE** | Not wired in grid |

### `agents/` (Framework-level agents)

| File | Class/Function | Status | Reason |
|------|---------------|--------|--------|
| `agent_framework.py` | `AgentRegistry` | **KEEP** | Used by agents_health, agents_real APIs |
| `watchdog_agents.py` | `WatchdogCoordinator` | **KEEP** | Started Phase 3, liveness checks |
| `reflection_layer.py` | `reflection_layer` | **KEEP** | Started Phase 1, reflection API |
| `reflection/` | Reflection subsystem | **KEEP** | ReflectionSystem started by OrchestratorMgr |
| `telegram_agent.py` | `TelegramAgent` | **KEEP** | Rate-limited Telegram sending |
| `twitter_agent.py` | `TwitterAgent` | **FUTURE** | Twitter posting not active |
| `news_monitor_agent.py` | `NewsMonitorAgent` | **KEEP** | Started by OrchestratorMgr (optional) |
| `streaming/` | StreamingAgents | **FUTURE** | Used by AgentMesh (disabled in kalshi-only) |
| `agent_mesh.py` | `agent_mesh` | **ARCHIVE** | Disabled in kalshi-only (saturates event loop) |
| `mesh.py` | AgentMesh | **ARCHIVE** | Same as above |
| `crypto_prediction_agent.py` | CryptoPredictionAgent | **ARCHIVE** | Legacy crypto, not Kalshi |
| `prediction_arbitrage_analyst.py` | PredictionArbitrageAnalyst | **ARCHIVE** | Legacy |
| `fast_prediction_arbitrage_analyst.py` | FastPredArb | **ARCHIVE** | Legacy |
| `governor_agent.py` | GovernorAgent | **ARCHIVE** | Not wired |
| `human_collaboration_ux.py` | HumanCollabUX | **ARCHIVE** | Not wired |
| `llm_roles.py` | LLM roles | **ARCHIVE** | Not wired |
| `manifest.py` | Agent manifest | **KEEP** | Static config, no runtime cost |
| `swarm_coordination.py` | SwarmCoordination | **ARCHIVE** | Not wired in kalshi-only |
| `swarm_mixin.py` | SwarmMixin | **ARCHIVE** | Same |
| `unified_decision_layer.py` | UnifiedDecisionLayer | **ARCHIVE** | Not wired |
| `base_agent.py` | BaseAgent | **KEEP** | Base class |
| `interface.py` | AgentInterface | **KEEP** | Base interface |
| `registry.py` | AgentRegistry | **KEEP** | Used by agent framework |
| `trading_registry.py` | TradingRegistry | **KEEP** | Trading agent registration |
| `_legacy/` | Legacy polymarket etc | **ARCHIVE** | Already moved |

---

## 3. Kalshi Venue — `merid/event_venues/kalshi/`

All files in this directory are Kalshi-specific. Classification:

| File | Status | Reason |
|------|--------|--------|
| `client.py` | **KEEP** | Core venue client, started Phase 3 |
| `client_enhanced.py` | **FUTURE** | 280 bytes, stub |
| `market_catalog.py` | **KEEP** | Started Phase 3, backbone |
| `market_cache.py` | **KEEP** | Started Phase 3, TTL cleanup |
| `market_state.py` | **KEEP** | KalshiMarketStateStore, fed by WS bridge |
| `ws.py` | **KEEP** | KalshiWebSocket (raw WS) |
| `ws_bridge.py` | **KEEP** | Started Phase 3, pipes WS→event bus |
| `ws_metrics.py` | **KEEP** | WS metrics counters |
| `order_router.py` | **KEEP** | Core order routing |
| `order_manager.py` | **KEEP** | Order lifecycle |
| `order_manager_enhanced.py` | **KEEP** | Enhanced order lifecycle |
| `order_group_manager.py` | **KEEP** | Order group lifecycle |
| `order_group_manager_enhanced.py` | **KEEP** | Enhanced groups |
| `order_group_lifecycle.py` | **KEEP** | Group state machine |
| `order_group_recovery.py` | **KEEP** | Crash recovery |
| `order_errors.py` | **KEEP** | Error classification |
| `orderbook.py` | **KEEP** | Orderbook data |
| `models.py` | **KEEP** | Core data models |
| `kalshi_risk.py` | **KEEP** | Risk manager |
| `bracket_risk.py` | **KEEP** | Bracket-level risk |
| `category_exposure.py` | **KEEP** | Per-category caps |
| `position_sizer.py` | **KEEP** | Kelly/vol sizing |
| `position_cache.py` | **KEEP** | Position cache |
| `stop_loss.py` | **KEEP** | Stop-loss engine |
| `sentiment.py` | **KEEP** | Started Phase 3 |
| `ticker_collector.py` | **KEEP** | Started Phase 3 |
| `market_filter.py` | **KEEP** | Market filtering |
| `market_classifier.py` | **KEEP** | Market classification |
| `market_context.py` | **KEEP** | Context provider |
| `market_context_resolver.py` | **KEEP** | Context resolution |
| `market_mapping.py` | **KEEP** | Ticker mapping |
| `metrics.py` | **KEEP** | Performance metrics |
| `rebalancer.py` | **KEEP** | Started Phase 0.53 |
| `universe.py` | **KEEP** | Universe management |
| `universe_sync.py` | **KEEP** | Universe sync |
| `auto_promoter.py` | **KEEP** | Auto-promotion engine |
| `deployment.py` | **KEEP** | Deployment tracking |
| `responsible_trading.py` | **KEEP** | Responsible trading limits |
| `trading.py` | **KEEP** | Trading helpers |
| `trading_enhanced.py` | **KEEP** | Enhanced trading |
| `venue_adapter.py` | **KEEP** | Venue adapter |
| `venue_adapter_enhanced.py` | **KEEP** | Enhanced adapter |
| `fix_client.py` | **FUTURE** | FIX protocol (not in live loop yet) |
| `websocket_service.py` | **KEEP** | WS service layer |
| `wiring_orchestrator.py` | **KEEP** | Wiring management |
| `wiring_service.py` | **KEEP** | Wiring service |
| `market_wiring/` | **KEEP** | Market-specific wiring |
| `liquidity_monitor.py` | **KEEP** | Liquidity monitoring |
| `volume_monitor.py` | **KEEP** | Volume monitoring |
| `collector.py` | **KEEP** | Data collection |
| `coverage_checker.py` | **KEEP** | Universe coverage |
| `regime_detection.py` | **KEEP** | Market regime |
| `performance_comparator.py` | **KEEP** | Performance comparison |
| `backtest.py` | **KEEP** | Backtesting engine |
| `backtest_checks.py` | **KEEP** | Backtest validation |
| `backtest_viz.py` | **KEEP** | Backtest visualization |
| `historical_sim.py` | **KEEP** | Historical simulation |
| `ruin_simulator.py` | **KEEP** | Ruin probability |
| `archiver.py` | **KEEP** | Data archival |
| `kalshi_robustness.py` | **KEEP** | Robustness patterns |
| `robustness_integration.py` | **KEEP** | Robustness wiring |
| `trade_analytics.py` | **KEEP** | Trade analytics |

---

## 4. Pipelines & Buses

### Event Buses (KEEP — all in Kalshi production path)

| Bus | Module | Producers | Consumers | Status |
|-----|--------|-----------|-----------|--------|
| **core.event_bus** | `core/event_bus.py` | trading_agent, order_router, MeridLoop | EventBusBridge → observability | **KEEP** |
| **observability.event_stream** | `observability/event_stream.py` | EventBusBridge, API routes | /ws WebSocket, WS endpoints | **KEEP** |
| **core.streaming_bus** | `core/streaming_bus.py` | InsightPipeline (NEWS topic) | NewsAnalystAgent, AgentMesh | **KEEP** |
| **MarketMoodBus** | `merid/swarm/market_mood_bus.py` | CFGI, HashtagMonitor, SentimentBus | trading_agent `_build_snapshot()`, lanes | **KEEP** |
| **SentimentBus** | `merid/sentiment/sentiment_bus.py` | Twitter, Reddit scrapers | MarketMoodBus | **ARCHIVE** (🔒 kalshi-only skip) |
| **SentimentBusV2** | `merid/sentiment/sentiment_bus_v2.py` | HashtagMonitor | MarketMoodBus | **KEEP** (still used by HashtagMonitor) |

### Pipelines (KEEP — in Kalshi production path)

| Pipeline | Module | Input | Output | Status |
|----------|--------|-------|--------|--------|
| **KalshiInsightPipeline** | `merid/publishing/kalshi_insight_pipeline.py` | Market catalog → swarm consensus | InsightObject → KalshiNewsAgent + streaming_bus.NEWS | **KEEP** |
| **KalshiInsightPipelineRobust** | `merid/publishing/kalshi_insight_pipeline_robust.py` | Same (hardened variant) | Same | **FUTURE** (not started, robust variant) |

### Web Services (publishers)

| Service | Module | Status | Reason |
|---------|--------|--------|--------|
| `web/services/price_publisher.py` | CryptoPricePublisher | **ARCHIVE** | Legacy crypto WS publisher, DISABLED in lifespan |
| `web/services/portfolio_publisher.py` | PortfolioPublisher | **ARCHIVE** | Legacy crypto WS publisher, DISABLED in lifespan |

---

## 5. Swarm / Orchestration Layer

### `consensus/` (KEEP — Kalshi consensus path)

| File | Status | Reason |
|------|--------|--------|
| `consensus_coordinator.py` | **KEEP** | EnhancedConsensusCoordinator, started Phase 3 |
| `taco_consensus.py` | **KEEP** | TaCoConsensusCoordinator, used by trading agents |
| `feedback_scheduler.py` | **KEEP** | Consensus feedback loop |

### `merid/swarm/` (Mixed)

| File | Status | Reason |
|------|--------|--------|
| `market_mood_bus.py` | **KEEP** | Started Phase 3 |
| `consensus_aggregator.py` | **KEEP** | Used by consensus-signals API |
| `consensus_engine.py` | **KEEP** | Swarm consensus engine |
| `auction_consensus.py` | **KEEP** | Escalation mechanism |
| `orchestrator.py` | **KEEP** | Swarm orchestrator |
| `critic_agent.py` | **KEEP** | Debate critic |
| `execution_subscriber.py` | **KEEP** | Execution event consumer |
| `matrix.py` | **KEEP** | Consensus matrix (UI) |
| `messages.py` | **KEEP** | Message types |

### `merid/prediction/` (KEEP — Kalshi agent grid + debate)

| File | Status | Reason |
|------|--------|--------|
| `agent_grid.py` | **KEEP** | Core — started Phase 0.5 |
| `agent_grid_config.py` | **KEEP** | Grid configuration |
| `trading_agent.py` | **KEEP** | Core — 35 trading agents |
| `paper_session.py` | **KEEP** | Paper tracking per cell |
| `opinion_strategy.py` | **KEEP** | KalshiLiveMarketStrategy |
| `consensus.py` | **KEEP** | Prediction consensus |
| `consensus_bridge.py` | **KEEP** | Consensus ↔ trading bridge |
| `debate.py` | **KEEP** | Debate store |
| `debate_orchestrator.py` | **KEEP** | Debate loop |
| `debate_position_sizing.py` | **KEEP** | Debate-informed sizing |
| `debate_exit_policy.py` | **KEEP** | Debate-informed exits |
| `debate_backtest.py` | **KEEP** | Debate backtesting |
| `debate_deployment.py` | **KEEP** | Debate deployment |
| `edge_model.py` | **KEEP** | Edge estimation |
| `edge_recalibrator.py` | **KEEP** | Edge recalibration |
| `pnl_attribution.py` | **KEEP** | PnL attribution |
| `pnl_attribution_db.py` | **KEEP** | PnL attribution DB |
| `portfolio_risk_agent.py` | **KEEP** | Portfolio risk |
| `portfolio_risk_manager.py` | **KEEP** | Portfolio risk manager |
| `agent_performance_tracker.py` | **KEEP** | Agent performance |
| `agent_risk_quotas.py` | **KEEP** | Risk quotas per agent |
| `ai_guardrails.py` | **KEEP** | AI guardrails |
| `alerts.py` | **KEEP** | Prediction alerts |
| `backtest_scheduler.py` | **KEEP** | Backtest scheduling |
| `execution_intelligence.py` | **KEEP** | Execution intelligence |
| `model.py` | **KEEP** | Prediction model |
| `risk.py` | **KEEP** | Prediction risk |
| `strategy.py` | **KEEP** | Prediction strategy |
| `venue_gate.py` | **KEEP** | SIM/PAPER/LIVE gate |
| `session_guard.py` | **KEEP** | Session time guard |
| `signal_calibrator.py` | **KEEP** | Signal calibration |
| `social_broadcaster.py` | **KEEP** | Started by OrchestratorMgr |
| `prob_accuracy_tracker.py` | **KEEP** | Probability accuracy |
| `quantitative_gates.py` | **KEEP** | Quantitative pre-trade gates |
| `universal_agent.py` | **KEEP** | All-markets agent |
| `kalshi_tools.py` | **KEEP** | Agent tool functions |
| `mcp_market_feed.py` | **FUTURE** | MCP protocol (not wired) |
| All `*_context.py` files | **KEEP** | Context providers for agents |
| `forecasters/` | **KEEP** | Forecasting models |

### `merid/lanes/` (KEEP — BTC 15m lane is primary)

| File | Status | Reason |
|------|--------|--------|
| `btc15m_lane.py` | **KEEP** | Primary lane, started by OrchestratorMgr |
| `crypto15m_lane.py` | **KEEP** | Multi-asset lane |
| `registry.py` | **KEEP** | Lane registry |
| `lane_metrics.py` | **KEEP** | Lane Prometheus metrics |
| `rck_integration.py` | **KEEP** | Risk-constrained Kelly |
| `rck_dataclasses.py` | **KEEP** | RCK data types |
| `rck_integration_wrapper.py` | **KEEP** | RCK wrapper |
| `rck_backtest.py` | **KEEP** | RCK backtesting |
| `rck_complete_example.py` | **FUTURE** | Example/demo |
| `consensus_integration.py` | **FUTURE** | Demo data |
| `consensus_engine_integration.py` | **KEEP** | Engine integration |

### `swarm/` — Production Safety Layer (KEEP)

These files provide runtime safety, metrics, and agent infrastructure for the Kalshi production loop.

| File | Status | Reason |
|------|--------|--------|
| `performance.py` | **KEEP** | `performance_ledger` imported at module level |
| `agents/charters.py` | **KEEP** | `CHARTER_REGISTRY` imported at module level |
| `agents/instances.py` | **KEEP** | Agent instance management |
| `agent_registry.py` | **KEEP** | Used by agent framework |
| `agent_monitoring_metrics.py` | **KEEP** | Agent metrics |
| `anti_silent_failure.py` | **KEEP** | Silent failure detection |
| `emergent_behavior_safeguards.py` | **KEEP** | Safety guardrails |

### `swarm/` — Research / Experimental (ARCHIVE — moved to `archive/legacy_swarm/`)

These files have been physically relocated. They must not be imported from any KEEP module.

| File | Former Location | Reason |
|------|----------------|--------|
| `dev_swarm_orchestrator.py` | `swarm/` | Dev-only, not Kalshi prod |
| `swarm_lab.py` | `swarm/` | Lab/experimental |
| `swarm_lab_orchestrator.py` | `swarm/` | Lab/experimental |
| `federated_learning.py` | `swarm/` | Not wired |
| `marl_engine.py` | `swarm/` | Not wired |
| `coma.py` | `swarm/` | Not wired |
| `replicator.py` | `swarm/` | Not wired |
| `rllib_wrapper.py` | `swarm/` | Not wired |
| `sb3_wrapper.py` | `swarm/` | Not wired |
| `pso_optimizer.py` | `swarm/` | Not wired |
| `continuous_learning_pipeline.py` | `swarm/` | Not wired |
| `sniper_scanner.py` | `swarm/` | Not wired (crypto sniping) |
| `contract_scanner.py` | `swarm/` | Not wired (on-chain) |
| `mev_rewards.py` | `swarm/` | Not wired (DeFi) |
| `secure_yield_contracts.py` | `swarm/` | Not wired (DeFi) |
| `zk_privacy_bridge.py` | `swarm/` | Not wired |
| `gamification_swarm.py` | `swarm/` | Not wired |
| `gamified_security.py` | `swarm/` | Not wired |
| `adaptive_model_selector.py` | `swarm/` | Not wired |
| `adversarial_robustness.py` | `swarm/` | Not wired |
| `agent_benchmarking.py` | `swarm/` | Not wired |
| `anomaly_detection_ml.py` | `swarm/` | Not wired |
| `auto_code_generator.py` | `swarm/` | Not wired |
| `automated_upgrade_testing.py` | `swarm/` | Not wired |
| `command_runner.py` | `swarm/` | Not wired |
| `cost_optimizer.py` | `swarm/` | Not wired |
| `cross_chain_invariants.py` | `swarm/` | Not wired (on-chain) |
| `cross_protocol_health.py` | `swarm/` | Not wired (on-chain) |

### `swarm/` — Future (not wired, still in tree)

| File | Status | Reason |
|------|--------|--------|
| `agents/local_venue_guardian.py` | **FUTURE** | Not wired |
| `collab_orchestrator.py` | **FUTURE** | Not wired in lifespan |

---

## 6. Web API Routers — KEEP / ARCHIVE / FUTURE

### Always-registered (Kalshi-critical)

| Router | Source | Status |
|--------|--------|--------|
| `auth_router` | `web.api.auth` | **KEEP** |
| `kalshi_api_router` | `web.api.kalshi_api` | **KEEP** |
| `kalshi_grid_router` | `web.api.kalshi_grid_api` | **KEEP** |
| `kalshi_ui_router` | `web.api.kalshi_ui` | **KEEP** |
| `kalshi_agent_grid_router` | `web.api.kalshi_agent_grid_api` | **KEEP** |
| `kalshi_agent_performance_router` | `web.api.kalshi_agent_performance_api` | **KEEP** |
| `kalshi_deployment_router` | `web.api.kalshi_deployment` | **KEEP** |
| `kalshi_metrics_api_router` | `web.api.kalshi_metrics_api` | **KEEP** |
| `kalshi_shims_router` | `web.api.kalshi_shims` | **KEEP** |
| `kalshi_exec_telemetry_router` | `web.api.kalshi_execution_telemetry_api` | **KEEP** |
| `paper_ladder_router` | `web.api.paper_ladder_api` | **KEEP** |
| `paper_session_router` | `web.api.paper_session_api` | **KEEP** |
| `operator_router` | `web.api.operator` | **KEEP** |
| `operator_endpoints_router` | `web.api.operator_endpoints` | **KEEP** |
| `risk_router` | `web.api.risk_routes` | **KEEP** |
| `risk_metrics_router` | `web.api.risk_metrics` | **KEEP** |
| `risk_metrics_api_router` | `web.api.risk_metrics_api` | **KEEP** |
| `system_endpoints_router` | `web.api.system_endpoints` | **KEEP** |
| `system_observability_router` | `web.api.system_observability` | **KEEP** |
| `system_control_router` | `web.api.system_control` | **KEEP** |
| `health_router` | `web.api.health` | **KEEP** |
| `monitoring_router` | `web.api.monitoring` | **KEEP** |
| `resilience_router` | `web.api.resilience` | **KEEP** |
| `guardrails_router` | `web.api.guardrails_api` | **KEEP** |
| `metrics_router` | `web.api.metrics` | **KEEP** |
| `telemetry_router` | `web.api.telemetry` | **KEEP** |
| `consensus_router` | `web.api.consensus` | **KEEP** |
| `consensus_api_router` | `web.api.consensus_api` | **KEEP** |
| `prediction_markets_router` | `web.api.prediction_markets` | **KEEP** |
| `prediction_consensus_router` | `web.api.prediction_consensus_api` | **KEEP** |
| `debate_data_router` | `web.api.debate_data_api` | **KEEP** |
| `debate_health_router` | `web.api.debate_health_api` | **KEEP** |
| `incentive_router` | `web.api.incentive_api` | **KEEP** |
| `notification_api_router` | `web.api.notification_api` | **KEEP** |
| `sentiment_api_router` | `web.api.sentiment_api` | **KEEP** |
| `swarm_bus_api_router` | `web.api.swarm_bus_api` | **KEEP** |
| `auto_promoter_api_router` | `web.api.auto_promoter_api` | **KEEP** |
| `correlation_api_router` | `web.api.correlation_api` | **KEEP** |
| `xtf_api_router` | `web.api.xtf_api` | **KEEP** |
| `crypto_lanes_router` | `web.api.crypto_lanes_api` | **KEEP** |
| `crypto_status_router` | `web.api.crypto_status` | **KEEP** |
| `brier_metrics_router` | `web.api.brier_metrics` | **KEEP** |
| `sidebar_config_router` | `web.api.sidebar_config` | **KEEP** |
| `loop_api_router` | `web.api.loop_api` | **KEEP** |
| `analytics_router` | `web.api.analytics` | **KEEP** |
| `dashboard_router` | `web.api.dashboard` | **KEEP** |
| `dashboard_data_router` | `web.api.dashboard_data` | **KEEP** |
| `dashboard_ws_router` | `web.api.dashboard_ws` | **KEEP** |
| `agents_router` | `web.api.agents` | **KEEP** |
| `agents_health_router` | `web.api.agents_health` | **KEEP** |
| `agents_real_router` | `web.api.agents_real` | **KEEP** |
| `orchestrator_api_router` | `web.api.orchestrator_api` | **KEEP** |
| `signals_api_router` | `web.api.signals_api` | **KEEP** |
| `swarm_router` | `web.api.swarm` | **KEEP** |
| `swarm_routes_router` | `web.api.swarm_routes` | **KEEP** |
| `observability_router` | `web.api.observability` | **KEEP** |
| `websocket_health_router` | `web.api.websocket_health` | **KEEP** |
| `ws_dedicated_router` | `web.api.ws_dedicated_streams` | **KEEP** |
| `ws_paper_router` | `web.api.ws_paper` | **KEEP** |
| `ws_trade_events_router` | `web.api.ws_trade_events` | **KEEP** |
| `replay_router` | `web.api.replay_api` | **KEEP** |
| `missing_endpoints_router` | `web.api.missing_endpoints` | **KEEP** (catch-all 404 prevention) |
| `degraded_router` | `web.api.degraded` | **KEEP** |
| `modes_router` | `web.api.modes` | **KEEP** |
| `markets_data_router` | `web.api.markets_data` | **KEEP** |
| `trading_mode_router` | `web.api.trading_mode` | **KEEP** |
| `explainability_router` | `web.api.explainability` | **KEEP** |
| `production_status_router` | `web.api.production_status` | **KEEP** |
| `feedback_router` | `web.api.feedback` | **KEEP** |
| `prime_screen_router` | `web.api.prime_screen` | **KEEP** |
| `api_status_router` | `web.api.api_status` | **KEEP** |

### Gated behind `not _kalshi_only` (ARCHIVE in Kalshi prod)

| Router | Source | Status |
|--------|--------|--------|
| `mining_router` | `web.api.mining` | **ARCHIVE** |
| `referrals_router` | `web.api.referrals` | **ARCHIVE** |
| `_trading_router` | `web.api.trading` | **ARCHIVE** |
| `betting_router` | `web.api.betting` | **ARCHIVE** |
| `_pt` / `_ptc` | `web.api.paper_trading` | **ARCHIVE** (Kalshi uses PaperSession) |
| `institutional_router` | `web.api.institutional` | **ARCHIVE** |
| `prediction_router` | `web.api.prediction` | **ARCHIVE** |
| `wallet_router` | `web.api.wallet` | **ARCHIVE** |
| `plugins_router` | `web.api.plugins` | **ARCHIVE** |
| `cost_models_router` | `web.api.cost_models` | **ARCHIVE** |
| `time_exploit_router` | `web.api.time_exploit` | **ARCHIVE** |
| `sniping_router` | `web.api.sniping` | **ARCHIVE** |
| `treasury_router` | `web.api.treasury` | **ARCHIVE** |
| `quadratic_funding_router` | `web.api.quadratic_funding` | **ARCHIVE** |
| `_ts` (trading_suite) | `web.api.trading_suite` | **ARCHIVE** |
| `reality_router` | `web.api.reality` | **ARCHIVE** |
| `intelligence_router` | `web.api.intelligence` | **ARCHIVE** |
| `local_venue_router` | `web.api.local_venue` | **ARCHIVE** |
| `local_venue_validation_router` | `web.api.local_venue_validation` | **ARCHIVE** |
| `market_assertions_router` | `web.api.market_assertions` | **ARCHIVE** |
| `onchain_assertions_router` | `web.api.onchain_assertions` | **ARCHIVE** |
| `simulation_assertions_router` | `web.api.simulation_assertions` | **ARCHIVE** |
| `agent_assertions_router` | `web.api.agent_assertions` | **ARCHIVE** |
| `moat_router` | `web.api.moat` | **ARCHIVE** |
| `simulation_router` | `web.api.simulation` | **ARCHIVE** |
| `neo4j_memory_router` | `web.api.neo4j_memory` | **ARCHIVE** |
| `autonomy_router` | `web.api.autonomy` | **ARCHIVE** |
| `us_compliant_markets_router` | `web.api.us_compliant_markets` | **ARCHIVE** |
| `blockchain_health_api_router` | `web.api.blockchain_health_api` | **ARCHIVE** |
| `rewards_router` | `web.api.rewards` | **ARCHIVE** |
| `cognitive_router` | `web.api.cognitive_api` | **ARCHIVE** |
| `dev_swarm_governance_router` | `web.api.dev_swarm_governance_routes` | **ARCHIVE** |
| `llm_governance_router` | `web.api.llm_governance_api` | **ARCHIVE** |
| `rag_router` | `web.api.rag_api` | **ARCHIVE** |
| `assistant_router` | `web.api.assistant_api` | **ARCHIVE** |
| `_si("web.api.arbitrage")` | `web.api.arbitrage` | **ARCHIVE** |

### Registered unconditionally but NOT Kalshi-critical

| Router | Source | Status | Action |
|--------|--------|--------|--------|
| `betting_consensus_router` | `web.api.betting_consensus_api` | **FUTURE** | Gate behind `not _kalshi_only` |
| `flow_router` | `web.api.flow_api` | **FUTURE** | Gate behind `not _kalshi_only` |
| `signal_layer_router` | `web.api.signal_layer_api` | **FUTURE** | Gate behind `not _kalshi_only` |
| `unified_pipeline_router` | `web.api.unified_pipeline` | **FUTURE** | Gate behind `not _kalshi_only` |
| `predictions_router` | `web.api.predictions` | **FUTURE** | Gate behind `not _kalshi_only` |
| `x_bot_router` | `web.api.x_bot` | **FUTURE** | Used for social broadcasting but not active |
| `dev_swarm_router` | `web.api.dev_swarm_routes` | **FUTURE** | Gate behind `not _kalshi_only` |
| `live_data_router` | `web.api.live_data` | **FUTURE** | Legacy live data |
| `live_stream_router` | `web.api.live_stream` | **FUTURE** | Legacy streaming |
| `streams_router` | `web.api.streams` | **FUTURE** | Legacy streams |
| `data_endpoints_router` | `web.api.data_endpoints` | **FUTURE** | Legacy data |
| `real_data_router` | `web.api.real_data_endpoints` | **FUTURE** | Legacy real data |
| `domain_priority_router` | `web.api.domain_priority` | **FUTURE** | Not Kalshi-critical |
| `governance_router` | `web.api.governance` | **FUTURE** | Gate behind `not _kalshi_only` |
| `compliance_router` | `web.api.compliance` | **FUTURE** | Gate behind `not _kalshi_only` |
| `offline_router` | `web.api.offline` | **FUTURE** | Gate behind `not _kalshi_only` |
| `notifications_router` | `web.api.notifications` | **FUTURE** | Overlaps with notification_api |
| `backup_router` | `web.api.backup` | **FUTURE** | Not critical path |
| `recovery_router` | `web.api.recovery` | **FUTURE** | Not critical path |
| `reflection_router` | `web.api.reflection` | **FUTURE** | Not critical path |
| `ops_router` | `web.api.ops` | **FUTURE** | Ops tooling |
| `archive_router` | `web.api.archive` | **FUTURE** | Archive access |
| `schemas_router` | `web.api.schemas` | **FUTURE** | Schema introspection |
| `benchmarks_router` | `web.api.benchmarks_api` | **FUTURE** | Not critical path |

---

## 7. Shim / Stub Inventory

> **Policy**: No new shims may be added to `kalshi_shims.py`. New endpoints must go directly to their owning router. This file is a **shrinking surface**.

### `web/api/kalshi_shims.py` — 9 shim endpoints (all functional)

| Endpoint | Real Implementation? | Action |
|----------|---------------------|--------|
| `POST /api/v1/reconciliation/run` | ✅ Calls `reconcile_all_venues()` | Promote to proper router |
| `GET /api/v1/reconciliation/status` | ✅ Calls `has_critical_discrepancies()` | Promote to proper router |
| `POST /api/v1/risk/downsize-all` | ✅ Calls `risk_controller.trigger_downsize_all()` | Promote to risk_routes |
| `DELETE /api/v1/risk/kill-switch` | ✅ Calls `risk_controller.reset_kill_switch()` | Promote to risk_routes |
| `POST /api/v1/system/pause-agents` | ✅ Calls `grid.pause_all()` | Promote to system_endpoints |
| `POST /api/v1/errors/report` | ❌ Returns empty `{errors: []}` | Wire to real error collection |
| `GET /api/v1/kalshi/lane/status` | ✅ Calls `get_lane_registry()` | Promote to crypto_lanes_api |
| `POST /api/v1/lanes/{lane_id}/toggle` | ✅ Calls `get_lane_registry()` | Promote to crypto_lanes_api |
| `GET /api/v1/venues` | ✅ Hardcoded Kalshi-only | Keep (correct for Kalshi-only) |
| `GET /api/v1/notifications/status` | ✅ Calls `get_notification_manager()` | Promote to notification_api |
| `GET /api/v1/notifications/recent-alerts` | ❌ Returns empty `{alerts: []}` | Wire to real alert history |

### `web/api/missing_endpoints.py` — 84KB catch-all

This file exists solely to prevent frontend 404s. All endpoints return stub responses. It should NOT contain any production logic. **Status: KEEP as-is** — prevents frontend crashes. Replace individual endpoints as real implementations mature.

---

## 8. Ad-Hoc Thread / Task Audit

All `asyncio.create_task()` and `threading.Thread()` calls found in the lifespan:

| Task Name | Started In | Has Stop? | Status |
|-----------|-----------|-----------|--------|
| `deferred-grid-start` | Phase 0.5 | `grid.stop()` | ✅ |
| `deferred-notif-start` | Phase 0.54 | `mgr.stop()` | ✅ |
| `deferred-orchestrator-start` | Phase 0.6 | `stop_all()` | ✅ |
| `event-bus-bridge` | Phase 3 | Cancelled | ✅ |
| `kalshi-ws-bridge` | Phase 3 | `bridge.stop()` | ✅ |
| `cfgi-fg-refresh` | Phase 3 | Cancelled | ✅ |
| `ws-price-feed` | Phase 3 🔒 | `mgr.stop()` | ✅ |
| `merid-loop` | Phase 3 | `loop.stop()` | ✅ |
| `agent-orchestrator` | Phase 3 🔒 | — | ⚠️ No explicit stop |
| `agent-mesh` | Phase 3 🔒 | — | ⚠️ No explicit stop |
| `intelligence-news` | Phase 3 | Cancelled | ✅ |
| `api-live-prices` | Phase 3 | Cancelled | ✅ |
| `deferred-recon` | Post-startup | Cancelled | ✅ |
| `kalshi-recon-loop` | Post-startup | CancelledError handled | ✅ |
| `el-watchdog-hb` | Post-yield | Cancelled | ✅ |
| `el-watchdog` (Thread) | Post-yield | Daemon | ✅ |

**Findings**: Agent orchestrator and agent mesh tasks (both 🔒 kalshi-only gated) lack explicit stop handlers but are cancelled via the background_tasks sweep. No ungated ad-hoc threads found outside lifespan.

---

## 9. Kalshi-Only Guards Checklist

Services that should ONLY coordinate Kalshi venue agents in production:

| Component | Has Kalshi-Only Guard? | Guard Location |
|-----------|----------------------|----------------|
| AgentGrid | ✅ Kalshi agents only via config | `agent_grid_config.py` |
| MeridLoop | ✅ Runs Kalshi tick cycle only | `merid/loop.py` |
| OrderRouter | ✅ Routes to Kalshi only | `order_router.py` |
| CategoryExposure | ✅ Kalshi categories only | `category_exposure.py` |
| KalshiUniverse | ✅ Kalshi-only | `universe.py` |
| OrchestratorAgentManager | ✅ Gated `MERID_PROFILE` | `_app_lifespan` Phase 0.6 |
| AgentOrchestrator | ✅ Gated `MERID_PROFILE` | `_app_lifespan` |
| AgentMesh | ✅ Gated `MERID_PROFILE` | `_app_lifespan` |
| SentimentBus | ✅ Gated `MERID_PROFILE` | `_app_lifespan` |
| WSFeedManager | ✅ Gated `MERID_PROFILE` | `_app_lifespan` |
| PaperTradingEngine | ✅ Gated `KALSHI_ONLY` | `_app_lifespan` Phase 1 |
| SimulationChain | ✅ Gated `KALSHI_ONLY` | `create_app()` |
| VenueGate | ✅ Polymarket/Augur blocked | `venue_gate.py` |

---

## 10. Summary & Recommended Actions

### Counts

| Category | KEEP | ARCHIVE | FUTURE |
|----------|------|---------|--------|
| Lifespan services | 30 | 5 | 8 |
| `merid/agents/` | 11 | 0 | 10 |
| `agents/` (framework) | 12 | 11 | 2 |
| `merid/event_venues/kalshi/` | 62 | 0 | 2 |
| Pipelines & buses | 7 | 3 | 1 |
| `consensus/` | 3 | 0 | 0 |
| `merid/swarm/` | 9 | 0 | 0 |
| `merid/prediction/` | 40+ | 0 | 1 |
| `merid/lanes/` | 10 | 0 | 2 |
| `swarm/` (top-level) | 6 | 25+ | 1 |
| Web API routers | 64 | 35 | 25 |
| Web services | 0 | 2 | 0 |

### Priority Actions

1. ~~**Gate 25 FUTURE routers** behind `not _kalshi_only` in `create_app()`~~ — ✅ DONE (2026-03-19)
2. ~~**Move `swarm/` ARCHIVE files** (28 files) to `archive/legacy_swarm/`~~ — ✅ DONE (2026-03-19)
3. ~~**Move `agents/` ARCHIVE files** (11 files) to `archive/legacy_agents/`~~ — ✅ DONE (2026-03-19)
4. ~~**Move `web/services/` ARCHIVE files** (2 files) to `archive/legacy_web_services/`~~ — ✅ DONE (2026-03-19)
5. ~~**Promote 4 capital-safety shims** (reconciliation ×2 deleted as duplicates, risk ×2 promoted to `risk_routes.py` with auth)~~ — ✅ DONE (2026-03-19)
6. ~~**Promote remaining 4 shims + delete 1 duplicate stub** (`pause-agents` → `system_endpoints.py`, lane/notification shims deleted as duplicates of real routers)~~ — ✅ DONE (2026-03-19). `KNOWN_SHIM_ENDPOINT_COUNT` 11 → **2** (only `/errors/report` stub + `/venues` static remain)
7. ~~**Add `# NOT_WIRED_NON_PROD` banner** to all 20 FUTURE files~~ — ✅ DONE (2026-03-19)
8. ~~**Create `test_archive_import_guard.py`** — fails if any `archive/` module is imported from `web.main` or a KEEP router~~ — ✅ DONE (2026-03-19)
9. ~~**Create `test_future_banner_guard.py`** — fails if any FUTURE file is missing the banner~~ — ✅ DONE (2026-03-19)
10. ~~**Capture baseline startup time / memory**~~ — ✅ DONE (2026-03-19)

### SRE Baseline (2026-03-19, kalshi-only profile)

| Metric | Value |
|--------|-------|
| Cold-start (spawn → `/system/status` 200) | **~92s** |
| RSS after 60s settle | **508.9 MB** |
| VMS after 60s settle | **921.3 MB** |
| First Kalshi API call (`/kalshi/markets?limit=1`) | **233 ms** |

Historical data: [`reports/sre-baseline.json`](../reports/sre-baseline.json)  
Capture script: [`scripts/sre_baseline_capture.py`](../scripts/sre_baseline_capture.py)

### Tracking

Detailed checklist: [`docs/kalshi_wiring_todo.md`](kalshi_wiring_todo.md)  
Automated guard: [`tests/test_archive_import_guard.py`](../tests/test_archive_import_guard.py)  
Banner guard: [`tests/test_future_banner_guard.py`](../tests/test_future_banner_guard.py)
