"""Comprehensive tests for merid/execution/executors/kalshi.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from merid.execution.executors.kalshi import KalshiExecutor


@pytest.fixture
def executor(monkeypatch):
    """Create KalshiExecutor with mocked environment."""
    monkeypatch.setenv("KALSHI_API_KEY_ID", "test_api_key")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PEM", "test_private_key")
    
    executor = KalshiExecutor()
    return executor


# =============================================================================
# Initialization Tests
# =============================================================================

class TestKalshiExecutorInit:
    """Test KalshiExecutor initialization."""

    def test_init_with_credentials(self, monkeypatch):
        monkeypatch.setenv("KALSHI_API_KEY_ID", "api_key_id")
        monkeypatch.setenv("KALSHI_PRIVATE_KEY_PEM", "private_key")
        
        executor = KalshiExecutor()
        
        assert executor.venue == "kalshi"
        assert executor.api_key_id == "api_key_id"
        assert executor.private_key_pem == "private_key"

    def test_init_defaults(self, monkeypatch):
        monkeypatch.delenv("KALSHI_API_KEY_ID", raising=False)
        monkeypatch.delenv("KALSHI_PRIVATE_KEY_PEM", raising=False)
        
        executor = KalshiExecutor()
        
        assert executor.api_key_id is None


class TestGetAuthHeaders:
    """Test _get_auth_headers method."""

    def test_auth_headers_with_key(self, executor):
        headers = executor._get_auth_headers()
        assert headers["KALSHI-API-KEY-ID"] == "test_api_key"

    def test_auth_headers_without_key(self, monkeypatch):
        monkeypatch.delenv("KALSHI_API_KEY_ID", raising=False)
        executor = KalshiExecutor()
        headers = executor._get_auth_headers()
        assert headers["KALSHI-API-KEY-ID"] == ""


# =============================================================================
# Get Quote Tests
# =============================================================================

class TestGetQuote:
    """Test get_quote method."""

    @pytest.mark.asyncio
    async def test_get_quote_success(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {"price": "0.65"}
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            quote = await executor.get_quote("PRES-2024-DEM", "buy", 100.0)
        
        assert quote.symbol == "PRES-2024-DEM"
        assert quote.side == "buy"
        assert quote.price == 0.65
        assert quote.venue == "kalshi"


# =============================================================================
# Execute Trade Tests
# =============================================================================

class TestExecuteTrade:
    """Test execute_trade method."""

    @pytest.mark.asyncio
    async def test_execute_market_order_success(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "order_id": "order_123",
            "executed_price": "0.55"
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            result = await executor.execute_trade(
                symbol="PRES-2024-DEM",
                side="buy",
                amount=100.0
            )
        
        assert result.success is True
        assert result.venue == "kalshi"
        assert result.tx_id == "order_123"

    @pytest.mark.asyncio
    async def test_execute_limit_order_success(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "order_id": "limit_456",
            "executed_price": "0.50"
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            result = await executor.execute_trade(
                symbol="PRES-2024-REP",
                side="sell",
                amount=50.0,
                order_type="limit",
                price=0.50
            )
        
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_trade_connection_error(self, executor):
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = ConnectionError("Network error")
            
            result = await executor.execute_trade(
                symbol="PRES-2024-DEM",
                side="buy",
                amount=100.0
            )
        
        assert result.success is False
        assert "Kalshi API error" in result.error

    @pytest.mark.asyncio
    async def test_execute_trade_runtime_error(self, executor):
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = RuntimeError("API error")
            
            result = await executor.execute_trade(
                symbol="PRES-2024-REP",
                side="sell",
                amount=50.0,
                price=0.45
            )
        
        assert result.success is False
        assert result.price == 0.45


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
                    "ticker": "PRES-2024-DEM",
                    "count": "100",
                    "avg_price": "0.55",
                    "pnl": "10.00"
                }
            ]
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            positions = await executor.get_positions()
        
        assert len(positions) == 1
        assert positions[0].symbol == "PRES-2024-DEM"
        assert positions[0].size == 100.0

    @pytest.mark.asyncio
    async def test_get_positions_empty(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {"positions": []}
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            positions = await executor.get_positions()
        
        assert positions == []


# =============================================================================
# Symbol/Ticker Conversion Tests
# =============================================================================

class TestSymbolTickerConversion:
    """Test symbol/ticker conversion methods."""

    def test_symbol_to_ticker_known(self, executor):
        result = executor._symbol_to_ticker("PRES-2024-DEM")
        assert result == "PRES-2024-DEM"

    def test_symbol_to_ticker_unknown(self, executor):
        result = executor._symbol_to_ticker("UNKNOWN-MARKET")
        assert result == "UNKNOWN-MARKET"

    def test_ticker_to_symbol_known(self, executor):
        result = executor._ticker_to_symbol("PRES-2024-REP")
        assert result == "PRES-2024-REP"

    def test_ticker_to_symbol_unknown(self, executor):
        result = executor._ticker_to_symbol("UNKNOWN-TICKER")
        assert result == "UNKNOWN-TICKER"


# =============================================================================
# Class Attributes Tests
# =============================================================================

class TestClassAttributes:
    """Test class-level attributes."""

    def test_venue_name(self):
        assert KalshiExecutor.venue == "kalshi"

    def test_default_timeout(self):
        assert KalshiExecutor.default_timeout == 10.0
