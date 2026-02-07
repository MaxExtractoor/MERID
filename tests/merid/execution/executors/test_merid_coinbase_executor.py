"""Comprehensive tests for merid/execution/executors/coinbase.py."""

import pytest
import respx
import json
from httpx import Response
from unittest.mock import patch

from merid.execution.executors.coinbase import CoinbaseExecutor
from merid.execution.base import Quote, TradeResult, Position


class TestCoinbaseExecutorInitialization:
    """Test CoinbaseExecutor initialization."""

    def test_default_initialization(self):
        """Test initialization with default values."""
        executor = CoinbaseExecutor()
        assert executor.venue == "coinbase"
        assert executor.base_url == "https://api.coinbase.com"
        assert executor.default_timeout == 10.0

    def test_custom_api_url_from_env(self, monkeypatch):
        """Test custom API URL can be overridden via class attribute."""
        # base_url is a class attribute evaluated at import time, so patch the class
        monkeypatch.setattr(CoinbaseExecutor, "base_url", "https://test.coinbase.com")
        executor = CoinbaseExecutor()
        assert executor.base_url == "https://test.coinbase.com"

    def test_credentials_from_env(self, monkeypatch):
        """Test credentials loaded from environment."""
        monkeypatch.setenv("COINBASE_API_KEY", "test_key")
        monkeypatch.setenv("COINBASE_API_SECRET", "test_secret")
        monkeypatch.setenv("COINBASE_PASSPHRASE", "test_passphrase")
        
        executor = CoinbaseExecutor()
        assert executor.api_key == "test_key"
        assert executor.api_secret == "test_secret"
        assert executor.passphrase == "test_passphrase"


class TestCoinbaseExecutorAuthHeaders:
    """Test CoinbaseExecutor authentication headers."""

    def test_get_auth_headers_empty(self):
        """Test base auth headers are empty."""
        executor = CoinbaseExecutor()
        
        headers = executor._get_auth_headers()
        
        assert headers == {}

    def test_sign_generates_headers(self, monkeypatch):
        """Test _sign generates authentication headers."""
        monkeypatch.setenv("COINBASE_API_KEY", "my_key")
        monkeypatch.setenv("COINBASE_API_SECRET", "my_secret")
        monkeypatch.setenv("COINBASE_PASSPHRASE", "my_passphrase")
        executor = CoinbaseExecutor()
        
        headers = executor._sign("GET", "/v2/accounts")
        
        assert headers["CB-ACCESS-KEY"] == "my_key"
        assert headers["CB-ACCESS-PASSPHRASE"] == "my_passphrase"
        assert "CB-ACCESS-SIGN" in headers
        assert "CB-ACCESS-TIMESTAMP" in headers
        assert len(headers["CB-ACCESS-SIGN"]) == 64  # SHA256 hex

    def test_sign_with_body(self, monkeypatch):
        """Test _sign with request body."""
        monkeypatch.setenv("COINBASE_API_SECRET", "my_secret")
        executor = CoinbaseExecutor()
        
        headers_no_body = executor._sign("POST", "/v2/orders")
        headers_with_body = executor._sign("POST", "/v2/orders", '{"test": "data"}')
        
        # Signatures should be different when body is included
        assert headers_no_body["CB-ACCESS-SIGN"] != headers_with_body["CB-ACCESS-SIGN"]

    def test_sign_without_credentials(self, monkeypatch):
        """Test _sign without credentials raises AttributeError."""
        # Clear any existing credentials from environment
        monkeypatch.delenv("COINBASE_API_KEY", raising=False)
        monkeypatch.delenv("COINBASE_API_SECRET", raising=False)
        monkeypatch.delenv("COINBASE_PASSPHRASE", raising=False)
        
        executor = CoinbaseExecutor()
        
        # _sign requires api_secret to be non-None for .encode()
        with pytest.raises(AttributeError):
            executor._sign("GET", "/v2/accounts")


class TestCoinbaseExecutorToProductId:
    """Test _to_product_id conversion."""

    def test_usd_quote(self):
        """Test conversion with USD quote."""
        executor = CoinbaseExecutor()
        
        assert executor._to_product_id("BTC-USD") == "BTC-USD"
        assert executor._to_product_id("ETH-USD") == "ETH-USD"

    def test_usdt_quote_converted(self):
        """Test USDT quote converted to USD."""
        executor = CoinbaseExecutor()
        
        assert executor._to_product_id("BTC-USDT") == "BTC-USD"
        assert executor._to_product_id("ETH-USDT") == "ETH-USD"

    def test_other_quotes_preserved(self):
        """Test other quote currencies preserved."""
        executor = CoinbaseExecutor()
        
        assert executor._to_product_id("BTC-EUR") == "BTC-EUR"
        assert executor._to_product_id("ETH-GBP") == "ETH-GBP"


class TestCoinbaseExecutorGetQuote:
    """Test CoinbaseExecutor get_quote method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_quote_success(self, monkeypatch):
        """Test successful quote retrieval."""
        monkeypatch.setenv("COINBASE_API_KEY", "test_key")
        monkeypatch.setenv("COINBASE_API_SECRET", "test_secret")
        executor = CoinbaseExecutor()
        
        route = respx.get("https://api.coinbase.com/v2/products/BTC-USD/ticker").mock(
            return_value=Response(200, json={"price": "45000.00"})
        )
        
        quote = await executor.get_quote("BTC-USD", "buy", 1.0)
        
        assert isinstance(quote, Quote)
        assert quote.symbol == "BTC-USD"
        assert quote.side == "buy"
        assert quote.price == 45000.00
        assert quote.venue == "coinbase"
        assert quote.size == 1.0
        assert quote.metadata["product_id"] == "BTC-USD"
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_quote_sell_side(self, monkeypatch):
        """Test getting quote for sell side."""
        monkeypatch.setenv("COINBASE_API_SECRET", "test_secret")
        executor = CoinbaseExecutor()
        
        route = respx.get("https://api.coinbase.com/v2/products/ETH-USD/ticker").mock(
            return_value=Response(200, json={"price": "3000.00"})
        )
        
        quote = await executor.get_quote("ETH-USD", "sell", 5.0)
        
        assert quote.side == "sell"
        assert quote.price == 3000.00

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_quote_with_usdt(self, monkeypatch):
        """Test quote with USDT converted to USD."""
        monkeypatch.setenv("COINBASE_API_SECRET", "test_secret")
        executor = CoinbaseExecutor()
        
        route = respx.get("https://api.coinbase.com/v2/products/BTC-USD/ticker").mock(
            return_value=Response(200, json={"price": "45000.00"})
        )
        
        quote = await executor.get_quote("BTC-USDT", "buy", 1.0)
        
        # Symbol preserved in quote, but API call uses BTC-USD
        assert quote.symbol == "BTC-USDT"
        assert quote.metadata["product_id"] == "BTC-USD"


class TestCoinbaseExecutorExecuteTrade:
    """Test CoinbaseExecutor execute_trade method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_market_order_success(self, monkeypatch):
        """Test successful market order execution."""
        monkeypatch.setenv("COINBASE_API_KEY", "test_key")
        monkeypatch.setenv("COINBASE_API_SECRET", "test_secret")
        executor = CoinbaseExecutor()
        
        route = respx.post("https://api.coinbase.com/v2/orders").mock(
            return_value=Response(200, json={
                "id": "order_123",
                "executed_value": "45000.00"
            })
        )
        
        result = await executor.execute_trade(
            symbol="BTC-USD",
            side="buy",
            amount=1.0,
            order_type="market"
        )
        
        assert isinstance(result, TradeResult)
        assert result.success is True
        assert result.venue == "coinbase"
        assert result.symbol == "BTC-USD"
        assert result.side == "buy"
        assert result.size == 1.0
        assert result.price == 45000.00  # executed_value / amount
        assert result.tx_id == "order_123"
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_limit_order_success(self, monkeypatch):
        """Test successful limit order execution."""
        monkeypatch.setenv("COINBASE_API_SECRET", "test_secret")
        executor = CoinbaseExecutor()
        
        route = respx.post("https://api.coinbase.com/v2/orders").mock(
            return_value=Response(200, json={
                "id": "order_456",
                "executed_value": "22000.00"
            })
        )
        
        result = await executor.execute_trade(
            symbol="ETH-USD",
            side="sell",
            amount=2.0,
            order_type="limit",
            price=11000.00
        )
        
        assert result.success is True
        assert result.price == 11000.00  # 22000 / 2
        
        # Verify price in payload
        request = route.calls[0].request
        payload = json.loads(request.content)
        assert payload["type"] == "limit"
        assert payload["price"] == "11000.0"

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_trade_api_error(self, monkeypatch):
        """Test trade execution with API error."""
        monkeypatch.setenv("COINBASE_API_SECRET", "test_secret")
        executor = CoinbaseExecutor()
        
        route = respx.post("https://api.coinbase.com/v2/orders").mock(
            return_value=Response(400, json={"message": "Invalid order"})
        )
        
        result = await executor.execute_trade(
            symbol="BTC-USD",
            side="buy",
            amount=1.0
        )
        
        assert result.success is False
        assert "Coinbase API error" in result.error

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_trade_network_error(self, monkeypatch):
        """Test trade execution with network error."""
        monkeypatch.setenv("COINBASE_API_SECRET", "test_secret")
        executor = CoinbaseExecutor()
        
        route = respx.post("https://api.coinbase.com/v2/orders").mock(
            side_effect=ConnectionError("Network unreachable")
        )
        
        result = await executor.execute_trade(
            symbol="ETH-USD",
            side="sell",
            amount=2.0
        )
        
        assert result.success is False
        assert "Coinbase API error" in result.error

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_trade_timeout_error(self, monkeypatch):
        """Test trade execution with timeout error."""
        import asyncio
        monkeypatch.setenv("COINBASE_API_SECRET", "test_secret")
        executor = CoinbaseExecutor()
        
        route = respx.post("https://api.coinbase.com/v2/orders").mock(
            side_effect=asyncio.TimeoutError("Request timeout")
        )
        
        result = await executor.execute_trade(
            symbol="BTC-USD",
            side="buy",
            amount=1.0
        )
        
        assert result.success is False
        assert "Coinbase API error" in result.error


class TestCoinbaseExecutorGetPositions:
    """Test CoinbaseExecutor get_positions method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_success(self, monkeypatch):
        """Test successful positions retrieval."""
        monkeypatch.setenv("COINBASE_API_KEY", "test_key")
        monkeypatch.setenv("COINBASE_API_SECRET", "test_secret")
        executor = CoinbaseExecutor()
        
        route = respx.get("https://api.coinbase.com/v2/accounts").mock(
            return_value=Response(200, json={
                "data": [
                    {
                        "id": "acct_1",
                        "type": "wallet",
                        "currency": "BTC",
                        "available": {"value": "1.5"}
                    },
                    {
                        "id": "acct_2",
                        "type": "wallet",
                        "currency": "ETH",
                        "available": {"value": "10.0"}
                    },
                    {
                        "id": "acct_3",
                        "type": "fiat",  # Should be skipped
                        "currency": "USD",
                        "available": {"value": "1000.0"}
                    }
                ]
            })
        )
        
        positions = await executor.get_positions()
        
        # Only wallet types with non-zero balance
        assert len(positions) == 2
        
        # BTC position
        btc_pos = next(p for p in positions if p.symbol == "BTC-USD")
        assert btc_pos.size == 1.5
        assert btc_pos.venue == "coinbase"
        assert btc_pos.metadata["account_id"] == "acct_1"
        
        # ETH position
        eth_pos = next(p for p in positions if p.symbol == "ETH-USD")
        assert eth_pos.size == 10.0
        
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_skips_zero_balance(self, monkeypatch):
        """Test positions with zero balance are skipped."""
        monkeypatch.setenv("COINBASE_API_SECRET", "test_secret")
        executor = CoinbaseExecutor()
        
        route = respx.get("https://api.coinbase.com/v2/accounts").mock(
            return_value=Response(200, json={
                "data": [
                    {
                        "id": "acct_1",
                        "type": "wallet",
                        "currency": "BTC",
                        "available": {"value": "1.5"}
                    },
                    {
                        "id": "acct_2",
                        "type": "wallet",
                        "currency": "ETH",
                        "available": {"value": "0.0"}  # Zero balance - should skip
                    }
                ]
            })
        )
        
        positions = await executor.get_positions()
        
        assert len(positions) == 1
        assert positions[0].symbol == "BTC-USD"

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_empty(self, monkeypatch):
        """Test empty positions list."""
        monkeypatch.setenv("COINBASE_API_SECRET", "test_secret")
        executor = CoinbaseExecutor()
        
        route = respx.get("https://api.coinbase.com/v2/accounts").mock(
            return_value=Response(200, json={"data": []})
        )
        
        positions = await executor.get_positions()
        
        assert positions == []

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_missing_available(self, monkeypatch):
        """Test handling missing available field."""
        monkeypatch.setenv("COINBASE_API_SECRET", "test_secret")
        executor = CoinbaseExecutor()
        
        route = respx.get("https://api.coinbase.com/v2/accounts").mock(
            return_value=Response(200, json={
                "data": [
                    {
                        "id": "acct_1",
                        "type": "wallet",
                        "currency": "BTC"
                        # Missing available field
                    }
                ]
            })
        )
        
        positions = await executor.get_positions()
        
        # Should skip due to missing available (treated as 0)
        assert positions == []
