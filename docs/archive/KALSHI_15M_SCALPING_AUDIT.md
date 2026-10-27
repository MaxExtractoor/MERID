# Kalshi 15-Minute Crypto Scalping Audit

**Date**: 2026-06-02  
**System**: MERID Agent Grid 15m (Kalshi Crypto 15m v2 Profile)  
**Assets**: BTC, ETH, SOL, XRP, DOGE  
**Target Use Case**: High-frequency short-hold scalping on 15-minute Kalshi crypto markets

---

## 1. Executive Verdict

**NO-GO** - This system is fundamentally unsuitable for 15-minute Kalshi crypto scalping.

**Summary**: The system is designed for swing trading (2-12 minute holds, 1-2 trades per cycle, 5% edge requirements) but is being evaluated for scalping (sub-1 minute holds, rapid entries/exits, high turnover). The architecture, risk controls, and execution logic are misaligned with scalping requirements. While the infrastructure is solid for its intended purpose, it would require substantial redesign to function as a scalping system.

**Critical Deal-Breakers**:
1. **Cycle frequency mismatch**: 15-minute cycle cadence is too slow for scalping (need 5-30 second cycles)
2. **Edge requirements too high**: 3-5% edge thresholds are unrealistic for scalping (need 0.5-1%)
3. **No stop-loss mechanism**: Cannot cut losses quickly in fast-moving markets
4. **No partial fill handling**: Scalping requires aggressive partial fill management
5. **No volatility regime detection**: Static thresholds fail during spikes
6. **No backtesting evidence**: No proof of edge on intraday data

---

## 2. Strengths

### Infrastructure
- **Solid WebSocket integration**: Real-time market data via KalshiMarketStateStore
- **Clean architecture**: Modular design with clear separation of concerns
- **Good logging**: EXECUTION-ATTEMPT, LIQUIDITY-LIFECYCLE, and detailed diagnostics
- **Risk envelope system**: Per-asset notional limits and cycle risk controls
- **Priority queue scheduling**: Best-edge-first order selection

### Market Data Handling
- **Dual-sided edge calculation**: Accounts for spread cost and fees in edge computation
- **Market state validation**: Canonical pre-trade validator with lifecycle checks
- **Freshness gates**: MD age limits (120s) prevent stale data trading
- **Liquidity diagnostics**: Per-asset depth tracking and one-sided rate monitoring

### Execution Path
- **IOC auto-conversion**: Automatically switches to IOC near expiry
- **Post-only support**: Can submit maker-only orders to avoid taker fees
- **Order intent tracking**: Unique client_tag for idempotency
- **Resting order monitor**: Tracks GTC limit orders for fill management

---

## 3. Weaknesses

### Cycle Frequency
- **15-minute cycle cadence**: Too slow for scalping - markets move faster than system can react
- **1 order per cycle limit**: Severely limits trade frequency for scalping
- **No sub-cycle execution**: Cannot react to intraday price movements between cycles
- **Priority queue overhead**: Adds latency to order submission

### Edge Requirements
- **3-5% edge thresholds**: Unrealistic for scalping - typical scalping edges are 0.5-1%
- **Static thresholds**: No dynamic adjustment based on volatility or market conditions
- **No edge decay modeling**: Edge deteriorates as expiry approaches but not accounted for
- **No slippage modeling**: Assumes perfect fills at limit prices

### Execution Logic
- **GTC default time-in-force**: Scalping needs IOC/FOK for immediate fills
- **No partial fill handling**: Cannot manage aggressive partial fills on thin books
- **No stale quote protection**: No check for quote staleness before submission
- **No fast reversal handling**: Cannot quickly flip positions on momentum reversals
- **No order queue position tracking**: Cannot assess fill probability before submission

### Risk Controls
- **No stop-loss mechanism**: Cannot cut losses quickly - critical for scalping
- **No dynamic position sizing**: Size doesn't scale with volatility or edge quality
- **No intraday drawdown limits**: Only daily/weekly limits - too slow for scalping
- **No correlation guards**: Can accumulate correlated positions across assets simultaneously
- **Cooldown periods (2 cycles)**: 30-minute cooldowns are too long for scalping

### Market Behavior Handling
- **No volatility regime detection**: Static thresholds fail during spikes
- **No news event handling**: No pause during high-impact events
- **No gap risk management**: Cannot handle overnight or weekend gaps
- **No liquidity regime detection**: Doesn't adjust for thin vs thick market conditions

### Backtesting & Validation
- **No intraday backtesting**: No evidence of testing on 15-minute data
- **No walk-forward validation**: No out-of-sample testing
- **No fill simulation**: Backtests likely assume perfect fills
- **No slippage modeling**: Doesn't account for realistic execution costs
- **No regime analysis**: No testing across different volatility regimes

### Monitoring
- **No edge deterioration detection**: Cannot detect when edge degrades
- **No automatic shutdown**: No kill switch when performance drops
- **No fill rate monitoring**: Cannot track execution quality
- **No slippage tracking**: Cannot measure execution costs
- **No PnL attribution**: Cannot separate edge from execution costs

---

## 4. Failure Points

### Point 1: Cycle Frequency Mismatch (CRITICAL)
**Issue**: 15-minute cycle cadence is fundamentally incompatible with scalping.

**Evidence**:
- `loop_15m.py` runs cycles every 15 minutes
- `agent_grid_15m.py` `_MAX_ORDERS_PER_CYCLE = 1` limits to 1 order per cycle
- Priority queue scheduling adds overhead within each cycle
- No mechanism for sub-cycle execution or rapid re-evaluation

**Impact**: In a 15-minute market, price can move 5-10% between cycles. By the time the system evaluates a signal, the edge may have evaporated or reversed. Scalping requires 5-30 second reaction times.

**Failure Mode**: System enters positions after edge has decayed, exits too late, misses profitable opportunities.

### Point 2: Edge Thresholds Too High (CRITICAL)
**Issue**: 3-5% edge requirements are unrealistic for short-hold trading.

**Evidence**:
- `ASSET_PROFILE` edge thresholds: BTC/ETH 5%, SOL/XRP 4%, DOGE 3%
- `_MIN_EDGE_PER_TRADE = 0.01` (1%) at queue level
- UnifiedEdgeComputer requires net_edge after spread and fees
- Typical 15-minute crypto moves are 1-3% - requiring 3-5% edge means almost no trades

**Impact**: System will rarely find qualifying trades. When it does, the edge is likely statistical noise rather than a real opportunity. Scalping requires lower edges (0.5-1%) with higher turnover.

**Failure Mode**: System generates no trades or trades on false positives with insufficient edge.

### Point 3: No Stop-Loss Mechanism (CRITICAL)
**Issue**: Cannot cut losses quickly in fast-moving markets.

**Evidence**:
- No stop-loss price tracking in OrderIntent
- No stop-loss order submission logic
- No automatic position exit on adverse moves
- Risk controls only limit position size, not individual trade loss

**Impact**: In scalping, a single bad trade can wipe out profits from 10 good trades. Without stop-losses, losses can spiral during volatility spikes.

**Failure Mode**: System holds losing positions too long, catastrophic drawdowns during spikes.

### Point 4: No Partial Fill Handling (CRITICAL)
**Issue**: Cannot manage aggressive partial fills on thin orderbooks.

**Evidence**:
- OrderIntent assumes full fill at specified price
- No logic to handle partial fills or re-submit unfilled portions
- No order queue position tracking to assess fill probability
- No market impact modeling for larger orders

**Impact**: On thin books (DOGE depth 5 contracts), a 10-contract order may partially fill at a worse price. The system doesn't account for this, leading to unexpected slippage.

**Failure Mode**: Unexpected slippage on partial fills, edge erosion, poor execution quality.

### Point 5: No Volatility Regime Detection (HIGH)
**Issue**: Static thresholds fail during volatility spikes.

**Evidence**:
- Edge thresholds are static per asset
- No volatility regime classification (LOW/NORMAL/HIGH/EXTREME)
- No dynamic threshold adjustment based on ATR or realized vol
- No pause during extreme volatility

**Impact**: During volatility spikes, spreads widen, edge requirements become impossible, but system doesn't adapt. Conversely, during low volatility, edge requirements are too conservative.

**Failure Mode**: Misses opportunities during high vol, over-trades during low vol, poor risk-adjusted returns.

### Point 6: No Backtesting Evidence (HIGH)
**Issue**: No proof of edge on realistic intraday data.

**Evidence**:
- No backtest results in codebase or documentation
- No walk-forward validation methodology
- No fill simulation or slippage modeling
- No regime analysis or stress testing

**Impact**: System is theoretical - no evidence it would be profitable in live trading. Edge requirements may be based on incorrect assumptions.

**Failure Mode**: Live trading losses due to unvalidated assumptions, poor performance.

### Point 7: GTC Time-in-Force Default (MEDIUM)
**Issue**: Default GTC orders are inappropriate for scalping.

**Evidence**:
- OrderIntent default `time_in_force = "gtc"`
- IOC auto-conversion only near expiry (below threshold)
- No option to force IOC for all scalping orders

**Impact**: Scalping requires immediate fills or no trade. GTC orders can sit unfilled, tying up capital and missing opportunities.

**Failure Mode**: Capital tied up in unfilled orders, missed opportunities, poor capital efficiency.

### Point 8: Cooldown Periods Too Long (MEDIUM)
**Issue**: 2-cycle (30-minute) cooldowns are too long for scalping.

**Evidence**:
- `base_cooldown_cycles = 2` in AssetProfile
- 15-minute cycle cadence = 30-minute cooldown
- No dynamic cooldown based on market conditions

**Impact**: After a trade, system cannot re-enter for 30 minutes. In a 15-minute market, this misses multiple opportunities.

**Failure Mode**: Low trade frequency, missed opportunities, poor capital efficiency.

---

## 5. Required Fixes

### Fix 1: Redesign for Sub-Cycle Execution (CRITICAL)
**Change**: Implement 5-30 second execution cadence instead of 15-minute cycles.

**Implementation**:
- Replace `loop_15m.py` with event-driven execution on market data updates
- Remove `_MAX_ORDERS_PER_CYCLE` limit
- Implement continuous order evaluation pipeline
- Add real-time market data trigger for signal re-evaluation

**Complexity**: High - requires architectural redesign

### Fix 2: Lower Edge Thresholds (CRITICAL)
**Change**: Reduce edge thresholds to 0.5-1% for scalping.

**Implementation**:
- Update `ASSET_PROFILE` edge thresholds: BTC/ETH 1%, SOL/XRP 0.75%, DOGE 0.5%
- Reduce `_MIN_EDGE_PER_TRADE` to 0.005 (0.5%)
- Add dynamic edge adjustment based on volatility regime
- Implement edge decay modeling as expiry approaches

**Complexity**: Medium - requires parameter tuning and regime logic

### Fix 3: Implement Stop-Loss Mechanism (CRITICAL)
**Change**: Add automatic stop-loss on adverse price moves.

**Implementation**:
- Add `stop_loss_price_cents` to OrderIntent (already exists but unused)
- Implement stop-loss order submission logic in order_router
- Add real-time PnL monitoring for open positions
- Implement automatic position exit on stop-loss trigger

**Complexity**: High - requires position monitoring and order management

### Fix 4: Add Partial Fill Handling (CRITICAL)
**Change**: Handle partial fills and re-submit unfilled portions.

**Implementation**:
- Add partial fill detection in fill processing
- Implement unfilled portion re-submission logic
- Add order queue position tracking
- Implement market impact modeling for larger orders

**Complexity**: High - requires order management system redesign

### Fix 5: Implement Volatility Regime Detection (HIGH)
**Change**: Classify volatility regimes and adjust thresholds dynamically.

**Implementation**:
- Add ATR or realized volatility calculation
- Implement regime classifier (LOW/NORMAL/HIGH/EXTREME)
- Add dynamic threshold adjustment based on regime
- Implement automatic pause during extreme volatility

**Complexity**: Medium - requires volatility calculation and regime logic

### Fix 6: Conduct Intraday Backtesting (HIGH)
**Change**: Backtest on realistic 15-minute data with fill simulation.

**Implementation**:
- Collect historical 15-minute Kalshi crypto market data
- Implement backtest engine with fill simulation
- Add slippage modeling based on orderbook depth
- Conduct walk-forward validation across multiple periods
- Test across different volatility regimes

**Complexity**: High - requires data collection and backtest infrastructure

### Fix 7: Force IOC Time-in-Force (MEDIUM)
**Change**: Default to IOC for scalping orders.

**Implementation**:
- Change OrderIntent default `time_in_force` to "ioc"
- Add configuration option for TIF selection
- Implement immediate fill-or-cancel logic
- Add unfilled order re-submission if needed

**Complexity**: Low - simple parameter change

### Fix 8: Reduce Cooldown Periods (MEDIUM)
**Change**: Reduce cooldowns to 0-1 cycles for scalping.

**Implementation**:
- Update `base_cooldown_cycles` to 0 or 1
- Implement dynamic cooldown based on market conditions
- Add cooldown bypass for high-confidence signals

**Complexity**: Low - simple parameter change

---

## 6. Go / No-Go Recommendation

**Recommendation: NO-GO**

**Rationale**:
1. **Architectural mismatch**: The system is designed for swing trading, not scalping. The cycle frequency, edge requirements, and risk controls are fundamentally misaligned with scalping requirements.

2. **Critical missing features**: Stop-loss mechanism, partial fill handling, and volatility regime detection are essential for scalping but absent from the system.

3. **No validation evidence**: No backtesting or proof of edge on intraday data. The system is theoretical and likely unprofitable in live trading.

4. **High implementation cost**: Required fixes are high-complexity architectural changes, not simple parameter tweaks. The cost to redesign for scalping exceeds the value.

5. **Better alternatives**: For 15-minute Kalshi crypto scalping, a purpose-built system with event-driven execution, low edge thresholds, and aggressive risk controls would be more appropriate.

**Alternative Path**:
- Keep the system for its intended purpose: swing trading on 15-minute markets with 2-12 minute holds
- Accept lower trade frequency but higher edge requirements
- Focus on improving edge quality rather than increasing turnover
- Consider building a separate scalping system if high-frequency trading is required

**Conclusion**: The system is well-designed for its intended purpose (swing trading) but fundamentally unsuitable for scalping. Do not use for 15-minute Kalshi crypto scalping without complete architectural redesign.
