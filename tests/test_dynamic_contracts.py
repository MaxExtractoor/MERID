"""Tests for dynamic contract sizing and spot-strike distance systems.

Implements tests per spec:
1. Unit tests – regime mapping for contract caps
2. Unit tests – static fallback
3. Unit tests – spot-strike distance selector
4. Integration tests – paper mode
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
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
from merid.event_venues.kalshi.strike_selector import (
    StrikeSelector,
    DEFAULT_SPOT_STRIKE_DISTANCE_PCT,
    get_strike_selector,
    reset_strike_selector,
)


class TestDynamicContractCaps:
    """Unit tests for contract cap band logic with KALSHI_DYNAMIC_CONTRACTS=true."""

    def _create_mock_settings_module(self, dynamic_enabled: bool = True, is_production: bool = True):
        """Create a mock settings module with specified configuration."""
        mock_settings = MagicMock()
        mock_settings.KALSHI_DYNAMIC_CONTRACTS = dynamic_enabled
        mock_settings.is_production = is_production
        mock_settings.KALSHI_PORTFOLIO_BANKROLL_CENTS = 5000000
        mock_settings.KALSHI_MAX_CONTRACTS_TOTAL = 5000
        mock_settings.KALSHI_MAX_CONTRACTS_PER_ASSET_FRACTION = 0.35
        mock_settings.KALSHI_MAX_CONTRACTS_PER_CLUSTER_FRACTION = 0.15
        return mock_settings

    def test_deep_underwater_contract_caps(self):
        """ratio=0.4 (DEEP_UNDERWATER) → total_frac=0.40, asset=0.20, cluster=0.10."""
        risk = KalshiRiskManager()
        mock_settings = self._create_mock_settings_module()
        with patch.dict("sys.modules", {"merid.settings": MagicMock(settings=mock_settings)}):
            with patch("merid.event_venues.kalshi.kalshi_risk.settings", mock_settings, create=True):
                (
                    notional_total,
                    notional_asset,
                    notional_cluster,
                    contracts_total,
                    contracts_asset,
                    contracts_cluster,
                    regime,
                    ratio,
                ) = risk._compute_dynamic_contract_caps(equity_usd=20000.0, bankroll_cents=5000000)

        assert regime == "DEEP_UNDERWATER"
        assert ratio == pytest.approx(0.4)
        assert notional_total == pytest.approx(20000.0)  # 40% of $50k
        assert notional_asset == pytest.approx(10000.0)  # 20% of $50k
        assert notional_cluster == pytest.approx(5000.0)  # 10% of $50k

    def test_underwater_contract_caps(self):
        """ratio=0.8 (UNDERWATER) → total_frac=0.30, asset=0.15, cluster=0.08."""
        risk = KalshiRiskManager()
        mock_settings = self._create_mock_settings_module()
        with patch.dict("sys.modules", {"merid.settings": MagicMock(settings=mock_settings)}):
            with patch("merid.event_venues.kalshi.kalshi_risk.settings", mock_settings, create=True):
                (
                    notional_total,
                    notional_asset,
                    notional_cluster,
                    contracts_total,
                    contracts_asset,
                    contracts_cluster,
                    regime,
                    ratio,
                ) = risk._compute_dynamic_contract_caps(equity_usd=40000.0, bankroll_cents=5000000)

        assert regime == "UNDERWATER"
        assert ratio == pytest.approx(0.8)
        assert notional_total == pytest.approx(15000.0)  # 30% of $50k
        assert notional_asset == pytest.approx(7500.0)  # 15% of $50k

    def test_baseline_contract_caps(self):
        """ratio=1.1 (BASELINE) → total_frac=0.25, asset=0.12, cluster=0.06."""
        risk = KalshiRiskManager()
        mock_settings = self._create_mock_settings_module()
        with patch.dict("sys.modules", {"merid.settings": MagicMock(settings=mock_settings)}):
            with patch("merid.event_venues.kalshi.kalshi_risk.settings", mock_settings, create=True):
                (
                    notional_total,
                    notional_asset,
                    notional_cluster,
                    contracts_total,
                    contracts_asset,
                    contracts_cluster,
                    regime,
                    ratio,
                ) = risk._compute_dynamic_contract_caps(equity_usd=55000.0, bankroll_cents=5000000)

        assert regime == "BASELINE"
        assert ratio == pytest.approx(1.1)
        assert notional_total == pytest.approx(12500.0)  # 25% of $50k
        assert notional_asset == pytest.approx(6000.0)  # 12% of $50k

    def test_lock_in_gains_contract_caps(self):
        """ratio=1.6 (LOCK_IN_GAINS) → total_frac=0.20, asset=0.10, cluster=0.04."""
        risk = KalshiRiskManager()
        mock_settings = self._create_mock_settings_module()
        with patch.dict("sys.modules", {"merid.settings": MagicMock(settings=mock_settings)}):
            with patch("merid.event_venues.kalshi.kalshi_risk.settings", mock_settings, create=True):
                (
                    notional_total,
                    notional_asset,
                    notional_cluster,
                    contracts_total,
                    contracts_asset,
                    contracts_cluster,
                    regime,
                    ratio,
                ) = risk._compute_dynamic_contract_caps(equity_usd=80000.0, bankroll_cents=5000000)

        assert regime == "LOCK_IN_GAINS"
        assert ratio == pytest.approx(1.6)
        assert notional_total == pytest.approx(10000.0)  # 20% of $50k
        assert notional_asset == pytest.approx(5000.0)  # 10% of $50k


class TestStaticFallbackContracts:
    """Test static fallback behavior when dynamic contracts is disabled."""

    def test_static_contract_fallback(self):
        """KALSHI_DYNAMIC_CONTRACTS=false → use existing config values."""
        risk = KalshiRiskManager()
        risk._config.max_total_notional_usd = 25000.0

        mock_settings = MagicMock()
        mock_settings.KALSHI_DYNAMIC_CONTRACTS = False
        mock_settings.is_production = True
        mock_settings.KALSHI_PORTFOLIO_BANKROLL_CENTS = 5000000
        mock_settings.KALSHI_MAX_CONTRACTS_TOTAL = 5000
        mock_settings.KALSHI_MAX_CONTRACTS_PER_ASSET_FRACTION = 0.35
        mock_settings.KALSHI_MAX_CONTRACTS_PER_CLUSTER_FRACTION = 0.15

        with patch.dict("sys.modules", {"merid.settings": MagicMock(settings=mock_settings)}):
            with patch("merid.event_venues.kalshi.kalshi_risk.settings", mock_settings, create=True):
                (
                    notional_total,
                    notional_asset,
                    notional_cluster,
                    contracts_total,
                    contracts_asset,
                    contracts_cluster,
                    regime,
                    ratio,
                ) = risk._compute_dynamic_contract_caps(equity_usd=50000.0, bankroll_cents=5000000)

        assert regime == "STATIC"
        # In static mode, returns min(hard_cap, notional) where notional is large
        # So contracts_total is capped by the hard limit KALSHI_MAX_CONTRACTS_TOTAL = 5000
        assert contracts_total == 5000


class TestSummaryIncludesContractCaps:
    """Test that summary includes contract cap info."""

    def test_summary_includes_contract_limits(self):
        """Verify that summary includes the contract cap limits."""
        risk = KalshiRiskManager()
        risk._config.max_contracts_total = 3000
        risk._config.max_contracts_per_asset = 1050
        risk._config.max_contracts_per_cluster = 450

        summary = risk.summary()

        assert "limits" in summary
        assert summary["limits"]["max_contracts_total"] == 3000
        assert summary["limits"]["max_contracts_per_asset"] == 1050
        assert summary["limits"]["max_contracts_per_cluster"] == 450


class TestStrikeSelectorDistance:
    """Unit tests for spot-strike distance computation."""

    def test_compute_distance_pct(self):
        """Test canonical distance formula: |strike - spot| / spot."""
        selector = StrikeSelector()

        # BTC example from logs: spot 75130.45, strike 83749.99
        distance = selector.compute_distance_pct(75130.45, 83749.99)
        assert distance == pytest.approx(0.1147, abs=0.001)

        # Far strike: spot 75130.45, strike 20000.00
        distance = selector.compute_distance_pct(75130.45, 20000.00)
        assert distance == pytest.approx(0.7338, abs=0.001)

        # Same spot/strike = 0 distance
        distance = selector.compute_distance_pct(50000.0, 50000.0)
        assert distance == 0.0

    def test_get_max_allowed_pct_static(self):
        """Test static maxallowedpct from config."""
        selector = StrikeSelector()

        btc_1h = selector.get_max_allowed_pct("BTC", "1h", dynamic_enabled=False)
        assert btc_1h == 0.05  # From DEFAULT_SPOT_STRIKE_DISTANCE_PCT

        eth_15m = selector.get_max_allowed_pct("ETH", "15m", dynamic_enabled=False)
        assert eth_15m == 0.04

        doge_annual = selector.get_max_allowed_pct("DOGE", "annual", dynamic_enabled=False)
        assert doge_annual == 0.35

    def test_get_max_allowed_pct_dynamic(self):
        """Test dynamic maxallowedpct with scaling."""
        selector = StrikeSelector()

        # Base BTC 1h = 0.05
        # With vol=high(1.3), tenor=2-14d(1.0), regime=BASELINE(1.0)
        max_pct = selector.get_max_allowed_pct(
            "BTC", "1h", vol_bucket="high", tenor_bucket="2-14d",
            regime="BASELINE", dynamic_enabled=True
        )
        assert max_pct == pytest.approx(0.065)  # 0.05 * 1.3 * 1.0 * 1.0

    def test_dynamic_with_hard_cap(self):
        """Test that hard cap is applied even with aggressive dynamic scaling."""
        selector = StrikeSelector()

        # Very high multipliers should be capped by hard_cap
        max_pct = selector.get_max_allowed_pct(
            "BTC", "annual", vol_bucket="high", tenor_bucket=">14d",
            regime="BASELINE", dynamic_enabled=True
        )
        # Base 0.20 * 1.3 * 1.3 * 1.0 = 0.338, but hard cap is 0.25
        assert max_pct <= 0.25


class TestStrikeSelectorCheck:
    """Tests for strike acceptance/rejection."""

    def test_check_strike_accepted(self):
        """Strike within distance limits → accepted."""
        selector = StrikeSelector()

        result = selector.check_strike(
            spot=75000.0,
            strike=78000.0,  # ~4% away
            asset="BTC",
            timeframe="1h",
            vol_bucket="medium",
            tenor_bucket="2-14d",
            regime="BASELINE",
            dynamic_enabled=False,
        )

        assert result.accepted is True
        assert result.distance_pct == pytest.approx(0.04)
        assert result.rejection_reason is None

    def test_check_strike_rejected_distance(self):
        """Strike beyond max distance → rejected."""
        selector = StrikeSelector()

        result = selector.check_strike(
            spot=75000.0,
            strike=85000.0,  # ~13.3% away, beyond BTC 1h 5% limit
            asset="BTC",
            timeframe="1h",
            vol_bucket="medium",
            tenor_bucket="2-14d",
            regime="BASELINE",
            dynamic_enabled=False,
        )

        assert result.accepted is False
        assert result.rejection_reason == "exceeds_max_distance"

    def test_check_strike_global_guard(self):
        """Strike beyond global warn pct → rejected with out_of_range."""
        selector = StrikeSelector(global_warn_pct=0.85)

        result = selector.check_strike(
            spot=75000.0,
            strike=200000.0,  # ~167% away, beyond 0.85 global guard
            asset="BTC",
            timeframe="annual",
        )

        assert result.accepted is False
        assert result.rejection_reason == "spot_out_of_range"

    def test_check_strike_logging(self):
        """Verify check_strike logs required fields."""
        selector = StrikeSelector()

        # Should not raise and should populate all fields
        result = selector.check_strike(
            spot=75000.0,
            strike=78000.0,
            asset="BTC",
            timeframe="1h",
            vol_bucket="high",
            tenor_bucket="6h-2d",
            regime="UNDERWATER",
            dynamic_enabled=True,
        )

        assert result.base_pct == 0.05
        assert result.vol_mult == 1.3
        assert result.tenor_mult == 0.75
        assert result.regime_mult == 0.7


class TestStrikeSelectorHelpers:
    """Tests for helper methods."""

    def test_infer_timeframe_from_expiry(self):
        """Test tenor bucket inference from expiry."""
        selector = StrikeSelector()
        now = datetime.now(timezone.utc)

        assert selector.infer_timeframe_from_expiry(now + timedelta(hours=3)) == "<6h"
        assert selector.infer_timeframe_from_expiry(now + timedelta(hours=12)) == "6h-2d"
        assert selector.infer_timeframe_from_expiry(now + timedelta(days=5)) == "2-14d"
        assert selector.infer_timeframe_from_expiry(now + timedelta(days=20)) == ">14d"

    def test_infer_vol_bucket_from_regime(self):
        """Test vol bucket inference from regime string."""
        selector = StrikeSelector()

        assert selector.infer_vol_bucket_from_regime("low_vol") == "low"
        assert selector.infer_vol_bucket_from_regime("high_breakout") == "high"
        assert selector.infer_vol_bucket_from_regime("elevated") == "high"
        assert selector.infer_vol_bucket_from_regime("quiet") == "low"
        assert selector.infer_vol_bucket_from_regime("normal") == "medium"


class TestStrikeSelectorSingleton:
    """Tests for singleton instance."""

    def test_get_strike_selector_singleton(self):
        """Test that get_strike_selector returns singleton."""
        reset_strike_selector()
        s1 = get_strike_selector()
        s2 = get_strike_selector()
        assert s1 is s2

    def test_reset_strike_selector(self):
        """Test that reset creates new instance."""
        s1 = get_strike_selector()
        reset_strike_selector()
        s2 = get_strike_selector()
        assert s1 is not s2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
