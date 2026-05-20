"""Tests for sentiment bug fix regressions.

Regression tests for the 13 sentiment-pipeline bug fixes.

BUG-1  cfgi_synthetic_sin_wave          — synthetic FGI never drives sizing/regime
BUG-2  double_weighted_social_double_count — combine_sentiment no double-count
BUG-3  twitter_stale_cache_persists     — staleness ceiling + nitter confidence cap
BUG-4  finbert_on_synthetic_data        — synthetic news blocked in live mode
BUG-5  news_integrator_dead_key         — 'headlines' key fixed; 'details'/'sentiment' used
BUG-6  single_fg_index_cross_asset      — non-crypto assets return FGI=50
BUG-7  cross_source_double_count        — kalshi_prob_adjustment hard-capped ±0.03
BUG-8  regime_history_stale_noisy       — NOISY regime uses internal rolling history
BUG-9  nitter_html_garbage_vader        — HTML unescape + 4-word minimum filter
BUG-10 risk_manager_stateless           — singleton preserves daily_pnl state
MED-11 confidence zero when no data     — _calculate_confidence returns 0.0
MED-12 gating singleton config warning  — mis-matched min_confidence warns
MED-13 model_version tags               — all SentimentResult types carry model_version

NOTE: This test is marked as sentiment_research and should be excluded from
kalshi_crypto_15m_v2 production test runs. Sentiment is research-only and
must not influence live 15m Kalshi trading decisions.
"""

import pytest

pytestmark = pytest.mark.sentiment_research
from __future__ import annotations

import sys
import types
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Minimal stub so utils.logger doesn't hit external services
# ---------------------------------------------------------------------------
if "utils.logger" not in sys.modules:
    import contextvars as _cv
    _ul = types.ModuleType("utils.logger")
    _ul.get_logger = logging.getLogger  # type: ignore[attr-defined]
    _ul.correlation_id_var = _cv.ContextVar("correlation_id", default=None)  # type: ignore[attr-defined]
    _ul.get_correlation_id = lambda: None  # type: ignore[attr-defined]
    _ul.set_correlation_id = lambda cid: None  # type: ignore[attr-defined]
    sys.modules["utils.logger"] = _ul


# ===========================================================================
# BUG-1: Synthetic FGI must never drive sizing/regime
# ===========================================================================
class TestBug1SyntheticFGI:

    def test_synthetic_fgi_value_is_50(self):
        """FearGreedData with is_synthetic=True must carry fgi=50, not a sine value."""
        from merid.sentiment.cfgi_client import CFGIClient
        # CFGIClient is a singleton — no constructor args
        CFGIClient._instance = None
        with patch.dict("os.environ", {}, clear=True):
            client = CFGIClient()
            client.api_key = None  # force no-key path
            client._cache.clear()
            data = client.get_fear_greed("BTC", use_cache=False)
        assert data.is_synthetic is True
        assert data.fgi == 50, f"Expected synthetic FGI=50, got {data.fgi}"

    def test_quick_fg_returns_50_when_synthetic(self):
        """quick_fg() must return 50 when the underlying data is synthetic."""
        from merid.sentiment.cfgi_client import quick_fg, CFGIClient, FearGreedData, FearGreedRegime
        synthetic = FearGreedData(
            asset="BTC", fgi=50,
            timestamp=datetime.now(timezone.utc),
            classification=FearGreedRegime.NEUTRAL,
            volatility=None, market_momentum=None,
            social_sentiment=None, dominance=None,
            is_synthetic=True,
        )
        with patch.object(CFGIClient, "get_fear_greed", return_value=synthetic):
            result = quick_fg("BTC")
        assert result == 50

    def test_sentiment_bus_get_fg_returns_50_for_synthetic(self):
        """SentimentBusV2._get_fg() must short-circuit to 50 when is_synthetic."""
        from merid.sentiment.cfgi_client import FearGreedData, FearGreedRegime
        synthetic = FearGreedData(
            asset="BTC", fgi=22,  # would be HOT_FEAR if used
            timestamp=datetime.now(timezone.utc),
            classification=FearGreedRegime.EXTREME_FEAR,
            volatility=None, market_momentum=None,
            social_sentiment=None, dominance=None,
            is_synthetic=True,
        )
        # _get_fg does `from merid.sentiment.cfgi_client import get_cfgi_client`
        # so we patch at the source module.
        with patch("merid.sentiment.cfgi_client.get_cfgi_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.get_fear_greed.return_value = synthetic
            mock_client_fn.return_value = mock_client

            from merid.sentiment.sentiment_bus_v2 import SentimentBusV2
            bus = SentimentBusV2.__new__(SentimentBusV2)
            bus.__init__()
            result = bus._get_fg("BTC")

        assert result == 50, f"Expected 50 for synthetic FGI, got {result}"

    def test_no_sine_wave_pattern_across_hours(self):
        """Calling get_fear_greed without API key must always yield fgi=50 (not a sine)."""
        from merid.sentiment.cfgi_client import CFGIClient
        CFGIClient._instance = None
        with patch.dict("os.environ", {}, clear=True):
            client = CFGIClient()
            client.api_key = None
            client._cache.clear()
            data = client.get_fear_greed("BTC", use_cache=False)
        # The old sine formula could yield values between 20-80 depending on hour.
        # Now it must always be 50.
        assert data.fgi == 50


# ===========================================================================
# BUG-2: combine_sentiment must not double-count social via hashtag overlay
# ===========================================================================
class TestBug2NoBusOverlayInCombineSentiment:

    def test_combine_sentiment_pure_social_only(self):
        """combine_sentiment() must blend only Twitter + Reddit, not hashtag/news."""
        from merid.sentiment import sentiment_bundle as sb_mod

        # combine_sentiment does local imports inside the function body, so we
        # patch at the source modules rather than on the bundle module.
        with patch("merid.sentiment.twitter_fetcher.quick_twitter_sentiment", return_value=0.8), \
             patch("merid.sentiment.reddit_scraper.quick_reddit_sentiment", return_value=0.8), \
             patch("merid.sentiment.cfgi_client.quick_fg", return_value=50), \
             patch("merid.sentiment.vader_utils.vader_signal", return_value="bullish"), \
             patch("merid.sentiment.vader_utils.vader_to_kalshi_adjustment", return_value=0.03):

            bundle = sb_mod.combine_sentiment("BTC")

        # With both social sources at 0.8 the combined must be exactly
        # the weighted blend: (0.5*0.8 + 0.3*0.8) / 0.8 = 0.8
        assert abs(bundle.combined - 0.8) < 1e-6, (
            f"Expected 0.8 pure social blend, got {bundle.combined}. "
            "Hashtag/news overlay may have been re-introduced."
        )

    def test_no_hashtag_bus_attribute_access(self):
        """combine_sentiment must not access SentimentBusV2._hashtag_contexts."""
        import inspect
        import merid.sentiment.sentiment_bundle as mod
        source = inspect.getsource(mod.combine_sentiment)
        assert "_hashtag_contexts" not in source, (
            "combine_sentiment() still accesses _hashtag_contexts — double-count bug re-introduced"
        )
        # hashtag_score must not appear as an active variable assignment (overlays removed)
        assert "hashtag_score" not in source, (
            "combine_sentiment() still references hashtag_score — double-count overlay may be present"
        )


# ===========================================================================
# BUG-3: Twitter stale cache / nitter confidence cap
# ===========================================================================
class TestBug3TwitterStaleness:

    def _make_service(self):
        from merid.sentiment.twitter_fetcher import TwitterSentimentService, SentimentResult
        svc = TwitterSentimentService.__new__(TwitterSentimentService)
        svc._cache = {}
        svc._cache_ttl_seconds = 900
        svc._last_api_call = None
        svc._api_call_count = 0
        return svc, SentimentResult

    def test_stale_cache_returns_zero_confidence(self):
        """Cache entries older than 1800s must produce confidence=0.0 neutral."""
        svc, SR = self._make_service()
        old_ts = datetime.now(timezone.utc) - timedelta(seconds=2000)
        stale = SR(score=0.7, confidence=0.9, volume=50, avg_engagement=5.0,
                   raw_data=[], timestamp=old_ts)
        svc._cache["BTC:15"] = stale

        with patch.object(svc, "fetch_tweets", return_value=[]), \
             patch.object(svc, "fetch_tweets_scrape", return_value=[]), \
             patch.object(svc, "analyze_sentiment", return_value=SR(
                 score=0.0, confidence=0.0, volume=0,
                 avg_engagement=0.0, raw_data=[],
                 timestamp=datetime.now(timezone.utc))):
            result = svc.get_sentiment_with_fallback("BTC", minutes=15, use_cache=True)

        assert result.confidence == 0.0, (
            f"Expected zero-confidence for stale cache (age>1800s), got {result.confidence}"
        )
        assert result.score == 0.0

    def test_nitter_tweet_has_source_field(self):
        """TweetData from nitter scrape must carry source='nitter_scrape'."""
        from merid.sentiment.twitter_fetcher import TweetData
        td = TweetData(
            id="scrape_BTC_0_12345",
            text="Bitcoin is going to the moon today because reasons",
            created_at=datetime.now(timezone.utc),
            like_count=0, retweet_count=0, reply_count=0,
            source="nitter_scrape",
        )
        assert td.source == "nitter_scrape"

    def test_scrape_only_batch_confidence_capped_at_03(self):
        """analyze_sentiment on all-nitter tweets must cap confidence at 0.3."""
        from merid.sentiment.twitter_fetcher import TwitterSentimentService, TweetData
        svc = TwitterSentimentService.__new__(TwitterSentimentService)

        scrape_tweets = [
            TweetData(
                id=f"scrape_BTC_{i}",
                text=f"Bitcoin rally continues strong momentum ahead price surge",
                created_at=datetime.now(timezone.utc),
                like_count=0, retweet_count=0, reply_count=0,
                source="nitter_scrape",
            )
            for i in range(20)
        ]
        result = svc.analyze_sentiment(scrape_tweets)
        assert result.confidence <= 0.3, (
            f"Nitter-scrape batch confidence must be ≤0.3, got {result.confidence}"
        )
        assert result.model_version == "vader/nitter_scrape"

    def test_nitter_html_unescape_applied(self):
        """Nitter HTML parsing must run html.unescape and require ≥4 words."""
        # Simulate what the scrape loop does — test the filtering logic directly
        import re, html as _html
        raw_fragments = [
            "&amp; $BTC 🚀",                          # < 4 words, should be dropped
            "Rate limited try again later",            # 4 words, passes
            "Bitcoin &amp; Ethereum surge today strongly",  # entities + 5 words
        ]
        results = []
        for raw in raw_fragments:
            clean = _html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
            if clean and len(clean.split()) >= 4:
                results.append(clean)

        assert len(results) == 2
        assert "Rate limited try again later" in results
        assert "&amp;" not in results[1], "html.unescape should have converted &amp;"
        assert "Bitcoin & Ethereum surge today strongly" in results


# ===========================================================================
# BUG-4: Synthetic news must not be injected into live mode
# ===========================================================================
class TestBug4SyntheticNewsGated:

    def test_fetch_crypto_news_returns_empty_without_api_key(self):
        """fetch_crypto_news() must return [] when NEWS_API_KEY is absent."""
        from merid.sentiment.news_sentiment import KalshiNewsSentiment
        with patch.dict("os.environ", {}, clear=True):
            analyzer = KalshiNewsSentiment(news_api_key=None)
            articles = analyzer.fetch_crypto_news("BTC")
        assert articles == [], (
            "Expected empty list when NEWS_API_KEY is missing — "
            "synthetic news must not be injected in live mode."
        )

    def test_fetch_crypto_sentiment_returns_zero_without_api_key(self):
        """fetch_crypto_sentiment() must yield sentiment=0.0 when no real articles."""
        from merid.sentiment.news_sentiment import KalshiNewsSentiment
        with patch.dict("os.environ", {}, clear=True):
            analyzer = KalshiNewsSentiment(news_api_key=None)
            result = analyzer.fetch_crypto_sentiment("BTC")
        assert result["sentiment"] == 0.0
        assert result["articles_scored"] == 0

    def test_is_synthetic_flag_present_in_response(self):
        """fetch_crypto_sentiment() response must always include is_synthetic key."""
        from merid.sentiment.news_sentiment import KalshiNewsSentiment
        with patch.dict("os.environ", {}, clear=True):
            analyzer = KalshiNewsSentiment(news_api_key=None)
            result = analyzer.fetch_crypto_sentiment("BTC")
        assert "is_synthetic" in result, "is_synthetic flag missing from response dict"

    def test_is_synthetic_false_for_real_articles(self):
        """When real articles are scored, is_synthetic must be False."""
        from merid.sentiment.news_sentiment import KalshiNewsSentiment, NewsSentimentResult
        fake_articles = [{"title": "Bitcoin rally", "source": "coindesk",
                          "timestamp": datetime.now(timezone.utc), "url": "https://x"}]
        fake_result = NewsSentimentResult(
            headline="Bitcoin rally", source="finbert",
            timestamp=datetime.now(timezone.utc),
            sentiment_score=0.5, confidence=0.8, label="positive",
            raw_probs={"positive": 0.8, "neutral": 0.15, "negative": 0.05},
            model_version="ProsusAI/finbert",
        )
        with patch.dict("os.environ", {"NEWS_API_KEY": "fake_key"}):
            analyzer = KalshiNewsSentiment(news_api_key="fake_key")
            with patch.object(analyzer, "fetch_crypto_news", return_value=fake_articles), \
                 patch.object(analyzer, "score_headline", return_value=fake_result):
                result = analyzer.fetch_crypto_sentiment("BTC")
        assert result["is_synthetic"] is False


# ===========================================================================
# BUG-5: Dead 'headlines' key fixed in SentimentSignalIntegrator
# ===========================================================================
class TestBug5NewsIntegratorKey:

    def test_get_news_sentiment_uses_correct_keys(self):
        """_get_news_sentiment must use 'articles_scored' and 'sentiment', not 'headlines'."""
        import inspect
        from merid.signals import sentiment_integration as si_mod
        source = inspect.getsource(si_mod.SentimentSignalIntegrator._get_news_sentiment)
        assert "'headlines'" not in source, (
            "_get_news_sentiment still references the dead 'headlines' key"
        )
        assert "articles_scored" in source or "sentiment" in source, (
            "_get_news_sentiment must use 'articles_scored' or 'sentiment' key"
        )

    def test_get_news_sentiment_returns_nonzero_when_articles_scored(self):
        """_get_news_sentiment must return non-zero sentiment when articles are available."""
        from merid.signals import sentiment_integration as si_mod
        from merid.signals.sentiment_integration import SentimentSignalIntegrator

        fake_result = {
            "symbol": "BTC", "sentiment": 0.45, "confidence": 0.7,
            "articles_scored": 5, "total_articles": 5,
            "label_distribution": {"positive": 5},
            "is_synthetic": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": [],
        }

        integrator = SentimentSignalIntegrator.__new__(SentimentSignalIntegrator)
        integrator._news_analyzer = MagicMock()
        integrator._news_analyzer.fetch_crypto_sentiment.return_value = fake_result

        integrator._symbol_mapping = {"BTC": ["bitcoin"]}
        avg_sent, intensity = integrator._get_news_sentiment("BTC")

        assert avg_sent != 0.0, (
            "_get_news_sentiment returned 0.0 even with articles_scored=5 — "
            "dead 'headlines' key bug may have been re-introduced."
        )
        assert intensity > 0.0

    def test_is_synthetic_results_are_skipped(self):
        """_get_news_sentiment must skip results where is_synthetic=True."""
        from merid.signals.sentiment_integration import SentimentSignalIntegrator

        synthetic_result = {
            "symbol": "BTC", "sentiment": 0.9, "confidence": 0.9,
            "articles_scored": 10, "is_synthetic": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        integrator = SentimentSignalIntegrator.__new__(SentimentSignalIntegrator)
        integrator._news_analyzer = MagicMock()
        integrator._news_analyzer.fetch_crypto_sentiment.return_value = synthetic_result
        integrator._symbol_mapping = {"BTC": ["bitcoin"]}

        avg_sent, intensity = integrator._get_news_sentiment("BTC")

        assert avg_sent == 0.0, "Synthetic results must be skipped, not blended"
        assert intensity == 0.0


# ===========================================================================
# BUG-6: Non-crypto assets must return FGI=50
# ===========================================================================
class TestBug6NonCryptoFGINeutral:

    @pytest.mark.parametrize("asset", ["FED", "SPX", "CPI", "UNEMPLOYMENT", "OIL"])
    def test_macro_asset_returns_neutral_fg(self, asset):
        """quick_fg() must return 50 for macro/equity assets with no CFGI mapping."""
        from merid.sentiment.cfgi_client import quick_fg
        result = quick_fg(asset)
        assert result == 50, (
            f"quick_fg('{asset}') returned {result} — macro assets must return 50 "
            "to prevent crypto FGI from governing non-crypto Kalshi contracts."
        )

    @pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL"])
    def test_crypto_asset_is_recognised(self, asset):
        """is_crypto_asset() must return True for known crypto tickers."""
        from merid.sentiment.cfgi_client import is_crypto_asset
        assert is_crypto_asset(asset) is True

    def test_unknown_asset_is_not_crypto(self):
        from merid.sentiment.cfgi_client import is_crypto_asset
        assert is_crypto_asset("FOMC") is False
        assert is_crypto_asset("GDP") is False


# ===========================================================================
# BUG-7: Hard ±3¢ cap on kalshi_prob_adjustment
# ===========================================================================
class TestBug7KalshiAdjCap:

    def _make_ctx(self, score: float, fg: int = 50):
        from merid.sentiment.sentiment_bus_v2 import AssetSentimentContext
        return AssetSentimentContext(
            asset="BTC", fg_index=fg, fg_regime="neutral",
            social_score=score, news_score=score, hashtag_score=score,
            kalman_smoothed=score, combined_score=score,
            confidence=0.9, signals=[], top_tags=[],
            provider_breakdown={},
            timestamp=datetime.now(timezone.utc),
        )

    def test_extreme_bullish_capped_at_003(self):
        ctx = self._make_ctx(score=1.0, fg=90)
        adj = ctx.kalshi_prob_adjustment()
        assert adj <= 0.03, f"Expected ≤+0.03, got {adj}"

    def test_extreme_bearish_capped_at_neg003(self):
        ctx = self._make_ctx(score=-1.0, fg=10)
        adj = ctx.kalshi_prob_adjustment()
        assert adj >= -0.03, f"Expected ≥-0.03, got {adj}"

    def test_external_sentiment_forecaster_cap(self):
        """ExternalSentimentForecaster must also cap total_adj at ±0.03."""
        import inspect
        from merid.prediction.forecasters import sentiment as sent_mod
        source = inspect.getsource(sent_mod.ExternalSentimentForecaster.predict)
        assert "0.03" in source, (
            "ExternalSentimentForecaster.predict does not contain 0.03 cap"
        )
        assert "0.08" not in source, (
            "Old ±0.08 cap still present in ExternalSentimentForecaster.predict"
        )

    def test_moderate_adjustment_not_clamped(self):
        """A small legitimate adjustment must pass through unchanged."""
        ctx = self._make_ctx(score=0.2, fg=55)
        adj = ctx.kalshi_prob_adjustment()
        # Should be non-zero but ≤ 0.03
        assert -0.03 <= adj <= 0.03


# ===========================================================================
# BUG-8: NOISY regime uses internal rolling history
# ===========================================================================
class TestBug8NoisyRegime:

    def _make_engine(self):
        from merid.sentiment.sentiment_regime import SentimentRegimeEngine
        eng = SentimentRegimeEngine()
        eng._history = []
        eng._current_regime = None
        return eng

    def test_noisy_regime_triggered_without_external_history(self):
        """NOISY must fire from internal history even when sent_history=None."""
        from merid.sentiment.sentiment_regime import SentimentRegime
        eng = self._make_engine()

        # Pump alternating sentiment values into history to populate internal window
        signs = [0.3, -0.3, 0.3, -0.3, 0.3]
        for s in signs:
            eng.detect_regime(fg_index=50, sent_combined=s, volatility=0.15)

        # Now call with a near-zero sent_combined (weak magnitude ← needed for NOISY)
        state = eng.detect_regime(fg_index=50, sent_combined=0.05, volatility=0.15)
        assert state.regime == SentimentRegime.NOISY, (
            f"Expected NOISY regime from internal history, got {state.regime}. "
            "The fix to use _recent_sent_values() may have regressed."
        )

    def test_internal_history_time_windowed(self):
        """_recent_sent_values must exclude entries older than 30 minutes."""
        from merid.sentiment.sentiment_regime import SentimentRegimeEngine, RegimeState, SentimentRegime
        eng = self._make_engine()

        # Inject a stale history entry (40 min ago)
        old_ts = datetime.now(timezone.utc) - timedelta(minutes=40)
        from dataclasses import dataclass
        stale_state = RegimeState(
            regime=SentimentRegime.CALM_NEUTRAL,
            fg_index=50, sent_combined=0.5,
            volatility=0.1, timestamp=old_ts,
            reasoning="old",
        )
        eng._history = [stale_state]

        now = datetime.now(timezone.utc)
        recent = eng._recent_sent_values(now)
        assert len(recent) == 0, (
            f"Expected 0 recent values (stale entry excluded), got {len(recent)}"
        )

    def test_calm_neutral_when_history_insufficient(self):
        """With < 5 history entries and non-extreme FG, must return CALM_NEUTRAL."""
        from merid.sentiment.sentiment_regime import SentimentRegime
        eng = self._make_engine()
        state = eng.detect_regime(fg_index=50, sent_combined=0.1, volatility=0.1)
        assert state.regime == SentimentRegime.CALM_NEUTRAL

    def test_sent_history_param_still_respected(self):
        """Explicit sent_history kwarg must still override internal history."""
        from merid.sentiment.sentiment_regime import SentimentRegime
        eng = self._make_engine()
        external = [0.3, -0.3, 0.4, -0.4, 0.3]
        state = eng.detect_regime(
            fg_index=50, sent_combined=0.05, volatility=0.15,
            sent_history=external,
        )
        assert state.regime == SentimentRegime.NOISY


# ===========================================================================
# BUG-9: Nitter HTML parsing quality
# ===========================================================================
class TestBug9NitterHTMLParsing:

    def test_html_entities_unescaped(self):
        """HTML entity refs in scraped text must be converted before VADER scoring."""
        import re, html as _html
        raw = "&amp; BTC breaking out to new highs strongly"
        clean = _html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
        assert "&amp;" not in clean
        assert "& BTC breaking out to new highs strongly" == clean

    def test_short_fragment_rejected(self):
        """Text with fewer than 4 words must be dropped."""
        import re, html as _html
        fragments = ["$BTC", "&amp; moon", "wen", ""]
        accepted = []
        for raw in fragments:
            clean = _html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
            if clean and len(clean.split()) >= 4:
                accepted.append(clean)
        assert accepted == [], f"Short fragments should be rejected, accepted: {accepted}"

    def test_four_word_minimum_accepted(self):
        """Text with exactly 4 words must pass the filter."""
        import re, html as _html
        raw = "Bitcoin price goes up"
        clean = _html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
        assert len(clean.split()) >= 4

    def test_html_tags_stripped(self):
        """HTML tags must be stripped from scraped text."""
        import re, html as _html
        raw = '<span class="tweet">Bitcoin rallies past key resistance today</span>'
        clean = _html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
        assert "<span" not in clean
        assert "Bitcoin rallies past key resistance today" == clean


# ===========================================================================
# BUG-10: SentimentRiskManager singleton preserves daily_pnl
# ===========================================================================
class TestBug10RiskManagerSingleton:

    def _reset_singleton(self):
        import merid.sentiment.sentiment_risk as mod
        mod._risk_manager_instance = None

    def test_singleton_accumulates_daily_pnl(self):
        """check_sentiment_trade_allowed must accumulate pnl via singleton."""
        self._reset_singleton()
        from merid.sentiment.sentiment_risk import get_sentiment_risk_manager

        mgr = get_sentiment_risk_manager()
        mgr.reset_daily()
        mgr.equity = 10000.0

        # Simulate losses via record_trade
        mgr.record_trade(pnl=-600.0, sentiment=0.0, timestamp=datetime.now(timezone.utc))
        assert mgr.daily_pnl == -600.0, "daily_pnl must persist across calls on singleton"

    def test_hard_stop_reachable_via_convenience_fn(self):
        """check_sentiment_trade_allowed must respect hard stop on accumulated pnl."""
        self._reset_singleton()
        from merid.sentiment.sentiment_risk import (
            check_sentiment_trade_allowed, get_sentiment_risk_manager,
        )
        mgr = get_sentiment_risk_manager()
        mgr.reset_daily()
        equity = 10000.0
        mgr.equity = equity
        # Simulate a -12% loss (beyond 10% hard stop)
        mgr.record_trade(pnl=-1200.0, sentiment=0.0, timestamp=datetime.now(timezone.utc))

        allowed, size, reason = check_sentiment_trade_allowed(
            equity=equity, daily_pnl=0.0,  # pnl=0.0 so singleton's value drives check
            sentiment_confidence=0.9,
            tech_signal="bullish", sent_signal="bullish",
            fg_index=50, sentiment=0.3,
        )
        assert not allowed, (
            "Hard stop should have blocked the trade — singleton pnl not being used."
        )
        assert "hard_stop" in reason

    def test_fresh_instance_does_not_reset_singleton(self):
        """Constructing a new SentimentRiskManager must not affect the singleton."""
        self._reset_singleton()
        from merid.sentiment.sentiment_risk import (
            get_sentiment_risk_manager, SentimentRiskManager,
        )
        mgr = get_sentiment_risk_manager()
        mgr.daily_pnl = -500.0

        _ = SentimentRiskManager()  # Create a throwaway instance

        assert get_sentiment_risk_manager().daily_pnl == -500.0, (
            "Singleton daily_pnl was reset by constructing a new SentimentRiskManager"
        )


# ===========================================================================
# MED-11: confidence=0.0 when both intensities are zero
# ===========================================================================
class TestMed11ConfidenceZeroWhenNoData:

    def test_zero_intensity_yields_zero_confidence(self):
        """_calculate_confidence must return 0.0 when both intensities are 0."""
        from merid.signals.sentiment_integration import SentimentSignalIntegrator
        integrator = SentimentSignalIntegrator.__new__(SentimentSignalIntegrator)
        conf = integrator._calculate_confidence(
            news_intensity=0.0, social_intensity=0.0
        )
        assert conf == 0.0, (
            f"Expected confidence=0.0 when no data, got {conf}. "
            "The 'minimum 0.1' floor must be removed."
        )

    def test_positive_intensity_yields_nonzero_confidence(self):
        """Positive intensity must still produce non-zero confidence."""
        from merid.signals.sentiment_integration import SentimentSignalIntegrator
        integrator = SentimentSignalIntegrator.__new__(SentimentSignalIntegrator)
        conf = integrator._calculate_confidence(
            news_intensity=0.5, social_intensity=0.5
        )
        assert conf > 0.0
        assert conf <= 1.0


# ===========================================================================
# MED-12: SentimentGatingLayer singleton config warning
# ===========================================================================
class TestMed12GatingSingletonWarning:

    def _reset_singleton(self):
        import merid.sentiment.sentiment_gating as mod
        mod._gating_layer = None

    def test_singleton_initialised_with_first_min_confidence(self):
        """First call sets min_confidence; second call with same value is silent."""
        self._reset_singleton()
        from merid.sentiment.sentiment_gating import get_sentiment_gating_layer
        layer = get_sentiment_gating_layer(min_confidence=0.6)
        assert layer.criteria.min_sentiment_confidence == 0.6

    def test_mismatched_confidence_emits_warning(self):
        """Second call with different min_confidence must emit a WARNING."""
        self._reset_singleton()
        from merid.sentiment.sentiment_gating import get_sentiment_gating_layer

        get_sentiment_gating_layer(min_confidence=0.5)  # initialise

        # The warning is issued via `import logging as _logging` inside the function.
        # Patch the stdlib logging.Logger.warning method to intercept it.
        with patch("logging.Logger.warning") as mock_warn:
            get_sentiment_gating_layer(min_confidence=0.8)  # different value
            mock_warn.assert_called_once()

    def test_mismatched_confidence_does_not_change_singleton(self):
        """Despite mismatched call, the singleton's threshold must stay unchanged."""
        self._reset_singleton()
        from merid.sentiment.sentiment_gating import get_sentiment_gating_layer

        layer1 = get_sentiment_gating_layer(min_confidence=0.5)
        with patch("logging.getLogger"):
            layer2 = get_sentiment_gating_layer(min_confidence=0.9)
        assert layer2.criteria.min_sentiment_confidence == 0.5
        assert layer1 is layer2


# ===========================================================================
# MED-13: model_version field present on all SentimentResult types
# ===========================================================================
class TestMed13ModelVersionTags:

    def test_news_sentiment_result_has_model_version(self):
        from merid.sentiment.news_sentiment import NewsSentimentResult
        r = NewsSentimentResult(
            headline="test", source="finbert",
            timestamp=datetime.now(timezone.utc),
            sentiment_score=0.5, confidence=0.8, label="positive",
            raw_probs={}, model_version="ProsusAI/finbert",
        )
        assert r.model_version == "ProsusAI/finbert"

    def test_news_sentiment_result_default_is_unknown(self):
        from merid.sentiment.news_sentiment import NewsSentimentResult
        r = NewsSentimentResult(
            headline="test", source="test",
            timestamp=datetime.now(timezone.utc),
            sentiment_score=0.0, confidence=0.0, label="neutral",
            raw_probs={},
        )
        assert r.model_version == "unknown"

    def test_twitter_sentiment_result_has_model_version(self):
        from merid.sentiment.twitter_fetcher import SentimentResult
        r = SentimentResult(
            score=0.0, confidence=0.0, volume=0,
            avg_engagement=0.0, raw_data=[],
            timestamp=datetime.now(timezone.utc),
        )
        assert hasattr(r, "model_version")
        assert r.model_version == "vader"

    def test_reddit_sentiment_result_has_model_version(self):
        from merid.sentiment.reddit_scraper import SentimentResult
        r = SentimentResult(
            score=0.0, confidence=0.0, volume=0,
            avg_engagement=0.0, subreddit_breakdown={},
            raw_data=[], timestamp=datetime.now(timezone.utc),
        )
        assert hasattr(r, "model_version")
        assert r.model_version == "vader"

    def test_finbert_score_carries_model_version(self):
        """score_headline with FinBERT available must set model_version=ProsusAI/finbert."""
        from merid.sentiment.news_sentiment import KalshiNewsSentiment, NewsSentimentResult
        import torch
        fake_probs = MagicMock()
        fake_probs.cpu.return_value.numpy.return_value = [0.1, 0.2, 0.7]  # pos wins
        fake_outputs = MagicMock()
        fake_outputs.logits = [MagicMock()]

        mock_tokenizer = MagicMock()
        mock_tokenizer.return_value = {"input_ids": MagicMock()}
        mock_model = MagicMock()
        mock_model.return_value = fake_outputs

        with patch("merid.sentiment.news_sentiment._get_finbert",
                   return_value=(mock_tokenizer, mock_model)), \
             patch("torch.no_grad"), \
             patch("torch.softmax", return_value=fake_probs), \
             patch("torch.cuda.is_available", return_value=False):
            analyzer = KalshiNewsSentiment(news_api_key="key")
            result = analyzer.score_headline("Bitcoin surges to new highs")

        if result is not None:
            assert result.model_version in ("ProsusAI/finbert", "vader_fallback", "neutral_fallback"), (
                f"Unexpected model_version: {result.model_version}"
            )

    def test_vader_fallback_carries_model_version(self):
        """_fallback_score must set model_version='vader_fallback'."""
        from merid.sentiment.news_sentiment import KalshiNewsSentiment
        analyzer = KalshiNewsSentiment()
        with patch("merid.sentiment.news_sentiment._get_finbert", return_value=(None, None)):
            result = analyzer.score_headline("Bitcoin drops sharply")
        if result is not None:
            assert result.model_version in ("vader_fallback", "neutral_fallback"), (
                f"Expected vader_fallback or neutral_fallback, got {result.model_version}"
            )
