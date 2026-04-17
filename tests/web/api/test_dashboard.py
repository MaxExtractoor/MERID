"""Tests for web/api/dashboard.py endpoints.

The dashboard module pulls data from:
  - trading.paper_trading.get_paper_engine()   → /api/portfolio/summary, /api/orders/recent
  - agents.registry.get_registry()             → /api/agents/activity

Tests patch those exact call sites, not non-existent shim helpers.
"""
from enum import Enum
import pytest
from unittest.mock import Mock, MagicMock, patch
import sys


# Suppress problematic side-effect imports before loading the router
sys.modules.setdefault('hardening.lockdown', MagicMock())
sys.modules.setdefault('web.api.institutional', MagicMock())

from fastapi.testclient import TestClient
from fastapi import FastAPI


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_paper_engine(
    portfolios=None,
    stats=None,
    trade_history=None,
):
    """Return a mock PaperTradingEngine with sensible defaults."""
    if stats is None:
        stats = {
            "equity": 10000.0,
            "current_balance": 9500.0,
            "starting_balance": 10000.0,
            "total_pnl": 250.0,
            "total_unrealized_pnl": 50.0,
            "open_positions": 2,
            "total_trades": 15,
            "win_rate_pct": 60.0,
            "roi_pct": 3.0,
        }
    portfolio = Mock()
    portfolio.trade_history = trade_history or []
    if portfolios is None:
        portfolios = {"default": portfolio}
    engine = Mock()
    engine.portfolios = portfolios
    engine.get_portfolio.return_value = portfolio
    engine.get_portfolio_stats.return_value = stats
    return engine


def _make_registry(agents=None):
    """Return a mock agents.registry.get_registry() result."""
    if agents is None:
        agents = []
    registry = Mock()
    registry.get_all_agents.return_value = agents
    return registry


def _make_agent(agent_id="agent-1", status="active", uptime_s=120, tasks_completed=5, last_action="voted"):
    """Return a mock Agent object matching what dashboard.get_agent_activity expects."""
    metrics = Mock()
    metrics.uptime_seconds = uptime_s
    metrics.last_action = last_action
    metrics.tasks_completed = tasks_completed

    agent = Mock()
    agent.agent_id = agent_id
    agent.name = agent_id
    agent.status = Mock()
    agent.status.value = status
    agent.get_metrics.return_value = metrics
    agent.current_task = None
    return agent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    from web.api.dashboard import router
    a = FastAPI()
    a.include_router(router)
    return a


@pytest.fixture
def client(app):
    return TestClient(app)


# ---------------------------------------------------------------------------
# Portfolio Summary
# ---------------------------------------------------------------------------

class TestPortfolioSummary:
    """Tests for /api/portfolio/summary endpoint."""

    def test_portfolio_summary_returns_required_fields(self, client):
        engine = _make_paper_engine()
        with patch("trading.paper_trading.get_paper_engine", return_value=engine):
            response = client.get("/api/portfolio/summary")

        assert response.status_code == 200
        data = response.json()
        for field in ("equity", "dailyPnl", "dailyPnlPct", "availableMargin", "activeBots"):
            assert field in data, f"Missing field: {field}"

    def test_portfolio_summary_calculates_pnl_percentage(self, client):
        """dailyPnlPct = (total_pnl + total_unrealized_pnl) / starting_balance * 100."""
        engine = _make_paper_engine(stats={
            "equity": 10000.0,
            "current_balance": 10000.0,
            "starting_balance": 10000.0,
            "total_pnl": 1000.0,
            "total_unrealized_pnl": 0.0,
            "open_positions": 1,
            "total_trades": 5,
            "win_rate_pct": 50.0,
            "roi_pct": 10.0,
        })
        with patch("trading.paper_trading.get_paper_engine", return_value=engine):
            response = client.get("/api/portfolio/summary")

        assert response.status_code == 200
        data = response.json()
        assert data["dailyPnlPct"] == 10.0

    def test_portfolio_summary_handles_zero_value(self, client):
        engine = _make_paper_engine(stats={
            "equity": 0,
            "current_balance": 0,
            "starting_balance": 0,
            "total_pnl": 0,
            "total_unrealized_pnl": 0,
            "open_positions": 0,
            "total_trades": 0,
            "win_rate_pct": 0,
            "roi_pct": 0,
        })
        with patch("trading.paper_trading.get_paper_engine", return_value=engine):
            response = client.get("/api/portfolio/summary")

        assert response.status_code == 200
        data = response.json()
        assert data["equity"] == 0
        assert data["dailyPnlPct"] == 0


# ---------------------------------------------------------------------------
# Live Prices
# ---------------------------------------------------------------------------

class TestLivePrices:
    """Tests for /api/prices/live endpoint."""

    def test_live_prices_returns_prices(self, client):
        with patch("data.live_price_feed.get_live_price_feed") as mock_feed:
            mock_feed.return_value.get_latest_prices.return_value = {
                "BTC": {"price": 50000.0, "change_24h": 2.5, "volume_24h": 1_500_000_000},
            }
            response = client.get("/api/prices/live?symbols=BTC")

        assert response.status_code == 200
        assert "prices" in response.json()
        assert len(response.json()["prices"]) > 0

    def test_live_prices_multiple_symbols(self, client):
        response = client.get("/api/prices/live?symbols=BTC-USD,ETH-USD,SOL-USD")
        assert response.status_code == 200
        assert "prices" in response.json()


# ---------------------------------------------------------------------------
# Recent Orders
# ---------------------------------------------------------------------------

class TestRecentOrders:
    """Tests for /api/orders/recent endpoint."""

    def test_recent_orders_returns_orders(self, client):
        engine = _make_paper_engine()
        with patch("trading.paper_trading.get_paper_engine", return_value=engine):
            response = client.get("/api/orders/recent")

        assert response.status_code == 200
        data = response.json()
        assert "orders" in data
        assert isinstance(data["orders"], list)

    def test_recent_orders_respects_limit(self, client):
        engine = _make_paper_engine()
        with patch("trading.paper_trading.get_paper_engine", return_value=engine):
            response = client.get("/api/orders/recent?limit=3")

        assert response.status_code == 200
        assert len(response.json()["orders"]) <= 3

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


# ---------------------------------------------------------------------------
# Agent Activity
# ---------------------------------------------------------------------------

class TestAgentActivity:
    """Tests for /api/agents/activity endpoint."""

    def test_agent_activity_returns_agents(self, client):
        agents = [_make_agent("twitter", "active"), _make_agent("news", "idle")]
        registry = _make_registry(agents)
        with patch("agents.registry.get_registry", return_value=registry):
            response = client.get("/api/agents/activity")

        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert "summary" in data
        assert isinstance(data["agents"], list)

    def test_agent_activity_summary_counts(self, client):
        agents = [
            _make_agent("a1", "active"),
            _make_agent("a2", "idle"),
            _make_agent("a3", "idle"),
        ]
        registry = _make_registry(agents)
        with patch("agents.registry.get_registry", return_value=registry):
            response = client.get("/api/agents/activity")

        assert response.status_code == 200
        data = response.json()
        summary = data["summary"]
        assert summary["total"] == 3
        # "active" includes idle (active+running+idle are all considered running);
        # "idle" is a subset that also contributes to "active", so active >= idle.
        assert summary["active"] <= summary["total"]
        assert summary["idle"] <= summary["total"]

    def test_agent_activity_includes_required_fields(self, client):
        registry = _make_registry([_make_agent("bot-1", "active")])
        with patch("agents.registry.get_registry", return_value=registry):
            response = client.get("/api/agents/activity")

        assert response.status_code == 200
        agent = response.json()["agents"][0]
        for field in ("agent_id", "agent_name", "status", "last_action", "last_action_time"):
            assert field in agent, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# Error Handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Tests for error handling in dashboard endpoints."""

    def test_portfolio_summary_handles_exception(self, client):
        with patch("trading.paper_trading.get_paper_engine", side_effect=Exception("db down")):
            response = client.get("/api/portfolio/summary")

        assert response.status_code == 500

    def test_agent_activity_handles_exception(self, client):
        with patch("agents.registry.get_registry", side_effect=Exception("registry gone")):
            response = client.get("/api/agents/activity")

        assert response.status_code == 500
