# MERID 15M Kalshi Crypto - Profitability Gap Analysis

**Date:** 2026-06-28  
**Profile:** kalshi_crypto_15m_v2  
**Scope:** Full stack audit for profitability optimization opportunities

---

## Executive Summary

This comprehensive audit analyzed the entire MERID 15M Kalshi crypto trading stack against industry best practices for prediction market profitability. The audit covered 7 major layers: signal generation, order execution, position management, market data/latency, risk management, portfolio construction, and backtesting infrastructure.

**Key Finding:** The system has solid foundational infrastructure but is missing several high-impact profitability features that are standard in profitable prediction market bots. The most significant gaps are in arbitrage strategies (YES/NO sum arbitrage and cross-venue probability arbitrage), which generated ~$150k in profits for a single bot in the industry.

---

## High-Impact Gaps (Priority 1)

### 1. YES/NO Sum Arbitrage - MISSING ⚠️

**Industry Reference:**  
- CoinDesk (2026-02-21): Bot executed 8,894 trades on YES/NO sum < $1 arbitrage
- Profit: ~$150k total, ~$16.80 per trade
- Edge: 1.5-3% per trade
- Duration: Fleeting milliseconds window

**Current State:**
- ✅ Duality validator exists (`merid/event_venues/kalshi/duality_validator.py`)
- ✅ Detects YES+NO ≠ 100c violations
- ❌ Only used for data integrity validation
- ❌ NO arbitrage execution logic
- ❌ NO profit capture from these opportunities

**Gap:**  
The system detects YES/NO sum violations but does NOT execute trades to capture the arbitrage profit. This is a significant missed opportunity.

**Implementation Required:**
```python
# Pseudo-code for arbitrage execution
if yes_ask + no_ask < 100 - threshold:
    # Buy both YES and NO
    # Lock in risk-free profit
    # Execute within milliseconds
```

**Files to Modify:**
- `merid/event_venues/kalshi/duality_validator.py` - Add arbitrage detection
- `merid/event_venues/kalshi/order_router.py` - Add arbitrage execution path
- `config/profiles/kalshi_crypto_15m_v2.yaml` - Enable arbitrage feature flag

**Estimated Impact:** HIGH (1.5-3% per trade, high frequency)

---

### 2. Cross-Venue Probability Arbitrage - MISSING ⚠️

**Industry Reference:**  
- Compare prediction market pricing to options market implied probabilities
- Identify discrepancies (e.g., options imply 62% vs prediction market 55%)
- Trade the mispriced side
- Small edges (few percentage points) compound at high frequency

**Current State:**
- ✅ Implied probability calculation exists
- ✅ Options pricing infrastructure exists in legacy code
- ❌ NO active options market data feed
- ❌ NO cross-venue probability comparison
- ❌ NO arbitrage execution based on probability discrepancies

**Gap:**  
Missing integration with options markets to identify and trade probability arbitrage opportunities.

**Implementation Required:**
1. Add options market data feed (e.g., Deribit for crypto options)
2. Compute implied probabilities from options pricing
3. Compare with Kalshi prediction market prices
4. Execute arbitrage when discrepancy exceeds threshold

**Files to Modify:**
- New: `merid/event_venues/options/` - Options market adapter
- New: `merid/prediction/probability_arbitrage.py` - Probability comparison logic
- `config/profiles/kalshi_crypto_15m_v2.yaml` - Enable options integration

**Estimated Impact:** HIGH (few % per trade, medium frequency)

---

## Medium-High Impact Gaps (Priority 2)

### 3. Market Making - DISABLED ⚠️

**Industry Reference:**  
- Liquidity provision earns spread income
- Continuously place bids and asks
- Maintain near-neutral directional exposure
- Profit from bid-ask spread

**Current State:**
- ✅ Market maker integration exists (`merid/kalshi/mm_integration.py`)
- ✅ Maker/taker policy engine exists
- ✅ Two-sided quoting logic implemented
- ❌ Market making DISABLED in production profile
- ❌ No active liquidity provision

**Gap:**  
Market making infrastructure exists but is not enabled, missing spread income opportunities.

**Implementation Required:**
1. Enable market making in profile configuration
2. Configure quoting parameters (spread, inventory limits)
3. Add risk controls for inventory management
4. Test in paper trading before live

**Files to Modify:**
- `config/profiles/kalshi_crypto_15m_v2.yaml` - Enable market making
- `merid/kalshi/mm_integration.py` - Tune quoting parameters

**Estimated Impact:** MEDIUM-HIGH (spread income, continuous)

---

### 4. Correlation-Adjusted Position Sizing - NOT ENABLED ⚠️

**Industry Reference:**  
- Reduce exposure when assets are highly correlated
- Prevent over-concentration in correlated positions
- Dynamic sizing based on correlation matrix

**Current State:**
- ✅ Correlation tracker exists (`merid/risk/correlation.py`)
- ✅ Portfolio optimizer with correlation matrix exists
- ✅ Correlation-adjusted sizing logic implemented
- ❌ Correlation tracking NOT enabled in profile
- ❌ NO correlation-based position sizing in production

**Gap:**  
Correlation infrastructure exists but is not used in the production profile, potentially leading to over-concentration risk.

**Implementation Required:**
1. Enable correlation tracking in profile
2. Configure correlation thresholds
3. Integrate correlation multiplier into position sizing
4. Monitor correlation matrix in real-time

**Files to Modify:**
- `config/profiles/kalshi_crypto_15m_v2.yaml` - Enable correlation tracking
- `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py` - Add correlation multiplier

**Estimated Impact:** MEDIUM (risk reduction, potential capital efficiency)

---

## Medium Impact Gaps (Priority 3)

### 5. Over-Conservative Kelly Fraction

**Industry Reference:**  
- Industry standard: 20-60% fractional Kelly
- Polymarket bots: 25-75% Kelly fraction
- Our system: 3-5% Kelly (very conservative)

**Current State:**
- Kelly fraction: 3-5% (tiered by asset)
- Very conservative sizing
- May be limiting profitability

**Gap:**  
Kelly fraction is significantly more conservative than industry standards, potentially limiting capital efficiency.

**Implementation Required:**
1. Backtest higher Kelly fractions (10-15%)
2. Validate with historical data
3. Gradually increase if validated
4. Monitor drawdown closely

**Files to Modify:**
- `config/profiles/kalshi_crypto_15m_v2.yaml` - Increase kelly_fraction
- `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py` - Update Kelly logic

**Estimated Impact:** MEDIUM (higher returns, higher risk)

---

### 6. Consecutive Loss Tracking - MISSING

**Industry Reference:**  
- Standard: Halt after 6 consecutive losses
- Prevents extended losing streaks
- Cooldown period before resuming

**Current State:**
- ❌ No consecutive loss tracking
- ❌ No consecutive loss halt logic
- Only drawdown-based halts

**Gap:**  
Missing consecutive loss tracking, which is a standard industry safeguard.

**Implementation Required:**
1. Add consecutive loss counter per asset
2. Implement halt after N consecutive losses
3. Add cooldown period
4. Log consecutive loss events

**Files to Modify:**
- `merid/event_venues/kalshi/position_cache.py` - Track consecutive losses
- `config/profiles/kalshi_crypto_15m_v2.yaml` - Configure consecutive loss limit

**Estimated Impact:** LOW-MEDIUM (risk management, not direct profitability)

---

## Low Impact Gaps (Priority 4)

### 7. Advanced ML Models

**Current State:**
- ✅ Ensemble forecasting exists
- ✅ Multiple forecasters (momentum, macro regime, FVG)
- ❌ No deep learning models
- ❌ No transformer-based models

**Gap:**  
Missing advanced ML models that could improve signal accuracy.

**Implementation Required:**
1. Research ML model effectiveness for 15m prediction markets
2. Implement and backtest
3. Integrate with ensemble

**Estimated Impact:** LOW (marginal signal improvement, high complexity)

---

### 8. Additional Asset Coverage

**Current State:**
- 5 assets: BTC, ETH, SOL, XRP, DOGE
- Comprehensive coverage of major crypto assets

**Gap:**  
Could add more assets (e.g., ADA, DOT, AVAX) for diversification.

**Implementation Required:**
1. Add asset to profile configuration
2. Configure risk parameters
3. Test in paper trading

**Estimated Impact:** LOW (marginal diversification, liquidity constraints)

---

## Existing Strengths (No Action Needed)

### ✅ Signal Generation
- Velocity-based signals (Coinbase 1m) - industry-winning strategy
- Multi-window velocity with EMA smoothing
- Ensemble forecasting with calibration weights
- Price-based strategy with dynamic thresholds
- Momentum FVG integration

### ✅ Order Execution
- Smart order routing (maker/taker decision)
- Latency tracking and optimization
- Sub-200ms WebSocket orderbook feeds
- Paper fill simulation with orderbook

### ✅ Position Management
- Dynamic take-profit (R-multiple based)
- Trailing stop implementation
- Stop loss with ATR-based sizing
- Position monitor with exit policies

### ✅ Market Data
- Real-time WebSocket feeds
- KalshiMarketStateStore for live orderbook
- Latency buffer calibration
- CF Benchmarks RTI integration

### ✅ Risk Management
- Conservative but safe parameters
- Drawdown-based adaptive risk bands
- Per-asset and venue-level caps
- Kelly criterion sizing

### ✅ Backtesting
- Determinism replay
- Historical simulator
- Paper trading engine
- Monte Carlo simulation

---

## Prioritized Action Plan

### Phase 1: Quick Wins (1-2 weeks)
1. **Enable YES/NO Sum Arbitrage** - Add arbitrage execution to duality validator
2. **Enable Market Making** - Activate existing MM integration with proper config
3. **Enable Correlation Tracking** - Turn on existing correlation tracker in profile

### Phase 2: Medium-Term (1-2 months)
4. **Implement Cross-Venue Probability Arbitrage** - Add options market integration
5. **Optimize Kelly Fraction** - Backtest and increase to 10-15%
6. **Add Consecutive Loss Tracking** - Implement standard safeguard

### Phase 3: Long-Term (3-6 months)
7. **Advanced ML Models** - Research and implement if beneficial
8. **Additional Assets** - Expand coverage if liquidity allows

---

## Risk Considerations

### High-Risk Changes
- YES/NO arbitrage: Requires sub-millisecond execution
- Cross-venue arbitrage: Requires options market integration
- Higher Kelly: Increases drawdown risk

### Medium-Risk Changes
- Market making: Requires inventory management
- Correlation tracking: May reduce position sizes

### Low-Risk Changes
- Consecutive loss tracking: Pure risk management
- ML models: Can be tested thoroughly before deployment

---

## Conclusion

The MERID 15M Kalshi crypto system has excellent foundational infrastructure but is missing several high-impact profitability features that are standard in the industry. The most significant opportunities are:

1. **YES/NO Sum Arbitrage** - Could generate 1.5-3% per trade at high frequency
2. **Cross-Venue Probability Arbitrage** - Could generate few % per trade at medium frequency
3. **Market Making** - Could generate spread income continuously

These three features alone could significantly improve profitability, with YES/NO arbitrage being the highest priority given its proven track record ($150k from 8,894 trades in the industry).

The system's conservative risk parameters (3-5% Kelly, 15% drawdown halt) are safe but may be limiting capital efficiency. Gradual optimization of these parameters with proper backtesting could improve returns without significantly increasing risk.

Overall, the system is well-positioned to implement these enhancements and achieve industry-leading profitability in prediction market trading.
