# MERID Event Catalog – Phase 6

Version: 1.1  
Date: January 13, 2026  
Scope: Events permitted to mutate `DashboardState` via the EventBus (`web/static/js/dashboard-v2.js`). Every dispatch must match the schema here **before** reducers fire.

---

## System events

| Event | Payload | Notes |
| --- | --- | --- |
| `SYSTEM_BOOTSTRAP_STARTED` | `{ timestamp: number; build: string; reason: string }` | Emitted by `initializeDashboardData()` to mark cold-start hydration. Marks `system.bootstrapping = true` and resets `bootstrapStatus`. |
| `SYSTEM_BOOTSTRAP_COMPLETED` | `{ timestamp: number; durationMs: number; success: boolean; errors: string[]; reason: string }` | Completes bootstrap; writes duration, errors, and success history. |
| `SYSTEM_REFRESH_STARTED` | `{ timestamp: number; reason: string }` | Sent before scheduled/on-demand snapshot refresh begins. Sets `refreshStatus.status = 'running'`. |
| `SYSTEM_REFRESH_COMPLETED` | `{ timestamp: number; durationMs: number; success: boolean; errors: string[]; reason: string }` | Finalizes refresh, logging success/failure and surfaced errors. |
| `SYSTEM_HEALTH_UPDATE` | `{ timestamp: number; health: Partial<SystemHealth>; meta?: Record<string, HealthMetaPatch> }` | Updates subsystem health lights plus optional explanatory metadata (message, updatedAt). |

### Rules

- `timestamp` values are epoch milliseconds and must be monotonic relative to `system.lastEvent`.
- `errors` must always be an array (empty allowed). Provide at least one error string when `success === false`.
- `meta` entries merge into `system.healthMeta` and should include human-readable `message`.

---

## Market events

| Event | Payload | Notes |
| --- | --- | --- |
| `MARKET_SNAPSHOT_RECEIVED` | `{ snapshotId: string; timestamp: number; overview: MarketOverview \| null; prices: PriceEntry[] }` | Full market hydration fetched via HTTP before ticks flow in. |
| `PRICE_TICK_RECEIVED` | `{ symbol: string; timestamp: number; price: number; bid?: number; ask?: number; volume24h?: number; change24h?: number }` | WebSocket tick delta; requires `markets.snapshotId` to exist. |

---

## Portfolio events

| Event | Payload |
| --- | --- |
| `PORTFOLIO_SNAPSHOT_RECEIVED` | `{ timestamp: number; summary: PortfolioSummary; positions: PositionEntry[] }` |

Positions array may be empty but never undefined.

---

## Agent events

| Event | Payload |
| --- | --- |
| `AGENT_SNAPSHOT_RECEIVED` | `{ snapshotId: string; agents: AgentSummary[]; timestamp?: number }` |

Reducers stamp `lastUpdate = payload.timestamp || Date.now()`.

---

## Risk events

| Event | Payload |
| --- | --- |
| `RISK_SNAPSHOT_RECEIVED` | `{ timestamp: number; metrics: RiskMetrics }` |

---

## Consensus events

| Event | Payload |
| --- | --- |
| `CONSENSUS_SNAPSHOT_RECEIVED` | `{ timestamp: number; strength: number; activeVotes: number; dissentRate: number }` |

---

## Alert events

| Event | Payload |
| --- | --- |
| `ALERTS_SNAPSHOT_RECEIVED` | `{ timestamp: number; alerts: AlertEntry[] }` |

---

## Audit ledger

| Event | Payload |
| --- | --- |
| `AUDIT_TRAIL_SNAPSHOT_RECEIVED` | `{ timestamp: number; events: AuditEvent[] }` |

---

## UI events

| Event | Payload | Constraints |
| --- | --- | --- |
| `UI_FILTER_CHANGE` | `{ timestamp: number; filters: Partial<UIFilters> }` | The **only** event allowed to mutate `ui.filters`. Must be dispatched via `applyGlobalFilters`. |

---

## Validation and invariants

1. **Schema validation** – `EventSchemas` in `dashboard-v2.js` asserts required fields, types, and array presence before reducers run.  
2. **State invariants** – `validateState` enforces domain-level rules (truth slices, arrays, numeric guards) after every reducer execution.  
3. **Source control** – Only bootstrapper, refresh loop, HTTP snapshot fetchers, and the WebSocket client dispatch these events. UI code may only emit `UI_FILTER_CHANGE`.  
4. **Truth pipeline** – `SYSTEM_BOOTSTRAP_*`, `SYSTEM_REFRESH_*`, and `SYSTEM_HEALTH_UPDATE` feed the UI truth panel. Missing events immediately surface as stale or “unknown” indicators.

Any new event must be documented here **before** it appears in code. Uncatalogued dispatches are unconstitutional and must be rejected during review.
