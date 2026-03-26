"""test_sentiment_bus.py — Unit tests for SentimentBusV2 ingestion, context
builders, cache invalidation, FG regime logic, and HashtagAgent.generate_signals.

Strategy:
- Reset the SentimentBusV2 singleton before each test class.
- No mocks for pure methods (_fg_regime, generate_signals).
- Async methods (update_hashtags, update_news) are sync-compatible — called directly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from unittest.mock import patch

import pytest

from merid.sentiment.hashtag_agent import HashtagAgent, HashtagSentiment, _TagHistory
from merid.sentiment.news_ingestion_agent import AggregatedNewsSentiment
from merid.sentiment.sentiment_bus_v2 import (
    SentimentBusV2,
    _ScoreWindow,
    AssetSentimentContext,
    EventSentimentContext,
    HashtagContext,
    NewsContext,
    get_sentiment_bus_v2,
)


# ── Helpers ───────────────────────────────────────────────────────────────

def _reset_bus() -> SentimentBusV2:
    """Destroy and recreate the SentimentBusV2 singleton for test isolation."""
    SentimentBusV2._instance = None
    bus = SentimentBusV2()
    return bus


def _make_hashtag_sentiment(
    tag: str = "#BTC",
    score: float = 0.4,
    volume: int = 100,
    asset: Optional[str] = "BTC",
    event_id: Optional[str] = None,
    category: str = "crypto",
    provider: str = "twitter",
    confidence: float = 0.7,
) -> HashtagSentiment:
    return HashtagSentiment(
        tag=tag,
        score=score,
        volume=volume,
        category=category,
        asset=asset,
        event_id=event_id,
        provider=provider,
        timestamp=datetime.now(timezone.utc),
        confidence=confidence,
    )


def _make_agg_news(
    key: str = "crypto:BTC",
    category: str = "crypto",
    asset: Optional[str] = "BTC",
    event_id: Optional[str] = None,
    score: float = 0.3,
    confidence: float = 0.6,
    headline_count: int = 5,
    label: str = "positive",
) -> AggregatedNewsSentiment:
    return AggregatedNewsSentiment(
        key=key,
        category=category,
        asset=asset,
        event_id=event_id,
        score=score,
        confidence=confidence,
        headline_count=headline_count,
        provider_scores={"newsapi": score},
        label=label,
        timestamp=datetime.now(timezone.utc),
    )


# ═══════════════════════════════════════════════════════════════════════════
# §1  SentimentBusV2 singleton
# ═══════════════════════════════════════════════════════════════════════════

class TestSentimentBusV2Singleton:

    def test_singleton_same_instance(self):
        b1 = SentimentBusV2()
        b2 = SentimentBusV2()
        assert b1 is b2

    def test_get_sentiment_bus_v2_returns_instance(self):
        bus = get_sentiment_bus_v2()
        assert isinstance(bus, SentimentBusV2)

    def test_reset_creates_fresh_instance(self):
        b1 = SentimentBusV2()
        SentimentBusV2._instance = None
        b2 = SentimentBusV2()
        assert b1 is not b2


# ═══════════════════════════════════════════════════════════════════════════
# §2  _fg_regime — pure method, no mocks
# ═══════════════════════════════════════════════════════════════════════════

class TestFgRegime:

    def setup_method(self):
        self.bus = _reset_bus()

    def test_extreme_fear(self):
        assert self.bus._fg_regime(0) == "extreme_fear"
        assert self.bus._fg_regime(20) == "extreme_fear"

    def test_fear(self):
        assert self.bus._fg_regime(21) == "fear"
        assert self.bus._fg_regime(40) == "fear"

    def test_neutral(self):
        assert self.bus._fg_regime(41) == "neutral"
        assert self.bus._fg_regime(60) == "neutral"

    def test_greed(self):
        assert self.bus._fg_regime(61) == "greed"
        assert self.bus._fg_regime(80) == "greed"

    def test_extreme_greed(self):
        assert self.bus._fg_regime(81) == "extreme_greed"
        assert self.bus._fg_regime(100) == "extreme_greed"


# ═══════════════════════════════════════════════════════════════════════════
# §3  update_hashtags — ingestion, grouping, volume-weighted score
# ═══════════════════════════════════════════════════════════════════════════

class TestUpdateHashtags:

    def setup_method(self):
        self.bus = _reset_bus()

    def test_single_sentiment_creates_context(self):
        s = _make_hashtag_sentiment(asset="BTC", score=0.5, volume=100)
        self.bus.update_hashtags([s])
        assert "BTC" in self.bus._hashtag_contexts

    def test_volume_weighted_score(self):
        s1 = _make_hashtag_sentiment(tag="#BTC", asset="BTC", score=0.0, volume=1)
        s2 = _make_hashtag_sentiment(tag="#bitcoin", asset="BTC", score=1.0, volume=9)
        self.bus.update_hashtags([s1, s2])
        ctx = self.bus._hashtag_contexts["BTC"]
        # (0*1 + 1*9) / 10 = 0.9
        assert ctx.score == pytest.approx(0.9, abs=0.001)

    def test_direction_bullish(self):
        s = _make_hashtag_sentiment(asset="ETH", score=0.5, volume=100)
        self.bus.update_hashtags([s])
        assert self.bus._hashtag_contexts["ETH"].direction == "bullish"

    def test_direction_bearish(self):
        s = _make_hashtag_sentiment(asset="ETH", score=-0.5, volume=100)
        self.bus.update_hashtags([s])
        assert self.bus._hashtag_contexts["ETH"].direction == "bearish"

    def test_direction_neutral(self):
        s = _make_hashtag_sentiment(asset="SOL", score=0.05, volume=50)
        self.bus.update_hashtags([s])
        assert self.bus._hashtag_contexts["SOL"].direction == "neutral"

    def test_provider_breakdown_populated(self):
        s = _make_hashtag_sentiment(asset="BTC", provider="twitter", score=0.3, volume=50)
        self.bus.update_hashtags([s])
        ctx = self.bus._hashtag_contexts["BTC"]
        assert "twitter" in ctx.provider_scores

    def test_rolling_window_updated(self):
        s = _make_hashtag_sentiment(asset="BTC", score=0.4, volume=100)
        self.bus.update_hashtags([s])
        assert self.bus._hashtag_windows["BTC"].count == 1

    def test_asset_cache_invalidated(self):
        # Pre-populate cache
        self.bus._asset_cache["BTC"] = object()
        s = _make_hashtag_sentiment(asset="BTC", score=0.4, volume=100)
        self.bus.update_hashtags([s])
        assert "BTC" not in self.bus._asset_cache

    def test_event_cache_invalidated(self):
        self.bus._event_cache["EVT-001"] = object()
        s = _make_hashtag_sentiment(asset=None, event_id="EVT-001", score=0.2, volume=50)
        self.bus.update_hashtags([s])
        assert "EVT-001" not in self.bus._event_cache

    def test_empty_list_no_error(self):
        self.bus.update_hashtags([])

    def test_top_tags_excludes_reddit_prefix(self):
        s1 = _make_hashtag_sentiment(tag="reddit:r/bitcoin", asset="BTC", score=0.3, volume=10)
        s2 = _make_hashtag_sentiment(tag="#BTC", asset="BTC", score=0.3, volume=10)
        self.bus.update_hashtags([s1, s2])
        ctx = self.bus._hashtag_contexts["BTC"]
        assert "reddit:r/bitcoin" not in ctx.top_tags
        assert "#BTC" in ctx.top_tags


# ═══════════════════════════════════════════════════════════════════════════
# §4  update_news — ingestion, cache invalidation
# ═══════════════════════════════════════════════════════════════════════════

class TestUpdateNews:

    def setup_method(self):
        self.bus = _reset_bus()

    def test_news_context_created(self):
        agg = _make_agg_news(key="crypto:BTC", asset="BTC")
        self.bus.update_news([agg])
        assert "crypto:BTC" in self.bus._news_contexts

    def test_score_stored(self):
        agg = _make_agg_news(key="crypto:ETH", asset="ETH", score=-0.3)
        self.bus.update_news([agg])
        ctx = self.bus._news_contexts["crypto:ETH"]
        assert ctx.score == pytest.approx(-0.3, abs=0.001)

    def test_headline_count_stored(self):
        agg = _make_agg_news(key="crypto:BTC", asset="BTC", headline_count=12)
        self.bus.update_news([agg])
        assert self.bus._news_contexts["crypto:BTC"].headline_count == 12

    def test_asset_cache_invalidated(self):
        self.bus._asset_cache["BTC"] = object()
        agg = _make_agg_news(key="crypto:BTC", asset="BTC")
        self.bus.update_news([agg])
        assert "BTC" not in self.bus._asset_cache

    def test_event_cache_invalidated(self):
        self.bus._event_cache["EVT-002"] = object()
        agg = _make_agg_news(key="politics:EVT-002", event_id="EVT-002", asset=None)
        self.bus.update_news([agg])
        assert "EVT-002" not in self.bus._event_cache

    def test_rolling_window_updated(self):
        agg = _make_agg_news(key="crypto:BTC", asset="BTC", score=0.5, headline_count=3)
        self.bus.update_news([agg])
        assert self.bus._news_windows["crypto:BTC"].count == 1

    def test_empty_list_no_error(self):
        self.bus.update_news([])


# ═══════════════════════════════════════════════════════════════════════════
# §5  get_asset_context — blending, caching, FG overlay
# ═══════════════════════════════════════════════════════════════════════════

class TestGetAssetContext:

    def setup_method(self):
        self.bus = _reset_bus()

    def _patch_fg(self, value: int = 50):
        return patch.object(self.bus, "_get_fg", return_value=(value, False))

    def _patch_social(self, score: float = 0.0, conf: float = 0.5):
        return patch.object(self.bus, "_get_social_score", return_value=(score, conf))

    def test_returns_asset_sentiment_context(self):
        with self._patch_fg(), self._patch_social():
            ctx = self.bus.get_asset_context("BTC")
        assert isinstance(ctx, AssetSentimentContext)
        assert ctx.asset == "BTC"

    def test_fg_regime_set(self):
        with self._patch_fg(25), self._patch_social():
            ctx = self.bus.get_asset_context("BTC")
        assert ctx.fg_regime == "fear"
        assert ctx.fg_index == 25

    def test_news_score_incorporated(self):
        agg = _make_agg_news(key="crypto:BTC", asset="BTC", score=0.8)
        self.bus.update_news([agg])
        with self._patch_fg(50), self._patch_social(0.0, 0.5):
            ctx = self.bus.get_asset_context("BTC")
        # news_score should be 0.8
        assert ctx.news_score == pytest.approx(0.8, abs=0.001)

    def test_hashtag_score_incorporated(self):
        s = _make_hashtag_sentiment(asset="ETH", score=0.6, volume=100)
        self.bus.update_hashtags([s])
        with self._patch_fg(50), self._patch_social(0.0, 0.5):
            ctx = self.bus.get_asset_context("ETH")
        assert ctx.hashtag_score == pytest.approx(0.6, abs=0.001)

    def test_result_cached(self):
        with self._patch_fg(), self._patch_social():
            ctx1 = self.bus.get_asset_context("BTC")
            ctx2 = self.bus.get_asset_context("BTC")
        assert ctx1 is ctx2

    def test_cache_invalidated_by_update_hashtags(self):
        with self._patch_fg(), self._patch_social():
            ctx1 = self.bus.get_asset_context("BTC")
        s = _make_hashtag_sentiment(asset="BTC", score=0.9, volume=200)
        self.bus.update_hashtags([s])
        with self._patch_fg(), self._patch_social():
            ctx2 = self.bus.get_asset_context("BTC")
        assert ctx1 is not ctx2

    def test_cache_invalidated_by_update_news(self):
        with self._patch_fg(), self._patch_social():
            ctx1 = self.bus.get_asset_context("BTC")
        agg = _make_agg_news(key="crypto:BTC", asset="BTC", score=0.5)
        self.bus.update_news([agg])
        with self._patch_fg(), self._patch_social():
            ctx2 = self.bus.get_asset_context("BTC")
        assert ctx1 is not ctx2

    def test_fg_extreme_fear_regime(self):
        with self._patch_fg(10), self._patch_social():
            ctx = self.bus.get_asset_context("BTC")
        assert ctx.fg_regime == "extreme_fear"
        assert ctx.should_reduce_size() is True

    def test_fg_extreme_greed_regime(self):
        with self._patch_fg(90), self._patch_social():
            ctx = self.bus.get_asset_context("BTC")
        assert ctx.fg_regime == "extreme_greed"
        assert ctx.should_reduce_size() is True

    def test_is_contrarian_bullish_in_fear(self):
        """Strong positive hashtag + extreme fear → contrarian."""
        s = _make_hashtag_sentiment(asset="BTC", score=0.8, volume=200)
        self.bus.update_hashtags([s])
        agg = _make_agg_news(key="crypto:BTC", asset="BTC", score=0.8)
        self.bus.update_news([agg])
        with self._patch_fg(10), self._patch_social(0.8, 0.8):
            ctx = self.bus.get_asset_context("BTC")
        assert ctx.is_contrarian() is True

    def test_is_contrarian_bearish_in_greed(self):
        """Strong negative sentiment + extreme greed → contrarian."""
        s = _make_hashtag_sentiment(asset="BTC", score=-0.8, volume=200)
        self.bus.update_hashtags([s])
        agg = _make_agg_news(key="crypto:BTC", asset="BTC", score=-0.8)
        self.bus.update_news([agg])
        with self._patch_fg(90), self._patch_social(-0.8, 0.8):
            ctx = self.bus.get_asset_context("BTC")
        assert ctx.is_contrarian() is True

    def test_not_contrarian_aligned_sentiment(self):
        """Positive sentiment + greed = aligned, not contrarian."""
        s = _make_hashtag_sentiment(asset="BTC", score=0.5, volume=100)
        self.bus.update_hashtags([s])
        with self._patch_fg(75), self._patch_social(0.5, 0.7):
            ctx = self.bus.get_asset_context("BTC")
        assert ctx.is_contrarian() is False

    def test_to_dict_has_required_keys(self):
        with self._patch_fg(), self._patch_social():
            ctx = self.bus.get_asset_context("BTC")
        d = ctx.to_dict()
        for key in ("asset", "fg_index", "fg_regime", "combined_score", "confidence",
                    "should_reduce_size", "is_contrarian", "kalshi_prob_adjustment"):
            assert key in d, f"Missing key: {key}"


# ═══════════════════════════════════════════════════════════════════════════
# §6  get_event_context — news + hashtag blend, fallback, caching
# ═══════════════════════════════════════════════════════════════════════════

class TestGetEventContext:

    def setup_method(self):
        self.bus = _reset_bus()

    def test_returns_event_sentiment_context(self):
        ctx = self.bus.get_event_context("EVT-001", category="politics")
        assert isinstance(ctx, EventSentimentContext)
        assert ctx.event_id == "EVT-001"

    def test_zero_scores_when_no_data(self):
        ctx = self.bus.get_event_context("EVT-EMPTY", category="politics")
        assert ctx.combined_score == pytest.approx(0.0)

    def test_news_score_used(self):
        agg = _make_agg_news(key="politics:EVT-001", event_id="EVT-001",
                             asset=None, score=0.6, category="politics")
        self.bus.update_news([agg])
        ctx = self.bus.get_event_context("EVT-001", category="politics")
        assert ctx.news_score == pytest.approx(0.6, abs=0.001)

    def test_hashtag_score_used(self):
        s = _make_hashtag_sentiment(tag="#EVT", asset=None, event_id="EVT-002",
                                    score=0.5, volume=80, category="politics")
        self.bus.update_hashtags([s])
        ctx = self.bus.get_event_context("EVT-002", category="politics")
        assert ctx.hashtag_score == pytest.approx(0.5, abs=0.001)

    def test_combined_is_50_50_blend(self):
        agg = _make_agg_news(key="politics:EVT-003", event_id="EVT-003",
                             asset=None, score=0.4, category="politics")
        self.bus.update_news([agg])
        s = _make_hashtag_sentiment(tag="#EVT3", asset=None, event_id="EVT-003",
                                    score=0.8, volume=100, category="politics")
        self.bus.update_hashtags([s])
        ctx = self.bus.get_event_context("EVT-003", category="politics")
        # 0.5*0.4 + 0.5*0.8 = 0.6
        assert ctx.combined_score == pytest.approx(0.6, abs=0.01)

    def test_label_positive(self):
        agg = _make_agg_news(key="politics:EVT-004", event_id="EVT-004",
                             asset=None, score=0.5, category="politics")
        self.bus.update_news([agg])
        ctx = self.bus.get_event_context("EVT-004", category="politics")
        assert ctx.label == "positive"

    def test_label_negative(self):
        agg = _make_agg_news(key="politics:EVT-005", event_id="EVT-005",
                             asset=None, score=-0.5, category="politics")
        self.bus.update_news([agg])
        ctx = self.bus.get_event_context("EVT-005", category="politics")
        assert ctx.label == "negative"

    def test_label_neutral(self):
        ctx = self.bus.get_event_context("EVT-NEUTRAL", category="politics")
        assert ctx.label == "neutral"

    def test_result_cached(self):
        ctx1 = self.bus.get_event_context("EVT-CACHE", category="politics")
        ctx2 = self.bus.get_event_context("EVT-CACHE", category="politics")
        assert ctx1 is ctx2

    def test_fallback_to_asset_hashtag(self):
        """If no event hashtag, fall back to asset hashtag context."""
        s = _make_hashtag_sentiment(asset="BTC", score=0.7, volume=100)
        self.bus.update_hashtags([s])
        ctx = self.bus.get_event_context("EVT-BTC", category="crypto", asset="BTC")
        assert ctx.hashtag_score == pytest.approx(0.7, abs=0.001)

    def test_to_dict_has_required_keys(self):
        ctx = self.bus.get_event_context("EVT-DICT", category="politics")
        d = ctx.to_dict()
        for key in ("event_id", "category", "combined_score", "confidence",
                    "label", "headline_count"):
            assert key in d, f"Missing key: {key}"


# ═══════════════════════════════════════════════════════════════════════════
# §7  HashtagAgent.generate_signals — pure logic, no network
# ═══════════════════════════════════════════════════════════════════════════

class TestGenerateSignals:

    def setup_method(self):
        # Fresh agent with empty history
        HashtagAgent._instance = None  # type: ignore[attr-defined]
        self.agent = HashtagAgent()

    def _sentiments(self, asset: str, score: float, volume: int,
                    tag: str = "#TEST", category: str = "crypto") -> list:
        return [HashtagSentiment(
            tag=tag, score=score, volume=volume, category=category,
            asset=asset, event_id=None, provider="twitter",
            timestamp=datetime.now(timezone.utc),
            confidence=min(1.0, volume / 100.0),
        )]

    def test_no_signals_for_weak_score_no_spike(self):
        sents = self._sentiments("BTC", score=0.03, volume=10)
        signals = self.agent.generate_signals(sents)
        assert signals == []

    def test_bullish_signal_strong_score(self):
        sents = self._sentiments("BTC", score=0.5, volume=100)
        signals = self.agent.generate_signals(sents, score_threshold=0.25)
        assert len(signals) == 1
        assert signals[0].direction == "bullish"

    def test_bearish_signal_strong_score(self):
        sents = self._sentiments("ETH", score=-0.5, volume=100)
        signals = self.agent.generate_signals(sents, score_threshold=0.25)
        assert len(signals) == 1
        assert signals[0].direction == "bearish"

    def test_signal_strength_bounded_0_1(self):
        sents = self._sentiments("BTC", score=0.9, volume=100)
        signals = self.agent.generate_signals(sents)
        assert 0.0 <= signals[0].strength <= 1.0

    def test_volume_spike_detected(self):
        """Pre-populate history so current volume is a spike."""
        tag = "#BTC"
        for _ in range(5):
            self.agent._history_push(tag, 0.1, 10)  # avg_volume = 10
        sents = [HashtagSentiment(
            tag=tag, score=0.1, volume=30,  # 3x avg → spike at threshold 2.5
            category="crypto", asset="BTC", event_id=None,
            provider="twitter", timestamp=datetime.now(timezone.utc),
            confidence=0.5,
        )]
        signals = self.agent.generate_signals(sents, volume_spike_threshold=2.5)
        assert len(signals) == 1
        assert "spike" in signals[0].reason

    def test_contrarian_bullish_vs_extreme_fear(self):
        sents = self._sentiments("BTC", score=0.5, volume=100)
        signals = self.agent.generate_signals(sents, fg_index=15)
        assert signals[0].direction == "contrarian"
        assert "fear" in signals[0].reason

    def test_contrarian_bearish_vs_extreme_greed(self):
        sents = self._sentiments("BTC", score=-0.5, volume=100)
        signals = self.agent.generate_signals(sents, fg_index=85)
        assert signals[0].direction == "contrarian"
        assert "greed" in signals[0].reason

    def test_no_contrarian_when_fg_neutral(self):
        sents = self._sentiments("BTC", score=0.5, volume=100)
        signals = self.agent.generate_signals(sents, fg_index=50)
        assert signals[0].direction == "bullish"

    def test_signal_asset_or_event_set(self):
        sents = self._sentiments("SOL", score=0.4, volume=100)
        signals = self.agent.generate_signals(sents)
        assert signals[0].asset_or_event == "SOL"

    def test_signal_tags_populated(self):
        sents = self._sentiments("BTC", score=0.4, volume=100, tag="#bitcoin")
        signals = self.agent.generate_signals(sents)
        assert "#bitcoin" in signals[0].tags

    def test_zero_volume_skipped(self):
        sents = self._sentiments("BTC", score=0.9, volume=0)
        signals = self.agent.generate_signals(sents)
        assert signals == []

    def test_multiple_assets_multiple_signals(self):
        sents = (
            self._sentiments("BTC", score=0.5, volume=100)
            + self._sentiments("ETH", score=-0.5, volume=100, tag="#eth")
        )
        signals = self.agent.generate_signals(sents)
        assets = {s.asset_or_event for s in signals}
        assert "BTC" in assets
        assert "ETH" in assets


# ═══════════════════════════════════════════════════════════════════════════
# §8  AssetSentimentContext helpers
# ═══════════════════════════════════════════════════════════════════════════

class TestAssetSentimentContextHelpers:

    def _make_ctx(self, fg_index: int, combined_score: float) -> AssetSentimentContext:
        bus = _reset_bus()
        with patch.object(bus, "_get_fg", return_value=(fg_index, False)), \
             patch.object(bus, "_get_social_score", return_value=(combined_score, 0.7)):
            # Inject matching hashtag score so combined ≈ combined_score
            s = _make_hashtag_sentiment(asset="BTC", score=combined_score, volume=100)
            bus.update_hashtags([s])
            agg = _make_agg_news(key="crypto:BTC", asset="BTC", score=combined_score)
            bus.update_news([agg])
            return bus.get_asset_context("BTC")

    def test_kalshi_prob_adjustment_range(self):
        ctx = self._make_ctx(fg_index=50, combined_score=0.5)
        adj = ctx.kalshi_prob_adjustment()
        assert -0.1 <= adj <= 0.1

    def test_should_reduce_size_neutral_fg(self):
        ctx = self._make_ctx(fg_index=50, combined_score=0.0)
        assert ctx.should_reduce_size() is False

    def test_to_dict_roundtrip(self):
        ctx = self._make_ctx(fg_index=50, combined_score=0.2)
        d = ctx.to_dict()
        assert isinstance(d["timestamp"], str)
        assert isinstance(d["signals"], list)
        assert isinstance(d["top_tags"], list)
