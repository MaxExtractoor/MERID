# MERID Platform Audit — 2026-02-15 (v2, Comprehensive)

## A. System Map

### How MERID Works Today

MERID is a multi-agent, multi-venue, multi-domain trading orchestrator. Data flows roughly as:

**Venues** (Kalshi, Binance, Coinbase, Kraken, OKX, Alpaca, IBKR) → **Live Price Feeds** (`data/live_price_feed.py`, ccxt adapters, Kalshi WebSocket) → **Signal Layer** (decay-aware features: news, macro, on-chain, social) → **Agent Registry** (14 canonical agents in 5 phases: RESEARCH → STRATEGY → RISK → COORDINATION → OPS) → **Consensus** (TaCo weighted voting, debate protocol) → **Trade Plans** → **Execution Guard** (CQI throttle, domain caps, kill switches, reconciliation gate) → **Paper Engine** / Matching Engine / Venue Adapters → **Reconciliation** → **UI** (35+ React views, 140+ API endpoint constants, polling-based data refresh with WebSocket for select streams).

The loop (`merid/loop.py`) drives the cadence: feature refresh (30s), agent cycles (60s), consensus (15s), arb scan (10s), CQI/drift update (5min), reconciliation (2min), betting odds refresh (2min). Execution is gated behind `enable_execution=False` by default — must be explicitly enabled via CLI flag `--execute`.

The frontend is a React SPA with 35+ views organized into 6 sidebar sections (Trading, Kalshi Suite, Prediction Markets, Agents & Swarms, Risk & Analytics, System). Data fetching uses two parallel patterns: a centralized `useApiData` hook (with stub detection, error handling, polling) used by ~6 core views, and raw `fetch()` calls used by ~50+ components that bypass stub detection, auth token injection, and error standardization. Real-time updates are provided by `useMeridSocket` (WebSocket event bus) and `useKafkaStream` (streaming topics with deduplication).

### MERID's Evolution So Far — Story Arc

**Season 1 (Sprints 1-10): Foundation** — Core loop, agent registry, paper engine, basic UI. Most of this is now legacy debt.

**Season 2 (Sprints 11-17): UI hardening + Wiring** — ErrorBoundary on all views, sidebar consolidation (32 items, 6 sections), 25 wiring tests, navigation coherence audit, `useApiData` hook, 140+ `API_ENDPOINTS` constants, CommandPalette, aria-labels, React.memo on 24 components. This is the **most mature layer** of MERID.

**Season 3 (Sprints 18-30): Domain buildout** — Prediction markets (Kalshi deep integration, 109+ tests), paper engine persistence, reconciliation, trade mode guards, capital ladder tests (67 tests, 5 brackets), matching engine, consensus coordinator. Structurally sound but with known gaps (PM PnL hardcoded, reconciliation placeholders).

**Season 4 (Sprints 31-46): Operator features** — Operator Dashboard (5 tabs, 20+ sub-components), promotion gates, agent gauntlet, readiness auditor, Dev Swarm governance, assistant, rewards, cognitive layer, LLM governance. **New but fragile** — many components use raw `fetch()`, hardcoded fallback data, and independent time ranges.

**What's mature:**
- **Navigation wiring** — coherent (sidebar ↔ routes ↔ API, tested with 25 wiring tests).
- **Mode control** — canonical `TradeMode` enum (MOCK/PAPER/LIVE) with env-var guards, transition rules, and `assert_not_live()` in the adapter base class.
- **Prediction markets** (Kalshi) — well-structured module (`merid/prediction/`) with venue gating, strategy, risk, alerts, and 109+ tests.
- **Adapter base class** — clean Protocol pattern with hard mode guard in `submit_order()`.
- **TaCo consensus** — well-designed data model (AgentOpinion, TradePlan, TradeExecution) with weighted voting, signal freshness, TTL expiry.
- **6 core views** (Logs, ApiDashboard, Agents, Settings, Risk, Research) — properly use `useApiData` with loading/error/empty states.

**What's still legacy or fragile:**
- **50+ components use raw `fetch()`** — bypassing `useApiData` entirely. This is systemic, not a few outliers.
- **SentimentTimeline has hardcoded fake data** as a fallback when the API fails.
- **DomainPnLChart has a loading-state bug** — `setLoading(false)` is never called on success, so the spinner shows forever.
- **Four competing mode enums** — only `TradeMode` is canonical but three others still exist.
- **Paper engine PnL for prediction markets** is hardcoded to `±50%`.
- **Loop consensus step is dead code** — increments a counter but aggregates nothing.
- **~80+ API routers** in `main.py` — ordering-dependent, `governance_router` imported twice.

---

## B. Design Flaws & Risks by Subsystem

### B1. Paper Trading Engine

| Issue | Why it matters | Risk | Tag |
|-------|---------------|------|-----|
| **Prediction market PnL is hardcoded `±50%`** (`_calculate_position_pnl`, line 607-612). For non-perp positions, PnL is `size * 0.5` or `size * -0.5` regardless of market state. | Any prediction market position shows fabricated PnL. The operator cannot trust equity or drawdown numbers for PM positions. | **HIGH** | Legacy debt |
| **No fees modeled.** Slippage is a flat 0.1% (`slippage = 0.001`, line 466). No exchange fees, no funding rates, no spread cost. | Paper performance will be systematically better than live. When transitioning to live, unexpected costs will erode alpha. | **MEDIUM** | Legacy debt |
| **`get_paper_engine()` vs `get_paper_trading_engine()` — two singleton getters** (lines 858 and 923). `get_paper_engine()` loads persisted state; `get_paper_trading_engine()` does not. | A caller using the wrong getter gets an empty engine. Silent data loss / position amnesia. | **MEDIUM** | Legacy debt |
| **Trade history capped at 500 per portfolio** (line 767). No rotation log, no warning when truncated. | After 500 trades, older trade audit data is silently dropped. Reconciliation check #2 (trade_count vs history length) will permanently fail. | **MEDIUM** | Legacy debt |
| **Position key is `{asset}_{side}_{market_type}`** (line 506). No venue dimension. | If the same asset is traded on two venues, positions merge incorrectly. Cross-venue reconciliation becomes impossible. | **HIGH** | Legacy debt |
| **No idempotency on order placement.** `order_counter` is a plain integer, not persisted. After restart, IDs can collide. | Replay or restart can produce duplicate order IDs, breaking audit trail causality chains. | **MEDIUM** | Legacy debt |

### B2. Reconciliation & Audit Trail

| Issue | Why it matters | Risk | Tag |
|-------|---------------|------|-----|
| **Realized PnL reconciliation is a no-op** (`trading/reconciliation.py` line 231-245). The code says "Full recomputation requires matching open/close pairs" and just checks `total_pnl` is finite. | The most important invariant — "did we actually make/lose what we think we did?" — is not enforced. | **HIGH** | Legacy debt |
| **`merid/reconciliation.py` and `trading/reconciliation.py` are two separate reconciliation systems** with different concerns (venue-vs-internal and balance-identity). Neither references the other. | An operator might run one and assume both ran. No unified reconciliation status. | **MEDIUM** | Recent regression risk |
| **`_last_discrepancies` is module-level mutable state** (`merid/reconciliation.py` line 36). Not thread-safe, not protected by a lock. | Concurrent reconciliation calls (background thread + API call) can produce torn reads. | **MEDIUM** | Legacy debt |
| **`has_critical_discrepancies()` uses module-level cache** — if reconciliation hasn't run yet, it returns False (empty list), implying "all clear." | On first startup, execution is allowed even though no reconciliation has ever run. False sense of safety. | **HIGH** | Legacy debt |
| **`force_align_from_venue()` has a NameError** — uses `get_adapter(venue_name)` without importing it (line 226). | The only way to resolve a critical reconciliation mismatch is broken. Cannot be called at all. | **HIGH** | New but fragile |
| **Audit trail** (`trading/audit_trail.py`) writes to `data/trade_audit.jsonl` — no size cap, no rotation. | Over weeks of paper trading, this file grows unbounded. No alerting if it fails to write. | **LOW** | Legacy debt |

### B3. Risk & Kill Switches

| Issue | Why it matters | Risk | Tag |
|-------|---------------|------|-----|
| **Two independent risk layers with different limits.** `ExecutionGuard` (crypto: $10k/day, prediction: $5k/day) vs `GlobalRiskManager` (crypto: $25k notional, prediction: $5k notional). Neither references the other's state. | An order can pass one gate but would fail the other. Depending on which code path is hit, risk enforcement is inconsistent. | **HIGH** | Recent regression risk |
| **`DomainCap.reset_if_new_day()` uses local time** (`time.strftime("%Y-%m-%d")`). | If the server's timezone changes, or if running in UTC vs EST, the daily cap may reset at the wrong time. Markets have specific daily cycles (e.g., Kalshi Thu 3-5 AM ET maintenance). | **MEDIUM** | Legacy debt |
| **Kill switch is in-memory only** (not persisted). After a process restart, the kill switch silently deactivates. | An operator activates the kill switch during a crisis, the process restarts (e.g., OOM, deploy), and execution resumes without the operator knowing. | **HIGH** | New but fragile |
| **Cooldown is a blunt 5-second global cooldown** (line 374). Not per-domain or per-symbol. | A prediction market order blocks crypto execution for 5 seconds. In fast markets, this can miss fill windows. | **LOW** | Legacy debt |
| **`_trade_log` list trimming** (line 406-407): when it exceeds 1000, it drops to 500. | Non-deterministic: 499 most recent verdicts are silently purged. Should use `deque(maxlen=N)` for predictable behavior. | **LOW** | Legacy debt |

### B4. Mode Control & Configuration

| Issue | Why it matters | Risk | Tag |
|-------|---------------|------|-----|
| **Four competing mode enums still exist.** `trading/trade_mode.py` (MOCK/PAPER/LIVE), `trading/mode_controller.py` (PAPER/LIVE/HYBRID/AUTONOMOUS), `trading/config/runtime_config.py` (OFFLINE/SIM/PAPER/LIVE/HYBRID), `merid/prediction/venue_gate.py` (SIM/PAPER/LIVE). | Different modules may read different mode sources. A module checking `mode_controller` might think it's in PAPER while `trade_mode` says LIVE. | **HIGH** | Legacy debt |
| **`_execute_single_plan` sets `live=True`** in `TradeRequest` (loop.py line 495). | Even in paper mode, the request is flagged `live=True`. The adapter's hard guard in `submit_order()` is the only thing preventing real execution. One adapter without that guard → real money at risk. | **HIGH** | Recent regression risk |
| **No centralized feature-flag system.** Flags are scattered across env vars (`MERID_TRADE_MODE`, `MERID_ALLOW_LIVE_TRADES`, `MERID_PM_LIVE_ENABLED`, `MERID_PM_TRADING_MODE`, etc.). | No single place to see what's enabled. No audit trail of who changed what flag. Easy to misconfigure. | **MEDIUM** | Legacy debt |

### B5. Agents & Orchestration

| Issue | Why it matters | Risk | Tag |
|-------|---------------|------|-----|
| **`_run_consensus` does nothing** (loop.py lines 349-355). It increments a counter and appends "consensus_check" to the summary. No actual opinions are aggregated in this step. | The consensus step in the main loop is effectively dead code. Real consensus happens via opinion submission to TaCoConsensusCoordinator, not via the loop's step 3. Misleading metrics (`consensus_cycles_run` counts up but nothing happens). | **MEDIUM** | Legacy debt |
| **`registry.run_all()` is an unbounded await** (loop.py line 342). No timeout, no backpressure. | If any agent hangs (e.g., waiting for an API call), the entire loop tick stalls indefinitely. No watchdog timer. | **HIGH** | New but fragile |
| **Agent errors are swallowed** (`logger.warning(f"Agent cycle failed: {e}")`, line 346). No structured error tracking per agent. | A single agent can fail silently on every tick for days. No alert rule for "agent X has failed N consecutive times." | **MEDIUM** | Legacy debt |
| **Phase context piping is implicit.** The orchestrator builds context via `_build_phase_context()` but the main loop doesn't use the orchestrator — it calls `registry.run_all()` directly. | The phased RESEARCH→STRATEGY→RISK→COORDINATION→OPS flow exists in `orchestrator.py` but the actual loop bypasses it. Two execution paths, potential drift. | **MEDIUM** | Recent regression risk |
| **TaCoConsensusCoordinator is a module-level singleton** (`_instance` class var). No reset mechanism except replacing the class var. | Tests that modify consensus state leak into other tests. No way to cleanly reinitialize in production without restart. | **LOW** | Legacy debt |

### B6. Venues & Adapters

| Issue | Why it matters | Risk | Tag |
|-------|---------------|------|-----|
| **`run_in_executor(None, adapter.submit_order, request)`** (loop.py line 498-499) runs synchronous adapter code in the default executor. | The default `ThreadPoolExecutor` has limited workers. Under load, venue calls queue up silently. No explicit pool sizing. | **MEDIUM** | Legacy debt |
| **Adapter registry is a plain dict** with no locking, no health pre-check. `get_adapter()` returns `Optional` — callers must handle `None`. | If a venue is down, the order attempt fails inside the executor with no pre-flight check. Wasted latency + unclear error. Race condition if adapters are registered concurrently. | **MEDIUM** | Legacy debt |
| **`TradingVenueAdapterBase.use_mock` auto-set from missing API key** (line 144: `self.use_mock = not bool(self.api_key)`). | If an env var is unset by accident, the adapter silently switches to mock mode. No warning or log. The operator sees "offline" status but might not know why. | **MEDIUM** | Legacy debt |

### B7. UI/UX & Data Surfaces

This section is the most significantly expanded from the initial audit, because the deep dive revealed **systemic** issues with data fetching, error handling, and operator trust.

#### B7.1 Systemic: Raw `fetch()` Bypass

**50+ components** in `web/react/src/components/` use raw `fetch()` instead of `useApiData`. This means they bypass:
- **Stub detection** (`isStub`, `stubMessage`) — the operator sees no warning when data is simulated.
- **Auth token injection** — `useApiData` adds `Authorization: Bearer ...` from localStorage; raw `fetch()` does not. If RBAC is enforced, these components will silently fail.
- **Standardized error/loading/empty states** — each component handles (or doesn't handle) these differently.

**Affected components include (non-exhaustive):**

| Component | Fetch count | Error handling | Fake fallback? | Tag |
|-----------|-------------|----------------|-----------------|-----|
| `EquityPnLChart` | 1 | `logUiError` only | No | Season 4 |
| `DomainPnLChart` | 1 | `logUiError` only + **loading-state bug** | No | Season 4 |
| `SentimentTimeline` | 1 | Silent catch → **hardcoded fake data** | **YES** | Season 4 |
| `TradingHaltBanner` | 4 | Silent catch | No | Season 4 |
| `ConsensusBoard` | 2 | Silent catch | No | Season 3 |
| `QuickActionsPanel` | 5 | Silent catch | No | Season 3 |
| `SimulationControlPanel` | 5 | Silent catch | No | Season 3 |
| `DrawdownChart` | 3 | Silent catch | No | Season 4 |
| `LiveNotifications` | 3 | Silent catch | No | Season 3 |
| `ModeControlPanel` | 3 | Silent catch | No | Season 4 |
| `ArbitragePanel` | 2 | Silent catch | No | Season 3 |
| `VenueHealthGrid` | 2 | Silent catch | No | Season 4 |
| `StrategyLeaderboard` | 2 | Silent catch | No | Season 4 |

**Risk:** **HIGH** — An operator making decisions based on stale, missing, or fabricated data. This is the single largest trust gap in the UI.

#### B7.2 Specific Chart/Card Bugs

| Issue | Component | Why it matters | Risk | Tag |
|-------|-----------|---------------|------|-----|
| **`DomainPnLChart` loading spinner never disappears on success.** `setLoading(false)` is only called in the failure path (line 36). On successful fetch, the function returns at line 31 without resetting `loading`. | `DomainPnLChart.tsx` | The Domain PnL chart on the Operator Dashboard is permanently stuck on "Loading PnL data..." spinner after a successful API response. The chart never renders. | **HIGH** | Season 4 bug |
| **`SentimentTimeline` renders hardcoded fake data when API fails** (lines 69-80). Five fabricated sentiment events with specific headlines like "Bitcoin breaks $105K resistance" are shown as if real. | `SentimentTimeline.tsx` | An operator sees realistic-looking sentiment data that is entirely fabricated. There is no "fake data" indicator. This directly undermines operator trust — they could make trading decisions based on fiction. | **HIGH** | Season 4 — directly contradicts the Sprint 18 fake-data purge |
| **`EquityPnLChart` uses hardcoded URL** (`${API_BASE_URL}/api/operator/equity-series`) instead of `API_ENDPOINTS` constant. No auth token. | `EquityPnLChart.tsx` | URL not governed by constants system. If endpoint changes, this breaks silently. No auth = fails if RBAC enabled. | **MEDIUM** | Season 4 |
| **`usePaperTrading` hook uses raw `fetch()`** for all 3 endpoints (portfolio, positions, orders). No auth token, no stub detection. | `usePaperTrading.ts` | The entire Paper Trading view bypasses the `useApiData` infrastructure. If the backend returns stub data, the view shows it as real. | **MEDIUM** | Season 3 |
| **`useOperatorSummary` has a TypeScript error**: `e.message` on `unknown` type (line 70). | `useOperatorSummary.ts` | Under TypeScript strict mode, this won't compile. Even without strict mode, if `e` is not an Error, `e.message` is `undefined`, and the error state shows `undefined`. | **LOW** | Season 3 |
| **`useNativeWebSocket` retry math is wrong.** On connection failure, `retriesRef.current += 2` (never opened, line 125) then `+= 1` (closed, line 126) = **3 per attempt**. With `MAX_RETRIES=5`, you get **at most 2 connection attempts**, not 5. | `useMeridSocket.ts` | The WebSocket reconnection gives up far too quickly. After 2 failed attempts, the socket is permanently disconnected and no retry ever happens. The `connected` state stays `false` forever. | **MEDIUM** | Season 2 |
| **`KalshiDashboardView` uses raw `fetch()`** with `console.debug` for errors. User never sees errors. No loading/error states after initial load. | `KalshiDashboardView.tsx` | Kalshi dashboard silently shows stale data if API goes down. No visual indicator. | **MEDIUM** | Season 4 |
| **`KalshiPortfolioView` kill switch uses query param** (`?activate=${activate}`) instead of request body. | `KalshiPortfolioView.tsx` | Query params are logged in access logs and browser history. Kill switch activation should use POST body. Security hygiene issue. | **LOW** | Season 4 |
| **`Overview.tsx` uses 5 raw `fetch()` hooks** — `usePortfolio`, `usePrices`, `useTrades`, risk exposure, equity series. No stub detection, no standardized error/loading states. | `Overview.tsx` | The main landing page — the first thing an operator sees — bypasses the entire data infrastructure. | **HIGH** | Legacy debt |
| **`TradeFloor.tsx` contains `Math.random()`** (1 occurrence). | `TradeFloor.tsx` | Residual fake data generation in a critical trading view. | **MEDIUM** | Legacy debt |
| **No synchronized time range across Operator Dashboard panels.** `EquityPnLChart` has its own `Window` selector (5m/15m/30m/1h/4h/1d). `DomainPnLChart` has its own `timeRange` (1h/4h/24h/7d). `SentimentTimeline` has no time range — shows whatever the API returns. | Operator Dashboard | Panels can show data from different time windows simultaneously. An operator comparing equity chart (set to 1h) vs PnL chart (set to 24h) may be misled about trends. | **HIGH** | New but fragile |
| **PaperTradingView equity curve** — has good empty-state check (`chartData.length > 1`), but when `pnlHistory` is empty, the entire chart section silently vanishes. No "no trades yet" message. | `PaperTradingView.tsx` | New paper accounts see stat cards with zeros but no chart section at all. Confusing — looks like a rendering bug rather than "no data." | **LOW** | New but fragile |
| **MetricCard threshold hardcoded.** `Risk.tsx` line 341 uses `> 10000` for "GOOD" status on "Available Margin". | `Risk.tsx` | Not derived from risk config. If starting capital changes, threshold is wrong. | **LOW** | Legacy debt |

#### B7.3 Operator Dashboard Component Assessment

The Operator Dashboard (`OperatorDashboard.tsx`) is the most complex view with 5 tabs and 20+ sub-components. Assessment:

| Tab | Components | Data Source | Time Range | Error handling | Verdict |
|-----|-----------|-------------|------------|----------------|---------|
| **Overview** | `LiveRiskStrip`, `EquityPnLChart`, `LiveAgentHealthPanel`, `DomainPnLChart`, `StrategyLeaderboard`, `OperatorActivityStream`, `OperatorControlPlane` | Mixed: `useOperatorSummary` (polling) + per-component raw `fetch()` | **Unsynced** — each component has its own | Per-component, inconsistent | ⚠️ Functional but untrustworthy |
| **Trading** | `DomainControlPanel`, `VenueHealthGrid`, `ModeControlPanel`, `PredictionMarketDetail`, `ExplainabilityTimeline` | Per-component raw `fetch()` | No shared range | Silent `catch` blocks | ⚠️ Functional but silent failures |
| **Risk** | `ConsensusTable`, `RiskLimitBars`, `RiskHeatmapWidget`, `DrawdownCard`, `InstrumentRadar`, `RiskTreeMap`, `BreachAlertLog`, `LatencyChart` | Per-component raw `fetch()` | **Unsynced** | Silent `catch` blocks | ⚠️ Functional but unsynced data |
| **Intelligence** | `OrchestratorPanel`, `SentimentTimeline`, `ArbScannerPanel` | Per-component raw `fetch()` | No shared range | `SentimentTimeline` **shows fake data on failure** | 🔴 Misleading when API down |
| **System** | Kill Switch button, Loop Status, `PromotionStatusCard`, `OnChainHealthPanel`, `DataFreshnessPanel`, `AlertHistoryPanel`, `CompliancePanel`, `TelegramLogViewer` | `useOperatorSummary` + per-component | N/A | Generally adequate | ✅ Most mature |

### B8. Logging & Observability

| Issue | Why it matters | Risk | Tag |
|-------|---------------|------|-----|
| **Logger format inconsistency.** Some modules use `logger.info(f"...")`, others use `logger.info("...", exc_info=e)`, and at least one uses structlog-style kwargs (`logger.debug("data_fetch_suppressed", error=str(exc))` — execution_guard.py line 308). | The stdlib logger doesn't handle kwargs as structlog does. That log line silently drops the `error` kwarg (goes into `args` tuple of the log record). | **MEDIUM** | Legacy debt |
| **No per-agent error rate alert rule.** The 18 alert rules in `system_observability.py` cover SLOs, staleness, circuit breakers, kill switch, WS feed, debate, rewards — but no rule for "agent X has error_rate > threshold." | A malfunctioning agent can degrade system quality without triggering any alert. | **MEDIUM** | Legacy debt |
| **Tick log** (`merid/tick_log.py`) is append-only with no rotation policy mentioned. | Over weeks, the tick log grows unbounded. | **LOW** | Legacy debt |
| **Frontend errors logged to `console.debug`** (KalshiDashboard, KalshiPortfolio, etc.) not to the structured logger (`logUiError`). | Frontend errors in Kalshi views are invisible in production — `console.debug` is suppressed by default. No observability. | **MEDIUM** | Season 4 |

### B9. WebSocket & Real-Time Data

| Issue | Why it matters | Risk | Tag |
|-------|---------------|------|-----|
| **`useNativeWebSocket` retry logic gives up after ~2 attempts** instead of 5. The retry counter increments by 3 per failed connection (2 for no-open + 1 for close). | Real-time data silently stops updating. The `connected` indicator shows `false` but there's no retry button or auto-recovery beyond the initial 2 attempts. | **MEDIUM** | Season 2 |
| **`useMeridSocket` event aliasing is hardcoded** (lines 58-68). If backend adds new event types, the frontend silently drops them. | New event types (e.g., `reconciliation_alert`, `mode_change`) won't trigger any UI update unless the alias map is manually updated. | **LOW** | Legacy debt |
| **No heartbeat/keepalive** in `useMeridSocket`. If the server silently drops the connection (e.g., load balancer timeout), the client has no way to detect it until the next message fails. | Stale "connected" indicator. The green dot stays green even if the connection is dead. | **MEDIUM** | Legacy debt |

---

## C. Recommended Fixes and Changes

### C1. Paper Engine — Make PM PnL Real (P0)

**What:** Replace the hardcoded `±50%` prediction market PnL in `_calculate_position_pnl()` with actual mark-to-market using current contract prices from the Kalshi price feed or consensus store.

```python
if position.side == "yes":
    pnl = (position.current_price - position.entry_price) * position.size_usd / position.entry_price
else:
    pnl = (position.entry_price - position.current_price) * position.size_usd / position.entry_price
```

**Verify:** Update capital ladder tests to include prediction market positions. Assert PnL changes when `current_price` is updated.

**Story arc:** Turns PM positions from "demo mode" into trustworthy paper trading.

### C2. Unify Mode Enums (P0)

**What:** Delete or alias `trading/mode_controller.py`'s `TradingMode`, `trading/config/runtime_config.py`'s `GlobalTradingMode`, and `merid/prediction/venue_gate.py`'s `TradingMode` to all import from `trading/trade_mode.py`. Grep for all usages and redirect.

**Verify:** `grep -r "class TradingMode" --include="*.py"` returns exactly one hit. `grep -r "class GlobalTradingMode" --include="*.py"` returns zero.

**Story arc:** Eliminates the #1 "paper vs live confusion" risk class.

### C3. Fix `live=True` in Plan Execution (P0)

**What:** In `loop.py` line 495, set `live=` based on actual trade mode:

```python
from trading.trade_mode import is_paper_or_mock
request = TradeRequest(
    ...
    live=not is_paper_or_mock(),
)
```

**Verify:** Add test asserting that when `MERID_TRADE_MODE=paper`, the TradeRequest has `live=False`.

**Story arc:** Closes a real-money safety gap introduced when the matching engine was added.

### C4. Fix DomainPnLChart Loading Bug (P0)

**What:** In `DomainPnLChart.tsx`, add `setLoading(false)` after `setData(json.data)` in the success path:

```typescript
if (json.data) { setData(json.data); setLoading(false); return; }
```

**Verify:** Open Operator Dashboard → Overview tab → DomainPnLChart renders data (not spinner).

**Story arc:** Fixes a chart that is currently 100% broken on the main dashboard.

### C5. Remove SentimentTimeline Fake Data Fallback (P0)

**What:** In `SentimentTimeline.tsx` lines 68-81, replace the hardcoded fake events with an error state:

```typescript
} catch {
  // Show error state instead of fake data
}
setEvents([]);
setWindows([]);
setLoading(false);
```

Add a visible error/empty state when no data is available.

**Verify:** Stop the backend → navigate to Operator Dashboard → Intelligence tab → see "No sentiment data" instead of fake headlines.

**Story arc:** Directly reverses a regression from the Sprint 18 fake-data purge. Critical for operator trust.

### C6. Persist Kill Switch State (P1)

**What:** Write kill switch state to `data/kill_switch.json` on activation. On startup, load and re-apply. Add a timestamp and reason.

**Verify:** Test: activate kill switch → restart process → assert `kill_switch_active` is still True.

**Story arc:** Pre-paper hardening — prevents crisis state from being silently cleared by restarts.

### C7. Reconciliation: Fail-Closed on First Startup (P1)

**What:** Initialize `has_critical_discrepancies()` to return True (or a "never ran" sentinel) when `_last_discrepancies` is empty AND no reconciliation has ever completed. Execution should be blocked until at least one successful reconciliation.

**Verify:** Test: fresh process start → `has_critical_discrepancies()` returns True → execution is blocked.

**Story arc:** Closes a gap where fresh startups assume clean reconciliation.

### C8. Fix `force_align_from_venue` Missing Import (P1)

**What:** In `merid/reconciliation.py` line 226, `get_adapter` is used but never imported. Add:

```python
from trading.adapters.registry import get_adapter
```

**Verify:** Call `force_align_from_venue("alpaca")` in a test → no NameError.

### C9. Add Agent Timeout + Per-Agent Error Tracking (P1)

**What:** Wrap `registry.run_all()` in `asyncio.wait_for(timeout=30)`. Track per-agent consecutive error count. Add alert rule `AgentConsecutiveFailureAlert` (warning at 3, critical at 10).

**Verify:** Test: mock an agent that raises → assert alert fires after 3 consecutive failures.

**Story arc:** Prevents a hung agent from stalling the entire loop.

### C10. Migrate Critical Views to `useApiData` (P1)

**What:** Migrate these high-priority raw-`fetch()` components to `useApiData`:
1. `Overview.tsx` — 5 hooks
2. `usePaperTrading.ts` — 3 fetches
3. `useOperatorSummary.ts` — 1 fetch + fix TS error on `e.message`
4. `KalshiPortfolioView.tsx` — 5 fetches
5. `KalshiDashboardView.tsx` — 3 fetches

For components that use `API_ENDPOINTS` functions (e.g., `PIPELINE_PNL(range)`), use `useApiData` with the `enabled` option and dynamic endpoint.

**Verify:** Each migrated component: stub detection works (add `_stub: true` to mock response, confirm stub badge appears).

**Story arc:** Closes the largest trust gap in the UI. Brings the remaining 50+ components to Sprint 18 standards.

### C11. Fix WebSocket Retry Math (P1)

**What:** In `useMeridSocket.ts` `useNativeWebSocket`, fix the retry counter:

```typescript
ws.onclose = () => {
  setConnected(false);
  setSocket(null);
  if (!mountedRef.current) return;
  retriesRef.current += 1;  // Remove the double-increment for !opened
  if (retriesRef.current < MAX_RETRIES) {
    const timeout = Math.min(1000 * 2 ** retriesRef.current, 10000);
    setTimeout(connect, timeout);
  }
};
```

**Verify:** Mock a WebSocket that always fails to connect → verify 5 retry attempts happen, not 2.

### C12. Implement Realized PnL Reconciliation (P1)

**What:** In `trading/reconciliation.py` check #6, match open→close trade pairs and recompute realized PnL from fill prices. Compare against `portfolio.total_pnl`. Fail with `CheckStatus.ERROR` if delta > $1.

**Verify:** Test with a sequence of open + close trades → assert reconciliation passes with correct PnL.

**Story arc:** Turns the reconciliation from "structural sanity check" into "accounting-grade proof."

### C13. Add Venue Dimension to Position Key (P1)

**What:** Change position key from `{asset}_{side}_{market_type}` to `{asset}_{side}_{market_type}_{venue}`.

**Verify:** Capital ladder tests still pass. Cross-venue positions are tracked separately.

**Story arc:** Prerequisite for multi-venue paper trading.

### C14. Synchronized Time Range for Operator Dashboard (P2)

**What:** Add a shared `timeRange` state (1h / 4h / 1d / 1w) at the OperatorDashboard level. Pass it as a prop to DomainPnLChart, SentimentTimeline, BreachAlertLog, EquityPnLChart. Each component uses it as a query parameter.

**Verify:** Change timeRange → all panels update. Visual inspection that data ranges align.

**Story arc:** Turns the operator dashboard from "collection of independent widgets" into a coherent decision-making surface.

### C15. Migrate Remaining 45+ Components to `useApiData` (P2)

**What:** Systematic migration of all remaining raw `fetch()` components. Create a tracking checklist. Each component gets:
- `useApiData` for data fetching
- Stub detection badge
- Error state (using `ErrorAlert` component)
- Loading state (using spinner pattern)

**Verify:** `grep -r "await fetch(" --include="*.tsx" web/react/src/components/ | wc -l` returns 0.

**Story arc:** Completes the Sprint 18 data-fetching standardization.

### C16. Remove Duplicate `governance_router` Wiring (P2)

**What:** In `web/main.py`, remove one of the two `application.include_router(governance_router)` calls.

**Verify:** Server starts without warnings. Governance endpoints still reachable.

### C17. Daily Cap Reset Timezone (P2)

**What:** Use UTC consistently: `datetime.now(timezone.utc).strftime("%Y-%m-%d")` in `DomainCap.reset_if_new_day()`.

**Verify:** Test with mocked time crossing midnight UTC → cap resets exactly once.

### C18. Add WebSocket Heartbeat (P2)

**What:** Add a ping/pong heartbeat to `useMeridSocket`:
- Send `{event: "ping"}` every 30 seconds
- If no pong received within 10 seconds, mark as disconnected and trigger reconnect

**Verify:** Mock a server that stops responding → verify disconnect detection within 40 seconds.

**Story arc:** Prevents the "green dot lies" scenario where the connection indicator stays green on a dead connection.

### C19. Data Health Card on Operator Dashboard (P2)

**What:** Create a `DataHealthCard` component that polls `/api/v1/data/freshness` and shows per-feed staleness (green < 30s, amber < 120s, red > 120s). Add to OperatorDashboard overview tab.

**Verify:** Component renders with mock data. Stale feeds show red.

**Story arc:** Single-pane-of-glass feed health — critical for live trading trust.

### C20. Paper Engine Fee Model (P2)

**What:** Configurable per-venue fee schedule. Deduct from PnL on fill.

**Verify:** Place a paper trade → assert PnL includes fee deduction. Capital ladder tests updated.

**Story arc:** Paper→Live bridge — makes paper PnL more realistic.

---

## D. Prioritized Task List

| # | Title | Subsystem | Priority | Phase | What to implement & verify |
|---|-------|-----------|----------|-------|---------------------------|
| 1 | **Fix DomainPnLChart loading bug** | UI: Operator Dashboard | P0 | Immediate | Add `setLoading(false)` in success path. Verify chart renders. |
| 2 | **Remove SentimentTimeline fake data** | UI: Operator Dashboard | P0 | Immediate | Replace hardcoded fallback with error/empty state. Verify no fake headlines. |
| 3 | **Fix PM PnL hardcoded ±50%** | Paper Engine | P0 | Pre-paper | Replace mock PnL with mark-to-market. Test with capital ladder PM bracket. |
| 4 | **Unify mode enums** | Configuration | P0 | Pre-paper | Delete/alias 3 competing enums. Grep verify single definition. |
| 5 | **Fix `live=True` in plan execution** | Loop / Safety | P0 | Pre-paper | Set `live=` from `is_paper_or_mock()`. Unit test the flag. |
| 6 | **Persist kill switch state** | Risk | P1 | Pre-paper | JSON file + startup reload. Test restart scenario. |
| 7 | **Fail-closed reconciliation on first start** | Reconciliation | P1 | Pre-paper | `has_critical_discrepancies()` returns True until first run. |
| 8 | **Fix `force_align_from_venue` NameError** | Reconciliation | P1 | Pre-paper | Add missing import. Test call doesn't crash. |
| 9 | **Agent timeout + error tracking** | Agents / Loop | P1 | Pre-paper | 30s timeout, per-agent error counter, alert rule at 3/10 failures. |
| 10 | **Migrate 5 critical views to `useApiData`** | UI: Multiple | P1 | Pre-paper | Overview, PaperTrading, OperatorSummary, KalshiDashboard, KalshiPortfolio. |
| 11 | **Fix WebSocket retry math** | UI: WebSocket | P1 | Pre-paper | Fix double-increment in `useNativeWebSocket`. Verify 5 retries. |
| 12 | **Implement realized PnL reconciliation** | Reconciliation | P1 | Paper→Live bridge | Match open/close pairs, recompute PnL, assert delta < $1. |
| 13 | **Add venue dimension to position key** | Paper Engine | P1 | Paper→Live bridge | `{asset}_{side}_{type}_{venue}`. Update reconciliation + tests. |
| 14 | **Synchronized time range on Operator Dashboard** | UI: Operator | P2 | Paper→Live bridge | Shared timeRange state, pass to all chart/table components. |
| 15 | **Migrate remaining 45+ components to `useApiData`** | UI: Components | P2 | Paper→Live bridge | Systematic migration. `grep` verify zero raw `fetch()` in components. |
| 16 | **Remove duplicate governance_router** | API Wiring | P2 | Pre-paper | Delete duplicate `include_router` in main.py. |
| 17 | **Daily cap reset timezone** | Risk | P2 | Paper→Live bridge | Use UTC in `reset_if_new_day()`. Mock-time test. |
| 18 | **WebSocket heartbeat/keepalive** | UI: WebSocket | P2 | Paper→Live bridge | Ping every 30s, disconnect on no pong. |
| 19 | **Data Health card** | UI: Operator | P2 | Paper→Live bridge | New component polling `/api/v1/data/freshness`. Red/amber/green per feed. |
| 20 | **Paper engine fee model** | Paper Engine | P2 | Paper→Live bridge | Per-venue fee schedule. Deduct on fill. Capital ladder update. |
| 21 | **Per-agent failure alert rule** | Observability | P2 | Paper→Live bridge | `AgentConsecutiveFailureAlert` in system_observability.py. |
| 22 | **Thread-safe `_last_discrepancies`** | Reconciliation | P2 | Pre-paper | `threading.Lock` or `copy()` for reads. |
| 23 | **Consolidate two reconciliation modules** | Reconciliation | P2 | Paper→Live bridge | Unify into single status API. |
| 24 | **Remove TradeFloor `Math.random()`** | UI: TradeFloor | P2 | Pre-paper | Replace with real data or zero fallback. |
| 25 | **Unbounded audit trail rotation** | Audit | P2 | Multi-tenant future | Max 50MB, keep 5 files. |

---

## E. Thought Experiments: Breaking MERID

### Scenario 1: Price Feed Goes Stale (Binance API down for 30 min)

**Today:** Positions continue to show the last known price. PnL freezes. CQI may degrade slowly (DriftDetector detects staleness via PSI/Brier). But the paper engine's `_calculate_position_pnl` will use the stale `current_prices` dict — equity and PnL numbers are silently frozen.

**UI impact:** The `StalenessIndicator` component on the Operator Dashboard header would turn amber/red if `lastUpdated` is old enough. But `EquityPnLChart` would plateau silently — no "stale data" badge. `DomainPnLChart` would stay on its loading spinner (bug #1). The Overview's 5 raw-fetch hooks would silently show stale data with no indicator.

**Discovery:** Partial — operator might notice the staleness indicator but wouldn't know which specific feeds are affected without navigating to System → DataFreshnessPanel.

**Missing:** A hard gate that blocks execution when key price feeds are stale (e.g., no price update for symbol X in > 60s). Alert rule `PriceFeedStalenessAlert` per-symbol. Per-chart "data age" badges.

**Story arc connection:** The `DataFreshnessPanel` was added in Season 4 but only in the System tab. Needs to be elevated to Overview/Risk visibility.

### Scenario 2: Kill Switch Activated, Process Restarts

**Today:** Kill switch is in-memory (`self._global_kill_switch = True`). After restart, `ExecutionGuard.__init__()` sets it to `False`. Execution resumes immediately.

**Discovery:** Only if the operator checks the dashboard and notices the kill switch badge is gone. The kill switch button in the System tab would show "✅ Execution Enabled" — no historical record that it was ever activated.

**Missing:** Persisted kill switch state (see fix C6). Also: a "kill switch history" panel showing when it was activated/deactivated and by whom.

### Scenario 3: Agent Spams 1000 Orders/Minute

**Today:** The 5-second global cooldown limits execution to ~12 trades/minute max. Per-domain daily trade cap (50 trades/day default) would kick in after 50. The paper engine's `place_order` has no rate limiter of its own.

**Discovery:** The operator would see `plans_executed` counter climb in LoopMetrics. But the `TradeVerdict` log in `_trade_log` silently drops entries when it exceeds 1000 (trimmed to 500). Evidence is destroyed.

**What's adequate:** The layered caps are reasonable. But the cooldown is global, not per-agent — a legitimate slow agent could be blocked by a fast one's cooldown.

### Scenario 4: Dashboard Shows "Risk OK" While PnL Charts Disagree

**Today:** This is **highly likely** given the current architecture. The Risk view polls `/api/v1/risk/metrics` every 5s. `DomainPnLChart` polls `PIPELINE_PNL(range)` at `BACKGROUND` interval. The `EquityPnLChart` polls `/api/operator/equity-series` every 5s with its own time window. `OperatorStatusBar` gets data from `useOperatorSummary` (every 5s). Each source computes PnL differently (paper engine vs risk manager vs domain PnL aggregator vs equity series).

**Compounding issue:** `DomainPnLChart` is stuck on a loading spinner (bug #1), so it never shows PnL at all. `SentimentTimeline` shows fake data on failure (bug #2). The operator is looking at a dashboard where one chart is permanently loading, another shows fake data, and the remaining charts show different time windows and different PnL calculations.

**Missing:** A single PnL source of truth. A "consistency check" alert when risk PnL ≠ paper engine PnL ≠ equity series PnL by more than a threshold. Synchronized time ranges.

**Story arc connection:** This is the most dangerous class of MERID bug — not a crash, but **correct-looking data that is wrong**. Sprint 18's fake-data purge caught some instances, but Season 4's rapid feature addition re-introduced the problem at the dashboard level.

### Scenario 5: WebSocket Connection Dies Silently

**Today:** The `useNativeWebSocket` hook has MAX_RETRIES=5 but the retry math means it gives up after 2 attempts. After that, `connected` stays `false` and no real-time updates arrive. The `ConnectionStatusIndicator` in the TopBar would show "Offline" but only if the user looks at it.

**Compounding:** Components using `useMeridSocket` for real-time order/fill updates would stop updating. The `TradeFloor` would freeze. The `LiveRiskStrip` would show stale risk data. But polling-based components (those using `useApiData` with `pollingInterval`) would continue working — creating a split where some parts of the dashboard update and others don't.

**Missing:** Auto-reconnect after longer backoff. A prominent "real-time disconnected" banner. Re-fetch of recent events on reconnect to catch up on missed updates.

### Scenario 6: Reconciliation Reports "All Clear" But Hasn't Run

**Today:** On fresh startup, `has_critical_discrepancies()` returns `False` (empty list). The execution guard checks this gate and sees "no discrepancies" — proceeds with execution. Meanwhile, positions could be out of sync with venue balances.

**Compounding:** If the background reconciliation thread fails to start (e.g., import error), no reconciliation ever runs. `has_critical_discrepancies()` permanently returns False. Execution is permanently unguarded.

**Discovery:** The operator would need to manually check `/api/v1/reconciliation/status` to notice that `last_run` is null. No automatic alert.

**Missing:** Fail-closed semantics (fix C7). Alert rule for "reconciliation hasn't run in > 5 minutes."

### Scenario 7: Charts Render "Normal" But Data is Actually Stub/Mock

**Today:** The backend's `_stub` detection (in `useApiData`) adds `_stub: true` and `_stub_message` to responses when returning mock data. However, 50+ components use raw `fetch()` and never check for `_stub`. They render stub data as if it's real.

**Impact:** An operator could see a PaperTradingView with `$100,000 equity` and `+$5,000 daily PnL` that is entirely simulated — and have no way to know. The KalshiPortfolioView could show fake positions and fake fills from the stub layer without any indicator.

**Missing:** Systematic migration to `useApiData` (fixes C10, C15). Or alternatively: a global "stub mode" banner when any API response contains `_stub: true`.

---

*Generated 2026-02-15 (v2) by MERID platform audit. This document reflects the codebase state as of this date and incorporates findings from a deep-dive into 50+ components, 10+ hooks, adapters, consensus coordinator, and the main loop.*
