"""Comprehensive tests for Jupiter executor - HTTP mocking with respx."""

import pytest
import respx
from httpx import Response
from unittest.mock import MagicMock

from merid.execution.executors.jupiter import JupiterExecutor
from merid.execution.base import Quote, TradeResult, Position


@pytest.fixture
def executor():
    """Create test Jupiter executor."""
    return JupiterExecutor()


class TestJupiterExecutorInitialization:
    """Test JupiterExecutor initialization."""
    
    def test_initialization(self, executor):
        """Test executor initialization."""
        assert executor.venue == "jupiter"
        assert executor.base_url == "https://quote-api.jup.ag"
        assert executor.default_timeout == 10.0
    
    def test_auth_headers_empty(self, executor):
        """Test auth headers returns empty dict."""
        headers = executor._get_auth_headers()
        assert headers == {}


@respx.mock
class TestJupiterExecutorQuotes:
    """Test JupiterExecutor quote functionality."""
    
    async def test_get_quote_buy(self, executor):
        """Test get_quote for buy side."""
        route = respx.get(
            "https://quote-api.jup.ag/v6/quote",
            params={
                "inputMint": "So11111111111111111111111111111111111111112",
                "outputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "amount": "1000000",  # 1 SOL in lamports
                "slippageBps": "100"
            }
        ).mock(
            return_value=Response(200, json={
                "inAmount": "1000000000",
                "outAmount": "50000000",
                "id": "quote_123"
            })
        )
        
        quote = await executor.get_quote("SOL-USDC", "buy", 1.0)
        
        assert isinstance(quote, Quote)
        assert quote.symbol == "SOL-USDC"
        assert quote.side == "buy"
        assert quote.price == 0.05  # 50000000 / 1000000000
        assert quote.venue == "jupiter"
        assert quote.size == 1.0
        assert route.called
    
    async def test_get_quote_sell(self, executor):
        """Test get_quote for sell side swaps mints."""
        route = respx.get(
            "https://quote-api.jup.ag/v6/quote",
            params={
                "inputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # Swapped for sell
                "outputMint": "So11111111111111111111111111111111111111112",
                "amount": "1000000",
                "slippageBps": "100"
            }
        ).mock(
            return_value=Response(200, json={
                "inAmount": "1000000",
                "outAmount": "1000000000",
                "id": "quote_456"
            })
        )
        
        quote = await executor.get_quote("SOL-USDC", "sell", 1.0)
        
        assert quote.symbol == "SOL-USDC"
        assert quote.side == "sell"
        assert quote.price == 1000.0  # 1000000000 / 1000000
        assert route.called


@respx.mock
class TestJupiterExecutorTrading:
    """Test JupiterExecutor trading functionality."""
    
    async def test_execute_trade_success(self, executor):
        """Test execute_trade success."""
        # Mock quote endpoint
        respx.get(
            "https://quote-api.jup.ag/v6/quote",
            params={
                "inputMint": "So11111111111111111111111111111111111111112",
                "outputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "amount": "1000000",
                "slippageBps": "100"
            }
        ).mock(
            return_value=Response(200, json={
                "inAmount": "1000000000",
                "outAmount": "50000000",
                "id": "quote_123"
            })
        )
        
        # Mock swap endpoint
        route = respx.post("https://quote-api.jup.ag/v6/swap").mock(
            return_value=Response(200, json={
                "txid": "tx_123",
                "swapTransaction": "base64_encoded_tx"
            })
        )
        
        result = await executor.execute_trade("SOL-USDC", "buy", 1.0)
        
        assert isinstance(result, TradeResult)
        assert result.success is True
        assert result.venue == "jupiter"
        assert result.symbol == "SOL-USDC"
        assert result.side == "buy"
        assert result.size == 1.0
        assert result.price == 0.05
        assert result.tx_id == "tx_123"
        assert route.called
    
    async def test_execute_trade_error(self, executor):
        """Test execute_trade with API error."""
        # Mock quote endpoint
        respx.get(
            "https://quote-api.jup.ag/v6/quote",
            params={
                "inputMint": "So11111111111111111111111111111111111111112",
                "outputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "amount": "1000000",
                "slippageBps": "100"
            }
        ).mock(
            return_value=Response(200, json={
                "inAmount": "1000000000",
                "outAmount": "50000000",
                "id": "quote_123"
            })
        )
        
        # Mock swap endpoint with error
        respx.post("https://quote-api.jup.ag/v6/swap").mock(
            return_value=Response(400, text="Insufficient liquidity")
        )
        
        result = await executor.execute_trade("SOL-USDC", "buy", 1.0)
        
        assert isinstance(result, TradeResult)
        assert result.success is False
        assert "jupiter" in result.error.lower()


class TestJupiterExecutorPositions:
    """Test JupiterExecutor positions functionality."""
    
    async def test_get_positions_empty(self, executor):
        """Test get_positions returns empty list."""
        positions = await executor.get_positions()
        
        assert positions == []
        assert isinstance(positions, list)


class TestJupiterExecutorHelpers:
    """Test JupiterExecutor helper methods."""
    
    def test_symbol_to_mints_sol_usdc(self, executor):
        """Test SOL-USDC symbol conversion."""
        input_mint, output_mint = executor._symbol_to_mints("SOL-USDC")
        assert input_mint == "So11111111111111111111111111111111111111112"
        assert output_mint == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    
    def test_symbol_to_mints_btc_usdc(self, executor):
        """Test BTC-USDC symbol conversion."""
        input_mint, output_mint = executor._symbol_to_mints("BTC-USDC")
        assert input_mint == "9n4nbM75f5Ui33ZbPYXn59EwSgE8CGsHtAeTH5YFeJ9E"
        assert output_mint == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    
    def test_symbol_to_mints_unknown(self, executor):
        """Test unknown symbol conversion returns empty strings."""
        input_mint, output_mint = executor._symbol_to_mints("UNKNOWN")
        assert input_mint == ""
        assert output_mint == ""
