# 2026-08-11 Unmatched-Exchange-Fill Circuit-Breaker Halt

## Summary

On 2026-08-11 at approximately 22:38:39 UTC the `TradingCircuitBreaker` tripped with
`unmatched_live_exchange_fill` for ticker `KXBTC15M-26AUG112145-45`. The halt was
process-wide and fail-closed. This document records the root cause, the
reconciliation record, the controlled release procedure, and the code changes made
 to prevent candidate churn while the breaker is set.

## Affected components

- `merid/governance/trading_circuit_breaker.py`
- `merid/loop_15m.py` (`_run_agent_grid_with_timeout`, `_run_one_cycle`)
- `merid/event_venues/kalshi/fills_ledger.py` (correlation lookup)
- `merid/event_venues/kalshi/order_router.py` (order gating)
- `data/trading_circuit_breaker_http_watermark.json`
- `data/reconciliation_record_6edd27fc.json`
- `data/risk_audit_chain.jsonl`

## Triggering fill

| Field | Value |
|-------|-------|
| `fill_id` | `6edd27fc-5274-6e46-6fc7-92ab0219585e` |
| `order_id` | `6ce07d03-b277-4828-bbcf-e7aefc74734d` |
| `client_order_id` (on wire) | `client_e2f7b5f653244b10` |
| `client_order_id` (in HTTP fill payload) | `null` |
| `intent_id` | `intent_e67241d991d14e539bd18c91c70f9b1c` |
| `trace_id` | `88408f7f-acca-4445-b22a-1373476f9a8e` |
| `ticker` | `KXBTC15M-26AUG112145-45` |
| `side` | `yes` |
| `count` | 1 |
| `price_cents` | 47 |
| `exchange_created_at` | `2026-08-12T01:38:34.000712+00:00` |
| `ingested_at` | `2026-08-12T01:38:39.244823+00:00` |
| `ingestion_source` | `http_poller` |

## Root cause

1. The order was submitted at 22:38:34 UTC and filled immediately. The order-router
   path recorded a `client_order_id` and generated a Kalshi `order_id`.
2. Approximately 5 seconds later, the HTTP fill poller fetched the same fill from
   Kalshi's `/portfolio/fills` endpoint.
3. Kalshi's HTTP fill payload did **not** echo the `client_order_id`, so the fill
   could only be correlated by `order_id`.
4. The `fills_ledger` pending-intent index had not yet durably updated its
   `order_id -> intent_id` mapping at the moment the circuit breaker performed its
   30-second grace lookup (`PENDING_INTENT_LOOKUP_SECONDS`).
5. The fill's exchange timestamp was newer than the persisted HTTP watermark, so the
   breaker treated it as a live, unmatched exchange fill and halted.

### Classification

`lost_intent` — the fill belonged to a legitimate MERID order; the intent record
existed in the system but the durable order-id correlation was not available in time
to match the HTTP fill. It is **not**:

- `other_writer` (the order was MERID's)
- `parser_defect` (the parser correctly read the HTTP payload and the wire `client_order_id`)
- `historical_false_positive` (the fill was live and newer than the watermark)
- `stale_order` (the fill was current)

## Evidence

- `server_output.log` line 52679: outbound order submit with `client_order_id=client_e2f7b5f653244b10`, `intent_id=intent_e67241d991d14e539bd18c91c70f9b1c`.
- `server_output.log` line 52690: router reports fill `6edd27fc-...` for the same `client_order_id`.
- `server_output.log` line 53252: breaker halts with `unmatched_live_exchange_fill`, `order_id=6ce07d03-...`, `client_order_id=null`.
- `server_output.log` line 53254: HTTP fill ingest log shows `side=yes count=1 price_cents=47`.
- `data/trading_circuit_breaker_http_watermark.json` current value: `2026-08-12T02:16:46.102593+00:00` (post-halt).
- `data/reconciliation_record_6edd27fc.json`: full structured reconciliation record.

## Exchange state at investigation end

As of the last log entries (2026-08-11 23:17:15 UTC):

- Kalshi balance: `equity=$6.14`, `cash=$5.66`, `positions=$0.48`.
- A live open position exists on `KXBTC15M-26AUG112330-30` side=yes, mid=48c.
- `PositionMonitor` is evaluating a take-profit exit at 52c; the breaker will reject it
  because it is not tagged as a manual emergency close.
- `get_balance` reported `available_cash != equity`, confirming an open position.

This invalidates the earlier 22:46 observation of `positions=$0.00`. A release is **not**
safe until this position is closed and the balance again shows `positions=$0.00`.

A live `audit_open_orders()` and a full `position_cache.get_all_positions()` reconciliation
must also be run.

## Code changes

### 1. Halt gating in `merid/loop_15m.py`

- `_run_agent_grid_with_timeout` now checks `TradingCircuitBreaker().halted` before
calling `agent_grid.run_cycle`. If halted, it logs a clear CRITICAL line, runs
`agent_grid.sync_from_rest(tick)` to keep exchange reconciliation alive, and returns
an empty candidate list. This stops signal generation, sizing, allocation, and entry
execution.
- `_run_one_cycle` now surfaces the halt in `no_trade_reason` as
`TRADING_CIRCUIT_BREAKER_HALT:<reason>` for observability.

### 2. Controlled release in `merid/governance/trading_circuit_breaker.py`

- Added `TradingCircuitBreaker.admin_release(operator, run_id, approval_token, *, force=False, trigger_fill_timestamp=None)`.
- Verifies (unless `force=True`):
  - Open positions are zero.
  - Open orders are zero and no untracked orders remain (`audit_open_orders`).
  - No `UNMATCHED_FILL` in the last 30 minutes.
  - HTTP watermark has advanced past the triggering fill.
  - `operator`, `run_id`, and a valid release token (`MERID_BREAKER_RELEASE_TOKEN` or
    `MERID_MANUAL_EMERGENCY_TOKEN`) are provided.
- Writes a `risk.trading_halt_released` record to `data/risk_audit_chain.jsonl` with
  the full check list, then calls `resume()`.

## Release procedure

Do **not** call `TradingCircuitBreaker.resume()` directly. Use the logged path:

```python
import asyncio
from merid.governance.trading_circuit_breaker import get_trading_circuit_breaker

breaker = get_trading_circuit_breaker()
result = await breaker.admin_release(
    operator="<operator-id>",
    run_id="<fresh-run-uuid>",
    approval_token="<MERID_BREAKER_RELEASE_TOKEN>",
    trigger_fill_timestamp="2026-08-12T01:38:34.000712+00:00",
)

assert result["released"] is True, result["failed_checks"]
```

Or from a synchronous script:

```python
import asyncio
result = asyncio.run(breaker.admin_release(...))
```

Pre-release checklist:

1. Run `audit_open_orders(cancel_untracked=False)` and confirm `open_orders_count == 0`
   and `untracked_order_ids == []`.
2. Confirm Kalshi balance `positions == 0.00` and `available_cash == equity`.
3. Confirm `fills_ledger.get_fills(since=...)` shows no `unmatched=True` fills in the
   last 30 minutes.
4. Confirm `data/trading_circuit_breaker_http_watermark.json` watermark is at or after
   `2026-08-12T01:38:34.000712+00:00`.
5. Set `MERID_BREAKER_RELEASE_TOKEN` (preferred) or use `MERID_MANUAL_EMERGENCY_TOKEN`.

If any check cannot be satisfied but the situation is an emergency, set `force=True`.
The audit record will still be written and will mark `force: true`.

## Manual close of the 23:17 open position

The open `KXBTC15M-26AUG112330-30` position will **not** close autonomously while the
breaker is set. `PositionMonitor` may generate a take-profit exit, but `order_router`
rejects it unless `is_manual_emergency_close=True` and `approval_token` is valid.

To close before release:

1. Use the Kalshi web UI or API to place a reducing order that flattens the position.
2. Alternatively, construct a `CanonicalOrderIntent` / `OrderIntent` with
   `is_manual_emergency_close=True`, `approval_token=<MERID_MANUAL_EMERGENCY_TOKEN>`,
   `purpose=exit`, and `qty_cc` equal to the open position size, then call
   `route_order_async()`.
3. Confirm `get_balance()` shows `positions=$0.00`.
4. Run `audit_open_orders(cancel_untracked=False)` and confirm zero open/untracked orders.

Only then run `admin_release()`.

## Follow-up work

- Harden `fills_ledger` correlation so an HTTP fill with `order_id` but no
  `client_order_id` is matched by `order_id` immediately if the order id is present
  in `_intents_by_order_id`, without requiring the pending-order grace window.
- Consider making `order_router` populate `order_id` into the fills ledger's
  `_intents_by_order_id` index synchronously before the HTTP poller can observe the
  fill.
- Validate the HTTP watermark and pending-intent lookup in
  `MERID_CIRCUIT_BREAKER_OBSERVE_ONLY=1` paper mode before the next production deploy.

## Related links

- `AGENTS.md` — "TradingCircuitBreaker halt gating and release (2026-08-11)"
- `data/reconciliation_record_6edd27fc.json`
- `docs/incidents/2026-08-09-fill-replay.md`
- `docs/incidents/2026-08-09-cross-leg-exposure.md`
