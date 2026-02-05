"""Tests for additional venue executors - Batch 7 Coverage."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import json

from merid.execution.executors.alpaca import AlpacaExecutor
from merid.execution.executors.jupiter import JupiterExecutor
from merid.execution.executors.webull import WebullExecutor


class TestAlpacaExecutor:
    """Tests for Alpaca venue executor."""

    @pytest.fixture
    def executor(self):
        """Create AlpacaExecutor instance."""
        with patch.dict('os.environ', {
            'ALPACA_API_KEY': 'test_key',
            'ALPACA_API_SECRET': 'test_secret'
        }):
            return AlpacaExecutor()

    def test_initialization(self, executor):
        """Test executor initialization."""
        assert executor is not None
        assert executor.venue == "alpaca"
        assert executor.api_key == "test_key"
        assert executor.api_secret == "test_secret"

    def test_get_auth_headers(self, executor):
        """Test auth headers generation."""
        headers = executor._get_auth_headers()
        assert "APCA-API-KEY-ID" in headers
        assert headers["APCA-API-KEY-ID"] == "test_key"
        assert "APCA-API-SECRET-KEY" in headers

    @pytest.mark.asyncio
    async def test_get_quote(self, executor):
        """Test getting quote."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "quote": {"ap": "150.00", "bp": "149.95"}
        }
        
        with patch.object(executor, '_request', AsyncMock(return_value=mock_response)):
            quote = await executor.get_quote("AAPL", "buy", 10)
            assert quote.symbol == "AAPL"
            assert quote.side == "buy"
            assert quote.venue == "alpaca"

    @pytest.mark.asyncio
    async def test_execute_trade_market(self, executor):
        """Test executing market trade."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": "order_123",
            "filled_avg_price": "150.00"
        }
        
        with patch.object(executor, '_request', AsyncMock(return_value=mock_response)):
            result = await executor.execute_trade("AAPL", "buy", 10)
            assert result.success is True
            assert result.venue == "alpaca"
            assert result.symbol == "AAPL"
            assert result.tx_id == "order_123"

    @pytest.mark.asyncio
    async def test_execute_trade_limit(self, executor):
        """Test executing limit trade."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": "order_456",
            "filled_avg_price": "200.00"
        }
        
        with patch.object(executor, '_request', AsyncMock(return_value=mock_response)):
            result = await executor.execute_trade(
                "TSLA", "sell", 5, 
                order_type="limit", 
                price=200.00
            )
            assert result.success is True
            assert result.price == 200.00

    @pytest.mark.asyncio
    async def test_execute_trade_error(self, executor):
        """Test trade execution error handling."""
        with patch.object(executor, '_request', AsyncMock(side_effect=ConnectionError("Network down"))):
            result = await executor.execute_trade("AAPL", "buy", 10)
            assert result.success is False
            assert "Network down" in result.error

    @pytest.mark.asyncio
    async def test_get_positions(self, executor):
        """Test getting positions."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "symbol": "AAPL",
                "qty": "10",
                "avg_entry_price": "150.00",
                "unrealized_plpc": "500",
                "asset_id": "asset_123"
            }
        ]
        
        with patch.object(executor, '_request', AsyncMock(return_value=mock_response)):
            positions = await executor.get_positions()
            assert len(positions) == 1
            assert positions[0].symbol == "AAPL"
            assert positions[0].size == 10.0


class TestJupiterExecutor:
    """Tests for Jupiter DEX executor (Solana)."""

    @pytest.fixture
    def executor(self):
        """Create JupiterExecutor instance."""
        with patch.dict('os.environ', {}, clear=True):
            return JupiterExecutor()

    def test_initialization(self, executor):
        """Test executor initialization."""
        assert executor is not None
        assert executor.venue == "jupiter"

    def test_venue_property(self, executor):
        """Test venue property."""
        assert hasattr(executor, 'venue')


class TestWebullExecutor:
    """Tests for Webull executor."""

    @pytest.fixture
    def executor(self):
        """Create WebullExecutor instance."""
        with patch.dict('os.environ', {}, clear=True):
            return WebullExecutor()

    def test_initialization(self, executor):
        """Test executor initialization."""
        assert executor is not None
        assert executor.venue == "webull"

    def test_venue_property(self, executor):
        """Test venue property."""
        assert hasattr(executor, 'venue')
