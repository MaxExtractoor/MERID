"""
Tests for WebSocket endpoints to verify they are functional.
"""

import pytest
import asyncio
import json
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect


@pytest.fixture
def mock_dependencies():
    """Mock all external dependencies."""
    import sys
    
    # Mock problematic imports
    sys.modules['hardening.lockdown'] = MagicMock()
    sys.modules['web.api.institutional'] = MagicMock()
    
    # Mock trading dependencies
    mock_paper_engine = MagicMock()
    mock_paper_engine.get_recent_trades.return_value = []
    mock_paper_engine.get_global_stats.return_value = {
        "accounts": 1,
        "cash": 10000.0,
        "equity": 10000.0,
        "total_pnl": 0.0,
        "active_positions": 0,
        "volume_24h": 0.0,
        "trades_24h": 0,
        "positions": []
    }
    mock_paper_engine.subscribe_to_trades.return_value = lambda: None
    mock_paper_engine.subscribe_to_summary.return_value = lambda: None
    mock_paper_engine.subscribe_to_positions.return_value = lambda: None
    
    # Mock price feed
    mock_price_feed = MagicMock()
    mock_price_feed.subscribe.return_value = None
    
    with patch('trading.paper_trading.get_paper_engine', return_value=mock_paper_engine), \
         patch('data.live_price_feed.get_live_price_feed', return_value=mock_price_feed):
        yield {
            'paper_engine': mock_paper_engine,
            'price_feed': mock_price_feed
        }


class TestWebSocketEndpoints:
    """Test WebSocket endpoint availability and basic functionality."""
    
    def test_ws_trades_endpoint_exists(self, mock_dependencies):
        """Test that a trades WebSocket endpoint exists."""
        from web.api.ws_dedicated_streams import router

        routes = [route.path for route in router.routes]
        # Actual path is /ws/trades-dedicated
        assert any("trades" in r for r in routes), f"No trades WS route found in {routes}"

    def test_ws_prices_endpoint_exists(self, mock_dependencies):
        """Test that a prices WebSocket endpoint exists."""
        from web.api.ws_dedicated_streams import router

        routes = [route.path for route in router.routes]
        # Actual path is /ws/prices-dedicated
        assert any("prices" in r for r in routes), f"No prices WS route found in {routes}"
    
    def test_ws_portfolio_endpoint_exists(self, mock_dependencies):
        """Test that /ws/portfolio endpoint exists and accepts connections."""
        from web.api.ws_dedicated_streams import router
        
        # Verify the router has the portfolio endpoint
        routes = [route.path for route in router.routes]
        assert "/ws/portfolio" in routes or "/portfolio" in routes
    
    def test_trades_manager_singleton(self, mock_dependencies):
        """Test that TradesStreamManager is a singleton."""
        from web.api.ws_dedicated_streams import get_trades_manager
        
        manager1 = get_trades_manager()
        manager2 = get_trades_manager()
        
        assert manager1 is manager2
    
    def test_prices_manager_singleton(self, mock_dependencies):
        """Test that PricesStreamManager is a singleton."""
        from web.api.ws_dedicated_streams import get_prices_manager
        
        manager1 = get_prices_manager()
        manager2 = get_prices_manager()
        
        assert manager1 is manager2
    
    def test_portfolio_manager_singleton(self, mock_dependencies):
        """Test that PortfolioStreamManager is a singleton."""
        from web.api.ws_dedicated_streams import get_portfolio_manager
        
        manager1 = get_portfolio_manager()
        manager2 = get_portfolio_manager()
        
        assert manager1 is manager2
    
    @pytest.mark.asyncio
    async def test_trades_manager_broadcast(self, mock_dependencies):
        """Test that TradesStreamManager can broadcast events."""
        from web.api.ws_dedicated_streams import get_trades_manager
        
        manager = get_trades_manager()
        
        # Create a test trade event
        trade_event = {
            "type": "order_filled",
            "symbol": "BTC/USD",
            "side": "long",
            "price": 50000.0,
            "qty": 0.1,
            "timestamp": 1234567890
        }
        
        # Broadcast should not raise an error even with no subscribers
        await manager.broadcast_trade(trade_event)
        
        # Verify event was stored in recent trades
        recent = manager.get_recent_trades(limit=10)
        assert len(recent) == 1
        assert recent[0]["symbol"] == "BTC/USD"
    
    @pytest.mark.asyncio
    async def test_prices_manager_broadcast(self, mock_dependencies):
        """Test that PricesStreamManager can broadcast price updates."""
        from web.api.ws_dedicated_streams import get_prices_manager
        
        manager = get_prices_manager()
        
        # Create a test price update
        price_data = {
            "price": 50000.0,
            "volume": 1000000.0,
            "timestamp": 1234567890
        }
        
        # Broadcast should not raise an error even with no subscribers
        await manager.broadcast_price("BTC/USD", price_data)
        
        # Verify price was stored
        current_prices = manager.get_current_prices()
        assert "BTC/USD" in current_prices
        assert current_prices["BTC/USD"]["price"] == 50000.0
    
    @pytest.mark.asyncio
    async def test_portfolio_manager_broadcast(self, mock_dependencies):
        """Test that PortfolioStreamManager can broadcast portfolio updates."""
        from web.api.ws_dedicated_streams import get_portfolio_manager
        
        manager = get_portfolio_manager()
        
        # Create a test portfolio update
        portfolio_data = {
            "equity": 10500.0,
            "cash": 10000.0,
            "total_pnl": 500.0,
            "active_positions": 2
        }
        
        # Broadcast should not raise an error even with no subscribers
        await manager.broadcast_portfolio(portfolio_data)
        
        # Verify portfolio was stored
        current_portfolio = manager.get_current_portfolio()
        assert current_portfolio is not None
        assert current_portfolio["equity"] == 10500.0
        assert current_portfolio["active_positions"] == 2


class TestExistingWebSocketEndpoints:
    """Test that existing WebSocket endpoints are properly registered."""
    
    def test_ws_general_endpoint_exists(self):
        """Test that /ws general event stream endpoint exists."""
        # SKIPPED: web.main deleted - legacy WebSocket endpoints not used in 15m production stack
        pytest.skip("Legacy web.main deleted - WebSocket endpoint tests not applicable to 15m stack")
    
    def test_ws_paper_trading_endpoint_exists(self):
        """Test that /ws/paper-trading endpoint exists."""
        # SKIPPED: web.main deleted - legacy WebSocket endpoints not used in 15m production stack
        pytest.skip("Legacy web.main deleted - WebSocket endpoint tests not applicable to 15m stack")
    
    def test_ws_kafka_endpoint_exists(self):
        """Test that /ws/kafka endpoint exists."""
        # The kafka endpoint is registered separately
        from web.api.ws_kafka_bridge import kafka_bridge_endpoint
        
        assert kafka_bridge_endpoint is not None


class TestWebSocketIntegration:
    """Integration tests for WebSocket data flow."""
    
    @pytest.mark.asyncio
    async def test_trades_stream_receives_paper_engine_events(self, mock_dependencies):
        """Test that trades stream receives events from paper trading engine."""
        from web.api.ws_dedicated_streams import get_trades_manager
        
        manager = get_trades_manager()
        paper_engine = mock_dependencies['paper_engine']
        
        # Simulate a trade event from paper engine
        trade_event = {
            "type": "trade",
            "order_id": "test_123",
            "asset": "BTC",
            "side": "long",
            "size_usd": 1000.0,
            "fill_price": 50000.0,
            "timestamp": 1234567890
        }
        
        await manager.broadcast_trade(trade_event)
        
        # Verify the event is in recent trades
        recent = manager.get_recent_trades(limit=1)
        assert len(recent) == 1
        assert recent[0]["order_id"] == "test_123"
    
    @pytest.mark.asyncio
    async def test_prices_stream_filters_by_symbol(self, mock_dependencies):
        """Test that prices stream can filter by symbol."""
        from web.api.ws_dedicated_streams import get_prices_manager
        
        manager = get_prices_manager()
        
        # Add prices for multiple symbols
        await manager.broadcast_price("BTC/USD", {"price": 50000.0, "timestamp": 123})
        await manager.broadcast_price("ETH/USD", {"price": 3000.0, "timestamp": 124})
        await manager.broadcast_price("SOL/USD", {"price": 100.0, "timestamp": 125})
        
        # Get filtered prices
        btc_only = manager.get_current_prices(["BTC/USD"])
        assert len(btc_only) == 1
        assert "BTC/USD" in btc_only
        assert "ETH/USD" not in btc_only
        
        # Get all prices
        all_prices = manager.get_current_prices()
        assert len(all_prices) == 3
