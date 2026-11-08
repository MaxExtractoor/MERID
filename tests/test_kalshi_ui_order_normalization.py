import ast
import asyncio
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def api():
    path = Path(__file__).resolve().parents[1] / "web" / "api" / "kalshi_api.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {"_safe_float_val", "_normalize_ui_order", "get_orders"}
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    for node in nodes:
        node.decorator_list = []
    namespace = {
        "__name__": "isolated_kalshi_orders",
        "Decimal": Decimal,
        "Any": object,
        "Dict": dict,
        "Query": lambda default, **kwargs: default,
        "asyncio": asyncio,
        "logger": Mock(),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


@pytest.mark.parametrize("source", ["executor", "rest_client"])
@pytest.mark.parametrize("raw, expected", [
    ({"side": "no", "initial_count_fp": "2.75", "count": 2, "fill_count_fp": "0.50", "filled_count": 0, "remaining_count_fp": "2.25", "remaining_count": 2, "yes_price_dollars": "0.6734", "no_price_dollars": "0.3266", "yes_price": 67, "no_price": 32}, (2.75, 0.5, 2.25, 0.3266)),
    ({"side": "yes", "count_fp": "0.75", "filled_count_fp": "0.25", "remaining_count_fp": "0.50", "yes_price_dollars": "0.0123", "no_price_dollars": "0.9877"}, (0.75, 0.25, 0.5, 0.0123)),
    ({"side": "no", "count": "3.5", "filled_count": "1.25", "remaining_count": "2.25", "yes_price": 73, "no_price": "27.5"}, (3.5, 1.25, 2.25, 0.275)),
    ({"side": "yes", "fill_count_fp": "0.25", "remaining_count_fp": "0.50", "yes_price": 0, "no_price": 100}, (0.75, 0.25, 0.5, 0)),
    ({"side": "yes", "count": 3, "filled_count": 1, "yes_price": 41}, (3, 1, None, 0.41)),
    ({"side": "buy", "count": 3, "filled_count": 1, "remaining_count": 2, "yes_price": 41}, (3, 1, 2, 0.41)),
    ({"side": "no", "count_fp": "0.01", "fill_count_fp": "0.00", "remaining_count_fp": "0.01", "yes_price_dollars": "0.9001"}, (0.01, 0, 0.01, 0.0999)),
    ({"side": "no", "count": 1, "filled_count": 1, "remaining_count": 0, "no_price": 0, "yes_price": 100}, (1, 1, 0, 0)),
    ({"side": "sell", "count": 2, "filled_count": 0, "remaining_count": 2, "yes_price": 32}, (2, 0, 2, 0.32)),
    ({"side": "yes", "initial_count_fp": "NaN", "count_fp": "", "count": "1.25", "fill_count_fp": "bad", "filled_count": "0.25", "remaining_count_fp": None, "remaining_count": "1.00", "yes_price_dollars": "Infinity", "yes_price": "41.25"}, (1.25, 0.25, 1, 0.4125)),
    ({"side": "no", "initial_count_fp": "0.00", "fill_count_fp": "0.00", "remaining_count_fp": "0.00", "no_price_dollars": "0.0000", "yes_price": 100}, (0, 0, 0, 0)),
    ({"side": "yes", "initial_count": "1.75", "fill_count": "0.50", "remaining_count": "1.25", "no_price": "61.25"}, (1.75, 0.5, 1.25, 0.3875)),
])
def test_orders_preserve_total_fractional_counts_and_own_side_price(api, source, raw, expected):
    raw = {"order_id": "order-1", "ticker": "KXBTC-TEST", "status": "resting", "created_time": "2026-01-01", **raw}
    executor = SimpleNamespace(get_orders=AsyncMock(return_value=[raw]))
    rest = SimpleNamespace(get_orders=Mock(return_value=[raw]))
    api["_get_executor"] = lambda: executor if source == "executor" else None
    api["_get_rest_client"] = lambda: rest
    result = asyncio.run(api["get_orders"](include_scanning=False))
    order = result["orders"][0]
    assert (order["size"], order["filled"], order["remaining"], order["price"]) == expected
    assert order["source"] == source
    assert order["synthetic"] is False
    assert order["order_id"] == "order-1"
    assert order["ticker"] == "KXBTC-TEST"
    assert order["side"] == raw["side"]
    assert order["status"] == "resting"
    assert order["created_at"] == "2026-01-01"
    assert result["venue_order_ids"] == ["order-1"]
    if source == "executor":
        executor.get_orders.assert_awaited_once_with(status="resting")
        rest.get_orders.assert_not_called()
    else:
        rest.get_orders.assert_called_once_with(status="resting")


@pytest.mark.parametrize("executor_fails", [False, True])
def test_orders_fall_back_to_rest(api, executor_fails):
    executor = SimpleNamespace(get_orders=AsyncMock(return_value=[]))
    if executor_fails:
        executor.get_orders.side_effect = RuntimeError("unavailable")
    rest = SimpleNamespace(get_orders=Mock(return_value=[{
        "order_id": "rest-order", "side": "no", "count_fp": "0.75",
        "fill_count_fp": "0.25", "remaining_count_fp": "0.50",
        "yes_price_dollars": "0.80", "no_price_dollars": "0.20",
    }]))
    api["_get_executor"] = lambda: executor
    api["_get_rest_client"] = lambda: rest
    result = asyncio.run(api["get_orders"](include_scanning=False))
    order = result["orders"][0]
    assert (order["size"], order["filled"], order["remaining"], order["price"]) == (0.75, 0.25, 0.5, 0.2)
    assert order["source"] == "rest_client"
    assert result["venue_order_ids"] == ["rest-order"]
    executor.get_orders.assert_awaited_once_with(status="resting")
    rest.get_orders.assert_called_once_with(status="resting")
