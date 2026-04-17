# CT / UA end-to-end audit reference

Companion to [`RUNTIME_CHECKLIST_UA_CT.md`](RUNTIME_CHECKLIST_UA_CT.md). Describes **actual** log order and code paths (not aspirational).

## `ua_ct_metrics` (`merid/prediction/ua_ct_metrics.py`)

| Symbol | Role |
|--------|------|
| `record_ct_cycle(...)` | Per CT cycle; increments cumulative `evaluated` by batch size. Alias: `record_cycle`. |
| `record_order_accept` / `record_order_reject` | Router + CT order outcomes |
| `snapshot()` | Keys: `ct_cycles`, `evaluated`, `orders_accepted`, `orders_rejected`, `last_trace`, `last_updated` |
| `merge_agent_dict("sweep-all", ...)` | Merges CT snapshot into UA-shaped dict |

## `[UA-GRID]` (Agent Grid)

Emitted ~every 60s when `MERID_AGENT_GRID_CT_COORD=1` and venue name is `kalshi`:

```text
[UA-GRID] ct_running=%s ct_cycle=%s ua_ct_evaluated=%s ua_ct_orders_accepted=%s ua_ct_orders_rejected=%s
```

## `[UA-TRACE]` (Kalshi Continuous Trader)

Every `_run_cycle()` completion (including after `cycle_inner_failed`):

```text
[UA-TRACE] cycle=%d catalog_markets=%d universe_markets=%d evaluated=%d approved=%d vetoed=%d orders_submitted=%d trace_error=%s
```

`trace_error` is `none` on success, or a short error prefix if `_run_cycle_inner()` raised.

## CT direct REST path (no order router)

Typical order of interest:

1. `[UA-TRACE]` (end of cycle)
2. `[CT-TRACE]` (per candidate sizing)
3. `[RISK]` — `KalshiRiskManager.check_order` inside CT before POST
4. `[KALSHI_ORDER_INTENT]` → `[KALSHI_ORDER_RESULT]` (`source=kalshi_ct`)

**No** `[VENUE-GATE]` on this path — live eligibility uses CT’s `_live_api_orders_allowed` / settings, not `VenueGate.log_order_decision`.

## Order router LIVE path (`_route_live`)

Order of **checks** (simplified):

1. Global kill switch  
2. `VenueGate`: if `not gate.live_enabled` → `[VENUE-GATE] decision=deny reason=live_not_enabled`  
3. `ExecutionGate` (loop lag, reconciliation, etc.) — may return without `[VENUE-GATE] approve`  
4. `KalshiRiskManager.check_order` → `[RISK] decision=approve|deny`  
5. Category exposure / sentiment / market filters / order groups  
6. Immediately before exchange IO: `[VENUE-GATE] decision=approve reason=live_order_admitted`  
7. `[KALSHI_ORDER_INTENT]` → submit → `[KALSHI_ORDER_RESULT]` (`source=order_router`)

So **`[RISK]` runs before the admitting `[VENUE-GATE] approve`** on the router path. Early deny may be `[VENUE-GATE]` (live off) or `[RISK]` or execution gate (no dedicated `[VENUE-GATE]` tag).

## APIs

| Endpoint | Handler | Notes |
|----------|---------|--------|
| `GET /api/v1/kalshi/universe/agents` | `get_universal_agents` | Always includes merged `sweep-all`; safe-merge if CT metrics fail |
| `GET /api/v1/kalshi-grid/status` | `grid_status` | Top-level `ua_ct` from `ua_ct_metrics.snapshot()` |

There is **no** `/api/v1/kalshi/universal-agents` route.

## Profile env

Use **`KALSHI_CT_PROFILE=initial_live`**. No `KALSHI_CT_EDGE_PROFILE` in this repository.
