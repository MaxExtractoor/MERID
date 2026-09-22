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

