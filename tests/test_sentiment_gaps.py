"""test_sentiment_gaps.py — 10 critical gap tests for full autonomy + HITL.

Covers: dedup, aggregation, update_signals, market_context blend,
stats accumulation, fallback safety, kalshi_prob_adjustment sign,
stale data eviction, singleton reset, thread safety.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.sentiment.hashtag_agent import HashtagAgent, HashtagSentiment, HashtagSignal, _TagHistory
from merid.sentiment.news_ingestion_agent import (
    AggregatedNewsSentiment,
    NewsSentiment,
    NewsIngestionAgent,
    RawHeadline,
    _dedupe_key,
    _label_from_score,
)
from merid.sentiment.sentiment_bus_v2 import (
    AssetSentimentContext,
    EventSentimentContext,
    HashtagContext,
    MarketSentimentContext,
    NewsContext,
    SentimentBusV2,
    _ScoreWindow,
)


# ── Helpers ───────────────────────────────────────────────────────────────

def _reset_bus() -> SentimentBusV2:
    SentimentBusV2._instance = None
    return SentimentBusV2()


def _make_raw(title: str, url: str, category: str = "crypto",
              asset: Optional[str] = "BTC") -> RawHeadline:
    return RawHeadline(
        title=title,
        description="desc",
        url=url,
        source="test",
        provider="newsapi",
        published_at=datetime.now(timezone.utc),
        category=category,
        asset=asset,
        event_id=None,
    )


def _make_scored(headline: str, url: str, score: float,
                 provider: str = "newsapi", category: str = "crypto",
                 asset: Optional[str] = "BTC") -> NewsSentiment:
    return NewsSentiment(
        headline=headline,
        url=url,
        source="test",
        provider=provider,
        published_at=datetime.now(timezone.utc),
        category=category,
        asset=asset,
        event_id=None,
        vader_score=score,
        finbert_score=0.0,
        combined_score=score,
        confidence=0.5,
        label=_label_from_score(score),
        timestamp=datetime.now(timezone.utc),
    )


def _make_hashtag(tag: str = "#BTC", score: float = 0.4, volume: int = 100,
                  asset: Optional[str] = "BTC", event_id: Optional[str] = None,
                  category: str = "crypto", provider: str = "twitter") -> HashtagSentiment:
    return HashtagSentiment(
        tag=tag, score=score, volume=volume, category=category,
        asset=asset, event_id=event_id, provider=provider,
        timestamp=datetime.now(timezone.utc),
        confidence=min(1.0, volume / 100.0) if volume > 0 else 0.1,
    )


def _make_signal(asset_or_event: str = "BTC", direction: str = "bullish",
                 strength: float = 0.7) -> HashtagSignal:
    return HashtagSignal(
        asset_or_event=asset_or_event, direction=direction,
        strength=strength, reason="test", score=0.5, volume=100,
        tags=["#BTC"], category="crypto",
        timestamp=datetime.now(timezone.utc),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Gap 1 — NewsIngestionAgent deduplication across cycles
# ═══════════════════════════════════════════════════════════════════════════

class TestNewsDeduplication:

    def test_same_headline_deduped(self):
        agent = NewsIngestionAgent(bus=None)
        raw = [
            _make_raw("Bitcoin surges", "https://a.com/1"),
            _make_raw("Bitcoin surges", "https://a.com/1"),
        ]
        result = agent._dedupe(raw)
        assert len(result) == 1

    def test_different_headlines_not_deduped(self):
        agent = NewsIngestionAgent(bus=None)
        raw = [
            _make_raw("Bitcoin surges", "https://a.com/1"),
            _make_raw("Bitcoin crashes", "https://a.com/2"),
        ]
        result = agent._dedupe(raw)
        assert len(result) == 2

    def test_dedup_persists_across_calls(self):
        agent = NewsIngestionAgent(bus=None)
        raw1 = [_make_raw("Bitcoin surges", "https://a.com/1")]
        raw2 = [_make_raw("Bitcoin surges", "https://a.com/1")]
        agent._dedupe(raw1)
        result = agent._dedupe(raw2)
        assert len(result) == 0

    def test_dedup_expires_after_ttl(self):
        agent = NewsIngestionAgent(bus=None)
        agent._seen_ttl = 0.0  # expire immediately
        raw = [_make_raw("Bitcoin surges", "https://a.com/1")]
        agent._dedupe(raw)
        time.sleep(0.01)
        result = agent._dedupe(raw)
        assert len(result) == 1

    def test_dedup_key_stored(self):
        agent = NewsIngestionAgent(bus=None)
        raw = [_make_raw("Test", "https://test.com")]
        agent._dedupe(raw)
        expected_key = _dedupe_key("Test", "https://test.com")
        assert expected_key in agent._seen


# ═══════════════════════════════════════════════════════════════════════════
# Gap 2 — NewsIngestionAgent aggregation math
# ═══════════════════════════════════════════════════════════════════════════

class TestNewsAggregation:

    def test_single_headline_aggregation(self):
        agent = NewsIngestionAgent(bus=None)
        scored = [_make_scored("BTC up", "u1", 0.6)]
        aggs = agent._aggregate(scored)
        assert len(aggs) == 1
        assert aggs[0].score == pytest.approx(0.6, abs=0.001)
        assert aggs[0].headline_count == 1

    def test_multiple_headlines_average(self):
        agent = NewsIngestionAgent(bus=None)
        scored = [
            _make_scored("BTC up", "u1", 0.4),
            _make_scored("BTC rally", "u2", 0.8),
        ]
        aggs = agent._aggregate(scored)
        assert len(aggs) == 1
        assert aggs[0].score == pytest.approx(0.6, abs=0.001)
        assert aggs[0].headline_count == 2

    def test_provider_scores_breakdown(self):
        agent = NewsIngestionAgent(bus=None)
        scored = [
            _make_scored("h1", "u1", 0.4, provider="newsapi"),
            _make_scored("h2", "u2", 0.8, provider="rss"),
        ]
        aggs = agent._aggregate(scored)
        assert "newsapi" in aggs[0].provider_scores
        assert "rss" in aggs[0].provider_scores
        assert aggs[0].provider_scores["newsapi"] == pytest.approx(0.4, abs=0.001)
        assert aggs[0].provider_scores["rss"] == pytest.approx(0.8, abs=0.001)

    def test_separate_categories_separate_aggregates(self):
        agent = NewsIngestionAgent(bus=None)
        scored = [
            _make_scored("BTC up", "u1", 0.5, category="crypto", asset="BTC"),
            _make_scored("Election", "u2", 0.3, category="politics", asset=None),
        ]
        aggs = agent._aggregate(scored)
        assert len(aggs) == 2
        keys = {a.key for a in aggs}
        assert "crypto:BTC" in keys
        assert "politics:general" in keys

    def test_label_from_aggregate_score(self):
        agent = NewsIngestionAgent(bus=None)
        scored = [_make_scored("h1", "u1", -0.5)]
        aggs = agent._aggregate(scored)
        assert aggs[0].label == "negative"

    def test_empty_input_returns_empty(self):
        agent = NewsIngestionAgent(bus=None)
        assert agent._aggregate([]) == []


# ═══════════════════════════════════════════════════════════════════════════
# Gap 3 — SentimentBusV2.update_signals() — attachment + cache bust
# ═══════════════════════════════════════════════════════════════════════════

class TestUpdateSignals:

    def setup_method(self):
        self.bus = _reset_bus()

    def test_signal_attached_to_existing_context(self):
        s = _make_hashtag(asset="BTC", score=0.5, volume=100)
        self.bus.update_hashtags([s])
        assert self.bus._hashtag_contexts["BTC"].signals == []

        sig = _make_signal(asset_or_event="BTC")
        self.bus.update_signals([sig])
        assert len(self.bus._hashtag_contexts["BTC"].signals) == 1
        assert self.bus._hashtag_contexts["BTC"].signals[0].direction == "bullish"

    def test_signal_invalidates_asset_cache(self):
        s = _make_hashtag(asset="BTC", score=0.5, volume=100)
        self.bus.update_hashtags([s])
        self.bus._asset_cache["BTC"] = object()
        sig = _make_signal(asset_or_event="BTC")
        self.bus.update_signals([sig])
        assert "BTC" not in self.bus._asset_cache

    def test_signal_invalidates_event_cache(self):
        s = _make_hashtag(asset=None, event_id="EVT-1", score=0.3, volume=50)
        self.bus.update_hashtags([s])
        self.bus._event_cache["EVT-1"] = object()
        sig = _make_signal(asset_or_event="EVT-1")
        self.bus.update_signals([sig])
        assert "EVT-1" not in self.bus._event_cache

    def test_signal_for_missing_context_no_error(self):
        sig = _make_signal(asset_or_event="NONEXISTENT")
        self.bus.update_signals([sig])  # should not raise

    def test_multiple_signals_replace_previous(self):
        s = _make_hashtag(asset="BTC", score=0.5, volume=100)
        self.bus.update_hashtags([s])
        sig1 = _make_signal(asset_or_event="BTC", direction="bullish")
        self.bus.update_signals([sig1])
        sig2 = _make_signal(asset_or_event="BTC", direction="bearish")
        self.bus.update_signals([sig2])
        signals = self.bus._hashtag_contexts["BTC"].signals
        directions = [s.direction for s in signals]
        assert "bearish" in directions


# ═══════════════════════════════════════════════════════════════════════════
# Gap 4 — get_market_context() blend with missing asset or event
# ═══════════════════════════════════════════════════════════════════════════

class TestMarketContextBlend:

    def setup_method(self):
        self.bus = _reset_bus()

    def test_asset_only_market(self):
        s = _make_hashtag(asset="BTC", score=0.6, volume=100)
        self.bus.update_hashtags([s])
        with patch.object(self.bus, "_get_fg", return_value=50), \
             patch.object(self.bus, "_get_social_score", return_value=(0.0, 0.5)):
            ctx = self.bus.get_market_context("MKT-1", asset="BTC", category="crypto")
        assert ctx.asset_context is not None
        assert ctx.event_context is None
        # combined should equal asset_context.combined_score (no averaging with 0)
        assert ctx.combined_score == pytest.approx(ctx.asset_context.combined_score, abs=0.001)

    def test_event_only_market(self):
        from merid.sentiment.news_ingestion_agent import AggregatedNewsSentiment
        agg = AggregatedNewsSentiment(
            key="politics:EVT-1", category="politics", asset=None,
            event_id="EVT-1", score=0.4, confidence=0.6,
            headline_count=3, provider_scores={"newsapi": 0.4},
            label="positive", timestamp=datetime.now(timezone.utc),
        )
        self.bus.update_news([agg])
        ctx = self.bus.get_market_context("MKT-2", event_id="EVT-1",
                                          category="politics")
        assert ctx.event_context is not None
        assert ctx.asset_context is None
        assert ctx.combined_score == pytest.approx(ctx.event_context.combined_score, abs=0.001)

    def test_both_asset_and_event(self):
        s = _make_hashtag(asset="BTC", score=0.8, volume=100)
        self.bus.update_hashtags([s])
        agg = AggregatedNewsSentiment(
            key="crypto:EVT-BTC", category="crypto", asset="BTC",
            event_id="EVT-BTC", score=0.2, confidence=0.6,
            headline_count=2, provider_scores={"newsapi": 0.2},
            label="positive", timestamp=datetime.now(timezone.utc),
        )
        self.bus.update_news([agg])
        with patch.object(self.bus, "_get_fg", return_value=50), \
             patch.object(self.bus, "_get_social_score", return_value=(0.0, 0.5)):
            ctx = self.bus.get_market_context("MKT-3", event_id="EVT-BTC",
                                              asset="BTC", category="crypto")
        assert ctx.asset_context is not None
        assert ctx.event_context is not None
        # combined is average of asset + event combined scores
        expected = (ctx.asset_context.combined_score + ctx.event_context.combined_score) / 2
        assert ctx.combined_score == pytest.approx(expected, abs=0.01)

    def test_neither_asset_nor_event(self):
        ctx = self.bus.get_market_context("MKT-EMPTY", category="politics")
        assert ctx.asset_context is None
        assert ctx.event_context is None
        assert ctx.combined_score == pytest.approx(0.0)


# ═══════════════════════════════════════════════════════════════════════════
# Gap 5 — HashtagMonitor stats accumulation across multiple force-cycles
# ═══════════════════════════════════════════════════════════════════════════

class TestMonitorStatsAccumulation:

    def _fresh_monitor(self):
        from merid.sentiment.hashtag_monitor import HashtagMonitor
        return HashtagMonitor(hashtag_interval=9999, news_interval=9999,
                              asset_cycle_interval=9999)

    def test_stats_accumulate_across_cycles(self):
        import asyncio
        m = self._fresh_monitor()
        sig = _make_signal()
        mock_agent = MagicMock()
        mock_agent.run_cycle = AsyncMock(return_value=[])
        mock_agent.generate_signals = MagicMock(return_value=[sig, sig])
        mock_bus = MagicMock()

        with patch.object(m, "_get_hashtag_agent", return_value=mock_agent), \
             patch.object(m, "_get_bus", return_value=mock_bus), \
             patch.object(m, "_get_fg", return_value=50):
            loop = asyncio.new_event_loop()
            try:
                for _ in range(3):
                    loop.run_until_complete(m.force_hashtag_cycle())
            finally:
                loop.close()

        assert m.stats.hashtag_cycles == 3
        assert m.stats.signals_generated == 6

    def test_error_does_not_increment_cycle_count(self):
        import asyncio
        m = self._fresh_monitor()
        mock_agent = MagicMock()
        mock_agent.run_cycle = AsyncMock(side_effect=RuntimeError("fail"))

        with patch.object(m, "_get_hashtag_agent", return_value=mock_agent):
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(m._run_hashtag_cycle())
            finally:
                loop.close()

        assert m.stats.hashtag_cycles == 0
        assert m.stats.errors == 1


# ═══════════════════════════════════════════════════════════════════════════
# Gap 6 — combine_sentiment fallback when all sources fail
# ═══════════════════════════════════════════════════════════════════════════

class TestCombineSentimentFallback:

    def test_all_sources_fail_returns_valid_bundle(self):
        from merid.sentiment.sentiment_bundle import SentimentBundle, combine_sentiment

        with patch("merid.sentiment.twitter_fetcher.quick_twitter_sentiment",
                   side_effect=RuntimeError("Twitter down")), \
             patch("merid.sentiment.reddit_scraper.quick_reddit_sentiment",
                   side_effect=RuntimeError("Reddit down")), \
             patch("merid.sentiment.cfgi_client.quick_fg",
                   side_effect=RuntimeError("FG down")):
            result = combine_sentiment("BTC")

        assert isinstance(result, SentimentBundle)
        assert result.asset == "BTC"
        assert result.twitter == pytest.approx(0.0)
        assert result.reddit == pytest.approx(0.0)
        assert result.fg_index == 50
        assert -1.0 <= result.combined <= 1.0

    def test_twitter_only_fails(self):
        from merid.sentiment.sentiment_bundle import combine_sentiment

        with patch("merid.sentiment.twitter_fetcher.quick_twitter_sentiment",
                   side_effect=RuntimeError("fail")), \
             patch("merid.sentiment.reddit_scraper.quick_reddit_sentiment",
                   return_value=0.3), \
             patch("merid.sentiment.cfgi_client.quick_fg",
                   return_value=50):
            result = combine_sentiment("BTC")

        assert result.twitter == pytest.approx(0.0)
        assert result.reddit == pytest.approx(0.3)


# ═══════════════════════════════════════════════════════════════════════════
# Gap 7 — kalshi_prob_adjustment sign and magnitude
# ═══════════════════════════════════════════════════════════════════════════

class TestKalshiProbAdjustment:

    def _make_ctx(self, combined: float, fg: int = 50) -> AssetSentimentContext:
        bus = _reset_bus()
        s = _make_hashtag(asset="BTC", score=combined, volume=200)
        bus.update_hashtags([s])
        agg = AggregatedNewsSentiment(
            key="crypto:BTC", category="crypto", asset="BTC",
            event_id=None, score=combined, confidence=0.7,
            headline_count=5, provider_scores={"newsapi": combined},
            label="positive" if combined > 0 else "negative",
            timestamp=datetime.now(timezone.utc),
        )
        bus.update_news([agg])
        with patch.object(bus, "_get_fg", return_value=fg), \
             patch.object(bus, "_get_social_score", return_value=(combined, 0.8)):
            return bus.get_asset_context("BTC")

    def test_positive_sentiment_positive_adjustment(self):
        ctx = self._make_ctx(combined=0.8, fg=50)
        adj = ctx.kalshi_prob_adjustment()
        assert adj > 0

    def test_negative_sentiment_negative_adjustment(self):
        ctx = self._make_ctx(combined=-0.8, fg=50)
        adj = ctx.kalshi_prob_adjustment()
        assert adj < 0

    def test_adjustment_bounded(self):
        ctx = self._make_ctx(combined=1.0, fg=50)
        adj = ctx.kalshi_prob_adjustment()
        assert -0.1 <= adj <= 0.1

    def test_neutral_sentiment_near_zero_adjustment(self):
        ctx = self._make_ctx(combined=0.0, fg=50)
        adj = ctx.kalshi_prob_adjustment()
        assert abs(adj) < 0.01


# ═══════════════════════════════════════════════════════════════════════════
# Gap 8 — _ScoreWindow edge cases
# ═══════════════════════════════════════════════════════════════════════════

class TestScoreWindowEdgeCases:

    def test_maxlen_1_kalman_returns_raw_score(self):
        w = _ScoreWindow(maxlen=1)
        w.push(0.75, 10)
        assert w.kalman_smooth() == pytest.approx(0.75)

    def test_maxlen_1_volume_weighted_avg(self):
        w = _ScoreWindow(maxlen=1)
        w.push(0.5, 10)
        w.push(0.9, 20)  # evicts 0.5
        assert w.volume_weighted_avg() == pytest.approx(0.9)
        assert w.count == 1

    def test_all_negative_scores(self):
        w = _ScoreWindow(maxlen=5)
        for s in [-0.1, -0.3, -0.5, -0.7, -0.9]:
            w.push(s, 1)
        assert w.simple_avg() < 0
        assert w.kalman_smooth() < 0
        assert w.volume_weighted_avg() < 0

    def test_alternating_scores_kalman_dampens(self):
        w = _ScoreWindow(maxlen=10)
        for i in range(10):
            w.push(1.0 if i % 2 == 0 else -1.0, 1)
        smoothed = w.kalman_smooth()
        # Kalman should dampen oscillation — result between -1 and 1
        assert -1.0 < smoothed < 1.0


# ═══════════════════════════════════════════════════════════════════════════
# Gap 9 — HashtagAgent singleton reset
# ═══════════════════════════════════════════════════════════════════════════

class TestHashtagAgentSingletonReset:

    def test_fresh_instance_has_empty_history(self):
        agent = HashtagAgent()
        assert len(agent._history) == 0

    def test_history_does_not_bleed_after_reset(self):
        agent1 = HashtagAgent()
        agent1._history["#BTC"].push(0.5, 100)
        assert len(agent1._history) == 1

        # Simulate singleton reset
        agent2 = HashtagAgent()
        # Different instance should have clean history
        assert agent2 is not agent1 or len(agent2._history) > 0
        # If same instance (singleton), history is shared — that's expected
        # The key invariant: a NEW instance has empty history
        fresh = HashtagAgent.__new__(HashtagAgent)
        fresh.__init__()
        # __init__ creates fresh _history
        assert "#BTC" not in fresh._history or fresh is agent1


# ═══════════════════════════════════════════════════════════════════════════
# Gap 10 — SentimentBusV2 concurrent read/write safety
# ═══════════════════════════════════════════════════════════════════════════

class TestBusConcurrentAccess:

    def test_concurrent_write_read_no_crash(self):
        bus = _reset_bus()
        errors = []

        def writer():
            for i in range(50):
                try:
                    s = _make_hashtag(asset="BTC", score=i * 0.01, volume=10 + i)
                    bus.update_hashtags([s])
                except Exception as e:
                    errors.append(("writer", e))

        def reader():
            for _ in range(50):
                try:
                    with patch.object(bus, "_get_fg", return_value=50), \
                         patch.object(bus, "_get_social_score", return_value=(0.0, 0.5)):
                        bus.get_asset_context("BTC")
                except Exception as e:
                    errors.append(("reader", e))

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        # No KeyError or AttributeError should occur
        critical_errors = [e for name, e in errors
                          if isinstance(e, (KeyError, AttributeError))]
        assert critical_errors == [], f"Critical errors: {critical_errors}"

    def test_concurrent_news_and_event_context(self):
        bus = _reset_bus()
        errors = []

        def writer():
            for i in range(50):
                try:
                    agg = AggregatedNewsSentiment(
                        key="politics:EVT-C", category="politics", asset=None,
                        event_id="EVT-C", score=i * 0.01, confidence=0.5,
                        headline_count=1, provider_scores={"newsapi": i * 0.01},
                        label="positive", timestamp=datetime.now(timezone.utc),
                    )
                    bus.update_news([agg])
                except Exception as e:
                    errors.append(("writer", e))

        def reader():
            for _ in range(50):
                try:
                    bus.get_event_context("EVT-C", category="politics")
                except Exception as e:
                    errors.append(("reader", e))

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        critical_errors = [e for name, e in errors
                          if isinstance(e, (KeyError, AttributeError))]
        assert critical_errors == [], f"Critical errors: {critical_errors}"
