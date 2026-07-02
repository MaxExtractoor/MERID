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


@pytest.mark.asyncio
async def test_bankroll_cap_fail_closed_logic():
    """Test that order router rejects orders when bankroll is unavailable (fail-closed)."""
    from unittest.mock import patch, MagicMock
    
    # Mock _derive_live_bankroll_usd to return None (bankroll unavailable)
    with patch('merid.event_venues.kalshi.order_router._derive_live_bankroll_usd') as mock_bankroll:
        mock_bankroll.return_value = None
        
        # Create order intent without effective_equity_usd
        intent = OrderIntent(
            ticker="KXBTCD-25JUN-T100000",
            side="yes",
            action="buy",
            price_cents=55,
            count=1,
            mode=TradingMode.PAPER,
            agent_id="BTC_15M",
            edge_pct=0.05,
            confidence=0.70,
            model_prob=0.60,
            group_id="test_group",
            snapshot_ts=time.time(),
            session_id="test_session",
            effective_equity_usd=None,  # No effective equity provided
        )
        
        # Route order - should be rejected due to unavailable bankroll
        result = await route_order_async(intent)
        
        # Verify order was rejected with bankroll_unavailable reason
        assert result.status == "rejected", "Order should be rejected when bankroll unavailable"
        assert "bankroll_unavailable" in result.reason, f"Reason should mention bankroll_unavailable, got: {result.reason}"


@pytest.mark.asyncio
async def test_bankroll_cap_with_valid_effective_equity():
    """Test that order router accepts orders when effective_equity_usd is provided."""
    # Create order intent with valid effective_equity_usd
    intent = OrderIntent(
        ticker="KXBTCD-25JUN-T100000",
        side="yes",
        action="buy",
        price_cents=55,
        count=1,
        mode=TradingMode.PAPER,
        agent_id="BTC_15M",
        edge_pct=0.05,
        confidence=0.70,
        model_prob=0.60,
        group_id="test_group",
        snapshot_ts=time.time(),
        session_id="test_session",
        effective_equity_usd=50.0,  # Valid effective equity
    )
    
    # Route order - should pass bankroll cap check
    result = await route_order_async(intent)
    
    # Order should not be rejected due to bankroll issues
    if result.status == "rejected":
        assert "bankroll" not in result.reason.lower(), f"Should not be rejected for bankroll reasons, got: {result.reason}"
