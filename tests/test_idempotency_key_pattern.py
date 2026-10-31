"""Tests for Idempotency-Key pattern implementation.

CRITICAL FIX (2026-07-17): Tests for duplicate order prevention via Idempotency-Key header.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal

from merid.event_venues.base import VenueOrder
from merid.event_venues.kalshi.order_router import OrderIntent


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Isolated attempt store backed by a tmp sqlite db — the durable home
    of (order_attempt_id, client_order_id) that finalize_order_identity
    writes before the first network request."""
    import merid.event_venues.kalshi.order_attempt_store as attempt_store_module
    from merid.event_venues.kalshi.order_attempt_store import OrderAttemptStore

    monkeypatch.setattr(
        attempt_store_module, "DEFAULT_DB_PATH", str(tmp_path / "attempts.db")
    )
    monkeypatch.setattr(OrderAttemptStore, "_instances", {})
    return OrderAttemptStore()


class TestIdempotencyKeyPattern:
    """Test Idempotency-Key pattern in order placement."""
    
    def test_order_intent_has_idempotency_key(self, store):
        """idempotency_key is minted at construction; client_order_id is
        deliberately NOT — durable identity is bound by
        finalize_order_identity immediately before the first network call."""
        from merid.event_venues.kalshi.order_identity import (
            finalize_order_identity,
        )
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

        # client_order_id is unbound until identity finalization
        assert intent1.client_order_id is None
        assert intent2.client_order_id is None

        finalize_order_identity(intent1, store=store)
        finalize_order_identity(intent2, store=store)

        # Identical economics = same fingerprint = same logical attempt.
        # The second finalize recovers the first's durable identity
        # (durable dedup — resubmitting identical economics must not mint
        # a second wire key).
        assert intent1.client_order_id is not None
        assert intent2.client_order_id == intent1.client_order_id
        assert intent2.order_attempt_id == intent1.order_attempt_id

        # Re-entry retains the same identity (retry safety).
        coid1 = intent1.client_order_id
        finalize_order_identity(intent1, store=store)
        assert intent1.client_order_id == coid1
    
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
    
    def test_client_order_id_format(self, store):
        """Durable client_order_id format: 'merid_' + 20 hex chars (26
        total), minted by finalize_order_identity."""
        from merid.event_venues.kalshi.order_identity import (
            finalize_order_identity,
        )
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL162015-15",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
        )
        finalize_order_identity(intent, store=store)

        assert intent.client_order_id.startswith("merid_")
        assert len(intent.client_order_id) == 26  # "merid_" + 20 hex chars


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
        
        # Create order with idempotency_key.  outcome_id is required —
        # the client's direction guard blocks before header construction
        # without it.
        order = VenueOrder(
            market_id="KXBTC15M-26JUL162015-15",
            side="buy",
            outcome_id="yes",
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
        
        # Create order without idempotency_key — outcome_id required so
        # the order actually reaches header construction (previously this
        # passed vacuously: the order was blocked upstream).
        order = VenueOrder(
            market_id="KXBTC15M-26JUL162015-15",
            side="buy",
            outcome_id="yes",
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
    
    def test_duplicate_intent_different_keys(self, store):
        """The durable dedup contract: identical economics share one
        durable identity while the attempt is unresolved (prevents
        double-submit); a *different* authorized attempt — different
        fingerprint — mints a distinct identity; and once the stored
        attempt is terminal its coid is permanently consumed."""
        from merid.event_venues.kalshi.order_identity import (
            finalize_order_identity,
        )
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

        # Construction-time audit nonces still differ
        assert intent1.idempotency_key != intent2.idempotency_key

        finalize_order_identity(intent1, store=store)
        finalize_order_identity(intent2, store=store)

        # Same fingerprint + unresolved attempt -> same durable identity
        assert intent2.client_order_id == intent1.client_order_id
        assert intent2.order_attempt_id == intent1.order_attempt_id

        # Different fingerprint (distinct authorized attempt) -> fresh identity
        intent3 = OrderIntent(
            ticker="KXBTC15M-26JUL162015-15",
            side="yes",
            action="buy",
            price_cents=51,
            count=10,
        )
        finalize_order_identity(intent3, store=store)
        assert intent3.client_order_id != intent1.client_order_id
        assert intent3.order_attempt_id != intent1.order_attempt_id

        # Terminal stored attempt consumes its coid permanently — the same
        # economics resubmitted gets a fresh key, never a rebound dead key.
        rec = store.get_by_client_order_id(intent1.client_order_id)
        store.update_status(rec.order_attempt_id, "REJECTED")
        intent4 = OrderIntent(
            ticker="KXBTC15M-26JUL162015-15",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
        )
        finalize_order_identity(intent4, store=store)
        assert intent4.client_order_id != intent1.client_order_id
        assert intent4.order_attempt_id != intent1.order_attempt_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
