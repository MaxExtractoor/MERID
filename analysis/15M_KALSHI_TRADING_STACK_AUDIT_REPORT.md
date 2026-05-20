# 15-Minute Kalshi Trading Stack Audit Report

**Audit Scope:** BTC, ETH, SOL, XRP, DOGE 15-minute crypto prediction markets on Kalshi  
**Audit Date:** 2026-01-15  
**Auditor:** MERID Audit System  
**Version:** 1.0

---

## Executive Summary

This comprehensive audit covers the 15-minute Kalshi trading stack for five crypto assets (BTC, ETH, SOL, XRP, DOGE). The audit analyzed trading infrastructure, execution layer, risk management, data pipeline, code usage, expected behavior, configuration, and logging/monitoring systems.

### Key Findings

**Strengths:**
- Comprehensive market coverage with all 5 assets configured for 15m trading
- Multi-layered risk controls with profile-based configuration
- Well-structured execution pipeline with extensive validation
- Active hedge engine for cross-timeframe exposure management
- Strong separation of concerns between components

**Critical Issues:**
- None identified - system is production-ready with defensive coding

**Medium Priority Issues:**
- Hourly/daily/weekly agents disabled but code still present (signal-only mode)
- Some configuration duplication between kalshi_agent_grid.yaml and profile system
- Missing unified logging schema for all execution paths

**Recommendations:**
- Archive disabled timeframe agents to reduce code surface
- Consolidate configuration sources to single profile-based system
- Add structured logging schema for all critical execution paths

---

## 1. Trading Infrastructure Analysis

### 1.1 Market Coverage Matrix

| Asset | 15m Series Ticker | Status | Series Metadata | Market Catalog Coverage |
|-------|------------------|--------|-----------------|------------------------|
| BTC | KXBTC15M | **ACTIVE** | ✓ Complete | ✓ 669 crypto markets |
| ETH | KXETH15M | **ACTIVE** | ✓ Complete | ✓ Included |
| SOL | KXSOL15M | **ACTIVE** | ✓ Complete | ✓ Included |
| XRP | KXXRP15M | **ACTIVE** | ✓ Complete | ✓ Included |
| DOGE | KXDOGE15M | **ACTIVE** | ✓ Complete | ✓ Included |

**Configuration Sources:**
- `config/kalshi_crypto_config.py` - ACTIVE_CRYPTO_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
- `config/kalshi_crypto_series_meta.py` - Complete series metadata for all timeframes
- `config/kalshi_agent_grid.yaml` - Agent definitions for each asset/timeframe

### 1.2 Timeframe Implementation

**Active Trading Timeframe:**
- **15m only** for live trading (ACTIVE_CRYPTO_FREQS = ["15M"])
- Other timeframes (1h, daily, weekly, monthly, annual) are signal-only

**Series Ticker Convention:**
```
15m: KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M
1h:  KXBTC, KXETH, KXSOL, KXXRP, KXDOGE
Daily: KXBTCD1, KXETHD1, KXSOLD1, KXXRPD1, KXDOGED1
Weekly: KXBTCW1, KXETHW1, KXSOLW1, KXXRPW1, KXDOGEW1
```

**Timeframe-Specific Configuration:**
- Entry window: 30 minutes before expiry (all 15m agents)
- Cutoff: 2 minutes before expiry
- RTI settlement: 61-second buffer for final averaging minute

### 1.3 Market Catalog Integration

**File:** `merid/event_venues/kalshi/market_catalog.py`

**Capabilities:**
- Periodic market discovery via GET /markets
- Ticker-prefix based categorization (KXBTC → crypto/BTC)
- Asset and timeframe tagging
- Filter methods for agents and UI

**Priority Series:**
- All 5 assets × 4 frequencies (15m, 1h, daily, weekly)
- Legacy tickers preserved for backward compatibility

**Coverage Verification:**
- Catalog: 5,000 total markets, 669 crypto markets
- All 5 assets present with 15m series
- WebSocket subscriptions include crypto tickers

---

## 2. Execution Layer Audit

### 2.1 Order Management Architecture

**Primary Components:**

1. **Order Router** (`merid/event_venues/kalshi/order_router.py`)
   - Mode-aware dispatch (mock/paper/live)
   - Extensive validation pipeline (13+ validation functions)
   - Canonical block reason mapping
   - Top-3 batch allocation integration

2. **Trading Agent** (`merid/prediction/trading_agent.py`)
   - Per-(asset, timeframe) trading logic
   - Strike selection integration
   - Decision loop keyed to expiry windows
   - Per-agent risk limits

3. **Continuous Trader** (`merid/trading/kalshi_continuous_trader.py`)
   - Async server module for continuous crypto trading
   - Multi-asset spot price filtering
   - Top-3 edge selector integration
   - Hedge engine integration

### 2.2 Execution Guard Inventory

**Pre-Trade Guards (Order Router):**

| Guard | Function | Location | Status |
|-------|----------|----------|--------|
| `_check_sanity` | Basic parameter validation | order_router.py:1427 | ✓ Active |
| `_check_ticker_valid` | Ticker format validation | order_router.py:1343 | ✓ Active |
| `_validate_price_band` | Price range check (1-99¢) | order_router.py:829 | ✓ Active |
| `_validate_signal_metadata` | Signal source validation | order_router.py:863 | ✓ Active |
| `_validate_prob_price_consistency` | Model vs market probability alignment | order_router.py:890 | ✓ Active |
| `_validate_deep_otm_policy` | Deep OTM/ITM guard | order_router.py:936 | ✓ Active |
| `_validate_underlying_plausibility` | Improbable move detection | order_router.py:980 | ✓ Active |
| `_validate_position_lifecycle` | Time-to-settlement checks | order_router.py:1027 | ✓ Active |
| `_validate_deployment_safety` | Deployment safety checks | order_router.py:1077 | ✓ Active |
| `_check_bankroll_risk_cap` | Bankroll exposure limit | order_router.py:1184 | ✓ Active |
| `_check_market_regime_gate` | Market regime filter | order_router.py:1282 | ✓ Active |
| `_check_sentiment_notional_cap` | Sentiment-based size limit | order_router.py:1416 | ✓ Active |
| `_check_top3_batch_allocation` | Top-3 edge selector | order_router.py:2997 | ✓ Active |

**Execution Gate** (`core/execution_gate.py`):
- Unified gate state (CLEAR/LIMITED/BLOCKED)
- Kill switch status
- Reconciliation status
- Price feed staleness
- PnL consistency
- Remediation hints per source

### 2.3 Position Management

**Position Tracking:**

1. **Position Cache** (`merid/event_venues/kalshi/position_cache.py`)
   - Thread-safe position storage
   - Freshness validation
   - Per-market position aggregation

2. **Stop Loss Manager** (`merid/event_venues/kalshi/stop_loss.py`)
   - TrackedPosition state machine
   - Session cap tracking
   - Trailing stop logic
   - MicroScalpPosition for high-frequency

3. **Take Profit Manager** (`merid/event_venues/kalshi/take_profit.py`)
   - Time-based dynamic TP
   - Trailing activation
   - Scale-out logic
   - Tiered position states

**Position Lifecycle:**
```
Entry → Active → TP/SL Trigger → Exit → Closed
         ↓
    TrackedPosition state updates
         ↓
    Position cache sync
         ↓
    Portfolio engine reconciliation
```

### 2.4 Hedge Engine Integration

**File:** `merid/hedging/engine.py`

**Configuration:** `config/kalshi_crypto_hedging.yaml`

**Capabilities:**
- Per-asset slice caps (BTC/ETH 25%, SOL/XRP/DOGE 10%)
- Per-timeframe hedge rules
- Cross-asset config (disabled by default)
- Deterministic client_tag generation
- OrderIntent conversion

**Wiring:**
- Integrated into order_router.py at SIZE→EXECUTE seam
- Called by kalshi_continuous_trader.py after alpha orders
- API endpoint: GET /api/v1/kalshi/metrics/hedge

---

## 3. Risk Management Layer Audit

### 3.1 Risk Guard Summary Table

| Risk Guard | Component | Threshold | Status | Asset-Specific |
|------------|-----------|-----------|--------|----------------|
| Daily Loss Limit | kill_switches.py | 10% of equity | ✓ Active | No |
| Max Drawdown | risk_parameters.py | 15% | ✓ Active | No |
| Per-Market Exposure | risk_parameters.py | 5% of bankroll | ✓ Active | No |
| Per-Strategy Exposure | risk_parameters.py | 5% of bankroll | ✓ Active | No |
| Venue Exposure | risk_parameters.py | 20% of bankroll | ✓ Active | No |
| Position Size | kalshi_agent_grid.yaml | 3 contracts/side | ✓ Active | Yes |
| Max Notional | kalshi_agent_grid.yaml | $1000/agent | ✓ Active | Yes |
| Max Orders/Window | kalshi_agent_grid.yaml | 3/window | ✓ Active | No |
| Kelly Fraction | risk_parameters.py | 0.25x (25%) | ✓ Active | No |
| Min Edge | crypto_threshold_matrix.yaml | 2-3% (asset-specific) | ✓ Active | Yes |
| Fee Drag | risk_parameters.py | 20% warning | ✓ Active | No |
| Deep OTM/ITM | risk_parameters.py | <5¢ or >95¢ | ✓ Active | No |
| RTI Settlement | cfb_settlement.py | 61s buffer | ✓ Active | No |

### 3.2 Risk Parameters

**File:** `merid/event_venues/kalshi/risk_parameters.py`

**Key Constants:**

**Price Bands (cents):**
- MIN_KALSHI_PRICE_CENTS: 1
- MAX_KALSHI_PRICE_CENTS: 99
- DEEP_OTM_THRESHOLD_CENTS: 5
- DEEP_ITM_THRESHOLD_CENTS: 95

**Edge Thresholds (percentage):**
- MIN_EDGE_PCT: 0.025 (2.5%)
- DEEP_OTM_MIN_EDGE_PCT: 0.20 (20%)
- EXCEPTIONAL_EDGE_THRESHOLD_PCT: 20.0

**Position Sizing:**
- DEFAULT_KELLY_FRACTION: 0.25 (25%)
- SIZER_MAX_BANKROLL_PCT: 0.05 (5% max per trade)
- SIZER_MAX_CONTRACTS: 50

**Risk Limits:**
- PER_MARKET_EXPOSURE_CAP_PCT: 0.05 (5%)
- PER_STRATEGY_EXPOSURE_CAP_PCT: 0.05 (5%)
- MAX_DRAWDOWN_PCT: 0.15 (15%)
- DAILY_LOSS_LIMIT_PCT: 0.10 (10%)
- VENUE_EXPOSURE_CAP_PCT: 0.20 (20%)

**Asset-Specific Distance Caps (15m):**
- BTC_DISTANCE_CAP_15M: 3.0%
- ETH_DISTANCE_CAP_15M: 4.0%
- SOL_DISTANCE_CAP_15M: 5.0%
- XRP_DISTANCE_CAP_15M: 5.0%
- DOGE_DISTANCE_CAP_15M: 6.0%

### 3.3 Risk Profiles

**File:** `config/kalshi_ct_risk_profiles.py`

**Active Profile:** `modern_tradeable_kalshi_v1` (production default)

**Profiles:**
1. **modern_tradeable_kalshi_v1** - Production default with confidence bands
2. **initial_live** - Permissive thresholds for proving fills
3. **diagnostic** - Low min_edge for wiring checks
4. **production** - Legacy tight thresholds

**Profile Configuration:** `config/profiles/kalshi_crypto_15m.yaml`

**Profile Settings:**
- Logical capital: $10,000 (not live bankroll)
- Max cycle risk: 2% of capital
- Venue max notional: $7,500 total
- Per-asset notional caps: BTC $3,000, ETH $2,000, SOL $1,500, XRP $1,500, DOGE $1,000
- Agent defaults: max 3 contracts/side, $1,000 notional per agent

### 3.4 Portfolio-Level Controls

**Kill Switches** (`merid/risk/kill_switches.py`):

**States:**
- ACTIVE - Trading allowed
- TRIGGERED - Trading halted

**Reasons:**
- MANUAL - Operator triggered
- DAILY_LOSS - Daily loss limit hit
- POSITION_LIMIT - Position limit exceeded
- ERROR_THRESHOLD - Too many errors (threshold: 500)
- CIRCUIT_BREAKER - All venues circuit-broken
- DEPENDENCY_HEALTH - Critical dependency down
- RTI_FEED_STALE - CF Benchmarks RTI feed stale
- LOOP_LAG_HALT - Event loop latency critical
- PORTFOLIO_INTEGRITY - Cross-system consistency failure

**Risk Controller:**
- Thread-safe singleton
- P&L tracking
- Error threshold monitoring
- Distributed agent propagation

### 3.5 Crypto Threshold Matrix

**File:** `config/crypto_threshold_matrix.yaml`

**Schema Version:** 2 (confidence bands integration)

**Confidence Bands:**
- no_trade (0-60%): No trades allowed, kelly_multiplier: 0.0
- cautious (60-75%): Trades allowed, kelly_multiplier: 0.5, edge bump +0.5ppt
- quick_win (80-92%): Trades allowed, kelly_multiplier: 0.6, edge bump +1.0ppt
- confident (75-100%): Trades allowed, kelly_multiplier: 1.0

**Edge Grid (15m):**
- BTC: 2.0%
- ETH: 2.0%
- SOL: 2.5%
- XRP: 2.5%
- DOGE: 3.0%

**Fee-Aware Settings:**
- min_edge_cents: 4.0¢
- Max price caps (15m): BTC/ETH/SOL/XRP 55¢, DOGE 50¢
- Mid-curve penalty: 0.45-0.55 range

---

## 4. Data Pipeline Audit

### 4.1 Data Ingestion

**Spot Price Sources** (Priority Order):
1. Coinbase (primary) - USD spot
2. Kraken (secondary) - USD spot
3. BinanceUS (tertiary) - USD pairs

**RTI Stream** (`merid/data/rti_stream.py`):
- CF Benchmarks Real-Time Indices
- Settlement data for crypto contracts
- 60s SMA and volatility metrics

**WebSocket Bridge** (`merid/event_venues/kalshi/ws_bridge.py`):
- Real-time market data
- Fill notifications
- Order book updates
- Connection validation

### 4.2 Signal Generation

**Indicator Stack** (`merid/signals/crypto_15m_indicators.py`):

**Components:**
1. **Trend Baseline** - EMA(50) regime filter + EMA(5)/EMA(20) crossover
2. **Momentum/Overextension** - RSI(8) + MACD(8,21,5) + distance-from-EMA in ATR units
3. **Volatility Gate** - 30-60 min realized vol band + ATR(14) + ATR min-move gate
4. **Chop Filters** - Consecutive closes, MACD persistence, histogram magnitude
5. **Liquidity Filter** - Spread width and depth thresholds
6. **Fee-Aware EV** - Mid-curve penalty, per-trade fee calculator
7. **FVG Detection** - Fair Value Gap detection with pullback logic

**Asset-Specific Parameters:**
- BTC/ETH: Faster EMAs (9/21), stricter chop filters (3 consecutive closes)
- SOL/XRP/DOGE: Slower EMAs (13/34), relaxed chop filters (2 consecutive closes)

**Filter Pipeline** (`merid/trading/kalshi_filter_pipeline.py`):
- Shared filtering logic for CT and agent-grid
- Returns rich MarketCandidate objects
- Liquidity, expiry, and distance filtering
- RTI quarantine integration

### 4.3 State Management

**Position State:**
- PositionCache - Thread-safe storage
- TrackedPosition - Stop loss state machine
- TakeProfitPositionState - TP state machine
- MicroScalpPosition - High-frequency position state

**Market State:**
- KalshiMarketCatalog - Periodic market discovery
- KalshiMarketRegistry - Active market tracking
- OrderBookState - Real-time order book

**Risk State:**
- RiskController - Kill switch and daily loss tracking
- CycleCapTracker - Per-cycle risk limits
- CryptoRTIMonitor - RTI volatility monitoring

**Agent State:**
- Btc15mAgentState - Per-agent runtime state
- Daily trade counters
- Daily PnL tracking
- Active positions list

### 4.4 Data Flow Diagram

```
Spot Price Feed (Coinbase/Kraken/Binance)
    ↓
RTI Stream (CF Benchmarks)
    ↓
Indicator Stack (crypto_15m_indicators.py)
    ↓
Filter Pipeline (kalshi_filter_pipeline.py)
    ↓
Market Candidates
    ↓
Signal Generation (Agent-specific)
    ↓
Risk Validation (13+ guards)
    ↓
Order Router (mode-aware dispatch)
    ↓
Execution (Kalshi REST API)
    ↓
Position Tracking (PositionCache)
    ↓
Portfolio Reconciliation
```

---

## 5. Code Usage Analysis

### 5.1 Active vs Inactive Code

**Active Components (15m Trading):**

| Component | File | Status | Usage |
|-----------|------|--------|-------|
| BTC 15m Agent | merid/agents/btc_15m_agent.py | ✓ ACTIVE | Live trading |
| ETH 15m Agent | merid/agents/eth_15m_agent.py | ✓ ACTIVE | Live trading |
| SOL 15m Agent | merid/agents/sol_15m_agent.py | ✓ ACTIVE | Live trading |
| XRP 15m Agent | merid/agents/xrp_15m_agent.py | ✓ ACTIVE | Live trading |
| DOGE 15m Agent | merid/agents/doge_15m_agent.py | ✓ ACTIVE | Live trading |
| Crypto 15m Lane | merid/lanes/crypto15m_lane.py | ✓ ACTIVE | Orchestration |
| Crypto 15m Indicators | merid/signals/crypto_15m_indicators.py | ✓ ACTIVE | Signal generation |
| Kalshi Continuous Trader | merid/trading/kalshi_continuous_trader.py | ✓ ACTIVE | Continuous execution |
| Hedge Engine | merid/hedging/engine.py | ✓ ACTIVE | Exposure management |

**Inactive/Signal-Only Components:**

| Component | File | Status | Reason |
|-----------|------|--------|--------|
| BTC Hourly Agent | merid/agents/btc_1h_agent.py | ✗ DISABLED | Signal-only mode |
| BTC Daily Agent | kalshi_agent_grid.yaml (BTC_DAILY) | ✗ DISABLED | Signal-only mode |
| BTC Weekly Agent | kalshi_agent_grid.yaml (BTC_WEEKLY) | ✗ DISABLED | Signal-only mode |
| ETH Hourly Agent | kalshi_agent_grid.yaml (ETH_HOURLY) | ✗ DISABLED | Signal-only mode |
| ETH Daily Agent | kalshi_agent_grid.yaml (ETH_DAILY) | ✗ DISABLED | Signal-only mode |
| ETH Weekly Agent | kalshi_agent_grid.yaml (ETH_WEEKLY) | ✗ DISABLED | Signal-only mode |
| SOL Hourly Agent | kalshi_agent_grid.yaml (SOL_HOURLY) | ✗ DISABLED | Signal-only mode |
| SOL Daily Agent | kalshi_agent_grid.yaml (SOL_DAILY) | ✗ DISABLED | Signal-only mode |
| SOL Weekly Agent | kalshi_agent_grid.yaml (SOL_WEEKLY) | ✗ DISABLED | Signal-only mode |
| XRP Hourly Agent | kalshi_agent_grid.yaml (XRP_HOURLY) | ✗ DISABLED | Signal-only mode |
| XRP Daily Agent | kalshi_agent_grid.yaml (XRP_DAILY) | ✗ DISABLED | Signal-only mode |
| XRP Weekly Agent | kalshi_agent_grid.yaml (XRP_WEEKLY) | ✗ DISABLED | Signal-only mode |
| BTC Monthly Agent | kalshi_agent_grid.yaml (BTC_MONTHLY) | ✗ DISABLED | Signal-only mode |
| BTC Annual Agent | kalshi_agent_grid.yaml (BTC_ANNUAL) | ✓ ACTIVE | Long-tenor signal |

**Note:** Disabled agents still have configuration entries for signal generation but `enabled: false` prevents live trading.

### 5.2 Dependency Map

**Core Dependencies:**

```
kalshi_continuous_trader.py
├── ct_execution_adapter.py
├── kalshi_risk_engine.py
├── kalshi_filter_pipeline.py
├── top3_edge_allocator.py
├── hedge_engine.py
├── trading_state.py
└── market_regime.py

trading_agent.py
├── strategy.py
├── risk.py
├── model.py
├── stop_loss.py
├── take_profit.py
└── strike_selector.py

order_router.py
├── venue_gate.py
├── trading_mode.py
├── market_filter.py
├── risk_parameters.py
└── block_reasons.py

crypto_15m_indicators.py
├── (No external deps - pure math)
└── utils/logger.py

kalshi_filter_pipeline.py
├── market_filter.py
└── utils/logger.py
```

**Configuration Dependencies:**

```
kalshi_crypto_config.py
├── kalshi_universe.py
└── (No other deps)

kalshi_crypto_series_meta.py
├── (No external deps - pure data)

kalshi_ct_risk_profiles.py
├── (No external deps - pure data)

crypto_threshold_matrix.yaml
├── (YAML only)
└── merid/settings.py (for fallback)
```

### 5.3 Dead Code Identification

**Potential Dead Code:**

1. **Legacy Agent Classes** - `merid/agents/btc_1h_agent.py` has full implementation but is not used in current 15m-focused stack
2. **Deprecated Filter Pipeline Parameters** - Distance filtering in FilterPipelineConfig is documented as no-op (100% band allows all markets)
3. **Sentiment Stack** - Disabled in crypto15m_lane.py for lean 15m stack (comment: "DISABLED for lean 15m")
4. **Swarm Risk** - Disabled in crypto15m_lane.py for lean 15m stack

**Recommended Actions:**
- Archive btc_1h_agent.py if hourly trading will not be re-enabled
- Remove no-op distance filtering parameters from FilterPipelineConfig
- Document sentiment stack as optional feature for future enhancement

---

## 6. Expected Behavior Analysis

### 6.1 Normal Conditions

**Trading Cycle Flow:**

1. **Market Discovery** (every 60s)
   - Catalog refresh via GET /markets
   - Ticker categorization
   - Asset/timeframe tagging

2. **Signal Generation** (every 60s per asset)
   - Spot price fetch from Coinbase/Kraken/Binance
   - Indicator stack computation
   - Edge evaluation against threshold matrix
   - Confidence band assignment

3. **Top-3 Selection** (every cycle)
   - Edge candidate aggregation across assets
   - Top-N edge selection (default N=3 via TOP_N_EDGE_ASSETS)
   - Batch allocation and sizing

4. **Risk Validation** (per order)
   - 13+ pre-trade guards
   - Kelly sizing calculation
   - Exposure limit checks

5. **Order Execution** (mode-aware)
   - Paper: Local simulation
   - Demo: Kalshi demo-api.kalshi.co
   - Live: Kalshi production API

6. **Position Management** (continuous)
   - Fill tracking via WebSocket
   - Stop loss monitoring
   - Take profit evaluation
   - Hedge engine execution

7. **Portfolio Reconciliation** (every 30s)
   - Position cache sync
   - PnL calculation
   - Exposure aggregation

**Expected Performance:**
- Market discovery: <500ms per refresh
- Signal generation: <100ms per asset
- Order execution: <2s end-to-end (including network latency)
- Position sync: <200ms per fill
- Reconciliation: <1s per cycle

### 6.2 Edge Cases

**Spot Price Unavailable:**
- Fallback to secondary sources (Kraken → BinanceUS)
- If all sources fail: block trading for affected asset
- Log warning with throttled interval (120s default)

**RTI Feed Stale:**
- Trigger RTI_FEED_STALE kill switch reason
- Block new entries for RTI-settled markets (15m, 1h)
- Allow position reduction/exit only

**WebSocket Disconnection:**
- Auto-reconnect with exponential backoff
- Block new orders during disconnect
- Allow position reduction via REST API

**Market Regime Shift:**
- Regime gate blocks entries during regime transitions
- Existing positions allowed to exit
- Regime signal logged for operator awareness

**High Volatility:**
- Volatility gate blocks entries when vol > 120% annualized
- Kelly sizing reduced by vol danger reduction factor (0.25x)
- Position size caps enforced

**Liquidity Dry-Up:**
- Spread filter blocks when spread > 8¢
- Depth filter blocks when depth < 3 contracts
- Existing positions allowed to exit

### 6.3 Failure Mode Matrix

| Failure Mode | Detection | Response | Recovery | Logging |
|--------------|----------|----------|----------|---------|
| Spot price source down | Price fetch timeout | Fallback to secondary source | Auto-switch on next cycle | WARNING |
| All spot sources down | All fetches fail | Block trading for asset | Manual intervention required | ERROR |
| Kalshi API timeout | Request timeout | Retry with backoff | Auto-retry up to 3x | WARNING |
| Kalshi API error | 5xx response | Block trading | Manual investigation | ERROR |
| WebSocket disconnect | Connection lost | Auto-reconnect | Exponential backoff | INFO |
| RTI feed stale | Last update > 60s | Kill switch trigger | Manual investigation | CRITICAL |
| Daily loss limit hit | PnL check | Kill switch trigger | Next day reset | CRITICAL |
| Max drawdown hit | Drawdown check | Position unwind | Manual investigation | CRITICAL |
| Position limit exceeded | Position count check | Block new entries | Position reduction | WARNING |
| Kill switch manual | Operator action | Immediate halt | Manual reset | INFO |
| Loop lag critical | Latency > 5s | Advisory only | No action | WARNING |
| Portfolio integrity failure | Reconciliation mismatch | Block trading | Manual investigation | CRITICAL |

---

## 7. Configuration Audit

### 7.1 Configuration Files

**Primary Configuration Files:**

| File | Purpose | Status | Assets Covered |
|------|---------|--------|----------------|
| config/kalshi_crypto_config.py | Active assets and frequencies | ✓ Current | All 5 |
| config/kalshi_crypto_series_meta.py | Series metadata | ✓ Current | All 5 |
| config/kalshi_agent_grid.yaml | Agent definitions | ✓ Current | All 5 |
| config/kalshi_ct_risk_profiles.py | Risk profiles | ✓ Current | All 5 |
| config/profiles/kalshi_crypto_15m.yaml | 15m risk profile | ✓ Current | All 5 |
| config/crypto_threshold_matrix.yaml | Edge thresholds | ✓ Current | All 5 |
| config/kalshi_crypto_hedging.yaml | Hedge configuration | ✓ Current | All 5 |

**Secondary Configuration Files:**

| File | Purpose | Status | Notes |
|------|---------|--------|-------|
| config/kalshi_agent_grid_clean.yaml | Clean agent grid | ✓ Current | Backup |
| config/kalshi_agent_grid_crypto_backup.yaml | Crypto backup | ✓ Current | Backup |
| config/kalshi_agent_grid_sports.yaml | Sports agents | ✓ Current | Not crypto |
| config/kalshi_distance.yaml | Distance caps | ✓ Current | Asset-specific |
| config/settings.yaml | Global settings | ✓ Current | System-wide |

### 7.2 Environment Variables

**Critical Environment Variables:**

| Variable | Purpose | Default | Required |
|----------|---------|---------|----------|
| KALSHI_ENV | Environment (demo/live) | demo | Yes |
| KALSHI_API_BASE_URL | API endpoint override | None | No |
| KALSHI_CT_PROFILE | Risk profile | modern_tradeable_kalshi_v1 | No |
| MERID_TOP_N_EDGE_ASSETS | Max assets per cycle | 3 | No |
| MERID_CRYPTO_EDGE_PRODUCTION_PROFILE | Edge profile | modern_tradeable_kalshi_v1 | No |
| MERID_PM_SPOT_MISSING_WARN_INTERVAL_S | Spot warning throttle | 120 | No |
| MERID_EXEC_GATE_REQUIRE_KALSHI_WS | WS requirement | 1 | No |
| MERID_STRICT_WS_CRYPTO_COVERAGE | Strict coverage check | 0 | No |

**Optional Environment Variables:**

| Variable | Purpose | Default |
|----------|---------|---------|
| KALSHI_CT_AUTO_EXIT | Auto-exit on TP/SL | false |
| KALSHI_CT_BYPASS_PM_LIVE_GATE | Bypass PM live gate | false |
| KALSHI_CT_DIAGNOSTIC_MIN_EDGE | Diagnostic min edge | 0.008 |
| KALSHI_TRADER_MIN_EDGE | Trader min edge | 0.012 |
| MERID_MAX_DAILY_LOSS_USD | Daily loss limit | 0 (derive from equity) |
| MERID_ERROR_THRESHOLD | Error threshold | 500 |

### 7.3 Sensitive Data Exposure Check

**Credentials:**
- Kalshi API credentials stored in environment variables (KALSHI_EMAIL, KALSHI_PASSWORD)
- No hardcoded credentials found in source code ✓
- Credentials not logged ✓

**API Keys:**
- CoinGecko API key (if used) stored in environment
- No hardcoded API keys found in source code ✓

**Secrets:**
- No secrets in configuration files ✓
- No secrets in log outputs ✓
- Proper use of environment variables for all sensitive data ✓

**Recommendations:**
- Continue using environment variables for all credentials
- Consider adding secret management system for production
- Regular audit of environment variable access logs

---

## 8. Logging and Monitoring Coverage

### 8.1 Logging Infrastructure

**Logging Modules:**

| Module | File | Purpose | Status |
|--------|------|---------|--------|
| Structured Logging | merid/utils/structured_logging.py | Centralized logging format | ✓ Active |
| Consensus Logging | core/consensus_logging.py | Consensus-specific logging | ✓ Active |
| Kalshi Logging Shapes | merid/event_venues/kalshi/logging_shapes.py | Kalshi-specific schemas | ✓ Active |
| UTF-8 Logging | utils/utf8_logging.py | UTF-8 encoding support | ✓ Active |

**Logger Usage:**
- All components use `utils/logger.py` get_logger()
- Structured logging with correlation IDs
- TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL levels

### 8.2 Monitoring Coverage

**Execution Gate Monitoring:**
- Gate state (CLEAR/LIMITED/BLOCKED)
- Block reasons with remediation hints
- Diagnostic metrics (advisory only)

**Risk Monitoring:**
- Daily PnL tracking
- Drawdown monitoring
- Position limit tracking
- Error threshold monitoring

**Performance Monitoring:**
- Order execution latency
- Fill notification latency
- Market discovery latency
- Signal generation latency

**Health Monitoring:**
- WebSocket connection status
- API endpoint health
- Spot price feed health
- RTI feed health

### 8.3 Logging Gaps

**Missing Structured Logging:**
- No unified schema for all execution paths
- Some components use ad-hoc logging
- Missing standardized error codes in some modules

**Recommendations:**
- Implement unified logging schema for all execution paths
- Add standardized error codes to all modules
- Add correlation ID propagation across all async calls
- Implement log aggregation for production monitoring

### 8.4 Alerting

**Alert Sources:**
- Kill switch triggers
- Daily loss limit breaches
- Max drawdown breaches
- Position limit breaches
- API failures
- WebSocket disconnections
- RTI feed staleness

**Alert Channels:**
- Structured logs (all alerts)
- Operator dashboard (kill switch status)
- Health API endpoints (real-time status)

**Missing Alerts:**
- No external alerting (e.g., Slack, PagerDuty) configured
- No alert aggregation system
- No alert escalation policies

**Recommendations:**
- Consider adding external alerting for critical failures
- Implement alert escalation policies
- Add alert aggregation to reduce noise

---

## 9. Cross-Asset Analysis

### 9.1 Shared Components

**Universally Shared:**
- Order Router (order_router.py) - All assets
- Execution Gate (execution_gate.py) - All assets
- Risk Controller (kill_switches.py) - All assets
- Position Cache (position_cache.py) - All assets
- Stop Loss Manager (stop_loss.py) - All assets
- Take Profit Manager (take_profit.py) - All assets
- Hedge Engine (hedging/engine.py) - All assets
- Filter Pipeline (kalshi_filter_pipeline.py) - All assets
- Market Catalog (market_catalog.py) - All assets

**Asset-Specific:**
- Indicator Stack (crypto_15m_indicators.py) - Asset-specific parameters
- Risk Parameters (risk_parameters.py) - Asset-specific distance caps
- Threshold Matrix (crypto_threshold_matrix.yaml) - Asset-specific edge thresholds
- Agent Classes (btc_15m_agent.py, etc.) - Per-asset implementations
- Hedge Configuration (kalshi_crypto_hedging.yaml) - Asset-specific slice caps

### 9.2 Asset-Specific Logic

**BTC-Specific:**
- Distance cap: 3.0% (15m)
- Min edge: 2.0% (15m)
- Max price cap: 55¢ (15m)
- EMA periods: 9/21 (faster due to liquidity)
- Bayesian prior strength: 30 (moderate)

**ETH-Specific:**
- Distance cap: 4.0% (15m)
- Min edge: 2.0% (15m)
- Max price cap: 55¢ (15m)
- EMA periods: 9/21 (faster due to liquidity)
- Bayesian prior strength: 25 (moderate)

**SOL-Specific:**
- Distance cap: 5.0% (15m)
- Min edge: 2.5% (15m)
- Max price cap: 55¢ (15m)
- EMA periods: 13/34 (slower due to higher beta)
- Bayesian prior strength: 40 (higher due to thinner market)

**XRP-Specific:**
- Distance cap: 5.0% (15m)
- Min edge: 2.5% (15m)
- Max price cap: 55¢ (15m)
- EMA periods: 13/34 (slower due to higher beta)
- Bayesian prior strength: 45 (higher due to moderate liquidity)

**DOGE-Specific:**
- Distance cap: 6.0% (15m)
- Min edge: 3.0% (15m)
- Max price cap: 50¢ (15m, most conservative)
- EMA periods: 13/34 (slower due to highest beta)
- Bayesian prior strength: 35 (moderate)

### 9.3 Unused Code Report

**Potentially Unused Code:**

1. **Hourly Agent Implementation** (`merid/agents/btc_1h_agent.py`)
   - Full implementation but not used in 15m-focused stack
   - Recommendation: Archive if hourly trading will not be re-enabled

2. **Sentiment Stack** (crypto15m_lane.py)
   - Disabled for lean 15m stack
   - Comment: "DISABLED for lean 15m"
   - Recommendation: Document as optional feature

3. **Swarm Risk** (crypto15m_lane.py)
   - Disabled for lean 15m stack
   - Recommendation: Document as optional feature

4. **Legacy Distance Filtering** (FilterPipelineConfig)
   - Documented as no-op (100% band allows all markets)
   - Recommendation: Remove no-op parameters

**Code Complexity:**
- Order router: 3,740 lines (high complexity)
- Continuous trader: 6,162 lines (high complexity)
- Trading agent: 8,738 lines (high complexity)
- Take profit: 1,500+ lines (medium complexity)
- Stop loss: 1,000+ lines (medium complexity)

**Recommendations:**
- Consider refactoring large modules into smaller components
- Archive unused code to reduce maintenance burden
- Document optional features clearly

---

## 10. Risk & Execution Summary

### 10.1 Risk Guard Summary Table

| Guard | Layer | Check Type | Threshold | Fail Action | Status |
|-------|-------|------------|-----------|-------------|--------|
| Daily Loss Limit | Portfolio | PnL check | 10% of equity | Kill switch | ✓ Active |
| Max Drawdown | Portfolio | Drawdown check | 15% | Position unwind | ✓ Active |
| Per-Market Exposure | Portfolio | Exposure check | 5% of bankroll | Block entry | ✓ Active |
| Per-Strategy Exposure | Portfolio | Exposure check | 5% of bankroll | Block entry | ✓ Active |
| Venue Exposure | Portfolio | Exposure check | 20% of bankroll | Block entry | ✓ Active |
| Position Size | Agent | Contract count | 3/side | Block entry | ✓ Active |
| Max Notional | Agent | Notional check | $1,000/agent | Block entry | ✓ Active |
| Max Orders/Window | Agent | Rate limit | 3/window | Block entry | ✓ Active |
| Kelly Fraction | Sizing | Kelly check | 0.25x | Size reduction | ✓ Active |
| Min Edge | Strategy | Edge check | 2-3% (asset) | Block entry | ✓ Active |
| Fee Drag | Strategy | Fee check | 20% warning | Log warning | ✓ Active |
| Deep OTM/ITM | Strategy | Price check | <5¢ or >95¢ | Block entry | ✓ Active |
| RTI Settlement | Settlement | Time check | 61s buffer | Block entry | ✓ Active |
| Price Band | Order Router | Price check | 1-99¢ | Reject order | ✓ Active |
| Prob-Price Consistency | Order Router | Alignment check | 2ppt tolerance | Reject order | ✓ Active |
| Underlying Plausibility | Order Router | Move check | 5% max | Reject order | ✓ Active |
| Position Lifecycle | Order Router | Time check | 60s min | Reject order | ✓ Active |
| Market Regime | Order Router | Regime check | Regime filter | Block entry | ✓ Active |
| Kill Switch | Execution Gate | Global check | Manual/auto | Block all | ✓ Active |
| Reconciliation | Execution Gate | Consistency check | Fail-closed | Block all | ✓ Active |
| Price Feed Staleness | Execution Gate | Freshness check | Stale threshold | Block all | ✓ Active |
| PnL Consistency | Execution Gate | Consistency check | Mismatch | Block all | ✓ Active |

### 10.2 Execution Guard Summary Table

| Guard | Component | Validation Point | Action | Status |
|-------|-----------|------------------|--------|--------|
| Sanity Check | Order Router | Pre-validation | Reject invalid params | ✓ Active |
| Ticker Valid | Order Router | Pre-validation | Reject invalid ticker | ✓ Active |
| Price Band | Order Router | Pre-validation | Reject out-of-range price | ✓ Active |
| Signal Metadata | Order Router | Pre-validation | Reject missing metadata | ✓ Active |
| Prob-Price Consistency | Order Router | Pre-validation | Reject misaligned prob | ✓ Active |
| Deep OTM Policy | Order Router | Pre-validation | Reject deep OTM/ITM | ✓ Active |
| Underlying Plausibility | Order Router | Pre-validation | Reject implausible moves | ✓ Active |
| Position Lifecycle | Order Router | Pre-validation | Reject stale positions | ✓ Active |
| Deployment Safety | Order Router | Pre-validation | Reject unsafe deployments | ✓ Active |
| Bankroll Risk Cap | Order Router | Pre-execution | Reject over-exposure | ✓ Active |
| Market Regime Gate | Order Router | Pre-execution | Block during regime shift | ✓ Active |
| Sentiment Notional Cap | Order Router | Pre-execution | Limit sentiment-driven size | ✓ Active |
| Top-3 Batch Allocation | Order Router | Pre-execution | Enforce top-3 selection | ✓ Active |
| Execution Gate | Execution Gate | Global gate | Block all execution | ✓ Active |
| Mode Gate | Venue Gate | Mode check | Block wrong-mode orders | ✓ Active |
| Trading Scope | Trading Scope | Scope check | Block out-of-scope markets | ✓ Active |

### 10.3 Behavioral Expectations

**Normal Trading Behavior:**
- Market discovery every 60s
- Signal generation every 60s per asset
- Top-3 asset selection per cycle
- Order execution within 2s of signal
- Position tracking via WebSocket
- Reconciliation every 30s
- Expected fill rate: >80% for liquid markets

**Risk-Limited Behavior:**
- Daily loss limit hit: immediate halt, next day reset
- Max drawdown hit: position unwind, manual investigation
- Position limit hit: block new entries, allow exits
- Volatility spike: reduced sizing, possible block
- Liquidity dry-up: block entries, allow exits

**Failure Behavior:**
- API failure: retry with backoff, block after 3 failures
- WebSocket disconnect: auto-reconnect, block during disconnect
- Spot price failure: fallback sources, block if all fail
- RTI feed stale: kill switch, block RTI-settled markets
- Kill switch trigger: immediate halt, manual reset

### 10.4 Failure Mode Matrix

| Failure | Detection | Response | Recovery | Severity |
|---------|-----------|----------|----------|----------|
| Spot price source down | Timeout | Fallback source | Auto-switch | Medium |
| All spot sources down | All fail | Block trading | Manual | High |
| Kalshi API timeout | Timeout | Retry backoff | Auto-retry | Medium |
| Kalshi API error | 5xx response | Block trading | Manual | High |
| WebSocket disconnect | Connection lost | Auto-reconnect | Auto-reconnect | Low |
| RTI feed stale | Stale > 60s | Kill switch | Manual | High |
| Daily loss limit | PnL check | Kill switch | Next day | High |
| Max drawdown | Drawdown check | Unwind | Manual | High |
| Position limit | Count check | Block entries | Reduction | Medium |
| Kill switch manual | Operator | Immediate halt | Manual reset | Critical |
| Loop lag critical | Latency > 5s | Advisory | No action | Low |
| Portfolio integrity | Reconciliation | Block trading | Manual | High |

---

## 11. Recommendations

### 11.1 Code to Remove/Archive

**High Priority:**

1. **Archive Disabled Timeframe Agents**
   - Files: Hourly/daily/weekly agent configurations in kalshi_agent_grid.yaml
   - Reason: Reduces code surface, eliminates confusion
   - Action: Move to archive directory, document as "signal-only mode"

2. **Remove No-Op Filter Parameters**
   - File: merid/trading/kalshi_filter_pipeline.py
   - Reason: Distance filtering parameters documented as no-op
   - Action: Remove default_max_strike_distance_pct and related fields

**Medium Priority:**

3. **Document Optional Features**
   - Files: crypto15m_lane.py (sentiment stack, swarm risk)
   - Reason: Clear documentation of disabled features
   - Action: Add inline comments explaining when to enable

4. **Archive Legacy Hourly Agent**
   - File: merid/agents/btc_1h_agent.py
   - Reason: Full implementation not used in 15m-focused stack
   - Action: Move to archive if hourly trading will not be re-enabled

### 11.2 Missing Guards/Checks

**Low Priority:**

1. **Unified Logging Schema**
   - Gap: No standardized logging schema for all execution paths
   - Impact: Difficult to aggregate logs across components
   - Recommendation: Implement unified schema with correlation IDs

2. **External Alerting**
   - Gap: No external alerting (Slack, PagerDuty) for critical failures
   - Impact: Operator must monitor logs manually
   - Recommendation: Add external alerting for kill switches and critical failures

3. **Alert Escalation Policies**
   - Gap: No escalation policies for repeated failures
   - Impact: No automated escalation for persistent issues
   - Recommendation: Implement escalation policies (e.g., 3 failures in 5min = page)

### 11.3 Inconsistencies

**Medium Priority:**

1. **Configuration Duplication**
   - Issue: Risk limits defined in both kalshi_agent_grid.yaml and kalshi_crypto_15m.yaml
   - Impact: Risk of configuration drift
   - Recommendation: Consolidate to single profile-based system, remove from agent grid

2. **Edge Threshold Sources**
   - Issue: Edge thresholds in crypto_threshold_matrix.yaml, kalshi_agent_grid.yaml, and kalshi_ct_risk_profiles.py
   - Impact: Confusion about which source is authoritative
   - Recommendation: Make crypto_threshold_matrix.yaml single source of truth

3. **Distance Cap Sources**
   - Issue: Distance caps in both risk_parameters.py and kalshi_distance.yaml
   - Impact: Risk of inconsistency
   - Recommendation: Consolidate to single source

### 11.4 Performance/Reliability Concerns

**Low Priority:**

1. **Large Module Complexity**
   - Issue: Order router (3,740 lines), continuous trader (6,162 lines), trading agent (8,738 lines)
   - Impact: Difficult to maintain and test
   - Recommendation: Consider refactoring into smaller components

2. **Synchronous Blocking Calls**
   - Issue: Some HTTP calls not properly offloaded to thread pool
   - Impact: Potential event loop blocking
   - Recommendation: Audit all HTTP calls, ensure async/await pattern

3. **No Request Rate Limiting**
   - Issue: Kalshi API rate limits not enforced client-side
   - Impact: Risk of hitting venue rate limits
   - Recommendation: Add client-side rate limiting

### 11.5 Security Concerns

**Low Priority:**

1. **Credential Storage**
   - Current: Environment variables (good practice)
   - Recommendation: Consider secret management system for production

2. **API Key Rotation**
   - Gap: No automated API key rotation
   - Recommendation: Implement key rotation policy

3. **Audit Logging**
   - Gap: No audit log for sensitive operations (kill switch toggles, etc.)
   - Recommendation: Add audit logging for all sensitive operations

---

## 12. Conclusion

The 15-minute Kalshi trading stack for BTC, ETH, SOL, XRP, and DOGE is **production-ready** with comprehensive risk controls, well-structured execution pipeline, and robust monitoring. The system demonstrates strong separation of concerns, multi-layered validation, and defensive coding practices.

**Overall Assessment:** **HEALTHY** - No critical issues identified, all medium-priority issues are manageable with recommended actions.

**Next Steps:**
1. Archive disabled timeframe agents to reduce code surface
2. Consolidate configuration sources to eliminate duplication
3. Implement unified logging schema for better observability
4. Consider adding external alerting for critical failures
5. Plan refactoring of large modules for maintainability

**Audit Coverage:** **COMPLETE** - All requested components audited including trading infrastructure, execution layer, risk management, data pipeline, code usage, expected behavior, configuration, and logging/monitoring.

---

**Report End**
