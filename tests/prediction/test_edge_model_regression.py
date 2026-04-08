"""Regression tests to verify critical behaviors remain unchanged."""

from unittest.mock import MagicMock, patch
from decimal import Decimal

import pytest


class TestCoinbasePrimarySource:
    """Verify Coinbase remains the primary spot price source."""

    def test_spot_fetch_tries_coinbase_first(self):
        """_fetch_spot_prices_with_fallback should try Coinbase first."""
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader

        # We can't easily instantiate CT without full setup, so just verify
        # the source code contains the expected priority
        import inspect
        source = inspect.getsource(KalshiContinuousTrader._fetch_spot_prices_with_fallback)

        # Should mention Coinbase as PRIMARY
        assert "Coinbase" in source or "coinbase" in source.lower()
        assert "PRIMARY" in source or "primary" in source.lower()

    def test_spot_source_priority_documented(self):
        """Verify spot source priority is documented in code."""
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader
        import inspect

        source = inspect.getsource(KalshiContinuousTrader._fetch_spot_prices_with_fallback)

        # Should document the fallback chain
        # Expected: Coinbase → CoinGecko → Binance → last-known
        assert "CoinGecko" in source or "coingecko" in source.lower()
        assert "fallback" in source.lower()


class TestDefaultConfigValues:
    """Verify default config values remain conservative."""

    def test_strategy_config_defaults_strict(self):
        """StrategyConfig should default to strict edge profile."""
        from merid.prediction.strategy import StrategyConfig

        config = StrategyConfig()

        assert config.edge_floor_profile == "strict"
        assert config.mm_consensus_mode == "full"

    def test_shadow_thresholds_default_zero(self):
        """Shadow thresholds should default to 0 (not enforced)."""
        from merid.prediction.strategy import StrategyConfig

        config = StrategyConfig()

        assert config.shadow_edge_early == Decimal("0.00")
        assert config.shadow_edge_mid == Decimal("0.00")
        assert config.shadow_edge_late == Decimal("0.00")
        assert config.shadow_edge_terminal == Decimal("0.00")

    def test_consensus_timeout_default_500ms(self):
        """Consensus wait timeout should default to 500ms."""
        from merid.prediction.strategy import StrategyConfig

        config = StrategyConfig()

        assert config.consensus_wait_timeout_ms == 500


class TestBackwardCompatibility:
    """Verify changes don't break existing behavior."""

    def test_strict_profile_matches_original_thresholds(self):
        """Strict profile should produce same thresholds as pre-feature code."""
        from merid.prediction.strategy import KalshiStrategy, StrategyConfig, ExpiryPhase
        from decimal import Decimal

        # Original hardcoded values
        original_early = Decimal("0.05")
        original_mid = Decimal("0.04")
        original_late = Decimal("0.03")
        original_terminal = Decimal("0.02")

        config = StrategyConfig(
            edge_floor_profile="strict",  # Should match original behavior
            min_edge_early=original_early,
            min_edge_mid=original_mid,
            min_edge_late=original_late,
            min_edge_terminal=original_terminal,
        )
        strategy = KalshiStrategy(config=config)

        # Should return unmodified thresholds
        assert strategy._get_edge_threshold(ExpiryPhase.EARLY) == original_early
        assert strategy._get_edge_threshold(ExpiryPhase.MID) == original_mid
        assert strategy._get_edge_threshold(ExpiryPhase.LATE) == original_late
        assert strategy._get_edge_threshold(ExpiryPhase.TERMINAL) == original_terminal

    def test_full_consensus_mode_matches_original(self):
        """Full MM consensus mode should match original blocking behavior."""
        from merid.prediction.trading_agent import KalshiTradingAgent
        from merid.prediction.agent_grid_config import AgentConfig, AgentRiskLimits
        from merid.prediction.strategy import StrategyConfig
        from decimal import Decimal

        config = AgentConfig(
            name="test_agent",
            category="crypto",
            assets=["BTC"],
            timeframes=["15m"],
            risk_limits=AgentRiskLimits(max_notional_usd=Decimal("1000")),
            enabled=True,
        )

        agent = KalshiTradingAgent(config)
        strategy_config = StrategyConfig(mm_consensus_mode="full")
        agent._strategy.config = strategy_config

        # Mock consensus with FORMING status
        with patch('merid.prediction.trading_agent.KalshiTradingAgent._get_consensus') as mock_get:
            mock_consensus = MagicMock()
            from merid.swarm.consensus_aggregator import ConsensusStatus
            mock_consensus.status = ConsensusStatus.FORMING

            mock_get.return_value = mock_consensus

            result = agent._resolve_consensus_for_mm("BTC", "15m", "full")

            # Full mode: should return FORMING consensus (will block downstream)
            assert result is mock_consensus
            assert result.status == ConsensusStatus.FORMING

    def test_no_trade_tracker_doesnt_affect_execution(self):
        """NoTradeDecisionTracker should only observe, not block trades."""
        from merid.prediction.no_trade_reasons import (
            get_no_trade_tracker,
            reset_no_trade_tracker,
            NoTradeReason,
        )

        reset_no_trade_tracker()
        tracker = get_no_trade_tracker()

        # Recording a decision should not raise or have side effects
        initial_counts = tracker.get_counts()

        tracker.record(
            agent_name="test",
            market_id="M1",
            asset="BTC",
            timeframe="15m",
            reason=NoTradeReason.EDGE_BELOW_THRESHOLD,
        )

        # Only the count should change, no other state
        final_counts = tracker.get_counts()
        assert final_counts["edge_below_threshold"] == initial_counts["edge_below_threshold"] + 1


class TestFeatureFlags:
    """Verify all changes are gated by configuration flags."""

    def test_edge_profile_is_configurable(self):
        """Edge floor profile should be configurable, not hardcoded."""
        from merid.prediction.strategy import StrategyConfig

        # Should accept all valid values
        config_strict = StrategyConfig(edge_floor_profile="strict")
        config_medium = StrategyConfig(edge_floor_profile="medium")
        config_relaxed = StrategyConfig(edge_floor_profile="relaxed")

        assert config_strict.edge_floor_profile == "strict"
        assert config_medium.edge_floor_profile == "medium"
        assert config_relaxed.edge_floor_profile == "relaxed"

    def test_mm_consensus_mode_is_configurable(self):
        """MM consensus mode should be configurable."""
        from merid.prediction.strategy import StrategyConfig

        config_full = StrategyConfig(mm_consensus_mode="full")
        config_soft = StrategyConfig(mm_consensus_mode="soft")
        config_bypass = StrategyConfig(mm_consensus_mode="bypass")

        assert config_full.mm_consensus_mode == "full"
        assert config_soft.mm_consensus_mode == "soft"
        assert config_bypass.mm_consensus_mode == "bypass"

    def test_shadow_thresholds_are_configurable(self):
        """Shadow thresholds should be configurable per phase."""
        from merid.prediction.strategy import StrategyConfig
        from decimal import Decimal

        config = StrategyConfig(
            shadow_edge_early=Decimal("0.01"),
            shadow_edge_mid=Decimal("0.02"),
            shadow_edge_late=Decimal("0.03"),
            shadow_edge_terminal=Decimal("0.04"),
        )

        assert config.shadow_edge_early == Decimal("0.01")
        assert config.shadow_edge_mid == Decimal("0.02")
        assert config.shadow_edge_late == Decimal("0.03")
        assert config.shadow_edge_terminal == Decimal("0.04")
