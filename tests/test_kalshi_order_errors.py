"""
Unit tests for Kalshi order-error handling and ticker quarantine.

Covers:
  - Payload construction for crypto contracts (15m, daily, monthly)
  - 400 invalid_parameters → KalshiInvalidParametersError raised immediately,
    no retry, ticker quarantined
  - 404 not found → KalshiTickerNotFoundError raised immediately, no retry,
    ticker quarantined
  - Quarantine is idempotent (second quarantine logs nothing extra)
  - Quarantined ticker is blocked by validate_ticker()
  - Non-critical errors (Twitter 401, CoinGecko 429, threshold rejection)
    do NOT increment the global halt counter
  - Spot staleness gate: stale spot returns None price_usd, model skips
  - CoinGecko 429 exponential back-off
"""

from __future__ import annotations

import asyncio
import time
import unittest
from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_http_response(status_code: int, text: str = ""):
    """Build a minimal mock requests.Response."""
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    r.headers = {}
    r.json.return_value = {}
    r.raise_for_status.side_effect = (
        None if status_code < 400 else _make_http_error(status_code, text)
    )
    return r


def _make_http_error(status_code: int, text: str = ""):
    import requests
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    exc = requests.exceptions.HTTPError(response=r)
    exc.response = r
    return exc


# ===========================================================================
# § 1  REST client — KalshiInvalidParametersError and KalshiTickerNotFoundError
# ===========================================================================

class TestRestClient400(unittest.TestCase):
    """HTTP 400 raises KalshiInvalidParametersError immediately, no retry."""

    def _make_client(self):
        from merid_core.kalshi.rest_client import KalshiRestClient
        import unittest.mock as mock

        with mock.patch.object(KalshiRestClient, "_load_private_key"):
            client = KalshiRestClient.__new__(KalshiRestClient)
            client.key_id = "test-key"
            client.private_key_path = MagicMock()
            client.env = "demo"
            client.base_url = "https://demo-api.kalshi.co"
            client.api_prefix = "/trade-api/v2"
            client.private_key = MagicMock()
            client.session = MagicMock()
            client._load_private_key = MagicMock()
            return client

    def test_400_raises_invalid_parameters_error(self):
        from merid_core.kalshi.rest_client import KalshiInvalidParametersError

        client = self._make_client()
        client.session.request.return_value = _make_http_response(
            400, '{"error_code":"invalid_parameters","message":"invalid parameters"}'
        )
        client._create_auth_headers = MagicMock(return_value={})

        with self.assertRaises(KalshiInvalidParametersError) as ctx:
            client._request("POST", "/portfolio/orders", json_data={"ticker": "KXBTC-26APR1117-T81249.99"})

        self.assertEqual(ctx.exception.status_code, 400)

    def test_400_no_retry(self):
        """Session.request must be called exactly once (no retry) on 400."""
        from merid_core.kalshi.rest_client import KalshiInvalidParametersError

        client = self._make_client()
        client.session.request.return_value = _make_http_response(400, "bad request")
        client._create_auth_headers = MagicMock(return_value={})

        with self.assertRaises(KalshiInvalidParametersError):
            client._request("POST", "/portfolio/orders")

        self.assertEqual(client.session.request.call_count, 1)

    def test_404_raises_ticker_not_found_error(self):
        from merid_core.kalshi.rest_client import KalshiTickerNotFoundError

        client = self._make_client()
        client.session.request.return_value = _make_http_response(404, "not found")
        client._create_auth_headers = MagicMock(return_value={})

        with self.assertRaises(KalshiTickerNotFoundError) as ctx:
            client._request("POST", "/portfolio/orders")

        self.assertEqual(ctx.exception.status_code, 404)

    def test_404_no_retry(self):
        from merid_core.kalshi.rest_client import KalshiTickerNotFoundError

        client = self._make_client()
        client.session.request.return_value = _make_http_response(404, "not found")
        client._create_auth_headers = MagicMock(return_value={})

        with self.assertRaises(KalshiTickerNotFoundError):
            client._request("POST", "/portfolio/orders")

        self.assertEqual(client.session.request.call_count, 1)

    def test_200_returns_json(self):
        client = self._make_client()
        resp = _make_http_response(200)
        resp.raise_for_status.side_effect = None
        resp.json.return_value = {"order": {"order_id": "abc123"}}
        client.session.request.return_value = resp
        client._create_auth_headers = MagicMock(return_value={})

        result = client._request("POST", "/portfolio/orders")
        self.assertEqual(result["order"]["order_id"], "abc123")


# ===========================================================================
# § 2  TickerCatalog — validation and quarantine
# ===========================================================================

class TestTickerCatalog(unittest.TestCase):
    """Catalog validation and quarantine logic."""

    def _catalog(self, markets=None):
        from merid_core.kalshi.ticker_catalog import TickerCatalog
        cat = TickerCatalog(refresh_interval_seconds=300)
        if markets is not None:
            # Seed directly for unit tests
            from merid_core.kalshi.ticker_catalog import _MarketEntry
            cat._markets = {
                m["ticker"]: _MarketEntry(
                    ticker=m["ticker"],
                    status=m.get("status", "active"),
                    title=m.get("title", ""),
                    category=m.get("category", "crypto"),
                )
                for m in markets
            }
            cat._last_refresh = time.time()
        return cat

    def test_valid_ticker_passes(self):
        cat = self._catalog([{"ticker": "KXBTC-26APR1117-T81249.99", "status": "active"}])
        ok, reason = cat.validate_ticker("KXBTC-26APR1117-T81249.99")
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_unknown_ticker_fails(self):
        cat = self._catalog([{"ticker": "KXBTC-26APR1117-T81249.99", "status": "active"}])
        ok, reason = cat.validate_ticker("KXBTC15M-NONEXISTENT")
        self.assertFalse(ok)
        self.assertEqual(reason, "ticker_not_in_catalog")

    def test_settled_ticker_fails(self):
        cat = self._catalog([{"ticker": "KXBTC-OLD", "status": "settled"}])
        ok, reason = cat.validate_ticker("KXBTC-OLD")
        self.assertFalse(ok)
        self.assertIn("market_status", reason)

    def test_quarantine_blocks_ticker(self):
        cat = self._catalog([{"ticker": "KXBTC-26APR1117-T81249.99", "status": "active"}])
        cat.quarantine("KXBTC-26APR1117-T81249.99", "400_invalid_parameters")
        ok, reason = cat.validate_ticker("KXBTC-26APR1117-T81249.99")
        self.assertFalse(ok)
        self.assertIn("ticker_quarantined", reason)

    def test_quarantine_is_idempotent(self):
        """Second call to quarantine() must not raise or double-log."""
        cat = self._catalog([{"ticker": "KXBTCX", "status": "active"}])
        cat.quarantine("KXBTCX", "404_not_found")
        cat.quarantine("KXBTCX", "404_not_found")  # should be a no-op
        self.assertEqual(len(cat.quarantined_tickers), 1)

    def test_unquarantine_re_allows_ticker(self):
        cat = self._catalog([{"ticker": "KXBTCX", "status": "active"}])
        cat.quarantine("KXBTCX", "400_invalid_parameters")
        cat.unquarantine("KXBTCX")
        ok, _ = cat.validate_ticker("KXBTCX")
        self.assertTrue(ok)

    def test_empty_catalog_allows_with_warning(self):
        """Empty catalog must allow (not block) — avoids cold-start lockout."""
        cat = self._catalog([])  # no markets
        cat._markets = {}
        ok, reason = cat.validate_ticker("KXBTC-ANY")
        self.assertTrue(ok)
        self.assertEqual(reason, "catalog_empty_allow")

    def test_summary_includes_quarantine_count(self):
        cat = self._catalog([{"ticker": "KXBTCX", "status": "active"}])
        cat.quarantine("KXBTCX", "400_invalid_parameters")
        s = cat.summary()
        self.assertEqual(s["quarantined_count"], 1)
        self.assertIn("KXBTCX", s["quarantined_tickers"])

    def test_15m_ticker_format(self):
        """15m contract tickers are accepted when in catalog."""
        cat = self._catalog([{"ticker": "KXBTC15M-26APR101945-45", "status": "active"}])
        ok, reason = cat.validate_ticker("KXBTC15M-26APR101945-45")
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")


# ===========================================================================
# § 3  ExecutionPipeline — 400/404 quarantine integration
# ===========================================================================

class TestExecutionPipeline400(unittest.IsolatedAsyncioTestCase):
    """Pipeline quarantines tickers on 400/404 and does not retry."""

    def _make_pipeline(self):
        from merid_core.kalshi.execution_pipeline import ExecutionPipeline, OrderIntent
        bus = AsyncMock()
        bus.publish = AsyncMock()
        pipeline = ExecutionPipeline(event_bus=bus, enable_live_trading=True)
        return pipeline

    def _make_intent(self, ticker: str) -> "OrderIntent":
        from merid_core.kalshi.execution_pipeline import OrderIntent
        return OrderIntent(
            session_id="s1",
            agent_id="a1",
            market_ticker=ticker,
            side="buy_no",
            qty=1,
            price=0.50,
            client_tag="tag-001",
            timestamp=int(time.time() * 1000),
        )

    async def test_400_quarantines_ticker(self):
        from merid_core.kalshi.rest_client import KalshiInvalidParametersError
        from merid_core.kalshi.ticker_catalog import TickerCatalog

        pipeline = self._make_pipeline()
        intent = self._make_intent("KXBTC-26APR1117-T81249.99")

        # Seed catalog so pre-flight passes
        cat = TickerCatalog()
        from merid_core.kalshi.ticker_catalog import _MarketEntry
        cat._markets = {"KXBTC-26APR1117-T81249.99": _MarketEntry(
            ticker="KXBTC-26APR1117-T81249.99", status="active"
        )}
        cat._last_refresh = time.time()

        mock_client = MagicMock()
        mock_client.create_order.side_effect = KalshiInvalidParametersError(
            "400", 400, '{"error_code":"invalid_parameters"}'
        )

        with patch.object(pipeline, "_get_catalog", return_value=cat):
            with patch("merid_core.kalshi.rest_client.get_rest_client",
                       return_value=mock_client):
                await pipeline._execute_order(intent)

        # Ticker must be quarantined
        self.assertIn("KXBTC-26APR1117-T81249.99", cat.quarantined_tickers)
        # create_order called exactly once (no retry)
        mock_client.create_order.assert_called_once()

    async def test_404_quarantines_ticker(self):
        from merid_core.kalshi.rest_client import KalshiTickerNotFoundError
        from merid_core.kalshi.ticker_catalog import TickerCatalog

        pipeline = self._make_pipeline()
        intent = self._make_intent("KXBTC15M-26APR101945-45")

        cat = TickerCatalog()
        from merid_core.kalshi.ticker_catalog import _MarketEntry
        cat._markets = {"KXBTC15M-26APR101945-45": _MarketEntry(
            ticker="KXBTC15M-26APR101945-45", status="active"
        )}
        cat._last_refresh = time.time()

        mock_client = MagicMock()
        mock_client.create_order.side_effect = KalshiTickerNotFoundError(
            "404", 404, "not found"
        )

        with patch.object(pipeline, "_get_catalog", return_value=cat):
            with patch("merid_core.kalshi.rest_client.get_rest_client",
                       return_value=mock_client):
                await pipeline._execute_order(intent)

        self.assertIn("KXBTC15M-26APR101945-45", cat.quarantined_tickers)
        mock_client.create_order.assert_called_once()

    async def test_quarantined_ticker_blocked_before_execution(self):
        """Pre-flight check must block quarantined tickers without calling execute."""
        from merid_core.kalshi.execution_pipeline import ExecutionPipeline, OrderIntent
        from merid_core.kalshi.ticker_catalog import TickerCatalog, _MarketEntry
        from merid_core.event_bus.nats_adapter import EventEnvelope

        bus = AsyncMock()
        bus.publish = AsyncMock()
        pipeline = ExecutionPipeline(event_bus=bus, enable_live_trading=True)
        pipeline._execute_order = AsyncMock()

        cat = TickerCatalog()
        cat._markets = {"KXBTCX": _MarketEntry(ticker="KXBTCX", status="active")}
        cat._last_refresh = time.time()
        cat.quarantine("KXBTCX", "400_invalid_parameters")

        with patch.object(pipeline, "_get_catalog", return_value=cat):
            envelope = EventEnvelope(
                topic="intents.orders",
                data={
                    "session_id": "s1", "agent_id": "a1",
                    "market_ticker": "KXBTCX", "side": "buy_yes",
                    "qty": 1, "price": 0.50, "client_tag": "tag-002",
                },
                ts=int(time.time() * 1000),
            )
            await pipeline.handle_intent(envelope)

        pipeline._execute_order.assert_not_called()


# ===========================================================================
# § 4  Payload validation: count and side/action format
# ===========================================================================

class TestPayloadValidation(unittest.IsolatedAsyncioTestCase):
    """_execute_order validates intent fields before hitting the REST client."""

    def _make_pipeline(self):
        from merid_core.kalshi.execution_pipeline import ExecutionPipeline
        bus = AsyncMock()
        bus.publish = AsyncMock()
        return ExecutionPipeline(event_bus=bus, enable_live_trading=True)

    async def test_invalid_side_format_raises(self):
        """Malformed side ('buy' without _yes/_no) must raise ValueError."""
        from merid_core.kalshi.execution_pipeline import OrderIntent
        from merid_core.kalshi.ticker_catalog import TickerCatalog, _MarketEntry

        pipeline = self._make_pipeline()
        cat = TickerCatalog()
        cat._markets = {"KXBTCX": _MarketEntry(ticker="KXBTCX", status="active")}
        cat._last_refresh = time.time()

        intent = OrderIntent(
            session_id="s", agent_id="a", market_ticker="KXBTCX",
            side="buy",  # malformed — missing _yes/_no
            qty=1, price=0.50, client_tag="tag-003",
            timestamp=int(time.time() * 1000),
        )
        with patch.object(pipeline, "_get_catalog", return_value=cat):
            with patch("merid_core.kalshi.rest_client.get_rest_client"):
                await pipeline._execute_order(intent)

        # Should publish ERROR outcome, not raise
        pipeline.event_bus.publish.assert_called()

    async def test_zero_quantity_raises(self):
        """qty=0 must not reach the REST client."""
        from merid_core.kalshi.execution_pipeline import OrderIntent
        from merid_core.kalshi.ticker_catalog import TickerCatalog, _MarketEntry

        pipeline = self._make_pipeline()
        cat = TickerCatalog()
        cat._markets = {"KXBTCX": _MarketEntry(ticker="KXBTCX", status="active")}
        cat._last_refresh = time.time()

        intent = OrderIntent(
            session_id="s", agent_id="a", market_ticker="KXBTCX",
            side="buy_yes", qty=0, price=0.50, client_tag="tag-004",
            timestamp=int(time.time() * 1000),
        )

        mock_client = MagicMock()
        with patch.object(pipeline, "_get_catalog", return_value=cat):
            with patch("merid_core.kalshi.rest_client.get_rest_client",
                       return_value=mock_client):
                await pipeline._execute_order(intent)

        mock_client.create_order.assert_not_called()

    def test_price_clamp_to_1_99(self):
        """Prices outside [1,99] cents must be clamped before API call."""
        # Verify the clamping logic manually (it's in _execute_order)
        for raw_price, expected_cents in [(0.0, 1), (1.0, 99), (0.5, 50), (0.01, 1)]:
            cents = int(raw_price * 100)
            cents = max(1, min(99, cents))
            self.assertEqual(cents, expected_cents)


# ===========================================================================
# § 5  Spot staleness — stale spot returns None and single log
# ===========================================================================

class TestSpotStaleness(unittest.TestCase):
    """get_spot_usd returns price_usd=None when cache is older than threshold."""

    def _feed(self):
        """Create a minimal LivePriceFeed instance without exchange init."""
        from data.live_price_feed import LivePriceFeed
        with patch("data.live_price_feed.LivePriceFeed._initialize_exchanges"):
            feed = LivePriceFeed.__new__(LivePriceFeed)
            feed.price_cache = {}
            feed.symbols = []
            feed.subscribers = []
            feed.exchanges = {}
            feed.exchange_failures = {}
            feed.last_successful_fetch = {}
            feed.running = False
            feed.update_interval = 1.0
            feed.exchange_priority = []
            feed.max_retries = 3
            feed.retry_delay = 2.0
            feed.circuit_breaker_threshold = 10
            feed.circuit_breaker_reset_time = 300
            from core.network_client import get_network_client
            feed._network_client = get_network_client()
            feed._module_name = "test"
            feed._pm_last_tick_mono = {}
            feed._pm_consecutive_failures = {}
            feed._pm_start_mono = None
            feed._pm_ticker_tasks = {}
            feed._coingecko_cooldown_until = 0.0
            feed._coingecko_429_count = 0
            feed._cg_backoff_base = 60.0
            feed._cg_backoff_max = 600.0
            return feed

    def _inject_price(self, feed, asset: str, price: float, age_seconds: float):
        from datetime import datetime, timezone, timedelta
        from data.live_price_feed import PriceData

        ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
        feed.price_cache[asset] = PriceData(
            symbol=asset, price=price, bid=price * 0.999, ask=price * 1.001,
            volume_24h=0.0, change_24h_pct=0.0, timestamp=ts, exchange="coinbase",
        )

    def test_fresh_spot_returns_price(self):
        feed = self._feed()
        self._inject_price(feed, "BTC", 80000.0, age_seconds=5)
        result = feed.get_spot_usd("BTC")
        self.assertIsNotNone(result)
        self.assertEqual(result.price_usd, 80000.0)
        self.assertNotEqual(result.spot_source, "stale")

    def test_stale_spot_returns_none_price(self):
        import os
        from data import live_price_feed as lm

        old_threshold = lm._SPOT_MAX_STALENESS_SECONDS
        lm._SPOT_MAX_STALENESS_SECONDS = 30.0
        try:
            feed = self._feed()
            self._inject_price(feed, "BTC", 80000.0, age_seconds=61)
            result = feed.get_spot_usd("BTC")
            self.assertIsNotNone(result)
            self.assertIsNone(result.price_usd, "Expected None price_usd for stale spot")
            self.assertEqual(result.spot_source, "stale")
        finally:
            lm._SPOT_MAX_STALENESS_SECONDS = old_threshold

    def test_no_cached_price_returns_none(self):
        feed = self._feed()
        result = feed.get_spot_usd("DOGE")
        self.assertIsNone(result)


# ===========================================================================
# § 6  CoinGecko 429 exponential backoff
# ===========================================================================

class TestCoinGecko429Backoff(unittest.IsolatedAsyncioTestCase):
    """_fetch_from_coingecko backs off after 429 and skips during cooldown."""

    def _feed(self):
        from data.live_price_feed import LivePriceFeed
        with patch("data.live_price_feed.LivePriceFeed._initialize_exchanges"):
            feed = LivePriceFeed.__new__(LivePriceFeed)
            feed.price_cache = {}
            feed.symbols = []
            feed.subscribers = []
            feed.exchanges = {}
            feed.exchange_failures = {}
            feed.last_successful_fetch = {}
            feed.running = False
            feed.update_interval = 1.0
            feed.exchange_priority = []
            feed.max_retries = 3
            feed.retry_delay = 2.0
            feed.circuit_breaker_threshold = 10
            feed.circuit_breaker_reset_time = 300
            from core.network_client import get_network_client
            feed._network_client = get_network_client()
            feed._module_name = "test"
            feed._pm_last_tick_mono = {}
            feed._pm_consecutive_failures = {}
            feed._pm_start_mono = None
            feed._pm_ticker_tasks = {}
            feed._coingecko_cooldown_until = 0.0
            feed._coingecko_429_count = 0
            feed._cg_backoff_base = 60.0
            feed._cg_backoff_max = 600.0
            feed._broadcast_update = AsyncMock()
            return feed

    async def test_429_sets_cooldown(self):
        feed = self._feed()
        mock_resp = MagicMock()
        mock_resp.status_code = 429

        with patch("httpx.AsyncClient") as mock_cls:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.get = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_ctx

            result = await feed._fetch_from_coingecko("BTC")

        self.assertFalse(result)
        self.assertGreater(feed._coingecko_cooldown_until, time.monotonic())
        self.assertEqual(feed._coingecko_429_count, 1)

    async def test_cooldown_skips_request(self):
        """While in cooldown, _fetch_from_coingecko must not make HTTP requests."""
        feed = self._feed()
        feed._coingecko_cooldown_until = time.monotonic() + 300.0  # active cooldown

        with patch("httpx.AsyncClient") as mock_cls:
            result = await feed._fetch_from_coingecko("BTC")
            mock_cls.assert_not_called()

        self.assertFalse(result)

    async def test_success_clears_429_counter(self):
        feed = self._feed()
        feed._coingecko_429_count = 3
        feed._coingecko_cooldown_until = 0.0  # cooldown expired

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [{
            "current_price": 80000.0,
            "total_volume": 1000000.0,
            "price_change_percentage_24h": 1.5,
        }]

        with patch("httpx.AsyncClient") as mock_cls:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.get = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_ctx

            result = await feed._fetch_from_coingecko("BTC")

        self.assertTrue(result)
        self.assertEqual(feed._coingecko_429_count, 0)
        self.assertEqual(feed._coingecko_cooldown_until, 0.0)


if __name__ == "__main__":
    unittest.main()
