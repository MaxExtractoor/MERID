"""Additional tests for merid/execution/executors/jupiter.py - Batch 63."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.execution.executors.jupiter import JupiterExecutor


class TestJupiterExecutorAsync:
    """Tests for JupiterExecutor async methods."""

    @pytest.fixture
    def executor(self):
        with patch.dict('os.environ', {}, clear=True):
            return JupiterExecutor()

    @pytest.mark.asyncio
    async def test_get_quote_buy(self, executor):
        """Test get_quote for buy side."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "inAmount": "1000000",
            "outAmount": "25000000",
            "id": "quote123"
        }
        
        with patch.object(executor, '_request', new_callable=AsyncMock, return_value=mock_response):
            quote = await executor.get_quote("SOL-USDC", "buy", 1.0)
            
        assert quote.symbol == "SOL-USDC"
        assert quote.side == "buy"
        assert quote.price == 25.0  # 25000000 / 1000000

    @pytest.mark.asyncio
    async def test_get_quote_sell(self, executor):
        """Test get_quote for sell side (reverses mints)."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "inAmount": "25000000",
            "outAmount": "1000000",
            "id": "quote456"
        }
        
        with patch.object(executor, '_request', new_callable=AsyncMock, return_value=mock_response):
            quote = await executor.get_quote("SOL-USDC", "sell", 25.0)
            
        assert quote.symbol == "SOL-USDC"
        assert quote.side == "sell"
        # When selling, input/output are reversed
        assert quote.metadata["input_mint"] == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

    @pytest.mark.asyncio
    async def test_execute_trade_success(self, executor):
        """Test successful trade execution."""
        mock_quote = MagicMock()
        mock_quote.json.return_value = {
            "inAmount": "1000000",
            "outAmount": "25000000",
            "id": "quote789"
        }
        
        mock_swap = MagicMock()
        mock_swap.json.return_value = {
            "txid": "tx123",
            "swapTransaction": "base64tx"
        }
        
        with patch.object(executor, '_request', new_callable=AsyncMock, side_effect=[mock_quote, mock_swap]):
            result = await executor.execute_trade("SOL-USDC", "buy", 1.0)
            
        assert result.success is True
        assert result.tx_id == "tx123"
        assert result.symbol == "SOL-USDC"

    @pytest.mark.asyncio
    async def test_execute_trade_error(self, executor):
        """Test execute_trade with API error."""
        mock_quote = MagicMock()
        mock_quote.json.return_value = {
            "inAmount": "1000000",
            "outAmount": "25000000",
            "id": "quote789"
        }
        
        # First call succeeds (quote), second call fails (swap)
        with patch.object(executor, '_request', new_callable=AsyncMock, side_effect=[mock_quote, ConnectionError("Network error")]):
            result = await executor.execute_trade("SOL-USDC", "buy", 1.0)
            
        assert result.success is False
        assert "Network error" in result.error

    @pytest.mark.asyncio
    async def test_get_positions_empty(self, executor):
        """Test get_positions returns empty list."""
        positions = await executor.get_positions()
        assert positions == []
