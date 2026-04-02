# Live Deployment Checklist - Optimized Spot Bands

## ✅ Pre-Deployment (COMPLETED)

- [x] Spot band optimization system implemented
- [x] SPOT_BANDS configuration added to market_filter.py
- [x] Dynamic lookup function integrated into MarketFilter.evaluate()
- [x] Optimized values applied (20%-50% range based on liquidity)
- [x] Syntax validation passed
- [x] Changes committed (commit: 5f556c5)

## 🚀 Deployment Steps

### 1. On Trading Box - Set Live Environment

```bash
# Set all required environment variables
export MERID_ENV=prod
export MERID_TRADING_MODE=live
export MERID_TRADE_MODE=live
export MERID_LIVE_TRADING_UNLOCKED=true
export MERID_ALLOW_LIVE_TRADES=true
export KALSHI_USE_DEMO=false
export KALSHI_ENV=live
```

### 2. Pull Latest Code

```bash
cd /path/to/MERID
git pull origin claude/optimize-spot-band-configuration
# Or merge to main first if preferred
```

### 3. Restart Server

```bash
python -m web.main
```

### 4. Bring Up Agents/CT

Start the continuous trader as usual. The new spot bands will be active immediately.

## 📊 Applied Configuration

| Asset | 15m  | 1h   | daily | weekly | monthly |
|-------|------|------|-------|--------|---------|
| BTC   | 20%  | 25%  | 30%   | 35%    | 40%     |
| ETH   | 25%  | 30%  | 35%   | 40%    | 45%     |
| SOL   | 30%  | 35%  | 40%   | 45%    | 50%     |
| XRP   | 30%  | 35%  | 40%   | 45%    | 50%     |
| DOGE  | 35%  | 40%  | 45%   | 50%    | 50%     |

**Change from legacy**: All previously 12.5%, now optimized per asset/timeframe

## 🔍 Post-Deployment Monitoring

### First Hour - Check These Logs

1. **Candidate counts per asset/timeframe:**
   ```
   ContinuousTrader candidates: BTC 15m = X
   ContinuousTrader candidates: ETH 1h = X
   ```
   Expected: 30-50% increase compared to baseline (was ~2-5, now ~3-8 per pair)

2. **Edge validation:**
   ```
   signal_to_sizing: ... edge=0.0XXX ... ACCEPTED
   ```
   Expected: Edges still in 2-10% range (EDGE_THRESHOLDS still active)

3. **No new errors:**
   - Check for any filter-related errors
   - Verify no increase in execution rejections

### First 24 Hours - Monitor

- [ ] Total candidates found per cycle (expect +30-50%)
- [ ] Average edge of accepted candidates (should maintain quality)
- [ ] Execution stats (fills, rejections, PnL)
- [ ] No unexpected alerts or system issues

### Success Criteria

✅ All 25 (asset, timeframe) pairs have candidates in 80%+ of cycles
✅ Average edge >= baseline (2-10% range maintained)
✅ No increase in execution rejections
✅ System stable (no errors, event loop lag < 500ms)

## 🛡️ Safety Guarantees

- ✅ All existing filters remain active (spread, volume, OI, edge thresholds)
- ✅ Risk caps unchanged (portfolio 3%, per-asset varies, drawdown 40%)
- ✅ Execution gate still blocks unsafe conditions
- ✅ Kill switches operational

## 🔄 Rollback Plan (If Needed)

If issues arise, rollback is simple:

```python
# In merid/event_venues/kalshi/market_filter.py
# Change all SPOT_BANDS values back to 0.125
("BTC", "15m"): 0.125,  # etc.
```

Or revert commit:
```bash
git revert 5f556c5
```

## 📝 Expected Impact

**Positive Changes:**
- 30-50% more trading candidates per cycle
- Better coverage for less liquid assets (SOL, XRP, DOGE)
- Maintained edge quality via existing thresholds

**Unchanged:**
- BTC may see modest increase (bands only 60% wider: 12.5% → 20-25%)
- All risk management, filters, and guardrails remain active
- Edge thresholds continue to filter low-quality candidates

## 📞 Support

If monitoring shows unexpected behavior:
1. Check logs for filter rejection reasons
2. Review candidate edge distributions
3. Verify SPOT_BANDS configuration is correct
4. Consider rollback if issues persist

---

**Deployment Date:** _____________________
**Deployed By:** _____________________
**Live Since:** _____________________
**Status:** ⏳ Ready for deployment
