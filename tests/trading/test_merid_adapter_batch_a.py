"""Tests for trading/merid_adapter.py - Batch A."""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch, call

from trading.merid_adapter import (
    MeridExecutionAdapter, MeridPaperTradingEngine,
    get_paper_engine, is_execution_service_available
)


class TestMeridExecutionAdapter:
    """Test MeridExecutionAdapter class."""

    @pytest.fixture
    def adapter(self):
        return MeridExecutionAdapter(execution_service_url="http://test:8011")

    @pytest.mark.asyncio
    async def test_connect_success(self, adapter, mocker):
        """Test successful connection."""
        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"status": "healthy"})

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=mock_cm)

        # Mock _ensure_account_exists
        adapter._ensure_account_exists = AsyncMock()

        mocker.patch("aiohttp.ClientSession", return_value=mock_session)

        await adapter.connect()

        assert adapter._connected is True
        assert adapter.session is mock_session

    @pytest.mark.asyncio
    async def test_connect_unhealthy_service(self, adapter, mocker):
        """Test connection to unhealthy service."""
        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.status = 500

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=mock_cm)

        mocker.patch("aiohttp.ClientSession", return_value=mock_session)

        with pytest.raises(RuntimeError, match="Execution service not healthy"):
            await adapter.connect()

    @pytest.mark.asyncio
    async def test_disconnect(self, adapter):
        """Test disconnection."""
        mock_session = AsyncMock()
        adapter.session = mock_session
        adapter._connected = True

        await adapter.disconnect()

        assert adapter._connected is False
        assert adapter.session is None
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_account_exists_account_found(self, adapter, mocker):
        """Test account exists check when account is found."""
        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.status = 200

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=mock_cm)
        adapter.session = mock_session

        # Should not raise
        await adapter._ensure_account_exists()

    @pytest.mark.asyncio
    async def test_ensure_account_exists_creates_account(self, adapter, mocker):
        """Test account creation when account not found."""
        mock_session = AsyncMock()
        mock_response_404 = MagicMock()
        mock_response_404.status = 404
        mock_response_200 = MagicMock()
        mock_response_200.status = 200

        mock_cm_404 = MagicMock()
        mock_cm_404.__aenter__ = AsyncMock(return_value=mock_response_404)
        mock_cm_404.__aexit__ = AsyncMock(return_value=False)

        mock_cm_200 = MagicMock()
        mock_cm_200.__aenter__ = AsyncMock(return_value=mock_response_200)
        mock_cm_200.__aexit__ = AsyncMock(return_value=False)

        mock_session.get = MagicMock(return_value=mock_cm_404)
        mock_session.post = MagicMock(return_value=mock_cm_200)
        adapter.session = mock_session

        await adapter._ensure_account_exists()

        mock_session.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_order_success(self, adapter):
        """Test successful order submission."""
        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"order_id": "123", "status": "submitted"})

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_cm)
        adapter.session = mock_session
        adapter._connected = True

        result = await adapter.submit_order({"symbol": "AAPL", "quantity": 10})

        assert result["order_id"] == "123"
        # account_id is added to order_data before sending, not returned

    @pytest.mark.asyncio
    async def test_submit_order_not_connected(self, adapter):
        """Test submit_order when not connected."""
        with pytest.raises(RuntimeError, match="Not connected to execution service"):
            await adapter.submit_order({"symbol": "AAPL"})

    @pytest.mark.asyncio
    async def test_submit_order_failure(self, adapter):
        """Test order submission failure."""
        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.status = 400
        mock_response.text = AsyncMock(return_value="Bad request")

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_cm)
        adapter.session = mock_session
        adapter._connected = True

        with pytest.raises(RuntimeError, match="Order submission failed"):
            await adapter.submit_order({"symbol": "AAPL"})

    @pytest.mark.asyncio
    async def test_cancel_order_success(self, adapter):
        """Test successful order cancellation."""
        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"status": "cancelled"})

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.delete = MagicMock(return_value=mock_cm)
        adapter.session = mock_session
        adapter._connected = True

        result = await adapter.cancel_order("order_123")

        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_order_failure(self, adapter):
        """Test order cancellation failure."""
        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.status = 404

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.delete = MagicMock(return_value=mock_cm)
        adapter.session = mock_session
        adapter._connected = True

        result = await adapter.cancel_order("order_123")

        assert result is False

    @pytest.mark.asyncio
    async def test_get_orders_success(self, adapter):
        """Test getting orders."""
        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"orders": [{"id": "1"}, {"id": "2"}]})

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=mock_cm)
        adapter.session = mock_session
        adapter._connected = True

        result = await adapter.get_orders()

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_orders_with_status(self, adapter):
        """Test getting orders with status filter."""
        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"orders": []})

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=mock_cm)
        adapter.session = mock_session
        adapter._connected = True

        await adapter.get_orders(status="open")

        call_args = mock_session.get.call_args
        assert call_args[1]["params"]["status"] == "open"

    @pytest.mark.asyncio
    async def test_get_positions_success(self, adapter):
        """Test getting positions."""
        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"positions": [{"symbol": "AAPL", "qty": 10}]})

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=mock_cm)
        adapter.session = mock_session
        adapter._connected = True

        result = await adapter.get_positions()

        assert len(result) == 1
        assert result[0]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_get_account_success(self, adapter):
        """Test getting account information."""
        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"cash": 100000, "buying_power": 200000})

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=mock_cm)
        adapter.session = mock_session
        adapter._connected = True

        result = await adapter.get_account()

        assert result["cash"] == 100000

    @pytest.mark.asyncio
    async def test_update_market_data_success(self, adapter):
        """Test updating market data."""
        mock_session = AsyncMock()
        mock_response = MagicMock()
        mock_response.status = 200

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_cm)
        adapter.session = mock_session
        adapter._connected = True

        await adapter.update_market_data({"AAPL": {"price": 150.0}})

        mock_session.post.assert_called_once()

    def test_is_connected(self, adapter):
        """Test is_connected property."""
        assert adapter.is_connected() is False
        adapter._connected = True
        assert adapter.is_connected() is True


class TestMeridPaperTradingEngine:
    """Test MeridPaperTradingEngine class."""

    @pytest.fixture
    def engine(self):
        return MeridPaperTradingEngine(execution_service_url="http://test:8011")

    @pytest.mark.asyncio
    async def test_start_engine(self, engine, mocker):
        """Test starting the engine."""
        mocker.patch.object(engine.adapter, "connect", new_callable=AsyncMock)

        await engine.start()

        assert engine._running is True
        engine.adapter.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_already_running(self, engine, mocker):
        """Test starting when already running."""
        engine._running = True

        await engine.start()

        # Should not try to connect again
        assert engine._running is True

    @pytest.mark.asyncio
    async def test_stop_engine(self, engine, mocker):
        """Test stopping the engine."""
        engine._running = True
        mocker.patch.object(engine.adapter, "disconnect", new_callable=AsyncMock)

        await engine.stop()

        assert engine._running is False
        engine.adapter.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_not_running(self, engine, mocker):
        """Test stopping when not running."""
        engine._running = False

        await engine.stop()

        # Should not raise
        assert engine._running is False

    def test_is_running(self, engine):
        """Test is_running property."""
        assert engine.is_running() is False
        engine._running = True
        assert engine.is_running() is True

    @pytest.mark.asyncio
    async def test_place_order(self, engine, mocker):
        """Test placing order through engine."""
        mocker.patch.object(engine.adapter, "submit_order", new_callable=AsyncMock, return_value={"order_id": "123"})

        result = await engine.place_order("AAPL", "buy", "market", 10, price=150.0)

        assert result["order_id"] == "123"
        call_args = engine.adapter.submit_order.call_args[0][0]
        assert call_args["symbol"] == "AAPL"
        assert call_args["price"] == 150.0

    @pytest.mark.asyncio
    async def test_cancel_order(self, engine, mocker):
        """Test cancelling order through engine."""
        mocker.patch.object(engine.adapter, "cancel_order", new_callable=AsyncMock, return_value=True)

        result = await engine.cancel_order("order_123")

        assert result is True
        engine.adapter.cancel_order.assert_called_once_with("order_123")

    @pytest.mark.asyncio
    async def test_get_orders(self, engine, mocker):
        """Test getting orders through engine."""
        mocker.patch.object(engine.adapter, "get_orders", new_callable=AsyncMock, return_value=[{"id": "1"}])

        result = await engine.get_orders("open")

        assert len(result) == 1
        engine.adapter.get_orders.assert_called_once_with("open")

    @pytest.mark.asyncio
    async def test_get_positions(self, engine, mocker):
        """Test getting positions through engine."""
        mocker.patch.object(engine.adapter, "get_positions", new_callable=AsyncMock, return_value=[{"symbol": "AAPL"}])

        result = await engine.get_positions()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_portfolio(self, engine, mocker):
        """Test getting portfolio information."""
        mocker.patch.object(engine.adapter, "get_account", new_callable=AsyncMock, return_value={
            "cash": 100000,
            "buying_power": 200000,
            "total_unrealized_pnl": 5000,
            "total_realized_pnl": 2000
        })

        result = await engine.get_portfolio()

        assert result["cash"] == 100000
        assert result["buying_power"] == 200000
        assert result["total_pnl"] == 7000


class TestGlobalFunctions:
    """Test global utility functions."""

    def test_get_paper_engine_singleton(self):
        """Test get_paper_engine returns singleton."""
        # Reset global state
        import trading.merid_adapter as ma
        ma._paper_engine = None

        engine1 = get_paper_engine()
        engine2 = get_paper_engine()

        assert engine1 is engine2


class AsyncContextManagerMock:
    """Helper for mocking async context managers."""
    def __init__(self, status=200):
        self.status = status
        self.response = MagicMock()
        self.response.status = status

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, exc_type, exc, tb):
        return False


class TestIsExecutionServiceAvailable:
    """Test is_execution_service_available function."""

    @pytest.mark.asyncio
    async def test_is_execution_service_available_exception(self, mocker):
        """Test service available check when exception occurs."""
        mocker.patch("aiohttp.ClientSession", side_effect=Exception("Connection refused"))

        result = await is_execution_service_available("http://test:8011")

        assert result is False
