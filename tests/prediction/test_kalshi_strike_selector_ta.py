"""
Kalshi Strike Selector TA Integration Tests
=============================================
Tests for TA signal integration in strike selection.
"""

import unittest
from typing import Optional

from merid.prediction.kalshi_strike_selector import (
    KalshiStrikeSelector,
    StrikeSelectionConfig,
)
from merid.signals.ta_models import (
    FusedClusterSignal,
    MarketStructure,
)
from merid.signals.regime_engine import RegimeEngine


class TestKalshiStrikeSelectorTAIntegration(unittest.TestCase):
    """Tests for TA signal context integration."""

    def setUp(self):
        self.config = StrikeSelectionConfig(
            max_spot_to_strike_pct=3.0,
        )
        self.selector = KalshiStrikeSelector(self.config)
        self.regime_engine = RegimeEngine()

    def _make_fused_signal(
        self,
        direction: str,
        quality: float = 0.7,
        confidence: float = 0.7,
        is_tradeable: bool = True,
        rejection_reason: Optional[str] = None,
        is_contra_trend: bool = False,
    ) -> FusedClusterSignal:
        """Create a test FusedClusterSignal."""
        return FusedClusterSignal(
            asset="BTC",
            primary_tf="15m",
            timestamp=0,
            direction=direction,
            confidence=confidence,
            quality_score=quality,
            higher_tf_alignment=0.8,
            lower_tf_confirmation=0.8,
            multi_tf_agreement=True,
            is_contra_trend=is_contra_trend,
            size_multiplier=1.0,
            rejection_reason=rejection_reason,
            rationale_tags=["test"],
        )


if __name__ == "__main__":
    unittest.main()
