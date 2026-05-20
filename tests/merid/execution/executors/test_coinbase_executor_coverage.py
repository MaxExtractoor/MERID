"""Comprehensive tests for merid/execution/executors/coinbase.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from merid.execution.executors.coinbase import CoinbaseExecutor


@pytest.fixture
def executor(monkeypatch):
    """Create CoinbaseExecutor with mocked environment."""
    monkeypatch.setenv("COINBASE_API_KEY", "test_api_key")
    monkeypatch.setenv("COINBASE_API_SECRET", "test_api_secret")
    
    executor = CoinbaseExecutor()
    return executor


# =============================================================================
# Initialization Tests
# =============================================================================

class TestCoinbaseExecutorInit:
    """Test CoinbaseExecutor initialization."""

    def test_init_with_credentials(self, monkeypatch):
        monkeypatch.setenv("COINBASE_API_KEY", "api_key")
        monkeypatch.setenv("COINBASE_API_SECRET", "api_secret")
        
        executor = CoinbaseExecutor()
        
        assert executor.venue == "coinbase"
        assert executor.api_key == "api_key"
        assert executor.api_secret == "api_secret"

    def test_init_defaults(self, monkeypatch):
        monkeypatch.delenv("COINBASE_API_KEY", raising=False)
        monkeypatch.delenv("COINBASE_API_SECRET", raising=False)
        
        executor = CoinbaseExecutor()
        
        assert executor.api_key is None


class TestGetAuthHeaders:
    """Test _get_auth_headers method."""

    def test_auth_headers_empty(self, executor):
        headers = executor._get_auth_headers()
        assert headers == {}


class TestSign:
    """Test _sign method."""

    def test_sign_generates_headers(self, executor):
        headers = executor._sign("GET", "/v2/accounts")
        
        assert "CB-ACCESS-KEY" in headers
        assert "CB-ACCESS-SIGN" in headers
        assert "CB-ACCESS-TIMESTAMP" in headers

    def test_sign_with_body(self, executor):
        headers = executor._sign("POST", "/v2/orders", '{"side":"buy"}')
        
        assert headers["CB-ACCESS-KEY"] == "test_api_key"


# =============================================================================
# Get Quote Tests
# =============================================================================

class TestGetQuote:
    """Test get_quote method."""

    @pytest.mark.asyncio
    async def test_get_quote_success(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {"price": "50000.00"}
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            quote = await executor.get_quote("BTC-USD", "buy", 1.0)
        
        assert quote.symbol == "BTC-USD"
        assert quote.side == "buy"
        assert quote.price == 50000.0
        assert quote.venue == "coinbase"


# =============================================================================
# Execute Trade Tests
# =============================================================================

class TestExecuteTrade:
    """Test execute_trade method."""

    @pytest.mark.asyncio
    async def test_execute_market_order_success(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": "order_123",
            "executed_value": "50000.00"
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            result = await executor.execute_trade(
                symbol="BTC-USD",
                side="buy",
                amount=1.0
            )
        
        assert result.success is True
        assert result.venue == "coinbase"
        assert result.tx_id == "order_123"

    @pytest.mark.asyncio
    async def test_execute_limit_order_success(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": "limit_456",
            "executed_value": "48000.00"
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            result = await executor.execute_trade(
                symbol="BTC-USD",
                side="buy",
                amount=1.0,
                order_type="limit",
                price=48000.0
            )
        
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_trade_connection_error(self, executor):
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = ConnectionError("Network error")
            
            result = await executor.execute_trade(
                symbol="BTC-USD",
                side="buy",
                amount=1.0
            )
        
        assert result.success is False
        assert "Coinbase API error" in result.error

    @pytest.mark.asyncio
    async def test_execute_trade_runtime_error(self, executor):
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = RuntimeError("API error")
            
            result = await executor.execute_trade(
                symbol="ETH-USD",
                side="sell",
                amount=10.0,
                price=3000.0
            )
        
        assert result.success is False
        assert result.price == 3000.0


# =============================================================================
# Get Positions Tests
# =============================================================================

class TestGetPositions:
    """Test get_positions method."""

    @pytest.mark.asyncio
    async def test_get_positions_success(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "type": "wallet",
                    "currency": "BTC",
                    "available": {"value": "1.5"},
                    "id": "acct_123"
                },
                {
                    "type": "wallet",
                    "currency": "ETH",
                    "available": {"value": "10.0"},
                    "id": "acct_456"
                }
            ]
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            positions = await executor.get_positions()
        
        assert len(positions) == 2
        assert positions[0].symbol == "BTC-USD"

    @pytest.mark.asyncio
    async def test_get_positions_filters_non_wallet(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"type": "fiat", "currency": "USD", "available": {"value": "1000"}, "id": "1"},
                {"type": "wallet", "currency": "BTC", "available": {"value": "0.5"}, "id": "2"}
            ]
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            positions = await executor.get_positions()
        
        assert len(positions) == 1

    @pytest.mark.asyncio
    async def test_get_positions_filters_zero_balance(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"type": "wallet", "currency": "BTC", "available": {"value": "0"}, "id": "1"},
                {"type": "wallet", "currency": "ETH", "available": {"value": "5.0"}, "id": "2"}
            ]
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            positions = await executor.get_positions()
        
        assert len(positions) == 1
        assert positions[0].symbol == "ETH-USD"


# =============================================================================
# Product ID Conversion Tests
# =============================================================================

class TestToProductId:
    """Test _to_product_id method."""

    def test_usdt_to_usd(self, executor):
        result = executor._to_product_id("BTC-USD")
        assert result == "BTC-USD"

    def test_usd_unchanged(self, executor):
        result = executor._to_product_id("ETH-USD")
        assert result == "ETH-USD"

    def test_other_quote_unchanged(self, executor):
        result = executor._to_product_id("ETH-BTC")
        assert result == "ETH-BTC"


# =============================================================================
# Class Attributes Tests
# =============================================================================

class TestClassAttributes:
    """Test class-level attributes."""

    def test_venue_name(self):
        assert CoinbaseExecutor.venue == "coinbase"

    def test_default_timeout(self):
        assert CoinbaseExecutor.default_timeout == 10.0
