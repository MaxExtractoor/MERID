"""
P0 tests for the normalized ``KalshiExecutionPort`` contract.

These tests drive ``DeterministicKalshiClient`` through the port boundary
(``set_kalshi_execution_port`` / ``get_kalshi_execution_port``) to verify
order entry, lookup, cancellation, positions, fills, and market state.

All calls are async; no respx / no real network.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import pytest

from merid.event_venues.base import VenuePosition
from merid.event_venues.kalshi.port import (
    CreateOrderRequest,
    get_kalshi_execution_port,
    reset_kalshi_execution_port_for_testing,
    set_kalshi_execution_port,
)
from tests.event_venues.kalshi.deterministic_kalshi_client import (
    DeterministicKalshiClient,
)

TICKER = "KXBTC15M-TEST-50000"
SETTLED_TICKER = "KXBTC15M-TEST-SETTLED"
EXPIRED_TICKER = "KXBTC15M-TEST-EXPIRED"


@pytest.fixture
def client() -> DeterministicKalshiClient:
    """Fresh deterministic simulator injected as the global KalshiExecutionPort."""
    c = DeterministicKalshiClient()
    c.set_time(1_700_000_000)
    c.set_balance(Decimal("10000"), locked=Decimal("0"))
    set_kalshi_execution_port(c)
    yield c
    reset_kalshi_execution_port_for_testing()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_order_request(
    client_order_id: str,
    size: int = 2,
    price_cents: Optional[int] = 50,
    tif: str = "GTC",
    ticker: str = TICKER,
    side: str = "buy",
    outcome: str = "yes",
) -> CreateOrderRequest:
    return CreateOrderRequest(
        ticker=ticker,
        side=side,
        outcome=outcome,
        size=Decimal(size),
        price_cents=price_cents,
        time_in_force=tif,
        client_order_id=client_order_id,
    )


# ---------------------------------------------------------------------------
# Normalized port contract coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_port_create_order_returns_order_id_and_status(
    client: DeterministicKalshiClient,
) -> None:
    port = get_kalshi_execution_port()
    client.set_orderbook(
        TICKER,
        best_bid_cents=40,
        best_ask_cents=60,
        bid_size=Decimal("10"),
        ask_size=Decimal("10"),
    )

    req = _create_order_request("port-create", size=4, price_cents=50)
    resp = await port.create_order(req)

    assert resp.success
    assert resp.order_id is not None
    assert resp.order_id.startswith("ord-")
    assert resp.client_order_id == "port-create"
    assert resp.status == "resting"
    assert resp.filled_size == Decimal("0")
    assert resp.remaining_size == Decimal("4")
    assert resp.average_price_cents == 50


@pytest.mark.asyncio
async def test_port_get_order_by_client_order_id(
    client: DeterministicKalshiClient,
) -> None:
    port = get_kalshi_execution_port()
    client.set_orderbook(
        TICKER,
        best_bid_cents=40,
        best_ask_cents=60,
        bid_size=Decimal("10"),
        ask_size=Decimal("10"),
    )

    req = _create_order_request("port-lookup", size=2, price_cents=50)
    resp = await port.create_order(req)
    assert resp.success

    order = await port.get_order(client_order_id="port-lookup")
    assert order is not None
    assert order.client_order_id == "port-lookup"
    assert order.ticker == TICKER
    assert order.side == "buy"
    assert order.outcome == "yes"
    assert order.status == "resting"
    assert order.price_cents == 50
    assert order.order_id == resp.order_id


@pytest.mark.asyncio
async def test_port_cancel_order_returns_cancel_result(
    client: DeterministicKalshiClient,
) -> None:
    port = get_kalshi_execution_port()
    client.set_orderbook(
        TICKER,
        best_bid_cents=40,
        best_ask_cents=60,
        bid_size=Decimal("10"),
        ask_size=Decimal("10"),
    )

    req = _create_order_request("port-cancel", size=2, price_cents=50)
    create = await port.create_order(req)
    assert create.success

    cancel = await port.cancel_order(create.order_id)
    assert cancel.success
    assert cancel.order_id == create.order_id
    assert cancel.new_status == "canceled"

    order = await port.get_order(create.order_id)
    assert order is not None
    assert order.status == "canceled"


@pytest.mark.asyncio
async def test_port_get_open_orders_filters_terminal(
    client: DeterministicKalshiClient,
) -> None:
    port = get_kalshi_execution_port()
    client.set_orderbook(
        TICKER,
        best_bid_cents=40,
        best_ask_cents=60,
        bid_size=Decimal("10"),
        ask_size=Decimal("10"),
    )

    # Resting GTC — should remain open.
    resting = _create_order_request("port-open", size=2, price_cents=50)
    await port.create_order(resting)

    # IOC no-fill — terminal.
    ioc_unfilled = _create_order_request(
        "port-ioc-unfilled", size=2, price_cents=50, tif="IOC"
    )
    await port.create_order(ioc_unfilled)

    # IOC full fill — terminal.
    ioc_filled = _create_order_request(
        "port-ioc-filled", size=2, price_cents=60, tif="IOC"
    )
    await port.create_order(ioc_filled)

    # GTC then canceled — terminal.
    to_cancel = _create_order_request("port-canceled", size=2, price_cents=50)
    created = await port.create_order(to_cancel)
    assert created.success
    await port.cancel_order(created.order_id)

    open_orders = await port.get_open_orders()
    assert len(open_orders) == 1
    assert open_orders[0].client_order_id == "port-open"
    assert open_orders[0].status == "resting"

    open_client_ids = {o.client_order_id for o in open_orders}
    assert "port-ioc-unfilled" not in open_client_ids
    assert "port-ioc-filled" not in open_client_ids
    assert "port-canceled" not in open_client_ids


@pytest.mark.asyncio
async def test_port_get_positions_returns_live_positions(
    client: DeterministicKalshiClient,
) -> None:
    port = get_kalshi_execution_port()

    # Set live positions directly.
    client.set_live_positions(
        market_positions=[
            {
                "ticker": TICKER,
                "side": "yes",
                "count": 7,
                "avg_price_dollars": Decimal("0.55"),
            },
        ],
        event_positions=[],
    )

    # Historical / settled positions must not appear in the live endpoint.
    client.set_historical_positions(
        [
            VenuePosition(
                market_id=SETTLED_TICKER,
                outcome_id="yes",
                size=Decimal("10"),
                average_entry_price=Decimal("0.60"),
                venue="kalshi",
            ),
        ]
    )

    response = await port.get_positions()
    assert len(response.positions) == 1

    pos = response.positions[0]
    assert pos.ticker == TICKER
    assert pos.outcome == "yes"
    assert pos.size == Decimal("7")
    assert pos.average_entry_price_cents == 55


@pytest.mark.asyncio
async def test_port_get_historical_positions_returns_settled_positions(
    client: DeterministicKalshiClient,
) -> None:
    port = get_kalshi_execution_port()

    client.set_live_positions(market_positions=[], event_positions=[])
    client.set_historical_positions(
        [
            VenuePosition(
                market_id=SETTLED_TICKER,
                outcome_id="yes",
                size=Decimal("12"),
                average_entry_price=Decimal("0.60"),
                venue="kalshi",
            ),
        ]
    )

    response = await port.get_historical_positions()
    assert len(response.positions) == 1

    pos = response.positions[0]
    assert pos.ticker == SETTLED_TICKER
    assert pos.outcome == "yes"
    assert pos.size == Decimal("12")
    assert pos.average_entry_price_cents == 60

    # Live endpoint stays empty.
    live = await port.get_positions()
    assert len(live.positions) == 0


@pytest.mark.asyncio
async def test_port_get_fills_pagination_and_since_ts(
    client: DeterministicKalshiClient,
) -> None:
    port = get_kalshi_execution_port()
    base = client.get_time()

    for i in range(5):
        fill = {
            "trade_id": f"trade-{i}",
            "order_id": f"ord-{i}",
            "market_ticker": TICKER,
            "side": "yes",
            "action": "buy",
            "count": 1,
            "yes_price": 50,
            "no_price": 50,
            "price": "0.50",
            "fee": "0",
            "created_time": datetime.fromtimestamp(
                base + i, tz=timezone.utc
            ).isoformat(),
        }
        client.inject_fill(fill)

    # since_ts filtering: include base+2 and later (3 fills)
    since_response = await port.get_fills(since_ts=base + 2)
    assert len(since_response.fills) == 3
    fill_ids = [f.fill_id for f in since_response.fills]
    assert fill_ids == ["trade-2", "trade-3", "trade-4"]

    # pagination by limit: only first 2 fills
    limit_response = await port.get_fills(limit=2)
    assert len(limit_response.fills) == 2
    assert limit_response.fills[0].fill_id == "trade-0"
    assert limit_response.fills[1].fill_id == "trade-1"


@pytest.mark.asyncio
async def test_port_get_market_resolved_state(
    client: DeterministicKalshiClient,
) -> None:
    port = get_kalshi_execution_port()

    client.set_market_expired(EXPIRED_TICKER)
    expired = await port.get_market(EXPIRED_TICKER)
    assert expired.success
    assert expired.market is not None
    assert expired.market.resolved is True
    assert expired.market.active is False
    assert expired.market.resolution == "expired"

    client.set_market(TICKER)
    active = await port.get_market(TICKER)
    assert active.success
    assert active.market is not None
    assert active.market.resolved is False
    assert active.market.active is True
