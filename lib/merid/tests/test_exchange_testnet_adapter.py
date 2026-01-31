import time

from trading.execution import place_order
from trading.exchange import get_default_adapter, LocalAdapter, TestnetAdapter


def test_get_default_adapter_switch(monkeypatch):
    monkeypatch.setenv("MERID_USE_TESTNET", "true")
    assert isinstance(get_default_adapter(), TestnetAdapter)
    monkeypatch.setenv("MERID_USE_TESTNET", "false")
    assert isinstance(get_default_adapter(), LocalAdapter)


def test_testnet_adapter_submits_order(monkeypatch):
    monkeypatch.setenv("MERID_USE_TESTNET", "true")
    order = {"symbol": "ABC", "quantity": 1, "side": "buy", "price": 100}
    account = {"balance": 10_000, "max_notional_pct": 0.5}

    rec = place_order(order, idempotency_key=None, account=account, actor="test", portfolio_id=None)
    assert rec["status"] == "submitted"
