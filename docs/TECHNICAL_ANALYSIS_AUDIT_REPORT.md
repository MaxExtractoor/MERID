# Technical Analysis Audit Report
## MERID 15-Minute Kalshi Crypto Trading System

**Audit Date:** 2026-07-06  
**Scope:** End-to-end audit of technical analysis components across upstream (configuration), midstream (signal generation), and downstream (execution) layers  
**Assets:** BTC, ETH, SOL, XRP, DOGE (complete crypto stack)

---

## Executive Summary

This audit comprehensively reviewed all technical analysis components in the MERID 15-minute Kalshi crypto trading system, including FVG, momentum, volatility, velocity, trend, candle patterns, reversal awareness, hedging, take profit, ratchet, and 99c exit logic. The audit identified several critical discrepancies, wiring gaps, and inconsistencies that require remediation.

**Key Findings:**
- **Critical Discrepancy:** FVG detection uses two different implementations with different OHLC data sources
- **Configuration Fragmentation:** FVG forecaster uses environment variables instead of profile YAML
- **Wiring Gap:** MACD and RSI indicators computed but not used in primary velocity-based signal path
- **Asset Inconsistency:** EMA periods differ by asset but velocity thresholds are uniform
- **Exit Logic Complexity:** Multiple overlapping exit mechanisms (ratchet, 99c, staged, adaptive) with unclear precedence

---

## 1. Upstream Layer (Configuration)

### 1.1 Single Source of Truth
**File:** `config/profiles/kalshi_crypto_15m_v2.yaml`

**Status:** ✅ **PRIMARY CONFIGURATION SOURCE**

The profile YAML is the authoritative source for risk and strategy parameters:
- `signal_mode: momentum_fvg` - Primary signal mode based on Turbine research
- `momentum_fvg` section - RSI, MACD, OBI, FVG parameters
- `ratchet_profit_floor` - Profit locking mechanism with 99c mandatory exit
- `staged_time_exit` - Time-based partial exits
- `dynamic_sizing` - Edge and confidence-based position scaling
- `price_based` - Swing trading price thresholds
- `hybrid` - Price caps for momentum-based trading

### 1.2 Configuration Issues

**Issue 1: FVG Configuration Fragmentation**
- **Location:** `merid/prediction/forecasters/fvg.py` (lines 34-64)
- **Problem:** FVG forecaster uses environment variables (`MERID_FVG_WINDOW_SIZE`, `MERID_FVG_MIN_GAP_CENTS`, etc.) instead of profile YAML
- **Impact:** Configuration split across two sources, violates single source of truth principle
- **Recommendation:** Migrate FVG parameters to profile YAML `momentum_fvg.fvg_*` section

**Issue 2: Velocity Threshold Configuration**
- **Location:** `merid/prediction/agent_grid_15m.py` (lines 175-185)
- **Status:** ✅ **FIXED** - Aligned with profile YAML (0.00001 for all assets)
- **Previous Issue:** Hardcoded thresholds (0.15%-0.20%) were 150-200x higher than profile YAML
- **Current State:** All assets use 0.00001 (0.001%) threshold from profile YAML

---

## 2. Midstream Layer (Indicator Calculation)

### 2.1 Indicator Stack Components

#### 2.1.1 Crypto15mIndicatorStack
**File:** `merid/signals/crypto_15m_indicators.py`

**Indicators Computed:**
- **Trend:** EMA(50) regime filter, EMA(9/21 or 13/34) crossover
- **Momentum:** RSI(8), MACD(8,21,5)
- **Volatility:** ATR(14), realized volatility bands
- **Chop Filters:** Consecutive closes, MACD persistence, histogram magnitude
- **FVG:** Fair Value Gap detection (lines 574-634)
- **Liquidity:** Spread width and depth thresholds

**Asset-Specific Configurations:**
- **BTC/ETH:** Faster EMAs (9/21), strict chop filter (3 bars), lower ATR threshold (0.02%)
- **SOL/XRP/DOGE:** Slower EMAs (13/34), relaxed chop filter (2 bars), higher ATR threshold

**Critical Issue: FVG OHLC Approximation**
- **Location:** `merid/signals/crypto_15m_indicators.py` (line 576)
- **Problem:** FVG detection approximates OHLC from close prices only
- **Code Comment:** `"approximates OHLC from close prices for FVG detection"`
- **Impact:** Inaccurate FVG detection without actual high/low data

#### 2.1.2 FVGForecaster
**File:** `merid/prediction/forecasters/fvg.py`

**Indicators Computed:**
- **FVG Detection:** Uses actual OHLC prices from candles (lines 142-187)
- **FVG Fill Checking:** Monitors price proximity to unfilled FVGs (lines 189-204)
- **Confluence Scoring:** Multi-timeframe FVG alignment (lines 223-268)

**Critical Discrepancy:**
- **Problem:** Uses actual OHLC data, unlike `crypto_15m_indicators.py` which approximates OHLC
- **Impact:** Two different FVG implementations producing different results
- **Recommendation:** Consolidate to single FVG implementation using actual OHLC data

#### 2.1.3 Regime Detector
**File:** `merid/prediction/regime_detector.py`

**Indicators Computed:**
- **HMM-based Regime Detection:** 3-state Gaussian HMM (bull, choppy, bear)
- **Features:** Log returns, realized volatility, momentum (lines 77-113)
- **Walk-forward Training:** Refits every 100 data points (line 60)

**Integration:**
- Connected to agent_grid_15m via regime adapter (lines 2855-2870)
- Updates canonical `ops.regime_detection` for risk controls

#### 2.1.4 Order Book Imbalance Filter
**File:** `merid/prediction/order_book_imbalance_filter.py`

**Indicators Computed:**
- **OBI Calculation:** `(bid_depth - ask_depth) / (bid_depth + ask_depth)` (lines 126-145)
- **Signal Classification:** STRONG_BUY, BUY, NEUTRAL, SELL, STRONG_SELL (lines 147-163)
- **Directional Consistency:** 60% agreement in rolling window (line 60)

**Per-Asset Thresholds (from profile YAML):**
- **BTC/ETH:** strong_threshold = 0.55, ewma_alpha = 0.15
- **SOL/XRP/DOGE:** strong_threshold = 0.45, ewma_alpha = 0.20

### 2.2 Signal Generation Components

#### 2.2.1 LeanAgentGrid15m
**File:** `merid/prediction/agent_grid_15m.py`

**Primary Signal Mode:** `momentum_fvg` (velocity-based with FVG confirmation)

**Signal Generation Flow:**
1. **Multi-Window Velocity Calculation** (lines 1727-1787)
   - Windows: [10s, 30s, 60s] with weights [0.2, 0.3, 0.5]
   - EMA smoothing (period 5)
   - ATR normalization (DISABLED per line 1812 comment)
   - Z-score filtering (period 20)

2. **Dynamic Velocity Threshold** (lines 1408-1446)
   - Base threshold from profile YAML (0.00001)
   - Volatility adjustment based on realized vol (lines 2801-2833)
   - Regime-aware adjustment (lines 2872-2896)

3. **Regime Detection** (lines 2835-2870)
   - HMM-based regime classification
   - Strategy mode selection (trend_following, mean_reversion)
   - Confidence threshold (0.7) to prevent signal inversion

4. **Panic Fade Strategy** (lines 1276-1345)
   - Volatility reversion when extreme velocity detected
   - RSI oversold/overbought thresholds (25/75)
   - Overrides velocity signal when triggered

5. **Price-Based Strategy** (lines 2696-2697)
   - Turbine research winner (+56.6% ROI)
   - Buy YES when price <= 0.48, sell when price >= 0.72

6. **Trend Alignment Strategy** (separate module)
   - Multi-timeframe trend agreement (5m / 1h)
   - Less explosive but more interpretable

---

## 3. Downstream Layer (Execution)

### 3.1 Exit Policy
**File:** `merid/position_management/exit_policy.py`

**Exit Reasons (in priority order):**
1. **RISK** - Risk kill switch triggered
2. **LOSS_CAP** - Maximum loss exceeded
3. **CANDLE_REVERSAL** - Candle pattern reversal detected
4. **ADAPTIVE_TIMING** - Optimal hold time exceeded
5. **TIME_STOP** - Maximum hold time reached
6. **EDGE_DECAY** - Edge degraded below threshold
7. **EXTREME_PROFIT** - 99c YES / 1c NO (guaranteed win)
8. **RATCHET_FLOOR** - Ratchet profit floor breached
9. **RATCHET_TRIM** - Position trimming at high price
10. **TAKE_PROFIT** - R-multiple target reached
11. **STOP_LOSS** - Protective stop hit
12. **TRAIL** - Trailing stop triggered

### 3.2 Candle Pattern Detection
**File:** `merid/position_management/candle_patterns.py`

**Patterns Detected:**
- Engulfing (bullish/bearish)
- Harami (bullish/bearish)
- Morning/Evening Star
- Hammer/Hanging Man
- Doji

**Integration:** Used by exit_policy.py for CANDLE_REVERSAL exit reason

### 3.3 Ratchet Profit Floor
**File:** `merid/position_management/position_monitor.py` (lines 216-300)

**Mechanism:**
- **Activation Threshold:** 85c (from profile YAML)
- **Floor Offset:** 5c below activation (80c floor)
- **Mandatory 99c Exit:** Enabled in profile YAML
- **Position Trimming:** Trim to 1 contract when price > 80c and size > 1
- **Minimum Hold:** 30 seconds after activation

**Configuration Source:** Profile YAML `ratchet_profit_floor` section

### 3.4 Dynamic Take Profit
**File:** `merid/prediction/dynamic_takeprofit.py`

**R-Multiple Based TP:**
- **Low Confidence (≤0.3):** 1.0R hard TP, no trailing
- **Medium Confidence (0.3-0.6):** 1.5R base TP, trailing at 1R
- **High Confidence (0.6-0.8):** 2.0-2.5R stretch TP
- **Very High Confidence (>0.8):** 2.5-3.0R aggressive TP

**60-70% Profit Capture Rule:**
- Caps TP at 70% of maximum theoretical gain
- Prevents holding for last 20-30% which takes disproportionately longer

**TTE Compression:**
- Compresses trailing parameters as expiry approaches
- >600s (10m): No compression
- 300-600s (5-10m): 20% compression
- 120-300s (2-5m): 40% compression
- <120s (2m): 60% compression

### 3.5 Staged Time Exit
**File:** `merid/event_venues/kalshi/position_cache.py` (lines 1641-1732)

**Configuration (from profile YAML):**
- **Stage 1:** 5 minutes, close 40%
- **Stage 2:** 10 minutes, close 30%
- **Stage 3:** 13 minutes, close 30%

**Implementation:** Partial liquidation at time intervals for volatile markets

### 3.6 Adaptive Exit Timing
**File:** `merid/position_management/adaptive_exit_timing.py`

**Mechanism:**
- Analyzes historical exit performance by hold duration buckets
- Adjusts optimal hold time based on current R-multiple
- Reduces hold time by 30-50% if already profitable

**Status:** Rule-based implementation, ML model planned for future

### 3.7 Hedging Engine
**File:** `merid/hedging/engine.py`

**Components:**
- **Deterministic Hedge Engine:** Rule-based hedge order generation
- **FVG-Aware Hedge Entry:** Uses FVGForecaster for optimal entry pricing (line with `_resolve_fvg_price`)
- **Take Profit/Stop Loss:** Auto-exit for hedge positions
- **Auto-Exit Loop:** Continuous monitoring of hedge positions

**Configuration:** `merid/hedging/config.py` loads from `config/kalshi_crypto_hedging.yaml`

---

## 4. Discrepancies Identified

### 4.1 Critical: FVG Implementation Split
**Severity:** 🔴 **CRITICAL**

**Description:** Two different FVG implementations with different data sources
- `crypto_15m_indicators.py`: Approximates OHLC from close prices only
- `fvg.py`: Uses actual OHLC prices from candles

**Impact:** Inconsistent FVG detection, unreliable signals

**Recommendation:** 
1. Consolidate to single FVG implementation using actual OHLC data
2. Remove approximation logic from `crypto_15m_indicators.py`
3. Use `fvg.py` as the authoritative FVG source

### 4.2 High: Configuration Fragmentation
**Severity:** 🟠 **HIGH**

**Description:** FVG forecaster uses environment variables instead of profile YAML
- Environment variables: `MERID_FVG_WINDOW_SIZE`, `MERID_FVG_MIN_GAP_CENTS`, etc.
- Profile YAML: `momentum_fvg.fvg_*` section exists but not used by forecaster

**Impact:** Violates single source of truth principle, configuration drift risk

**Recommendation:**
1. Migrate FVG parameters to profile YAML
2. Update `fvg.py` to read from profile YAML
3. Remove environment variable fallbacks

### 4.3 Medium: Indicator Computation vs Usage Mismatch
**Severity:** 🟡 **MEDIUM**

**Description:** MACD and RSI computed but not used in primary signal path
- `crypto_15m_indicators.py` computes MACD(8,21,5) and RSI(8)
- Profile YAML has `momentum_fvg.momentum_min_macd_hist_long/short` thresholds
- Agent grid primary signal path uses velocity only, not MACD/RSI

**Impact:** Computed indicators wasted, potential signal quality improvement unused

**Recommendation:**
1. Either integrate MACD/RSI into velocity-based signal generation
2. Or remove indicator computation if not used
3. Clarify intended signal generation strategy

### 4.4 Low: Velocity Calculation Inconsistency (FIXED)
**Severity:** 🟢 **RESOLVED**

**Description:** Previously used different velocity calculations for threshold vs logit
- **Previous:** Simple velocity for threshold, multi-window for logit
- **Current:** Both use multi-window velocity with EMA smoothing (line 2703)

**Status:** ✅ **FIXED** in agent_grid_15m.py

---

## 5. Wiring Gaps Identified

### 5.1 Gap: MACD/RSI Not Wired to Signal Generation
**Location:** `merid/prediction/agent_grid_15m.py`

**Description:** 
- Profile YAML defines MACD histogram thresholds for momentum_fvg mode
- `crypto_15m_indicators.py` computes MACD and RSI
- Agent grid `_generate_signal` does not check MACD/RSI thresholds

**Current Code:**
```python
# agent_grid_15m.py line 2696-2697
if self.config.signal_mode == "price_based":
    return self._generate_price_based_signal(asset, spot_price, market, minutes_to_expiry)
```

**Missing Logic:**
```python
# Should check MACD/RSI for momentum_fvg mode
if self.config.signal_mode == "momentum_fvg":
    # Check MACD histogram threshold
    # Check RSI threshold
    # Check OBI threshold
    # Check FVG confluence
```

**Recommendation:** Implement momentum_fvg signal logic that uses all configured indicators

### 5.2 Gap: Trend Alignment Strategy Not Integrated
**Location:** `merid/prediction/strategies/trend_alignment.py`

**Description:**
- Trend alignment strategy exists as standalone module
- Based on Turbine research (profitable)
- Not integrated into agent_grid_15m signal generation

**Recommendation:** 
1. Integrate trend alignment as signal mode option
2. Or use as confirmation filter for velocity signals

### 5.3 Gap: Adaptive Exit Timing Not Used
**Location:** `merid/position_management/adaptive_exit_timing.py`

**Description:**
- Adaptive exit timing module exists
- Not integrated into position_monitor or exit_policy
- Historical performance tracking not populated

**Recommendation:** 
1. Integrate into exit_policy evaluation
2. Populate historical performance data from trade results
3. Or remove if not intended for production use

---

## 6. Asset Inconsistencies

### 6.1 EMA Periods (Intentional)
**Status:** ✅ **INTENTIONAL DIFFERENTIATION**

**Configuration:**
- **BTC/ETH:** EMA fast=9, slow=21, trend=21, consecutive closes=3
- **SOL/XRP/DOGE:** EMA fast=13, slow=34, trend=34, consecutive closes=2

**Rationale:** Asset-specific volatility profiles (documented in code comments)

**Assessment:** Appropriate differentiation for different asset characteristics

### 6.2 Velocity Thresholds (Uniform)
**Status:** ✅ **CONSISTENT**

**Configuration:** All assets use 0.00001 (0.001%) threshold from profile YAML

**Assessment:** Consistent treatment across all assets

### 6.3 OBI Thresholds (Intentional)
**Status:** ✅ **INTENTIONAL DIFFERENTIATION**

**Configuration:**
- **BTC/ETH:** strong_threshold=0.55, ewma_alpha=0.15
- **SOL/XRP/DOGE:** strong_threshold=0.45, ewma_alpha=0.20

**Rationale:** Thinner order books for SOL/XRP/DOGE require lower thresholds

**Assessment:** Appropriate differentiation based on market depth

### 6.4 Divergence Thresholds (Intentional)
**Status:** ✅ **INTENTIONAL DIFFERENTIATION**

**Configuration:** (agent_grid_15m.py lines 2774-2781)
- **BTC/ETH:** 0.1% divergence threshold
- **SOL:** 0.15% divergence threshold
- **XRP/DOGE:** 0.2% divergence threshold

**Rationale:** Higher volatility assets allow larger divergence

**Assessment:** Appropriate differentiation based on asset volatility

### 6.5 Minimum Entry Prices (Uniform)
**Status:** ✅ **CONSISTENT**

**Configuration:** All assets use 15c minimum (agent_grid_15m.py lines 2593-2600)

**Assessment:** Consistent treatment across all assets

---

## 7. Exit Logic Complexity

### 7.1 Overlapping Exit Mechanisms
**Issue:** Multiple exit mechanisms can trigger simultaneously with unclear precedence

**Exit Mechanisms:**
1. **Ratchet Profit Floor:** 85c activation, 80c floor, mandatory 99c exit
2. **Extreme Profit:** 99c YES / 1c NO (guaranteed win)
3. **Staged Time Exit:** Partial exits at 5m/10m/13m
4. **Dynamic Take Profit:** R-multiple based TP with trailing
5. **Adaptive Exit Timing:** Historical performance-based optimal hold
6. **Candle Reversal:** Pattern-based reversal exits
7. **Trailing Stop:** Trailing stop from profile YAML

**Precedence Issues:**
- Ratchet 99c mandatory exit vs Extreme Profit exit (both trigger at 99c)
- Staged time exit vs Dynamic TP (which takes priority?)
- Ratchet floor vs Trailing stop (which controls the exit price?)

**Recommendation:**
1. Document clear precedence order in exit_policy.py
2. Add conflict resolution logic when multiple exits trigger
3. Consider consolidating overlapping mechanisms

### 7.2 99c Exit Duplication
**Issue:** Two separate mechanisms for 99c exit
- **Ratchet:** `ratchet_mandatory_exit_at_99c` (profile YAML)
- **Extreme Profit:** `ExitReason.EXTREME_PROFIT` (exit_policy.py)

**Current Code:** (position_monitor.py lines 189-214)
```python
# RATCHET: Check mandatory 99c exit (profile-controlled)
if profile.ratchet_profit_floor_enabled and profile.ratchet_mandatory_exit_at_99c:
    if position.side == PositionSide.YES and current_price_cents >= 99:
        self._emit_exit_intent(position, ExitReason.EXTREME_PROFIT, current_price_cents)
```

**Recommendation:** Consolidate to single 99c exit mechanism with clear ownership

---

## 8. Recommendations Summary

### 8.1 Critical Priority
1. **Consolidate FVG Implementation:** Use single FVG implementation with actual OHLC data
2. **Migrate FVG Config to Profile YAML:** Eliminate environment variable configuration
3. **Wire MACD/RSI to Signal Generation:** Implement momentum_fvg signal logic using all configured indicators

### 8.2 High Priority
4. **Clarify Exit Precedence:** Document and implement clear precedence order for overlapping exit mechanisms
5. **Consolidate 99c Exit:** Single mechanism for 99c exit with clear ownership
6. **Integrate Trend Alignment:** Add trend alignment as signal mode or confirmation filter

### 8.3 Medium Priority
7. **Integrate Adaptive Exit Timing:** Wire into exit_policy or remove if not intended
8. **Review Indicator Usage:** Either use computed indicators or remove computation to reduce complexity
9. **Asset Consistency Review:** Ensure all 5 assets have consistent treatment where appropriate

### 8.4 Low Priority
10. **Documentation Updates:** Update code comments to reflect current implementation
11. **Test Coverage:** Add tests for FVG consolidation and exit precedence logic
12. **Monitoring:** Add metrics for exit reason distribution to identify conflicts

---

## 9. Conclusion

The MERID 15-minute Kalshi crypto trading system has a comprehensive technical analysis stack with multiple indicators, signal generation strategies, and exit mechanisms. However, the audit identified several critical issues that require remediation:

**Most Critical:** FVG implementation split and configuration fragmentation pose the highest risk to signal quality and system maintainability.

**High Impact:** Unwired indicators (MACD/RSI) and overlapping exit mechanisms reduce system effectiveness and clarity.

**Positive Findings:** Asset-specific configurations are well-documented and appropriate. Velocity threshold alignment with profile YAML has been fixed. The system has good separation of concerns between upstream, midstream, and downstream layers.

**Overall Assessment:** The system architecture is sound but requires consolidation of duplicate implementations, clarification of exit logic, and completion of indicator wiring to achieve full effectiveness.

---

## Appendix A: File Inventory

### Upstream Configuration
- `config/profiles/kalshi_crypto_15m_v2.yaml` - Primary configuration source

### Midstream Indicator Calculation
- `merid/signals/crypto_15m_indicators.py` - Crypto15mIndicatorStack
- `merid/prediction/forecasters/fvg.py` - FVGForecaster
- `merid/prediction/regime_detector.py` - RegimeDetector
- `merid/prediction/order_book_imbalance_filter.py` - OBI filter

### Midstream Signal Generation
- `merid/prediction/agent_grid_15m.py` - LeanAgentGrid15m
- `merid/prediction/strategies/trend_alignment.py` - TrendAlignmentStrategy

### Downstream Execution
- `merid/position_management/exit_policy.py` - Exit policy evaluation
- `merid/position_management/candle_patterns.py` - Candle pattern detection
- `merid/position_management/position_monitor.py` - Position monitoring and ratchet
- `merid/prediction/dynamic_takeprofit.py` - Dynamic take profit engine
- `merid/position_management/adaptive_exit_timing.py` - Adaptive exit timing
- `merid/hedging/engine.py` - Hedging engine
- `merid/hedging/config.py` - Hedge configuration
- `merid/event_venues/kalshi/position_cache.py` - Position cache with staged exits

---

**Audit Completed:** 2026-07-06  
**Auditor:** Cascade AI Assistant  
**Next Review:** After critical issues remediated
