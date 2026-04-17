"""Tests for the risk agent endpoints (drawdown-history, equity-history, metrics)."""
import pytest
from fastapi.testclient import TestClient


class TestRiskAgentEndpoints:
    """Test the /api/v1/risk/agents/{agentId}/* endpoints."""

    def test_agent_metrics_returns_404_for_unknown_agent(self) -> None:
        """Agent metrics should return 404 for unknown agent."""
        from web.main import app
        client = TestClient(app)
        response = client.get("/api/v1/risk/agents/nonexistent-agent/metrics")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "nonexistent-agent" in data["detail"]

    def test_agent_drawdown_history_returns_valid_structure(self) -> None:
        """Drawdown history endpoint returns valid structure."""
        from web.main import app
        client = TestClient(app)
        response = client.get("/api/v1/risk/agents/test-agent/drawdown-history")
        assert response.status_code == 200

        data = response.json()
        assert "agent_id" in data
        assert data["agent_id"] == "test-agent"
        assert "history" in data
        assert isinstance(data["history"], list)
        assert "count" in data
        assert isinstance(data["count"], int)
        assert data["count"] == len(data["history"])

    def test_agent_equity_history_returns_valid_structure(self) -> None:
        """Equity history endpoint returns valid structure."""
        from web.main import app
        client = TestClient(app)
        response = client.get("/api/v1/risk/agents/test-agent/equity-history")
        assert response.status_code == 200

        data = response.json()
        assert "agent_id" in data
        assert data["agent_id"] == "test-agent"
        assert "history" in data
        assert isinstance(data["history"], list)
        assert "count" in data
        assert isinstance(data["count"], int)
        assert data["count"] == len(data["history"])

    def test_agent_metrics_with_registered_agent(self) -> None:
        """Agent metrics should work after registering an agent."""
        from web.main import app
        from merid.risk.agent_metrics import get_agent_metrics_tracker

        # Register an agent
        tracker = get_agent_metrics_tracker()
        tracker.register_agent("test-agent-123", role="analyst", initial_equity=10000.0)

        # Now get metrics
        client = TestClient(app)
        response = client.get("/api/v1/risk/agents/test-agent-123/metrics")
        assert response.status_code == 200

        data = response.json()
        assert data["agent_id"] == "test-agent-123"
        assert data["role"] == "analyst"
        assert "current_equity" in data
        assert "total_pnl" in data
        assert "sharpe_ratio" in data
        assert "max_drawdown" in data
        assert "win_rate" in data

    def test_agent_metrics_history_with_data(self) -> None:
        """Agent metrics history should reflect recorded trades."""
        from web.main import app
        from merid.risk.agent_metrics import get_agent_metrics_tracker

        # Register an agent and record some trades
        tracker = get_agent_metrics_tracker()
        agent = tracker.register_agent("test-agent-with-trades", role="trader", initial_equity=10000.0)

        # Record a winning trade
        tracker.record_trade("test-agent-with-trades", pnl=100.0, is_win=True, trade_size=1000.0)

        # Record a losing trade
        tracker.record_trade("test-agent-with-trades", pnl=-50.0, is_win=False, trade_size=1000.0)

        # Check metrics
        client = TestClient(app)
        response = client.get("/api/v1/risk/agents/test-agent-with-trades/metrics")
        assert response.status_code == 200
        data = response.json()

        assert data["total_trades"] == 2
        assert data["winning_trades"] == 1
        assert data["losing_trades"] == 1
        assert data["total_pnl"] == 50.0  # 100 - 50
        assert data["win_rate"] == 0.5

        # Check equity history
        response = client.get("/api/v1/risk/agents/test-agent-with-trades/equity-history")
        assert response.status_code == 200
        data = response.json()
        assert len(data["history"]) >= 2  # Should have recorded equity updates

        # Check drawdown history
        response = client.get("/api/v1/risk/agents/test-agent-with-trades/drawdown-history")
        assert response.status_code == 200
        data = response.json()
        assert "history" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
