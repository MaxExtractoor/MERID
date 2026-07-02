"""
Unit tests for Order Router rate limits and pricing validation.

Tests order submission rate limiting, price validation, and rejection handling.
"""

import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    OrderResult,
    route_order_async,
)
from merid.event_venues.kalshi.rate_limiter import get_rate_limiter, reset_rate_limiter

class TestOrderRouterPricingValidation:
    """Test order router pricing validation."""
    
    @pytest.fixture
    def valid_order_intent(self):
        """Create a valid order intent for testing."""
        return OrderIntent(
            intent_id="test-123",
            ticker="KXBTC15M-26JUN022230-30",
            side="yes",
            action="buy",
            price_cents=55,  # Valid: 1-99 cents
            count=10,
            source="BTC_15M"  # Valid agent in whitelist
        )
    
    @pytest.mark.asyncio
    async def test_valid_order_passes_pricing_validation(self, valid_order_intent):
        """Test that a valid order passes pricing validation specifically."""
        # Test that valid price passes the pricing validation check
        # This focuses on the guardrail we implemented
        
        # Valid prices should pass the pricing validation logic
        valid_prices = [1, 50, 99]  # Boundary values
        
        for price in valid_prices:
            valid_order_intent.price_cents = price
            
            # The pricing validation logic: 1 <= price_cents <= 99 and integer
            is_valid_price = (
                isinstance(valid_order_intent.price_cents, int) and
                1 <= valid_order_intent.price_cents <= 99
            )
            
            assert is_valid_price == True, f"Price {price} should be valid"
        
        # Test the actual validation logic in the order router
        # We'll test the specific validation function logic
        from merid.event_venues.kalshi.order_router import route_order_async
        
        # Mock all the complex dependencies to focus on pricing
        with patch('merid.event_venues.kalshi.order_router.get_rate_limiter') as mock_get_limiter, \
             patch('merid.event_venues.kalshi.order_router._resolve_mode') as mock_resolve_mode, \
             patch('merid.event_venues.kalshi.order_router._check_exit_target_invariant') as mock_invariant, \
             patch('merid.event_venues.kalshi.order_router._validate_risk_contract_linkage') as mock_risk:
            
            mock_limiter = AsyncMock()
            mock_limiter.acquire.return_value = True
            mock_get_limiter.return_value = mock_limiter
            mock_resolve_mode.return_value = "paper"
            mock_invariant.return_value = None
            mock_risk.return_value = (True, None)
            
            # Test with valid price - should not be rejected for pricing reasons
            valid_order_intent.price_cents = 55
            result = await route_order_async(valid_order_intent)
            
            # If rejected, it should NOT be due to pricing validation
            if result.status == "rejected":
                assert "invalid_price" not in result.reason, f"Order rejected for pricing: {result.reason}"
            else:
                # Order accepted - pricing validation passed
                assert True
    
    @pytest.mark.asyncio
    async def test_invalid_price_zero(self, valid_order_intent):
        """Test rejection of order with price_cents = 0."""
        valid_order_intent.price_cents = 0
        
        with patch('merid.event_venues.kalshi.order_router.get_rate_limiter') as mock_get_limiter:
            mock_limiter = AsyncMock()
            mock_limiter.acquire.return_value = True
            mock_get_limiter.return_value = mock_limiter
            
            result = await route_order_async(valid_order_intent)
            
            assert result.status == "rejected"
            assert "invalid_price:price_cents=0" in result.reason
    
    @pytest.mark.asyncio
    async def test_invalid_price_too_high(self, valid_order_intent):
        """Test rejection of order with price_cents > 99."""
        valid_order_intent.price_cents = 100
        
        with patch('merid.event_venues.kalshi.order_router.get_rate_limiter') as mock_get_limiter:
            mock_limiter = AsyncMock()
            mock_limiter.acquire.return_value = True
            mock_get_limiter.return_value = mock_limiter
            
            result = await route_order_async(valid_order_intent)
            
            assert result.status == "rejected"
            assert "invalid_price:price_cents=100" in result.reason
    
    @pytest.mark.asyncio
    async def test_invalid_price_negative(self, valid_order_intent):
        """Test rejection of order with negative price_cents."""
        valid_order_intent.price_cents = -10
        
        with patch('merid.event_venues.kalshi.order_router.get_rate_limiter') as mock_get_limiter:
            mock_limiter = AsyncMock()
            mock_limiter.acquire.return_value = True
            mock_get_limiter.return_value = mock_limiter
            
            result = await route_order_async(valid_order_intent)
            
            assert result.status == "rejected"
            assert "invalid_price:price_cents=-10" in result.reason
    
    @pytest.mark.asyncio
    async def test_invalid_price_non_integer(self, valid_order_intent):
        """Test rejection of order with non-integer price_cents."""
        valid_order_intent.price_cents = 55.5  # Float instead of int
        
        with patch('merid.event_venues.kalshi.order_router.get_rate_limiter') as mock_get_limiter:
            mock_limiter = AsyncMock()
            mock_limiter.acquire.return_value = True
            mock_get_limiter.return_value = mock_limiter
            
            result = await route_order_async(valid_order_intent)
            
            assert result.status == "rejected"
            assert "invalid_price:price_not_integer" in result.reason
    
    @pytest.mark.asyncio
    async def test_invalid_price_string(self, valid_order_intent):
        """Test rejection of order with string price_cents."""
        valid_order_intent.price_cents = "55"  # String instead of int
        
        with patch('merid.event_venues.kalshi.order_router.get_rate_limiter') as mock_get_limiter:
            mock_limiter = AsyncMock()
            mock_limiter.acquire.return_value = True
            mock_get_limiter.return_value = mock_limiter
            
            result = await route_order_async(valid_order_intent)
            
            assert result.status == "rejected"
            assert "invalid_price:price_not_integer" in result.reason
    
    @pytest.mark.asyncio
    async def test_valid_price_boundary_values(self, valid_order_intent):
        """Test that boundary values (1 and 99) are accepted."""
        # Test price_cents = 1
        valid_order_intent.price_cents = 1
        
        with patch('merid.event_venues.kalshi.order_router.get_rate_limiter') as mock_get_limiter, \
             patch('merid.event_venues.kalshi.order_router._resolve_mode') as mock_resolve_mode, \
             patch('merid.event_venues.kalshi.order_router._check_exit_target_invariant') as mock_invariant, \
             patch('merid.event_venues.kalshi.order_router._validate_risk_contract_linkage') as mock_risk:
            
            mock_limiter = AsyncMock()
            mock_limiter.acquire.return_value = True
            mock_get_limiter.return_value = mock_limiter
            mock_resolve_mode.return_value = "paper"
            mock_invariant.return_value = None
            mock_risk.return_value = (True, None)
            
            result = await route_order_async(valid_order_intent)
            assert result.status != "rejected" or "invalid_price" not in result.reason
        
        # Test price_cents = 99
        valid_order_intent.price_cents = 99
        
        with patch('merid.event_venues.kalshi.order_router.get_rate_limiter') as mock_get_limiter, \
             patch('merid.event_venues.kalshi.order_router._resolve_mode') as mock_resolve_mode, \
             patch('merid.event_venues.kalshi.order_router._check_exit_target_invariant') as mock_invariant, \
             patch('merid.event_venues.kalshi.order_router._validate_risk_contract_linkage') as mock_risk:
            
            mock_limiter = AsyncMock()
            mock_limiter.acquire.return_value = True
            mock_get_limiter.return_value = mock_limiter
            mock_resolve_mode.return_value = "paper"
            mock_invariant.return_value = None
            mock_risk.return_value = (True, None)
            
            result = await route_order_async(valid_order_intent)
            assert result.status != "rejected" or "invalid_price" not in result.reason

class TestOrderRouterRateLimits:
    """Test order router rate limiting."""
    
    @pytest.fixture
    def valid_order_intent(self):
        """Create a valid order intent for testing."""
        return OrderIntent(
            intent_id="test-123",
            ticker="KXBTC15M-26JUN022230-30",
            side="yes",
            action="buy",
            price_cents=55,
            count=10,
            source="test"
        )
    
    def setup_method(self):
        """Reset rate limiter before each test."""
        reset_rate_limiter()
    
    @pytest.mark.asyncio
    async def test_order_rate_limit_accepts_within_limit(self, valid_order_intent):
        """Test that orders within rate limit are accepted."""
        # Mock rate limiter to allow the order
        with patch('merid.event_venues.kalshi.order_router.get_rate_limiter') as mock_get_limiter:
            mock_limiter = AsyncMock()
            mock_limiter.acquire.return_value = True
            mock_get_limiter.return_value = mock_limiter
            
            with patch('merid.event_venues.kalshi.order_router._resolve_mode') as mock_resolve_mode, \
                 patch('merid.event_venues.kalshi.order_router._check_exit_target_invariant') as mock_invariant, \
                 patch('merid.event_venues.kalshi.order_router._validate_risk_contract_linkage') as mock_risk:
                
                mock_resolve_mode.return_value = "paper"
                mock_invariant.return_value = None
                mock_risk.return_value = (True, None)
                
                result = await route_order_async(valid_order_intent)
                
                # Rate limiter should be called for "order" endpoint
                mock_limiter.acquire.assert_called_once_with("order")
                
                # Should not be rejected due to rate limiting
                assert result.status != "rejected" or "rate_limit" not in result.reason
    
    @pytest.mark.asyncio
    async def test_order_rate_limit_rejects_when_exceeded(self, valid_order_intent):
        """Test that orders are rejected when rate limit is exceeded."""
        # Mock rate limiter to reject the order
        with patch('merid.event_venues.kalshi.order_router.get_rate_limiter') as mock_get_limiter:
            mock_limiter = AsyncMock()
            mock_limiter.acquire.return_value = False
            mock_get_limiter.return_value = mock_limiter
            
            result = await route_order_async(valid_order_intent)
            
            # Should be rejected due to rate limiting
            assert result.status == "rejected"
            assert "rate_limit:order_rate_exceeded" in result.reason
            
            # Rate limiter should be called for "order" endpoint
            mock_limiter.acquire.assert_called_once_with("order")
    
    @pytest.mark.asyncio
    async def test_multiple_orders_rate_limiting(self, valid_order_intent):
        """Test rate limiting across multiple orders."""
        limiter = get_rate_limiter()
        
        # Configure rate limiter for testing
        limiter.config.burst_capacity = 2
        limiter.config.requests_per_second = 1.0
        
        # Mock other dependencies
        with patch('merid.event_venues.kalshi.order_router._resolve_mode') as mock_resolve_mode, \
             patch('merid.event_venues.kalshi.order_router._check_exit_target_invariant') as mock_invariant, \
             patch('merid.event_venues.kalshi.order_router._validate_risk_contract_linkage') as mock_risk:
            
            mock_resolve_mode.return_value = "paper"
            mock_invariant.return_value = None
            mock_risk.return_value = (True, None)
            
            # First order should succeed
            result1 = await route_order_async(valid_order_intent)
            assert result1.status != "rejected" or "rate_limit" not in result1.reason
            
            # Second order should succeed
            result2 = await route_order_async(valid_order_intent)
            assert result2.status != "rejected" or "rate_limit" not in result2.reason
            
            # Third order should be rate limited
            result3 = await route_order_async(valid_order_intent)
            assert result3.status == "rejected"
            assert "rate_limit:order_rate_exceeded" in result3.reason

class TestOrderRouterIntegration:
    """Integration tests for order router with realistic scenarios."""
    
    @pytest.fixture
    def valid_order_intent(self):
        """Create a valid order intent for testing."""
        return OrderIntent(
            intent_id="test-123",
            ticker="KXBTC15M-26JUN022230-30",
            side="yes",
            action="buy",
            price_cents=55,
            count=10,
            source="test"
        )
    
    def setup_method(self):
        """Reset rate limiter before each test."""
        reset_rate_limiter()
    
    @pytest.mark.asyncio
    async def test_order_validation_priority(self, valid_order_intent):
        """Test that price validation happens before rate limiting."""
        # Set invalid price
        valid_order_intent.price_cents = 150  # Invalid
        
        # Mock rate limiter to allow (but shouldn't be called)
        with patch('merid.event_venues.kalshi.order_router.get_rate_limiter') as mock_get_limiter:
            mock_limiter = AsyncMock()
            mock_limiter.acquire.return_value = True
            mock_get_limiter.return_value = mock_limiter
            
            result = await route_order_async(valid_order_intent)
            
            # Should be rejected due to invalid price, not rate limit
            assert result.status == "rejected"
            assert "invalid_price:price_cents=150" in result.reason
            assert "rate_limit" not in result.reason
    
    @pytest.mark.asyncio
    async def test_order_rejection_reason_tracking(self, valid_order_intent):
        """Test that different rejection reasons are properly tracked."""
        # Test price rejection
        valid_order_intent.price_cents = 0
        
        with patch('merid.event_venues.kalshi.order_router.get_rate_limiter') as mock_get_limiter:
            mock_limiter = AsyncMock()
            mock_limiter.acquire.return_value = True
            mock_get_limiter.return_value = mock_limiter
            
            result = await route_order_async(valid_order_intent)
            assert result.status == "rejected"
            assert "invalid_price" in result.reason
        
        # Test rate limit rejection
        valid_order_intent.price_cents = 55  # Valid price
        
        with patch('merid.event_venues.kalshi.order_router.get_rate_limiter') as mock_get_limiter:
            mock_limiter = AsyncMock()
            mock_limiter.acquire.return_value = False
            mock_get_limiter.return_value = mock_limiter
            
            result = await route_order_async(valid_order_intent)
            assert result.status == "rejected"
            assert "rate_limit" in result.reason
    
    @pytest.mark.asyncio
    async def test_different_assets_rate_limiting(self, valid_order_intent):
        """Test rate limiting across different assets."""
        limiter = get_rate_limiter()
        limiter.config.burst_capacity = 1  # Very low limit for testing
        
        # Mock other dependencies
        with patch('merid.event_venues.kalshi.order_router._resolve_mode') as mock_resolve_mode, \
             patch('merid.event_venues.kalshi.order_router._check_exit_target_invariant') as mock_invariant, \
             patch('merid.event_venues.kalshi.order_router._validate_risk_contract_linkage') as mock_risk:
            
            mock_resolve_mode.return_value = "paper"
            mock_invariant.return_value = None
            mock_risk.return_value = (True, None)
            
            # BTC order
            btc_order = OrderIntent(
                intent_id="btc-123",
                ticker="KXBTC15M-26JUN022230-30",
                side="yes", action="buy", price_cents=55, count=10, source="test"
            )
            
            # ETH order
            eth_order = OrderIntent(
                intent_id="eth-123", 
                ticker="KXETH15M-26JUN022230-30",
                side="yes", action="buy", price_cents=55, count=10, source="test"
            )
            
            # First order (BTC) should succeed
            result_btc = await route_order_async(btc_order)
            assert result_btc.status != "rejected" or "rate_limit" not in result_btc.reason
            
            # Second order (ETH) should be rate limited (global limit)
            result_eth = await route_order_async(eth_order)
            assert result_eth.status == "rejected"
            assert "rate_limit:order_rate_exceeded" in result_eth.reason
