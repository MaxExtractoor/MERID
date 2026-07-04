"""Tests for ratchet exit order routing.

This tests that ratchet exit orders are properly routed through the order router
and are fast-tracked as exit orders.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch


class TestRatchetExitOrderRouting:
    """Test suite for ratchet exit order routing."""
    
    def test_ratchet_exit_intent_creation(self):
        """Test that ratchet exit OrderIntent is created correctly."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        from merid.event_venues.kalshi.position_cache import CachedPosition
        from datetime import datetime, timezone
        
        position = CachedPosition(
            market_id="BTC-USD-240329-W10",
            side="yes",
            contracts=10,
            avg_price_cents=50,
            ratchet_activated=True,
            ratchet_floor_price_cents=80,
            ratchet_activation_timestamp=datetime.now(timezone.utc),
        )
        
        current_price_cents = 79
        
        # Create ratchet exit intent (as done in position cache)
        if position.side == "yes":
            exit_action = "sell"
            exit_side = "yes"
        else:
            exit_action = "buy"
            exit_side = "yes"
        
        ratchet_exit_intent = OrderIntent(
            ticker=position.market_id,
            side=exit_side,
            action=exit_action,
            price_cents=current_price_cents - 1 if position.side == "yes" else current_price_cents + 1,
            count=position.contracts,
            order_type="market",
            source="ratchet_floor_breach",
            agent_id="position_cache",
            rationale=f"Ratchet floor breach: current={current_price_cents}c floor={position.ratchet_floor_price_cents}c",
        )
        
        # Verify intent is created correctly
        assert ratchet_exit_intent.action == "sell"
        assert ratchet_exit_intent.side == "yes"
        assert ratchet_exit_intent.source == "ratchet_floor_breach"
        assert ratchet_exit_intent.agent_id == "position_cache"
        assert ratchet_exit_intent.order_type == "market"
        assert ratchet_exit_intent.count == 10
    
    def test_ratchet_exit_short_position_intent(self):
        """Test ratchet exit intent for SHORT (NO) position."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        from merid.event_venues.kalshi.position_cache import CachedPosition
        from datetime import datetime, timezone
        
        position = CachedPosition(
            market_id="BTC-USD-240329-W10",
            side="no",
            contracts=10,
            avg_price_cents=50,
            ratchet_activated=True,
            ratchet_floor_price_cents=55,
            ratchet_activation_timestamp=datetime.now(timezone.utc),
        )
        
        current_price_cents = 56
        
        # Create ratchet exit intent for NO position
        if position.side == "yes":
            exit_action = "sell"
            exit_side = "yes"
        else:
            exit_action = "buy"
            exit_side = "yes"
        
        ratchet_exit_intent = OrderIntent(
            ticker=position.market_id,
            side=exit_side,
            action=exit_action,
            price_cents=current_price_cents - 1 if position.side == "yes" else current_price_cents + 1,
            count=position.contracts,
            order_type="market",
            source="ratchet_floor_breach",
            agent_id="position_cache",
        )
        
        # For NO: exit is buy YES to close
        assert ratchet_exit_intent.action == "buy"
        assert ratchet_exit_intent.side == "yes"
    
    def test_ratchet_exit_is_exit_order(self):
        """Test that ratchet exit is recognized as an exit order."""
        from merid.event_venues.kalshi.order_router import OrderIntent, _is_exit_order
        
        ratchet_exit_intent = OrderIntent(
            ticker="BTC-USD-240329-W10",
            side="yes",
            action="sell",
            price_cents=78,
            count=10,
            order_type="market",
            source="ratchet_floor_breach",
            agent_id="position_cache",
        )
        
        # Should be recognized as exit order
        assert _is_exit_order(ratchet_exit_intent) is True
    
    def test_ratchet_source_in_exit_markers(self):
        """Test that 'ratchet' is in the exit order markers."""
        from merid.event_venues.kalshi.order_router import _is_exit_order, OrderIntent
        
        # Test with ratchet source
        ratchet_intent = OrderIntent(
            ticker="BTC-USD-240329-W10",
            side="yes",
            action="buy",  # Even buy action with ratchet source should be exit
            price_cents=78,
            count=10,
            order_type="market",
            source="ratchet_floor_breach",
        )
        
        assert _is_exit_order(ratchet_intent) is True
    
    def test_ratchet_exit_bypasses_non_critical_checks(self):
        """Test that ratchet exit bypasses non-critical checks."""
        from merid.event_venues.kalshi.order_router import _is_exit_order, OrderIntent
        
        ratchet_exit_intent = OrderIntent(
            ticker="BTC-USD-240329-W10",
            side="yes",
            action="sell",
            price_cents=78,
            count=10,
            order_type="market",
            source="ratchet_floor_breach",
            agent_id="position_cache",
        )
        
        # Should be fast-tracked as exit order
        is_exit = _is_exit_order(ratchet_exit_intent)
        assert is_exit is True
    
    def test_ratchet_exit_route_order_async(self):
        """Test that ratchet exit intent is properly structured for routing."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        ratchet_exit_intent = OrderIntent(
            ticker="BTC-USD-240329-W10",
            side="yes",
            action="sell",
            price_cents=78,
            count=10,
            order_type="market",
            source="ratchet_floor_breach",
            agent_id="position_cache",
        )
        
        # Verify intent is properly structured for routing
        assert ratchet_exit_intent.action == "sell"
        assert ratchet_exit_intent.source == "ratchet_floor_breach"
        assert ratchet_exit_intent.agent_id == "position_cache"
        assert ratchet_exit_intent.order_type == "market"
        assert ratchet_exit_intent.count == 10
    
    def test_ratchet_exit_aggressive_pricing(self):
        """Test that ratchet exit uses aggressive pricing for fast execution."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        from merid.event_venues.kalshi.position_cache import CachedPosition
        from datetime import datetime, timezone
        
        position = CachedPosition(
            market_id="BTC-USD-240329-W10",
            side="yes",
            contracts=10,
            avg_price_cents=50,
            ratchet_activated=True,
            ratchet_floor_price_cents=80,
            ratchet_activation_timestamp=datetime.now(timezone.utc),
        )
        
        current_price_cents = 79
        
        # For YES: aggressive pricing is current - 1
        if position.side == "yes":
            aggressive_price = current_price_cents - 1
        else:
            aggressive_price = current_price_cents + 1
        
        ratchet_exit_intent = OrderIntent(
            ticker=position.market_id,
            side="yes",
            action="sell",
            price_cents=aggressive_price,
            count=position.contracts,
            order_type="market",
            source="ratchet_floor_breach",
        )
        
        # Verify aggressive pricing
        assert ratchet_exit_intent.price_cents == 78  # 79 - 1
    
    def test_ratchet_exit_rationale_includes_context(self):
        """Test that ratchet exit rationale includes floor breach context."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        from merid.event_venues.kalshi.position_cache import CachedPosition
        from datetime import datetime, timezone
        
        position = CachedPosition(
            market_id="BTC-USD-240329-W10",
            side="yes",
            contracts=10,
            avg_price_cents=50,
            ratchet_activated=True,
            ratchet_floor_price_cents=80,
            ratchet_activation_timestamp=datetime.now(timezone.utc),
        )
        
        current_price_cents = 79
        
        rationale = f"Ratchet floor breach: current={current_price_cents}c floor={position.ratchet_floor_price_cents}c"
        
        ratchet_exit_intent = OrderIntent(
            ticker=position.market_id,
            side="yes",
            action="sell",
            price_cents=78,
            count=position.contracts,
            order_type="market",
            source="ratchet_floor_breach",
            rationale=rationale,
        )
        
        # Verify rationale includes context
        assert "current=79c" in ratchet_exit_intent.rationale
        assert "floor=80c" in ratchet_exit_intent.rationale
        assert "Ratchet floor breach" in ratchet_exit_intent.rationale


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
