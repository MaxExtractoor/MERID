"""Focused tests for the trade attribution fact table."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict

import pytest

from merid.monitoring.trade_attribution_fact_table import TradeAttributionTable, get_trade_attribution_table


@pytest.fixture
async def attribution_table():
    """Provide an isolated, initialized TradeAttributionTable."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "trade_attribution.db")
        # Reset singleton so each test gets a fresh instance.
        TradeAttributionTable.reset_instance()
        table = TradeAttributionTable.get_instance(db_path)
        await table.start()
        yield table
        await table.stop()
        TradeAttributionTable.reset_instance()


@dataclass
class _FakeIntent:
    run_id: str = "run-1"
    process_id: str = "pid-1"
    source_signal_id: str = "signal-1"
    intent_id: str = "intent-1"
    client_order_id: str = "coid-1"
    ticker: str = "KXBTC15M-TEST-000000-00"
    asset: str = "BTC"
    side: str = "yes"
    action: str = "buy"
    price_cents: int = 55
    count_fp: Decimal = Decimal("1")
    count: int = 1
    take_profit_price_cents: int = 75
    stop_loss_price_cents: int = 35
    source: str = "agent_grid"


@dataclass
class _FakeRequest:
    ticker: str = "KXBTC15M-TEST-000000-00"
    side: str = "buy"
    outcome: str = "yes"
    size: Decimal = Decimal("1")
    price_cents: int = 55
    order_type: str = "limit"
    time_in_force: str = "GTC"
    client_order_id: str = "coid-1"
    post_only: bool = False
    reduce_only: bool = False
    cancel_order_on_pause: bool = True
    self_trade_prevention_type: str = "taker_at_cross"
    max_execution_cost_cents: int = 100
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class _FakePlacedOrder:
    order_id: str = "order-1"
    market_id: str = "KXBTC15M-TEST-000000-00"
    side: str = "buy"
    size: Decimal = Decimal("1")
    price: Decimal = Decimal("0.55")
    status: str = "resting"
    raw_data: Dict[str, Any] = None

    def __post_init__(self):
        if self.raw_data is None:
            self.raw_data = {}


@dataclass
class _FakeCreateOrderResponse:
    success: bool = True
    order_id: str = "order-1"
    client_order_id: str = "coid-1"
    status: str = "resting"
    error: str = None


@dataclass
class _FakeFill:
    fill_id: str = "fill-1"
    order_id: str = "order-1"
    client_order_id: str = "coid-1"
    client_tag: str = "coid-1"
    market_ticker: str = "KXBTC15M-TEST-000000-00"
    asset: str = "BTC"
    side: str = "yes"
    action: str = "buy"
    canonical_position_side: str = "yes"
    canonical_position_action: str = "buy"
    canonical_leg_price_cents: int = 55
    count_fp: Decimal = Decimal("1")
    quantity_cc: int = 100
    fee_cost: Decimal = Decimal("0.02")
    ingestion_source: str = "websocket"
    intent_id: str = "intent-1"


@dataclass
class _FakePosition:
    market_id: str = "KXBTC15M-TEST-000000-00"
    side: str = "yes"
    contracts: int = 1
    avg_price_cents: int = 55
    realized_pnl_usd: Decimal = Decimal("0.45")
    entry_intent_id: str = "intent-1"
    fill_source: str = "alpha"


@pytest.mark.asyncio
async def test_record_intent_and_query(attribution_table):
    table: TradeAttributionTable = attribution_table
    intent = _FakeIntent()
    request = _FakeRequest()
    table.record_intent(intent, request)
    await table.flush()

    events = await table.get_events_for_intent("intent-1")
    assert len(events) == 1
    assert events[0]["event_type"] == "intent"
    assert events[0]["ticker"] == "KXBTC15M-TEST-000000-00"
    assert events[0]["cancel_order_on_pause"] == 1
    assert events[0]["client_order_id"] == "coid-1"


@pytest.mark.asyncio
async def test_record_order_and_query(attribution_table):
    table: TradeAttributionTable = attribution_table
    request = _FakeRequest()
    request.metadata = {"intent_id": "intent-1"}
    response = _FakeCreateOrderResponse()
    placed = _FakePlacedOrder()
    table.record_order(request, response, placed)
    await table.flush()

    events = await table.get_events_for_intent("intent-1")
    assert len(events) == 1
    assert events[0]["event_type"] == "order"
    assert events[0]["order_id"] == "order-1"
    assert events[0]["order_status"] == "resting"


@pytest.mark.asyncio
async def test_record_fill_and_query(attribution_table):
    table: TradeAttributionTable = attribution_table
    fill = _FakeFill()
    table.record_fill(fill)
    await table.flush()

    events = await table.get_events_for_intent("intent-1")
    assert len(events) == 1
    assert events[0]["event_type"] == "fill"
    assert events[0]["fill_id"] == "fill-1"
    assert events[0]["fill_quantity_cc"] == 100
    assert events[0]["fee_cost_cents"] == 2


@pytest.mark.asyncio
async def test_record_settlement_and_query(attribution_table):
    table: TradeAttributionTable = attribution_table
    position = _FakePosition()
    table.record_settlement("KXBTC15M-TEST-000000-00", "yes", position)
    await table.flush()

    events = await table.get_events_for_intent("intent-1")
    assert len(events) == 1
    assert events[0]["event_type"] == "settlement"
    assert events[0]["settlement_outcome"] == "yes"
    assert events[0]["settlement_price_cents"] == 100
    assert events[0]["realized_pnl_cents"] == 45


@pytest.mark.asyncio
async def test_record_without_initialization_is_noop():
    """record_* must not crash when the singleton has not been created."""
    TradeAttributionTable.reset_instance()
    assert get_trade_attribution_table() is None
    # These should not raise.
    table = TradeAttributionTable.get_instance()
    table.record_intent(_FakeIntent(), _FakeRequest())
