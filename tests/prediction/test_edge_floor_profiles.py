"""Tests for edge floor profile and shadow threshold logic in KalshiStrategy."""

from decimal import Decimal
from datetime import datetime, timezone, timedelta

import pytest

from merid.prediction.strategy import (
    KalshiStrategy,
    StrategyConfig,
    ExpiryPhase,
    SignalAction,
)
from merid.prediction.model import (
    MarketSnapshot,
    ContractState,
    EdgeEstimate,
    ImpliedProbability,
    PredictionMarketModel,
)


class TestEdgeFloorProfile:
    """Tests for edge_floor_profile parameter."""

    def test_strict_profile_uses_baseline_thresholds(self):
        """Strict profile should use unmodified thresholds."""
        config = StrategyConfig(
            edge_floor_profile="strict",
            min_edge_early=Decimal("0.05"),
            min_edge_mid=Decimal("0.04"),
            min_edge_late=Decimal("0.03"),
            min_edge_terminal=Decimal("0.02"),
        )
        strategy = KalshiStrategy(config=config)

        # Test each phase
        assert strategy._get_edge_threshold(ExpiryPhase.EARLY) == Decimal("0.05")
        assert strategy._get_edge_threshold(ExpiryPhase.MID) == Decimal("0.04")
        assert strategy._get_edge_threshold(ExpiryPhase.LATE) == Decimal("0.03")
        assert strategy._get_edge_threshold(ExpiryPhase.TERMINAL) == Decimal("0.02")

    def test_medium_profile_relaxes_40_percent(self):
        """Medium profile should reduce thresholds by 40%."""
        config = StrategyConfig(
            edge_floor_profile="medium",
            min_edge_early=Decimal("0.05"),  # Should become 0.03
            min_edge_mid=Decimal("0.04"),    # Should become 0.024
            min_edge_late=Decimal("0.03"),   # Should become 0.018
            min_edge_terminal=Decimal("0.02"),  # Should become 0.012
        )
        strategy = KalshiStrategy(config=config)

        # Test each phase (60% of original = 40% reduction)
        assert strategy._get_edge_threshold(ExpiryPhase.EARLY) == Decimal("0.05") * Decimal("0.6")
        assert strategy._get_edge_threshold(ExpiryPhase.MID) == Decimal("0.04") * Decimal("0.6")
        assert strategy._get_edge_threshold(ExpiryPhase.LATE) == Decimal("0.03") * Decimal("0.6")
        assert strategy._get_edge_threshold(ExpiryPhase.TERMINAL) == Decimal("0.02") * Decimal("0.6")

    def test_relaxed_profile_relaxes_60_percent(self):
        """Relaxed profile should reduce thresholds by 60%."""
        config = StrategyConfig(
            edge_floor_profile="relaxed",
            min_edge_early=Decimal("0.05"),  # Should become 0.02
            min_edge_mid=Decimal("0.04"),    # Should become 0.016
            min_edge_late=Decimal("0.03"),   # Should become 0.012
            min_edge_terminal=Decimal("0.02"),  # Should become 0.008
        )
        strategy = KalshiStrategy(config=config)

        # Test each phase (40% of original = 60% reduction)
        assert strategy._get_edge_threshold(ExpiryPhase.EARLY) == Decimal("0.05") * Decimal("0.4")
        assert strategy._get_edge_threshold(ExpiryPhase.MID) == Decimal("0.04") * Decimal("0.4")
        assert strategy._get_edge_threshold(ExpiryPhase.LATE) == Decimal("0.03") * Decimal("0.4")
        assert strategy._get_edge_threshold(ExpiryPhase.TERMINAL) == Decimal("0.02") * Decimal("0.4")

    def test_unknown_profile_defaults_to_strict(self):
        """Unknown profile should fall back to strict behavior."""
        config = StrategyConfig(
            edge_floor_profile="unknown_profile",
            min_edge_early=Decimal("0.05"),
        )
        strategy = KalshiStrategy(config=config)

        # Should use strict (unmodified) threshold
        assert strategy._get_edge_threshold(ExpiryPhase.EARLY) == Decimal("0.05")


class TestShadowEdgeThresholds:
    """Tests for shadow edge threshold logic."""

    def test_shadow_edge_defaults_to_zero(self):
        """Default shadow thresholds should be 0.00."""
        config = StrategyConfig()
        strategy = KalshiStrategy(config=config)

        assert strategy._shadow_edge_for_phase(ExpiryPhase.EARLY) == Decimal("0.00")
        assert strategy._shadow_edge_for_phase(ExpiryPhase.MID) == Decimal("0.00")
        assert strategy._shadow_edge_for_phase(ExpiryPhase.LATE) == Decimal("0.00")
        assert strategy._shadow_edge_for_phase(ExpiryPhase.TERMINAL) == Decimal("0.00")

    def test_shadow_edge_can_be_configured(self):
        """Shadow thresholds should be configurable per phase."""
        config = StrategyConfig(
            shadow_edge_early=Decimal("0.01"),
            shadow_edge_mid=Decimal("0.015"),
            shadow_edge_late=Decimal("0.02"),
            shadow_edge_terminal=Decimal("0.025"),
        )
        strategy = KalshiStrategy(config=config)

        assert strategy._shadow_edge_for_phase(ExpiryPhase.EARLY) == Decimal("0.01")
        assert strategy._shadow_edge_for_phase(ExpiryPhase.MID) == Decimal("0.015")
        assert strategy._shadow_edge_for_phase(ExpiryPhase.LATE) == Decimal("0.02")
        assert strategy._shadow_edge_for_phase(ExpiryPhase.TERMINAL) == Decimal("0.025")

    def test_shadow_edge_none_defaults_to_zero(self):
        """None shadow thresholds should default to 0.00."""
        config = StrategyConfig(
            shadow_edge_early=None,
            shadow_edge_mid=None,
            shadow_edge_late=None,
            shadow_edge_terminal=None,
        )
        strategy = KalshiStrategy(config=config)

        assert strategy._shadow_edge_for_phase(ExpiryPhase.EARLY) == Decimal("0.00")
        assert strategy._shadow_edge_for_phase(ExpiryPhase.MID) == Decimal("0.00")
        assert strategy._shadow_edge_for_phase(ExpiryPhase.LATE) == Decimal("0.00")
        assert strategy._shadow_edge_for_phase(ExpiryPhase.TERMINAL) == Decimal("0.00")


class TestEdgeGateWithProfiles:
    """Integration tests for edge gating with different profiles."""

    def _create_snapshot_with_edge(self, net_edge: Decimal, minutes_to_expiry: float = 30.0) -> MarketSnapshot:
        """Helper to create a market snapshot with specific net edge."""
        model = PredictionMarketModel()

        # Create implied probabilities
        # For simplicity, use mid=0.50 and manipulate edge via our estimate
        implied = model.implied_probabilities(
            yes_bid=Decimal("49"),
            yes_ask=Decimal("51"),
            no_bid=Decimal("49"),
            no_ask=Decimal("51"),
        )

        snapshot = MarketSnapshot(
            market_id="KXBTC-TEST",
            event_id="KXBTC-EVENT",
            title="Test Market",
            state=ContractState.TRADING,
            implied=implied,
            volume=Decimal("10000"),
            open_interest=Decimal("5000"),
            timestamp=datetime.now(timezone.utc),
            minutes_to_expiry=minutes_to_expiry,
        )

        # Mock the edge estimate directly
        snapshot._edge_estimate = EdgeEstimate(
            probability=Decimal("0.55"),
            net_edge=net_edge,
            confidence=Decimal("0.7"),
            raw_edge=net_edge + Decimal("0.01"),  # Simulate some fee drag
        )

        return snapshot

    def test_strict_profile_blocks_below_threshold(self):
        """Strict profile should block trades below threshold."""
        config = StrategyConfig(
            edge_floor_profile="strict",
            min_edge_early=Decimal("0.05"),
        )
        strategy = KalshiStrategy(config=config)

        # Edge = 3%, threshold = 5% → should block
        snapshot = self._create_snapshot_with_edge(
            net_edge=Decimal("0.03"),
            minutes_to_expiry=2000.0,  # Early phase
        )

        signal = strategy.evaluate(snapshot, archetype="directional")

        assert signal.action == SignalAction.NO_ACTION
        assert "below" in signal.reason.lower()

    def test_strict_profile_allows_above_threshold(self):
        """Strict profile should allow trades above threshold."""
        config = StrategyConfig(
            edge_floor_profile="strict",
            min_edge_early=Decimal("0.05"),
            min_confidence=Decimal("0.5"),
        )
        strategy = KalshiStrategy(config=config)

        # Edge = 6%, threshold = 5% → should pass
        snapshot = self._create_snapshot_with_edge(
            net_edge=Decimal("0.06"),
            minutes_to_expiry=2000.0,  # Early phase
        )

        signal = strategy.evaluate(snapshot, archetype="directional")

        # Should generate actionable signal (not NO_ACTION)
        assert signal.action != SignalAction.NO_ACTION

    def test_medium_profile_allows_relaxed_threshold(self):
        """Medium profile should allow trades that strict would block."""
        config_strict = StrategyConfig(
            edge_floor_profile="strict",
            min_edge_early=Decimal("0.05"),
        )
        config_medium = StrategyConfig(
            edge_floor_profile="medium",
            min_edge_early=Decimal("0.05"),  # Same base, but will be reduced to 0.03
        )

        strategy_strict = KalshiStrategy(config=config_strict)
        strategy_medium = KalshiStrategy(config=config_medium)

        # Edge = 3.5%, strict threshold = 5%, medium threshold = 3%
        snapshot = self._create_snapshot_with_edge(
            net_edge=Decimal("0.035"),
            minutes_to_expiry=2000.0,
        )

        signal_strict = strategy_strict.evaluate(snapshot, archetype="directional")
        signal_medium = strategy_medium.evaluate(snapshot, archetype="directional")

        # Strict should block
        assert signal_strict.action == SignalAction.NO_ACTION

        # Medium should pass
        assert signal_medium.action != SignalAction.NO_ACTION

    def test_relaxed_profile_most_permissive(self):
        """Relaxed profile should be most permissive."""
        config = StrategyConfig(
            edge_floor_profile="relaxed",
            min_edge_early=Decimal("0.05"),  # Will be reduced to 0.02
            min_confidence=Decimal("0.5"),
        )
        strategy = KalshiStrategy(config=config)

        # Edge = 2.5%, relaxed threshold = 2%
        snapshot = self._create_snapshot_with_edge(
            net_edge=Decimal("0.025"),
            minutes_to_expiry=2000.0,
        )

        signal = strategy.evaluate(snapshot, archetype="directional")

        # Should pass with relaxed threshold
        assert signal.action != SignalAction.NO_ACTION

    def test_phase_affects_threshold(self):
        """Different expiry phases should use different thresholds."""
        config = StrategyConfig(
            edge_floor_profile="strict",
            min_edge_early=Decimal("0.05"),
            min_edge_terminal=Decimal("0.02"),
            min_confidence=Decimal("0.5"),
        )
        strategy = KalshiStrategy(config=config)

        # Edge = 3% should fail early but pass terminal
        edge = Decimal("0.03")

        snapshot_early = self._create_snapshot_with_edge(
            net_edge=edge,
            minutes_to_expiry=2000.0,  # Early: threshold 5%
        )
        snapshot_terminal = self._create_snapshot_with_edge(
            net_edge=edge,
            minutes_to_expiry=30.0,  # Terminal: threshold 2%
        )

        signal_early = strategy.evaluate(snapshot_early, archetype="directional")
        signal_terminal = strategy.evaluate(snapshot_terminal, archetype="directional")

        # Early should block (3% < 5%)
        assert signal_early.action == SignalAction.NO_ACTION

        # Terminal should pass (3% > 2%)
        assert signal_terminal.action != SignalAction.NO_ACTION
