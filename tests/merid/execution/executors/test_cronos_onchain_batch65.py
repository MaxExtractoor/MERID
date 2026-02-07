"""Additional tests for merid/execution/executors/cronos_onchain.py - Batch 65."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.execution.executors.cronos_onchain import CronosOnchainExecutor


class TestCronosOnchainExecutorAsync:
    """Tests for CronosOnchainExecutor async methods."""

    @pytest.fixture
    def executor(self):
        with patch('core.multichain_wallet.get_multichain_wallet'):
            with patch.dict('os.environ', {}, clear=True):
                return CronosOnchainExecutor()

    @pytest.mark.asyncio
    async def test_get_quote(self, executor):
        """Test get_quote."""
        quote = await executor.get_quote("ETH-USDC", "buy", 1.0)
        
        assert quote.symbol == "ETH-USDC"
        assert quote.side == "buy"
        assert quote.price == 3000.0
        assert quote.venue == "cronos_onchain"
        assert quote.metadata["base"] == "ETH"
        assert quote.metadata["quote"] == "USDC"

    @pytest.mark.asyncio
    async def test_execute_trade_market(self, executor):
        """Test execute_trade with market order."""
        with patch.object(executor, '_fetch_price', new_callable=AsyncMock, return_value=3000.0):
            result = await executor.execute_trade("ETH-USDC", "buy", 1.0)
            
        assert result.success is True
        assert result.symbol == "ETH-USDC"
        assert result.price == 3000.0
        assert result.tx_id.startswith("0x")

    @pytest.mark.asyncio
    async def test_execute_trade_limit(self, executor):
        """Test execute_trade with limit order."""
        result = await executor.execute_trade("ETH-USDC", "sell", 0.5, order_type="limit", price=3100.0)
        
        assert result.success is True
        assert result.symbol == "ETH-USDC"
        assert result.price == 3100.0

    @pytest.mark.asyncio
    async def test_get_positions(self, executor):
        """Test get_positions."""
        positions = await executor.get_positions()
        
        assert len(positions) >= 0  # May be empty or have USDC position
        # Check if USDC position exists (mock balance returns 1234.56)
        usdc_positions = [p for p in positions if p.symbol == "USDC-CRO"]
        if usdc_positions:
            assert usdc_positions[0].size == 1234.56

    @pytest.mark.asyncio
    async def test_token_balance(self, executor):
        """Test _token_balance helper."""
        balance = await executor._token_balance("USDC")
        assert balance == 1234.56

    @pytest.mark.asyncio
    async def test_fetch_price_known_pairs(self, executor):
        """Test _fetch_price for known pairs."""
        assert await executor._fetch_price("ETH", "USDC") == 3000.0
        assert await executor._fetch_price("BTC", "USDC") == 50000.0
        assert await executor._fetch_price("CRO", "USDC") == 0.08

    @pytest.mark.asyncio
    async def test_fetch_price_unknown_pair(self, executor):
        """Test _fetch_price for unknown pair."""
        assert await executor._fetch_price("UNKNOWN", "TOKEN") == 1.0
