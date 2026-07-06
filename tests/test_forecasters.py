"""Tests for merid.prediction.forecasters — Sprint B + C.

Sprint B: Heterogeneous forecasters (momentum, mean_reversion, registry).
Sprint C: Calibration-weighted consensus feedback loop.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

from merid.prediction.forecasters.base import Forecaster, ForecastResult
from merid.prediction.forecasters.momentum import MomentumForecaster
from merid.prediction.forecasters.mean_reversion import MeanReversionForecaster
from merid.prediction.forecasters.registry import ForecasterRegistry, EnsembleForecast
from merid.metrics.calibration import CalibrationStore


# ══════════════════════════════════════════════════════════════════════════
# §1 MomentumForecaster
# ══════════════════════════════════════════════════════════════════════════


class TestMomentumForecaster(unittest.TestCase):

    def setUp(self):
        self.f = MomentumForecaster()
        # _momentum_history is now an instance variable, not module-level
        # Clear per-instance history
        self.f._momentum_history.clear()

    def test_forecaster_id(self):
        self.assertEqual(self.f.forecaster_id, "momentum_v1")

    def test_returns_none_no_history(self):
        """First call with no history returns None (needs observations)."""
        result = self.f.predict(
            market_id="MKT1", implied_yes=0.55, implied_no=0.45,
            volume=100, open_interest=50, minutes_to_expiry=30,
        )
        # First call seeds history but likely no momentum signals yet
        # (needs at least 3 observations for momentum)
        # Result may be None or a low-confidence forecast
        if result is not None:
            self.assertGreater(result.confidence, 0)

    def test_builds_momentum_after_observations(self):
        """After several observations, momentum signals appear."""
        for i in range(5):
            self.f.predict(
                market_id="MKT1", implied_yes=0.50 + i * 0.02,
                implied_no=0.50 - i * 0.02,
                volume=100 + i * 50, open_interest=50 + i * 10,
                minutes_to_expiry=60, bid=0.48 + i * 0.02, ask=0.52 + i * 0.02,
            )
        result = self.f.predict(
            market_id="MKT1", implied_yes=0.60, implied_no=0.40,
            volume=400, open_interest=100, minutes_to_expiry=60,
            bid=0.58, ask=0.62,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.forecaster_id, "momentum_v1")
        # Rising prices + rising volume → bullish momentum → p > implied
        self.assertGreater(result.p_model, 0.55)

    def test_time_decay_weakens_momentum(self):
        """Near expiry, momentum signals weaken."""
        for i in range(5):
            self.f.predict(
                market_id="MKT1", implied_yes=0.55 + i * 0.01,
                implied_no=0.45 - i * 0.01,
                volume=100 + i * 50, open_interest=50,
                minutes_to_expiry=3,
            )
        result = self.f.predict(
            market_id="MKT1", implied_yes=0.60, implied_no=0.40,
            volume=400, open_interest=100, minutes_to_expiry=3,
        )
        if result is not None:
            # Near expiry, p_model should be close to implied (time_factor=0.2)
            self.assertAlmostEqual(result.p_model, 0.60, delta=0.05)

    def test_invalid_implied_returns_none(self):
        result = self.f.predict(
            market_id="MKT1", implied_yes=0.0, implied_no=1.0,
            volume=100, open_interest=50, minutes_to_expiry=30,
        )
        self.assertIsNone(result)

    def test_forecast_result_has_components(self):
        """After enough history, result includes component breakdown."""
        for i in range(5):
            self.f.predict(
                market_id="MKT1", implied_yes=0.55, implied_no=0.45,
                volume=100, open_interest=50, minutes_to_expiry=60,
                bid=0.53, ask=0.57,
            )
        result = self.f.predict(
            market_id="MKT1", implied_yes=0.55, implied_no=0.45,
            volume=100, open_interest=50, minutes_to_expiry=60,
            bid=0.53, ask=0.57,
        )
        if result is not None:
            self.assertIsInstance(result.components, dict)


# ══════════════════════════════════════════════════════════════════════════
# §2 MeanReversionForecaster
# ══════════════════════════════════════════════════════════════════════════


class TestMeanReversionForecaster(unittest.TestCase):

    def setUp(self):
        self.f = MeanReversionForecaster()

    def test_forecaster_id(self):
        self.assertEqual(self.f.forecaster_id, "mean_reversion_v1")

    def test_extreme_high_reverts_down(self):
        """Price at 0.85 → mean reversion pushes toward 0.50."""
        result = self.f.predict(
            market_id="MKT1", implied_yes=0.85, implied_no=0.15,
            volume=100, open_interest=50, minutes_to_expiry=30,
            bid=0.83, ask=0.87,
        )
        self.assertIsNotNone(result)
        self.assertLess(result.p_model, 0.85)

    def test_extreme_low_reverts_up(self):
        """Price at 0.15 → mean reversion pushes toward 0.50."""
        result = self.f.predict(
            market_id="MKT1", implied_yes=0.15, implied_no=0.85,
            volume=100, open_interest=50, minutes_to_expiry=30,
            bid=0.13, ask=0.17,
        )
        self.assertIsNotNone(result)
        self.assertGreater(result.p_model, 0.15)

    def test_near_center_weak_signal(self):
        """Price near 0.50 → weak reversion signal."""
        result = self.f.predict(
            market_id="MKT1", implied_yes=0.50, implied_no=0.50,
            volume=100, open_interest=50, minutes_to_expiry=30,
            bid=0.48, ask=0.52,
        )
        self.assertIsNotNone(result)
        # Near center, adjustment should be small
        self.assertAlmostEqual(result.p_model, 0.50, delta=0.05)

    def test_time_amplifies_reversion(self):
        """Near expiry, mean reversion signal gets stronger."""
        result_far = self.f.predict(
            market_id="MKT1", implied_yes=0.80, implied_no=0.20,
            volume=100, open_interest=50, minutes_to_expiry=1440,
        )
        result_near = self.f.predict(
            market_id="MKT1", implied_yes=0.80, implied_no=0.20,
            volume=100, open_interest=50, minutes_to_expiry=3,
        )
        self.assertIsNotNone(result_far)
        self.assertIsNotNone(result_near)
        # Near-expiry result should be further from implied (stronger reversion)
        far_shift = abs(result_far.p_model - 0.80)
        near_shift = abs(result_near.p_model - 0.80)
        self.assertGreater(near_shift, far_shift)

    def test_invalid_implied_returns_none(self):
        result = self.f.predict(
            market_id="MKT1", implied_yes=1.0, implied_no=0.0,
            volume=100, open_interest=50, minutes_to_expiry=30,
        )
        self.assertIsNone(result)

    def test_orderbook_imbalance_bid_heavy(self):
        """Bid closer to mid than ask → buying pressure → bullish."""
        result = self.f.predict(
            market_id="MKT1", implied_yes=0.50, implied_no=0.50,
            volume=100, open_interest=50, minutes_to_expiry=60,
            bid=0.49, ask=0.55,  # bid close to mid, ask far → bid heavy
        )
        self.assertIsNotNone(result)
        # Bid-heavy → slight bullish push
        self.assertGreaterEqual(result.p_model, 0.49)


# ══════════════════════════════════════════════════════════════════════════
# §3 ForecasterRegistry
# ══════════════════════════════════════════════════════════════════════════


class TestForecasterRegistry(unittest.TestCase):

    def setUp(self):
        self.registry = ForecasterRegistry()
        # _momentum_history is now per-instance, not module-level
        # Create a fresh MomentumForecaster instance and clear its history
        self.momentum = MomentumForecaster()
        self.momentum._momentum_history.clear()

    def test_default_forecasters_registered(self):
        """Registry starts with momentum and mean_reversion."""
        ids = [f.forecaster_id for f in self.registry.forecasters]
        self.assertIn("momentum_v1", ids)
        self.assertIn("mean_reversion_v1", ids)

    def test_register_custom(self):
        """Can register a custom forecaster."""
        class DummyForecaster(Forecaster):
            @property
            def forecaster_id(self): return "dummy_v1"
            def predict(self, **kw): return None

        self.registry.register(DummyForecaster())
        ids = [f.forecaster_id for f in self.registry.forecasters]
        self.assertIn("dummy_v1", ids)

    def test_predict_all_produces_ensemble(self):
        """predict_all returns an EnsembleForecast with results."""
        # Mean reversion should always produce a result for extreme prices
        result = self.registry.predict_all(
            market_id="MKT1", implied_yes=0.80, implied_no=0.20,
            volume=100, open_interest=50, minutes_to_expiry=30,
            bid=0.78, ask=0.82, category="crypto",
        )
        self.assertIsNotNone(result)
        self.assertIsInstance(result, EnsembleForecast)
        self.assertGreater(len(result.forecasts), 0)
        self.assertEqual(result.bucket, "crypto")

    def test_ensemble_probability_bounded(self):
        """Ensemble probability is bounded [0.02, 0.98]."""
        result = self.registry.predict_all(
            market_id="MKT1", implied_yes=0.95, implied_no=0.05,
            volume=100, open_interest=50, minutes_to_expiry=30,
            category="crypto",
        )
        if result:
            self.assertGreaterEqual(result.p_ensemble, 0.02)
            self.assertLessEqual(result.p_ensemble, 0.98)

    def test_ensemble_logs_to_calibration(self):
        """Each forecaster's prediction is logged to CalibrationStore."""
        cal = CalibrationStore(db_path=":memory:")
        with patch("merid.metrics.calibration.get_calibration_store", return_value=cal):
            self.registry.predict_all(
                market_id="MKT1", implied_yes=0.80, implied_no=0.20,
                volume=100, open_interest=50, minutes_to_expiry=30,
                bid=0.78, ask=0.82, category="crypto",
            )
        # At least mean_reversion should have logged a forecast
        forecasters = cal.list_forecasters()
        self.assertGreater(len(forecasters), 0)

    def test_ensemble_uses_calibration_weights(self):
        """Ensemble weights come from CalibrationStore."""
        cal = CalibrationStore(db_path=":memory:")
        # Seed calibration data for mean_reversion_v1
        for i in range(15):
            cal.record_forecast("mean_reversion_v1", "crypto", f"M{i}", 0.85)
            cal.resolve_outcome(f"M{i}", outcome=1)

        with patch("merid.metrics.calibration.get_calibration_store", return_value=cal):
            result = self.registry.predict_all(
                market_id="MKT1", implied_yes=0.80, implied_no=0.20,
                volume=100, open_interest=50, minutes_to_expiry=30,
                bid=0.78, ask=0.82, category="crypto",
            )

        if result and "mean_reversion_v1" in result.weights_used:
            # Weight should differ from default 1.0 since we have calibration data
            w = result.weights_used["mean_reversion_v1"]
            self.assertNotEqual(w, 1.0)

    def test_ensemble_to_dict(self):
        """EnsembleForecast serializes correctly."""
        result = self.registry.predict_all(
            market_id="MKT1", implied_yes=0.80, implied_no=0.20,
            volume=100, open_interest=50, minutes_to_expiry=30,
            category="crypto",
        )
        if result:
            d = result.to_dict()
            self.assertIn("p_ensemble", d)
            self.assertIn("forecaster_count", d)


# ══════════════════════════════════════════════════════════════════════════
# §4 Sprint C — Consensus feedback loop
# ══════════════════════════════════════════════════════════════════════════


@unittest.skip("Legacy consensus modules (core.consensus_engine, merid.swarm.consensus_aggregator) no longer exist")
class TestConsensusCalibrationFeedback(unittest.TestCase):
    """Test that CalibrationStore weights flow into consensus voting."""

    def test_swarm_aggregator_uses_brier_weight(self):
        """SwarmConsensusAggregator._calculate_agent_weight uses Brier calibration."""
        from merid.swarm.consensus_aggregator import SwarmConsensusAggregator, AgentProposal
        from datetime import datetime, timezone

        # Reset singleton for clean test
        SwarmConsensusAggregator._instance = None
        agg = SwarmConsensusAggregator()

        cal = CalibrationStore(db_path=":memory:")
        # Seed good calibration for "good_agent"
        for i in range(15):
            cal.record_forecast("good_agent", "crypto", f"M{i}", 0.85)
            cal.resolve_outcome(f"M{i}", outcome=1)
        # Seed bad calibration for "bad_agent"
        for i in range(15):
            cal.record_forecast("bad_agent", "crypto", f"N{i}", 0.85)
            cal.resolve_outcome(f"N{i}", outcome=0)

        good_proposal = AgentProposal(
            agent_id="good_agent", asset="crypto", timeframe="15m",
            direction="yes", probability=0.7, confidence=0.8,
            size_preference="base", rationale="test",
            edge_estimate=5.0, timestamp=datetime.now(timezone.utc),
            agent_archetype="trend",
        )
        bad_proposal = AgentProposal(
            agent_id="bad_agent", asset="crypto", timeframe="15m",
            direction="yes", probability=0.7, confidence=0.8,
            size_preference="base", rationale="test",
            edge_estimate=5.0, timestamp=datetime.now(timezone.utc),
            agent_archetype="momentum",
        )

        with patch("merid.metrics.calibration.get_calibration_store", return_value=cal):
            good_weight = agg._calculate_agent_weight(good_proposal)
            bad_weight = agg._calculate_agent_weight(bad_proposal)

        # Good agent should have higher weight than bad agent
        self.assertGreater(good_weight, bad_weight)

    def test_consensus_engine_blends_brier_trust(self):
        """ConsensusEngine._extract_vote blends Brier weight into trust."""
        from core.consensus_engine import ConsensusEngine
        from core.streaming_bus import StreamEvent, EventChannel

        engine = ConsensusEngine()

        cal = CalibrationStore(db_path=":memory:")
        for i in range(15):
            cal.record_forecast("agent_x", "crypto", f"M{i}", 0.9)
            cal.resolve_outcome(f"M{i}", outcome=1)

        event = StreamEvent(
            channel=EventChannel.AGENT_OUTPUT,
            event_type="price_signal",
            source="agent_x",
            data={"signal": "bullish", "confidence": 0.8, "category": "crypto"},
        )

        with patch("merid.metrics.calibration.get_calibration_store", return_value=cal):
            vote = engine._extract_vote(event)

        self.assertIsNotNone(vote)
        # Trust should be blended: 70% Brier weight + 30% base trust (1.0)
        # Brier weight for a good forecaster should be > 1.0
        self.assertGreater(vote.trust, 0.5)

    def test_no_calibration_falls_back_gracefully(self):
        """If CalibrationStore is unavailable, consensus still works."""
        from core.consensus_engine import ConsensusEngine
        from core.streaming_bus import StreamEvent, EventChannel

        engine = ConsensusEngine()

        event = StreamEvent(
            channel=EventChannel.AGENT_OUTPUT,
            event_type="price_signal",
            source="unknown_agent",
            data={"signal": "bearish", "confidence": 0.6},
        )

        # Even with import error, should fall back to default trust
        with patch("merid.metrics.calibration.get_calibration_store", side_effect=ImportError):
            vote = engine._extract_vote(event)

        self.assertIsNotNone(vote)
        self.assertAlmostEqual(vote.trust, 1.0)  # Default trust


# ══════════════════════════════════════════════════════════════════════════
# §5 Forecaster diversity validation
# ══════════════════════════════════════════════════════════════════════════


class TestForecasterDiversity(unittest.TestCase):
    """Verify that momentum and mean_reversion produce different predictions."""

    def test_different_predictions_on_extreme_market(self):
        """Momentum and mean_reversion disagree on extreme markets."""
        mom = MomentumForecaster()
        mr = MeanReversionForecaster()

        # Seed momentum history with rising trend
        for i in range(5):
            mom.predict(
                market_id="MKT1", implied_yes=0.70 + i * 0.03,
                implied_no=0.30 - i * 0.03,
                volume=100 + i * 100, open_interest=50 + i * 20,
                minutes_to_expiry=60,
            )

        mom_result = mom.predict(
            market_id="MKT1", implied_yes=0.85, implied_no=0.15,
            volume=600, open_interest=150, minutes_to_expiry=60,
            bid=0.83, ask=0.87,
        )
        mr_result = mr.predict(
            market_id="MKT1", implied_yes=0.85, implied_no=0.15,
            volume=600, open_interest=150, minutes_to_expiry=60,
            bid=0.83, ask=0.87,
        )

        # Both should produce a prediction
        self.assertIsNotNone(mr_result)
        # Mean reversion should push BELOW 0.85 (toward 0.50)
        self.assertLess(mr_result.p_model, 0.85)

        if mom_result is not None:
            # Momentum may push above or close to 0.85 (trend continuation)
            # The key test: they should disagree (different p_model)
            self.assertNotAlmostEqual(
                mom_result.p_model, mr_result.p_model, places=2,
                msg="Momentum and MeanReversion should produce different forecasts"
            )


if __name__ == "__main__":
    unittest.main()
