# Redundancy & Drift Audit — Kalshi Execution Stack

_Date: 2026-04-20_
_Scope: Phases 1, 2, 4 of the Deep Redundancy & Drift audit prompt. Phase 5 (prioritized cleanup plan) intentionally deferred — this document is the **ground-truth map** + **target architecture sketch** you react to before committing to refactors._

**Companion docs:**
- `docs/TRADING_OWNERSHIP_DECISION.md` — authoritative ownership statement (updated alongside this audit).
- `docs/RISK_CONFIG_FULL_STACK_AUDIT.md` — point-in-time risk audit (still valid).
- `docs/ORDER_FLOW_AND_OVERTRADING_AUDIT.md` — full wiring.

---

## 0. North-star architectural intent (benchmark)

1. **One canonical Kalshi executor** that owns sizing + risk + submit.
2. **One shared `GlobalRiskGuard`** (singleton) — 1–2 % cycle / total caps on unified `equity_cents`.
3. **Agents, lanes, tools, universals are signal/intent producers**, not independent executors.
4. **Configs are a single source of truth** — no dead knobs, no conflicting risk budgets.

Everything below is evaluated against this benchmark.

---

# Phase 1 — Redundancy & overlap mapping

## 1.1 Executor × Responsibility Matrix

Legend: ✅ owns · 🟡 partial / shared · ⬜ not involved · 🔴 drift (does work that belongs elsewhere).

| Component | Module | Signals | Sizing | Risk gating | Submit path | Intended role | Actual behavior today |
|---|---|---|---|---|---|---|---|
| **KalshiContinuousTrader (CT)** | `merid/trading/kalshi_continuous_trader.py` | ✅ (indicator stacks, per-asset edges) | ✅ (`TopNEdgeAllocator` + `BankrollManager`) | ✅ (calls shared `GlobalRiskGuard` singleton directly; also its own `KalshiRiskEngine`, `category_exposure`, filter pipeline) | 🔴 **direct `self._post("/portfolio/orders")`** — bypasses `order_router` | Per `TRADING_OWNERSHIP_DECISION.md`: *shadow/experimental* behind `MERID_ENABLE_KALSHI_CT` | Fully functional standalone trader. Shares the guard singleton ✓, but does not share lease/dedup/sanity/regime/sentiment checks wired into `route_order_async`. |
| **KalshiTradingAgent (AgentGrid)** | `merid/prediction/trading_agent.py` | ✅ (`KalshiStrategy`, `_model`, strike selector) | ✅ (agent-local; uses `get_prediction_risk()` singleton) | ✅ (`PredictionMarketRisk`, `VenueGate`, `SessionGuard`, strike selector) + ✅ (shared guard via `route_order_async`) | ✅ `route_order_async` (many sites: entry, TP, SL, IOC, arb) | **Canonical prod executor** per `TRADING_OWNERSHIP_DECISION.md` | Matches intent. One exception: `_kalshi_place_order` tool fallback paths at `trading_agent.py:4036/4045/4240` bypass `route_order_async`. 🔴 |
| **BTC15m Lane** | `merid/lanes/btc15m_lane.py` | ✅ (15m BTC setup, RCK integration) | ✅ (lane-local `_compute_size`, equity compounding) | ✅ (own `RiskDecision` flow) | ✅ `route_order_async` (line 1556) | **Intent producer under canonical executor** (per intent) | Actually acts as a full executor that happens to emit through `route_order_async`. Risk decisioning is lane-internal. 🟡 |
| **Crypto15m Lane** | `merid/lanes/crypto15m_lane.py` | ✅ | ✅ (lane-local sizing) | ✅ (own `risk_bus.publish_order_event`) | 🔴 **direct `self.kalshi.place_order(...)`** (line 1296) — **bypasses `route_order_async`** | Intent producer | Full executor, and its live path skips the shared guard, dedup, lease, sanity, regime, and category-exposure checks. **Hard drift.** |
| **Universal Agent** | `merid/prediction/universal_agent.py` | ✅ | ✅ | 🟡 (delegates to router) | ✅ `route_order_async` (line 365) | Intent producer | Matches intent. |
| **Kalshi Tools** (`_kalshi_place_order`) | `merid/prediction/kalshi_tools.py` | ⬜ | ⬜ | 🟡 | ⬜ **direct `KalshiVenueClient.place_order`** when not in demo mode | LLM-tool surface for agents | Called from `trading_agent.py` as a secondary submit path (quotes, fallbacks). 🔴 Second live submit path inside the canonical executor. |
| **Web — manual place order** | `web/api/kalshi_api.py::place_order` (~L2773) | ⬜ | 🟡 (caller-supplied size) | 🟡 | ✅ `route_order_async` (L2837) | UI-driven intent source | Matches intent. |
| **Web — grid trigger** | `web/api/kalshi_grid_api.py` (~L753) | ⬜ | 🟡 | 🟡 | ✅ `route_order_async` (L766) | UI-driven intent source | Matches intent. |
| **Web — FIX submit** | `web/api/kalshi_api.py::fix_submit_order` (L5852) | ⬜ | ⬜ | ⬜ (no guard wiring observed) | 🔴 direct FIX path | Legacy / experimental | Additional submit surface not audited in the risk chain. 🔴 |
| **Web — batch place** | `web/api/kalshi_api.py::batch_place_orders` (L2975) | ⬜ | ⬜ | ⬜ | 🔴 `client.batch_place_orders` direct | Admin/ops | Another bypass. 🔴 |
| **CT Execution Adapter** | `merid/trading/ct_execution_adapter.py` | ⬜ | ⬜ | ⬜ | ✅ `route_order_async` (shadow + Phase-2 live stub) | **Bridge** to migrate CT off direct HTTP onto `route_order_async` | Shadow mode only; `execute_live` exists but is not wired in CT's main loop. ⏸ stalled migration. |

### Summary of submit paths actually in use

| Path | Callers | Shared guard? | Dedup? | Lease? | Sanity/Regime? | Fill-awareness? |
|---|---|---|---|---|---|---|
| `route_order_async` (order_router.py L2025) | AgentGrid trading_agent (primary), btc15m_lane, universal_agent, kalshi_api place_order, kalshi_grid_api, ct_execution_adapter | ✅ (line 2121) | ✅ | ✅ | ✅ | ✅ |
| `route_order` (sync, order_router.py L1713) | Some legacy sync callers; rejects LIVE mode | ❌ **shared guard not wired** (only `_check_intent_risk`) | ✅ (via `_run_pre_trade_gate`) | ✅ | ✅ | ✅ |
| `CT._post("/portfolio/orders")` | CT main loop | ✅ (explicit `_risk_guard.check_order` call upstream) | ❌ no `order_dedup_registry` | ❌ no `contract_lease` | ❌ no `_check_sanity`/regime gate | ❌ no `IdempotentOrderStore` — uses own OrderTracker |
| `crypto15m_lane.self.kalshi.place_order` | Crypto15m lane live path | ❌ | ❌ | ❌ | ❌ | ❌ |
| `kalshi_tools._kalshi_place_order` → direct client | trading_agent quote/fallback paths, LLM tool invocation | ❌ | ❌ | ❌ | ❌ | ❌ |
| `kalshi_api.fix_submit_order` / `batch_place_orders` | Web admin | ❌ | ❌ | ❌ | ❌ | ❌ |

**Key observation:** the *declared* invariant ("all orders share the same guard and dedup") holds only for `route_order_async` callers plus CT (which reaches into the singleton by import, skipping everything else). Four other live submit paths bypass the chain entirely.

---

## 1.2 Duplicated logic

### 1.2.1 Two parallel allocators — `top3_edge_allocator.py` vs `topn_allocator.py`

| | `merid/trading/top3_edge_allocator.py` | `merid/trading/topn_allocator.py` |
|---|---|---|
| Class | `Top3EdgeAllocator` | `TopNEdgeAllocator` |
| Purpose | Top-3 selection + stateful batch lifecycle (PENDING/ACTIVE/CLOSING/CLOSED) | Fixed-fractional Top-N (0–3) selection with dynamic step-down |
| Data models | `EdgeCandidate`, `Top3Allocation`, `Top3Batch`, `BatchStatus` | `EdgeCandidate`, allocation tuples |
| Cap source | `TOP3_CYCLE_RISK_CAP_PCT` env | `TOPN_MAX_CYCLE_RISK_PCT` env + `GlobalRiskGuard` |
| Stateful | ✅ batch state in Cache adapter | ❌ pure function of inputs |
| Used by | `Top3BatchManager` (still active in CT for "mark_asset_filled") | CT main order loop (primary, when `_USE_TOPN_ALLOCATOR`) |

**Both are still imported and in use inside CT.** The `Top3` module supplies batch lifecycle tracking (which `TopN` doesn't have), so they're not fully interchangeable — but the `EdgeCandidate` dataclass and selection heuristics are near-duplicates. **Drift tag:** "unintentional redundancy — candidate for merge."

### 1.2.2 Risk gating — multiple layers, overlapping responsibilities

Inside a single `route_order_async` call the request is inspected by:

1. `_check_intent_risk` — field-level bounds (order_router L471) — **LEGACY per-intent guard**, runs before everything.
2. `_check_sentiment_notional_cap`.
3. `_check_sanity` — OrderSanityChecker (`merid/event_venues/kalshi/kalshi_risk.py` helpers).
4. `_check_market_regime_gate`.
5. `_run_pre_trade_gate` — lease + dedup + fill-awareness (`contract_lease`, `order_gate`).
6. `_run_shared_risk_guard_and_dedup` — **cross-caller** `order_dedup_registry` + `GlobalRiskGuard`.
7. Downstream, inside `_route_live`: `KalshiRiskManager`, `CategoryExposureTracker`, `SentimentBus` size halving, `BracketRiskManager`, per-market re-validation.

Plus, **outside** the router:
- `PredictionMarketRisk` (`merid/prediction/risk.py`) owned by AgentGrid.
- `RiskController` / kill switches (`merid/risk/kill_switches.py`).
- `ExecutionGuard` (`merid/execution_guard.py`) — CQI throttle.
- `KalshiRiskEngine` (CT-local).
- Lane-local `RiskDecision` flows in btc15m/crypto15m.

**Overlap patterns:**
- "Per-trade risk cap" is encoded in: `GlobalRiskGuard`, `TopNAllocatorConfig`, `portfolio_optimizer.yaml`, `kalshi_crypto_hedging.yaml`, `pm_profiles.yaml`, `PredictionMarketRisk`.
- "Category exposure" lives in both `CategoryExposureTracker` and `PredictionMarketRisk`.
- "Kill switch" exists in `RiskController`, CT's own halt flags, per-lane halt flags.

Some of this is intentional layering (agent-local sizing → portfolio-wide guard). Much is not.

### 1.2.3 Duplicated `min_edge` / edge-filter definitions

Edge thresholds are defined in **at least seven** places, with materially different numbers:

| Source | Early | Mid | Late | Terminal | Notes |
|---|---|---|---|---|---|
| `config/kalshi_agent_grid.yaml` (per-agent, highest) | 0.12 | 0.11 | 0.10 | 0.09 | Production-leaning |
| `config/kalshi_agent_grid.yaml` (per-agent, low tier) | 0.06 | 0.05 | 0.04 | 0.03 | Diverges >4× from the top tier |
| `config/trade_hold_config.yaml` | 0.08 | 0.07 | 0.06 | 0.06 | Different schema |
| `config/pm_profiles.yaml` (default profile) | 0.01 | 0.008 | 0.006 | 0.005 | **Order of magnitude lower** |
| `config/trading_constants.py` (env-backed) | 0.08 | 0.07 | 0.06 | 0.06 | Reads `MERID_PM_MIN_EDGE_*` |
| `config/kalshi_ct_risk_profiles.py` | n/a (profile-based) | | | | CT-specific; `KALSHI_CT_PROFILE=modern_tradeable_kalshi_v1` default |
| Per-asset agent specs (`config/*_15m_agent_spec.py`) | 0.02–0.05 flat | | | | Asset-specific |

**Drift tag:** "unintentional — candidate for consolidation into a single phase-based `EdgeThresholdTable` provider."

### 1.2.4 Duplicated order submission wrappers

- `route_order` (sync) + `route_order_async` — two codepaths that diverge subtly (shared guard wired only in async).
- `_kalshi_place_order` tool (`kalshi_tools.py`) — parallel submit path.
- `kalshi_api_retrofit.place_order_robust` — retry wrapper around the client; separate circuit breaker thresholds (`kalshi_api_robust.py` L329).
- `kalshi_rate_limit.place_order` — rate-limited wrapper.
- FIX path (`fix_submit_order`) — parallel transport.
- CT `self._post` — parallel transport.

---

# Phase 2 — Drift between code, docs, and configs

## 2.1 Docstring / doc vs reality

| Claim | Source | Reality | Verdict |
|---|---|---|---|
| "CT is legacy/research/optional — not part of the live AgentGrid PM path." | `kalshi_continuous_trader.py:646-651` | CT still runs behind `MERID_ENABLE_KALSHI_CT`; **when on, it is a fully-functional production trader** with its own submit path. | ⚠ **Partially true.** Matches `TRADING_OWNERSHIP_DECISION.md` ("shadow/experimental"). But "not part of live path" reads stronger than it is — CT *is* the live path in any deployment that sets `MERID_ENABLE_KALSHI_CT=1`. |
| "KalshiTradingAgent + AgentGrid + lanes + web API are canonical." | `TRADING_OWNERSHIP_DECISION.md:24` | True for AgentGrid, btc15m_lane, universal_agent, web `place_order`, web `kalshi_grid_api`. **False for crypto15m_lane** (bypasses `route_order_async`). | 🔴 drift |
| "Canonical submit router: `route_order_async`." | `TRADING_OWNERSHIP_DECISION.md:28` | Multiple live paths ignore it: CT, crypto15m_lane, kalshi_tools, fix_submit_order, batch_place_orders. | 🔴 drift |
| "Process-wide `GlobalRiskGuard` enforces 1–2 % caps on unified equity." | `global_risk_guard.py` + ownership doc | ✅ Singleton is the same instance for CT + `route_order_async`. **But** `equity_cents` provider is only registered if someone calls `set_equity_provider()` — otherwise falls back to `KalshiPositionCache.total_value_cents()` or `MERID_INITIAL_CAPITAL`. No startup registration was observed in `web/main.py`. | 🟡 partial drift — works via fallback but provider is not explicitly wired. |
| "Exits are exempt — they reduce exposure." | `check_intent` docstring | Enforced by `route_order_async` shared guard (action != "buy" → skip). `_run_pre_trade_gate` also gives sells a bypass (fill-awareness only on buys). | ✅ consistent. |
| "Sync `route_order()` must never be called in live mode." | `order_router.py:1798-1812` (fail-loud) | ✅ enforced. But sync path still exists and still performs risk checks — dead-code risk surface. | 🟡 keep-or-retire question. |
| "`MERID_ENABLE_KALSHI_CT=false` by default; AgentGrid owns PM execution." | `web/main.py:2975` log line | ✅ default matches. `.env` in the repo does **not** set `MERID_ENABLE_KALSHI_CT`, so CT is off unless explicitly enabled. | ✅ consistent. |
| "`MERID_PM_PROFILE=production` is incompatible with `MERID_ENABLE_KALSHI_CT=true`." | `merid/startup_validations.py:89` | ✅ enforced at startup. | ✅ consistent. |

## 2.2 Config drift audit

### 2.2.1 Risk-budget drift — **the 6 % vs 2 % contradiction**

| File | Knob | Value | Used by |
|---|---|---|---|
| `.env` | `MAX_CYCLE_RISK_PCT` | **0.02** (2 %) | `GlobalRiskGuard` singleton via `core.settings` |
| `.env` | `MAX_TOTAL_RISK_PCT` | **0.02** (2 %) | same |
| `config/portfolio_optimizer.yaml:29` | `max_risk_pct_global` | **0.06** (6 %) | Mean-variance optimizer selection (3 assets × 2 % max = 6 % framing) |
| `config/portfolio_optimizer.yaml:25` | `max_risk_pct_per_trade` | 0.02 | Per-trade cap — consistent with guard |
| `config/portfolio_optimizer.yaml:143,151` | profile-scoped | 0.06 | same 6 % framing inside profiles |
| `config/kalshi_crypto_hedging.yaml` | `per_trade_risk_pct_of_slice` | 0.5–1.0 **(units: % of slice, not of equity)** | Hedging engine |
| `merid/trading/topn_allocator.py` defaults | `max_cycle_risk_pct` | 0.02 | TopN allocator (✅ aligned) |

**Interpretation:** The "6 %" was authored pre-`GlobalRiskGuard`, when the sum of 3 concurrent 2 % trades could reach 6 % of equity. With the guard now enforcing **2 % total open risk**, the optimizer's 6 % budget is either:
- (a) **Dead** — guard clips first regardless of optimizer output, **or**
- (b) **Still active** on a path that does not flow through the guard (crypto15m_lane? portfolio manager?).

Until (b) is disproven, treat `max_risk_pct_global: 0.06` as **active & misaligned**.

### 2.2.2 Profile / enable-flag drift

| Flag | Default | Where read | Intent |
|---|---|---|---|
| `MERID_ENABLE_KALSHI_CT` | `false` (`merid/settings.py:301`) | `web/main.py:2955`, `kalshi_continuous_trader.py:400`, `startup_validations.py:81`, `pm_live_readiness.py:24`, `pm_bankroll_snapshot.py:25` | CT shadow/experimental. |
| `MERID_PROFILE` | `kalshi-only` (`.env`) | `web/main.py` | Disables non-Kalshi domains. |
| `MERID_PM_PROFILE` | — (not set in `.env`) | `startup_validations.py`, `pm_profiles.yaml` | "production" forces CT off. |
| `KALSHI_CT_PROFILE` | `modern_tradeable_kalshi_v1` | `kalshi_ct_risk_profiles.py:85` | CT-only edge floor profile. Ignored when CT is off. |
| `MERID_PM_LIVE_ENABLED` | `true` (`.env`) | VenueGate | PM live allowed. |
| `MERID_PM_TRADING_MODE` | `live` (`.env`) | VenueGate | Mode. |
| `KALSHI_ENV` | `live` (`.env`) | Kalshi client | Endpoint selection. |
| `USE_TOPN_ALLOCATOR` | `true` (inferred from CT init log) | CT-only | Activates TopN vs legacy sizing. |
| `TOP3_CYCLE_RISK_CAP_PCT` | — | `top3_edge_allocator.py:398` | Legacy cap; kept for rollback. |
| `MERID_PM_MIN_EDGE_{EARLY,MID,LATE,TERMINAL}` | 0.08/0.07/0.06/0.06 | `config/trading_constants.py` | Overrides `pm_profiles.yaml`. |

**Drift flags:**
- `KALSHI_CT_PROFILE` conditions edge floors that collide with `pm_profiles.yaml` — two profile systems for the same dimension.
- `MERID_ENABLE_AGENT_GRID` / `MERID_ENABLE_LANES` *do not exist* — there is no symmetric kill for the canonical executor. AgentGrid is started by `web/main.py` unconditionally. Lanes are imported and started by the lane registry (if configured).
- `.env` has `MERID_ENABLE_POLYMARKET=true` (line ~164) despite Polymarket being removed in the Kalshi-only refactor. **Dead, with drift risk** (confusing operators).

### 2.2.3 Inventory tag per config knob

| Knob | Status |
|---|---|
| `MAX_{CYCLE,TOTAL}_RISK_PCT = 0.02` | **Active & aligned** |
| `portfolio_optimizer.yaml: max_risk_pct_global: 0.06` | **Active & misaligned** (guard shaves to 2 %) |
| `portfolio_optimizer.yaml: max_risk_pct_per_trade: 0.02` | Active & aligned |
| `portfolio_optimizer.yaml` legacy USD caps (commented) | Inactive — documented deprecation, keep |
| `TOP3_CYCLE_RISK_CAP_PCT` | **Inactive / dead, but drift risk** (Top3 allocator still imported) |
| `KALSHI_CT_PROFILE` | Active when CT on — else dead; low drift risk (CT-scoped) |
| `MERID_PM_MIN_EDGE_*` | Active — but one of several parallel edge-threshold providers (see 1.2.3) |
| Per-asset `*_15m_agent_spec.py: min_edge_threshold` | Active per agent — overlaps AgentGrid YAML |
| `MERID_ENABLE_POLYMARKET=true` | **Dead** — Polymarket removed. Retire. |
| `MERID_ENABLE_UMA_ORACLE=true`, `MERID_ENABLE_CHAINLINK=false`, `MERID_ENABLE_AUGUR=false` (duplicated in `.env`) | Dead or stale given Kalshi-only profile |

---

# Phase 4 — Target architecture

## 4.1 Proposed minimal-disruption long-term design

The claim in `TRADING_OWNERSHIP_DECISION.md` is already 85 % the right design. What's missing is **making it the only way to submit**. The following design finishes that job without a rewrite.

### Control plane vs data plane

```
┌──────────────────────────────────────────────────────────────────────────┐
│                            DATA PLANE                                    │
│         (edge / intent producers — safe to multiply freely)              │
│                                                                          │
│  KalshiStrategy (per-agent)       BTC15mLane             Crypto15mLane   │
│  PredictionMarketModel            RCKIntegration         rck_dataclasses │
│  IndicatorStacks (per-asset)      LaneMetrics            …               │
│  Universal/Research agents        Debate orchestrator                    │
│  Web UI (manual intent)           Ops tools / scripts                    │
│                                                                          │
│  Output:  ────────────────►   OrderIntent   ────────────────►            │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                           CONTROL PLANE                                  │
│     (risk / sizing / submit — SINGLE chokepoint, no bypasses)            │
│                                                                          │
│   route_order_async(intent)                                              │
│     │                                                                    │
│     ├─ caller-audit (_is_authorized_caller)                              │
│     ├─ _check_intent_risk                (field bounds)                  │
│     ├─ _check_sentiment_notional_cap                                     │
│     ├─ _check_sanity                                                     │
│     ├─ _check_market_regime_gate                                         │
│     ├─ _run_pre_trade_gate               (lease + dedup + fill-aware)    │
│     ├─ _run_shared_risk_guard_and_dedup ─► GlobalRiskGuard (singleton)   │
│     │                                   ─► OrderDedupRegistry           │
│     │                                                                    │
│     ├─ _route_live  ──► KalshiVenueClient (REST/FIX) ──► Kalshi          │
│     └─ _route_sync_non_live ──► simulate_paper_fill                      │
│                                                                          │
│   Shared singletons (one-per-process, provider-backed):                  │
│     • GlobalRiskGuard       (2 %/2 % caps, unified equity_cents)         │
│     • OrderDedupRegistry    (cross-caller dedup, 60s buckets)            │
│     • ContractLeaseRegistry (per-contract TTL leases)                    │
│     • PreTradeGate + IdempotentOrderStore (deterministic client_order_id)│
│     • KalshiPositionCache   (equity + existing risk)                     │
└──────────────────────────────────────────────────────────────────────────┘
```

### Invariants (the whole point)

1. **No module outside `_route_live` / `_route_sync_non_live` calls `KalshiVenueClient.place_order`, `client.batch_place_orders`, FIX submit, or raw `httpx.POST /portfolio/orders`.** Enforced by:
   - A *unit* test that greps the repo for those symbols and fails on any new caller not in a tight allowlist.
   - Runtime caller-audit in `order_router` (already exists as `_is_authorized_caller`) — extend to hard-reject unauthorized modules.
2. `GlobalRiskGuard` is **the only** code that reads `MAX_CYCLE_RISK_PCT` / `MAX_TOTAL_RISK_PCT`. Every other "percent risk" knob either (a) feeds per-trade sizing *before* the guard, or (b) is removed.
3. `equity_cents` has exactly **one** canonical provider registered via `set_equity_provider(fn)` at startup. Fallbacks exist for tests; production registers explicitly.
4. **One** edge-threshold table keyed by `(asset, timeframe, phase)`. All `min_edge*` lookups go through it.

### Canonical executor choice

**Converge on `route_order_async` as the executor**, not on any class. Rationale:

- It is already the fat codepath (audit, guard, dedup, lease, gate, sanity, regime, per-market re-validation, live/paper split).
- Every component that matters (AgentGrid, btc15m_lane, web, universal, ct_execution_adapter) already uses it.
- Rebranding CT as "ExecutionCoordinator" would re-litigate ownership needlessly — `KalshiTradingAgent` + `route_order_async` already *are* the coordinator at the seam.
- CT becomes: **indicator + edge producer + bankroll/TopN sizing hint**, emitting `OrderIntent` through `route_order_async` via `CTExecutionAdapter.execute_live` (which already exists, Phase 2 stalled).

So the target executor is the **router function itself**, backed by the five singletons. "The executor" is not a class — it's a pipeline.

### Sequence (typical trade, target design)

```
Signal-source (e.g., BTC15mLane / KalshiTradingAgent / CT-via-adapter)
    │
    │  1. compute edge, phase, size-hint
    │
    ├─► OrderIntent(ticker, side, action, price_cents, count, source, agent_id,
    │              group_id, snapshot_ts, decision_trace_id, ...)
    │
    └─► await route_order_async(intent)
            │
            │  2. caller audit        (allowlist)
            │  3. field bounds        (_check_intent_risk)
            │  4. sentiment / sanity / regime
            │  5. lease acquire       (ContractLeaseRegistry)
            │  6. pre-trade gate      (IdempotentOrderStore → deterministic coid)
            │  7. cross-caller dedup  (OrderDedupRegistry, 60s buckets)
            │  8. GlobalRiskGuard     (2 %/2 % on equity_cents)
            │  9. branch:
            │         live → _route_live → client.place_order → Kalshi REST
            │         non-live → simulate_paper_fill
            │ 10. record_submitted / record_filled on gate
            │ 11. release lease / mark OG
            │
            └─► OrderResult(status, mode, fill, reason, latency_ms)
```

## 4.2 Mapping current modules to target design

| Module | Target role |
|---|---|
| `merid/event_venues/kalshi/order_router.py` | **Canonical executor** (the pipeline itself). Retain both `route_order_async` and `route_order`, but retire the sync live path (already rejects live) and either merge `_run_shared_risk_guard_and_dedup` into the sync path too or delete sync. |
| `merid/guards/global_risk_guard.py` | **Canonical risk gate singleton.** Keep as-is. Add explicit `set_equity_provider` call in `web/main.py` lifespan. |
| `merid/guards/order_dedup_registry.py` | **Canonical cross-caller dedup.** Keep. |
| `merid/event_venues/kalshi/contract_lease.py` | **Canonical lease.** Keep. |
| `merid/event_venues/kalshi/order_gate.py` | **Canonical idempotency.** Keep. |
| `merid/prediction/trading_agent.py` (`KalshiTradingAgent`) | **Pure intent producer.** Remove the `_kalshi_place_order` fallback paths at L4036/4045/4240; route them through `route_order_async`. |
| `merid/lanes/btc15m_lane.py` | **Intent producer.** Already uses `route_order_async`. ✅ |
| `merid/lanes/crypto15m_lane.py` | **Intent producer.** 🔴 Must be refactored: replace `self.kalshi.place_order(...)` at L1296 with `OrderIntent` → `route_order_async`. |
| `merid/prediction/kalshi_tools.py::_kalshi_place_order` | Either **retire** (tools become edge/research-only) or **internally delegate to `route_order_async`** preserving the tool signature. Preferred: retire as a live-submit path. |
| `merid/prediction/universal_agent.py` | **Intent producer.** ✅ already compliant. |
| `merid/trading/kalshi_continuous_trader.py` | **Edge/sizing research.** Route its `_post("/portfolio/orders")` through `CTExecutionAdapter.execute_live` → `route_order_async`. This is the existing Phase-2 migration — finish it. Deletion of direct HTTP path = Phase 3. |
| `merid/trading/ct_execution_adapter.py` | **Bridge (transitional).** Active during CT migration, retire after Phase 3. |
| `merid/trading/topn_allocator.py` | **Sizing helper** used by intent producers (CT + optionally AgentGrid) to propose `count` given edge + equity. Keep. |
| `merid/trading/top3_edge_allocator.py` + `top3_batch_manager.py` | **Retire after merge** into `topn_allocator`'s batch lifecycle (or extract `Top3BatchManager` as a small stateful helper on top of TopN). Currently *intentional redundancy* because CT still uses `Top3BatchManager.mark_asset_filled` for batch tracking. |
| `web/api/kalshi_api.py::place_order` | **Web intent source.** ✅ |
| `web/api/kalshi_api.py::batch_place_orders` | **Refactor**: either (a) loop `route_order_async` internally, or (b) restrict to admin/ops with explicit bypass audit annotation. |
| `web/api/kalshi_api.py::fix_submit_order` | Legacy / retire, or gate behind strict ops flag + route through a FIX adapter that still invokes `_run_shared_risk_guard_and_dedup`. |
| `web/api/kalshi_api_retrofit.py`, `kalshi_api_robust.py`, `kalshi_rate_limit.py` `place_order` variants | **Consolidate** into a single retry/rate-limit decorator applied to the one canonical path. |
| `config/portfolio_optimizer.yaml` | **Align**: delete `max_risk_pct_global: 0.06` (or explicitly mark as *advisory for optimizer selection, hard cap enforced by `GlobalRiskGuard`*). |
| `config/pm_profiles.yaml`, `config/trade_hold_config.yaml`, `config/trading_constants.py`, `config/kalshi_ct_risk_profiles.py`, per-asset `*_spec.py` | **Collapse** the seven `min_edge` sources into one `EdgeThresholdTable` with explicit override order (env > profile > default). |
| `.env` legacy flags (`MERID_ENABLE_POLYMARKET`, `MERID_ENABLE_AUGUR`, `MERID_ENABLE_UMA_ORACLE`, duplicated Kalshi blocks) | **Prune** — retire dead flags, dedup Kalshi creds. |

## 4.3 Intentional vs accidental redundancy

| Item | Tag |
|---|---|
| `GlobalRiskGuard` + per-agent `PredictionMarketRisk` | **Intentional / keep** — agent-local sizing vs portfolio-wide hard cap. |
| `_check_intent_risk` + `GlobalRiskGuard` | **Intentional / keep** — field bounds vs aggregate risk. |
| Multiple web submit endpoints (manual place + grid + batch + FIX) | **Intentional for surfaces, accidental for transport** — different UI triggers should share the same transport (`route_order_async`). |
| CT + AgentGrid both able to run | **Intentional** — shadow/experimental coexistence per ownership doc — **provided** CT routes through `route_order_async`. |
| `route_order` (sync) + `route_order_async` | **Accidental** — sync is vestigial after live-mode rejection. Candidate for deletion or thin-wrapper. |
| `top3_edge_allocator` + `topn_allocator` | **Accidental** — merge or extract shared primitives. |
| `crypto15m_lane` direct submit | **Accidental** — straight drift. |
| `_kalshi_place_order` as a live submit tool | **Accidental** — started as LLM tool surface, became a bypass. |
| Seven `min_edge` configs | **Accidental** — grew over sprints. |
| `portfolio_optimizer.yaml: 6 %` vs guard `2 %` | **Accidental** — pre-guard artifact. |
| `MERID_ENABLE_POLYMARKET` et al. | **Accidental / dead.** |
| Agent-grid YAML per-agent edge floors + per-asset `*_spec.py` floors | **Accidental overlap** — pick one authority. |

---

# Appendix A — Evidence index (line refs)

- Guard singleton: `merid/guards/global_risk_guard.py:63-222`
- Shared guard + dedup call in router: `merid/event_venues/kalshi/order_router.py:1915-2022` (definition), `2121` (call from `route_order_async`)
- Router entry: `merid/event_venues/kalshi/order_router.py:2025` (`route_order_async`), `1713` (sync `route_order`)
- CT direct POST: `merid/trading/kalshi_continuous_trader.py:4150`
- CT guard singleton import: `merid/trading/kalshi_continuous_trader.py:549-550, 678, 2304`
- Crypto15m lane drift: `merid/lanes/crypto15m_lane.py:1296`
- BTC15m lane canonical: `merid/lanes/btc15m_lane.py:1530-1556`
- CT Execution Adapter (Phase 1 shadow): `merid/trading/ct_execution_adapter.py` (whole file)
- Allocators: `merid/trading/topn_allocator.py:710`, `merid/trading/top3_edge_allocator.py:364`
- Risk-budget contradiction: `.env` (`MAX_CYCLE_RISK_PCT=0.02`) vs `config/portfolio_optimizer.yaml:29` (`max_risk_pct_global: 0.06`)
- Min-edge sources: `config/kalshi_agent_grid.yaml:820-896`, `config/pm_profiles.yaml:12-15`, `config/trade_hold_config.yaml:42-45`, `config/trading_constants.py:33-36`, `config/kalshi_ct_risk_profiles.py`, per-asset specs
- CT docstring ("legacy/research"): `merid/trading/kalshi_continuous_trader.py:646-651`
- Startup compatibility check: `merid/startup_validations.py:81-89`
- Web main CT gate: `web/main.py:2951-2976`

---

# Next step (deferred)

Phase 5 (prioritized cleanup plan) not included by design. Once this document is reviewed, pick any subset of the drift items tagged "Accidental" and move them into a phased plan. The obvious HIGH-priority candidates, for when you're ready:

1. Refactor `crypto15m_lane._execute_live_order` onto `route_order_async`.
2. Delete or migrate `trading_agent.py` L4036/4045/4240 off `_kalshi_place_order`.
3. Register an explicit `set_equity_provider` at startup.
4. Reconcile `portfolio_optimizer.yaml: max_risk_pct_global: 0.06` (delete or annotate).
5. Finish CT → `route_order_async` migration via `CTExecutionAdapter.execute_live`.
6. Consolidate the seven `min_edge` sources into one table.

None of those are large; all close real drift.
