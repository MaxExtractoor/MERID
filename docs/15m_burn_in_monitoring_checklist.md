# 15m Mean-Reversion Burn-In Monitoring Checklist

**Purpose:** Validate that the system is expressing the mean-reversion design correctly after P0/P1 audit fixes.

**Target:** 30-50 trades per asset (BTC, ETH, SOL, XRP, DOGE) in paper mode over 24-48 hours.

**Strategy Identity:** Mean-Reversion Scalping
- Entry: Fade price extremes when they re-enter Bollinger Bands (short upper touches, long lower touches)
- Regime: Range-only (ADX < 20), avoid trending markets
- Exit: Target mid-band (SMA) with ATR-based stop loss
- Edge: 2-3% prob_edge baseline across all assets
- Risk: 1% max per trade

---

## Runtime Checklist

### 1. Signal Location
**Check:** Every entry should occur at or beyond the outer band (or at defined "top edge" threshold) with clear deviation from the mean.

**What to monitor:**
- Entry price is at or beyond upper/lower Bollinger Band
- Z-score from SMA is ≥ 2.0 (or asset-specific threshold)
- Entry occurs when price re-enters band from outside (not on first touch)
- No entries in middle of band range

**Pass criteria:**
- 90%+ of entries occur at band edges (z-score ≥ 2.0)
- No entries in middle 50% of band width
- Entries align with "top edge" concept (extreme deviations only)

**Fail indicators:**
- Entries occurring randomly within band range
- Entries at SMA or mid-band (momentum behavior, not mean-reversion)
- Entries on first band touch without re-entry confirmation

---

### 2. Direction Logic
**Check:** Fade behavior - short at upper band, long at lower band, in range regime only.

**What to monitor:**
- At upper band: Short / fade back toward midline in range regime
- At lower band: Long / fade up toward midline in range regime
- ADX < 20 for all entries (range regime)
- RSI confirmation: oversold (<30) for long, overbought (>70) for short
- No entries when ADX ≥ 20 (trend regime filter active)

**Pass criteria:**
- 100% of upper band entries are SHORT
- 100% of lower band entries are LONG
- 95%+ of entries have ADX < 20
- RSI confirmation present (direction-appropriate extreme)

**Fail indicators:**
- Long entries at upper band (momentum behavior)
- Short entries at lower band (momentum behavior)
- Entries in trending markets (ADX ≥ 20)
- Missing RSI confirmation

---

### 3. Risk Per Trade
**Check:** No trade should exceed 1% risk per trade based on account equity.

**What to monitor:**
- Position size × stop-loss distance ≤ 1% of bankroll
- Kalshi risk engine max_risk_per_trade_pct = 0.01 (1%)
- No log line or fill shows >1% risk
- Consistent sizing across all assets (not varying wildly)

**Pass criteria:**
- 100% of trades have risk ≤ 1% of bankroll
- Max observed risk ≤ 1.05% (allowing for minor rounding)
- No trades blocked by risk limits (system properly sized)

**Fail indicators:**
- Any trade with risk > 1.05%
- Trades blocked by risk engine (sizing too aggressive)
- Wildly varying position sizes (no consistent sizing logic)

---

### 4. Edge Usage
**Check:** Filled trades should cluster in the 2-3% prob_edge corridor, not legacy 5-10% values.

**What to monitor:**
- prob_edge for filled trades should be 0.02-0.03 (2-3%)
- No trades with prob_edge < 0.02 (below floor)
- No trades with prob_edge > 0.05 (legacy "sure bet" mode)
- Edge distribution centered around configured baseline

**Pass criteria:**
- 90%+ of filled trades have prob_edge in [0.02, 0.03]
- No trades with prob_edge < 0.015
- No trades with prob_edge > 0.04
- Mean prob_edge ≈ 0.025 (2.5%)

**Fail indicators:**
- Trades with prob_edge < 0.02 (below new floor)
- Trades with prob_edge > 0.05 (legacy behavior)
- Edge distribution shifted (config not applied)

---

### 5. Validator Health
**Check:** Startup validator passes and fails loudly on contradictions.

**What to monitor:**
- Startup completes without config validation errors
- Validator runs in startup sequence (web/main.py lifespan)
- No warnings about edge threshold variance
- No warnings about risk limit violations

**Pass criteria:**
- Startup completes cleanly with "✅ Config validation passed"
- No validator errors or warnings
- All YAML configs load successfully

**Fail indicators:**
- Startup blocked by config validation errors
- Validator warnings about contradictions
- Config files fail to load

---

## Data Collection Plan

### Per-Asset Metrics to Track

For each asset (BTC, ETH, SOL, XRP, DOGE), collect:

1. **Trade count:** Total number of entries
2. **Entry location:** Z-score at entry (distance from SMA in SD units)
3. **Direction:** % SHORT at upper band, % LONG at lower band
4. **Regime:** % entries with ADX < 20 (range regime)
5. **RSI confirmation:** % entries with appropriate RSI extreme
6. **Risk per trade:** Mean, max, std dev of % bankroll risked
7. **Edge:** Mean, min, max of prob_edge
8. **Outcome:** Win/loss, PnL, hold time

### Aggregate Metrics

- Total trades across all assets
- Asset starvation: Any asset with < 10 trades (may need config adjustment)
- Win-rate target: 80%+ (long-term goal, not immediate requirement)
- Average hold time: Should be < 240 minutes (max hold setting)

---

## Success Criteria

**Minimum to proceed to tuning:**
- 30 trades per asset (150 total)
- 90%+ entries at band edges (z-score ≥ 2.0)
- 100% correct direction logic (short upper, long lower)
- 95%+ entries in range regime (ADX < 20)
- 100% trades ≤ 1% risk
- 90%+ trades with prob_edge in 2-3% corridor

**If criteria not met:**
- Investigate config issues (edge thresholds too high/low)
- Check band parameters (period, SD multipliers)
- Verify regime filter (ADX threshold)
- Review entry filters (RSI, volatility gates)
- Adjust before proceeding to band/TP tuning

---

## Next Steps After Burn-In

Once burn-in criteria are met:

1. **Band parameter tuning:** Optimize BB period, SD multipliers per asset
2. **TP/SL optimization:** Tune take-profit and stop-loss levels for 80%+ win-rate
3. **Entry filter refinement:** Adjust RSI, volatility, chop filters
4. **Walk-forward testing:** Validate parameter stability across time periods
5. **Live-small deployment:** Gradual rollout with position size limits

---

## Reference Links

- [Mean-Reversion Trading Strategy Guide](https://surmount.ai/blogs/mean-reversion-trading-strategy-the-complete-guide)
- [1% Risk Rule for Day Trading](https://tradethatswing.com/the-1-risk-rule-for-day-trading-and-swing-trading/)
- [Mean-Reversion Strategies for Algorithmic Trading](https://www.luxalgo.com/blog/mean-reversion-strategies-for-algorithmic-trading/)
- [Common Algorithmic Trading Errors](https://nurp.com/algorithmic-trading-blog/common-algorithmic-trading-errors-and-solutions/)
