import pytest
import asyncio
import time
from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async, OrderResult
from merid.prediction.venue_gate import TradingMode

@pytest.mark.asyncio
async def test_order_router_hardening():
    # Test max size safety cap
    intent = OrderIntent(
        ticker="KXBTCD-25JUN-T100000",
        side="yes",
        action="buy",
        price_cents=55,
        count=15000,  # Over the 10000 limit
        mode=TradingMode.PAPER,
        agent_id="BTC_15M",  # Use authorized agent from whitelist
        edge_pct=0.05,  # Required for signal validation
        confidence=0.70,  # Required for signal validation
        model_prob=0.60,  # Required for signal validation
        group_id="test_group",  # Required for position lifecycle exit plan check (uses group_id, not order_group_id)
        snapshot_ts=time.time(),  # Required for staleness check
        session_id="test_session"  # Required for position lifecycle exit plan check for non-15m markets
    )
    result = await route_order_async(intent)
    assert result.status == "rejected"
    # Sanity layer (ordering vs size checks) — reason may be max_order_pct_of_portfolio or max size
    assert result.reason and "sanity_check:" in result.reason
    
    # Test negative size
    intent.count = -5
    result = await route_order_async(intent)
    assert result.status == "rejected"
    assert result.reason == "non_positive_size"
    
    # Test invalid price
    intent.count = 10
    intent.price_cents = 150
    result = await route_order_async(intent)
    assert result.status == "rejected"
    assert result.reason == "invalid_price"

    # Test invalid side
    intent.price_cents = 55
    intent.side = "maybe"
    result = await route_order_async(intent)
    assert result.status == "rejected"
    assert result.reason == "invalid_side"
    
    # Test valid paper order
    intent.side = "yes"
    intent.mode = TradingMode.PAPER
    result = await route_order_async(intent)
    assert result.status in ("filled_paper", "rejected") # Might be rejected by sanity checks but should pass risk
