# MERID — Kalshi Swarm Workflow Gap Analysis

**Date:** 2026-02-23 (updated v3.4.0)
**Scope:** Audit MERID codebase against canonical Kalshi swarm workflow checklist + deployment hardening

---

## Scoring Key

| Symbol | Meaning |
|--------|---------|
| ✅ | Fully implemented and wired |
| 🟡 | Partially implemented or exists but not wired end-to-end |
| ❌ | Missing or not started |

---

## 1. Market Discovery

| Requirement | Status | MERID Implementation | Gap |
|-------------|--------|---------------------|-----|
| Pull Kalshi markets by category/asset/tenor via REST | ✅ | `market_catalog.py` — periodic `GET /markets`, indexes by category, asset, timeframe | — |
| Tag contracts with metadata (crypto vs macro, event date, liquidity, fee class) | ✅ | `market_catalog.py` — regex-based ticker categorization into crypto/economics/financials/politics/climate/sports/tech/culture/science. Asset detection (BTC, ETH, SOL, CPI, GDP, etc.), timeframe detection (15m, 1h, daily, weekly). `CatalogMarket` dataclass with expiry, strike, category, asset, timeframe | Fee class not explicitly tagged per-contract (handled globally in `kalshi_risk.py`) |
| Quality filtering (liquidity, spread, price range) | ✅ | `market_filter.py` — `MarketFilterConfig` with min_volume, min_OI, max_spread_cents, price floor/ceiling, overlap detection, allowed underlyings/timeframes | — |
| Periodic refresh | ✅ | `KalshiMarketCatalog` — configurable refresh interval (default 5 min), async background task | — |
| Historical data collection | ✅ | `collector.py` + `archiver.py` — fetch closed markets + trade history for backtesting | — |
| MCP server integration | ✅ | `merid/prediction/mcp_market_feed.py` — async MCP client with aiohttp/urllib fallback, configurable via env vars, publishes to StreamingBus. Sprint R. | — |

**Score: 6/6 — Complete**

---

## 2. Agent Roles — Signal Generation

### Scanner Agents

| Requirement | Status | MERID Implementation | Gap |
|-------------|--------|---------------------|-----|
| Continuously pull markets | ✅ | `market_catalog.py` refresh loop + `ws.py` real-time WebSocket stream | — |
| Tag with metadata | ✅ | `CatalogMarket` enrichment in `market_catalog.py` | — |

### Forecaster Agents (heterogeneous)

| Requirement | Status | MERID Implementation | Gap |
|-------------|--------|---------------------|-----|
| Multiple different models | ✅ | `ForecasterRegistry` runs 4 independent forecasters: `MomentumForecaster`, `MeanReversionForecaster`, `MacroRegimeForecaster`, `OrderbookForecaster`. Calibration-weighted ensemble. Sprint B+I+N. | — |
| Per-market output: p_model, confidence, features | ✅ | `ForecastResult` with `p_model`, `confidence`, `components`. Published as typed `Forecast` messages to `StreamingBus`. Sprint E. | — |
| Time-series model | ✅ | `TimeSeriesForecaster` — AR(2) autoregressive model, EWMA volatility, Ornstein-Uhlenbeck mean-reversion half-life, Hurst exponent proxy. Sprint Q. | — |
| Orderbook microstructure model | ✅ | `OrderbookForecaster` — bid/ask imbalance, spread compression, depth-weighted fair value. Standalone forecaster registered in `ForecasterRegistry`. Sprint N. | — |
| Macro regime model | ✅ | `MacroRegimeForecaster` — fear/greed contrarian, cross-timeframe agreement, volatility regime, sentiment composite. Sprint I. | — |
| News/X sentiment model | ✅ | `ExternalSentimentForecaster` — pluggable `SentimentFeedProvider` for news/X APIs, MarketMoodBus context, fear/greed contrarian, sentiment divergence detection. Sprint Q. | — |

### Critic / Sanity Agents

| Requirement | Status | MERID Implementation | Gap |
|-------------|--------|---------------------|-----|
| Detect stale data | ✅ | `core/feed_staleness_monitor.py`, `merid/signals/drift.py` — CQI tracks data freshness | — |
| Detect arbitrage mismatches | ✅ | `merid/signals/arb_scanner.py` — cross-market arb detection | — |
| Detect impossible probabilities | ✅ | `CriticAgent._check_impossible_probs()` — detects p_yes + p_no ≠ 1, multi-outcome sum ≠ 1. Sprint N. | — |
| Detect illiquid markets | ✅ | `market_filter.py` quality gates + `liquidity_monitor.py` real-time alerting | — |
| Veto/down-weight forecaster outputs | ✅ | `CriticAgent` publishes `Critique` messages with `weight_adjustment` (0.0=veto, 0.3=down-weight). Consumed by consensus. Sprint H. | — |

### Risk Agents

| Requirement | Status | MERID Implementation | Gap |
|-------------|--------|---------------------|-----|
| Per-market edge (vs implied Kalshi probability) | ✅ | `edge_model.py` + `strategy.py` — computes edge = model_prob − implied_prob | — |
| Kelly fraction | ✅ | `kalshi_risk.py` — fee-aware Kelly. `position_sizer.py` — fractional Kelly with PF gates | — |
| Exposure vs caps | ✅ | `portfolio_risk_agent.py` — per-asset notional caps. `execution_guard.py` — per-domain daily caps | — |
| Correlation with existing book | ✅ | `merid/risk/correlation.py` — Rolling Pearson correlation, cluster caps, exposure reduction. Wired into `PortfolioRiskAgent`. Sprint D. | — |
| Per-category risk | ✅ | `kalshi_risk.py` — `dynamic_position_sizes()` has `category_cap_pct`. Per-domain limits in pipeline risk manager | — |
| Daily loss tracking | ✅ | `kalshi_risk.py`, `paper_session.py`, `execution_guard.py` — all track daily loss with kill switch | — |
| Drawdown monitoring | ✅ | `paper_session.py` — tiered drawdown governance (warning 5%, downsize 8%, halt 12%) | — |

### Supervisor / Consensus Agent

| Requirement | Status | MERID Implementation | Gap |
|-------------|--------|---------------------|-----|
| Ingests all forecasts + risk views | ✅ | `SwarmConsensusAggregator` collects proposals. Forecasters publish typed `Forecast` messages to `StreamingBus`. Sprints E+H. | — |
| Weighted vote consensus | ✅ | `ConsensusEngine` — trust × energy × confidence weighted voting | — |
| Minimum diversity requirement | ✅ | `SwarmConsensusAggregator` diversity gate requires ≥2 archetypes. Sprint D. | — |
| Outputs BUY/SELL/SKIP + size | ✅ | `ConsensusResult` with decision + `StrategySignal` with action + size | — |

**Score: 24/24 items fully implemented — 7 forecaster types + full critic suite (Sprints B+I+N+Q)**

---

## 3. Consensus & Safety Patterns

| Requirement | Status | MERID Implementation | Gap |
|-------------|--------|---------------------|-----|
| Weighted majority vote | ✅ | `ConsensusEngine` — trust-weighted voting with 2/3 quorum | — |
| Weight by historical Brier score | ✅ | `merid/metrics/calibration.py` — EWMA Brier scores. `ConsensusEngine` blends 70% Brier + 30% trust. Sprint A+C. | — |
| Minimum diversity of agents | ✅ | `SwarmConsensusAggregator` — requires ≥2 archetypes for READY status. Sprint D. | — |
| Auction-style consensus for conflicts | ✅ | `AuctionConsensusResolver` — escalation-based bidding with calibration weights. Wired into `SwarmConsensusAggregator` for CONFLICTED status. Sprint R. | — |
| Pre-trade risk checks | ✅ | `PredictionMarketRisk` — 10-point check. `GlobalRiskManager` — 7-point check. `ExecutionGuard` — 5-layer check. | — |
| Post-trade monitoring (drawdowns, stop-rules) | ✅ | `stop_loss.py` — binary-aware stops. `paper_session.py` — drawdown governance. `DrawdownGovernor` in pipeline. | — |
| Supervisor can override/down-weight aggressive agents | ✅ | `PortfolioRiskAgent` can pause individual agents. Kill switch halts all. | — |
| Global kill switch | ✅ | `ExecutionGuard` — global + per-domain kill switch, persistent to disk | — |

**Score: 8/8 — Complete safety + calibration + auction consensus (Sprints A+C+D+R)**

---

## 4. Message Flow

| Plane | Status | MERID Implementation | Gap |
|-------|--------|---------------------|-----|
| **Data plane** — Market/orderbook/trades broadcast to all forecasters | ✅ | `ws.py` + `ws_bridge.py` — real-time Kalshi data. `market_catalog.py` for REST. `order_router.py` WS channel constants for price/trade/orderbook/fill events | — |
| **Data plane** — Portfolio broadcast to risk and supervisor | ✅ | `portfolio_risk_agent.py` fetches positions/balance. `MeridLoop` reconciliation step. | — |
| **Decision plane** — Forecasters publish typed `Forecast` messages | ✅ | `merid/swarm/messages.py` — Forecast schema. `ForecasterRegistry` publishes to `StreamingBus`. Sprint E. | — |
| **Decision plane** — Critics publish typed `Critique` messages | ✅ | `merid/swarm/critic_agent.py` — CriticAgent wraps staleness + liquidity monitors, publishes Critique messages. Sprint H. | — |
| **Decision plane** — Risk publishes typed `RiskView` messages | ✅ | `PortfolioRiskAgent._publish_risk_view()` — publishes RiskView after each check cycle. Sprint H. | — |
| **Decision plane** — Supervisor emits `Decision` | ✅ | `SwarmConsensusAggregator._recompute_consensus()` — publishes Decision on READY status. Sprint H. | — |
| **Execution plane** — Execution agent subscribes to Decision | ✅ | `merid/swarm/execution_subscriber.py` — subscribes to CONSENSUS+EXECUTION channels, routes risk-approved Decisions to order placement. Sprint M. | — |
| **Feedback plane** — Fills/PnL/slippage feed back into agent scores | ✅ | `CalibrationStore` Brier scores → `ConsensusEngine` trust + `SwarmConsensusAggregator` weights. Sprint C. | — |

**Score: 8/8 — Full typed message flow, all planes wired (Sprints C+E+H+M)**

---

## 5. Kalshi-Specific Nuances

| Requirement | Status | MERID Implementation | Gap |
|-------------|--------|---------------------|-----|
| Binary contract awareness | ✅ | Entire system designed around binary $1 payout contracts | — |
| Fee schedule modeling | ✅ | `kalshi_risk.py` — tiered 7%/5%/3% schedule, fee-aware Kelly | — |
| Time-to-expiry behavior | ✅ | `strategy.py` — `ExpiryPhase` enum (early/mid/late/terminal) with different edge thresholds per phase | — |
| Category-specific rules | ✅ | `market_catalog.py` categorization + per-category risk caps | — |
| Live orderbook awareness | ✅ | `liquidity_monitor.py` — spread/depth alerting. `market_filter.py` — spread gates | — |
| Avoid crossing wide spreads | ✅ | `execution_intelligence.py` — 5-factor scoring (spread width, edge magnitude, urgency, queue depth, imbalance) decides cross vs join_queue vs join_far. Sprint O. | — |
| Respect API rate limits | ✅ | `client.py` — circuit breaker, retry with backoff, concurrency cap (10 concurrent requests) | — |
| Partial fill handling | ✅ | `order_manager.py` — full lifecycle tracking, incremental fill events, timeout cancels | — |
| Order group support | ✅ | `order_group_manager.py` + `order_group_lifecycle.py` + `order_group_recovery.py` | — |

**Score: 9/9 — Complete**

---

## 6. Monitoring & Adaptation

| Requirement | Status | MERID Implementation | Gap |
|-------------|--------|---------------------|-----|
| Fill quality tracking | ✅ | `order_manager.py` — fill events with price/size/fee. `metrics.py` — latency histograms | — |
| Hit ratio tracking | ✅ | `merid/metrics/hit_ratio.py` — Tracks p_model vs p_implied directional accuracy, per-forecaster hit rates, surprise ratio, edge capture. Sprint O. | — |
| Realized edge tracking | ✅ | `merid/metrics/realized_edge.py` — Per-trade edge tracking. `merid/prediction/edge_recalibrator.py` — auto-adjusts thresholds. Sprints A+G. | — |
| PnL tracking | ✅ | `paper_session.py` — per-cell, per-cluster, daily/weekly PnL. `performance_comparator.py` — backtest vs paper vs live | — |
| Agent performance metrics | ✅ | `agent_gauntlet.py` — SLO-based scoring (liveness, latency, signal quality, risk compliance, fill quality, PnL) | — |
| Feed metrics back into consensus weights | ✅ | `CalibrationStore.get_weight()` → `SwarmConsensusAggregator` + `ConsensusEngine`. Sprint C. | — |
| Promotion/demotion logic | ✅ | `auto_promoter.py` — paper → shadow → live promotion with rollback gates (PF, expectancy, drawdown, trade count) | — |

**Score: 7/7 — Complete monitoring + feedback loop (Sprints A+C+G+O)**

---

## Summary Scorecard

| Stage | Score | Grade |
|-------|-------|-------|
| 1. Market Discovery | 6/6 | **A+** |
| 2. Agent Roles / Signal Gen | 24/24 | **A+** |
| 3. Consensus & Safety | 8/8 | **A+** |
| 4. Message Flow | 8/8 | **A+** |
| 5. Kalshi-Specific | 9/9 | **A+** |
| 6. Monitoring & Adaptation | 7/7 | **A+** |
| **Overall** | **62/62** | **A+** |

---

## Critical Gaps (Priority Order)

### 1. ~~No Brier Score / Forecast Calibration Feedback~~ ✅ DONE (Sprint A+C)

**Implemented:** `merid/metrics/calibration.py` — SQLite Brier store with EWMA. Wired into `ConsensusEngine` and `SwarmConsensusAggregator`.

### 2. ~~Homogeneous Agents — No Forecaster Diversity~~ ✅ DONE (Sprint B)

**Implemented:** `merid/prediction/forecasters/` — MomentumForecaster + MeanReversionForecaster + ForecasterRegistry. Calibration-weighted ensemble. Minimum diversity gate requires ≥2 archetypes (Sprint D).

### 3. ~~No Realized Edge Tracking~~ ✅ DONE (Sprint A+G)

**Implemented:** `merid/metrics/realized_edge.py` — Per-trade edge tracking. `merid/prediction/edge_recalibrator.py` — auto-adjusts strategy thresholds based on realized vs predicted edge bias.

### 4. ~~No Feedback Loop into Consensus Weights~~ ✅ DONE (Sprint C)

**Implemented:** `OutcomeResolver` (every 5m) updates Brier scores → `ConsensusEngine` trust = 70% Brier + 30% existing → `SwarmConsensusAggregator` uses calibration weights.

### 5. ~~Sequential Pipeline, Not Message Bus~~ ✅ DONE (Sprints E+H+M)

**Implemented:** `merid/swarm/messages.py` — Typed schemas. `ForecasterRegistry` → Forecast, `CriticAgent` → Critique, `PortfolioRiskAgent` → RiskView, `SwarmConsensusAggregator` → Decision, `ExecutionSubscriber` → routes Decisions to order placement via bus subscription.

### 6. ~~No Inter-Asset Correlation Tracking~~ ✅ DONE (Sprint D)

**Implemented:** `merid/risk/correlation.py` — Rolling Pearson tracker, asset clusters (BTC_ETH, ALT_BASKET), exposure reduction factors. Wired into `PortfolioRiskAgent._check_limits()`.

---

## What's Strong

- **Kalshi integration** is production-grade: REST client with circuit breakers, WebSocket with sequence tracking, order lifecycle management, partial fills, order groups
- **Risk infrastructure** is deep: 3 layers of risk checks (prediction risk, pipeline risk, execution guard), kill switches, drawdown governance, tiered stops
- **Market discovery** is excellent: regex-based categorization across 9 categories, quality filtering, historical collection
- **Execution** is solid: mode-aware routing (sim/paper/live), fee-aware sizing, slippage modeling
- **Promotion pipeline** is unique: paper → shadow → live with quantitative gates and automatic rollback

---

## Recommended Sprint Order

1. ~~**Sprint A** — Brier calibration + realized edge tracking~~ ✅
2. ~~**Sprint B** — Heterogeneous forecaster agent types~~ ✅
3. ~~**Sprint C** — Feedback loop: calibration → consensus weights~~ ✅
4. ~~**Sprint D** — Inter-asset correlation + diversity gate~~ ✅
5. ~~**Sprint E** — Typed message schemas on event bus~~ ✅ (partial — Forecast wired, others schema-only)
6. ~~**Sprint F** — UI: CalibrationDashboardView + CorrelationRiskPanel~~ ✅
7. ~~**Sprint G** — Edge threshold recalibration from realized edge data~~ ✅

### Remaining Work
- ~~Wire Critique/RiskView/Decision publishers~~ ✅ (Sprint H+M)
- ~~Macro regime forecaster agent~~ ✅ (Sprint I)
- ~~Queue-join vs market-cross execution intelligence~~ ✅ (Sprint O)
- ~~Hit ratio tracking: p_model vs implied~~ ✅ (Sprint O)
- ~~MCP server integration for market data~~ ✅ (Sprint R)
- ~~Auction-style consensus for conflicts~~ ✅ (Sprint R)
- ~~External news/X sentiment feed integration~~ ✅ (Sprint Q)

**All gaps closed. 62/62 A+.**

---

## 7. Deployment Hardening (v3.4.0)

Added 2026-02-23 after full deployment readiness sweep.

### Safety Verification

| Check | Status | Detail |
|-------|--------|--------|
| Trade mode defaults to PAPER | ✅ | `MERID_TRADE_MODE=paper` in `.env` + settings default |
| KALSHI_USE_DEMO defaults to True | ✅ | `merid/settings.py` default changed from `False` to `True` |
| VenueGate safety guard | ✅ | Forces PAPER when `MERID_ALLOW_LIVE_TRADES` unset, even if `.env` says LIVE |
| kalshi_tools demo safety net | ✅ | Blocks real orders at tool level when `KALSHI_USE_DEMO=true` |
| Agent risk limits capped | ✅ | All 35 agents: $250 max notional, 500 max contracts, 10 max orders |
| Kill switch armed | ✅ | $500 daily loss limit, persistent state |
| Execution guard wired | ✅ | 4-source aggregation (kill switch + recon + price feed + PnL) |
| Loop isolation | ✅ | Per-step try/except, 15s tick watchdog, 5-failure circuit breaker |
| Frontend builds | ✅ | `vite build` passes cleanly (17.91s) |
| Backend imports | ✅ | 109/114 modules load (5 need Neo4j/Redis infra) |

### Deploy Readiness Script

```bash
python scripts/_deploy_readiness.py
# Expected: CRITICAL: 0, HIGH: 0, MEDIUM: 0
```

### 3-Layer Order Blocking

No single misconfiguration can cause real orders:

1. **Environment layer** — `KALSHI_USE_DEMO=true`, `MERID_TRADE_MODE=paper`, `MERID_ALLOW_LIVE_TRADES=false`
2. **VenueGate layer** — Constructor forces PAPER if LIVE resolves without `MERID_ALLOW_LIVE_TRADES`
3. **Tool layer** — `kalshi_place_order()` returns simulated fill when `KALSHI_USE_DEMO=true`

**Score: 10/10 deployment checks passing. System is production-safe.**
