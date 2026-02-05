"""Tests for merid/execution/executors/alpaca.py."""
import pytest
import respx
from httpx import Response

from merid.execution.executors.alpaca import AlpacaExecutor
from merid.execution.base import Quote, TradeResult, Position


class TestAlpacaExecutorInitialization:
    """Test AlpacaExecutor initialization."""

    def test_default_initialization(self):
        """Test initialization with default values."""
        executor = AlpacaExecutor()
        assert executor.venue == "alpaca"
        assert executor.base_url == "https://paper-api.alpaca.markets"
        assert executor.default_timeout == 10.0

    def test_custom_url_from_env(self, monkeypatch):
        """Test custom API URL can be overridden via class attribute."""
        # base_url is a class attribute evaluated at import time, so patch the class
        monkeypatch.setattr(AlpacaExecutor, "base_url", "https://live-api.alpaca.markets")
        executor = AlpacaExecutor()
        assert executor.base_url == "https://live-api.alpaca.markets"

    def test_api_credentials_from_env(self, monkeypatch):
        """Test API credentials loaded from environment."""
        monkeypatch.setenv("ALPACA_API_KEY", "test_key")
        monkeypatch.setenv("ALPACA_API_SECRET", "test_secret")
        executor = AlpacaExecutor()
        assert executor.api_key == "test_key"
        assert executor.api_secret == "test_secret"


class TestAlpacaExecutorAuthHeaders:
    """Test AlpacaExecutor authentication headers."""

    def test_get_auth_headers(self, monkeypatch):
        """Test auth headers include API credentials."""
        monkeypatch.setenv("ALPACA_API_KEY", "test_key")
        monkeypatch.setenv("ALPACA_API_SECRET", "test_secret")
        executor = AlpacaExecutor()
        
        headers = executor._get_auth_headers()
        
        assert headers["APCA-API-KEY-ID"] == "test_key"
        assert headers["APCA-API-SECRET-KEY"] == "test_secret"


class TestAlpacaExecutorGetQuote:
    """Test AlpacaExecutor get_quote method."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_quote_buy(self):
        """Test successful buy quote retrieval."""
        executor = AlpacaExecutor()
        
        # Mock the API response
        route = respx.get("https://paper-api.alpaca.markets/v2/stocks/AAPL/quotes/latest").mock(
            return_value=Response(200, json={
                "quote": {
                    "ap": "150.00",  # ask price
                    "bp": "149.50"   # bid price
                }
            })
        )
        
        quote = await executor.get_quote("AAPL", "buy", 100.0)
        
        assert isinstance(quote, Quote)
        assert quote.symbol == "AAPL"
        assert quote.side == "buy"
        assert quote.price == 150.00  # ask price for buy
        assert quote.venue == "alpaca"
        assert quote.size == 100.0
        assert quote.metadata["ask"] == "150.00"
        assert quote.metadata["bid"] == "149.50"
        assert route.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_quote_sell(self):
        """Test successful sell quote retrieval."""
        executor = AlpacaExecutor()
        
        respx.get("https://paper-api.alpaca.markets/v2/stocks/TSLA/quotes/latest").mock(
            return_value=Response(200, json={
                "quote": {
                    "ap": "200.00",
                    "bp": "199.50"
                }
            })
        )
        
        quote = await executor.get_quote("TSLA", "sell", 50.0)
        
        assert quote.side == "sell"
        assert quote.price == 199.50  # bid price for sell


class TestAlpacaExecutorExecuteTrade:
    """Test AlpacaExecutor execute_trade method."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_market_order_success(self):
        """Test successful market order execution."""
        executor = AlpacaExecutor()
        
        respx.post("https://paper-api.alpaca.markets/v2/orders").mock(
            return_value=Response(200, json={
                "id": "order_123",
                "symbol": "AAPL",
                "filled_avg_price": "150.25",
                "status": "filled"
            })
        )
        
        result = await executor.execute_trade(
            symbol="AAPL",
            side="buy",
            amount=100.0,
            order_type="market"
        )
        
        assert isinstance(result, TradeResult)
        assert result.success is True
        assert result.venue == "alpaca"
        assert result.symbol == "AAPL"
        assert result.side == "buy"
        assert result.size == 100.0
        assert result.price == 150.25
        assert result.tx_id == "order_123"
        assert result.metadata["order_id"] == "order_123"

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_limit_order_success(self):
        """Test successful limit order execution with price."""
        executor = AlpacaExecutor()
        
        respx.post("https://paper-api.alpaca.markets/v2/orders").mock(
            return_value=Response(200, json={
                "id": "order_456",
                "symbol": "TSLA",
                "filled_avg_price": "199.50",
                "status": "filled"
            })
        )
        
        result = await executor.execute_trade(
            symbol="TSLA",
            side="sell",
            amount=10.0,
            order_type="limit",
            price=200.00
        )
        
        assert result.success is True
        assert result.price == 199.50

    @pytest.mark.asyncio
    @respx.mock
    async def test_execute_trade_error(self):
        """Test error handling when trade execution fails with client error."""
        from merid.execution.http_base import NonRetryableError
        
        executor = AlpacaExecutor()
        
        # Use 400 (client error) which raises NonRetryableError
        respx.post("https://paper-api.alpaca.markets/v2/orders").mock(
            return_value=Response(400, json={"message": "Invalid order"})
        )
        
        with pytest.raises(NonRetryableError) as exc_info:
            await executor.execute_trade(
                symbol="AAPL",
                side="buy",
                amount=100.0
            )
        
        assert "400" in str(exc_info.value)
        assert "alpaca" in str(exc_info.value).lower()


class TestAlpacaExecutorGetPositions:
    """Test AlpacaExecutor get_positions method."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_positions_success(self):
        """Test successful positions retrieval."""
        executor = AlpacaExecutor()
        
        respx.get("https://paper-api.alpaca.markets/v2/positions").mock(
            return_value=Response(200, json=[
                {
                    "symbol": "AAPL",
                    "qty": "100",
                    "avg_entry_price": "145.00",
                    "unrealized_plpc": "500",
                    "asset_id": "asset_123"
                },
                {
                    "symbol": "TSLA",
                    "qty": "50",
                    "avg_entry_price": "195.00",
                    "unrealized_plpc": "-250",
                    "asset_id": "asset_456"
                }
            ])
        )
        
        positions = await executor.get_positions()
        
        assert len(positions) == 2
        assert isinstance(positions[0], Position)
        assert positions[0].symbol == "AAPL"
        assert positions[0].size == 100.0
        assert positions[0].entry_price == 145.00
        assert positions[0].pnl == 0.05  # 500 / 10000
        assert positions[0].venue == "alpaca"
        assert positions[0].metadata["asset_id"] == "asset_123"
        
        assert positions[1].symbol == "TSLA"
        assert positions[1].size == 50.0

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_positions_empty(self):
        """Test empty positions list."""
        executor = AlpacaExecutor()
        
        respx.get("https://paper-api.alpaca.markets/v2/positions").mock(
            return_value=Response(200, json=[])
        )
        
        positions = await executor.get_positions()
        
        assert positions == []
