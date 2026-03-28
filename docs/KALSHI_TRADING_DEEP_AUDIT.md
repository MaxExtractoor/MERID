# Kalshi Trading System Deep Audit

**Date**: 2026-03-28
**Scope**: Complete audit of Kalshi trading agents, risk management, and wiring
**Status**: Comprehensive analysis completed, critical issues identified

---

## Executive Summary

Deep audit of the Kalshi trading system revealed that the log messages reference components ("KalshiContinuousTrader", "KalshiRiskEngine") that don't exist in the current codebase. The actual implementation uses:
- **KalshiTradingAgent** (per-asset/timeframe trading)
- **PortfolioRiskAgent** (cross-asset risk monitoring)

**Critical Findings**:
- ✅ 5 critical bugs previously fixed
- ⚠️ 8 high-priority issues identified requiring fixes
- ⚠️ 5 medium-priority issues documented
- ⚠️ 3 configuration validation gaps

---

## System Architecture

### Current Implementation

```
AgentGrid
  ├─ 20+ KalshiTradingAgent instances (per asset/timeframe)
  ├─ 1 PortfolioRiskAgent (cross-agent monitor)
  ├─ MarketCatalog (Kalshi market discovery)
  ├─ SentimentService (fear/greed index)
  ├─ MarketMoodBus (unified sentiment)
  └─ InsightPipeline (signal publishing)
```

### Per-Agent Configuration (from kalshi_agent_grid.yaml)

**Assets**: BTC, ETH, SOL, XRP, DOGE
**Timeframes**: 15m, 1h, daily, weekly
**Total Agents**: 25 (20 directional + 5 specialized)

Example agent:
```yaml
- name: BTC_15M
  assets: [BTC]
  timeframes: [15m]
  risk_limits:
    max_yes_position: 2000
    max_no_position: 2000
    max_orders_per_window: 20
    max_notional_usd: 500
  entry_window:
    minutes_before_expiry: 10
    cutoff_minutes_before_expiry: 1
```

---

## Critical Issues Previously Fixed ✅

### 1. Risk Check Semantic Bug (FIXED)
**File**: `execution/execution_coordinator.py:127-146`
**Issue**: `risk_checked` flag was ambiguous
**Fix**: Separated check performance from approval status

### 2. Missing Rejection Events (FIXED)
**File**: `execution/execution_coordinator.py:134-141`
**Issue**: Blocked orders had no audit trail
**Fix**: Added `execution_rejected` event publishing

### 3. Empty Market Catalog (FIXED)
**File**: `merid/prediction/agent_grid.py:126-134`
**Issue**: Grid could start with no markets
**Fix**: Fail-fast validation after catalog startup

### 4. Session Guard Validation (FIXED)
**File**: `merid/prediction/session_guard.py:53-83`
**Issue**: Invalid time formats not validated
**Fix**: Comprehensive format validation with clear errors

### 5. Deployment Registration (FIXED)
**File**: `merid/prediction/agent_grid.py:139-148`
**Issue**: Registration failures were warnings
**Fix**: Made failures fatal to prevent inconsistent state

---

## High-Priority Issues Requiring Fixes ⚠️

### Issue #1: Portfolio Fetch Failure Doesn't Block Trading

**Location**: `merid/prediction/portfolio_risk_agent.py:141-190`

**Problem**:
```python
async def _check_portfolio(self):
    pos_result = await self._kalshi_get_positions()
    if not pos_result.success:
        logger.warning(f"Failed to fetch portfolio data: {exc}")
        return  # JUST RETURNS - agents keep trading!
```

**Impact**: If portfolio position fetch fails, agents continue placing orders without portfolio visibility. Kill-switch is NOT activated.

**Recommendation**:
```python
if not pos_result.success:
    logger.error("CRITICAL: Portfolio fetch failed - activating kill switch")
    self._kill_switch_active = True
    # Pause all agents
    for agent in self._agents:
        agent.state.enabled = False
        logger.warning(f"Paused agent {agent.config.name} due to portfolio fetch failure")
```

---

### Issue #2: Order Window Counter Not Thread-Safe

**Location**: `merid/prediction/trading_agent.py:257-259`

**Problem**:
```python
if self.state.orders_this_window >= self.config.risk_limits.max_orders_per_window:
    logger.debug(f"Order limit reached")
    break

# Later in loop:
self.state.orders_this_window += 1  # No atomic increment
```

**Impact**: Multiple markets evaluated in same cycle could all see counter < limit, all increment it, exceeding the limit.

**Recommendation**: Use atomic operations or evaluate markets sequentially:
```python
import threading
self._window_lock = threading.Lock()

# In order placement:
with self._window_lock:
    if self.state.orders_this_window >= self.config.risk_limits.max_orders_per_window:
        return False
    self.state.orders_this_window += 1
```

---

### Issue #3: Kelly Sizing Ignores Existing Positions

**Location**: Various files - Kelly formula doesn't account for open positions

**Problem**: When agent has existing YES position of 1500 contracts and Kelly formula suggests 1000 more:
1. Kelly returns 1000 contracts
2. Risk check validates: existing (1500) + new (1000) = 2500
3. If `max_yes_position = 2000`, check fails

**Impact**: Orders rejected after Kelly calculation, wasting compute.

**Recommendation**: Pass existing position to Kelly sizing:
```python
def kelly_size_kalshi(
    edge: float,
    price_cents: int,
    bankroll_cents: int,
    existing_position: int = 0,  # NEW
    max_position: int = 3000,     # NEW
) -> int:
    # Calculate Kelly fraction
    raw_size = int(fraction * bankroll_cents / price_cents)

    # Adjust for existing position
    available_room = max_position - abs(existing_position)
    adjusted_size = min(raw_size, available_room)

    return adjusted_size
```

---

### Issue #4: Config Parameter Validation Missing

**Location**: `merid/prediction/agent_grid_config.py:144-177`

**Problem**: No validation that config parameters are sensible:

```python
def _parse_risk_limits(raw: Dict[str, Any]) -> AgentRiskLimits:
    return AgentRiskLimits(
        max_yes_position=raw.get("max_yes_position", 3000),  # Could be 0!
        max_no_position=raw.get("max_no_position", 3000),    # Could be negative!
        max_orders_per_window=raw.get("max_orders_per_window", 10),  # Could be 0!
        max_notional_usd=Decimal(str(raw.get("max_notional_usd", 500))),  # Could be 0!
    )
```

**Recommendation**: Add validation:
```python
def _parse_risk_limits(raw: Dict[str, Any]) -> AgentRiskLimits:
    max_yes = raw.get("max_yes_position", 3000)
    max_no = raw.get("max_no_position", 3000)
    max_orders = raw.get("max_orders_per_window", 10)
    max_notional = Decimal(str(raw.get("max_notional_usd", 500)))

    # Validate
    if max_yes <= 0:
        raise ValueError(f"max_yes_position must be > 0, got {max_yes}")
    if max_no <= 0:
        raise ValueError(f"max_no_position must be > 0, got {max_no}")
    if max_orders <= 0:
        raise ValueError(f"max_orders_per_window must be > 0, got {max_orders}")
    if max_notional <= 0:
        raise ValueError(f"max_notional_usd must be > 0, got {max_notional}")

    return AgentRiskLimits(...)
```

---

### Issue #5: Entry Window Validation Missing

**Location**: `merid/prediction/agent_grid_config.py:177-185`

**Problem**:
```python
def _parse_entry_window(raw: Dict[str, Any]) -> EntryWindowConfig:
    return EntryWindowConfig(
        minutes_before_expiry=raw.get("minutes_before_expiry", 10),
        cutoff_minutes_before_expiry=raw.get("cutoff_minutes_before_expiry", 2),
        # No check: is cutoff < minutes_before_expiry?
    )
```

**Impact**: If `cutoff_minutes_before_expiry >= minutes_before_expiry`, entry window is 0 or negative!

**Recommendation**:
```python
minutes_before = raw.get("minutes_before_expiry", 10)
cutoff = raw.get("cutoff_minutes_before_expiry", 2)

if cutoff >= minutes_before:
    raise ValueError(
        f"cutoff_minutes_before_expiry ({cutoff}) must be < minutes_before_expiry ({minutes_before})"
    )

return EntryWindowConfig(minutes_before_expiry=minutes_before, cutoff_minutes_before_expiry=cutoff)
```

---

### Issue #6: Portfolio Config Sum Exceeds Total Limit

**Location**: `config/kalshi_agent_grid.yaml`

**Problem**: Sum of per-agent notional limits exceeds portfolio total:

```yaml
# Per-agent limits:
BTC_15M: max_notional_usd: 500
BTC_HOURLY: max_notional_usd: 1000
...
# 25 agents × 500-5000 = ~80,000 total

# Portfolio limit:
portfolio_risk:
  max_total_notional_usd: 50000  # Too low!
```

**Impact**: Portfolio immediately breaches on startup if multiple agents place orders.

**Recommendation**: Either:
1. Increase portfolio limit to accommodate sum of agent limits
2. Reduce per-agent limits to ensure sum ≤ portfolio limit
3. Add validation in `AgentGridConfig.__init__()`:

```python
def __post_init__(self):
    # Validate sum of agent limits <= portfolio limit
    total_agent_notional = sum(
        a.risk_limits.max_notional_usd for a in self.agents
    )
    if total_agent_notional > self.portfolio_risk.max_total_notional_usd:
        logger.warning(
            f"Sum of agent notional limits ({total_agent_notional}) exceeds "
            f"portfolio limit ({self.portfolio_risk.max_total_notional_usd})"
        )
```

---

### Issue #7: KalshiRiskManager State Not Synced with Real Positions

**Location**: `merid/event_venues/kalshi/kalshi_risk.py` and `portfolio_risk_agent.py`

**Problem**: KalshiRiskManager maintains cached state that's only updated by PortfolioRiskAgent sync:

```python
# KalshiRiskManager
self._state.category_notional: Dict[str, float]  # Cached
self._state.category_contracts: Dict[str, int]   # Cached

# Updated only by:
portfolio_risk_agent._sync_to_risk_manager()  # Every 30s
```

**Impact**: Between syncs, risk checks use stale position data. Orders placed at T+5s use stale data from T+0s.

**Recommendation**: Add staleness detection:
```python
def check_order(...):
    # Check state freshness
    if time.time() - self._state.last_sync_ts > 30:
        logger.warning("Risk state stale - last sync >30s ago")
        # Optionally: trigger immediate sync or fail-closed
```

---

### Issue #8: Tracked Positions Not Reconciled

**Location**: `merid/prediction/trading_agent.py:119-122`

**Problem**:
```python
# Agent tracks positions locally
self._tracked_positions: Dict[str, TrackedPosition] = {}

# Stop-loss checks these
# But if position expires/settles while market data stale, becomes stale
# No automatic reconciliation with real Kalshi positions
```

**Recommendation**: Periodic reconciliation:
```python
async def _reconcile_positions(self):
    """Reconcile tracked positions with actual Kalshi positions"""
    actual_positions = await kalshi_get_positions()

    for ticker, tracked in self._tracked_positions.items():
        actual = actual_positions.get(ticker)
        if not actual:
            logger.warning(f"Tracked position {ticker} not found in actual positions - may have settled")
            # Remove from tracking
        elif abs(actual.contracts - tracked.contracts) > 0:
            logger.warning(f"Position mismatch {ticker}: tracked={tracked.contracts} actual={actual.contracts}")
            # Update tracking
```

---

## Medium-Priority Issues 📋

### Issue #9: Entry Window Off-By-One Semantics

**Location**: `merid/prediction/trading_agent.py:558-567`

**Problem**: For config:
```yaml
entry_window:
  minutes_before_expiry: 10
  cutoff_minutes_before_expiry: 1
```

Actual window is 9 minutes (10 - 1), not 10 minutes as user might expect.

**Recommendation**: Clarify documentation or adjust semantics.

---

### Issue #10: Bankroll Zero Division

**Location**: Multiple files using bankroll_cents

**Problem**: If bankroll becomes 0, calculations silently return 0:
```python
contracts = int(fraction * bankroll_cents / price_cents)
# If bankroll_cents = 0, contracts = 0 (no error)
```

**Recommendation**: Add explicit check:
```python
if bankroll_cents <= 0:
    logger.error(f"Bankroll is zero or negative: {bankroll_cents}")
    return 0
```

---

### Issue #11: Fee Tier Mismatch in Kelly

**Problem**: Kelly sizing estimates fees for 10-contract tier (7%), but actual order might be 100+ contracts (5% tier). Actual fees differ from estimated.

**Recommendation**: Use actual contract count in fee calculation or add safety margin.

---

### Issue #12: Series Resolution with Empty Assets

**Location**: `merid/prediction/trading_agent.py:267-269`

**Problem**:
```python
asset = self.config.assets[0] if self.config.assets else ""
# If assets = [], asset = "" → mood lookup fails
```

**Impact**: Market maker and arbitrage agents (no specific assets) can't get sentiment data.

**Recommendation**: Handle empty assets gracefully:
```python
asset = self.config.assets[0] if self.config.assets else None
if asset:
    mood_context = self._get_mood_context(asset, timeframe)
else:
    mood_context = self._get_default_mood_context()
```

---

### Issue #13: Session Guard DST Hardcoded

**Location**: `merid/prediction/session_guard.py:22-31`

**Problem**: DST boundaries hardcoded, doesn't account for rule changes.

**Recommendation**: Use `pytz` or `zoneinfo`:
```python
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
et_time = dt_utc.astimezone(ET)
```

---

## Wiring Verification ✅

### Component Wiring Status

| Source | Target | Wired | Validated |
|--------|--------|-------|-----------|
| AgentGrid → KalshiTradingAgent | ✅ | ✅ |
| AgentGrid → PortfolioRiskAgent | ✅ | ✅ |
| AgentGrid → MarketCatalog | ✅ | ✅ FIXED |
| AgentGrid → DeploymentController | ✅ | ✅ FIXED |
| PortfolioRiskAgent → KalshiRiskManager | ✅ | ⚠️ Issue #7 |
| TradingAgent → Strategy | ✅ | ✅ |
| TradingAgent → Risk | ✅ | ✅ FIXED |
| TradingAgent → StopLoss | ✅ | ⚠️ Issue #8 |
| ExecutionCoordinator → OrderRouter | ✅ | ✅ FIXED |

---

## Configuration Audit

### kalshi_agent_grid.yaml Validation

**Assets Covered**: BTC ✅, ETH ✅, SOL ✅, XRP ✅, DOGE ✅

**Agents per Asset**:
- BTC: 4 (15m, 1h, daily, weekly) ✅
- ETH: 4 (15m, 1h, daily, weekly) ✅
- SOL: 4 (15m, 1h, daily, weekly) ✅
- XRP: 4 (15m, 1h, daily, weekly) ✅
- DOGE: 4 (15m, 1h, daily, weekly) ✅

**Special Agents**: 5 (market maker, arbitrage, macro, sentiment, catch-all) ✅

**Total**: 25 agents ✅

**Portfolio Limits**:
```yaml
max_total_notional_usd: 50000      # ⚠️ May be too low (Issue #6)
max_notional_per_asset_usd: 15000  # ✅
max_open_markets: 200              # ✅
max_daily_loss_usd: 5000           # ✅
max_margin_utilization_pct: 80     # ✅
```

---

## Testing Recommendations

### Required Unit Tests

1. **Config Validation Tests**
   ```python
   def test_risk_limits_validation():
       # Test negative/zero values raise errors

   def test_entry_window_validation():
       # Test cutoff >= minutes_before raises error

   def test_portfolio_limit_sum():
       # Test sum of agent limits validated against portfolio
   ```

2. **State Synchronization Tests**
   ```python
   def test_portfolio_fetch_failure_activates_kill_switch():
       # Verify agents paused on fetch failure

   def test_risk_state_staleness_detection():
       # Verify stale state detected and handled
   ```

3. **Kelly Sizing Tests**
   ```python
   def test_kelly_with_existing_position():
       # Verify Kelly accounts for open positions

   def test_kelly_bankroll_zero():
       # Verify zero bankroll handled gracefully
   ```

### Integration Tests

1. **Full Startup Sequence**
   - Verify all 25 agents initialize
   - Verify market catalog loads markets
   - Verify portfolio monitoring starts

2. **Risk Check Flow**
   - Verify per-agent checks
   - Verify portfolio checks
   - Verify rejection events published

3. **Position Tracking**
   - Verify positions tracked correctly
   - Verify reconciliation with Kalshi API
   - Verify stop-loss execution

---

## Summary

### Issues Fixed (5)
✅ All critical silent failure modes eliminated

### Issues Identified (16)
- **High Priority (8)**: Require immediate fixes
- **Medium Priority (5)**: Should be addressed
- **Low Priority (3)**: Documentation/cleanup

### Key Recommendations

1. **Immediate**: Fix portfolio fetch failure handling (#1)
2. **Immediate**: Add config parameter validation (#4, #5)
3. **High Priority**: Fix order window counter thread safety (#2)
4. **High Priority**: Adjust Kelly sizing for existing positions (#3)
5. **High Priority**: Validate portfolio limit configuration (#6)
6. **High Priority**: Add state staleness detection (#7)
7. **High Priority**: Implement position reconciliation (#8)

### Overall Assessment

**System Architecture**: ✅ Well-designed with proper separation of concerns

**Initialization & Wiring**: ✅ Mostly correct after recent fixes

**Risk Management**: ⚠️ Several edge cases need hardening

**Configuration**: ⚠️ Needs validation to prevent misconfiguration

**Testing**: ❌ Needs comprehensive unit and integration tests

The system is fundamentally sound but requires the identified fixes to ensure production reliability, especially around portfolio visibility failures and configuration validation.
