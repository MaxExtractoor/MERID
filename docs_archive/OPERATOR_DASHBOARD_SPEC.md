# MERID Operator Dashboard — Specification

**Created:** 2026-02-06  
**Status:** Draft  
**Goal:** A single unified view for operators to monitor, control, and debug MERID's
swarm-trading system during 24/7 operation.

## Scope

This spec defines the **Operator Dashboard** — a purpose-built view that
consolidates the most critical information an operator needs during live or
paper trading. It is distinct from the existing feature-specific views
(Trading, Agents, Risk, etc.) in that it prioritizes *at-a-glance safety* and
*one-click control* over depth.

## Design Principles

- **Glanceable:** Top-level status visible in < 2 seconds.
- **Actionable:** Pause, resume, mode-switch, and kill switch within 1 click.
- **Safe:** Destructive actions require confirmation; mode changes are logged.
- **Live:** All panels auto-refresh via polling or WebSocket; no manual reload.

---

## Panel Layout (5 sections)

```
┌─────────────────────────────────────────────────────────┐
│  1. STATUS BAR  (mode, uptime, circuit breaker, alerts) │
├──────────────────────┬──────────────────────────────────┤
│  2. PORTFOLIO &      │  3. SWARM HEALTH                 │
│     RISK SUMMARY     │     (agents, queues, errors)     │
├──────────────────────┼──────────────────────────────────┤
│  4. ACTIVITY STREAM  │  5. CONTROL PLANE                │
│     (orders, fills,  │     (pause, resume, mode,        │
│      decisions)      │      shutdown, scale)            │
└──────────────────────┴──────────────────────────────────┘
```

---

## 1. Status Bar

**Purpose:** Instant system-wide health at a glance.

| Widget | Data Source | Exists? | Notes |
|--------|-----------|---------|-------|
| Trading mode badge (SIM/PAPER/LIVE) | `GET /api/v1/trading-mode/mode` | ✅ `trading_mode.py` | Show colored badge |
| System uptime | `GET /api/system/health` | ✅ `health.py` | `uptime_hours` field |
| Circuit breaker status | `GET /api/risk/protections` | ✅ `useRiskProtections` hook | Green/yellow/red icon |
| Active alert count | `GET /api/v1/risk/alerts` | ✅ `Risk.tsx` polls this | Badge with count |
| WebSocket connection indicator | Client-side | ✅ `useMeridSocket` | Green dot when connected |
| Last heartbeat timestamp | `GET /api/system/health` | ✅ | `timestamp` field |

**Gap:** None — all data sources exist. Needs assembly into a compact bar component.

---

## 2. Portfolio & Risk Summary

**Purpose:** Current financial state and risk utilization.

| Widget | Data Source | Exists? | Notes |
|--------|-----------|---------|-------|
| Total equity / portfolio value | `GET /api/v1/trading/portfolio/summary` | ✅ `trading.py` | `total_value` |
| Unrealized P&L | Same endpoint | ✅ | `unrealized_pnl` |
| Daily P&L | `GET /api/v1/trading/stats` | ✅ `trading.py` | `pnl_today` |
| Open position count | `GET /api/v1/trading/portfolio/summary` | ✅ | `position_count` |
| Top 3 positions by size | Same endpoint | ✅ | Sort `positions[]` by `size` |
| Drawdown gauge | `GET /api/v1/risk/metrics` | ✅ `useRiskMetrics` | `maxDrawdown` |
| Margin utilization | Same endpoint | ✅ | `marginUsed / marginAvailable` |
| VaR (95%) | Same endpoint | ✅ | `var95` |
| Risk limit utilization bars | `GET /api/risk/limits` | ✅ | Per-limit % used |

**Existing components to reuse:**
- `LiveRiskStrip.tsx` — P&L, drawdown, margin, circuit breaker cards
- `LivePortfolioValue.tsx` — equity curve
- `Positions.tsx` — position cards with PnL

**Gap:** No *aggregated* risk-summary endpoint that returns all of the above in
one call. Currently requires 3+ API calls. Consider adding
`GET /api/operator/summary` that bundles portfolio + risk + mode in one response.

---

## 3. Swarm Health

**Purpose:** Are agents running, healthy, and keeping up?

| Widget | Data Source | Exists? | Notes |
|--------|-----------|---------|-------|
| Agent count (total/online/degraded/offline) | `GET /api/agents/summary` | ✅ `agents.py` | `total_agents`, `active_agents` |
| Per-agent status table | `GET /api/v1/system/agents` | ✅ `system_control.py` | Role, enabled, running |
| Agent latency / error rate | `useAgentsHealth` hook | ✅ `LiveAgentHealthPanel.tsx` | CPU, memory, latency, tasks |
| Dev Swarm task queue depth | `GET /api/dev-swarm/stats` | ✅ `dev_swarm_routes.py` | `pending_tasks` |
| Dev Swarm error rate | Same endpoint | ✅ | `failed_tasks / total_tasks` |
| Consensus history (last 5) | `GET /api/v1/system/consensus/history` | ✅ `system_control.py` | Approval rate |
| Drift status | `GET /api/dev-swarm/codebase-drift` | ✅ `codebase_drift_auditor` | OK/WARNING/CRITICAL |

**Existing components to reuse:**
- `LiveAgentHealthPanel.tsx` — metric cards + sortable agent table
- `SwarmActivityPanel.tsx` — recent swarm activity
- `ConsensusBoard.tsx` — consensus visualization
- `DriftDetectionPanel.tsx` — drift alerts

**Gap:** No single "swarm health score" metric. Consider computing
`online_agents / total_agents` + `error_rate < threshold` as a composite.

---

## 4. Activity Stream

**Purpose:** What just happened? Recent orders, fills, and agent decisions.

| Widget | Data Source | Exists? | Notes |
|--------|-----------|---------|-------|
| Recent orders (last 20) | `GET /api/v1/orders` | ✅ `trading.py` | With status badges |
| Recent fills | `GET /api/v1/fills` | ✅ | Price, size, venue |
| Agent decisions (last 10) | `GET /api/v1/system/decisions/recent` | ✅ `system_control.py` | Agent, type, confidence |
| Trade explanations | `GET /api/explainability/recent` | ✅ `explainability.py` | Rationale per decision |
| Audit trail entries | Internal (audit_trail.py) | ⚠️ No API | Hash-chained log exists but no REST endpoint |

**Existing components to reuse:**
- `OpenOrdersPanel.tsx` — live open orders with cancel
- `AgentActivityPanel.tsx` — recent agent actions
- `ExplainabilityPanel.tsx` — decision rationale viewer
- `TradeFloor.tsx` — WebSocket-driven event stream

**Gap:** No REST endpoint for `core/audit_trail.py` entries. Add
`GET /api/operator/audit-trail?limit=20` to surface hash-chained entries.

---

## 5. Control Plane

**Purpose:** One-click operator actions with guardrails.

| Action | Endpoint | Exists? | Guardrail |
|--------|---------|---------|-----------|
| **Start system** | `POST /api/v1/system/start` | ✅ `system_control.py` | — |
| **Stop system** | `POST /api/v1/system/stop` | ✅ | Confirmation dialog |
| **Shutdown Dev Swarm** | `POST /api/dev-swarm/shutdown` | ✅ `dev_swarm_routes.py` | Confirmation dialog |
| **Switch trading mode** | `POST /api/v1/trading-mode/mode` | ✅ `trading_mode.py` | Dropdown + reason field |
| **Get current mode** | `GET /api/v1/trading-mode/mode` | ✅ | — |
| **Set autonomous limits** | `POST /api/v1/trading-mode/limits` | ✅ | Form with validation |
| **Pause trading** | — | ❌ **MISSING** | Needs new endpoint |
| **Resume trading** | — | ❌ **MISSING** | Needs new endpoint |
| **Pause Dev Swarm** | — | ❌ **MISSING** | Needs new endpoint |
| **Resume Dev Swarm** | — | ❌ **MISSING** | Needs new endpoint |
| **Scale agents** | — | ❌ **MISSING** | Needs new endpoint |

**Existing components to reuse:**
- `QuickActionsPanel.tsx` — action buttons on Overview page

**Gaps (3 new endpoints needed):**

1. `POST /api/dev-swarm/pause` — Pause task processing without full shutdown
2. `POST /api/dev-swarm/resume` — Resume after pause
3. `POST /api/v1/trading-mode/pause` — Pause trading (set mode to MAINTENANCE)

---

## API Gap Summary

| # | Endpoint | Purpose | Priority |
|---|---------|---------|----------|
| 1 | `GET /api/operator/summary` | Bundled portfolio + risk + mode + swarm health | High |
| 2 | `POST /api/dev-swarm/pause` | Pause swarm task processing | High |
| 3 | `POST /api/dev-swarm/resume` | Resume swarm task processing | High |
| 4 | `GET /api/operator/audit-trail` | Surface hash-chained audit entries | Medium |
| 5 | `POST /api/v1/trading-mode/pause` | Quick-pause trading (→ MAINTENANCE) | Medium |

---

## React Component Plan

### New: `OperatorDashboard.tsx`

A single view that composes existing components into the 5-panel layout:

```
import { LiveRiskStrip } from './LiveRiskStrip';
import { LiveAgentHealthPanel } from './LiveAgentHealthPanel';
import { OpenOrdersPanel } from './OpenOrdersPanel';
import QuickActionsPanel from '../components/QuickActionsPanel';
import StatusIndicator from '../components/StatusIndicator';
// + new: OperatorStatusBar, OperatorControlPlane
```

### New sub-components:

| Component | Panel | Description |
|-----------|-------|-------------|
| `OperatorStatusBar.tsx` | 1 | Mode badge, uptime, circuit breaker, alert count |
| `OperatorControlPlane.tsx` | 5 | Pause/resume/mode/shutdown buttons with confirmations |
| `OperatorActivityStream.tsx` | 4 | Tabbed: Orders / Decisions / Audit Trail |

### Reused as-is:

| Component | Panel |
|-----------|-------|
| `LiveRiskStrip.tsx` | 2 |
| `LiveAgentHealthPanel.tsx` | 3 |
| `OpenOrdersPanel.tsx` | 4 |
| `SwarmActivityPanel.tsx` | 3 |

---

## Existing UI Inventory (for reference)

### Views (73 .tsx files)

| View | Lines | Status | Relevant to Operator Dashboard? |
|------|-------|--------|--------------------------------|
| `Overview.tsx` | 393 | ✅ Full | Portfolio summary, agent activity, quick actions |
| `Trading.tsx` | 483 | ✅ Full | Order form, positions, fills, risk strip |
| `TradeFloor.tsx` | 718 | ✅ Full | WebSocket event stream, consensus, risk summary |
| `Positions.tsx` | 189 | ✅ Full | Position cards with PnL |
| `Risk.tsx` | 427 | ✅ Full | Risk metrics, alerts, system health, position limits |
| `Agents.tsx` | 600 | ✅ Full | Agent fleet, health, explainability, drift, consensus |
| `Health.tsx` | 211 | ✅ Full | Service health, system metrics |
| `DevSwarm.tsx` | 96 | ✅ Full | Task list, stats, create task, readiness, codebase health |
| `LiveRiskStrip.tsx` | 155 | ✅ Full | Compact risk metrics row |
| `LiveAgentHealthPanel.tsx` | 87 | ✅ Full | Agent health metric cards + table |
| `OpenOrdersPanel.tsx` | — | ✅ Full | Live open orders |
| `Orders.tsx` | — | ✅ Full | Order history |
| `Logs.tsx` | — | ✅ Full | System logs viewer |

### API Routes (102 .py files in `web/api/`)

Key existing routes relevant to operator dashboard:

| Module | Prefix | Key Endpoints |
|--------|--------|--------------|
| `system_control.py` | `/api/v1/system` | `/start`, `/stop`, `/status`, `/agents`, `/decisions/recent`, `/consensus/history` |
| `trading_mode.py` | `/api/v1/trading-mode` | `/mode` (GET/POST), `/status`, `/limits`, `/history` |
| `trading.py` | `/api/v1/trading` | `/portfolio/summary`, `/stats`, `/perps/positions`, `/markets/positions` |
| `dev_swarm_routes.py` | `/api/dev-swarm` | `/tasks`, `/stats`, `/shutdown`, `/submit` |
| `health.py` | `/api/system` | `/health` |
| `agents_health.py` | `/api/agents` | `/health` |
| `monitoring.py` | `/api/monitoring` | Prometheus metrics |
| `explainability.py` | `/api/explainability` | Decision rationale |

---

## Implementation Order

1. **Week 1:** Add 3 missing API endpoints (pause/resume swarm, operator summary)
2. **Week 1:** Create `OperatorStatusBar.tsx` and `OperatorControlPlane.tsx`
3. **Week 2:** Create `OperatorDashboard.tsx` composing all panels
4. **Week 2:** Add `OperatorActivityStream.tsx` with audit trail tab
5. **Week 3:** Wire WebSocket live updates for all panels
6. **Week 3:** Add confirmation dialogs for destructive actions
7. **Week 4:** E2E Playwright tests for operator dashboard flows

---

## Success Criteria

- [ ] Operator can see system mode, health, and PnL in < 2 seconds
- [ ] Operator can pause/resume trading in 1 click + confirmation
- [ ] Operator can switch modes with reason logging
- [ ] All panels auto-refresh (polling or WebSocket)
- [ ] Destructive actions require confirmation dialog
- [ ] Dashboard works on tablet (responsive grid)
- [ ] Readiness scores S10-01 → 2, S10-02 → 2 (+3 points)
