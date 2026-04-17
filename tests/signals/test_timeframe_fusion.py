"""
Timeframe Fusion Engine Tests
=============================
Tests for multi-timeframe signal fusion logic.
"""

import unittest
from typing import Optional

from merid.signals.ta_models import SignalScore, MarketStructure, FusedClusterSignal
from merid.signals.timeframe_fusion import TimeframeFusionEngine, FusionConfig


class TestTimeframeFusion(unittest.TestCase):
    """Tests for signal fusion logic."""

    def setUp(self):
        self.engine = TimeframeFusionEngine()

    def _make_signal(
        self,
        asset: str,
        timeframe: str,
        direction: str,
        confidence: float,
        quality: float,
        contra_trend: bool = False,
        divergence_score: float = 0.0,
    ) -> SignalScore:
        """Create a test SignalScore."""
        return SignalScore(
            asset=asset,
            timeframe=timeframe,
            timestamp=0,
            direction=direction,
            confidence=confidence,
            quality_score=quality,
            rationale_tags=["test_signal"],
            contra_trend=contra_trend,
            divergence_score=divergence_score,
        )

    def test_aligned_signals_produce_tradeable(self):
        """All TFs aligned should produce high-confidence tradeable signal."""
        higher = self._make_signal("BTC", "1h", "long", 0.8, 0.7)
        primary = self._make_signal("BTC", "15m", "long", 0.75, 0.6)
        lower = self._make_signal("BTC", "5m", "long", 0.7, 0.5)
        market = MarketStructure(asset="BTC", timestamp=0, trend_regime="uptrend")

        fused = self.engine.fuse("BTC", "15m", higher, primary, lower, market)

        self.assertEqual(fused.direction, "long")
        self.assertTrue(fused.is_tradeable())
        self.assertTrue(fused.multi_tf_agreement)

    def test_contra_trend_signal_penalty(self):
        """Contra-trend signal should have reduced confidence."""
        higher = self._make_signal("BTC", "1h", "short", 0.8, 0.7)  # Downtrend
        primary = self._make_signal("BTC", "15m", "long", 0.75, 0.6, contra_trend=True)
        lower = self._make_signal("BTC", "5m", "long", 0.7, 0.5)
        market = MarketStructure(asset="BTC", timestamp=0, trend_regime="downtrend")

        fused = self.engine.fuse("BTC", "15m", higher, primary, lower, market)

        # Contra-trend should have lower confidence than primary
        self.assertLess(fused.confidence, primary.confidence)

    def test_flat_primary_signal_rejected(self):
        """Flat primary signal should always be rejected."""
        higher = self._make_signal("BTC", "1h", "long", 0.8, 0.7)
        primary = self._make_signal("BTC", "15m", "flat", 0.0, 0.0)
        lower = self._make_signal("BTC", "5m", "long", 0.7, 0.5)
        market = MarketStructure(asset="BTC", timestamp=0, trend_regime="uptrend")

        fused = self.engine.fuse("BTC", "15m", higher, primary, lower, market)

        self.assertEqual(fused.direction, "flat")
        self.assertFalse(fused.is_tradeable())

    def test_quality_affects_tradeability(self):
        """Higher quality should make signal tradeable."""
        market = MarketStructure(asset="BTC", timestamp=0, trend_regime="uptrend")

        # High quality
        primary_high = self._make_signal("BTC", "15m", "long", 0.9, 0.8)
        fused_high = self.engine.fuse("BTC", "15m", None, primary_high, None, market)

        # Low quality
        primary_low = self._make_signal("BTC", "15m", "long", 0.6, 0.3)
        fused_low = self.engine.fuse("BTC", "15m", None, primary_low, None, market)

        self.assertTrue(fused_high.is_tradeable())
        self.assertFalse(fused_low.is_tradeable())

    def test_none_higher_lower_allowed(self):
        """Should work with None for higher or lower TF signals."""
        primary = self._make_signal("BTC", "15m", "long", 0.75, 0.6)
        market = MarketStructure(asset="BTC", timestamp=0, trend_regime="uptrend")

        fused = self.engine.fuse("BTC", "15m", None, primary, None, market)

        self.assertEqual(fused.direction, "long")
        self.assertIsNone(fused.higher_tf_signal)
        self.assertIsNone(fused.lower_tf_signal)

    def test_multi_tf_agreement_detection(self):
        """Multi-TF agreement should be detected."""
        market = MarketStructure(asset="BTC", timestamp=0, trend_regime="uptrend")

        # All aligned
        higher = self._make_signal("BTC", "1h", "long", 0.8, 0.7)
        primary = self._make_signal("BTC", "15m", "long", 0.75, 0.6)
        lower = self._make_signal("BTC", "5m", "long", 0.7, 0.5)

        fused_aligned = self.engine.fuse("BTC", "15m", higher, primary, lower, market)

        # Lower TF disagrees
        lower_disagree = self._make_signal("BTC", "5m", "short", 0.7, 0.5)
        fused_disagree = self.engine.fuse("BTC", "15m", higher, primary, lower_disagree, market)

        self.assertTrue(fused_aligned.multi_tf_agreement)
        self.assertFalse(fused_disagree.multi_tf_agreement)


if __name__ == "__main__":
    unittest.main()
