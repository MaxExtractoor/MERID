"""Tests for MERID adapter - Batch 24 Coverage."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from trading.merid_adapter import (
    MeridExecutionAdapter,
    MeridPaperTradingEngine,
    get_paper_engine,
    is_execution_service_available
)


class TestMeridExecutionAdapter:
    """Tests for MeridExecutionAdapter."""

    @pytest.fixture
    def adapter(self):
        """Create adapter."""
        return MeridExecutionAdapter(execution_service_url="http://localhost:8012")

    def test_initialization(self, adapter):
        """Test adapter initialization."""
        assert adapter.execution_service_url == "http://localhost:8012"
        assert adapter.account_id == "merid_sim_account"
        assert adapter._connected is False

    @pytest.mark.asyncio
    async def test_disconnect(self, adapter):
        """Test disconnection."""
        adapter.session = MagicMock()
        adapter.session.close = AsyncMock()
        adapter._connected = True
        
        await adapter.disconnect()
        
        assert adapter._connected is False

    def test_is_connected(self, adapter):
        """Test connection status check."""
        assert adapter.is_connected() is False
        adapter._connected = True
        assert adapter.is_connected() is True

    @pytest.mark.asyncio
    async def test_submit_order_not_connected(self, adapter):
        """Test order submission when not connected."""
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.submit_order({"symbol": "BTC"})

    @pytest.mark.asyncio
    async def test_cancel_order_not_connected(self, adapter):
        """Test order cancellation when not connected."""
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.cancel_order("order_123")

    @pytest.mark.asyncio
    async def test_get_orders_not_connected(self, adapter):
        """Test get orders when not connected."""
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.get_orders()


class TestMeridPaperTradingEngine:
    """Tests for MeridPaperTradingEngine."""

    @pytest.fixture
    def engine(self):
        """Create paper trading engine."""
        return MeridPaperTradingEngine()

    def test_initialization(self, engine):
        """Test engine initialization."""
        assert engine._running is False

    def test_is_running(self, engine):
        """Test checking if engine is running."""
        assert engine.is_running() is False
        engine._running = True
        assert engine.is_running() is True


class TestGetPaperEngine:
    """Tests for get_paper_engine singleton."""

    def test_singleton(self):
        """Test singleton pattern."""
        import trading.merid_adapter as merid_module
        merid_module._paper_engine = None
        
        engine1 = get_paper_engine()
        engine2 = get_paper_engine()
        
        assert engine1 is engine2
