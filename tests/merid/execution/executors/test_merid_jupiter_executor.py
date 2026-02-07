"""Comprehensive tests for merid/execution/executors/jupiter.py."""

import pytest
import respx
from httpx import Response

from merid.execution.executors.jupiter import JupiterExecutor
from merid.execution.base import Quote, TradeResult, Position


class TestJupiterExecutorInitialization:
    """Test JupiterExecutor initialization."""

    def test_default_initialization(self):
        """Test initialization with default values."""
        executor = JupiterExecutor()
        assert executor.venue == "jupiter"
        assert executor.base_url == "https://quote-api.jup.ag"
        assert executor.default_timeout == 10.0
        assert executor.rpc_url == "https://api.mainnet-beta.solana.com"

    def test_custom_api_url_from_env(self, monkeypatch):
        """Test custom API URL can be overridden via class attribute."""
        # base_url is a class attribute evaluated at import time, so patch the class
        monkeypatch.setattr(JupiterExecutor, "base_url", "https://test.jup.ag")
        executor = JupiterExecutor()
        assert executor.base_url == "https://test.jup.ag"

    def test_solana_config_from_env(self, monkeypatch):
        """Test Solana config loaded from environment."""
        monkeypatch.setenv("SOLANA_RPC_URL", "https://test.solana.com")
        monkeypatch.setenv("SOLANA_PRIVATE_KEY", "test_private_key")
        monkeypatch.setenv("SOLANA_PUBLIC_KEY", "test_public_key")
        
        executor = JupiterExecutor()
        assert executor.rpc_url == "https://test.solana.com"
        assert executor.private_key == "test_private_key"
        assert executor.public_key == "test_public_key"


class TestJupiterExecutorAuthHeaders:
    """Test JupiterExecutor authentication headers."""

    def test_get_auth_headers_empty(self):
        """Test auth headers are empty (Jupiter doesn't require auth)."""
        executor = JupiterExecutor()
        
        headers = executor._get_auth_headers()
        
        assert headers == {}


class TestJupiterExecutorSymbolToMints:
    """Test _symbol_to_mints conversion."""

    def test_known_symbols(self):
        """Test conversion for known symbols."""
        executor = JupiterExecutor()
        
        sol_usdc = executor._symbol_to_mints("SOL-USDC")
        assert sol_usdc[1] == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC mint
        
        btc_usdc = executor._symbol_to_mints("BTC-USDC")
        assert btc_usdc[1] == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        
        eth_usdc = executor._symbol_to_mints("ETH-USDC")
        assert eth_usdc[1] == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

    def test_unknown_symbol(self):
        """Test conversion for unknown symbol returns empty strings."""
        executor = JupiterExecutor()
        
        result = executor._symbol_to_mints("UNKNOWN-PAIR")
        
        assert result == ("", "")


class TestJupiterExecutorGetQuote:
    """Test JupiterExecutor get_quote method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_quote_buy_success(self):
        """Test successful buy quote retrieval."""
        executor = JupiterExecutor()
        
        route = respx.get("https://quote-api.jup.ag/v6/quote").mock(
            return_value=Response(200, json={
                "inAmount": "1000000",
                "outAmount": "45000000",
                "id": "quote_123"
            })
        )
        
        quote = await executor.get_quote("SOL-USDC", "buy", 1.0)
        
        assert isinstance(quote, Quote)
        assert quote.symbol == "SOL-USDC"
        assert quote.side == "buy"
        assert quote.price == 45.0  # 45000000 / 1000000
        assert quote.venue == "jupiter"
        assert quote.size == 1.0
        assert quote.metadata["quote_id"] == "quote_123"
        assert route.called
        
        # Verify query params - amount should be scaled by 1e6
        request = route.calls[0].request
        params = str(request.url.params)
        assert "inputMint=So11111111111111111111111111111111111111112" in params
        assert "outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" in params
        assert "amount=1000000" in params  # 1.0 * 1e6
        assert "slippageBps=100" in params

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_quote_sell_swaps_mints(self):
        """Test sell quote swaps input/output mints."""
        executor = JupiterExecutor()
        
        route = respx.get("https://quote-api.jup.ag/v6/quote").mock(
            return_value=Response(200, json={
                "inAmount": "45000000",
                "outAmount": "1000000",
                "id": "quote_456"
            })
        )
        
        quote = await executor.get_quote("SOL-USDC", "sell", 1.0)
        
        assert quote.side == "sell"
        assert quote.price == 0.022222222222222223  # 1000000 / 45000000
        
        # Verify mints are swapped for sell
        request = route.calls[0].request
        params = str(request.url.params)
        assert "inputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" in params  # USDC first
        assert "outputMint=So11111111111111111111111111111111111111112" in params  # SOL second


class TestJupiterExecutorExecuteTrade:
    """Test JupiterExecutor execute_trade method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_swap_success(self, monkeypatch):
        """Test successful swap execution."""
        monkeypatch.setenv("SOLANA_PUBLIC_KEY", "test_public_key")
        executor = JupiterExecutor()
        
        # Mock quote endpoint
        quote_route = respx.get("https://quote-api.jup.ag/v6/quote").mock(
            return_value=Response(200, json={
                "inAmount": "1000000",
                "outAmount": "45000000",
                "id": "quote_123"
            })
        )
        
        # Mock swap endpoint
        swap_route = respx.post("https://quote-api.jup.ag/v6/swap").mock(
            return_value=Response(200, json={
                "txid": "tx_abc123",
                "swapTransaction": "base64_encoded_tx"
            })
        )
        
        result = await executor.execute_trade(
            symbol="SOL-USDC",
            side="buy",
            amount=1.0
        )
        
        assert isinstance(result, TradeResult)
        assert result.success is True
        assert result.venue == "jupiter"
        assert result.symbol == "SOL-USDC"
        assert result.side == "buy"
        assert result.size == 1.0
        assert result.price == 45.0
        assert result.tx_id == "tx_abc123"
        assert result.metadata["swap_transaction"] == "base64_encoded_tx"
        assert quote_route.called
        assert swap_route.called
        
        # Verify swap payload
        request = swap_route.calls[0].request
        import json
        payload = json.loads(request.content)
        assert payload["quoteResponse"]["id"] == "quote_123"
        assert payload["userPublicKey"] == "test_public_key"
        assert payload["wrapAndUnwrapSol"] is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_swap_api_error(self, monkeypatch):
        """Test swap execution with API error."""
        monkeypatch.setenv("SOLANA_PUBLIC_KEY", "test_public_key")
        executor = JupiterExecutor()
        
        # Mock quote endpoint
        quote_route = respx.get("https://quote-api.jup.ag/v6/quote").mock(
            return_value=Response(200, json={
                "inAmount": "1000000",
                "outAmount": "45000000"
            })
        )
        
        # Mock swap endpoint with error
        swap_route = respx.post("https://quote-api.jup.ag/v6/swap").mock(
            return_value=Response(400, json={"message": "Invalid swap"})
        )
        
        from merid.execution.http_base import NonRetryableError
        with pytest.raises(NonRetryableError) as exc_info:
            await executor.execute_trade(
                symbol="SOL-USDC",
                side="buy",
                amount=1.0
            )
        
        assert "400" in str(exc_info.value)

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_swap_network_error(self, monkeypatch):
        """Test swap execution with network error."""
        monkeypatch.setenv("SOLANA_PUBLIC_KEY", "test_public_key")
        executor = JupiterExecutor()
        
        # Mock quote endpoint
        quote_route = respx.get("https://quote-api.jup.ag/v6/quote").mock(
            return_value=Response(200, json={
                "inAmount": "1000000",
                "outAmount": "45000000"
            })
        )
        
        # Mock swap endpoint with network error
        swap_route = respx.post("https://quote-api.jup.ag/v6/swap").mock(
            side_effect=ConnectionError("Network unreachable")
        )
        
        from merid.execution.http_base import ExecutionError
        with pytest.raises(ExecutionError) as exc_info:
            await executor.execute_trade(
                symbol="SOL-USDC",
                side="sell",
                amount=2.0
            )
        
        assert "Network unreachable" in str(exc_info.value)

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_swap_without_public_key(self):
        """Test swap execution without public key set."""
        executor = JupiterExecutor()
        
        # Mock quote endpoint
        quote_route = respx.get("https://quote-api.jup.ag/v6/quote").mock(
            return_value=Response(200, json={
                "inAmount": "1000000",
                "outAmount": "45000000"
            })
        )
        
        # Mock swap endpoint
        swap_route = respx.post("https://quote-api.jup.ag/v6/swap").mock(
            return_value=Response(200, json={
                "txid": "tx_123",
                "swapTransaction": "tx_data"
            })
        )
        
        result = await executor.execute_trade(
            symbol="SOL-USDC",
            side="buy",
            amount=1.0
        )
        
        # Should still work, just with None public key
        request = swap_route.calls[0].request
        import json
        payload = json.loads(request.content)
        assert payload["userPublicKey"] is None


class TestJupiterExecutorGetPositions:
    """Test JupiterExecutor get_positions method."""

    @pytest.mark.asyncio
    async def test_get_positions_returns_empty(self):
        """Test get_positions returns empty list."""
        executor = JupiterExecutor()
        
        positions = await executor.get_positions()
        
        assert positions == []
        assert isinstance(positions, list)
