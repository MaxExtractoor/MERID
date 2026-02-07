"""Comprehensive tests for merid/execution/executors/crypto_com.py."""

import pytest
import respx
from httpx import Response

from merid.execution.executors.crypto_com import CryptoComExecutor
from merid.execution.base import Quote, TradeResult, Position


class TestCryptoComExecutorInitialization:
    """Test CryptoComExecutor initialization."""

    def test_default_initialization(self):
        """Test initialization with default values."""
        executor = CryptoComExecutor()
        assert executor.venue == "crypto_com"
        assert executor.base_url == "https://api.crypto.com"
        assert executor.default_timeout == 10.0

    def test_custom_api_url_from_env(self, monkeypatch):
        """Test custom API URL from environment variable."""
        # base_url is a class attribute evaluated at definition time,
        # so we patch the class attribute directly
        monkeypatch.setattr(CryptoComExecutor, "base_url", "https://test.crypto.com")
        executor = CryptoComExecutor()
        assert executor.base_url == "https://test.crypto.com"

    def test_api_credentials_from_env(self, monkeypatch):
        """Test API credentials loaded from environment."""
        monkeypatch.setenv("CRYPTO_COM_API_KEY", "test_key")
        monkeypatch.setenv("CRYPTO_COM_API_SECRET", "test_secret")
        executor = CryptoComExecutor()
        assert executor.api_key == "test_key"
        assert executor.api_secret == "test_secret"


class TestCryptoComExecutorAuth:
    """Test CryptoComExecutor authentication."""

    def test_get_auth_headers_with_credentials(self, monkeypatch):
        """Test auth headers with credentials."""
        monkeypatch.setenv("CRYPTO_COM_API_KEY", "my_key")
        monkeypatch.setenv("CRYPTO_COM_API_SECRET", "my_secret")
        executor = CryptoComExecutor()
        
        headers = executor._get_auth_headers()
        
        assert headers["API-Key"] == "my_key"
        assert headers["API-Secret"] == "my_secret"

    def test_get_auth_headers_without_credentials(self):
        """Test auth headers without credentials."""
        executor = CryptoComExecutor()
        
        headers = executor._get_auth_headers()
        
        assert headers["API-Key"] == ""
        assert headers["API-Secret"] == ""


class TestCryptoComExecutorSymbolConversion:
    """Test symbol/instrument conversion methods."""

    def test_symbol_to_instrument(self):
        """Test converting symbol to instrument format."""
        executor = CryptoComExecutor()
        
        assert executor._symbol_to_instrument("BTC-USD") == "BTCUSD"
        assert executor._symbol_to_instrument("ETH-USDT") == "ETHUSDT"
        assert executor._symbol_to_instrument("BTC") == "BTC"

    def test_instrument_to_symbol(self):
        """Test converting instrument to symbol format."""
        executor = CryptoComExecutor()
        
        # Implementation assumes 4-char quote currency
        assert executor._instrument_to_symbol("BTCUSDC") == "BTC-USDC"
        assert executor._instrument_to_symbol("ETHUSDT") == "ETH-USDT"
        assert executor._instrument_to_symbol("BTC") == "BTC"

    def test_instrument_to_symbol_short_names(self):
        """Test converting short instrument names."""
        executor = CryptoComExecutor()
        
        # Short names (4 chars or less) pass through unchanged
        assert executor._instrument_to_symbol("BTC") == "BTC"
        assert executor._instrument_to_symbol("ETH") == "ETH"


class TestCryptoComExecutorGetQuote:
    """Test CryptoComExecutor get_quote method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_quote_buy_side(self):
        """Test getting quote for buy side."""
        executor = CryptoComExecutor()
        
        route = respx.get("https://api.crypto.com/v2/public/get-ticker").mock(
            return_value=Response(200, json={
                "result": {"b": "45000.00", "k": "44900.00"}
            })
        )
        
        quote = await executor.get_quote("BTC-USD", "buy", 1.0)
        
        assert isinstance(quote, Quote)
        assert quote.symbol == "BTC-USD"
        assert quote.side == "buy"
        assert quote.price == 45000.00
        assert quote.venue == "crypto_com"
        assert quote.size == 1.0
        assert quote.metadata["instrument"] == "BTCUSD"
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_quote_sell_side(self):
        """Test getting quote for sell side."""
        executor = CryptoComExecutor()
        
        route = respx.get("https://api.crypto.com/v2/public/get-ticker").mock(
            return_value=Response(200, json={
                "result": {"b": "45000.00", "k": "44900.00"}
            })
        )
        
        quote = await executor.get_quote("BTC-USD", "sell", 0.5)
        
        assert quote.price == 44900.00
        assert quote.side == "sell"


class TestCryptoComExecutorExecuteTrade:
    """Test CryptoComExecutor execute_trade method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_market_order_success(self):
        """Test successful market order execution."""
        executor = CryptoComExecutor()
        
        route = respx.post("https://api.crypto.com/v2/private/create-order").mock(
            return_value=Response(200, json={
                "result": {"order_id": "order_123", "price": "45000.00"}
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
        assert result.venue == "crypto_com"
        assert result.symbol == "BTC-USD"
        assert result.side == "buy"
        assert result.size == 1.0
        assert result.price == 45000.00
        assert result.tx_id == "order_123"
        assert route.called
        
        # Verify request payload
        request = route.calls[0].request
        import json
        payload = json.loads(request.content)
        assert payload["instrument_name"] == "BTCUSD"
        assert payload["side"] == "buy"
        assert payload["type"] == "market"
        assert payload["quantity"] == "1.0"

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_limit_order_success(self):
        """Test successful limit order execution."""
        executor = CryptoComExecutor()
        
        route = respx.post("https://api.crypto.com/v2/private/create-order").mock(
            return_value=Response(200, json={
                "result": {"order_id": "order_456", "price": "44000.00"}
            })
        )
        
        result = await executor.execute_trade(
            symbol="BTC-USD",
            side="sell",
            amount=0.5,
            order_type="limit",
            price=44000.00
        )
        
        assert result.success is True
        assert result.price == 44000.00
        assert result.tx_id == "order_456"
        
        # Verify price in payload
        request = route.calls[0].request
        import json
        payload = json.loads(request.content)
        assert payload["type"] == "limit"
        assert payload["price"] == "44000.0"

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_trade_api_error(self):
        """Test trade execution with API error raises NonRetryableError."""
        from merid.execution.http_base import NonRetryableError
        
        executor = CryptoComExecutor()
        
        respx.post("https://api.crypto.com/v2/private/create-order").mock(
            return_value=Response(400, json={"message": "Invalid order"})
        )
        
        with pytest.raises(NonRetryableError) as exc_info:
            await executor.execute_trade(
                symbol="BTC-USD",
                side="buy",
                amount=1.0
            )
        
        assert "400" in str(exc_info.value)

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_trade_network_error(self):
        """Test trade execution with network error raises ExecutionError."""
        from merid.execution.http_base import ExecutionError
        
        executor = CryptoComExecutor()
        
        respx.post("https://api.crypto.com/v2/private/create-order").mock(
            side_effect=ConnectionError("Network unreachable")
        )
        
        with pytest.raises(ExecutionError) as exc_info:
            await executor.execute_trade(
                symbol="ETH-USD",
                side="sell",
                amount=2.0
            )
        
        assert "Network unreachable" in str(exc_info.value)


class TestCryptoComExecutorGetPositions:
    """Test CryptoComExecutor get_positions method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_success(self):
        """Test successful positions retrieval."""
        executor = CryptoComExecutor()
        
        route = respx.get("https://api.crypto.com/v2/private/get-positions").mock(
            return_value=Response(200, json={
                "result": {
                    "list": [
                        {
                            "instrument_name": "BTCUSDC",
                            "size": "1.5",
                            "entry_price": "40000.00",
                            "unrealized_pnl": "7500.00"
                        },
                        {
                            "instrument_name": "ETHUSDT",
                            "size": "10.0",
                            "entry_price": "2000.00",
                            "unrealized_pnl": "500.00"
                        }
                    ]
                }
            })
        )
        
        positions = await executor.get_positions()
        
        assert len(positions) == 2
        
        # First position (BTCUSDC -> BTC-USDC with 4-char quote)
        assert positions[0].symbol == "BTC-USDC"
        assert positions[0].size == 1.5
        assert positions[0].entry_price == 40000.00
        assert positions[0].pnl == 7500.00
        assert positions[0].venue == "crypto_com"
        
        # Second position
        assert positions[1].symbol == "ETH-USDT"
        assert positions[1].size == 10.0
        assert positions[1].metadata["instrument_name"] == "ETHUSDT"
        
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_empty_list(self):
        """Test positions retrieval with empty list."""
        executor = CryptoComExecutor()
        
        route = respx.get("https://api.crypto.com/v2/private/get-positions").mock(
            return_value=Response(200, json={"result": {"list": []}})
        )
        
        positions = await executor.get_positions()
        
        assert positions == []

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_missing_fields(self):
        """Test positions retrieval with missing optional fields."""
        executor = CryptoComExecutor()
        
        route = respx.get("https://api.crypto.com/v2/private/get-positions").mock(
            return_value=Response(200, json={
                "result": {
                    "list": [
                        {
                            "instrument_name": "BTCUSDC",
                            "size": "0.5"
                            # Missing entry_price and unrealized_pnl
                        }
                    ]
                }
            })
        )
        
        positions = await executor.get_positions()
        
        assert len(positions) == 1
        assert positions[0].symbol == "BTC-USDC"
        assert positions[0].size == 0.5
        assert positions[0].entry_price == 0.0  # Default value
        assert positions[0].pnl == 0.0  # Default value

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_positions_api_error(self):
        """Test positions retrieval with API error."""
        executor = CryptoComExecutor()
        
        route = respx.get("https://api.crypto.com/v2/private/get-positions").mock(
            return_value=Response(401, json={"error": "Unauthorized"})
        )
        
        with pytest.raises(Exception):
            await executor.get_positions()
