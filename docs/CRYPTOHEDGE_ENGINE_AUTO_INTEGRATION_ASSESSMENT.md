# CryptoHedgeEngine Auto-Integration Assessment

**Created:** 2026-07-07  
**Purpose:** Assess whether CryptoHedgeEngine should be automatically integrated into the 15m trading cycle

---

## Executive Summary

**Recommendation:** Do NOT auto-integrate CryptoHedgeEngine into the 15m trading cycle at this time.

**Rationale:**
1. 15m stack uses different architecture (agent grid) than legacy continuous trader
2. Current risk management (trailing stops, ratchet, dynamic TP) provides sufficient protection
3. Auto-hedging would add complexity without clear benefit for 15m binary options
4. Manual API control provides flexibility for operator intervention

---

## Background

### Legacy Conflict Report

The `docs/MOMENTUM_HEDGE_CONFLICT_REPORT.md` (May 2026) identified that CryptoHedgeEngine was not integrated into the legacy `kalshi_continuous_trader.py` cycle and recommended auto-integration as a critical fix.

**However**, this report was written for the **legacy continuous trader stack**, which is different from the current **15m lean stack**.

### Current 15m Stack Architecture

**File:** `web/main_15m_lean.py`

**Components:**
- Agent grid (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M)
- Market state store
- Order router with order gate
- Position monitor with exit policies
- CryptoHedgeEngine auto-exit loop (for hedge TP/SL only)

**Trading Cycle:**
1. Agent generates signal
2. Agent computes edge
3. Unified sizing computes order size
4. Order gate checks (window limits, price guards, duplicates)
5. Order router submits to Kalshi
6. Position monitor manages exits (TP/SL, trailing, ratchet, dynamic TP)

**Hedging Integration:**
- CryptoHedgeEngine auto-exit loop started at startup
- Hedge TP/SL managed independently
- Hedge proposal/activation requires manual API calls
- No automatic hedge order generation in agent cycle

---

## Assessment Criteria

### 1. Does 15m Stack Need Auto-Hedging?

**Current Risk Management:**
- **Window-based hard stops:** 3% per agent, 5% total per 15m window
- **Trailing stops:** Activated at 12c profit, aggressive 2c mode in 80-85c zone
- **Ratchet profit floor:** Locks in profits at 80-85c range
- **Dynamic take profit:** Laddered exits based on entry price
- **Extreme profit exit:** 99c YES / 1c NO (guaranteed win)
- **Stop loss:** Hard stop loss on position
- **Time stop:** Exit if no progress after 15 minutes
- **Candle reversal:** Exit on momentum reversal patterns

**Assessment:** Current risk management is comprehensive and appropriate for 15m binary options. Auto-hedging would be redundant.

### 2. Would Auto-Hedging Improve Risk-Adjusted Returns?

**Potential Benefits:**
- Reduce directional exposure across timeframes
- Maintain positions during drawdown with hedge protection
- Gradual position reduction vs. forced liquidation

**Potential Drawbacks:**
- Basis risk (prediction markets vs. spot/derivatives)
- Additional transaction costs (hedge orders)
- Complexity in position management (hedge + alpha positions)
- Potential for over-hedging (net exposure too small)
- Conflict with existing exit policies (trailing stops, ratchet)

**Assessment:** For 15m binary options, the short duration (15 minutes) and binary outcome make hedging less effective than direct position management. The current exit policies are better suited to the time horizon.

### 3. Is Auto-Hedging Aligned with 15m Strategy?

**15m Strategy Characteristics:**
- High-frequency trading (5s cadence)
- Short duration (15 minutes to expiry)
- Binary outcome (0 or 1 at settlement)
- Price-based entries (10-75c sweet spot)
- Momentum-based signals
- Quick profit taking (dynamic TP, ratchet)

**Hedging Characteristics:**
- Longer duration (multi-timeframe)
- Continuous price movements
- Basis risk management
- Position maintenance over time
- Gradual exposure reduction

**Assessment:** Auto-hedging is misaligned with 15m strategy. The strategy is designed for quick entries and exits, not position maintenance with hedge protection.

### 4. What Are the Implementation Costs?

**Required Changes:**
1. Integrate `compute_hedge_orders()` into agent grid cycle
2. Add hedge order routing after alpha order routing
3. Handle hedge order failures and retries
4. Track hedge positions alongside alpha positions
5. Update position monitor to handle hedge positions
6. Add hedge exposure to window limit accounting
7. Test hedge order generation and routing
8. Backtest auto-hedging vs. manual control
9. Update documentation and training materials

**Estimated Effort:** 3-5 days (implementation + testing + backtesting)

**Assessment:** High implementation cost for unclear benefit.

---

## Comparison: Manual vs. Auto Hedging

| Aspect | Manual (Current) | Auto (Proposed) |
|--------|------------------|-----------------|
| **Control** | Operator decides when to hedge | System decides automatically |
| **Flexibility** | High (operator discretion) | Low (rule-based only) |
| **Complexity** | Low (API endpoints) | High (cycle integration) |
| **Risk** | Operator error | System error / over-hedging |
| **Cost** | API call overhead | Transaction costs + complexity |
| **Suitability for 15m** | Appropriate | Misaligned |

---

## Recommendation: Keep Manual Control

### Rationale

1. **Current Risk Management is Sufficient**
   - Window-based hard stops prevent overexposure
   - Multiple exit policies (trailing, ratchet, dynamic TP) protect profits
   - Position monitor provides comprehensive exit management

2. **15m Strategy is Not Hedging-Friendly**
   - Short duration (15 minutes) makes hedging inefficient
   - Binary outcome creates basis risk with continuous instruments
   - High-frequency trading requires quick entries/exits, not position maintenance

3. **Manual Control Provides Flexibility**
   - Operator can decide when hedging is appropriate
   - Can be used for special situations (e.g., major news events)
   - Avoids automatic over-hedging

4. **Implementation Cost Outweighs Benefit**
   - 3-5 days of development and testing
   - Unclear improvement in risk-adjusted returns
   - Adds complexity to trading cycle

### When to Reconsider

Auto-integration may be appropriate if:

1. **Strategy Changes**
   - Move to longer timeframes (1h, daily)
   - Increase position holding duration
   - Shift from momentum to mean-reversion

2. **Risk Management Changes**
   - Remove window-based hard stops
   - Reduce exit policy effectiveness
   - Need for position maintenance during drawdown

3. **Market Changes**
   - Kalshi introduces longer-duration contracts
   - Increased correlation with spot/derivatives
   - Reduced basis risk

---

## Alternative: Conditional Auto-Hedging

If auto-hedging is desired in the future, consider a conditional approach:

```python
# In agent grid cycle
if hedge_config.auto_hedge_enabled:
    # Only auto-hedge if conditions met
    if (total_exposure > hedge_config.auto_hedge_threshold and
        drawdown < hedge_config.auto_hedge_max_drawdown and
        volatility_regime == "NORMAL"):
        hedge_orders = hedge_engine.compute_hedge_orders(...)
        for order in hedge_orders.orders:
            await route_order_async(order.to_intent(), source="HEDGE_ENGINE")
```

**Benefits:**
- Operator control via config flag
- Only hedges in appropriate conditions
- Avoids over-hedging in extreme markets

**Implementation:** 1-2 days (simpler than full auto-integration)

---

## Current Status Summary

**CryptoHedgeEngine Status:**
- ✅ Engine implemented and functional
- ✅ Config loaded from `kalshi_crypto_hedging.yaml`
- ✅ Auto-exit loop running for hedge TP/SL
- ✅ API endpoints available for manual control
- ❌ Not auto-integrated into agent grid cycle
- ❌ Hedge orders not automatically generated

**Recommendation:** Keep current state (manual control only).

---

## Next Steps

1. **Document Decision**
   - Update `docs/HEDGING_SYSTEM_ARCHITECTURE.md` with assessment results
   - Add decision rationale to system documentation

2. **Monitor Conditions**
   - Track if strategy changes (timeframes, holding duration)
   - Monitor risk management effectiveness
   - Assess if hedging needs change over time

3. **Reassess Periodically**
   - Quarterly review of hedging strategy
   - Backtest auto-hedging if conditions change
   - Update recommendation based on new data

---

## References

**Related Documentation:**
- `docs/HEDGING_SYSTEM_ARCHITECTURE.md` - Dual hedging system overview
- `docs/MOMENTUM_HEDGE_CONFLICT_REPORT.md` - Legacy conflict report (May 2026)
- `config/kalshi_crypto_hedging.yaml` - Hedge engine configuration
- `merid/hedging/engine.py` - CryptoHedgeEngine implementation
- `web/main_15m_lean.py` - 15m stack startup and cycle

**Key Files:**
- `merid/hedging/config.py` - Hedge config loader
- `web/api/prediction.py` - Hedge API endpoints
- `merid/position_management/position_monitor.py` - Position exit management
