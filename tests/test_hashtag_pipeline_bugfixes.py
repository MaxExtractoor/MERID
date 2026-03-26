"""test_hashtag_pipeline_bugfixes.py — Regression tests for nine bugs fixed in
the MERID hashtag agent pipeline audit.

BUG-1: HashtagAgent._get_bus() used v1 SentimentBus (no update_hashtags).
BUG-2: NewsIngestionAgent._get_bus() used v1 SentimentBus (no update_news).
BUG-3: SentimentBusV2._lock was never acquired — all mutations unprotected.
BUG-4: _RateLimiter race condition — concurrent coroutines both skipped wait.
BUG-5: update_signals() dropped all but the last signal per key per call.
BUG-6: generate_signals() used items[0].tag (potentially reddit:) for history.
BUG-7: HashtagAgent._history was an unbounded defaultdict.
BUG-8: SentimentBusV2 window/context dicts were unbounded defaultdicts.
BUG-9: Synthetic FG data not propagated to AssetSentimentContext.
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from merid.sentiment.hashtag_agent import (
    HashtagAgent,
    HashtagSentiment,
    HashtagSignal,
    _RateLimiter,
    _TagHistory,
)
from merid.sentiment.sentiment_bus_v2 import (
    AssetSentimentContext,
    SentimentBusV2,
    _ScoreWindow,
)


# ── Helpers ───────────────────────────────────────────────────────────────

def _reset_bus() -> SentimentBusV2:
    SentimentBusV2._instance = None
    return SentimentBusV2()


def _make_sentiment(
    tag: str = "#BTC",
    score: float = 0.5,
    volume: int = 100,
    asset: Optional[str] = "BTC",
    provider: str = "twitter",
    category: str = "crypto",
) -> HashtagSentiment:
    return HashtagSentiment(
        tag=tag,
        score=score,
        volume=volume,
        category=category,
        asset=asset,
        event_id=None,
        provider=provider,
        timestamp=datetime.now(timezone.utc),
        confidence=0.5,
    )


def _make_signal(asset: str = "BTC", direction: str = "bullish", strength: float = 0.7) -> HashtagSignal:
    return HashtagSignal(
        asset_or_event=asset,
        direction=direction,
        strength=strength,
        reason="test",
        score=0.5,
        volume=100,
        tags=["#BTC"],
        category="crypto",
        timestamp=datetime.now(timezone.utc),
    )


# ═══════════════════════════════════════════════════════════════════════════
# BUG-1: HashtagAgent._get_bus() must return SentimentBusV2
# ═══════════════════════════════════════════════════════════════════════════

class TestBug1AgentBusVersion:
    def test_get_bus_returns_v2_instance(self):
        """HashtagAgent._get_bus() must resolve to SentimentBusV2, not v1."""
        from merid.sentiment.sentiment_bus_v2 import SentimentBusV2

        agent = HashtagAgent(bus=None)
        with patch("merid.sentiment.sentiment_bus_v2.get_sentiment_bus_v2") as mock_v2:
            mock_v2.return_value = MagicMock(spec=SentimentBusV2)
            bus = agent._get_bus()
        mock_v2.assert_called_once()
        assert bus is mock_v2.return_value

    def test_update_hashtags_called_on_v2(self):
        """run_cycle must call update_hashtags on SentimentBusV2."""
        bus_mock = MagicMock()
        agent = HashtagAgent(bus=bus_mock)

        # Make twitter/reddit clients return immediately
        async def _fake_tweet(tag, **kw):
            return 0.3, 50

        async def _fake_reddit(*a, **kw):
            return 0.1, 20

        tw = MagicMock()
        tw.sentiment_for_hashtag = _fake_tweet
        rd = MagicMock()
        rd.sentiment_for_subreddits = _fake_reddit

        # Patch away Kalshi and run a minimal cycle
        agent._kalshi = MagicMock()
        agent._kalshi.get_all_live_events.return_value = []
        agent._twitter = tw
        agent._reddit = rd

        asyncio.run(agent.run_cycle())
        bus_mock.update_hashtags.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
# BUG-2: NewsIngestionAgent._get_bus() must return SentimentBusV2
# ═══════════════════════════════════════════════════════════════════════════

class TestBug2NewsAgentBusVersion:
    def test_news_agent_get_bus_returns_v2(self):
        """NewsIngestionAgent._get_bus() must resolve to SentimentBusV2."""
        from merid.sentiment.news_ingestion_agent import NewsIngestionAgent
        from merid.sentiment.sentiment_bus_v2 import SentimentBusV2

        agent = NewsIngestionAgent(bus=None)
        with patch("merid.sentiment.sentiment_bus_v2.get_sentiment_bus_v2") as mock_v2:
            mock_v2.return_value = MagicMock(spec=SentimentBusV2)
            bus = agent._get_bus()
        mock_v2.assert_called_once()
        assert bus is mock_v2.return_value


# ═══════════════════════════════════════════════════════════════════════════
# BUG-3: SentimentBusV2 lock must be a threading.Lock, not asyncio.Lock
# ═══════════════════════════════════════════════════════════════════════════

class TestBug3LockType:
    def test_lock_is_threading_lock(self):
        """SentimentBusV2._lock must be a threading.Lock (usable in sync methods)."""
        import threading as _threading

        bus = _reset_bus()
        assert isinstance(bus._lock, type(_threading.Lock()))

    def test_concurrent_update_hashtags_is_safe(self):
        """Two threads updating hashtags concurrently should not raise."""
        bus = _reset_bus()
        errors: list = []

        def worker(score: float) -> None:
            try:
                sents = [_make_sentiment(score=score, volume=50)]
                bus.update_hashtags(sents)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(0.1 * i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent update raised: {errors}"


# ═══════════════════════════════════════════════════════════════════════════
# BUG-4: _RateLimiter race condition — two concurrent callers must queue
# ═══════════════════════════════════════════════════════════════════════════

class TestBug4RateLimiter:
    def test_concurrent_calls_are_serialised(self):
        """Two concurrent acquire() calls must be at least interval apart."""
        rl = _RateLimiter(calls_per_minute=60)  # 1-second interval

        call_times: list = []

        async def task() -> None:
            await rl.acquire()
            call_times.append(time.monotonic())

        async def run() -> None:
            await asyncio.gather(task(), task())

        asyncio.run(run())
        gap = call_times[1] - call_times[0]
        # The second call must be delayed by ≥ the interval (1 s).
        # We use a loose bound (0.8 s) to account for scheduler jitter.
        assert gap >= 0.8, f"Rate limiter failed: gap was only {gap:.3f}s"

    def test_single_call_does_not_block(self):
        """A single acquire() on a fresh limiter should not sleep."""
        rl = _RateLimiter(calls_per_minute=60)
        t0 = time.monotonic()
        asyncio.run(rl.acquire())
        elapsed = time.monotonic() - t0
        assert elapsed < 0.1, f"First acquire took unexpectedly long: {elapsed:.3f}s"


# ═══════════════════════════════════════════════════════════════════════════
# BUG-5: update_signals must accumulate all signals per key per call
# ═══════════════════════════════════════════════════════════════════════════

class TestBug5UpdateSignals:
    def test_multiple_signals_same_key_all_stored(self):
        """All signals for the same asset emitted in one call must be stored."""
        bus = _reset_bus()
        # Seed a hashtag context so update_signals has somewhere to write
        bus.update_hashtags([_make_sentiment(asset="BTC", score=0.4)])

        sig_a = _make_signal("BTC", "bullish", 0.8)
        sig_b = _make_signal("BTC", "contrarian", 0.6)
        bus.update_signals([sig_a, sig_b])

        ctx = bus._hashtag_contexts.get("BTC")
        assert ctx is not None
        # Both signals must survive — not just the last one
        assert len(ctx.signals) == 2, (
            f"Expected 2 signals, got {len(ctx.signals)}: {ctx.signals}"
        )

    def test_signals_replaced_across_cycles(self):
        """Signals from a later cycle should replace those from an earlier cycle."""
        bus = _reset_bus()
        bus.update_hashtags([_make_sentiment(asset="ETH", score=0.3)])

        old_sig = _make_signal("ETH", "bearish", 0.5)
        bus.update_signals([old_sig])

        new_sig = _make_signal("ETH", "bullish", 0.9)
        bus.update_signals([new_sig])

        ctx = bus._hashtag_contexts.get("ETH")
        assert ctx is not None
        assert len(ctx.signals) == 1
        assert ctx.signals[0].direction == "bullish"


# ═══════════════════════════════════════════════════════════════════════════
# BUG-6: generate_signals spike detection must skip reddit: tags
# ═══════════════════════════════════════════════════════════════════════════

class TestBug6SpikeDetection:
    def test_spike_detection_uses_twitter_tag_not_reddit(self):
        """Spike detection must use a non-reddit: tag's history when available."""
        agent = HashtagAgent()

        twitter_tag = "#ETH"
        reddit_tag = "reddit:crypto:ETH"

        # Seed history only for the twitter tag
        for _ in range(5):
            agent._history_push(twitter_tag, 0.1, 10)

        sents = [
            # reddit entry comes FIRST in the list
            _make_sentiment(tag=reddit_tag, score=0.2, volume=50,
                            asset="ETH", provider="reddit"),
            _make_sentiment(tag=twitter_tag, score=0.4, volume=300,
                            asset="ETH", provider="twitter"),
        ]
        signals = agent.generate_signals(sents, volume_spike_threshold=2.5)
        # 300 volume > 2.5 * 10 avg → should be detected as spike
        assert len(signals) == 1
        assert "spike" in signals[0].reason, (
            f"Expected spike reason, got: {signals[0].reason}"
        )

    def test_spike_detection_fallback_to_reddit_tag_when_no_twitter(self):
        """When only a reddit: tag exists in the group, it should still work."""
        agent = HashtagAgent()

        reddit_tag = "reddit:crypto:SOL"
        for _ in range(5):
            agent._history_push(reddit_tag, 0.1, 10)

        sents = [
            _make_sentiment(tag=reddit_tag, score=0.5, volume=300,
                            asset="SOL", provider="reddit"),
        ]
        signals = agent.generate_signals(sents, volume_spike_threshold=2.5)
        assert len(signals) == 1
        assert "spike" in signals[0].reason


# ═══════════════════════════════════════════════════════════════════════════
# BUG-7: HashtagAgent._history must be bounded
# ═══════════════════════════════════════════════════════════════════════════

class TestBug7BoundedHistory:
    def test_history_is_ordereddict(self):
        agent = HashtagAgent()
        assert isinstance(agent._history, OrderedDict)

    def test_history_evicts_oldest_when_full(self):
        """Pushing more than history_max entries evicts the oldest."""
        agent = HashtagAgent()
        agent._history_max = 5  # small cap for test speed

        for i in range(7):
            agent._history_push(f"tag_{i}", 0.1, 10)

        assert len(agent._history) == 5, (
            f"Expected 5 entries after eviction, got {len(agent._history)}"
        )
        # Oldest two tags should be gone
        assert "tag_0" not in agent._history
        assert "tag_1" not in agent._history
        # Most recent should be present
        assert "tag_6" in agent._history

    def test_lru_promotes_recently_accessed_tag(self):
        """Accessing an existing tag moves it to most-recent position."""
        agent = HashtagAgent()
        agent._history_max = 3

        agent._history_push("tag_A", 0.1, 10)
        agent._history_push("tag_B", 0.1, 10)
        agent._history_push("tag_C", 0.1, 10)

        # Re-access tag_A — should be moved to end
        agent._history_push("tag_A", 0.2, 20)

        # Adding a 4th tag should evict tag_B (oldest after promotion of A)
        agent._history_push("tag_D", 0.1, 10)
        assert "tag_B" not in agent._history
        assert "tag_A" in agent._history


# ═══════════════════════════════════════════════════════════════════════════
# BUG-8: SentimentBusV2 window/context dicts must be bounded
# ═══════════════════════════════════════════════════════════════════════════

class TestBug8BoundedBusWindows:
    def test_hashtag_windows_are_ordereddict(self):
        bus = _reset_bus()
        assert isinstance(bus._hashtag_windows, OrderedDict)
        assert isinstance(bus._hashtag_contexts, OrderedDict)

    def test_news_windows_are_ordereddict(self):
        bus = _reset_bus()
        assert isinstance(bus._news_windows, OrderedDict)
        assert isinstance(bus._news_contexts, OrderedDict)

    def test_hashtag_contexts_evict_oldest(self):
        """update_hashtags evicts oldest context entries when cap is reached."""
        bus = _reset_bus()
        bus._ctx_max = 3

        for i in range(5):
            asset = f"ASSET_{i}"
            bus.update_hashtags([_make_sentiment(tag=f"#{asset}", asset=asset)])

        assert len(bus._hashtag_contexts) <= 3

    def test_news_contexts_evict_oldest(self):
        """update_news evicts oldest context entries when cap is reached."""
        from merid.sentiment.news_ingestion_agent import AggregatedNewsSentiment

        bus = _reset_bus()
        bus._ctx_max = 3

        for i in range(5):
            key = f"crypto:ASSET_{i}"
            agg = AggregatedNewsSentiment(
                key=key,
                category="crypto",
                asset=f"ASSET_{i}",
                event_id=None,
                score=0.3,
                confidence=0.6,
                headline_count=5,
                label="positive",
                provider_scores={"newsapi": 0.3},
                timestamp=datetime.now(timezone.utc),
            )
            bus.update_news([agg])

        assert len(bus._news_contexts) <= 3


# ═══════════════════════════════════════════════════════════════════════════
# BUG-9: Synthetic FG flag must appear in AssetSentimentContext
# ═══════════════════════════════════════════════════════════════════════════

class TestBug9SyntheticFgFlag:
    def _make_ctx(self, fg: int, is_synthetic: bool) -> AssetSentimentContext:
        bus = _reset_bus()
        with patch.object(bus, "_get_fg", return_value=(fg, is_synthetic)), \
             patch.object(bus, "_get_social_score", return_value=(0.0, 0.5)):
            return bus.get_asset_context("BTC")

    def test_synthetic_flag_false_when_real_data(self):
        ctx = self._make_ctx(fg=50, is_synthetic=False)
        assert ctx.fg_is_synthetic is False

    def test_synthetic_flag_true_when_fallback(self):
        ctx = self._make_ctx(fg=65, is_synthetic=True)
        assert ctx.fg_is_synthetic is True

    def test_synthetic_flag_in_to_dict(self):
        ctx = self._make_ctx(fg=30, is_synthetic=True)
        d = ctx.to_dict()
        assert "fg_is_synthetic" in d
        assert d["fg_is_synthetic"] is True

    def test_non_synthetic_fg_not_flagged_in_to_dict(self):
        ctx = self._make_ctx(fg=70, is_synthetic=False)
        d = ctx.to_dict()
        assert d.get("fg_is_synthetic") is False
