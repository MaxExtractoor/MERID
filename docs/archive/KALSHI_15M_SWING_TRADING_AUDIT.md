# Kalshi 15-Minute Crypto Swing Trading Audit

**Date**: 2026-06-02  
**System**: MERID Agent Grid 15m (Kalshi Crypto 15m v2 Profile)  
**Assets**: BTC, ETH, SOL, XRP, DOGE  
**Target Use Case**: Swing trading on 15-minute Kalshi crypto markets (2-12 minute holds)

---

## 1. Executive Verdict

**CONDITIONAL GO** - System is well-designed for swing trading but requires critical missing features for production viability.

**Summary**: The system has solid infrastructure for swing trading (appropriate cycle cadence, conservative edge thresholds, good risk controls, and proper market data handling). However, it lacks critical exit management features (active TP/SL execution, position monitoring, dynamic exits) that are essential for swing trading profitability. The entry logic is sound, but the exit logic is incomplete.

**Critical Missing Features**:
1. **No active TP/SL execution**: TP/SL fields exist in OrderIntent but are not actively enforced
2. **No position monitoring system**: No real-time PnL tracking for open positions
3. **No exit signal generation**: No logic to exit positions based on market conditions
4. **No trailing stop functionality**: Cannot lock in profits as edge decays
5. **No hold time optimization**: Fixed 10-15 minute max hold regardless of market conditions

**Recommended Path**: Implement exit management system before live trading. Entry logic is production-ready, exit logic is not.

---

## 2. Strengths

### Entry Logic
- **Appropriate cycle cadence**: 15-minute cycles match 15-minute market duration
- **Conservative edge thresholds**: 3-5% edge requirements filter out noise
- **Tiered edge structure**: Watch/small/standard bands allow data collection while trading only clear mispricings
- **Priority queue scheduling**: Best-edge-first order selection maximizes edge quality
- **Market state validation**: Canonical pre-trade validator with lifecycle checks
- **Dual-sided edge calculation**: Accounts for spread cost and fees in edge computation

### Risk Controls
- **Drawdown-based risk scaling**: Adaptive risk bands reduce exposure as drawdown increases
- **Rolling PnL-based size reduction**: 1h/4h PnL triggers size reduction
- **Per-trade risk cap**: 0.8% per trade (survive 15-20 consecutive losses)
- **Regime cooldown**: Asset halting based on winrate and loss percentage
- **Per-asset notional caps**: BTC/ETH 1%, SOL/XRP/DOGE 0.5% limit concentration
- **Category exposure limits**: 30% total crypto exposure prevents over-concentration

### Market Data Handling
- **Real-time WebSocket integration**: KalshiMarketStateStore for live orderbook data
- **Freshness gates**: 120s MD staleness threshold prevents stale data trading
- **Liquidity diagnostics**: Per-asset depth tracking and one-sided rate monitoring
- **Series ticker extraction**: Correct 15M series ticker detection from market_id

### Execution Infrastructure
- **Resting order monitor**: Tracks GTC limit orders for fill management
- **IOC auto-conversion**: Automatically switches to IOC near expiry (120s)
- **Post-only support**: Can submit maker-only orders to avoid taker fees
- **Order intent tracking**: Unique client_tag for idempotency
- **Coherent risk contracts**: Window/exit policy framework for position management

### Configuration
- **Profile-driven risk**: Single source of truth in kalshi_crypto_15m.yaml
- **Asset tiering**: Tier 1 (BTC/ETH) vs Tier 2 (SOL/XRP/DOGE) with appropriate thresholds
- **Operation mode support**: Test vs prod modes with different daily loss limits
- **Experimental slices**: Price band and TTE band guards for hypothesis testing

---

## 3. Weaknesses

### Exit Management (CRITICAL)
- **No active TP/SL execution**: TP/SL fields in OrderIntent are not enforced by any system
- **No position monitoring**: No real-time PnL tracking for open positions
- **No exit signal generation**: No logic to exit based on market conditions
- **No trailing stop**: Cannot lock in profits as edge decays
- **No hold time optimization**: Fixed 10-15 minute max hold regardless of market conditions
- **No exit policy enforcement**: Window/exit policy framework exists but not actively used

### Signal Quality
- **Simple threshold-based signals**: Entry logic is basic (spot > threshold)
- **No RTI metrics**: No real-time indicators for signal quality
- **No volatility regime integration**: Signal doesn't adapt to volatility
- **No trend confirmation**: No momentum or trend filters
- **No mean reversion detection**: No logic to identify overextensions

### Position Sizing
- **Static Kelly multiplier**: 0.5x Kelly for standard band, not dynamic
- **No edge-to-size mapping**: Size doesn't scale with edge quality
- **No volatility adjustment**: Size doesn't account for current volatility
- **No correlation adjustment**: Size doesn't account for correlated positions

### Execution Quality
- **GTC default TIF**: Default GTC may not be optimal for swing trading
- **No partial fill handling**: No logic to manage partial fills
- **No order queue position tracking**: Cannot assess fill probability
- **No market impact modeling**: Doesn't account for slippage on larger orders

### Monitoring
- **No edge deterioration detection**: Cannot detect when edge degrades post-entry
- **No PnL attribution**: Cannot separate edge from execution costs
- **No fill rate monitoring**: Cannot track execution quality
- **No regime transition alerts**: No notification when volatility regime changes

### Backtesting
- **No intraday backtesting**: No evidence of testing on 15-minute data
- **No walk-forward validation**: No out-of-sample testing
- **No fill simulation**: Backtests likely assume perfect fills
- **No slippage modeling**: Doesn't account for realistic execution costs

---

## 4. Failure Points

### Point 1: No Active Exit Management (CRITICAL)
**Issue**: TP/SL fields exist in OrderIntent but are not enforced by any system.

**Evidence**:
- OrderIntent has `take_profit_price_cents`, `take_profit_r_multiple`, `stop_loss_price_cents` fields
- RestingOrderMonitor only tracks GTC orders, doesn't enforce TP/SL
- No position monitoring system to check PnL against TP/SL levels
- No exit signal generation logic
- Exit policy framework exists (window_resolution_id, exit_policy_id) but not actively used

**Impact**: Positions are held until expiry or manual cancellation. No profit-taking or loss-cutting mechanism. In swing trading, this leads to:
- Profits evaporating as edge decays
- Losses spiraling during adverse moves
- Inability to manage risk dynamically

**Failure Mode**: System enters good positions but fails to exit optimally, turning winning trades into losers or small winners.

### Point 2: No Position Monitoring (CRITICAL)
**Issue**: No real-time PnL tracking for open positions.

**Evidence**:
- No position monitoring system separate from RestingOrderMonitor
- RestingOrderMonitor only tracks order status, not PnL
- No real-time mark-to-market for open positions
- No PnL-based exit triggers

**Impact**: Cannot make informed exit decisions based on current PnL. System is blind to:
- Whether position is profitable or losing
- How much edge has decayed since entry
- Whether market conditions have changed

**Failure Mode**: System holds positions without awareness of current PnL, missing exit opportunities.

### Point 3: Simple Entry Signals (HIGH)
**Issue**: Entry logic is basic threshold-based, lacking sophistication.

**Evidence**:
- `_generate_signal` uses simple threshold: "If spot > 70000 (BTC), buy YES"
- No RTI metrics (momentum, volatility, regime)
- No trend confirmation or mean reversion detection
- No multi-factor signal generation
- Indicator stack exists but gates are temporarily bypassed

**Impact**: Entry quality is suboptimal. System may:
- Enter during unfavorable conditions (chop, low vol)
- Miss high-quality setups due to lack of filters
- Enter on false signals due to noise

**Failure Mode**: Low winrate due to poor entry quality, despite good edge thresholds.

### Point 4: No Hold Time Optimization (MEDIUM)
**Issue**: Fixed 10-15 minute max hold regardless of market conditions.

**Evidence**:
- `max_hold_seconds` hardcoded to 600-900 seconds
- No dynamic adjustment based on edge decay
- No adjustment based on volatility regime
- No adjustment based on time to expiry

**Impact**: Suboptimal hold times. System may:
- Hold too long in fast-moving markets (edge decays)
- Exit too early in slow-moving markets (miss profit)
- Hold through adverse moves when should exit

**Failure Mode**: Missed profit opportunities and unnecessary losses due to poor timing.

### Point 5: No Backtesting Evidence (HIGH)
**Issue**: No proof of edge on realistic intraday data.

**Evidence**:
- No backtest results in codebase or documentation
- No walk-forward validation methodology
- No fill simulation or slippage modeling
- No regime analysis or stress testing

**Impact**: System is theoretical - no evidence it would be profitable in live trading. Edge requirements may be based on incorrect assumptions.

**Failure Mode**: Live trading losses due to unvalidated assumptions, poor performance.

### Point 6: GTC Default TIF (MEDIUM)
**Issue**: Default GTC orders may not be optimal for swing trading.

**Evidence**:
- OrderIntent default `time_in_force = "gtc"`
- IOC auto-conversion only near expiry (120s)
- No option to force IOC for all orders

**Impact**: GTC orders can sit unfilled, tying up capital. In swing trading, you want:
- Immediate fills or no trade
- Capital efficiency
- Ability to re-enter if fill fails

**Failure Mode**: Capital tied up in unfilled orders, missed opportunities.

---

## 5. Required Fixes

### Fix 1: Implement Active Exit Management (CRITICAL)
**Change**: Build position monitoring system with active TP/SL enforcement.

**Implementation**:
- Create PositionMonitor class to track open positions
- Implement real-time PnL calculation using KalshiMarketStateStore
- Add TP/SL enforcement logic (submit exit orders when triggered)
- Implement trailing stop functionality (adjust SL as position becomes profitable)
- Add exit signal generation (exit when edge decays below threshold)
- Wire exit logic into RestingOrderMonitor or separate system

**Complexity**: High - requires new position monitoring infrastructure

### Fix 2: Implement Exit Policy Enforcement (CRITICAL)
**Change**: Actively use window/exit policy framework for position management.

**Implementation**:
- Implement WindowPolicyResolver to resolve window policies
- Implement ExitPolicyResolver to resolve exit policies
- Add policy-based exit triggers (time-based, PnL-based, edge-based)
- Wire policy enforcement into PositionMonitor
- Add policy override capability for manual intervention

**Complexity**: Medium - framework exists, needs implementation

### Fix 3: Enhance Entry Signals (HIGH)
**Change**: Improve signal quality with multi-factor entry logic.

**Implementation**:
- Re-enable indicator stack gates (remove TEMPORARY_BYPASS_INDICATOR_GATES)
- Add RTI metrics (momentum, volatility, regime)
- Implement trend confirmation (moving average crossovers, ADX)
- Add mean reversion detection (RSI, Bollinger Bands)
- Implement multi-factor signal scoring

**Complexity**: Medium - indicator stack exists, needs integration

### Fix 4: Implement Hold Time Optimization (MEDIUM)
**Change**: Dynamic hold time based on edge decay and market conditions.

**Implementation**:
- Add edge decay modeling (edge vs time to expiry)
- Implement dynamic max_hold calculation based on edge decay rate
- Add volatility regime adjustment (shorter holds in high vol)
- Add time-to-expiry adjustment (shorter holds near expiry)
- Wire into PositionMonitor exit logic

**Complexity**: Medium - requires edge decay modeling

### Fix 5: Conduct Intraday Backtesting (HIGH)
**Change**: Backtest on realistic 15-minute data with fill simulation.

**Implementation**:
- Collect historical 15-minute Kalshi crypto market data
- Implement backtest engine with fill simulation
- Add slippage modeling based on orderbook depth
- Conduct walk-forward validation across multiple periods
- Test across different volatility regimes
- Validate TP/SL logic effectiveness

**Complexity**: High - requires data collection and backtest infrastructure

### Fix 6: Force IOC for Entry Orders (MEDIUM)
**Change**: Default to IOC for entry orders to ensure fills.

**Implementation**:
- Change OrderIntent default `time_in_force` to "ioc" for entry orders
- Keep GTC for exit orders (to ensure fills)
- Add configuration option for TIF selection
- Implement unfilled order re-submission if needed

**Complexity**: Low - simple parameter change

### Fix 7: Add Position Sizing Optimization (MEDIUM)
**Change**: Dynamic sizing based on edge quality and volatility.

**Implementation**:
- Implement edge-to-size mapping (higher edge = larger size)
- Add volatility adjustment (lower size in high vol)
- Add correlation adjustment (reduce size for correlated positions)
- Implement Kelly fraction scaling based on confidence
- Wire into unified sizing logic

**Complexity**: Medium - requires sizing formula changes

---

## 6. Go / No-Go Recommendation

**Recommendation: CONDITIONAL GO**

**Rationale**:
1. **Entry logic is solid**: Appropriate cycle cadence, conservative edge thresholds, good risk controls
2. **Infrastructure is production-ready**: WebSocket integration, market state validation, resting order monitor
3. **Exit logic is incomplete**: No active TP/SL, no position monitoring, no exit signal generation
4. **Signal quality needs improvement**: Simple threshold-based signals lack sophistication
5. **No backtesting evidence**: No proof of edge on intraday data

**Conditions for Go**:
1. **Implement exit management** (Fix 1 and 2) - REQUIRED before live trading
2. **Enhance entry signals** (Fix 3) - RECOMMENDED for better winrate
3. **Conduct backtesting** (Fix 5) - REQUIRED to validate edge
4. **Optimize hold time** (Fix 4) - RECOMMENDED for better timing
5. **Force IOC for entries** (Fix 6) - OPTIONAL but recommended

**Estimated Timeline**:
- Exit management: 2-3 weeks (high complexity)
- Entry signal enhancement: 1-2 weeks (medium complexity)
- Backtesting: 2-3 weeks (high complexity)
- Hold time optimization: 1 week (medium complexity)
- **Total**: 6-9 weeks to production-ready

**Alternative Path**:
- Implement paper trading mode with current system
- Collect live data on entry quality without exit management
- Use manual exit decisions to validate entry logic
- Build exit management system based on live data insights

**Conclusion**: The system has a solid foundation for swing trading but requires critical exit management features before live trading. The entry logic and risk controls are production-ready, but the exit logic is incomplete. Implement exit management, enhance signals, and conduct backtesting before going live.

---

## 7. Implementation Priority

### P0 (Critical - Before Live Trading)
1. **Exit Management System** (Fix 1): PositionMonitor, TP/SL enforcement, trailing stops
2. **Exit Policy Enforcement** (Fix 2): Window/exit policy resolver, policy-based exits
3. **Backtesting** (Fix 5): Validate edge on historical data with fill simulation

### P1 (High - Recommended)
4. **Entry Signal Enhancement** (Fix 3): Re-enable indicator gates, add RTI metrics
5. **Hold Time Optimization** (Fix 4): Dynamic hold time based on edge decay

### P2 (Medium - Nice to Have)
6. **IOC for Entries** (Fix 6): Ensure fills on entry orders
7. **Position Sizing Optimization** (Fix 7): Dynamic sizing based on edge/vol

### P3 (Low - Future Enhancements)
8. **Correlation Guards**: Prevent correlated position accumulation
9. **Regime Transition Alerts**: Notify when volatility regime changes
10. **PnL Attribution**: Separate edge from execution costs
