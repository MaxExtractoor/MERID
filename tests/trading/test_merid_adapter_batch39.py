"""Tests for trading merid_adapter module - Batch 39 Coverage."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp

from trading.merid_adapter import (
    MeridExecutionAdapter,
    MeridPaperTradingEngine,
    get_paper_engine,
    is_execution_service_available,
    initialize_self_hosted_paper_trading,
)


class TestMeridExecutionAdapter:
    """Tests for MeridExecutionAdapter class."""

    @pytest.fixture
    def adapter(self):
        return MeridExecutionAdapter(execution_service_url="http://localhost:8011")

    def test_initialization(self, adapter):
        assert adapter.execution_service_url == "http://localhost:8011"
        assert adapter.account_id == "merid_sim_account"
        assert adapter.session is None
        assert adapter._connected is False

    def test_initialization_default_url(self):
        adapter = MeridExecutionAdapter()
        assert adapter.execution_service_url == "http://127.0.0.1:8011"

    @pytest.mark.asyncio
    async def test_disconnect(self, adapter):
        mock_session = MagicMock()
        mock_session.close = AsyncMock()
        adapter.session = mock_session
        adapter._connected = True
        
        await adapter.disconnect()
        assert adapter._connected is False
        assert adapter.session is None

    @pytest.mark.asyncio
    async def test_disconnect_no_session(self, adapter):
        adapter.session = None
        adapter._connected = False
        
        await adapter.disconnect()
        assert adapter._connected is False

    def test_is_connected_not_connected(self, adapter):
        assert adapter.is_connected() is False

    def test_is_connected_connected(self, adapter):
        adapter._connected = True
        assert adapter.is_connected() is True

    @pytest.mark.asyncio
    async def test_submit_order_not_connected(self, adapter):
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.submit_order({"symbol": "BTC"})

    @pytest.mark.asyncio
    async def test_cancel_order_not_connected(self, adapter):
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.cancel_order("order_123")

    @pytest.mark.asyncio
    async def test_get_orders_not_connected(self, adapter):
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.get_orders()

    @pytest.mark.asyncio
    async def test_get_positions_not_connected(self, adapter):
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.get_positions()

    @pytest.mark.asyncio
    async def test_get_account_not_connected(self, adapter):
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.get_account()

    @pytest.mark.asyncio
    async def test_update_market_data_not_connected(self, adapter):
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.update_market_data({"price": 50000})


class TestMeridPaperTradingEngine:
    """Tests for MeridPaperTradingEngine class."""

    @pytest.fixture
    def engine(self):
        with patch('trading.merid_adapter.MeridExecutionAdapter'):
            return MeridPaperTradingEngine(execution_service_url="http://localhost:8011")

    def test_initialization(self, engine):
        assert engine._running is False
        assert engine.adapter is not None

    @pytest.mark.asyncio
    async def test_start(self, engine):
        engine.adapter.connect = AsyncMock()
        
        await engine.start()
        assert engine._running is True
        engine.adapter.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_already_running(self, engine):
        engine._running = True
        engine.adapter.connect = AsyncMock()
        
        await engine.start()
        engine.adapter.connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop(self, engine):
        engine._running = True
        engine.adapter.disconnect = AsyncMock()
        
        await engine.stop()
        assert engine._running is False
        engine.adapter.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_not_running(self, engine):
        engine._running = False
        engine.adapter.disconnect = AsyncMock()
        
        await engine.stop()
        engine.adapter.disconnect.assert_not_called()

    def test_is_running_false(self, engine):
        assert engine.is_running() is False

    def test_is_running_true(self, engine):
        engine._running = True
        assert engine.is_running() is True

    @pytest.mark.asyncio
    async def test_place_order(self, engine):
        engine.adapter.submit_order = AsyncMock(return_value={"order_id": "123"})
        
        result = await engine.place_order("BTC", "buy", "market", 1.0, price=50000.0)
        assert result == {"order_id": "123"}
        engine.adapter.submit_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_order(self, engine):
        engine.adapter.cancel_order = AsyncMock(return_value=True)
        
        result = await engine.cancel_order("order_123")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_orders(self, engine):
        engine.adapter.get_orders = AsyncMock(return_value=[{"order_id": "123"}])
        
        result = await engine.get_orders()
        assert result == [{"order_id": "123"}]

    @pytest.mark.asyncio
    async def test_get_positions(self, engine):
        engine.adapter.get_positions = AsyncMock(return_value=[{"symbol": "BTC"}])
        
        result = await engine.get_positions()
        assert result == [{"symbol": "BTC"}]

    @pytest.mark.asyncio
    async def test_get_portfolio(self, engine):
        engine.adapter.get_account = AsyncMock(return_value={
            "cash": 10000.0,
            "buying_power": 20000.0,
            "total_unrealized_pnl": 500.0,
            "total_realized_pnl": 1000.0,
        })
        
        result = await engine.get_portfolio()
        assert result["cash"] == 10000.0
        assert result["buying_power"] == 20000.0
        assert result["total_pnl"] == 1500.0


class TestUtilityFunctions:
    """Tests for utility functions."""

    @pytest.mark.asyncio
    async def test_is_execution_service_available_exception(self):
        """Test that exceptions return False."""
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.get = AsyncMock(side_effect=aiohttp.ClientError("Connection refused"))
            mock_session_class.return_value = mock_session
            
            result = await is_execution_service_available("http://localhost:8011")
            assert result is False

    @pytest.mark.asyncio
    async def test_initialize_self_hosted_paper_trading(self):
        mock_engine = MagicMock()
        mock_engine.start = AsyncMock()
        
        with patch('trading.merid_adapter.MeridPaperTradingEngine', return_value=mock_engine):
            result = await initialize_self_hosted_paper_trading("http://localhost:8011")
            assert result is mock_engine
            mock_engine.start.assert_called_once()


class TestSingleton:
    """Tests for singleton pattern."""

    def test_get_paper_engine(self):
        # Reset singleton
        import trading.merid_adapter as ma_module
        ma_module._paper_engine = None

        with patch('trading.merid_adapter.MeridPaperTradingEngine') as mock_engine:
            mock_instance = MagicMock()
            mock_engine.return_value = mock_instance
            
            engine1 = get_paper_engine()
            engine2 = get_paper_engine()
            assert engine1 is engine2
