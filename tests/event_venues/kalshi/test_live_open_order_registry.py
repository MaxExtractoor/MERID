"""Live open-order registry: record + prune against venue open IDs."""

from __future__ import annotations

from decimal import Decimal

import pytest

from merid.event_venues.base import PlacedOrder
from merid.event_venues.kalshi.live_open_order_registry import (
    get_live_open_order_registry,
    reset_live_open_order_registry_for_testing,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    reset_live_open_order_registry_for_testing()
    yield
    reset_live_open_order_registry_for_testing()


def test_record_and_prune_keeps_only_venue_open_orders():
    reg = get_live_open_order_registry()
    reg.record_placed(
        PlacedOrder(
            order_id="a",
            market_id="KX1",
            side="buy",
            size=Decimal("5"),
            price=Decimal("0.5"),
            filled_size=Decimal("0"),
            status="resting",
            venue="kalshi",
        )
    )
    reg.record_placed(
        PlacedOrder(
            order_id="b",
            market_id="KX2",
            side="buy",
            size=Decimal("1"),
            price=Decimal("0.4"),
            filled_size=Decimal("0"),
            status="resting",
            venue="kalshi",
        )
    )
    assert len(reg.snapshot()) == 2
    reg.prune_to_open_order_ids({"a"})
    snap = reg.snapshot()
    assert len(snap) == 1
    assert snap[0].order_id == "a"
