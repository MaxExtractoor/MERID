# Entry Matrix Implementation Documentation
**Date:** 2026-07-02  
**Scope:** Kalshi 15-minute crypto YES/NO markets (BTC, ETH, SOL, XRP, DOGE)

---

## Summary of Changes

Based on research from TheLines, DefiRate, and Perplexity, the following entry matrix enhancements have been implemented to align with industry best practices for 15-minute crypto prediction markets.

### 1. Time Window Entry Rules

**Location:** `merid/prediction/agent_grid_15m.py` lines 1914-1942

**Implementation:**
- **Skip first minute (≥14 minutes to expiry):** Initial price discovery is noisy unless spot/Kalshi tightly aligned
- **Skip last 2 minutes (≤2 minutes to expiry):** Edge decay dominates, only mean-reversion or locked-in continuation patterns allowed
- **Reduced entries (2-4 minutes to expiry):** Apply 1.5x edge multiplier for late entries
- **Optimal window (4-12 minutes to expiry):** Baseline edge requirements

**Code:**
```python
time_edge_multiplier = 1.0
if minutes_to_expiry >= 14.0:
    logger.info("[TIME-WINDOW-FILTER] asset=%s minutes_to_expiry=%.1f -> SKIP (first minute - price discovery noise)", asset, minutes_to_expiry)
    return None
elif minutes_to_expiry <= 2.0:
    logger.info("[TIME-WINDOW-FILTER] asset=%s minutes_to_expiry=%.1f -> SKIP (last 2 minutes - edge decay)", asset, minutes_to_expiry)
    return None
elif minutes_to_expiry <= 4.0:
    time_edge_multiplier = 1.5
    logger.info("[TIME-WINDOW-FILTER] asset=%s minutes_to_expiry=%.1f -> REDUCED (late entry, 1.5x edge multiplier)", asset, minutes_to_expiry)
else:
    logger.info("[TIME-WINDOW-FILTER] asset=%s minutes_to_expiry=%.1f -> OPTIMAL (baseline edge requirements)", asset, minutes_to_expiry)
```

### 2. Momentum Agreement Check

**Location:** `merid/prediction/agent_grid_15m.py` lines 2287-2309

**Implementation:**
- Trade only when spot momentum and Kalshi price direction agree
- Spot velocity > 0 (up) → Only consider BUY YES (Kalshi should show upward bias)
- Spot velocity < 0 (down) → Only consider BUY NO (Kalshi should show downward bias)
- If Kalshi price doesn't align with spot direction → SKIP

**Code:**
```python
if market_price > 0:
    kalshi_direction = "up" if market_price > 0.5 else "down"
    spot_direction = "up" if velocity > 0 else "down"
    
    if kalshi_direction != spot_direction:
        logger.info("[MOMENTUM-AGREEMENT-FILTER] asset=%s spot_velocity=%.6f (%s) market_price=%.2f (%s) -> SKIP (directions disagree)", 
                    asset, velocity, spot_direction, market_price, kalshi_direction)
        return None
    else:
        logger.info("[MOMENTUM-AGREEMENT-FILTER] asset=%s spot_velocity=%.6f (%s) market_price=%.2f (%s) -> PASS (directions agree)", 
                    asset, velocity, spot_direction, market_price, kalshi_direction)
```

### 3. Price Band Edge Multipliers

**Location:** `merid/prediction/agent_grid_15m.py` lines 2699-2741

**Implementation:**
- **50-65c:** Sweet spot, baseline edge requirements (1.0x multiplier)
- **15-29c:** Deep OTM, require higher edge due to poor convexity
- **30-49c:** Conservative edge requirements
- **66-70c:** Near max price, require higher edge due to small payout
- Higher volatility assets (SOL, DOGE) need stricter multipliers

**Multiplier Matrix:**

| Price Band | BTC/ETH | XRP | SOL/DOGE |
|------------|---------|-----|----------|
| 15-29c | 2.0x | 2.5x | 3.0x |
| 30-49c | 1.5x | 2.0x | 2.5x |
| 50-65c | 1.0x | 1.0x | 1.0x |
| 66-70c | 1.5x | 2.0x | 2.5x |

**Code:**
```python
price_cents = (best_bid + best_ask) / 2 if best_bid and best_ask else 0
price_edge_multiplier = 1.0

if price_cents > 0:
    if 15 <= price_cents <= 29:
        if asset in ['SOL', 'DOGE']:
            price_edge_multiplier = 3.0
        elif asset in ['XRP']:
            price_edge_multiplier = 2.5
        else:  # BTC, ETH
            price_edge_multiplier = 2.0
    elif 30 <= price_cents <= 49:
        if asset in ['SOL', 'DOGE']:
            price_edge_multiplier = 2.5
        elif asset in ['XRP']:
            price_edge_multiplier = 2.0
        else:  # BTC, ETH
            price_edge_multiplier = 1.5
    elif 50 <= price_cents <= 65:
        price_edge_multiplier = 1.0
    elif 66 <= price_cents <= 70:
        if asset in ['SOL', 'DOGE']:
            price_edge_multiplier = 2.5
        elif asset in ['XRP']:
            price_edge_multiplier = 2.0
        else:  # BTC, ETH
            price_edge_multiplier = 1.5

edge_pct = edge_pct * price_edge_multiplier
```

### 4. Time Edge Multiplier Application

**Location:** `merid/prediction/agent_grid_15m.py` line 2697

**Implementation:**
- Apply time_edge_multiplier to edge calculation
- Late entries (2-4 minutes) require 1.5x edge due to edge decay

**Code:**
```python
edge_pct = edge_pct * time_edge_multiplier
```

---

## Research Alignment

### TheLines Research
- **50c to 55c entries:** Cleanest with strong signal, convexity still available ✅
- **55c to 65c entries:** Good when move established, continuation-focused ✅
- **Avoid > 70c:** Payout too small, fees/slippage matter more ✅ (max price 70c)
- **Avoid < 15c:** Deep OTM longshots with poor expected returns ✅ (min price 15c)
- **Entry zone:** First 3-8 minutes after clean impulse/pullback ✅ (4-12 minute optimal window)
- **Avoid first minute:** Initial price discovery noisy ✅ (skip ≥14 minutes to expiry)
- **Avoid last 2-4 minutes:** Edge decay dominates ✅ (skip ≤2 minutes to expiry)

### Perplexity Research
- **Selective timing:** Edge in quality, not frequency ✅ (time window filters)
- **Different thresholds per asset:** DOGE and SOL need stricter filters ✅ (price band multipliers)
- **Momentum agreement:** Trade only when spot momentum and Kalshi price direction agree ✅

### DefiRate Research
- **BTC/ETH:** Highest quality signals ✅ (lower edge multipliers)
- **SOL/XRP/DOGE:** Higher-volatility confirmation names ✅ (higher edge multipliers)

---

## Current Configuration Summary

**Price Range:** 15-70c (aligned with research)
**Time Windows:** 
- Skip first minute (≥14 minutes to expiry)
- Skip last 2 minutes (≤2 minutes to expiry)
- Reduced entries (2-4 minutes to expiry, 1.5x edge multiplier)
- Optimal window (4-12 minutes to expiry, baseline edge)

**Momentum Agreement:** Spot velocity direction must match Kalshi price direction
**Price Band Multipliers:** Per-asset multipliers based on volatility and price band
**Edge Thresholds:** Per-asset (BTC/ETH: 3%, SOL: 5%, XRP: 4%, DOGE: 5%)

---

## Files Modified

1. **merid/prediction/agent_grid_15m.py**
   - Added time window entry rules (lines 1914-1942)
   - Added momentum agreement check (lines 2287-2309)
   - Added price band edge multipliers (lines 2699-2741)
   - Applied time edge multiplier (line 2697)

2. **ENTRY_MATRIX_RESEARCH.md**
   - Research comparison document
   - Entry matrix design
   - Implementation plan

3. **MAKER_TAKER_AUDIT_REPORT.md**
   - End-to-end maker-taker audit
   - Price guard fixes documented
   - Per-asset parameter analysis

---

## Testing Strategy

Tests to be added:
1. Time window filter test (skip first/last minutes)
2. Momentum agreement check test (direction agreement)
3. Price band edge multiplier test (per-asset multipliers)
4. Time edge multiplier test (late entry multiplier)

---

## Expected Impact

**Positive:**
- Reduced noise trading (time window filters)
- Better signal quality (momentum agreement)
- Improved edge quality (price band multipliers)
- Asset-specific tuning (volatility-aware multipliers)

**Trade-offs:**
- Fewer total entries (stricter filters)
- Higher quality entries (better win rate expected)
- Late entries require stronger conviction (1.5x edge multiplier)

---

## Monitoring Metrics

Track after implementation:
- Entry frequency per asset
- Win rate per time window
- Win rate per price band
- Momentum agreement filter rate
- Overall PnL impact
