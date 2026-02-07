"""Comprehensive tests for merid/execution/executors/kalshi.py."""

import pytest
import respx
from httpx import Response

from merid.execution.executors.kalshi import KalshiExecutor
from merid.execution.base import Quote, TradeResult, Position


class TestKalshiExecutorInitialization:
    """Test KalshiExecutor initialization."""

    def test_default_initialization(self):
        """Test initialization with default values."""
        executor = KalshiExecutor()
        assert executor.venue == "kalshi"
        assert executor.base_url == "https://api.elections.kalshi.com"
        assert executor.default_timeout == 10.0

    def test_custom_api_url_from_env(self, monkeypatch):
        """Test custom API URL can be overridden via class attribute."""
        # base_url is a class attribute evaluated at import time, so patch the class
        monkeypatch.setattr(KalshiExecutor, "base_url", "https://test.kalshi.com")
        executor = KalshiExecutor()
        assert executor.base_url == "https://test.kalshi.com"

    def test_credentials_from_env(self, monkeypatch):
        """Test credentials loaded from environment."""
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key_id")
        monkeypatch.setenv("KALSHI_PRIVATE_KEY_PEM", "test_pem")
        
        executor = KalshiExecutor()
        assert executor.api_key_id == "test_key_id"
        assert executor.private_key_pem == "test_pem"


class TestKalshiExecutorAuthHeaders:
    """Test KalshiExecutor authentication headers."""

    def test_get_auth_headers_with_credentials(self, monkeypatch):
        """Test auth headers with credentials."""
        monkeypatch.setenv("KALSHI_API_KEY_ID", "my_key_id")
        executor = KalshiExecutor()
        
        headers = executor._get_auth_headers()
        
        assert headers["KALSHI-API-KEY-ID"] == "my_key_id"

    def test_get_auth_headers_without_credentials(self, monkeypatch):
        """Test auth headers without credentials."""
        # Clear any existing credentials from environment
        monkeypatch.delenv("KALSHI_API_KEY_ID", raising=False)
        monkeypatch.delenv("KALSHI_PRIVATE_KEY_PEM", raising=False)
        
        executor = KalshiExecutor()
        
        headers = executor._get_auth_headers()
        
        assert headers["KALSHI-API-KEY-ID"] == ""


class TestKalshiExecutorSymbolConversion:
    """Test symbol/ticker conversion methods."""

    def test_symbol_to_ticker_known(self):
        """Test symbol to ticker for known mappings."""
        executor = KalshiExecutor()
        
        assert executor._symbol_to_ticker("PRES-2024-DEM") == "PRES-2024-DEM"
        assert executor._symbol_to_ticker("PRES-2024-REP") == "PRES-2024-REP"

    def test_symbol_to_ticker_unknown(self):
        """Test symbol to ticker for unknown symbol passes through."""
        executor = KalshiExecutor()
        
        assert executor._symbol_to_ticker("UNKNOWN-EVENT") == "UNKNOWN-EVENT"

    def test_ticker_to_symbol_known(self):
        """Test ticker to symbol for known mappings."""
        executor = KalshiExecutor()
        
        assert executor._ticker_to_symbol("PRES-2024-DEM") == "PRES-2024-DEM"
        assert executor._ticker_to_symbol("PRES-2024-REP") == "PRES-2024-REP"

    def test_ticker_to_symbol_unknown(self):
        """Test ticker to symbol for unknown ticker passes through."""
        executor = KalshiExecutor()
        
        assert executor._ticker_to_symbol("UNKNOWN-TICKER") == "UNKNOWN-TICKER"


class TestKalshiExecutorGetQuote:
    """Test KalshiExecutor get_quote method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_quote_success(self):
        """Test successful quote retrieval."""
        executor = KalshiExecutor()
        
        route = respx.get("https://api.elections.kalshi.com/trade/v1/price").mock(
            return_value=Response(200, json={"price": "0.65"})
        )
        
        quote = await executor.get_quote("PRES-2024-DEM", "buy", 10.0)
        
        assert isinstance(quote, Quote)
        assert quote.symbol == "PRES-2024-DEM"
        assert quote.side == "buy"
        assert quote.price == 0.65
        assert quote.venue == "kalshi"
        assert quote.size == 10.0
        assert quote.metadata["ticker"] == "PRES-2024-DEM"
        assert route.called
        
        # Verify query params
        request = route.calls[0].request
        params = str(request.url.params)
        assert "ticker=PRES-2024-DEM" in params
        assert "side=buy" in params
        assert "count=10" in params

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_quote_sell_side(self):
        """Test getting quote for sell side."""
        executor = KalshiExecutor()
        
        route = respx.get("https://api.elections.kalshi.com/trade/v1/price").mock(
            return_value=Response(200, json={"price": "0.35"})
        )
        
        quote = await executor.get_quote("PRES-2024-REP", "sell", 5.0)
        
        assert quote.side == "sell"
        assert quote.price == 0.35


class TestKalshiExecutorExecuteTrade:
    """Test KalshiExecutor execute_trade method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_market_order_success(self, monkeypatch):
        """Test successful market order execution."""
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        executor = KalshiExecutor()
        
        route = respx.post("https://api.elections.kalshi.com/trade/v1/order").mock(
            return_value=Response(200, json={
                "order_id": "order_123",
                "executed_price": "0.65"
            })
        )
        
        result = await executor.execute_trade(
            symbol="PRES-2024-DEM",
            side="buy",
            amount=10.0,
            order_type="market"
        )
        
        assert isinstance(result, TradeResult)
        assert result.success is True
        assert result.venue == "kalshi"
        assert result.symbol == "PRES-2024-DEM"
        assert result.side == "buy"
        assert result.size == 10.0
        assert result.price == 0.65
        assert result.tx_id == "order_123"
        assert route.called
        
        # Verify request payload
        request = route.calls[0].request
        import json
        payload = json.loads(request.content)
        assert payload["ticker"] == "PRES-2024-DEM"
        assert payload["side"] == "buy"
        assert payload["count"] == 10
        assert payload["client_order_id"].startswith("merid_")

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_limit_order_success(self, monkeypatch):
        """Test successful limit order execution."""
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        executor = KalshiExecutor()
        
        route = respx.post("https://api.elections.kalshi.com/trade/v1/order").mock(
            return_value=Response(200, json={
                "order_id": "order_456",
                "executed_price": "0.60"
            })
        )
        
        result = await executor.execute_trade(
            symbol="PRES-2024-REP",
            side="sell",
            amount=5.0,
            order_type="limit",
            price=0.60
        )
        
        assert result.success is True
        assert result.price == 0.60
        
        # Verify price in payload (Kalshi executor adds price for limit orders, not order_type)
        request = route.calls[0].request
        import json
        payload = json.loads(request.content)
        assert payload["price"] == 0.60
        assert payload["ticker"] == "PRES-2024-REP"
        assert payload["side"] == "sell"

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_trade_api_error(self, monkeypatch):
        """Test trade execution with API error."""
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        executor = KalshiExecutor()
        
        route = respx.post("https://api.elections.kalshi.com/trade/v1/order").mock(
            return_value=Response(400, json={"message": "Invalid order"})
        )
        
        result = await executor.execute_trade(
            symbol="PRES-2024-DEM",
            side="buy",
            amount=10.0
        )
        
        assert result.success is False
        assert "Kalshi API error" in result.error

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_trade_network_error(self, monkeypatch):
        """Test trade execution with network error."""
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        executor = KalshiExecutor()
        
        route = respx.post("https://api.elections.kalshi.com/trade/v1/order").mock(
            side_effect=ConnectionError("Network unreachable")
        )
        
        result = await executor.execute_trade(
            symbol="PRES-2024-REP",
            side="sell",
            amount=5.0
        )
        
        assert result.success is False
        assert "Kalshi API error" in result.error

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_trade_timeout_error(self, monkeypatch):
        """Test trade execution with timeout error."""
        import asyncio
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        executor = KalshiExecutor()
        
        route = respx.post("https://api.elections.kalshi.com/trade/v1/order").mock(
            side_effect=asyncio.TimeoutError("Request timeout")
        )
        
        result = await executor.execute_trade(
            symbol="PRES-2024-DEM",
            side="buy",
            amount=10.0
        )
        
        assert result.success is False
        assert "Kalshi API error" in result.error


class TestKalshiExecutorGetPositions:
    """Test KalshiExecutor get_positions method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_success(self, monkeypatch):
        """Test successful positions retrieval."""
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        executor = KalshiExecutor()
        
        route = respx.get("https://api.elections.kalshi.com/portfolio/v1/positions").mock(
            return_value=Response(200, json={
                "positions": [
                    {
                        "ticker": "PRES-2024-DEM",
                        "count": "100",
                        "avg_price": "0.60",
                        "pnl": "5.00"
                    },
                    {
                        "ticker": "PRES-2024-REP",
                        "count": "50",
                        "avg_price": "0.40",
                        "pnl": "-2.00"
                    }
                ]
            })
        )
        
        positions = await executor.get_positions()
        
        assert len(positions) == 2
        
        # First position
        assert positions[0].symbol == "PRES-2024-DEM"
        assert positions[0].size == 100.0
        assert positions[0].entry_price == 0.60
        assert positions[0].pnl == 5.00
        assert positions[0].venue == "kalshi"
        assert positions[0].metadata["ticker"] == "PRES-2024-DEM"
        
        # Second position
        assert positions[1].symbol == "PRES-2024-REP"
        assert positions[1].size == 50.0
        assert positions[1].pnl == -2.00
        
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_empty(self, monkeypatch):
        """Test empty positions list."""
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        executor = KalshiExecutor()
        
        route = respx.get("https://api.elections.kalshi.com/portfolio/v1/positions").mock(
            return_value=Response(200, json={"positions": []})
        )
        
        positions = await executor.get_positions()
        
        assert positions == []

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_missing_optional_fields(self, monkeypatch):
        """Test positions retrieval with missing optional fields."""
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        executor = KalshiExecutor()
        
        route = respx.get("https://api.elections.kalshi.com/portfolio/v1/positions").mock(
            return_value=Response(200, json={
                "positions": [
                    {
                        "ticker": "PRES-2024-DEM",
                        "count": "25"
                        # Missing avg_price and pnl
                    }
                ]
            })
        )
        
        positions = await executor.get_positions()
        
        assert len(positions) == 1
        assert positions[0].symbol == "PRES-2024-DEM"
        assert positions[0].size == 25.0
        assert positions[0].entry_price == 0.0  # Default
        assert positions[0].pnl == 0.0  # Default

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_api_error(self, monkeypatch):
        """Test positions retrieval with API error."""
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        executor = KalshiExecutor()
        
        route = respx.get("https://api.elections.kalshi.com/portfolio/v1/positions").mock(
            return_value=Response(401, json={"error": "Unauthorized"})
        )
        
        with pytest.raises(Exception):
            await executor.get_positions()
