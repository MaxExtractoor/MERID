"""Comprehensive tests for merid/execution/executors/crypto_com.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import httpx

from merid.execution.executors.crypto_com import CryptoComExecutor


@pytest.fixture
def executor(monkeypatch):
    """Create CryptoComExecutor with mocked environment."""
    monkeypatch.setenv("CRYPTO_COM_API_KEY", "test_api_key")
    monkeypatch.setenv("CRYPTO_COM_API_SECRET", "test_api_secret")
    
    executor = CryptoComExecutor()
    return executor


# =============================================================================
# Initialization Tests
# =============================================================================

class TestCryptoComExecutorInit:
    """Test CryptoComExecutor initialization."""

    def test_init_with_credentials(self, monkeypatch):
        monkeypatch.setenv("CRYPTO_COM_API_KEY", "test_key")
        monkeypatch.setenv("CRYPTO_COM_API_SECRET", "test_secret")
        
        executor = CryptoComExecutor()
        
        assert executor.venue == "crypto_com"
        assert executor.api_key == "test_key"
        assert executor.api_secret == "test_secret"

    def test_init_without_credentials(self, monkeypatch):
        monkeypatch.delenv("CRYPTO_COM_API_KEY", raising=False)
        monkeypatch.delenv("CRYPTO_COM_API_SECRET", raising=False)
        
        executor = CryptoComExecutor()
        
        assert executor.api_key is None
        assert executor.api_secret is None


# =============================================================================
# Auth Headers Tests
# =============================================================================

class TestGetAuthHeaders:
    """Test _get_auth_headers method."""

    def test_auth_headers_with_credentials(self, executor):
        headers = executor._get_auth_headers()
        
        assert headers["API-Key"] == "test_api_key"
        assert headers["API-Secret"] == "test_api_secret"

    def test_auth_headers_without_credentials(self, monkeypatch):
        monkeypatch.delenv("CRYPTO_COM_API_KEY", raising=False)
        monkeypatch.delenv("CRYPTO_COM_API_SECRET", raising=False)
        
        executor = CryptoComExecutor()
        headers = executor._get_auth_headers()
        
        assert headers["API-Key"] == ""
        assert headers["API-Secret"] == ""


# =============================================================================
# Get Quote Tests
# =============================================================================

class TestGetQuote:
    """Test get_quote method."""

    @pytest.mark.asyncio
    async def test_get_quote_buy(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {"b": "50000.00", "k": "50100.00"}
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            quote = await executor.get_quote("BTC-USDT", "buy", 1.0)
        
        assert quote.symbol == "BTC-USDT"
        assert quote.side == "buy"
        assert quote.price == 50000.0
        assert quote.venue == "crypto_com"

    @pytest.mark.asyncio
    async def test_get_quote_sell(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {"b": "50000.00", "k": "50100.00"}
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            quote = await executor.get_quote("ETH-USDT", "sell", 10.0)
        
        assert quote.price == 50100.0


# =============================================================================
# Execute Trade Tests
# =============================================================================

class TestExecuteTrade:
    """Test execute_trade method."""

    @pytest.mark.asyncio
    async def test_execute_market_order_success(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "order_id": "order_123",
                "price": "50000.00"
            }
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            result = await executor.execute_trade(
                symbol="BTC-USDT",
                side="buy",
                amount=1.0
            )
        
        assert result.success is True
        assert result.venue == "crypto_com"
        assert result.tx_id == "order_123"

    @pytest.mark.asyncio
    async def test_execute_limit_order_success(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "order_id": "limit_order_456",
                "price": "48000.00"
            }
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            result = await executor.execute_trade(
                symbol="BTC-USDT",
                side="buy",
                amount=1.0,
                order_type="limit",
                price=48000.0
            )
        
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_trade_connection_error(self, executor):
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = ConnectionError("Network error")
            
            result = await executor.execute_trade(
                symbol="BTC-USDT",
                side="buy",
                amount=1.0
            )
        
        assert result.success is False
        assert "Crypto.com API error" in result.error

    @pytest.mark.asyncio
    async def test_execute_trade_runtime_error(self, executor):
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = RuntimeError("API error")
            
            result = await executor.execute_trade(
                symbol="ETH-USDT",
                side="sell",
                amount=10.0
            )
        
        assert result.success is False

    @pytest.mark.asyncio
    async def test_execute_trade_value_error(self, executor):
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = ValueError("Invalid response")
            
            result = await executor.execute_trade(
                symbol="SOL-USDT",
                side="buy",
                amount=100.0,
                price=150.0
            )
        
        assert result.success is False
        assert result.price == 150.0


# =============================================================================
# Get Positions Tests
# =============================================================================

class TestGetPositions:
    """Test get_positions method."""

    @pytest.mark.asyncio
    async def test_get_positions_success(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "list": [
                    {
                        "instrument_name": "BTCUSDT",
                        "size": "0.5",
                        "entry_price": "48000.00",
                        "unrealized_pnl": "1000.00"
                    },
                    {
                        "instrument_name": "ETHUSDT",
                        "size": "10.0",
                        "entry_price": "2800.00",
                        "unrealized_pnl": "200.00"
                    }
                ]
            }
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            positions = await executor.get_positions()
        
        assert len(positions) == 2
        assert positions[0].symbol == "BTC-USDT"
        assert positions[0].size == 0.5

    @pytest.mark.asyncio
    async def test_get_positions_empty(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"list": []}}
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            positions = await executor.get_positions()
        
        assert positions == []


# =============================================================================
# Symbol Conversion Tests
# =============================================================================

class TestSymbolConversion:
    """Test symbol conversion methods."""

    def test_symbol_to_instrument(self, executor):
        result = executor._symbol_to_instrument("BTC-USDT")
        assert result == "BTCUSDT"

    def test_symbol_to_instrument_no_dash(self, executor):
        result = executor._symbol_to_instrument("BTCUSDT")
        assert result == "BTCUSDT"

    def test_instrument_to_symbol_standard(self, executor):
        result = executor._instrument_to_symbol("BTCUSDT")
        assert result == "BTC-USDT"

    def test_instrument_to_symbol_short(self, executor):
        result = executor._instrument_to_symbol("BTC")
        assert result == "BTC"

    def test_instrument_to_symbol_exact_4_chars(self, executor):
        result = executor._instrument_to_symbol("USDT")
        assert result == "USDT"


# =============================================================================
# Class Attributes Tests
# =============================================================================

class TestClassAttributes:
    """Test class-level attributes."""

    def test_venue_name(self):
        assert CryptoComExecutor.venue == "crypto_com"

    def test_default_timeout(self):
        assert CryptoComExecutor.default_timeout == 10.0
