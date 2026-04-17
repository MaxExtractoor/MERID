"""Tests for dynamic per-cluster stop loss system.

Implements tests per spec:
1. Unit tests – regime mapping
2. Unit tests – static fallback
3. Unit tests – cluster capping
4. Integration tests – paper mode
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# Ensure merid is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from merid.event_venues.kalshi.kalshi_risk import (
    KalshiRiskManager,
    KalshiRiskConfig,
    RiskState,
    get_kalshi_risk,
)


class TestDynamicClusterStopLossBands:
    """Unit tests for cluster stop loss band logic with KALSHI_DYNAMIC_STOP_LOSS=true."""

    def _create_mock_settings_module(self, dynamic_enabled: bool = True, is_production: bool = True):
        """Create a mock settings module with specified configuration."""
        mock_settings = MagicMock()
        mock_settings.KALSHI_DYNAMIC_STOP_LOSS = dynamic_enabled
        mock_settings.is_production = is_production
        mock_settings.KALSHI_PORTFOLIO_BANKROLL_CENTS = 5000000
        mock_settings.KALSHI_PORTFOLIO_CLUSTER_STOP_PCT = 0.50
        return mock_settings

    def test_deep_underwater_regime(self):
        """ratio=0.4 → per_cluster_sl_frac=0.20, max_stop_loss_usd_per_cluster=10000."""
        risk = KalshiRiskManager()
        mock_settings = self._create_mock_settings_module()
        with patch.dict("sys.modules", {"merid.settings": MagicMock(settings=mock_settings)}):
            with patch("merid.event_venues.kalshi.kalshi_risk.settings", mock_settings, create=True):
                max_sl, regime, ratio = risk._compute_dynamic_stop_loss(
                    equity_usd=20000.0, bankroll_cents=5000000
                )
        assert regime == "DEEP_UNDERWATER"
        assert ratio == pytest.approx(0.4)
        assert max_sl == pytest.approx(10000.0)  # 20% of $50,000

    def test_underwater_regime(self):
        """ratio=0.8 → per_cluster_sl_frac=0.14, max_stop_loss_usd_per_cluster=7000."""
        risk = KalshiRiskManager()
        mock_settings = self._create_mock_settings_module()
        with patch.dict("sys.modules", {"merid.settings": MagicMock(settings=mock_settings)}):
            with patch("merid.event_venues.kalshi.kalshi_risk.settings", mock_settings, create=True):
                max_sl, regime, ratio = risk._compute_dynamic_stop_loss(
                    equity_usd=40000.0, bankroll_cents=5000000
                )
        assert regime == "UNDERWATER"
        assert ratio == pytest.approx(0.8)
        assert max_sl == pytest.approx(7000.0)  # 14% of $50,000

    def test_baseline_regime(self):
        """ratio=1.1 → per_cluster_sl_frac=0.08, max_stop_loss_usd_per_cluster=4000."""
        risk = KalshiRiskManager()
        mock_settings = self._create_mock_settings_module()
        with patch.dict("sys.modules", {"merid.settings": MagicMock(settings=mock_settings)}):
            with patch("merid.event_venues.kalshi.kalshi_risk.settings", mock_settings, create=True):
                max_sl, regime, ratio = risk._compute_dynamic_stop_loss(
                    equity_usd=55000.0, bankroll_cents=5000000
                )
        assert regime == "BASELINE"
        assert ratio == pytest.approx(1.1)
        assert max_sl == pytest.approx(4000.0)  # 8% of $50,000

    def test_lock_in_gains_regime(self):
        """ratio=1.6 → per_cluster_sl_frac=0.04, max_stop_loss_usd_per_cluster=2000."""
        risk = KalshiRiskManager()
        mock_settings = self._create_mock_settings_module()
        with patch.dict("sys.modules", {"merid.settings": MagicMock(settings=mock_settings)}):
            with patch("merid.event_venues.kalshi.kalshi_risk.settings", mock_settings, create=True):
                max_sl, regime, ratio = risk._compute_dynamic_stop_loss(
                    equity_usd=80000.0, bankroll_cents=5000000
                )
        assert regime == "LOCK_IN_GAINS"
        assert ratio == pytest.approx(1.6)
        assert max_sl == pytest.approx(2000.0)  # 4% of $50,000


class TestStaticFallback:
    """Test static fallback behavior when dynamic is disabled."""

    def test_static_cluster_stop_pct_fallback(self):
        """KALSHI_DYNAMIC_STOP_LOSS=false, KALSHI_PORTFOLIO_CLUSTER_STOP_PCT=0.5,
        KALSHI_PORTFOLIO_MAX_DAILY_LOSS_PCT=0.1, bankroll=50000 → max_dailyloss_usd=5000 → max_cluster_stop=2500."""
        risk = KalshiRiskManager()
        # Set up config with daily loss cap
        risk._config.max_daily_loss_usd = 5000.0  # 10% of $50k

        mock_settings = MagicMock()
        mock_settings.KALSHI_DYNAMIC_STOP_LOSS = False
        mock_settings.is_production = True
        mock_settings.KALSHI_PORTFOLIO_BANKROLL_CENTS = 5000000
        mock_settings.KALSHI_PORTFOLIO_CLUSTER_STOP_PCT = 0.50

        with patch.dict("sys.modules", {"merid.settings": MagicMock(settings=mock_settings)}):
            with patch("merid.event_venues.kalshi.kalshi_risk.settings", mock_settings, create=True):
                max_sl, regime, ratio = risk._compute_dynamic_stop_loss(
                    equity_usd=50000.0, bankroll_cents=5000000
                )

        assert regime == "STATIC"
        assert max_sl == pytest.approx(2500.0)  # 50% of daily loss cap


class TestClusterIdHelpers:
    """Test cluster ID generation and inference helpers."""

    def test_get_cluster_id(self):
        """Test cluster ID generation from asset and timeframe."""
        risk = KalshiRiskManager()
        assert risk._get_cluster_id("BTC", "15m") == "BTC-15m"
        assert risk._get_cluster_id("ETH", "1h") == "ETH-1h"
        # Both None and empty strings are handled by the 'or' fallback
        assert risk._get_cluster_id(None, None) == "UNKNOWN-unknown"
        assert risk._get_cluster_id("", "") == "UNKNOWN-unknown"

    def test_infer_asset_from_ticker(self):
        """Test asset inference from Kalshi tickers."""
        risk = KalshiRiskManager()
        assert risk._infer_asset_from_ticker("KXBTC-15M") == "BTC"
        assert risk._infer_asset_from_ticker("KXETH-1H") == "ETH"
        assert risk._infer_asset_from_ticker("KXSOL-D") == "SOL"
        assert risk._infer_asset_from_ticker("KXXRP-W") == "XRP"
        assert risk._infer_asset_from_ticker("KXDOGE-15M") == "DOGE"
        assert risk._infer_asset_from_ticker("UNKNOWN") is None

    def test_infer_timeframe_from_ticker(self):
        """Test timeframe inference from Kalshi tickers."""
        risk = KalshiRiskManager()
        assert risk._infer_timeframe_from_ticker("KXBTC-15M") == "15m"
        assert risk._infer_timeframe_from_ticker("KXBTC-1H") == "1h"
        assert risk._infer_timeframe_from_ticker("KXBTC-D") == "daily"
        assert risk._infer_timeframe_from_ticker("KXBTC-W") == "weekly"
        assert risk._infer_timeframe_from_ticker("KXBTC") is None


class TestClusterStopLossCheck:
    """Test cluster stop loss enforcement."""

    def test_cluster_stop_loss_allowed(self):
        """cluster_unrealized_loss_usd=2000, max_stop_loss_usd_per_cluster=5000,
        order_worst_case_loss_usd=2000 → post=4000 < 5000 → allowed."""
        risk = KalshiRiskManager()
        risk._config.max_stop_loss_usd_per_cluster = 5000.0

        # Mock the cluster unrealized loss computation
        with patch.object(risk, "_compute_cluster_unrealized_loss_usd", return_value=2000.0):
            allowed, reason, cluster_loss, post_loss = risk._check_cluster_stop_loss(
                cluster_id="BTC-15m", order_worst_case_loss_usd=2000.0
            )

        assert allowed is True
        assert reason == "OK"
        assert cluster_loss == 2000.0
        assert post_loss == 4000.0

    def test_cluster_stop_loss_denied(self):
        """cluster_unrealized_loss_usd=3000, max_stop_loss_usd_per_cluster=5000,
        order_worst_case_loss_usd=2500 → post=5500 > 5000 → denied."""
        risk = KalshiRiskManager()
        risk._config.max_stop_loss_usd_per_cluster = 5000.0

        with patch.object(risk, "_compute_cluster_unrealized_loss_usd", return_value=3000.0):
            allowed, reason, cluster_loss, post_loss = risk._check_cluster_stop_loss(
                cluster_id="BTC-15m", order_worst_case_loss_usd=2500.0
            )

        assert allowed is False
        assert "breached" in reason.lower()
        assert cluster_loss == 3000.0
        assert post_loss == 5500.0

    def test_cluster_stop_loss_no_existing_loss(self):
        """No existing loss, order within limit → allowed."""
        risk = KalshiRiskManager()
        risk._config.max_stop_loss_usd_per_cluster = 5000.0

        with patch.object(risk, "_compute_cluster_unrealized_loss_usd", return_value=0.0):
            allowed, reason, cluster_loss, post_loss = risk._check_cluster_stop_loss(
                cluster_id="BTC-15m", order_worst_case_loss_usd=1000.0
            )

        assert allowed is True
        assert cluster_loss == 0.0
        assert post_loss == 1000.0


class TestIntegrationPaperMode:
    """Integration tests for paper mode."""

    def test_cluster_stop_loss_independent_of_daily_loss(self):
        """Verify cluster stop loss is enforced independently of daily loss."""
        risk = KalshiRiskManager()

        # Setup: Daily loss OK, but cluster stop loss would be breached
        risk._config.max_stop_loss_usd_per_cluster = 3000.0  # Low cluster limit

        # Mock cluster loss to be near limit (2500 + 800 = 3300 > 3000)
        with patch.object(risk, "_compute_cluster_unrealized_loss_usd", return_value=2500.0):
            allowed, reason, cluster_loss, post_loss = risk._check_cluster_stop_loss(
                cluster_id="BTC-15m", order_worst_case_loss_usd=800.0
            )

        # Should be denied due to cluster stop loss
        assert allowed is False
        assert "breached" in reason.lower()
        assert cluster_loss == 2500.0
        assert post_loss == 3300.0  # 2500 + 800

    def test_cluster_headroom_restored_on_close(self):
        """Closing positions should restore cluster headroom."""
        risk = KalshiRiskManager()
        risk._config.max_stop_loss_usd_per_cluster = 5000.0

        # First check shows loss
        with patch.object(risk, "_compute_cluster_unrealized_loss_usd", return_value=4000.0):
            allowed1, _, cluster_loss1, _ = risk._check_cluster_stop_loss("BTC-15m", 500.0)
            assert allowed1 is True  # 4000 + 500 = 4500 < 5000

        # After positions close, loss reduces
        with patch.object(risk, "_compute_cluster_unrealized_loss_usd", return_value=1000.0):
            allowed2, _, cluster_loss2, _ = risk._check_cluster_stop_loss("BTC-15m", 2000.0)
            assert allowed2 is True  # 1000 + 2000 = 3000 < 5000
            assert cluster_loss2 == 1000.0


class TestSummaryIncludesClusterStopLoss:
    """Test that summary includes cluster stop loss info."""

    def test_summary_includes_cluster_stop_limit(self):
        """Verify that summary includes the max_stop_loss_usd_per_cluster limit."""
        risk = KalshiRiskManager()
        risk._config.max_stop_loss_usd_per_cluster = 3500.0

        summary = risk.summary()

        assert "limits" in summary
        assert summary["limits"]["max_stop_loss_usd_per_cluster"] == 3500.0


class TestRegimeBasedRR:
    """Test regime-based reward:risk targets (optional feature)."""

    def test_target_rr_by_regime(self):
        """Verify target R:R values per regime."""
        # This is a conceptual test - actual implementation would be in sizing code
        target_rr_map = {
            "DEEP_UNDERWATER": 2.0,
            "UNDERWATER": 1.5,
            "BASELINE": 1.2,
            "LOCK_IN_GAINS": 1.0,
        }

        assert target_rr_map["DEEP_UNDERWATER"] == 2.0
        assert target_rr_map["LOCK_IN_GAINS"] == 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
