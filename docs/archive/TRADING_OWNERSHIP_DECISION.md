# Trading Ownership Decision — Canonical PM Execution Owner

_Date: 2026-04-20 (revised — aligned with `docs/REDUNDANCY_AND_DRIFT_AUDIT.md`)_
_Status: **Authoritative** — supersedes contradictory language in `RISK_CONFIG_FULL_STACK_AUDIT.md` §1 and `kalshi_continuous_trader.py` class docstring._

---

## 1. Context

A contradiction existed across the codebase about who owns the live Kalshi prediction-market (PM) order flow:

- `@c:\Dev\MERID\merid\trading\kalshi_continuous_trader.py:714-720` (class docstring) states:
  > "Legacy / research / optional service — **not** part of the live AgentGrid PM path. Production prediction-market execution is owned by `KalshiTradingAgent` / AgentGrid (PortfolioRiskAgent, VenueGate, ExecutionGate, `order_router`). CT remains available behind `MERID_ENABLE_KALSHI_CT` for experiments and parity checks; do not wire it back in as a parallel trading loop."
- `@c:\Dev\MERID\docs\RISK_CONFIG_FULL_STACK_AUDIT.md` §1 implicitly treats CT as the production path because it is the only path with a fully hardened risk chain (TopN → `GlobalRiskGuard` → unified `equity_cents` → single submit site).

Both are factually correct about their own piece; neither is wrong. But operators need a single authoritative statement before we refactor risk gating.

---

## 2. Decision

| Question | Decision |
|---|---|
| Canonical production PM executor | **`KalshiTradingAgent` + AgentGrid + lanes + web API** (all callers of `route_order_async`). |
| Status of `KalshiContinuousTrader` (CT) | **Legacy / shadow / experimental.** CT may run when `MERID_ENABLE_KALSHI_CT=1`, but it is *not* the owner of prod PM order flow. When it runs, it is "just another caller" of the shared risk guard. |
| Canonical risk gate | **`GlobalRiskGuard`**, extracted into `merid/guards/global_risk_guard.py` and exposed as a process-wide singleton. Enforces 1–2 % per-cycle and per-total risk caps on a unified `equity_cents`. |
| Canonical sizing | **`TopNEdgeAllocator`** (`merid/trading/topn_allocator.py`) where used (CT today). Agent/lane sizing remains agent-local, but all outputs feed the same guard. |
| Canonical submit router | **`merid/event_venues/kalshi/order_router.py::route_order_async`** for agent/lane/web callers. CT submits directly via its own REST adapter and registers with the same shared guard. |

### Implications

1. `GlobalRiskGuard` is **no longer owned by CT**. It lives in `merid/guards/`. CT becomes a consumer of the shared singleton.
2. `route_order_async` invokes the shared guard for all entry (`buy`) intents before `_route_live` / `_route_sync_non_live`. Exits (`sell`) are exempt — they reduce risk.
3. A process-wide **order-dedup registry** prevents two callers (e.g., CT *and* a lane) from submitting on the same signal in the same cycle.
4. Equity source (`equity_cents`) is **unified**: a provider callback lets CT, AgentGrid, or any other canonical bankroll holder publish the same `total_value_cents` the guard uses.
5. `MERID_ENABLE_KALSHI_CT`, `MERID_ENABLE_AGENT_GRID`, and similar env flags **do not change** as part of this decision. They are orthogonal operational switches and will be tuned in a separate, lower-priority cleanup.

---

## 3. What this replaces

- "CT is the safe path; agent_grid is the gap" framing in `RISK_CONFIG_FULL_STACK_AUDIT.md` §1, §9.
- CT docstring wording implying CT must never be wired into live. (CT may run behind its env flag; when it does, it shares the canonical guard.)

`RISK_CONFIG_FULL_STACK_AUDIT.md` is otherwise still valid as a point-in-time risk audit.

---

## 4. Non-goals

- Turning CT off in production right now.
- Changing agent_grid startup defaults.
- Disabling lanes.
- Replacing TopN with a new allocator.

These are follow-on operational decisions, not part of this ownership declaration.

---

## 5. Sign-off

- Production PM executor: **AgentGrid (+ lanes + web API)**.
- Canonical risk gate: **`merid.guards.global_risk_guard.GlobalRiskGuard`** (singleton).
- Canonical dedup: **`merid.guards.order_dedup_registry`** (process-wide, cycle-scoped).
- CT: **shadow / experimental**; shares the same guard and dedup when enabled.

See `docs/ORDER_FLOW_AND_OVERTRADING_AUDIT.md` for the full wiring.

---

## 6. Known drift from this decision (as of 2026-04-20)

Enumerated in `docs/REDUNDANCY_AND_DRIFT_AUDIT.md`. Summary — these live paths exist today and must be converged onto `route_order_async`:

1. `merid/lanes/crypto15m_lane.py:1296` — `self.kalshi.place_order(...)` direct call (bypasses shared guard, dedup, lease, sanity, regime).
2. `merid/prediction/kalshi_tools.py::_kalshi_place_order` — live submit path used as a fallback from `merid/prediction/trading_agent.py:4036/4045/4240`.
3. `web/api/kalshi_api.py::fix_submit_order` and `::batch_place_orders` — transport bypasses.
4. `merid/trading/kalshi_continuous_trader.py:4150` — `self._post("/portfolio/orders")`; tolerated while `CTExecutionAdapter` Phase-2 migration is pending.

Config drift to resolve alongside:

5. `config/portfolio_optimizer.yaml:29` — `max_risk_pct_global: 0.06` contradicts `MAX_TOTAL_RISK_PCT=0.02` enforced by `GlobalRiskGuard`.
6. Seven independent `min_edge` tables (`kalshi_agent_grid.yaml`, `pm_profiles.yaml`, `trade_hold_config.yaml`, `trading_constants.py`, `kalshi_ct_risk_profiles.py`, per-asset `*_15m_agent_spec.py`).
7. Dead enable flags in `.env` (`MERID_ENABLE_POLYMARKET`, etc.) post-Kalshi-only refactor.

Prioritized cleanup plan intentionally deferred — see `REDUNDANCY_AND_DRIFT_AUDIT.md` "Next step".
See `docs/ORDER_FLOW_AND_OVERTRADING_AUDIT.md` for the full wiring.
