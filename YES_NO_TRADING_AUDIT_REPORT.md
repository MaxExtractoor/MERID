# YES/NO Trading Deep Audit Report

**Date**: 2026-07-31  
**System**: MERID Kalshi Trading Stack  
**Profile**: kalshi_crypto_15m_v2  
**Issue**: System only trading YES, not NO

---

## Executive Summary

The MERID trading system is configured to trade both YES and NO sides, but multiple high-leverage bugs prevent NO-side trading from functioning. The root cause is a combination of neutralized synthetic bias, incomplete arbitrage wiring, and strategy logic that systematically favors YES-side signals.

**Critical Finding**: The system has all the infrastructure for NO-side trading (BUY_NO, SELL_NO signals, order routing, position management), but the signal generation and execution pathways are broken or incomplete.

---

## Root Cause Analysis

### 1. Neutralized Synthetic Bias (PRIMARY ROOT CAUSE)

**Location**: `merid/prediction/model.py:601`

```python
if _profile == "kalshi_crypto_15m_v2":
    _SYNTHETIC_BIAS = Decimal("0.0")
    logger.debug("[model] Synthetic bias neutralized for kalshi_crypto_15m_v2 (profile-driven mode)")
```

**Issue**: The synthetic bias that creates directional signals from spread analysis is explicitly neutralized to 0.0 for the production profile. This removes the primary mechanism for generating NO-side signals when market microstructure suggests NO is undervalued.

**Impact**: 
- When `yes_ask < no_ask`, the system should bias toward YES (mp = 0.5 + bias)
- When `no_ask < yes_ask`, the system should bias toward NO (mp = 0.5 + bias)  
- With bias = 0.0, both cases result in mp = 0.5, creating no directional edge

**Why This Exists**: Profile-driven architecture intended to rely on other signal sources (velocity, sentiment, spot price) rather than spread microstructure.

---

### 2. Incomplete Arbitrage Wiring

**Location**: `merid/event_venues/kalshi/duality_validator.py:464-471`

**Issue**: The arbitrage callback mechanism exists but is never registered.

```python
def set_arbitrage_callback(self, callback: Callable[[ArbitrageOpportunity], None]) -> None:
    """Register a callback to execute arbitrage opportunities."""
    self._arbitrage_callback = callback
    logger.info("[ARBITRAGE-SET] Arbitrage execution callback registered")
```

**Evidence**:
- Arbitrage detection works: `loop_15m.py:3520-3536` checks for arbitrage opportunities
- Arbitrage execution function exists: `order_router.py:10129-10215` has `execute_arbitrage_async()`
- **Missing**: No code calls `get_duality_validator().set_arbitrage_callback()`

**Impact**: YES/NO arbitrage opportunities are detected and logged but never executed. This is a critical missed opportunity for risk-free profits and natural NO-side exposure.

---

### 3. Strategy Logic Biases Toward YES

**Location**: `merid/prediction/strategy.py:1431`

```python
best = max(spec_edges, key=lambda e: e.net_edge)
```

**Issue**: The strategy selects the best edge based solely on `net_edge`, but edge computation (lines 608-661 in model.py) with neutralized bias creates symmetric edges that may systematically favor YES due to:

1. **Implied probability bias**: `implied.yes_prob` and `implied.no_prob` are derived from market makers who may skew toward YES
2. **Spot price model bias**: When using spot price for probability (lines 522-570), the linear mapping `yes_prob = 0.5 + (dist_pct * scale)` may have calibration bias
3. **Sentiment model not implemented**: `_get_sentiment_model_prob()` (line 837) always returns `None`, forcing fallback to spread-based logic with neutralized bias

**Impact**: Even when both YES and NO edges are computed, the selection logic may systematically pick YES edges due to input data biases.

---

### 4. Entry Trade Logic Restriction

**Location**: `merid/prediction/strategy.py:2127`

```python
action = SignalAction.BUY_YES if best.side == "yes" else SignalAction.BUY_NO
```

**Issue**: Entry trades are restricted to BUY actions only. The system never uses SELL_YES or SELL_NO for entry, even though these are valid signal types.

**Impact**:
- Cannot short YES (SELL_YES) for entry
- Cannot short NO (SELL_NO) for entry  
- Limited to long-only entry strategies
- Missing opportunities to sell overpriced contracts

**Why This Exists**: Comment states "Entry trades must ALWAYS use BUY actions" - this is a design choice, not a bug, but limits trading flexibility.

---

### 5. Behavioral Exploitation Limited

**Location**: `merid/prediction/strategy.py:2032-2042`

```python
if has_longshot and recommended_side == "no":
    # Overpriced longshot - switch to NO (or sell YES)
    if best.side == "yes":
        logger.info("[LONGSHOT-BIAS-EXPLOIT] switching from BUY_YES to BUY_NO")
        best.side = "no"
```

**Issue**: The only mechanism that switches from YES to NO is the longshot bias exploitation, which requires:
- `has_longshot = "longshot_inflated" in patterns`
- `recommended_side == "no"`
- `best.side == "yes"` (currently on YES side)

**Impact**: NO-side signals only generated when specific behavioral patterns are detected, not as part of normal signal generation.

---

## Secondary Issues

### 6. Market Making Incomplete

**Location**: `config/profiles/kalshi_crypto_15m_v2.yaml:165-179`

**Issue**: Market making is enabled in configuration but implementation is incomplete in `loop_15m.py:3538-3560`.

```python
if self._market_maker and state and asset_depth_ok:
    try:
        if self._market_maker.should_refresh_quotes():
            quotes = self._market_maker.generate_quotes(...)
```

**Evidence**: 
- Configuration exists with two-phase quoting strategy
- `should_refresh_quotes()` and `generate_quotes()` are called
- **Missing**: Quote execution logic - quotes are generated but never submitted to order router

**Impact**: Natural two-sided trading (providing liquidity on both YES and NO) is not functioning.

---

### 7. Sentiment Model Not Implemented

**Location**: `merid/prediction/model.py:837-862`

```python
def _get_sentiment_model_prob(self, asset: Optional[str], side: str) -> Optional[Decimal]:
    """Get sentiment-driven model probability for directional markets."""
    if not asset:
        return None
    logger.debug("[model_sentiment] asset=%s side=%s sentiment=None", asset, side)
    return None
```

**Issue**: The sentiment model always returns `None`, forcing fallback to spread-based logic with neutralized bias.

**Impact**: A key signal source for directional bias is non-functional, removing potential NO-side signals.

---

## High-Leverage Bugs Summary

| Priority | Component | Issue | Impact | Fix Complexity |
|----------|-----------|-------|--------|----------------|
| **P0** | Arbitrage Wiring | Callback never registered | Missed risk-free profits, no NO-side arb exposure | LOW (add one line) |
| **P0** | Synthetic Bias | Neutralized for production profile | No directional signals from spread | MEDIUM (adjust bias or enable alternative signals) |
| **P1** | Market Making | Quotes generated but not executed | No two-sided liquidity provision | MEDIUM (add quote execution) |
| **P1** | Sentiment Model | Always returns None | Missing directional signal source | HIGH (implement sentiment integration) |
| **P2** | Strategy Selection | May systematically favor YES | YES-side bias in edge selection | LOW (add side diversity factor) |
| **P3** | Entry Logic | BUY-only restriction | Limited trading flexibility | MEDIUM (design change) |

---

## Recommended Fixes

### Immediate (P0)

1. **Wire Arbitrage Callback** (5 minutes)
   ```python
   # In loop_15m.py initialization
   from merid.event_venues.kalshi.duality_validator import get_duality_validator
   from merid.event_venues.kalshi.order_router import execute_arbitrage_async
   
   def arb_callback(opp):
       asyncio.create_task(execute_arbitrage_async(
           opp.yes_ticker, opp.no_ticker, opp.yes_ask, opp.no_bid, opp.recommended_size
       ))
   
   get_duality_validator().set_arbitrage_callback(arb_callback)
   ```

2. **Enable Non-Zero Synthetic Bias** (5 minutes)
   ```python
   # In model.py:601, change from:
   _SYNTHETIC_BIAS = Decimal("0.0")
   # To:
   _SYNTHETIC_BIAS = Decimal("0.02")  # 2% bias for directional signals
   ```

### Short-term (P1)

3. **Complete Market Making Execution** (2 hours)
   - Add quote submission logic after `generate_quotes()`
   - Convert quotes to OrderIntent objects
   - Route quotes to order router

4. **Implement Sentiment Model** (8 hours)
   - Integrate with existing sentiment data sources
   - Implement probability mapping from sentiment scores
   - Add YES/NO directional bias from sentiment

### Medium-term (P2-P3)

5. **Add Side Diversity to Strategy Selection** (4 hours)
   - Modify edge selection to consider both sides
   - Add side diversity score to edge comparison
   - Ensure balanced YES/NO signal generation

6. **Consider SELL Actions for Entry** (Design discussion)
   - Evaluate risk/reward of allowing SELL_YES/SELL_NO for entry
   - Implement if aligned with risk management strategy
   - Add position sizing for short entries

---

## Verification Steps

After implementing fixes:

1. **Test Arbitrage Execution**
   - Create synthetic market with yes_ask + no_bid < 95c
   - Verify arbitrage callback is triggered
   - Confirm both sides are executed

2. **Test Synthetic Bias**
   - Create market with no_ask < yes_ask
   - Verify NO-side signal is generated
   - Check BUY_NO order is submitted

3. **Test Market Making**
   - Enable market making in test environment
   - Verify quotes are generated and submitted
   - Confirm two-sided quoting (YES and NO)

4. **Monitor YES/NO Ratio**
   - Track signal generation by side (YES vs NO)
   - Target: 40-60% balance (not 100% YES)
   - Alert if ratio exceeds 80:20

---

## Conclusion

The MERID system has comprehensive infrastructure for YES/NO trading but is prevented from trading NO by:
1. Neutralized synthetic bias (primary root cause)
2. Unwired arbitrage execution (missed opportunities)
3. Incomplete market making (no two-sided liquidity)
4. Non-functional sentiment model (missing signal source)

The fixes are straightforward and can be implemented incrementally. The highest-impact fix is wiring the arbitrage callback, which will immediately enable NO-side trading through arbitrage opportunities.

**Estimated Time to Full NO-Side Trading**: 1-2 days with focused development effort.