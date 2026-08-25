"""Tests for Idempotency-Key pattern implementation.

CRITICAL FIX (2026-07-17): Tests for duplicate order prevention via Idempotency-Key header.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal

from merid.event_venues.base import VenueOrder
from merid.event_venues.kalshi.order_router import OrderIntent


class TestIdempotencyKeyPattern:
    """Test Idempotency-Key pattern in order placement."""
    
    def test_order_intent_has_idempotency_key(self):
        """Test that OrderIntent generates unique idempotency_key."""
        intent1 = OrderIntent(
            ticker="KXBTC15M-26JUL162015-15",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
        )
        
        intent2 = OrderIntent(
            ticker="KXBTC15M-26JUL162015-15",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
        )
        
        # Should have unique idempotency keys
        assert intent1.idempotency_key is not None
        assert intent2.idempotency_key is not None
        assert intent1.idempotency_key != intent2.idempotency_key
        
        # Should have unique client_order_ids
        assert intent1.client_order_id is not None
        assert intent2.client_order_id is not None
        assert intent1.client_order_id != intent2.client_order_id
    
    def test_venue_order_has_idempotency_key_field(self):
        """Test that VenueOrder has idempotency_key field."""
        order = VenueOrder(
            market_id="KXBTC15M-26JUL162015-15",
            side="buy",
            size=Decimal("10"),
            price=Decimal("0.50"),
            idempotency_key="test_idemp_key_123",
        )
        
        assert order.idempotency_key == "test_idemp_key_123"
    
    def test_venue_order_idempotency_key_optional(self):
        """Test that idempotency_key is optional in VenueOrder."""
        order = VenueOrder(
            market_id="KXBTC15M-26JUL162015-15",
            side="buy",
            size=Decimal("10"),
            price=Decimal("0.50"),
        )
        
        assert order.idempotency_key is None
    
    def test_idempotency_key_format(self):
        """Test that idempotency_key follows expected format."""
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL162015-15",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
        )
        
        # Should start with "idemp_"
        assert intent.idempotency_key.startswith("idemp_")
        
        # Should be a reasonable length (UUID hex)
        assert len(intent.idempotency_key) > 10
    
    def test_client_order_id_format(self):
        """Test that client_order_id follows expected format."""
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL162015-15",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
        )
        
        # Should start with "client_"
        assert intent.client_order_id.startswith("client_")
        
        # Should be 16 hex chars after "client_" prefix (total 23 chars)
        assert len(intent.client_order_id) == 23  # "client_" + 16 hex chars


class TestIdempotencyKeyInClient:
    """Test Idempotency-Key header in Kalshi client."""
    
    @pytest.mark.asyncio
    async def test_idempotency_key_added_to_headers(self):
        """Test that idempotency_key is added to request headers."""
        import os
        os.environ["DEBUG_ALLOW_MANUAL_ORDERS"] = "true"
        
        from merid.event_venues.kalshi.client import KalshiVenueClient
        
        # Mock the client
        config = MagicMock()
        config.rest_base_url = "https://api.test.com"
        config.api_key = "test_key"
        
        client = KalshiVenueClient(config)
        
        # Create order with idempotency_key
        order = VenueOrder(
            market_id="KXBTC15M-26JUL162015-15",
            side="buy",
            size=Decimal("10"),
            price=Decimal("0.50"),
            idempotency_key="test_idemp_key_123",
        )
        
        # Mock _request_with_resilience to capture headers
        captured_headers = {}
        
        async def mock_request_with_resilience(method, path, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            return MagicMock(success=True, data={"order_id": "test_order"})
        
        client._request_with_resilience = mock_request_with_resilience
        
        # Call place_order_result
        result = await client.place_order_result(order)
        
        # Verify idempotency_key was passed in headers
        assert "Idempotency-Key" in captured_headers
        assert captured_headers["Idempotency-Key"] == "test_idemp_key_123"
    
    @pytest.mark.asyncio
    async def test_idempotency_key_not_added_when_missing(self):
        """Test that header is not added when idempotency_key is missing."""
        import os
        os.environ["DEBUG_ALLOW_MANUAL_ORDERS"] = "true"
        
        from merid.event_venues.kalshi.client import KalshiVenueClient
        
        # Mock the client
        config = MagicMock()
        config.rest_base_url = "https://api.test.com"
        config.api_key = "test_key"
        
        client = KalshiVenueClient(config)
        
        # Create order without idempotency_key
        order = VenueOrder(
            market_id="KXBTC15M-26JUL162015-15",
            side="buy",
            size=Decimal("10"),
            price=Decimal("0.50"),
        )
        
        # Mock _request_with_resilience to capture headers
        captured_headers = {}
        
        async def mock_request_with_resilience(method, path, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            return MagicMock(success=True, data={"order_id": "test_order"})
        
        client._request_with_resilience = mock_request_with_resilience
        
        # Call place_order_result
        result = await client.place_order_result(order)
        
        # Verify Idempotency-Key was not added
        assert "Idempotency-Key" not in captured_headers


class TestIdempotencyKeyIntegration:
    """Integration tests for Idempotency-Key pattern."""
    
    def test_order_intent_to_venue_order_mapping(self):
        """Test that idempotency_key is mapped from intent to venue order."""
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL162015-15",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
            idempotency_key="test_idemp_key_123",
            client_order_id="test_client_order_456",
        )
        
        # In the actual implementation, this mapping happens in order_router.py
        # We're testing the data structure compatibility here
        assert intent.idempotency_key == "test_idemp_key_123"
        assert intent.client_order_id == "test_client_order_456"
    
    def test_duplicate_intent_different_keys(self):
        """Test that duplicate intents get different keys."""
        intent1 = OrderIntent(
            ticker="KXBTC15M-26JUL162015-15",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
        )
        
        intent2 = OrderIntent(
            ticker="KXBTC15M-26JUL162015-15",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
        )
        
        # Even with identical parameters, keys should be unique
        assert intent1.idempotency_key != intent2.idempotency_key
        assert intent1.client_order_id != intent2.client_order_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
