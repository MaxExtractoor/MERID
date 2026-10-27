# Kalshi 15m Integration Second-Pass Audit: Duplicate & Synthetic Logic

**Date:** 2026-05-13  
**Scope:** MERID ↔ Kalshi 15m crypto integration for BTC/ETH/SOL/XRP/DOGE  
**Profile:** `kalshi_crypto_15m_v2`  
**Focus:** Duplicate logic and synthetic/unused implementations

---

## Executive Summary

This second-pass audit identifies **duplicate logic** (near-clones, copy-pasted pipelines, diverged forks) and **synthetic logic** (unused shadow implementations, experimental branches, non-production paths) across the Kalshi 15m stack.

**Critical Finding:** The system has **TWO parallel trading engines** that can both execute Kalshi orders:
- `KalshiTradingAgent` (AgentGrid PM) - **PRODUCTION** path for `kalshi_crypto_15m_v2`
- `KalshiContinuousTrader` (legacy runner) - **SUPPRESSED** but still code-complete

While `KalshiContinuousTrader` is gated by `pm_ct_policy.ct_legacy_must_not_trade()`, the existence of two complete trading engines with duplicate implementations of sizing, risk checks, and order routing represents a **P0 structural risk**.

**Overall Risk Assessment:**
- **P0 Issues:** 1 (dual trading engines with overlapping capabilities)
- **P1 Issues:** 4 (bankroll services, risk classes, order managers, reconciliation)
- **P2 Issues:** 6 (strategy-specific logic, UI-only paths, deprecated code)

---

## 1. Duplicate & Synthetic Logic Map

### 1.1 Entry-Point to Venue Mapping

| Concern | Implementations | Canonical | Production-Reachable | Type | Risk |
|---------|----------------|-----------|----------------------|------|------|
| **Order Routing** | `order_router.route_order_async()` | `route_order_async()` | YES (KalshiTradingAgent) | N/A | N/A |
| | `kalshi_tools._kalshi_place_order()` | `route_order_async()` | YES (LLM tools) | Duplicate-near | P1 |
| | `client.place_order()` | `route_order_async()` | NO (internal only) | Synthetic-dead | P2 |
| **Trading Engine** | `KalshiTradingAgent` (AgentGrid PM) | `KalshiTradingAgent` | YES | N/A | N/A |
| | `KalshiContinuousTrader` | `KalshiTradingAgent` | GATED | Synthetic-shadow | **P0** |
| **Order Intent Creation** | `trading_agent._execute_signal_body()` | `trading_agent` | YES | N/A | N/A |
| | `ct_execution_adapter.convert_to_intent()` | `trading_agent` | GATED | Duplicate-near | P1 |
| | `kalshi_tools.build_live_route_order_intent()` | `trading_agent` | YES (LLM tools) | Duplicate-near | P1 |

**Analysis:**
- **P0 Risk:** `KalshiContinuousTrader` is a complete trading engine with its own sizing, risk checks, and order routing. While currently gated by `pm_ct_policy.ct_legacy_must_not_trade()`, it represents a shadow execution path that could accidentally become active if the policy is bypassed or misconfigured.
- **P1 Risk:** Multiple `OrderIntent` creation paths exist (trading_agent, ct_execution_adapter, kalshi_tools). They have similar logic but slightly different parameter handling.

### 1.2 Side Semantics (YES/NO Mapping)

| Concern | Implementations | Canonical | Production-Reachable | Type | Risk |
|---------|----------------|-----------|----------------------|------|------|
| **Side Enum** | `side_semantics.Side` enum | `Side.YES`/`Side.NO` | NO (unused in practice) | Synthetic-dead | P2 |
| **String Literals** | `"yes"`/`"no"` strings throughout | `Side` enum | YES | Duplicate-near | P1 |

**Analysis:**
- **P1 Risk:** Canonical `Side` enum exists in `side_semantics.py` but trading code uses string literals `"yes"`/`"no"` instead. This is a type-safety gap.
- Files using string literals: `trading.py`, `order_router.py`, `kalshi_tools.py`, `position_cache.py`, and many strategy files.

### 1.3 Entry Window Logic

| Concern | Implementations | Canonical | Production-Reachable | Type | Risk |
|---------|----------------|-----------|----------------------|------|------|
| **Entry Window Resolution** | `dynamic_entry_window.resolve_entry_window()` | `resolve_entry_window()` | YES | N/A | N/A |
| | `trading_agent._in_entry_window()` | `resolve_entry_window()` | YES | Duplicate-near | P2 |
| | `kalshi_risk._check_entry_window()` | `resolve_entry_window()` | YES | Duplicate-near | P2 |
| | `resting_order_monitor._check_entry_window()` | `resolve_entry_window()` | YES | Duplicate-near | P2 |
| **Entry Window Config** | `dynamic_entry_window.EntryWindowConfig` | `EntryWindowConfig` | YES | N/A | N/A |
| | `agent_grid_config.EntryWindowConfig` | `EntryWindowConfig` | YES | Duplicate-exact | P1 |

**Analysis:**
- **P1 Risk:** `EntryWindowConfig` is defined twice (in `dynamic_entry_window.py` and `agent_grid_config.py`) with identical structure. This is copy-paste duplication.
- **P2 Risk:** Multiple entry window checks exist across different modules. They all eventually call `resolve_entry_window()`, but the wrapper logic is duplicated.

### 1.4 Sizing Logic (Position/Order Sizing)

| Concern | Implementations | Canonical | Production-Reachable | Type | Risk |
|---------|----------------|-----------|----------------------|------|------|
| **Order Sizing** | `kalshi_risk.KalshiRiskEngine.calculate_order_size()` | `KalshiRiskEngine` | YES (KalshiTradingAgent) | N/A | N/A |
| | `kalshi_continuous_trader.BankrollManager.calculate_order_size()` | `KalshiRiskEngine` | GATED | Duplicate-near | P1 |
| | `crypto15mallocator.compute_effective_budget()` | `KalshiRiskEngine` | YES | Duplicate-near | P2 |
| | Multiple `calculate_position_size()` in strategies | `KalshiRiskEngine` | NO (strategy-specific) | Synthetic-shadow | P2 |
| **Kelly Sizing** | `strategies.kelly.calculate_position_size()` | `KalshiRiskEngine` | NO (backtest only) | Synthetic-shadow | P2 |
| | `strategies.crypto_15m_strategy._calculate_position_size()` | `KalshiRiskEngine` | YES (strategy path) | Duplicate-near | P2 |

**Analysis:**
- **P1 Risk:** `BankrollManager.calculate_order_size()` in `KalshiContinuousTrader` is a near-duplicate of `KalshiRiskEngine.calculate_order_size()` with slightly different parameters.
- **P2 Risk:** Multiple strategy-specific sizing functions exist for backtesting and research. These are synthetic (not used in production).

### 1.5 Take Profit Logic

| Concern | Implementations | Canonical | Production-Reachable | Type | Risk |
|---------|----------------|-----------|----------------------|------|------|
| **TP Manager** | `take_profit.TakeProfitManager` | `TakeProfitManager` | YES (KalshiTradingAgent) | N/A | N/A |
| | `dynamic_takeprofit.DynamicTakeProfitEngine` | `TakeProfitManager` | YES (used by TA) | Duplicate-near | P2 |
| | `ct_profit_taking_integration.CTPProfitTaking` | `TakeProfitManager` | GATED | Duplicate-near | P1 |
| **Strategy TP** | Multiple strategy files with own TP logic | `TakeProfitManager` | NO (strategy-specific) | Synthetic-shadow | P2 |

**Analysis:**
- **P1 Risk:** `CTProfitTaking` in `ct_profit_taking_integration.py` is a CT-specific wrapper around `TakeProfitManager`. This is duplicate orchestration logic.
- **P2 Risk:** `DynamicTakeProfitEngine` provides R-multiple based TP calculations, which is complementary to `TakeProfitManager` but overlaps in purpose.

### 1.6 Stop Loss Logic

| Concern | Implementations | Canonical | Production-Reachable | Type | Risk |
|---------|----------------|-----------|----------------------|------|------|
| **SL Rules** | `stop_loss.StopLossRules` | `StopLossRules` | YES (KalshiTradingAgent) | N/A | N/A |
| | `kalshi_continuous_trader` inline SL checks | `StopLossRules` | GATED | Duplicate-near | P1 |
| | Multiple strategy files with own SL logic | `StopLossRules` | NO (strategy-specific) | Synthetic-shadow | P2 |

**Analysis:**
- **P1 Risk:** `KalshiContinuousTrader` has inline stop-loss checks (lines 3119-3145) that duplicate logic from `StopLossRules.check_position()`.
- **P2 Risk:** Multiple strategy files implement their own stop-loss logic for backtesting.

### 1.7 Order Lifecycle Tracking

| Concern | Implementations | Canonical | Production-Reachable | Type | Risk |
|---------|----------------|-----------|----------------------|------|------|
| **Order Manager** | `order_manager.OrderManager` | `OrderManager` | YES (used by trading_agent) | N/A | N/A |
| | `order_manager_enhanced.EnhancedOrderManager` | `OrderManager` | NO (unused) | Synthetic-dead | P2 |
| **Order Group Manager** | `order_group_manager.KalshiOrderGroupManager` | `KalshiOrderGroupManager` | YES | N/A | N/A |
| | `order_group_manager_enhanced.EnhancedOrderGroupRiskManager` | `KalshiOrderGroupManager` | NO (unused) | Synthetic-dead | P2 |

**Analysis:**
- **P2 Risk:** `EnhancedOrderManager` and `EnhancedOrderGroupRiskManager` exist but appear to be unused in production. They have circuit breaker and enhanced error handling but are not wired into the production path.

### 1.8 PnL, Balance, Portfolio Logic

| Concern | Implementations | Canonical | Production-Reachable | Type | Risk |
|---------|----------------|-----------|----------------------|------|------|
| **PnL Computation** | `portfolio_pnl_computer.RealTimePnLComputer` | `RealTimePnLComputer` | YES (canonical) | N/A | N/A |
| | `fills_ledger._compute_realized_pnl()` | `RealTimePnLComputer` | YES (fills ledger) | Duplicate-near | P1 |
| | `kalshi_risk.record_pnl()` | `RealTimePnLComputer` | YES (risk tracking) | Duplicate-near | P1 |
| | `stop_loss.TrackedPosition.unrealized_pnl_cents` | `RealTimePnLComputer` | YES (SL tracking) | Duplicate-near | P1 |
| **Bankroll Service** | `bankroll_service.KalshiBankrollService` | `BankrollServiceV2` | NO (legacy) | Synthetic-dead | P1 |
| | `bankroll_service_v2.BankrollServiceV2` | `BankrollServiceV2` | YES (canonical) | N/A | N/A |
| | `bankroll_resolver.BankrollResolver` | `BankrollServiceV2` | YES (helper) | Duplicate-near | P2 |
| | `bankroll_adapter.BankrollAdapter` | `BankrollServiceV2` | YES (adapter) | Duplicate-near | P2 |
| **Reconciliation** | `portfolio_reconciliation.PortfolioReconciler` | `PortfolioReconciler` | YES (canonical) | N/A | N/A |
| | `reconciliation.kalshi_reconciler.KalshiReconciler` | `PortfolioReconciler` | NO (legacy) | Synthetic-dead | P1 |
| | `sentiment_reconciliation_job.SentimentReconciliationJob` | `PortfolioReconciler` | NO (sentiment only) | Synthetic-shadow | P2 |

**Analysis:**
- **P1 Risk:** Multiple PnL computation implementations exist with slightly different logic (real-time vs fills-based vs risk-based). This can lead to PnL discrepancies if different sources are used.
- **P1 Risk:** `KalshiBankrollService` (legacy) and `BankrollServiceV2` (new) both exist. The legacy service should be removed.
- **P1 Risk:** `KalshiReconciler` (legacy) and `PortfolioReconciler` (event-sourced) both exist. The legacy reconciler should be removed.

### 1.9 Risk Logic

| Concern | Implementations | Canonical | Production-Reachable | Type | Risk |
|---------|----------------|-----------|----------------------|------|------|
| **Global Risk** | `risk.kill_switches.RiskController` | `RiskController` | YES (canonical) | N/A | N/A |
| | `risk.risk_guard.RiskGuard` | `RiskController` | YES (execution guard) | Duplicate-near | P1 |
| | `guards.global_risk_guard.GlobalRiskGuard` | `RiskController` | YES (guards layer) | Duplicate-near | P1 |
| **Kalshi Risk** | `kalshi_risk.KalshiRiskManager` | `KalshiRiskManager` | YES (canonical) | N/A | N/A |
| | `kalshi_continuous_trader.GlobalRiskGuard` | `KalshiRiskManager` | GATED | Duplicate-exact | P1 |
| | `kalshi_continuous_trader.BankrollManager` | `KalshiRiskManager` | GATED | Duplicate-near | P1 |
| **Unified Risk** | `risk.unified_risk_engine.UnifiedRiskEngine` | `UnifiedRiskEngine` | YES (unified) | N/A | N/A |
| | `prediction.portfolio_risk_manager.PortfolioRiskManager` | `UnifiedRiskEngine` | YES (portfolio) | Duplicate-near | P1 |

**Analysis:**
- **P1 Risk:** Multiple risk guard implementations exist (`RiskGuard`, `GlobalRiskGuard`, `GlobalRiskGuard` in CT). They have similar functionality but slightly different APIs.
- **P1 Risk:** `KalshiContinuousTrader.GlobalRiskGuard` is an exact duplicate subclass of the shared `_SharedGlobalRiskGuard`. This is pure duplication.

### 1.10 Position Tracking

| Concern | Implementations | Canonical | Production-Reachable | Type | Risk |
|---------|----------------|-----------|----------------------|------|------|
| **Position Cache** | `position_cache.KalshiPositionCache` | `KalshiPositionCache` | YES (canonical) | N/A | N/A |
| | `risk_adapter.LegacyPositionCache` | `KalshiPositionCache` | NO (adapter) | Synthetic-shadow | P2 |

**Analysis:**
- **P2 Risk:** `LegacyPositionCache` exists as an adapter for legacy code. This is acceptable transitional code but should be marked for eventual removal.

---

## 2. New Issues (P0/P1/P2)

### P0 Issues

#### P0-1: Dual Trading Engines with Overlapping Capabilities

**Location:** 
- `merid/trading/kalshi_continuous_trader.py` (KalshiContinuousTrader)
- `merid/prediction/trading_agent.py` (KalshiTradingAgent)

**Description:**
Two complete trading engines exist that can both execute Kalshi orders:
1. **KalshiTradingAgent** (AgentGrid PM) - Production path for `kalshi_crypto_15m_v2`
2. **KalshiContinuousTrader** (legacy runner) - Suppressed but code-complete

**How it diverges from canonical:**
- `KalshiContinuousTrader` has its own:
  - Sizing logic (`BankrollManager.calculate_order_size()`)
  - Risk checks (`GlobalRiskGuard`, inline stop-loss)
  - Order routing (`ct_execution_adapter.convert_to_intent()`)
  - TP/SL integration (`ct_profit_taking_integration`)
  - PnL reconciliation (`ct_pnl_reconciler`)

**What happens if both are used:**
- Duplicate order submissions
- Conflicting position tracking
- Risk limit confusion (which engine enforces?)
- Bankroll double-spending risk
- PnL calculation discrepancies

**Current Mitigation:**
- Gated by `pm_ct_policy.ct_legacy_must_not_trade()` which checks:
  - `MERID_TRADE_MODE=live` AND `MERID_ALLOW_LIVE_TRADES=true`
  - If both are live, CT is suppressed
- `KALSHI_TRADER_ENABLED` kill switch

**Risk Assessment:**
- **Risk:** If the policy check is bypassed or misconfigured, both engines could trade simultaneously
- **Impact:** Catastrophic - double orders, risk limit violations, bankroll overspend
- **Likelihood:** Low (policy gate exists) but not zero (code is complex)

**Recommendation:**
1. **Immediate:** Add hard-coded assertion in `KalshiContinuousTrader.__init__` that raises if `MERID_PROFILE=kalshi_crypto_15m_v2` is set
2. **Short-term:** Remove CT-specific implementations (sizing, risk, routing) and force CT to use the same canonical paths as KalshiTradingAgent
3. **Long-term:** Deprecate and remove `KalshiContinuousTrader` entirely if it's not needed for research

---

### P1 Issues

#### P1-1: Duplicate Bankroll Services (Legacy vs V2)

**Location:**
- `merid/event_venues/kalshi/bankroll_service.py` (legacy)
- `merid/event_venues/kalshi/bankroll_service_v2.py` (canonical)

**Description:**
Two bankroll service implementations exist with similar functionality:
- `KalshiBankrollService` (legacy) - older implementation
- `BankrollServiceV2` (new) - event-sourced, canonical

**How it diverges:**
- Legacy: Simple balance fetching, no event sourcing
- V2: Event-sourced, portfolio value computation, subscription model

**What happens if both are used:**
- Different balance values returned
- Risk limits calculated incorrectly
- Inconsistent sizing decisions

**Current Mitigation:**
- Code comments indicate legacy is deprecated
- Profile gating in `kalshi_risk.py` uses V2 when available

**Recommendation:**
1. Search for all imports of `KalshiBankrollService` and replace with `BankrollServiceV2`
2. Remove `bankroll_service.py` after migration
3. Update all references to use the canonical V2 service

---

#### P1-2: Multiple Risk Guard Implementations

**Location:**
- `merid/risk/risk_guard.py` (RiskGuard)
- `merid/guards/global_risk_guard.py` (GlobalRiskGuard)
- `merid/trading/kalshi_continuous_trader.py` (GlobalRiskGuard subclass)

**Description:**
Three risk guard implementations exist with overlapping functionality:
- `RiskGuard` - general risk guard
- `GlobalRiskGuard` - guards-layer implementation
- `KalshiContinuousTrader.GlobalRiskGuard` - CT-specific duplicate

**How it diverges:**
- Different APIs (`check_trade()` vs `can_trade()`)
- Different state management
- Slightly different risk checks

**What happens if both are used:**
- Inconsistent risk decisions
- One guard may allow what another blocks
- Confusing risk state

**Recommendation:**
1. Consolidate to single `RiskController` from `risk.kill_switches`
2. Make `GlobalRiskGuard` and `RiskGuard` thin wrappers around `RiskController`
3. Remove CT-specific `GlobalRiskGuard` subclass

---

#### P1-3: Duplicate Order Intent Creation Paths

**Location:**
- `merid/prediction/trading_agent.py` (_execute_signal_body)
- `merid/trading/ct_execution_adapter.py` (convert_to_intent)
- `merid/prediction/kalshi_tools.py` (build_live_route_order_intent)

**Description:**
Three different functions create `OrderIntent` objects with similar logic:
- Trading agent creates intents for agent-based trading
- CT adapter creates intents for continuous trader
- Kalshi tools creates intents for LLM tools

**How it diverges:**
- Slightly different parameter handling
- Different default values for TP/SL
- Different validation logic

**What happens if both are used:**
- Inconsistent intent validation
- Missing parameters in some paths
- Different risk check behavior

**Recommendation:**
1. Create single canonical `OrderIntentBuilder` class
2. Make all three paths use the builder
3. Ensure consistent validation and defaults

---

#### P1-4: Multiple PnL Computation Implementations

**Location:**
- `merid/event_venues/kalshi/portfolio_pnl_computer.py` (RealTimePnLComputer)
- `merid/event_venues/kalshi/fills_ledger.py` (_compute_realized_pnl)
- `merid/event_venues/kalshi/kalshi_risk.py` (record_pnl)
- `merid/event_venues/kalshi/stop_loss.py` (unrealized_pnl_cents)

**Description:**
Four different PnL computation implementations with slightly different logic:
- Real-time PnL from market state
- Realized PnL from fills
- Risk tracking PnL
- Stop-loss tracking PnL

**How it diverges:**
- Different fee treatment
- Different rounding
- Different inclusion of unrealized PnL
- Different update frequencies

**What happens if both are used:**
- PnL discrepancies between sources
- UI shows different values than risk engine
- Confusion about which PnL is "correct"

**Current Mitigation:**
- `RealTimePnLComputer` is marked as canonical
- Other implementations are for specific use cases

**Recommendation:**
1. Make all PnL consumers use `RealTimePnLComputer` as source of truth
2. Convert other implementations to pure view layers over canonical state
3. Add validation that all PnL sources agree within tolerance

---

### P2 Issues

#### P2-1: Strategy-Specific Take Profit/Stop Loss Logic

**Location:**
- Multiple strategy files in `merid/strategies/`

**Description:**
Many strategy files have their own TP/SL implementations for backtesting:
- `stops_tp.py`
- `crypto_15m_strategy.py`
- `band_strategy_15m.py`
- And others

**Risk:**
- These are synthetic (backtest-only) and don't affect production
- However, if someone accidentally uses them in production, they bypass canonical TP/SL

**Recommendation:**
- Mark clearly as "backtest-only" with module-level docstrings
- Add runtime assertions that these are never called in live mode
- Consider consolidating to shared backtesting utilities

---

#### P2-2: Enhanced Order Managers (Unused)

**Location:**
- `merid/event_venues/kalshi/order_manager_enhanced.py`
- `merid/event_venues/kalshi/order_group_manager_enhanced.py`

**Description:**
Enhanced order managers with circuit breaker and better error handling exist but are not used in production.

**Risk:**
- Dead code that may confuse developers
- If accidentally wired in, could change behavior

**Recommendation:**
- Remove if truly unused
- Or merge enhancements into canonical managers

---

#### P2-3: Legacy Reconciler

**Location:**
- `merid/reconciliation/kalshi_reconciler.py`

**Description:**
Legacy reconciler exists alongside canonical `PortfolioReconciler`.

**Risk:**
- If both run, could cause double-reconciliation
- Confusion about which is source of truth

**Recommendation:**
- Remove legacy reconciler
- Ensure all consumers use `PortfolioReconciler`

---

#### P2-4: EntryWindowConfig Duplication

**Location:**
- `merid/prediction/dynamic_entry_window.py`
- `merid/prediction/agent_grid_config.py`

**Description:**
`EntryWindowConfig` is defined twice with identical structure.

**Risk:**
- Changes must be made in two places
- Inconsistency risk if definitions diverge

**Recommendation:**
- Keep single definition in `dynamic_entry_window.py`
- Import from there in `agent_grid_config.py`

---

#### P2-5: Side Enum Not Used

**Location:**
- `merid/event_venues/kalshi/side_semantics.py`

**Description:**
Canonical `Side` enum exists but code uses string literals.

**Risk:**
- Type safety gap
- Potential for typos ("yse" vs "yes")

**Recommendation:**
- Migrate trading code to use `Side.YES` and `Side.NO`
- Add validation that side values are from enum

---

#### P2-6: Multiple Sizing Functions in Strategies

**Location:**
- Multiple `calculate_position_size()` functions across strategy files

**Description:**
Many strategy files have their own sizing logic for backtesting.

**Risk:**
- Synthetic (backtest-only)
- Could confuse developers about which sizing to use

**Recommendation:**
- Mark as backtest-only
- Consolidate to shared utilities where possible

---

## 3. Consolidation Plan

### 3.1 High Priority (P0/P1)

#### P0-1: Dual Trading Engines

**Canonical to keep:** `KalshiTradingAgent` (AgentGrid PM)

**To deprecate/remove:** `KalshiContinuousTrader`

**Concrete refactor steps:**
1. **Immediate (Safety):**
   ```python
   # In KalshiContinuousTrader.__init__, add:
   if os.getenv("MERID_PROFILE") == "kalshi_crypto_15m_v2":
       raise RuntimeError(
           "KalshiContinuousTrader is incompatible with kalshi_crypto_15m_v2 profile. "
           "Use KalshiTradingAgent (AgentGrid PM) instead."
       )
   ```

2. **Short-term (1-2 weeks):**
   - Remove CT-specific sizing (`BankrollManager.calculate_order_size()`)
   - Force CT to use `KalshiRiskEngine.calculate_order_size()`
   - Remove CT-specific risk checks (`GlobalRiskGuard` subclass)
   - Force CT to use canonical `RiskController`
   - Remove CT-specific TP/SL integration
   - Force CT to use canonical `TakeProfitManager` and `StopLossRules`

3. **Long-term (1-2 months):**
   - If CT is only used for research, move to `research/` directory
   - Add clear documentation that CT is research-only
   - Or remove entirely if not needed

#### P1-1: Duplicate Bankroll Services

**Canonical to keep:** `BankrollServiceV2`

**To deprecate/remove:** `KalshiBankrollService` (legacy)

**Concrete refactor steps:**
1. Search for all imports:
   ```bash
   grep -r "from merid.event_venues.kalshi.bankroll_service import" merid/
   grep -r "KalshiBankrollService" merid/
   ```

2. Replace imports:
   ```python
   # Before:
   from merid.event_venues.kalshi.bankroll_service import KalshiBankrollService
   # After:
   from merid.event_venues.kalshi.bankroll_service_v2 import BankrollServiceV2 as KalshiBankrollService
   ```

3. Update API calls (V2 has different method names):
   - `fetch_live_bankroll_async()` → `get_current_bankroll()`
   - `compute_effective_bankroll_usd()` → `get_summary()`

4. Remove `bankroll_service.py` after migration

#### P1-2: Multiple Risk Guards

**Canonical to keep:** `RiskController` from `risk.kill_switches`

**To deprecate/remove:** `RiskGuard`, `GlobalRiskGuard`, CT-specific `GlobalRiskGuard`

**Concrete refactor steps:**
1. Make `RiskGuard` and `GlobalRiskGuard` thin wrappers:
   ```python
   class RiskGuard:
       def __init__(self):
           self._controller = get_risk_controller()
       
       def can_trade(self, *args, **kwargs):
           return self._controller.check_trade(...)
   ```

2. Remove CT-specific `GlobalRiskGuard` subclass

3. Update all consumers to use `RiskController` directly

#### P1-3: Duplicate Order Intent Creation

**Canonical to keep:** Single `OrderIntentBuilder` class

**To create:** New `OrderIntentBuilder` in `order_router.py`

**Concrete refactor steps:**
1. Create canonical builder:
   ```python
   class OrderIntentBuilder:
       def build(self, side, action, ticker, size, price_cents, **kwargs) -> OrderIntent:
           # Canonical validation and defaults
           # Set TP/SL from defaults if not provided
           # Validate against entry-exit invariant
           return OrderIntent(...)
   ```

2. Update `trading_agent._execute_signal_body()` to use builder

3. Update `ct_execution_adapter.convert_to_intent()` to use builder

4. Update `kalshi_tools.build_live_route_order_intent()` to use builder

#### P1-4: Multiple PnL Computations

**Canonical to keep:** `RealTimePnLComputer`

**To convert to view layers:** Other implementations

**Concrete refactor steps:**
1. Make `fills_ledger._compute_realized_pnl()` a view over `RealTimePnLComputer` state

2. Make `kalshi_risk.record_pnl()` update canonical state, not compute independently

3. Make `stop_loss.unrealized_pnl_cents()` query canonical state

4. Add validation:
   ```python
   # In startup validation:
   pnl_from_computer = get_pnl_computer().get_snapshot()
   pnl_from_ledger = fills_ledger.get_realized_pnl()
   assert abs(pnl_from_computer - pnl_from_ledger) < 10  # 10 cent tolerance
   ```

### 3.2 Medium Priority (P2)

#### P2-1 to P2-6: Strategy-Specific and Legacy Code

**General approach:**
1. Add module-level docstrings: "BACKTEST-ONLY - Not for production use"
2. Add runtime assertions in key functions:
   ```python
   if os.getenv("MERID_TRADE_MODE") == "live":
       raise RuntimeError("This function is for backtesting only")
   ```
3. Consolidate shared logic to utility modules
4. Remove clearly dead code (enhanced order managers, legacy reconciler)

---

## 4. Guardrails and Tests

### 4.1 New Tests to Prevent Future Duplication

#### Test: Single PnL Source of Truth
```python
def test_single_pnl_source_of_truth():
    """Ensure all PnL sources agree within tolerance."""
    computer = get_pnl_computer()
    ledger = get_fills_ledger()
    risk = get_kalshi_risk()
    
    pnl_computer = computer.get_snapshot().total_pnl_cents
    pnl_ledger = ledger.get_realized_pnl()
    pnl_risk = risk.get_session_pnl()
    
    assert abs(pnl_computer - pnl_ledger) < 10  # 10 cent tolerance
    assert abs(pnl_computer - pnl_risk) < 10
```

#### Test: Single Bankroll Service
```python
def test_single_bankroll_service_used():
    """Ensure only BankrollServiceV2 is imported in production code."""
    # Scan production code for legacy bankroll service imports
    # Fail if found in merid/event_venues/kalshi/ (excluding tests)
```

#### Test: Single Risk Controller
```python
def test_single_risk_controller():
    """Ensure all risk checks go through RiskController."""
    # Verify RiskGuard and GlobalRiskGuard are thin wrappers
    # Verify no direct risk checks bypass RiskController
```

#### Test: EntryWindowConfig Single Source
```python
def test_entry_window_config_single_source():
    """Ensure EntryWindowConfig is defined only once."""
    # Scan for class definitions
    # Fail if more than one EntryWindowConfig class found
```

### 4.2 CI Hooks to Detect High Similarity

#### Tool: Copy-paste detector in CI
```yaml
# In .github/workflows/ci.yml
- name: Detect duplicate code
  run: |
    pip install jscpd
    jscpd merid/ --threshold 5 --ignore "*/tests/*"
```

#### Tool: AST-based similarity check
```python
# In tests/test_duplicate_logic.py
def test_no_duplicate_function_signatures():
    """Detect functions with identical signatures across modules."""
    # Parse all Python files in merid/
    # Build signature map: (module, function_name) -> signature
    # Flag duplicates with >80% similarity
```

### 4.3 Static Analysis Rules

#### Rule: Ban legacy imports in production code
```python
# In .pylintrc or similar
disable=
    # Ban these imports in production code
    banned-imports=
        merid.event_venues.kalshi.bankroll_service,
        merid.reconciliation.kalshi_reconciler,
```

#### Rule: Require canonical enum usage
```python
# Custom flake8 plugin
def check_side_enum_usage(node):
    """Flag string literals "yes"/"no" in trading code."""
    if isinstance(node, ast.Str) and node.s in ("yes", "no"):
        # Check if in trading-related file
        # Suggest using Side.YES / Side.NO instead
```

---

## 5. Summary

### Key Findings

1. **P0 Risk:** Dual trading engines (`KalshiTradingAgent` vs `KalshiContinuousTrader`) with overlapping capabilities
2. **P1 Risks:** Duplicate bankroll services, risk guards, order intent creation, PnL computation
3. **P2 Risks:** Strategy-specific logic, unused enhanced managers, legacy reconciler, config duplication

### Production Readiness

**Current State:** System is production-ready with current mitigations in place (policy gates, kill switches).

**Post-Consolidation State:** System will be significantly more maintainable and less error-prone.

### Recommended Timeline

- **Week 1:** Add hard-coded assertion for P0 (CT vs profile)
- **Weeks 2-3:** Consolidate bankroll services (P1-1)
- **Weeks 4-5:** Consolidate risk guards (P1-2)
- **Weeks 6-7:** Consolidate order intent creation (P1-3)
- **Weeks 8-9:** Consolidate PnL computation (P1-4)
- **Weeks 10-12:** Address P2 issues (strategy code, legacy removal)

### Success Metrics

- Zero duplicate implementations for production-critical concerns
- Single source of truth for PnL, bankroll, risk
- All trading paths use canonical order routing
- CI fails if new duplicate code is introduced
