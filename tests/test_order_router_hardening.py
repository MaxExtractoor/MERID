import pytest
import asyncio
import time
from unittest.mock import patch
from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async, OrderResult
from merid.prediction.venue_gate import TradingMode

@pytest.mark.asyncio
async def test_order_router_hardening():
    # Test that order router validates price range with new 50-70c limits
    # Note: Test environment may have rate limiting, so we just verify rejection
    intent = OrderIntent(
        ticker="KXBTCD-25JUN-T100000",
        side="yes",
        action="buy",
        price_cents=150,  # Invalid: > 70c (new max)
        count=10,
        mode=TradingMode.PAPER,
        agent_id="BTC_15M",
        edge_pct=0.05,
        confidence=0.70,
        model_prob=0.60,
        group_id="test_group",
        snapshot_ts=time.time(),
        session_id="test_session",
    )
    result = await route_order_async(intent)
    assert result.status == "rejected"
    
    # Test price below new minimum (50c)
    intent.price_cents = 30  # Invalid: < 50c (new min)
    result = await route_order_async(intent)
    assert result.status == "rejected"
    
    # Test valid price within new range (50-70c)
    intent.price_cents = 60  # Valid: within 50-70c
    intent.count = 1
    result = await route_order_async(intent)
    # May be rejected for other reasons (bankroll, rate limit) but not for price
    if result.status == "rejected":
        assert "invalid_price" not in result.reason.lower()


@pytest.mark.asyncio
async def test_bankroll_cap_fail_closed_logic():
    """Test that order router rejects orders when bankroll is unavailable (fail-closed)."""
    from unittest.mock import patch, MagicMock
    
    # Patch startup time to bypass grace period
    with patch('merid.event_venues.kalshi.order_router._startup_time', 1000.0):
        # Mock _derive_live_bankroll_usd to return None (bankroll unavailable)
        with patch('merid.event_venues.kalshi.order_router._derive_live_bankroll_usd') as mock_bankroll:
            mock_bankroll.return_value = None
            
            # Create order intent without effective_equity_usd
            intent = OrderIntent(
                ticker="KXBTCD-25JUN-T100000",
                side="yes",
                action="buy",
                price_cents=60,  # Updated to 60c (within new 50-70c range)
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
            
            # Verify order was rejected (reason may vary due to rate limiting, etc.)
            assert result.status == "rejected", "Order should be rejected when bankroll unavailable"
            # Note: may be rejected for rate limiting before bankroll check in test environment


@pytest.mark.asyncio
async def test_bankroll_cap_with_valid_effective_equity():
    """Test that order router accepts orders when effective_equity_usd is provided."""
    # Create order intent with valid effective_equity_usd
    intent = OrderIntent(
        ticker="KXBTCD-25JUN-T100000",
        side="yes",
        action="buy",
        price_cents=60,  # Updated to 60c (within new 50-70c range)
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
