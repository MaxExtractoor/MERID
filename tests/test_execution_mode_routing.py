"""
Tests for execution mode routing in order_router.

Tests the _apply_execution_mode function that maps execution_mode to order parameters.
"""

import pytest
from merid.event_venues.kalshi.order_router import OrderIntent, _apply_execution_mode


class TestExecutionModeRouting:
    """Test execution mode to order parameter mapping."""
    
    def test_maker_execution_mode(self):
        """Test maker execution mode parameters."""
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            execution_mode="maker",
        )
        
        post_only, aggressiveness, order_type, tif = _apply_execution_mode(intent)
        
        assert post_only is True
        assert aggressiveness == 0.0
        assert order_type == "limit"
        assert tif == "gtc"
    
    def test_taker_execution_mode(self):
        """Test taker execution mode parameters."""
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            execution_mode="taker",
        )
        
        post_only, aggressiveness, order_type, tif = _apply_execution_mode(intent)
        
        assert post_only is False
        assert aggressiveness == 1.0
        assert order_type == "limit"
        assert tif == "ioc"
    
    def test_staged_ioc_execution_mode(self):
        """Test staged IOC execution mode parameters."""
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            execution_mode="staged_ioc",
        )
        
        post_only, aggressiveness, order_type, tif = _apply_execution_mode(intent)
        
        assert post_only is False
        assert aggressiveness == 0.5
        assert order_type == "limit"
        assert tif == "ioc"
    
    def test_passive_quote_execution_mode(self):
        """Test passive quote execution mode parameters."""
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            execution_mode="passive_quote",
        )
        
        post_only, aggressiveness, order_type, tif = _apply_execution_mode(intent)
        
        assert post_only is True
        assert aggressiveness == 0.0
        assert order_type == "limit"
        assert tif == "gtc"
    
    def test_none_execution_mode(self):
        """Test default behavior when execution_mode is None."""
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            execution_mode=None,
            post_only=False,
            aggressiveness=0.5,
            order_type="limit",
            time_in_force="gtc",
        )
        
        post_only, aggressiveness, order_type, tif = _apply_execution_mode(intent)
        
        # Should use existing intent values
        assert post_only is False
        assert aggressiveness == 0.5
        assert order_type == "limit"
        assert tif == "gtc"
    
    def test_invalid_execution_mode(self):
        """Test default behavior when execution_mode is invalid."""
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            execution_mode="invalid_mode",
            post_only=True,
            aggressiveness=0.0,
            order_type="limit",
            time_in_force="gtc",
        )
        
        post_only, aggressiveness, order_type, tif = _apply_execution_mode(intent)
        
        # Should use existing intent values
        assert post_only is True
        assert aggressiveness == 0.0
        assert order_type == "limit"
        assert tif == "gtc"
    
    def test_execution_mode_field_in_order_intent(self):
        """Test that OrderIntent has execution_mode field."""
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            execution_mode="maker",
        )
        
        assert hasattr(intent, 'execution_mode')
        assert intent.execution_mode == "maker"
    
    def test_execution_mode_optional(self):
        """Test that execution_mode is optional in OrderIntent."""
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        
        assert intent.execution_mode is None
