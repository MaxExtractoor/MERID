"""Comprehensive tests for merid/execution/executors/jupiter.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from merid.execution.executors.jupiter import JupiterExecutor


@pytest.fixture
def executor(monkeypatch):
    """Create JupiterExecutor with mocked environment."""
    monkeypatch.setenv("SOLANA_RPC_URL", "https://test.solana.rpc")
    monkeypatch.setenv("SOLANA_PRIVATE_KEY", "test_private_key")
    monkeypatch.setenv("SOLANA_PUBLIC_KEY", "test_public_key")
    
    executor = JupiterExecutor()
    return executor


# =============================================================================
# Initialization Tests
# =============================================================================

class TestJupiterExecutorInit:
    """Test JupiterExecutor initialization."""

    def test_init_with_credentials(self, monkeypatch):
        monkeypatch.setenv("SOLANA_RPC_URL", "https://custom.rpc")
        monkeypatch.setenv("SOLANA_PRIVATE_KEY", "priv_key")
        monkeypatch.setenv("SOLANA_PUBLIC_KEY", "pub_key")
        
        executor = JupiterExecutor()
        
        assert executor.venue == "jupiter"
        assert executor.rpc_url == "https://custom.rpc"
        assert executor.private_key == "priv_key"
        assert executor.public_key == "pub_key"

    def test_init_defaults(self, monkeypatch):
        monkeypatch.delenv("SOLANA_RPC_URL", raising=False)
        monkeypatch.delenv("SOLANA_PRIVATE_KEY", raising=False)
        monkeypatch.delenv("SOLANA_PUBLIC_KEY", raising=False)
        
        executor = JupiterExecutor()
        
        assert executor.rpc_url == "https://api.mainnet-beta.solana.com"
        assert executor.private_key is None


# =============================================================================
# Auth Headers Tests
# =============================================================================

class TestGetAuthHeaders:
    """Test _get_auth_headers method."""

    def test_auth_headers_empty(self, executor):
        headers = executor._get_auth_headers()
        assert headers == {}


# =============================================================================
# Get Quote Tests
# =============================================================================

class TestGetQuote:
    """Test get_quote method."""

    @pytest.mark.asyncio
    async def test_get_quote_buy(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "inAmount": "1000000",
            "outAmount": "100",
            "id": "quote_123"
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            quote = await executor.get_quote("SOL-USDC", "buy", 1.0)
        
        assert quote.symbol == "SOL-USDC"
        assert quote.side == "buy"
        assert quote.venue == "jupiter"

    @pytest.mark.asyncio
    async def test_get_quote_sell(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "inAmount": "100",
            "outAmount": "1000000",
            "id": "quote_456"
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            quote = await executor.get_quote("SOL-USDC", "sell", 1.0)
        
        assert quote.side == "sell"


# =============================================================================
# Execute Trade Tests
# =============================================================================

class TestExecuteTrade:
    """Test execute_trade method."""

    @pytest.mark.asyncio
    async def test_execute_trade_buy_success(self, executor):
        mock_quote_response = MagicMock()
        mock_quote_response.json.return_value = {
            "inAmount": "1000000",
            "outAmount": "100",
            "id": "quote_abc"
        }
        
        mock_swap_response = MagicMock()
        mock_swap_response.json.return_value = {
            "txid": "tx_xyz",
            "swapTransaction": "encoded_tx"
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = [mock_quote_response, mock_swap_response]
            
            result = await executor.execute_trade(
                symbol="SOL-USDC",
                side="buy",
                amount=1.0
            )
        
        assert result.success is True
        assert result.venue == "jupiter"
        assert result.tx_id == "tx_xyz"

    @pytest.mark.asyncio
    async def test_execute_trade_sell_success(self, executor):
        mock_quote_response = MagicMock()
        mock_quote_response.json.return_value = {
            "inAmount": "100",
            "outAmount": "1000000",
            "id": "quote_sell"
        }
        
        mock_swap_response = MagicMock()
        mock_swap_response.json.return_value = {"txid": "tx_sell"}
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = [mock_quote_response, mock_swap_response]
            
            result = await executor.execute_trade(
                symbol="SOL-USDC",
                side="sell",
                amount=5.0
            )
        
        assert result.success is True
        assert result.side == "sell"

    @pytest.mark.asyncio
    async def test_execute_trade_connection_error(self, executor):
        mock_quote_response = MagicMock()
        mock_quote_response.json.return_value = {
            "inAmount": "1000000",
            "outAmount": "100"
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = [mock_quote_response, ConnectionError("Network error")]
            
            result = await executor.execute_trade(
                symbol="SOL-USDC",
                side="buy",
                amount=1.0
            )
        
        assert result.success is False
        assert "Jupiter API error" in result.error

    @pytest.mark.asyncio
    async def test_execute_trade_runtime_error(self, executor):
        mock_quote_response = MagicMock()
        mock_quote_response.json.return_value = {
            "inAmount": "1000000",
            "outAmount": "100"
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = [mock_quote_response, RuntimeError("Swap failed")]
            
            result = await executor.execute_trade(
                symbol="ETH-USDC",
                side="buy",
                amount=0.5,
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
    async def test_get_positions_returns_empty(self, executor):
        positions = await executor.get_positions()
        assert positions == []


# =============================================================================
# Symbol to Mints Tests
# =============================================================================

class TestSymbolToMints:
    """Test _symbol_to_mints method."""

    def test_sol_usdc(self, executor):
        input_mint, output_mint = executor._symbol_to_mints("SOL-USDC")
        assert input_mint == "So11111111111111111111111111111111111111112"
        assert "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" in output_mint

    def test_btc_usdc(self, executor):
        input_mint, output_mint = executor._symbol_to_mints("BTC-USDC")
        assert input_mint != ""
        assert output_mint != ""

    def test_eth_usdc(self, executor):
        input_mint, output_mint = executor._symbol_to_mints("ETH-USDC")
        assert input_mint != ""

    def test_unknown_symbol(self, executor):
        input_mint, output_mint = executor._symbol_to_mints("UNKNOWN-PAIR")
        assert input_mint == ""
        assert output_mint == ""


# =============================================================================
# Class Attributes Tests
# =============================================================================

class TestClassAttributes:
    """Test class-level attributes."""

    def test_venue_name(self):
        assert JupiterExecutor.venue == "jupiter"

    def test_default_timeout(self):
        assert JupiterExecutor.default_timeout == 10.0
