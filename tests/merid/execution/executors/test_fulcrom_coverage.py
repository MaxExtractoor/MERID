"""Comprehensive tests for merid/execution/executors/fulcrom.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from merid.execution.executors.fulcrom import FulcromExecutor


@pytest.fixture
def executor(monkeypatch):
    """Create FulcromExecutor with mocked environment."""
    monkeypatch.setenv("CRONOS_RPC_URL", "https://test.cronos.rpc")
    monkeypatch.setenv("CRONOS_PRIVATE_KEY", "test_private_key")
    
    executor = FulcromExecutor()
    return executor


# =============================================================================
# Initialization Tests
# =============================================================================

class TestFulcromExecutorInit:
    """Test FulcromExecutor initialization."""

    def test_init_with_credentials(self, monkeypatch):
        monkeypatch.setenv("CRONOS_RPC_URL", "https://custom.cronos.rpc")
        monkeypatch.setenv("CRONOS_PRIVATE_KEY", "priv_key")
        
        executor = FulcromExecutor()
        
        assert executor.venue == "fulcrom"
        assert executor.rpc_url == "https://custom.cronos.rpc"
        assert executor.private_key == "priv_key"

    def test_init_defaults(self, monkeypatch):
        monkeypatch.delenv("CRONOS_RPC_URL", raising=False)
        monkeypatch.delenv("CRONOS_PRIVATE_KEY", raising=False)
        
        executor = FulcromExecutor()
        
        assert executor.rpc_url == "https://evm-cronos.crypto.org"
        assert executor.private_key is None


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
        mock_response.json.return_value = {"price": "100.50", "id": "quote_123"}
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            quote = await executor.get_quote("CRO-USDC", "buy", 100.0)
        
        assert quote.symbol == "CRO-USDC"
        assert quote.side == "buy"
        assert quote.price == 100.50
        assert quote.venue == "fulcrom"

    @pytest.mark.asyncio
    async def test_get_quote_sell(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {"price": "99.00"}
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            quote = await executor.get_quote("ETH-USDC", "sell", 10.0)
        
        assert quote.side == "sell"
        assert quote.price == 99.0


# =============================================================================
# Execute Trade Tests
# =============================================================================

class TestExecuteTrade:
    """Test execute_trade method."""

    @pytest.mark.asyncio
    async def test_execute_market_order_success(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "executed_price": "100.25",
            "tx_hash": "0xabc123",
            "id": "order_456"
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            result = await executor.execute_trade(
                symbol="CRO-USDC",
                side="buy",
                amount=100.0
            )
        
        assert result.success is True
        assert result.venue == "fulcrom"
        assert result.tx_id == "0xabc123"
        assert result.price == 100.25

    @pytest.mark.asyncio
    async def test_execute_limit_order_success(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "executed_price": "95.00",
            "tx_hash": "0xdef456",
            "id": "limit_order"
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            result = await executor.execute_trade(
                symbol="CRO-USDC",
                side="buy",
                amount=50.0,
                order_type="limit",
                price=95.0
            )
        
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_trade_connection_error(self, executor):
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = ConnectionError("Network error")
            
            result = await executor.execute_trade(
                symbol="CRO-USDC",
                side="buy",
                amount=100.0
            )
        
        assert result.success is False
        assert "Fulcrom API error" in result.error

    @pytest.mark.asyncio
    async def test_execute_trade_runtime_error(self, executor):
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = RuntimeError("API error")
            
            result = await executor.execute_trade(
                symbol="ETH-USDC",
                side="sell",
                amount=10.0,
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
    async def test_get_positions_success(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "positions": [
                {
                    "base": "CRO",
                    "quote": "USDC",
                    "size": "1000",
                    "entry_price": "0.10",
                    "pnl": "50.00",
                    "id": "pos_1"
                }
            ]
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            positions = await executor.get_positions()
        
        assert len(positions) == 1
        assert positions[0].symbol == "CRO-USDC"
        assert positions[0].size == 1000.0

    @pytest.mark.asyncio
    async def test_get_positions_empty(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {"positions": []}
        
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
        assert FulcromExecutor.venue == "fulcrom"

    def test_default_timeout(self):
        assert FulcromExecutor.default_timeout == 10.0
