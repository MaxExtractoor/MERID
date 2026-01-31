from __future__ import annotations

import pytest

from db.audit_store import clear_store, list_audit
from merid_trading import place_order, cancel_order, modify_order, ExecutionError


def setup_function():
    clear_store()


def test_place_order_records_audit():
    o = {"symbol": "BTCUSD", "side": "buy", "quantity": 1, "price": 50000}
    r = place_order(o, idempotency_key="k-audit", actor="admin", account={"balance": 100_000, "max_notional_pct": 0.5})
    audits = list_audit()
    assert any(a["action"] == "order.place" and a["actor"] == "admin" for a in audits)


def test_place_order_failure_records_audit():
    try:
        place_order({"symbol": "X", "side": "buy", "quantity": -5}, actor="bob", account={"balance": 100_000})
    except ExecutionError:
        pass
    audits = list_audit()
    assert any(a["action"].startswith("order.place.failed") and a["actor"] == "bob" for a in audits)


def test_cancel_modify_record_audits():
    o = {"symbol": "X", "side": "sell", "quantity": 1, "price": 10}
    r = place_order(o, actor="ops", account={"balance": 100_000})
    with pytest.raises(ExecutionError):
        cancel_order(r["id"], actor="ops")
    with pytest.raises(ExecutionError):
        modify_order(r["id"], {"price": 11}, actor="ops")
    audits = list_audit()
    assert any(a["action"] == "order.cancel.failed" for a in audits)
    assert any(a["action"] == "order.modify.failed" for a in audits)
