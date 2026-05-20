"""Unit tests for Kalshi order constraints.

Tests that the order constraints module correctly enforces:
- Market status gating (only submit when open/active)
- Price bounds (0-100 cents for binary markets)
- Quantity limits (per-order and per-market)
- Trading windows (no orders after close_ts)
"""

import pytest
from datetime import datetime, timezone, timedelta
from merid.event_venues.kalshi.order_constraints import (
    KalshiOrderConstraints,
    KalshiOrderLimits,
    OrderConstraintResult,
    OrderRejectionReason,
    validate_kalshi_order,
    get_order_constraints,
)


class TestMarketStatusGating:
    """Tests for market status validation."""
    
    def test_active_market_allows_orders(self):
        """Active market should allow orders."""
        constraints = KalshiOrderConstraints()
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        
        assert result.allowed is True
        assert result.reason is None
    
    def test_closed_market_blocks_orders(self):
        """Closed market should block orders."""
        constraints = KalshiOrderConstraints()
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="closed",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        
        assert result.allowed is False
        assert result.reason == OrderRejectionReason.MARKET_CLOSED
        assert "closed" in result.message.lower()
    
    def test_settled_market_blocks_orders(self):
        """Settled market should block orders."""
        constraints = KalshiOrderConstraints()
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="settled",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        
        assert result.allowed is False
        assert result.reason == OrderRejectionReason.MARKET_SETTLED
        assert "settled" in result.message.lower()
    
    def test_paused_market_blocks_orders(self):
        """Paused market should block orders."""
        constraints = KalshiOrderConstraints()
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="paused",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        
        assert result.allowed is False
        assert result.reason == OrderRejectionReason.MARKET_PAUSED
        assert "paused" in result.message.lower()
    
    def test_unknown_status_blocks_orders(self):
        """Unknown market status should block orders (fail-closed)."""
        constraints = KalshiOrderConstraints()
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="unknown_status",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        
        assert result.allowed is False
        assert result.reason == OrderRejectionReason.MARKET_NOT_OPEN
        assert "unknown" in result.message.lower()
    
    def test_halted_market_blocks_orders(self):
        """Halted market should block orders."""
        constraints = KalshiOrderConstraints()
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=10,
            current_position=0,
            market_halted=True,
        )
        
        assert result.allowed is False
        assert result.reason == OrderRejectionReason.MARKET_HALTED
        assert "halted" in result.message.lower()
    
    def test_status_case_insensitive(self):
        """Status validation should be case-insensitive."""
        constraints = KalshiOrderConstraints()
        
        # Test uppercase
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="ACTIVE",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        assert result.allowed is True
        
        # Test mixed case
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="Closed",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        assert result.allowed is False


class TestPriceBounds:
    """Tests for price bounds validation."""
    
    def test_price_in_bounds_allows_order(self):
        """Price within bounds should allow order."""
        constraints = KalshiOrderConstraints()
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        
        assert result.allowed is True
    
    def test_price_at_minimum_boundary(self):
        """Price at minimum boundary (1 cent) should allow order."""
        constraints = KalshiOrderConstraints()
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=1,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        
        assert result.allowed is True
    
    def test_price_at_maximum_boundary(self):
        """Price at maximum boundary (99 cents) should allow order."""
        constraints = KalshiOrderConstraints()
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=99,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        
        assert result.allowed is True
    
    def test_price_below_minimum_blocks_order(self):
        """Price below minimum (0 cents) should block order."""
        constraints = KalshiOrderConstraints()
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=0,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        
        assert result.allowed is False
        assert result.reason == OrderRejectionReason.PRICE_OUT_OF_BOUNDS
        assert "below" in result.message.lower()
    
    def test_price_above_maximum_blocks_order(self):
        """Price above maximum (100 cents) should block order."""
        constraints = KalshiOrderConstraints()
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=100,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        
        assert result.allowed is False
        assert result.reason == OrderRejectionReason.PRICE_OUT_OF_BOUNDS
        assert "above" in result.message.lower()
    
    def test_negative_price_blocks_order(self):
        """Negative price should block order."""
        constraints = KalshiOrderConstraints()
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=-10,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        
        assert result.allowed is False
        assert result.reason == OrderRejectionReason.PRICE_OUT_OF_BOUNDS


class TestQuantityLimits:
    """Tests for quantity limits validation."""
    
    def test_quantity_in_bounds_allows_order(self):
        """Quantity within bounds should allow order."""
        constraints = KalshiOrderConstraints()
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        
        assert result.allowed is True
    
    def test_quantity_at_minimum_boundary(self):
        """Quantity at minimum boundary (1) should allow order."""
        constraints = KalshiOrderConstraints()
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=1,
            current_position=0,
            market_halted=False,
        )
        
        assert result.allowed is True
    
    def test_quantity_at_maximum_boundary(self):
        """Quantity at maximum boundary should allow order."""
        constraints = KalshiOrderConstraints()
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=10000,
            current_position=0,
            market_halted=False,
        )
        
        assert result.allowed is True
    
    def test_quantity_below_minimum_blocks_order(self):
        """Quantity below minimum (0) should block order."""
        constraints = KalshiOrderConstraints()
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=0,
            current_position=0,
            market_halted=False,
        )
        
        assert result.allowed is False
        assert result.reason == OrderRejectionReason.QUANTITY_TOO_SMALL
        assert "below" in result.message.lower()
    
    def test_quantity_above_maximum_blocks_order(self):
        """Quantity above maximum should block order."""
        constraints = KalshiOrderConstraints()
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=10001,
            current_position=0,
            market_halted=False,
        )
        
        assert result.allowed is False
        assert result.reason == OrderRejectionReason.QUANTITY_TOO_LARGE
        assert "above" in result.message.lower()
    
    def test_market_position_limit_exceeded(self):
        """Order that would exceed market position limit should be blocked."""
        constraints = KalshiOrderConstraints()
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=5001,
            current_position=5000,  # Would exceed 10000 limit
            market_halted=False,
        )
        
        assert result.allowed is False
        assert result.reason == OrderRejectionReason.MARKET_LIMIT_EXCEEDED
        assert "exceed" in result.message.lower()
    
    def test_market_position_limit_at_boundary(self):
        """Order at market position limit boundary should be allowed."""
        constraints = KalshiOrderConstraints()
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=5000,
            current_position=5000,  # Exactly at 10000 limit
            market_halted=False,
        )
        
        assert result.allowed is True


class TestTradingWindow:
    """Tests for trading window validation."""
    
    def test_sufficient_time_to_close_allows_order(self):
        """Sufficient time before market close should allow order."""
        constraints = KalshiOrderConstraints()
        close_time = datetime.now(timezone.utc) + timedelta(seconds=120)
        
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=close_time,
            side="yes",
            price_cents=50,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        
        assert result.allowed is True
    
    def test_within_buffer_blocks_order(self):
        """Order within buffer window (60s) should be blocked."""
        constraints = KalshiOrderConstraints()
        close_time = datetime.now(timezone.utc) + timedelta(seconds=30)
        
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=close_time,
            side="yes",
            price_cents=50,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        
        assert result.allowed is False
        assert result.reason == OrderRejectionReason.TRADING_WINDOW_CLOSED
        assert "buffer" in result.message.lower()
    
    def test_market_already_closed_blocks_order(self):
        """Order after market close should be blocked."""
        constraints = KalshiOrderConstraints()
        close_time = datetime.now(timezone.utc) - timedelta(seconds=30)
        
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=close_time,
            side="yes",
            price_cents=50,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        
        assert result.allowed is False
        assert result.reason == OrderRejectionReason.TRADING_WINDOW_CLOSED
        assert "closes" in result.message.lower() or "closed" in result.message.lower()
    
    def test_no_close_time_allows_order(self):
        """Market without close time should allow order."""
        constraints = KalshiOrderConstraints()
        
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        
        assert result.allowed is True
    
    def test_custom_buffer_seconds(self):
        """Custom buffer seconds should be respected."""
        custom_limits = KalshiOrderLimits(CLOSE_WINDOW_BUFFER_SECONDS=120)
        constraints = KalshiOrderLimits(custom_limits)
        constraints = KalshiOrderConstraints(limits=custom_limits)
        
        # 90 seconds is within custom 120s buffer
        close_time = datetime.now(timezone.utc) + timedelta(seconds=90)
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=close_time,
            side="yes",
            price_cents=50,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        
        assert result.allowed is False


class TestConvenienceFunction:
    """Tests for the convenience validate_kalshi_order function."""
    
    def test_convenience_function_allowed(self):
        """Convenience function should return (True, "") for allowed orders."""
        allowed, reason = validate_kalshi_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        
        assert allowed is True
        assert reason == ""
    
    def test_convenience_function_rejected(self):
        """Convenience function should return (False, reason) for rejected orders."""
        allowed, reason = validate_kalshi_order(
            market_id="KXBTC15M-TEST",
            market_status="closed",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        
        assert allowed is False
        assert "closed" in reason.lower()
    
    def test_singleton_get_order_constraints(self):
        """get_order_constraints should return singleton instance."""
        constraints1 = get_order_constraints()
        constraints2 = get_order_constraints()
        
        assert constraints1 is constraints2


class TestCustomLimits:
    """Tests for custom order limits."""
    
    def test_custom_price_limits(self):
        """Custom price limits should be enforced."""
        custom_limits = KalshiOrderLimits(MIN_PRICE_CENTS=10, MAX_PRICE_CENTS=90)
        constraints = KalshiOrderConstraints(limits=custom_limits)
        
        # Price below custom minimum
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=5,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        assert result.allowed is False
        
        # Price within custom bounds
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        assert result.allowed is True
        
        # Price above custom maximum
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=95,
            quantity=10,
            current_position=0,
            market_halted=False,
        )
        assert result.allowed is False
    
    def test_custom_quantity_limits(self):
        """Custom quantity limits should be enforced."""
        custom_limits = KalshiOrderLimits(MIN_ORDER_SIZE=5, MAX_ORDER_SIZE=1000)
        constraints = KalshiOrderConstraints(limits=custom_limits)
        
        # Quantity below custom minimum
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=3,
            current_position=0,
            market_halted=False,
        )
        assert result.allowed is False
        
        # Quantity within custom bounds
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=100,
            current_position=0,
            market_halted=False,
        )
        assert result.allowed is True
        
        # Quantity above custom maximum
        result = constraints.validate_order(
            market_id="KXBTC15M-TEST",
            market_status="active",
            market_close_time=None,
            side="yes",
            price_cents=50,
            quantity=2000,
            current_position=0,
            market_halted=False,
        )
        assert result.allowed is False
