import pytest
from merid_trading import place_order, cancel_order, modify_order, ExecutionError
from db.order_store import clear_store


def setup_function():
    clear_store()


def test_place_order_success():
    o = {"symbol": "BTCUSD", "side": "buy", "quantity": 1, "price": 50000}
    r = place_order(o, idempotency_key="k1", account={"balance": 100_000, "max_notional_pct": 0.5})
    assert r["status"] == "filled"
    assert r["idempotency_key"] == "k1"


def test_place_order_idempotency():
    o = {"symbol": "ETHUSD", "side": "buy", "quantity": 2, "price": 1500}
    r1 = place_order(o, idempotency_key="abc", account={"balance": 100_000, "max_notional_pct": 0.5})
    r2 = place_order(o, idempotency_key="abc", account={"balance": 100_000, "max_notional_pct": 0.5})
    assert r1["id"] == r2["id"]


def test_place_order_fails_bad_quantity():
    with pytest.raises(ExecutionError):
        place_order({"symbol": "X", "side": "buy", "quantity": -5}, idempotency_key=None, account={"balance": 100_000})


def test_cancel_and_modify_errors():
    o = {"symbol": "X", "side": "sell", "quantity": 1, "price": 10}
    r = place_order(o, account={"balance": 100_000})
    # after fill, cancel should fail
    with pytest.raises(ExecutionError):
        cancel_order(r["id"])
    with pytest.raises(ExecutionError):
        modify_order(r["id"], {"price": 11})
