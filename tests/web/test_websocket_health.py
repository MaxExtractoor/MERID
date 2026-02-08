"""
Tests for WebSocket health check endpoints.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI


@pytest.fixture
def mock_dependencies():
    """Mock all WebSocket manager dependencies."""
    # Mock trades manager
    mock_trades_manager = MagicMock()
    mock_trades_manager._subscribers = set()
    mock_trades_manager.get_recent_trades.return_value = []
    
    # Mock prices manager
    mock_prices_manager = MagicMock()
    mock_prices_manager._subscribers = {}
    mock_prices_manager.get_current_prices.return_value = {
        "BTC/USD": {"price": 50000.0, "timestamp": 123456789},
        "ETH/USD": {"price": 3000.0, "timestamp": 123456789}
    }
    
    # Mock portfolio manager
    mock_portfolio_manager = MagicMock()
    mock_portfolio_manager._subscribers = set()
    mock_portfolio_manager.get_current_portfolio.return_value = {
        "equity": 10000.0,
        "cash": 9000.0,
        "total_pnl": 0.0
    }
    
    # Mock paper engine
    mock_paper_engine = MagicMock()
    mock_paper_engine.portfolios = {"user1": Mock(), "user2": Mock()}
    mock_paper_engine.portfolios["user1"].total_trades = 5
    mock_paper_engine.portfolios["user2"].total_trades = 3
    mock_paper_engine.get_global_stats.return_value = {
        "accounts": 2,
        "active_positions": 3,
        "trades_24h": 8
    }
    
    # Mock event stream
    mock_event_stream = MagicMock()
    mock_event_stream._subscribers = set([Mock(), Mock(), Mock()])
    
    with patch('web.api.ws_dedicated_streams.get_trades_manager', return_value=mock_trades_manager), \
         patch('web.api.ws_dedicated_streams.get_prices_manager', return_value=mock_prices_manager), \
         patch('web.api.ws_dedicated_streams.get_portfolio_manager', return_value=mock_portfolio_manager), \
         patch('trading.paper_trading.get_paper_engine', return_value=mock_paper_engine), \
         patch('observability.event_stream.get_event_stream', return_value=mock_event_stream):
        yield {
            'trades_manager': mock_trades_manager,
            'prices_manager': mock_prices_manager,
            'portfolio_manager': mock_portfolio_manager,
            'paper_engine': mock_paper_engine,
            'event_stream': mock_event_stream
        }


@pytest.fixture
def client(mock_dependencies):
    """Create a test client with the health check router."""
    import sys
    import importlib.util
    
    # Load the module directly
    spec = importlib.util.spec_from_file_location(
        "websocket_health",
        "c:/Dev/MERID/web/api/websocket_health.py"
    )
    websocket_health = importlib.util.module_from_spec(spec)
    sys.modules['websocket_health'] = websocket_health
    spec.loader.exec_module(websocket_health)
    
    app = FastAPI()
    app.include_router(websocket_health.router)
    
    return TestClient(app)


class TestWebSocketHealthEndpoint:
    """Test the /api/websocket/health endpoint."""
    
    def test_health_endpoint_returns_200(self, client):
        """Test that health endpoint returns 200 status."""
        response = client.get("/api/websocket/health")
        assert response.status_code == 200
    
    def test_health_endpoint_structure(self, client):
        """Test that health endpoint returns correct structure."""
        response = client.get("/api/websocket/health")
        data = response.json()
        
        assert "status" in data
        assert "timestamp" in data
        assert "endpoints" in data
        assert "summary" in data
    
    def test_health_all_endpoints_operational(self, client):
        """Test health when all endpoints are operational."""
        response = client.get("/api/websocket/health")
        data = response.json()
        
        assert data["status"] == "healthy"
        
        # Check individual endpoints
        assert "trades" in data["endpoints"]
        assert data["endpoints"]["trades"]["status"] == "operational"
        
        assert "prices" in data["endpoints"]
        assert data["endpoints"]["prices"]["status"] == "operational"
        
        assert "portfolio" in data["endpoints"]
        assert data["endpoints"]["portfolio"]["status"] == "operational"
        
        assert "paper_trading" in data["endpoints"]
        assert data["endpoints"]["paper_trading"]["status"] == "operational"
        
        assert "general" in data["endpoints"]
        assert data["endpoints"]["general"]["status"] == "operational"
    
    def test_health_summary_statistics(self, client):
        """Test that summary statistics are calculated correctly."""
        response = client.get("/api/websocket/health")
        data = response.json()
        
        summary = data["summary"]
        
        assert "total_endpoints" in summary
        assert "operational" in summary
        assert "degraded" in summary
        assert "health_percentage" in summary
        
        # All endpoints should be operational
        assert summary["total_endpoints"] == 5
        assert summary["operational"] == 5
        assert summary["degraded"] == 0
        assert summary["health_percentage"] == 100.0
    
    def test_health_includes_connection_counts(self, client, mock_dependencies):
        """Test that health includes active connection counts."""
        # Add some mock connections
        mock_dependencies['trades_manager']._subscribers = {Mock(), Mock()}
        mock_dependencies['prices_manager']._subscribers = {Mock(): {"BTC/USD"}}
        mock_dependencies['portfolio_manager']._subscribers = {Mock()}
        
        response = client.get("/api/websocket/health")
        data = response.json()
        
        assert data["endpoints"]["trades"]["active_connections"] == 2
        assert data["endpoints"]["prices"]["active_connections"] == 1
        assert data["endpoints"]["portfolio"]["active_connections"] == 1
    
    def test_health_degraded_when_endpoint_fails(self, client):
        """Test that health status is degraded when an endpoint fails."""
        # Mock one endpoint to fail
        with patch('websocket_health.get_trades_manager', side_effect=Exception("Connection failed")):
            response = client.get("/api/websocket/health")
            data = response.json()
            
            # Overall status should be degraded
            assert data["status"] == "degraded"
            
            # Failed endpoint should show error
            assert data["endpoints"]["trades"]["status"] == "error"
            assert "error" in data["endpoints"]["trades"]
            
            # Summary should reflect degradation
            assert data["summary"]["degraded"] > 0
            assert data["summary"]["health_percentage"] < 100.0


class TestWebSocketConnectionsEndpoint:
    """Test the /api/websocket/connections endpoint."""
    
    def test_connections_endpoint_returns_200(self, client):
        """Test that connections endpoint returns 200 status."""
        response = client.get("/api/websocket/connections")
        assert response.status_code == 200
    
    def test_connections_endpoint_structure(self, client):
        """Test that connections endpoint returns correct structure."""
        response = client.get("/api/websocket/connections")
        data = response.json()
        
        assert "timestamp" in data
        assert "total_connections" in data
        assert "by_endpoint" in data
    
    def test_connections_counts_all_endpoints(self, client, mock_dependencies):
        """Test that connections are counted across all endpoints."""
        # Set up mock connections
        mock_dependencies['trades_manager']._subscribers = {Mock(), Mock()}
        mock_dependencies['prices_manager']._subscribers = {Mock(): {"BTC/USD"}, Mock(): {"ETH/USD"}}
        mock_dependencies['portfolio_manager']._subscribers = {Mock()}
        
        response = client.get("/api/websocket/connections")
        data = response.json()
        
        # Total should be sum of all connections
        assert data["total_connections"] == 5  # 2 + 2 + 1
        
        # Individual counts
        assert data["by_endpoint"]["trades"]["connections"] == 2
        assert data["by_endpoint"]["prices"]["connections"] == 2
        assert data["by_endpoint"]["portfolio"]["connections"] == 1
    
    def test_connections_includes_tracked_symbols(self, client, mock_dependencies):
        """Test that connections endpoint includes tracked symbols."""
        response = client.get("/api/websocket/connections")
        data = response.json()
        
        # Should include list of tracked symbols for prices endpoint
        assert "tracked_symbols" in data["by_endpoint"]["prices"]
        symbols = data["by_endpoint"]["prices"]["tracked_symbols"]
        assert "BTC/USD" in symbols
        assert "ETH/USD" in symbols


class TestWebSocketMetricsEndpoint:
    """Test the /api/websocket/metrics endpoint."""
    
    def test_metrics_endpoint_returns_200(self, client):
        """Test that metrics endpoint returns 200 status."""
        response = client.get("/api/websocket/metrics")
        assert response.status_code == 200
    
    def test_metrics_endpoint_structure(self, client):
        """Test that metrics endpoint returns correct structure."""
        response = client.get("/api/websocket/metrics")
        data = response.json()
        
        assert "timestamp" in data
        assert "endpoints" in data
        assert "trades" in data["endpoints"]
        assert "prices" in data["endpoints"]
        assert "portfolio" in data["endpoints"]
    
    def test_metrics_trades_endpoint(self, client, mock_dependencies):
        """Test metrics for trades endpoint."""
        # Set up mock data
        mock_dependencies['trades_manager'].get_recent_trades.return_value = [
            {"order_id": "1"}, {"order_id": "2"}, {"order_id": "3"}
        ]
        mock_dependencies['trades_manager']._subscribers = {Mock(), Mock()}
        
        response = client.get("/api/websocket/metrics")
        data = response.json()
        
        trades_metrics = data["endpoints"]["trades"]
        
        assert trades_metrics["total_events_buffered"] == 3
        assert trades_metrics["active_subscribers"] == 2
        assert trades_metrics["events_per_subscriber"] == 1.5
    
    def test_metrics_prices_endpoint(self, client, mock_dependencies):
        """Test metrics for prices endpoint."""
        response = client.get("/api/websocket/metrics")
        data = response.json()
        
        prices_metrics = data["endpoints"]["prices"]
        
        assert prices_metrics["symbols_tracked"] == 2  # BTC/USD, ETH/USD
        assert "active_subscribers" in prices_metrics
    
    def test_metrics_portfolio_endpoint(self, client, mock_dependencies):
        """Test metrics for portfolio endpoint."""
        response = client.get("/api/websocket/metrics")
        data = response.json()
        
        portfolio_metrics = data["endpoints"]["portfolio"]
        
        assert portfolio_metrics["active_portfolios"] == 2
        assert portfolio_metrics["total_positions"] == 3
        assert portfolio_metrics["trades_24h"] == 8
    
    def test_metrics_handles_zero_subscribers(self, client, mock_dependencies):
        """Test that metrics handle zero subscribers gracefully."""
        # Set no subscribers
        mock_dependencies['trades_manager']._subscribers = set()
        mock_dependencies['trades_manager'].get_recent_trades.return_value = [{"order_id": "1"}]
        
        response = client.get("/api/websocket/metrics")
        data = response.json()
        
        trades_metrics = data["endpoints"]["trades"]
        
        # Should not divide by zero
        assert trades_metrics["events_per_subscriber"] == 0


class TestHealthCheckIntegration:
    """Integration tests for health check functionality."""
    
    def test_health_check_reflects_system_state(self, client, mock_dependencies):
        """Test that health check accurately reflects system state."""
        # Set up a realistic system state
        mock_dependencies['trades_manager']._subscribers = {Mock(), Mock(), Mock()}
        mock_dependencies['trades_manager'].get_recent_trades.return_value = [
            {"order_id": f"order_{i}"} for i in range(10)
        ]
        
        mock_dependencies['prices_manager']._subscribers = {
            Mock(): {"BTC/USD", "ETH/USD"},
            Mock(): {"BTC/USD"}
        }
        
        mock_dependencies['portfolio_manager']._subscribers = {Mock()}
        
        # Get all endpoints
        health_response = client.get("/api/websocket/health")
        connections_response = client.get("/api/websocket/connections")
        metrics_response = client.get("/api/websocket/metrics")
        
        # All should succeed
        assert health_response.status_code == 200
        assert connections_response.status_code == 200
        assert metrics_response.status_code == 200
        
        # Data should be consistent
        health_data = health_response.json()
        connections_data = connections_response.json()
        metrics_data = metrics_response.json()
        
        # Health should show all operational
        assert health_data["status"] == "healthy"
        
        # Connections should match
        assert connections_data["total_connections"] == 6  # 3 + 2 + 1
        
        # Metrics should show activity
        assert metrics_data["endpoints"]["trades"]["total_events_buffered"] == 10
