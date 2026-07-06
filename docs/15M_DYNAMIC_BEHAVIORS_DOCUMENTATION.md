# MERID 15M Stack - Dynamic Behaviors Documentation

**Generated:** 2026-07-06  
**Scope:** Documentation of dynamic behaviors not captured in static profile YAML

---

## Overview

The 15M Kalshi crypto trading system implements several dynamic behaviors that override or modify the static profile YAML values at runtime. This document describes these behaviors to ensure developers understand the full system behavior.

---

## Adaptive Price Caps (Agent Grid)

**Location:** `merid/prediction/agent_grid_15m.py` (lines 3058-3097)

**Description:**
The agent grid implements adaptive regime-based price caps that override the static profile YAML values for `max_entry_price_yes` and `min_entry_price_no`. These caps adjust based on the detected market regime.

**Regime-Based Caps:**

| Regime | max_entry_price_yes | min_entry_price_no | Description |
|--------|-------------------|-------------------|-------------|
| trending_strong | 0.95 | 0.05 | Strong trend: allow extreme prices |
| trending_weak | 0.90 | 0.10 | Weak trend: moderate price range |
| mean_reverting | 0.80 | 0.20 | Mean reverting: conservative range |
| neutral | 0.85 | 0.15 | Neutral: balanced range |

**Static Profile Values (for reference):**
- `max_entry_price_yes`: 0.70 (from profile YAML)
- `min_entry_price_no`: 0.30 (from profile YAML)

**Impact:**
The adaptive caps are more aggressive than the static profile values, allowing the system to trade at more extreme prices when the regime detection indicates strong trending behavior.

**Code Reference:**
```python
# Adaptive price caps based on regime
if regime == "trending_strong":
    max_entry_price_yes = 0.95
    min_entry_price_no = 0.05
elif regime == "trending_weak":
    max_entry_price_yes = 0.90
    min_entry_price_no = 0.10
elif regime == "mean_reverting":
    max_entry_price_yes = 0.80
    min_entry_price_no = 0.20
else:
    max_entry_price_yes = 0.85
    min_entry_price_no = 0.15
```

---

## Dynamic Velocity Threshold Adjustment (Agent Grid)

**Location:** `merid/prediction/agent_grid_15m.py` (lines 1408-1426, 2801-2833, 2877-2896)

**Description:**
The agent grid adjusts velocity thresholds dynamically based on multiple volatility indicators, rather than using the static profile YAML values. This allows the system to be more sensitive to price movements in high-volatility environments and less sensitive in low-volatility environments.

**Adjustment Factors:**

1. **ATR (Average True Range) Volatility:**
   - Higher ATR → higher velocity threshold (requires larger price movement to trigger signal)
   - Lower ATR → lower velocity threshold (more sensitive to small movements)

2. **Realized Volatility:**
   - Higher realized volatility → higher velocity threshold
   - Lower realized volatility → lower velocity threshold

3. **Regime Detection:**
   - Trending regimes → adjusted thresholds based on trend strength
   - Mean reverting regimes → adjusted thresholds based on volatility bands

**Static Profile Values (for reference):**
- `velocity_thresholds.BTC`: 0.00001 (0.001%)
- `velocity_thresholds.ETH`: 0.00001 (0.001%)
- `velocity_thresholds.SOL`: 0.00001 (0.001%)
- `velocity_thresholds.XRP`: 0.00001 (0.001%)
- `velocity_thresholds.DOGE`: 0.00001 (0.001%)

**Impact:**
The dynamic adjustment means the actual velocity threshold used in signal generation may be significantly different from the static profile values, depending on current market conditions.

**Code Reference:**
```python
def _calculate_dynamic_velocity_threshold(self, asset: str) -> float:
    # Adjust threshold based on ATR, volatility, regime
    atr = self._get_atr(asset)
    realized_vol = self._get_realized_volatility(asset)
    regime = self._detect_regime(asset)
    
    base_threshold = self._get_base_velocity_threshold(asset)
    
    # Apply multipliers based on conditions
    if atr > high_atr_threshold:
        threshold *= 1.5
    elif atr < low_atr_threshold:
        threshold *= 0.7
    
    if realized_vol > high_vol_threshold:
        threshold *= 1.3
    
    return threshold
```

---

## Dynamic Kelly Multipliers (Confidence-Based)

**Location:** Profile YAML `confidence.kelly_multiplier_*` fields

**Description:**
Kelly sizing multipliers are adjusted based on confidence levels, allowing the system to size positions more aggressively when confidence is high and more conservatively when confidence is low.

**Confidence-Based Multipliers:**

| Confidence Level | Kelly Multiplier | Description |
|------------------|-----------------|-------------|
| no_trade | 0.0 | No sizing (confidence too low) |
| cautious | 0.5 | Conservative sizing (50% of Kelly) |
| quick_win | 0.6 | Moderate sizing (60% of Kelly) |
| confident | 1.0 | Full Kelly sizing |

**Static Profile Values:**
- `confidence.kelly_multiplier_no_trade`: 0.0
- `confidence.kelly_multiplier_cautious`: 0.5
- `confidence.kelly_multiplier_quick_win`: 0.6
- `confidence.kelly_multiplier_confident`: 1.0

**Impact:**
The system uses these multipliers to scale the Kelly fraction based on the confidence level of the signal, providing an additional layer of risk control.

---

## Summary

**Key Takeaways:**

1. **Adaptive Price Caps:** The system uses regime-based price caps that can be significantly more aggressive than the static profile values.

2. **Dynamic Velocity Thresholds:** Velocity thresholds are adjusted based on ATR, realized volatility, and regime detection, meaning the actual threshold may differ from profile values.

3. **Kelly Multipliers:** Kelly sizing is scaled based on confidence levels, providing dynamic position sizing.

**Recommendations for Future Changes:**

- When modifying profile YAML values related to price caps or velocity thresholds, consider the dynamic adjustments that may override them.
- For regime-based behaviors, consider whether the static profile values should be updated to reflect the typical operating range, or if the dynamic behavior should be modified.
- When adding new dynamic behaviors, document them in this file to maintain visibility into runtime behavior.

---

**Document End**
