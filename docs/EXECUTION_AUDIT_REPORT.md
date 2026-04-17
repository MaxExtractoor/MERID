# Autonomous Trading Execution Audit Report
**Date:** 2026-03-15  
**Scope:** Autonomous trading and execution layer — Kalshi prediction market swarm  
**Auditor:** Senior Algo-Trading Engineer / Reliability Lead  
**Codebase Snapshot:** `c:\Dev\MERID`

---

## Executive Summary

The execution pipeline has solid scaffolding — layered risk guards, mode isolation, partial-fill simulation, circuit breakers, and a kill switch that persists to disk. However, **eight high-risk issues** exist that could produce unbounded loss, runaway trading, or inability to stop/flatten in live conditions. The most critical are: (1) a fail-open catch in the category-exposure gate that silently skips the check on any exception; (2) a `_execute_signal` that treats a successful API call as a "fill" without waiting for or verifying actual fill status from the venue; (3) simulated PnL used for BTC-15m risk tracking in production (Bernoulli draw instead of real settlement outcome); and (4) the `PredictionMarketRisk` singleton being constructed per-agent, meaning risk caps do not aggregate across agents on the same portfolio.

---

## Pipeline Map

| Stage | Key Files / Classes | Contract |
|---|---|---|
| **Signal** | `merid/prediction/trading_agent.py::KalshiTradingAgent._run_cycle_body` | Input: resolved `EventMarket` list. Output: `StrategySignal`. Invariant: only one active contract per asset/timeframe slot. |
| **Sizing** | `merid/prediction/strategy.py::KalshiStrategy.evaluate` → `merid/prediction/risk.py::PredictionMarketRisk.check_order` | Input: `MarketSnapshot`. Output: `StrategySignal.contracts`, `PreTradeCheck.adjusted_size`. Invariant: contracts ≤ per-market & portfolio caps. |
| **Routing** | `merid/event_venues/kalshi/order_router.py::route_order_async` | Input: `OrderIntent`. Output: `OrderResult`. Invariant: LIVE mode can only execute after kill-switch, risk-manager, and category-cap pass. |
| **Submission** | `merid/event_venues/kalshi/client.py::KalshiClient.place_order_result` | Input: `VenueOrder`. Output: `OperationResult[PlacedOrder]`. Invariant: uses RSA-signed REST, circuit-breaker backs off on 5xx. |
| **Fill / Monitoring** | `trading_agent.py::_execute_signal` → `stop_loss.py::StopLossRules` | Input: `result.payload`. Output: `TrackedPosition` in `_tracked_positions`. Invariant: every fill registers a stop-loss position. |
| **Reconciliation** | `trading/reconciliation.py::ReconciliationReport`, `merid/prediction/agent_grid.py::_reconciliation_loop` | Input: paper ledger + venue positions. Output: `ReconciliationReport`. Invariant: cash + positions = equity, no ghost positions. |

---

## 1. High-Risk Autonomous Trading / Execution Bugs

### BUG-01 — Category Exposure Gate Fails Open
- **Name:** `_check_sanity` + category-cap exception swallows block
- **Location:** `merid/event_venues/kalshi/order_router.py:528-529`
- **Category:** risk-control
- **Description:**
  ```python
  except Exception as _exc:
      logger.error("[order-router] Category exposure check error (fail-open): %s", _exc)
  ```
  The `except` block for the A3/A4 category cap and correlated-market stacking guard (lines 503-527) logs an error and **falls through to live order submission**. Any import error, attribute error, or transient exception in `get_category_exposure_tracker()` will silently skip the cross-agent category cap. The comment explicitly says `fail-open`. Contrast this with the kill-switch check above it, which explicitly fails closed. This means a bug in any dependency of the exposure tracker (e.g., a stale `infer_category` call or `get_category_exposure_tracker()` returning `None`) causes the live order to proceed uncapped.
- **Impact:** Multiple agents simultaneously targeting the same category (e.g., BTC crypto markets) can each pass their local cap while violating the aggregate cross-agent category cap. In a volatile market, 8 agents × $500 notional each = $4,000 of concentrated exposure against a $5,000 portfolio cap, with zero risk-system awareness.
- **Proposed fix:** Change the except block to fail closed (return a rejected `OrderResult`) or at minimum re-raise after logging. The sanity-checker catch at line 380-382 has the same fail-open comment and should receive the same treatment for live mode.

---

### BUG-02 — "Order Placed" Conflated With "Order Filled"
- **Name:** Optimistic fill accounting — submitted = filled
- **Location:** `merid/prediction/trading_agent.py:1168-1210`
- **Category:** lifecycle
- **Description:**
  The `_execute_signal` method receives `result_success = result.success` from `_kalshi_place_order`. In live mode, the Kalshi API returns `placed.status` which can be `"accepted_live"` (GTC order resting on the book, not yet filled). However, the code then immediately:
  1. Appends an entry to `state.fill_log` (line 1208)
  2. Calls `event_stream.publish("kalshi:order_filled", ...)` (line 1215)
  3. Registers a `TrackedPosition` in `_tracked_positions` (line 1285)
  4. Calls `risk_mgr.record_order(...)` to consume notional cap (line 1306)
  5. Calls `edge_store.record_trade_entry(...)` (line 1240)

  None of these are gated on `status == "filled_live"`. In `order_router.py:674-679`, the status is correctly discriminated (`accepted_live` vs `partial_live` vs `filled_live`), but the caller in `_execute_signal` checks only `result.success` (line 1168), which is `True` for all three statuses.
  
  Consequence: a GTC limit order that never fills will consume notional cap, be logged as a fill, trigger the stop-loss engine, and be counted in `orders_placed` — all without any actual exposure existing on the venue. Simultaneously, the actual fill arrives asynchronously via WS but has no code path to update the already-created `TrackedPosition`.
- **Impact:** Over-counting notional cap consumption blocks legitimate future orders. If the GTC order is later cancelled by the venue (e.g., market closes), MERID's internal risk state shows a phantom position that will never be unwound, permanently consuming cap until restart.
- **Proposed fix:** Gate all fill-accounting paths on `status == "filled_live"` or `"partial_live"`. For `accepted_live` orders, store only a pending-order record. Implement a WS fill handler that moves the pending order to filled state and then triggers the risk accounting.

---

### BUG-03 — BTC-15m Risk Tracking Uses Bernoulli Draw, Not Real Settlement
- **Name:** Fabricated PnL fed into live risk manager
- **Location:** `merid/prediction/trading_agent.py:1390-1406`
- **Category:** risk-control / execution-quality
- **Description:**
  ```python
  _won = random.random() < _win_prob
  _pnl = ((100.0 - p_c) * size / 100.0) if _won else -(p_c * size / 100.0)
  self._btc15m_risk.record_trade_result(ticker=..., realized_pnl=_pnl, mode=_btc_mode)
  ```
  On every fill (including live fills when `_btc_mode == TradeMode.LIVE`), the CryptoSwarmRiskBTC15m risk manager is fed a random PnL draw from a Bernoulli distribution parameterised by the implied probability. This is not the actual settlement outcome. Kalshi binary contracts settle days later; the real PnL is only known at expiry.
  
  The risk manager uses `record_trade_result` to track daily PnL for phase promotion / demotion and sizing decisions. Random PnL inputs will cause the risk manager to promote or demote the agent's phase based on noise, not actual performance. In a bad-luck streak (random draw says "lose" repeatedly), the system may demote to Phase 0 and block all new orders even when the real portfolio is profitable.
- **Impact:** Erratic phase transitions produce erratic sizing. In the worst case, a live session with real edge will be throttled to minimum size due to unlucky RNG, while a losing session may be allowed to run at full size because RNG was lucky. The risk manager's state diverges from reality.
- **Proposed fix:** Remove the Bernoulli draw. Call `record_trade_result` only from `OutcomeResolver.record_settlement()` (which already exists), using the real settlement outcome. For the risk manager to have a live view of unrealized exposure, expose a separate method (e.g., `update_open_exposure`) that takes contract count and entry price, without fabricating a PnL.

---

### BUG-04 — Per-Agent `PredictionMarketRisk` Singleton Does Not Aggregate Across Agents
- **Name:** Fragmented risk state — agents don't share a portfolio-level risk manager
- **Location:** `merid/prediction/trading_agent.py:115-118`, `merid/prediction/risk.py:166-188`
- **Category:** risk-control / multi-agent
- **Description:**
  Each `KalshiTradingAgent` instantiates its own `PredictionMarketRisk`:
  ```python
  self._risk = PredictionMarketRisk(PredictionRiskConfig(
      max_notional_per_market_usd=config.risk_limits.max_notional_usd,
      ...
  ))
  ```
  This is **not** the shared `get_prediction_risk()` singleton (line 719-726 of `risk.py`). Each agent has a private risk manager tracking only its own exposure. There is a separate `PortfolioRiskAgent` at the grid level, but the per-order pre-trade checks at lines 429-463 of `trading_agent.py` call `self._risk.check_order()` which uses only the agent's private state.
  
  The `max_total_notional_usd` cap ($5,000 default) is enforced per-agent, not across all agents. With 8 agents each capped at $5,000, the total portfolio exposure cap is effectively $40,000 rather than $5,000.
- **Impact:** A flash-crash or adversarial market condition that fools all agents simultaneously allows 8× overexposure relative to the intended portfolio limit. This is a structural failure of risk aggregation — the most dangerous category of risk failure.
- **Proposed fix:** Use the shared `get_prediction_risk()` singleton for all per-order checks, **or** have each agent's `check_order` call also pass through `PortfolioRiskAgent.check_order()` which has grid-wide visibility. The `ExecutionGuard` pattern from `merid/execution_guard.py` demonstrates the correct singleton approach.

---

### BUG-05 — Stop-Loss Close on Failure Silently Retains Position
- **Name:** Stop-loss failure — position retained indefinitely with no escalation
- **Location:** `merid/prediction/trading_agent.py:580-590`
- **Category:** autonomy/failsafe
- **Description:**
  ```python
  else:
      self.logger.warning(
          "stop_loss close order failed for %s: %s — position retained for retry",
          pos.ticker, result.error_message,
      )
  ```
  When a stop-loss triggered close order fails, the position is retained in `_tracked_positions` for "retry". However, there is no retry counter, no exponential backoff, no escalation to a human operator, and no maximum retry limit. The position will be checked again on the next cycle (every 30–60 seconds), but if the Kalshi API is degraded (the exact condition most likely to require stop-loss execution), every retry will also fail. There is no mechanism to:
  - Alert an operator that a stop-loss failed
  - Halt new order entry while a stop-loss close is pending
  - Escalate to a market-order with `price_cents=0` after N failures
  - Log the failure to an audit trail accessible outside the in-memory `state.errors`
- **Impact:** During a Kalshi API outage or rate-limit event, stop-loss triggers will silently fail. The agent continues evaluating new signals and may place additional entries in the same market while an existing losing position cannot be closed. In the worst case, the position expires worthless after the system has added to it multiple times.
- **Proposed fix:** Implement a `RetryState` per position with a counter and `last_attempt_ts`. After 3 failures, halt the agent (`self.pause()`), fire an alert via `_alert_manager`, and log to the audit trail. Escalate to market order after 2 failures. Add a metric counter for failed stop-loss attempts that feeds the monitoring dashboard.

---

### BUG-06 — `_is_live_fill` Detection Relies on `result.payload["simulated"]`
- **Name:** Mode detection via payload field — can silently misclassify live fills as paper
- **Location:** `merid/prediction/trading_agent.py:1293`
- **Category:** risk-control / lifecycle
- **Description:**
  ```python
  _is_live_fill = not bool(result_payload.get("simulated", True)) if result_payload else False
  ```
  The default value is `True` (simulated). If `result_payload` is falsy (e.g., `None`, `{}`, or a result with an unexpected schema), `_is_live_fill` is `False`, meaning the fill is treated as paper. This is used to gate:
  - `risk_mgr.record_order()` (live exposure accounting)
  - `rebalancer.execute_rebalance()` (live rebalance orders)
  
  In live mode, if the Kalshi client returns a successful `PlacedOrder` but the `fill` dict does not contain the `"simulated": False` key (e.g., due to an API schema change or a code path that omits it), the fill silently bypasses live risk accounting. The agent has placed a real order on Kalshi, consumed real money, but MERID's risk state shows no exposure change.
  
  Conversely, the `OrderResult.fill` dict in `order_router.py:704` hardcodes `"simulated": False` for live fills — but only in `_route_live`. If the code path ever changes or a new route is added, this silent default-to-paper becomes a liability.
- **Impact:** Live positions are not tracked in the risk manager. Daily loss limits, notional caps, and drawdown triggers will not fire for positions that bypassed accounting. The system may continue trading past all safety limits.
- **Proposed fix:** Derive mode from `OrderResult.mode` (a `TradingMode` enum) rather than a dict field that can be absent. The mode is reliably set at line 190 of `order_router.py`. Replace:
  ```python
  _is_live_fill = result.mode == TradingMode.LIVE
  ```

---

### BUG-07 — Stale Market Snapshot Used for Risk Check: `_build_snapshot` Has No Orderbook Data
- **Name:** Risk checks 12-14 (spread, slippage, depth) always pass — inputs are None
- **Location:** `merid/prediction/trading_agent.py:429-437`, `merid/prediction/risk.py:505-541`
- **Category:** execution-quality
- **Description:**
  The pre-trade risk check at `_run_cycle_body:430` calls:
  ```python
  check = self._risk.check_order(
      market_id=market.market_id,
      event_id=event_id,
      side=side_str,
      contracts=signal.contracts,
      price_cents=check_price,
      edge=signal.edge.net_edge if signal.edge else Decimal("0"),
  )
  ```
  The keyword arguments `best_bid_cents`, `best_ask_cents`, and `depth_at_price` are **not passed** — they default to `None`. In `risk.py`:
  - Check 12 (spread): `if best_bid_cents is not None and best_ask_cents is not None` → **always skipped**
  - Check 13 (slippage guard): `if side in ("buy",...) and best_ask_cents is not None` → **always skipped**
  - Check 14 (depth check): `if depth_at_price is not None` → **always skipped**
  
  The `MarketSnapshot` does contain bid/ask via `implied.yes_bid` and `implied.yes_ask`, but these are synthetic implied probabilities computed from a single price point (line 686-692 of `trading_agent.py`), not live orderbook data. `_build_snapshot` does not call any orderbook API. Checks 12-14 are therefore dead code under all current call sites in `trading_agent.py`.
- **Impact:** Orders can be placed into markets with a 20+ cent spread, zero depth, or extreme slippage, bypassing the very checks designed to prevent trading in illiquid conditions. The agent will consistently overpay to fill in thin markets, eroding edge.
- **Proposed fix:** Fetch live orderbook in `_build_snapshot` using `client.get_orderbook(market.market_id)` (which exists in the Kalshi client). Pass `best_bid_cents`, `best_ask_cents`, and `depth_at_price` from the live book into `check_order`. Cache per-cycle to avoid redundant API calls.

---

### BUG-08 — Solo Execution in Swarm-Degraded Mode Has No Absolute Cap
- **Name:** Degraded-mode trading allows unbounded order volume after 120s without consensus
- **Location:** `merid/prediction/trading_agent.py:382-410`
- **Category:** autonomy/failsafe / multi-agent
- **Description:**
  When swarm consensus has been unavailable for `_MAX_SOLO_SECONDS = 120.0s`, the agent:
  1. Logs a single warning about entering degraded mode
  2. Halves `signal.contracts` (min 1)
  3. **Continues trading indefinitely at half-size**
  
  There is no:
  - Maximum number of solo trades allowed per degraded session
  - Time limit on how long degraded mode can persist before halting
  - Per-symbol or per-session notional limit that is specifically tighter in degraded mode
  - Alert sink notification (the warning is logged but not published to `_alert_manager`)
  
  The `state.swarm_degraded` flag is set but never consumed by any external kill-switch or escalation path. An agent can trade indefinitely solo at half-size, which still doubles the total portfolio exposure if all 8 agents degrade simultaneously (e.g., consensus service goes down, which is exactly when correlated market moves are most dangerous).
- **Impact:** Full swarm failure → all 8 agents enter degraded mode simultaneously → 8 agents × half-size × unlimited cycles = equivalent of 4 full-size agents running without consensus, each on the same signals, potentially concentrating in the same direction. This is the worst-case multi-agent failure mode: correlated exposure with no coordination, in the exact market conditions most likely to produce correlated losses.
- **Proposed fix:** Enforce a hard cap on solo trades: e.g., max 3 solo trades per agent per degraded session. After the cap, pause the agent and fire an alert. Set a wall-clock limit (e.g., 30 minutes of degraded mode → halt and require operator resume). Publish to `_alert_manager` on degraded-mode entry.

---

## 2. Medium-Risk Issues and Missing Invariants

- **`route_order` (sync) callable on live mode intent**: `merid/event_venues/kalshi/order_router.py:747-753` rejects live intents with `"live_requires_async_route_order"`, but the sync function is still importable and could be called by new code. **Invariant that should hold:** all call sites producing live-mode `OrderIntent` must use `route_order_async`. Add a static assertion or deprecation wrapper.

- **Daily order counter never resets on date change in `OrderRouter`**: `execution/order_router.py::_maybe_reset_daily_counter` resets based on elapsed time from `_last_reset_day = time.time()`, not calendar midnight. If the server runs continuously, the counter rolls at a random time of day. **Invariant:** `max_daily_orders` cap must reset at UTC midnight, not 24h from startup.

- **`_tracked_positions` uses `order_id` as key but order_id may be empty string**: `trading_agent.py:1273` assigns `pos_id = result_payload.get("order_id") or market.market_id`. If `order_id` is absent, the market ticker is the key. Two fills on the same market (e.g., adding to a position) will silently overwrite the first `TrackedPosition`, losing stop-loss data. **Invariant:** each fill must produce a unique position entry; use a `uuid` fallback, not the market ID.

- **`record_close` in `PredictionMarketRisk` allows negative `contracts`**: `risk.py:276` does `exp.contracts -= contracts` without checking that `contracts <= exp.contracts`. An over-close (closing more than open) produces a negative contract count, corrupting the notional cap state. **Invariant:** `contracts_to_close ≤ exp.contracts` before decrement.

- **`ExecutionGuard` cooldown is global (5s between all trades)**: `merid/execution_guard.py` uses `_last_execution_at` as a single global cooldown, not per-domain or per-market. In a system with 8 agents on different markets, this serialises all order placements with a 5s gap. Combined with the 30s cycle interval, this artificially limits throughput. More critically, the cooldown state is not persisted — restart resets it, allowing a burst of orders immediately after recovery. **Invariant:** cooldown should persist to the same `data/kill_switch.json` file used by the kill switch.

- **`OrderRouterConfig.run_mode` defaults to `TradingMode.MOCK`**: `execution/order_router.py` — the default mode is MOCK. A misconfiguration where the router is instantiated without explicit mode in a production context would silently execute all orders against the simulator. **Invariant:** in any environment where `MERID_TRADING_MODE=live`, the router must fail loudly if not explicitly configured for live mode.

- **`simulate_paper_fill` uses `random.random()` (unseeded)**: `order_router.py:258` — partial fill probability and fill ratio are non-deterministic. Backtest replay using paper mode will produce different results each run, making regression testing unreliable. **Invariant:** backtests must use a seeded PRNG; paper trading uses OS entropy only in interactive sessions.

- **Circuit breaker check (`check_circuit_breaker`) is never called in the trading cycle**: `merid/prediction/risk.py:601-630` implements odds-move detection but `_run_cycle_body` in `trading_agent.py` never calls `self._risk.check_circuit_breaker(market.market_id)`. The method is dead code in the live path. **Invariant:** circuit breaker must be checked before evaluating a signal for any market that has live price data.

- **Stop-loss `_check_stop_losses` runs before `_session_guard.is_trading_allowed`**: `trading_agent.py:265-270` — this is intentional (close positions even outside session). But the `_check_stop_losses` places orders via `_kalshi_place_order` without checking `_venue_gate.mode`. If the mode is MOCK, stop-loss closes will simulate fills, clearing `_tracked_positions` as if real closes happened. **Invariant:** stop-loss close orders must always use live execution regardless of mode.

- **`route_batch_orders_async` has no aggregate risk check before dispatch**: `order_router.py:855-880` validates each order individually but does not compute total batch notional against any cap. Five concurrent $900 orders against a $5,000 portfolio cap would each individually pass a $1,000 per-order limit but together exceed the cap. **Invariant:** batch submission must compute aggregate notional and reject or truncate before dispatch.

- **`_resolve_mode` fallback chain is silently lossy**: `order_router.py:198-206` — if `get_trade_mode()` raises, it silently falls back to `get_venue_gate().mode`. If the venue gate's mode differs from the trade mode controller (e.g., one is `LIVE`, the other `PAPER`), the resolved mode is silently wrong. **Invariant:** mode sources must agree; a mismatch should raise, not silently prefer one source.

---

## 3. Recommended Invariants, Simulations, and Canary Checks

### Invariants (plain text)

1. **Total notional across all agents ≤ `max_total_notional_usd` at all times.** Requires a shared singleton risk manager, not per-agent instances.
2. **No order leaves the system without passing both `ExecutionGuard.pre_trade_check` AND `KalshiRiskManager.check_order`.** Currently, paper/mock mode bypasses `ExecutionGuard`; live mode bypasses the agent-level `PredictionMarketRisk`.
3. **Every `TrackedPosition` entry corresponds to an unambiguously open, venue-confirmed position.** GTC-resting orders must not create `TrackedPosition` until a fill event is confirmed.
4. **`_is_live_fill` is derived from `OrderResult.mode`, never from a payload dict field.**
5. **Kill switch activation (any layer) propagates to all running agents within one cycle interval.** Currently, `ExecutionGuard` kill switch and `PredictionMarketRisk.halt()` are independent; an operator triggering one does not trigger the other.
6. **After a stop-loss fails N times, the agent halts and an operator alert fires within 60 seconds.**
7. **Swarm-degraded mode has a maximum wall-clock duration; agents auto-halt after the limit.**
8. **Checks 12-14 in `PredictionMarketRisk.check_order` are exercised on every live order with real orderbook data.**
9. **Daily PnL counters reset at UTC midnight, not at an arbitrary 24h interval from startup.**
10. **The `record_close` call never produces a negative contract count in any market exposure record.**

### Suggested Simulations and Tests

| Scenario | What to Test | Pass Criterion |
|---|---|---|
| **Kill switch mid-fill** | Activate global kill switch while 3 GTC orders are resting on the venue. | All resting orders are cancelled within 2 cycles; no new orders placed after kill. |
| **Consensus service outage** | Simulate 0 consensus responses for 10 minutes across all agents. | All agents pause after `_MAX_SOLO_SECONDS`; operator alert fires; no order storm during degraded window. |
| **Venue API 429 storm** | Configure mock client to return HTTP 429 for 60s, then recover. | Circuit breaker opens; backoff respected; no duplicate orders on recovery. |
| **Partial fill + WS drop** | Place an order that partially fills, then drop the WS connection. | Position size in risk manager matches partial fill quantity; remaining open order is reconciled on WS reconnect. |
| **Multi-agent correlated entry** | 8 agents simultaneously signal BUY on the same underlying. | Category cap fires before the 5th order; remaining 3 are rejected with clear reason. |
| **Stop-loss close failure** | Mock the close API to always return error for 5 cycles. | Agent pauses; alert fires; audit trail records all failed attempts. |
| **Mode switch PAPER→LIVE mid-session** | Switch `VenueGate.mode` from PAPER to LIVE while 2 paper positions are open. | MERID does not attempt to close paper positions via live API; paper positions are clearly labelled as simulation artifacts. |
| **Agent restart with open positions** | Restart `AgentGrid` with open positions on Kalshi. | Positions are re-loaded from venue via reconciliation loop before new orders are evaluated; no duplicate entries. |

### Canary Checks for New Strategies / Code

- Before promoting a new agent to paper mode, run `merid/agent_gauntlet.py` and require all 8 SLOs to pass for ≥ 20 cycles.
- Add a nightly canary that calls `trading/reconciliation.py::run_reconciliation()` against paper portfolio state and alerts if `all_ok = False`.
- For any new order route or code path, add a test that calls `route_order_async` with `mode=LIVE` in isolation and verifies it returns `rejected` when `risk_controller.can_trade() = False`.
- Alert on `orders_placed / cycles_run > 0.8` per agent per hour (sustained high order rate may indicate a runaway loop rather than genuine edge).

---

## 4. Design-Level Execution Risks

### 4.1 No Single Source of Truth for Open Positions

MERID maintains open positions in at least **five separate stores**:
1. `KalshiTradingAgent._tracked_positions` (per-agent in-memory dict)
2. `PredictionMarketRisk._exposures` (per-agent in-memory dict)
3. `KalshiRiskManager._state.category_notional` (global, but only updated for live non-simulated fills)
4. `PaperSession` open trades (paper only)
5. `trading/reconciliation.py` snapshot (computed on demand)

None of these are authoritative; all are derived from event-sourced updates that can be missed or double-counted (see BUG-02, BUG-06). In a crash-restart scenario, only the Kalshi venue has ground truth. The reconciliation loop exists but runs as a background task that "auto-fixes critical discrepancies" — fix semantics and tolerated delta thresholds are not documented.

**Risk:** After any unclean shutdown, MERID may restart with zero internal exposure state and begin placing new orders without knowing about positions still open on Kalshi, leading to unintended position accumulation.

**Recommendation:** Implement a mandatory "position reconciliation" gate in `AgentGrid.start()` that must complete before any agent is allowed to call `_run_cycle`. The gate fetches current Kalshi positions via REST, populates all internal stores, and logs the reconciled state to the audit trail.

---

### 4.2 LLM-Adjacent Agents Can Signal Without Deterministic Safety Gating

The swarm consensus path (`_submit_to_consensus`, `_get_consensus`) uses LLM-based agents to produce `consensus_direction` and `consensus_confidence`. The agent then uses consensus confidence to directly override `signal.edge.confidence` (line 367-368 of `trading_agent.py`):
```python
signal.edge.confidence = consensus.consensus_confidence
```
A hallucinating or adversarially prompted LLM agent could report `consensus_confidence=1.0` on any direction, bypassing the strategy's own edge estimate and overriding the Kelly fraction toward maximum size. There is no sanity bound on `consensus_confidence` before it is used to set position size.

**Risk:** Prompt injection or LLM instability could cause all agents to allocate maximum size on a low-edge trade. The pre-trade risk check will still enforce contract limits, but not the quality of the sizing decision.

**Recommendation:** Clamp `consensus.consensus_confidence` to a maximum of `signal.edge.confidence * 1.5` before injection. Require consensus confidence to pass a statistical plausibility check (e.g., Brier calibration weight > 0.3) before it modifies sizing.

---

### 4.3 Error Handling Gutter — Silent `except Exception: pass` Pattern

Across `_execute_signal` there are approximately **12 `except Exception as exc: self.logger.debug(...)` blocks** (lines 1165, 1216, 1253, 1268, 1287, 1320, 1355, 1380, 1408, 1438, 1461). Every post-fill bookkeeping action — realized edge store, risk manager update, paper session, rebalancer, reflection system, reward engine — is silently discarded on any exception.

This is a reasonable pattern for non-critical observability components, but it extends to `risk_mgr.record_order()` (line 1320), which **is** a safety-critical write. If `KalshiRiskManager.record_order` throws (e.g., a threading bug), the fill proceeds but the risk state is not updated. This is the same failure mode as BUG-06 but arriving from the opposite direction.

**Risk:** A threading bug or attribute error in the risk manager silently decouples risk state from actual exposure. The system continues trading past all limits without any signal that limits are being violated.

**Recommendation:** Separate the exception scopes: keep `debug`-level silencing for observability components (calibration, reflection, reward engine), but let exceptions from `risk_mgr.record_order()` propagate (or at minimum log at `ERROR` and increment a counter that feeds the kill-switch error threshold).

---

### 4.4 Rebalancer Can Place Live Orders After Every Fill Without Aggregate Limit

`trading_agent.py:1363-1374` — after every successful fill, the portfolio rebalancer is invoked and, if not simulated, will immediately execute rebalance orders via the live Kalshi client. There is no rate limit, cooldown, or minimum-move threshold documented at this call site. If 8 agents fill in rapid succession (e.g., a new market window opens), the rebalancer may fire 8 times in quick succession, placing potentially 8 × N rebalance orders with no coordination.

**Risk:** Rebalancer storms — a cascade of fills triggering cascading rebalance orders, each of which counts toward the daily order cap but bypasses the per-agent order-window limit (since they come from the rebalancer, not the agent's `orders_this_window` counter).

**Recommendation:** Add a rebalancer cooldown (e.g., minimum 5 minutes between rebalances) implemented via `get_execution_guard().pre_trade_check()` so the same global cooldown and daily caps that govern agent orders also govern rebalance orders.

---

*End of audit report. Total issues identified: 8 high-risk, 11 medium-risk, 4 design-level structural risks.*
