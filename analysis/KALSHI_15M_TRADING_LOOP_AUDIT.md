# Kalshi 15m Trading Loop Audit - Component Mapping

## Executive Summary

This document provides a comprehensive mapping of MERID components to the 5-stage trading loop for BTC/ETH/SOL/XRP/DOGE 15-minute Kalshi contracts. The audit systematically verifies data flow from market ingestion through post-trade lifecycle management.

**Scope:** BTC, ETH, SOL, XRP, DOGE on 15m Kalshi contracts  
**Audit Date:** 2025-01-XX  
**Version:** 1.0

---

## Stage 1: Market and Data Layer

### 1.1 Kalshi Market Lifecycle

| Component | Module | File | Responsibility | Status |
|-----------|--------|------|----------------|--------|
| Market Discovery | KalshiMarketCatalog | `merid/event_venues/kalshi/market_catalog.py` | Fetches active markets from Kalshi REST API, enriches with asset/timeframe tags | ✅ Verified |
| Market Categorization | KalshiMarketCatalog | `merid/event_venues/kalshi/market_catalog.py` | Categorizes markets by asset (BTC/ETH/SOL/XRP/DOGE) and timeframe (15m/1h/daily/weekly) | ✅ Verified |
| Series Resolution | MarketSelector | `merid/event_venues/kalshi/market_selector.py` | Maps agent names to series tickers (e.g., KXBTC-15M) | ✅ Verified |
| Lifecycle State Tracking | ContractState | `merid/prediction/model.py` | Tracks market states: LISTED → TRADING → CLOSING → CLOSED → SETTLED | ✅ Verified |

### 1.2 Data Feeds

| Component | Module | File | Data Source | Update Frequency | Status |
|-----------|--------|------|-------------|------------------|--------|
| WebSocket Bridge | KalshiWebSocketBridge | `merid/event_venues/kalshi/ws_bridge.py` | Kalshi WebSocket (real-time orderbook, trades, fills) | Real-time | ✅ Verified |
| REST Market Data | KalshiMarketCatalog | `merid/event_venues/kalshi/market_catalog.py` | Kalshi REST API (market list, volume, OI) | Periodic (configurable) | ✅ Verified |
| Orderbook Snapshots | KalshiMarketStateStore | `merid/event_venues/kalshi/market_state.py` | REST bootstrap + WS deltas | Real-time | ✅ Verified |
| Spot Price Feed | LivePriceFeed | `data/live_price_feed.py` | Coinbase Advanced Trade (BTC-USD, ETH-USD, etc.) | Polling | ✅ Verified |
| Sentiment Feed | SentimentStore | `merid/sentiment/sentiment_store.py` | Finnhub news/social sentiment | Periodic | ✅ Verified |

### 1.3 Preprocessing

| Component | Module | File | Transformation | Status |
|-----------|--------|------|----------------|--------|
| Symbol Normalization | extract_asset_from_ticker | `merid/prediction/trading_agent.py` | KXBTC15M-... → BTC | ✅ Verified |
| Timeframe Normalization | extract_timeframe_from_ticker | `merid/prediction/trading_agent.py` | KXBTC-15M → 15m | ✅ Verified |
| Orderbook Merging | MultiMarketOrderbook | `merid/event_venues/kalshi/market_state.py` | REST snapshot + WS deltas → unified book | ✅ Verified |
| Quote Health Validation | QuoteHealth | `merid/event_venues/kalshi/market_state.py` | Staleness, source confidence checks | ✅ Verified |
| Asset/Timeframe Filtering | _ALLOWED_SYMBOLS | `merid/event_venues/kalshi/ws_bridge.py` | Whitelist: BTC, ETH, SOL, XRP, DOGE | ✅ Verified |

**Key Constants:**
- `_ALLOWED_SYMBOLS`: {"BTC", "ETH", "SOL", "XRP", "DOGE"}
- `EXECUTION_TIMEFRAMES`: {"15m"} (FATAL gate for execution)
- `MAX_BOOK_STALENESS_MS`: 30000 (30s max staleness)
- `MIN_HEALTHY_BOOKS_FOR_TRADING`: 3 (60% quorum for 5 markets)

---

## Stage 2: Signal and Modeling Stack

### 2.1 Feature Construction

| Component | Module | File | Features | Status |
|-----------|--------|------|----------|--------|
| Crypto Features | CryptoFeatures | `merid/signals/crypto_features.py` | Price/volatility, moneyness, time-to-expiry, mean-reversion | ✅ Verified |
| 15m Indicators | Crypto15mIndicators | `merid/signals/crypto_15m_indicators.py` | 15m-specific technical indicators | ✅ Verified |
| Spot-to-Strike Distance | KalshiEdgeMetrics | `merid/prediction/trading_agent.py` | delta_pct, delta_bps, z_score (sigma-normalized) | ✅ Verified |
| Sentiment Features | SentimentScore | `merid/sentiment/sentiment_scoring_service.py` | Local, category, global sentiment scores | ✅ Verified |
| Volatility Band | CryptoVolBridge | `merid/signals/crypto_pm_vol_bridge.py` | Realized vol band → sizing multiplier | ✅ Verified |

### 2.2 Predictive Model

| Component | Module | File | Output | Status |
|-----------|--------|------|--------|--------|
| Implied Probability | PredictionMarketModel | `merid/prediction/model.py` | q = P (market-implied YES probability) | ✅ Verified |
| Model Probability | PredictionMarketModel | `merid/prediction/model.py` | p_hat (MERID's estimated probability) | ✅ Verified |
| Edge Estimation | EdgeEstimate | `merid/prediction/model.py` | raw_edge = p_hat - q, net_edge after fees/slippage | ✅ Verified |
| Spot-Relative Model | PredictionMarketModel | `merid/prediction/model.py` | Spot-distance-based probability nudge | ✅ Verified |
| Strike Selection | KalshiStrikeSelector | `merid/prediction/kalshi_strike_selector.py` | ATM band validation, deep-OTM rejection | ✅ Verified |

**Key Constants:**
- `ASSET_VOL_SCALE_15M`: BTC=0.010, ETH=0.012, SOL=0.016, XRP=0.018, DOGE=0.022
- `MAX_DELTA_PCT`: BTC=0.04, ETH=0.05, SOL=0.06, XRP=0.065, DOGE=0.065
- `MAX_Z_DISTANCE`: 0.75 (sigma max)
- `Z_NEAR_THRESHOLD`: 0.50

### 2.3 Strategy Layer

| Component | Module | File | Logic | Status |
|-----------|--------|------|-------|--------|
| Edge Thresholds | KalshiStrategy | `merid/prediction/strategy.py` | Time-to-expiry aware min edge (early/mid/late/terminal) | ✅ Verified |
| Position Sizing | KalshiStrategy | `merid/prediction/strategy.py` | Kelly-based sizing with bankroll derivation | ✅ Verified |
| Sentiment Gating | StrategyConfig | `merid/prediction/strategy.py` | contrarian_sentiment_min, sentiment_mode (gating/feature_only) | ✅ Verified |
| Volatility Breakout | StrategyConfig | `merid/prediction/strategy.py` | vol_breakout_neutral_low/high | ✅ Verified |
| Market Making | StrategyConfig | `merid/prediction/strategy.py` | mm_max_spread_cents, mm_target_spread_cents | ✅ Verified |

**Key Config (from kalshi_distance.yaml):**
- `min_edge_near`: BTC=0.055, ETH=0.055, SOL=0.060, XRP=0.060, DOGE=0.065
- Phase multipliers: EARLY=1.6x, MID=1.2x, LATE=1.0x, TERMINAL=2.0x
- `min_confidence`: 0.58 (58% - conservative sure bet)
- `kelly_fraction`: 0.20 (fifth-Kelly)

---

## Stage 3: EV Computation and Gating

### 3.1 EV Calculation

| Component | Module | File | Formula | Status |
|-----------|--------|------|--------|--------|
| Edge Metrics | KalshiEdgeMetrics | `merid/prediction/trading_agent.py` | ev_gross = model_prob - kalshi_price | ✅ Verified |
| Fee Drag | KalshiEdgeMetrics | `merid/prediction/trading_agent.py` | fee = 0.07 * P * (1-P) per contract | ✅ Verified |
| Net EV | KalshiEdgeMetrics | `merid/prediction/trading_agent.py` | ev_net = ev_gross - fee | ✅ Verified |
| EV per Contract | KalshiEdgeMetrics | `merid/prediction/trading_agent.py` | Scaled by contract count | ✅ Verified |

### 3.2 Global and Terminal EV Guards

| Component | Module | File | Guard Logic | Status |
|-----------|--------|------|------------|--------|
| Asset Whitelist | check_execution_guards | `merid/prediction/trading_agent.py` | asset ∈ {BTC, ETH, SOL, XRP, DOGE} | ✅ Verified |
| Timeframe Gate | check_execution_guards | `merid/prediction/trading_agent.py` | timeframe == "15m" (FATAL for execution) | ✅ Verified |
| Distance Cap | check_execution_guards | `merid/prediction/trading_agent.py` | |delta_pct| ≤ MAX_DELTA_PCT[asset] | ✅ Verified |
| Sigma Distance | check_execution_guards | `merid/prediction/trading_agent.py` | |z_score| ≤ MAX_Z_DISTANCE | ✅ Verified |
| Edge Floor | check_execution_guards | `merid/prediction/trading_agent.py` | edge ≥ min_edge_for_phase | ✅ Verified |
| Terminal Phase Guard | _get_min_edge_for_phase | `merid/prediction/strategy.py` | 2x edge multiplier in terminal phase | ✅ Verified |

**Key Guards:**
- `ALLOWED_ASSETS`: {"BTC", "ETH", "SOL", "XRP", "DOGE"}
- `EXECUTION_TIMEFRAMES`: {"15m"} (signal-only for other timeframes)
- Terminal phase: < 1h to expiry, 2x edge threshold

### 3.3 Sentiment Mode

| Component | Module | File | Mode | Status |
|-----------|--------|------|------|--------|
| Sentiment Mode | StrategyConfig | `merid/prediction/strategy.py` | "gating" (can block), "feature_only" (no block), "disabled" | ✅ Verified |
| Gating Enabled | SENTIMENT_GATING_ENABLED | `merid/prediction/strategy.py` | Env: MERID_SENTIMENT_MODE | ✅ Verified |
| Contrarian Threshold | contrarian_sentiment_min | `merid/prediction/strategy.py` | 15.0 (lowered from 35.0 for realistic signals) | ✅ Verified |
| Model Gap Threshold | contrarian_model_gap_min | `merid/prediction/strategy.py` | 0.10 | ✅ Verified |

**Important:** In `feature_only` mode, sentiment affects model probabilities but CANNOT block trades post-EV. Only EV + risk constraints determine trade approval.

---

## Stage 4: Execution Engine and Kalshi Interaction

### 4.1 Order Construction

| Component | Module | File | Order Fields | Status |
|-----------|--------|------|-------------|--------|
| Order Intent | OrderIntent | `merid/event_venues/kalshi/order_router.py` | ticker, side, action, price_cents, count, edge_pct, confidence | ✅ Verified |
| Order Result | OrderResult | `merid/event_venues/kalshi/order_router.py` | success, filled_count, avg_price_cents, order_id, reason | ✅ Verified |
| TIF Resolution | _resolve_tif | `merid/event_venues/kalshi/order_router.py` | IOC if seconds_to_expiry < IOC_AUTO_BELOW_SECONDS | ✅ Verified |
| Client Order ID | route_order_async | `merid/event_venues/kalshi/order_router.py` | Deterministic UUID suffix for idempotency | ✅ Verified |

### 4.2 Routing to Kalshi

| Component | Module | File | Path | Status |
|-----------|--------|------|------|--------|
| Order Router | route_order_async | `merid/event_venues/kalshi/order_router.py` | Single chokepoint for all orders | ✅ Verified |
| Caller Authorization | _is_authorized_caller | `merid/event_venues/kalshi/order_router.py` | Whitelist: trading_agent, tests, governance only | ✅ Verified |
| Mode Routing | TradingMode | `merid/prediction/trading_mode.py` | mock → paper → live | ✅ Verified |
| Venue Gate | VenueGate | `merid/prediction/venue_gate.py` | Per-venue mode gating | ✅ Verified |
| Global Execution Guard | GlobalExecutionGuard | `merid/guards/global_execution_guard.py` | 2% bankroll cap, rate limiting | ✅ Verified |

**Critical Security:** Only `merid.prediction.trading_agent` is authorized to execute trades. All other agents are SIGNAL-ONLY and must route through trading_agent.

### 4.3 Slippage and Micro-Logic

| Component | Module | File | Logic | Status |
|-----------|--------|------|-------|--------|
| Paper Slippage | PAPER_SLIPPAGE_BPS | `merid/event_venues/kalshi/order_router.py` | 8.0 bps default (env: MERID_KALSHI_PAPER_SLIPPAGE_BPS) | ✅ Verified |
| Partial Fill Prob | PAPER_PARTIAL_FILL_PROB | `merid/event_venues/kalshi/order_router.py` | 0.35 (35% chance) | ✅ Verified |
| Min Fill Ratio | PAPER_MIN_FILL_RATIO | `merid/event_venues/kalshi/order_router.py` | 0.40 (40% minimum) | ✅ Verified |
| Spread Guard | max_spread_cents | `merid/prediction/risk.py` | Reject if spread > 10 cents | ✅ Verified |
| Depth Check | min_depth_contracts | `merid/prediction/risk.py` | Min 5 contracts at target price | ✅ Verified |

**Order State Machine:**
new → working → filled/partially_filled → canceled/rejected

---

## Stage 5: Post-Execution and Lifecycle

### 5.1 Position and P&L Tracking

| Component | Module | File | Tracking | Status |
|-----------|--------|------|---------|--------|
| Fills Ledger | KalshiFillsLedger | `merid/event_venues/kalshi/fills_ledger.py` | Canonical fill store (HTTP + WS dual ingestion) | ✅ Verified |
| Fill Model | KalshiFill | `merid/event_venues/kalshi/fills_ledger.py` | All Kalshi fields + MERID metadata (agent_id, intent_id) | ✅ Verified |
| Position Cache | PositionCache | `merid/event_venues/kalshi/position_cache.py` | Per-market position tracking | ✅ Verified |
| P&L Computer | PortfolioPnLComputer | `merid/event_venues/kalshi/portfolio_pnl_computer.py` | Realized + unrealized P&L | ✅ Verified |
| Paper Session | PaperSession | `merid/prediction/paper_session.py` | Paper trading P&L tracking | ✅ Verified |
| Agent Performance | AgentPerformanceTracker | `merid/prediction/agent_performance_tracker.py` | Per-agent metrics (sharpe, sortino, calmar) | ✅ Verified |

### 5.2 Clearing and Settlement

| Component | Module | File | Process | Status |
|-----------|--------|------|---------|--------|
| Settlement Poller | SettlementPoller | `merid/event_venues/kalshi/settlement_poller.py` | Polls /portfolio/settlements endpoint | ✅ Verified |
| Settlement Events | SettlementEvent | `merid/event_venues/kalshi/settlement_poller.py` | Published to event bus (topic: merid.kalshi.settlements) | ✅ Verified |
| Outcome Resolution | Outcome | `merid/event_venues/kalshi/settlement_poller.py` | YES=1, NO=0, CANCELLED=-1, INVALID=-2 | ✅ Verified |
| Ticker Normalization | normalize_kalshi_ticker | `merid/event_venues/kalshi/settlement_poller.py` | Canonical format: KX{ASSET}-{TENOR} | ✅ Verified |
| Cursor Persistence | _get_redis | `merid/event_venues/kalshi/settlement_poller.py` | Redis cursor tracking for idempotency | ✅ Verified |

### 5.3 Risk and Limits

| Component | Module | File | Limits | Status |
|-----------|--------|------|-------|--------|
| Prediction Market Risk | PredictionMarketRisk | `merid/prediction/risk.py` | Per-market, per-event, portfolio-wide limits | ✅ Verified |
| Global Risk Guard | GlobalRiskGuard | `merid/guards/global_risk_guard.py` | Daily loss cap, cluster stop | ✅ Verified |
| Global Execution Guard | GlobalExecutionGuard | `merid/guards/global_execution_guard.py` | 2% bankroll cap per cycle | ✅ Verified |
| Category Exposure | CategoryExposureTracker | `merid/event_venues/kalshi/category_exposure.py` | Per-category caps (crypto, economics, etc.) | ✅ Verified |
| Drawdown Protection | drawdown_config | `merid/risk/drawdown_config.py` | 15% halt, 8% reduce sizing | ✅ Verified |
| Kill Switch | kill_switches | `merid/risk/kill_switches.py` | Emergency halt on drawdown | ✅ Verified |

**Risk Constants (from core.settings):**
- `MAX_CYCLE_RISK_PCT`: 0.02 (2% per cycle)
- `DAILY_LOSS_CAP_PCT`: 0.12 (12% daily)
- `CLUSTER_STOP_PCT`: 0.06 (6% cluster stop)

### 5.4 Logging, Monitoring, and Audit

| Component | Module | File | Logging | Status |
|-----------|--------|------|---------|--------|
| Decision Trace | DecisionTrace | `merid/event_venues/kalshi/decision_trace.py` | End-to-end trace ID (swarm → sizer → order) | ✅ Verified |
| Block Reasons | BlockReason | `merid/guards/block_reasons.py` | Canonical block reason enum + structured logging | ✅ Verified |
| Trade Notifier | TradeNotifier | `merid/alerts/trade_notifier.py` | Trade execution alerts | ✅ Verified |
| Crypto Alert Router | CryptoAlertRouter | `merid/alerts/crypto_alert_router.py` | Per-asset alert routing | ✅ Verified |
| Execution Audit | ExecutionAudit | `merid/event_venues/kalshi/execution_audit.py` | Execution path audit logging | ✅ Verified |
| Metrics Registry | get_metrics_registry | `monitoring/metrics.py` | Prometheus metrics | ✅ Verified |

**Audit Trace Fields:**
- decision_trace_id
- agent_id
- intent_id
- fill_id
- correlation_id
- timestamp
- All gate decisions with reasons

---

## Component Integration Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           STAGE 1: MARKET & DATA                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  KalshiMarketCatalog → Market Discovery & Categorization                     │
│  KalshiWebSocketBridge → Real-time orderbook/trades/fills (WS)              │
│  KalshiMarketStateStore → Orderbook snapshots (REST) + WS deltas            │
│  LivePriceFeed → Spot prices (Coinbase)                                      │
│  SentimentStore → News/social sentiment (Finnhub)                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                        STAGE 2: SIGNAL & MODELING                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  CryptoFeatures → Price/volatility, moneyness, time-to-expiry               │
│  KalshiStrikeSelector → ATM band validation, deep-OTM rejection              │
│  PredictionMarketModel → Implied prob, model prob, edge estimation           │
│  KalshiStrategy → Edge thresholds, position sizing, sentiment gating         │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                       STAGE 3: EV COMPUTATION & GATING                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  KalshiEdgeMetrics → EV calculation (gross - fees)                           │
│  check_execution_guards → Asset/tf whitelist, distance caps, edge floors     │
│  GlobalExecutionGuard → 2% bankroll cap, rate limiting                      │
│  SENTIMENT_MODE → Gating vs feature_only mode                                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                     STAGE 4: EXECUTION ENGINE                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  OrderIntent → Order construction (ticker, side, action, price, count)       │
│  route_order_async → Single chokepoint routing (caller authorization)        │
│  TradingMode → mock → paper → live routing                                   │
│  _resolve_tif → IOC if near expiry                                          │
│  PAPER_SLIPPAGE_BPS → Paper slippage simulation                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                    STAGE 5: POST-EXECUTION LIFECYCLE                         │
├─────────────────────────────────────────────────────────────────────────────┤
│  KalshiFillsLedger → Canonical fill store (HTTP + WS dual ingestion)         │
│  PositionCache → Per-market position tracking                                │
│  PortfolioPnLComputer → Realized + unrealized P&L                            │
│  SettlementPoller → Settlement polling, outcome resolution                   │
│  PredictionMarketRisk → Per-market, portfolio-wide limits                     │
│  DecisionTrace → End-to-end audit trail                                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Critical Invariants

### Production Invariants (NON-NEGOTIABLE)

1. **DATA FLOW INVARIANTS:**
   - Only subscribe to `orderbook_delta` on Kalshi WS
   - Snapshots come from REST `GET /markets/{ticker}/orderbook` ONLY
   - Every traded market MUST be bootstrapped via REST `orderbook_fp` before accepting WS deltas
   - Scope is strictly BTC/ETH/SOL/XRP/DOGE 15m, enforced at subscription, bootstrap, and apply_orderbook_message

2. **SINGLE SOURCE OF TRUTH:**
   - market_state + LocalOrderbook are the ONLY authoritative source of bid/ask/mid
   - UI/API layers MUST read from this state, not invent their own book or call Kalshi directly
   - No duplicate orderbook logic outside this module

3. **HEALTH & CIRCUIT BREAKER INVARIANTS:**
   - MAX_BOOK_STALENESS_MS = 30000 (30s maximum staleness)
   - MIN_HEALTHY_BOOKS_FOR_TRADING = 3 (60% quorum for 5 markets)
   - HEALTH_CHECK_INITIALIZED = True (book must have REST snapshot)
   - HEALTH_CHECK_FRESH = True (book must be within staleness threshold)
   - HEALTH_CHECK_BID_ASK = True (book must have valid bid < ask with non-zero sizes)
   - is_trading_enabled() enforces these thresholds

4. **EXECUTION AUTHORIZATION INVARIANTS:**
   - ONLY `merid.prediction.trading_agent` can execute trades
   - All other agents are SIGNAL-ONLY and must route through trading_agent
   - Caller whitelist enforced in `_is_authorized_caller()`
   - Direct HTTP bypass removed (use_router_percent = 100)

5. **RISK REGIME INVARIANTS:**
   - MAX_CYCLE_RISK_PCT = 0.02 (2% per cycle, unified across all modes)
   - DAILY_LOSS_CAP_PCT = 0.12 (12% daily loss cap)
   - CLUSTER_STOP_PCT = 0.06 (6% cluster stop, half of daily)
   - GlobalExecutionGuard enforces 2% bankroll cap for ALL execution paths

---

## Configuration Sources

### Single Sources of Truth

1. **Distance Config:** `config/kalshi_distance.yaml`
   - min_edge_near (per asset)
   - max_delta_pct (per asset)
   - max_z_distance
   - z_near_threshold

2. **Risk Config:** `core/settings.py`
   - MAX_CYCLE_RISK_PCT
   - DAILY_LOSS_CAP_PCT
   - CLUSTER_STOP_PCT
   - USE_TOPN_ALLOCATOR

3. **Series Mapping:** `config/kalshi_crypto_series_meta.py`
   - SERIES_META_BY_TICKER
   - infer_asset_from_kalshi_market_ticker

4. **Agent Config:** `config/kalshi_agent_grid.yaml`
   - AgentConfig.series_tickers
   - strike_selection parameters
   - strategy parameters

---

## Environment Variables

### Critical Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| MERID_SENTIMENT_MODE | "gating" | Sentiment mode (gating/feature_only/disabled) |
| MERID_PM_MAX_SPOT_AGE_SECONDS | 120 | Max spot price age for PM model |
| MERID_KALSHI_PAPER_SLIPPAGE_BPS | 8.0 | Paper slippage in basis points |
| MERID_PM_MIN_EDGE_* | Varies | Per-phase min edge (env override for YAML) |
| MERID_PM_MAX_DELTA_PCT_* | Varies | Per-asset max distance (env override for YAML) |
| MERID_PM_MAX_Z_DISTANCE | 0.75 | Sigma-based distance cap |
| MERID_PM_MIN_CONFIDENCE | 0.58 | Minimum confidence threshold |
| MERID_PM_CONTRARIAN_SENTIMENT_MIN | 15.0 | Contrarian sentiment threshold |
| KALSHI_IOC_AUTO_BELOW_SECONDS | 120.0 | Auto-IOC threshold (seconds to expiry) |
| MERID_KALSHI_MAX_REST_AGE_SECONDS | 10 | REST data staleness threshold |
| MERID_FEE_MISMATCH_THRESHOLD_PCT | 5.0 | Fee validation threshold |

---

## Next Steps

1. **Gap Analysis:** Identify missing components or incomplete implementations
2. **Bug Identification:** Document specific bugs found during audit
3. **Integration Testing:** Verify end-to-end flow for each asset/timeframe
4. **Performance Profiling:** Measure latency at each stage
5. **Documentation Updates:** Ensure all components are documented

---

## Appendix A: File Inventory

### Core Trading Loop Files

- `merid/loop.py` - Main orchestrator
- `merid/event_venues/kalshi/ws_bridge.py` - WebSocket bridge
- `merid/event_venues/kalshi/market_catalog.py` - Market discovery
- `merid/event_venues/kalshi/market_state.py` - Market state store
- `merid/event_venues/kalshi/order_router.py` - Order routing
- `merid/prediction/trading_agent.py` - Trading agent
- `merid/prediction/strategy.py` - Strategy layer
- `merid/prediction/model.py` - Predictive model
- `merid/prediction/risk.py` - Risk management
- `merid/prediction/kalshi_strike_selector.py` - Strike selection
- `merid/event_venues/kalshi/fills_ledger.py` - Fills ledger
- `merid/event_venues/kalshi/settlement_poller.py` - Settlement polling
- `merid/guards/global_execution_guard.py` - Global execution guard
- `merid/guards/global_risk_guard.py` - Global risk guard
- `merid/sentiment/sentiment_store.py` - Sentiment storage

### Configuration Files

- `config/kalshi_distance.yaml` - Distance config (single source of truth)
- `config/kalshi_agent_grid.yaml` - Agent grid configuration
- `config/kalshi_crypto_series_meta.py` - Series metadata
- `core/settings.py` - Global settings (risk regime)

### Test Files

- `tests/event_venues/kalshi/test_kalshi_market_state.py` - Market state tests
- `tests/event_venues/kalshi/test_kalshi_execution.py` - Execution tests
- `tests/prediction/test_trading_agent_surface.py` - Trading agent surface tests
- `tests/test_order_router_caller_restrictions.py` - Router authorization tests

---

**End of Component Mapping Document**
