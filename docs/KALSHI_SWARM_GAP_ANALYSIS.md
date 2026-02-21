# MERID — Kalshi Swarm Workflow Gap Analysis

**Date:** 2026-02-21
**Scope:** Audit MERID codebase against canonical Kalshi swarm workflow checklist

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
| MCP server integration | ❌ | Not implemented | Could use mcpmarket.com Kalshi MCP server as alternative data source |

**Score: 5/6 — Strong**

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
| Multiple different models | 🟡 | `edge_model.py` combines 3 signal sources (spot-relative, spread-based, volume/OI) in one ensemble. `sentiment.py` provides fear/greed index. But these are **one model, not competing agents**. | Agents are **homogeneous** — all 20 cells run the same `KalshiStrategy` + `EdgeModel`. No dedicated news/macro/orderbook-microstructure forecaster agents. |
| Per-market output: p_model, confidence, features | 🟡 | `EdgePrediction` dataclass has `probability`, `confidence`, `source`, `components`. `StrategySignal` has `edge`, `confidence`, `action`. | Output is consumed internally per-agent, not published as typed `Forecast` messages to a shared bus. |
| Time-series model | 🟡 | Spot-relative model uses live price vs strike with vol adjustment | Not a dedicated ARIMA/GARCH/ML time-series agent |
| Orderbook microstructure model | 🟡 | `sentiment.py` uses book imbalance as a signal component, `liquidity_monitor.py` tracks spread/depth | Not a standalone forecaster agent |
| Macro regime model | ❌ | No macro regime detection agent | Missing |
| News/X sentiment model | 🟡 | `sentiment.py` exists but derives from Kalshi orderflow only, not from external news/social feeds | External news/X sentiment feeds not wired |

### Critic / Sanity Agents

| Requirement | Status | MERID Implementation | Gap |
|-------------|--------|---------------------|-----|
| Detect stale data | ✅ | `core/feed_staleness_monitor.py`, `merid/signals/drift.py` — CQI tracks data freshness | — |
| Detect arbitrage mismatches | ✅ | `merid/signals/arb_scanner.py` — cross-market arb detection | — |
| Detect impossible probabilities | 🟡 | `strategy.py` checks for arb across multi-outcome contracts | No dedicated critic agent; checks are inline in strategy |
| Detect illiquid markets | ✅ | `market_filter.py` quality gates + `liquidity_monitor.py` real-time alerting | — |
| Veto/down-weight forecaster outputs | 🟡 | Risk agent VETO exists in `ConsensusEngine`. `PortfolioRiskAgent` can pause agents. | No dedicated critic agent that down-weights specific forecaster outputs |

### Risk Agents

| Requirement | Status | MERID Implementation | Gap |
|-------------|--------|---------------------|-----|
| Per-market edge (vs implied Kalshi probability) | ✅ | `edge_model.py` + `strategy.py` — computes edge = model_prob − implied_prob | — |
| Kelly fraction | ✅ | `kalshi_risk.py` — fee-aware Kelly. `position_sizer.py` — fractional Kelly with PF gates | — |
| Exposure vs caps | ✅ | `portfolio_risk_agent.py` — per-asset notional caps. `execution_guard.py` — per-domain daily caps | — |
| Correlation with existing book | ❌ | Per-asset caps exist but no inter-asset **correlation** computation | Missing: should compute BTC/ETH correlation to avoid concentrated crypto exposure |
| Per-category risk | ✅ | `kalshi_risk.py` — `dynamic_position_sizes()` has `category_cap_pct`. Per-domain limits in pipeline risk manager | — |
| Daily loss tracking | ✅ | `kalshi_risk.py`, `paper_session.py`, `execution_guard.py` — all track daily loss with kill switch | — |
| Drawdown monitoring | ✅ | `paper_session.py` — tiered drawdown governance (warning 5%, downsize 8%, halt 12%) | — |

### Supervisor / Consensus Agent

| Requirement | Status | MERID Implementation | Gap |
|-------------|--------|---------------------|-----|
| Ingests all forecasts + risk views | 🟡 | `ConsensusCoordinatorAgent` collects votes. `MeridLoop` runs consensus step. | Forecasts are not published as typed messages; the loop orchestrates sequentially |
| Weighted vote consensus | ✅ | `ConsensusEngine` — trust × energy × confidence weighted voting | — |
| Minimum diversity requirement | ❌ | No check that N different model types contributed | Missing |
| Outputs BUY/SELL/SKIP + size | ✅ | `ConsensusResult` with decision + `StrategySignal` with action + size | — |

**Score: 15/24 items fully implemented — Moderate with clear gaps**

---

## 3. Consensus & Safety Patterns

| Requirement | Status | MERID Implementation | Gap |
|-------------|--------|---------------------|-----|
| Weighted majority vote | ✅ | `ConsensusEngine` — trust-weighted voting with 2/3 quorum | — |
| Weight by historical Brier score | ❌ | **No Brier score computation anywhere in the codebase.** Trust scores are static defaults. | **Critical gap** — agents are not scored by forecast accuracy |
| Minimum diversity of agents | ❌ | No diversity check | Missing |
| Auction-style consensus for conflicts | ❌ | Only weighted vote implemented | Nice-to-have |
| Pre-trade risk checks | ✅ | `PredictionMarketRisk` — 10-point check. `GlobalRiskManager` — 7-point check. `ExecutionGuard` — 5-layer check. | — |
| Post-trade monitoring (drawdowns, stop-rules) | ✅ | `stop_loss.py` — binary-aware stops. `paper_session.py` — drawdown governance. `DrawdownGovernor` in pipeline. | — |
| Supervisor can override/down-weight aggressive agents | ✅ | `PortfolioRiskAgent` can pause individual agents. Kill switch halts all. | — |
| Global kill switch | ✅ | `ExecutionGuard` — global + per-domain kill switch, persistent to disk | — |

**Score: 5/8 — Solid safety, weak on calibration feedback**

---

## 4. Message Flow

| Plane | Status | MERID Implementation | Gap |
|-------|--------|---------------------|-----|
| **Data plane** — Market/orderbook/trades broadcast to all forecasters | ✅ | `ws.py` + `ws_bridge.py` — real-time Kalshi data. `market_catalog.py` for REST. `order_router.py` WS channel constants for price/trade/orderbook/fill events | — |
| **Data plane** — Portfolio broadcast to risk and supervisor | ✅ | `portfolio_risk_agent.py` fetches positions/balance. `MeridLoop` reconciliation step. | — |
| **Decision plane** — Forecasters publish typed `Forecast` messages | ❌ | Agents use `strategy.evaluate()` internally. No shared typed `Forecast` schema on a bus. | **Architectural gap** — agents don't publish independent forecasts to a shared topic |
| **Decision plane** — Critics publish typed `Critique` messages | ❌ | Critic checks are inline, not published as typed messages | Missing |
| **Decision plane** — Risk publishes typed `RiskView` messages | 🟡 | `RiskContext` exists as a system-wide snapshot but not published per-market as typed messages | Partial |
| **Decision plane** — Supervisor emits `Decision` | 🟡 | `ConsensusResult` exists but is consumed within the loop, not published on a bus | Partial |
| **Execution plane** — Execution agent subscribes to Decision | 🟡 | `order_router.py` handles execution but is called directly by the loop, not via pub/sub | Sequential, not event-driven |
| **Feedback plane** — Fills/PnL/slippage feed back into agent scores | 🟡 | `paper_session.py` tracks per-cell PnL. `performance_comparator.py` compares stages. But **feedback doesn't update consensus weights**. | Missing: no closed-loop weight update |

**Score: 3/8 — Sequential pipeline, not a true message bus**

---

## 5. Kalshi-Specific Nuances

| Requirement | Status | MERID Implementation | Gap |
|-------------|--------|---------------------|-----|
| Binary contract awareness | ✅ | Entire system designed around binary $1 payout contracts | — |
| Fee schedule modeling | ✅ | `kalshi_risk.py` — tiered 7%/5%/3% schedule, fee-aware Kelly | — |
| Time-to-expiry behavior | ✅ | `strategy.py` — `ExpiryPhase` enum (early/mid/late/terminal) with different edge thresholds per phase | — |
| Category-specific rules | ✅ | `market_catalog.py` categorization + per-category risk caps | — |
| Live orderbook awareness | ✅ | `liquidity_monitor.py` — spread/depth alerting. `market_filter.py` — spread gates | — |
| Avoid crossing wide spreads | 🟡 | `market_filter.py` gates on max_spread. But execution doesn't decide between "cross spread" vs "join queue" | No queue-join vs market-cross intelligence |
| Respect API rate limits | ✅ | `client.py` — circuit breaker, retry with backoff, concurrency cap (10 concurrent requests) | — |
| Partial fill handling | ✅ | `order_manager.py` — full lifecycle tracking, incremental fill events, timeout cancels | — |
| Order group support | ✅ | `order_group_manager.py` + `order_group_lifecycle.py` + `order_group_recovery.py` | — |

**Score: 8/9 — Very strong**

---

## 6. Monitoring & Adaptation

| Requirement | Status | MERID Implementation | Gap |
|-------------|--------|---------------------|-----|
| Fill quality tracking | ✅ | `order_manager.py` — fill events with price/size/fee. `metrics.py` — latency histograms | — |
| Hit ratio tracking | 🟡 | Win/loss tracked in `paper_session.py` and `performance_comparator.py` | Not specifically "did our p_model beat implied prob" |
| Realized edge tracking | ❌ | No module computes (predicted edge − actual outcome) | **Key gap** for measuring forecast quality |
| PnL tracking | ✅ | `paper_session.py` — per-cell, per-cluster, daily/weekly PnL. `performance_comparator.py` — backtest vs paper vs live | — |
| Agent performance metrics | ✅ | `agent_gauntlet.py` — SLO-based scoring (liveness, latency, signal quality, risk compliance, fill quality, PnL) | — |
| Feed metrics back into consensus weights | ❌ | **No feedback loop.** Performance metrics exist but don't adjust agent trust scores or consensus weights. | **Critical gap** — static weights means no learning |
| Promotion/demotion logic | ✅ | `auto_promoter.py` — paper → shadow → live promotion with rollback gates (PF, expectancy, drawdown, trade count) | — |

**Score: 4/7 — Good monitoring, no feedback loop**

---

## Summary Scorecard

| Stage | Score | Grade |
|-------|-------|-------|
| 1. Market Discovery | 5/6 | **A** |
| 2. Agent Roles / Signal Gen | 15/24 | **C+** |
| 3. Consensus & Safety | 5/8 | **B−** |
| 4. Message Flow | 3/8 | **D** |
| 5. Kalshi-Specific | 8/9 | **A** |
| 6. Monitoring & Adaptation | 4/7 | **C+** |
| **Overall** | **40/62** | **C+** |

---

## Critical Gaps (Priority Order)

### 1. No Brier Score / Forecast Calibration Feedback ❌

**Impact:** Without calibration scoring, all agents have equal voice regardless of accuracy. The swarm can't learn.

**What's needed:**
- Track each agent's probability predictions vs actual outcomes
- Compute rolling Brier score per agent per category
- Use Brier score as consensus weight multiplier
- Files to create: `merid/prediction/calibration.py`

### 2. Homogeneous Agents — No Forecaster Diversity ❌

**Impact:** All 20 grid cells run the same `KalshiStrategy` + `EdgeModel`. There's no wisdom-of-crowds benefit because there's only one crowd.

**What's needed:**
- At minimum 3-4 heterogeneous forecaster types:
  - **Spread/orderbook microstructure** (already partially in `edge_model.py`)
  - **Macro regime** (new — Fed rate, CPI surprise, VIX-equivalent)
  - **Volume/momentum** (partially in `sentiment.py` but not a standalone forecaster)
  - **Mean-reversion/arbitrage** (partially in `strategy.py` arb checks)
- Each outputs typed `{market, p_model, confidence, model_id}`
- Consensus layer aggregates across model types

### 3. No Realized Edge Tracking ❌

**Impact:** Can't measure if your edge estimates are actually profitable after fees.

**What's needed:**
- For each trade: record `predicted_edge` at entry time
- At settlement: compute `realized_edge = actual_outcome − implied_prob_at_entry`
- Track `predicted_edge − realized_edge` as forecast error
- Use this to recalibrate edge thresholds in `strategy.py`

### 4. No Feedback Loop into Consensus Weights ❌

**Impact:** The system monitors but doesn't adapt. Agent trust scores stay at defaults forever.

**What's needed:**
- After each settlement batch:
  - Update per-agent Brier scores
  - Recompute trust scores proportional to inverse Brier
  - Promote/demote agents in the consensus weight table
- Wire into `ConsensusEngine.trust_scores`

### 5. Sequential Pipeline, Not Message Bus 🟡

**Impact:** Agents can't operate independently or asynchronously. Everything goes through the MeridLoop tick.

**What's needed (lower priority):**
- Define typed message schemas: `Forecast`, `Critique`, `RiskView`, `Decision`
- Publish to `core/streaming_bus.py` channels
- Have supervisor agent consume from bus instead of sequential calls
- This is architectural — lower priority than the calibration gaps

### 6. No Inter-Asset Correlation Tracking ❌

**Impact:** Could take correlated positions in BTC and ETH without recognizing the overlap.

**What's needed:**
- Compute rolling correlation between assets (BTC/ETH, SOL/BTC, etc.)
- Reduce combined exposure when correlation is high
- Wire into `PortfolioRiskAgent` or `kalshi_risk.py`

---

## What's Strong

- **Kalshi integration** is production-grade: REST client with circuit breakers, WebSocket with sequence tracking, order lifecycle management, partial fills, order groups
- **Risk infrastructure** is deep: 3 layers of risk checks (prediction risk, pipeline risk, execution guard), kill switches, drawdown governance, tiered stops
- **Market discovery** is excellent: regex-based categorization across 9 categories, quality filtering, historical collection
- **Execution** is solid: mode-aware routing (sim/paper/live), fee-aware sizing, slippage modeling
- **Promotion pipeline** is unique: paper → shadow → live with quantitative gates and automatic rollback

---

## Recommended Sprint Order

1. **Sprint A** — Brier calibration + realized edge tracking (unlocks learning)
2. **Sprint B** — 2-3 heterogeneous forecaster agent types (unlocks diversity)
3. **Sprint C** — Feedback loop: calibration → consensus weights (closes the loop)
4. **Sprint D** — Inter-asset correlation in risk layer
5. **Sprint E** — Typed message schemas on event bus (architectural improvement)
