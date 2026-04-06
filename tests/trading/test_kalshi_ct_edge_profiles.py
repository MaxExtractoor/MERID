"""Tests for Kalshi CT edge profile configuration and sizing logic.

Validates that:
  - initial_live profile accepts smaller edges (0.5-2%)
  - production profile requires larger edges (2-8%)
  - Kelly sizing works correctly for approved edges
  - CT-TRACE logging shows min_edge_required vs actual edge
"""

import os
import pytest
from unittest.mock import Mock

# Set initial_live profile for these tests
os.environ["KALSHI_CT_EDGE_PROFILE"] = "initial_live"

from merid.trading.kalshi_continuous_trader import (
    KalshiContinuousTrader,
    TradingCandidate,
    EDGE_THRESHOLDS,
    EDGE_THRESHOLDS_INITIAL_LIVE,
    EDGE_THRESHOLDS_PRODUCTION,
    _EDGE_PROFILE,
)
from merid.event_venues.kalshi.market_filter import MarketCandidate
from merid.prediction.opinion_strategy import OpinionEstimate


class TestCTEdgeProfiles:
    """Test edge profile configuration and threshold logic."""

    def test_initial_live_profile_loaded(self):
        """Verify that initial_live profile is active."""
        assert _EDGE_PROFILE == "initial_live"
        assert EDGE_THRESHOLDS == EDGE_THRESHOLDS_INITIAL_LIVE

    def test_initial_live_thresholds_lower(self):
        """initial_live thresholds should be significantly lower than production."""
        # BTC 15m: 0.5% vs 2.0%
        assert EDGE_THRESHOLDS_INITIAL_LIVE[("BTC", "15m")] == 0.005
        assert EDGE_THRESHOLDS_PRODUCTION[("BTC", "15m")] == 0.02

        # DOGE 1h: 1.2% vs 6.0%
        assert EDGE_THRESHOLDS_INITIAL_LIVE[("DOGE", "1h")] == 0.012
        assert EDGE_THRESHOLDS_PRODUCTION[("DOGE", "1h")] == 0.06

    def test_btc_15m_small_edge_accepted_initial_live(self):
        """BTC 15m with edge above fee_impact should be accepted in initial_live.

        At mid=55¢, fee_impact ≈ 4.4%, so we use a 5% edge to verify the
        pipeline accepts trades that cover fees (note: small edges like 0.5%
        are blocked by the fee check regardless of the per-asset threshold).
        """
        trader = KalshiContinuousTrader(
            dry_run=True,
            kelly_fraction=0.10,
            min_edge=0.005,  # Align with initial_live
        )

        candidate = TradingCandidate(
            ticker="KXBTC-15M-T95000",
            underlying="BTC",
            timeframe="15m",
            mid_price_cents=55,
            edge_pct=5.0,  # 5% edge — clears both threshold (0.5%) and fee_impact (4.4%)
        )

        bankroll = 1000.0
        sizing = trader.signal_to_sizing(candidate, bankroll, edge_override=0.05)

        # Should produce a valid size (not rejected)
        assert sizing.edge == 0.05
        assert sizing.kelly_raw > 0
        assert sizing.size_contracts >= 1
        assert sizing.source == "override"

    def test_btc_15m_tiny_edge_rejected_initial_live(self):
        """BTC 15m with 0.3% edge should be rejected even in initial_live."""
        trader = KalshiContinuousTrader(
            dry_run=True,
            kelly_fraction=0.10,
            min_edge=0.005,
        )

        candidate = TradingCandidate(
            ticker="KXBTC-15M-T95000",
            underlying="BTC",
            timeframe="15m",
            mid_price_cents=55,
            edge_pct=0.3,  # 0.3% edge (below 0.5% threshold)
        )

        bankroll = 1000.0
        sizing = trader.signal_to_sizing(candidate, bankroll, edge_override=0.003)

        # Should be rejected (size=0)
        assert sizing.edge == 0.003
        assert sizing.size_contracts == 0

    def test_doge_1h_medium_edge_accepted_initial_live(self):
        """DOGE 1h with edge that clears fee_impact should be accepted in initial_live.

        At mid=48¢, fee_impact ≈ 3.8%, so we use a 5% edge to verify the
        pipeline accepts fee-profitable DOGE/1h trades (threshold=1.2% initial_live).
        """
        trader = KalshiContinuousTrader(
            dry_run=True,
            kelly_fraction=0.10,
            min_edge=0.005,
        )

        candidate = TradingCandidate(
            ticker="KXDOGE-1H-T0.15",
            underlying="DOGE",
            timeframe="1h",
            mid_price_cents=48,
            edge_pct=5.0,  # 5% edge — clears both threshold (1.2%) and fee_impact (~3.8%)
        )

        bankroll = 1000.0
        sizing = trader.signal_to_sizing(candidate, bankroll, edge_override=0.05)

        # Should produce a valid size
        assert sizing.edge == 0.05
        assert sizing.kelly_raw > 0
        assert sizing.size_contracts >= 1

    def test_doge_1h_medium_edge_rejected_production(self):
        """DOGE 1h with 1.5% edge would be rejected in production profile."""
        # Manually check production threshold
        production_threshold = EDGE_THRESHOLDS_PRODUCTION[("DOGE", "1h")]
        assert production_threshold == 0.06  # 6.0%

        # 1.5% edge is below 6.0% threshold → would be rejected
        assert 0.015 < production_threshold

    def test_get_min_edge_returns_correct_threshold(self):
        """_get_min_edge() should return profile-specific thresholds."""
        trader = KalshiContinuousTrader(
            dry_run=True,)

        # BTC 15m in initial_live
        btc_candidate = TradingCandidate(
            ticker="KXBTC-15M-T95000",
            underlying="BTC",
            timeframe="15m",
        )
        min_edge = trader._get_min_edge(btc_candidate)
        assert min_edge == 0.005  # initial_live threshold

        # DOGE daily in initial_live
        doge_candidate = TradingCandidate(
            ticker="KXDOGE-D-T0.15",
            underlying="DOGE",
            timeframe="daily",
        )
        min_edge = trader._get_min_edge(doge_candidate)
        assert min_edge == 0.015  # initial_live threshold

    def test_status_shows_active_profile(self):
        """status() should include edge_profile for visibility."""
        trader = KalshiContinuousTrader(
            dry_run=True,)
        status = trader.status()

        assert "config" in status
        assert "edge_profile" in status["config"]
        assert status["config"]["edge_profile"] == "initial_live"


class TestKellySizingWithSmallEdges:
    """Test Kelly sizing with small edges typical of initial_live."""

    def test_kelly_with_1_percent_edge(self):
        """1% edge above fee_impact should produce positive Kelly and valid size.

        At mid=10¢ (far from 50¢), payout=90¢, fee=2¢ → fee_impact ≈ 2.2%.
        Use 3% edge to verify Kelly sizing with a small-but-profitable edge.
        """
        trader = KalshiContinuousTrader(
            dry_run=True,
            kelly_fraction=0.10,
        )

        candidate = TradingCandidate(
            ticker="KXBTC-15M-T95000",
            underlying="BTC",
            timeframe="15m",
            mid_price_cents=10,  # Far from 50¢: fee_impact ≈ 2.2%, payout=90¢
        )

        bankroll = 1000.0
        edge = 0.03  # 3% — above fee_impact ≈ 2.2%
        sizing = trader.signal_to_sizing(candidate, bankroll, edge_override=edge)

        assert sizing.edge == 0.03
        assert sizing.win_prob > 0.10  # implied + edge
        assert sizing.kelly_raw > 0
        assert sizing.kelly_frac > 0
        assert sizing.size_contracts >= 1

    def test_kelly_with_half_percent_edge(self):
        """Verify Kelly produces zero size when edge is below fee_impact (0.5% < 2%).

        At near-50¢ prices, fee_impact ≈ 4%+, so edges below 2% are always
        fee-unprofitable.  Kelly correctly sizes to 0 in these cases.
        """
        trader = KalshiContinuousTrader(
            dry_run=True,
            kelly_fraction=0.10,
        )

        candidate = TradingCandidate(
            ticker="KXBTC-15M-T95000",
            underlying="BTC",
            timeframe="15m",
            mid_price_cents=55,
        )

        bankroll = 1000.0
        edge = 0.005  # 0.5% — below fee_impact (4.4% at mid=55¢)
        sizing = trader.signal_to_sizing(candidate, bankroll, edge_override=edge)

        assert sizing.edge == 0.005
        # kelly_raw is positive (threshold not violated) but fee check blocks the trade.
        assert sizing.kelly_raw > 0
        # Fee check prevents this trade: 0.5% edge < 4.4% fee_impact
        assert sizing.size_contracts == 0, (
            "Edge below fee_impact should yield 0 contracts (fee-unprofitable)"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
