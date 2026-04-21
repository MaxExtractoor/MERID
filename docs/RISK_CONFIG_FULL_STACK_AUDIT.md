# Risk Config & Code Alignment — Full-Stack Audit (1–2% Cap)

_Date: 2026-04-20_
_Scope: Entire MERID prediction-market trading stack (Kalshi-only profile)._
_Goal: Prove no combination of code path, config, or YAML can push **live risk per cycle or per order batch above 1–2% of bankroll**, given the TopN allocator + GlobalRiskGuard design._

---

## 1. Executive Summary

| Area | Status | Notes |
|---|---|---|
| `KalshiContinuousTrader` (CT) live path | **SAFE** | TopN allocator owns sizing; GlobalRiskGuard is last-line cap; unified `equity_cents` source; single submit path. |
| TopN + Top3 co-existence | **SAFE** | Top3 is eligibility-only; TopN owns `order_count`. Both clamp risk to 1–2%. |
| Legacy BankrollManager Kelly in CT | **FENCED** | Only runs when `USE_TOPN_ALLOCATOR=false`; current `.env` has it `=true`. |
| `.env` / `core.settings` risk config | **SAFE** | `USE_TOPN_ALLOCATOR=true`, `MAX_CYCLE_RISK_PCT=0.02`, `MAX_TOTAL_RISK_PCT=0.02`. No diagnostic profile overrides in prod `.env`. |
| `portfolio_optimizer.yaml` (6% global) | **INERT** | `merid/portfolio/*` module is not imported by CT, `trading_agent`, `order_router`, `agent_grid`, or `web/main.py`. Dead config in live path. |
| `config/kalshi_agent_grid.yaml` risk_limits | **INERT for risk-%** | Only encodes per-agent position/notional ceilings ($250 notional, 500 contracts). No `risk_pct_*` keys. These are absolute ceilings above the 1–2% envelope and never override it. |
| `KalshiTradingAgent` (agent_grid, 35 agents) live path | **GAP — FLAGGED** | Uses `route_order_async` directly. Does **not** go through TopN allocator or GlobalRiskGuard. Sizing comes from per-agent strategy + local `PreTradeCheck` only. **Must be fenced** — see §6. |
| `merid/lanes/btc15m_lane.py`, `crypto15m_lane.py` | **GAP — FLAGGED** | Also use `route_order_async` directly; same concern as `KalshiTradingAgent`. |
| `route_order_async` caller allowlist | **PARTIAL** | Rejects unknown callers, but does not enforce cycle-wide risk cap. |
| Other legacy sizing (`BankrollManager`, `position_sizer`, `calculate_order_size`) | **SCOPED** | Only CT imports `BankrollManager`. `merid/event_venues/kalshi/position_sizer.py` is called from CT’s legacy path and from `trading_agent.py` tangentially for caps only. |
| Tests | **PARTIAL** | `test_topn_top3_alignment.py` covers CT. Added negative tests in §6. |

**Bottom line:** CT + TopN + GlobalRiskGuard is airtight at 1–2%. The main residual risk is **concurrent order submission** by `KalshiTradingAgent` (agent_grid) and `btc15m_lane` / `crypto15m_lane` — these bypass GlobalRiskGuard and could, in a high-edge regime, aggregate above the 1–2% envelope. Phase 6 lists mitigations.

---

## 2. Ground Truth (Validated Pieces)

### `merid/trading/topn_allocator.py`
- `TopNAllocatorConfig` (`@@/merid/trading/topn_allocator.py:40-93`): hard-coded `min_cycle_risk_pct=0.01`, `max_cycle_risk_pct=0.02`; env overrides via `TOPN_MIN_CYCLE_RISK_PCT` / `TOPN_MAX_CYCLE_RISK_PCT` only.
- `TopNEdgeAllocator.allocate()` + `select_topn_allocations()`: pick top `N ∈ {0,1,2,3}` edges, size by **max loss**, clamp `sum(max_loss) ≤ cycle_risk_usd`.

### `merid/trading/kalshi_continuous_trader.py`
- Imports canonical settings (`@@/merid/trading/kalshi_continuous_trader.py:90`): `USE_TOPN_ALLOCATOR, MAX_CYCLE_RISK_PCT, MAX_TOTAL_RISK_PCT` from `core.settings`.
- Instantiates `GlobalRiskGuard(max_cycle_risk_pct=..., max_total_risk_pct=...)` on construction (`@@/merid/trading/kalshi_continuous_trader.py:743-746`).
- Calls `self._risk_guard.reset_cycle()` at the start of each decision cycle (`@@/merid/trading/kalshi_continuous_trader.py:2366`).
- Sizing branches to TopN when `_USE_TOPN_ALLOCATOR and _topn_allocations and _candidate_asset in _topn_allocations` (`@@/merid/trading/kalshi_continuous_trader.py:3531-3548`). The legacy branch is `continue`d when TopN is enabled but asset is not in allocation (`@@/merid/trading/kalshi_continuous_trader.py:3549-3556`) — **no sizing via Kelly on TopN-missing assets**.

### `core/settings.py`
```
USE_TOPN_ALLOCATOR: bool = ... default "false"
MAX_CYCLE_RISK_PCT: float = float(os.getenv("MAX_CYCLE_RISK_PCT", "0.02"))
MAX_TOTAL_RISK_PCT: float = float(os.getenv("MAX_TOTAL_RISK_PCT", "0.02"))
```
`.env` line 41–43 explicitly sets `USE_TOPN_ALLOCATOR=true`, `MAX_CYCLE_RISK_PCT=0.02`, `MAX_TOTAL_RISK_PCT=0.02`.

---

## 3. Phase 1 — Global Risk/Sizing Inventory

### 3.1 Sizing modules that can reach live orders

| File | Role | Live path? | Risk bound |
|---|---|---|---|
| `merid/trading/topn_allocator.py` | TopN sizer | Yes (via CT) | Hard 1–2% |
| `merid/trading/top3_edge_allocator.py` | Top3 sizer (legacy notional-based) | Eligibility only in CT | Internal 1–2% clamp |
| `merid/trading/top3_batch_manager.py` | Batch lifecycle | Eligibility only | n/a |
| `merid/event_venues/kalshi/position_sizer.py` | Per-order contract count helper | CT legacy + `trading_agent` caps | **NOT** risk-% aware |
| `merid/event_venues/kalshi/bracket_risk.py`, `stop_loss.py`, `kalshi_risk.py` | Exit sizing, stops | Exit paths | Exits reduce risk, not add |
| `merid/prediction/strategy.py` | Kalshi strategy (`KalshiStrategy`) position sizing | Signals feed `KalshiTradingAgent` | Quarter-Kelly via strategy only |
| `merid/strategies/*` (70+ files) | Backtest/dashboard notebooks | **No live imports** | Backtest-only |
| `merid/prediction/risk/_prediction_risk.py`, `merid/prediction/risk.py` | Pre-trade checks | Both gates | Pre-trade rejections only |
| `merid/hedging/engine.py` | Hedge orders | `compute_hedge_intents()` | Reduces net risk; own caps |
| `merid/portfolio/optimizer.py` | Portfolio optimizer | **Not imported by live code** | Dead |

### 3.2 Config / env / YAML inventory

| Path | Risk-impacting keys | Active in live? | Notes |
|---|---|---|---|
| `.env` | `USE_TOPN_ALLOCATOR`, `MAX_CYCLE_RISK_PCT`, `MAX_TOTAL_RISK_PCT`, `MERID_INITIAL_CAPITAL=10`, `MERID_PROFILE=kalshi-only`, `MERID_TRADE_MODE=live`, `MERID_PM_TRADING_MODE=live`, `MERID_PM_LIVE_ENABLED=true`, `MERID_SPECTATOR_MODE=false` | Yes | No `KALSHI_CT_PROFILE`, no `KALSHI_CT_DIAGNOSTIC_*`, no `TOP3_CYCLE_RISK_CAP_PCT`, no `TOPN_*` overrides. |
| `core/settings.py` | same + `TRADE_HOLD_*`, `HTTP_PORT`, etc. | Yes | Defaults are conservative (2% cap). |
| `config/portfolio_optimizer.yaml` | `min_risk_pct_per_trade=0.005`, `max_risk_pct_per_trade=0.02`, `max_risk_pct_global=0.06` | **No** | Consumed only by `merid/portfolio/config.py`. No live importer. |
| `config/kalshi_agent_grid.yaml` | `risk_limits.max_yes_position=500`, `max_no_position=500`, `max_notional_usd=250` per agent | Yes, as per-agent absolute ceiling | Not a `risk_pct`; higher than 1–2% envelope on $10 capital, so envelope binds via CT; see GAP for agent_grid. |
| `config/kalshi_crypto_hedging.yaml` | `max_risk_per_trade` for hedge legs | Yes, within hedge engine | Hedge engine reduces exposure; separate from cycle cap. |
| `config/crypto_threshold_matrix.yaml` | Edge thresholds, min confidence | Yes | Filters candidates; does not size. |
| `config/kalshi_btc_15m_agent_spec.py`, `kalshi_sol_15m_agent_spec.py` | `max_risk_per_trade` | Via `merid/prediction/strategy.py` | Feeds signal sizing; within PreTradeCheck caps. |
| `config/trade_hold_config.yaml`, `config/profiles/trade_hold_live.yaml` | Trade hold / pause | Yes | Blocks trades globally; never increases risk. |

### 3.3 Profile / diagnostic flags

| Flag | Default | `.env` | Effect if ON |
|---|---|---|---|
| `KALSHI_CT_PROFILE` | `production` | not set | `diagnostic` loosens edge floors; **not set in prod .env**. |
| `KALSHI_CT_DIAGNOSTIC_MIN_EDGE` | 0.008 | not set | Only if diagnostic profile active. |
| `KALSHI_CT_AUTO_EXIT` | off | not set | Exits only; reduces risk. |
| `KALSHI_CT_BYPASS_PM_LIVE_GATE` | off | not set | Allows CT to trade even if `MERID_PM_*` non-live — does **not** affect risk cap. |
| `TOP3_ENABLED` | true | not set (defaults true) | Eligibility layer; compatible with TopN. |
| `TOP3_CYCLE_RISK_CAP_PCT` | 0.02 (clamped 0.01–0.02) | not set | Clamped by allocator to [0.01, 0.02]. |
| `USE_TOPN_ALLOCATOR` | false | **true** | Activates TopN + GlobalRiskGuard. |
| `MERID_VALIDATION_MODE` | off | not set | Skips agent_grid deferred start. |
| `MERID_PROFILE=kalshi-only` | off | **kalshi-only** | Disables ~35 non-Kalshi routers; narrows attack surface. |

**Conclusion:** No profile in prod loosens the 1–2% cap.

---

## 4. Phase 2 — Upstream: Edge / Candidate Generation

### 4.1 Filter pipeline
- `merid/trading/kalshi_filter_pipeline.py` (`FilterPipeline`) and `merid/event_venues/kalshi/market_filter.py`: edge/spread/depth filters. Candidates passed into CT’s TopN.
- `KALSHI_CT_DIAGNOSTIC_MIN_EDGE` only binds when `KALSHI_CT_PROFILE=diagnostic`; not set in `.env`.
- `config/kalshi_agent_grid.yaml` `min_edge` keys (if any) affect per-agent signal generation only; do not feed TopN sizing.

### 4.2 Alternate selectors
- `Top3BatchManager` + `Top3EdgeAllocator`: present, enabled by default (`TOP3_ENABLED=true`). Their role in CT is **eligibility gating** only — CT’s `order_count` comes from `TopNAllocation.target_contracts` (`@@/merid/trading/kalshi_continuous_trader.py:3534`). Top3’s internal notional sizing is not used when TopN is active.
- `Top3SelectionSpec.DEFAULT_CYCLE_RISK_CAP_PCT_MAX = 0.02` (`@@/merid/trading/top3_edge_allocator.py:226`). Even if Top3 sized orders, it’d still be within 2%.
- No other top-N / top-3 selectors found outside `merid/trading/`.

---

## 5. Phase 3 — Downstream: Sizing & Execution

### 5.1 CT order path
1. `_run_cycle_inner`: builds edge candidates → TopN allocates → Top3 filters → order loop → `GlobalRiskGuard.check_order(equity_cents, pending)` → direct REST `self._post()` or `get_ct_execution_adapter()`.
2. **Single submit path** gated by GlobalRiskGuard.
3. Legacy `BankrollManager.calculate_order_size` only reached when `USE_TOPN_ALLOCATOR=false` (fenced).

### 5.2 `route_order_async` path (non-CT)
Callers:
- `merid/prediction/trading_agent.py` (agent_grid), `merid/prediction/kalshi_tools.py`
- `merid/lanes/btc15m_lane.py`, `merid/lanes/crypto15m_lane.py` (via `trading_agent` imports)
- `merid/event_venues/kalshi/take_profit.py` (exits; risk-reducing)

`route_order_async` applies in order: caller allowlist → `_check_intent_risk` → sentiment cap → sanity check → market regime gate → pre-trade gate (lease/dedup/fill-aware) → venue submit.

**None of these layers enforce a cycle-wide 1–2% bankroll cap.** `_check_intent_risk` bounds per-order notional/size via `kalshi_risk` category caps but not cycle-% of equity.

### 5.3 Bypass paths
- CT uses direct `self._post()` → flagged as `_KNOWN_BYPASS_PATHS = {"merid.trading.kalshi_continuous_trader"}` in `order_router.py`. CT has its own GlobalRiskGuard in the submit path (safe).
- `_submit_sell_yes_limit` and other CT-only sell paths are exits (risk-reducing).

---

## 6. Phase 4 — Other Agents / Venues / Legacy

### 6.1 GAP 1 — `KalshiTradingAgent` agent_grid (35 agents)
- `web/main.py:2172–2186` starts `agent_grid.start()` in background unless `MERID_VALIDATION_MODE=1`.
- Each `KalshiTradingAgent` runs its own sizing via `merid/prediction/strategy.py` `KalshiStrategy` (quarter-Kelly) + per-agent `PreTradeCheck` (`@@/merid/prediction/trading_agent.py:1664–1679`).
- Submits via `route_order_async` (allowed caller).
- **No TopN, no GlobalRiskGuard.** Each agent operates on its own notion of bankroll.

#### Mitigation status
- `config/kalshi_agent_grid.yaml` caps each agent at `max_notional_usd=250` per order — **absolute** ceiling, not risk-%. On `MERID_INITIAL_CAPITAL=10`, $250 is 25× bankroll; binding only if the agent actually trades at full size. Per-agent `PreTradeCheck` should reject any order exceeding available equity.
- `merid/prediction/risk/_prediction_risk.py` / `merid/prediction/risk.py` perform the pre-trade check; their 10-point gate rejects when portfolio notional exceeds configured limits (`MERID_PM_MAX_TOTAL_NOTIONAL`, default 5000 USD).
- The combined effect caps exposure to `MERID_PM_MAX_TOTAL_NOTIONAL` at the whole-agent-grid level — not at 1–2%.

#### Recommendation (see §9)
- Either (a) **fence agent_grid off in prod** (e.g., `MERID_DISABLE_AGENT_GRID=1` env var + gate in `web/main.py:2172`), or (b) **wire GlobalRiskGuard into `route_order_async`** with a shared-bankroll singleton so every caller — CT, agent_grid, lanes — shares the 1–2% envelope.

### 6.2 GAP 2 — `merid/lanes/btc15m_lane.py`, `crypto15m_lane.py`
- Call `route_order_async` directly (`@@/merid/lanes/btc15m_lane.py:1530–1556`).
- No TopN, no GlobalRiskGuard.
- Same remediation as GAP 1.

### 6.3 Portfolio / optimizer modules
- `merid/portfolio/optimizer.py`: **no upstream importer**. Not connected to live path.
- `merid/risk/portfolio_optimizer.py`: imports only within `merid/risk/__init__.py` lazy path; not reached by CT/trading_agent/order_router live submit paths.

### 6.4 Scripts / tools
- `scripts/kalshi_live_trade.py` is a CLI one-shot trader. Not invoked by services. Bounded to a single order per run.
- `scripts/go_live_preflight.py`, `scripts/post_close.py`, other `scripts/*`: audit-only, do not submit orders.

---

## 7. Phase 5 — Config / Env Drift

Verified in `.env` (lines 41–43, 12–500):
- Risk: `USE_TOPN_ALLOCATOR=true`, `MAX_CYCLE_RISK_PCT=0.02`, `MAX_TOTAL_RISK_PCT=0.02`.
- Mode: `MERID_TRADE_MODE=live`, `MERID_PM_TRADING_MODE=live`, `MERID_PM_LIVE_ENABLED=true`, `MERID_SPECTATOR_MODE=false`, `MERID_ALLOW_LIVE_TRADES=true`.
- Capital: `MERID_INITIAL_CAPITAL=10` → 2% = $0.20/cycle risk.
- Profile: `MERID_PROFILE=kalshi-only`.
- No `KALSHI_CT_PROFILE`, `KALSHI_CT_DIAGNOSTIC_*`, `TOP3_CYCLE_RISK_CAP_PCT`, `TOPN_*` overrides.

No risk-loosening drift detected in prod config.

---

## 8. Evidence — Log Lines to Watch

| Log tag | Source | What it proves |
|---|---|---|
| `[RISK-MODE] Using new TopNEdgeAllocator ...` | CT startup | TopN active |
| `[RISK-CONFIG] USE_TOPN_ALLOCATOR=true, max_cycle_risk_pct=2.00% ...` | CT startup | Canonical settings loaded |
| `[BANKROLL-SOURCES topnB=... cashB=... portfolioB=...]` | CT cycle | Unified equity source |
| `[TOPN-ALLOCATE] n=... sum_max_loss_usd=... cycle_risk_usd=...` | TopN allocator | Cycle cap honored |
| `[TOPN-SIZE] ticker=... contracts=... max_loss=$... allocated_risk=$...` | CT per-order | Max-loss sizing used |
| `[GLOBAL-RISK-GUARD BLOCK]` | GlobalRiskGuard | Last-line reject fired |
| `[TOPN-SKIP] asset not in top-n allocations, skipping` | CT | Legacy Kelly fenced |
| `[AUDIT] KNOWN_BYPASS_CALLER module=merid.trading.kalshi_continuous_trader` | order_router | CT bypass acknowledged (has its own guard) |
| `[AUDIT] UNAUTHORIZED_CALLER_REJECTED` | order_router | Unknown callers blocked |

---

## 9. Findings & Recommendations

### 9.1 Resolved / Safe
1. CT is provably bounded to 1–2% via TopN + GlobalRiskGuard on a shared `equity_cents`.
2. Legacy Kelly sizing in CT is fenced behind `USE_TOPN_ALLOCATOR=true`.
3. `portfolio_optimizer.yaml` (6% global) is inert — no live importer.
4. `kalshi_agent_grid.yaml` encodes **absolute** per-agent caps, not risk-% overrides.
5. No profile/diagnostic flag in prod `.env` loosens the 1–2% cap.
6. Top3 allocator co-exists as eligibility filter only; it also self-clamps to [1%, 2%].

### 9.2 Open Gaps (require action)
1. **GAP-A (HIGH): `KalshiTradingAgent` agent_grid path bypasses GlobalRiskGuard.** 35 concurrent agents can each submit via `route_order_async`. In a high-edge regime, aggregate live risk can exceed 1–2% of bankroll. **Recommendation:**
   - Short-term: gate `agent_grid` behind `MERID_ENABLE_AGENT_GRID` (default `false` in prod) in `web/main.py:2172`.
   - Long-term: extract `GlobalRiskGuard` into a process-wide singleton (e.g., `merid/risk/global_risk_guard.py`) and invoke it inside `route_order_async` before `_route_live`/`_route_sync_non_live`, using the same unified `equity_cents` as CT.
2. **GAP-B (HIGH): `btc15m_lane` / `crypto15m_lane` bypass GlobalRiskGuard.** Same mitigation as GAP-A.
3. **GAP-C (MEDIUM): `route_order_async` caller allowlist permits bypass paths without enforcing a cycle cap.** Adding the shared `GlobalRiskGuard` invocation in `route_order_async` closes GAP-A, B, C simultaneously.
4. **GAP-D (LOW): `portfolio_optimizer.yaml` encodes a 6% global budget that contradicts the 1–2% envelope.** Because it’s inert, risk is zero today, but drift could reconnect it. **Recommendation:** either delete the YAML or update its values to `max_risk_pct_global: 0.02` and add a note that `merid/portfolio/*` is deprecated.

### 9.3 Tests Added
- `tests/trading/test_risk_config_full_stack_audit.py` — Negative / bypass invariants (see §10).

---

## 10. Test Surface

### Existing
- `tests/trading/test_topn_top3_alignment.py` — scenarios A–E; TopN ↔ Top3 alignment under CT’s `_run_cycle_inner`.
- `tests/trading/test_risk_oversizing_regression.py` — regression guard for the “7-BTC-orders-with-$28-equity” bug.

### New in this audit
- `tests/trading/test_risk_config_full_stack_audit.py`
  - `test_env_has_use_topn_allocator_true` — prod `.env` must set `USE_TOPN_ALLOCATOR=true`.
  - `test_env_has_max_cycle_risk_pct_le_2pct` — `MAX_CYCLE_RISK_PCT ≤ 0.02`.
  - `test_env_has_max_total_risk_pct_le_2pct` — `MAX_TOTAL_RISK_PCT ≤ 0.02`.
  - `test_topn_config_cap_invariant` — `TopNAllocatorConfig.max_cycle_risk_pct ≤ 0.02` by default.
  - `test_top3_cap_invariant` — `Top3SelectionSpec.DEFAULT_CYCLE_RISK_CAP_PCT_MAX ≤ 0.02`.
  - `test_core_settings_defaults_le_2pct` — `core.settings.MAX_CYCLE_RISK_PCT/MAX_TOTAL_RISK_PCT ≤ 0.02`.
  - `test_ct_legacy_bankroll_fenced_behind_flag` — CT source contains a `continue` in the legacy branch when `_USE_TOPN_ALLOCATOR` is true.
  - `test_portfolio_optimizer_yaml_has_no_live_importer` — static import scan: no live module imports `merid.portfolio`.
  - `test_route_order_async_requires_authorized_caller` — unknown module names are rejected.
  - `test_no_diagnostic_profile_in_env` — `.env` must not set `KALSHI_CT_PROFILE=diagnostic` or `KALSHI_CT_DIAGNOSTIC_MIN_EDGE`.
  - `test_no_portfolio_optimizer_6pct_budget_active` — if any live module imports `merid.portfolio`, fail loud.

### Recommended follow-on (GAP-A / GAP-B remediation)
- `test_agent_grid_disabled_in_prod_until_global_guard` — once the shared-guard refactor lands, replace this with `test_agent_grid_orders_go_through_global_risk_guard`.
- `test_lanes_go_through_global_risk_guard`.
- `test_full_stack_aggregate_cycle_risk_le_2pct` — spin up CT + agent_grid + lanes in a simulated cycle under a high-edge regime and assert sum of new max-loss ≤ `MAX_CYCLE_RISK_PCT * equity`.

---

## 11. Sign-Off Checklist

- [x] All risk/sizing modules catalogued.
- [x] All env/YAML/profile sources reviewed.
- [x] CT + TopN + GlobalRiskGuard verified airtight for CT-originated orders.
- [x] Legacy Kelly in CT proved fenced behind `USE_TOPN_ALLOCATOR=true`.
- [x] `.env` prod values confirmed conservative (2%).
- [x] `portfolio_optimizer.yaml` 6% proved inert.
- [x] Top3 / TopN coexistence proved safe.
- [ ] **GAP-A/B/C: agent_grid + lanes still bypass GlobalRiskGuard.** Requires either disabling agent_grid/lanes in prod, or wiring shared guard into `route_order_async`. Tracked.
- [ ] GAP-D: prune or rewrite `portfolio_optimizer.yaml`. Low priority.

**Overall verdict:** Live risk is bounded to 1–2% for **CT-originated orders today**. Closing GAP-A/B makes the bound hold system-wide. Recommend GAP-A/B remediation before scaling bankroll above the $10 validation baseline.
