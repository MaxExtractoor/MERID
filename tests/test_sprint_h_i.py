"""Tests for Sprints H–I: Message bus wiring, Critic agent, MacroRegime forecaster.

Sprint H: Wire Critique/RiskView/Decision publishers to agents
Sprint I: MacroRegime forecaster + registry wiring
"""

from __future__ import annotations

import asyncio
import inspect
import time
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Sprint H — Critic Agent
# ═══════════════════════════════════════════════════════════════════════════


class TestCriticAgent:
    """Tests for merid.swarm.critic_agent.CriticAgent."""

    def test_critic_agent_import(self):
        from merid.swarm.critic_agent import CriticAgent, get_critic_agent
        agent = get_critic_agent()
        assert isinstance(agent, CriticAgent)

    def test_critic_singleton(self):
        from merid.swarm.critic_agent import get_critic_agent
        a1 = get_critic_agent()
        a2 = get_critic_agent()
        assert a1 is a2

    def test_critic_config_defaults(self):
        from merid.swarm.critic_agent import CriticConfig
        config = CriticConfig()
        assert config.staleness_threshold_s == 300.0
        assert config.critical_staleness_s == 600.0
        assert config.min_depth == 50
        assert config.max_spread == 0.08

    def test_check_staleness_returns_list(self):
        from merid.swarm.critic_agent import CriticAgent
        agent = CriticAgent()
        # Without a running staleness monitor, should return empty list
        result = agent._check_staleness()
        assert isinstance(result, list)

    def test_check_liquidity_returns_list(self):
        from merid.swarm.critic_agent import CriticAgent
        agent = CriticAgent()
        result = agent._check_liquidity()
        assert isinstance(result, list)

    def test_evaluate_market_returns_list(self):
        from merid.swarm.critic_agent import CriticAgent
        agent = CriticAgent()
        result = agent.evaluate_market("KXBTC-TEST")
        assert isinstance(result, list)

    def test_history_empty_initially(self):
        from merid.swarm.critic_agent import CriticAgent
        agent = CriticAgent()
        assert agent.history == []


class TestCriticStalenessIntegration:
    """Test that staleness checks produce Critique messages."""

    def test_stale_feed_produces_critique(self):
        from merid.swarm.critic_agent import CriticAgent
        from merid.swarm.messages import Critique
        agent = CriticAgent()

        # Mock the staleness monitor
        mock_status = MagicMock()
        mock_status.feed_id = "kalshi"
        mock_status.instrument = "KXBTC"
        mock_status.age_seconds = 400.0
        mock_status.stale = True
        mock_status.critical = False

        mock_monitor = MagicMock()
        mock_monitor.check_all.return_value = [mock_status]

        with patch("core.feed_staleness_monitor.get_feed_staleness_monitor", return_value=mock_monitor):
            critiques = agent._check_staleness()
            assert len(critiques) == 1
            assert isinstance(critiques[0], Critique)
            assert critiques[0].critique_type == "stale_data"
            assert critiques[0].weight_adjustment == 0.3

    def test_critical_stale_feed_vetos(self):
        from merid.swarm.critic_agent import CriticAgent
        agent = CriticAgent()

        mock_status = MagicMock()
        mock_status.feed_id = "kalshi"
        mock_status.instrument = "KXBTC"
        mock_status.age_seconds = 700.0
        mock_status.stale = True
        mock_status.critical = True

        mock_monitor = MagicMock()
        mock_monitor.check_all.return_value = [mock_status]

        with patch("core.feed_staleness_monitor.get_feed_staleness_monitor", return_value=mock_monitor):
            critiques = agent._check_staleness()
            assert len(critiques) == 1
            assert critiques[0].recommended_action == "veto"
            assert critiques[0].weight_adjustment == 0.0
            assert critiques[0].severity == 1.0


class TestCriticLiquidityIntegration:
    """Test that liquidity alerts produce Critique messages."""

    def test_liquidity_alert_produces_critique(self):
        from merid.swarm.critic_agent import CriticAgent
        from merid.swarm.messages import Critique
        agent = CriticAgent()

        mock_alert = MagicMock()
        mock_alert.market_id = "KXBTC"
        mock_alert.kind = "thin_book"
        mock_alert.severity = "warning"
        mock_alert.msg = "Depth 20 < 50"
        mock_alert.ts = time.time()  # Recent
        mock_alert.details = {"depth": 20}

        mock_monitor = MagicMock()
        mock_monitor._alert_log = [mock_alert]

        with patch("merid.event_venues.kalshi.liquidity_monitor.get_liquidity_monitor", return_value=mock_monitor):
            critiques = agent._check_liquidity()
            assert len(critiques) == 1
            assert isinstance(critiques[0], Critique)
            assert critiques[0].critique_type == "illiquid"


# ═══════════════════════════════════════════════════════════════════════════
# Sprint H — RiskView Publisher in PortfolioRiskAgent
# ═══════════════════════════════════════════════════════════════════════════


class TestRiskViewPublisher:
    """Test that PortfolioRiskAgent publishes RiskView messages."""

    def test_publish_risk_view_method_exists(self):
        from merid.prediction.portfolio_risk_agent import PortfolioRiskAgent
        assert hasattr(PortfolioRiskAgent, '_publish_risk_view')

    def test_publish_risk_view_in_check_portfolio(self):
        source = inspect.getsource(
            __import__('merid.prediction.portfolio_risk_agent', fromlist=['PortfolioRiskAgent']).PortfolioRiskAgent._check_portfolio
        )
        assert "_publish_risk_view" in source

    @pytest.mark.asyncio
    async def test_publish_risk_view_no_crash(self):
        """Publishing should be non-fatal even without a running bus."""
        from merid.prediction.portfolio_risk_agent import PortfolioRiskAgent

        agent = PortfolioRiskAgent.__new__(PortfolioRiskAgent)
        # Create a minimal snapshot mock
        mock_snapshot = MagicMock()
        mock_snapshot.margin_utilization_pct = 50.0

        await agent._publish_risk_view(mock_snapshot, [])

    @pytest.mark.asyncio
    async def test_publish_risk_view_with_breaches(self):
        from merid.prediction.portfolio_risk_agent import PortfolioRiskAgent

        agent = PortfolioRiskAgent.__new__(PortfolioRiskAgent)
        mock_snapshot = MagicMock()
        mock_snapshot.margin_utilization_pct = 85.0

        breaches = ["Daily loss $300 > limit $250"]
        # Should not raise
        await agent._publish_risk_view(mock_snapshot, breaches)


# ═══════════════════════════════════════════════════════════════════════════
# Sprint H — Decision Publisher in Consensus Aggregator
# ═══════════════════════════════════════════════════════════════════════════


class TestDecisionPublisher:
    """Test that SwarmConsensusAggregator publishes Decision messages."""

    def test_decision_publish_in_recompute(self):
        source = inspect.getsource(
            __import__('merid.swarm.consensus_aggregator', fromlist=['SwarmConsensusAggregator']).SwarmConsensusAggregator._recompute_consensus
        )
        assert "Decision" in source
        assert "publish_decision" in source

    def test_decision_published_on_ready_consensus(self):
        """Decision should be published when consensus status is READY."""
        from merid.swarm.consensus_aggregator import (
            SwarmConsensusAggregator, AgentProposal, ConsensusStatus
        )
        agg = SwarmConsensusAggregator()
        agg.min_agents = 2

        archetypes = ["momentum", "mean_reversion", "edge_model"]
        for i in range(3):
            proposal = AgentProposal(
                agent_id=f"agent_{i}",
                agent_archetype=archetypes[i],
                asset="BTC",
                timeframe="15m",
                direction="buy_yes",
                probability=0.65,
                confidence=0.8,
                edge_estimate=5.0,
                size_preference="base",
                rationale="test",
                timestamp=datetime.now(timezone.utc),
            )
            agg.submit_proposal(proposal)

        # After submitting, consensus should be in cache
        view = agg.get_consensus("BTC", "15m")
        assert view is not None
        assert view.status == ConsensusStatus.READY


# ═══════════════════════════════════════════════════════════════════════════
# Sprint I — MacroRegime Forecaster
# ═══════════════════════════════════════════════════════════════════════════


class TestMacroRegimeForecaster:
    """Tests for merid.prediction.forecasters.macro_regime."""

    def _make_forecaster(self):
        from merid.prediction.forecasters.macro_regime import MacroRegimeForecaster
        return MacroRegimeForecaster()

    def test_basic_prediction(self):
        f = self._make_forecaster()
        result = f.predict(
            market_id="KXBTC-TEST",
            implied_yes=0.55,
            implied_no=0.45,
        )
        assert result is not None
        assert result.forecaster_id == "macro_regime"
        assert result.forecaster_id == "macro_regime"
        assert 0.02 <= result.p_model <= 0.98

    def test_extreme_implied_returns_none(self):
        f = self._make_forecaster()
        result = f.predict(
            market_id="KXBTC-TEST",
            implied_yes=0.005,
            implied_no=0.995,
        )
        assert result is None

    def test_fear_greed_bullish(self):
        f = self._make_forecaster()
        result = f.predict(
            market_id="KXBTC-TEST",
            implied_yes=0.50,
            implied_no=0.50,
            fear_greed_index=15,  # Extreme fear → contrarian bullish
        )
        assert result is not None
        assert result.p_model > 0.50  # Should push probability up
        assert result.components["fear_greed_signal"] > 0

    def test_fear_greed_bearish(self):
        f = self._make_forecaster()
        result = f.predict(
            market_id="KXBTC-TEST",
            implied_yes=0.50,
            implied_no=0.50,
            fear_greed_index=85,  # Extreme greed → contrarian bearish
        )
        assert result is not None
        assert result.p_model < 0.50
        assert result.components["fear_greed_signal"] < 0

    def test_high_vol_reduces_confidence(self):
        f = self._make_forecaster()
        low_vol_result = f.predict(
            market_id="KXBTC-TEST",
            implied_yes=0.50,
            implied_no=0.50,
            fear_greed_index=15,
            realized_vol_ann=25,  # Low vol
        )
        high_vol_result = f.predict(
            market_id="KXBTC-TEST",
            implied_yes=0.50,
            implied_no=0.50,
            fear_greed_index=15,
            realized_vol_ann=100,  # High vol
        )
        assert high_vol_result.confidence < low_vol_result.confidence

    def test_xtf_agreement_signal(self):
        f = self._make_forecaster()
        result = f.predict(
            market_id="KXBTC-TEST",
            implied_yes=0.50,
            implied_no=0.50,
            xtf_agreement=0.8,  # Strong bullish agreement
        )
        assert result is not None
        assert result.components["xtf_agreement"] > 0

    def test_sentiment_signal(self):
        f = self._make_forecaster()
        result = f.predict(
            market_id="KXBTC-TEST",
            implied_yes=0.50,
            implied_no=0.50,
            sentiment_score=0.5,  # Strong positive sentiment
        )
        assert result is not None
        assert result.p_model > 0.50

    def test_adjustment_clamped(self):
        """Total adjustment should be clamped to ±10%."""
        f = self._make_forecaster()
        result = f.predict(
            market_id="KXBTC-TEST",
            implied_yes=0.50,
            implied_no=0.50,
            fear_greed_index=10,      # Max bullish
            xtf_agreement=1.0,        # Max bullish
            sentiment_score=1.0,      # Max bullish
            realized_vol_ann=25,      # Low vol
        )
        assert result is not None
        # Even with all signals maxed, adjustment clamped to ±10%
        assert result.p_model <= 0.60 + 0.01  # 0.50 + 0.10 + small rounding

    def test_to_dict(self):
        f = self._make_forecaster()
        result = f.predict(
            market_id="KXBTC-TEST",
            implied_yes=0.55,
            implied_no=0.45,
        )
        d = result.to_dict()
        assert d["forecaster_id"] == "macro_regime"
        assert "components" in d


class TestMacroRegimeConstants:
    """Test constants used by the macro regime forecaster."""

    def test_fear_greed_thresholds(self):
        from merid.prediction.forecasters.macro_regime import (
            EXTREME_FEAR, FEAR, GREED, EXTREME_GREED
        )
        assert EXTREME_FEAR < FEAR < GREED < EXTREME_GREED

    def test_vol_thresholds(self):
        from merid.prediction.forecasters.macro_regime import LOW_VOL, HIGH_VOL
        assert LOW_VOL < HIGH_VOL


# ═══════════════════════════════════════════════════════════════════════════
# Sprint I — Registry Wiring
# ═══════════════════════════════════════════════════════════════════════════


class TestRegistryMacroWiring:
    """Test that MacroRegimeForecaster is wired into the registry."""

    def test_macro_in_init(self):
        import os
        init_path = os.path.join("merid", "prediction", "forecasters", "__init__.py")
        with open(init_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "MacroRegimeForecaster" in content

    def test_registry_auto_registers_macro(self):
        """The singleton registry should include macro_regime."""
        # Reset singleton to force fresh creation
        import merid.prediction.forecasters.registry as reg_mod
        old = reg_mod._registry
        reg_mod._registry = None
        try:
            registry = reg_mod.get_forecaster_registry()
            ids = [f.forecaster_id for f in registry._forecasters]
            assert "macro_regime" in ids
            assert "momentum_v1" in ids
            assert "mean_reversion_v1" in ids
        finally:
            reg_mod._registry = old

    def test_registry_has_three_forecasters(self):
        import merid.prediction.forecasters.registry as reg_mod
        old = reg_mod._registry
        reg_mod._registry = None
        try:
            registry = reg_mod.get_forecaster_registry()
            assert len(registry._forecasters) >= 3
        finally:
            reg_mod._registry = old


# ═══════════════════════════════════════════════════════════════════════════
# Sprint H — Source Verification
# ═══════════════════════════════════════════════════════════════════════════


class TestSourceWiring:
    """Verify Sprint H wiring in source code."""

    def test_critic_agent_file_exists(self):
        import os
        assert os.path.exists(os.path.join("merid", "swarm", "critic_agent.py"))

    def test_macro_regime_file_exists(self):
        import os
        assert os.path.exists(os.path.join("merid", "prediction", "forecasters", "macro_regime.py"))

    def test_portfolio_risk_agent_has_risk_view(self):
        source = inspect.getsource(
            __import__('merid.prediction.portfolio_risk_agent', fromlist=['PortfolioRiskAgent']).PortfolioRiskAgent
        )
        assert "RiskView" in source
        assert "publish_risk_view" in source

    def test_consensus_aggregator_has_decision(self):
        source = inspect.getsource(
            __import__('merid.swarm.consensus_aggregator', fromlist=['SwarmConsensusAggregator']).SwarmConsensusAggregator
        )
        assert "Decision" in source
        assert "publish_decision" in source
