# UI Wiring & Backend-Contract Audit — 2026-11-08

**Scope:** active seven-view React console (`agent-wall`, `mission-control`,
`agent-detail`, `terminal`, `portfolio`, `risk`, `system`), shared
hooks/store/agents layer, and the upstream `web/api` + `web/main_15m_lean.py`
contracts it consumes. Multi-domain parallel audit; every finding below was
verified against source before fixing.

## Fixed this audit

### Upstream (backend) contracts

| Finding | Fix |
| --- | --- |
| `/api/v1/ready` always returned HTTP 200 with `"not_ready"` payload — any probe keyed on status code saw the pod as ready | `web/main_15m_lean.py` now returns `JSONResponse(503)` when not ready (Kubernetes probe semantics) |
| `POST /api/internal/v1/kalshi/place-order` was an **unauthenticated live order path** (docstring admitted it "should be guarded") | Now `Depends(get_current_session)`, with a fail-closed 503 stub when the auth module is unavailable |
| `GET /api/v1/kalshi/ui-summary` bypassed the router-level session gate that every other `/api/v1/kalshi/*` route enforces | `web/api/kalshi_ui.py` router now carries `Depends(get_current_session)` |
| `ui-summary` catch-all reported `kill_switch_active: False` (the safest-looking lie) on total risk-summary failure | Defaults to `True` + `monitoring_failure` reason |
| `ui-summary` `mode` read the `MERID_PM_TRADING_MODE` env var, which can disagree with the canonical runtime machine | Now derived from `get_live_runtime_state()`; env var only as last-resort fallback |
| `ui-summary` imported legacy `merid.prediction.paper_session` (explicitly removed contaminant) | Removed; grid PnL belongs to the canonical `/api/v1/kalshi/pnl` surface |
| `/orders` truncated fractional centi-contracts (`int()`), used `remaining_count` as `size`, and preferred `yes_price` regardless of side — partially filled NO orders displayed shrunken size + YES-leg price | New `_normalize_ui_order` shared by executor + REST paths: Decimal parsing, `*_fp`/`initial_count` preference, `size`/`filled`/`remaining` distinct, own-side price with opposite-leg derivation |
| `/kill-switch` GET returned no reason; store mixed authoritative toggle with `/risk` reason | GET now emits `kill_switch_reason`; store prefers it |

### Frontend state, freshness, and lifecycle

| Finding | Fix |
| --- | --- |
| `isSessionScopedPath` used `startsWith('/api/v1/kalshi')` — matched `/api/v1/kalshi-grid/*`, minting pointless sessions on every grid probe | Exact-prefix match (`/api/v1/kalshi` or `/api/v1/kalshi/`) in `agents/session.ts` |
| Session minted token silently lost when `localStorage` throws (private mode/policy) | In-memory `memoryToken` fallback; `clearSession` wipes both |
| Session mint had no timeout/abort — `getJson`'s 10s AbortController never reached the register call | Caller `AbortSignal` propagated into `mintSession` |
| `usePoll` wrote stale responses after endpoint/`enabled` changes and leaked old data across source changes | Generation counter + `mounted` per effect + state reset on `sourceKey` change; StrictMode double-mount safe |
| `refreshAll` late responses could overwrite a newer refresh | `refreshGeneration` guard discards stale results |
| `useExecutionGate` reported nothing when risk/system slices were stale or missing | New `freshness` warning when slices lack `lastOk` within 60s or runtime state is absent |
| Live-runtime `reason` could be null while `reason_codes[]` was populated — UI showed halt with no reason | Store falls back to `reason_codes[0]`; type updated |
| `TopBar` `secsToWindowClose` used `Math.ceil` — on an exact 15m boundary it reported 0s until the next tick instead of 15:00 | `Math.floor + 1` gives the true next boundary |

### UX, a11y, and navigation

| Finding | Fix |
| --- | --- |
| `KalshiErrorBoundary` fallback navigated to `#/overview` — dead hash, app uses state routing | `#/agent-wall` + label "Back to Agent Wall" |
| Mobile sidebar drawer: no `role="dialog"`, no Escape-to-close | `role="dialog" aria-modal`, Escape handler |
| Command palette `scrollIntoView` indexed raw `children` — miscount when non-item nodes interleave | Items tagged `data-palette-item`; scroll target query |
| `GateChangeToast` rendered bottom-right on top of the ToastProvider stack (overlapping alerts) | Moved to top-right; animation class fixed |
| Alerts/toasts/popovers lacked `role="alert"`, `role="tooltip"`, `aria-haspopup`, `aria-expanded`, `aria-current`, `aria-pressed` | Added across banners, sidebar, HelpPopover, ConnectionStatusIndicator, ToastProvider, asset switcher |
| Collapsed sidebar showed no mode status at all | Live-status dot renders when collapsed |
| `web/api/sidebar_config.py` — dormant legacy contract mounted only on the `web/main.py` stub; advertises ~18 routes that 404 on the lean app and a `mode-indicator` that can report `sim` on live | Docstring now marked DORMANT with the warning; `tests/test_sidebar_wiring.py` rewritten to guard the **live** views.ts↔App↔Sidebar↔palette wiring instead |

### Tests

- New: `tests/test_ui_readiness_contract.py` (503/200 matrix + ui-summary session gate), `tests/test_kalshi_ui_order_normalization.py` (14 raw-order shapes × 2 sources, fractional counts, own-side pricing, NaN/Infinity rejection, REST fallback), `web/react/src/agents/__tests__/session.test.ts` (11 cases), `web/react/src/hooks/usePoll.test.tsx` (4 races), `web/react/e2e/ui-contract.spec.ts`.
- Deleted stale e2e specs for retired views (`dashboard`, `trade`, `kalshi-dashboards`); `accessibility.spec.ts` rewritten for the seven views. Playwright `Ctrl+K` is browser-reserved in headless — e2e exercises the TopBar-search open path instead.

## 2026-11-12 — upstream/midstream/downstream contract audit (second pass)

Second full-stack pass focused on real backend payloads vs. what the views
actually render. Every finding verified against source before fixing.

### Backend contracts

| Finding | Fix |
| --- | --- |
| `GET /api/v1/kalshi/markets` catalog path serialized outcomes with `price` but no `bid`/`ask`, so the market picker showed no spread/quotes even though `CatalogMarket.yes_bid`/`yes_ask` were authoritative dollars | Outcome rows now carry real `bid`/`ask` (YES side from catalog BBO; NO side as the YES-book complement, `null` when absent — never fabricated from `price`) |
| `GET /api/v1/kalshi/positions` cache path dropped `unrealized_pnl`/`realized_pnl`, so the portfolio rendered `$0.00` PnL for cached positions | Cache rows now pass through both PnL fields |
| `GET /api/v1/kalshi/market-states` returned only a sparse subset (spread/mid/depth/tob) — agent wall market blocks, depth chart, and trade-ticket staleness had no BBO/freshness/executable/shard data to render | Endpoint now emits the canonical `KalshiMarketState` fields: `yes_bid_c`/`yes_ask_c`, mid, spread, depth, book health, data quality, quote owner, `executable`, freshness timestamps, exchange shard |
| `POST /api/v1/kalshi/orders` `count` was `int` — fractional centi-contract orders (which `OrderIntent`/`count_fp` already support end-to-end) were rejected at the API boundary | `count: float` with finite/positive validation and 0.01-grid rounding downstream |
| Crypto 15m exit-policy branch in `place_order` matched BTC/ETH/XRP/DOGE prefixes but omitted `KXSOL` | `KXSOL` added — SOL 15m orders now get the same lifecycle/exit handling |
| `GET /api/v1/kalshi-grid/summary` returned `available`/`agent_count`/loop fields but not the `agents_total`/`agents_running`/`mode` the UI consumed — SystemRibbon's mode chip rendered a dead field | Summary now emits per-agent `enabled`/`running` flags plus `agents_total`/`agents_running`/`mode` aggregates |

### Frontend wiring

| Finding | Fix |
| --- | --- |
| `AgentDetail.normalizeBook` couldn't tell cent-priced vs dollar-priced ladders apart; YES asks were missing when only NO bids existed | Normalization now handles both unit shapes and derives YES asks from NO bids (`100 - no_bid`) |
| `Terminal` listed expired/settled 15m markets alongside live ones and passed no book-freshness signal to the ticket | Expired/closed markets filtered out; `bookAgeMs`/`bookStale` props wired through |
| `KalshiTradeTicket` forced integer contracts (min 1) despite the API's 0.01 contract grid, and let a `null`/`NaN` price slip into validation | Fractional quantity (min 0.01, step 0.01), `price: number \| null`, explicit finite/range price guards, book-age staleness disable |
| `SystemRibbon` grid chip read `summary.mode` which the backend never emitted | Replaced with real grid telemetry (`agents_running`/`agents_total` + loop state) |
| `mergeWallAgents` left new market-state fields (BBO, executable, shard, freshness) unmapped | Mapper + `MarketState`/`ServerAgent`/`GridSummary` types extended; wall/detail/terminal consume them |

### Tests

- New `tests/test_ui_wiring_audit_contracts.py` pins: market-states field set,
  positions PnL passthrough, catalog outcome bid/ask (incl. NO-side complement
  and absent-BBO honesty), fractional `place_order` count validation +
  `KXSOL` lifecycle branch, and grid summary aggregates.
- Jest: `agents/__tests__/api.test.ts` (normalizer coverage for the new
  payload shapes) and `KalshiTradeTicket.test.tsx` (0.01 min qty, fractional
  steps, null-price guards).

## Verified but deliberately unchanged

- `system.mode` stays `'live'` under `LIVE_ENTRIES_HALTED` — it is **venue mode**
  (real money), not "entries enabled"; exits/cancels still hit the exchange.
  Reporting `paper` during a halt would be the worse lie. Entry enablement is
  read separately via `live.state === 'LIVE_ENTRIES_ENABLED'` (already enforced
  in `KalshiTradeTicket` and System's runtime-state badge).
- `CommandPalette` owns the only `Ctrl+K` registration (no Shift leak — no
  conflicting chord exists in the seven-view build).
- `/api/v1/agents` vs `/api/v1/kalshi-grid/agents` schema drift is tolerated by
  the defensive mapper (`ServerAgent` union) — consolidating the duplicate
  endpoint is a backend-side follow-up, not a UI fix.

## Remaining follow-ups (documented, not fixed here)

1. `web/api/health_api.py` mounts legacy daemon-health routes
   (`/api/health/signals-daemon`, `/execution-daemon`, `/system`) that
   instantiate legacy singletons inside the lean process — recommend pruning
   to `kalshi-readiness`/`kalshi-config`/`thesis-side-monitor` in a focused
   backend change.
2. `web/main.py` is a legacy stub on the lean app's FORBIDDEN_MODULES list —
   it serves session-gated routes with uninitialized state if launched
   directly. Consider deleting or making it fail fast.
3. Duplicate agent surfaces (`/api/v1/agents`, `/kalshi-grid/agents`,
   `ui-summary.grid`) and three health surfaces with different semantics —
   needs a canonical-endpoint decision upstream.
4. `pnpm`-level dependency refresh (`vite 4`, `typescript 4.9`, caniuse-lite
   10 months stale) — separate maintenance task, not part of the bug sweep.

## Research applied

- React docs: async effects need ignore/abort cleanup + per-query staleness
  guards (`usePoll`/`refreshAll` generation counters).
- WAI-ARIA APG dialog pattern: focus into dialog, Escape closes, focus trap
  (palette already trapped Tab; drawer now has `role="dialog"` + Escape).
- Kubernetes probe contract: readiness must fail by status code (503).
- Playwright: network isolation via `context.route('**/api/**')` — all new e2e
  specs run fully isolated; browser-reserved chords (Ctrl+K) can't be
  delivered to the page in headless.

## Verification

- `tsc --noEmit` clean; `jest` 61/61 pass (3 skipped);
- `vite build` ok; Playwright chromium 7/7 pass (isolated);
- `pytest --noconftest`: `test_ui_readiness_contract` 4 pass,
  `test_kalshi_ui_order_normalization` 31 pass, `test_sidebar_wiring` 12 pass.
