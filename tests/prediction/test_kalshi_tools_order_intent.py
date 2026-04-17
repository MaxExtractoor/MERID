"""kalshi_tools builds OrderIntent fields aligned with order_router / VenueOrder."""

from decimal import Decimal

from merid.event_venues.base import VenueOrder
from merid.prediction.kalshi_tools import build_live_route_order_intent


def test_build_live_route_order_intent_matches_router_venue_mapping():
    intent = build_live_route_order_intent(
        "KXBTC-TEST-MARKET",
        "yes",
        "buy",
        55,
        10,
        correlation_id="corr-tool-1",
        source="test_agent",
    )
    assert intent.ticker == "KXBTC-TEST-MARKET"
    assert intent.side == "yes"
    assert intent.action == "buy"
    assert intent.price_cents == 55
    assert intent.count == 10
    assert intent.order_type == "limit"
    assert intent.client_tag == "corr-tool-1"
    assert intent.decision_trace_id == "corr-tool-1"
    assert intent.source == "test_agent"
    assert intent.mode is None

    # Same client_tag resolution as route_order_async before VenueOrder build
    if not intent.client_tag and intent.correlation_id:
        intent.client_tag = intent.correlation_id

    order = VenueOrder(
        market_id=intent.ticker,
        side=intent.action,
        size=Decimal(intent.count),
        price=(Decimal(intent.price_cents) / Decimal("100")) if intent.order_type == "limit" else None,
        order_type="limit" if intent.order_type == "limit" else "market",
        outcome_id=intent.side,
        client_order_id=intent.client_tag,
    )
    assert order.market_id == "KXBTC-TEST-MARKET"
    assert order.outcome_id == "yes"
    assert order.side == "buy"
    assert order.size == Decimal("10")
    assert order.client_order_id == "corr-tool-1"


def test_build_live_route_order_intent_market_order_zero_price():
    intent = build_live_route_order_intent("KX-T", "no", "sell", 0, 2)
    assert intent.order_type == "market"
    assert intent.price_cents == 0
    assert intent.count == 2
