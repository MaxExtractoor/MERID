"""Transport-boundary payload assertions for reduce-only exits.

Captures the actual request dict handed to the HTTP layer
(``KalshiVenueClient._request_with_resilience``) after every adapter /
serializer has run, and asserts the Kalshi V2 contract:

  endpoint            /portfolio/events/orders
  reduce_only         true
  time_in_force       immediate_or_cancel
  expiration_time     absent (IOC cannot carry it)
  side/price          YES-normalized bid/ask + YES-space dollar price
  count               <= approved reducible quantity

Per Kalshi V2 semantics (docs.kalshi.com/api-reference/orders/create-order-v2):
  Close YES  -> ask @ YES-price   (realize >= limit)
  Close NO   -> bid @ YES-price   (realize >= 100 - limit; lower buy = more)
Both internal representations of the same economic exit must converge.
"""
import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# This test asserts the transport payload only. The firewall's approval /
# floor logic is covered by _test_floor_payload.py; observe-only mode keeps
# this test from requiring a live firewall decision record.
os.environ["MERID_EXIT_FIREWALL_OBSERVE_ONLY"] = "true"

from merid.event_venues.base import VenueOrder
from merid.event_venues.kalshi.client import (
    KalshiVenueClient,
    OperationResult,
)
import merid.event_venues.kalshi.client as client_mod


class _Capture:
    """Stubbed transport: records (method, path, json_data) and returns a
    canned success so place_order_result completes without network."""

    def __init__(self):
        self.calls = []

    async def __call__(self, method, path, *, params=None, json_data=None,
                       operation_name="", headers=None):
        self.calls.append({
            "method": method,
            "path": path,
            "json_data": json_data,
            "headers": headers,
        })
        return OperationResult.ok({"order": {"order_id": "test-oid"}})


def _make_client():
    client = KalshiVenueClient.__new__(KalshiVenueClient)
    cap = _Capture()
    client._request_with_resilience = cap
    # Bypass catalog lookup â€” ticker validity is checked against the live
    # catalog upstream; this test asserts the transport payload only.
    client_mod._validate_ticker_exists = lambda t: _ok_true()
    return client, cap


async def _ok_true():
    return True, None


def _order(*, side, outcome, price_dollars, size, tif="ioc", coid):
    o = VenueOrder(
        market_id="KXXRP15M-TESTW-30",
        side=side,
        size=Decimal(str(size)),
        price=Decimal(str(price_dollars)),
        order_type="limit",
        outcome_id=outcome,
        client_order_id=coid,
        time_in_force=tif,
        source="stop_candidate",
        reduce_only=True,
        exchange_index=2,
    )
    return o


def _assert_exit_payload(call, *, side, price_cents_bound, bound_op, max_qty):
    assert call["method"] == "POST"
    assert call["path"] == "/portfolio/events/orders", call["path"]
    body = call["json_data"]
    assert body["reduce_only"] is True, body
    assert body["time_in_force"] == "immediate_or_cancel", body
    assert "expiration_time" not in body, body
    assert body["side"] == side, body
    price_cents = int(round(float(body["price"]) * 100))
    if bound_op == "<=":
        assert price_cents <= price_cents_bound, (price_cents, body)
    else:
        assert price_cents >= price_cents_bound, (price_cents, body)
    qty = Decimal(str(body["count_fp"]))
    assert qty <= Decimal(str(max_qty)), (qty, body)
    return body


async def main():
    results = []

    # -- Close YES, held-side form: sell YES @ 0.36 -> ask @ 0.36 -----------
    client, cap = _make_client()
    res = await client.place_order_result(
        _order(side="sell", outcome="yes", price_dollars="0.36",
               size=3, coid="test_closeyes_held")
    )
    assert res.success, res.error
    body = _assert_exit_payload(cap.calls[0], side="ask",
                                price_cents_bound=36, bound_op=">=", max_qty=3)
    results.append(("close-YES held-side sell_yes@36", body["side"], body["price"]))

    # -- Close NO, held-side form: sell NO @ 0.36 -> bid @ 0.64 -------------
    client, cap = _make_client()
    res = await client.place_order_result(
        _order(side="sell", outcome="no", price_dollars="0.36",
               size=3, coid="test_closeno_held")
    )
    assert res.success, res.error
    body_no_held = _assert_exit_payload(cap.calls[0], side="bid",
                                        price_cents_bound=64, bound_op="<=",
                                        max_qty=3)
    results.append(("close-NO held-side sell_no@36", body_no_held["side"],
                    body_no_held["price"]))

    # -- Close NO, complementary form: buy YES @ 0.64 -> bid @ 0.64 ---------
    # Same economic exit as above; must converge to an equivalent request.
    client, cap = _make_client()
    res = await client.place_order_result(
        _order(side="buy", outcome="yes", price_dollars="0.64",
               size=3, coid="test_closeno_comp")
    )
    assert res.success, res.error
    body_no_comp = _assert_exit_payload(cap.calls[0], side="bid",
                                        price_cents_bound=64, bound_op="<=",
                                        max_qty=3)
    results.append(("close-NO complementary buy_yes@64", body_no_comp["side"],
                    body_no_comp["price"]))
    # Convergence: both representations of close-NO emit the same wire
    # side and the same YES-space price constraint.
    assert body_no_held["side"] == body_no_comp["side"] == "bid"
    assert abs(float(body_no_held["price"]) - float(body_no_comp["price"])) < 1e-9

    # -- Close YES, complementary form: buy NO @ 0.64 -> ask @ 0.36 ---------
    client, cap = _make_client()
    res = await client.place_order_result(
        _order(side="buy", outcome="no", price_dollars="0.64",
               size=3, coid="test_closeyes_comp")
    )
    assert res.success, res.error
    body_yes_comp = _assert_exit_payload(cap.calls[0], side="ask",
                                         price_cents_bound=36, bound_op=">=",
                                         max_qty=3)
    results.append(("close-YES complementary buy_no@64",
                    body_yes_comp["side"], body_yes_comp["price"]))

    # -- Fractional quantity: 0.26 contracts -> count_fp="0.26" -------------
    client, cap = _make_client()
    res = await client.place_order_result(
        _order(side="sell", outcome="no", price_dollars="0.36",
               size=0.26, coid="test_closeno_frac")
    )
    assert res.success, res.error
    body = cap.calls[0]["json_data"]
    assert body["count_fp"] == "0.26", body
    results.append(("fractional count_fp", "bid", body["count_fp"]))

    # -- Non-reduce_only order must NOT appear as a reduce-only exit --------
    client, cap = _make_client()
    o = _order(side="buy", outcome="yes", price_dollars="0.40", size=1,
               coid="test_entry_yes")
    o.reduce_only = False
    res = await client.place_order_result(o)
    assert res.success, res.error
    body = cap.calls[0]["json_data"]
    assert body.get("reduce_only") is False, body
    results.append(("entry order reduce_only=false", body["side"], body["price"]))

    print("\nWIRE PAYLOAD MATRIX: ALL CHECKS PASSED")
    for name, s, p in results:
        print(f"  {name}: side={s} price={p}")
    return 0


if __name__ == "__main__":
    rc = asyncio.run(main())
    print(f"WIRE_EXIT={rc}")
    sys.exit(rc)

