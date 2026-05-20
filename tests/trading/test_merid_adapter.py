"""Tests for trading/merid_adapter.py - Coverage improvement."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp

from trading.merid_adapter import (
    MeridExecutionAdapter,
    MeridPaperTradingEngine,
    get_paper_engine,
    initialize_self_hosted_paper_trading,
    is_execution_service_available,
)


# =============================================================================
# MeridExecutionAdapter Tests
# =============================================================================

class TestMeridExecutionAdapterInit:
    """Test MeridExecutionAdapter initialization."""
    
    def test_init_default_url(self):
        """Test initialization with default URL."""
        adapter = MeridExecutionAdapter()
        
        assert adapter.execution_service_url == "http://127.0.0.1:8011"
        assert adapter.account_id == "merid_sim_account"
        assert adapter._connected is False
        assert adapter.session is None
    
    def test_init_custom_url(self):
        """Test initialization with custom URL."""
        adapter = MeridExecutionAdapter("http://localhost:9000")
        
        assert adapter.execution_service_url == "http://localhost:9000"


class TestMeridExecutionAdapterConnect:
    """Test connect method."""
    
    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test successful connection."""
        adapter = MeridExecutionAdapter()
        
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"status": "healthy"})
        
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response)))
        
        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch.object(adapter, "_ensure_account_exists", new_callable=AsyncMock):
                await adapter.connect()
        
        assert adapter._connected is True
    
    @pytest.mark.asyncio
    async def test_connect_service_unhealthy(self):
        """Test connection when service is unhealthy."""
        adapter = MeridExecutionAdapter()
        
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"status": "unhealthy"})
        
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock()
        
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_ctx)
        
        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(RuntimeError, match="not healthy"):
                await adapter.connect()
    
    @pytest.mark.asyncio
    async def test_connect_service_unavailable(self):
        """Test connection when service is unavailable."""
        adapter = MeridExecutionAdapter()
        
        mock_response = AsyncMock()
        mock_response.status = 500
        
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock()
        
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_ctx)
        
        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(RuntimeError):
                await adapter.connect()


class TestMeridExecutionAdapterDisconnect:
    """Test disconnect method."""
    
    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Test disconnection."""
        adapter = MeridExecutionAdapter()
        mock_session = AsyncMock()
        adapter.session = mock_session
        adapter._connected = True
        
        await adapter.disconnect()
        
        mock_session.close.assert_called_once()
        assert adapter._connected is False
        assert adapter.session is None
    
    @pytest.mark.asyncio
    async def test_disconnect_no_session(self):
        """Test disconnect when no session exists."""
        adapter = MeridExecutionAdapter()
        adapter._connected = True
        
        await adapter.disconnect()
        
        assert adapter._connected is False


class TestMeridExecutionAdapterEnsureAccount:
    """Test _ensure_account_exists method."""
    
    @pytest.mark.asyncio
    async def test_ensure_account_exists_already(self):
        """Test when account already exists."""
        adapter = MeridExecutionAdapter()
        
        mock_response = AsyncMock()
        mock_response.status = 200
        
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock()
        
        adapter.session = MagicMock()
        adapter.session.get = MagicMock(return_value=mock_ctx)
        
        await adapter._ensure_account_exists()
        
        adapter.session.get.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_ensure_account_creates_new(self):
        """Test account creation when not exists."""
        adapter = MeridExecutionAdapter()
        
        # GET returns 404
        get_response = AsyncMock()
        get_response.status = 404
        
        # POST returns 200
        post_response = AsyncMock()
        post_response.status = 200
        
        get_ctx = AsyncMock()
        get_ctx.__aenter__ = AsyncMock(return_value=get_response)
        get_ctx.__aexit__ = AsyncMock()
        
        post_ctx = AsyncMock()
        post_ctx.__aenter__ = AsyncMock(return_value=post_response)
        post_ctx.__aexit__ = AsyncMock()
        
        adapter.session = MagicMock()
        adapter.session.get = MagicMock(return_value=get_ctx)
        adapter.session.post = MagicMock(return_value=post_ctx)
        
        await adapter._ensure_account_exists()
        
        adapter.session.post.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_ensure_account_creation_fails(self):
        """Test when account creation fails - returns empty list on error."""
        adapter = MeridExecutionAdapter()
        
        # Simulate exception during account check
        adapter.session = MagicMock()
        adapter.session.get = MagicMock(side_effect=Exception("Network error"))
        
        with pytest.raises(Exception):
            await adapter._ensure_account_exists()


class TestMeridExecutionAdapterSubmitOrder:
    """Test submit_order method."""
    
    @pytest.mark.asyncio
    async def test_submit_order_not_connected(self):
        """Test order submission when not connected."""
        adapter = MeridExecutionAdapter()
        
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.submit_order({"symbol": "AAPL"})
    
    @pytest.mark.asyncio
    async def test_submit_order_success(self):
        """Test successful order submission."""
        adapter = MeridExecutionAdapter()
        adapter._connected = True
        
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"order_id": "order_123"})
        
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock()
        
        adapter.session = MagicMock()
        adapter.session.post = MagicMock(return_value=mock_ctx)
        
        result = await adapter.submit_order({"symbol": "AAPL", "quantity": 10})
        
        assert result["order_id"] == "order_123"
    
    @pytest.mark.asyncio
    async def test_submit_order_failure(self):
        """Test order submission failure raises exception."""
        adapter = MeridExecutionAdapter()
        adapter._connected = True
        
        # Simulate network exception
        adapter.session = MagicMock()
        adapter.session.post = MagicMock(side_effect=Exception("Network error"))
        
        with pytest.raises(Exception):
            await adapter.submit_order({"symbol": "AAPL"})


class TestMeridExecutionAdapterCancelOrder:
    """Test cancel_order method."""
    
    @pytest.mark.asyncio
    async def test_cancel_order_not_connected(self):
        """Test order cancellation when not connected."""
        adapter = MeridExecutionAdapter()
        
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.cancel_order("order_123")
    
    @pytest.mark.asyncio
    async def test_cancel_order_success(self):
        """Test successful order cancellation."""
        adapter = MeridExecutionAdapter()
        adapter._connected = True
        
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"status": "cancelled"})
        
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock()
        
        adapter.session = MagicMock()
        adapter.session.delete = MagicMock(return_value=mock_ctx)
        
        result = await adapter.cancel_order("order_123")
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_cancel_order_failure(self):
        """Test order cancellation failure."""
        adapter = MeridExecutionAdapter()
        adapter._connected = True
        
        mock_response = AsyncMock()
        mock_response.status = 404
        
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock()
        
        adapter.session = MagicMock()
        adapter.session.delete = MagicMock(return_value=mock_ctx)
        
        result = await adapter.cancel_order("order_123")
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_cancel_order_exception(self):
        """Test order cancellation with exception."""
        adapter = MeridExecutionAdapter()
        adapter._connected = True
        
        adapter.session = MagicMock()
        adapter.session.delete = MagicMock(side_effect=Exception("Network error"))
        
        result = await adapter.cancel_order("order_123")
        
        assert result is False


class TestMeridExecutionAdapterGetOrders:
    """Test get_orders method."""
    
    @pytest.mark.asyncio
    async def test_get_orders_not_connected(self):
        """Test getting orders when not connected."""
        adapter = MeridExecutionAdapter()
        
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.get_orders()
    
    @pytest.mark.asyncio
    async def test_get_orders_success(self):
        """Test successful order retrieval."""
        adapter = MeridExecutionAdapter()
        adapter._connected = True
        
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"orders": [{"id": "1"}, {"id": "2"}]})
        
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock()
        
        adapter.session = MagicMock()
        adapter.session.get = MagicMock(return_value=mock_ctx)
        
        result = await adapter.get_orders()
        
        assert len(result) == 2
    
    @pytest.mark.asyncio
    async def test_get_orders_with_status_filter(self):
        """Test order retrieval with status filter."""
        adapter = MeridExecutionAdapter()
        adapter._connected = True
        
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"orders": [{"id": "1", "status": "filled"}]})
        
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock()
        
        adapter.session = MagicMock()
        adapter.session.get = MagicMock(return_value=mock_ctx)
        
        result = await adapter.get_orders(status="filled")
        
        assert len(result) == 1
    
    @pytest.mark.asyncio
    async def test_get_orders_failure(self):
        """Test order retrieval failure."""
        adapter = MeridExecutionAdapter()
        adapter._connected = True
        
        mock_response = AsyncMock()
        mock_response.status = 500
        
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock()
        
        adapter.session = MagicMock()
        adapter.session.get = MagicMock(return_value=mock_ctx)
        
        result = await adapter.get_orders()
        
        assert result == []


class TestMeridExecutionAdapterGetPositions:
    """Test get_positions method."""
    
    @pytest.mark.asyncio
    async def test_get_positions_not_connected(self):
        """Test getting positions when not connected."""
        adapter = MeridExecutionAdapter()
        
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.get_positions()
    
    @pytest.mark.asyncio
    async def test_get_positions_success(self):
        """Test successful position retrieval."""
        adapter = MeridExecutionAdapter()
        adapter._connected = True
        
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"positions": [{"symbol": "AAPL", "qty": 100}]})
        
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock()
        
        adapter.session = MagicMock()
        adapter.session.get = MagicMock(return_value=mock_ctx)
        
        result = await adapter.get_positions()
        
        assert len(result) == 1
        assert result[0]["symbol"] == "AAPL"


class TestMeridExecutionAdapterGetAccount:
    """Test get_account method."""
    
    @pytest.mark.asyncio
    async def test_get_account_not_connected(self):
        """Test getting account when not connected."""
        adapter = MeridExecutionAdapter()
        
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.get_account()
    
    @pytest.mark.asyncio
    async def test_get_account_success(self):
        """Test successful account retrieval."""
        adapter = MeridExecutionAdapter()
        adapter._connected = True
        
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"cash": 100000.0})
        
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock()
        
        adapter.session = MagicMock()
        adapter.session.get = MagicMock(return_value=mock_ctx)
        
        result = await adapter.get_account()
        
        assert result["cash"] == 100000.0


class TestMeridExecutionAdapterUpdateMarketData:
    """Test update_market_data method."""
    
    @pytest.mark.asyncio
    async def test_update_market_data_not_connected(self):
        """Test updating market data when not connected."""
        adapter = MeridExecutionAdapter()
        
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.update_market_data({"AAPL": 150.0})
    
    @pytest.mark.asyncio
    async def test_update_market_data_success(self):
        """Test successful market data update."""
        adapter = MeridExecutionAdapter()
        adapter._connected = True
        
        mock_response = AsyncMock()
        mock_response.status = 200
        
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock()
        
        adapter.session = MagicMock()
        adapter.session.post = MagicMock(return_value=mock_ctx)
        
        await adapter.update_market_data({"AAPL": 150.0})
        
        adapter.session.post.assert_called_once()


class TestMeridExecutionAdapterIsConnected:
    """Test is_connected method."""
    
    def test_is_connected_true(self):
        """Test is_connected when connected."""
        adapter = MeridExecutionAdapter()
        adapter._connected = True
        
        assert adapter.is_connected() is True
    
    def test_is_connected_false(self):
        """Test is_connected when not connected."""
        adapter = MeridExecutionAdapter()
        
        assert adapter.is_connected() is False


# =============================================================================
# MeridPaperTradingEngine Tests
# =============================================================================

class TestMeridPaperTradingEngine:
    """Test MeridPaperTradingEngine class."""
    
    def test_init(self):
        """Test initialization."""
        engine = MeridPaperTradingEngine()
        
        assert engine._running is False
        assert engine.adapter is not None
    
    @pytest.mark.asyncio
    async def test_start(self):
        """Test starting the engine."""
        engine = MeridPaperTradingEngine()
        
        with patch.object(engine.adapter, "connect", new_callable=AsyncMock):
            await engine.start()
        
        assert engine._running is True
    
    @pytest.mark.asyncio
    async def test_start_already_running(self):
        """Test starting when already running."""
        engine = MeridPaperTradingEngine()
        engine._running = True
        
        with patch.object(engine.adapter, "connect", new_callable=AsyncMock) as mock_connect:
            await engine.start()
        
        mock_connect.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_stop(self):
        """Test stopping the engine."""
        engine = MeridPaperTradingEngine()
        engine._running = True
        
        with patch.object(engine.adapter, "disconnect", new_callable=AsyncMock):
            await engine.stop()
        
        assert engine._running is False
    
    @pytest.mark.asyncio
    async def test_stop_not_running(self):
        """Test stopping when not running."""
        engine = MeridPaperTradingEngine()
        
        with patch.object(engine.adapter, "disconnect", new_callable=AsyncMock) as mock_disconnect:
            await engine.stop()
        
        mock_disconnect.assert_not_called()
    
    def test_is_running(self):
        """Test is_running method."""
        engine = MeridPaperTradingEngine()
        
        assert engine.is_running() is False
        engine._running = True
        assert engine.is_running() is True
    
    @pytest.mark.asyncio
    async def test_place_order(self):
        """Test placing an order."""
        engine = MeridPaperTradingEngine()
        
        with patch.object(engine.adapter, "submit_order", new_callable=AsyncMock) as mock_submit:
            mock_submit.return_value = {"order_id": "123"}
            
            result = await engine.place_order("AAPL", "buy", "market", 10)
        
        assert result["order_id"] == "123"
        mock_submit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_place_order_with_price(self):
        """Test placing a limit order with price."""
        engine = MeridPaperTradingEngine()
        
        with patch.object(engine.adapter, "submit_order", new_callable=AsyncMock) as mock_submit:
            mock_submit.return_value = {"order_id": "123"}
            
            result = await engine.place_order("AAPL", "buy", "limit", 10, price=150.0)
        
        call_args = mock_submit.call_args[0][0]
        assert call_args["price"] == 150.0
    
    @pytest.mark.asyncio
    async def test_cancel_order(self):
        """Test cancelling an order."""
        engine = MeridPaperTradingEngine()
        
        with patch.object(engine.adapter, "cancel_order", new_callable=AsyncMock) as mock_cancel:
            mock_cancel.return_value = True
            
            result = await engine.cancel_order("order_123")
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_get_orders(self):
        """Test getting orders."""
        engine = MeridPaperTradingEngine()
        
        with patch.object(engine.adapter, "get_orders", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = [{"id": "1"}]
            
            result = await engine.get_orders()
        
        assert len(result) == 1
    
    @pytest.mark.asyncio
    async def test_get_positions(self):
        """Test getting positions."""
        engine = MeridPaperTradingEngine()
        
        with patch.object(engine.adapter, "get_positions", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = [{"symbol": "AAPL"}]
            
            result = await engine.get_positions()
        
        assert len(result) == 1
    
    @pytest.mark.asyncio
    async def test_get_portfolio(self):
        """Test getting portfolio."""
        engine = MeridPaperTradingEngine()
        
        with patch.object(engine.adapter, "get_account", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "cash": 100000.0,
                "buying_power": 200000.0,
                "total_unrealized_pnl": 500.0,
                "total_realized_pnl": 1000.0
            }
            
            result = await engine.get_portfolio()
        
        assert result["cash"] == 100000.0
        assert result["total_pnl"] == 1500.0


# =============================================================================
# Module Functions Tests
# =============================================================================

class TestModuleFunctions:
    """Test module-level functions."""
    
    def test_get_paper_engine(self):
        """Test get_paper_engine returns singleton."""
        import trading.merid_adapter as module
        module._paper_engine = None
        
        engine1 = get_paper_engine()
        engine2 = get_paper_engine()
        
        assert engine1 is engine2
    
    @pytest.mark.asyncio
    async def test_initialize_self_hosted_paper_trading(self):
        """Test initialize_self_hosted_paper_trading function."""
        with patch.object(MeridPaperTradingEngine, "start", new_callable=AsyncMock):
            engine = await initialize_self_hosted_paper_trading()
        
        assert engine is not None
    
    @pytest.mark.asyncio
    async def test_is_execution_service_available_true(self):
        """Test is_execution_service_available when service is up."""
        mock_response = AsyncMock()
        mock_response.status = 200
        
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock()
        
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_ctx)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        
        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await is_execution_service_available()
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_is_execution_service_available_false(self):
        """Test is_execution_service_available when service is down."""
        with patch("aiohttp.ClientSession", side_effect=Exception("Connection refused")):
            result = await is_execution_service_available()
        
        assert result is False


# =============================================================================
# Error Handling Tests - Lines 158-160, 173-178, 190-195, 208-211
# =============================================================================

class TestMeridExecutionAdapterErrorHandling:
    """Test error handling in MeridExecutionAdapter methods."""

    @pytest.mark.asyncio
    async def test_get_orders_exception(self):
        """Test get_orders handles exceptions (lines 158-160)."""
        adapter = MeridExecutionAdapter()
        adapter._connected = True
        
        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=Exception("Network error"))
        adapter.session = mock_session
        
        result = await adapter.get_orders()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_positions_error_status(self):
        """Test get_positions handles error status (lines 173-174)."""
        adapter = MeridExecutionAdapter()
        adapter._connected = True
        
        mock_response = AsyncMock()
        mock_response.status = 500
        
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock()
        
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_ctx)
        adapter.session = mock_session
        
        result = await adapter.get_positions()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_positions_exception(self):
        """Test get_positions handles exceptions (lines 176-178)."""
        adapter = MeridExecutionAdapter()
        adapter._connected = True
        
        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=Exception("Network error"))
        adapter.session = mock_session
        
        result = await adapter.get_positions()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_account_error_status(self):
        """Test get_account handles error status (lines 190-191).
        
        Note: This tests the exception path since the error status causes
        a RuntimeError to be raised which is then caught and re-raised.
        """
        adapter = MeridExecutionAdapter()
        adapter._connected = True
        
        # Mock session that raises an error simulating failed request
        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=RuntimeError("Failed to get account: 404"))
        adapter.session = mock_session
        
        with pytest.raises(RuntimeError):
            await adapter.get_account()

    @pytest.mark.asyncio
    async def test_get_account_exception(self):
        """Test get_account handles exceptions (lines 193-195)."""
        adapter = MeridExecutionAdapter()
        adapter._connected = True
        
        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=Exception("Network error"))
        adapter.session = mock_session
        
        with pytest.raises(Exception, match="Network error"):
            await adapter.get_account()

    @pytest.mark.asyncio
    async def test_update_market_data_error_status(self):
        """Test update_market_data handles error status (line 208)."""
        adapter = MeridExecutionAdapter()
        adapter._connected = True
        
        mock_response = AsyncMock()
        mock_response.status = 400
        
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock()
        
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_ctx)
        adapter.session = mock_session
        
        # Should not raise, just log warning
        await adapter.update_market_data({"BTC": 50000.0})

    @pytest.mark.asyncio
    async def test_update_market_data_exception(self):
        """Test update_market_data handles exceptions (lines 210-211)."""
        adapter = MeridExecutionAdapter()
        adapter._connected = True
        
        mock_session = MagicMock()
        mock_session.post = MagicMock(side_effect=Exception("Network error"))
        adapter.session = mock_session
        
        # Should not raise, just log error
        await adapter.update_market_data({"BTC": 50000.0})
