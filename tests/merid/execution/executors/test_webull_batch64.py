"""Additional tests for merid/execution/executors/webull.py - Batch 64."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.execution.executors.webull import WebullExecutor


class TestWebullExecutorAsync:
    """Tests for WebullExecutor async methods."""

    @pytest.fixture
    def executor(self):
        with patch.dict('os.environ', {'WEBULL_ACCESS_TOKEN': 'test_token'}, clear=True):
            return WebullExecutor()

    @pytest.mark.asyncio
    async def test_get_quote(self, executor):
        """Test get_quote."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "latestPrice": "150.25",
            "timestamp": "1234567890"
        }
        
        with patch.object(executor, '_request', new_callable=AsyncMock, return_value=mock_response):
            quote = await executor.get_quote("AAPL", "buy", 10.0)
            
        assert quote.symbol == "AAPL"
        assert quote.side == "buy"
        assert quote.price == 150.25
        assert quote.venue == "webull"

    @pytest.mark.asyncio
    async def test_execute_trade_market(self, executor):
        """Test execute_trade with market order."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "orderId": "order123",
            "avgPrice": "150.50"
        }
        
        with patch.object(executor, '_request', new_callable=AsyncMock, return_value=mock_response):
            result = await executor.execute_trade("TSLA", "buy", 5.0)
            
        assert result.success is True
        assert result.symbol == "TSLA"
        assert result.tx_id == "order123"

    @pytest.mark.asyncio
    async def test_execute_trade_limit(self, executor):
        """Test execute_trade with limit order."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "orderId": "order456",
            "avgPrice": "145.00"
        }
        
        with patch.object(executor, '_request', new_callable=AsyncMock, return_value=mock_response):
            result = await executor.execute_trade("AAPL", "sell", 10.0, order_type="limit", price=145.0)
            
        assert result.success is True
        assert result.price == 145.0

    @pytest.mark.asyncio
    async def test_execute_trade_error(self, executor):
        """Test execute_trade with API error."""
        with patch.object(executor, '_request', new_callable=AsyncMock, side_effect=ConnectionError("Network error")):
            result = await executor.execute_trade("AAPL", "buy", 10.0)
            
        assert result.success is False
        assert "Network error" in result.error

    @pytest.mark.asyncio
    async def test_get_positions(self, executor):
        """Test get_positions."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "positions": [
                {"tickerSymbol": "AAPL", "position": "10.0", "avgPrice": "145.0", "unrealizedPnl": "50.0", "securityId": "sec123"}
            ]
        }
        
        with patch.object(executor, '_request', new_callable=AsyncMock, return_value=mock_response):
            positions = await executor.get_positions()
            
        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"
        assert positions[0].size == 10.0
