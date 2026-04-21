"""Comprehensive tests for merid/execution/executors/fulcrom.py."""

import pytest
import respx
from httpx import Response

from merid.execution.executors.fulcrom import FulcromExecutor
from merid.execution.base import Quote, TradeResult, Position


class TestFulcromExecutorInitialization:
    """Test FulcromExecutor initialization."""

    def test_default_initialization(self):
        """Test initialization with default values."""
        executor = FulcromExecutor()
        assert executor.venue == "fulcrom"
        assert executor.base_url == "https://api.fulcrom.finance"
        assert executor.default_timeout == 10.0

    def test_custom_api_url_from_env(self, monkeypatch):
        """Test custom API URL can be overridden via class attribute."""
        # base_url is a class attribute evaluated at import time, so patch the class
        monkeypatch.setattr(FulcromExecutor, "base_url", "https://test.fulcrom.finance")
        executor = FulcromExecutor()
        assert executor.base_url == "https://test.fulcrom.finance"

    def test_cronos_config_from_env(self, monkeypatch):
        """Test Cronos config loaded from environment."""
        monkeypatch.setenv("CRONOS_RPC_URL", "https://test.cronos.org")
        monkeypatch.setenv("CRONOS_PRIVATE_KEY", "0xprivatekey")
        
        executor = FulcromExecutor()
        assert executor.rpc_url == "https://test.cronos.org"
        assert executor.private_key == "0xprivatekey"

    def test_default_cronos_rpc(self):
        """Test default Cronos RPC URL."""
        executor = FulcromExecutor()
        assert executor.rpc_url == "https://evm-cronos.crypto.org"


class TestFulcromExecutorAuth:
    """Test FulcromExecutor authentication."""

    def test_get_auth_headers(self):
        """Test auth headers (Fulcrom uses empty headers)."""
        executor = FulcromExecutor()
        
        headers = executor._get_auth_headers()
        
        assert headers == {}


class TestFulcromExecutorGetQuote:
    """Test FulcromExecutor get_quote method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_quote_buy_success(self):
        """Test successful buy quote retrieval."""
        executor = FulcromExecutor()
        
        route = respx.get("https://api.fulcrom.finance/v1/quote").mock(
            return_value=Response(200, json={
                "price": "0.0005",
                "id": "quote_123"
            })
        )
        
        quote = await executor.get_quote("BTC-USDC", "buy", 1.0)
        
        assert isinstance(quote, Quote)
        assert quote.symbol == "BTC-USDC"
        assert quote.side == "buy"
        assert quote.price == 0.0005
        assert quote.venue == "fulcrom"
        assert quote.size == 1.0
        assert quote.metadata["quote_id"] == "quote_123"
        assert route.called
        
        # Verify query params
        request = route.calls[0].request
        params = str(request.url.params)
        assert "base=BTC" in params
        assert "quote=USDC" in params
        assert "amount=1.0" in params
        assert "type=buy" in params

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_quote_sell_success(self):
        """Test successful sell quote retrieval."""
        executor = FulcromExecutor()
        
        route = respx.get("https://api.fulcrom.finance/v1/quote").mock(
            return_value=Response(200, json={
                "price": "0.00048",
                "id": "quote_456"
            })
        )
        
        quote = await executor.get_quote("ETH-USD", "sell", 2.5)
        
        assert quote.side == "sell"
        assert quote.price == 0.00048
        assert quote.metadata["quote_id"] == "quote_456"


class TestFulcromExecutorExecuteTrade:
    """Test FulcromExecutor execute_trade method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_market_order_success(self):
        """Test successful market order execution."""
        executor = FulcromExecutor()
        
        route = respx.post("https://api.fulcrom.finance/v1/order").mock(
            return_value=Response(200, json={
                "id": "order_123",
                "tx_hash": "0xabc123",
                "executed_price": "0.0005"
            })
        )
        
        result = await executor.execute_trade(
            symbol="BTC-USDC",
            side="buy",
            amount=1.0,
            order_type="market"
        )
        
        assert isinstance(result, TradeResult)
        assert result.success is True
        assert result.venue == "fulcrom"
        assert result.symbol == "BTC-USDC"
        assert result.side == "buy"
        assert result.size == 1.0
        assert result.price == 0.0005
        assert result.tx_id == "0xabc123"
        assert route.called
        
        # Verify request payload
        request = route.calls[0].request
        import json
        payload = json.loads(request.content)
        assert payload["base"] == "BTC"
        assert payload["quote"] == "USDC"
        assert payload["amount"] == "1.0"
        assert payload["type"] == "buy"
        assert payload["order_type"] == "market"

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_limit_order_success(self):
        """Test successful limit order execution."""
        executor = FulcromExecutor()
        
        route = respx.post("https://api.fulcrom.finance/v1/order").mock(
            return_value=Response(200, json={
                "id": "order_456",
                "tx_hash": "0xdef456",
                "executed_price": "0.00045"
            })
        )
        
        result = await executor.execute_trade(
            symbol="ETH-USD",
            side="sell",
            amount=5.0,
            order_type="limit",
            price=0.00045
        )
        
        assert result.success is True
        assert result.price == 0.00045
        assert result.tx_id == "0xdef456"
        
        # Verify price in payload
        request = route.calls[0].request
        import json
        payload = json.loads(request.content)
        assert payload["order_type"] == "limit"
        assert payload["price"] == "0.00045"

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_trade_api_error(self):
        """Test trade execution with API error raises NonRetryableError."""
        from merid.execution.http_base import NonRetryableError
        
        executor = FulcromExecutor()
        
        respx.post("https://api.fulcrom.finance/v1/order").mock(
            return_value=Response(400, json={"message": "Invalid order"})
        )
        
        with pytest.raises(NonRetryableError) as exc_info:
            await executor.execute_trade(
                symbol="BTC-USDC",
                side="buy",
                amount=1.0
            )
        
        assert "400" in str(exc_info.value)

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_trade_network_error(self):
        """Test trade execution with network error raises ExecutionError."""
        from merid.execution.http_base import ExecutionError
        
        executor = FulcromExecutor()
        
        respx.post("https://api.fulcrom.finance/v1/order").mock(
            side_effect=ConnectionError("Network unreachable")
        )
        
        with pytest.raises(ExecutionError) as exc_info:
            await executor.execute_trade(
                symbol="ETH-USD",
                side="sell",
                amount=2.0
            )
        
        assert "Network unreachable" in str(exc_info.value)


class TestFulcromExecutorGetPositions:
    """Test FulcromExecutor get_positions method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_success(self):
        """Test successful positions retrieval."""
        executor = FulcromExecutor()
        
        route = respx.get("https://api.fulcrom.finance/v1/positions").mock(
            return_value=Response(200, json={
                "positions": [
                    {
                        "id": "pos_1",
                        "base": "BTC",
                        "quote": "USDC",
                        "size": "1.5",
                        "entry_price": "45000.00",
                        "pnl": "500.00"
                    },
                    {
                        "id": "pos_2",
                        "base": "ETH",
                        "quote": "USDT",
                        "size": "10.0",
                        "entry_price": "3000.00",
                        "pnl": "200.00"
                    }
                ]
            })
        )
        
        positions = await executor.get_positions()
        
        assert len(positions) == 2
        
        # First position
        assert positions[0].symbol == "BTC-USDC"
        assert positions[0].size == 1.5
        assert positions[0].entry_price == 45000.00
        assert positions[0].pnl == 500.00
        assert positions[0].venue == "fulcrom"
        assert positions[0].metadata["position_id"] == "pos_1"
        
        # Second position
        assert positions[1].symbol == "ETH-USD"
        assert positions[1].size == 10.0
        assert positions[1].metadata["position_id"] == "pos_2"
        
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_empty(self):
        """Test positions retrieval with empty positions."""
        executor = FulcromExecutor()
        
        route = respx.get("https://api.fulcrom.finance/v1/positions").mock(
            return_value=Response(200, json={"positions": []})
        )
        
        positions = await executor.get_positions()
        
        assert positions == []

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_api_error(self):
        """Test positions retrieval with API error."""
        executor = FulcromExecutor()
        
        route = respx.get("https://api.fulcrom.finance/v1/positions").mock(
            return_value=Response(401, json={"error": "Unauthorized"})
        )
        
        with pytest.raises(Exception):
            await executor.get_positions()
