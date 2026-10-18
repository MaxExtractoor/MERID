"""Approval-binding integration test (2026-10-17) â€” TRANSPORT-BOUNDARY.

Canonical exit intent -> enforcing firewall -> approval bound to the approved
order -> port adapter -> venue client -> captured HTTP request.

The HTTP transport is stubbed at ``_request_with_resilience``; this proves
the *serialized request* carries exactly the economics the firewall approved,
and that any post-approval mutation of a protected field is rejected.  It
does NOT submit live orders.

Protected fields asserted: market, outcome/action (side), quantity, limit
price, reduce_only, time_in_force, exchange_index, position generation (via
client_order_id rebinding), emergency permission (an ordinary approval cannot
transmit a below-floor price).  Account/subaccount: orders carry no per-order
account field â€” account scope is bound by the authenticated client
credential; asserted absent from the payload.
"""
import asyncio
import os
import sys
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("PYTEST_CURRENT_TEST", "approval_binding")
os.environ["MERID_EXIT_FIREWALL_OBSERVE_ONLY"] = "0"  # ENFORCING
os.environ["MERID_EXIT_STATE_PATH"] = str(
    Path(__file__).resolve().parents[2] / "data" / "_test_exit_state_nonexistent.json"
)
os.environ.pop("DEBUG_ALLOW_MANUAL_ORDERS", None)

from merid.settings import settings
settings.MERID_ENV = "production"  # enforcing path requires production gate

import merid.event_venues.kalshi.client as client_mod
from merid.event_venues.base import VenueOrder
from merid.event_venues.kalshi.client import KalshiVenueClient, OperationResult
from merid.event_venues.kalshi.execution_risk_firewall import (
    BookDepth, ExecutionRiskFirewall, PositionSnapshot,
)
from merid.event_venues.kalshi.order_intent_contract import normalize_order
from merid.event_venues.kalshi.order_router import OrderIntent
from merid.event_venues.kalshi.port import CreateOrderRequest
from merid.event_venues.kalshi.venue_client_port import KalshiVenueClientExecutionPort

TICKER = "KXXRP15M-TESTBIND-30"
ENTRY = 32


class _Capture:
    def __init__(self):
        self.calls = []

    async def __call__(self, method, path, *, params=None, json_data=None,
                       operation_name="", headers=None):
        self.calls.append({"method": method, "path": path,
                           "json_data": json_data, "headers": headers})
        return OperationResult.ok({"order": {"order_id": "test-oid"}})


def _mk_fw():
    fw = ExecutionRiskFirewall.get_instance()
    fw._decisions.clear()
    pos = PositionSnapshot(position_cc=-300, side="no", avg_price_cents=ENTRY,
                           version="t1", snapshot_age_ms=0,
                           parent_entry_fill_id="f_entry")
    book = BookDepth(vwap_cents=33, available_qty_cc=1000,
                     levels=[(33, 1000)], best_bid_cents=33,
                     best_ask_cents=None, book_age_ms=10,
                     book_sequence=1, marginal_price_cents=33)

    async def _fp(t):
        return pos
    fw._fetch_position = _fp
    fw._fetch_book = lambda c: book
    fw._market_active_and_before_deadline = lambda t: True
    fw._has_in_flight_exit = lambda c: None
    return fw


def _mk_client():
    client = KalshiVenueClient.__new__(KalshiVenueClient)
    cap = _Capture()
    client._request_with_resilience = cap
    client_mod._validate_ticker_exists = _ok_true
    return client, cap


async def _ok_true(t):
    return True, None


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


results = []
fw = _mk_fw()

# â”€â”€ Step 1: canonical exit intent (ordinary profit exit, sell no @33) â”€â”€â”€â”€â”€â”€
raw = OrderIntent(
    ticker=TICKER, price_cents=33, count=3.0, side="no", action="sell",
    time_in_force="ioc", source="position_monitor_exit",
    entry_or_exit="exit", reduce_only=True, exit_reason="take_profit",
    reason="take_profit", parent_entry_fill_id="f_entry",
    parentage_status="CANONICAL_FILL", exchange_index=2,
)
canonical = normalize_order(raw, exchange_position_cc=-300,
                            position_avg_price_cents=ENTRY, position_side="no")

# â”€â”€ Step 2: enforcing firewall decision â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
d = run(fw.validate_exit(canonical, raw))
print(f"approve  : status={d.status} limit={d.approved_limit_cents} "
      f"emergency={d.emergency} tif={d.time_in_force} ro={d.reduce_only} "
      f"shard={d.exchange_index}")
assert d.status == "approved", d.reason
assert d.approved_limit_cents >= 35  # floored to fee-adjusted breakeven
assert d.emergency is False          # ordinary exit: no loss authority used
assert d.exchange_index == 2

# â”€â”€ Step 3: adapter -> captured request (stubbed transport) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
client, cap = _mk_client()
port = KalshiVenueClientExecutionPort(client=client)


def _req(**over):
    kw = dict(
        ticker=TICKER, side="sell", outcome="no", size=Decimal("3.0"),
        price_cents=d.approved_limit_cents, order_type="limit",
        time_in_force="IOC", client_order_id=d.client_order_id,
        reduce_only=True, source="position_monitor_exit",
        exchange_index=2,
        metadata={"firewall_decision_id": d.decision_id,
                  "entry_or_exit": "exit"},
    )
    kw.update(over)
    return CreateOrderRequest(**kw)


resp = run(port.create_order(_req()))
print(f"order    : success={resp.success} err={resp.error}")
assert resp.success, resp.error
body = cap.calls[0]["json_data"]
assert cap.calls[0]["path"] == "/portfolio/events/orders"
# sell NO @36 -> bid @0.6400; serialized economics == approved economics
assert body["side"] == "bid", body
assert int(round(float(body["price"]) * 100)) == 100 - d.approved_limit_cents
assert Decimal(body["count_fp"]) == 3, body
assert body["reduce_only"] is True
assert body["time_in_force"] == "immediate_or_cancel"
assert "expiration_time" not in body
assert "subaccount" not in body and "subaccount_number" not in body
assert body["client_order_id"] == d.client_order_id
assert body["exchange_index"] == 2
results.append("approved order -> captured wire economics == approval")

# â”€â”€ Step 4: post-approval mutation of every protected field -> reject â”€â”€â”€â”€â”€
mutations = [
    ("market",         dict(ticker="KXXRP15M-OTHER-00"),  "market:"),
    ("side",           dict(side="buy"),                  "action:"),
    ("quantity",       dict(size=Decimal("4.0")),         "qty_cc:"),
    ("limit price",    dict(price_cents=30),              "price_c:"),
    ("reduce_only",    dict(reduce_only=False),           "reduce_only:"),
    ("time_in_force",  dict(time_in_force="GTC"),         "tif:"),
    ("exchange_index", dict(exchange_index=0),            "exchange_index:"),
]
for name, over, needle in mutations:
    r = run(port.create_order(_req(**over)))
    ok = (not r.success) and r.error and "firewall:" in r.error and needle in r.error
    print(f"mutate {name:14s}: success={r.success} err={r.error}")
    assert ok, f"mutation {name} must be rejected with {needle}: {r.error}"
    results.append(f"mutate {name} -> rejected")

# position-generation rebinding: a different coid (new order lineage) cannot
# reuse this approval token.
r = run(port.create_order(_req(client_order_id="merid_other_generation")))
print(f"gen rebind : success={r.success} err={r.error}")
assert not r.success and "invalid" in r.error
results.append("client_order_id rebind -> invalid token")

# forged token
r = run(port.create_order(_req(metadata={"firewall_decision_id": "bogus",
                                         "entry_or_exit": "exit"})))
print(f"bad token  : success={r.success} err={r.error}")
assert not r.success and "invalid" in r.error
results.append("forged decision_id -> invalid token")

# missing token
r = run(port.create_order(_req(metadata={"entry_or_exit": "exit"})))
print(f"no token   : success={r.success} err={r.error}")
assert not r.success and "approval" in r.error
results.append("missing token -> rejected")

# â”€â”€ Step 5: ordinary approval cannot carry a below-floor emergency price â”€â”€â”€
r = run(port.create_order(_req(price_cents=13)))
print(f"ord->emerg : success={r.success} err={r.error}")
assert not r.success and "price_c:" in r.error, r.error
results.append("ordinary approval @ below-floor price -> rejected")

# â”€â”€ Step 6: authorized emergency approval transmits its own economics â”€â”€â”€â”€â”€
raw_em = OrderIntent(
    ticker=TICKER, price_cents=13, count=3.0, side="no", action="sell",
    time_in_force="ioc", source="position_monitor_exit",
    entry_or_exit="exit", reduce_only=True, exit_reason="loss_cap",
    reason="loss_cap", parent_entry_fill_id="f_entry",
    parentage_status="CANONICAL_FILL", exchange_index=2,
    exit_class="emergency", emergency_type="POSITION_LOSS_BUDGET",
    authorization_source="position_monitor",
    position_generation_id="f_entry",
)
can_em = normalize_order(raw_em, exchange_position_cc=-300,
                         position_avg_price_cents=ENTRY, position_side="no")
d_em = run(fw.validate_exit(can_em, raw_em))
print(f"emerg    : status={d_em.status} limit={d_em.approved_limit_cents} "
      f"emergency={d_em.emergency}")
assert d_em.status == "approved" and d_em.approved_limit_cents == 13
assert d_em.emergency is True

cap2 = _Capture()
client._request_with_resilience = cap2
resp2 = run(port.create_order(_req(
    price_cents=13,
    client_order_id=d_em.client_order_id,
    metadata={"firewall_decision_id": d_em.decision_id,
              "entry_or_exit": "exit"},
)))
print(f"emerg ord: success={resp2.success} err={resp2.error}")
assert resp2.success, resp2.error
b2 = cap2.calls[0]["json_data"]
assert int(round(float(b2["price"]) * 100)) == 100 - 13  # bid @0.87
assert b2["side"] == "bid" and b2["reduce_only"] is True
results.append("authorized emergency @13 -> wire carries approved 13")

# â”€â”€ Step 7: emergency approval cannot be reused for a different price â”€â”€â”€â”€â”€â”€
r = run(port.create_order(_req(
    price_cents=20,
    client_order_id=d_em.client_order_id,
    metadata={"firewall_decision_id": d_em.decision_id,
              "entry_or_exit": "exit"},
)))
print(f"emerg reuse: success={r.success} err={r.error}")
assert not r.success and "price_c:" in r.error
results.append("emergency approval @ mutated price -> rejected")

print("\nAPPROVAL BINDING MATRIX: ALL CHECKS PASSED")
for x in results:
    print(f"  {x}")

