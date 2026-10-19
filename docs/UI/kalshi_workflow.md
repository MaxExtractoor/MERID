# MERID Kalshi 15m — Operator Workflow & UI Map

> Canonical reference for the MERID Kalshi 15-minute crypto trading UI.
> Stack: `web.main_15m_lean:app` on port **8011**, profile `kalshi_crypto_15m_v2`.
>
> **10 active views** · **5 sidebar groups** — Trading, Swarm Intelligence, Analytics, Operator, System.

---

## Sidebar Structure

```
TRADING                     SWARM INTELLIGENCE
  Dashboard                   Grid
  Markets
  Portfolio                 ANALYTICS
  Trade                       Risk
                              Calibration
OPERATOR
  Monitor                   SYSTEM
                              Logs
                              Settings
```

View registry lives in `web/react/src/types/views.ts`; navigation in `web/react/src/components/Sidebar.tsx`.

## View Inventory

| View ID | Component | Purpose |
|---------|-----------|---------|
| `dashboard` | `views/Dashboard.tsx` | System health, balance, PnL, live status overview |
| `kalshi-dashboard` | `views/KalshiDashboardView.tsx` | Market discovery: Kalshi 15m catalog, edge signals, market detail |
| `kalshi-portfolio` | `views/KalshiPortfolioView.tsx` | Positions, orders, fills, risk tabs, PnL chart |
| `trade` | `views/Trade.tsx` | Execution cockpit: orderbook, trade ticket, sizing |
| `grid` | `views/Grid.tsx` | 5-asset 15m agent grid status/control (BTC/ETH/SOL/XRP/DOGE) |
| `risk` | `views/Risk.tsx` | Risk state, drawdown, limits, circuit-breaker posture |
| `calibration` | `views/Calibration.tsx` | Model/tail calibration state and forecast accuracy |
| `monitor` | `views/Monitor.tsx` | Operator health: data freshness, reconciliation, alerts |
| `logs` | `views/Logs.tsx` | System log viewer |
| `settings` | `views/Settings.tsx` | Preferences and configuration surface |

## Operator Workflow (15m production)

### 1. VERIFY — startup state

After `.\start_15m.ps1` launches, confirm:

- `GET /api/v1/health` → `app=merid_15m_kalshi_crypto`, `profile=kalshi_crypto_15m_v2`
- `GET /api/v1/self-check` → runtime invariants pass
- Logs show `STARTING → PREFLIGHT_RUNNING → LIVE_ENTRIES_ENABLED` (or a structured denial reason if `LIVE_ENTRIES_HALTED`)

**Views:** Dashboard, Monitor. **Endpoints:** `/api/v1/health`, `/api/v1/self-check`.

### 2. OBSERVE — market state & edge

**Views:** Markets (Kalshi Dashboard), Grid. Watch the per-asset decision pipeline — spot signal, edge vs book, EV gate outcomes, veto reasons. In `LIVE_ENTRIES_HALTED` or observe-only mode the pipeline still computes and logs decisions without submitting.

### 3. TRACK — positions, orders, fills

**Views:** Portfolio, Monitor. Confirm reconciliation stays clean per ticker (exchange ↔ ledger ↔ cache ↔ monitor ↔ allocator ↔ pending reservations) and the trusted fill watermark is advancing.

### 4. PROTECT — risk posture & halts

**Views:** Risk, Monitor. Kill-switch and circuit-breaker state, drawdown, shard-collateral status (`insufficient_shard_balance` local rejects). Halts are fail-closed: entries block while reduce-only exits and cancels stay active.

### 5. RECOVER — after a halt

Entries resume only after the specific failure clears: new reconciliation snapshot, current non-regressing fill watermark, no unresolved audit discrepancy — per the recovery contract in [`AGENTS.md`](../../AGENTS.md). There is no "resume" button that bypasses these checks.

### 6. AUDIT — logs & telemetry

**Views:** Logs, Calibration. Structured startup telemetry includes `live_startup_preflight_passed`, `run_id`, `process_id`, `kalshi_account_id`, `venue_environment`, `fill_watermark`, `model_release_id`.

---

## Emergency Controls

- **`MERID_OBSERVE_ONLY=1`** (env, takes effect on restart) — read-only; entries never submit, exits/cancels preserved.
- **Kill switch** — per the policy in [`RUNBOOK.md`](../../RUNBOOK.md); the committed `data/kill_switch.json` must stay `active != true` (enforced by `scripts/check_kill_switch_default.py` in CI).
- **Halting without stopping the server** — an entry halt (`LIVE_ENTRIES_HALTED`) is the safe degradation: no new entries, full exit/cancel capability retained.

## Legacy note

Earlier revisions of this document described a 17-view "swarm" UI (Swarm Matrix, Lane Control, Kill Switch view, Sentiment view, Vol & Sizing view, Terminal). Those views belonged to the retired pre-15m stack; the current sidebar above is authoritative. The 8-stage workflow terminology survives in `types/views.ts` comments but the rendered navigation is the 10-view/5-group structure above.
