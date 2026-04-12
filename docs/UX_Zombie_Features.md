# UX Zombie-Feature Cleanup Playbook

> **Status:** Active — telemetry collection started after the Phase 1 dead-code
> cleanup (see `web/react/src/utils/uxTelemetry.ts`).  
> **Do not delete any zombie candidate without following this process.**

---

## 1. Decision rule

A live view may be classified as a **ZombieFeature candidate** when **all three**
conditions hold:

| Condition | Threshold |
|---|---|
| Session share (rolling 14-day window) | **< 1 %** of total sessions |
| Not in the always-exempt list (see §3) | confirmed |
| No open incident or active use by ops team | confirmed |

Use `getUxStats()` (exported from `utils/uxTelemetry.ts`) to pull the
14-day impression counts per view and compare to total sessions.

```ts
import { getUxStats } from './utils/uxTelemetry';
const stats = getUxStats();
// { total: number; byAction: Record<string, number>; lastEvent: number | null }
```

Or dump the raw event log:

```ts
import { exportUxEvents } from './utils/uxTelemetry';
console.log(exportUxEvents()); // JSON array
```

---

## 2. Mandatory deprecation process

**Step 1 — Open an issue**  
Tag it `status:zombie-candidate` with the view name, 14-day session %, and a
link to the `getUxStats()` snapshot.

**Step 2 — Feature-flag the navigation surface (not the code)**  
In `components/CommandPalette.tsx`, mark the view's `CommandItem` with
`legacy: true`.  
In `components/Sidebar.tsx`, remove or comment out the nav-array entry.  
The `kalshiOnly` feature flag in CommandPalette already filters `legacy: true`
items, so toggling that flag hides the view in production without touching
any route logic.

**Step 3 — Monitor for 14 more days**  
If no user complaints, no operator access, and no new telemetry hits, proceed.

**Step 4 — Delete**  
Open a PR that:  
- Removes the view file(s).  
- Removes the route in `App.tsx`.  
- Removes the `CommandItem` entry and the Sidebar entry.  
- Runs `tsc --noEmit` and the full test suite (must pass with ≤ baseline
  failures).

---

## 3. Always-exempt views

These views **must never be deleted** solely because of low session share.
They guard execution, safety, and operator control paths and require **explicit
human sign-off** from the trading-systems team even before step 2:

| View route | Reason |
|---|---|
| `operator` | Operator overrides and control plane |
| `kill-switch` | Trading kill-switch; Kalshi-critical |
| `risk-control` | Risk limits and circuit breakers |
| `lane-control` | Cross-timeframe promoter / deployment gate |
| `position-sizing` | Kelly/vol-adjusted sizing controls |
| `promotion-status` | Agent promotion pipeline status |

---

## 4. Current zombie candidates

> **Do not delete or hide any of these without telemetry and human sign-off.**
> They are listed here only as *observed candidates* pending 14-day data.

| View route | Observed signal | Next action |
|---|---|---|
| `promotion-status` | Low navigation frequency observed | Collect 14-day telemetry |
| `lane-control` | Low navigation frequency observed | Collect 14-day telemetry |
| `swarm-consensus` | Low navigation frequency observed | Collect 14-day telemetry |
| `calibration-dashboard` | Low navigation frequency observed | Collect 14-day telemetry |
| `kalshi-sentiment` | Low navigation frequency observed | Collect 14-day telemetry |

---

## 5. Background — Phase 1 dead-code cleanup (2026-04-12)

~188 confirmed-dead files were removed from `_legacy` subtrees:

| Batch | Removed |
|---|---|
| A | `views/_legacy/` (36 views) + `views/__tests__/_legacy/` (14 tests) |
| B | `components/_legacy/` (78) + `components/__tests__/_legacy/` (6 tests) |
| C | `components/_legacy_charts/` (27) |
| D | `hooks/_legacy/` (35) + `hooks/__tests__/_legacy/` (5 tests) |
| E | 8 dead util/service/api files + `services/__tests__/_legacy/` |

**Preserved:** `types/_legacy/risk.ts` — imported by the live
`hooks/useRiskProtections.ts` hook (`CircuitBreakerState` type).  
Do not delete this file until `useRiskProtections.ts` is updated to use a
canonical type from `types/api.ts`.
