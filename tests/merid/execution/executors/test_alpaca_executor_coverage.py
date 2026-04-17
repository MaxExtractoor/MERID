"""Comprehensive tests for merid/execution/executors/alpaca.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from merid.execution.executors.alpaca import AlpacaExecutor


@pytest.fixture
def executor(monkeypatch):
    """Create AlpacaExecutor with mocked environment."""
    monkeypatch.setenv("ALPACA_API_KEY", "test_api_key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test_api_secret")
    
    executor = AlpacaExecutor()
    return executor


# =============================================================================
# Initialization Tests
# =============================================================================

class TestAlpacaExecutorInit:
    """Test AlpacaExecutor initialization."""

    def test_init_with_credentials(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "api_key")
        monkeypatch.setenv("ALPACA_API_SECRET", "api_secret")
        
        executor = AlpacaExecutor()
        
        assert executor.venue == "alpaca"
        assert executor.api_key == "api_key"
        assert executor.api_secret == "api_secret"

    def test_init_defaults(self, monkeypatch):
        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
        
        executor = AlpacaExecutor()
        
        assert executor.api_key is None
        assert executor.api_secret is None


class TestGetAuthHeaders:
    """Test _get_auth_headers method."""

    def test_auth_headers_with_credentials(self, executor):
        headers = executor._get_auth_headers()
        
        assert headers["APCA-API-KEY-ID"] == "test_api_key"
        assert headers["APCA-API-SECRET-KEY"] == "test_api_secret"

    def test_auth_headers_without_credentials(self, monkeypatch):
        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
        
        executor = AlpacaExecutor()
        headers = executor._get_auth_headers()
        
        assert headers["APCA-API-KEY-ID"] == ""
        assert headers["APCA-API-SECRET-KEY"] == ""


# =============================================================================
# Get Quote Tests
# =============================================================================

class TestGetQuote:
    """Test get_quote method."""

    @pytest.mark.asyncio
    async def test_get_quote_buy(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "quote": {"ap": "150.50", "bp": "150.25"}
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            quote = await executor.get_quote("AAPL", "buy", 10.0)
        
        assert quote.symbol == "AAPL"
        assert quote.side == "buy"
        assert quote.price == 150.50
        assert quote.venue == "alpaca"

    @pytest.mark.asyncio
    async def test_get_quote_sell(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "quote": {"ap": "150.50", "bp": "150.25"}
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            quote = await executor.get_quote("AAPL", "sell", 10.0)
        
        assert quote.price == 150.25


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
            "filled_avg_price": "151.00"
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            result = await executor.execute_trade(
                symbol="AAPL",
                side="buy",
                amount=10.0
            )
        
        assert result.success is True
        assert result.venue == "alpaca"
        assert result.tx_id == "order_123"
        assert result.price == 151.0

    @pytest.mark.asyncio
    async def test_execute_limit_order_success(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": "limit_456",
            "filled_avg_price": "145.00"
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            result = await executor.execute_trade(
                symbol="AAPL",
                side="buy",
                amount=10.0,
                order_type="limit",
                price=145.0
            )
        
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_trade_connection_error(self, executor):
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = ConnectionError("Network error")
            
            result = await executor.execute_trade(
                symbol="AAPL",
                side="buy",
                amount=10.0
            )
        
        assert result.success is False
        assert "Alpaca API error" in result.error

    @pytest.mark.asyncio
    async def test_execute_trade_runtime_error(self, executor):
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = RuntimeError("API error")
            
            result = await executor.execute_trade(
                symbol="TSLA",
                side="sell",
                amount=5.0,
                price=200.0
            )
        
        assert result.success is False
        assert result.price == 200.0


# =============================================================================
# Get Positions Tests
# =============================================================================

class TestGetPositions:
    """Test get_positions method."""

    @pytest.mark.asyncio
    async def test_get_positions_success(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "symbol": "AAPL",
                "qty": "100",
                "avg_entry_price": "150.00",
                "unrealized_pl": "99.99",
                "asset_id": "asset_123"
            }
        ]
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            positions = await executor.get_positions()
        
        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"
        assert positions[0].size == 100.0

    @pytest.mark.asyncio
    async def test_get_positions_empty(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = []
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            positions = await executor.get_positions()
        
        assert positions == []


# =============================================================================
# Class Attributes Tests
# =============================================================================

class TestClassAttributes:
    """Test class-level attributes."""

    def test_venue_name(self):
        assert AlpacaExecutor.venue == "alpaca"

    def test_default_timeout(self):
        assert AlpacaExecutor.default_timeout == 10.0
