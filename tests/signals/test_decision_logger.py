"""
Decision Logger Tests
=====================
Tests for structured trade decision logging.
"""

import unittest
import time
from typing import Dict, Any, List

from merid.signals.ta_models import (
    FusedClusterSignal,
    MarketStructure,
)
from merid.signals.decision_logger import (
    DecisionLogger,
    TradeDecisionLog,
    get_decision_logger,
)


class TestDecisionLogger(unittest.TestCase):
    """Tests for DecisionLogger functionality."""

    def setUp(self):
        self.logger = DecisionLogger()
        self.logger._buffer.clear()

    def test_singleton_pattern(self):
        """Singleton should return same instance."""
        logger1 = get_decision_logger()
        logger2 = get_decision_logger()
        self.assertIs(logger1, logger2)

    def _make_decision(self, decision_id: str, asset: str = "BTC", rejection: str = None) -> TradeDecisionLog:
        """Create a TradeDecisionLog with required fields."""
        return TradeDecisionLog(
            decision_id=decision_id,
            timestamp=time.time(),
            asset=asset,
            timeframe="15m",
            spot=100.0,
            trend_regime="uptrend",
            vol_regime="normal",
            liquidity_regime="good",
            cluster_direction="long",
            cluster_quality=0.75,
            cluster_confidence=0.8,
            rationale_tags=["test"],
            higher_tf_alignment=0.9,
            lower_tf_confirmation=0.8,
            selected_ticker=f"KX{asset}-15M-102C" if not rejection else None,
            strike=102.0 if not rejection else None,
            distance_pct=0.02 if not rejection else None,
            base_max_distance_pct=0.03,
            dynamic_max_distance_pct=0.04,
            rejection_reason=rejection,
            base_size=10,
            adjusted_size=12,
            size_multiplier=1.2,
            risk_usd=100.0,
            signal_valid=not rejection,
            regime_valid=True,
            distance_valid=not rejection,
            risk_gate_passed=True,
        )

    def test_log_decision_basic(self):
        """Basic decision logging should work."""
        decision = self._make_decision("test-001")

        self.logger.log_decision(decision)

        self.assertEqual(len(self.logger._buffer), 1)
        self.assertEqual(self.logger._buffer[0].decision_id, "test-001")

    def test_log_rejected_trade(self):
        """Rejected trades should be logged with reason."""
        decision = self._make_decision("test-002", rejection="INSUFFICIENT_CONFIDENCE")

        self.logger.log_decision(decision)

        recent = self.logger.get_recent_decisions(n=10)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["kalshi_selection"]["rejection"], "INSUFFICIENT_CONFIDENCE")

    def test_get_recent_decisions_limit(self):
        """get_recent_decisions should respect limit."""
        # Add 20 decisions
        for i in range(20):
            decision = self._make_decision(f"test-{i:03d}")
            decision.timestamp = time.time() - i  # Make older as i increases
            self.logger.log_decision(decision)

        # Get only 5
        recent = self.logger.get_recent_decisions(n=5)
        self.assertEqual(len(recent), 5)

    def test_get_stats_basic(self):
        """Stats calculation should work."""
        # Add mix of trades
        for i in range(3):
            decision = self._make_decision(f"accepted-{i}")
            self.logger.log_decision(decision)

        for i in range(2):
            decision = self._make_decision(f"rejected-{i}", rejection="INSUFFICIENT_CONFIDENCE")
            self.logger.log_decision(decision)

        stats = self.logger.get_stats(window=100)

        self.assertEqual(stats["total"], 5)
        self.assertEqual(stats["accepted"], 3)
        self.assertEqual(stats["rejected"], 2)
        self.assertIn("BTC", stats["by_asset"])

    def test_ring_buffer_limit(self):
        """Ring buffer should enforce max size."""
        # Add 20 decisions
        for i in range(20):
            decision = self._make_decision(f"test-{i:03d}")
            self.logger.log_decision(decision)

        self.assertEqual(len(self.logger._buffer), 20)

    def test_multiple_assets_tracking(self):
        """Stats should track multiple assets."""
        assets = ["BTC", "ETH", "SOL"]
        for asset in assets:
            for i in range(3):
                decision = self._make_decision(f"{asset}-{i}", asset=asset)
                self.logger.log_decision(decision)

        stats = self.logger.get_stats(window=100)

        self.assertEqual(len(stats["by_asset"]), 3)
        for asset in assets:
            self.assertIn(asset, stats["by_asset"])

    def test_create_from_fused_signal(self):
        """Helper should create log from fused signal correctly."""
        fused = FusedClusterSignal(
            asset="BTC",
            primary_tf="15m",
            timestamp=int(time.time()),
            direction="long",
            confidence=0.8,
            quality_score=0.75,
            higher_tf_alignment=0.9,
            lower_tf_confirmation=0.8,
            multi_tf_agreement=True,
            size_multiplier=1.2,
            rationale_tags=["test"],
        )
        market = MarketStructure(
            asset="BTC",
            timestamp=time.time(),
            trend_regime="uptrend",
            vol_regime="normal",
            liquidity_regime="good",
        )

        log = self.logger.create_from_fused_signal(
            asset="BTC",
            timeframe="15m",
            spot=100.0,
            fused_signal=fused,
            market_structure=market,
            ticker="KXBTC-15M-102C",
            strike=102.0,
            base_max_distance=0.03,
            dynamic_max_distance=0.04,
            rejection=None,
            base_size=10,
            risk_usd=100.0,
        )

        self.assertEqual(log.asset, "BTC")
        self.assertEqual(log.cluster_direction, "long")
        self.assertEqual(log.cluster_quality, 0.75)
        self.assertEqual(log.selected_ticker, "KXBTC-15M-102C")


if __name__ == "__main__":
    unittest.main()
