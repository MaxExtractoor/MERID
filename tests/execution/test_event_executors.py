"""Tests for event venues - Batch 8 Coverage (Kalshi, Polymarket)."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime

from merid.execution.executors.kalshi import KalshiExecutor


class TestKalshiExecutor:
    """Tests for Kalshi prediction market executor."""

    @pytest.fixture
    def executor(self):
        """Create KalshiExecutor instance."""
        with patch.dict('os.environ', {
            'KALSHI_API_KEY_ID': 'test_key_id',
            'KALSHI_PRIVATE_KEY_PEM': 'test_private_key'
        }):
            return KalshiExecutor()

    def test_initialization(self, executor):
        """Test executor initialization."""
        assert executor is not None
        assert executor.venue == "kalshi"
        assert executor.api_key_id == "test_key_id"
        assert executor.private_key_pem == "test_private_key"

    def test_get_auth_headers(self, executor):
        """Test auth headers generation."""
        headers = executor._get_auth_headers()
        assert "KALSHI-API-KEY-ID" in headers
        assert headers["KALSHI-API-KEY-ID"] == "test_key_id"

    def test_symbol_to_ticker_mapping(self, executor):
        """Test symbol to ticker conversion with known mappings."""
        assert executor._symbol_to_ticker("PRES-2024-DEM") == "PRES-2024-DEM"
        assert executor._symbol_to_ticker("PRES-2024-REP") == "PRES-2024-REP"
        # Unknown symbols pass through
        assert executor._symbol_to_ticker("BTC-YES") == "BTC-YES"

    def test_ticker_to_symbol_mapping(self, executor):
        """Test ticker to symbol conversion with known mappings."""
        assert executor._ticker_to_symbol("PRES-2024-DEM") == "PRES-2024-DEM"
        assert executor._ticker_to_symbol("PRES-2024-REP") == "PRES-2024-REP"
        # Unknown tickers pass through
        assert executor._ticker_to_symbol("BTCYES") == "BTCYES"

    @pytest.mark.asyncio
    async def test_get_quote(self, executor):
        """Test getting quote for prediction market."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "price": 65.0
        }

        with patch.object(executor, '_request', AsyncMock(return_value=mock_response)):
            quote = await executor.get_quote("PRES-2024-DEM", "buy", 100)
            assert quote.symbol == "PRES-2024-DEM"
            assert quote.venue == "kalshi"
            assert quote.price == 65.0
            assert quote.side == "buy"
            assert quote.size == 100

    @pytest.mark.asyncio
    async def test_execute_trade_buy(self, executor):
        """Test executing buy trade."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "order_id": "kalshi_order_123",
            "executed_price": 65.0
        }

        with patch.object(executor, '_request', AsyncMock(return_value=mock_response)):
            result = await executor.execute_trade("PRES-2024-DEM", "buy", 100)
            assert result.success is True
            assert result.venue == "kalshi"
            assert result.symbol == "PRES-2024-DEM"
            assert result.tx_id == "kalshi_order_123"
            assert result.price == 65.0

    @pytest.mark.asyncio
    async def test_execute_trade_limit(self, executor):
        """Test executing limit trade."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "order_id": "kalshi_order_456",
            "executed_price": 45.0
        }

        with patch.object(executor, '_request', AsyncMock(return_value=mock_response)):
            result = await executor.execute_trade(
                "PRES-2024-REP", "sell", 50,
                order_type="limit", price=45.0
            )
            assert result.success is True
            assert result.size == 50
            assert result.price == 45.0

    @pytest.mark.asyncio
    async def test_execute_trade_error(self, executor):
        """Test trade execution error handling."""
        with patch.object(executor, '_request', AsyncMock(side_effect=ConnectionError("Network down"))):
            result = await executor.execute_trade("PRES-2024-DEM", "buy", 100)
            assert result.success is False
            assert "Network down" in result.error

    @pytest.mark.asyncio
    async def test_get_positions(self, executor):
        """Test getting positions from Kalshi."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "positions": [
                {
                    "ticker": "PRES-2024-DEM",
                    "count": 100,
                    "avg_price": 60.0,
                    "pnl": 500.0
                }
            ]
        }

        with patch.object(executor, '_request', AsyncMock(return_value=mock_response)):
            positions = await executor.get_positions()
            assert len(positions) == 1
            assert positions[0].symbol == "PRES-2024-DEM"
            assert positions[0].size == 100.0
            assert positions[0].entry_price == 60.0
            assert positions[0].pnl == 500.0

    @pytest.mark.asyncio
    async def test_get_positions_empty(self, executor):
        """Test getting positions when none exist."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"positions": []}

        with patch.object(executor, '_request', AsyncMock(return_value=mock_response)):
            positions = await executor.get_positions()
            assert len(positions) == 0

    @pytest.mark.asyncio
    async def test_execute_trade_timeout_error(self, executor):
        """Test handling timeout error."""
        import asyncio
        with patch.object(executor, '_request', AsyncMock(side_effect=asyncio.TimeoutError("Timeout"))):
            result = await executor.execute_trade("PRES-2024-DEM", "buy", 100)
            assert result.success is False
            assert "Timeout" in result.error
