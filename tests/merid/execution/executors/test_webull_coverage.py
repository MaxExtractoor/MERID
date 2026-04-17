"""Comprehensive tests for merid/execution/executors/webull.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from merid.execution.executors.webull import WebullExecutor


@pytest.fixture
def executor(monkeypatch):
    """Create WebullExecutor with mocked environment."""
    monkeypatch.setenv("WEBULL_USERNAME", "test_user")
    monkeypatch.setenv("WEBULL_PASSWORD", "test_pass")
    monkeypatch.setenv("WEBULL_DID", "test_did")
    monkeypatch.setenv("WEBULL_ACCESS_TOKEN", "test_token")
    
    executor = WebullExecutor()
    return executor


# =============================================================================
# Initialization Tests
# =============================================================================

class TestWebullExecutorInit:
    """Test WebullExecutor initialization."""

    def test_init_with_credentials(self, monkeypatch):
        monkeypatch.setenv("WEBULL_USERNAME", "user123")
        monkeypatch.setenv("WEBULL_PASSWORD", "pass123")
        monkeypatch.setenv("WEBULL_DID", "device_id")
        
        executor = WebullExecutor()
        
        assert executor.venue == "webull"
        assert executor.username == "user123"
        assert executor.password == "pass123"
        assert executor.did == "device_id"

    def test_init_defaults(self, monkeypatch):
        monkeypatch.delenv("WEBULL_USERNAME", raising=False)
        monkeypatch.delenv("WEBULL_PASSWORD", raising=False)
        monkeypatch.delenv("WEBULL_DID", raising=False)
        
        executor = WebullExecutor()
        
        assert executor.username is None
        assert executor._access_token is None


# =============================================================================
# Auth Tests
# =============================================================================

class TestEnsureAuth:
    """Test _ensure_auth method."""

    @pytest.mark.asyncio
    async def test_ensure_auth_with_token(self, executor):
        executor._access_token = "existing_token"
        
        await executor._ensure_auth()
        
        assert executor._access_token == "existing_token"

    @pytest.mark.asyncio
    async def test_ensure_auth_from_env(self, executor, monkeypatch):
        monkeypatch.setenv("WEBULL_ACCESS_TOKEN", "env_token")
        executor._access_token = None
        
        await executor._ensure_auth()
        
        assert executor._access_token == "env_token"


class TestGetAuthHeaders:
    """Test _get_auth_headers method."""

    def test_auth_headers_with_token(self, executor):
        executor._access_token = "my_token"
        
        headers = executor._get_auth_headers()
        
        assert headers["Authorization"] == "Bearer my_token"

    def test_auth_headers_without_token(self, executor):
        executor._access_token = None
        
        headers = executor._get_auth_headers()
        
        assert headers["Authorization"] == "Bearer "


# =============================================================================
# Get Quote Tests
# =============================================================================

class TestGetQuote:
    """Test get_quote method."""

    @pytest.mark.asyncio
    async def test_get_quote_success(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "latestPrice": "150.50",
            "timestamp": "2024-01-01T12:00:00Z"
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            quote = await executor.get_quote("AAPL", "buy", 10.0)
        
        assert quote.symbol == "AAPL"
        assert quote.side == "buy"
        assert quote.price == 150.50
        assert quote.venue == "webull"


# =============================================================================
# Execute Trade Tests
# =============================================================================

class TestExecuteTrade:
    """Test execute_trade method."""

    @pytest.mark.asyncio
    async def test_execute_market_order_success(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "avgPrice": "151.00",
            "orderId": "order_123"
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            result = await executor.execute_trade(
                symbol="AAPL",
                side="buy",
                amount=10.0
            )
        
        assert result.success is True
        assert result.venue == "webull"
        assert result.tx_id == "order_123"
        assert result.price == 151.0

    @pytest.mark.asyncio
    async def test_execute_limit_order_success(self, executor):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "avgPrice": "145.00",
            "orderId": "limit_456"
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            result = await executor.execute_trade(
                symbol="AAPL",
                side="buy",
                amount=10.0,
                order_type="limit",
                price=145.0
            )
        
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_trade_connection_error(self, executor):
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = ConnectionError("Network error")
            
            result = await executor.execute_trade(
                symbol="AAPL",
                side="buy",
                amount=10.0
            )
        
        assert result.success is False
        assert "Webull API error" in result.error

    @pytest.mark.asyncio
    async def test_execute_trade_runtime_error(self, executor):
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = RuntimeError("API error")
            
            result = await executor.execute_trade(
                symbol="TSLA",
                side="sell",
                amount=5.0,
                price=200.0
            )
        
        assert result.success is False
        assert result.price == 200.0


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
                    "tickerSymbol": "AAPL",
                    "position": "100",
                    "avgPrice": "150.00",
                    "unrealizedPnl": "500.00",
                    "securityId": "sec_123"
                }
            ]
        }
        
        with patch.object(executor, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            positions = await executor.get_positions()
        
        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"
        assert positions[0].size == 100.0
        assert positions[0].pnl == 500.0

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
        assert WebullExecutor.venue == "webull"

    def test_default_timeout(self):
        assert WebullExecutor.default_timeout == 10.0
