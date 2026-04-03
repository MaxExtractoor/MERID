"""Tests for Sprints D–G: Correlation, Messages, Edge Recalibration, UI wiring.

Sprint D: Inter-asset correlation + diversity gate
Sprint E: Typed message schemas + bus publishing
Sprint F: UI component/view existence + API endpoint wiring
Sprint G: Edge threshold recalibration
"""

from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Sprint D — Correlation Tracker
# ═══════════════════════════════════════════════════════════════════════════


class TestCorrelationTracker:
    """Tests for merid.risk.correlation.CorrelationTracker."""

    def _make_tracker(self, window=50):
        from merid.risk.correlation import CorrelationTracker
        return CorrelationTracker(window=window)

    def test_empty_tracker_returns_zero(self):
        tracker = self._make_tracker()
        assert tracker.get_correlation("BTC", "ETH") == 0.0

    def test_same_asset_returns_one(self):
        tracker = self._make_tracker()
        assert tracker.get_correlation("BTC", "BTC") == 1.0

    def test_perfectly_correlated(self):
        tracker = self._make_tracker()
        for i in range(20):
            r = 0.01 * (i % 5 - 2)
            tracker.record_return("BTC", r)
            tracker.record_return("ETH", r)  # Identical returns
        corr = tracker.get_correlation("BTC", "ETH")
        assert corr > 0.99, f"Expected ≈1.0, got {corr}"

    def test_perfectly_anticorrelated(self):
        tracker = self._make_tracker()
        for i in range(20):
            r = 0.01 * (i % 5 - 2)
            tracker.record_return("BTC", r)
            tracker.record_return("ETH", -r)  # Opposite returns
        corr = tracker.get_correlation("BTC", "ETH")
        assert corr < -0.99, f"Expected ≈-1.0, got {corr}"

    def test_uncorrelated_near_zero(self):
        import random
        random.seed(42)
        tracker = self._make_tracker()
        for _ in range(100):
            tracker.record_return("BTC", random.gauss(0, 0.01))
            tracker.record_return("SOL", random.gauss(0, 0.01))
        corr = tracker.get_correlation("BTC", "SOL")
        assert abs(corr) < 0.3, f"Expected ≈0, got {corr}"

    def test_insufficient_data_returns_zero(self):
        tracker = self._make_tracker()
        for i in range(3):  # < 5 minimum
            tracker.record_return("BTC", 0.01)
            tracker.record_return("ETH", 0.01)
        assert tracker.get_correlation("BTC", "ETH") == 0.0

    def test_window_trimming(self):
        tracker = self._make_tracker(window=10)
        for i in range(20):
            tracker.record_return("BTC", 0.01 * i)
        assert len(tracker._returns["BTC"]) == 10

    def test_case_insensitive(self):
        tracker = self._make_tracker()
        for i in range(10):
            tracker.record_return("btc", 0.01)
            tracker.record_return("BTC", 0.01)
        assert len(tracker._returns["BTC"]) == 20

    def test_tracked_assets(self):
        tracker = self._make_tracker()
        tracker.record_return("BTC", 0.01)
        tracker.record_return("ETH", 0.01)
        tracker.record_return("SOL", 0.01)
        assert tracker.tracked_assets == ["BTC", "ETH", "SOL"]

    def test_reset(self):
        tracker = self._make_tracker()
        tracker.record_return("BTC", 0.01)
        tracker.reset()
        assert tracker.tracked_assets == []


class TestExposureReductionFactor:
    """Tests for CorrelationTracker.exposure_reduction_factor."""

    def _make_tracker(self):
        from merid.risk.correlation import CorrelationTracker
        return CorrelationTracker()

    def test_no_data_returns_one(self):
        tracker = self._make_tracker()
        assert tracker.exposure_reduction_factor("BTC", "ETH") == 1.0

    def test_low_correlation_no_reduction(self):
        tracker = self._make_tracker()
        # Feed data that produces low correlation
        import random
        random.seed(99)
        for _ in range(30):
            tracker.record_return("BTC", random.gauss(0, 0.01))
            tracker.record_return("DOGE", random.gauss(0, 0.01))
        factor = tracker.exposure_reduction_factor("BTC", "DOGE")
        # With truly random data, correlation should be low → factor ≈ 1.0
        assert factor >= 0.7, f"Expected >= 0.7, got {factor}"

    def test_high_correlation_reduces(self):
        tracker = self._make_tracker()
        for i in range(30):
            r = 0.01 * (i % 5 - 2)
            tracker.record_return("BTC", r)
            tracker.record_return("ETH", r * 0.95)  # Very similar
        factor = tracker.exposure_reduction_factor("BTC", "ETH")
        assert factor < 0.8, f"Expected reduction, got {factor}"

    def test_factor_bounds(self):
        from merid.risk.correlation import MAX_REDUCTION
        tracker = self._make_tracker()
        for i in range(30):
            r = 0.01 * (i % 7 - 3)
            tracker.record_return("A", r)
            tracker.record_return("B", r)  # Perfect correlation
        factor = tracker.exposure_reduction_factor("A", "B")
        assert factor >= MAX_REDUCTION, f"Factor {factor} below floor {MAX_REDUCTION}"
        assert factor <= 1.0


class TestCorrelationMatrix:
    """Tests for the full matrix snapshot."""

    def test_matrix_structure(self):
        from merid.risk.correlation import CorrelationTracker
        tracker = CorrelationTracker()
        for i in range(10):
            tracker.record_return("BTC", 0.01 * i)
            tracker.record_return("ETH", 0.01 * i)
            tracker.record_return("SOL", 0.01 * i)
        matrix = tracker.get_matrix()
        assert len(matrix.assets) == 3
        assert len(matrix.pairs) == 3  # 3 choose 2

    def test_matrix_to_dict(self):
        from merid.risk.correlation import CorrelationTracker
        tracker = CorrelationTracker()
        for i in range(10):
            tracker.record_return("BTC", 0.01)
            tracker.record_return("ETH", 0.01)
        d = tracker.get_matrix().to_dict()
        assert "assets" in d
        assert "pairs" in d
        assert "timestamp" in d


class TestClusterFactor:
    """Tests for cluster-level reduction factor."""

    def test_cluster_factor_with_no_data(self):
        from merid.risk.correlation import CorrelationTracker
        tracker = CorrelationTracker()
        assert tracker.get_cluster_factor("BTC") == 1.0

    def test_cluster_factor_unknown_asset(self):
        from merid.risk.correlation import CorrelationTracker
        tracker = CorrelationTracker()
        assert tracker.get_cluster_factor("UNKNOWN") == 1.0


class TestCorrelationSingleton:
    """Test singleton behavior."""

    def test_singleton(self):
        from merid.risk.correlation import get_correlation_tracker
        t1 = get_correlation_tracker()
        t2 = get_correlation_tracker()
        assert t1 is t2


# ═══════════════════════════════════════════════════════════════════════════
# Sprint D — Portfolio Risk Correlation Wiring
# ═══════════════════════════════════════════════════════════════════════════


class TestPortfolioCorrelationCheck:
    """Test that PortfolioRiskAgent._check_limits includes correlation check."""

    def test_check_limits_includes_correlation_code(self):
        """Verify the correlation check was wired in."""
        import inspect
        from merid.prediction.portfolio_risk_agent import PortfolioRiskAgent
        source = inspect.getsource(PortfolioRiskAgent._check_limits)
        assert "correlation" in source.lower()
        assert "ASSET_CLUSTERS" in source


# ═══════════════════════════════════════════════════════════════════════════
# Sprint D — Consensus Diversity Gate
# ═══════════════════════════════════════════════════════════════════════════


class TestConsensusDiversityGate:
    """Test minimum archetype diversity requirement."""

    def test_diversity_gate_in_source(self):
        import inspect
        from merid.swarm.consensus_aggregator import SwarmConsensusAggregator
        source = inspect.getsource(SwarmConsensusAggregator._aggregate_proposals)
        assert "min_archetypes" in source
        assert "Insufficient diversity" in source

    def test_single_archetype_blocks_consensus(self):
        """With only one archetype type in LIVE mode, consensus should be FORMING."""
        from merid.swarm.consensus_aggregator import (
            SwarmConsensusAggregator, AgentProposal, ConsensusStatus
        )
        agg = SwarmConsensusAggregator()
        agg.min_agents = 2

        proposals = [
            AgentProposal(
                agent_id=f"agent_{i}",
                agent_archetype="momentum",  # Same type
                asset="BTC",
                timeframe="15m",
                direction="buy_yes",
                probability=0.6,
                confidence=0.7,
                edge_estimate=0.05,
                size_preference="base",
                rationale="test",
                timestamp=datetime.now(timezone.utc),
                mode="LIVE",  # LIVE mode requires archetype diversity (min_archetypes=2)
            )
            for i in range(3)
        ]

        view = agg._aggregate_proposals("BTC", "15m", proposals)
        assert view.status == ConsensusStatus.FORMING

    def test_diverse_archetypes_allow_consensus(self):
        """With 2+ archetype types, consensus can proceed."""
        from merid.swarm.consensus_aggregator import (
            SwarmConsensusAggregator, AgentProposal, ConsensusStatus
        )
        agg = SwarmConsensusAggregator()
        agg.min_agents = 2

        archetypes = ["momentum", "mean_reversion", "edge_model"]
        proposals = [
            AgentProposal(
                agent_id=f"agent_{i}",
                agent_archetype=archetypes[i],
                asset="BTC",
                timeframe="15m",
                direction="buy_yes",
                probability=0.6,
                confidence=0.7,
                edge_estimate=0.05,
                size_preference="base",
                rationale="test",
                timestamp=datetime.now(timezone.utc),
            )
            for i in range(3)
        ]

        view = agg._aggregate_proposals("BTC", "15m", proposals)
        assert view.status == ConsensusStatus.READY


class TestAdaptiveQuorum:
    """Adaptive quorum: SIM mode relaxes thresholds; LIVE keeps full quorum."""

    def _make_proposal(self, agent_id: str, archetype: str, mode: str, asset: str = "BTC", timeframe: str = "daily"):
        from merid.swarm.consensus_aggregator import AgentProposal
        return AgentProposal(
            agent_id=agent_id,
            agent_archetype=archetype,
            asset=asset,
            timeframe=timeframe,
            direction="yes",
            probability=0.55,
            confidence=0.65,
            edge_estimate=2.0,
            size_preference="base",
            rationale="test",
            timestamp=datetime.now(timezone.utc),
            mode=mode,
        )

    def test_sim_single_proposal_reaches_ready(self):
        """One SIM proposal is enough when sim_min_agents=1 (default)."""
        from merid.swarm.consensus_aggregator import (
            SwarmConsensusAggregator, ConsensusStatus
        )
        agg = SwarmConsensusAggregator()

        proposals = [self._make_proposal("news_sentiment", "sentiment", "SIM")]
        view = agg._aggregate_proposals("BTC", "daily", proposals)
        assert view.status == ConsensusStatus.READY

    def test_live_single_proposal_stays_forming(self):
        """One LIVE proposal stays FORMING because live requires min_agents=2."""
        from merid.swarm.consensus_aggregator import (
            SwarmConsensusAggregator, ConsensusStatus
        )
        agg = SwarmConsensusAggregator()

        proposals = [self._make_proposal("news_sentiment", "sentiment", "LIVE")]
        view = agg._aggregate_proposals("BTC", "daily", proposals)
        assert view.status == ConsensusStatus.FORMING

    def test_live_two_archetypes_reaches_ready(self):
        """Two LIVE proposals from different archetypes graduates to READY."""
        from merid.swarm.consensus_aggregator import (
            SwarmConsensusAggregator, ConsensusStatus
        )
        agg = SwarmConsensusAggregator()

        proposals = [
            self._make_proposal("news_sentiment", "sentiment", "LIVE"),
            self._make_proposal("fg_contrarian", "contrarian", "LIVE"),
        ]
        view = agg._aggregate_proposals("BTC", "daily", proposals)
        assert view.status == ConsensusStatus.READY

    def test_mixed_one_live_one_sim_two_archetypes_reaches_ready(self):
        """1 SIM + 1 LIVE from different archetypes: LIVE thresholds apply and are met."""
        from merid.swarm.consensus_aggregator import (
            SwarmConsensusAggregator, ConsensusStatus
        )
        agg = SwarmConsensusAggregator()

        proposals = [
            self._make_proposal("news_sentiment", "sentiment", "SIM"),
            self._make_proposal("fg_contrarian", "contrarian", "LIVE"),
        ]
        view = agg._aggregate_proposals("BTC", "daily", proposals)
        assert view.status == ConsensusStatus.READY

    def test_sim_effective_thresholds_are_relaxed(self):
        """_effective_thresholds returns (1, 1) for all-SIM proposals."""
        from merid.swarm.consensus_aggregator import SwarmConsensusAggregator
        agg = SwarmConsensusAggregator()

        sim_proposals = [self._make_proposal("a", "sentiment", "SIM")]
        eff_agents, eff_arch = agg._effective_thresholds(sim_proposals)
        assert eff_agents == agg.sim_min_agents
        assert eff_arch == agg.sim_min_archetypes

    def test_live_effective_thresholds_are_strict(self):
        """_effective_thresholds returns live thresholds the moment any proposal is LIVE."""
        from merid.swarm.consensus_aggregator import SwarmConsensusAggregator
        agg = SwarmConsensusAggregator()

        mixed = [
            self._make_proposal("sim_agent", "sentiment", "SIM"),
            self._make_proposal("live_agent", "contrarian", "LIVE"),
        ]
        eff_agents, eff_arch = agg._effective_thresholds(mixed)
        assert eff_agents == agg.min_agents
        assert eff_arch == agg.min_archetypes

    def test_submit_proposal_sim_single_yields_consensus(self):
        """Full path: submit_proposal with 1 SIM proposal → get_consensus returns non-None READY view."""
        from merid.swarm.consensus_aggregator import (
            SwarmConsensusAggregator, ConsensusStatus
        )
        agg = SwarmConsensusAggregator()
        # Use a unique key to avoid pollution from other tests running on the same singleton
        p = self._make_proposal("news_sentiment", "sentiment", "SIM", asset="TESTADAPTIVE", timeframe="sim_test")
        agg.submit_proposal(p)
        view = agg.get_consensus("TESTADAPTIVE", "sim_test")
        assert view is not None, "Expected a ConsensusView to be cached after submit"
        assert view.status == ConsensusStatus.READY
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# Sprint E — Typed Message Schemas
# ═══════════════════════════════════════════════════════════════════════════


class TestForecastMessage:
    """Tests for Forecast message schema."""

    def test_forecast_defaults(self):
        from merid.swarm.messages import Forecast, MessageType
        f = Forecast()
        assert f.message_type == MessageType.FORECAST
        assert f.p_model == 0.5
        assert f.confidence == 0.0

    def test_forecast_to_dict(self):
        from merid.swarm.messages import Forecast
        f = Forecast(
            forecaster_id="momentum_1",
            model_type="momentum",
            market_id="KXBTC-24FEB21",
            p_model=0.65,
            confidence=0.8,
            edge_estimate=0.05,
        )
        d = f.to_dict()
        assert d["forecaster_id"] == "momentum_1"
        assert d["p_model"] == 0.65
        assert d["message_type"] == "forecast"

    def test_forecast_components(self):
        from merid.swarm.messages import Forecast
        f = Forecast(components={"vol_signal": 0.3, "oi_signal": 0.5})
        d = f.to_dict()
        assert "vol_signal" in d["components"]


class TestCritiqueMessage:
    """Tests for Critique message schema."""

    def test_critique_defaults(self):
        from merid.swarm.messages import Critique, MessageType
        c = Critique()
        assert c.message_type == MessageType.CRITIQUE
        assert c.weight_adjustment == 1.0

    def test_critique_to_dict(self):
        from merid.swarm.messages import Critique
        c = Critique(
            critic_id="staleness_critic",
            critique_type="stale_data",
            market_id="KXBTC",
            severity=0.8,
            reason="Data older than 5 minutes",
            recommended_action="down_weight",
            weight_adjustment=0.5,
        )
        d = c.to_dict()
        assert d["severity"] == 0.8
        assert d["weight_adjustment"] == 0.5


class TestRiskViewMessage:
    """Tests for RiskView message schema."""

    def test_risk_view_defaults(self):
        from merid.swarm.messages import RiskView, MessageType
        rv = RiskView()
        assert rv.message_type == MessageType.RISK_VIEW
        assert rv.correlation_factor == 1.0

    def test_risk_view_to_dict(self):
        from merid.swarm.messages import RiskView
        rv = RiskView(
            risk_agent_id="portfolio_risk",
            market_id="KXBTC",
            asset="BTC",
            risk_level="high",
            max_size_contracts=10,
            kelly_fraction=0.15,
            flags=["near_daily_limit"],
        )
        d = rv.to_dict()
        assert d["risk_level"] == "high"
        assert "near_daily_limit" in d["flags"]


class TestDecisionMessage:
    """Tests for Decision message schema."""

    def test_decision_defaults(self):
        from merid.swarm.messages import Decision, MessageType, DecisionAction
        d = Decision()
        assert d.message_type == MessageType.DECISION
        assert d.action == DecisionAction.SKIP

    def test_decision_to_dict(self):
        from merid.swarm.messages import Decision
        d = Decision(
            decision_id="dec_001",
            market_id="KXBTC",
            action="buy_yes",
            side="yes",
            size_contracts=5,
            p_consensus=0.68,
            consensus_confidence=0.75,
            contributing_forecasters=["momentum_1", "mean_reversion_1"],
            risk_approved=True,
        )
        dd = d.to_dict()
        assert dd["action"] == "buy_yes"
        assert dd["risk_approved"] is True
        assert len(dd["contributing_forecasters"]) == 2


class TestMessagePublishers:
    """Tests for async publish helpers."""

    @pytest.mark.asyncio
    async def test_publish_forecast_no_crash(self):
        """Publishing should be non-fatal even if bus is unavailable."""
        from merid.swarm.messages import Forecast, publish_forecast
        f = Forecast(forecaster_id="test")
        await publish_forecast(f)  # Should not raise

    @pytest.mark.asyncio
    async def test_publish_critique_no_crash(self):
        from merid.swarm.messages import Critique, publish_critique
        c = Critique(critic_id="test")
        await publish_critique(c)

    @pytest.mark.asyncio
    async def test_publish_risk_view_no_crash(self):
        from merid.swarm.messages import RiskView, publish_risk_view
        rv = RiskView(risk_agent_id="test")
        await publish_risk_view(rv)

    @pytest.mark.asyncio
    async def test_publish_decision_no_crash(self):
        from merid.swarm.messages import Decision, publish_decision
        d = Decision(decision_id="test")
        await publish_decision(d)


# ═══════════════════════════════════════════════════════════════════════════
# Sprint E — ForecasterRegistry Bus Publishing
# ═══════════════════════════════════════════════════════════════════════════


class TestRegistryBusPublishing:
    """Test that ForecasterRegistry publishes to the bus."""

    def test_publish_method_exists(self):
        from merid.prediction.forecasters.registry import ForecasterRegistry
        registry = ForecasterRegistry()
        assert hasattr(registry, '_publish_forecast_message')

    def test_publish_method_in_predict_all(self):
        import inspect
        from merid.prediction.forecasters.registry import ForecasterRegistry
        source = inspect.getsource(ForecasterRegistry.predict_all)
        assert "_publish_forecast_message" in source


# ═══════════════════════════════════════════════════════════════════════════
# Sprint F — UI Component/View Wiring
# ═══════════════════════════════════════════════════════════════════════════


class TestUIWiring:
    """Test that new UI components and views exist and are wired."""

    def test_calibration_dashboard_view_exists(self):
        import os
        path = os.path.join("web", "react", "src", "views", "CalibrationDashboardView.tsx")
        assert os.path.exists(path), f"Missing: {path}"

    def test_correlation_risk_panel_exists(self):
        import os
        path = os.path.join("web", "react", "src", "components", "CorrelationRiskPanel.tsx")
        assert os.path.exists(path), f"Missing: {path}"

    def test_calibration_view_in_app_tsx(self):
        import os
        app_path = os.path.join("web", "react", "src", "App.tsx")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "CalibrationDashboardView" in content
        assert "calibration-dashboard" in content

    def test_calibration_view_in_views_ts(self):
        import os
        views_path = os.path.join("web", "react", "src", "types", "views.ts")
        with open(views_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "calibration-dashboard" in content

    def test_calibration_in_sidebar(self):
        import os
        sidebar_path = os.path.join("web", "react", "src", "components", "Sidebar.tsx")
        with open(sidebar_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "calibration-dashboard" in content
        assert "Target" in content  # Icon import

    def test_correlation_constants(self):
        import os
        constants_path = os.path.join("web", "react", "src", "config", "constants.ts")
        with open(constants_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "CORRELATION_MATRIX" in content
        assert "CORRELATION_CLUSTERS" in content
        assert "METRICS_FORECASTERS" in content


# ═══════════════════════════════════════════════════════════════════════════
# Sprint F — API Endpoint Wiring
# ═══════════════════════════════════════════════════════════════════════════


class TestAPIWiring:
    """Test that API endpoints are properly wired."""

    def test_correlation_api_file_exists(self):
        import os
        assert os.path.exists(os.path.join("web", "api", "correlation_api.py"))

    def test_correlation_api_in_main(self):
        import os
        main_path = os.path.join("web", "main.py")
        with open(main_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "correlation_api_router" in content

    def test_correlation_api_has_endpoints(self):
        from web.api.correlation_api import router
        routes = [r.path for r in router.routes]
        assert any("matrix" in r for r in routes)
        assert any("factor" in r for r in routes)
        assert any("clusters" in r for r in routes)
        assert any("record" in r for r in routes)


# ═══════════════════════════════════════════════════════════════════════════
# Sprint G — Edge Recalibrator
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeRecalibrator:
    """Tests for merid.prediction.edge_recalibrator."""

    def test_recalibrate_skips_without_data(self):
        from merid.prediction.edge_recalibrator import EdgeRecalibrator
        recal = EdgeRecalibrator()
        result = recal.recalibrate()
        assert result.skipped is True

    def test_recalibrate_skips_insufficient_trades(self):
        from merid.prediction.edge_recalibrator import EdgeRecalibrator
        recal = EdgeRecalibrator()

        with patch("merid.metrics.realized_edge.get_realized_edge_store") as mock_store:
            mock_store.return_value.get_summary.return_value = {
                "trade_count": 5,
                "avg_predicted_edge": 0.05,
                "avg_realized_edge": 0.03,
            }
            result = recal.recalibrate()
            assert result.skipped is True
            assert "Insufficient" in result.skip_reason

    def test_recalibrate_adjusts_thresholds(self):
        from merid.prediction.edge_recalibrator import EdgeRecalibrator
        from merid.prediction.strategy import StrategyConfig
        recal = EdgeRecalibrator()
        config = StrategyConfig()
        old_early = config.min_edge_early

        with patch("merid.metrics.realized_edge.get_realized_edge_store") as mock_store, \
             patch.object(recal, "_get_strategy_config", return_value=config):
            mock_store.return_value.get_summary.return_value = {
                "trade_count": 50,
                "avg_predicted_edge": 0.08,  # Over-estimating
                "avg_realized_edge": 0.03,
            }
            result = recal.recalibrate()
            assert result.skipped is False
            assert result.edge_bias > 0  # Over-estimating
            # Threshold should increase
            assert config.min_edge_early >= old_early

    def test_recalibrate_respects_floor(self):
        from merid.prediction.edge_recalibrator import EdgeRecalibrator, MIN_EDGE_FLOOR
        from merid.prediction.strategy import StrategyConfig
        config = StrategyConfig()
        config.min_edge_early = Decimal("0.02")  # Near floor
        recal = EdgeRecalibrator()

        with patch("merid.metrics.realized_edge.get_realized_edge_store") as mock_store, \
             patch.object(recal, "_get_strategy_config", return_value=config):
            mock_store.return_value.get_summary.return_value = {
                "trade_count": 50,
                "avg_predicted_edge": 0.02,  # Under-estimating
                "avg_realized_edge": 0.05,
            }
            result = recal.recalibrate()
            assert config.min_edge_early >= MIN_EDGE_FLOOR

    def test_recalibrate_history(self):
        from merid.prediction.edge_recalibrator import EdgeRecalibrator
        recal = EdgeRecalibrator()
        recal.recalibrate()
        assert len(recal.history) == 1
        assert recal.latest is not None

    def test_result_to_dict(self):
        from merid.prediction.edge_recalibrator import RecalibrationResult
        r = RecalibrationResult(
            timestamp=time.time(),
            trade_count=50,
            avg_predicted_edge=0.06,
            avg_realized_edge=0.04,
            edge_bias=0.02,
            adjustments={"early": "0.050 -> 0.054"},
        )
        d = r.to_dict()
        assert d["trade_count"] == 50
        assert d["edge_bias"] == 0.02


class TestEdgeRecalibratorSingleton:
    """Test singleton behavior."""

    def test_singleton(self):
        from merid.prediction.edge_recalibrator import get_edge_recalibrator
        r1 = get_edge_recalibrator()
        r2 = get_edge_recalibrator()
        assert r1 is r2


# ═══════════════════════════════════════════════════════════════════════════
# Sprint E — Message Enums
# ═══════════════════════════════════════════════════════════════════════════


class TestMessageEnums:
    """Test message type enums are properly defined."""

    def test_message_types(self):
        from merid.swarm.messages import MessageType
        assert MessageType.FORECAST == "forecast"
        assert MessageType.CRITIQUE == "critique"
        assert MessageType.RISK_VIEW == "risk_view"
        assert MessageType.DECISION == "decision"

    def test_critique_types(self):
        from merid.swarm.messages import CritiqueType
        assert CritiqueType.STALE_DATA == "stale_data"
        assert CritiqueType.ILLIQUID == "illiquid"
        assert CritiqueType.ARB_MISMATCH == "arb_mismatch"

    def test_risk_levels(self):
        from merid.swarm.messages import RiskLevel
        assert RiskLevel.LOW == "low"
        assert RiskLevel.CRITICAL == "critical"

    def test_decision_actions(self):
        from merid.swarm.messages import DecisionAction
        assert DecisionAction.BUY_YES == "buy_yes"
        assert DecisionAction.SKIP == "skip"
        assert DecisionAction.CLOSE == "close"
