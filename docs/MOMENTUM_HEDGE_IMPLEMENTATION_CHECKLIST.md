# Implementation Checklist
## Momentum Scalping + Hedging System — Action Items

**Priority:** PRODUCTION BLOCKER  
**Target Completion:** 4 weeks  
**Dependencies:** Kalshi API access, test environment with paper trading

---

## Phase 1: Critical Fixes (Week 1)
**Goal:** Make hedging functional and define clear system states

### P1.1 — Wire Hedge Engine into CT Cycle
- [ ] Add import: `from merid.hedging.engine import get_hedge_engine`
- [ ] Add to CT `__init__`: `self._hedge_engine = get_hedge_engine()`
- [ ] Add to `_run_cycle()` after sizing, before execution:
  ```python
  hedge_result = self._hedge_engine.compute_hedge_orders(
      exposure=self._exposure_snapshot,
      config=self._hedge_config,
      bankroll_cents=self._bankroll.balance_cents,
      market_catalog=self._catalog,
  )
  for h_order in hedge_result.orders:
      intent = self._hedge_order_to_intent(h_order)
      await self._route_with_tag(intent, source="HEDGE_ENGINE")
  ```
- [ ] Add helper: `_hedge_order_to_intent()` for conversion
- [ ] Add exposure snapshot update after fills
- [ ] **Test:** Unit test with mock exposure, verify hedge orders generated

**Files:** `merid/trading/kalshi_continuous_trader.py`  
**Estimated Hours:** 4  
**Risk:** Medium — affects core trading loop

---

### P1.2 — Implement State Machine in CT
- [ ] Create enum in new file: `merid/trading/trading_state.py`
  ```python
  class TradingState(Enum):
      SCALP_ONLY = "scalp_only"
      SCALP_HEDGE = "scalp_hedge"
      HEDGE_ONLY = "hedge_only"
      FLAT = "flat"
  ```
- [ ] Add state attribute to CT: `self._state: TradingState`
- [ ] Add transition logic:
  ```python
  def _evaluate_state_transition(self) -> TradingState:
      current = self._state
      dd = self._current_drawdown_pct
      
      if current == TradingState.SCALP_ONLY:
          if dd >= 0.05:  # 5%
              return TradingState.SCALP_HEDGE
          elif dd >= 0.10:  # 10%
              return TradingState.HEDGE_ONLY
      
      elif current == TradingState.SCALP_HEDGE:
          if dd >= 0.10:
              return TradingState.HEDGE_ONLY
          elif dd < 0.03 and self._time_in_state > 900:  # 15 min
              return TradingState.SCALP_ONLY
      
      elif current == TradingState.HEDGE_ONLY:
          if dd < 0.05 and self._time_in_state > 1800:  # 30 min
              return TradingState.SCALP_HEDGE
          elif self._all_positions_closed():
              return TradingState.FLAT
      
      return current  # No change
  ```
- [ ] Add state to status output: `_status_snapshot_inner()`
- [ ] Add state transition logging with reason codes
- [ ] Add hysteresis tracking: `_state_entry_time`, `_time_in_state`
- [ ] **Test:** All state transitions, verify hysteresis enforced

**Files:** `merid/trading/trading_state.py` (new), `merid/trading/kalshi_continuous_trader.py`  
**Estimated Hours:** 8  
**Risk:** High — changes core control flow

---

### P1.3 — Unify Drawdown Thresholds
- [ ] Create unified config: `merid/risk/drawdown_config.py`
  ```python
  @dataclass
  class UnifiedDrawdownConfig:
      warning_pct: float = 0.03        # 3%
      hedge_active_pct: float = 0.05   # 5%
      scalp_halt_pct: float = 0.10    # 10%
      full_halt_pct: float = 0.15     # 15%
  ```
- [ ] Update `KalshiRiskConfig` to reference unified config
- [ ] Update `CycleDrawdownConfig` to reference unified config
- [ ] Remove `HedgeConfig.max_drawdown_pct` (unused 40%)
- [ ] Update all threshold comparisons to use unified values
- [ ] Add validation: thresholds must be ascending
- [ ] **Test:** Simulate drawdown scenarios, verify correct triggers

**Files:** `merid/risk/drawdown_config.py` (new), `merid/prediction/risk/kalshi_risk_engine.py`, `merid/event_venues/kalshi/cycle_drawdown.py`, `merid/hedging/config.py`  
**Estimated Hours:** 6  
**Risk:** Medium — affects all risk systems

---

## Phase 2: Signal Enhancement (Week 2)
**Goal:** Optimize per-asset performance

### P2.1 — Asset-Specific Indicator Configs
- [ ] Create: `merid/signals/asset_configs.py`
  ```python
  ASSET_CONFIGS = {
      "BTC": AssetIndicatorConfig(
          ema_trend=50, ema_fast=5, ema_slow=20, rsi=8,
          atr_stop_mult=1.5, min_edge=0.015, chop_atr_min=0.0003
      ),
      "ETH": AssetIndicatorConfig(
          ema_trend=45, ema_fast=5, ema_slow=18, rsi=8,
          atr_stop_mult=1.6, min_edge=0.016, chop_atr_min=0.00035
      ),
      "SOL": AssetIndicatorConfig(
          ema_trend=35, ema_fast=4, ema_slow=15, rsi=6,
          atr_stop_mult=2.0, min_edge=0.020, chop_atr_min=0.0005
      ),
      "XRP": AssetIndicatorConfig(
          ema_trend=40, ema_fast=5, ema_slow=16, rsi=7,
          atr_stop_mult=1.8, min_edge=0.018, chop_atr_min=0.0004
      ),
      "DOGE": AssetIndicatorConfig(
          ema_trend=30, ema_fast=3, ema_slow=12, rsi=5,
          atr_stop_mult=2.5, min_edge=0.025, chop_atr_min=0.0006
      ),
  }
  ```
- [ ] Refactor `Crypto15mIndicatorStack` to accept asset symbol
- [ ] Replace hardcoded parameters with asset-specific lookups
- [ ] Update all indicator calculations to use config values
- [ ] Add config validation (periods must be positive, etc.)
- [ ] **Test:** Verify each asset uses correct parameters

**Files:** `merid/signals/asset_configs.py` (new), `merid/signals/crypto_15m_indicators.py`  
**Estimated Hours:** 8  
**Risk:** Medium — requires re-tuning via backtest

---

### P2.2 — Cross-Asset Beta Integration
- [ ] Add import to topn_allocator: `from merid.signals.btc_anchored_move import get_beta_model`
- [ ] Modify `EdgeCandidate.compute_contracts_for_risk_budget()`:
  ```python
  def compute_contracts_for_risk_budget(self, risk_budget_cents: int) -> int:
      max_loss = self.compute_max_loss_per_contract()
      if max_loss == 0:
          return 0
      
      # Beta normalization for high-beta assets
      beta = get_beta_model().get_beta(self.asset, "15m")
      adjusted_budget = risk_budget_cents / beta
      
      return int(adjusted_budget / max_loss)
  ```
- [ ] Add beta to `EdgeCandidate` dataclass for transparency
- [ ] Update allocator logging to show pre/post-beta sizing
- [ ] **Test:** Verify SOL positions sized ~25% smaller than BTC for same edge

**Files:** `merid/trading/topn_allocator.py`  
**Estimated Hours:** 4  
**Risk:** Low — sizing change only

---

### P2.3 — FVG-Based Entry Refinement
- [ ] Add to `IndicatorSnapshot`: `fvg_levels: List[FVGLevel]`
- [ ] Add FVG entry condition in strategy:
  ```python
  def evaluate_fvg_entry(self, snapshot, side):
      for fvg in snapshot.fvg_levels:
          if fvg.is_active and fvg.age_bars < 20:
              if side == "long" and price_near(fvg.bottom):
                  return True, fvg.bottom  # Stop below FVG
              elif side == "short" and price_near(fvg.top):
                  return True, fvg.top
      return False, None
  ```
- [ ] Add FVG-aware stop placement:
  ```python
  if fvg_stop_level:
      stop_price = fvg_stop_level - atr_buffer  # Long case
  else:
      stop_price = entry - (atr * atr_mult)
  ```
- [ ] Add config flag: `use_fvg_entries: bool = True`
- [ ] **Test:** Backtest FVG entry variant vs. base strategy

**Files:** `merid/signals/crypto_15m_indicators.py`, `merid/prediction/strategy.py`  
**Estimated Hours:** 6  
**Risk:** Low — additive feature

---

## Phase 3: Kalshi Integration (Week 3)
**Goal:** Functional hedge execution

### P3.1 — Market Selector for Hedging
- [ ] Implement `merid/hedging/market_selector.py`:
  ```python
  def select_hedge_market(asset, timeframe, catalog, preference):
      # 1. Try same-asset, same-timeframe
      primary = catalog.find(f"KX{asset}-{timeframe}")
      if primary and primary.liquidity_ok:
          return primary
      
      # 2. Try adjacent timeframe
      for adj_timeframe in get_adjacent(timeframe):
          alt = catalog.find(f"KX{asset}-{adj_timeframe}")
          if alt and alt.liquidity_ok:
              return alt
      
      # 3. Try BTC proxy for alts (beta-adjusted)
      if asset != "BTC":
          beta = get_beta(asset, timeframe)
          proxy = catalog.find(f"KXBTC-{timeframe}")
          if proxy:
              return ProxyMarket(proxy, beta_adjust=beta)
      
      return None
  ```
- [ ] Integrate into `CryptoHedgeEngine._resolve_mid_price()`
- [ ] Add liquidity checks (min depth, max spread)
- [ ] **Test:** Verify correct market selection for all asset/tf combinations

**Files:** `merid/hedging/market_selector.py` (new), `merid/hedging/engine.py`  
**Estimated Hours:** 6  
**Risk:** Medium — affects hedge pricing

---

### P3.2 — Hedge Execution via Order Router
- [ ] Ensure hedge orders use proper tags:
  ```python
  intent = OrderIntent(
      ticker=hedge_order.target_ticker,
      side=hedge_order.side,
      count=hedge_order.count,
      price_cents=hedge_order.price_cents,
      source="HEDGE_ENGINE",
      agent_id="hedge_engine",
      strategy_group="hedge",  # Prevents lease collision
      client_tag=f"HEDGE_{hedge_order.hedge_reason}_{uuid4()[:8]}",
  )
  ```
- [ ] Update `order_router.py` to allow hedge orders through certain gates
- [ ] Add hedge-specific PnL tracking (separate from alpha)
- [ ] Add hedge fill callbacks to update exposure snapshot
- [ ] **Test:** End-to-end hedge order routing, verify fills tracked

**Files:** `merid/event_venues/kalshi/order_router.py`, `merid/hedging/exposure.py`  
**Estimated Hours:** 6  
**Risk:** Medium — execution path changes

---

### P3.3 — Fee-Aware Hedge Sizing
- [ ] Add fee calculation to hedge sizing:
  ```python
  def should_hedge_position(position, hedge_cost, expected_protection):
      # Expected protection value = position_delta * probability_of_adverse_move
      protection_value = estimate_protection_value(position)
      
      # Hedge is worthwhile if protection > 2x cost
      return protection_value > (hedge_cost * 2)
  ```
- [ ] Add minimum hedge threshold: skip if exposure < $5
- [ ] Add dynamic hedge ratio based on market implied costs
- [ ] **Test:** Verify small positions not hedged, large positions fully hedged

**Files:** `merid/hedging/engine.py`  
**Estimated Hours:** 4  
**Risk:** Low — sizing refinement

---

## Phase 4: Testing & Monitoring (Week 4)
**Goal:** Validation and observability

### P4.1 — State Machine Unit Tests
- [ ] Create: `tests/test_trading_state_machine.py`
- [ ] Test all 12 possible state transitions
- [ ] Test hysteresis (time-based delays)
- [ ] Test edge cases (rapid DD oscillation)
- [ ] Test manual override functionality
- [ ] **Pass Criteria:** All transitions behave as specified

**Files:** `tests/test_trading_state_machine.py` (new)  
**Estimated Hours:** 6  
**Risk:** Low — test code only

---

### P4.2 — Hedge Effectiveness Backtests
- [ ] Create: `tests/backtest_hedge_effectiveness.py`
- [ ] Simulate 3 historical drawdown periods:
  - May 2024: BTC flash crash
  - March 2024: Altcoin correlation breakdown
  - January 2025: Range-bound chop
- [ ] Measure:
  - Max drawdown with/without hedging
  - Total hedge cost (fees paid)
  - Net benefit: drawdown reduction - hedge cost
- [ ] Optimize hedge ratio per asset based on results
- [ ] **Pass Criteria:** Hedging reduces max DD by at least 20% net of costs

**Files:** `tests/backtest_hedge_effectiveness.py` (new)  
**Estimated Hours:** 8  
**Risk:** Low — offline analysis

---

### P4.3 — Monitoring Dashboard Updates
- [ ] Add current state indicator to API:
  ```python
  # In kalshi_continuous_trader.py status
  "trading_state": self._state.value,
  "state_time_elapsed": self._time_in_state,
  "state_entry_reason": self._last_transition_reason,
  ```
- [ ] Add exposure breakdown:
  ```python
  "exposure": {
      "alpha_delta_cents": self._alpha_exposure.total_delta(),
      "hedge_delta_cents": self._hedge_exposure.total_delta(),
      "net_delta_cents": self._net_exposure.total_delta(),
      "net_beta": self._net_exposure.beta_weighted(),
  }
  ```
- [ ] Add hedge effectiveness metrics:
  ```python
  "hedge_metrics": {
      "total_hedge_cost_cents": self._hedge_cost_tracker.total(),
      "active_hedge_positions": len(self._hedge_positions),
      "hedge_coverage_ratio": self._hedge_coverage_ratio(),
  }
  ```
- [ ] Update frontend to display new fields
- [ ] **Test:** Verify all new fields populated correctly

**Files:** `merid/trading/kalshi_continuous_trader.py`, `web/api/...`, frontend components  
**Estimated Hours:** 8  
**Risk:** Low — additive monitoring

---

## Summary

| Phase | Items | Est. Hours | Risk |
|-------|-------|------------|------|
| 1: Critical | 3 | 18 | High |
| 2: Signals | 3 | 18 | Medium |
| 3: Kalshi | 3 | 16 | Medium |
| 4: Testing | 3 | 22 | Low |
| **Total** | **12** | **74** | **High** |

**Critical Path:** P1.1 → P1.2 → P1.3 → P3.2 (must be sequential)  
**Parallel Work:** P2.x can proceed alongside P1.x, P3.x after P1 complete  
**Review Points:** End of each phase, require sign-off before proceeding

---

## Rollback Plan

If issues discovered in Phase 1:
1. Keep existing CT logic as `kalshi_continuous_trader_legacy.py`
2. Feature flag: `USE_STATE_MACHINE=false` (default to legacy)
3. Gradual rollout: 10% → 50% → 100% of paper sessions
4. Automatic rollback if error rate > 0.1% or PnL divergence > 5%

---

**End of Implementation Checklist**
