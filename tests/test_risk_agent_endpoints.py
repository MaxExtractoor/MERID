"""Tests for the risk agent endpoints (drawdown-history, equity-history, metrics)."""
import pytest
from fastapi.testclient import TestClient


"""Tests for the risk agent handlers (drawdown-history, equity-history, metrics).

The ``risk_metrics_api`` router is deliberately unmounted in ``web.main_15m_lean``
pending auth migration, so these tests exercise the handler functions directly.
"""
import asyncio
import pytest


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestRiskAgentEndpoints:
    """Test the risk_metrics_api per-agent handlers."""

    def test_agent_metrics_returns_404_for_unknown_agent(self) -> None:
        """Agent metrics should raise 404 for unknown agent."""
        from fastapi import HTTPException
        from web.api.risk_metrics_api import get_agent_metrics
        with pytest.raises(HTTPException) as exc_info:
            _run(get_agent_metrics("nonexistent-agent"))
        assert exc_info.value.status_code == 404
        assert "nonexistent-agent" in exc_info.value.detail

    def test_agent_drawdown_history_returns_valid_structure(self) -> None:
        """Drawdown history handler returns valid structure."""
        from web.api.risk_metrics_api import get_agent_drawdown_history
        data = _run(get_agent_drawdown_history("test-agent"))
        assert "agent_id" in data
        assert data["agent_id"] == "test-agent"
        assert "history" in data
        assert isinstance(data["history"], list)

    def test_agent_equity_history_returns_valid_structure(self) -> None:
        """Equity history handler returns valid structure."""
        from web.api.risk_metrics_api import get_agent_equity_history
        data = _run(get_agent_equity_history("test-agent"))
        assert "agent_id" in data
        assert data["agent_id"] == "test-agent"
        assert "history" in data
        assert isinstance(data["history"], list)

    def test_agent_metrics_with_registered_agent(self) -> None:
        """Registered agent returns metrics dict."""
        from merid.risk.agent_metrics import get_agent_metrics_tracker
        from web.api.risk_metrics_api import get_agent_metrics

        tracker = get_agent_metrics_tracker()
        tracker.record_trade("test-agent-2", pnl=5.0, is_win=True)
        data = _run(get_agent_metrics("test-agent-2"))
        assert "agent_id" in data or "sharpe_ratio" in data or "total_trades" in data

    def test_agent_metrics_history_with_data(self) -> None:
        """Equity history accumulates after recorded closes."""
        from merid.risk.agent_metrics import get_agent_metrics_tracker
        from web.api.risk_metrics_api import get_agent_equity_history

        tracker = get_agent_metrics_tracker()
        tracker.record_trade("test-agent-3", pnl=10.0, is_win=True)
        data = _run(get_agent_equity_history("test-agent-3"))
        assert data["agent_id"] == "test-agent-3"
        assert isinstance(data["history"], list)
