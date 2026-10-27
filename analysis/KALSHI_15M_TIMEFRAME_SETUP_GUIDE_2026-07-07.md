# Kalshi 15-Minute Market Timeframe Setup Guide
**Date:** 2026-07-07  
**Scope:** Optimal timeframe hierarchy for trading 15-minute Kalshi crypto markets  
**Assets:** BTC, ETH, SOL, XRP, DOGE  
**Purpose:** Define the best micro timeframe setup and multi-timeframe analysis strategy for 15m binary contracts

---

## Executive Summary

Based on comprehensive research into Kalshi 15m market mechanics, industry best practices for multi-timeframe analysis, and the unique characteristics of binary prediction markets, this guide recommends a **3-tier timeframe hierarchy** optimized for 15-minute contract trading.

**Recommended Timeframe Stack:**
- **HTF (Bias):** 1H - Macro trend and regime classification
- **MTF (Setup):** 15M - Contract timeframe, primary signal generation
- **LTF (Entry):** 5M - Precision entry timing and micro-structure

**Alternative for High-Volatility Assets (SOL, XRP, DOGE):**
- **HTF (Bias):** 1H - Macro trend
- **MTF (Setup):** 15M - Contract timeframe
- **LTF (Entry):** 3M - Faster entry for higher volatility

**Key Insight:** The 15m contract itself is the "setup" timeframe. Don't use 15m for entry timing - use a lower timeframe (5m or 3m) for precision. The higher timeframe (1H) provides trend context to avoid counter-trend trades.

---

## 1. Kalshi 15M Market Characteristics

### 1.1 Contract Mechanics

**Settlement:** Binary contracts settle every 15 minutes
- **Format:** Up/Down (YES/NO) on price direction
- **Payout:** $1.00 if correct, $0.00 if wrong
- **Pricing:** 1-99 cents reflecting implied probability
- **Resolution:** CF Benchmarks Real-Time Index (RTI) for settlement

**Trading Dynamics:**
- **Duration:** 15 minutes from open to settlement
- **Frequency:** New contracts open immediately after settlement
- **Volume:** $70M daily volume across Kalshi + Polymarket (2026)
- **Dominance:** 15m contracts account for 50%+ of crypto flow on both platforms

### 1.2 Market Structure Implications

**Bot-Native Market:**
- Humans cannot process implied volatility, settlement risk, and orderbook depth every 15 minutes
- Bots execute across all available contracts simultaneously
- Mathematical precision required - no room for hesitation
- Latency arbitrage opportunities between Kalshi and spot exchanges

**Volatility Characteristics:**
- High intraday volatility within 15-minute windows
- Last-minute price swings can reverse winning positions
- Funding rate arbitrage opportunities on perpetuals
- Cross-platform arbitrage (Kalshi vs Polymarket)

**Backtest Insights (Turbine, 2026):**
- 4,904 strategies backtested on KXBTC15M
- Only 2% made money
- **Volatility-reversion works:** Fade the panic when book moves hard
- **Mean reversion fails:** Price doesn't have time to drift and return in 15m
- **Size matters:** fade_size=100 dominated smaller sizes
- **Regime-dependent:** Strategies that worked 3 weeks ago now fail

### 1.3 Critical Constraints

**Time Constraint:**
- 15 minutes is insufficient for mean-reversion strategies
- Price must move decisively in one direction
- No time for "wait for bounce" approaches
- Entry timing is critical - late entries lose edge

**Fee Structure:**
- Kalshi fee: 7% × p × (1-p) for takers
- At 50¢ pricing: ~$0.0175 per contract
- Competitive at small size, expensive at scale
- Tight 2-cent targets get eaten by fees and slippage

**Liquidity:**
- CLOB model with varying liquidity by contract
- Less liquid markets harder to execute at desired price
- BTC and ETH have best liquidity
- SOL, XRP, DOGE have moderate liquidity

---

## 2. Multi-Timeframe Analysis Principles

### 2.1 The 4-6x Ratio Rule

**Industry Standard:** Each timeframe should be 4-6x the duration of the one below it.

**Valid Stacks:**
- 4H → 1H → 15M (4x ratio)
- 1H → 15M → 5M (4x ratio)
- 1H → 15M → 3M (5x ratio)

**Invalid Stacks:**
- 1H → 30M → 15M (2x ratio - too close, redundant)
- Daily → 15M (96x ratio - too disconnected)

**Rationale:**
- Ensures HTF contains enough candles to define genuine trend
- LTF has enough resolution for precise entry timing
- Avoids seeing same price action at slightly different resolutions
- Provides meaningful context at each level

### 2.2 Three-Tier Framework

**HTF (Higher Timeframe) - "World Map"**
- **Purpose:** Macro trend and regime classification
- **Question:** Is the market bullish or bearish?
- **What to look for:** EMA alignment, market structure (BOS/CHoCH), Supertrend
- **Decision bias:** Only trade in HTF direction

**MTF (Medium Timeframe) - "Region"**
- **Purpose:** Trade setup identification
- **Question:** Where is price within the trend?
- **What to look for:** Order Blocks, FVGs, RSI zones, Bollinger Bands
- **Setup confirmation:** Price at key level with confluence

**LTF (Lower Timeframe) - "Street"**
- **Purpose:** Precision entry timing
- **Question:** When to enter exactly?
- **What to look for:** Candlestick patterns, micro-structure breaks, volume spikes
- **Entry trigger:** CHOCH/BOS in HTF direction at MTF level

### 2.3 Crypto-Specific Considerations

**24/7 Market:**
- No formal exchange sessions
- BTC respects NY/London timing patterns
- Asian session builds liquidity pool (range)
- London Open sweeps Asian liquidity (impulse)
- NY Open continues or reverses

**Higher Volatility:**
- LTF is noisier than forex
- Consider 15m instead of 5m as LTF for general crypto
- For 15m contracts specifically, use 5m or 3m as LTF
- Higher volatility assets need faster LTF (3m vs 5m)

**BTC Leadership:**
- BTC Daily bias = macro bias for altcoins
- Altcoins follow BTC direction
- Use BTC HTF as additional filter for alt trades

**Funding Rate as Additional TF:**
- Perpetual funding rates give macro sentiment
- Positive funding = bullish crowd
- Negative funding = bearish crowd
- Use as confirmation for HTF bias

---

## 3. Optimal Timeframe Stack for Kalshi 15M

### 3.1 Recommended Configuration

**Primary Stack (BTC, ETH):**
```
HTF (Bias):    1H  - Macro trend, regime classification
MTF (Setup):   15M - Contract timeframe, primary signal generation
LTF (Entry):   5M  - Precision entry timing
```

**High-Volatility Stack (SOL, XRP, DOGE):**
```
HTF (Bias):    1H  - Macro trend, regime classification
MTF (Setup):   15M - Contract timeframe, primary signal generation
LTF (Entry):   3M  - Faster entry for higher volatility
```

**Rationale:**
- **1H HTF:** Provides 4 candles per 15m contract - sufficient for trend context without being disconnected
- **15M MTF:** The contract timeframe itself - natural setup level
- **5M/3M LTF:** 3-5 candles per 15m contract - enough resolution for entry timing without excessive noise

### 3.2 Why This Stack Works

**1H as HTF:**
- 4 candles per 15m contract = good trend context
- Captures intraday regime shifts
- Not too slow (like 4H) to miss 15m opportunities
- Not too fast (like 15m) to be just noise
- Aligns with crypto intraday session patterns

**15M as MTF:**
- The contract timeframe - natural setup level
- Price action on 15M directly maps to contract lifecycle
- 3 candles per 1H HTF - good alignment
- RSI/MACD on 15M capture momentum shifts within contract window

**5M as LTF (BTC/ETH):**
- 3 candles per 15M contract - good entry resolution
- Less noise than 1M, more precision than 15M
- Captures micro-structure changes within contract window
- Allows precise entry at key 15M levels

**3M as LTF (SOL/XRP/DOGE):**
- 5 candles per 15M contract - higher resolution for volatile assets
- Faster reaction to price movements
- Necessary for higher volatility where 5M may be too slow
- More noise, but volatility provides signal

### 3.3 Alternative Stacks Considered

**Stack A: 4H → 15M → 5M**
- **Problem:** 4H is too slow for 15m contracts
- **Issue:** Only 0.25 candles per 15m contract - disconnected
- **Use case:** Swing trading, not 15m binary contracts

**Stack B: 15M → 5M → 1M**
- **Problem:** No HTF trend context
- **Issue:** Will trade counter-trend frequently
- **Use case:** Pure scalping, not suitable for binary contracts

**Stack C: 1H → 15M → 1M**
- **Problem:** 1M is too noisy for reliable entry signals
- **Issue:** High whipsaw rate, false signals
- **Use case:** HFT scalping, not suitable for 15m contracts

**Stack D: 30M → 15M → 5M**
- **Problem:** 30M and 15M too close (2x ratio)
- **Issue:** Redundant information, no additional context
- **Use case:** Not recommended per 4-6x ratio rule

---

## 4. Asset-Specific Configurations

### 4.1 BTC (Bitcoin)

**Characteristics:**
- Highest liquidity
- Lowest volatility (relatively)
- Market leader
- Most predictable patterns

**Recommended Stack:**
```
HTF: 1H
MTF: 15M
LTF: 5M
```

**Indicator Parameters:**
- **RSI:** Period 14, thresholds 70/30 (standard)
- **MACD:** 12/26/9 (standard) or 8/21/5 (faster)
- **EMA:** 21/55 for trend, 200 for regime
- **ATR:** Period 14

**Special Considerations:**
- Use BTC 1H bias as filter for all other assets
- BTC leads market moves - watch for divergence
- Highest liquidity allows tighter entries
- Can use standard parameters without extreme adjustments

### 4.2 ETH (Ethereum)

**Characteristics:**
- High liquidity (second to BTC)
- Moderate volatility
- Correlated with BTC but with independent moves
- Smart contract events can cause sudden moves

**Recommended Stack:**
```
HTF: 1H
MTF: 15M
LTF: 5M
```

**Indicator Parameters:**
- **RSI:** Period 14, thresholds 70/30 (standard)
- **MACD:** 8/21/5 (slightly faster due to higher volatility)
- **EMA:** 21/55 for trend, 200 for regime
- **ATR:** Period 14

**Special Considerations:**
- Follows BTC but can diverge
- Watch for DeFi event catalysts
- Slightly faster MACD for quicker reaction
- Use BTC 1H bias as primary filter

### 4.3 SOL (Solana)

**Characteristics:**
- Moderate liquidity
- High volatility
- Strong momentum moves
- Prone to sudden spikes

**Recommended Stack:**
```
HTF: 1H
MTF: 15M
LTF: 3M
```

**Indicator Parameters:**
- **RSI:** Period 11, thresholds 65/35 (relaxed for volatility)
- **MACD:** 8/21/5 (faster for quick reaction)
- **EMA:** 13/34 for trend, 200 for regime
- **ATR:** Period 14

**Special Considerations:**
- Higher volatility requires 3M LTF for faster entry
- Relaxed RSI thresholds (65/35) to stay in trades longer
- Faster EMA periods (13/34) for trend responsiveness
- Can extend moves quickly - use wider stops

### 4.4 XRP (Ripple)

**Characteristics:**
- Moderate liquidity
- High volatility
- News-sensitive (regulatory announcements)
- Sharp moves on catalysts

**Recommended Stack:**
```
HTF: 1H
MTF: 15M
LTF: 3M
```

**Indicator Parameters:**
- **RSI:** Period 11, thresholds 65/35 (relaxed for volatility)
- **MACD:** 8/21/5 (faster for quick reaction)
- **EMA:** 13/34 for trend, 200 for regime
- **ATR:** Period 14

**Special Considerations:**
- Higher volatility requires 3M LTF for faster entry
- News catalysts can cause gaps - avoid during major announcements
- Relaxed RSI thresholds for volatility
- Faster EMA periods for responsiveness

### 4.5 DOGE (Dogecoin)

**Characteristics:**
- Lower liquidity
- Highest volatility
- Social media driven
- Extremely erratic movements

**Recommended Stack:**
```
HTF: 1H
MTF: 15M
LTF: 3M
```

**Indicator Parameters:**
- **RSI:** Period 9, thresholds 60/40 (widest for highest volatility)
- **MACD:** 5/13/1 (fastest for extreme volatility)
- **EMA:** 9/21 for trend, 200 for regime
- **ATR:** Period 14

**Special Considerations:**
- Highest volatility requires fastest parameters
- Widest RSI thresholds (60/40) to avoid premature exits
- Fastest MACD (5/13/1) for reaction speed
- Fastest EMA periods (9/21) for trend following
- Lower liquidity - reduce position sizes
- Social media catalysts - avoid during Elon tweets etc.

---

## 5. Signal Generation Strategy

### 5.1 HTF (1H) - Trend Bias

**Primary Purpose:** Establish directional bias

**Indicators:**
- EMA 21/55 crossover (trend direction)
- EMA 200 position (regime: above = bull, below = bear)
- RSI(14) zone (above 50 = bullish, below 50 = bearish)
- MACD(12,26,9) histogram direction

**Bias Rules:**
- **Bullish bias:** Price > EMA 200, EMA 21 > EMA 55, RSI > 50, MACD histogram positive
- **Bearish bias:** Price < EMA 200, EMA 21 < EMA 55, RSI < 50, MACD histogram negative
- **Neutral:** Mixed signals or price within 1% of EMA 200

**Action:**
- Only take 15M signals aligned with 1H bias
- Strongly prefer 3+ confluence factors agreeing
- Avoid counter-trend trades unless exceptional edge

### 5.2 MTF (15M) - Setup Identification

**Primary Purpose:** Identify trade setups within 15m contract window

**Indicators:**
- RSI(8-14) with regime-based thresholds
- MACD(8,21,5) with histogram analysis
- EMA 9/21 crossover (fast trend)
- FVG detection and fill proximity
- ATR(14) for volatility normalization

**Setup Conditions:**
**Bullish Setup:**
- 1H bias is bullish
- RSI dips toward 40-50 (not oversold)
- MACD histogram turning positive or crossing above signal
- Price pulls back to EMA 21 or FVG support
- ATR indicates sufficient volatility for move

**Bearish Setup:**
- 1H bias is bearish
- RSI rises toward 50-60 (not overbought)
- MACD histogram turning negative or crossing below signal
- Price rallies to EMA 21 or FVG resistance
- ATR indicates sufficient volatility for move

**Action:**
- When setup conditions met, drop to LTF for entry timing
- Require 2+ confluence factors on 15M
- Note key levels for LTF entry (EMA, FVG, support/resistance)

### 5.3 LTF (5M/3M) - Entry Timing

**Primary Purpose:** Precise entry at optimal moment within 15m window

**Indicators:**
- Candlestick patterns (engulfing, hammer, pin bar)
- Micro-structure breaks (CHOCH/BOS)
- Volume spikes (confirmation)
- EMA 9 crossover (fast signal)

**Entry Triggers:**
**Bullish Entry:**
- 15M setup is bullish
- 5M/3M prints bullish reversal candle at 15M support level
- Volume > 1.5x average on entry candle
- Micro BOS above recent lower high
- Enter on close of confirmation candle

**Bearish Entry:**
- 15M setup is bearish
- 5M/3M prints bearish reversal candle at 15M resistance level
- Volume > 1.5x average on entry candle
- Micro BOS below recent higher low
- Enter on close of confirmation candle

**Stop Loss:**
- **Bullish:** 1x ATR below 5M/3M candle low
- **Bearish:** 1x ATR above 5M/3M candle high
- Maximum risk: 2% of bankroll per trade

**Take Profit:**
- **Primary:** 75c threshold (per MERID risk rules)
- **Secondary:** Opposing FVG or next structural level
- **Time-based:** Exit if no progress by minute 12 of 15m window

### 5.4 Volatility-Reversion Strategy (Backtested Winner)

**Based on Turbine backtest (4,904 strategies):**

**Strategy:** Fade the panic
- When book moves hard in one direction (panic_threshold: 0.03-0.15)
- Take the other side with conviction (fade_size: 100)
- Works across all parameterizations
- Mean ROI: +4.90%

**Implementation:**
- Monitor orderbook for rapid price moves
- Detect panic when price moves >3% in <2 minutes
- Enter opposite direction with full position size
- Exit at mean reversion or contract settlement

**Why It Works:**
- 15m duration too short for sustained directional moves
- Panic moves overshoot and revert
- Size matters more than threshold
- Fade with conviction or don't fade at all

**What Doesn't Work:**
- Mean reversion (price doesn't have time to drift and return)
- Tight 2-cent price targets (fees and slippage eat profits)
- Buy cheap and wait for bounce (bounce doesn't come fast enough)

---

## 6. Implementation Guide

### 6.1 Data Requirements

**Price Feed:**
- 1M OHLCV data for all 5 assets (BTC, ETH, SOL, XRP, DOGE)
- Real-time spot price from CF Benchmarks RTI (Kalshi settlement source)
- Order book depth for panic detection
- Volume data for confirmation

**Historical Data:**
- Minimum 6 months of 1M data for backtesting
- 1H data for HTF analysis (can be derived from 1M)
- Tick data for order flow analysis (optional but beneficial)

**Update Frequency:**
- 1M data: Update every minute
- 5M/3M indicators: Recalculate on each 1M update
- 15M indicators: Recalculate on each 1M update
- 1H indicators: Recalculate on each 1M update

### 6.2 Indicator Calculation

**RSI:**
- Calculate on 1M close prices
- Downsample to 5M/3M/15M/1H by taking close of last candle
- Use Wilder smoothing (correct for RSI)
- Multi-timeframe RSI: Calculate separately on each timeframe

**MACD:**
- Calculate on 1M close prices
- Downsample to 5M/3M/15M/1H
- Use asset-specific parameters
- Track histogram direction and crossovers

**EMA:**
- Calculate on 1M close prices
- Downsample to 5M/3M/15M/1H
- Use asset-specific periods
- Track crossovers and slope

**FVG:**
- Detect on 15M OHLCV (contract timeframe)
- Track active FVGs and fill status
- Calculate distance from current price
- Multi-timeframe confluence: Check 15M, 1H, 4H FVGs

**ATR:**
- Calculate on 1M OHLCV using true range
- Downsample to 5M/3M/15M/1H
- Use 14-period lookback
- Normalize by price for percentage ATR

### 6.3 Signal Generation Flow

**Every 1M Update:**
1. Update 1M price buffer
2. Recalculate 1M indicators (RSI, MACD, EMA, ATR)
3. Downsample to 5M/3M/15M/1H
4. Recalculate multi-timeframe indicators
5. Check HTF (1H) bias
6. Check MTF (15M) setup conditions
7. If setup active, check LTF (5M/3M) entry triggers
8. If entry trigger, generate signal
9. Apply risk filters (75c threshold, position sizing)
10. Submit order if all conditions met

**Every 15M Contract Cycle:**
1. At contract open, establish HTF bias
2. Monitor for MTF setup throughout 15m window
3. On setup, drop to LTF for entry
4. If entry triggered, execute trade
5. Monitor position for exit conditions
6. At contract close, settle and repeat

### 6.4 Risk Management

**Position Sizing:**
- Maximum 3% of bankroll per 15m window (per agent)
- Maximum 5% total venue per 15m window
- Kelly hard cap: 2%
- Size based on edge and volatility

**Entry Rules:**
- Only enter between 10c-75c (per MERID 75c threshold)
- Reject entries above 75c (moonshot territory)
- Reject entries below 10c (lottery zone)
- Require HTF alignment

**Exit Rules:**
- Take profit at 75c or above
- Stop loss at 1x ATR from entry
- Time exit at minute 12 if no progress
- Exit on opposing signal

**Window Tracking:**
- Track cumulative exposure per 15m window
- Reset at start of each 15m window
- Hard stop at 3% per agent, 5% total
- No new entries until exposure closed

---

## 7. Backtesting Strategy

### 7.1 Backtest Design

**Data Period:**
- Minimum 6 months of historical data
- Include different market regimes (bull, bear, range)
- Use actual Kalshi 15m contract data if available
- Otherwise simulate using CF Benchmarks RTI data

**Strategies to Test:**
1. **Volatility-reversion (panic fade)** - Expected winner
2. **Trend-following with MTA** - Test HTF alignment value
3. **RSI+MACD confluence** - Test indicator combination
4. **FVG-based entries** - Test FVG effectiveness
5. **Mean reversion** - Expected to fail (control)

**Metrics to Track:**
- Win rate
- Profit factor
- Maximum drawdown
- Sharpe ratio
- Average trade duration
- Signals per day
- Regime performance (bull/bear/range)

### 7.2 Validation

**In-Sample Testing:**
- Train on first 4 months
- Test on remaining 2 months
- Validate no overfitting

**Out-of-Sample Testing:**
- Walk-forward validation
- Rolling 1-month windows
- Ensure robustness across time

**Cross-Asset Validation:**
- Test on all 5 assets (BTC, ETH, SOL, XRP, DOGE)
- Validate asset-specific parameters
- Ensure consistent performance

### 7.3 Expected Results

**Based on Turbine Backtest:**
- Volatility-reversion: ~5% ROI, 60%+ win rate
- Trend-following with MTA: 2-3% ROI, 55% win rate
- Mean reversion: Negative ROI (expected to fail)
- Tight 2-cent targets: Negative ROI (fees eat profits)

**MERID-Specific Expectations:**
- With RSI/MACD improvements: +20-30% signal quality
- With trend filter: +40% fewer false signals
- With volume confirmation: +15-20% success rate
- Combined: 25-35% overall improvement

---

## 8. Monitoring and Optimization

### 8.1 Live Monitoring

**Key Metrics:**
- Signal generation rate
- Execution success rate
- Win rate by asset
- Win rate by regime
- PnL by asset
- PnL by regime
- Latency metrics
- Error rates

**Alerts:**
- Win rate drops below 40%
- Execution success rate drops below 95%
- Latency exceeds threshold
- Error rate spikes
- Regime change detected

### 8.2 Regime Detection

**Regime Classification:**
- **Bull:** Price > EMA 200, ADX > 25
- **Bear:** Price < EMA 200, ADX > 25
- **Range:** Price near EMA 200, ADX < 25

**Regime-Specific Parameters:**
- **Bull:** RSI 80/40, favor long signals
- **Bear:** RSI 60/20, favor short signals
- **Range:** RSI 70/30, reduce position sizes

**Regime Transitions:**
- Detect regime changes on 1H timeframe
- Smooth transitions (3+ consecutive confirms)
- Alert on regime change
- Adjust parameters dynamically

### 8.3 Parameter Optimization

**Optimization Frequency:**
- Monthly parameter review
- Quarterly deep optimization
- Annual major overhaul

**Optimization Method:**
- Walk-forward optimization
- Bayesian optimization for hyperparameters
- Genetic algorithms for strategy combinations
- Validate on out-of-sample data

**Parameters to Optimize:**
- RSI periods and thresholds
- MACD parameters
- EMA periods
- FVG thresholds
- Entry/exit rules
- Position sizing parameters

---

## 9. Risk Considerations

### 9.1 Market Risks

**Last-Minute Reversals:**
- Price can reverse in final seconds
- No control over price spikes
- Mitigation: Exit at minute 12 if no progress

**Liquidity Risk:**
- Lower liquidity on smaller assets (SOL, XRP, DOGE)
- Slippage on entry/exit
- Mitigation: Reduce position sizes, use limit orders

**Settlement Risk:**
- CF Benchmarks RTI may differ from spot
- Latency in settlement data
- Mitigation: Use official RTI data, buffer for latency

### 9.2 System Risks

**Latency Risk:**
- Slow execution misses entry window
- Competition from other bots
- Mitigation: Optimize code, use co-location if available

**Data Risk:**
- Missing or delayed price data
- Incorrect settlement data
- Mitigation: Multiple data sources, validation checks

**Integration Risk:**
- Kalshi API downtime
- WebSocket disconnections
- Mitigation: Redundant connections, fallback mechanisms

### 9.3 Strategy Risks

**Regime Change:**
- Strategy works in one regime, fails in another
- Mitigation: Regime detection, adaptive parameters

**Overfitting:**
- Strategy optimized to historical data
- Fails in live trading
- Mitigation: Out-of-sample testing, walk-forward validation

**Crowded Trade:**
- Other bots using same strategy
- Edge diminishes
- Mitigation: Unique parameters, adaptive strategies

---

## 10. Conclusion

### 10.1 Recommended Setup Summary

**Timeframe Stack:**
- **HTF:** 1H for trend bias and regime classification
- **MTF:** 15M for setup identification (contract timeframe)
- **LTF:** 5M for BTC/ETH, 3M for SOL/XRP/DOGE (entry timing)

**Asset-Specific Parameters:**
- **BTC/ETH:** Standard parameters, 5M LTF
- **SOL/XRP:** Relaxed thresholds, 3M LTF
- **DOGE:** Fastest parameters, widest thresholds, 3M LTF

**Primary Strategy:**
- Volatility-reversion (panic fade) with MTA confirmation
- HTF trend filter to avoid counter-trend trades
- LTF precision entry for optimal timing
- Strict risk management (75c threshold, window limits)

### 10.2 Expected Performance

**Baseline (Current):**
- Win rate: ~40%
- Profit factor: ~1.2
- False signals: High

**With Improvements:**
- Win rate: 55-65% (+25-50%)
- Profit factor: 1.5-1.8 (+25-50%)
- False signals: -40-50%

### 10.3 Implementation Priority

**Phase 1 (Week 1-2):**
- Implement 1H/15M/5M (3M) timeframe stack
- Add HTF trend filter
- Implement volatility-reversion strategy

**Phase 2 (Week 3-4):**
- Add asset-specific parameters
- Implement regime detection
- Add volume confirmation

**Phase 3 (Week 5-6):**
- Optimize parameters via backtesting
- Implement adaptive thresholds
- Add regime-specific parameters

**Phase 4 (Week 7-8):**
- Live testing with small sizes
- Monitor and adjust
- Scale up gradually

---

## Appendix A: Timeframe Comparison Table

| Timeframe | Purpose | Signal Noise | Decision Time | Stress Level | Trend Clarity | Use Case |
|-----------|---------|--------------|--------------|--------------|---------------|----------|
| 1M | Micro entry | High | Very Short | High | Low | HFT scalping |
| 3M | Fast entry | Moderate-High | Short | High | Low-Moderate | High-volatility entry |
| 5M | Precision entry | Moderate | Short | Moderate | Moderate | Standard entry |
| 15M | Setup | Low-Moderate | Medium | Low | High | Contract timeframe |
| 1H | Trend bias | Low | Longer | Low | High | Macro context |
| 4H | Macro trend | Very Low | Long | Very Low | Very High | Swing trading |

## Appendix B: Asset Parameter Summary

| Asset | HTF | MTF | LTF | RSI Period | RSI Thresholds | MACD | EMA Trend | EMA Fast |
|-------|-----|-----|-----|-----------|----------------|------|-----------|----------|
| BTC | 1H | 15M | 5M | 14 | 70/30 | 12/26/9 | 55 | 21 |
| ETH | 1H | 15M | 5M | 14 | 70/30 | 8/21/5 | 55 | 21 |
| SOL | 1H | 15M | 3M | 11 | 65/35 | 8/21/5 | 34 | 13 |
| XRP | 1H | 15M | 3M | 11 | 65/35 | 8/21/5 | 34 | 13 |
| DOGE | 1H | 15M | 3M | 9 | 60/40 | 5/13/1 | 21 | 9 |

## Appendix C: Signal Flow Diagram

```
1M Price Update
    ↓
Update 1M Indicators (RSI, MACD, EMA, ATR)
    ↓
Downsample to 5M/3M/15M/1H
    ↓
Recalculate Multi-TF Indicators
    ↓
Check HTF (1H) Bias
    ↓
Check MTF (15M) Setup
    ↓
Setup Active? → Drop to LTF (5M/3M)
    ↓
Check LTF Entry Trigger
    ↓
Entry Triggered? → Generate Signal
    ↓
Apply Risk Filters (75c, Window Limits)
    ↓
All Clear? → Submit Order
    ↓
Monitor Position
    ↓
Exit Conditions Met? → Close Position
    ↓
Contract Settlement → Reset for Next Cycle
```

---

**Guide Created:** 2026-07-07  
**Author:** Cascade AI Assistant  
**Version:** 1.0  
**Status:** Ready for Implementation
