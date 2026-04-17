"""HTTP mocking utilities for MERID integration tests."""

import pytest
import respx
from httpx import Response
import asyncio
from typing import Dict, Any, List


class BrokerAPIMocks:
    """Mock configurations for broker APIs."""
    
    @staticmethod
    @respx.mock
    def mock_alpaca_account(mock_router):
        """Mock Alpaca account endpoint."""
        mock_router.get("https://paper-api.alpaca.markets/v2/account").mock(
            return_value=Response(
                200,
                json={
                    "id": "acc_123",
                    "account_number": "PA12345678",
                    "status": "ACTIVE",
                    "currency": "USD",
                    "cash": "100000.00",
                    "portfolio_value": "125000.00",
                    "buying_power": "200000.00"
                }
            )
        )
    
    @staticmethod
    @respx.mock
    def mock_alpaca_order(mock_router, order_id: str = "order_123"):
        """Mock Alpaca order submission."""
        mock_router.post("https://paper-api.alpaca.markets/v2/orders").mock(
            return_value=Response(
                200,
                json={
                    "id": order_id,
                    "client_order_id": f"client_{order_id}",
                    "symbol": "AAPL",
                    "qty": "10",
                    "side": "buy",
                    "type": "market",
                    "status": "accepted",
                    "created_at": "2024-01-15T10:30:00Z"
                }
            )
        )
    
    @staticmethod
    @respx.mock
    def mock_kalshi_markets(mock_router):
        """Mock Kalshi markets endpoint."""
        mock_router.get("https://trading-api.kalshi.com/markets").mock(
            return_value=Response(
                200,
                json={
                    "markets": [
                        {
                            "id": "KXBTCDEC24",
                            "ticker": "BTC-24DEC24",
                            "title": "Bitcoin price prediction",
                            "status": "active",
                            "yes_bid": 0.65,
                            "yes_ask": 0.67
                        }
                    ],
                    "cursor": "next_page"
                }
            )
        )
    
    @staticmethod
    @respx.mock  
    def mock_kalshi_order(mock_router, order_id: str = "ord_12345"):
        """Mock Kalshi order placement."""
        mock_router.post("https://trading-api.kalshi.com/orders").mock(
            return_value=Response(
                201,
                json={
                    "order_id": order_id,
                    "status": "resting",
                    "ticker": "BTC-24DEC24",
                    "side": "yes",
                    "count": 10,
                    "price": 0.65,
                    "created_time": "2024-01-15T10:30:00Z"
                }
            )
        )


@pytest.fixture
def alpaca_mocks():
    """Fixture providing Alpaca API mocks."""
    with respx.mock(assert_all_mocked=False) as respx_mock:
        BrokerAPIMocks.mock_alpaca_account(respx_mock)
        BrokerAPIMocks.mock_alpaca_order(respx_mock)
        yield respx_mock


@pytest.fixture
def kalshi_mocks():
    """Fixture providing Kalshi API mocks."""
    with respx.mock(assert_all_mocked=False) as respx_mock:
        BrokerAPIMocks.mock_kalshi_markets(respx_mock)
        BrokerAPIMocks.mock_kalshi_order(respx_mock)
        yield respx_mock


class TestHTTPMocks:
    """Example tests using HTTP mocks."""
    
    @pytest.mark.asyncio
    async def test_alpaca_client_with_mock(self, alpaca_mocks):
        """Test Alpaca client uses mocked endpoints."""
        import httpx
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://paper-api.alpaca.markets/v2/account",
                headers={"APCA-API-KEY-ID": "test", "APCA-API-SECRET-KEY": "test"}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ACTIVE"
            assert float(data["cash"]) == 100000.00
    
    @pytest.mark.asyncio
    async def test_kalshi_client_with_mock(self, kalshi_mocks):
        """Test Kalshi client uses mocked endpoints."""
        import httpx
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://trading-api.kalshi.com/markets",
                params={"status": "active"}
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["markets"]) == 1
            assert data["markets"][0]["ticker"] == "BTC-24DEC24"


# Retry testing with tenacity
class TestRetryBehavior:
    """Test retry logic with mocked failures."""
    
    @pytest.mark.asyncio
    @respx.mock
    async def test_retry_on_500_error(self):
        """Test that client retries on 500 errors."""
        from tenacity import retry, stop_after_attempt, wait_exponential
        
        call_count = 0
        
        @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=0.1, max=1))
        async def make_request():
            nonlocal call_count
            call_count += 1
            
            async with httpx.AsyncClient() as client:
                response = await client.get("https://api.example.com/data")
                response.raise_for_status()
                return response.json()
        
        # Mock to fail twice, then succeed
        route = respx.get("https://api.example.com/data")
        route.side_effect = [
            Response(500, json={"error": "Internal Server Error"}),
            Response(500, json={"error": "Internal Server Error"}),
            Response(200, json={"data": "success"})
        ]
        
        result = await make_request()
        
        assert result["data"] == "success"
        assert call_count == 3  # Two failures + one success
