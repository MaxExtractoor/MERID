# Conflict Report: Momentum Scalping vs. Hedging System
## MERID Trading System — Critical Issues & Recommended Fixes

**Audit Date:** May 2, 2026  
**Classification:** PRODUCTION BLOCKER — Fixes Required Before Live Trading

---

## Summary Statistics

| Severity | Count | Status |
|----------|-------|--------|
| 🔴 CRITICAL | 3 | Must fix before deployment |
| 🟡 MEDIUM | 5 | Should fix within 2 weeks |
| 🟢 LOW | 2 | Address when convenient |
| **Total** | **10** | |

---

## 🔴 CRITICAL CONFLICTS

### CONFLICT-001: Hedging Engine Not Integrated with CT Cycle

**Severity:** 🔴 CRITICAL  
**Impact:** Hedging system is dead code — no automatic hedging possible  
**Files:** `merid/trading/kalshi_continuous_trader.py`, `merid/hedging/engine.py`

**Description:**
The `CryptoHedgeEngine` class exists and is fully implemented but is **never called** from the continuous trader cycle. The CT runs its full discovery → edge → sizing → execute pipeline without any hedging computation step.

**Evidence:**
```python
# In kalshi_continuous_trader.py (~line 2000)
# After bankroll.calculate_order_size():

# Current code flow:
# 1. Discover markets
# 2. Calculate edges
# 3. Size orders via bankroll
# 4. EXECUTE (missing: compute hedge orders)

# Missing:
# hedge_orders = hedge_engine.compute_hedge_orders(exposure, config, bankroll)
```

**Risk:**
- Drawdown protection relies solely on halt switches (all-or-nothing)
- No ability to maintain positions with hedged protection
- Hedging config YAML has no effect

**Fix:**
```python
# In kalshi_continuous_trader.py, add after sizing:
from merid.hedging.engine import get_hedge_engine
hedge_engine = get_hedge_engine()
hedge_result = hedge_engine.compute_hedge_orders(
    exposure=current_exposure_snapshot,
    config=hedge_config,
    bankroll_cents=bankroll.balance_cents,
)
for order in hedge_result.orders:
    await route_order_async(order.to_intent(), source="HEDGE_ENGINE")
```

**Estimated Effort:** 4 hours  
**Testing:** Unit test with mock exposure, verify hedge orders generated

---

### CONFLICT-002: Conflicting Drawdown Thresholds Across Systems

**Severity:** 🔴 CRITICAL  
**Impact:** Unclear which drawdown limit applies; risk of unexpected halts  
**Files:** `merid/prediction/risk/kalshi_risk_engine.py`, `merid/event_venues/kalshi/cycle_drawdown.py`, `merid/hedging/config.py`

**Description:**
Three different systems enforce drawdown with conflicting thresholds:

| System | Halt Threshold | Reduce Threshold | Action |
|--------|----------------|------------------|--------|
| KalshiRiskEngine | 20% | 10% | HALT / REDUCE |
| CycleDrawdown | 3-7% (variable) | 25% of max | RESTRICT / DE-RISK |
| HedgeConfig | 40% | N/A | None (unused) |

**Contradiction:**
- Cycle drawdown triggers at 3-7% (tight)
- Portfolio drawdown triggers at 20% (loose)
- Hedge system never triggers (40% never reached)

**Risk:**
- System may halt at 7% (cycle) when user expects 20% (portfolio)
- No graduated response — no hedging mode before halt
- HedgeConfig 40% is meaningless noise

**Fix:**
Unify thresholds with clear hierarchy:

```python
# In unified config
DRAWDOWN_THRESHOLDS = {
    "warning": 0.03,      # 3% — alert only
    "hedge_active": 0.05,  # 5% — activate hedging (State B)
    "scalp_halt": 0.10,    # 10% — stop new scalping (State C)
    "full_halt": 0.15,     # 15% — close all positions (State D)
}
```

**Estimated Effort:** 2 days (refactoring + testing)  
**Testing:** Simulate drawdown scenarios, verify correct state transitions

---

### CONFLICT-003: No State Machine — Binary Trading vs. Flat

**Severity:** 🔴 CRITICAL  
**Impact:** System cannot operate in hedged mode; only scalping OR flat  
**Files:** `merid/trading/kalshi_continuous_trader.py` (entire cycle)

**Description:**
The CT operates as a binary system: either trading is enabled (full speed) or halted (flat). There is no intermediate "hedged scalping" state where positions are maintained with hedge protection.

**Current Logic:**
```python
if drawdown > halt_threshold:
    stop_trading()  # Go flat
else:
    trade_normally()  # Full risk
```

**Required Logic:**
```python
if drawdown > full_halt_threshold:
    go_flat()
elif drawdown > scalp_halt_threshold:
    hedge_only_mode()  # Maintain hedges, no new scalp
elif drawdown > hedge_active_threshold:
    scalp_with_hedge()  # Reduced size + active hedging
else:
    scalp_normally()
```

**Risk:**
- System gives up on profitable positions during drawdown
- No ability to "defend" positions with hedges
- Forced liquidation at worst possible times

**Fix:**
Implement the state machine described in `MOMENTUM_HEDGE_STATE_MACHINE.md`:
- State A: SCALP-ONLY (normal)
- State B: SCALP+HEDGE (protected)
- State C: HEDGE-ONLY (risk-off)
- State D: FLAT (no positions)

**Estimated Effort:** 3 days (new state machine + integration + UI updates)  
**Testing:** Full state transition testing, backtest hedge effectiveness

---

## 🟡 MEDIUM CONFLICTS

### CONFLICT-004: Sentiment Filter Reduces Hedge Effectiveness

**Severity:** 🟡 MEDIUM  
**Impact:** Fear/Greed filter may prevent proper hedging  
**File:** `merid/sentiment/btc_risk_dial.py`

**Description:**
The `fg_clamps()` function reduces position sizes by 60% in extreme fear (≤20) or extreme greed (≥80). However, extreme fear is precisely when hedging should be MAXIMUM, not reduced.

**Current Behavior:**
```python
extreme = (fg.value <= 25 or fg.value >= 75) and abs(fg.combined) > 0.2
if extreme:
    per_trade *= 0.60  # 60% reduction
```

**Risk:**
- System may be unable to establish full hedges during crisis
- Hedge protection under-sized when most needed
- Conflicting signals: risk dial says reduce, hedge engine says increase

**Fix:**
Separate sentiment treatment for alpha vs. hedge positions:
```python
# For alpha positions:
if extreme_fear_or_greed:
    alpha_size *= 0.60

# For hedge positions:
if extreme_fear:  # Risk-off signal
    hedge_size *= 1.50  # Increase hedging
```

**Estimated Effort:** 4 hours  
**Testing:** Unit test with extreme FG values

---

### CONFLICT-005: Cross-Asset Beta Not Used in Sizing

**Severity:** 🟡 MEDIUM  
**Impact:** SOL/DOGE positions under-sized relative to BTC  
**File:** `merid/signals/btc_anchored_move.py` (unused), `merid/trading/topn_allocator.py`

**Description:**
The `BtcAnchoredMoveModel` computes betas (SOL = 1.40x BTC), but the TopN allocator sizes all positions independently. This means:
- BTC position sized for 1% move
- SOL position sized same way, but SOL moves 1.40x as much
- Effective risk on SOL is 40% higher than intended

**Risk:**
- Position sizing doesn't reflect true risk
- Higher-beta assets create unexpected drawdown spikes
- Risk-adjusted returns suboptimal

**Fix:**
Apply beta normalization in position sizing:
```python
# In topn_allocator.py
def size_position(asset, edge, ...):
    base_size = compute_kelly_size(edge, ...)
    beta = get_beta(asset, "15m")  # From btc_anchored_move
    normalized_size = base_size / beta  # Reduce for high-beta assets
    return normalized_size
```

**Estimated Effort:** 1 day  
**Testing:** Verify SOL positions sized ~25% smaller than BTC

---

### CONFLICT-006: Asset-Uniform Indicator Parameters

**Severity:** 🟡 MEDIUM  
**Impact:** SOL/DOGE use same parameters as BTC despite different dynamics  
**File:** `merid/signals/crypto_15m_indicators.py`

**Description:**
All five assets use identical indicator parameters:
- EMA(50) trend filter
- RSI(8) overbought/oversold
- MACD(8,21,5)
- ATR 0.03% min-move

**Risk:**
- SOL/DOGE need faster indicators (shorter lookbacks)
- Slower assets (BTC) may need more smoothing
- Suboptimal signal quality on 2/5 assets

**Fix:**
Implement asset-specific configs:
```python
ASSET_PARAMS = {
    "BTC": {"ema_trend": 50, "rsi": 8, "macd_fast": 8, ...},
    "ETH": {"ema_trend": 45, "rsi": 8, "macd_fast": 8, ...},
    "SOL": {"ema_trend": 35, "rsi": 6, "macd_fast": 6, ...},
    "XRP": {"ema_trend": 40, "rsi": 7, "macd_fast": 7, ...},
    "DOGE": {"ema_trend": 30, "rsi": 5, "macd_fast": 5, ...},
}
```

**Estimated Effort:** 2 days (refactoring + backtest tuning)  
**Testing:** Backtest each asset with optimized params

---

### CONFLICT-007: Timeframe Mismatch in Risk Aggregation

**Severity:** 🟡 MEDIUM  
**Impact:** No coherent multi-timeframe risk view  
**Files:** Multiple

**Description:**
Risk checks operate on different time horizons without coordination:
- 15m indicators: 1m data, 15m evaluation
- Cycle drawdown: 15m rolling window
- Portfolio drawdown: Session-based
- Kalshi expiry: Variable (15m to weekly)

**Risk:**
- Position can pass 15m cycle check but violate portfolio limit
- Risk concentrations build across timeframes undetected
- No unified "current risk" metric

**Fix:**
Implement hierarchical risk tracking:
```python
class UnifiedRiskMonitor:
    def check_all(self, position_intent):
        # 1. 15m cycle check (fastest)
        if not cycle_drawdown.ok():
            return False, "cycle_limit"
        
        # 2. Hourly aggregation
        if not hourly_risk.ok():
            return False, "hourly_limit"
        
        # 3. Session/daily limit
        if not portfolio_drawdown.ok():
            return False, "portfolio_limit"
        
        return True, "ok"
```

**Estimated Effort:** 2 days  
**Testing:** Cross-timeframe stress test

---

### CONFLICT-008: FVG Detection Not Used for Entries

**Severity:** 🟢 LOW  
**Impact:** Missed entry opportunities from FVG retests  
**File:** `merid/signals/crypto_15m_indicators.py`

**Description:**
The indicator stack detects Fair Value Gaps (FVGs) with parameters:
- Min gap: 1.5x ATR or 0.2%
- Max age: 50 bars

However, FVG detection is informational only — not used in entry logic.

**Risk:**
- Missed high-probability entry signals
- Stops not placed at FVG levels (optimal S/R)

**Fix:**
Add FVG entry condition:
```python
# Entry trigger variant: FVG retest
if fvg_detected and price_retesting_fvg_level and trend_aligned:
    entry_signal = True
    stop_loss = fvg_opposite_side  # Use FVG as stop reference
```

**Estimated Effort:** 1 day  
**Testing:** Backtest FVG entry variant vs. base

---

## 🟢 LOW CONFLICTS

### CONFLICT-009: Hedge Engine Uses Static 50¢ Mid-Price Heuristic

**Severity:** 🟢 LOW  
**Impact:** Hedge sizing approximations when catalog unavailable  
**File:** `merid/hedging/engine.py` (~line 195)

**Description:**
When market catalog is unavailable, hedge engine falls back to 50¢ mid-price:
```python
mid_price_cents = self._resolve_mid_price(asset, tf, market_catalog)
if mid_price_cents <= 0:
    mid_price_cents = 50  # safe fallback
```

**Risk:**
- For OTM contracts (10¢ or 90¢), hedge sizing off by 5x
- Rare edge case (catalog should always be available)

**Fix:**
Use series average price from recent fills as fallback.

**Estimated Effort:** 2 hours  
**Testing:** Unit test with missing catalog

---

### CONFLICT-010: Cross-Asset Hedging Configured But Not Implemented

**Severity:** 🟢 LOW  
**Impact:** Cross-asset hedging config has no effect  
**File:** `merid/hedging/config.py`

**Description:**
Config has cross-asset section:
```python
cross_asset_enabled: bool = False  # Always false
cross_asset_pairs: Tuple[CrossAssetPairConfig, ...] = ()
```

The `engine.py` doesn't implement cross-asset hedge logic (only same-asset).

**Risk:**
- Config implies capability that doesn't exist
- Minor — same-asset hedging preferred anyway

**Fix:**
Either implement cross-asset hedging or remove from config to avoid confusion.

**Estimated Effort:** Remove: 30 min / Implement: 2 days  
**Testing:** N/A for removal

---

## Resolution Priority

### Week 1 (Critical Path)
1. **CONFLICT-001:** Wire hedge engine into CT
2. **CONFLICT-002:** Unify drawdown thresholds
3. **CONFLICT-003:** Implement state machine

### Week 2 (Signal Quality)
4. **CONFLICT-004:** Fix sentiment filter for hedges
5. **CONFLICT-005:** Apply beta normalization
6. **CONFLICT-006:** Asset-specific parameters

### Week 3 (Polish)
7. **CONFLICT-007:** Multi-timeframe risk aggregation
8. **CONFLICT-008:** FVG entry integration
9. **CONFLICT-009:** Catalog fallback improvement
10. **CONFLICT-010:** Cross-asset cleanup

---

## Testing Requirements

For each critical conflict fix:

1. **Unit tests:** Mock dependencies, verify correct behavior
2. **Integration tests:** Full CT cycle with test scenarios
3. **Backtests:** Historical simulation with conflict scenario replay
4. **Paper trading:** 48-hour validation on demo environment

**Pass Criteria:**
- All 3 critical conflicts resolved
- State machine transitions correctly in all test scenarios
- Hedge orders generated and routed appropriately
- Drawdown triggers at expected thresholds

---

**End of Conflict Report**
