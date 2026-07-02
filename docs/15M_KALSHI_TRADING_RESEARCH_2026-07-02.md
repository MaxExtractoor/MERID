# 15-Minute Kalshi Crypto Trading Research Findings
**Date:** 2026-07-02  
**Purpose:** Future development roadmap based on industry research and backtesting

## Executive Summary

Deep research across 15-minute binary options trading, Kalshi-specific strategies, and crypto prediction markets reveals critical insights:

1. **Only 2% of strategies make money on Kalshi BTC 15M** (Turbine backtest: 4,904 strategies tested)
2. **Volatility reversion (panic fade) is the ONLY profitable strategy** - 93 of 96 variants profitable
3. **Directional prediction is near-random** - State-of-the-art ML achieves 53.1% accuracy (barely above 50%)
4. **Current system lacks key production features** - No ML ensemble, no multi-exchange data, no regime detection

## Key Research Sources

### Turbine Backtest (4,904 strategies on KXBTC15M)
- **Source:** https://www.turbinefi.com/blog/5000-strategy-backtest-kalshi-btc-15m
- **Scope:** 30 days of Kalshi BTC 15-minute markets, 41.8 million simulated trades
- **Key Finding:** Only 102 strategies made money (2.1% success rate)

### GRDazzle Production Bot
- **Source:** https://github.com/GRDazzle/BTC-15-Minute-Trading-Bot
- **Architecture:** Stacked ensemble (LSTM + XGB) with multi-exchange data
- **Performance:** Production-grade with walk-forward PnL optimization

### Binary Options Research
- **Sources:** TradersUnion, DayTrading.com, BinaryOptions.co.uk
- **Key Strategies:** Opening range breakout, momentum, volume, straddle
- **Best Practices:** Kelly Criterion sizing, regime-aware timing, multi-timeframe confirmation

## Critical Findings

### 1. What Works on Kalshi 15M

#### Panic Fade (Volatility Reversion)
- **Success Rate:** 93 of 96 variants profitable (96.9%)
- **Mean ROI:** +4.90%
- **Best Variant:** +18.32% (panic_threshold=0.04, fade_size=100)
- **Logic:** When the book moves hard in 15 minutes, take the other side
- **Key Insight:** Size matters more than threshold - fade_size=100 dominated

#### What DOES NOT Work
- **Mean Reversion:** 0 for 432 profitable (duration too short for 15m markets)
- **Tight Price Thresholds:** 62-63% win rate but 75-78% loss (fees/slippage)
- **Directional Prediction:** 53.1% accuracy (barely above random)

### 2. Production Bot Architecture

#### Stacked Ensemble
```
LSTM(180s bars) → lstm_p → XGB(51 features + lstm_p) → final probability → threshold gate → trade
```

#### Multi-Exchange Data
- Three exchange feeds (Coinbase, Kraken, Bitstamp)
- Cross-exchange features capture price divergence and market disagreement
- Eliminates ~17% label mismatch from single-exchange price direction

#### Walk-Forward Optimization
- Hyperparameters selected by out-of-sample PnL (not log-loss)
- Per-asset configuration (different features/thresholds per asset)
- Weekly retraining on fresh data

### 3. 15-Minute Binary Options Best Practices

#### Entry Timing
- **Opening Range Breakout:** Wait for decisive break with volume
- **Confirmation:** 9-EMA/20-SMA alignment, RSI above 50 (bullish) or below 50 (bearish)
- **Best Windows:** Post-resolution (15-30 min after major events), evening trading (7-10 PM ET)

#### Position Sizing
- **Kelly Criterion:** Edge / Odds
- **Practical Rule:** Never risk more than 3-5% of bankroll per contract
- **Half-Kelly/Quarter-Kelly:** Account for model uncertainty

#### Volume Strategy
- **High Volume:** Predict continuation in same direction
- **Low Volume:** Predict reversal
- **Average Volume:** Ignore the period

#### Straddle Strategy
- **Concept:** Hedge YES/NO positions for risk management
- **Benefit:** Can profit from volatility regardless of direction
- **Implementation:** Buy both sides when uncertainty is high

## Current System Gaps

### Critical Gaps (High Priority)
1. **No panic fade strategy** - The ONLY profitable strategy on KXBTC15M
2. **No multi-exchange data** - Missing cross-exchange arbitrage signals
3. **No machine learning ensemble** - Rule-based vs LSTM/XGB stacked ensemble
4. **No regime detection** - Strategies are regime-dependent but we don't detect changes
5. **Label mismatch** - Likely using Coinbase price vs Kalshi settlement outcomes

### Configuration Gaps (Medium Priority)
6. **No per-asset optimization** - Same parameters across all 5 assets
7. **No walk-forward model selection** - Static vs PnL-optimized over time
8. **No panic detection** - Don't detect rapid price moves to fade
9. **Tight spread thresholds** - May be over-filtering (max_spread_cents=25)

### Strategic Gaps (Long-Term)
10. **No straddle/hedging strategy** - Can hedge YES/NO positions
11. **No boundary options logic** - Can win on momentum regardless of direction
12. **No take-profit optimization** - Close early when contract moves sharply in favor

## Recommended Implementation Roadmap

### Phase 1: Immediate (High Impact)
1. **Implement panic fade strategy**
   - Detect rapid price moves (panic_threshold)
   - Fade with conviction (fade_size=100)
   - Use volatility reversion logic

2. **Add multi-exchange data feeds**
   - Integrate Kraken and Bitstamp APIs
   - Add cross-exchange price divergence features
   - Use composite market view

3. **Use Kalshi settlement labels**
   - Train on actual settlement outcomes
   - Eliminate Coinbase price direction mismatch
   - Fetch via Kalshi API

4. **Add regime detection**
   - Detect market regime changes
   - Adapt strategy based on regime
   - Use volatility and trend metrics

### Phase 2: Medium-Term
5. **Implement stacked ensemble**
   - LSTM for sequence modeling (180s bars)
   - XGB for final decision with 51 features
   - Walk-forward PnL optimization

6. **Per-asset configuration**
   - Different feature sets per asset
   - Asset-specific thresholds and parameters
   - Walk-forward selection per asset

7. **Add straddle/hedging logic**
   - Hedge YES/NO positions
   - Risk management through diversification
   - Profit from volatility regardless of direction

8. **Optimize take-profit timing**
   - Close early when contract moves sharply in favor
   - Lock in profit before binary settlement
   - Free capital for new opportunities

### Phase 3: Long-Term
9. **Implement boundary options**
   - Win on momentum regardless of direction
   - Use when market is volatile but direction unclear
   - Higher win rate on pure momentum plays

10. **Add volume surge detection**
    - High volume = continue direction
    - Low volume = predict reversal
    - Combine with momentum signals

11. **Optimize timing windows**
    - Focus on post-resolution windows
    - Evening trading (7-10 PM ET)
    - Avoid final hours before high-uncertainty events

12. **Dynamic position sizing**
    - Kelly Criterion with regime awareness
    - Adjust size based on confidence
    - Half-Kelly/Quarter-Kelly for uncertainty

## Key Metrics to Track

### Performance Metrics
- Win rate (target: >55%)
- ROI per trade (target: >2%)
- Maximum drawdown (target: <20%)
- Sharpe ratio (target: >1.5)

### Execution Metrics
- Order fill rate (target: >90%)
- Slippage (target: <2 cents)
- Latency (target: <500ms)
- Rejection rate (target: <5%)

### Model Metrics
- Prediction accuracy (target: >53%)
- Calibration (Brier score)
- Regime detection accuracy
- Feature importance drift

## Risk Management Principles

1. **Never risk more than 3-5% of bankroll per contract**
2. **Use half-Kelly or quarter-Kelly for model uncertainty**
3. **Avoid illiquid markets (spread >5 cents, OI <$500)**
4. **Take profit early when contract moves sharply in favor**
5. **Diversify across assets, timelines, and directions**
6. **Stop trading if daily loss exceeds 5% of bankroll**
7. **Avoid trading in final hours before high-uncertainty events**

## Conclusion

The fundamental insight from this research is that **15-minute crypto markets are too efficient for directional prediction**. The edge comes from **fading panic moves (volatility reversion)**, not predicting direction. State-of-the-art ML achieves only 53.1% accuracy, barely above random.

The current system uses rule-based velocity signals with good risk management, but it's missing the volatility reversion strategy that is the ONLY profitable approach on Kalshi BTC 15M. Implementing panic fade, multi-exchange data, ML ensemble, and regime detection will significantly improve performance.

**Key Takeaway:** Focus on volatility reversion (panic fade) rather than directional prediction for 15-minute Kalshi crypto markets.
