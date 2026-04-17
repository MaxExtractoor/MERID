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

    @pytest.mark.asyncio
    async def test_first_message_sends_immediately(self):
        """First message after long gap should send immediately (not buffer)."""
        self._reset_globals()
        with patch("merid.alerts.webhook_client._tg_raw_send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            from merid.alerts.webhook_client import tg_send, _tg_buffer
            result = await tg_send("hello world")
            assert result is True
            mock_send.assert_called_once_with("hello world", 5.0)
            assert len(_tg_buffer) == 0  # Not buffered

    @pytest.mark.asyncio
    async def test_rapid_messages_get_buffered(self):
        """Second message within flush interval should be buffered."""
        self._reset_globals()
        import merid.alerts.webhook_client as wc
        with patch("merid.alerts.webhook_client._tg_raw_send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            # First send claims the slot
            await wc.tg_send("msg1")
            assert mock_send.call_count == 1

            # Second send within interval should be buffered
            await wc.tg_send("msg2")
            assert mock_send.call_count == 1  # Still 1 — msg2 was buffered
            assert len(wc._tg_buffer) == 1
            assert "msg2" in list(wc._tg_buffer)

    @pytest.mark.asyncio
    async def test_critical_messages_bypass_buffer(self):
        """Messages containing critical keywords should send immediately."""
        self._reset_globals()
        import merid.alerts.webhook_client as wc
        with patch("merid.alerts.webhook_client._tg_raw_send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            # First normal message
            await wc.tg_send("normal msg")
            assert mock_send.call_count == 1

            # Critical message should bypass buffer even within interval
            await wc.tg_send("⛔ KILL SWITCH ACTIVATED: daily loss")
            assert mock_send.call_count == 2
            assert "KILL SWITCH" in mock_send.call_args_list[1][0][0]

    @pytest.mark.asyncio
    async def test_critical_keywords_case_sensitive(self):
        """All critical keyword variants should bypass."""
        self._reset_globals()
        import merid.alerts.webhook_client as wc

        keywords_to_test = [
            "KILL SWITCH active",
            "kill switch triggered",
            "CIRCUIT BREAKER fired",
            "EMERGENCY stop",
            "DRAWDOWN UNWIND threshold",
        ]
        with patch("merid.alerts.webhook_client._tg_raw_send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            for kw in keywords_to_test:
                await wc.tg_send(kw)
            # All should have been sent immediately
            assert mock_send.call_count == len(keywords_to_test)

    @pytest.mark.asyncio
    async def test_buffer_overflow_drops_oldest(self):
        """Buffer should not exceed _TG_MAX_BUFFER."""
        self._reset_globals()
        import merid.alerts.webhook_client as wc
        # Set last_send to now so everything buffers
        wc._tg_last_send = time.monotonic()

        with patch("merid.alerts.webhook_client._tg_raw_send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            for i in range(30):  # More than _TG_MAX_BUFFER (20)
                await wc.tg_send(f"msg_{i}")
            assert len(wc._tg_buffer) <= wc._TG_MAX_BUFFER

    @pytest.mark.asyncio
    async def test_flush_buffer_combines_messages(self):
        """_tg_flush_buffer should combine buffered messages into one send."""
        self._reset_globals()
        import merid.alerts.webhook_client as wc
        wc._tg_last_send = time.monotonic()  # Force buffering

        with patch("merid.alerts.webhook_client._tg_raw_send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            # Buffer 3 messages
            await wc.tg_send("alpha")
            await wc.tg_send("beta")
            await wc.tg_send("gamma")
            assert mock_send.call_count == 0  # All buffered

            # Flush
            await wc._tg_flush_buffer()
            assert mock_send.call_count == 1
            combined = mock_send.call_args[0][0]
            assert "alpha" in combined
            assert "beta" in combined
            assert "gamma" in combined
            assert len(wc._tg_buffer) == 0


# ---------------------------------------------------------------------------
# send_signal_digest tests
# ---------------------------------------------------------------------------


class TestSignalDigest:
    """Verify signal digest formatting."""

    @pytest.mark.asyncio
    async def test_digest_groups_by_direction(self):
        """Signals should be grouped into BULLISH/BEARISH/NEUTRAL."""
        with patch("merid.alerts.webhook_client.tg_send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            from merid.alerts.webhook_client import send_signal_digest

            signals = [
                {"direction": "yes", "ticker": "KXBTCD-T100", "probability": 0.7, "confidence": 0.8, "agent": "btc_15m"},
                {"direction": "no", "ticker": "KXETHUSD-T50", "probability": 0.4, "confidence": 0.6, "agent": "eth_1h"},
                {"direction": "neutral", "ticker": "KXSOLUSD-T10", "probability": 0.5, "confidence": 0.3, "agent": "sol_daily"},
            ]
            trades = [
                {"ticker": "KXBTCD-T100", "side": "yes", "size": 25.0, "pnl": 3.50},
            ]

            await send_signal_digest(signals, trades, asset="BTC")
            mock_send.assert_called_once()
            msg = mock_send.call_args[0][0]

            assert "BULLISH" in msg
            assert "BEARISH" in msg
            assert "NEUTRAL" in msg
            assert "Active Trades" in msg
            assert "$+3.50" in msg

    @pytest.mark.asyncio
    async def test_digest_empty_signals(self):
        """Empty signals should show 'No active signals'."""
        with patch("merid.alerts.webhook_client.tg_send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            from merid.alerts.webhook_client import send_signal_digest

            await send_signal_digest([], [])
            msg = mock_send.call_args[0][0]
            assert "No active signals" in msg
            assert "No active trades" in msg

    @pytest.mark.asyncio
    async def test_digest_with_only_trades(self):
        """Should show trades even with no signals."""
        with patch("merid.alerts.webhook_client.tg_send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            from merid.alerts.webhook_client import send_signal_digest

            trades = [
                {"ticker": "KXBTCD-T100", "side": "yes", "size": 10.0, "pnl": -1.50},
            ]
            await send_signal_digest([], trades)
            msg = mock_send.call_args[0][0]
            assert "No active signals" in msg
            assert "Active Trades" in msg


# ---------------------------------------------------------------------------
# send_trade_fill_alert tests
# ---------------------------------------------------------------------------


class TestTradeFillAlert:
    """Verify trade fill alert formatting."""

    @pytest.mark.asyncio
    async def test_paper_trade_format(self):
        with patch("merid.alerts.webhook_client.tg_send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            from merid.alerts.webhook_client import send_trade_fill_alert

            await send_trade_fill_alert(
                ticker="KXBTCD-T100",
                direction="yes",
                contracts=5,
                price=0.65,
                size_usd=32.50,
                mode="paper",
                pnl=2.50,
            )
            msg = mock_send.call_args[0][0]
            assert "PAPER" in msg
            assert "YES" in msg
            assert "KXBTCD-T100" in msg
            assert "pnl=$+2.50" in msg

    @pytest.mark.asyncio
    async def test_live_trade_format(self):
        with patch("merid.alerts.webhook_client.tg_send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            from merid.alerts.webhook_client import send_trade_fill_alert

            await send_trade_fill_alert(
                ticker="KXBTCD-T100",
                direction="no",
                contracts=3,
                price=0.40,
                size_usd=12.00,
                mode="live",
            )
            msg = mock_send.call_args[0][0]
            assert "LIVE" in msg
            assert "NO" in msg
            assert "pnl" not in msg  # No pnl provided


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
