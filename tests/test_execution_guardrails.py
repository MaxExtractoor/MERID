"""Execution guardrail tests for trading.execution."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from trading.execution import (
    ExecutionEngine,
    ExecutionConfig,
    ExecutionError,
    ExecutionMode,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionLimitError,
    OrderRejectedError,
)
from trading.execution.defense import DefenseAction, ThreatLevel


def _dummy_logger():
    return SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
        critical=lambda *args, **kwargs: None,
    )


def _async_noop(*args, **kwargs):  # pragma: no cover - helper
    async def _inner(*_a, **_k):
        return None

    return _inner


def make_engine(config: ExecutionConfig | None = None) -> ExecutionEngine:
    engine = object.__new__(ExecutionEngine)
    engine.config = config or ExecutionConfig()
    engine._orders = {}
    engine._positions = {}
    engine._order_history = []
    engine._price_cache = {}
    engine._balance = 250_000.0
    engine._equity = 250_000.0
    engine._total_exposure = 0.0
    engine._event_callbacks = []
    engine._logger = _dummy_logger()
    engine._reality_auditor = None
    engine._mev_defender = None
    engine._validator = None
    engine._state_manager = SimpleNamespace()
    engine._self_healing = SimpleNamespace()
    engine._health_monitor = SimpleNamespace()

    async def _handle_error(*_args, **_kwargs):
        return None

    engine._error_handler = SimpleNamespace(handle_error=_handle_error)
    return engine


def test_market_and_limit_respect_constraints():
    config = ExecutionConfig(
        max_position_size_usd=50_000.0,
        max_total_exposure_usd=80_000.0,
    )
    engine = make_engine(config)
    engine._price_cache["BTC"] = 30_000.0
    engine._total_exposure = 40_000.0

    oversized_market = Order(
        order_id="oversized",
        symbol="BTC",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=3.5,  # -> $105k value
    )

    with pytest.raises(PositionLimitError):
        engine._validate_order(oversized_market)

    compliant_limit = Order(
        order_id="compliant",
        symbol="BTC",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=1.0,
        price=25_000.0,
    )

    # Should not raise when staying inside limits
    engine._validate_order(compliant_limit)


@pytest.mark.asyncio
async def test_rejected_orders_propagate_errors():
    engine = make_engine()
    engine._price_cache["SOL"] = 100.0

    async def failing_execute(*_args, **_kwargs):
        raise OrderRejectedError("MEV breach 42")

    engine._execute_paper_order = failing_execute  # type: ignore[assignment]

    with pytest.raises(OrderRejectedError) as exc:
        await engine.submit_order(
            symbol="SOL",
            side=OrderSide.BUY,
            quantity=10,
            order_type=OrderType.MARKET,
        )

    assert "MEV breach 42" in str(exc.value)


@pytest.mark.asyncio
async def test_downstream_rejection_via_mock(monkeypatch):
    engine = make_engine()
    engine._price_cache["ATOM"] = 12.5

    mock_client = AsyncMock(side_effect=OrderRejectedError("EXCHANGE_REJECT: 9001"))
    monkeypatch.setattr(engine, "_execute_paper_order", mock_client)

    with pytest.raises(OrderRejectedError) as exc:
        await engine.submit_order(
            symbol="ATOM",
            side=OrderSide.BUY,
            quantity=100,
            order_type=OrderType.MARKET,
        )

    assert "EXCHANGE_REJECT: 9001" in str(exc.value)
    mock_client.assert_awaited_once()


@pytest.mark.asyncio
async def test_live_mode_falls_back_to_paper(monkeypatch):
    config = ExecutionConfig(mode=ExecutionMode.LIVE)
    engine = make_engine(config)
    engine._price_cache["BTC"] = 20_000.0

    async def fake_paper(order, *_a, **_k):
        order.status = OrderStatus.FILLED

    engine._execute_paper_order = AsyncMock(side_effect=fake_paper)

    class FakeExchange:
        def __init__(self, *_a, **_k):
            raise RuntimeError("provider unavailable")

    fake_ccxt_module = SimpleNamespace(coinbase=FakeExchange)
    monkeypatch.setitem(sys.modules, "ccxt.async_support", fake_ccxt_module)

    await engine.submit_order(
        symbol="BTC",
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
    )

    engine._execute_paper_order.assert_called_once()


@pytest.mark.asyncio
async def test_mev_defense_blocks_critical_threat(monkeypatch):
    engine = make_engine()
    engine._price_cache["ETH"] = 1_500.0

    class FakeRecommendation:
        def __init__(self):
            self.action = DefenseAction.ABORT
            self.threat_level = ThreatLevel.CRITICAL
            self.estimated_mev_risk = 1000.0

        def to_dict(self):
            return {"action": self.action.value, "threat_level": self.threat_level.value}

    class FakeDefender:
        def __init__(self):
            self.front_running_detector = SimpleNamespace(
                register_pending_order=lambda **_: None
            )

        def get_defense_recommendation(self, **_):
            return FakeRecommendation()

    engine._mev_defender = FakeDefender()

    with pytest.raises(OrderRejectedError):
        await engine.submit_order(
            symbol="ETH",
            side=OrderSide.BUY,
            quantity=2,
            order_type=OrderType.MARKET,
        )

def test_cascading_fills_reconcile_state():
    engine = make_engine()

    order = Order(
        order_id="partial",
        symbol="ETH",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=8,
    )

    fill_sequence = [(3, 2_000.0), (1, 1_990.0), (2, 2_005.0)]

    cumulative_qty = 0
    for qty, price in fill_sequence:
        order.filled_quantity = qty
        order.filled_price = price
        engine._update_position_from_fill(order, stop_loss=None, take_profit=None)

        cumulative_qty += qty
        position = engine._positions["ETH"]
        assert position.quantity == cumulative_qty

    position = engine._positions["ETH"]
    total_filled = sum(q for q, _ in fill_sequence)
    assert position.quantity == total_filled

    expected_avg = (
        sum(q * p for q, p in fill_sequence)
    ) / total_filled
    assert position.entry_price == pytest.approx(expected_avg, rel=1e-6)

    remaining_qty = order.quantity - total_filled
    assert remaining_qty >= 0
    assert remaining_qty == order.quantity - total_filled

    assert len(engine._positions) == 1
    assert engine._total_exposure == pytest.approx(position.quantity * position.entry_price, rel=1e-6)


def test_boundary_constraints_allow_exact_limits():
    config = ExecutionConfig(
        max_position_size_usd=100_000.0,
        max_total_exposure_usd=150_000.0,
        paper_max_position_size_usd=100_000.0,
        paper_max_total_exposure_usd=150_000.0,
    )
    engine = make_engine(config)
    engine._price_cache["BTC"] = 20_000.0
    engine._total_exposure = 50_000.0

    boundary_order = Order(
        order_id="boundary",
        symbol="BTC",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=5.0,  # -> $100k value
    )

    # Exactly at both per-order and aggregate exposure caps should be allowed.
    engine._validate_order(boundary_order)


def test_boundary_constraints_reject_when_exceeding_total():
    config = ExecutionConfig(
        max_position_size_usd=120_000.0,
        max_total_exposure_usd=150_000.0,
        paper_max_position_size_usd=120_000.0,
        paper_max_total_exposure_usd=150_000.0,
    )
    engine = make_engine(config)
    engine._price_cache["ETH"] = 3_000.0
    engine._total_exposure = 140_000.0

    breaching_order = Order(
        order_id="breach",
        symbol="ETH",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=4.0,  # -> $12k value pushes total to 152k
    )

    with pytest.raises(PositionLimitError):
        engine._validate_order(breaching_order)


@pytest.mark.asyncio
async def test_zero_liquidity_rejects_market_order():
    engine = make_engine()

    with pytest.raises(ExecutionError) as exc:
        await engine.submit_order(
            symbol="ADA",
            side=OrderSide.BUY,
            quantity=1,
            order_type=OrderType.MARKET,
        )

    assert "No price available" in str(exc.value)


@pytest.mark.asyncio
async def test_conflicting_constraints_surface_reason():
    engine = make_engine()
    engine._price_cache["SOL"] = 75.0

    async def raising_error_handler(error, *args, **kwargs):
        raise error

    engine._error_handler = SimpleNamespace(handle_error=raising_error_handler)

    class ValidatorStub:
        async def validate_order(self, order):
            return SimpleNamespace(passed=False, reason="slippage-latency conflict")

    engine._validator = ValidatorStub()

    with pytest.raises(OrderRejectedError) as exc:
        await engine.submit_order(
            symbol="SOL",
            side=OrderSide.BUY,
            quantity=2,
            order_type=OrderType.MARKET,
        )

    assert "slippage-latency conflict" in str(exc.value)


@pytest.mark.asyncio
async def test_global_halt_blocks_new_orders():
    engine = make_engine()
    engine._price_cache["BTC"] = 30_000.0

    class HaltedAuditor:
        def audit_execution_intent(self, *args, **kwargs):
            return SimpleNamespace(passed=False, reason="maintenance window", warnings=[])

    engine._reality_auditor = HaltedAuditor()

    with pytest.raises(OrderRejectedError) as exc:
        await engine.submit_order(
            symbol="BTC",
            side=OrderSide.BUY,
            quantity=1,
            order_type=OrderType.MARKET,
        )

    assert "maintenance window" in str(exc.value)
