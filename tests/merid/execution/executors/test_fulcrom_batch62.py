"""Additional tests for merid/execution/executors/fulcrom.py - Batch 62."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.execution.executors.fulcrom import FulcromExecutor


class TestFulcromExecutorAsync:
    """Tests for FulcromExecutor async methods."""

    @pytest.fixture
    def executor(self):
        with patch.dict('os.environ', {}, clear=True):
            return FulcromExecutor()

    @pytest.mark.asyncio
    async def test_get_quote(self, executor):
        """Test get_quote."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "price": "0.08",
            "id": "quote123"
        }
        
        with patch.object(executor, '_request', new_callable=AsyncMock, return_value=mock_response):
            quote = await executor.get_quote("CRO-USDC", "buy", 100.0)
            
        assert quote.symbol == "CRO-USDC"
        assert quote.side == "buy"
        assert quote.price == 0.08
        assert quote.metadata["quote_id"] == "quote123"

    @pytest.mark.asyncio
    async def test_execute_trade_market(self, executor):
        """Test execute_trade with market order."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": "order123",
            "executed_price": "0.081",
            "tx_hash": "0xabc123"
        }
        
        with patch.object(executor, '_request', new_callable=AsyncMock, return_value=mock_response):
            result = await executor.execute_trade("CRO-USDC", "buy", 100.0)
            
        assert result.success is True
        assert result.symbol == "CRO-USDC"
        assert result.tx_id == "0xabc123"

    @pytest.mark.asyncio
    async def test_execute_trade_limit(self, executor):
        """Test execute_trade with limit order."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": "order456",
            "executed_price": "0.075",
            "tx_hash": "0xdef456"
        }
        
        with patch.object(executor, '_request', new_callable=AsyncMock, return_value=mock_response):
            result = await executor.execute_trade("CRO-USDC", "sell", 50.0, order_type="limit", price=0.075)
            
        assert result.success is True
        assert result.price == 0.075

    @pytest.mark.asyncio
    async def test_execute_trade_error(self, executor):
        """Test execute_trade with API error."""
        with patch.object(executor, '_request', new_callable=AsyncMock, side_effect=ValueError("Invalid price")):
            result = await executor.execute_trade("CRO-USDC", "buy", 100.0)
            
        assert result.success is False
        assert "Invalid price" in result.error

    @pytest.mark.asyncio
    async def test_get_positions(self, executor):
        """Test get_positions."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "positions": [
                {"id": "pos1", "base": "CRO", "quote": "USDC", "size": "1000.0", "entry_price": "0.07", "pnl": "10.0"}
            ]
        }
        
        with patch.object(executor, '_request', new_callable=AsyncMock, return_value=mock_response):
            positions = await executor.get_positions()
            
        assert len(positions) == 1
        assert positions[0].symbol == "CRO-USDC"
        assert positions[0].size == 1000.0
