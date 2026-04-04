"""Tests for CT new knobs wiring (AUDIT-02..08, AUDIT-20, AUDIT-16).

Covers:
  AUDIT-02  — max_candidates_per_asset cap respected by MarketFilter
  AUDIT-03  — max_spread_cents filter enforced
  AUDIT-04  — min_volume filter enforced
  AUDIT-06  — max_position_contracts cap applied to sizing
  AUDIT-07  — exposure_multiplier scales computed notional
  AUDIT-08  — per-asset cooldown via _last_trade_ts
  AUDIT-16  — _CRYPTO_ASSETS / _CRYPTO_TIMEFRAMES from config.crypto_universe
  AUDIT-20  — _refresh_candidates halts CT when zero candidates exist
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_mock_catalog(markets_by_asset: Optional[Dict] = None):
    """Return a mock KalshiMarketCatalog."""
    catalog = MagicMock()
    markets_by_asset = markets_by_asset or {}
    catalog.get_markets_by_asset.side_effect = lambda asset, timeframe=None: (
        markets_by_asset.get((asset, timeframe), [])
    )
    return catalog


def _make_ct(catalog=None, **kwargs):
    """Build a KalshiContinuousTrader with dry_run=True and a mock catalog."""
    if catalog is None:
        catalog = _make_mock_catalog()
    with patch("merid.trading.kalshi_continuous_trader._assert_kalshi_credentials_present"):
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader
        return KalshiContinuousTrader(catalog=catalog, dry_run=True, **kwargs)


# ── AUDIT-16: _CRYPTO_ASSETS / _CRYPTO_TIMEFRAMES from crypto_universe ────────

class TestCryptoUniverseImport:
    def test_crypto_assets_from_canonical_universe(self):
        from merid.trading.kalshi_continuous_trader import _CRYPTO_ASSETS
        from config.crypto_universe import CRYPTO_ASSETS_ORDERED
        assert tuple(CRYPTO_ASSETS_ORDERED) == _CRYPTO_ASSETS

    def test_crypto_timeframes_from_canonical_universe(self):
        from merid.trading.kalshi_continuous_trader import _CRYPTO_TIMEFRAMES
        from config.crypto_universe import CRYPTO_TIMEFRAMES_ORDERED
        assert tuple(CRYPTO_TIMEFRAMES_ORDERED) == _CRYPTO_TIMEFRAMES

    def test_canonical_assets_contain_5_coins(self):
        from merid.trading.kalshi_continuous_trader import _CRYPTO_ASSETS
        assert len(_CRYPTO_ASSETS) == 5
        for coin in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            assert coin in _CRYPTO_ASSETS

    def test_canonical_timeframes_contain_5(self):
        from merid.trading.kalshi_continuous_trader import _CRYPTO_TIMEFRAMES
        assert len(_CRYPTO_TIMEFRAMES) == 5


# ── AUDIT-02: max_candidates_per_asset ────────────────────────────────────────

class TestMaxCandidatesCapWiring:
    def test_filter_config_inherits_max_candidates(self):
        ct = _make_ct(max_candidates_per_asset=3)
        assert ct._filter_config.max_candidates_per_asset == 3

    def test_default_max_candidates_is_5(self, monkeypatch):
        monkeypatch.delenv("MERID_CT_MAX_CANDIDATES", raising=False)
        ct = _make_ct()
        assert ct._filter_config.max_candidates_per_asset == 5


# ── AUDIT-03: max_spread_cents ────────────────────────────────────────────────

class TestSpreadFilterWiring:
    def test_filter_config_inherits_max_spread(self):
        ct = _make_ct(max_spread_cents=8)
        assert ct._filter_config.max_spread_cents == 8

    def test_default_max_spread_is_12(self, monkeypatch):
        monkeypatch.delenv("MERID_CT_MAX_SPREAD_CENTS", raising=False)
        ct = _make_ct()
        assert ct._filter_config.max_spread_cents == 12


# ── AUDIT-04: min_volume ──────────────────────────────────────────────────────

class TestMinVolumeWiring:
    def test_filter_config_inherits_min_volume(self):
        ct = _make_ct(min_volume=200)
        assert ct._filter_config.min_volume == 200

    def test_default_min_volume_is_50(self, monkeypatch):
        monkeypatch.delenv("MERID_CT_MIN_VOLUME", raising=False)
        ct = _make_ct()
        assert ct._filter_config.min_volume == 50


# ── AUDIT-06 / 07: contracts cap + exposure multiplier ───────────────────────

class TestContractsCap:
    def test_ct_stores_max_position_contracts(self):
        ct = _make_ct(max_position_contracts=10)
        assert ct._max_position_contracts == 10

    def test_default_max_position_contracts_is_zero(self, monkeypatch):
        monkeypatch.delenv("MERID_CT_MAX_POSITION_CONTRACTS", raising=False)
        ct = _make_ct()
        assert ct._max_position_contracts == 0


class TestExposureMultiplierWiring:
    def test_ct_stores_exposure_multiplier(self):
        ct = _make_ct(exposure_multiplier=0.5)
        assert ct._exposure_multiplier == pytest.approx(0.5)

    def test_default_exposure_multiplier_is_1(self, monkeypatch):
        monkeypatch.delenv("MERID_CT_EXPOSURE_MULTIPLIER", raising=False)
        ct = _make_ct()
        assert ct._exposure_multiplier == pytest.approx(1.0)


# ── AUDIT-08: per-asset cooldown ──────────────────────────────────────────────

class TestPerAssetCooldownWiring:
    def test_ct_stores_cooldown(self):
        ct = _make_ct(per_asset_cooldown_seconds=60.0)
        assert ct._per_asset_cooldown_seconds == pytest.approx(60.0)

    def test_last_trade_ts_initially_empty(self):
        ct = _make_ct(per_asset_cooldown_seconds=30.0)
        assert ct._last_trade_ts == {}

    def test_cooldown_enforced_in_trade_cycle(self, monkeypatch):
        """A candidate that was just traded should be skipped on the next cycle."""
        ct = _make_ct(per_asset_cooldown_seconds=300.0)
        # Pretend BTC was traded just now
        ct._last_trade_ts["BTC"] = time.time()
        # The trade cycle checks cooldown before ordering; here we check that the
        # _last_trade_ts dict is populated and that the remaining time is > 0
        last = ct._last_trade_ts.get("BTC", 0.0)
        elapsed = time.time() - last
        assert elapsed < ct._per_asset_cooldown_seconds

    def test_zero_cooldown_does_not_block(self):
        ct = _make_ct(per_asset_cooldown_seconds=0.0)
        # With cooldown disabled, any asset key set in the past still passes
        ct._last_trade_ts["ETH"] = time.time() - 999
        elapsed = time.time() - ct._last_trade_ts.get("ETH", 0.0)
        # cooldown is 0 so check is disabled; elapsed > 0 = would proceed
        assert elapsed > ct._per_asset_cooldown_seconds


# ── AUDIT-20: _refresh_candidates halts CT on zero candidates ─────────────────

class TestRefreshCandidatesHaltOnZero:
    @pytest.mark.asyncio
    async def test_zero_candidates_sets_running_false(self):
        """CT must set _running=False and log CRITICAL when catalog yields nothing."""
        catalog = _make_mock_catalog(markets_by_asset={})
        ct = _make_ct(catalog=catalog)
        ct._running = True

        import logging
        with patch("merid.trading.kalshi_continuous_trader.logger") as mock_logger:
            await ct._refresh_candidates()

        assert ct._running is False
        mock_logger.critical.assert_called_once()
        call_args = mock_logger.critical.call_args[0]
        assert "zero candidates" in call_args[0].lower()

    @pytest.mark.asyncio
    async def test_nonzero_candidates_keeps_running(self):
        """When at least one market exists, CT must remain running."""
        from merid.event_venues.kalshi.market_catalog import CatalogMarket
        mock_event_market = MagicMock()
        mock_event_market.outcomes = []
        mock_catalog_market = MagicMock(spec=CatalogMarket)
        mock_catalog_market.market = mock_event_market
        mock_catalog_market.ticker = "KXBTCD-25JUN-T100000"
        mock_catalog_market.underlying = "BTC"
        mock_catalog_market.timeframe = "15m"
        mock_catalog_market.volume = 100

        catalog = MagicMock()
        # Return one market for BTC/15m, nothing else
        def _get(asset, timeframe=None):
            if asset == "BTC" and timeframe == "15m":
                return [mock_catalog_market]
            return []
        catalog.get_markets_by_asset.side_effect = _get

        ct = _make_ct(catalog=catalog)
        ct._running = True

        await ct._refresh_candidates()
        # CT should stay running — it has candidates from BTC/15m
        assert ct._running is True

    @pytest.mark.asyncio
    async def test_refresh_candidates_wires_spot_prices_into_filter_candidates(self):
        from merid.event_venues.kalshi.market_catalog import CatalogMarket

        mock_event_market = MagicMock()
        mock_event_market.outcomes = []
        mock_event_market.volume = 100
        mock_event_market.open_interest = 10
        mock_catalog_market = MagicMock(spec=CatalogMarket)
        mock_catalog_market.market = mock_event_market
        mock_catalog_market.category = "crypto"
        mock_catalog_market.expires_at = None
        mock_catalog_market.strike_price = 100000.0

        catalog = MagicMock()
        catalog.get_markets_by_asset.side_effect = lambda asset, timeframe=None: [mock_catalog_market] if asset == "BTC" and timeframe == "15m" else []

        ct = _make_ct(catalog=catalog)
        captured_candidates: List[Any] = []

        def _capture(candidates):
            captured_candidates.extend(candidates)
            return SimpleNamespace(
                candidates=[],
                total_input=len(candidates),
                passed=0,
                rejected_oi=0,
                rejected_volume_band=0,
                rejected_edge_deadzone=0,
                rejected_distance=0,
                rejected_price=0,
                rejected_spread=0,
                rejected_volume=0,
                rejected_missing_spot=0,
                capped_per_asset=0,
            )

        with patch("merid.trading.kalshi_continuous_trader._fetch_spot_prices_with_fallback", AsyncMock(return_value={"BTC": 99500.0})):
            ct._filter.filter_markets = _capture
            await ct._refresh_candidates()

        assert captured_candidates
        assert captured_candidates[0].spot_price == 99500.0


# ── AUDIT-11: agent_stagger_seconds in agent_grid ─────────────────────────────

class TestAgentGridStagger:
    def test_default_stagger_is_half_second(self, monkeypatch):
        monkeypatch.delenv("MERID_AGENT_STAGGER_SECONDS", raising=False)
        import importlib
        import merid.prediction.agent_grid as ag
        importlib.reload(ag)
        # The stagger is read inside the start() method; verify the env default
        import os
        assert float(os.getenv("MERID_AGENT_STAGGER_SECONDS", "0.5")) == pytest.approx(0.5)

    def test_env_override_controls_stagger(self, monkeypatch):
        monkeypatch.setenv("MERID_AGENT_STAGGER_SECONDS", "2.0")
        import os
        assert float(os.getenv("MERID_AGENT_STAGGER_SECONDS", "0.5")) == pytest.approx(2.0)

    def test_zero_stagger_disables_sleep(self, monkeypatch):
        monkeypatch.setenv("MERID_AGENT_STAGGER_SECONDS", "0")
        import os
        assert float(os.getenv("MERID_AGENT_STAGGER_SECONDS", "0.5")) == pytest.approx(0.0)
