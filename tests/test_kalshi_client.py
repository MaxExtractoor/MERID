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

pytestmark = pytest.mark.kalshi_15m

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
from merid.event_venues.kalshi.kalshi_config import KalshiConfig
from merid.resilience import OperationResult


@pytest_asyncio.fixture
async def client():
    """Create a test client with mocked auth."""
    config = KalshiConfig(
        env="prod",
        rest_base_url="https://external-api.kalshi.com/trade-api/v2",
        ws_base_url="wss://external-api-ws.kalshi.com/trade-api/ws/v2",
        api_key_id="test_key_12345",
        private_key_path="/path/to/key.pem",
        public_rest_api_url="https://api.kalshi.com/public-api/v2",
        private_key_pem="""-----BEGIN RSA PRIVATE KEY-----
MIICXgIBAAJBAL8U2zCkGqM3mLwP+5F1z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9
z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z0CAwEAAQJBAKjM3mLw
P+5F1z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F
9z9F9z9F9z9F9z9F9z9F9z0CIQDP8U2zCkGqM3mLwP+5F1z9F9z9F9z9F9z9F9z9
F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z0IfwIX
AAL8U2zCkGqM3mLwP+5F1z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9
z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z0=
-----END RSA PRIVATE KEY-----""",
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

    @pytest.mark.asyncio
    async def test_event_loop_closure_protection(self, client):
        """Request should fail gracefully when event loop is closed."""
        # Simulate event loop closure by mocking get_running_loop to return a closed loop
        import asyncio
        from unittest.mock import patch
        
        closed_loop = asyncio.new_event_loop()
        closed_loop.close()  # Close the loop
        
        with patch('asyncio.get_running_loop', return_value=closed_loop):
            result = await client._request_with_resilience(
                "GET", "/markets", operation_name="test_closed_loop"
            )
        
        # Should fail with event loop closed error, not attempt HTTP request
        assert result.success is False
        assert "Event loop is closed" in str(result.error)
        assert result.metadata.get("status_code") is None


class TestPagination:
    """Tests for cursor-based pagination."""

    @pytest.mark.asyncio
    async def test_list_markets_pagination(self, fake_public_client):
        """Test that list_open_markets_for_series follows cursors correctly."""
        client, fake_http = fake_public_client
        
        # Use future timestamps to pass freshness filter (default 2 hours ago)
        import time
        now = int(time.time())
        future_base = now + 3600  # 1 hour in the future
        
        # Configure fake HTTP with paginated responses
        fake_http.pages = [
            {
                "markets": [
                    {"ticker": f"KXBTC15M-{i}", "series_ticker": "KXBTC15M", "close_ts": future_base + i * 60}
                    for i in range(5)
                ],
                "cursor": "cursor_1"
            },
            {
                "markets": [
                    {"ticker": f"KXBTC15M-{i+5}", "series_ticker": "KXBTC15M", "close_ts": future_base + (i+5) * 60}
                    for i in range(5)
                ],
                "cursor": None  # End of pagination
            },
        ]
        
        # Call list_open_markets_for_series
        result = await client.list_open_markets_for_series(series_ticker="KXBTC15M")
        
        # Assert pagination worked correctly
        assert len(result) == 10
        assert fake_http._call_count == 2  # Made 2 calls for 2 pages
        
        # Verify the correct endpoint was called with correct params
        assert len(fake_http.calls) == 2
        url, params, _ = fake_http.calls[0]
        assert "/markets" in url
        assert params.get("series_ticker") == "KXBTC15M"
        # client_public.py uses min_close_ts instead of status for filtering
        assert "min_close_ts" in params

    @pytest.mark.asyncio
    async def test_get_positions_pagination(self, client):
        """Test positions pagination. Event positions are aggregates, not market positions."""
        responses = [
            MagicMock(
                status_code=200,
                json=MagicMock(return_value={
                    "market_positions": [
                        {"ticker": "A", "side": "yes", "count": 10, "avg_price": 50}
                    ],
                    "event_positions": [
                        # Aggregate event exposure must not be returned as a VenuePosition.
                        {"event_ticker": "EVT-1", "event_exposure": 100}
                    ],
                    "cursor": "cursor_1"
                }),
                headers={},
                text="",
            ),
            MagicMock(
                status_code=200,
                json=MagicMock(return_value={
                    "market_positions": [
                        {"ticker": "B", "side": "no", "count": 5, "avg_price": 30}
                    ],
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
        assert len(result.data) == 2  # 2 market positions (event position ignored)
        assert result.data[0].market_id == "A"
        assert result.data[1].market_id == "B"


class TestFilters:
    """Tests for API filtering."""

    @pytest.mark.asyncio
    async def test_list_markets_with_event_ticker_filter(self, fake_public_client):
        """Test series_ticker filter is passed correctly to public API."""
        client, fake_http = fake_public_client
        
        # Use future timestamp to pass freshness filter (default 2 hours ago)
        import time
        now = int(time.time())
        future_ts = now + 3600  # 1 hour in the future
        
        # Configure fake HTTP with filtered response
        fake_http.pages = [
            {
                "markets": [
                    {
                        "ticker": "KXBTC15M-001",
                        "series_ticker": "KXBTC15M",
                        "close_ts": future_ts
                    }
                ],
                "cursor": None
            }
        ]
        
        # Call list_open_markets_for_series with series_ticker filter
        result = await client.list_open_markets_for_series(series_ticker="KXBTC15M")
        
        # Assert correct series_ticker was passed
        assert len(result) == 1
        assert len(fake_http.calls) == 1
        url, params, _ = fake_http.calls[0]
        assert "/markets" in url
        assert params.get("series_ticker") == "KXBTC15M"
        # client_public.py uses min_close_ts instead of status for filtering
        assert "min_close_ts" in params

    @pytest.mark.asyncio
    async def test_get_positions_with_filters(self, client):
        """Test position filtering by nonzero flag."""
        response = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
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
            json=MagicMock(return_value={
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
            json=MagicMock(return_value={
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
        # Mock get_order_result to return an active order (not already canceled)
        order_response = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "order": {
                    "order_id": "order_123",
                    "status": "resting"
                }
            }),
            headers={},
            text="",
        )
        # Mock cancel endpoint response
        cancel_response = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"order_id": "123", "status": "canceled"}),
            headers={},
            text="",
        )
        client._http_client.request = AsyncMock(side_effect=[order_response, cancel_response])
        
        result = await client.cancel_order_result("order_123")
        
        assert result.success is True
        # Should have made 2 calls: GET for status check, POST for cancel
        assert client._http_client.request.call_count == 2
        # Second call should be POST to cancel endpoint
        cancel_call = client._http_client.request.call_args_list[1]
        assert cancel_call.kwargs["method"] == "POST"
        assert "/portfolio/orders/order_123/cancel" in cancel_call.kwargs["url"]

    @pytest.mark.asyncio
    async def test_batch_cancel_limits_to_20(self, client):
        """Verify batch cancel enforces 20 order limit."""
        response = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"canceled": ["o1", "o2"], "failed": [], "not_found": []}),
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
        # Enable manual orders for testing
        import os
        os.environ["DEBUG_ALLOW_MANUAL_ORDERS"] = "true"

        response = MagicMock(
            status_code=201,
            json=MagicMock(return_value={
                "order": {
                    "order_id": "o1",
                    "ticker": "KXBTC15M-001",
                    "status": "resting"
                }
            }),
            headers={},
            text="",
        )
        client._http_client.request = AsyncMock(return_value=response)

        order = VenueOrder(
            market_id="KXBTC15M-001",  # Valid Kalshi ticker format
            side="buy",
            outcome_id="yes",
            size=Decimal("5"),
            price=Decimal("0.65"),  # $0.65 = 65 cents
            order_type="limit"
        )

        await client.place_order_result(order)

        call_args = client._http_client.request.call_args
        json_data = call_args.kwargs["json"]
        # Kalshi V2 API uses "price" field as string in fixed-point dollars (e.g., "0.6500")
        assert json_data["price"] == "0.6500"  # Converted to dollars with 4 decimal places

    @pytest.mark.parametrize(
        "side,outcome_id,expected_book_side,expected_yes_price",
        [
            ("buy", "yes", "bid", "0.6500"),   # BUY_YES  -> bid, YES price
            ("sell", "yes", "ask", "0.6500"),  # SELL_YES -> ask, YES price
            ("buy", "no", "ask", "0.3500"),    # BUY_NO   -> ask, YES price = 1 - NO price
            ("sell", "no", "bid", "0.3500"),   # SELL_NO  -> bid, YES price = 1 - NO price
        ],
    )
    @pytest.mark.asyncio
    async def test_place_order_v2_wire_mapping(
        self, client, side, outcome_id, expected_book_side, expected_yes_price
    ):
        """V2 CreateOrderV2Request uses BookSide only; no deprecated action/outcome fields."""
        import os
        os.environ["DEBUG_ALLOW_MANUAL_ORDERS"] = "true"

        response = MagicMock(
            status_code=201,
            json=MagicMock(return_value={"order": {"order_id": "o1", "ticker": "KXBTC15M-001", "status": "resting"}}),
            headers={},
            text="",
        )
        client._http_client.request = AsyncMock(return_value=response)

        order = VenueOrder(
            market_id="KXBTC15M-001",
            side=side,
            outcome_id=outcome_id,
            size=Decimal("1"),
            price=Decimal("0.65"),  # internal NO-space price for NO orders
            order_type="limit",
        )

        await client.place_order_result(order)

        json_data = client._http_client.request.call_args.kwargs["json"]

        # V2 direction is carried exclusively by BookSide (bid/ask).
        assert json_data["side"] == expected_book_side
        # Legacy V1 action/side/outcome fields must not leak into the V2 wire.
        assert "action" not in json_data
        # Price is always in YES-space dollars.
        assert json_data["price"] == expected_yes_price

    @pytest.mark.parametrize(
        "side,outcome_id,expected_action,expected_side,expected_price_field,expected_price",
        [
            ("buy", "yes", "buy", "yes", "yes_price_dollars", "0.6500"),
            ("sell", "yes", "sell", "yes", "yes_price_dollars", "0.6500"),
            ("buy", "no", "buy", "no", "no_price_dollars", "0.6500"),
            ("sell", "no", "sell", "no", "no_price_dollars", "0.6500"),
        ],
    )
    @pytest.mark.asyncio
    async def test_place_order_legacy_v1_wire_mapping(
        self,
        client,
        monkeypatch,
        side,
        outcome_id,
        expected_action,
        expected_side,
        expected_price_field,
        expected_price,
    ):
        """Legacy V1 CreateOrderRequest preserves user action/side and side-space price."""
        monkeypatch.setenv("DEBUG_ALLOW_MANUAL_ORDERS", "true")
        monkeypatch.setenv("KALSHI_ORDER_API_VERSION", "legacy")

        response = MagicMock(
            status_code=201,
            json=MagicMock(
                return_value={
                    "order": {
                        "order_id": "o1",
                        "ticker": "KXBTC15M-001",
                        "status": "resting",
                        "action": expected_action,
                        "side": expected_side,
                        expected_price_field: expected_price,
                        "initial_count_fp": "1.00",
                    }
                }
            ),
            headers={},
            text="",
        )
        client._http_client.request = AsyncMock(return_value=response)

        order = VenueOrder(
            market_id="KXBTC15M-001",
            side=side,
            outcome_id=outcome_id,
            size=Decimal("1"),
            price=Decimal("0.65"),  # internal side-space price (NO-space for NO orders)
            order_type="limit",
        )

        result = await client.place_order_result(order)

        call_args = client._http_client.request.call_args
        assert call_args.kwargs["method"] == "POST"
        assert "/portfolio/orders" in call_args.kwargs["url"]

        json_data = call_args.kwargs["json"]

        # V1 direction is explicit action + side.
        assert json_data["action"] == expected_action
        assert json_data["side"] == expected_side
        # V2 single-book "price"/"book_side" fields must not leak into V1 wire.
        assert "price" not in json_data
        assert "book_side" not in json_data
        # Price stays in the order's own side-space (no V2 YES-space inversion).
        assert json_data[expected_price_field] == expected_price

        # PlacedOrder should preserve the user's action and parse the price.
        assert result.success is True
        assert result.data is not None
        assert result.data.side == expected_action
        assert result.data.price == Decimal(expected_price)

    @pytest.mark.asyncio
    async def test_place_order_v2_reduce_only_wire(self, client):
        """Exit orders must set reduce_only=True on the V2 wire."""
        import os
        os.environ["DEBUG_ALLOW_MANUAL_ORDERS"] = "true"

        response = MagicMock(
            status_code=201,
            json=MagicMock(return_value={"order": {"order_id": "o1", "ticker": "KXBTC15M-001", "status": "resting"}}),
            headers={},
            text="",
        )
        client._http_client.request = AsyncMock(return_value=response)

        order = VenueOrder(
            market_id="KXBTC15M-001",
            side="sell",
            outcome_id="no",
            size=Decimal("1"),
            price=Decimal("0.81"),
            order_type="limit",
            reduce_only=True,
        )

        await client.place_order_result(order)

        json_data = client._http_client.request.call_args.kwargs["json"]
        assert json_data["reduce_only"] is True


class TestSubaccountOperations:
    """Tests for subaccount-specific operations."""

    @pytest.mark.asyncio
    async def test_aggregate_positions_by_subaccount(self, client):
        """Test aggregation across subaccounts."""
        # Mock empty responses for most subaccounts
        empty_response = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"market_positions": [], "event_positions": []}),
            headers={},
            text="",
        )
        
        # One subaccount with positions
        populated_response = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
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


class TestSingleton:
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
