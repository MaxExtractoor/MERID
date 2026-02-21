# MERID Season 5 — Execution Plan

*Derived from [MERID_AUDIT_2026_02_15.md](./MERID_AUDIT_2026_02_15.md) (v2, Comprehensive)*
*Generated 2026-02-15*

---

# Part 1: GitHub Issue Plan

## Labels

| Label | Color | Description |
|-------|-------|-------------|
| `P0-critical` | `#b60205` | Must fix before any paper trading session |
| `P1-important` | `#d93f0b` | Must fix before paper→live bridge |
| `P2-improvement` | `#fbca04` | Improves robustness, not blocking |
| `paper-engine` | `#0e8a16` | Paper trading engine subsystem |
| `reconciliation` | `#006b75` | Reconciliation & audit trail |
| `risk` | `#1d76db` | Risk management & kill switches |
| `mode-control` | `#5319e7` | Mode enums, feature flags |
| `agents` | `#c5def5` | Agent registry, orchestration, consensus |
| `ui-trust` | `#e99695` | UI data integrity, operator trust |
| `websocket` | `#bfd4f2` | WebSocket & real-time data |
| `observability` | `#d4c5f9` | Logging, alerts, monitoring |
| `api-wiring` | `#f9d0c4` | API routing, endpoint wiring |
| `bug` | `#d73a4a` | Confirmed bug in existing code |
| `safety` | `#b60205` | Could cause real-money loss |
| `fake-data` | `#d73a4a` | Fabricated data shown to operator |

## Milestones

| Milestone | Target | Description |
|-----------|--------|-------------|
| **S5-Phase1: Operator Trust** | Week 1-2 | Fix broken charts, remove fake data, fix safety bugs |
| **S5-Phase2: Data Integrity** | Week 3-4 | Migrate views to `useApiData`, fix reconciliation, persist kill switch |
| **S5-Phase3: Paper→Live Bridge** | Week 5-8 | Realized PnL reconciliation, fee model, synced dashboards, WebSocket hardening |

---

## Issues

### Issue #1 — Fix DomainPnLChart permanent loading spinner
**Labels:** `P0-critical`, `ui-trust`, `bug`
**Milestone:** S5-Phase1
**Assignee:** Frontend

**Description:**
`DomainPnLChart.tsx` has a loading-state bug where `setLoading(false)` is only called in the failure path (line 36). On successful fetch, the function returns at line 31 without resetting `loading`. The chart permanently displays "Loading PnL data..." and never renders.

**File:** `web/react/src/components/DomainPnLChart.tsx`
**Line:** 31

**Fix:**
```typescript
if (json.data) { setData(json.data); setLoading(false); return; }
```

**Acceptance criteria:**
- [ ] Open Operator Dashboard → Overview tab → DomainPnLChart renders data (not spinner)
- [ ] When API returns empty `data`, chart shows empty state (not spinner)
- [ ] Add test: mock successful API response → assert `loading` becomes `false`

---

### Issue #2 — Remove SentimentTimeline hardcoded fake data
**Labels:** `P0-critical`, `ui-trust`, `fake-data`, `bug`
**Milestone:** S5-Phase1
**Assignee:** Frontend

**Description:**
`SentimentTimeline.tsx` lines 69-80 render 5 hardcoded fake sentiment events (e.g., "Bitcoin breaks $105K resistance") when the API call fails. This directly contradicts the Sprint 18 fake-data purge and can mislead operators into making trading decisions based on fabricated headlines.

**File:** `web/react/src/components/SentimentTimeline.tsx`
**Lines:** 68-81

**Fix:**
Replace fake data fallback with empty state + error indicator. Set `events=[]`, `windows=[]`, show "Sentiment data unavailable" message.

**Acceptance criteria:**
- [ ] Stop backend → navigate to Intelligence tab → see "No sentiment data" (not fake headlines)
- [ ] No hardcoded event objects remain in the component
- [ ] `grep -n "Bitcoin breaks" web/react/src/components/SentimentTimeline.tsx` returns 0 hits

---

### Issue #3 — Fix prediction market PnL hardcoded ±50%
**Labels:** `P0-critical`, `paper-engine`, `safety`
**Milestone:** S5-Phase1
**Assignee:** Backend

**Description:**
`trading/paper_trading.py` `_calculate_position_pnl()` (lines 607-612) returns `size * 0.5` or `size * -0.5` for all prediction market positions regardless of actual market state. Equity, drawdown, and PnL numbers for PM positions are fabricated.

**File:** `trading/paper_trading.py`
**Lines:** 607-612

**Fix:**
Replace with mark-to-market using `current_price` vs `entry_price`:
```python
if position.side == "yes":
    pnl = (position.current_price - position.entry_price) * position.size_usd / position.entry_price
else:
    pnl = (position.entry_price - position.current_price) * position.size_usd / position.entry_price
```

**Acceptance criteria:**
- [ ] Capital ladder tests include PM positions with variable PnL
- [ ] PnL changes when `current_price` is updated
- [ ] `grep -n "0.5" trading/paper_trading.py | grep -i pnl` returns 0 hits for the hardcoded pattern

---

### Issue #4 — Unify competing mode enums
**Labels:** `P0-critical`, `mode-control`, `safety`
**Milestone:** S5-Phase1
**Assignee:** Backend

**Description:**
Four competing mode enums exist:
1. `trading/trade_mode.py` — `TradeMode` (MOCK/PAPER/LIVE) ← **canonical**
2. `trading/mode_controller.py` — `TradingMode` (PAPER/LIVE/HYBRID/AUTONOMOUS)
3. `trading/config/runtime_config.py` — `GlobalTradingMode` (OFFLINE/SIM/PAPER/LIVE/HYBRID)
4. `merid/prediction/venue_gate.py` — `TradingMode` (SIM/PAPER/LIVE)

Different modules reading different enums can disagree on whether the system is in paper or live mode.

**Fix:**
Delete or alias enums 2-4 to import from `trading/trade_mode.py`. Redirect all usages.

**Acceptance criteria:**
- [ ] `grep -r "class TradingMode" --include="*.py"` returns exactly 1 hit
- [ ] `grep -r "class GlobalTradingMode" --include="*.py"` returns 0 hits
- [ ] All existing tests pass
- [ ] New test: assert only one `TradeMode` source of truth exists

---

### Issue #5 — Fix `live=True` hardcoded in plan execution
**Labels:** `P0-critical`, `mode-control`, `safety`
**Milestone:** S5-Phase1
**Assignee:** Backend

**Description:**
`merid/loop.py` line 495 sets `live=True` in every `TradeRequest`, even when the system is in paper mode. The adapter's `submit_order()` hard guard is the sole defense against real-money execution. Any adapter that omits this guard would execute real trades.

**File:** `merid/loop.py`
**Line:** 495

**Fix:**
```python
from trading.trade_mode import is_paper_or_mock
request = TradeRequest(..., live=not is_paper_or_mock())
```

**Acceptance criteria:**
- [ ] Test: `MERID_TRADE_MODE=paper` → `TradeRequest.live == False`
- [ ] Test: `MERID_TRADE_MODE=live` + `MERID_ALLOW_LIVE_TRADES=true` → `TradeRequest.live == True`

---

### Issue #6 — Persist kill switch state across restarts
**Labels:** `P1-important`, `risk`
**Milestone:** S5-Phase2
**Assignee:** Backend

**Description:**
The kill switch is in-memory only (`self._global_kill_switch`). After process restart (OOM, deploy, crash), it silently deactivates. Execution resumes without operator awareness.

**Fix:**
Write kill switch state to `data/kill_switch.json` on activation. On startup, load and re-apply. Include timestamp and reason.

**Acceptance criteria:**
- [ ] Test: activate → restart process → `kill_switch_active == True`
- [ ] Test: deactivate → restart → `kill_switch_active == False`
- [ ] JSON file includes `activated_at`, `reason`, `activated_by`

---

### Issue #7 — Fail-closed reconciliation on first startup
**Labels:** `P1-important`, `reconciliation`, `safety`
**Milestone:** S5-Phase2
**Assignee:** Backend

**Description:**
`has_critical_discrepancies()` returns `False` when `_last_discrepancies` is empty (no reconciliation has ever run). On fresh startup, execution proceeds unguarded.

**File:** `merid/reconciliation.py`

**Fix:**
Return `True` (or "never_ran" sentinel) when no reconciliation has completed. Block execution until first successful reconciliation.

**Acceptance criteria:**
- [ ] Test: fresh start → `has_critical_discrepancies() == True` → execution blocked
- [ ] Test: after first successful reconciliation → gate opens
- [ ] Alert rule: "reconciliation hasn't run in > 5 minutes"

---

### Issue #8 — Fix `force_align_from_venue` NameError
**Labels:** `P1-important`, `reconciliation`, `bug`
**Milestone:** S5-Phase2
**Assignee:** Backend

**Description:**
`merid/reconciliation.py` line 226 calls `get_adapter(venue_name)` without importing it. The function — the only way to resolve critical reconciliation mismatches — is broken at the module level.

**File:** `merid/reconciliation.py`
**Line:** 226

**Fix:**
Add `from trading.adapters.registry import get_adapter` at the call site or top of file.

**Acceptance criteria:**
- [ ] `force_align_from_venue("alpaca")` callable without `NameError`
- [ ] Test: call with mock adapter → positions overwritten from venue state

---

### Issue #9 — Add agent timeout and per-agent error tracking
**Labels:** `P1-important`, `agents`
**Milestone:** S5-Phase2
**Assignee:** Backend

**Description:**
`registry.run_all()` in `merid/loop.py` line 342 is an unbounded `await` with no timeout. A hung agent stalls the entire loop indefinitely. Agent errors are logged as warnings with no per-agent tracking or alerting.

**Fix:**
1. Wrap in `asyncio.wait_for(timeout=30)`
2. Track per-agent consecutive error count
3. Add `AgentConsecutiveFailureAlert` (warning at 3, critical at 10)

**Acceptance criteria:**
- [ ] Test: mock agent that hangs → loop tick completes within 30s
- [ ] Test: mock agent that raises 3x → warning alert fires
- [ ] Test: mock agent that raises 10x → critical alert fires

---

### Issue #10 — Migrate 5 critical views/hooks to `useApiData`
**Labels:** `P1-important`, `ui-trust`
**Milestone:** S5-Phase2
**Assignee:** Frontend

**Description:**
These high-traffic views/hooks use raw `fetch()`, bypassing stub detection, auth tokens, and error standardization:
1. `Overview.tsx` — 5 hooks
2. `usePaperTrading.ts` — 3 fetches
3. `useOperatorSummary.ts` — 1 fetch + fix TS error (`e.message` on `unknown`)
4. `KalshiPortfolioView.tsx` — 5 fetches
5. `KalshiDashboardView.tsx` — 3 fetches

**Fix:**
Replace raw `fetch()` with `useApiData` in each. For dynamic endpoints (e.g., `PIPELINE_PNL(range)`), use `useApiData` with dynamic `endpoint` prop.

**Acceptance criteria:**
- [ ] Each migrated component: mock API returns `{ _stub: true }` → stub badge appears
- [ ] Each migrated component: mock API 500 → `ErrorAlert` shown
- [ ] `grep -c "await fetch(" web/react/src/views/Overview.tsx` returns 0
- [ ] `useOperatorSummary.ts` compiles under `strict: true`

---

### Issue #11 — Fix WebSocket retry math (double-increment)
**Labels:** `P1-important`, `websocket`, `bug`
**Milestone:** S5-Phase2
**Assignee:** Frontend

**Description:**
`useNativeWebSocket` in `useMeridSocket.ts` increments `retriesRef.current` by 3 per failed connection attempt (2 for not-opened + 1 for close). With `MAX_RETRIES=5`, only ~2 actual attempts occur.

**File:** `web/react/src/hooks/useMeridSocket.ts`

**Fix:**
Remove the `+= 2` for not-opened. Increment by 1 only in `onclose`.

**Acceptance criteria:**
- [ ] Test: mock WebSocket always fails → exactly 5 retry attempts
- [ ] After 5 failures, status is `max_retries_exceeded` (not silently dead)

---

### Issue #12 — Implement realized PnL reconciliation
**Labels:** `P1-important`, `reconciliation`
**Milestone:** S5-Phase3
**Assignee:** Backend

**Description:**
`trading/reconciliation.py` check #6 (lines 231-245) is a placeholder — it only checks `total_pnl` is finite. No actual matching of open/close trade pairs occurs.

**Fix:**
Match open→close trade pairs from `portfolio.trade_history`. Recompute realized PnL from fill prices. Compare against `portfolio.total_pnl`. Fail with `CheckStatus.ERROR` if delta > $1.

**Acceptance criteria:**
- [ ] Test: open BTC long → close at higher price → reconciliation passes with correct PnL
- [ ] Test: tamper with `total_pnl` → reconciliation fails with `ERROR`
- [ ] Test: partial close → correct per-leg realized PnL

---

### Issue #13 — Add venue dimension to position key
**Labels:** `P1-important`, `paper-engine`
**Milestone:** S5-Phase3
**Assignee:** Backend

**Description:**
Position key is `{asset}_{side}_{market_type}` (line 506) with no venue dimension. Same-asset trades on different venues merge incorrectly.

**File:** `trading/paper_trading.py`
**Line:** 506

**Fix:**
Change key to `{asset}_{side}_{market_type}_{venue}`.

**Acceptance criteria:**
- [ ] Capital ladder tests still pass
- [ ] Test: BTC long on Binance + BTC long on Coinbase → two separate positions
- [ ] Reconciliation uses venue-aware keys

---

### Issue #14 — Synchronized time range for Operator Dashboard
**Labels:** `P2-improvement`, `ui-trust`
**Milestone:** S5-Phase3
**Assignee:** Frontend

**Description:**
Each Operator Dashboard chart component (`EquityPnLChart`, `DomainPnLChart`, `SentimentTimeline`, `BreachAlertLog`) has its own independent time range selector. Panels can display different time windows simultaneously, misleading the operator.

**Fix:**
Add shared `timeRange` state at `OperatorDashboard` level. Pass as prop to all chart components. Each uses it as a query parameter.

**Acceptance criteria:**
- [ ] Change timeRange → all panels refresh with new range
- [ ] All charts show matching time axis labels

---

### Issue #15 — Migrate remaining 45+ components to `useApiData`
**Labels:** `P2-improvement`, `ui-trust`
**Milestone:** S5-Phase3
**Assignee:** Frontend

**Description:**
50+ components in `web/react/src/components/` use raw `fetch()`. This is the systemic trust gap identified in audit §B7.1. See the component table in the audit for the full list.

**Fix:**
Systematic migration. Each component gets `useApiData`, stub badge, `ErrorAlert`, and loading spinner.

**Acceptance criteria:**
- [ ] `grep -rc "await fetch(" web/react/src/components/ | grep -v ":0$" | wc -l` returns 0
- [ ] Spot-check 5 components: stub detection works, error state shows `ErrorAlert`

---

### Issue #16 — Remove duplicate `governance_router` wiring
**Labels:** `P2-improvement`, `api-wiring`
**Milestone:** S5-Phase3
**Assignee:** Backend

**Description:**
`web/main.py` imports and wires `governance_router` twice (lines 101+171, lines 334+381).

**Fix:** Remove the duplicate `include_router` call.

**Acceptance criteria:**
- [ ] Server starts without warnings
- [ ] Governance endpoints still reachable
- [ ] `grep -c "governance_router" web/main.py` returns expected count (import + 1 include)

---

### Issue #17 — Daily cap reset: use UTC
**Labels:** `P2-improvement`, `risk`
**Milestone:** S5-Phase3
**Assignee:** Backend

**Description:**
`DomainCap.reset_if_new_day()` uses `time.strftime("%Y-%m-%d")` (local time). Timezone changes cause incorrect daily cap resets.

**Fix:**
Use `datetime.now(timezone.utc).strftime("%Y-%m-%d")`.

**Acceptance criteria:**
- [ ] Test: mock time crossing midnight UTC → cap resets exactly once
- [ ] Test: mock time crossing midnight local (non-UTC) → cap does NOT reset

---

### Issue #18 — Add WebSocket heartbeat/keepalive
**Labels:** `P2-improvement`, `websocket`
**Milestone:** S5-Phase3
**Assignee:** Frontend

**Description:**
`useMeridSocket` has no heartbeat. If the server silently drops the connection (e.g., load balancer timeout), the client has no way to detect it. The green "connected" dot lies.

**Fix:**
Send `{event: "ping"}` every 30s. If no pong within 10s, mark disconnected and trigger reconnect.

**Acceptance criteria:**
- [ ] Test: mock server stops responding → disconnect detected within 40s
- [ ] Test: mock server responds to ping → connection stays healthy

---

### Issue #19 — Data Health card on Operator Dashboard
**Labels:** `P2-improvement`, `ui-trust`, `observability`
**Milestone:** S5-Phase3
**Assignee:** Frontend

**Description:**
No single-pane-of-glass feed health view on the Operator Dashboard. `DataFreshnessPanel` exists only in the System tab. Operators must navigate away from Overview to check feed health.

**Fix:**
Create `DataHealthCard` component polling `/api/v1/data/freshness`. Show per-feed staleness: green < 30s, amber < 120s, red > 120s. Add to Overview tab.

**Acceptance criteria:**
- [ ] Component renders with mock data
- [ ] Stale feeds (> 120s) show red indicator
- [ ] Card visible on Operator Dashboard → Overview tab

---

### Issue #20 — Paper engine fee model
**Labels:** `P2-improvement`, `paper-engine`
**Milestone:** S5-Phase3
**Assignee:** Backend

**Description:**
No fees modeled in the paper engine. Slippage is a flat 0.1%. Paper performance systematically exceeds live performance.

**Fix:**
Add configurable per-venue fee schedule. Deduct from PnL on fill.

**Acceptance criteria:**
- [ ] Test: place paper trade → PnL includes fee deduction
- [ ] Capital ladder tests updated with fee-aware assertions
- [ ] Fee config stored in `config/` (not hardcoded)

---

### Issue #21 — Per-agent failure alert rule
**Labels:** `P2-improvement`, `observability`, `agents`
**Milestone:** S5-Phase3
**Assignee:** Backend

**Description:**
No alert rule fires when an individual agent fails repeatedly. A malfunctioning agent degrades system quality silently.

**Fix:**
Add `AgentConsecutiveFailureAlert` to `web/api/system_observability.py`. Warning at 3 consecutive failures, critical at 10.

**Acceptance criteria:**
- [ ] Alert fires in test with mock failing agent
- [ ] Alert auto-clears when agent recovers

---

### Issue #22 — Thread-safe `_last_discrepancies`
**Labels:** `P2-improvement`, `reconciliation`
**Milestone:** S5-Phase3
**Assignee:** Backend

**Description:**
`merid/reconciliation.py` line 36: `_last_discrepancies` is module-level mutable state, not protected by a lock. Concurrent reconciliation calls produce torn reads.

**Fix:**
Wrap in `threading.Lock` or use `copy()` for reads.

**Acceptance criteria:**
- [ ] Test: concurrent reconciliation calls → no data corruption

---

### Issue #23 — Consolidate two reconciliation modules
**Labels:** `P2-improvement`, `reconciliation`
**Milestone:** S5-Phase3
**Assignee:** Backend

**Description:**
`trading/reconciliation.py` (balance-identity checks) and `merid/reconciliation.py` (venue-vs-internal) are independent systems. Neither references the other. No unified reconciliation status.

**Fix:**
Create unified `/api/v1/reconciliation/unified-status` that reports from both. Link the two in documentation.

**Acceptance criteria:**
- [ ] API returns combined report from both modules
- [ ] Operator Dashboard shows unified reconciliation status

---

### Issue #24 — Remove TradeFloor `Math.random()`
**Labels:** `P2-improvement`, `ui-trust`, `fake-data`
**Milestone:** S5-Phase3
**Assignee:** Frontend

**Description:**
`TradeFloor.tsx` contains 1 occurrence of `Math.random()` — residual fake data generation.

**Fix:**
Replace with real data source or zero fallback.

**Acceptance criteria:**
- [ ] `grep -n "Math.random" web/react/src/views/TradeFloor.tsx` returns 0 hits

---

### Issue #25 — Audit trail log rotation
**Labels:** `P2-improvement`, `observability`
**Milestone:** S5-Phase3
**Assignee:** Backend

**Description:**
`data/trade_audit.jsonl` and `merid/tick_log.py` grow unbounded. No rotation or size cap.

**Fix:**
Add log rotation: max 50MB, keep 5 files.

**Acceptance criteria:**
- [ ] Test: write > 50MB → old file rotated, new file created
- [ ] At most 5 rotated files exist

---

---

# Part 2: P0/P1 Engineer Checklist

Copy-pastable checklist for the 13 highest-priority items. Each entry has the file, the line, a one-liner fix, and a verification command.

```
═══════════════════════════════════════════════════════════════
  MERID P0/P1 CHECKLIST — 13 items — Season 5 Phase 1+2
═══════════════════════════════════════════════════════════════

──── P0: FIX BEFORE ANY PAPER TRADING SESSION ────────────────

[ ] #1  DomainPnLChart loading bug
      FILE: web/react/src/components/DomainPnLChart.tsx:31
      FIX:  Add `setLoading(false)` in success path
      CODE: if (json.data) { setData(json.data); setLoading(false); return; }
      TEST: Open Operator Dashboard → Overview → chart renders (not spinner)

[ ] #2  SentimentTimeline fake data
      FILE: web/react/src/components/SentimentTimeline.tsx:68-81
      FIX:  Delete hardcoded events array, set events=[], show empty state
      CODE: Remove lines 69-80 (fake events), add setEvents([]); setWindows([]); setLoading(false);
      TEST: grep -n "Bitcoin breaks" SentimentTimeline.tsx → 0 hits

[ ] #3  PM PnL hardcoded ±50%
      FILE: trading/paper_trading.py:607-612
      FIX:  Replace mock PnL with (current_price - entry_price) * size / entry
      TEST: python -m pytest tests/test_capital_ladder.py -k prediction

[ ] #4  Unify mode enums
      FILES: trading/mode_controller.py, trading/config/runtime_config.py,
             merid/prediction/venue_gate.py
      FIX:  Delete/alias competing TradingMode/GlobalTradingMode classes,
            redirect imports to trading.trade_mode.TradeMode
      TEST: grep -r "class TradingMode" --include="*.py" → exactly 1 hit
            grep -r "class GlobalTradingMode" --include="*.py" → 0 hits

[ ] #5  live=True hardcoded in loop
      FILE: merid/loop.py:495
      FIX:  live=not is_paper_or_mock()
      TEST: MERID_TRADE_MODE=paper python -c "..." → TradeRequest.live == False

──── P1: FIX BEFORE PAPER→LIVE BRIDGE ───────────────────────

[ ] #6  Persist kill switch
      FILE: merid/execution_guard.py
      FIX:  Write to data/kill_switch.json on toggle, reload on startup
      TEST: Activate → restart → assert still active

[ ] #7  Fail-closed reconciliation
      FILE: merid/reconciliation.py
      FIX:  has_critical_discrepancies() → True when never ran
      TEST: Fresh start → execution blocked until first recon completes

[ ] #8  force_align_from_venue NameError
      FILE: merid/reconciliation.py:226
      FIX:  Add: from trading.adapters.registry import get_adapter
      TEST: Call force_align_from_venue("alpaca") → no NameError

[ ] #9  Agent timeout + error tracking
      FILE: merid/loop.py:342
      FIX:  asyncio.wait_for(registry.run_all(), timeout=30)
            + per-agent error counter + AgentConsecutiveFailureAlert
      TEST: Mock hung agent → tick completes in <30s

[ ] #10 Migrate 5 views to useApiData
      FILES: Overview.tsx, usePaperTrading.ts, useOperatorSummary.ts,
             KalshiPortfolioView.tsx, KalshiDashboardView.tsx
      FIX:  Replace raw fetch() with useApiData hook
      TEST: grep -c "await fetch(" in each file → 0

[ ] #11 WebSocket retry math
      FILE: web/react/src/hooks/useMeridSocket.ts
      FIX:  Remove double-increment (retriesRef += 2) for !opened
      TEST: Mock failing WS → exactly 5 retries occur

[ ] #12 Realized PnL reconciliation
      FILE: trading/reconciliation.py:231-245
      FIX:  Match open/close pairs, recompute realized PnL, delta < $1
      TEST: Open → close sequence → recon passes; tamper PnL → recon fails

[ ] #13 Venue dimension in position key
      FILE: trading/paper_trading.py:506
      FIX:  Key = {asset}_{side}_{type}_{venue}
      TEST: BTC long on binance + BTC long on coinbase → 2 positions
```

---

---

# Part 3: Season 5 Roadmap

## Vision

Season 5 transforms MERID from **"structurally impressive but operationally untrustworthy"** into **"an operator can trust every pixel on the dashboard and every number in the paper engine."**

The audit revealed that MERID's backend architecture (loop, agents, consensus, adapters) is sound, but the **data surfaces** (UI, PnL calculations, reconciliation) have systematic trust gaps. Season 5 fixes these from the inside out.

## Phases

### Phase 1: Operator Trust (Week 1-2, 5 items)

**Theme:** *Fix everything that currently lies to the operator.*

**Goal:** After Phase 1, every chart renders, no fake data is shown, and the mode system cannot accidentally route paper orders to live venues.

| Sprint | Items | Estimated effort |
|--------|-------|-----------------|
| Sprint 47 | #1 DomainPnLChart bug, #2 SentimentTimeline fake data | 2 hours |
| Sprint 48 | #3 PM PnL mark-to-market, #4 Mode enum unification, #5 `live=True` fix | 6 hours |

**Dependencies:** None — all items are independent.

**Exit criteria:**
- `DomainPnLChart` renders on the Operator Dashboard
- `grep "Bitcoin breaks" SentimentTimeline.tsx` returns 0
- `grep -r "class TradingMode" --include="*.py"` returns 1
- `TradeRequest.live` reflects actual mode
- All existing tests pass

**Deliverables:**
- 5 bug fixes merged
- Updated capital ladder tests with PM PnL assertions
- Mode unification migration guide (for any downstream consumers)

---

### Phase 2: Data Integrity (Week 3-4, 8 items)

**Theme:** *Ensure every data path from backend to UI is honest, authenticated, and resilient.*

**Goal:** After Phase 2, the kill switch survives restarts, reconciliation fails-closed, agents can't hang the loop, and the 5 most-trafficked views use `useApiData` with stub detection.

| Sprint | Items | Estimated effort |
|--------|-------|-----------------|
| Sprint 49 | #6 Kill switch persistence, #7 Fail-closed reconciliation, #8 `force_align` fix | 4 hours |
| Sprint 50 | #9 Agent timeout + error tracking, #11 WebSocket retry fix | 4 hours |
| Sprint 51 | #10 Migrate 5 critical views to `useApiData` | 8 hours |

**Dependencies:**
- #8 depends on adapter registry being importable (trivial)
- #10 depends on `useApiData` hook being stable (it is — Season 2)

**Exit criteria:**
- Kill switch survives process restart (test)
- Fresh startup blocks execution until reconciliation completes (test)
- `force_align_from_venue()` callable without error (test)
- Agent timeout fires within 30s (test)
- WebSocket makes 5 retry attempts, not 2 (test)
- `grep "await fetch(" Overview.tsx` returns 0

**Deliverables:**
- 8 fixes merged
- `AgentConsecutiveFailureAlert` rule in observability
- Updated `useMeridSocket` with correct retry logic
- 5 views migrated with stub detection

---

### Phase 3: Paper→Live Bridge (Week 5-8, 12 items)

**Theme:** *Make paper trading accounting-grade accurate and the dashboard a coherent decision surface.*

**Goal:** After Phase 3, paper PnL includes fees, reconciliation validates realized PnL, positions are venue-aware, dashboard time ranges are synchronized, and all remaining components use `useApiData`.

| Sprint | Items | Estimated effort |
|--------|-------|-----------------|
| Sprint 52 | #12 Realized PnL reconciliation, #13 Venue position key | 8 hours |
| Sprint 53 | #14 Synced dashboard time range, #15 Migrate 45+ components (batch 1: 15 components) | 10 hours |
| Sprint 54 | #15 (batch 2: 15 components), #16 governance_router dedup, #17 UTC daily cap | 8 hours |
| Sprint 55 | #15 (batch 3: 15 components), #18 WebSocket heartbeat, #19 Data Health card | 10 hours |
| Sprint 56 | #20 Fee model, #21 Agent failure alerts, #22 Thread-safe reconciliation, #23 Unified recon API, #24 TradeFloor Math.random, #25 Audit trail rotation | 8 hours |

**Dependencies:**
- #12 depends on #3 (PM PnL must be real before validating it)
- #13 depends on #3 (position keys change, need correct PnL first)
- #14 depends on #1 (DomainPnLChart must render before syncing its range)
- #15 depends on #10 (pattern established by first 5 migrations)

**Exit criteria:**
- Realized PnL reconciliation catches $1+ discrepancies (test)
- Multi-venue positions tracked separately (test)
- All Operator Dashboard charts share a time range (visual)
- `grep -rc "await fetch(" components/ | grep -v ":0$"` returns 0
- Fee model deducts on fill (test)
- Audit trail rotates at 50MB (test)

**Deliverables:**
- 12 fixes merged
- Complete `useApiData` migration (0 raw `fetch()` in components)
- Accounting-grade paper engine (mark-to-market + fees + realized PnL reconciliation)
- Coherent Operator Dashboard with synced time ranges
- Data Health card
- WebSocket heartbeat

---

## Season 5 Summary

| Metric | Start (2026-02-15) | Phase 1 End | Phase 2 End | Phase 3 End |
|--------|--------------------:|------------:|------------:|------------:|
| **Broken charts** | 1 (DomainPnLChart) | 0 | 0 | 0 |
| **Fake data sources** | 2 (Sentiment, TradeFloor) | 1 | 1 | 0 |
| **Raw `fetch()` components** | 50+ | 50+ | 45+ | 0 |
| **Mode enum definitions** | 4 | 1 | 1 | 1 |
| **Kill switch survives restart** | No | No | Yes | Yes |
| **Reconciliation fail-closed** | No | No | Yes | Yes |
| **Realized PnL verified** | No | No | No | Yes |
| **Dashboard time synced** | No | No | No | Yes |
| **Paper fees modeled** | No | No | No | Yes |
| **WS retries correct** | No (2/5) | No | Yes (5/5) | Yes + heartbeat |
| **Total estimated effort** | — | 8 hrs | 16 hrs | 44 hrs |

**Total Season 5 effort: ~68 engineer-hours across 10 sprints (5-8 weeks).**

---

*This plan is derived from MERID_AUDIT_2026_02_15.md v2. Review and update as fixes are landed.*
