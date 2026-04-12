# MERID Kalshi Crypto Trading System — Halt Conditions Audit

> **Generated**: 2026-04-12  
> **Scope**: All conditions in the MERID codebase that can halt, block, or degrade crypto trading on Kalshi.  
> **Constraint**: Read-only audit — no code changes.

---

## Top 5 Most Dangerous Halt Conditions

1. **P0 — Kill switch TRIGGERED** (`merid/risk/kill_switches.py`): Global `_global_kill = True` — blocks *all* orders across *all* agents and cancels all open orders. Manual reset required.
2. **P0 — Phantom kill switch armed** (`merid/reconciliation/__init__.py`): Position mismatch between MERID and Kalshi — blocks every `check_order()` call in KalshiRiskManager. Manual reconciliation required.
3. **P0 — Execution gate BLOCKED** (`core/execution_gate.py`): Aggregation of critical reasons (kill switch, recon discrepancies, dead WS, circuit breaker OPEN) — blocks all trading via `is_execution_blocked()`.
4. **P0 — Kalshi WebSocket "failed"** (`merid/event_venues/kalshi/ws.py` → `core/execution_gate.py`): No order-book data → execution gate BLOCKED (fail-closed). All agents stop placing orders.
5. **P0 — Kalshi authentication failure** (`merid/event_venues/kalshi/client.py`): RSA key missing or auth rejected → all API calls fail → no orders can be placed.

---

## Consolidated Halt Conditions Table

### P0 — Immediate Hard Halt (process crash, global kill, complete venue failure)

#### Core Infra / Event Loop / WS Feeds

| # | Subsystem | Log Message (Template) | Level | File:Function | Halt Type | Impact |
|---|-----------|----------------------|-------|---------------|-----------|--------|
| 1 | Kalshi WS | `"Failed to connect to Kalshi WebSocket: {e}"` | ERROR | `merid/event_venues/kalshi/ws.py:connect()` | Hard halt | WS never starts → no market data → execution gate blocks all orders. Raises to caller. |
| 2 | Kalshi WS | `"Kalshi WebSocket feed has failed (stale/dead)"` (BlockReason) | CRITICAL (gate) | `core/execution_gate.py:is_execution_blocked()` | Hard halt | `ws_health_status == "failed"` → gate state=BLOCKED → all order submission blocked. |
| 3 | Kalshi WS | `"Kalshi WebSocket error: {e}"` | ERROR | `merid/event_venues/kalshi/ws.py:listen()` | Hard halt (transient) | WS read loop error → triggers `_reconnect()`. While disconnected, gate sees "failed" and blocks orders. |
| 4 | Kalshi WS | `"Kalshi WS FATAL error code={code} msg={msg!r} ctx={context} — will disconnect and reconnect"` | ERROR | `merid/event_venues/kalshi/ws.py:_handle_error_message()` | Hard halt (transient) | Fatal codes: `auth_failed`, `invalid_token`, `rate_limited`. Forces disconnect+reconnect → gate BLOCKED until recovery. |
| 5 | Circuit breaker | `"Circuit breaker OPEN: {_cb_name}"` (BlockReason) | CRITICAL (gate) | `core/execution_gate.py:is_execution_blocked()` | Hard halt | Any named circuit breaker OPEN → gate state=BLOCKED → all orders blocked. |
| 6 | Execution gate | `"⛔ EXECUTION BLOCKED: {reasons_str}"` | WARNING | `core/execution_gate.py:is_execution_blocked()` | Hard halt | Gate transition to BLOCKED → session event recorded → all trading paths respect this. |

#### Kalshi Session / API / Auth

| # | Subsystem | Log Message (Template) | Level | File:Function | Halt Type | Impact |
|---|-----------|----------------------|-------|---------------|-----------|--------|
| 7 | Kalshi auth | `"Kalshi authentication failed: {e}"` | ERROR | `merid/event_venues/kalshi/client.py:_authenticate_password()` | Hard halt | Auth failure → no bearer token → all subsequent API calls fail. Raises to caller. |
| 8 | Kalshi auth | `"Failed to load Kalshi RSA key: {e}"` | ERROR | `merid/event_venues/kalshi/client.py:_authenticate_rsa()` | Hard halt | RSA key load failure → fallback to password auth attempted; if both fail, no API access. |
| 9 | Kalshi auth | `"RSA private key not loaded. Check credentials and private_key_path."` | — (raises RuntimeError) | `merid/event_venues/kalshi/client.py:_sign_headers()` | Hard halt | Every signed request fails → all order placement, position fetch, etc. blocked. |
| 10 | Kalshi auth | `"No RSA key source: set private_key_path or private_key_pem"` | — (raises ValueError) | `merid/event_venues/kalshi/client.py:_authenticate_rsa()` | Hard halt | No key configured → auth impossible → trading blocked. |
| 11 | Kalshi client | `"HTTP client not initialized before authentication"` | — (raises RuntimeError) | `merid/event_venues/kalshi/client.py:_authenticate()` | Hard halt | Client state corruption → auth cannot proceed. |
| 12 | Kalshi client | `"[kalshi] {operation_name} auth error {status_code}: {body_text}"` | WARNING | `merid/event_venues/kalshi/client.py:_make_request()` | Hard halt | 401/403 from Kalshi → returns OperationResult.fail → all API calls rejected. |
| 13 | Kalshi client | `"[kalshi] {operation_name} service unavailable (503)"` | ERROR | `merid/event_venues/kalshi/client.py:_make_request()` | Hard halt | Kalshi 503 → KalshiSessionError → venue completely unavailable. |

#### Kill Switch / Safety Circuit

| # | Subsystem | Log Message (Template) | Level | File:Function | Halt Type | Impact |
|---|-----------|----------------------|-------|---------------|-----------|--------|
| 14 | Kill switch | `"[risk] EMERGENCY STOP: {reason}"` | CRITICAL | `merid/risk/kill_switches.py:emergency_stop()` | Hard halt | Manual operator kill → `_global_kill = True` → blocks all orders globally + cancels all open orders. |
| 15 | Kill switch | `"[risk] DAILY LOSS KILL: ${loss} >= ${limit} (signals: {breaches})"` | CRITICAL | `merid/risk/kill_switches.py:record_pnl()` | Hard halt | Daily loss exceeds limit + multi-signal or single-step jump → global kill triggered. |
| 16 | Kill switch | `"[risk] POSITION LIMIT KILL: ${value} > ${limit} (signals: {breaches})"` | CRITICAL | `merid/risk/kill_switches.py:update_position_value()` | Hard halt | Position value exceeds limit by ≥20% or multi-signal breach → global kill triggered. |
| 17 | Kill switch | `"[risk] HALT TRANSITION → TRIGGERED \| reason=ERROR_THRESHOLD \| errors={n} threshold={t} \| top_classes={cls} \| signals={s} \| dedup_suppressed={d} \| action=all_trading_blocked."` | CRITICAL | `merid/risk/kill_switches.py:record_error()` | Hard halt | Error count ≥ threshold + (multi-signal or ≥150% runaway) → global kill. Default threshold: 50/hr (env `MERID_ERROR_THRESHOLD`). |
| 18 | Kill switch | `"[risk] KILL SWITCH: Canceling all open orders (reason: {reason.value})"` | CRITICAL | `merid/risk/kill_switches.py:_cancel_all_orders_async()` | Hard halt (cleanup) | After kill triggered in LIVE mode → batch-cancels all open Kalshi orders. |
| 19 | Kill switch | `"[risk] KILL SWITCH: Canceled {n} orders, {m} failed (reason: {reason})"` | CRITICAL | `merid/risk/kill_switches.py:_cancel_all_orders_async()` | Hard halt (cleanup) | Confirms order cancellation result. Trading remains halted until manual reset. |
| 20 | Kill switch | `"Kill switch is engaged"` (BlockReason) | CRITICAL (gate) | `core/execution_gate.py:is_execution_blocked()` | Hard halt | Gate check reads `risk_controller._global_kill` → adds critical reason → gate BLOCKED. |

#### Reconciliation & Order Gate

| # | Subsystem | Log Message (Template) | Level | File:Function | Halt Type | Impact |
|---|-----------|----------------------|-------|---------------|-----------|--------|
| 21 | Phantom kill | `"PHANTOM KILL SWITCH ARMED — {reason or 'phantom positions detected'}"` | CRITICAL | `merid/reconciliation/__init__.py:arm_phantom_kill_switch()` | Hard halt | Sets module-level `_phantom_kill_switch = True` → `KalshiRiskManager.check_order()` blocks every order. |
| 22 | Phantom kill | `"phantom_kill_switch:phantom positions detected — orders halted pending reconciliation"` | — (returns False) | `merid/event_venues/kalshi/kalshi_risk.py:check_order()` | Hard halt | Check #0 in KalshiRiskManager — first gate before any other risk check. Blocks all orders. |
| 23 | Phantom kill | `"phantom_kill_switch:unavailable — unexpected error, blocking order as fail-safe."` | ERROR | `merid/event_venues/kalshi/kalshi_risk.py:check_order()` | Hard halt | Fail-closed: error checking phantom status → order blocked for safety. |
| 24 | Recon critical | `"Kalshi venue reconciliation found {n} critical discrepancies"` (BlockReason) | ERROR | `core/execution_gate.py:is_execution_blocked()` | Hard halt | Reconciliation ran + found critical mismatches → gate state=BLOCKED. |
| 25 | Recon critical | `"Kalshi reconciliation: RAN_CRITICAL — blocking execution due to {n} critical discrepancies"` | ERROR | `core/execution_gate.py:is_execution_blocked()` | Hard halt | Logged when gate detects critical recon state. |

#### Venue Adapter / Order Router

| # | Subsystem | Log Message (Template) | Level | File:Function | Halt Type | Impact |
|---|-----------|----------------------|-------|---------------|-----------|--------|
| 26 | Order router | `"[order-router] Live order blocked by kill switch: {reason}"` | WARNING | `merid/event_venues/kalshi/order_router.py:_route_live()` | Hard halt | Kill switch check at order-router entry → returns OrderResult(rejected). |
| 27 | Order router | `"[order-router] Risk controller unavailable - blocking live order: {exc}"` | ERROR | `merid/event_venues/kalshi/order_router.py:_route_live()` | Hard halt | Fail-closed: if risk_controller import fails → block all live orders. |
| 28 | Order router | `"[order-router] Risk check failed - blocking live order: {exc}"` | ERROR | `merid/event_venues/kalshi/order_router.py:_route_live()` | Hard halt | Fail-closed: unexpected error in risk check → block order. |
| 29 | Venue adapter | `"Trading halted: {reason}"` (raises RuntimeError) | — | `merid/event_venues/kalshi/venue_adapter.py:_submit_live_order()` | Hard halt | Kill switch active → raises RuntimeError → order rejected at venue adapter level. |
| 30 | Venue adapter | `"VenueGate blocked: mode={mode} (paper/sim — no real orders)"` (raises RuntimeError) | — | `merid/event_venues/kalshi/venue_adapter.py:_submit_live_order()` | Hard halt | VenueGate in wrong mode → blocks all live orders. |
| 31 | KalshiRisk | `"KILL SWITCH ACTIVATED: {reason}"` | WARNING | `merid/event_venues/kalshi/kalshi_risk.py:_activate_kill_switch()` | Hard halt | KalshiRiskManager's own kill switch → halts all agents via DeploymentController. |

---

### P1 — Severe Functional Halt (trading heavily impaired for venue/asset/timeframe)

#### Kalshi Session / API / Limits

| # | Subsystem | Log Message (Template) | Level | File:Function | Halt Type | Impact |
|---|-----------|----------------------|-------|---------------|-----------|--------|
| 32 | Kalshi client | `"[kalshi] Circuit open for {operation_name}: {e}"` | WARNING | `merid/event_venues/kalshi/client.py:_make_request()` | Functional halt | Circuit breaker tripped for Kalshi API → all requests for that operation fail-fast → no orders placed until recovery. |
| 33 | Kalshi client | `"[kalshi] {operation_name} rate-limited (429), Retry-After={ra}, sleeping {wait}s"` | WARNING | `merid/event_venues/kalshi/client.py:_make_request()` | Functional halt | Kalshi 429 → exponential backoff → orders delayed/blocked until retries exhausted (max 3). |
| 34 | Kalshi client | `"[kalshi] {operation_name} business error {status}: {body}"` | ERROR | `merid/event_venues/kalshi/client.py:_make_request()` | Functional halt | 400/422 from Kalshi → KalshiBusinessError → order rejected. Persistent for config issues. |
| 35 | Kalshi client | `"[kalshi] {operation_name} timeout, retrying in {wait}s"` | WARNING | `merid/event_venues/kalshi/client.py:_make_request()` | Functional halt | Timeout → retries with backoff → if max retries exhausted, operation fails. |
| 36 | Kalshi client | `"[kalshi] {operation_name} connection error, retrying in {wait}s: {e}"` | WARNING | `merid/event_venues/kalshi/client.py:_make_request()` | Functional halt | Connection error → retries → if exhausted, Kalshi venue unavailable. |
| 37 | Kalshi client | `"[kalshi] Unexpected error in {operation_name}: {e}"` | ERROR | `merid/event_venues/kalshi/client.py:_make_request()` | Functional halt | Unexpected error → no retry → operation fails immediately. |
| 38 | Kalshi client | `"Batch cancel failed: {result.error}"` | ERROR | `merid/event_venues/kalshi/client.py:batch_cancel_orders()` | Functional halt | Cannot cancel orders → positions stuck, risk unmanaged. |
| 39 | Order router | `"[order-router] Live order blocked by KalshiRiskManager: {reason}"` | WARNING | `merid/event_venues/kalshi/order_router.py:_route_live()` | Functional halt | KalshiRiskManager rejects order → that specific order blocked by risk limits. |
| 40 | Order router | `"[order-router] KalshiRiskManager unavailable — blocking live order: {exc}"` | ERROR | `merid/event_venues/kalshi/order_router.py:_route_live()` | Functional halt | Fail-closed: risk manager import/init error → all live orders blocked. |

#### KalshiRiskManager — Pre-Trade Blocks

| # | Subsystem | Log Message (Template) | Level | File:Function | Halt Type | Impact |
|---|-----------|----------------------|-------|---------------|-----------|--------|
| 41 | KalshiRisk | `"bankroll_zero:current equity {eq} is at or below zero"` | — (returns False) | `merid/event_venues/kalshi/kalshi_risk.py:check_order()` | Functional halt | Zero equity → all risk-increasing orders blocked. |
| 42 | KalshiRisk | `"Kill switch active: {reason}"` | — (returns False) | `merid/event_venues/kalshi/kalshi_risk.py:check_order()` | Hard halt | KalshiRisk's own kill_switch_active flag → all orders blocked. |
| 43 | KalshiRisk | `"Daily loss ${loss} exceeds max ${limit}"` | — (returns False, triggers _activate_kill_switch) | `merid/event_venues/kalshi/kalshi_risk.py:check_order()` | Hard halt | Daily loss limit breached → activates kill switch → all subsequent orders also blocked. |
| 44 | KalshiRisk | `"Drawdown {pct} exceeds unwind threshold {threshold}"` | — (returns False, triggers _activate_kill_switch) | `merid/event_venues/kalshi/kalshi_risk.py:check_order()` | Hard halt | Drawdown exceeds unwind threshold → kill switch activated. |
| 45 | KalshiRisk | `"Drawdown {pct} exceeds halt threshold {threshold}"` | — (returns False) | `merid/event_venues/kalshi/kalshi_risk.py:check_order()` | Functional halt | Drawdown exceeds halt threshold (but below unwind) → order blocked but no kill switch. |
| 46 | KalshiRisk | `"Total notional ${total} exceeds max ${max}"` | — (returns False) | `merid/event_venues/kalshi/kalshi_risk.py:check_order()` | Functional halt | Portfolio notional limit hit → all new orders blocked until positions reduce. |
| 47 | KalshiRisk | `"Rate limit: {n} orders this minute"` / `"Rate limit: {n} orders this hour"` | — (returns False) | `merid/event_venues/kalshi/kalshi_risk.py:check_order()` | Functional halt | Internal rate limit → orders blocked temporarily. |

#### Kalshi WS / Data Feed

| # | Subsystem | Log Message (Template) | Level | File:Function | Halt Type | Impact |
|---|-----------|----------------------|-------|---------------|-----------|--------|
| 48 | Kalshi WS | `"RES-1: WS health transition {prev} → {new} (msg_rate={r}/s, last_msg_ago={s}s, queue={d}/{c})"` | WARNING | `merid/event_venues/kalshi/ws.py:_check_ws_health()` | Functional halt | WS health degrades to "degraded"/"failed" → REST failover enabled. If "failed", execution gate blocks. |
| 49 | Kalshi WS | `"RES-1: WS degraded — enabling REST polling failover (health={status})"` | WARNING | `merid/event_venues/kalshi/ws.py:_check_ws_health()` | Functional halt | WS degraded → REST polling activated. Reduced data quality/freshness. |
| 50 | Kalshi WS | `"WS message queue full — dropped oldest message (queue_size={sz}, total_overflows={n})"` | WARNING | `merid/event_venues/kalshi/ws.py:listen()` | Functional halt | Queue overflow → messages dropped → stale orderbook data → potential mispricing. |
| 51 | Kalshi WS | `"Kalshi reconnection failed: {e}"` | ERROR | `merid/event_venues/kalshi/ws.py:_reconnect()` | Functional halt | Reconnect attempt failed → stays disconnected → gate sees "failed" until next attempt succeeds. |

#### PM Spot Health / Price Feeds

| # | Subsystem | Log Message (Template) | Level | File:Function | Halt Type | Impact |
|---|-----------|----------------------|-------|---------------|-----------|--------|
| 52 | PM spot | `"[AGENT-VETO] pm_spot_hard_gate \| agent={name} asset={asset} status={status}"` | WARNING | `merid/prediction/trading_agent.py:_run_cycle()` | Functional halt | PM spot feed unhealthy for this agent's asset → cycle aborted → no orders for this agent. |
| 53 | PM spot | `"[AGENT-VETO] pm_spot_hard_gate \| agent={name} blocked_assets={list}"` | WARNING | `merid/prediction/trading_agent.py:_run_cycle()` | Functional halt | All-asset PM spot gate blocked → cycle aborted for agents without specific asset config. |
| 54 | PM spot | `"[AGENT-VETO] pm_spot_hard_gate check error (fail-closed): {exc}"` | WARNING | `merid/prediction/trading_agent.py:_run_cycle()` | Functional halt | Fail-closed: error in gate check → block cycle. |
| 55 | PM spot | `"get_pm_spot_health_all: failed to get snapshot — {exc}"` | ERROR | `merid/event_venues/kalshi/pm_spot_health.py:get_pm_spot_health_all()` | Functional halt | Cannot get spot health → all assets reported as LIVE_PRICE_FEED_UNHEALTHY → all PM gates blocked. |
| 56 | PM spot | `"[PM_SPOT_HEALTH] per_asset_gate: unknown asset={asset} — treating as blocked"` | WARNING | `merid/event_venues/kalshi/pm_spot_health.py:pm_spot_hard_gate_open_for_asset()` | Functional halt | Unknown asset → treated as blocked (fail-closed). |
| 57 | PM spot | `"[PM_SPOT_HEALTH] hard_gate=BLOCKED — one or more assets not ok"` | WARNING | `merid/event_venues/kalshi/pm_spot_health.py:log_pm_spot_health()` | Functional halt | Periodic log showing PM gate is blocking trading. |
| 58 | Price feed | `"{n} price feed(s) stale"` (BlockReason, critical if major_crypto group) | CRITICAL/WARNING (gate) | `core/execution_gate.py:is_execution_blocked()` | Functional halt | Major crypto (BTC/ETH/SOL) price feed stale >60s → gate BLOCKED (in production). Alt crypto stale is warning only. |

#### Kill Switch 3-Tier Escalation

| # | Subsystem | Log Message (Template) | Level | File:Function | Halt Type | Impact |
|---|-----------|----------------------|-------|---------------|-----------|--------|
| 59 | Kill switch | `"[risk] Tier 2 LIMITED: {metric} — fraction={pct}% of threshold. Order sizes reduced to {mult}%."` | WARNING | `merid/risk/kill_switches.py:_promote_tier()` | Functional halt | Tier 2 LIMITED: orders still placed but at reduced size (default 50%). Significant trading impairment. |
| 60 | Kill switch | `"[risk] Error threshold breached ({n}/{t}) but only {b}/{r} signals active — holding at LIMITED tier."` | WARNING | `merid/risk/kill_switches.py:record_error()` | Functional halt | Error threshold hit but insufficient signals for full kill → size reduced, monitoring for escalation. |
| 61 | Kill switch | `"[risk] Daily loss at limit but only {b}/{r} signals active — holding at LIMITED tier."` | WARNING | `merid/risk/kill_switches.py:record_pnl()` | Functional halt | Daily loss at limit + single signal → LIMITED tier, not yet full kill. |
| 62 | Kill switch | `"[risk] KILL SWITCH: Failed to cancel orders: {exc}"` | ERROR | `merid/risk/kill_switches.py:_cancel_all_orders_async()` | Functional halt | Kill switch triggered but order cancellation failed → positions remain open with no new orders. |

#### Order Router / Pre-Trade Gate

| # | Subsystem | Log Message (Template) | Level | File:Function | Halt Type | Impact |
|---|-----------|----------------------|-------|---------------|-----------|--------|
| 63 | Order router | `"[order-router] LIVE execution failed: {exc}"` | ERROR | `merid/event_venues/kalshi/order_router.py:_route_live()` | Functional halt | Order submission to Kalshi failed → order rejected. |
| 64 | Order router | `"[order-router] Pre-trade gate blocked: duplicate:{status} coid={coid} contract={ticker}"` | WARNING | `merid/event_venues/kalshi/order_router.py:_route_live()` | Functional halt | Pre-trade idempotency gate → duplicate order blocked. Prevents specific order, not all trading. |
| 65 | Order router | `"[order-router] Order group {group_id} triggered - initiating auto-cancel"` | WARNING | `merid/event_venues/kalshi/order_router.py` | Functional halt | Order group triggered → auto-cancel initiated → that group's orders are closed. |
| 66 | Order group | `"order_group_not_found:{id}"` / `"order_group_not_active:{id}"` / `"order_group_limit_exceeded:{id}"` | — (returns rejected) | `merid/event_venues/kalshi/order_router.py:_route_live()` | Functional halt | Order group lifecycle issues → specific order rejected. |
| 67 | Venue adapter | `"Failed to place Kalshi order: {exc}"` (raises RuntimeError) | ERROR | `merid/event_venues/kalshi/venue_adapter.py:_submit_live_order()` | Functional halt | Order submission failed at venue adapter level. |
| 68 | Venue adapter | `"Matching engine not available for paper trading"` (raises RuntimeError) | — | `merid/event_venues/kalshi/venue_adapter.py:_submit_paper_order()` | Functional halt | Paper mode matching engine unavailable → paper fills fail. |

---

### P2 — Degraded but Not Total Halt (subset of strategies/markets stand down)

#### Trading Agent Cycle Vetoes

| # | Subsystem | Log Message (Template) | Level | File:Function | Halt Type | Impact |
|---|-----------|----------------------|-------|---------------|-----------|--------|
| 69 | Session guard | `"[AGENT-VETO] session_guard \| agent={name} reason={reason}"` | INFO | `merid/prediction/trading_agent.py:_run_cycle()` | Partial stand-down | Kalshi maintenance window (Thu 3-5 AM ET) → agent cycle skipped. All agents affected during maintenance. |
| 70 | Trading agent | `"[AGENT-VETO] spot_strike_basis \| agent={name} market={id} basis={basis}"` | INFO | `merid/prediction/trading_agent.py:_run_cycle()` | Partial stand-down | Missing/invalid spot or strike data for specific market → that market skipped. Others continue. |
| 71 | Trading agent | `"[AGENT-VETO] no_markets \| agent={name} resolved=0"` | INFO | `merid/prediction/trading_agent.py:_run_cycle()` | Partial stand-down | No resolved markets for this agent → cycle does nothing. Other agents unaffected. |
| 72 | Trading agent | `"[AGENT-VETO] order_limit \| agent={name} limit={n} current={c}"` | INFO | `merid/prediction/trading_agent.py:_run_cycle()` | Partial stand-down | Per-window order limit hit for this agent → no more orders this window. Other agents unaffected. |
| 73 | Trading agent | `"stop_loss session cap breached — pausing agent {name}"` | WARNING | `merid/prediction/trading_agent.py:_check_stop_losses()` | Partial stand-down | Stop-loss cap → agent paused (`state.enabled = False`). Other agents continue. |
| 74 | Trading agent | `"Cycle error: {exc}"` | ERROR | `merid/prediction/trading_agent.py:_run_loop()` | Partial stand-down | Unhandled exception in cycle → error logged, agent retries next cycle. Not fatal. |
| 75 | Trading agent | `"Error evaluating {market_id}: {exc}"` | WARNING | `merid/prediction/trading_agent.py:_run_cycle()` | Partial stand-down | Strategy evaluation error for one market → that market skipped, others continue. |
| 76 | Trading agent | `"Error executing {market_id}: {exc}"` | WARNING | `merid/prediction/trading_agent.py:_run_cycle()` | Partial stand-down | Execution error for one market → that order fails, agent continues to next market. |
| 77 | Trading agent | `"Market resolution error: {exc}"` | WARNING | `merid/prediction/trading_agent.py:_resolve_markets()` | Partial stand-down | Cannot resolve markets → no candidates this cycle. |

#### KalshiRiskManager — Per-Order Blocks

| # | Subsystem | Log Message (Template) | Level | File:Function | Halt Type | Impact |
|---|-----------|----------------------|-------|---------------|-----------|--------|
| 78 | KalshiRisk | `"Order size {n} exceeds max {max}"` | — (returns False) | `merid/event_venues/kalshi/kalshi_risk.py:check_order()` | Partial stand-down | Single order too large → rejected; agent can retry with smaller size. |
| 79 | KalshiRisk | `"Order notional ${n} exceeds max ${max}"` | — (returns False) | `merid/event_venues/kalshi/kalshi_risk.py:check_order()` | Partial stand-down | Order notional too high → rejected; other orders may pass. |
| 80 | KalshiRisk | `"Position {n} would exceed per-contract limit {max}"` | — (returns False) | `merid/event_venues/kalshi/kalshi_risk.py:check_order()` | Partial stand-down | Per-contract position limit → that contract blocked, others OK. |
| 81 | KalshiRisk | `"Category '{cat}' notional ${n} exceeds cap ${max}"` | — (returns False) | `merid/event_venues/kalshi/kalshi_risk.py:check_order()` | Partial stand-down | Category cap → that category blocked, other categories OK. |
| 82 | KalshiRisk | `"Category '{cat}' contracts {n} exceeds cap {max}"` | — (returns False) | `merid/event_venues/kalshi/kalshi_risk.py:check_order()` | Partial stand-down | Category contract cap → that category blocked. |
| 83 | KalshiRisk | `"Post-fee edge {e} below minimum {min}"` | — (returns False) | `merid/event_venues/kalshi/kalshi_risk.py:check_order()` | Partial stand-down | Edge too thin → order rejected. Market-condition dependent; other markets may have sufficient edge. |
| 84 | KalshiRisk | `"Spread {n}¢ exceeds max {max}¢ (live orderbook check)"` | — (returns False) | `merid/event_venues/kalshi/kalshi_risk.py:check_order()` | Partial stand-down | Wide spread → that market blocked. Other markets with tighter spreads OK. |
| 85 | KalshiRisk | `"Depth {n} contracts below minimum {min} (live orderbook check)"` | — (returns False) | `merid/event_venues/kalshi/kalshi_risk.py:check_order()` | Partial stand-down | Thin book → that market blocked. Other markets with deeper books OK. |
| 86 | KalshiRisk | `"max_yes_price_cap:YES price {n}¢ exceeds cap {cap}¢ for {ticker}"` | WARNING | `merid/event_venues/kalshi/kalshi_risk.py:check_order()` | Partial stand-down | YES price cap → that specific order blocked. |

#### Execution Gate — Warning/Limited State

| # | Subsystem | Log Message (Template) | Level | File:Function | Halt Type | Impact |
|---|-----------|----------------------|-------|---------------|-----------|--------|
| 87 | Execution gate | `"Kalshi venue reconciliation has never run (fresh start)"` (BlockReason, warning) | INFO | `core/execution_gate.py:is_execution_blocked()` | Partial stand-down | Recon never ran → gate_state=LIMITED → new risk entries blocked, reduce/close OK. Transient at startup. |
| 88 | Execution gate | `"PnL sources diverge by ${n}"` (BlockReason, warning) | WARNING (gate) | `core/execution_gate.py:is_execution_blocked()` | Partial stand-down | PnL consistency check failed → gate_state=LIMITED → sizing unreliable, new entries blocked. |
| 89 | Execution gate | `"GATE WHITELIST VIOLATION: source={s!r} attempted to set gate=limited"` | ERROR | `core/execution_gate.py:is_execution_blocked()` | Non-blocking | Warning from non-whitelisted source → rejected, does NOT cause limited state. Diagnostic only. |

#### Kill Switch Tier 1 — Warning Only

| # | Subsystem | Log Message (Template) | Level | File:Function | Halt Type | Impact |
|---|-----------|----------------------|-------|---------------|-----------|--------|
| 90 | Kill switch | `"[risk] Tier 1 WARNING: {metric} — fraction={pct}% of threshold. Monitor closely. Trading continues normally."` | WARNING | `merid/risk/kill_switches.py:_promote_tier()` | Non-blocking | Tier 1 alert only — trading continues at full size. Operators should monitor. |
| 91 | Kill switch | `"[risk] Exempt error recorded (class={cls}, severity={sev}, not counted toward budget)."` | WARNING | `merid/risk/kill_switches.py:record_error()` | Non-blocking | Exempt error class (MEDIUM/LOW severity) → logged but does NOT consume error budget. |

#### Event Loop / Observability (Advisory Only)

| # | Subsystem | Log Message (Template) | Level | File:Function | Halt Type | Impact |
|---|-----------|----------------------|-------|---------------|-----------|--------|
| 92 | Event loop | `"event_loop_lag_halt_band: lag={n}ms halt_band_ms={t} ... [ADVISORY — no kill switch triggered]"` | WARNING | `observability/event_loop_monitor.py:_monitor_loop()` | Non-blocking | Extreme lag (>2000ms default) → advisory counter only. NEVER triggers kill switch or gate. |
| 93 | Event loop | `"Event loop DEGRADED [advisory]: lag={n}ms (crit threshold={t}ms) — no trading halt triggered"` | WARNING | `observability/event_loop_monitor.py:_monitor_loop()` | Non-blocking | `_degraded = True` flag set → dashboard display only. GATE_LIMITED_WHITELIST prohibits loop_lag. |
| 94 | Event loop | `"MERID_LOOP_LAG_KILL_SWITCH_ENABLED=true — halt-band kill-switch path enabled (non-prod only)."` | ERROR | `observability/event_loop_monitor.py:_monitor_loop()` | Non-blocking | Flag guard present but even when set, NO kill switch is actually activated. Documentation marker only. |
| 95 | Event loop | `"High-lag profile captured: {n}ms, {t} active tasks."` | WARNING | `observability/event_loop_monitor.py:_capture_high_lag_profile()` | Non-blocking | Diagnostic capture — no trading impact. |
| 96 | Event loop | `"Error in event loop monitor: {exc}"` | ERROR | `observability/event_loop_monitor.py:_monitor_loop()` | Non-blocking | Monitor itself errored → backs off 1s. No trading impact. |

#### Kalshi WS — Non-Fatal Warnings

| # | Subsystem | Log Message (Template) | Level | File:Function | Halt Type | Impact |
|---|-----------|----------------------|-------|---------------|-----------|--------|
| 97 | Kalshi WS | `"Kalshi WS error code={code} msg={msg!r} ctx={ctx} — continuing"` | WARNING | `merid/event_venues/kalshi/ws.py:_handle_error_message()` | Non-blocking | Warn-level error codes: `invalid_channel`, `bad_request`, `unknown_ticker` → logged, processing continues. |
| 98 | Kalshi WS | `"WS seq gap: market={id} expected={e} got={g} gap={n}"` | WARNING | `merid/event_venues/kalshi/ws.py:_check_sequence()` | Non-blocking | Sequence gap detected → orderbook snapshot invalidated for that market. Data quality issue, not halt. |
| 99 | Kalshi WS | `"Malformed WS JSON (dropped): {e}"` | WARNING | `merid/event_venues/kalshi/ws.py:listen()` | Non-blocking | Single malformed message dropped. Processing continues. |
| 100 | Kalshi WS | `"Slow WS handler: {n}ms for type={t} market={m}"` | WARNING | `merid/event_venues/kalshi/ws.py:_process_queue()` | Non-blocking | Handler took >50ms → logged as suspicious. No halt. |

#### Reconciliation — Non-Blocking

| # | Subsystem | Log Message (Template) | Level | File:Function | Halt Type | Impact |
|---|-----------|----------------------|-------|---------------|-----------|--------|
| 101 | Reconciliation | `"No adapter for venue {name}"` | WARNING | `merid/reconciliation/venue_reconciler.py:reconcile()` | Non-blocking | Missing venue adapter → reconciliation incomplete but trading continues. |
| 102 | Reconciliation | `"Failed to fetch positions from {venue}: {e}"` | ERROR | `merid/reconciliation/venue_reconciler.py:reconcile()` | Non-blocking | Position fetch failed → recon cycle incomplete; next cycle may succeed. |
| 103 | Reconciliation | `"Paper engine positions unavailable: {e}"` | WARNING | `merid/reconciliation/venue_reconciler.py:reconcile()` | Non-blocking | Paper engine unavailable → recon partial. Not blocking. |

#### Error Classification (trading_agent.py) — Budget Impact Reference

| # | Error Class | Severity | Budget-Exempt? | Typical Trigger |
|---|-------------|----------|----------------|-----------------|
| 104 | `gate_blocked` | LOW | Yes | Kill switch, execution gate, halted agent — self-referential, must not exhaust budget |
| 105 | `paper_session_error` | LOW | Yes | Paper fill bookkeeping failed |
| 106 | `order_group_not_found` | MEDIUM | Yes | Order group expired before action |
| 107 | `order_group_triggered` | LOW | Yes | Order group already triggered/resolved |
| 108 | `market_closed` | MEDIUM | Yes | Market not accepting orders |
| 109 | `stale_snapshot` | MEDIUM | Yes | Snapshot age guard tripped |
| 110 | `risk_violation` | CRITICAL | No | Bankroll zero, drawdown exceeded — counts toward budget, can trigger kill |
| 111 | `low_edge` | LOW | Yes | Post-fee edge insufficient |
| 112 | `spread_too_wide` | LOW | Yes | Orderbook spread exceeds config |
| 113 | `depth_insufficient` | LOW | Yes | Orderbook depth below minimum |
| 114 | `risk_check_blocked` | MEDIUM | Yes | KalshiRiskManager position/notional rejection |
| 115 | `min_notional` | LOW | Yes | Notional below minimum |
| 116 | `ws_reconnect` | LOW | Yes | WebSocket reconnecting |
| 117 | `rate_limit` | MEDIUM | Yes | Kalshi 429 / internal rate limit |
| 118 | `auth_error` | CRITICAL | No | 401/403 / authentication failure — counts toward budget |
| 119 | `exchange_error` | MEDIUM | Yes | Kalshi 5xx transient |
| 120 | `feed_timeout` | MEDIUM | Yes | Spot/feed data timeout |
| 121 | `network_timeout` | MEDIUM | Yes | Connection/read timeout |
| 122 | `connection_error` | MEDIUM | Yes | TCP connection failure |
| 123 | `stale_cache` | MEDIUM | Yes | Stale data cache |
| 124 | `consensus_timeout` | MEDIUM | Yes | Swarm consensus unavailable |
| 125 | `spot_stale` | MEDIUM | Yes | Spot price data stale |
| 126 | `insufficient_funds` | HIGH | No | Kalshi balance insufficient — counts toward budget |
| 127 | `no_open_orders` | LOW | Yes | No orders to cancel (normal state) |
| 128 | `no_position` | LOW | Yes | No position found (normal state) |
| 129 | `duplicate_order_rejected` | LOW | Yes | Idempotency-key collision (benign) |
| 130 | `order_rejected` | HIGH | No | Exchange rejected order (post-only cross, invalid size) — counts toward budget |
| 131 | `generic` | HIGH | No | Unclassified error — counts toward budget |

---

## Architecture Summary: How Halt Signals Flow

```
┌────────────────────────────────────────────────────────────────────────────┐
│                        TRADING AGENT (_run_cycle)                          │
│                                                                            │
│  Step 1: SessionGuard.is_trading_allowed() ─── maintenance window? ──→ VETO│
│  Step 1.5: pm_spot_hard_gate_open_for_asset() ─── stale feed? ──────→ VETO│
│  Step 2: _resolve_markets() ─── no markets? ────────────────────────→ VETO│
│  Step 5: _strategy.evaluate() ─── no action / veto basis ──────────→ SKIP│
│  Step 6: _execute_trade_signal() ──────────────┐                          │
│                                                 ▼                          │
│                                          ORDER ROUTER                      │
│                                     (_route_live / _route_paper)           │
│                                                 │                          │
│  ┌──────────────────────────────────────────────┤                          │
│  │  Gate 1: risk_controller.can_trade()         │ ← kill switch check      │
│  │  Gate 2: venue_gate.live_enabled             │ ← mode check             │
│  │  Gate 3: KalshiRiskManager.check_order()     │ ← 12 pre-trade checks    │
│  │    ├── Phantom kill switch                   │                          │
│  │    ├── Bankroll zero                         │                          │
│  │    ├── Kill switch active                    │                          │
│  │    ├── YES price cap                         │                          │
│  │    ├── Order size / notional limits          │                          │
│  │    ├── Position limit                        │                          │
│  │    ├── Category caps                         │                          │
│  │    ├── Total portfolio notional              │                          │
│  │    ├── Daily loss                            │                          │
│  │    ├── Drawdown                              │                          │
│  │    ├── Post-fee edge                         │                          │
│  │    └── Rate limit + Spread/Depth             │                          │
│  │  Gate 4: Pre-trade idempotency gate          │ ← duplicate check        │
│  │  Gate 5: Order group lifecycle               │ ← group active/limits    │
│  └──────────────────────────────────────────────┤                          │
│                                                 ▼                          │
│                                     KALSHI VENUE CLIENT                    │
│                                    (place_order_result)                    │
│                                                 │                          │
│  ┌──────────────────────────────────────────────┤                          │
│  │  Circuit breaker check                       │                          │
│  │  Request semaphore                           │                          │
│  │  Retry loop (max 3)                          │                          │
│  │  Auth header signing                         │                          │
│  └──────────────────────────────────────────────┘                          │
│                                                                            │
│  PARALLEL: ExecutionGate.is_execution_blocked() polled by UI + backend     │
│    ├── Kill switch engaged?                                                │
│    ├── Reconciliation critical?                                            │
│    ├── Price feeds stale (major crypto)?                                   │
│    ├── PnL consistency divergence?                                         │
│    ├── Kalshi WS "failed"?                                                 │
│    └── Circuit breaker OPEN?                                               │
│                                                                            │
│  PARALLEL: RiskController 3-tier escalation                                │
│    Tier 0 ACTIVE ──→ Tier 1 WARNING (70%) ──→ Tier 2 LIMITED (90%)        │
│          ──→ Tier 3 TRIGGERED (100% + multi-signal or runaway)             │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## Key Configuration Knobs Affecting Halt Behavior

| Env Variable | Default | Effect |
|---|---|---|
| `MERID_ERROR_THRESHOLD` | `50` | Errors/hr before kill switch escalation begins |
| `MERID_DEDUP_WINDOW_SECS` | `60.0` | Same-class errors within this window count as one |
| `MERID_WARN_PCT` | `0.70` | Tier 1 WARNING threshold (fraction of limit) |
| `MERID_LIMIT_PCT` | `0.90` | Tier 2 LIMITED threshold (fraction of limit) |
| `MERID_LOOP_LAG_HALT_BAND_MS` | `2000` | Advisory lag counter threshold (no halt) |
| `MERID_LOOP_LAG_KILL_SWITCH_ENABLED` | `false` | Guard flag for kill switch path (always disabled) |
| `MERID_EXEC_GATE_REQUIRE_KALSHI_WS` | `1` | Set `0` to allow trading without WS feed |
| `KALSHI_USE_DEMO` | `false` | Demo mode downgrades recon/feed severity to warning |

---

## Recovery Paths

| Halt Condition | Recovery Method |
|---|---|
| Kill switch TRIGGERED | Manual reset via `/api/risk/kill-switch/disable` or `risk_controller.reset(operator)` |
| Phantom kill switch | Fix position mismatch + clear `_phantom_kill_switch` flag |
| Execution gate BLOCKED | Resolve underlying reason(s) — gate auto-clears on next poll |
| Kalshi WS failed | Auto-reconnect with exponential backoff + jitter; gate clears when WS recovers |
| Kalshi auth failure | Fix credentials/key → restart or re-auth |
| Circuit breaker OPEN | Wait for auto-reset (half-open → closed) or manual reset via Risk panel |
| Recon critical discrepancies | Wait for next recon cycle or trigger manual reconciliation |
| PM spot feed stale | Coinbase streaming recovers → gate auto-opens |
| KalshiRisk kill switch | `reset_kill_switch()` via operator action |
| Session guard (maintenance) | Wait for maintenance window to end (auto-resolves) |
| Tier 2 LIMITED | Address the breached metric; tier auto-demotes when fraction drops below threshold |
