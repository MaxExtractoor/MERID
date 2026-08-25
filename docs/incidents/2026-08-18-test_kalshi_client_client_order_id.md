# Test: `tests/test_kalshi_client.py` failures

## Status
Open, tracked. Not introduced by 2026-08-18 bypass-closure work; surfaced when validating the test suite after firewall/adapter changes.

## Failing tests

| Class | Test | Failure |
|-------|------|---------|
| `TestPagination` | `test_get_positions_pagination` | `assert len(result.data) == 2` returns `1`; only the market position is parsed, the event-position leg is missing. |
| `TestOrderOperations` | `test_place_order_converts_price_to_cents` | `client._http_client.request.call_args` is `None` because `place_order` fails closed with `client_order_id missing`. |
| `TestOrderOperations` | `test_place_order_v2_wire_mapping[buy-yes-bid-0.6500]` | `call_args` is `None`; `client_order_id missing` before wire call. |
| `TestOrderOperations` | `test_place_order_v2_wire_mapping[sell-yes-ask-0.6500]` | Same `client_order_id missing`. |
| `TestOrderOperations` | `test_place_order_v2_wire_mapping[buy-no-ask-0.3500]` | Same `client_order_id missing`. |
| `TestOrderOperations` | `test_place_order_v2_wire_mapping[sell-no-bid-0.3500]` | Same `client_order_id missing`. |
| `TestOrderOperations` | `test_place_order_v2_reduce_only_wire` | Same `client_order_id missing`. |

## Common root cause

`KalshiVenueClient._build_v2_create_order_request` (and related V2 wire paths) now fails closed when `client_order_id` is missing:

```text
CRITICAL merid.event_venues.kalshi.client:client.py:2221
[KALSHI-V2-WIRE] client_order_id missing for ticker=KXBTC15M-001; failing closed
```

The tests construct a raw `VenueOrder` or `MarketOrder` directly and call `client.place_order_result(...)`. They do not run `order_identity.finalize_order_identity()` or `order_router.route_order_async()`, which are the canonical paths that allocate a durable `client_order_id`. In production the fail-closed behavior is correct, but the unit tests need to be updated to either:

1. Pre-allocate a `client_order_id` on the order object, or
2. Route through `route_order_async()` / `KalshiVenueClientExecutionPort` so identity is finalized.

## `test_get_positions_pagination` additional detail

Response payload includes a market position and an event position, but the parser returns only one `VenuePosition`. Likely the event-position branch of `get_positions` pagination is not populating a second `PortfolioPosition` into the result list.

## Acceptance criteria

- [ ] All `TestOrderOperations` V2 wire tests pass by supplying a valid `client_order_id` or by routing through the canonical order router.
- [ ] `test_place_order_converts_price_to_cents` reaches the HTTP mock and validates price-in-cents conversion.
- [ ] `test_get_positions_pagination` returns both the market and event positions (`len(result.data) == 2`).
- [ ] `test_kalshi_client.py` runs green end-to-end.
