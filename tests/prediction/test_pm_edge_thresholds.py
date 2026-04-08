"""Tests for PM edge threshold behavior — verifies threshold profiles, per-phase gates,
and crypto threshold application through the full PM agent lifecycle."""

from decimal import Decimal
from datetime import datetime, timezone

import pytest

from merid.prediction.strategy import KalshiStrategy, StrategyConfig, ExpiryPhase, SignalAction
from merid.prediction.model import (
    MarketSnapshot,
    ContractState,
    EdgeEstimate,
    PredictionMarketModel,
)
from merid.prediction.crypto_thresholds import apply_crypto_strategy_thresholds_to_config


def _make_implied(yes_prob_pct: float = 50.0):
    """Build ImpliedProbability from a YES probability expressed as a percentage."""
    model = PredictionMarketModel()
    p = max(1, min(99, int(yes_prob_pct)))
    return model.implied_probabilities(
        yes_bid=Decimal(str(p - 1)),
        yes_ask=Decimal(str(p)),
        no_bid=Decimal(str(100 - p - 1)),
        no_ask=Decimal(str(100 - p)),
    )


def _make_snapshot_with_edges(net_edge: Decimal, tte_hours: float = 30.0) -> MarketSnapshot:
    """Build a MarketSnapshot pre-loaded with a single speculative edge."""
    implied = _make_implied(55.0)
    snap = MarketSnapshot(
        market_id="KXBTC-TEST",
        event_id="KXBTC",
        title="BTC Test",
        state=ContractState.TRADING,
        implied=implied,
        volume=Decimal("5000"),
        open_interest=Decimal("2000"),
        time_to_expiry_hours=Decimal(str(tte_hours)),
    )
    snap.edges = [
        EdgeEstimate(
            market_id="KXBTC-TEST",
            side="yes",
            action="buy",
            market_prob=Decimal("0.50"),
            model_prob=Decimal("0.55"),
            raw_edge=net_edge + Decimal("0.01"),
            fee_drag=Decimal("0.005"),
            slippage_est=Decimal("0.005"),
            net_edge=net_edge,
            edge_type="speculative",
            confidence=Decimal("0.7"),
        )
    ]
    return snap


class TestStrictThresholds:
    """Tests for the strict (default) edge floor profile."""

    def test_strict_early_phase_blocks_below_5pct(self):
        config = StrategyConfig(edge_floor_profile="strict")
        strategy = KalshiStrategy(config)
        snap = _make_snapshot_with_edges(Decimal("0.03"), tte_hours=48.0)
        sig = strategy.evaluate(snap)
        assert sig.action == SignalAction.NO_ACTION

    def test_strict_early_phase_allows_at_5pct(self):
        config = StrategyConfig(
            edge_floor_profile="strict",
            min_edge_early=Decimal("0.05"),
        )
        strategy = KalshiStrategy(config)
        snap = _make_snapshot_with_edges(Decimal("0.05"), tte_hours=48.0)
        sig = strategy.evaluate(snap)
        # At exactly the threshold, action should be allowed
        assert sig.action != SignalAction.NO_ACTION

    def test_strict_terminal_phase_threshold_lower(self):
        config = StrategyConfig(edge_floor_profile="strict")
        strategy = KalshiStrategy(config)
        # Terminal phase: threshold = 0.02; edge = 0.025 should pass
        snap = _make_snapshot_with_edges(Decimal("0.025"), tte_hours=0.5)
        sig = strategy.evaluate(snap)
        assert sig.action != SignalAction.NO_ACTION

    def test_get_edge_threshold_method_exists_and_works(self):
        """_get_edge_threshold is a public alias for _min_edge_for_phase."""
        config = StrategyConfig(
            edge_floor_profile="strict",
            min_edge_early=Decimal("0.05"),
            min_edge_mid=Decimal("0.04"),
            min_edge_late=Decimal("0.03"),
            min_edge_terminal=Decimal("0.02"),
        )
        strategy = KalshiStrategy(config)
        assert strategy._get_edge_threshold(ExpiryPhase.EARLY) == Decimal("0.05")
        assert strategy._get_edge_threshold(ExpiryPhase.MID) == Decimal("0.04")
        assert strategy._get_edge_threshold(ExpiryPhase.LATE) == Decimal("0.03")
        assert strategy._get_edge_threshold(ExpiryPhase.TERMINAL) == Decimal("0.02")


class TestMediumRelaxedProfiles:
    """Tests for medium and relaxed edge floor profiles."""

    def test_medium_relaxes_threshold(self):
        strict_cfg = StrategyConfig(edge_floor_profile="strict", min_edge_early=Decimal("0.05"))
        medium_cfg = StrategyConfig(edge_floor_profile="medium", min_edge_early=Decimal("0.05"))

        strict_strat = KalshiStrategy(strict_cfg)
        medium_strat = KalshiStrategy(medium_cfg)

        t_strict = strict_strat._get_edge_threshold(ExpiryPhase.EARLY)
        t_medium = medium_strat._get_edge_threshold(ExpiryPhase.EARLY)

        assert t_medium < t_strict

    def test_relaxed_more_lenient_than_medium(self):
        medium_cfg = StrategyConfig(edge_floor_profile="medium", min_edge_early=Decimal("0.05"))
        relaxed_cfg = StrategyConfig(edge_floor_profile="relaxed", min_edge_early=Decimal("0.05"))

        medium_strat = KalshiStrategy(medium_cfg)
        relaxed_strat = KalshiStrategy(relaxed_cfg)

        t_medium = medium_strat._get_edge_threshold(ExpiryPhase.EARLY)
        t_relaxed = relaxed_strat._get_edge_threshold(ExpiryPhase.EARLY)

        assert t_relaxed < t_medium


class TestCryptoThresholdApplication:
    """Tests verifying crypto thresholds get applied to StrategyConfig."""

    def test_crypto_agent_gets_lenient_thresholds(self):
        """A BTC agent should get modern (lenient) crypto thresholds."""
        config = StrategyConfig()
        original_early = config.min_edge_early  # strict default = 0.05
        applied = apply_crypto_strategy_thresholds_to_config(
            config, agent_name="BTC_15M", profile="modern"
        )
        assert applied is True
        assert config.min_edge_early < original_early

    def test_strategy_uses_applied_thresholds(self):
        """KalshiStrategy should reflect crypto thresholds after they are applied."""
        config = StrategyConfig()
        apply_crypto_strategy_thresholds_to_config(
            config, agent_name="ETH_1H", profile="modern"
        )
        strategy = KalshiStrategy(config)

        # Early-phase threshold for modern should be < 0.05 (strict)
        t = strategy._get_edge_threshold(ExpiryPhase.EARLY)
        assert t < Decimal("0.05")

    def test_non_crypto_agent_retains_defaults(self):
        """Non-crypto agents must not have crypto thresholds applied."""
        config = StrategyConfig()
        applied = apply_crypto_strategy_thresholds_to_config(
            config, agent_name="MACRO_DIRECTIONAL", profile="modern"
        )
        assert applied is False
        assert config.edge_floor_profile == "strict"


class TestShadowThresholds:
    """Tests for shadow threshold observability (not enforced)."""

    def test_shadow_threshold_zero_by_default(self):
        config = StrategyConfig()
        strategy = KalshiStrategy(config)
        assert strategy._shadow_edge_for_phase(ExpiryPhase.EARLY) == Decimal("0.00")
        assert strategy._shadow_edge_for_phase(ExpiryPhase.TERMINAL) == Decimal("0.00")

    def test_shadow_threshold_does_not_block_trade(self):
        """Shadow thresholds must not block trades — they are for logging only."""
        config = StrategyConfig(
            edge_floor_profile="strict",
            min_edge_early=Decimal("0.05"),
            shadow_edge_early=Decimal("0.10"),  # Shadow > min edge; should not block
        )
        strategy = KalshiStrategy(config)
        # Edge is 6% > min 5% → should be allowed despite shadow being 10%
        snap = _make_snapshot_with_edges(Decimal("0.06"), tte_hours=48.0)
        sig = strategy.evaluate(snap)
        assert sig.action != SignalAction.NO_ACTION
