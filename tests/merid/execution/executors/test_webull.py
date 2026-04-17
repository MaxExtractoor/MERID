"""Comprehensive tests for merid/execution/executors/webull.py."""

import pytest
import respx
from httpx import Response

from merid.execution.executors.webull import WebullExecutor
from merid.execution.base import Quote, TradeResult, Position


class TestWebullExecutorInitialization:
    """Test WebullExecutor initialization."""

    def test_default_initialization(self):
        """Test initialization with default values."""
        executor = WebullExecutor()
        assert executor.venue == "webull"
        assert executor.base_url == "https://api.webull.com"
        assert executor.default_timeout == 10.0
        assert executor._access_token is None

    def test_custom_api_url_from_env(self, monkeypatch):
        """Test custom API URL can be overridden via class attribute."""
        # base_url is a class attribute evaluated at import time, so patch the class
        monkeypatch.setattr(WebullExecutor, "base_url", "https://test.webull.com")
        executor = WebullExecutor()
        assert executor.base_url == "https://test.webull.com"

    def test_credentials_from_env(self, monkeypatch):
        """Test credentials loaded from environment."""
        monkeypatch.setenv("WEBULL_USERNAME", "test_user")
        monkeypatch.setenv("WEBULL_PASSWORD", "test_pass")
        monkeypatch.setenv("WEBULL_DID", "test_did")
        monkeypatch.setenv("WEBULL_ACCESS_TOKEN", "test_token")
        
        executor = WebullExecutor()
        assert executor.username == "test_user"
        assert executor.password == "test_pass"
        assert executor.did == "test_did"


class TestWebullExecutorAuth:
    """Test WebullExecutor authentication."""

    @pytest.mark.asyncio
    async def test_ensure_auth_with_existing_token(self):
        """Test _ensure_auth when token already exists."""
        executor = WebullExecutor()
        executor._access_token = "existing_token"
        
        await executor._ensure_auth()
        
        assert executor._access_token == "existing_token"

    @pytest.mark.asyncio
    async def test_ensure_auth_loads_from_env(self, monkeypatch):
        """Test _ensure_auth loads token from environment."""
        monkeypatch.setenv("WEBULL_ACCESS_TOKEN", "env_token")
        executor = WebullExecutor()
        
        await executor._ensure_auth()
        
        assert executor._access_token == "env_token"

    def test_get_auth_headers_with_token(self):
        """Test auth headers with token."""
        executor = WebullExecutor()
        executor._access_token = "my_token"
        
        headers = executor._get_auth_headers()
        
        assert headers["Authorization"] == "Bearer my_token"

    def test_get_auth_headers_without_token(self):
        """Test auth headers without token."""
        executor = WebullExecutor()
        
        headers = executor._get_auth_headers()
        
        assert headers["Authorization"] == "Bearer "


class TestWebullExecutorGetQuote:
    """Test WebullExecutor get_quote method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_quote_success(self, monkeypatch):
        """Test successful quote retrieval."""
        monkeypatch.setenv("WEBULL_ACCESS_TOKEN", "test_token")
        executor = WebullExecutor()
        
        route = respx.get("https://api.webull.com/quote/realTime/AAPL").mock(
            return_value=Response(200, json={
                "latestPrice": "150.00",
                "timestamp": "1234567890"
            })
        )
        
        quote = await executor.get_quote("AAPL", "buy", 10.0)
        
        assert isinstance(quote, Quote)
        assert quote.symbol == "AAPL"
        assert quote.side == "buy"
        assert quote.price == 150.00
        assert quote.venue == "webull"
        assert quote.size == 10.0
        assert quote.metadata["timestamp"] == "1234567890"
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_quote_sell_side(self, monkeypatch):
        """Test getting quote for sell side."""
        monkeypatch.setenv("WEBULL_ACCESS_TOKEN", "test_token")
        executor = WebullExecutor()
        
        route = respx.get("https://api.webull.com/quote/realTime/TSLA").mock(
            return_value=Response(200, json={"latestPrice": "200.00"})
        )
        
        quote = await executor.get_quote("TSLA", "sell", 5.0)
        
        assert quote.side == "sell"
        assert quote.price == 200.00


class TestWebullExecutorExecuteTrade:
    """Test WebullExecutor execute_trade method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_market_order_success(self, monkeypatch):
        """Test successful market order execution."""
        monkeypatch.setenv("WEBULL_ACCESS_TOKEN", "test_token")
        executor = WebullExecutor()
        
        route = respx.post("https://api.webull.com/trade/v2/order/place").mock(
            return_value=Response(200, json={
                "orderId": "order_123",
                "avgPrice": "150.00"
            })
        )
        
        result = await executor.execute_trade(
            symbol="AAPL",
            side="buy",
            amount=10.0,
            order_type="market"
        )
        
        assert isinstance(result, TradeResult)
        assert result.success is True
        assert result.venue == "webull"
        assert result.symbol == "AAPL"
        assert result.side == "buy"
        assert result.size == 10.0
        assert result.price == 150.00
        assert result.tx_id == "order_123"
        assert route.called
        
        # Verify request payload
        request = route.calls[0].request
        import json
        payload = json.loads(request.content)
        assert payload["securityId"] == "AAPL"
        assert payload["orderType"] == "MARKET"
        assert payload["orderAction"] == "BUY"
        assert payload["totalQuantity"] == "10.0"
        assert payload["timeInForce"] == "DAY"

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_limit_order_success(self, monkeypatch):
        """Test successful limit order execution."""
        monkeypatch.setenv("WEBULL_ACCESS_TOKEN", "test_token")
        executor = WebullExecutor()
        
        route = respx.post("https://api.webull.com/trade/v2/order/place").mock(
            return_value=Response(200, json={
                "orderId": "order_456",
                "avgPrice": "145.00"
            })
        )
        
        result = await executor.execute_trade(
            symbol="AAPL",
            side="sell",
            amount=5.0,
            order_type="limit",
            price=145.00
        )
        
        assert result.success is True
        assert result.price == 145.00
        assert result.tx_id == "order_456"
        
        # Verify price in payload
        request = route.calls[0].request
        import json
        payload = json.loads(request.content)
        assert payload["orderType"] == "LIMIT"
        assert payload["orderAction"] == "SELL"
        assert payload["limitPrice"] == "145.0"

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_trade_api_error(self, monkeypatch):
        """Test trade execution with API error raises NonRetryableError."""
        from merid.execution.http_base import NonRetryableError
        
        monkeypatch.setenv("WEBULL_ACCESS_TOKEN", "test_token")
        executor = WebullExecutor()
        
        respx.post("https://api.webull.com/trade/v2/order/place").mock(
            return_value=Response(400, json={"message": "Invalid order"})
        )
        
        with pytest.raises(NonRetryableError) as exc_info:
            await executor.execute_trade(
                symbol="AAPL",
                side="buy",
                amount=10.0
            )
        
        assert "400" in str(exc_info.value)

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_trade_network_error(self, monkeypatch):
        """Test trade execution with network error raises exception."""
        monkeypatch.setenv("WEBULL_ACCESS_TOKEN", "test_token")
        executor = WebullExecutor()
        
        respx.post("https://api.webull.com/trade/v2/order/place").mock(
            side_effect=ConnectionError("Network unreachable")
        )
        
        from merid.execution.http_base import ExecutionError
        with pytest.raises(ExecutionError) as exc_info:
            await executor.execute_trade(
                symbol="TSLA",
                side="sell",
                amount=5.0
            )
        
        assert "Network unreachable" in str(exc_info.value)


class TestWebullExecutorGetPositions:
    """Test WebullExecutor get_positions method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_success(self, monkeypatch):
        """Test successful positions retrieval."""
        monkeypatch.setenv("WEBULL_ACCESS_TOKEN", "test_token")
        executor = WebullExecutor()
        
        route = respx.get("https://api.webull.com/account/v5/positions").mock(
            return_value=Response(200, json={
                "positions": [
                    {
                        "tickerSymbol": "AAPL",
                        "securityId": "913256135",
                        "position": "100",
                        "avgPrice": "140.00",
                        "unrealizedPnl": "1000.00"
                    },
                    {
                        "tickerSymbol": "TSLA",
                        "securityId": "913254513",
                        "position": "50",
                        "avgPrice": "180.00",
                        "unrealizedPnl": "500.00"
                    }
                ]
            })
        )
        
        positions = await executor.get_positions()
        
        assert len(positions) == 2
        
        # First position
        assert positions[0].symbol == "AAPL"
        assert positions[0].size == 100.0
        assert positions[0].entry_price == 140.00
        assert positions[0].pnl == 1000.00
        assert positions[0].venue == "webull"
        assert positions[0].metadata["security_id"] == "913256135"
        
        # Second position
        assert positions[1].symbol == "TSLA"
        assert positions[1].size == 50.0
        assert positions[1].metadata["security_id"] == "913254513"
        
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_empty(self, monkeypatch):
        """Test positions retrieval with empty positions."""
        monkeypatch.setenv("WEBULL_ACCESS_TOKEN", "test_token")
        executor = WebullExecutor()
        
        route = respx.get("https://api.webull.com/account/v5/positions").mock(
            return_value=Response(200, json={"positions": []})
        )
        
        positions = await executor.get_positions()
        
        assert positions == []

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_missing_optional_fields(self, monkeypatch):
        """Test positions retrieval with missing optional fields."""
        monkeypatch.setenv("WEBULL_ACCESS_TOKEN", "test_token")
        executor = WebullExecutor()
        
        route = respx.get("https://api.webull.com/account/v5/positions").mock(
            return_value=Response(200, json={
                "positions": [
                    {
                        "tickerSymbol": "AAPL",
                        "securityId": "913256135",
                        "position": "25"
                        # Missing avgPrice and unrealizedPnl
                    }
                ]
            })
        )
        
        positions = await executor.get_positions()
        
        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"
        assert positions[0].size == 25.0
        assert positions[0].entry_price == 0.0  # Default
        assert positions[0].pnl == 0.0  # Default

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_api_error(self, monkeypatch):
        """Test positions retrieval with API error."""
        monkeypatch.setenv("WEBULL_ACCESS_TOKEN", "test_token")
        executor = WebullExecutor()
        
        route = respx.get("https://api.webull.com/account/v5/positions").mock(
            return_value=Response(401, json={"error": "Unauthorized"})
        )
        
        with pytest.raises(Exception):
            await executor.get_positions()
