"""Regression tests for Session 3 audit fixes.

Covers:
  1. ExecutionGuard.summary() exists and returns promotion_enforcement
  2. AgentMetrics.to_dict() handles float('inf') and float('nan') safely (JSON-serializable)
  3. SwarmOrchestrator.review_portfolio_risk() handles portfolio snapshots
  4. PerpContextService._fetch_premium_index cascading fallback
"""

import asyncio
import json
import math
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── 1. ExecutionGuard.summary() ──────────────────────────────────────

class TestExecutionGuardSummary:
    """ExecutionGuard must have a summary() method for the operator endpoint."""

    def _make_guard(self):
        from merid.execution_guard import ExecutionGuard
        guard = ExecutionGuard.__new__(ExecutionGuard)
        guard._global_kill_switch = False
        guard._global_kill_reason = ""
        guard._cqi_config = MagicMock()
        guard._domain_caps = {}
        guard._venue_caps = {}
        guard._last_cqi = {"prediction": 0.75}
        guard._cooldown_seconds = 5.0
        guard._last_execution_at = 0.0
        guard._trade_log = []
        guard.enforce_promotion = True
        guard._promotion_report = None
        guard._promotion_eligible_domains = None
        guard._promotion_blocked_agents = None
        guard._promotion_report_ts = 0.0
        return guard

    def test_summary_method_exists(self):
        guard = self._make_guard()
        assert hasattr(guard, "summary"), "ExecutionGuard must have summary() method"

    def test_summary_returns_dict(self):
        guard = self._make_guard()
        result = guard.summary()
        assert isinstance(result, dict)

    def test_summary_includes_promotion_enforcement(self):
        guard = self._make_guard()
        result = guard.summary()
        assert "promotion_enforcement" in result
        promo = result["promotion_enforcement"]
        assert "enforce_promotion" in promo
        assert "eligible_domains" in promo
        assert "blocked_agents" in promo

    def test_summary_includes_get_status_keys(self):
        guard = self._make_guard()
        result = guard.summary()
        assert "global_kill_switch" in result
        assert "last_cqi" in result
        assert result["last_cqi"]["prediction"] == 0.75

    def test_summary_with_active_promotion(self):
        guard = self._make_guard()
        guard._promotion_eligible_domains = {"prediction", "crypto"}
        guard._promotion_blocked_agents = {"agent-bad"}
        result = guard.summary()
        promo = result["promotion_enforcement"]
        assert "prediction" in promo["eligible_domains"]
        assert "agent-bad" in promo["blocked_agents"]

    def test_summary_is_json_serializable(self):
        guard = self._make_guard()
        result = guard.summary()
        # Must not raise
        serialized = json.dumps(result, default=str)
        assert len(serialized) > 0


# ── 2. AgentMetrics.to_dict() inf/nan safety ─────────────────────────

class TestAgentMetricsJsonSafety:
    """AgentMetrics.to_dict() must produce JSON-serializable output even with inf/nan."""

    def _make_metrics(self, **overrides):
        from merid.prediction.agent_performance_tracker import AgentMetrics
        defaults = {
            "agent_id": "test-agent",
            "total_fills": 10,
            "total_closes": 5,
            "wins": 5,
            "losses": 0,
            "total_pnl_usd": Decimal("100.00"),
        }
        defaults.update(overrides)
        return AgentMetrics(**defaults)

    def test_normal_values_serializable(self):
        m = self._make_metrics(sharpe_ratio=1.5, profit_factor=2.0)
        d = m.to_dict()
        serialized = json.dumps(d)
        assert '"profit_factor": 2.0' in serialized

    def test_inf_profit_factor_serializable(self):
        """When gross_losses=0, profit_factor=inf — must not crash JSON."""
        m = self._make_metrics(profit_factor=float("inf"))
        d = m.to_dict()
        # Must not raise ValueError
        serialized = json.dumps(d)
        assert "9999" in serialized  # capped to 9999.0

    def test_negative_inf_serializable(self):
        m = self._make_metrics(calmar_ratio=float("-inf"))
        d = m.to_dict()
        serialized = json.dumps(d)
        assert "-9999" in serialized

    def test_nan_serializable(self):
        m = self._make_metrics(sortino_ratio=float("nan"))
        d = m.to_dict()
        serialized = json.dumps(d)
        # nan should be replaced with 0.0
        parsed = json.loads(serialized)
        assert parsed["sortino_ratio"] == 0.0

    def test_safe_float_static_method(self):
        from merid.prediction.agent_performance_tracker import AgentMetrics
        assert AgentMetrics._safe_float(float("inf")) == 9999.0
        assert AgentMetrics._safe_float(float("-inf")) == -9999.0
        assert AgentMetrics._safe_float(float("nan")) == 0.0
        assert AgentMetrics._safe_float(1.23456, 2) == 1.23

    def test_all_ratio_fields_safe(self):
        """All four ratio fields must survive inf without crash."""
        m = self._make_metrics(
            sharpe_ratio=float("inf"),
            sortino_ratio=float("-inf"),
            calmar_ratio=float("nan"),
            profit_factor=float("inf"),
        )
        d = m.to_dict()
        serialized = json.dumps(d)
        parsed = json.loads(serialized)
        assert parsed["sharpe_ratio"] == 9999.0
        assert parsed["sortino_ratio"] == -9999.0
        assert parsed["calmar_ratio"] == 0.0
        assert parsed["profit_factor"] == 9999.0


# ── 3. SwarmOrchestrator.review_portfolio_risk() ─────────────────────

class TestSwarmOrchestratorPortfolioRisk:
    """review_portfolio_risk must handle portfolio snapshots (not trade intents)."""

    def _make_orchestrator(self):
        from merid.swarm.orchestrator import SwarmOrchestrator
        return SwarmOrchestrator(enabled=True)

    def test_method_exists(self):
        orch = self._make_orchestrator()
        assert hasattr(orch, "review_portfolio_risk")

    def test_healthy_portfolio_approved(self):
        orch = self._make_orchestrator()
        result = asyncio.get_event_loop().run_until_complete(
            orch.review_portfolio_risk({
                "total_notional": 5000.0,
                "daily_pnl": 100.0,
                "margin_util": 30.0,
                "drawdown_pct": 2.0,
                "breaches": [],
            })
        )
        assert result["approved"] is True
        assert result["risk_score"] < 0.8

    def test_high_risk_portfolio_flagged(self):
        orch = self._make_orchestrator()
        result = asyncio.get_event_loop().run_until_complete(
            orch.review_portfolio_risk({
                "total_notional": 50000.0,
                "daily_pnl": -1000.0,
                "margin_util": 90.0,
                "drawdown_pct": 15.0,
                "breaches": ["max_daily_loss", "margin_limit"],
            })
        )
        assert result["approved"] is False
        assert result["risk_score"] >= 0.8

    def test_review_intent_rejects_portfolio_snapshot(self):
        """review_intent should still reject portfolio snapshots (missing required fields)."""
        orch = self._make_orchestrator()
        result = asyncio.get_event_loop().run_until_complete(
            orch.review_intent({
                "total_notional": 5000.0,
                "daily_pnl": 100.0,
            })
        )
        assert result["approved"] is False
        assert result["reason"] == "missing_required_fields"


# ── 4. PerpContext cascading fallback ─────────────────────────────────

class TestPerpContextFallback:
    """_fetch_premium_index should cascade through Binance → Bybit → CoinGecko → stub."""

    def test_binance_451_falls_to_bybit(self):
        """When Binance returns 451, Bybit should be tried next."""
        import httpx

        call_count = {"n": 0}
        original_fetch = None

        async def mock_fetch(url):
            call_count["n"] += 1
            if "binance.com" in url:
                raise httpx.HTTPStatusError(
                    "451", request=MagicMock(), response=MagicMock(status_code=451)
                )
            if "bybit.com" in url:
                return {
                    "result": {
                        "list": [{
                            "fundingRate": "0.0001",
                            "markPrice": "87000.5",
                            "indexPrice": "87001.0",
                        }]
                    }
                }
            return {}

        from merid.prediction import perp_context
        with patch.object(perp_context, "_fetch_json", side_effect=mock_fetch):
            result = asyncio.get_event_loop().run_until_complete(
                perp_context._fetch_premium_index("BTCUSD")
            )

        assert result.mark_price == 87000.5
        assert result.funding_rate == 0.0001
        assert call_count["n"] == 2  # Binance failed, Bybit succeeded

    def test_all_fail_returns_stub(self):
        """When all sources fail, return a zero-filled stub."""
        async def mock_fetch(url):
            raise Exception("network error")

        from merid.prediction import perp_context
        with patch.object(perp_context, "_fetch_json", side_effect=mock_fetch):
            result = asyncio.get_event_loop().run_until_complete(
                perp_context._fetch_premium_index("BTCUSD")
            )

        assert result.symbol == "BTCUSD"
        assert result.mark_price == 0.0
        assert result.funding_rate == 0.0

    def test_coingecko_fallback_when_both_perp_fail(self):
        """When Binance and Bybit fail, CoinGecko provides spot price."""
        call_urls = []

        async def mock_fetch(url):
            call_urls.append(url)
            if "binance.com" in url:
                raise Exception("451 geo-blocked")
            if "bybit.com" in url:
                raise Exception("timeout")
            if "coingecko.com" in url:
                return {"bitcoin": {"usd": 86500.0}}
            return {}

        from merid.prediction import perp_context
        with patch.object(perp_context, "_fetch_json", side_effect=mock_fetch):
            result = asyncio.get_event_loop().run_until_complete(
                perp_context._fetch_premium_index("BTCUSD")
            )

        assert result.mark_price == 86500.0
        assert result.index_price == 86500.0
        assert result.funding_rate == 0.0  # CoinGecko doesn't have funding rate
        assert any("coingecko" in u for u in call_urls)


# ── 5. risk-metrics/agents endpoint — no _stub flag ─────────────────────

class TestRiskMetricsAgentsNoStub:
    """The /api/v1/risk-metrics/agents endpoint must return real agent data
    from AgentPerformanceTracker/AgentGrid instead of hardcoded stubs.

    This prevents the global Stub Mode banner in the UI.
    """

    def test_returns_grid_agents_without_stub(self):
        """When AgentGrid has agents, endpoint returns them without _stub."""
        from unittest.mock import patch, MagicMock
        import asyncio

        # Mock AgentGrid with two agents
        mock_grid = MagicMock()
        agent1 = MagicMock()
        agent1.agent_id = "kalshi-btc_15m"
        agent2 = MagicMock()
        agent2.agent_id = "kalshi-eth_15m"
        mock_grid.agents = [agent1, agent2]

        # Mock tracker with empty metrics (no trades yet)
        mock_tracker = MagicMock()
        mock_tracker.get_all_metrics.return_value = {}

        with patch("merid.prediction.agent_performance_tracker.get_agent_performance_tracker", return_value=mock_tracker), \
             patch("merid.prediction.agent_grid.get_agent_grid", return_value=mock_grid):

            from web.api.missing_endpoints import get_risk_metrics_agents_v1
            result = asyncio.get_event_loop().run_until_complete(get_risk_metrics_agents_v1())

        assert "_stub" not in result, "Endpoint must NOT return _stub flag"
        assert len(result["agents"]) == 2
        ids = {a["agent_id"] for a in result["agents"]}
        assert "kalshi-btc_15m" in ids
        assert "kalshi-eth_15m" in ids

    def test_returns_tracker_metrics_when_available(self):
        """When tracker has recorded trades, metrics flow through."""
        from unittest.mock import patch, MagicMock
        import asyncio

        mock_metrics = MagicMock()
        mock_metrics.to_dict.return_value = {
            "agent_id": "kalshi-btc_15m",
            "total_fills": 10,
            "total_closes": 5,
            "wins": 4,
            "losses": 1,
            "win_rate": 0.8,
            "total_pnl_usd": "12.50",
            "avg_profit_per_trade": "2.50",
            "avg_predicted_edge": 0.05,
            "avg_realized_edge": 0.04,
            "edge_accuracy": -0.01,
            "avg_confidence": 0.7,
            "calibration_error": 0.02,
            "sharpe_ratio": 1.5,
            "sortino_ratio": 2.0,
            "calmar_ratio": 3.0,
            "profit_factor": 4.0,
            "last_updated": "2026-01-01T00:00:00",
        }

        mock_tracker = MagicMock()
        mock_tracker.get_all_metrics.return_value = {"kalshi-btc_15m": mock_metrics}

        mock_grid = MagicMock()
        mock_grid.agents = []

        with patch("merid.prediction.agent_performance_tracker.get_agent_performance_tracker", return_value=mock_tracker), \
             patch("merid.prediction.agent_grid.get_agent_grid", return_value=mock_grid):

            from web.api.missing_endpoints import get_risk_metrics_agents_v1
            result = asyncio.get_event_loop().run_until_complete(get_risk_metrics_agents_v1())

        assert "_stub" not in result
        assert len(result["agents"]) == 1
        agent = result["agents"][0]
        assert agent["total_trades"] == 10
        assert agent["winning_trades"] == 4
        assert agent["win_rate"] == 0.8
        assert agent["sharpe_ratio"] == 1.5
        assert float(agent["total_pnl"]) == 12.50

    def test_empty_agents_no_stub(self):
        """Even with no agents anywhere, response should NOT include _stub."""
        from unittest.mock import patch, MagicMock
        import asyncio

        mock_tracker = MagicMock()
        mock_tracker.get_all_metrics.return_value = {}

        mock_grid = MagicMock()
        mock_grid.agents = []

        # Also make legacy registry fail
        with patch("merid.prediction.agent_performance_tracker.get_agent_performance_tracker", return_value=mock_tracker), \
             patch("merid.prediction.agent_grid.get_agent_grid", return_value=mock_grid), \
             patch("web.api.missing_endpoints.get_agent_registry", side_effect=Exception("no registry")):

            from web.api.missing_endpoints import get_risk_metrics_agents_v1
            result = asyncio.get_event_loop().run_until_complete(get_risk_metrics_agents_v1())

        assert "_stub" not in result
        assert result["agents"] == []
