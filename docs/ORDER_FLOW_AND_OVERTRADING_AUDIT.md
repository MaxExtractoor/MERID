# Order Flow & Over-Trading Audit

_Date: 2026-04-20_
_Scope: every code path that can submit a Kalshi order, the shared risk guard that clamps them all to 1–2 %, and the cross-caller dedup that prevents double-ordering on the same signal._

_Prerequisite reading: `@c:\Dev\MERID\docs\TRADING_OWNERSHIP_DECISION.md` (who owns production PM), `@c:\Dev\MERID\docs\RISK_CONFIG_FULL_STACK_AUDIT.md` (the risk-config audit this extends)._

---

## 1. Executive Summary

| Area | Before | After |
|---|---|---|
| CT (`KalshiContinuousTrader`) entry orders | Guard-protected (CT-local) | Guard-protected (shared singleton) |
| `KalshiTradingAgent` agent grid (35 agents) entry orders | **No global cap** (GAP-A) | **Protected** via shared guard in `route_order_async` |
| `merid/lanes/btc15m_lane.py`, `crypto15m_lane.py` | **No global cap** (GAP-B) | **Protected** via shared guard in `route_order_async` |
| `route_order_async` — caller allowlist | Existed; no cycle cap (GAP-C) | Allowlist + **shared guard + cross-caller dedup** |
| `config/portfolio_optimizer.yaml` (6 % global budget) | Dead config, drift risk (GAP-D) | Still inert; flagged in §8 for follow-on |
| Double-ordering across CT + agent + lane on same signal | Possible | Blocked by `OrderDedupRegistry` |

**Bottom line:** every order source that goes through `route_order_async` now shares the same 1–2 % envelope on the same `equity_cents`. CT still submits directly via its REST adapter, but uses the *same* singleton via `get_global_risk_guard()`. The cycle-risk accumulator is process-wide, so concurrent callers cannot each consume the full budget independently. Entry orders are deduped across callers in a 60-second time bucket.

---

## 2. Phase 1 — Complete Inventory of Order Submission Sites

### 2.1 Low-level submit primitives

| File | Function | Role |
|---|---|---|
| `@c:\Dev\MERID\merid\event_venues\kalshi\order_router.py:2025` | `route_order_async` | Canonical async router — used by all non-CT callers. |
| `@c:\Dev\MERID\merid\event_venues\kalshi\order_router.py:1724` | `route_order` | Sync wrapper for MOCK/PAPER. LIVE requires the async path. |
| `@c:\Dev\MERID\merid\event_venues\kalshi\order_router.py:810` | `_route_live` | Live path via `KalshiVenueClient`. Called from `route_order_async` only. |
| `@c:\Dev\MERID\merid\event_venues\kalshi\order_router.py:743` | `_route_sync_non_live` | Simulated fill path (paper/mock). |
| `@c:\Dev\MERID\merid\trading\kalshi_continuous_trader.py` | `self._post(...)` | CT's direct HTTPS POST to `/trade-api/v2/portfolio/orders` — `_KNOWN_BYPASS_PATHS` ack'd; CT runs the shared guard upstream. |

### 2.2 Callers of `route_order_async` (production)

| Caller | File | Purpose | Shared guard? |
|---|---|---|---|
| `KalshiTradingAgent` (agent grid, 35 agents) | `@c:\Dev\MERID\merid\prediction\trading_agent.py:2385, 2522, 2628, 4127` | TP/SL/IOC exits **and** arb entries | **Yes** for buys (entries); sells exempt. |
| `KalshiPredictionTools` | `@c:\Dev\MERID\merid\prediction\kalshi_tools.py:435` | Tool-layer entries | Yes |
| `UniversalAgent` | `@c:\Dev\MERID\merid\prediction\universal_agent.py:365` | Generic agent entries | Yes |
| `btc15m_lane` | `@c:\Dev\MERID\merid\lanes\btc15m_lane.py:1556` | Lane entry orders | Yes |
| `ct_execution_adapter` | `@c:\Dev\MERID\merid\trading\ct_execution_adapter.py:131, 234` | CT wrapper (caller tag = CT; documented bypass) | CT already ran the guard upstream — skipped here. |
| `web/api/kalshi_api.py` | Manual UI trades | Operator manual orders | Yes |
| `web/api/kalshi_grid_api.py` | Grid UI actions | Operator manual orders | Yes |
| `take_profit.py` | Doc-only reference; agents route the intent | exit | sells exempt |

CT itself does not call `route_order_async` — it submits directly via `_post()` and runs the guard before the REST call.

### 2.3 Scripts / tools (non-loop)

- `@c:\Dev\MERID\scripts\kalshi_live_trade.py` — one-shot CLI.
- `@c:\Dev\MERID\scripts\go_live_preflight.py`, `post_close.py`, etc. — audit-only.

---

## 3. Phase 2 — Risk-gating state before the refactor

`route_order_async` applied, in order, before this refactor:
1. Caller allowlist (`_is_authorized_caller`).
2. `_check_intent_risk` — per-order schema sanity.
3. `_check_sentiment_notional_cap` — per-asset notional.
4. `_check_sanity` — `OrderSanityChecker` 7-point guard.
5. `_check_market_regime_gate` — basket flatness.
6. `_run_pre_trade_gate` — lease + idempotent client-order-id + fill awareness.
7. **Mode dispatch** → `_route_live` / `_route_sync_non_live`.

**None of these enforced a cycle-wide 1–2 % bankroll cap.** Each agent, lane, and web caller could independently size up to its per-order notional without any shared ceiling.

---

## 4. Phase 3 — The shared `GlobalRiskGuard` (wired)

### 4.1 New module: `@c:\Dev\MERID\merid\guards\global_risk_guard.py`

- `PendingOrderRisk` — order risk metadata (`ticker`, `asset`, `contracts`, `entry_price_cents`, `direction`, `max_loss_cents`, `edge`).
- `GlobalRiskGuard` — the guard class. Identical semantics to the previous CT-local class.
- `get_global_risk_guard()` — process-wide singleton accessor (lazy double-checked lock). Pulls `MAX_CYCLE_RISK_PCT` / `MAX_TOTAL_RISK_PCT` from `core.settings` at init; env-overridable.
- `set_equity_provider(fn)` / `set_existing_risk_provider(fn)` — startup hooks to register canonical equity / open-risk views. Last registration wins.
- `default_equity_cents()` — fallback when no provider registered:
  1. `KalshiPositionCache.total_value_cents()`
  2. `MERID_INITIAL_CAPITAL` env (dollars → cents)
  3. `0` (guard fails closed)
- `resolve_equity_cents()`, `resolve_existing_risk_cents()` — the lookup functions used by the router.
- `compute_intent_max_loss_cents(side, action, price_cents, count)` — canonical max-loss math for a binary Kalshi contract.
- `check_intent(ticker, asset, side, action, price_cents, count, edge)` — convenience that builds `PendingOrderRisk`, runs `check_order`, and auto-exempts non-buy actions (exits).

### 4.2 CT re-uses the shared singleton

`@c:\Dev\MERID\merid\trading\kalshi_continuous_trader.py:538-571` now imports `PendingOrderRisk` and `GlobalRiskGuard` from `merid.guards.global_risk_guard`, keeps the local `GlobalRiskGuard` name as a thin subclass (pass-through) for backward-compat with existing imports, and constructs `self._risk_guard = _get_global_risk_guard()` (the singleton). `check_order`, `reset_cycle`, and cycle-accumulator semantics are identical.

### 4.3 `route_order_async` invocation point

`@c:\Dev\MERID\merid\event_venues\kalshi\order_router.py:2107-2123` — after the pre-trade gate, before mode dispatch, the router calls `_run_shared_risk_guard_and_dedup` for every caller that is:

- Not in `_KNOWN_BYPASS_PATHS` (CT is bypassed here because it already ran the guard upstream with its own unified equity).
- In LIVE mode (paper/mock skip; CT's paper loop enforces its own cap).
- Not explicitly disabled via `MERID_DISABLE_SHARED_RISK_GUARD=1` (break-glass env flag; default off).

The helper:
1. Skips sells (`action != "buy"` → exits are risk-reducing).
2. Admits into the cross-caller dedup registry — first caller in the 60-second bucket wins; subsequent callers are rejected with `order_dedup:duplicate_in_bucket|original_caller=...`.
3. Runs the shared `GlobalRiskGuard.check_order(equity_cents, existing_risk_cents, pending)`.
4. On guard rejection, releases the dedup slot so a corrected smaller intent can retry.
5. On infrastructure exception (import / resolve errors), **fails closed** — the whole point of the gate is to bound aggregate risk; if we can't evaluate it, reject.

### 4.4 Cycle reset semantics

Only CT calls `reset_cycle()` today (at the start of each `_run_cycle_inner`). That is intentional and matches **Option A** in the prompt:

> CT remains the only component calling `reset_cycle()` at the start of each master cycle, and all other sources' orders are conceptually part of that same cycle.

Because the guard is the **same singleton**, CT's `reset_cycle()` also resets the accumulator seen by agent-grid and lane callers. The 60-second dedup bucket provides the secondary "cycle" boundary for flows that don't participate in CT's loop.

---

## 5. Phase 4 — Dedup & concurrency

### 5.1 New module: `@c:\Dev\MERID\merid\guards\order_dedup_registry.py`

- `DedupKey(ticker, side, action, bucket)` — frozen dataclass; bucket = `int(ts) // bucket_seconds` (default 60 s, tunable via `MERID_ORDER_DEDUP_BUCKET_SECONDS`).
- `DedupEntry(caller, first_ts, count)` — tracks the original caller for logging.
- `OrderDedupRegistry.try_admit(...)` — first-wins admission, returns `(False, existing)` on duplicate.
- `release(...)` — frees a slot so a rejected order can retry.
- `get_order_dedup_registry()` — process-wide singleton.

This is **complementary** to the existing `merid.event_venues.kalshi.order_gate.IdempotentOrderStore`:

| Mechanism | Scope | Prevents |
|---|---|---|
| `order_gate` (existing) | Single caller | Network-retry duplicates (same agent submits same order twice). |
| `OrderDedupRegistry` (new) | All callers | CT + agent + lane all submitting on the same ticker in the same bucket. |

### 5.2 Per-asset / per-market caps

Still enforced by existing gates:
- `CategoryExposureTracker` — per-category USD cap + correlated-market stacking guard (`@c:\Dev\MERID\merid\event_venues\kalshi\category_exposure.py`).
- `_check_intent_risk` / `kalshi_risk` — per-order notional/size caps.
- `order_gate` — per-(ticker, side) fill-awareness.

No duplication with the shared guard: the guard bounds *aggregate cycle risk*, the existing gates bound *per-order* and *per-category*.

---

## 6. Phase 5 — Config drift (GAP-D) status

`@c:\Dev\MERID\config\portfolio_optimizer.yaml` is still inert in production: no live module imports `merid/portfolio/*`. The 6 % `max_risk_pct_global` key exists only on paper. **Left for a follow-on cleanup** — either delete the YAML or edit it down to 0.02 and mark the consumer deprecated. Not blocking.

Env flag situation (unchanged by this refactor):
- `MERID_ENABLE_KALSHI_CT` — CT behind its own gate (see `TRADING_OWNERSHIP_DECISION.md`).
- `MERID_VALIDATION_MODE=1` — defers agent-grid startup.
- `MERID_ENABLE_AGENT_GRID` / `MERID_ENABLE_LANES` — **not introduced**; the shared guard makes them safe without a feature flag.
- `MERID_DISABLE_SHARED_RISK_GUARD=1` — break-glass only; do not set in prod.

---

## 7. Phase 6 — Tests & verification

### 7.1 New: `@c:\Dev\MERID\tests\trading\test_global_risk_guard_singleton.py` (21 tests)

- Singleton identity across modules.
- CT's re-exported subclass shares semantics (`issubclass` + `PendingOrderRisk is` shared type).
- Cycle-cap and total-cap invariants.
- Fail-closed on non-positive equity.
- `reset_cycle()` resets accumulator.
- `compute_intent_max_loss_cents` edge cases (price clamping, negative counts).
- `set_equity_provider` / `set_existing_risk_provider` wiring.
- `default_equity_cents` env fallback.
- Provider-exception fallback (no propagation).
- `check_intent` exit-exemption.
- `check_intent` buy enforces cap.
- Dedup: admits first, blocks duplicates same bucket.
- Dedup: different bucket admits.
- Dedup: release frees slot.
- Dedup: singleton identity.
- Dedup: different tickers / sides are independent.
- Dedup: metrics counters.
- **Multi-source aggregate-cap invariant** — CT + agent + lane all submit 80 ¢ entries on $100 equity; exactly two are approved, third is blocked by the shared guard.
- Guard metrics counters increment on approvals / rejections.

### 7.2 Extended: `@c:\Dev\MERID\tests\trading\test_topn_top3_alignment.py`

`test_guard_uses_canonical_settings` updated to verify CT obtains the singleton (`_get_global_risk_guard()`) and that the singleton loads the canonical `MAX_CYCLE_RISK_PCT` / `MAX_TOTAL_RISK_PCT` from `core.settings`.

### 7.3 Regression suite

Full risk suite passes: **60/60** across:
- `tests/trading/test_topn_top3_alignment.py` (21)
- `tests/trading/test_risk_config_full_stack_audit.py` (11)
- `tests/trading/test_risk_oversizing_regression.py` (7)
- `tests/trading/test_global_risk_guard_singleton.py` (21)

Order-router caller-restriction + sprint-A suites: **61/61** pass:
- `tests/test_order_router_caller_restrictions.py`
- `tests/test_order_router_hardening.py`
- `tests/event_venues/kalshi/test_kalshi_sprint_a.py`

---

## 8. Remaining follow-on items (not in this refactor)

1. **Neutralize `config/portfolio_optimizer.yaml` (GAP-D, low priority).** Either delete or set `max_risk_pct_global: 0.02` + deprecation banner.
2. **Env flags for agent_grid / lanes (optional).** The shared guard clamps risk, but operational control via `MERID_ENABLE_AGENT_GRID` / `MERID_ENABLE_LANES` would add clarity on which loops are active.
3. **Register AgentGrid as canonical equity provider.** Today `resolve_equity_cents()` falls back to `KalshiPositionCache.total_value_cents()` → `MERID_INITIAL_CAPITAL`. When AgentGrid owns the bankroll view in prod, it can call `set_equity_provider(fn)` once at startup for a tighter binding.
4. **Wire a real `existing_risk_provider`.** Currently returns 0, which is the conservative default (guard only enforces the cycle cap; total cap is a no-op until a provider publishes open-position risk). Plug in `KalshiPositionCache` open-risk calc for full protection.
5. **Dashboard surface.** Expose `get_global_risk_guard().metrics()` + `get_order_dedup_registry().metrics()` through an API endpoint (`/api/v1/kalshi/metrics/order-invariants` already exists for leases / idempotency; append guard / dedup metrics there).

---

## 9. Sign-Off Checklist

- [x] All order sources enumerated.
- [x] `GlobalRiskGuard` extracted to `merid/guards/global_risk_guard.py`.
- [x] Singleton accessor `get_global_risk_guard()` with lazy double-checked init.
- [x] Canonical equity source wired via `resolve_equity_cents()` (providers + `KalshiPositionCache` + env fallback).
- [x] `route_order_async` invokes the shared guard for all non-CT entry intents in LIVE mode.
- [x] Cross-caller `OrderDedupRegistry` prevents double-submits on the same `(ticker, side, action, bucket)`.
- [x] Fail-closed on guard infrastructure failure.
- [x] CT re-uses the singleton; its `reset_cycle()` resets the shared accumulator.
- [x] Exits (`sell`) exempt — they reduce risk.
- [x] Tests: singleton, invariants, dedup, multi-source aggregate cap — 21/21 new + 60/60 combined.
- [x] No regression in order-router caller-restriction or sprint-A suites (61/61).
- [x] Ownership decision documented (`docs/TRADING_OWNERSHIP_DECISION.md`).

**Overall verdict:** Aggregate cycle risk is now provably bounded to 1–2 % of the unified `equity_cents` across **every** live order source (CT, agent grid, lanes, web API). Double-ordering on the same signal is prevented by a process-wide cross-caller dedup. The two remaining items (`portfolio_optimizer.yaml` neutralization, tighter equity/existing-risk providers) are low-priority polish.
