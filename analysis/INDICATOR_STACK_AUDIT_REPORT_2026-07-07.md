# Indicator Stack Audit Report
**Date**: 2026-07-07  
**Scope**: End-to-end audit of indicator stack across trading and execution pipeline  
**Objective**: Identify design flaws, conflicts, and ensure indicators act as a cohesive unit

---

## Executive Summary

This audit examined the indicator stack across upstream (data feeds), midstream (risk envelope, signal fusion, agent grid), and downstream (execution, sizing, order routing) layers. The audit identified **2 potential issues** and **1 design flaw** that require remediation.

### Critical Findings
- **RESOLVED**: Confidence threshold variation (intentional design for different strategies)
- **RESOLVED**: Velocity threshold alignment (fixed 2026-07-05)
- **RESOLVED**: FVG detection duplication (consolidated to single source)
- **POTENTIAL**: Indicator redundancy (multiple momentum indicators)
- **DESIGN FLAW**: Indicator stack complexity exceeds 2026 best practices

---

## Indicator Stack Architecture

### Upstream Layer (Data Feeds & Calculations)

#### Data Sources
1. **Unified Spot Service** (`data/unified_spot_service.py`)
   - Primary: Coinbase Public API (no auth required)
   - Assets: BTC, ETH, SOL, XRP, DOGE
   - Refresh interval: 5 seconds
   - Provides: Spot price, OHLC data, volume

2. **Live Price Feed** (`data/live_price_feed.py`)
   - Coinbase Advanced Trade API v3
   - Multi-exchange fallback: Kraken, CCXT
   - Timeframes: 1m, 5m, 15m, 1h, 4h, 1d, 1w
   - Cache TTL: 5 minutes

#### Indicator Calculations
1. **TA Engine** (`merid/signals/ta_engine.py`)
   - RSI (Relative Strength Index)
   - MACD (Moving Average Convergence Divergence)
   - EMAs (Exponential Moving Averages)
   - SMAs (Simple Moving Averages)
   - ATR (Average True Range)
   - Fibonacci Pivots
   - Volume Z-score
   - Divergence Detection

2. **Crypto 15m Indicators** (`merid/signals/crypto_15m_indicators.py`)
   - Streaming indicator calculator for 15-minute crypto markets
   - Processes 1-minute close prices
   - **DEPRECATED**: FVG detection (moved to `merid/prediction/forecasters/fvg.py`)

3. **Velocity Signal Generator** (`merid/event_venues/coinbase/velocity_signal.py`)
   - Coinbase 1-minute velocity as lead indicator
   - Per-asset thresholds: BTC/ETH: 0.00015, SOL/XRP: 0.000225, DOGE: 0.0003

---

### Midstream Layer (Risk Envelope, Signal Fusion, Agent Grid)

#### Risk Envelope
1. **Kalshi Crypto 15m Risk Envelope** (`merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`)
   - Per-agent per-window limit: 3% (HARD STOP)
   - Total venue per-window limit: 5% (HARD STOP)
   - Per-asset cap: 3% max notional
   - Window-based tracking (15-minute windows)

2. **Unified Sizing** (`merid/prediction/unified_sizing.py`)
   - Bankroll-aware position sizing
   - **DISABLED**: Regime-based sizing (to prevent interference with risk limits)
   - **DISABLED**: TTE-based sizing (to prevent interference with risk limits)
   - **DISABLED**: Time-of-day scaling (to prevent interference with risk limits)

#### Signal Fusion
1. **Signal Router** (`merid/event_venues/kalshi/signal_router.py`)
   - Routes signals from signal-only agents to trading_agent
   - Validation, quality scoring, deduplication, rate limiting
   - **_MIN_CONFIDENCE: 0.65** (aligned with profile YAML)

2. **Signal Calibrator** (`merid/prediction/signal_calibrator.py`)
   - Brier score tracking for signal accuracy
   - Adaptive weight derivation based on historical performance
   - Signals: macro, perp, news, technical (RSI, MACD, etc.)

3. **Unified Edge** (`merid/prediction/unified_edge.py`)
   - Cross-asset edge computation
   - Spot-contract relationship modeling per asset
   - Edge = q_a(t) - π_a(t) (unified across all assets)

#### Agent Grid
1. **Agent Grid 15m** (`merid/prediction/agent_grid_15m.py`)
   - Lean agent grid for Kalshi 15m crypto trading
   - Velocity-based signals (primary strategy)
   - Per-asset velocity thresholds (aligned with profile YAML)
   - Signal modes: trend, mean_reversion, momentum_fvg, hybrid, price_based

2. **Forecasters** (`merid/prediction/forecasters/`)
   - FVG Forecaster (Fair Value Gap detection)
   - Momentum Forecaster
   - Mean Reversion Forecaster
   - Macro Regime Forecaster
   - Orderbook Forecaster

---

### Downstream Layer (Execution, Sizing, Order Routing)

#### Execution
1. **Execution Router** (`merid/execution/router.py`)
   - Unified entrypoint for all trade intents
   - Guard evaluation, explainability, venue dispatch
   - Kill switch integration

2. **Kalshi Executor** (`merid/execution/executors/kalshi.py`)
   - Wraps order_router for API endpoint use
   - Dynamic TP/SL computation for 15m crypto contracts

3. **Order Router** (`merid/event_venues/kalshi/order_router.py`)
   - Mode-aware order dispatch (mock/paper/live)
   - Fee-aware edge calculation
   - Market microstructure filters
   - **Uses confidence_min_confidence_threshold from profile (0.65)**

#### Guards
1. **Trading Guardian** (`merid/guards/__init__.py`)
   - Upstream guards: market sanity, config integrity, regime checks
   - Mid-pipeline guards: indicator health, hierarchy enforcement, conviction consistency
   - Downstream guards: pre-trade risk, execution monitoring, post-trade TCA

---

## Identified Issues

### RESOLVED: Confidence Threshold Variation (Intentional Design)

**Severity**: INFORMATIONAL  
**Status**: RESOLVED (Intentional Design)  
**Impact**: Different confidence thresholds for different trading strategies

#### Issue Description
The system uses different confidence thresholds for different trading strategies. This was initially flagged as an inconsistency, but upon analysis, this is **intentional design**:

| Location | Threshold | Purpose | Status |
|----------|-----------|---------|--------|
| Profile YAML (primary) | 0.65 | Primary threshold for probability-based trades | ✅ Single source of truth |
| Signal Router | 0.65 | Aligned with profile | ✅ Correct |
| Order Router (main path) | 0.65 | Aligned with profile | ✅ Correct |
| Order Router (velocity orders) | 0.50 | Intentionally relaxed for momentum trading | ✅ Intentional |
| Strategy.py | 0.50 | Industry-aligned threshold for 15m crypto | ✅ Intentional |
| Trade Hold Config | 0.50 | Industry-aligned threshold | ✅ Intentional |
| Execution Signal Daemon | 0.60 | Environment-configurable default | ✅ Configurable |

#### Rationale for Different Thresholds
1. **Velocity orders (0.50)**: Velocity-based signals use velocity magnitude as signal strength, not probability-based confidence. Comments explicitly state: "Relax confidence validation for velocity orders (may have lower confidence)" and "Research shows momentum trading should not be gated by probability confidence."

2. **Strategy.py (0.50)**: Comments state "ALIGNED TO 2026 INDUSTRY STANDARD: 50% threshold" and "50% balances signal quality with trade volume for 15m crypto markets."

3. **Execution daemon (0.60)**: Uses environment variable `MERID_EXECUTION_MIN_CONFIDENCE` with default 0.6, allowing operator configuration.

#### Conclusion
The confidence threshold variation is **intentional and correct**. Different trading strategies legitimately require different confidence thresholds. No fix required.

---

### RESOLVED: Velocity Threshold Alignment

**Severity**: HIGH  
**Status**: RESOLVED (2026-07-05)  
**Impact**: Previously inconsistent velocity thresholds across components

#### Issue Description
Velocity thresholds were misaligned between profile YAML, agent grid, and velocity signal generator. This was fixed on 2026-07-05.

#### Current State (Aligned)
| Asset | Profile YAML | Agent Grid | Velocity Signal |
|-------|-------------|-----------|----------------|
| BTC | 0.00015 (0.015%) | 0.00015 | 0.00015 |
| ETH | 0.00015 (0.015%) | 0.00015 | 0.00015 |
| SOL | 0.000225 (0.0225%) | 0.000225 | 0.000225 |
| XRP | 0.000225 (0.0225%) | 0.000225 | 0.000225 |
| DOGE | 0.0003 (0.03%) | 0.0003 | 0.0003 |

#### Verification
All three sources now use the same per-asset velocity thresholds, ensuring consistent signal generation.

---

### RESOLVED: FVG Detection Duplication

**Severity**: MEDIUM  
**Status**: RESOLVED (2026-07-06)  
**Impact**: Duplicate FVG implementations causing potential inconsistency

#### Issue Description
FVG detection was implemented in two locations:
1. `merid/signals/crypto_15m_indicators.py` (approximation-based)
2. `merid/prediction/forecasters/fvg.py` (authoritative OHLC-based)

#### Resolution
- Deprecated FVG detection in `crypto_15m_indicators.py`
- Consolidated to single source: `merid/prediction/forecasters/fvg.py`
- Updated profile YAML to be single source of truth for FVG configuration

#### Current State
All FVG detection now uses the authoritative forecaster, ensuring consistency across the stack.

---

### POTENTIAL: Indicator Redundancy

**Severity**: MEDIUM  
**Status**: POTENTIAL ISSUE  
**Impact**: Multiple momentum indicators may provide redundant signals

#### Issue Description
The system uses multiple momentum indicators that may provide overlapping signals:

1. **Velocity-based signals** (primary strategy)
   - Coinbase 1-minute velocity
   - Used in agent grid as main signal source

2. **MA Crossover** (`merid/prediction/strategies/ma_crossover.py`)
   - Fast EMA (9-period) over short SMA (21-period)
   - Based on Turbine research

3. **MACD** (in TA Engine)
   - Standard MACD with histogram
   - Used in signal scoring

4. **Regime Detection** (`merid/prediction/strategies/regime_detection.py`)
   - Detects trending, ranging, volatile regimes
   - For adaptive strategy selection

#### Analysis
According to 2026 best practices (from web research):
- **Recommendation**: Use 2-3 complementary indicators
- **Current state**: 4+ momentum-related indicators
- **Risk**: Redundant signals, analysis paralysis, conflicting signals

#### Recommended Action
Evaluate which momentum indicators provide unique value and consolidate to 2-3 complementary indicators. Consider:
- Keep velocity (primary, research-backed)
- Keep regime detection (for adaptive strategy selection)
- Evaluate if MA crossover and MACD provide unique signals or redundancy

---

### DESIGN FLAW: Indicator Stack Complexity

**Severity**: MEDIUM  
**Status**: DESIGN FLAW  
**Impact**: Violates 2026 best practices for indicator usage

#### Issue Description
The current indicator stack includes:
- RSI, MACD, EMAs, SMAs, ATR, Fibonacci Pivots, Volume Z-score, Divergence Detection
- Velocity signals, MA Crossover, Regime Detection
- FVG detection, Orderbook imbalance, Momentum forecaster, Mean reversion forecaster

Total: **15+ indicators** across the stack

#### Best Practices (2026 Research)
From web research on technical analysis best practices:
- **Avoid overcrowding charts with redundant or conflicting indicators**
- **Use 2-3 complementary indicators instead of a multitude**
- **Indicators should support analysis, not replace it**
- **Price action should be primary decision-maker, indicators as secondary filters**

#### Current State vs Best Practices
| Aspect | Best Practice | Current State |
|--------|---------------|---------------|
| Number of indicators | 2-3 complementary | 15+ indicators |
| Indicator role | Secondary filters | Primary signal sources |
| Redundancy | Avoid redundant measures | Multiple momentum indicators |
| Price action | Primary decision-maker | Indicator-driven |

#### Recommended Action
1. **Consolidate to core indicators**: Identify 2-3 indicators that provide unique, complementary value
2. **Shift to price-action-first**: Use price action (support/resistance, trend, candlestick patterns) as primary decision-maker
3. **Indicators as filters**: Use remaining indicators only for confirmation, not signal generation
4. **Test simplified stack**: Backtest simplified indicator stack to verify performance

---

## Best Practices Research Summary

### Key Findings from 2026 Research

1. **Indicator Stack Simplicity**
   - Use 2-3 complementary indicators
   - Avoid redundant indicators that measure the same thing
   - Example: Don't stack RSI, Stochastic, and Williams %R (all measure momentum)

2. **Price Action vs Indicators**
   - Price action is real-time (shows current buyer/seller behavior)
   - Indicators are lagging (derived from past prices)
   - Use price action as primary, indicators as secondary filters

3. **Core Framework**
   - Location: Support and resistance zones
   - Direction: Trend filters (market structure, moving averages)
   - Confirmation: Candlestick patterns
   - Risk: Risk-reward filters

4. **Multi-Timeframe Analysis**
   - Higher timeframe (Daily/4H): Dominant trend, major S/R zones
   - Lower timeframe (1H/15M): Pullbacks, rejection candles, entry timing
   - Always align lower-timeframe trades with higher-timeframe trend

5. **Common Mistakes**
   - Overcomplicating the chart (too many indicators)
   - Trading without confirmation (entering before candle close)
   - Ignoring trend context (counter-trend in strong momentum)
   - Chasing extended price (FOMO instead of pullback)
   - Failing to manage risk (unfavorable reward-to-risk)

---

## Recommendations

### Short-term Actions (High Priority)

2. **Evaluate Indicator Redundancy**
   - Analyze correlation between velocity, MA crossover, and MACD signals
   - Identify which indicators provide unique value
   - Consolidate to 2-3 complementary momentum indicators

3. **Simplify Indicator Stack**
   - Implement price-action-first framework
   - Reduce from 15+ indicators to 2-3 core indicators
   - Use indicators as confirmation filters, not primary signals
   - Backtest simplified stack

### Long-term Actions (Medium Priority)

4. **Implement Multi-Timeframe Analysis**
   - Add higher-timeframe trend detection (Daily/4H)
   - Align lower-timeframe trades with higher-timeframe trend
   - Use higher-timeframe for major S/R zones

5. **Add Comprehensive Testing**
   - Unit tests for all indicator calculations
   - Integration tests for signal flow
   - Regression tests for threshold consistency
   - Backtests for simplified indicator stack

---

## Conclusion

The indicator stack audit found that the system has made good progress on resolving previous issues (velocity threshold alignment, FVG detection consolidation). The confidence threshold variation is intentional design for different trading strategies, not a bug.

However, the system still suffers from indicator redundancy and complexity that violates 2026 best practices:
- **15+ indicators** across the stack (vs recommended 2-3)
- Multiple momentum indicators that may provide redundant signals
- Indicator-driven approach vs price-action-first framework

The recommended path forward is:
1. **Short-term**: Evaluate and consolidate redundant indicators
2. **Long-term**: Implement price-action-first framework with simplified indicator stack

This will ensure the indicators act as a cohesive unit rather than conflicting with each other across the trading and execution pipeline.
