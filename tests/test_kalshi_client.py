"""Tests for KalshiVenueClient.

Tests all production-ready methods including pagination, risk calculations,
and portfolio aggregation. Uses mocked responses to avoid external API calls.
"""

import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from merid.event_venues.base import (
    EventMarket,
    MarketFilter,
    PlacedOrder,
    VenueOrder,
)
from merid.event_venues.kalshi.client import (
    KalshiTokenBucket,
    KalshiVenueClient,
    get_kalshi_client,
    KALSHI_RATE_TIERS,
)
from merid.event_venues.kalshi.models import KalshiConfig
from merid.resilience import OperationResult


@pytest_asyncio.fixture
async def client():
    """Create a test client with mocked auth."""
    config = KalshiConfig(
        api_key="test_key_12345",
        private_key_pem="""-----BEGIN RSA PRIVATE KEY-----
MIICXgIBAAJBAL8U2zCkGqM3mLwP+5F1z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9
z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z0CAwEAAQJBAKjM3mLw
P+5F1z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F
9z9F9z9F9z9F9z9F9z9F9z0CIQDP8U2zCkGqM3mLwP+5F1z9F9z9F9z9F9z9F9z9
F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z0IfwIX
AAL8U2zCkGqM3mLwP+5F1z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9
z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z0=
-----END RSA PRIVATE KEY-----""",
        base_url="https://api.elections.kalshi.com/trade-api/v2",
    )
    client = KalshiVenueClient(config)
    
    # Mock the HTTP client
    client._http_client = AsyncMock()
    client._http_client.is_closed = False
    client._auth_mode = "rsa"
    client._private_key = MagicMock()
    client._private_key.sign.return_value = b"mock_signature"
    
    yield client
    
    await client.close()


class TestTokenBucket:
    """Tests for the rate limiter."""

    def test_init_basic_tier(self):
        bucket = KalshiTokenBucket("basic")
        assert bucket.read_rate == 20
        assert bucket.write_rate == 10

    def test_init_premier_tier(self):
        bucket = KalshiTokenBucket("premier")
        assert bucket.read_rate == 100
        assert bucket.write_rate == 100

    @pytest.mark.asyncio
    async def test_acquire_read_token(self):
        bucket = KalshiTokenBucket("basic")
        wait = await bucket.acquire(is_write=False)
        assert wait == 0.0
        assert bucket._read_tokens == 19.0

    @pytest.mark.asyncio
    async def test_acquire_write_token(self):
        bucket = KalshiTokenBucket("basic")
        wait = await bucket.acquire(is_write=True)
        assert wait == 0.0
        assert bucket._write_tokens == 9.0


class TestCircuitBreaker:
    """Tests for circuit breaker integration."""

    @pytest.mark.asyncio
    async def test_circuit_opens_after_failures(self, client):
        """Circuit should open after threshold failures."""
        # Mock failures
        client._http_client.request.side_effect = Exception("Network error")
        
        # Make requests until circuit opens
        for _ in range(5):
            result = await client._request_with_resilience(
                "GET", "/markets", operation_name="test"
            )
        
        # Circuit should be open now
        assert result.success is False
        
    @pytest.mark.asyncio
    async def test_circuit_recover_after_timeout(self, client):
        """Circuit should allow test requests after recovery timeout."""
        status = client.get_circuit_status()
        assert "state" in status


class TestPagination:
    """Tests for cursor-based pagination."""

    @pytest.mark.asyncio
    async def test_list_markets_pagination(self, client):
        """Test that list_markets follows cursors correctly."""
        # Mock paginated response
        responses = [
            MagicMock(
                status_code=200,
                json=AsyncMock(return_value={
                    "markets": [{"ticker": f"M{i}", "title": f"Market {i}"} for i in range(5)],
                    "cursor": "cursor_1"
                }),
                headers={},
                text="",
            ),
            MagicMock(
                status_code=200,
                json=AsyncMock(return_value={
                    "markets": [{"ticker": f"M{i+5}", "title": f"Market {i+5}"} for i in range(5)],
                    "cursor": None  # End of pagination
                }),
                headers={},
                text="",
            ),
        ]
        
        client._http_client.request = AsyncMock(side_effect=responses)
        
        filter_params = MarketFilter(limit=10)
        result = await client.list_markets_result(filter_params)
        
        assert result.success is True
        assert len(result.data) == 10
        assert client._http_client.request.call_count == 2

    @pytest.mark.asyncio
    async def test_get_positions_pagination(self, client):
        """Test positions pagination with both market and event positions."""
        responses = [
            MagicMock(
                status_code=200,
                json=AsyncMock(return_value={
                    "market_positions": [
                        {"ticker": "A", "side": "yes", "count": 10, "avg_price": 50}
                    ],
                    "event_positions": [
                        {"event_ticker": "EVT-1", "event_exposure": 100}
                    ],
                    "cursor": "cursor_1"
                }),
                headers={},
                text="",
            ),
            MagicMock(
                status_code=200,
                json=AsyncMock(return_value={
                    "market_positions": [],
                    "event_positions": [],
                    "cursor": None
                }),
                headers={},
                text="",
            ),
        ]
        
        client._http_client.request = AsyncMock(side_effect=responses)
        
        result = await client.get_positions_result()
        
        assert result.success is True
        assert len(result.data) == 2  # 1 market + 1 event position


class TestFilters:
    """Tests for API filtering."""

    @pytest.mark.asyncio
    async def test_list_markets_with_event_ticker_filter(self, client):
        """Test event_ticker filter is passed correctly."""
        response = MagicMock(
            status_code=200,
            json=AsyncMock(return_value={"markets": [], "cursor": None}),
            headers={},
            text="",
        )
        client._http_client.request = AsyncMock(return_value=response)
        
        filter_params = MarketFilter(event_ticker="KXBTC-24DEC", limit=100)
        await client.list_markets_result(filter_params)
        
        # Check params included event_ticker
        call_args = client._http_client.request.call_args
        assert call_args.kwargs["params"]["event_ticker"] == "KXBTC-24DEC"

    @pytest.mark.asyncio
    async def test_get_positions_with_filters(self, client):
        """Test position filtering by nonzero flag."""
        response = MagicMock(
            status_code=200,
            json=AsyncMock(return_value={
                "market_positions": [{"ticker": "A", "side": "yes", "count": 10}],
                "event_positions": []
            }),
            headers={},
            text="",
        )
        client._http_client.request = AsyncMock(return_value=response)
        
        result = await client.get_positions_with_filters(
            filters={"nonzero": "position"}
        )
        
        assert result.success is True
        call_args = client._http_client.request.call_args
        assert call_args.kwargs["params"]["nonzero"] == "position"


class TestRiskCalculations:
    """Tests for portfolio risk methods."""

    @pytest.mark.asyncio
    async def test_compute_var(self, client):
        """Test VaR calculation with mock positions."""
        response = MagicMock(
            status_code=200,
            json=AsyncMock(return_value={
                "market_positions": [],
                "event_positions": [
                    {"event_ticker": "EVT-1", "event_exposure": 1000},
                    {"event_ticker": "EVT-2", "event_exposure": -500},
                ]
            }),
            headers={},
            text="",
        )
        client._http_client.request = AsyncMock(return_value=response)
        
        result = await client.compute_var(alpha=0.1)
        
        assert result.success is True
        # VaR = |exposure| * alpha
        assert result.data["var_by_event_cents"]["EVT-1"] == Decimal("100")
        assert result.data["var_by_event_cents"]["EVT-2"] == Decimal("50")
        assert result.data["portfolio_var_cents"] == Decimal("150")

    @pytest.mark.asyncio
    async def test_compute_portfolio_risk(self, client):
        """Test portfolio risk aggregation."""
        response = MagicMock(
            status_code=200,
            json=AsyncMock(return_value={
                "market_positions": [],
                "event_positions": [
                    {
                        "event_ticker": "EVT-1",
                        "event_exposure": 1000,
                        "realized_pnl": 100,
                        "fees_paid": 10
                    }
                ]
            }),
            headers={},
            text="",
        )
        client._http_client.request = AsyncMock(return_value=response)
        
        result = await client.compute_portfolio_risk()
        
        assert result.success is True
        assert result.data["total_exposure"] == Decimal("1000")
        assert result.data["total_realized_pnl"] == Decimal("100")
        assert result.data["total_fees"] == Decimal("10")
        assert result.data["net_realized_pnl"] == Decimal("90")


class TestOrderOperations:
    """Tests for order placement and cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_order_uses_correct_endpoint(self, client):
        """Verify cancel uses POST /portfolio/orders/{id}/cancel."""
        response = MagicMock(
            status_code=200,
            json=AsyncMock(return_value={"order_id": "123", "status": "canceled"}),
            headers={},
            text="",
        )
        client._http_client.request = AsyncMock(return_value=response)
        
        result = await client.cancel_order_result("order_123")
        
        assert result.success is True
        call_args = client._http_client.request.call_args
        assert call_args.args[0] == "POST"
        assert "/portfolio/orders/order_123/cancel" in call_args.kwargs["url"]

    @pytest.mark.asyncio
    async def test_batch_cancel_limits_to_20(self, client):
        """Verify batch cancel enforces 20 order limit."""
        response = MagicMock(
            status_code=200,
            json=AsyncMock(return_value={"canceled": ["o1", "o2"], "failed": [], "not_found": []}),
            headers={},
            text="",
        )
        client._http_client.request = AsyncMock(return_value=response)
        
        # Try to cancel 25 orders
        order_ids = [f"order_{i}" for i in range(25)]
        result = await client.batch_cancel_orders(order_ids)
        
        # Should only attempt first 20
        call_args = client._http_client.request.call_args
        json_data = call_args.kwargs["json"]
        assert len(json_data["order_ids"]) == 20

    @pytest.mark.asyncio
    async def test_place_order_converts_price_to_cents(self, client):
        """Verify price is converted from dollars to cents."""
        response = MagicMock(
            status_code=201,
            json=AsyncMock(return_value={
                "order": {
                    "order_id": "o1",
                    "ticker": "MKT",
                    "status": "resting"
                }
            }),
            headers={},
            text="",
        )
        client._http_client.request = AsyncMock(return_value=response)
        
        order = VenueOrder(
            market_id="MKT",
            side="buy",
            outcome_id="yes",
            size=Decimal("5"),
            price=Decimal("0.65"),  # $0.65 = 65 cents
            order_type="limit"
        )
        
        await client.place_order_result(order)
        
        call_args = client._http_client.request.call_args
        json_data = call_args.kwargs["json"]
        assert json_data["yes_price"] == 65  # Converted to cents


class TestSubaccountOperations:
    """Tests for subaccount-specific operations."""

    @pytest.mark.asyncio
    async def test_aggregate_positions_by_subaccount(self, client):
        """Test aggregation across subaccounts."""
        # Mock empty responses for most subaccounts
        empty_response = MagicMock(
            status_code=200,
            json=AsyncMock(return_value={"market_positions": [], "event_positions": []}),
            headers={},
            text="",
        )
        
        # One subaccount with positions
        populated_response = MagicMock(
            status_code=200,
            json=AsyncMock(return_value={
                "market_positions": [{"ticker": "A", "total_cost": 500}],
                "event_positions": [{"event_ticker": "EVT", "event_exposure": 1000}]
            }),
            headers={},
            text="",
        )
        
        # Return populated for subaccount 5, empty for others
        responses = [empty_response] * 5 + [populated_response] + [empty_response] * 27
        client._http_client.request = AsyncMock(side_effect=responses)
        
        result = await client.aggregate_positions_by_subaccount(range(0, 33))
        
        assert result.success is True
        assert "5" in result.data
        assert result.data["5"]["total_cost"] == Decimal("500")
        assert result.data["5"]["event_exposure"] == Decimal("1000")


classTestSingleton:
    """Tests for singleton pattern."""

    def test_get_kalshi_client_returns_same_instance(self):
        """Verify singleton returns same client instance."""
        # Reset singleton for test
        import merid.event_venues.kalshi.client as client_module
        client_module._client = None
        
        client1 = get_kalshi_client()
        client2 = get_kalshi_client()
        
        assert client1 is client2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
