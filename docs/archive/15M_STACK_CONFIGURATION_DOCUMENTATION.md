# MERID 15M Kalshi Crypto Trading Stack - Configuration Documentation

**Generated:** 2026-07-06  
**Profile:** kalshi_crypto_15m_v2  
**Version:** 2.3.0

---

## Executive Summary

The MERID 15-minute Kalshi crypto trading system is a production-grade automated trading platform for crypto prediction markets on Kalshi. This document provides a comprehensive overview of all modes, strategies, settings, and configurations currently in use.

**Key Characteristics:**
- **Assets:** BTC, ETH, SOL, XRP, DOGE (5-asset crypto stack)
- **Timeframe:** 15-minute prediction markets
- **Venue:** Kalshi (api.elections.kalshi.com)
- **Profile:** kalshi_crypto_15m_v2 (v2.3.0)
- **Entry Point:** web/main_15m_lean.py (PRODUCTION)
- **Startup:** start_15m.ps1

---

## 1. Startup Configuration

### 1.1 Startup Script
**File:** `start_15m.ps1`

**Default Command:**
```powershell
CD C:\Dev\MERID
.\start_15m.ps1 -Port 8011 -Profile kalshi_crypto_15m_v2
```

**Key Environment Variables:**
- `MERID_PROFILE`: kalshi_crypto_15m_v2
- `TRADING_ENABLED`: true
- `MERID_PM_TRADING_MODE`: live
- `MERID_PM_LIVE_ENABLED`: true
- `MERID_ALLOW_LIVE_TRADES`: true
- `MERID_KALSHI_ENV`: prod
- `MERID_KALSHI_HTTP_BASE`: https://api.elections.kalshi.com/trade-api/v2
- `MERID_KALSHI_WS_BASE`: wss://api.elections.kalshi.com/trade-api/ws/v2
- `MERID_KALSHI_NET_EDGE_FILTER_ENABLED`: false (allows velocity-based small-edge trades)
- `MERID_DISABLE_SHARED_RISK_GUARD`: true (uses risk envelope only)
- `MAX_CYCLE_RISK_PCT`: 0.05 (5% - aligned with risk envelope)
- `MERID_YES_NO_ARBITRAGE_ENABLED`: true (Phase 1 profitability enhancement)
- `MERID_LOOP_DIAG_FILE`: 1 (diagnostic logging enabled)

### 1.2 Production Entry Point
**File:** `web/main_15m_lean.py`

**Architecture:**
- FastAPI application with lifespan-based startup
- No legacy module imports (FORBIDDEN: merid.prediction.agent_grid, web.main, core.*)
- Clean, minimal dependencies for 15m crypto trading
- Startup handled exclusively by FastAPI lifespan events

**Key Features:**
- Singleton reset on startup (unified_spot_service, ws_bridge)
- Profile validation (kalshi_crypto_15m_v2 required)
- Legacy module guard (prevents contamination)
- Runtime mode flag: MERID_RUNTIME_MODE=15m_live

**API Routers (Production):**
- performance_router
- kalshi_agent_grid_router
- health_router
- loop_router
- spot_router
- auth_router
- health_snapshot_router
- kalshi_api_router (fills ledger, positions, orders)
- kalshi_ui_router (reconciler migrated)
- diagnostics_router

**Disabled Routers (Legacy Dependencies):**
- kalshi_ui_state_router (needs legacy module migration)
- kalshi_dashboard_router (needs cqi_gating module)
- ui_audit_router (may have auth dependencies)

---

## 2. Profile Configuration (kalshi_crypto_15m_v2.yaml)

### 2.1 Profile Metadata
- **Profile Name:** kalshi_crypto_15m_v2
- **Version:** 2.3.0
- **Description:** Config-only risk model for 15m crypto prediction markets with 2026 research-based correlation and volatility management
- **Operation Mode:** prod (test/prod switch available)
- **Dry Run:** false (live trading)

### 2.2 Signal Mode
**Current:** `momentum_fvg` (2026-07-05: Changed from trend based on Turbine research)

**Options:**
- mean_reversion: Trade against overextensions
- momentum_fvg: Trade with trend using Fair Value Gaps and Order Book Imbalance
- hybrid: Allow both modes
- price_based: Buy YES when price <= 0.50, sell when price >= 0.70
- trend: Trend-following strategy

**Rationale:** Turbine research showed momentum was the only profitable family (78 of 100 strategies), while mean reversion failed completely (0 for 432 variants) on 15-minute markets.

### 2.3 Phase 1 Profitability Enhancements

#### YES/NO Sum Arbitrage
- **Enabled:** true
- **Threshold:** 3 cents (3% minimum arbitrage edge)
- **Max Size:** 10 contracts per arbitrage trade
- **Execution Timeout:** 500ms
- **Description:** Buy both YES and NO when YES_ask + NO_bid < 100c for risk-free profit

#### Market Making
- **Enabled:** true
- **Quoting Mode:** two_sided
- **Spread:** 2 cents target spread
- **Inventory Limit:** 50 contracts per asset
- **Skew Adjustment:** true (adjust quotes based on inventory imbalance)
- **Description:** Provide liquidity and earn spread income

#### Correlation Tracking
- **Enabled:** false (DISABLED for 15m crypto prediction markets)
- **Rationale:** These are prediction markets on crypto price movements, not spot crypto assets. Correlation between prediction market outcomes differs from spot crypto correlation. This was blocking multiple assets from trading in the same 15m window.

#### Offset Hedging
- **Enabled:** false (DISABLED - binary hedging inefficient for crypto with public markets)
- **Rationale:** Binary payouts are structurally mismatched for linear loss hedging. For assets with public markets (BTC/ETH/SOL/XRP/DOGE), options are more efficient.

#### Trailing Stop
- **Enabled:** true
- **Trailing Distance:** 5 cents
- **Min Profit:** 12 cents (activation threshold)
- **Activation Delay:** 30 seconds
- **Description:** Dynamic stop-loss that follows price to lock in profits

#### Ratchet Profit Floor
- **Enabled:** true
- **Activation Threshold:** 85 cents
- **Floor Offset:** 5 cents (sets floor at 80¢ when activated)
- **Force Exit on Floor Breach:** true
- **Min Hold After Activation:** 30 seconds
- **Mandatory Exit at 99c:** true (maximum profit capture)
- **Trim Position Enabled:** true (trim to 1 contract when >1 contract and price >80c)
- **Description:** Lock in profits at high price thresholds to prevent giving back gains

#### Staged Time-Based Exit
- **Enabled:** true
- **Stages:**
  - 5 minutes: close 40%
  - 10 minutes: close 30%
  - 13 minutes: close remaining 30%
- **Description:** Partial liquidation at time intervals for volatile markets

#### Dynamic Position Sizing
- **Enabled:** true
- **Base Contracts:** 1
- **Edge Multiplier:** 2.0 (increased from 0.5 based on Turbine research)
- **Confidence Multiplier:** 1.0 (increased from 0.3 based on Turbine research)
- **Max Contracts:** 3 (global cap, per-asset limits take precedence)
- **Min Contracts:** 1
- **Description:** Scale position based on edge and confidence (2026 research-tuned)

#### Order Scaling
- **Enabled:** true
- **Strategy:** adaptive (options: twap, iceberg, adaptive)
- **Min Child Orders:** 2
- **Max Child Orders:** 5
- **Time Window:** 300 seconds (5 minutes)
- **Participation Rate:** 10% of market volume
- **Visible Pct:** 10% (iceberg visible portion)
- **Edge Threshold:** 2% minimum edge for scaling
- **Size Threshold:** 3 contracts minimum for scaling
- **Description:** TWAP/iceberg/adaptive for large orders to reduce market impact

### 2.4 Momentum/FVG Mode Parameters

#### RSI Thresholds
- **Momentum RSI Long Min:** 55 (bullish momentum)
- **Momentum RSI Short Max:** 45 (bearish momentum)

#### MACD Histogram Thresholds
- **Long:** >= 0
- **Short:** <= 0

#### Order Book Imbalance (OBI) Parameters
- **OBI Min:** 0.25 (minimum absolute OBI to qualify as directional)
- **OBI Persistence Min:** 0.6 (60% minimum fraction of snapshots with consistent OBI sign)
- **OBI Persistence Window:** 10 seconds
- **OBI EWMA Alpha:** 0.15 (smoothing factor)

#### Per-Asset OBI Strong Thresholds
- **BTC:** 0.55
- **ETH:** 0.55
- **SOL:** 0.45 (thinner book)
- **XRP:** 0.45 (thinner book)
- **DOGE:** 0.45 (thinner book)

#### Per-Asset OBI EWMA Alpha
- **BTC:** 0.15 (more depth, more flicker, smoother)
- **ETH:** 0.15
- **SOL:** 0.20 (less depth, quicker reaction)
- **XRP:** 0.20
- **DOGE:** 0.20

#### Fair Value Gap (FVG) Parameters
- **Max Age:** 4 bars (60 minutes at 15m bars)
- **Min Size:** 3 ticks
- **Min Time to Expiry:** 30 minutes for new entries

#### Trend Confirmation
- **Require EMA Stack:** true (fast > slow for longs)
- **Require Price vs EMA50:** true

#### Liquidity-Aware Size Scaling
- **High Threshold:** 200 contracts (1.0x profile risk)
- **Medium Threshold:** 80 contracts (0.75x profile risk)
- **Low Threshold:** 40 contracts (0.5x profile risk)
- **Ultra-Low Threshold:** 25 contracts (0.25x profile risk)
- **Min Threshold:** 25 contracts (no new entries below this)

#### Spread Gate
- **Spread Gate Cents:** 75 (unified with guardrails.max_spread_cents)
- **Spread Gate OBI Persistence Boost:** 0.75 (require 75% persistence if spread is wide)

### 2.5 Price-Based Strategy Parameters
- **Buy Threshold:** 0.48 (buy YES when price <= 48¢)
- **Sell Threshold:** 0.72 (buy NO when price >= 72¢)
- **Rationale:** Optimized for swing trading with wider entry range to capture YES/NO reversals

### 2.6 Hybrid Mode Price Caps
- **Max Entry Price YES:** 0.70 (avoids highest fee zone)
- **Min Entry Price NO:** 0.30 (symmetry with 70¢ YES cap)
- **Rationale:** Prevents overpriced entries while keeping momentum signals

### 2.7 Sentiment Isolation
- **Enable Sentiment Execution:** false (sentiment-based trading disabled for 15m crypto)
- **Sentiment Mode:** disabled

### 2.8 Drawdown Semantics
- **Time Horizon:** since_process_start (not rolling window)
- **PnL Basis:** equity_including_positions (realized + unrealized)
- **Deposit/Withdrawal Treatment:** as_pnl
- **Fresh Start Behavior:** peak_equity resets to current_equity when MERID_FRESH_START=1

### 2.9 Global Capital and Cycle Risk
- **Capital USD:** 0 (derive from live Kalshi bankroll API)
- **Min Notional USD:** 0.50 (minimum notional per trade)
- **Min Contracts:** 1 (Kalshi venue invariant)
- **Allow Fallback Trades:** false (require live market data)
- **Max Fallback Notional USD:** 0.35 (unused when disabled)
- **Max Fallback Cycles:** 0 (disabled)
- **Max Cycle Risk Pct:** 0.05 (5% of capital per cycle)
- **Max Total Risk Pct:** 0.15 (15% total risk cap for production safety)
- **Max Cycle Risk USD:** 7.00 (hardcoded cap for 10 contracts at max entry price)

### 2.10 Venue-Level Caps (Kalshi)
- **Max Total Notional Pct:** 0.15 (15% of capital)
- **Max Category Notional Pct:** 0.15 (15% for "crypto" category)
- **Max Single Order Pct:** 0.03 (3% of bankroll per single order)
- **Bankroll Cap Pct:** 0.03 (3% of bankroll per order)

### 2.11 Universe Liquidity Filters
- **Min Volume:** 5 contracts (relaxed from default 50 for 15m crypto)
- **Min Open Interest:** 1 contract (relaxed from default 10)
- **Max Spread Cents:** 75 (unified with guardrails)

### 2.12 Throttling (Order Rate Limits)
- **Global Orders Window Sec:** 60 (rolling window)
- **Global Orders Limit:** 30 (max 30 orders per minute globally)
- **Per Asset Cooldown Sec:** 8 (cooldown per asset)
- **Per Strip Notional USD:** 0.0 (disabled)
- **Max Orders Per 15m Window:** 12 (max 12 orders per 15m window)
- **Cooldown After Loss Cycles:** 2 (no new entry for 2 cycles after loss)
- **Consecutive Loss Pause:** 3 (pause after 3 consecutive losses)
- **Max Session Risk Pct:** 0.10 (max 10% session risk)

### 2.13 Failsafe Configuration
- **Max Contracts Per Order:** 1 (emergency brake when in failsafe mode)

### 2.14 Price Range Validation
- **Min Price Cents:** 10 (allows NO-side entries in high-probability markets)
- **Max Price Cents:** 70 (avoids risky high-end markets with poor scaling)
- **Rationale:** 10-70c range for momentum-based trading, avoids extreme prices with poor scaling effectiveness

### 2.15 Per-Asset Caps (BTC/ETH/SOL/XRP/DOGE)

#### BTC
- **Max Notional Pct:** 0.03 (3% of capital)
- **Max Contracts:** 3
- **Min Edge Early:** 0.03 (3%)
- **Min Edge Mid:** 0.03 (3%)
- **Min Edge Late:** 0.03 (3%)
- **Min Edge Terminal:** 0.04 (4%)
- **Max Distance Pct:** 0.015 (1.5%)
- **Min Order Book Depth USD:** 1000.0
- **Min Volume 24h USD:** 5000.0
- **Max Skew Ratio:** 0.70
- **Asset Tier:** 1 (core asset)
- **Min Depth Yes:** 1 contract
- **Min Depth No:** 1 contract

#### ETH
- **Max Notional Pct:** 0.03 (3% of capital)
- **Max Contracts:** 3
- **Min Edge Early:** 0.03 (3%)
- **Min Edge Mid:** 0.03 (3%)
- **Min Edge Late:** 0.03 (3%)
- **Min Edge Terminal:** 0.04 (4%)
- **Max Distance Pct:** 0.018 (1.8%)
- **Min Order Book Depth USD:** 800.0
- **Min Volume 24h USD:** 4000.0
- **Max Skew Ratio:** 0.70
- **Asset Tier:** 1 (core asset)
- **Min Depth Yes:** 1 contract
- **Min Depth No:** 1 contract

#### SOL
- **Max Notional Pct:** 0.03 (3% of capital)
- **Max Contracts:** 3
- **Min Edge Early:** 0.04 (4%)
- **Min Edge Mid:** 0.04 (4%)
- **Min Edge Late:** 0.04 (4%)
- **Min Edge Terminal:** 0.05 (5%)
- **Max Distance Pct:** 0.025 (2.5%)
- **Min Order Book Depth USD:** 500.0
- **Min Volume 24h USD:** 3000.0
- **Max Skew Ratio:** 0.65
- **Asset Tier:** 2 (alt asset)
- **Min Depth Yes:** 1 contract
- **Min Depth No:** 1 contract

#### XRP
- **Max Notional Pct:** 0.03 (3% of capital)
- **Max Contracts:** 3
- **Min Edge Early:** 0.04 (4%)
- **Min Edge Mid:** 0.04 (4%)
- **Min Edge Late:** 0.04 (4%)
- **Min Edge Terminal:** 0.05 (5%)
- **Max Distance Pct:** 0.025 (2.5%)
- **Min Order Book Depth USD:** 400.0
- **Min Volume 24h USD:** 2500.0
- **Max Skew Ratio:** 0.65
- **Asset Tier:** 2 (alt asset)
- **Min Depth Yes:** 1 contract
- **Min Depth No:** 1 contract

#### DOGE
- **Max Notional Pct:** 0.03 (3% of capital)
- **Max Contracts:** 2 (lower due to highest volatility)
- **Min Edge Early:** 0.05 (5%)
- **Min Edge Mid:** 0.05 (5%)
- **Min Edge Late:** 0.05 (5%)
- **Min Edge Terminal:** 0.06 (6%)
- **Max Distance Pct:** 0.025 (2.5%)
- **Min Order Book Depth USD:** 200.0
- **Min Volume 24h USD:** 1500.0
- **Max Skew Ratio:** 0.60
- **Asset Tier:** 2 (alt asset)
- **Min Depth Yes:** 1 contract
- **Min Depth No:** 1 contract

### 2.16 Per-Agent Defaults
- **Max Notional Pct:** 0.03 (3% of capital per agent)
- **Max Orders Per Window:** 20
- **Max Yes Position:** 5
- **Max No Position:** 5
- **Max Concurrent Trades:** 8
- **Minutes Before Expiry:** 12 (entry window)
- **Cutoff Minutes Before Expiry:** 2 (stop trading 2 minutes before expiry)

### 2.17 Edge/Confidence Thresholds
- **Use Crypto Threshold Matrix:** false (profile-gated)
- **Min Confidence Threshold:** 0.65 (65% - increased from 50% based on GRDazzle research)

### 2.18 Tiered Edge Band Configuration
- **Enabled:** true
- **Watch Band:** 0.8-1.5% edge (log only, no trading)
- **Small Band:** 1.5-3% edge (trade with 0.25x Kelly)
- **Standard Band:** >=3% edge (trade with 0.5x Kelly)

### 2.19 Guardrails
- **Max Spread Cents:** 75
- **Max Slippage Cents:** 5
- **Min Post Fee Edge:** 0.015 (1.5%)
- **Min Time to Expiry Min:** 2.0 (120 seconds)
- **Max Dist Pct Trade:** 2.5
- **Min Contract Price Cents:** 10
- **Max Contract Price Cents:** 75
- **Max Same Side Per Strip:** 5
- **Min Edge Per Trade:** 0.02 (2% base edge for maker orders)
- **Max Entry Mins:** 15.0
- **Min Entry Mins:** 2.0
- **Max Spread For Edge:** 25 cents (default)
- **Depth Size Multiplier:** 1.5
- **Regime Cooldown Enabled:** false
- **Regime Cooldown Min Trades:** 20
- **Regime Cooldown Min Winrate:** 0.45
- **Regime Cooldown Max Loss Pct:** 0.10
- **Experimental Price Band Enabled:** false
- **Experimental TTE Band Enabled:** false
- **Spread Guard Enabled:** true
- **Spread Guard Edge Multiplier:** 1.1
- **Min Spread Gate Cents:** 75
- **Drawdown Halt Pct:** 0.20 (20%)
- **Drawdown Unwind Pct:** 0.25 (25%)
- **Max Position Value USD:** 100000.0
- **Per Trade Risk Pct:** 0.03 (3%)
- **Daily Loss Enabled:** true
- **Max Daily Loss Pct:** 0.20 (20% for both test and prod)
- **Max Daily Loss USD:** 8.00 (fallback for small bankrolls)
- **Rolling 1h PnL Halt Pct:** 0.05 (5%)
- **Rolling 4h PnL Halt Pct:** 0.08 (8%)
- **Rolling 1h PnL Reduce Pct:** 0.02 (2%)
- **Rolling 4h PnL Reduce Pct:** 0.03 (3%)

#### Adaptive Risk Bands
- **0-8% drawdown:** 100% multiplier (normal)
- **8-10% drawdown:** 80% multiplier (warning)
- **10-12% drawdown:** 50% multiplier (downsize)
- **12-15% drawdown:** 25% multiplier (critical)
- **15%+ drawdown:** 0% multiplier (halt)

### 2.20 Reconciliation Thresholds
- **Cash Tolerance Cents:** 1
- **PnL Tolerance Cents:** 10
- **Position Tolerance Contracts:** 0 (exact match required)
- **Discrepancy Persistence Cycles:** 2
- **Reconciliation Interval Seconds:** 300 (5 minutes)

### 2.21 Clock Drift Detection
- **Clock Skew Tolerance Seconds:** 5.0
- **Max Age Seconds:** 30.0

### 2.22 Kelly Sizing
- **Kelly Fraction:** 0.02 (2% hard cap, aligned with unified risk limit)
- **Kelly Hard Cap:** 0.02
- **Kelly Min Edge Pct:** 0.015 (1.5%)
- **Kelly Max Edge Pct:** 0.25 (25%)
- **Kelly Min Win Prob:** 0.01
- **Kelly Max Win Prob:** 0.99
- **Kelly Global Notional Cap Pct:** 0.02 (2% of equity)

#### Tiered Kelly Caps
- **Tier1 Fraction:** 0.02 (2% for BTC, ETH)
- **Tier2 Fraction:** 0.015 (1.5% for SOL, XRP, DOGE)
- **Tier1 Assets:** BTC, ETH
- **Tier2 Assets:** SOL, XRP, DOGE

### 2.23 Contract Caps
- **Max Contracts Total:** 5000
- **Max Contracts Per Asset:** 1750
- **Max Contracts Per Cluster:** 750
- **Max Single Order Contracts:** 2

### 2.24 Risk Policy
- **Group Notional Cap Pct:** 0.05 (5% of bankroll per group)
- **Group Notional Cap Min USD:** 5.00
- **Group Notional Cap Max USD:** 2000.0
- **Max Fee to Notional Pct:** 15.0
- **Max Stop Loss USD Per Cluster:** 5.00
- **Per Asset Cluster Stop Loss:**
  - BTC: 3.00
  - ETH: 3.00
  - SOL: 5.00
  - XRP: 5.00
  - DOGE: 5.00
- **Daily VaR Cap Pct:** 0.03 (3%)
- **Daily VaR Cap Min USD:** 2.00
- **Daily VaR Cap Max USD:** 1500.0
- **Anomalous State Detection:** true
- **Anomalous Position Reduction Pct:** 0.50

### 2.25 Venue Invariants
- **Valid Price Cents Min:** 10
- **Valid Price Cents Max:** 99
- **Deep OTM Threshold Cents:** 5
- **Deep ITM Threshold Cents:** 99
- **IOC Auto Below Seconds:** 120
- **Max Book Staleness Ms:** 30000 (30 seconds)
- **Entry TIF Default:** ioc
- **Exit TIF Default:** gtc

### 2.26 Market Discovery Freshness
- **Kalshi Min Close Seconds Ago:** null (disabled - get all markets)

### 2.27 Edge/Lag Filter Configuration
- **Min Edge/Lag Ratio:**
  - BTC: 0.02
  - ETH: 0.02
  - SOL: 0.03
  - XRP: 0.03
  - DOGE: 0.04
- **Edge/Lag Filter Enabled:** 0 (disabled for all assets - log only)
- **Cold Start Min Samples:** 100

### 2.28 Strategy Policy
- **Min Edge:** 0.015 (1.5% global minimum edge)
- **Min Confidence:** 0.50 (50%)
- **Max MD Staleness Sec:** 20.0
- **Require Secondary Confirmation:** false
- **Min Edge Stability Cycles:** 1
- **Max Pyramid Entries:** 1

#### Edge Thresholds
- **Market Entry:** 0.04 (4% - cross spread if edge >= threshold)
- **Resting Entry:** 0.02 (2% - join spread if edge >= threshold)
- **Cancel Threshold:**
  - BTC: 0.50
  - ETH: 0.50
  - SOL: 0.52
  - XRP: 0.53
  - DOGE: 0.55

### 2.29 Exit Policy

#### Risk/Reward
- **Min RR:**
  - BTC: 2.0
  - ETH: 2.0
  - SOL: 1.5
  - XRP: 1.5
  - DOGE: 1.5
- **TP Distance Pct:**
  - BTC: 0.15 (15%)
  - ETH: 0.15 (15%)
  - SOL: 0.12 (12%)
  - XRP: 0.12 (12%)
  - DOGE: 0.10 (10%)
- **SL Distance Pct:**
  - BTC: 0.075 (7.5%)
  - ETH: 0.075 (7.5%)
  - SOL: 0.08 (8%)
  - XRP: 0.08 (8%)
  - DOGE: 0.067 (6.7%)

#### Trailing
- **Enabled:** true
- **Activation R Multiple:** 0.8
- **Giveback Cents:** 5
- **Scale Out Enabled:** true
- **Scale Out Trigger R:** 0.7
- **Scale Out Fraction:** 0.5

#### Time Exit
- **Cutoff Minutes Before Expiry:** 2
- **Max Hold Minutes:** 15

### 2.30 Legacy Path Control
- **Disable Balance Calibration:** false (enable for 15m crypto)
- **Disable Dynamic Contract Caps:** true
- **Disable Bankroll Category Limits:** true
- **Disable Bankroll Prediction Risk:** true
- **Disable Bankroll Guardrails:** true

### 2.31 Velocity Model (Phase 1)
- **Formula:** p_model = sigmoid(alpha_0 + alpha_1 * velocity)
- **Coefficients:**
  - BTC: alpha_0=0.0, alpha_1=200.0
  - ETH: alpha_0=0.0, alpha_1=200.0
  - SOL: alpha_0=0.0, alpha_1=300.0
  - XRP: alpha_0=0.0, alpha_1=300.0
  - DOGE: alpha_0=0.0, alpha_1=500.0
- **Velocity Windows:** [10, 30, 60] seconds
- **Momentum Weights:** [0.2, 0.3, 0.5]
- **Velocity EMA Period:** 5
- **ATR Period:** 3
- **Z-Score Period:** 20

### 2.32 Velocity Thresholds (Per-Asset)
- **BTC:** 0.00001 (0.001% - effectively zero)
- **ETH:** 0.00001 (0.001%)
- **SOL:** 0.00001 (0.001%)
- **XRP:** 0.00001 (0.001%)
- **DOGE:** 0.00001 (0.001%)

### 2.33 Momentum Weights (Phase 4.1)
- **Windows:** [10, 30, 60]
- **Weights:** [0.2, 0.3, 0.5]

### 2.34 Logit Fusion Weights (Phase 4.4)
- **Velocity Logit:** 0.7
- **Mean Reversion Logit:** 0.3

### 2.35 Calibration Config (Phase 5.2)
- **Enabled:** false (uncalibrated model)
- **Auto Fit:** true
- **Min Samples For Fit:** 100
- **Max Samples:** 1000
- **Regularization:** 0.0001
- **Fit Interval Hours:** 24

### 2.36 Fee-Aware Edge Gate (Phase 1)
- **Enabled:** false (disabled for price-based strategy)
- **Min Edge Cents:** 2
- **Fee Per Contract:** 0.07

### 2.37 Market Microstructure Filters (Phase 1)
- **Enabled:** true
- **Max Spread Cents:** 75
- **Min Depth USD:** 0.0 (disabled - limit orders used)
- **Min Yes Depth:** 1
- **Min No Depth:** 1

### 2.38 Volume Filter Configuration
- **Enabled:** false (previous implementation was broken)
- **Description:** Volume filter using 2026 best practices (relative Z-scores, multi-timeframe confirmation)

### 2.39 Strategies
- **Heuristic Velocity:**
  - **ID:** heuristic_velocity
  - **Type:** heuristic_velocity
  - **Enabled:** true
  - **Min Edge:** 0.01 (1%)
  - **Min Confidence:** 0.50 (50%)

---

## 3. Risk Envelope (kalshi_crypto_15m_risk_envelope.py)

### 3.1 Risk Envelope Version
- **Version:** v20260529a-cache-fix
- **Description:** operation_mode support for daily loss limit

### 3.2 Risk Bands
- **NORMAL:** 0-10% drawdown, 100% risk multiplier
- **WARNING:** 10-12% drawdown, 50% risk multiplier
- **DOWNSIZE:** 12-15% drawdown, 25% risk multiplier
- **HALT:** 15%+ drawdown, 0% risk multiplier

### 3.3 Feature Flag
- **MERID_RISK_ENVELOPE_ENABLED:** true (default)

### 3.4 Computed Venue-Level Caps
- **Max Single Order Notional USD:** Derived from 3% of capital
- **Max Total Notional USD:** Derived from 15% of capital
- **Max Concurrent Trades:** 8 (from profile agent_defaults)

### 3.5 Per-Asset Caps
- **Asset Max Notional USD:** 3% of capital per asset (BTC, ETH, SOL, XRP, DOGE)
- **Min Max Notional USD:** 0.10 (minimum floor for small bankrolls)
- **Asset Depth Thresholds:** Sourced from profile YAML (min_depth_yes=1, min_depth_no=1)

### 3.6 Per-Agent Defaults
- **Agent Max Notional USD:** 3% of capital
- **Agent Max Orders Per Window:** 20
- **Agent Max Yes Position:** 5
- **Agent Max No Position:** 5

### 3.7 Cycle Risk Cap
- **Max Cycle Risk Pct:** 0.05 (5% of capital per cycle)

### 3.8 Guardrails
- **Daily Loss Enabled:** true
- **Max Daily Loss USD:** 20% of capital (aligned with drawdown halt)
- **Drawdown Halt Pct:** 0.20 (20%)
- **Drawdown Unwind Pct:** 0.25 (25%)

### 3.9 Drawdown Tracking
- **Time Horizon:** since_process_start
- **PnL Basis:** equity_including_positions
- **Deposit/Withdrawal Treatment:** as_pnl

### 3.10 Kelly Fraction
- **Kelly Fraction:** 0.02 (2% hard cap)

### 3.11 Adaptive Risk Scaling
- **Per Trade Risk Multiplier:** Based on drawdown bands
- **Is Halted:** Based on drawdown threshold
- **Current Risk Band:** Explicit band state (NORMAL/WARNING/DOWNSIZE/HALT)
- **Resume If Drawdown Improves:** false (manual operator intervention required)

### 3.12 Correlation Tracking (Phase 1)
- **Enabled:** false (disabled for 15m crypto prediction markets)
- **Correlation Threshold:** 0.5
- **Correlation Multiplier:** 1.0 (default)

### 3.13 Per-Trade Risk Pct
- **Uniform 3% per-trade risk** for all bankroll sizes (matches YAML config)
- **Rationale:** Aligned with 3% per agent / 5% per 15m window limits

### 3.14 Validation
- **Asset caps scaled down if sum exceeds venue cap**
- **Per-trade cap validated against bankroll**
- **Adaptive risk bands validated for ascending order**
- **Multipliers validated between 0 and 1**
- **Last band must have multiplier 0 (halt)**

---

## 4. Agent Grid (agent_grid_15m.py)

### 4.1 Agent Grid Version
- **Version:** v20260529a-cache-fix

### 4.2 Strategy Invariants
1. **Velocity-based signals:** Use Coinbase 1-minute velocity for trade direction
2. **Simplified gates:** Only liquidity, spread, staleness (no complex indicator gates)
3. **Market state validation:** Use KalshiMarketStateStore for live orderbook data
4. **Risk envelope:** Apply profile-driven risk limits and position sizing
5. **Full asset coverage:** All 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) must be included

### 4.3 Kalshi Fee Calculation
- **Formula:** fee = 7% × p × (1-p) × contract_price
- **Cap:** $0.0175 (1.75 cents) per contract

### 4.4 Agent Configuration (LeanAgentConfig)

#### Basic Configuration
- **Signal Mode:** momentum_fvg
- **Max Spread Cents:** 100
- **Min Time to Expiry S:** 180
- **Max Time to Expiry S:** 900
- **Per Strip Order Limit:** 200 (increased for 2026 high-frequency standards)
- **Per Asset Cooldown S:** 8
- **Max Orders Per 15m Window:** 12 (aligned with profile YAML)
- **Consecutive Loss Pause:** 3
- **Max Session Risk Pct:** 0.10
- **Velocity Threshold:** 0.0015 (0.15%)

#### Per-Asset Velocity Thresholds
- **BTC:** 0.00001 (0.001%)
- **ETH:** 0.00001 (0.001%)
- **SOL:** 0.00001 (0.001%)
- **XRP:** 0.00001 (0.001%)
- **DOGE:** 0.00001 (0.001%)

#### Fee-Aware Trading Parameters
- **Prefer Maker Orders:** true (earn rebates vs taker fees)
- **Min Profit Basis Points:** 20
- **Max Spread Basis Points:** 50
- **Use Limit Orders:** true (better fill rates in thin markets)
- **Limit Order Slippage Cents:** 2

#### Regime Detection Parameters
- **Volatility Window S:** 300 (5-minute window)
- **Min Volatility Threshold:** 0.001 (0.1%)

#### Hybrid Mode Price Caps
- **Max Entry Price Yes:** 0.70 (70¢)
- **Min Entry Price No:** 0.30 (30¢)

#### Position Management
- **Max Concurrent Positions:** 15 (total across all assets)

#### Dynamic Spread Threshold
- **Calm Volatility Threshold:** 0.005 (0.5%)
- **Elevated Volatility Threshold:** 0.015 (1.5%)
- **Calm Spread Threshold BP:** 200
- **Elevated Spread Threshold BP:** 300
- **Violent Spread Threshold BP:** 500
- **Spread Volatility Sensitivity:** 1.5

#### Session-Based Trading Windows
- **Enable Session Filter:** false (24/7 trading)
- **US-Europe Overlap:** 13:00-17:00 UTC
- **US Session:** 17:00-22:00 UTC
- **European Morning:** 08:00-13:00 UTC

#### Phase 1: Velocity Model Coefficients
- **Alpha_0:** 0.0 (intercept)
- **Alpha_1:** 1000.0 (velocity coefficient)

#### Phase 4.1: Multi-Window Velocity
- **Velocity Windows:** [10, 30, 60]
- **Momentum Weights:** [0.2, 0.3, 0.5]
- **Velocity EMA Period:** 5
- **ATR Period:** 3
- **Z-Score Period:** 20

#### Phase 4.4: Logit Fusion Weights
- **Velocity Weight:** 0.7
- **Mean Reversion Weight:** 0.3

#### Phase 4.5: Near Expiry Guard
- **Near Expiry Guard Sec:** 300 (5 minutes)

#### Phase 5.2: Calibration Configuration
- **Calibration Enabled:** false
- **Calibration Auto Fit:** true
- **Calibration Min Samples:** 100
- **Calibration Max Samples:** 1000
- **Calibration Regularization:** 0.0001
- **Calibration Fit Interval Hours:** 24

#### Phase 5.3: Price-Based Strategy
- **Price Based Buy Threshold:** 0.70
- **Price Based Sell Threshold:** 0.95

#### Phase 6: Regime Detection
- **Regime Detector Enabled:** true

#### Phase 7: Panic Fade (Volatility Reversion)
- **Panic Fade Enabled:** true
- **Panic Fade Threshold:** 0.00013 (0.013%)
- **Panic Fade Z-Score Threshold:** 2.0
- **Panic Fade RSI Oversold:** 25.0
- **Panic Fade RSI Overbought:** 75.0
- **Panic Fade Min Velocity:** 0.000065 (0.0065%)

### 4.5 LeanAgent15m Initialization

#### Price History
- **Price History Window Size:** 300 (5 minutes at 1-second intervals)
- **Assets:** BTC, ETH, SOL, XRP, DOGE

#### SMA History (Mean Reversion)
- **SMA Window Size:** 120 (2 minutes)

#### Velocity EMA History
- **EMA Window Size:** 10 (velocity_ema_period * 2)

#### Volatility History
- **Volatility Window Size:** 300 (5 minutes for dynamic cooldown)

#### Velocity Z-Score History
- **Z-Score Window Size:** 20

#### ADX History (Trend Filtering)
- **ADX Window Size:** 14 (industry standard)
- **ADX History Window Size:** 300 (match price history)

#### Volume History
- **Volume Window Size:** 300 (5 minutes for EMA20 calculation)

#### Multi-Timeframe Price History
- **1m Window Size:** 60
- **5m Window Size:** 300

#### Cooldown Tracking
- **Last Trade Time:** Per asset (initialized to 0.0)
- **Per Strip Order Counts:** Per series ticker
- **Current Market IDs:** Per series ticker

#### Session-Level Order Tracking
- **Session Order Count:** 0
- **Session Start Time:** current time
- **Session Window Sec:** 900 (15 minutes)

#### Consecutive Loss Tracking
- **Consecutive Losses:** Per asset
- **Consecutive Loss Pause Until:** Per asset

#### Session Risk Cap
- **Session Risk USD:** 0.0
- **Session Risk Cap USD:** Derived from profile (10% of capital)

#### Portfolio Heat Tracking
- **Portfolio Heat Enabled:** false
- **Portfolio Heat Threshold Warning:** 0.70
- **Portfolio Heat Threshold Critical:** 0.85

#### Asset-Specific Rolling PnL Limits
- **Rolling PnL Enabled:** false

---

## 5. Market Configurations and Asset Universe

### 5.1 Agent Grid Configuration (kalshi_agent_grid.yaml)

#### Venue Configuration
- **Name:** kalshi
- **Base URL:** https://api.elections.kalshi.com/trade-api/v2
- **Use Demo:** false
- **Max Notional Per Expiry USD:** 0 (derive from actual Kalshi bankroll)
- **Max Open Markets Per Asset:** 20

#### Session Configuration
- **Maintenance Day:** 3
- **Maintenance Start ET:** 03:00
- **Maintenance End ET:** 05:00

#### Agent Configurations

##### BTC_15M
- **Enabled:** true
- **Series Tickers:** KXBTC15M
- **Assets:** BTC
- **Timeframes:** 15m
- **Archetype:** directional
- **Market Filter:** crypto, fifteen_min
- **Signal Mode:** momentum_fvg
- **Take Profit:** enabled with time-based dynamic TP
- **Strike Selection:** target_spot_band_pct=0.06, deep_otm_allowed=false

##### ETH_15M
- **Enabled:** true
- **Series Tickers:** KXETH15M
- **Assets:** ETH
- **Timeframes:** 15m
- **Archetype:** directional
- **Market Filter:** crypto, fifteen_min
- **Signal Mode:** momentum_fvg
- **Take Profit:** enabled with time-based dynamic TP
- **Strike Selection:** target_spot_band_pct=0.06, deep_otm_allowed=false

##### SOL_15M
- **Enabled:** true
- **Series Tickers:** KXSOL15M
- **Assets:** SOL
- **Timeframes:** 15m
- **Archetype:** directional
- **Market Filter:** crypto, fifteen_min
- **Signal Mode:** momentum_fvg
- **Take Profit:** enabled with time-based dynamic TP
- **Strike Selection:** target_spot_band_pct=0.06, deep_otm_allowed=false

##### XRP_15M
- **Enabled:** true
- **Series Tickers:** KXXRP15M
- **Assets:** XRP
- **Timeframes:** 15m
- **Archetype:** directional
- **Market Filter:** crypto, fifteen_min
- **Signal Mode:** momentum_fvg
- **Take Profit:** enabled with time-based dynamic TP
- **Strike Selection:** target_spot_band_pct=0.06, deep_otm_allowed=false

##### DOGE_15M
- **Enabled:** true
- **Series Tickers:** KXDOGE15M
- **Assets:** DOGE
- **Timeframes:** 15m
- **Archetype:** directional
- **Market Filter:** crypto, fifteen_min
- **Signal Mode:** momentum_fvg
- **Take Profit:** enabled with time-based dynamic TP
- **Strike Selection:** target_spot_band_pct=0.06, deep_otm_allowed=false

### 5.2 Asset Universe
- **Complete Crypto Stack:** BTC, ETH, SOL, XRP, DOGE (5 assets)
- **All assets must be included** across:
  - Live price feed
  - Agent grid
  - Market catalog
  - Risk enforcement
  - Trading

### 5.3 Market Discovery
- **Kalshi Min Close Seconds Ago:** null (disabled - get all markets)
- **Rationale:** Need ALL markets to find current 15m window

---

## 6. Sizing and Execution Settings

### 6.1 Unified Sizing (unified_sizing.py)

#### Regime Position Size Multiplier
- **Status:** DISABLED (returns 1.0)
- **Rationale:** Prevents interference with 3% per asset / 5% per 15m window limits
- **Re-Enable Risks:** Could cause oversizing beyond hard risk limits
- **Re-Enable Requirements:** Update risk envelope to apply regime_multiplier to risk limits

#### TTE Position Size Multiplier
- **Status:** DISABLED (returns 1.0)
- **Rationale:** Prevents interference with 3% per asset / 5% per 15m window limits
- **Re-Enable Risks:** Could cause oversizing beyond hard risk limits
- **Re-Enable Requirements:** Update risk envelope to apply tte_multiplier to risk limits

#### Venue-Aware Minimum Notional
- **Kalshi:** $0.50 (aligned with profile for micro account support)
- **Other Venues:** $0.0 (no constraint)

### 6.2 Order Scaling
- **Enabled:** true
- **Strategy:** adaptive
- **Min Child Orders:** 2
- **Max Child Orders:** 5
- **Time Window:** 300 seconds
- **Participation Rate:** 10%
- **Visible Pct:** 10%
- **Edge Threshold:** 2%
- **Size Threshold:** 3 contracts

### 6.3 Dynamic Position Sizing
- **Enabled:** true
- **Base Contracts:** 1
- **Edge Multiplier:** 2.0
- **Confidence Multiplier:** 1.0
- **Max Contracts:** 3
- **Min Contracts:** 1

### 6.4 Kelly Sizing
- **Kelly Fraction:** 0.02 (2% hard cap)
- **Kelly Hard Cap:** 0.02
- **Kelly Min Edge Pct:** 0.015
- **Kelly Max Edge Pct:** 0.25
- **Kelly Global Notional Cap Pct:** 0.02

#### Tiered Kelly Caps
- **Tier1 (BTC, ETH):** 0.02 (2%)
- **Tier2 (SOL, XRP, DOGE):** 0.015 (1.5%)

---

## 7. Runtime Checks and Validation

### 7.1 Production Runtime Check (kalshi_15m_runtime_check.py)

#### Profile and Env Check
- **Required Profile:** kalshi_crypto_15m_v2
- **Kalshi Base URL:** https://api.elections.kalshi.com/trade-api/v2
- **Trade Mode:** live (requires live URL, not demo)

#### No Legacy Subsystems Check
- **Forbidden Modules:**
  - merid.prediction.paper_session
  - merid.agents.reflection.integration
  - merid.agents.base.CanonicalAgentRegistry

#### Startup State Check
- **Startup Started:** true
- **Startup Failed:** false
- **Startup Completed:** true

#### App State Components Check
- **Agent Grid 15m:** initialized
- **Loop 15m:** initialized
- **Kalshi Client:** initialized
- **Market Catalog:** initialized
- **Market State Store:** initialized
- **Bankroll Service:** initialized

---

## 8. Operational Cadence

### 8.1 Loop Cadence
- **Kalshi15mLoop:** 5-second cadence

### 8.2 Data Refresh Cadence
- **Market Catalog:** every 60 seconds
- **Fills Polling:** every 20 seconds
- **Settlement Polling:** every 60 seconds
- **Bankroll Balance Polling:** every 30 seconds

---

## 9. Critical Invariants and Rules

### 9.1 Single Source of Truth
- **Profile YAML:** config/profiles/kalshi_crypto_15m_v2.yaml
- **Risk Envelope:** merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py
- **Agent Grid:** merid/prediction/agent_grid_15m.py
- **Unified Sizing:** merid/prediction/unified_sizing.py

### 9.2 Legacy vs Production Stack
- **PRODUCTION:** web/main_15m_lean.py
- **LEGACY:** web/main.py (DO NOT USE)
- **FORBIDDEN:** merid.prediction.agent_grid, web.main, core.*

### 9.3 Asset Coverage
- **CRITICAL:** BTC, ETH, SOL, XRP, DOGE must ALWAYS be included
- **NEVER** skip, comment out, or disable any of these 5 assets

### 9.4 Risk Limits
- **Per Asset:** 3% of capital
- **Per 15m Window:** 5% of capital
- **Per Trade:** 3% of capital
- **Total Venue:** 15% of capital
- **Drawdown Halt:** 20%
- **Daily Loss:** 20%

### 9.5 Disabled Features (to prevent interference with risk limits)
- **Time-of-Day Risk Scaling:** DISABLED
- **Regime-Based Sizing:** DISABLED
- **TTE-Based Sizing:** DISABLED
- **Correlation Tracking:** DISABLED (for 15m crypto prediction markets)
- **Offset Hedging:** DISABLED (binary hedging inefficient for crypto)

---

## 10. Configuration Change Audit Process

### 10.1 Upstream/Midstream/Downstream Audit

**UPSTREAM (Configuration Layer):**
- Profile YAML files (config/profiles/kalshi_crypto_15m_v2.yaml)
- Risk limits and percentage thresholds
- Asset-specific configurations (BTC, ETH, SOL, XRP, DOGE)
- Agent defaults (max_notional_pct, max_orders_per_window, etc.)

**MIDSTREAM (Risk Envelope Layer):**
- Risk envelope calculations (merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py)
- Profile adapter (merid/risk/profiles/crypto_15m_profile.py)
- Percentage-to-USD conversions
- Per-asset cap enforcement
- Agent default enforcement

**DOWNSTREAM (Sizing Layer):**
- Unified sizing (merid/prediction/unified_sizing.py)
- Time-of-day scaling (DISABLED)
- Regime-based sizing (DISABLED)
- TTE-based sizing (DISABLED)
- Position size multipliers

**END-TO-END CONSISTENCY CHECKS:**
1. Verify profile values match risk envelope defaults
2. Verify risk envelope defaults match sizing layer behavior
3. Ensure no scaling multipliers interfere with hard risk limits
4. Confirm 3% per asset / 5% per 15m window limits are respected
5. Check that all 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) are treated consistently

### 10.2 Audit Checklist After Any Change
- [ ] Profile YAML updated with correct values
- [ ] Risk envelope defaults match profile values
- [ ] Sizing layer disabled or aligned with risk limits
- [ ] No scaling multipliers interfere with hard limits
- [ ] All 5 assets have consistent treatment
- [ ] Tests updated to reflect new values
- [ ] Documentation updated if needed

---

## 11. Known Contamination Points

### 11.1 Legacy vs Production Stack Contamination
- **Signs:**
  - Diagnostic probes connecting to wrong endpoints/services
  - MD health checks using overly strict thresholds from legacy code
  - Market selection logic diverging between different components
  - WebSocket subscriptions to wrong market IDs or series
  - Agent grid using outdated state management

- **Current Known Issues:**
  - MD health thresholds may be from legacy strict requirements
  - Some diagnostics may be querying legacy catalog/MD instead of production
  - WebSocket forwarder IDLE state suggests subscription issues

- **Always Verify:**
  - Is this code path using the production KalshiVenueClient, KalshiMarketCatalog, and market state store, or legacy versions?

---

## 12. Summary of Key Configuration Values

### 12.1 Risk Limits
- **Per Asset:** 3% of capital
- **Per 15m Window:** 5% of capital
- **Per Trade:** 3% of capital
- **Total Venue:** 15% of capital
- **Drawdown Halt:** 20%
- **Daily Loss:** 20%

### 12.2 Trading Parameters
- **Signal Mode:** momentum_fvg
- **Max Orders Per 15m Window:** 12
- **Per Asset Cooldown:** 8 seconds
- **Consecutive Loss Pause:** 3
- **Max Session Risk:** 10%

### 12.3 Edge Thresholds
- **Watch Band:** 0.8-1.5% (log only)
- **Small Band:** 1.5-3% (trade with 0.25x Kelly)
- **Standard Band:** >=3% (trade with 0.5x Kelly)

### 12.4 Price Range
- **Min Price:** 10 cents
- **Max Price:** 70 cents

### 12.5 Spread Limits
- **Max Spread:** 75 cents
- **Spread Guard:** 75 cents

### 12.6 Depth Thresholds
- **Min Depth Yes:** 1 contract
- **Min Depth No:** 1 contract

### 12.7 Time Parameters
- **Min Time to Expiry:** 2 minutes
- **Max Time to Expiry:** 15 minutes
- **Loop Cadence:** 5 seconds

### 12.8 Kelly Sizing
- **Kelly Fraction:** 2%
- **Tier1 (BTC, ETH):** 2%
- **Tier2 (SOL, XRP, DOGE):** 1.5%

---

## Appendix A: File Structure

### Configuration Files
- `config/profiles/kalshi_crypto_15m_v2.yaml` - Main profile configuration
- `config/kalshi_agent_grid.yaml` - Agent grid configuration (profile-gated)
- `config/agent_manifest.yml` - Agent capability manifest

### Core Files
- `web/main_15m_lean.py` - Production entry point
- `start_15m.ps1` - Startup script
- `merid/prediction/agent_grid_15m.py` - Agent grid implementation
- `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py` - Risk envelope
- `merid/prediction/unified_sizing.py` - Unified sizing
- `merid/kalshi_15m_runtime_check.py` - Runtime validation

### Legacy Files (DO NOT USE)
- `web/main.py` - Legacy entry point
- `merid/prediction/agent_grid.py` - Legacy agent grid

---

## Appendix B: Environment Variables

### Required
- `MERID_PROFILE`: kalshi_crypto_15m_v2
- `TRADING_ENABLED`: true
- `MERID_PM_TRADING_MODE`: live
- `MERID_PM_LIVE_ENABLED`: true
- `MERID_ALLOW_LIVE_TRADES`: true

### Kalshi Configuration
- `MERID_KALSHI_ENV`: prod
- `MERID_KALSHI_HTTP_BASE`: https://api.elections.kalshi.com/trade-api/v2
- `MERID_KALSHI_WS_BASE`: wss://api.elections.kalshi.com/trade-api/ws/v2
- `KALSHI_LIVE_API_KEY_ID`: (from .env)
- `KALSHI_LIVE_PRIVATE_KEY_PATH`: (from .env)

### Optional
- `MERID_RUNTIME_MODE`: 15m_live (set automatically)
- `MERID_OPERATION_MODE`: prod (default)
- `MERID_FRESH_START`: 1 (reset drawdown state)
- `MERID_RISK_ENVELOPE_ENABLED`: true (default)

---

**Document End**
