"""Safety gate tests for KalshiContinuousTrader.

Covers:
  TestLivePmGate           — _live_api_orders_allowed() allows demo env without pm_live
  TestPerAssetConfig       — PER_ASSET_EXPOSURE_PCTS defaults and GLOBAL_MAX_EXPOSURE_PCT
  TestCalibratedExposureValues — compute_exposure_cap_cents / compute_global_max_cap_cents
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


# ── Fixture ──────────────────────────────────────────────────────────────────

def _make_ct(**kwargs):
    """Return a KalshiContinuousTrader with a mocked catalog and dry_run=True."""
    mock_catalog = MagicMock()
    mock_catalog.get_markets_by_asset.return_value = []
    with patch(
        "merid.trading.kalshi_continuous_trader.get_market_catalog",
        return_value=mock_catalog,
    ):
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader
        return KalshiContinuousTrader(catalog=mock_catalog, dry_run=True, **kwargs)


# ── TestLivePmGate ────────────────────────────────────────────────────────────

class TestLivePmGate:
    """_live_api_orders_allowed() safety-gate behaviour."""

    def test_demo_env_allows_without_pm_live(self, monkeypatch):
        """In paper/demo mode, orders are allowed without MERID_PM_TRADING_MODE=live."""
        monkeypatch.setenv("MERID_TRADE_MODE", "paper")
        monkeypatch.setenv("MERID_PM_TRADING_MODE", "paper")
        t = _make_ct()
        t._guardian = None
        t._base_url = "https://demo-api.kalshi.co"
        assert t._live_api_orders_allowed() is True

    def test_paper_mode_allows_without_guardian(self, monkeypatch):
        """No guardian set + paper mode → allowed."""
        monkeypatch.setenv("MERID_TRADE_MODE", "paper")
        monkeypatch.delenv("MERID_PM_TRADING_MODE", raising=False)
        t = _make_ct()
        t._guardian = None
        assert t._live_api_orders_allowed() is True

    def test_has_base_url_attribute(self):
        """_base_url attribute must exist on every CT instance."""
        t = _make_ct()
        assert hasattr(t, "_base_url")
        assert isinstance(t._base_url, str)

    def test_has_guardian_attribute(self):
        """_guardian attribute must exist on every CT instance."""
        t = _make_ct()
        assert hasattr(t, "_guardian")

    def test_guardian_none_by_default(self):
        """_guardian should default to None (no guardian installed at construction)."""
        t = _make_ct()
        assert t._guardian is None

    def test_base_url_defaults_to_demo(self, monkeypatch):
        """When KALSHI_API_BASE_URL env var is unset, default to the Kalshi demo endpoint."""
        monkeypatch.delenv("KALSHI_API_BASE_URL", raising=False)
        t = _make_ct()
        assert t._base_url == "https://demo-api.kalshi.co"


# ── TestPerAssetConfig ────────────────────────────────────────────────────────

class TestPerAssetConfig:
    """Per-asset exposure percentage configuration."""

    def test_default_asset_exposure_pcts(self):
        """BTC/ETH/SOL/XRP/DOGE must each have a 0.30 default exposure pct."""
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader
        for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            pct = KalshiContinuousTrader.PER_ASSET_EXPOSURE_PCTS.get(asset)
            assert pct is not None, f"PER_ASSET_EXPOSURE_PCTS missing key '{asset}'"
            assert pct == pytest.approx(0.30), (
                f"{asset} exposure pct should be 0.30, got {pct}"
            )

    def test_global_max_exposure_pct_default(self):
        """GLOBAL_MAX_EXPOSURE_PCT must default to 0.50."""
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader
        assert KalshiContinuousTrader.GLOBAL_MAX_EXPOSURE_PCT == pytest.approx(0.50)

    def test_per_asset_pcts_accessible_on_instance(self):
        """PER_ASSET_EXPOSURE_PCTS is readable from an instance too."""
        t = _make_ct()
        assert t.PER_ASSET_EXPOSURE_PCTS["ETH"] == pytest.approx(0.30)

    def test_global_max_pct_accessible_on_instance(self):
        """GLOBAL_MAX_EXPOSURE_PCT is readable from an instance too."""
        t = _make_ct()
        assert t.GLOBAL_MAX_EXPOSURE_PCT == pytest.approx(0.50)


# ── TestCalibratedExposureValues ──────────────────────────────────────────────

class TestCalibratedExposureValues:
    """Verify computed exposure caps against anchor scenarios."""

    def test_anchor_1211_eth_1h_cap_cents(self):
        """Anchor scenario: bankroll=1211 cents.

        ETH 1h cap = bankroll × per_asset_pct(0.30) × timeframe_factor(1h=0.70)
                   = 1211 × 0.30 × 0.70 = 254.31 → truncated to 254 cents.

        Global max cap = bankroll × GLOBAL_MAX_EXPOSURE_PCT(0.50)
                       = 1211 × 0.50 = 605.5  → truncated to 605 cents.
        """
        t = _make_ct()
        bankroll = 1211  # cents

        eth_1h_cap = t.compute_exposure_cap_cents(bankroll, "ETH", "1h")
        assert eth_1h_cap == 254, (
            f"ETH 1h cap with bankroll=1211: expected 254, got {eth_1h_cap}"
        )

        global_cap = t.compute_global_max_cap_cents(bankroll)
        assert global_cap == 605, (
            f"Global max cap with bankroll=1211: expected 605, got {global_cap}"
        )

    def test_compute_exposure_cap_all_assets(self):
        """All 5 assets must produce valid (positive) caps."""
        t = _make_ct()
        bankroll = 1000
        for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            cap = t.compute_exposure_cap_cents(bankroll, asset, "1h")
            assert cap > 0, f"{asset} 1h cap should be positive"
            assert cap <= bankroll, f"{asset} 1h cap should not exceed bankroll"

    def test_compute_global_max_cap_scales_with_bankroll(self):
        """Global cap scales linearly with bankroll."""
        t = _make_ct()
        cap_100 = t.compute_global_max_cap_cents(100)
        cap_1000 = t.compute_global_max_cap_cents(1000)
        assert cap_1000 == cap_100 * 10

    def test_shorter_timeframe_yields_smaller_cap(self):
        """15m cap should be smaller than daily cap for the same asset/bankroll."""
        t = _make_ct()
        bankroll = 1000
        cap_15m = t.compute_exposure_cap_cents(bankroll, "ETH", "15m")
        cap_daily = t.compute_exposure_cap_cents(bankroll, "ETH", "daily")
        assert cap_15m < cap_daily
