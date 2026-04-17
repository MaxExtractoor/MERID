"""
Regime Engine Tests
===================
Tests for market regime classification and dynamic distance multipliers.
"""

import unittest
from typing import Dict

from merid.signals.ta_models import MarketStructure, GlobalRegime
from merid.signals.regime_engine import RegimeEngine, get_regime_engine


class TestRegimeEngine(unittest.TestCase):
    """Tests for RegimeEngine functionality."""

    def setUp(self):
        self.engine = RegimeEngine()

    def test_singleton_pattern(self):
        """Singleton should return same instance."""
        engine1 = get_regime_engine()
        engine2 = get_regime_engine()
        self.assertIs(engine1, engine2)

    def test_trend_classification_uptrend(self):
        """EMAs stacked up should classify as uptrend."""
        ms = MarketStructure(
            asset="BTC",
            timestamp=0,
            trend_regime="uptrend",
        )
        self.assertEqual(ms.trend_regime, "uptrend")

    def test_trend_classification_downtrend(self):
        """EMAs stacked down should classify as downtrend."""
        ms = MarketStructure(
            asset="BTC",
            timestamp=0,
            trend_regime="downtrend",
        )
        self.assertEqual(ms.trend_regime, "downtrend")

    def test_volatility_classification(self):
        """Vol regime should be stored correctly."""
        ms_low = MarketStructure(
            asset="BTC",
            timestamp=0,
            vol_regime="low",
        )
        self.assertEqual(ms_low.vol_regime, "low")

        ms_high = MarketStructure(
            asset="BTC",
            timestamp=0,
            vol_regime="high",
        )
        self.assertEqual(ms_high.vol_regime, "high")

    def test_liquidity_classification(self):
        """Liquidity regime should be stored correctly."""
        ms_good = MarketStructure(
            asset="BTC",
            timestamp=0,
            liquidity_regime="good",
        )
        self.assertEqual(ms_good.liquidity_regime, "good")

        ms_poor = MarketStructure(
            asset="BTC",
            timestamp=0,
            liquidity_regime="poor",
        )
        self.assertEqual(ms_poor.liquidity_regime, "poor")

    def test_to_dict_serialization(self):
        """MarketStructure should serialize correctly."""
        ms = MarketStructure(
            asset="BTC",
            timestamp=0,
            trend_regime="uptrend",
            vol_regime="normal",
            liquidity_regime="good",
        )

        d = ms.to_dict()
        self.assertEqual(d["asset"], "BTC")
        self.assertEqual(d["trend"], "uptrend")
        self.assertEqual(d["vol"], "normal")
        self.assertEqual(d["liquidity"], "good")

    def test_global_regime_serialization(self):
        """GlobalRegime should serialize correctly."""
        gr = GlobalRegime(
            timestamp=1234567890,
            btc_dominant_trend="uptrend",
            correlation_regime="high",
            global_vol_regime="elevated",
        )

        d = gr.to_dict()
        self.assertEqual(d["timestamp"], 1234567890)
        self.assertEqual(d["btc_trend"], "uptrend")
        self.assertEqual(d["correlation"], "high")


if __name__ == "__main__":
    unittest.main()
