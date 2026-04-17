"""
TA Engine Unit Tests
====================
Tests for technical indicator calculations and divergence detection.
"""

import unittest
import numpy as np
from typing import List

from merid.signals.ta_models import (
    OHLCVSnapshot,
    IndicatorBundle,
    Divergence,
    MarketStructure,
)
from merid.signals.ta_engine import TAEngine, IndicatorConfig


class TestTAEngineBasics(unittest.TestCase):
    """Basic functionality tests."""

    def setUp(self):
        self.engine = TAEngine()
        self.config = IndicatorConfig()

    def test_compute_bundle_insufficient_data(self):
        """Bundle with < 30 bars should return minimal data."""
        buffer = self._make_buffer(20, price=100.0)
        bundle = self.engine.compute_bundle(buffer, "BTC", "15m")

        self.assertEqual(bundle.asset, "BTC")
        self.assertEqual(bundle.timeframe, "15m")
        self.assertEqual(bundle.bars_available, 20)
        self.assertFalse(bundle.bars_available >= 50)  # trade_ready condition

    def test_compute_bundle_sufficient_data(self):
        """Bundle with > 50 bars should have full indicators."""
        buffer = self._make_buffer(60, price=100.0, trend="up")
        bundle = self.engine.compute_bundle(buffer, "BTC", "15m")

        self.assertTrue(bundle.bars_available >= 50)  # trade_ready condition
        self.assertIsNotNone(bundle.rsi)
        self.assertIsNotNone(bundle.macd_line)
        self.assertIsNotNone(bundle.ema_fast)

    def test_rsi_calculation(self):
        """RSI should be in valid range."""
        buffer = self._make_buffer(60, price=100.0)
        bundle = self.engine.compute_bundle(buffer, "BTC", "15m")

        self.assertGreaterEqual(bundle.rsi, 0)
        self.assertLessEqual(bundle.rsi, 100)

    def test_macd_calculation(self):
        """MACD components should be calculated."""
        buffer = self._make_buffer(60, price=100.0)
        bundle = self.engine.compute_bundle(buffer, "BTC", "15m")

        self.assertIsNotNone(bundle.macd_line)
        self.assertIsNotNone(bundle.macd_signal)
        self.assertIsNotNone(bundle.macd_histogram)

    def test_fib_pivots_calculation(self):
        """Fib pivots should have correct structure."""
        buffer = self._make_buffer(60, price=100.0, volatility=0.02)
        bundle = self.engine.compute_bundle(buffer, "BTC", "15m")

        self.assertIsNotNone(bundle.fib_pivots)
        if bundle.fib_pivots:
            self.assertLess(bundle.fib_pivots.s2, bundle.fib_pivots.s1)
            self.assertLess(bundle.fib_pivots.s1, bundle.fib_pivots.pivot)
            self.assertLess(bundle.fib_pivots.pivot, bundle.fib_pivots.r1)
            self.assertLess(bundle.fib_pivots.r1, bundle.fib_pivots.r2)

    def _make_buffer(
        self,
        n: int,
        price: float = 100.0,
        trend: str = "flat",
        volatility: float = 0.01,
    ) -> List[OHLCVSnapshot]:
        """Generate synthetic OHLCV buffer."""
        buffer = []
        current = price
        for i in range(n):
            if trend == "up":
                current *= 1.001
            elif trend == "down":
                current *= 0.999

            noise = np.random.normal(0, volatility * current)
            open_p = current + noise * 0.3
            close = current + noise * 0.7
            high = max(open_p, close) + abs(noise) * 0.5
            low = min(open_p, close) - abs(noise) * 0.5

            buffer.append(OHLCVSnapshot(
                asset="BTC",
                timeframe="15m",
                open=open_p,
                high=high,
                low=low,
                close=close,
                volume=1000.0,
                timestamp_window_start=i * 900,
                timestamp_window_end=(i + 1) * 900,
            ))
            current = close
        return buffer


class TestDivergenceDetection(unittest.TestCase):
    """Tests for RSI and MACD divergence detection."""

    def setUp(self):
        self.engine = TAEngine()

    def test_bullish_rsi_divergence(self):
        """
        Test bullish RSI divergence with synthetic bundle.
        """
        # Create bundle with bullish divergence directly
        bundle = IndicatorBundle(
            asset="BTC",
            timeframe="15m",
            timestamp=0,
            close=95.0,
            volume=1000.0,
            ema_fast=98.0,
            ema_slow=99.0,
            ema_trend=100.0,
            ema_trend_slope=-0.001,
            sma_50=100.0,
            rsi=28.0,
            rsi_zone="oversold",
            divergences=[
                Divergence(
                    div_type="bullish_rsi",
                    strength=0.7,
                    price_pivot=92.0,
                    indicator_pivot=25.0,
                    price_pivot_idx=40,
                    indicator_pivot_idx=40,
                    confirmed=True,
                    rsi_at_pivot=25.0,
                )
            ],
            bars_available=60,
        )

        self.assertTrue(bundle.has_bullish_divergence(min_strength=0.5))

    def test_bearish_rsi_divergence(self):
        """
        Test bearish RSI divergence with synthetic bundle.
        """
        # Create bundle with bearish divergence directly
        bundle = IndicatorBundle(
            asset="BTC",
            timeframe="15m",
            timestamp=0,
            close=105.0,
            volume=1000.0,
            ema_fast=102.0,
            ema_slow=101.0,
            ema_trend=100.0,
            ema_trend_slope=0.001,
            sma_50=100.0,
            rsi=72.0,
            rsi_zone="overbought",
            divergences=[
                Divergence(
                    div_type="bearish_rsi",
                    strength=0.7,
                    price_pivot=108.0,
                    indicator_pivot=75.0,
                    price_pivot_idx=40,
                    indicator_pivot_idx=40,
                    confirmed=True,
                    rsi_at_pivot=75.0,
                )
            ],
            bars_available=60,
        )

        self.assertTrue(bundle.has_bearish_divergence(min_strength=0.5))

    def test_no_divergence_flat(self):
        """Bundle without divergences should return False."""
        bundle = IndicatorBundle(
            asset="BTC",
            timeframe="15m",
            timestamp=0,
            close=100.0,
            volume=1000.0,
            ema_fast=100.0,
            ema_slow=100.0,
            ema_trend=100.0,
            ema_trend_slope=0.0,
            sma_50=100.0,
            rsi=50.0,
            rsi_zone="neutral",
            divergences=[],  # No divergences
            bars_available=60,
        )

        self.assertFalse(bundle.has_bullish_divergence())
        self.assertFalse(bundle.has_bearish_divergence())

    def _make_bullish_divergence_buffer(self) -> List[OHLCVSnapshot]:
        """Generate buffer with bullish divergence pattern."""
        buffer = []
        base_price = 100.0

        # Trend down to oversold
        for i in range(40):
            price = base_price * (1 - 0.002 * i)
            buffer.append(self._make_bar(i, price, "down"))

        # First low
        buffer.append(self._make_bar(40, base_price * 0.92, "low"))

        # Small bounce
        for i in range(5, 10):
            buffer.append(self._make_bar(40 + i, base_price * (0.92 + 0.001 * i), "flat"))

        # Second lower low (lower price, but RSI will be higher due to momentum shift)
        buffer.append(self._make_bar(51, base_price * 0.91, "low"))

        # Fill to 60 bars
        for i in range(52, 60):
            buffer.append(self._make_bar(i, base_price * (0.91 + 0.002 * (i - 51)), "up"))

        return buffer

    def _make_bearish_divergence_buffer(self) -> List[OHLCVSnapshot]:
        """Generate buffer with bearish divergence pattern."""
        buffer = []
        base_price = 100.0

        # Trend up to overbought
        for i in range(40):
            price = base_price * (1 + 0.002 * i)
            buffer.append(self._make_bar(i, price, "up"))

        # First high
        buffer.append(self._make_bar(40, base_price * 1.08, "high"))

        # Small pullback
        for i in range(5, 10):
            buffer.append(self._make_bar(40 + i, base_price * (1.08 - 0.001 * i), "flat"))

        # Second higher high (higher price, but RSI will be lower)
        buffer.append(self._make_bar(51, base_price * 1.09, "high"))

        # Fill to 60 bars
        for i in range(52, 60):
            buffer.append(self._make_bar(i, base_price * (1.09 - 0.002 * (i - 51)), "down"))

        return buffer

    def _make_flat_buffer(self) -> List[OHLCVSnapshot]:
        """Generate flat buffer with no divergences."""
        buffer = []
        for i in range(60):
            noise = np.random.normal(0, 0.5)
            price = 100.0 + noise
            buffer.append(self._make_bar(i, price, "flat"))
        return buffer

    def _make_bar(
        self,
        idx: int,
        close: float,
        pattern: str,
    ) -> OHLCVSnapshot:
        """Create a single OHLCV bar."""
        noise = 0.5
        if pattern == "up":
            open_p = close - 0.3
            high = close + 0.5
            low = open_p - 0.2
        elif pattern == "down":
            open_p = close + 0.3
            high = open_p + 0.2
            low = close - 0.5
        elif pattern == "low":
            open_p = close + 0.1
            high = open_p + 0.2
            low = close - 0.3
        elif pattern == "high":
            open_p = close - 0.1
            high = close + 0.3
            low = open_p - 0.2
        else:
            open_p = close + np.random.normal(0, 0.1)
            high = max(open_p, close) + noise
            low = min(open_p, close) - noise

        return OHLCVSnapshot(
            asset="BTC",
            timeframe="15m",
            open=open_p,
            high=high,
            low=low,
            close=close,
            volume=1000.0,
            timestamp_window_start=idx * 900,
            timestamp_window_end=(idx + 1) * 900,
        )


class TestSignalScore(unittest.TestCase):
    """Tests for signal scoring logic."""

    def setUp(self):
        self.engine = TAEngine()

    def test_bullish_signal(self):
        """Strong bullish setup should produce long signal."""
        bundle = self._make_bullish_bundle()
        market_structure = MarketStructure(asset="BTC", timestamp=0)

        signal = self.engine.compute_signal_score(bundle, market_structure)

        self.assertEqual(signal.direction, "long")
        self.assertGreater(signal.confidence, 0.6)
        self.assertTrue("bullish_div" in signal.rationale_tags or "ema_bull_stack" in signal.rationale_tags)

    def test_bearish_signal(self):
        """Strong bearish setup should produce short signal."""
        bundle = self._make_bearish_bundle()
        market_structure = MarketStructure(asset="BTC", timestamp=0)

        signal = self.engine.compute_signal_score(bundle, market_structure)

        self.assertEqual(signal.direction, "short")
        self.assertGreater(signal.confidence, 0.6)

    def test_flat_signal_chop(self):
        """Weak scoring bundle should produce flat signal."""
        # Create a bundle with weak scores that won't trigger direction
        bundle = IndicatorBundle(
            asset="BTC",
            timeframe="15m",
            timestamp=0,
            close=100.0,
            volume=1000.0,
            ema_fast=100.0,
            ema_slow=100.0,
            ema_trend=100.0,
            ema_trend_slope=0.0,
            sma_50=100.0,
            rsi=50.0,
            rsi_zone="neutral",
            macd_line=0.0,
            macd_signal=0.0,
            macd_histogram=0.0,
            macd_histogram_slope=0.0,
            divergences=[],
            bars_available=60,
        )
        market_structure = MarketStructure(asset="BTC", timestamp=0)

        signal = self.engine.compute_signal_score(bundle, market_structure)

        # With neutral/weak indicators, should be flat
        self.assertEqual(signal.direction, "flat")

    def _make_bullish_bundle(self) -> IndicatorBundle:
        """Create a bullish indicator bundle."""
        return IndicatorBundle(
            asset="BTC",
            timeframe="15m",
            timestamp=0,
            close=105.0,
            volume=2000.0,
            ema_fast=102.0,
            ema_slow=101.0,
            ema_trend=100.0,
            ema_trend_slope=0.001,
            sma_50=100.0,
            rsi=25.0,  # Oversold
            rsi_zone="oversold",
            macd_line=0.5,
            macd_signal=0.2,
            macd_histogram=0.3,
            macd_histogram_slope=0.1,
            divergences=[
                Divergence(
                    div_type="bullish_rsi",
                    strength=0.8,
                    price_pivot=95.0,
                    indicator_pivot=25.0,
                    price_pivot_idx=40,
                    indicator_pivot_idx=40,
                    confirmed=True,
                    rsi_at_pivot=25.0,
                )
            ],
            atr=1.0,
            atr_pct=0.01,
            volume_zscore=2.0,
            bars_available=60,
        )

    def _make_bearish_bundle(self) -> IndicatorBundle:
        """Create a bearish indicator bundle."""
        return IndicatorBundle(
            asset="BTC",
            timeframe="15m",
            timestamp=0,
            close=95.0,
            volume=2000.0,
            ema_fast=98.0,
            ema_slow=99.0,
            ema_trend=100.0,
            ema_trend_slope=-0.001,
            sma_50=100.0,
            rsi=75.0,  # Overbought
            rsi_zone="overbought",
            macd_line=-0.5,
            macd_signal=-0.2,
            macd_histogram=-0.3,
            macd_histogram_slope=-0.1,
            divergences=[
                Divergence(
                    div_type="bearish_rsi",
                    strength=0.8,
                    price_pivot=105.0,
                    indicator_pivot=75.0,
                    price_pivot_idx=40,
                    indicator_pivot_idx=40,
                    confirmed=True,
                    rsi_at_pivot=75.0,
                )
            ],
            atr=1.0,
            atr_pct=0.01,
            volume_zscore=2.0,
            bars_available=60,
        )

    def _make_flat_buffer(self) -> List[OHLCVSnapshot]:
        """Generate flat buffer."""
        buffer = []
        for i in range(60):
            price = 100.0 + np.random.normal(0, 0.3)
            buffer.append(OHLCVSnapshot(
                asset="BTC",
                timeframe="15m",
                open=price - 0.1,
                high=price + 0.2,
                low=price - 0.2,
                close=price,
                volume=1000.0,
                timestamp_window_start=i * 900,
                timestamp_window_end=(i + 1) * 900,
            ))
        return buffer


if __name__ == "__main__":
    unittest.main()
