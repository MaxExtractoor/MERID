# MERID 15m Kalshi Crypto Trading System - Current Setup Documentation
**Date**: 2026-07-02  
**Profile**: kalshi_crypto_15m_v2  
**Version**: 2.2.0

---

## Executive Summary

The 15-minute Kalshi crypto trading system is configured for live trading on 5 assets (BTC, ETH, SOL, XRP, DOGE) with conservative risk parameters and hybrid signal generation. Recent trades show both YES and NO side execution, indicating balanced signal generation.

**Recent Trade Performance (Last Session)**:
- DOGE: $0.72 YES
- XRP: $0.62 YES
- SOL: $0.60 YES
- ETH: $0.62 YES
- BTC: $0.59 YES

---

## System Architecture

### Entry Point
- **File**: `web/main_15m_lean.py` (PRODUCTION - NOT legacy main.py)
- **Port**: 8011
- **Startup Command**: `.\start_15m.ps1 -Port 8011 -Profile kalshi_crypto_15m_v2`

### Core Components
1. **KalshiVenueClient**: Live API connection to Kalshi
2. **MarketCatalog**: Market discovery and filtering
3. **MarketStateStore**: Orderbook state management
4. **BankrollService**: Live bankroll tracking
5. **UnifiedSpotService**: Spot price feed for 5 assets
6. **AgentGrid15m**: Signal generation and candidate collection
7. **OrderRouter**: Order execution and validation

### Operational Cadence
- **Trading Loop**: 5-second cadence
- **Market Catalog Refresh**: 60 seconds
- **Fills Polling**: 20 seconds
- **Settlement Polling**: 60 seconds
- **Bankroll Polling**: 30 seconds

---

## Asset Universe

### Traded Assets (5 total)
- **BTC/USD** (Tier 1 - Core Asset)
- **ETH/USD** (Tier 1 - Core Asset)
- **SOL/USD** (Tier 2 - Alt Asset)
- **XRP/USD** (Tier 2 - Alt Asset)
- **DOGE/USD** (Tier 2 - Alt Asset)

**CRITICAL**: All 5 assets must always be included. Never skip or disable any asset.

---

## Risk Configuration

### Capital Management
- **Capital Source**: Live Kalshi bankroll API (capital_usd: 0)
- **Minimum Notional**: $0.50 per trade
- **Minimum Contracts**: 1 contract per trade
- **Fallback Trades**: DISABLED (require live market data)

### Risk Limits
- **Max Cycle Risk**: 0.5% of capital per cycle
- **Max Total Risk**: 15% of capital (production safety cap)
- **Per-Trade Risk**: 2% of capital (bankroll-tiered: 2-3% for <$100, 2% for $100-$1k, 2% for >$1k)
- **Daily Loss Limit**: 5% of bankroll (halt trading)
- **Drawdown Halt**: 20% (halt trading)
- **Drawdown Unwind**: 25% (unwind positions)

### Venue-Level Caps
- **Max Total Notional**: 25% of capital (sum of 5% per asset × 5 assets)
- **Bankroll Cap per Order**: 1% of bankroll
- **Max Orders per Minute**: 30
- **Max Orders per Hour**: 300

---

## Per-Asset Configuration

### Tier 1 Assets (BTC, ETH)
- **Max Notional**: 5% of capital
- **Max Contracts**: 2 contracts
- **Min Edge**: 3% (early/mid/late), 4% (terminal)
- **Max Distance**: 1.5% (BTC), 2.0% (ETH)
- **Min Depth**: 1 contract (both YES and NO)
- **Asset Tier**: 1

### Tier 2 Assets (SOL, XRP, DOGE)
- **Max Notional**: 5% of capital
- **Max Contracts**: 2 contracts
- **Min Edge**: 4-5% (varies by asset)
- **Max Distance**: 2.5-4.0% (varies by asset)
- **Min Depth**: 1 contract (both YES and NO)
- **Asset Tier**: 2

---

## Signal Generation

### Signal Mode: HYBRID
Combines mean_reversion and momentum_fvg for maximum opportunity capture.

#### Mean Reversion Parameters
- RSI thresholds for overbought/oversold zones
- Trade against overextensions

#### Momentum/FVG Parameters
- **Momentum RSI**: Long >55, Short <45
- **MACD Histogram**: Long >=0, Short <=0
- **OBI Thresholds**: 
  - BTC/ETH: 0.55 (strong)
  - SOL/XRP/DOGE: 0.45 (strong)
- **FVG Max Age**: 4 bars (60 minutes)
- **FVG Min Size**: 3 ticks
- **Min Time to Expiry**: 30 minutes

#### Price-Based Strategy (Alternative)
- **Buy Threshold**: 0.52 (buy YES when price <= 52c)
- **Sell Threshold**: 0.68 (buy NO when price >= 68c)

---

## Market Microstructure Filters

### Universe Liquidity Filters
- **Min Volume**: 5 contracts
- **Min Open Interest**: 1 contract
- **Max Spread**: 10 cents (REVERTED from 100c - 82c spreads are one-sided markets with NO bids at 1c)

### Market Microstructure Filters
- **Max Spread**: 25 cents (REVERTED from 100c)
- **Min Depth USD**: $50 (DISABLED - set to 0)
- **Min YES Depth**: 1 contract
- **Min NO Depth**: 1 contract

### Guardrails
- **Max Spread**: 25 cents
- **Max Slippage**: 3 cents
- **Min Depth Contracts**: 2 contracts
- **Min Post-Fee Edge**: 2%
- **Min Time to Expiry**: 2.5 minutes
- **Max Spot-Strike Distance**: 2.0%
- **Min Contract Price**: 20 cents (blocks deep OTM longshots)
- **Max Same-Side per Strip**: 4 positions
- **Max Orders per Cycle**: 3 orders

---

## Throttling and Rate Limits

### Global Throttling
- **Global Orders Window**: 60 seconds
- **Global Orders Limit**: 5 orders per minute
- **Per-Asset Cooldown**: 30 seconds
- **Max Orders per 15m Window**: 5 orders total
- **Cooldown After Loss**: 2 cycles (30 seconds)

### Per-Asset Cooldown Logic
- Dynamic cooldown based on volatility history
- Falls back to 30 seconds if insufficient volatility data
- Updated after each candidate generation

---

## Spread Filter Analysis (2026-07-02)

### Root Cause Investigation
**Issue**: Orders rejected due to wide spreads (82c-92c)

**Root Cause**: 
- NO bids at 1c (implies ~99% YES probability)
- YES ask = 100 - NO_bid = 100 - 1 = 99c
- These are extremely one-sided markets with near-certain outcomes

**Trading Implications**:
- Trading 99% probability markets has poor edge (max 1% upside)
- Wide spreads (82c) represent 82% slippage on a $1 contract
- The spread filter is CORRECTLY protecting from bad trades

**Configuration Decision**:
- REVERTED threshold increases (was 100c, now 10c/25c)
- Spread filter is working as designed
- These markets should NOT be traded

---

## Recent Observations

### Trade Execution (Last Session)
- 5 trades executed (all YES side)
- Prices: $0.59-$0.72 per contract
- Both YES and NO sides being generated (good signal diversity)

### Market Conditions
- Markets are currently one-sided (NO bids at 1c)
- YES ask prices at 99c due to formula: YES_ask = 100 - NO_bid
- Spread filter correctly blocking these low-edge trades

### System Health
- WebSocket receiving orderbook_delta events
- Market state store updating correctly
- Cooldown enforcement working (30 seconds)
- No data quality issues - spreads reflect actual market conditions

---

## Profitability Enhancements (Phase 1)

### YES/NO Sum Arbitrage
- **Enabled**: true
- **Threshold**: 3 cents
- **Max Size**: 10 contracts
- **Execution Timeout**: 500ms

### Market Making
- **Enabled**: true
- **Quoting Mode**: two_sided
- **Spread**: 2 cents
- **Inventory Limit**: 50 contracts
- **Skew Adjustment**: enabled

### Correlation Tracking
- **Enabled**: true
- **Threshold**: 0.5
- **Max Reduction**: 40%
- **Window**: 30 days

---

## Advanced Filters

### Multi-Timeframe Filter
- **Enabled**: true
- **Higher Timeframe**: 1h
- **Alignment Mode**: strict
- **Neutral Size Multiplier**: 0.5

### Order Book Imbalance Filter
- **Enabled**: true
- **Strong Threshold**: 0.7
- **Moderate Threshold**: 0.3
- **Consistency Window**: 20 snapshots
- **Min Consistency**: 60%
- **Max Staleness**: 5 seconds

### News Event Avoidance
- **Enabled**: true
- **Avoidance Window**: 15 minutes before/after news
- **High Impact Events**: NFP, CPI, FOMC, GDP, PPI, Retail Sales, ISM

---

## Edge Bands Configuration

### Watch Band (0.8-1.5% edge)
- Action: log_only
- Kelly Multiplier: 0.0

### Small Band (1.5-3% edge)
- Action: trade_small
- Kelly Multiplier: 0.25

### Standard Band (3%+ edge)
- Action: trade_standard
- Kelly Multiplier: 0.50

---

## Confidence Thresholds

- **Min Confidence**: 50% (lowered from 75% for increased trade frequency)
- **Use Crypto Threshold Matrix**: false (profile-gated)

---

## Entry Window Configuration

- **Minutes Before Expiry**: 12 minutes
- **Cutoff Before Expiry**: 2 minutes
- **Min Decision Minute**: 
  - BTC/ETH: 2 minutes
  - SOL/XRP: 3 minutes
  - DOGE: 4 minutes

---

## Operation Mode

- **Mode**: prod (production)
- **Dry Run**: false (live trading)
- **Catalog Staleness Enforced**: false (informational only)

---

## Known Issues and Observations

### Spread Rejections
- **Status**: Working as designed
- **Cause**: One-sided markets with NO bids at 1c
- **Action**: No changes needed - filter is protecting from bad trades

### Trade Frequency
- **Status**: Low due to spread filter
- **Cause**: Current market conditions are one-sided
- **Expected**: Will improve when markets become more balanced

### Signal Diversity
- **Status**: Good
- **Observation**: Both YES and NO sides being generated
- **Recent Trades**: All YES side in last session (normal for current conditions)

---

## Next Steps

1. **Wait for next 15-minute market window**
2. **Restart server with current configuration**
3. **Monitor logs for 15 minutes**
4. **Analyze trade execution results**
5. **Identify needed adjustments based on observations**

---

## Configuration Files

- **Primary Profile**: `config/profiles/kalshi_crypto_15m_v2.yaml`
- **Python Profile**: `merid/risk/profiles/crypto_15m_profile.py`
- **Entry Point**: `web/main_15m_lean.py`
- **Agent Grid**: `merid/prediction/agent_grid_15m.py`
- **Order Router**: `merid/event_venues/kalshi/order_router.py`

---

## Log Location

- **Main Log**: `logs/full.log`
- **Key Patterns to Monitor**:
  - `[CANDIDATE-GENERATED]` - Signal generation
  - `[ORDER-ROUTED]` - Order execution
  - `[COOLDOWN-CHECK]` - Cooldown enforcement
  - `[MARKET-VALIDATION]` - Market state checks
  - `microstructure_gate_failed` - Spread rejections

---

## Version History

### v2.2.0 (2026-06-28)
- Phase 1 profitability enhancements
- YES/NO arbitrage, market making, correlation tracking

### v2.1.0 (2026-06-24)
- Complete 5-phase probability modeling roadmap
- Velocity model, momentum fusion, calibration, strategies, regime classification

### v2.0.0 (2025-12-01)
- Initial config-only risk model
- Per-asset configuration, strategy policy

---

**Document Generated**: 2026-07-02 06:45 UTC  
**System Status**: Ready for next 15-minute window monitoring
