# 15M Kalshi Crypto Trading System - Complete Setup Documentation

**Date**: 2026-07-04  
**Profile**: kalshi_crypto_15m_v2  
**Assets**: BTC, ETH, SOL, XRP, DOGE (complete crypto stack)

---

## Executive Summary

This document provides a comprehensive end-to-end overview of the 15-minute Kalshi crypto trading system setup across all 5 assets (BTC, ETH, SOL, XRP, DOGE). It covers upstream (data ingestion), midstream (signal generation and risk management), and downstream (execution and position management) components with all thresholds and configuration parameters.

**Critical Invariant**: All 5 assets are mandatory. Never skip, disable, or comment out any asset. Fix root causes instead of workarounds.

---

## Table of Contents

1. [Asset Overview](#asset-overview)
2. [Upstream Components](#upstream-components)
3. [Midstream Components](#midstream-components)
4. [Downstream Components](#downstream-components)
5. [Per-Asset Configuration](#per-asset-configuration)
6. [Threshold Matrix](#threshold-matrix)
7. [Risk Management](#risk-management)
8. [Operational Cadence](#operational-cadence)

---

## Asset Overview

### Complete Crypto Stack (5 Assets)

| Asset | Series Ticker | Agent Name | Asset Tier | Volatility Profile |
|-------|--------------|------------|------------|-------------------|
| BTC   | KXBTC15M     | BTC_15M    | Tier 1     | 45-55% vol, 1.5-3% intraday range |
| ETH   | KXETH15M     | ETH_15M    | Tier 1     | 45.2% vol (declining) |
| SOL   | KXSOL15M     | SOL_15M    | Tier 2     | 89.6% vol (increasing) |
| XRP   | KXXRP15M     | XRP_15M    | Tier 2     | ~55% vol, event-driven, beta 1.35 |
| DOGE  | KXDOGE15M    | DOGE_15M   | Tier 2     | ~100% vol, sentiment-driven, beta 2.70 |

### Asset Tier Classification

- **Tier 1 (Core Assets)**: BTC, ETH - Deeper liquidity, lower volatility, tighter thresholds
- **Tier 2 (Alt Assets)**: SOL, XRP, DOGE - Thinner books, higher volatility, looser thresholds

---

## Upstream Components

### 1. Price Feed Service

**Component**: `data/unified_spot_service.py`  
**Source**: Coinbase Public API (no auth required)  
**Assets**: BTC/USD, ETH/USD, SOL/USD, XRP/USD, DOGE/USD

**Configuration**:
- **Fetch Method**: On-demand HTTP GET with TTL caching
- **Freshness Requirement**: < 60 seconds for 15m crypto strategy
- **Cache TTL**: Configurable via `spot_sla_config.py`
- **Graceful Shutdown**: Integrated with FastAPI lifespan events

**Hard Rules**:
- PM model uses ONLY UnifiedSpotService
- Execution uses ONLY UnifiedSpotService
- Filters use ONLY UnifiedSpotService
- Basis tracker uses ONLY UnifiedSpotService

**API Endpoint**: `https://api.coinbase.com/v2/prices/{asset}-USD/spot`

---

### 2. WebSocket Bridge

**Component**: `merid/event_venues/kalshi/ws_bridge.py`  
**Purpose**: Pipes Kalshi WS events into MERID's event bus

**Event Types**:
- `kalshi:price_update` - Ticker channel quote updates
- `kalshi:trade` - Trade channel fill events
- `kalshi:orderbook_delta` - Orderbook channel updates

**Subscription Scope**: All 5 assets (KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M)

**Health Monitoring**:
- **Dead Threshold**: 60 seconds (no messages)
- **Stale Threshold**: 30 seconds (lagging)
- **Health Status**: ALIVE, STALE, DEAD
- **Metrics**: Forwarder activity, WS client activity, message counts

**Hardened Features**:
- Bounded async queue with backpressure
- Per-type event counters
- Forward-error isolation
- Exposes WS client stats for dashboards

---

### 3. Market State Store

**Component**: `merid/event_venues/kalshi/market_state.py`  
**Purpose**: Unified per-market live state management

**Production Invariants**:
1. **Data Flow**: Subscribe to `orderbook_delta` and `orderbook_snapshot` on Kalshi WS
2. **Bootstrap**: REST `GET /markets/{ticker}/orderbook` for initialization
3. **Single Source of Truth**: market_state + LocalOrderbook are authoritative
4. **Scope**: Strictly BTC/ETH/SOL/XRP/DOGE 15m

**Health Thresholds**:
- **MAX_BOOK_STALENESS_MS**: 120,000 (120 seconds)
- **MIN_HEALTHY_BOOKS_FOR_TRADING**: 3 (60% quorum for 5 markets)
- **HEALTH_CHECK_INITIALIZED**: True (must have REST snapshot)
- **HEALTH_CHECK_FRESH**: True (within staleness threshold)
- **HEALTH_CHECK_BID_ASK**: True (valid bid < ask with non-zero sizes)

**Monitoring**:
- `log_book_health()` every 60 seconds
- `/internal/kalshi_health` endpoint for detailed metrics
- Circuit breaker logs on trading state changes

---

### 4. Market Catalog

**Component**: Integrated into market state and loop  
**Refresh Rate**: Every 60 seconds  
**Scope**: All 5 assets, exactly 5 markets per asset cycle

**Liquidity Prefilters** (from profile):
- **min_volume**: 5 contracts (relaxed from default 50)
- **min_open_interest**: 1 contract (relaxed from default 10)
- **max_spread_cents**: 15 cents (unified across system)

---

## Midstream Components

### 1. Main Event Loop

**Component**: `merid/loop_15m.py`  
**Cadence**: 5 seconds  
**Profile**: kalshi_crypto_15m_v2

**Responsibilities**:
- Pull latest market state / RTI inputs
- Run 5 agents' signal + decision logic via AgentGrid.run_cycle()
- Route orders through KalshiTradingAgent / order router / risk
- Manage loop states (HALT, WAITING, IDLE, ACTIVE)

**Loop States**:
- **HALT**: infra_ready=False (system/venue broken)
- **WAITING**: infra OK, markets expected but none posted (venue lag)
- **IDLE**: infra OK, markets not expected (maintenance/off hours)
- **ACTIVE**: infra OK and >=1 strip present

**Execution Modes** (within ACTIVE):
- **NORMAL**: ready_assets_count >= 2 (full breadth, normal sizing)
- **DEGRADED**: ready_assets_count == 1 (trade single ready asset)
- **ACTIVE-HALT**: ready_assets_count == 0 while markets present (RED FLAG)
- **NONE**: set when loop_state != ACTIVE

**Asset Readiness**: MD fresh (<30s) AND book depth meets per-asset threshold

**Degraded Mode Semantics**:
- **Allowed**: Continue quoting in healthy markets, consume websockets, maintain bookkeeping, run signal generation, execute orders in deep markets
- **Disallowed**: New market onboarding, aggressive scaling, opening positions in markets failing depth checks

---

### 2. Signal Generation

**Mode**: momentum_fvg (switched from hybrid based on 2026 research)

**Momentum/FVG Parameters**:
- **RSI Thresholds**: 
  - Long: RSI > 55
  - Short: RSI < 45
- **MACD Histogram**: 
  - Long: >= 0
  - Short: <= 0
- **Order Book Imbalance (OBI)**:
  - Minimum absolute OBI: 0.25
  - Persistence minimum: 0.60 (60% consistent snapshots)
  - Persistence window: 10 seconds
  - EWMA alpha: 0.15

**Per-Asset OBI Strong Thresholds**:
- BTC: 0.55
- ETH: 0.55
- SOL: 0.45 (thinner book)
- XRP: 0.45 (thinner book)
- DOGE: 0.45 (thinner book)

**Per-Asset EWMA Alpha**:
- BTC: 0.15 (smoother, more depth)
- ETH: 0.15 (smoother, more depth)
- SOL: 0.20 (quicker reaction, less depth)
- XRP: 0.20 (quicker reaction, less depth)
- DOGE: 0.20 (quickest reaction, thinnest book)

**Fair Value Gap (FVG) Parameters**:
- **Max age**: 4 bars (60 minutes)
- **Min size**: 3 ticks
- **Min time to expiry**: 30 minutes for new entries

**Trend Confirmation**:
- **Require EMA stack**: True (fast > slow for longs)
- **Require price vs EMA50**: True

**Liquidity-Aware Size Scaling**:
- **High threshold**: 200 contracts (1.0x profile risk)
- **Medium threshold**: 80 contracts (0.75x profile risk)
- **Low threshold**: 40 contracts (0.5x profile risk)
- **Ultra-low threshold**: 25 contracts (0.25x profile risk)
- **Min threshold**: 25 contracts (0.0x - no new entries)

**Spread Gate Interaction**:
- **Spread gate cents**: 15 cents
- **Spread gate OBI persistence boost**: 0.75 (require 75% persistence if spread is wide)

---

### 3. Confidence Thresholds

**Minimum Confidence Threshold**: 0.65 (65%)
- **Increased from 0.50** based on GRDazzle research (0.75 threshold with 83.4% win rate)
- **Industry standards**: voltage-kalshi (0.55), Predict & Profit (0.30)
- **Purpose**: Improves signal quality and reduces false signals

---

### 4. Edge Bands

**Tiered Structure** (ACTUAL thresholds used):
- **Watch Band**: 4-5% edge (log only, no trading)
- **Small Band**: 5-7% edge (trade with 0.25x Kelly)
- **Standard Band**: >=7% edge (trade with 0.5x Kelly)

**Kelly Multipliers**:
- **No trade**: 0.0
- **Cautious**: 0.5
- **Quick win**: 0.6
- **Confident**: 1.0

---

## Downstream Components

### 1. Order Router

**Component**: `merid/event_venues/kalshi/order_router.py`  
**Purpose**: Mode-aware order dispatch (mock/paper/live)

**Modes**:
- **Mock**: Simulation without API calls
- **Paper**: Paper trading with risk checks
- **Live**: Real trading on Kalshi

**Profitability Enhancements**:
- **YES/NO Sum Arbitrage**: Buy both sides when YES_ask + NO_bid < 100c
- **Arbitrage threshold**: 3 cents minimum edge
- **Max size**: 10 contracts per arbitrage trade
- **Execution timeout**: 500ms

**Resting Order Tracking**:
- **Edge decay monitoring**: Auto-cancel when edge falls below threshold
- **Time limit**: Auto-cancel after max_live_seconds
- **Aggressiveness tracking**: 0.0=resting, >0.0=marketable

**Order Deduplication**:
- **Cache integration**: Prevent duplicate order submissions
- **Hash-based**: Content-based deduplication

---

### 2. Position Sizing

**Dynamic Sizing** (from profile):
- **Base contracts**: 1
- **Edge multiplier**: 0.5 contracts per 1% edge
- **Confidence multiplier**: 0.3 contracts per 1% confidence
- **Max contracts**: 3 (per trade)
- **Min contracts**: 1 (per trade)

**Order Scaling** (institutional-grade):
- **Strategy**: Adaptive (TWAP/iceberg/adaptive)
- **Min child orders**: 2
- **Max child orders**: 5
- **Time window**: 300 seconds (5 minutes)
- **Participation rate**: 10% of market volume
- **Visible pct**: 10% (iceberg)
- **Edge threshold**: 2% minimum
- **Size threshold**: 3 contracts minimum

**Fractional Contract Override**:
- **Threshold**: 0.5 (allow 1 contract if max_notional >= 50% of contract cost)
- **Purpose**: Enables trading with small bankrolls

---

### 3. Circuit Breakers

**Price Range Validation**:
- **Min price cents**: 50 cents (optimized for scaling)
- **Max price cents**: 70 cents (avoids thin high-end markets)
- **Rationale**: Mid-range prices (50-70c) have better depth for scaled child orders

**Drawdown Semantics**:
- **Time horizon**: Since process start (not rolling window)
- **PnL basis**: Equity including open positions (realized + unrealized)
- **Peak equity**: Tracks highest equity since FastAPI startup
- **Fresh start**: Resets peak equity to current equity when MERID_FRESH_START=1

**Drawdown Limits**:
- **Halt percentage**: 10% (trading halt)
- **Unwind percentage**: 15% (position unwind)

**Daily Loss Limit**:
- **Production**: 5% of bankroll
- **Test**: 10% of bankroll (relaxed for testing)

**Asset-Specific Rolling PnL Limits**:
- **BTC**: 4% (1h), 7% (4h)
- **ETH**: 4% (1h), 7% (4h)
- **SOL**: 6% (1h), 9% (4h)
- **XRP**: 6% (1h), 9% (4h)
- **DOGE**: 8% (1h), 12% (4h)

---

### 4. Exit Strategies

**Take Profit** (from agent grid):
- **Time-based R multiple**:
  - Over 7 min: 1.0x
  - Between 4-7 min: 0.75x
  - Under 4 min: 0.5x
- **Min cents**: 3 cents
- **Scale out fraction**: 0.5 (50%)
- **Trailing enabled**: True
- **Trailing activation R multiple**: 0.8
- **Trailing giveback cents**: 3 cents
- **Max round trips per contract**: 2
- **Min price move for reentry**: 5-6 cents (varies by asset)
- **Min edge after fees cents**: 2.0-2.5 cents (varies by asset)

**Trailing Stop**:
- **Enabled**: True
- **Trailing distance cents**: 5 cents
- **Min profit cents**: 12 cents
- **Activation delay sec**: 30 seconds

**Ratchet Profit Floor**:
- **Enabled**: True
- **Activation threshold cents**: 85 cents
- **Floor offset cents**: 5 cents
- **Force exit on floor breach**: True
- **Min hold after activation sec**: 30 seconds

**Staged Time Exit**:
- **Enabled**: True
- **Stages**:
  - 5 min: Close 40%
  - 10 min: Close 30%
  - 13 min: Close 30%

---

## Per-Asset Configuration

### BTC (Bitcoin)

**Series Ticker**: KXBTC15M  
**Asset Tier**: 1 (Core)  
**Volatility**: 45-55% vol, 1.5-3% intraday range

**Risk Parameters**:
- **Max notional pct**: 5% of capital
- **Max contracts**: 2
- **Min decision minute**: 2 (skip first 2 minutes)

**Edge Thresholds**:
- **Early**: 6%
- **Mid**: 6%
- **Late**: 6%
- **Terminal**: 7%

**Distance Filter**:
- **Max spot to strike pct**: 1.5% (tighter due to deep liquidity)

**Liquidity Filters**:
- **Min order book depth USD**: 1000.0
- **Min volume 24h USD**: 5000.0
- **Max skew ratio**: 0.70
- **Min depth YES**: 1 contract
- **Min depth NO**: 1 contract

**Strike Selection** (from agent grid):
- **Max spot to strike pct**: 15%
- **Target spot band pct**: 6%
- **Deep OTM allowed**: False

**15m Thresholds** (from kalshi_15m_thresholds.yaml):
- **Max spread cents**: 3 cents
- **Extreme YES price min**: 5 cents
- **Extreme YES price max**: 95 cents
- **Min depth contracts**: 50
- **Max one-sidedness ratio**: 0.70

**Take Profit Specifics**:
- **Min edge after fees cents**: 2.0 cents
- **Min price move for reentry**: 5 cents

---

### ETH (Ethereum)

**Series Ticker**: KXETH15M  
**Asset Tier**: 1 (Core)  
**Volatility**: 45.2% vol (declining due to L2 scaling maturation)

**Risk Parameters**:
- **Max notional pct**: 5% of capital
- **Max contracts**: 2
- **Min decision minute**: 2 (skip first 2 minutes)

**Edge Thresholds**:
- **Early**: 6%
- **Mid**: 6%
- **Late**: 6%
- **Terminal**: 7%

**Distance Filter**:
- **Max spot to strike pct**: 1.8% (tightened from 2.0% due to declining volatility)

**Liquidity Filters**:
- **Min order book depth USD**: 800.0
- **Min volume 24h USD**: 4000.0
- **Max skew ratio**: 0.70
- **Min depth YES**: 1 contract
- **Min depth NO**: 1 contract

**Strike Selection** (from agent grid):
- **Max spot to strike pct**: 15%
- **Target spot band pct**: 6%
- **Deep OTM allowed**: False

**15m Thresholds** (from kalshi_15m_thresholds.yaml):
- **Max spread cents**: 4 cents
- **Extreme YES price min**: 5 cents
- **Extreme YES price max**: 95 cents
- **Min depth contracts**: 30
- **Max one-sidedness ratio**: 0.75

**Take Profit Specifics**:
- **Min edge after fees cents**: 2.0 cents
- **Min price move for reentry**: 5 cents

---

### SOL (Solana)

**Series Ticker**: KXSOL15M  
**Asset Tier**: 2 (Alt)  
**Volatility**: 89.6% vol (increasing due to speculative capital rotation)

**Risk Parameters**:
- **Max notional pct**: 5% of capital
- **Max contracts**: 2
- **Min decision minute**: 3 (skip first 3 minutes - thinner book, more noise)

**Edge Thresholds**:
- **Early**: 8%
- **Mid**: 8%
- **Late**: 8%
- **Terminal**: 9%

**Distance Filter**:
- **Max spot to strike pct**: 2.5% (appropriate for high volatility)

**Liquidity Filters**:
- **Min order book depth USD**: 500.0
- **Min volume 24h USD**: 3000.0
- **Max skew ratio**: 0.65 (stricter due to higher volatility)
- **Min depth YES**: 1 contract
- **Min depth NO**: 1 contract

**Strike Selection** (from agent grid):
- **Max spot to strike pct**: 15%
- **Target spot band pct**: 6%
- **Deep OTM allowed**: False

**15m Thresholds** (from kalshi_15m_thresholds.yaml):
- **Max spread cents**: 5 cents
- **Extreme YES price min**: 8 cents (more lenient)
- **Extreme YES price max**: 92 cents
- **Min depth contracts**: 20
- **Max one-sidedness ratio**: 0.80

**Take Profit Specifics**:
- **Scale out fraction**: 0.6 (60%)
- **Min edge after fees cents**: 2.5 cents
- **Min price move for reentry**: 6 cents

---

### XRP (Ripple)

**Series Ticker**: KXXRP15M  
**Asset Tier**: 2 (Alt)  
**Volatility**: ~55% vol, event-driven, beta 1.35

**Risk Parameters**:
- **Max notional pct**: 5% of capital
- **Max contracts**: 2
- **Min decision minute**: 3 (skip first 3 minutes - thinner book, more noise)

**Edge Thresholds**:
- **Early**: 7%
- **Mid**: 7%
- **Late**: 7%
- **Terminal**: 8%

**Distance Filter**:
- **Max spot to strike pct**: 2.5% (tightened from 3.0% - event-driven needs precision)

**Liquidity Filters**:
- **Min order book depth USD**: 400.0
- **Min volume 24h USD**: 2500.0
- **Max skew ratio**: 0.65
- **Min depth YES**: 1 contract
- **Min depth NO**: 1 contract

**Strike Selection** (from agent grid):
- **Max spot to strike pct**: 20%
- **Target spot band pct**: 8%
- **Deep OTM allowed**: False

**15m Thresholds** (from kalshi_15m_thresholds.yaml):
- **Max spread cents**: 6 cents
- **Extreme YES price min**: 8 cents
- **Extreme YES price max**: 92 cents
- **Min depth contracts**: 15
- **Max one-sidedness ratio**: 0.85

**Take Profit Specifics**:
- **Scale out fraction**: 0.6 (60%)
- **Min edge after fees cents**: 2.5 cents
- **Min price move for reentry**: 6 cents

---

### DOGE (Dogecoin)

**Series Ticker**: KXDOGE15M  
**Asset Tier**: 2 (Alt)  
**Volatility**: ~100% vol, sentiment-driven, highest beta 2.70

**Risk Parameters**:
- **Max notional pct**: 5% of capital
- **Max contracts**: 1 (reduced from 2 due to extreme volatility)
- **Min decision minute**: 5 (skip first 5 minutes - thinnest book, most noise)

**Edge Thresholds**:
- **Early**: 8.5%
- **Mid**: 8.5%
- **Late**: 8.5%
- **Terminal**: 9.5%

**Distance Filter**:
- **Max spot to strike pct**: 2.5% (tightened from 3.0% - sentiment-driven needs precision)

**Liquidity Filters**:
- **Min order book depth USD**: 200.0 (lowest threshold)
- **Min volume 24h USD**: 1500.0
- **Max skew ratio**: 0.60 (strictest skew filter)
- **Min depth YES**: 1 contract
- **Min depth NO**: 1 contract

**Strike Selection** (from agent grid):
- **Max spot to strike pct**: 20%
- **Target spot band pct**: 8%
- **Deep OTM allowed**: False

**15m Thresholds** (from kalshi_15m_thresholds.yaml):
- **Max spread cents**: 7 cents
- **Extreme YES price min**: 10 cents (most lenient)
- **Extreme YES price max**: 90 cents
- **Min depth contracts**: 10
- **Max one-sidedness ratio**: 0.90

**Take Profit Specifics**:
- **Scale out fraction**: 0.6 (60%)
- **Min edge after fees cents**: 2.5 cents
- **Min price move for reentry**: 6 cents

---

## Threshold Matrix

### Global Guardrails (from profile)

**Pre-trade Checks**:
- **Max spread cents**: 15 cents (unified across system)
- **Max slippage cents**: 5 cents
- **Min post-fee edge**: 1.5%
- **Min time to expiry min**: 2.0 minutes (120 seconds)
- **Max dist pct trade**: 2.5%
- **Min contract price cents**: 50 cents
- **Max contract price cents**: 70 cents
- **Max same side per strip**: 5
- **Min edge per trade**: 0.8%

### Staleness Thresholds

- **Max book staleness s**: 15 seconds
- **Max quote staleness s**: 30 seconds

### Duality Validation

- **Duality tolerance cents**: 15 cents (allowed deviation from YES + NO = 100c)

### Market Lifecycle

- **Min seconds to expiry**: 150 seconds (2.5 minutes)
- **Cutoff seconds to expiry**: 60 seconds (1 minute hard cutoff)

### Volume and Open Interest

- **Min volume 24h**: 1000 ($1000 minimum 24h volume)
- **Min open interest**: 10 contracts

---

## Risk Management

### Global Capital and Cycle Risk

**Capital**: Derived from live Kalshi bankroll API (capital_usd: 0)

**Minimum Trade Size**:
- **Min notional USD**: 0.50 (micro-account adjusted)
- **Min contracts**: 1 (Kalshi venue invariant)

**Maximum Risk Per Cycle**:
- **Max cycle risk pct**: 0.5% of capital (conservative for 5-second cycles)
- **Dynamic**: Computed from live bankroll via RiskEnvelopeService

**Maximum Total Risk**:
- **Max total risk pct**: 15% total risk cap (production safety)

### Venue-Level Caps

**Max total notional pct**: 25% (sum of 5% per asset × 5 assets)

**Bankroll cap pct**: 1% of bankroll per order (Quarter Kelly for crypto)

### Category-Level Caps

**Crypto category**: 25% of bankroll (5% per asset × 5 assets)

**Correlated stack**: 15% of bankroll (BTC, ETH, SOL, XRP, DOGE treated as single position due to 0.8+ correlation)

### Per-Trade Limits

**Max notional pct**: 2% of bankroll (aligned with 2026 industry standards)

**Max contracts**: 10 (global, overridden by per-asset limits)

### Throttling (Order Rate Limits)

**Global orders window sec**: 60 seconds

**Global orders limit**: 15 orders per minute (increased from 5 for 5 assets)

**Per asset cooldown sec**: 15 seconds (reduced from 30s for 15m trading)

**Max orders per 15m window**: 5 (reduced from 15 based on 2026 research)

**Cooldown after loss cycles**: 2 cycles (30 seconds)

**Consecutive loss pause**: 3 losses (industry standard for behavioral risk control)

**Max session risk pct**: 10% (prevents overexposure in single session)

### 2026 Optimizations

**Volatility-Regime Edge Adjustment**:
- **Enabled**: True
- **Lookback days**: 30
- **Low volatility threshold**: 30% (below 30-day avg)
- **High volatility threshold**: 70% (above 30-day avg)
- **Low volatility adjustment**: -0.5% (reduce min edge)
- **High volatility adjustment**: +1.0% (increase min edge)

**Portfolio Heat Tracking**:
- **Enabled**: True
- **Calculation method**: Correlation-adjusted exposure
- **Heat threshold warning**: 70% of max adjusted exposure
- **Heat threshold critical**: 85% of max adjusted exposure
- **Warning response**: Reduce new positions by 25%
- **Critical response**: Reduce new positions by 50%

**Time-of-Day Risk Scaling**:
- **Enabled**: True
- **US market hours**: 09:30-16:00 ET (100% risk)
- **Asian session**: 20:00-02:00 ET (80% risk)
- **European session**: 02:00-09:30 ET (90% risk)
- **Weekend**: 80% risk (relaxed from 50% - use volatility regime instead)

**Multi-Timeframe Trend Filter**:
- **Enabled**: True
- **Higher timeframe**: 1h
- **Alignment mode**: Strict (only with trend)
- **Neutral size multiplier**: 0.5 (reduce size by 50% when 1h is neutral)

**Order Book Imbalance Filter**:
- **Enabled**: True
- **Strong threshold**: 0.85 (increased for crypto volatility)
- **Moderate threshold**: 0.3
- **Consistency window size**: 20
- **Min consistency pct**: 0.60
- **Max staleness ms**: 5000
- **Top levels**: 5

**News Event Avoidance**:
- **Enabled**: True
- **Avoidance window min**: 15 minutes before/after news
- **High impact events**: NFP, CPI, FOMC, GDP, PPI, Retail Sales, ISM Manufacturing, ISM Services

**Correlation Tracking**:
- **Enabled**: True
- **Threshold**: 0.5
- **Max reduction**: 0.4 (reduce to 40% at perfect correlation)
- **Window days**: 30
- **Real-time monitoring**: True
- **Threshold high**: 0.80 (treat as ONE position)
- **Threshold moderate**: 0.50 (reduce by correlation %)
- **Threshold alert**: 0.85 (alert + 50% size reduction)
- **Max correlated assets**: 3

---

## Operational Cadence

### Loop Cadence

**Main loop**: 5 seconds

**Market catalog refresh**: 60 seconds

**Fills polling**: 20 seconds

**Settlement polling**: 60 seconds

**Bankroll balance polling**: 30 seconds

### Entry Window

**Minutes before expiry**: 12 (start trading)

**Cutoff minutes before expiry**: 2 (stop trading)

**Realistic trading window**: 2-12 minutes (sweet spot: 5-10 minutes)

### Per-Asset Minimum Decision Minute

**BTC**: 2 minutes

**ETH**: 2 minutes

**SOL**: 3 minutes

**XRP**: 3 minutes

**DOGE**: 5 minutes

### Maintenance Window

**Maintenance day**: 3 (Wednesday)

**Maintenance start ET**: 03:00

**Maintenance end ET**: 05:00

---

## Configuration Files

### Single Source of Truth

**Primary Profile**: `config/profiles/kalshi_crypto_15m_v2.yaml`

**Agent Grid**: `config/kalshi_agent_grid.yaml`

**15m Thresholds**: `config/kalshi_15m_thresholds.yaml`

**Risk Limits**: `config/risk_limits.yaml`

**Crypto Threshold Matrix**: `config/crypto_threshold_matrix.yaml` (profile-guarded for 15m)

### Agent Specs

**BTC**: `config/kalshi_btc_15m_agent_spec.py`

**ETH**: `config/eth_15m_agent_spec.py`

**SOL**: `config/sol_15m_agent_spec.py`

**XRP**: `config/xrp_15m_agent_spec.py`

**DOGE**: `config/doge_15m_agent_spec.py`

---

## Startup Command

**Standard startup**:
```powershell
CD C:\Dev\MERID
.\start_15m.ps1 -Port 8011 -Profile kalshi_crypto_15m_v2
```

**Pre-startup cleanup** (critical):
```powershell
taskkill /F /IM python.exe
```

---

## Critical Reminders

1. **All 5 assets are mandatory**: BTC, ETH, SOL, XRP, DOGE must always be active
2. **Fix root causes**: Never skip or disable assets due to issues
3. **Use production stack**: web/main_15m_lean.py (NOT web/main.py)
4. **Profile is single source of truth**: kalshi_crypto_15m_v2.yaml overrides all other risk config
5. **Thresholds are tier-based**: Edge bands (4-5% watch, 5-7% small, >=7% standard) are ACTUAL thresholds
6. **Price range is 50-70c**: Optimized for scaling strategies
7. **Max orders per 15m window**: 5 (industry standard)
8. **Correlation-aware risk**: >0.80 correlation treated as ONE position
9. **Volatility-regime adjustment**: Adapt edge thresholds based on 30-day volatility
10. **Time-of-day scaling**: Adjust risk based on session liquidity

---

## Document Version

**Version**: 1.0  
**Date**: 2026-07-04  
**Profile**: kalshi_crypto_15m_v2  
**Profile Version**: 2.3.0

