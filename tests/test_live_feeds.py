"""Tests for the live feed manager — verifies API wiring, ingestion, and fallbacks.

Tests mock HTTP responses to avoid hitting real APIs during CI.
"""

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from merid.signals.features import FeatureService, FeatureSet
from merid.signals.live_feeds import LiveFeedManager


def run_async(coro):
    """Helper to run async code in sync tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestHeadlineSentiment(unittest.TestCase):
    """Test keyword-based sentiment scoring."""

    def test_positive_headline(self):
        score = LiveFeedManager._headline_sentiment("Stock surges on strong earnings beat")
        self.assertGreater(score, 0)

    def test_negative_headline(self):
        score = LiveFeedManager._headline_sentiment("Market crashes amid bankruptcy fears")
        self.assertLess(score, 0)

    def test_neutral_headline(self):
        score = LiveFeedManager._headline_sentiment("Company announces quarterly results")
        self.assertEqual(score, 0.0)

    def test_mixed_headline(self):
        score = LiveFeedManager._headline_sentiment("Rally stalls as sell pressure drops")
        # Has both positive (rally) and negative (sell, drops) — should be close to 0
        self.assertGreaterEqual(score, -1.0)
        self.assertLessEqual(score, 1.0)

    def test_empty_headline(self):
        score = LiveFeedManager._headline_sentiment("")
        self.assertEqual(score, 0.0)

    def test_clamped_to_range(self):
        score = LiveFeedManager._headline_sentiment(
            "surge rally gain bullish beat exceed upgrade buy growth record soar jump"
        )
        self.assertLessEqual(score, 1.0)
        self.assertGreaterEqual(score, -1.0)


class TestPolygonTickerMapping(unittest.TestCase):
    """Test symbol to Polygon ticker mapping."""

    def test_crypto_symbol(self):
        self.assertEqual(LiveFeedManager._to_polygon_ticker("BTC"), "X:BTCUSD")
        self.assertEqual(LiveFeedManager._to_polygon_ticker("ETH"), "X:ETHUSD")

    def test_equity_symbol(self):
        self.assertEqual(LiveFeedManager._to_polygon_ticker("AAPL"), "AAPL")
        self.assertEqual(LiveFeedManager._to_polygon_ticker("SPY"), "SPY")

    def test_case_insensitive(self):
        self.assertEqual(LiveFeedManager._to_polygon_ticker("btc"), "X:BTCUSD")


class TestLiveFeedManagerInit(unittest.TestCase):
    """Test LiveFeedManager initialization."""

    def test_creates_with_feature_service(self):
        fs = FeatureService()
        mgr = LiveFeedManager(fs)
        self.assertIs(mgr._fs, fs)

    def test_stats_initialized(self):
        mgr = LiveFeedManager(FeatureService())
        stats = mgr.stats()
        self.assertEqual(stats["news_fetched"], 0)
        self.assertEqual(stats["errors"], 0)

    def test_should_fetch_respects_interval(self):
        mgr = LiveFeedManager(FeatureService())
        now = time.time()
        self.assertTrue(mgr._should_fetch("news", now))
        mgr._last_fetch["news"] = now
        self.assertFalse(mgr._should_fetch("news", now + 10))
        self.assertTrue(mgr._should_fetch("news", now + 60))


class TestFinnhubNews(unittest.TestCase):
    """Test Finnhub news fetching with mocked HTTP."""

    def test_finnhub_ingests_matching_articles(self):
        fs = FeatureService()
        mgr = LiveFeedManager(fs)
        mgr._finnhub_key = "test_key"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = [
            {
                "headline": "Bitcoin surges past 100k",
                "summary": "BTC rally continues",
                "datetime": time.time() - 60,
                "related": "BTC",
            },
            {
                "headline": "Ethereum upgrade boosts network",
                "summary": "ETH growth expected",
                "datetime": time.time() - 120,
                "related": "ETH",
            },
        ]

        with patch.object(mgr._client, "get", new_callable=AsyncMock, return_value=mock_response):
            run_async(mgr._fetch_finnhub_news(["BTC", "ETH"], time.time()))

        self.assertGreater(mgr._stats["news_fetched"], 0)
        # Verify data was ingested into the feature service
        btc_news = fs.news.get_news_features("BTC")
        self.assertEqual(btc_news.source, "live")

    def test_finnhub_handles_http_error(self):
        fs = FeatureService()
        mgr = LiveFeedManager(fs)
        mgr._finnhub_key = "test_key"

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Rate limited", request=MagicMock(), response=mock_response
        )

        with patch.object(mgr._client, "get", new_callable=AsyncMock, return_value=mock_response):
            run_async(mgr._fetch_finnhub_news(["BTC"], time.time()))

        self.assertEqual(mgr._stats["errors"], 1)

    def test_finnhub_handles_unexpected_response(self):
        fs = FeatureService()
        mgr = LiveFeedManager(fs)
        mgr._finnhub_key = "test_key"

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"error": "invalid token"}

        with patch.object(mgr._client, "get", new_callable=AsyncMock, return_value=mock_response):
            run_async(mgr._fetch_finnhub_news(["BTC"], time.time()))

        # Should not crash, just log warning
        self.assertEqual(mgr._stats["news_fetched"], 0)


class TestCoinGecko(unittest.TestCase):
    """Test CoinGecko on-chain data fetching."""

    def test_coingecko_ingests_market_data(self):
        fs = FeatureService()
        mgr = LiveFeedManager(fs)
        now = time.time()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = [
            {
                "id": "bitcoin",
                "current_price": 98500,
                "market_cap": 1900000000000,
                "total_volume": 35000000000,
                "price_change_percentage_1h_in_currency": 0.5,
                "price_change_percentage_24h": 2.1,
                "price_change_percentage_7d_in_currency": -1.3,
                "circulating_supply": 19500000,
                "ath_change_percentage": -2.5,
            },
        ]

        with patch.object(mgr._client, "get", new_callable=AsyncMock, return_value=mock_response):
            run_async(mgr._fetch_coingecko(["BTC"], now))

        self.assertEqual(mgr._stats["onchain_fetched"], 1)
        btc_onchain = fs.onchain.get_onchain_features("ethereum", "BTC", now=now)
        self.assertEqual(btc_onchain.source, "live")
        self.assertIn("price_usd", btc_onchain.features)

    def test_coingecko_skips_unknown_symbols(self):
        fs = FeatureService()
        mgr = LiveFeedManager(fs)

        # AAPL is not a crypto coin — should be skipped
        with patch.object(mgr._client, "get", new_callable=AsyncMock) as mock_get:
            run_async(mgr._fetch_coingecko(["AAPL"], time.time()))
            mock_get.assert_not_called()

    def test_coingecko_handles_error(self):
        fs = FeatureService()
        mgr = LiveFeedManager(fs)

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Rate limited", request=MagicMock(), response=mock_response
        )

        with patch.object(mgr._client, "get", new_callable=AsyncMock, return_value=mock_response):
            run_async(mgr._fetch_coingecko(["BTC"], time.time()))

        self.assertEqual(mgr._stats["errors"], 1)


class TestFredMacro(unittest.TestCase):
    """Test FRED macro data fetching."""

    def test_neutral_fallback_when_no_key(self):
        fs = FeatureService()
        mgr = LiveFeedManager(fs)

        with patch.dict("os.environ", {"FRED_API_KEY": ""}, clear=False):
            run_async(mgr._fetch_fred_macro(time.time()))

        self.assertEqual(mgr._stats["macro_fetched"], 7)  # 7 series with neutral values
        macro = fs.macro.get_macro_features()
        self.assertEqual(macro.source, "live")  # Data was ingested

    @patch.dict("os.environ", {"FRED_API_KEY": "test_fred_key"}, clear=False)
    def test_fred_fetches_with_key(self):
        fs = FeatureService()
        mgr = LiveFeedManager(fs)
        now = time.time()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "observations": [{"value": "3.2", "date": "2026-01-15"}]
        }

        with patch.object(mgr._client, "get", new_callable=AsyncMock, return_value=mock_response):
            run_async(mgr._fetch_fred_macro(now))

        self.assertGreater(mgr._stats["macro_fetched"], 0)


class TestRefreshAll(unittest.TestCase):
    """Test the top-level refresh_all method."""

    def test_refresh_all_calls_all_fetchers(self):
        fs = FeatureService()
        mgr = LiveFeedManager(fs)

        with patch.object(mgr, "refresh_news", new_callable=AsyncMock) as mock_news, \
             patch.object(mgr, "refresh_macro", new_callable=AsyncMock) as mock_macro, \
             patch.object(mgr, "refresh_onchain", new_callable=AsyncMock) as mock_onchain:
            run_async(mgr.refresh_all(["BTC", "ETH"]))
            mock_news.assert_called_once()
            mock_macro.assert_called_once()
            mock_onchain.assert_called_once()

    def test_refresh_skips_when_too_soon(self):
        fs = FeatureService()
        mgr = LiveFeedManager(fs)
        now = time.time()
        mgr._last_fetch["news"] = now
        mgr._last_fetch["macro"] = now
        mgr._last_fetch["onchain"] = now

        # Should skip all fetches since we just fetched
        with patch.object(mgr, "_fetch_finnhub_news", new_callable=AsyncMock) as mock_fn:
            run_async(mgr.refresh_news(["BTC"], now + 5))
            mock_fn.assert_not_called()


class TestNeutralFallbacks(unittest.TestCase):
    """Verify that synthetic fallbacks now return neutral data, not random."""

    def test_news_fallback_is_neutral(self):
        from merid.signals.features import NewsFeatureService
        svc = NewsFeatureService()
        now = time.time()
        fs = svc.get_news_features("UNKNOWN_SYM", now=now)
        self.assertEqual(fs.source, "synthetic")
        sent = fs.features["sentiment"]
        self.assertAlmostEqual(sent.value, 0.0)

    def test_macro_fallback_is_neutral(self):
        from merid.signals.features import MacroFeatureService
        svc = MacroFeatureService()
        now = time.time()
        fs = svc.get_macro_features(now=now)
        self.assertEqual(fs.source, "synthetic")
        surprise = fs.features["surprise_avg"]
        self.assertAlmostEqual(surprise.value, 0.0)

    def test_onchain_fallback_is_neutral(self):
        from merid.signals.features import OnChainFeatureService
        svc = OnChainFeatureService()
        now = time.time()
        fs = svc.get_onchain_features("ethereum", "NOTOKEN", now=now)
        self.assertEqual(fs.source, "synthetic")
        for name, env in fs.features.items():
            self.assertAlmostEqual(env.value, 0.0, msg=f"{name} should be 0.0")

    def test_social_fallback_is_neutral(self):
        from merid.signals.features import SocialFeatureService
        svc = SocialFeatureService()
        now = time.time()
        fs = svc.get_social_features("NOTOKEN", now=now)
        self.assertEqual(fs.source, "synthetic")
        sent = fs.features["sentiment"]
        self.assertAlmostEqual(sent.value, 0.0)


if __name__ == "__main__":
    unittest.main()
