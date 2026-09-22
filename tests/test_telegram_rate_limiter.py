"""Tests for Telegram rate limiter, signal digest, and crypto discovery helpers.

Covers:
- tg_send global rate limiter: buffering, flush, critical bypass
- send_signal_digest: bullish/bearish/neutral grouping
- send_trade_fill_alert: formatting
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
# tg_send rate limiter tests
# ---------------------------------------------------------------------------


class TestTgSendRateLimiter:
    """Verify that tg_send buffers and batches messages."""

    def _reset_globals(self):
        """Reset module-level rate limiter state between tests."""
        import merid.alerts.webhook_client as wc
        with wc._tg_buffer_lock:
            wc._tg_buffer.clear()
            wc._tg_last_send = 0.0
            wc._tg_flush_scheduled = False








# ---------------------------------------------------------------------------
# send_signal_digest tests
# ---------------------------------------------------------------------------


        assert len(results) == 1
        assert results[0].market.market_id == "KXBTCD-25MAR-T100000"

    def test_get_crypto_markets_filters_by_asset(self):
        catalog = self._make_catalog()
        results = catalog.get_crypto_markets(assets=["BTC", "ETH"])
        assert len(results) == 2
        assets = {m.asset for m in results}
        assert assets == {"BTC", "ETH"}

    def test_get_crypto_markets_filters_by_volume(self):
        catalog = self._make_catalog()
        results = catalog.get_crypto_markets(min_volume=1000000)
        assert len(results) == 2  # BTC (5M) and ETH (2M), not SOL (100k)

    def test_get_crypto_tickers_returns_strings(self):
        catalog = self._make_catalog()
        tickers = catalog.get_crypto_tickers()
        assert isinstance(tickers, list)
        assert all(isinstance(t, str) for t in tickers)
        assert len(tickers) == 3

    def test_get_crypto_tickers_with_filters(self):
        catalog = self._make_catalog()
        tickers = catalog.get_crypto_tickers(min_volume=1000000, assets=["BTC"])
        assert tickers == ["KXBTCD-25MAR-T100000"]


# ---------------------------------------------------------------------------
# PredictionAlertManager Telegram sink re-enabled
# ---------------------------------------------------------------------------


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
    """Verify default dashboard interval is 5 minutes, not 2."""

    def test_default_interval_is_300(self):
        import inspect
        from merid.alerts.webhook_client import dashboard_loop
        sig = inspect.signature(dashboard_loop)
        assert sig.parameters["interval_sec"].default == 300.0



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

    def test_get_crypto_markets_returns_all_crypto(self):
        catalog = self._make_catalog()
        results = catalog.get_crypto_markets()
        assert len(results) == 3
        assert all(m.category == "crypto" for m in results)

    def test_get_crypto_markets_excludes_non_crypto(self):
        catalog = self._make_catalog()
        results = catalog.get_crypto_markets()
        tickers = [m.market.market_id for m in results]
        assert "PRES-2028-DEM" not in tickers

    def test_get_crypto_markets_filters_by_timeframe(self):
        catalog = self._make_catalog()
        results = catalog.get_crypto_markets(timeframe="15m")
        assert len(results) == 1
        assert results[0].market.market_id == "KXBTCD-25MAR-T100000"

    def test_get_crypto_markets_filters_by_asset(self):
        catalog = self._make_catalog()
        results = catalog.get_crypto_markets(assets=["BTC", "ETH"])
        assert len(results) == 2
        assets = {m.asset for m in results}
        assert assets == {"BTC", "ETH"}

    def test_get_crypto_markets_filters_by_volume(self):
        catalog = self._make_catalog()
        results = catalog.get_crypto_markets(min_volume=1000000)
        assert len(results) == 2  # BTC (5M) and ETH (2M), not SOL (100k)

    def test_get_crypto_tickers_returns_strings(self):
        catalog = self._make_catalog()
        tickers = catalog.get_crypto_tickers()
        assert isinstance(tickers, list)
        assert all(isinstance(t, str) for t in tickers)
        assert len(tickers) == 3

    def test_get_crypto_tickers_with_filters(self):
        catalog = self._make_catalog()
        tickers = catalog.get_crypto_tickers(min_volume=1000000, assets=["BTC"])
        assert tickers == ["KXBTCD-25MAR-T100000"]
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

    def test_get_crypto_markets_returns_all_crypto(self):
        catalog = self._make_catalog()
        results = catalog.get_crypto_markets()
        assert len(results) == 3
        assert all(m.category == "crypto" for m in results)

    def test_get_crypto_markets_excludes_non_crypto(self):
        catalog = self._make_catalog()
        results = catalog.get_crypto_markets()
        tickers = [m.market.market_id for m in results]
        assert "PRES-2028-DEM" not in tickers

    def test_get_crypto_markets_filters_by_timeframe(self):
        catalog = self._make_catalog()
        results = catalog.get_crypto_markets(timeframe="15m")
        assert len(results) == 1
        assert results[0].market.market_id == "KXBTCD-25MAR-T100000"

    def test_get_crypto_markets_filters_by_asset(self):
        catalog = self._make_catalog()
        results = catalog.get_crypto_markets(assets=["BTC", "ETH"])
        assert len(results) == 2
        assets = {m.asset for m in results}
        assert assets == {"BTC", "ETH"}

    def test_get_crypto_markets_filters_by_volume(self):
        catalog = self._make_catalog()
        results = catalog.get_crypto_markets(min_volume=1000000)
        assert len(results) == 2  # BTC (5M) and ETH (2M), not SOL (100k)

    def test_get_crypto_tickers_returns_strings(self):
        catalog = self._make_catalog()
        tickers = catalog.get_crypto_tickers()
        assert isinstance(tickers, list)
        assert all(isinstance(t, str) for t in tickers)
        assert len(tickers) == 3

    def test_get_crypto_tickers_with_filters(self):
        catalog = self._make_catalog()
        tickers = catalog.get_crypto_tickers(min_volume=1000000, assets=["BTC"])
        assert tickers == ["KXBTCD-25MAR-T100000"]


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

    def test_get_crypto_markets_returns_all_crypto(self):
        catalog = self._make_catalog()
        results = catalog.get_crypto_markets()
        assert len(results) == 3
        assert all(m.category == "crypto" for m in results)

    def test_get_crypto_markets_excludes_non_crypto(self):
        catalog = self._make_catalog()
        results = catalog.get_crypto_markets()
        tickers = [m.market.market_id for m in results]
        assert "PRES-2028-DEM" not in tickers

    def test_get_crypto_markets_filters_by_timeframe(self):
        catalog = self._make_catalog()
        results = catalog.get_crypto_markets(timeframe="15m")
        assert len(results) == 1
        assert results[0].market.market_id == "KXBTCD-25MAR-T100000"

    def test_get_crypto_markets_filters_by_asset(self):
        catalog = self._make_catalog()
        results = catalog.get_crypto_markets(assets=["BTC", "ETH"])
        assert len(results) == 2
        assets = {m.asset for m in results}
        assert assets == {"BTC", "ETH"}

    def test_get_crypto_markets_filters_by_volume(self):
        catalog = self._make_catalog()
        results = catalog.get_crypto_markets(min_volume=1000000)
        assert len(results) == 2  # BTC (5M) and ETH (2M), not SOL (100k)

    def test_get_crypto_tickers_returns_strings(self):
        catalog = self._make_catalog()
        tickers = catalog.get_crypto_tickers()
        assert isinstance(tickers, list)
        assert all(isinstance(t, str) for t in tickers)
        assert len(tickers) == 3

    def test_get_crypto_tickers_with_filters(self):
        catalog = self._make_catalog()
        tickers = catalog.get_crypto_tickers(min_volume=1000000, assets=["BTC"])
        assert tickers == ["KXBTCD-25MAR-T100000"]


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

    def test_get_crypto_markets_returns_all_crypto(self):
        catalog = self._make_catalog()
        results = catalog.get_crypto_markets()
        assert len(results) == 3
        assert all(m.category == "crypto" for m in results)

    def test_get_crypto_markets_excludes_non_crypto(self):
        catalog = self._make_catalog()
        results = catalog.get_crypto_markets()
        tickers = [m.market.market_id for m in results]
        assert "PRES-2028-DEM" not in tickers

    def test_get_crypto_markets_filters_by_timeframe(self):
        catalog = self._make_catalog()
        results = catalog.get_crypto_markets(timeframe="15m")
        assert len(results) == 1
        assert results[0].market.market_id == "KXBTCD-25MAR-T100000"

    def test_get_crypto_markets_filters_by_asset(self):
        catalog = self._make_catalog()
        results = catalog.get_crypto_markets(assets=["BTC", "ETH"])
        assert len(results) == 2
        assets = {m.asset for m in results}
        assert assets == {"BTC", "ETH"}

    def test_get_crypto_markets_filters_by_volume(self):
        catalog = self._make_catalog()
        results = catalog.get_crypto_markets(min_volume=1000000)
        assert len(results) == 2  # BTC (5M) and ETH (2M), not SOL (100k)

    def test_get_crypto_tickers_returns_strings(self):
        catalog = self._make_catalog()
        tickers = catalog.get_crypto_tickers()
        assert isinstance(tickers, list)
        assert all(isinstance(t, str) for t in tickers)
        assert len(tickers) == 3

    def test_get_crypto_tickers_with_filters(self):
        catalog = self._make_catalog()
        tickers = catalog.get_crypto_tickers(min_volume=1000000, assets=["BTC"])
        assert tickers == ["KXBTCD-25MAR-T100000"]