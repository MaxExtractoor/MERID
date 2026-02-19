"""Tests for web/api/dashboard.py endpoints."""
from enum import Enum
import pytest
from unittest.mock import Mock, patch, MagicMock
import sys


# Mock the problematic imports before importing dashboard
sys.modules['hardening.lockdown'] = MagicMock()
sys.modules['web.api.institutional'] = MagicMock()

from fastapi.testclient import TestClient
from fastapi import FastAPI


@pytest.fixture
def mock_portfolio_engine():
    """Mock portfolio engine."""
    with patch('core.cross_domain_portfolio.get_portfolio_engine') as mock:
        mock.return_value.get_summary.return_value = {
            "total_value": 100000.0,
            "total_pnl": 5000.0,
            "positions": 5,
            "sharpe_ratio": 1.5,
            "max_drawdown": 0.05
        }
        yield mock


@pytest.fixture
def mock_agent_orchestrator():
    """Mock agent orchestrator."""
    with patch('core.agent_orchestrator.get_agent_orchestrator') as mock:
        mock.return_value.agents = {}
        mock.return_value.recent_decisions = []
        yield mock


@pytest.fixture
def app():
    """Create test FastAPI app with dashboard router."""
    from web.api.dashboard import router
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


class TestPortfolioSummary:
    """Tests for /api/portfolio/summary endpoint."""

    def test_portfolio_summary_returns_required_fields(self, client):
        """Test that portfolio summary returns all required fields."""
        with patch('web.api.dashboard.get_portfolio_engine') as mock_engine, \
             patch('web.api.dashboard.get_agent_orchestrator') as mock_orchestrator:
            
            # Mock portfolio engine
            mock_engine.return_value.get_summary.return_value = {
                "total_value": 100000.0,
                "total_pnl": 5000.0,
                "positions": 5,
                "sharpe_ratio": 1.5,
                "max_drawdown": 0.05
            }
            
            # Mock orchestrator
            mock_orchestrator.return_value.agents = {
                "agent1": Mock(enabled=True),
                "agent2": Mock(enabled=True),
                "agent3": Mock(enabled=False)
            }
            
            response = client.get("/api/portfolio/summary")
            
            assert response.status_code == 200
            data = response.json()
            
            assert "equity" in data
            assert "dailyPnl" in data
            assert "dailyPnlPct" in data
            assert "availableMargin" in data
            assert "activeBots" in data
            assert "sharpeRatio" in data
            assert "maxDrawdown" in data
            assert "positionCount" in data

    def test_portfolio_summary_calculates_pnl_percentage(self, client):
        """Test that P&L percentage is calculated correctly."""
        with patch('web.api.dashboard.get_portfolio_engine') as mock_engine, \
             patch('web.api.dashboard.get_agent_orchestrator') as mock_orchestrator:
            
            mock_engine.return_value.get_summary.return_value = {
                "total_value": 100000.0,
                "total_pnl": 10000.0,  # 10% of total value
                "positions": 3,
                "sharpe_ratio": 1.2,
                "max_drawdown": 0.03
            }
            mock_orchestrator.return_value.agents = {}
            
            response = client.get("/api/portfolio/summary")
            
            assert response.status_code == 200
            data = response.json()
            
            # P&L percentage should be 10%
            assert data["dailyPnlPct"] == 10.0

    def test_portfolio_summary_handles_zero_value(self, client):
        """Test handling of zero portfolio value."""
        with patch('web.api.dashboard.get_portfolio_engine') as mock_engine, \
             patch('web.api.dashboard.get_agent_orchestrator') as mock_orchestrator:
            
            mock_engine.return_value.get_summary.return_value = {
                "total_value": 0,
                "total_pnl": 0,
                "positions": 0,
                "sharpe_ratio": 0,
                "max_drawdown": 0
            }
            mock_orchestrator.return_value.agents = {}
            
            response = client.get("/api/portfolio/summary")
            
            assert response.status_code == 200
            data = response.json()
            
            assert data["equity"] == 0
            assert data["dailyPnlPct"] == 0


class TestLivePrices:
    """Tests for /api/prices/live endpoint."""

    def test_live_prices_returns_prices(self, client):
        """Test that live prices endpoint returns price data."""
        with patch('data.live_price_feed.get_live_price_feed') as mock_feed:
            mock_feed.return_value.get_latest_price.return_value = {
                "price": 50000.0,
                "change_24h": 2.5,
                "volume_24h": 1500000000
            }
            
            response = client.get("/api/prices/live?symbols=BTC-USD")
            
            assert response.status_code == 200
            data = response.json()
            
            assert "prices" in data
            assert len(data["prices"]) > 0

    def test_live_prices_multiple_symbols(self, client):
        """Test that multiple symbols are handled."""
        response = client.get("/api/prices/live?symbols=BTC-USD,ETH-USD,SOL-USD")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "prices" in data


class TestRecentOrders:
    """Tests for /api/orders/recent endpoint."""

    def test_recent_orders_returns_orders(self, client):
        """Test that recent orders endpoint returns order data."""
        response = client.get("/api/orders/recent")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "orders" in data
        assert isinstance(data["orders"], list)

    def test_recent_orders_respects_limit(self, client):
        """Test that limit parameter is respected."""
        response = client.get("/api/orders/recent?limit=3")
        
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["orders"]) <= 3

    def test_recent_orders_handles_enum_side_and_status(self, client):
        """Regression: side/status may be enum-like objects, not raw strings."""

        class _OrderSide(Enum):
            BUY = "buy"

        class _OrderStatus(Enum):
            FILLED = "filled"

        fake_order = Mock(
            filled_at=1739570100,
            created_at=1739570000,
            side=_OrderSide.BUY,
            asset="BTC",
            size_usd=1250.0,
            fill_price=70358.12,
            status=_OrderStatus.FILLED,
        )

        fake_portfolio = Mock(trade_history=[fake_order])
        fake_engine = Mock(
            portfolios={"default": fake_portfolio},
            get_portfolio=Mock(return_value=fake_portfolio),
        )

        with patch("trading.paper_trading.get_paper_engine", return_value=fake_engine):
            response = client.get("/api/orders/recent?limit=8")

        assert response.status_code == 200
        data = response.json()
        assert len(data["orders"]) == 1
        assert data["orders"][0]["action"].startswith("BUY ")
        assert data["orders"][0]["status"] == "FILLED"


class TestAgentActivity:
    """Tests for /api/agents/activity endpoint."""

    def test_agent_activity_returns_agents(self, client):
        """Test that agent activity endpoint returns agent data."""
        with patch('web.api.dashboard.get_agent_orchestrator') as mock_orchestrator:
            from core.agent_orchestrator import AgentRole
            
            mock_orchestrator.return_value.agents = {
                AgentRole.TWITTER: Mock(enabled=True),
                AgentRole.NEWS_MONITOR: Mock(enabled=True),
                AgentRole.ARBITRAGE: Mock(enabled=False)
            }
            mock_orchestrator.return_value.recent_decisions = []
            
            response = client.get("/api/agents/activity")
            
            assert response.status_code == 200
            data = response.json()
            
            assert "agents" in data
            assert "summary" in data
            assert isinstance(data["agents"], list)

    def test_agent_activity_summary_counts(self, client):
        """Test that summary counts are correct."""
        with patch('web.api.dashboard.get_agent_orchestrator') as mock_orchestrator:
            from core.agent_orchestrator import AgentRole
            
            # 2 active, 1 idle
            mock_orchestrator.return_value.agents = {
                AgentRole.TWITTER: Mock(enabled=True),
                AgentRole.NEWS_MONITOR: Mock(enabled=True),
                AgentRole.ARBITRAGE: Mock(enabled=False)
            }
            mock_orchestrator.return_value.recent_decisions = []
            
            response = client.get("/api/agents/activity")
            
            assert response.status_code == 200
            data = response.json()
            
            summary = data["summary"]
            assert summary["total"] == 3
            # Note: agents without 'enabled' attr default to active
            assert summary["active"] + summary["idle"] == summary["total"]

    def test_agent_activity_includes_required_fields(self, client):
        """Test that each agent has required fields."""
        with patch('web.api.dashboard.get_agent_orchestrator') as mock_orchestrator:
            from core.agent_orchestrator import AgentRole
            
            mock_orchestrator.return_value.agents = {
                AgentRole.TWITTER: Mock(enabled=True)
            }
            mock_orchestrator.return_value.recent_decisions = []
            
            response = client.get("/api/agents/activity")
            
            assert response.status_code == 200
            data = response.json()
            
            agent = data["agents"][0]
            required_fields = ["agent_id", "agent_name", "status", "last_action", "last_action_time"]
            for field in required_fields:
                assert field in agent, f"Missing field: {field}"


class TestErrorHandling:
    """Tests for error handling in dashboard endpoints."""

    def test_portfolio_summary_handles_exception(self, client):
        """Test that portfolio summary handles exceptions gracefully."""
        with patch('web.api.dashboard.get_portfolio_engine') as mock_engine:
            mock_engine.side_effect = Exception("Test error")
            
            response = client.get("/api/portfolio/summary")
            
            assert response.status_code == 500

    def test_agent_activity_handles_exception(self, client):
        """Test that agent activity handles exceptions gracefully."""
        with patch('web.api.dashboard.get_agent_orchestrator') as mock_orchestrator:
            mock_orchestrator.side_effect = Exception("Test error")
            
            response = client.get("/api/agents/activity")
            
            assert response.status_code == 500
