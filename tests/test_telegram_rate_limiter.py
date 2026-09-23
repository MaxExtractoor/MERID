"""Tests for Telegram flood control and crypto discovery helpers.

Covers:
- tg_send circuit breaker: closed-path sends, open-breaker suppression,
  429/timeout trips
- KalshiMarketCatalog.get_crypto_markets / get_crypto_tickers
"""

from __future__ import annotations

import asyncio
import time
import threading
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# tg_send circuit-breaker flood control tests
#
# The legacy buffer-based rate limiter (_tg_buffer / _tg_flush_buffer) was
# removed. Flood control is now a shared circuit breaker: every send checks
# is_open() first, and a Telegram 429 or a timeout trips the breaker so a
# failure storm suppresses subsequent sends instead of hammering the API.
# ---------------------------------------------------------------------------


def _ok_response():
    resp = MagicMock()
    resp.status_code = 200
    return resp


def _429_response(retry_after: float = 30.0):
    resp = MagicMock()
    resp.status_code = 429
    resp.text = "Too Many Requests"
    resp.json.return_value = {"parameters": {"retry_after": retry_after}}
    return resp


class TestTgSendCircuitBreaker:
    """Verify tg_send honors and trips the shared Telegram circuit breaker."""

    def _reset(self):
        from merid.alerts import tg_circuit_breaker as cb
        cb.reset()

    def _patched(self, post_side_effect=None, post_return=None):
        """Patch creds + httpx so tg_send never hits the network."""
        import merid.alerts.webhook_client as wc
        client = MagicMock()
        if post_side_effect is not None:
            client.post = AsyncMock(side_effect=post_side_effect)
        else:
            client.post = AsyncMock(return_value=post_return or _ok_response())
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=client)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return wc, client, patch("merid.alerts.webhook_client._tg_creds",
                                 return_value=("tok", "chat")),             patch("httpx.AsyncClient", return_value=ctx)

    @pytest.mark.asyncio
    async def test_send_succeeds_when_breaker_closed(self):
        self._reset()
        wc, client, creds, http = self._patched()
        with creds, http:
            assert await wc.tg_send("hello world") is True
            client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_skipped_when_breaker_open(self):
        """An open breaker suppresses sends without any HTTP call."""
        self._reset()
        from merid.alerts import tg_circuit_breaker as cb
        cb.trip(60.0, source="test")
        wc, client, creds, http = self._patched()
        with creds, http:
            assert await wc.tg_send("suppressed") is False
            client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_429_trips_breaker(self):
        """A Telegram 429 response must trip the breaker (flood control)."""
        self._reset()
        from merid.alerts import tg_circuit_breaker as cb
        wc, client, creds, http = self._patched(post_return=_429_response(45.0))
        with creds, http:
            assert await wc.tg_send("flood") is False
        assert cb.is_open()
        # Subsequent sends are suppressed while the breaker is open.
        with creds, http:
            assert await wc.tg_send("still open") is False
        assert client.post.call_count == 1  # only the first send hit HTTP

    @pytest.mark.asyncio
    async def test_timeout_trips_breaker(self):
        """A send timeout must trip the breaker to suppress a retry storm."""
        self._reset()
        from merid.alerts import tg_circuit_breaker as cb
        wc, client, creds, http = self._patched(
            post_side_effect=Exception("request timed out"))
        with creds, http:
            assert await wc.tg_send("slow") is False
        assert cb.is_open()

    @pytest.mark.asyncio
    async def test_reset_restores_sends(self):
        self._reset()
        from merid.alerts import tg_circuit_breaker as cb
        cb.trip(60.0, source="test")
        assert cb.is_open()
        cb.reset()
        assert not cb.is_open()
        wc, client, creds, http = self._patched()
        with creds, http:
            assert await wc.tg_send("back online") is True

    @pytest.mark.asyncio
    async def test_no_credentials_skips_without_breaker(self):
        """Missing creds skip the send (fail-quiet) without tripping."""
        self._reset()
        from merid.alerts import tg_circuit_breaker as cb
        import merid.alerts.webhook_client as wc
        with patch("merid.alerts.webhook_client._tg_creds",
                   return_value=(None, None)):
            assert await wc.tg_send("no creds") is False
        assert not cb.is_open()


# ---------------------------------------------------------------------------
# Crypto market catalog tests
# ---------------------------------------------------------------------------


class TestCryptoMarketDiscovery:
    """Verify catalog crypto filtering methods."""

    def _make_catalog(self):
        """Build a minimal catalog with mock markets."""
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog, CatalogMarket
        from merid.event_venues.base import EventMarket

        catalog = KalshiMarketCatalog.__new__(KalshiMarketCatalog)
        catalog._markets = []
        catalog._by_category = {}
        catalog._by_asset = {}
        catalog._by_timeframe = {}
        catalog._by_ticker = {}
        catalog._last_refresh = None
        catalog._refresh_count = 0
        catalog._lock = asyncio.Lock()
        catalog._task = None
        catalog._shutdown = asyncio.Event()
        catalog._refresh_interval = 300.0
        catalog._max_markets = 2000

        # Create mock markets
        def _mock_market(ticker, category, asset, volume, timeframe):
            mkt = MagicMock(spec=EventMarket)
            mkt.market_id = ticker
            mkt.volume = str(volume)
            mkt.question = f"Will {asset} reach target?"
            cm = MagicMock(spec=CatalogMarket)
            cm.market = mkt
            cm.category = category
            cm.asset = asset
            cm.timeframe = timeframe
            return cm

        crypto_btc_15m = _mock_market("KXBTCD-25MAR-T100000", "crypto", "BTC", 5000000, "15m")
        crypto_eth_1h = _mock_market("KXETHUSD-25MAR-T5000", "crypto", "ETH", 2000000, "1h")
        crypto_sol_daily = _mock_market("KXSOLUSD-25MAR-T200", "crypto", "SOL", 100000, "daily")
        politics = _mock_market("PRES-2028-DEM", "politics", None, 8000000, None)

        all_markets = [crypto_btc_15m, crypto_eth_1h, crypto_sol_daily, politics]
        catalog._markets = all_markets
        catalog._by_category = {
            "crypto": [crypto_btc_15m, crypto_eth_1h, crypto_sol_daily],
            "politics": [politics],
        }
        catalog._by_asset = {
            "BTC": [crypto_btc_15m],
            "ETH": [crypto_eth_1h],
            "SOL": [crypto_sol_daily],
        }
        catalog._by_timeframe = {
            "15m": [crypto_btc_15m],
            "1h": [crypto_eth_1h],
            "daily": [crypto_sol_daily],
        }
        catalog._by_ticker = {m.market.market_id: m for m in all_markets}
        return catalog

    def test_get_markets_by_category_crypto_scoped_to_15m(self):
        """Crypto category lookups are scope-filtered to 15m markets only."""
        catalog = self._make_catalog()
        results = catalog.get_markets_by_category("crypto")
        tickers = [m.market.market_id for m in results]
        # Only the BTC 15m market survives the production 15m scope filter.
        assert tickers == ["KXBTCD-25MAR-T100000"]
        assert "PRES-2028-DEM" not in tickers

    def test_get_markets_by_category_excludes_non_crypto(self):
        catalog = self._make_catalog()
        results = catalog.get_markets_by_category("crypto")
        assert all(m.category == "crypto" for m in results)

    def test_get_markets_by_category_politics_unfiltered(self):
        """Non-crypto categories are not subject to the 15m scope filter."""
        catalog = self._make_catalog()
        results = catalog.get_markets_by_category("politics")
        assert [m.market.market_id for m in results] == ["PRES-2028-DEM"]

    def test_get_markets_by_asset_filters_to_15m(self):
        """Allowed crypto assets are filtered to 15m markets."""
        catalog = self._make_catalog()
        btc = catalog.get_markets_by_asset("BTC")
        assert [m.market.market_id for m in btc] == ["KXBTCD-25MAR-T100000"]
        # ETH only has a 1h market in this fixture -> scoped out.
        assert catalog.get_markets_by_asset("ETH") == []

    def test_get_markets_by_timeframe(self):
        catalog = self._make_catalog()
        daily = catalog.get_markets_by_timeframe("daily")
        assert [m.market.market_id for m in daily] == ["KXSOLUSD-25MAR-T200"]
        hourly = catalog.get_markets_by_timeframe("1h")
        assert [m.market.market_id for m in hourly] == ["KXETHUSD-25MAR-T5000"]

    def test_get_market_by_ticker(self):
        catalog = self._make_catalog()
        assert catalog.get_market("KXBTCD-25MAR-T100000").asset == "BTC"
        assert catalog.get_market("PRES-2028-DEM").category == "politics"
        assert catalog.get_market("NOPE") is None

    def test_get_all_markets(self):
        catalog = self._make_catalog()
        assert len(catalog.get_all_markets()) == 4


class TestAlertManagerSinkEnabled:
    """Verify the Telegram sink is re-enabled in PredictionAlertManager."""

    def test_singleton_has_sink(self):
        """get_alert_manager() should register a Telegram sink."""
        import merid.prediction.alerts as alerts_mod
        # Reset singleton
        alerts_mod._alert_manager = None
        with patch("merid.prediction.alerts._make_telegram_sink") as mock_make:
            mock_sink = MagicMock()
            mock_make.return_value = mock_sink
            mgr = alerts_mod.get_alert_manager()
            mock_make.assert_called_once()
            assert mock_sink in mgr._sinks

    def test_singleton_handles_no_sink(self):
        """If _make_telegram_sink returns None, no sink should be added."""
        import merid.prediction.alerts as alerts_mod
        alerts_mod._alert_manager = None
        with patch("merid.prediction.alerts._make_telegram_sink", return_value=None):
            mgr = alerts_mod.get_alert_manager()
            assert len(mgr._sinks) == 0


# ---------------------------------------------------------------------------
# Dashboard loop interval
# ---------------------------------------------------------------------------


class TestDashboardLoopInterval:
    """Verify the dashboard loop exposes a bounded default interval."""

    def test_default_interval_is_60(self):
        import inspect
        from merid.alerts.webhook_client import dashboard_loop
        sig = inspect.signature(dashboard_loop)
        assert sig.parameters["interval_sec"].default == 60.0
