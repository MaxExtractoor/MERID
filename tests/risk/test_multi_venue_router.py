"""Risk-core tests for multi-venue routing strategy."""

from __future__ import annotations

from decimal import Decimal

import pytest

from swarm.multi_venue_router import MultiVenueRouter, RouteAllocation, VenueQuote


pytestmark = pytest.mark.risk_core


def _mk_quote(
    venue_id: str,
    price: float,
    fee_bps: float,
    latency_ms: float,
    liquidity: float,
) -> VenueQuote:
    return VenueQuote(
        venue_id=venue_id,
        price=Decimal(str(price)),
        fee_bps=Decimal(str(fee_bps)),
        latency_ms=latency_ms,
        available_liquidity=Decimal(str(liquidity)),
    )


def test_router_sorts_by_price_fee_and_latency() -> None:
    router = MultiVenueRouter()
    router.update_quote(_mk_quote("cheap", price=100.0, fee_bps=5, latency_ms=50, liquidity=10))
    router.update_quote(_mk_quote("same_price_lower_fee", price=100.0, fee_bps=2, latency_ms=70, liquidity=10))
    router.update_quote(_mk_quote("same_price_fee_lower_latency", price=100.0, fee_bps=2, latency_ms=20, liquidity=10))
    router.update_quote(_mk_quote("expensive", price=101.0, fee_bps=1, latency_ms=10, liquidity=10))

    allocations = router.optimize(total_size_usd=Decimal("15"))
    order = [alloc.venue_id for alloc in allocations]

    # Expect same_price_fee_lower_latency first (price + fee tie, lower latency)
    # then same_price_lower_fee (price tie, lower fee). Router should stop once
    # requested size is satisfied, so more expensive venues stay unused.
    assert order == [
        "same_price_fee_lower_latency",
        "same_price_lower_fee",
    ]
    # Ensure allocation sizes respect available liquidity and total size.
    assert allocations[0].size_usd == Decimal("10")
    assert allocations[1].size_usd == Decimal("5")


def test_router_handles_empty_and_partial_book() -> None:
    router = MultiVenueRouter()
    allocations = router.optimize(total_size_usd=Decimal("10"))
    assert allocations == []

    router.update_quote(_mk_quote("only", price=200.0, fee_bps=0, latency_ms=5, liquidity=5))
    allocations = router.optimize(total_size_usd=Decimal("10"))
    assert allocations == [RouteAllocation(venue_id="only", size_usd=Decimal("5"), expected_price=Decimal("200"))]
