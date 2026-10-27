# Kalshi Agent Signal Audit Report
**Date**: 2026-07-05
**Profile**: kalshi_crypto_15m_v2
**Signal Mode**: momentum_fvg
**Assets**: BTC, ETH, SOL, XRP, DOGE

---

## Executive Summary

This audit analyzes the signal generation triggers for YES/NO trades across all 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) in the Kalshi 15-minute trading system. The system uses velocity-based signals with regime-aware side mapping, symmetric thresholds, and per-asset edge thresholds.

**Key Findings**:
- All assets use identical velocity thresholds (0.00001 = 0.001%)
- Edge thresholds vary by asset tier (Tier 1: 3-4%, Tier 2: 4-6%)
- OBI thresholds vary by asset depth (BTC/ETH: 0.70, SOL/XRP/DOGE: 0.65)
- Min decision minute varies by asset volatility (BTC/ETH: 2min, SOL/XRP: 3min, DOGE: 5min)
- Max contracts differ for DOGE (2) vs others (3)

---

## 1. Agent Configuration Summary

### 1.1 Active Agents
All 5 assets have active agents with identical configuration structure:
- **BTC_15M**: KXBTC15M ticker
- **ETH_15M**: KXETH15M ticker
- **SOL_15M**: KXSOL15M ticker
- **XRP_15M**: KXXRP15M ticker
- **DOGE_15M**: KXDOGE15M ticker

### 1.2 Signal Mode
**Current**: `momentum_fvg` (switched from `trend` on 2026-07-05 based on Turbine research)
- Rationale: Momentum was the only profitable family (78 of 100 strategies)
- Mean reversion failed completely (0 for 432 variants) on 15-minute markets

### 1.3 Velocity Thresholds (All Assets Identical)
```yaml
velocity_thresholds:
  BTC: 0.00001  # 0.001%
  ETH: 0.00001  # 0.001%
  SOL: 0.00001  # 0.001%
  XRP: 0.00001  # 0.001%
  DOGE: 0.00001 # 0.001%
```

**Note**: Effectively zero to enable any movement in calm markets.

---

## 2. Signal Generation Triggers

### 2.1 Velocity-Based Signal Decision

**Core Logic** (agent_grid_15m.py lines 3165-3197):
```python
if velocity > velocity_threshold:
    if strategy_mode == "trend_following":
        signal_side = "yes"  # BUY YES (positive momentum)
    else:  # mean_reversion
        signal_side = "no"   # BUY NO (expect reversion down)
elif velocity < -velocity_threshold:
    if strategy_mode == "trend_following":
        signal_side = "no"   # BUY NO (negative momentum)
    else:  # mean_reversion
        signal_side = "yes"  # BUY YES (expect reversion up)
```

**Key Characteristics**:
- **Symmetric thresholds**: no_conviction_multiplier = 1.0 (removed 1.5x NO multiplier)
- **Regime-aware mapping**: strategy_mode determined by HMM regime detector
- **No marginal zone**: yes_bias_margin = 0.0 (signals fire at threshold)

### 2.2 Regime-Aware Side Mapping

**Strategy Modes**:
- **trend_following** (default): Velocity direction = signal side
  - Positive velocity → BUY YES
  - Negative velocity → BUY NO
- **mean_reversion**: Velocity direction = opposite signal side
  - Positive velocity → BUY NO (expect reversion down)
  - Negative velocity → BUY YES (expect reversion up)

**Regime Detection**:
- Uses HMM-based regime detector with confidence threshold (>0.7)
- Default to trend_following if confidence < 0.7
- Prevents systematic signal inversion from low-confidence classifications

### 2.3 Panic Fade Override

**Panic Fade Signal** (agent_grid_15m.py lines 1298-1348):
- Triggers on extreme velocity + RSI + Z-score
- Oversold (RSI < 25): BUY YES
- Overbought (RSI > 75): BUY NO
- Overrides velocity-based signal when active

**Parameters**:
- panic_fade_threshold: 0.00013 (0.013%)
- panic_fade_zscore_threshold: 2.0
- panic_fade_rsi_oversold: 25.0
- panic_fade_rsi_overbought: 75.0

---

## 3. Per-Asset Parameter Comparison

### 3.1 Edge Thresholds (Minimum Edge Required)

| Asset | Tier | min_edge_early | min_edge_mid | min_edge_late | min_edge_terminal |
|-------|------|----------------|--------------|---------------|-------------------|
| BTC   | 1    | 3%             | 3%           | 3%            | 4%                |
| ETH   | 1    | 3%             | 3%           | 3%            | 4%                |
| SOL   | 2    | 4%             | 4%           | 4%            | 5%                |
| XRP   | 2    | 4%             | 4%           | 4%            | 5%                |
| DOGE  | 2    | 5%             | 5%           | 5%            | 6%                |

**Rationale**: Higher volatility assets (DOGE) require higher edge to compensate for risk.

### 3.2 Order Book Imbalance (OBI) Thresholds

| Asset | Strong Threshold | EWMA Alpha |
|-------|------------------|------------|
| BTC   | 0.70             | 0.15       |
| ETH   | 0.70             | 0.15       |
| SOL   | 0.65             | 0.20       |
| XRP   | 0.65             | 0.20       |
| DOGE  | 0.65             | 0.20       |

**Rationale**: Thinner books (SOL/XRP/DOGE) have lower thresholds to allow more signals.

### 3.3 Minimum Decision Minute (Skip Early Noise)

| Asset | Min Decision Minute |
|-------|---------------------|
| BTC   | 2 minutes           |
| ETH   | 2 minutes           |
| SOL   | 3 minutes           |
| XRP   | 3 minutes           |
| DOGE  | 5 minutes           |

**Rationale**: Thinner/more volatile assets need longer to settle before signal clarity.

### 3.4 Max Contracts Per Trade

| Asset | Max Contracts |
|-------|--------------|
| BTC   | 3            |
| ETH   | 3            |
| SOL   | 3            |
| XRP   | 3            |
| DOGE  | 2            |

**Rationale**: DOGE has higher volatility, more conservative sizing.

### 3.5 Depth Thresholds (All Assets Identical)

| Asset | min_depth_yes | min_depth_no |
|-------|--------------|-------------|
| BTC   | 1            | 1           |
| ETH   | 1            | 1           |
| SOL   | 1            | 1           |
| XRP   | 1            | 1           |
| DOGE  | 1            | 1           |

**Note**: Aligned with 1 contract per order trading strategy.

---

## 4. Additional Signal Filters

### 4.1 Order Book Imbalance (OBI) Filter
- **Enabled**: Yes
- **Strong Threshold**: 0.70 (BTC/ETH), 0.65 (SOL/XRP/DOGE)
- **Consistency Required**: 60% directional consistency
- **Cross-Signal Alignment**: Velocity and OBI must align (contradictory signals filtered)

### 4.2 News Event Avoidance
- **Enabled**: Yes
- **Avoidance Window**: 15 minutes before/after high-impact news
- **Events**: NFP, CPI, FOMC, GDP, PPI, Retail Sales, ISM Manufacturing/Services

### 4.3 Multi-Timeframe Filter
- **Enabled**: Yes
- **Higher Timeframe**: 1h
- **Alignment Mode**: Strict (only with trend)
- **Neutral Size Multiplier**: 0.5 (reduce size when 1h is neutral)

### 4.4 Noise Filters
- **Sustained Velocity**: Requires 3 consecutive periods with same sign
- **Wick Filter**: Reject if wick > 50% of candle body (avoid liquidation cascades)

---

## 5. Discrepancies Identified

### 5.1 Potential Discrepancy: Identical Velocity Thresholds
**Issue**: All 5 assets use identical velocity thresholds (0.00001)
- **Expected**: Higher volatility assets (DOGE) should have higher thresholds
- **Current**: DOGE (100% vol) has same threshold as BTC (45% vol)
- **Impact**: May generate false signals on high-volatility assets
- **Recommendation**: Consider asset-specific velocity thresholds based on volatility

### 5.2 Potential Discrepancy: DOGE Max Contracts
**Issue**: DOGE has max_contracts=2 while others have 3
- **Rationale**: Higher volatility (100% annual vol)
- **Impact**: Limits position size on DOGE
- **Recommendation**: Monitor if this is too restrictive for DOGE opportunities

### 5.3 Potential Discrepancy: Min Decision Minute
**Issue**: DOGE has 5-minute min decision vs 2-3 minutes for others
- **Rationale**: Thinnest book, most noise
- **Impact**: May miss early opportunities on DOGE
- **Recommendation**: Monitor if 5-minute window is too conservative

### 5.4 No Discrepancy: Edge Thresholds
**Status**: Appropriate differentiation
- Tier 1 (BTC/ETH): 3-4% edge (more stable, lower edge acceptable)
- Tier 2 (SOL/XRP): 4-5% edge (moderate volatility)
- DOGE: 5-6% edge (highest volatility, highest edge required)

### 5.5 No Discrepancy: OBI Thresholds
**Status**: Appropriate differentiation
- BTC/ETH: 0.70 (deeper books, higher threshold)
- SOL/XRP/DOGE: 0.65 (thinner books, lower threshold)

---

## 6. Fine-Tuning Opportunities

### 6.1 Asset-Specific Velocity Thresholds
**Current**: All assets use 0.00001 (0.001%)
**Recommendation**: Implement volatility-based velocity thresholds
```yaml
velocity_thresholds:
  BTC: 0.000015  # 0.0015% (deeper market, lower threshold)
  ETH: 0.000015  # 0.0015% (deeper market, lower threshold)
  SOL: 0.000025  # 0.0025% (moderate volatility)
  XRP: 0.000025  # 0.0025% (moderate volatility)
  DOGE: 0.00005  # 0.005% (highest volatility, highest threshold)
```

### 6.2 DOGE Min Decision Minute Adjustment
**Current**: 5 minutes
**Recommendation**: Test 3-4 minutes to capture more early opportunities
- Monitor signal quality at earlier entries
- Compare win rate between 3min vs 5min entries

### 6.3 DOGE Max Contracts Adjustment
**Current**: 2 contracts
**Recommendation**: Test 3 contracts with tighter edge requirements
- Monitor PnL volatility with larger DOGE positions
- Consider dynamic sizing based on volatility regime

### 6.4 OBI Threshold Fine-Tuning
**Current**: BTC/ETH 0.70, SOL/XRP/DOGE 0.65
**Recommendation**: Test intermediate values
- BTC/ETH: 0.65-0.70 range
- SOL/XRP/DOGE: 0.60-0.65 range
- Monitor false positive/negative rates

### 6.5 Regime Detection Confidence Threshold
**Current**: 0.70 confidence required for mean_reversion mode
**Recommendation**: Test 0.65-0.75 range
- Lower threshold: More mean_reversion signals, higher risk
- Higher threshold: More trend_following signals, conservative

---

## 7. Signal Flow Summary

### 7.1 Complete Signal Generation Flow

1. **Time Window Filter** (lines 2563-2585)
   - Skip first minute (price discovery noise)
   - Skip last 30 seconds (edge decay)
   - 0.5-4 minutes: 1.5x edge multiplier
   - 4-12 minutes: baseline edge requirements

2. **Price Filter** (lines 2593-2647)
   - Hard ban below 10c (lottery zone)
   - Per-asset minimum (15c for all assets)

3. **Velocity Calculation** (lines 2703-2708)
   - Multi-window velocity [10s, 30s, 60s]
   - EMA smoothing (period=5)
   - ATR normalization

4. **Velocity Threshold Check** (lines 3165-3197)
   - Positive velocity > threshold → YES (trend) or NO (mean_reversion)
   - Negative velocity < -threshold → NO (trend) or YES (mean_reversion)
   - Symmetric thresholds (no_conviction_multiplier = 1.0)

5. **Panic Fade Override** (lines 1298-1348)
   - Extreme velocity + RSI + Z-score
   - Overrides velocity-based signal

6. **Noise Filters** (lines 3270-3327)
   - Sustained velocity (3 consecutive periods)
   - Wick filter (reject >50% wick candles)

7. **OBI Filter** (lines 3329-3393)
   - Per-asset strong thresholds
   - Directional consistency check
   - Cross-signal alignment (velocity vs OBI)

8. **News Event Avoidance** (lines 3395-3418)
   - Skip 15 minutes before/after high-impact news

9. **Multi-Timeframe Filter** (lines 2596-2603)
   - 1h trend alignment
   - Neutral size reduction

10. **Edge Calculation** (not shown in audit)
    - Model probability from velocity (logistic mapping)
    - Edge = p_model - p_mkt
    - Per-asset edge thresholds

11. **Entry Band Filter** (lines 3896-3945)
    - Price range [10c, 70c]
    - Sweet-spot band enforcement

---

## 8. Conclusion

### 8.1 Current State
- **Signal Mode**: momentum_fvg (appropriate based on Turbine research)
- **Velocity Thresholds**: Identical across all assets (potential fine-tuning opportunity)
- **Edge Thresholds**: Appropriate differentiation by asset tier
- **OBI Thresholds**: Appropriate differentiation by book depth
- **Min Decision Minute**: Appropriate differentiation by volatility
- **Max Contracts**: DOGE conservative (potential fine-tuning opportunity)

### 8.2 Priority Recommendations
1. **High Priority**: Implement asset-specific velocity thresholds based on volatility
2. **Medium Priority**: Test DOGE min decision minute reduction (5min → 3-4min)
3. **Medium Priority**: Test DOGE max contracts increase (2 → 3)
4. **Low Priority**: Fine-tune OBI thresholds within current ranges

### 8.3 No Critical Issues Found
- Signal generation logic is sound and well-documented
- Per-asset parameters are appropriately differentiated
- No systematic biases or blocking issues identified
- System is production-ready with optimization opportunities

---

**Audit Completed**: 2026-07-05
**Auditor**: Cascade AI Agent
**Next Review**: After implementing velocity threshold fine-tuning
