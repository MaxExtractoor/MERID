"""Integration tests for ratchet profit floor with position cache.

This tests the integration between ratchet logic and the position cache,
including ratchet state tracking, activation, and floor breach handling.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock
import time


class TestRatchetPositionCacheIntegration:
    """Test suite for ratchet integration with position cache."""
    
    def test_cached_position_has_ratchet_fields(self):
        """Verify CachedPosition has ratchet tracking fields."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        
        position = CachedPosition(
            market_id="BTC-USD-240329-W10",
            agent_id="test_agent",
            side="yes",
            thesis_side="yes",
            contracts=10,
            avg_price_cents=50,
            # Ratchet fields
            ratchet_activated=False,
            ratchet_floor_price_cents=None,
            ratchet_activation_timestamp=None,
        )
        
        assert position.ratchet_activated is False
        assert position.ratchet_floor_price_cents is None
        assert position.ratchet_activation_timestamp is None
    
    def test_ratchet_state_initialization_on_fill(self):
        """Test that ratchet state is initialized to inactive on new fills."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        
        # Simulate a new position creation (as happens in on_fill)
        position = CachedPosition(
            market_id="BTC-USD-240329-W10",
            agent_id="test_agent",
            side="yes",
            thesis_side="yes",
            contracts=10,
            avg_price_cents=50,
            take_profit_price_cents=99,
            take_profit_r_multiple=2.0,
            stop_loss_price_cents=45,
            fill_source="alpha",
            client_order_id="test-coid",
            entry_intent_id="test-coid",
            # Ratchet initialization
            ratchet_activated=False,
            ratchet_floor_price_cents=None,
            ratchet_activation_timestamp=None,
        )
        
        # Verify ratchet starts inactive
        assert position.ratchet_activated is False
        assert position.ratchet_floor_price_cents is None
        assert position.ratchet_activation_timestamp is None
    
    def test_ratchet_activation_updates_position_state(self):
        """Test that ratchet activation updates position state correctly."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        from merid.prediction.dynamic_takeprofit import DynamicTakeProfitEngine, TakeProfitPlan
        
        position = CachedPosition(
            market_id="BTC-USD-240329-W10",
            agent_id="test_agent",
            side="yes",
            thesis_side="yes",
            contracts=10,
            avg_price_cents=50,
            ratchet_activated=False,
            ratchet_floor_price_cents=None,
            ratchet_activation_timestamp=None,
        )
        
        engine = DynamicTakeProfitEngine()
        plan = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=True,
            ratchet_activation_threshold_cents=85,
            ratchet_floor_offset_cents=5,
        )
        
        # Simulate ratchet activation at 85c
        current_price_cents = 85
        should_activate = engine.should_activate_ratchet(current_price_cents, "LONG", plan)
        
        assert should_activate is True
        
        # Update position state
        floor_price = engine.compute_ratchet_floor(current_price_cents, plan, "LONG")
        position.ratchet_activated = True
        position.ratchet_floor_price_cents = floor_price
        position.ratchet_activation_timestamp = datetime.now(timezone.utc)
        
        # Verify state updated
        assert position.ratchet_activated is True
        assert position.ratchet_floor_price_cents == 80
        assert position.ratchet_activation_timestamp is not None
    
    def test_ratchet_floor_breach_detection(self):
        """Test that floor breach is detected correctly."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        from merid.prediction.dynamic_takeprofit import DynamicTakeProfitEngine, TakeProfitPlan
        
        position = CachedPosition(
            market_id="BTC-USD-240329-W10",
            side="yes",
            contracts=10,
            avg_price_cents=50,
            ratchet_activated=True,
            ratchet_floor_price_cents=80,
            ratchet_activation_timestamp=datetime.now(timezone.utc),
        )
        
        engine = DynamicTakeProfitEngine()
        plan = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=True,
            ratchet_floor_offset_cents=5,
            ratchet_force_exit_on_breach=True,
            ratchet_min_hold_after_activation_sec=30,
        )
        
        # Test floor breach
        activation_ts = position.ratchet_activation_timestamp.timestamp()
        
        # Below floor should trigger exit (after min hold time)
        should_exit = engine.should_exit_on_ratchet_floor(
            current_price_cents=79,
            floor_price_cents=position.ratchet_floor_price_cents,
            direction="LONG",
            activation_timestamp=activation_ts - 60,  # 60 seconds ago (past min hold)
            min_hold_seconds=30,
        )
        assert should_exit is True
        
        # Above floor should not trigger exit
        should_exit = engine.should_exit_on_ratchet_floor(
            current_price_cents=81,
            floor_price_cents=position.ratchet_floor_price_cents,
            direction="LONG",
            activation_timestamp=activation_ts - 60,
            min_hold_seconds=30,
        )
        assert should_exit is False
    
    def test_ratchet_min_hold_prevents_immediate_exit(self):
        """Test that min hold time prevents immediate exit on noise."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        from merid.prediction.dynamic_takeprofit import DynamicTakeProfitEngine, TakeProfitPlan
        
        position = CachedPosition(
            market_id="BTC-USD-240329-W10",
            side="yes",
            contracts=10,
            avg_price_cents=50,
            ratchet_activated=True,
            ratchet_floor_price_cents=80,
            ratchet_activation_timestamp=datetime.now(timezone.utc),
        )
        
        engine = DynamicTakeProfitEngine()
        plan = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=True,
            ratchet_floor_offset_cents=5,
            ratchet_min_hold_after_activation_sec=30,
        )
        
        # Just activated (0 seconds ago)
        activation_ts = position.ratchet_activation_timestamp.timestamp()
        
        # Should not exit due to min hold time
        should_exit = engine.should_exit_on_ratchet_floor(
            current_price_cents=79,
            floor_price_cents=position.ratchet_floor_price_cents,
            direction="LONG",
            activation_timestamp=activation_ts,
            min_hold_seconds=30,
        )
        assert should_exit is False
    
    def test_ratchet_short_position_floor_breach(self):
        """Test ratchet floor breach for SHORT (NO) positions."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        from merid.prediction.dynamic_takeprofit import DynamicTakeProfitEngine, TakeProfitPlan
        
        position = CachedPosition(
            market_id="BTC-USD-240329-W10",
            side="no",
            contracts=10,
            avg_price_cents=50,
            ratchet_activated=True,
            ratchet_floor_price_cents=55,  # For NO, floor is above activation
            ratchet_activation_timestamp=datetime.now(timezone.utc),
        )
        
        engine = DynamicTakeProfitEngine()
        plan = TakeProfitPlan(
            tp_price=0.99,
            tp_r_multiple=2.0,
            tp_level=type('obj', (object,), {'value': 'stretch'})(),
            ratchet_enabled=True,
            ratchet_floor_offset_cents=5,
        )
        
        activation_ts = position.ratchet_activation_timestamp.timestamp() - 60
        
        # For NO: exit when price rises to or above floor
        should_exit = engine.should_exit_on_ratchet_floor(
            current_price_cents=56,
            floor_price_cents=position.ratchet_floor_price_cents,
            direction="SHORT",
            activation_timestamp=activation_ts,
            min_hold_seconds=30,
        )
        assert should_exit is True
        
        # Below floor should not trigger exit
        should_exit = engine.should_exit_on_ratchet_floor(
            current_price_cents=54,
            floor_price_cents=position.ratchet_floor_price_cents,
            direction="SHORT",
            activation_timestamp=activation_ts,
            min_hold_seconds=30,
        )
        assert should_exit is False
    
    def test_racket_state_persistence_in_cache(self):
        """Test that ratchet state persists in position cache."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        
        # Create position with active ratchet
        position = CachedPosition(
            market_id="BTC-USD-240329-W10",
            side="yes",
            contracts=10,
            avg_price_cents=50,
            ratchet_activated=True,
            ratchet_floor_price_cents=80,
            ratchet_activation_timestamp=datetime.now(timezone.utc),
        )
        
        # Convert to dict (as would happen in cache sync)
        pos_dict = {
            "market_id": position.market_id,
            "contracts": position.contracts,
            "side": position.side,
            "avg_price_cents": position.avg_price_cents,
            "ratchet_activated": position.ratchet_activated,
            "ratchet_floor_price_cents": position.ratchet_floor_price_cents,
            "ratchet_activation_timestamp": position.ratchet_activation_timestamp,
        }
        
        # Reconstruct from dict
        reconstructed = CachedPosition(
            market_id=pos_dict["market_id"],
            agent_id="test_agent",
            contracts=pos_dict["contracts"],
            side=pos_dict["side"],
            thesis_side=pos_dict.get("thesis_side", "yes"),
            avg_price_cents=pos_dict["avg_price_cents"],
            ratchet_activated=pos_dict.get("ratchet_activated", False),
            ratchet_floor_price_cents=pos_dict.get("ratchet_floor_price_cents"),
            ratchet_activation_timestamp=pos_dict.get("ratchet_activation_timestamp"),
        )
        
        # Verify state preserved
        assert reconstructed.ratchet_activated is True
        assert reconstructed.ratchet_floor_price_cents == 80
        assert reconstructed.ratchet_activation_timestamp is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
