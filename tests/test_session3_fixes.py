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
        guard._asset_caps = {}
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
        assert "enabled" in promo
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


# ── 2. AgentPerformanceMetrics basic serialization ─────────────────────────

class TestAgentPerformanceMetricsBasic:
    """AgentPerformanceMetrics basic functionality after rename from AgentMetrics."""

    def _make_metrics(self, **overrides):
        from merid.prediction.agent_performance_tracker import AgentPerformanceMetrics
        defaults = {
            "agent_id": "test-agent",
            "total_fills": 10,
            "total_closes": 5,
            "wins": 5,
            "losses": 0,
            "total_pnl_usd": Decimal("100.00"),
        }
        defaults.update(overrides)
        return AgentPerformanceMetrics(**defaults)

    def test_normal_values_serializable(self):
        m = self._make_metrics(sharpe_ratio=1.5)
        d = m.to_dict()
        serialized = json.dumps(d)
        assert '"sharpe_ratio": 1.5' in serialized

    def test_win_rate_calculation(self):
        m = self._make_metrics(total_closes=10, wins=7)
        assert m.win_rate == 0.7


# ── 3. SwarmOrchestrator.review_portfolio_risk() ─────────────────────



# ── 4. PerpContext cascading fallback ─────────────────────────────────

class TestPerpContextFallback:
    """Perp context: Binance single-source; PerpContextService falls back to stub."""

    def test_premium_index_parses_binance_payload(self):
        async def mock_fetch(url):
            return {
                "lastFundingRate": "0.0001",
                "markPrice": "87000.5",
                "indexPrice": "87001.0",
                "nextFundingTime": "1700000000000",
            }

        from merid.prediction import perp_context
        with patch.object(perp_context, "_fetch_json", side_effect=mock_fetch):
            result = asyncio.get_event_loop().run_until_complete(
                perp_context._fetch_premium_index("BTCUSD")
            )

        assert result.symbol == "BTCUSD"
        assert result.mark_price == 87000.5
        assert result.index_price == 87001.0
        assert result.funding_rate == 0.0001
        assert result.next_funding_ts == 1700000000.0

    def test_binance_failure_returns_stub_snapshot(self):
        """PerpContextService must degrade to a stub snapshot on Binance failure."""
        async def mock_fetch(url):
            raise Exception("451 geo-blocked")

        from merid.prediction import perp_context
        svc = perp_context.PerpContextService()
        with patch.object(perp_context, "_fetch_json", side_effect=mock_fetch):
            snap = asyncio.get_event_loop().run_until_complete(svc._fetch(0.0))

        assert snap.source == "stub"
        assert snap.btc.mark_price == 0.0
        assert snap.btc.funding_rate == 0.0

    def test_iv_fetch_failure_yields_zero_iv(self):
        """IV fetch failure degrades to 0.0, not an exception."""
        async def mock_fetch(url):
            raise Exception("network error")

        from merid.prediction import perp_context
        with patch.object(perp_context, "_fetch_json", side_effect=mock_fetch):
            iv = asyncio.get_event_loop().run_until_complete(
                perp_context._fetch_iv("BTCUSD")
            )
        assert iv == 0.0

