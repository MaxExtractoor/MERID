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

