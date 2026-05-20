"""Tests for Kalshi news agent.

NOTE: This test is marked as sentiment_research and should be excluded from
kalshi_crypto_15m_v2 production test runs. Sentiment is research-only and
must not influence live 15m Kalshi trading decisions.
"""

import pytest

pytestmark = pytest.mark.sentiment_research

"""
Tests for KalshiNewsAgent — Telegram/X formatting, cooldown enforcement, dispatch.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from merid.publishing.kalshi_insight_pipeline import InsightObject
from merid.publishing.kalshi_news_agent import KalshiNewsAgent, CATEGORY_POST_COOLDOWN as CATEGORY_COOLDOWNS


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_insight(**kwargs) -> InsightObject:
    base = dict(
        source="kalshi",
        category="Crypto",
        ticker="KXBTC-1H-T95000",
        question="Will BTC exceed $95k in the next hour?",
        kalshi_prob=0.72,
        swarm_prob=0.70,
        swarm_confidence=0.65,
        change_24h=0.09,
        timestamp="2026-02-20T00:00:00Z",
        narrative="BTC surged 9% in the last hour driven by ETF inflows.",
        action="swing",
        market_url="https://kalshi.com/markets/KXBTC-1H-T95000",
        volume=1500,
        open_interest=900,
        tags=["crypto", "btc"],
    )
    base.update(kwargs)
    return InsightObject(**base)


def make_agent(telegram=None, twitter=None) -> KalshiNewsAgent:
    from collections import defaultdict
    agent = KalshiNewsAgent.__new__(KalshiNewsAgent)
    agent._last_post_ts = defaultdict(float)
    agent._ticker_last_post = {}
    agent._post_history = []
    agent._thread_ids = {}
    agent._stats = {
        "total_processed": 0,
        "total_telegram": 0,
        "total_x": 0,
        "skipped_cooldown": 0,
        "errors": 0,
    }
    return agent


# ── Telegram formatting ───────────────────────────────────────────────────────

class TestFormatTelegram:
    def test_contains_ticker(self):
        agent = make_agent()
        insight = make_insight()
        text = agent._format_telegram(insight)
        assert "KXBTC-1H-T95000" in text

    def test_contains_probability(self):
        agent = make_agent()
        insight = make_insight(kalshi_prob=0.72)
        text = agent._format_telegram(insight)
        assert "72%" in text

    def test_contains_narrative(self):
        agent = make_agent()
        insight = make_insight(narrative="BTC surged 9%.")
        text = agent._format_telegram(insight)
        assert "BTC surged 9%." in text

    def test_contains_market_url(self):
        agent = make_agent()
        insight = make_insight(market_url="https://kalshi.com/markets/KXBTC-1H-T95000")
        text = agent._format_telegram(insight)
        assert "kalshi.com" in text

    def test_contains_category_emoji(self):
        agent = make_agent()
        insight = make_insight(category="Crypto")
        text = agent._format_telegram(insight)
        assert "₿" in text  # Crypto emoji

    def test_contains_swarm_confidence(self):
        agent = make_agent()
        insight = make_insight(swarm_confidence=0.65)
        text = agent._format_telegram(insight)
        assert "65%" in text

    def test_resolution_action_shows_result(self):
        agent = make_agent()
        insight = make_insight(action="resolution", resolved_yes=True, narrative="Market resolved YES.")
        text = agent._format_telegram(insight)
        assert "Settled" in text or "settled" in text.lower() or "YES" in text


# ── X/Twitter formatting ──────────────────────────────────────────────────────

class TestFormatX:
    def test_within_280_chars(self):
        agent = make_agent()
        insight = make_insight()
        text = agent._format_x(insight)
        assert len(text) <= 280

    def test_contains_ticker(self):
        agent = make_agent()
        insight = make_insight(ticker="KXBTC-1H-T95000")
        text = agent._format_x(insight)
        assert "KXBTC" in text

    def test_contains_probability(self):
        agent = make_agent()
        insight = make_insight(kalshi_prob=0.72)
        text = agent._format_x(insight)
        assert "72%" in text

    def test_contains_category_emoji(self):
        agent = make_agent()
        insight = make_insight(category="Politics")
        text = agent._format_x(insight)
        assert "🏛️" in text

    def test_contains_action_emoji_swing(self):
        agent = make_agent()
        insight = make_insight(action="swing")
        text = agent._format_x(insight)
        # swing action should have some directional indicator
        assert any(c in text for c in ["📈", "📉", "⚡", "🔄", "↕"])

    def test_long_question_truncated(self):
        agent = make_agent()
        long_q = "Will the Federal Reserve raise interest rates by more than 50 basis points in the next FOMC meeting scheduled for March 2026?"
        insight = make_insight(question=long_q)
        text = agent._format_x(insight)
        assert len(text) <= 280

    def test_all_categories_produce_valid_post(self):
        agent = make_agent()
        categories = ["Trending", "Politics", "Sports", "Culture", "Crypto",
                      "Climate", "Economics", "Mentions", "Companies",
                      "Financials", "Tech & Science"]
        for cat in categories:
            insight = make_insight(category=cat)
            text = agent._format_x(insight)
            assert len(text) <= 280, f"Post too long for category {cat}: {len(text)} chars"


# ── Cooldown enforcement ──────────────────────────────────────────────────────

class TestCooldownEnforcement:
    @pytest.mark.asyncio
    async def test_first_post_not_throttled(self):
        """First post for a category should not be skipped by cooldown."""
        telegram = MagicMock()
        telegram.send_message = AsyncMock(return_value=MagicMock(message_id=1))
        twitter = MagicMock()
        twitter.enabled = True
        tweet_result = MagicMock()
        tweet_result.tweet_id = "tweet-001"
        twitter.post_tweet = MagicMock(return_value=tweet_result)
        agent = make_agent()
        insight = make_insight(category="Crypto", ticker="KXBTC-001")
        with patch("agents.telegram_agent.get_telegram_agent", return_value=telegram), \
             patch("agents.twitter_agent.get_twitter_agent", return_value=twitter):
            await agent.handle_insight(insight)
        assert agent._stats["skipped_cooldown"] == 0

    @pytest.mark.asyncio
    async def test_second_post_within_cooldown_throttled(self):
        agent = make_agent()
        insight = make_insight(category="Crypto", ticker="KXBTC-001")
        agent._last_post_ts["Crypto"] = time.time()  # just posted
        await agent.handle_insight(insight)
        assert agent._stats["skipped_cooldown"] == 1

    @pytest.mark.asyncio
    async def test_post_after_cooldown_not_throttled(self):
        telegram = MagicMock()
        telegram.send_message = AsyncMock(return_value=MagicMock(message_id=1))
        twitter = MagicMock()
        tweet_result = MagicMock()
        tweet_result.tweet_id = "tweet-002"
        twitter.post_tweet = MagicMock(return_value=tweet_result)
        twitter.enabled = True
        agent = make_agent()
        insight = make_insight(category="Crypto", ticker="KXBTC-001")
        cooldown = CATEGORY_COOLDOWNS.get("Crypto", 300)
        agent._last_post_ts["Crypto"] = time.time() - cooldown - 1
        with patch("agents.telegram_agent.get_telegram_agent", return_value=telegram), \
             patch("agents.twitter_agent.get_twitter_agent", return_value=twitter):
            await agent.handle_insight(insight)
        assert agent._stats["skipped_cooldown"] == 0

    @pytest.mark.asyncio
    async def test_per_ticker_cooldown_enforced(self):
        agent = make_agent()
        insight = make_insight(category="Trending", ticker="KXBTC-001")
        # Category is clear but ticker was just posted
        agent._ticker_last_post["KXBTC-001"] = time.time()
        await agent.handle_insight(insight)
        assert agent._stats["skipped_cooldown"] == 1

    @pytest.mark.asyncio
    async def test_skipped_count_increments_on_throttle(self):
        agent = make_agent()
        insight = make_insight(category="Crypto", ticker="KXBTC-001")
        agent._last_post_ts["Crypto"] = time.time()
        await agent.handle_insight(insight)
        assert agent._stats["skipped_cooldown"] == 1


# ── Dispatch flow ─────────────────────────────────────────────────────────────

class TestDispatch:
    @pytest.mark.asyncio
    async def test_processes_insight_increments_counter(self):
        telegram = MagicMock()
        telegram.send_message = AsyncMock(return_value=MagicMock(message_id=1))
        twitter = MagicMock()
        tweet_result = MagicMock()
        tweet_result.tweet_id = "tweet-id-001"
        twitter.post_tweet = MagicMock(return_value=tweet_result)
        twitter.enabled = True
        agent = make_agent()
        insight = make_insight()
        with patch("agents.telegram_agent.get_telegram_agent", return_value=telegram), \
             patch("agents.twitter_agent.get_twitter_agent", return_value=twitter):
            await agent.handle_insight(insight)
        assert agent._stats["total_processed"] == 1

    @pytest.mark.asyncio
    async def test_telegram_called_when_enabled(self):
        telegram = MagicMock()
        telegram.send_message = AsyncMock(return_value=MagicMock(message_id=1))
        twitter = MagicMock()
        tweet_result = MagicMock()
        tweet_result.tweet_id = None
        twitter.post_tweet = MagicMock(return_value=tweet_result)
        twitter.enabled = True
        agent = make_agent()
        insight = make_insight()
        with patch("agents.telegram_agent.get_telegram_agent", return_value=telegram), \
             patch("agents.twitter_agent.get_twitter_agent", return_value=twitter):
            await agent.handle_insight(insight)
        telegram.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_twitter_called_when_enabled(self):
        telegram = MagicMock()
        telegram.send_message = AsyncMock(return_value=MagicMock(message_id=1))
        twitter = MagicMock()
        tweet_result = MagicMock()
        tweet_result.tweet_id = "tweet-id-001"
        twitter.post_tweet = MagicMock(return_value=tweet_result)
        twitter.enabled = True
        agent = make_agent()
        insight = make_insight()
        with patch("agents.telegram_agent.get_telegram_agent", return_value=telegram), \
             patch("agents.twitter_agent.get_twitter_agent", return_value=twitter):
            await agent.handle_insight(insight)
        twitter.post_tweet.assert_called_once()

    @pytest.mark.asyncio
    async def test_throttled_insight_not_dispatched(self):
        telegram = MagicMock()
        telegram.send_message = AsyncMock()
        twitter = MagicMock()
        twitter.post_tweet = MagicMock()
        agent = make_agent()
        insight = make_insight(category="Crypto", ticker="KXBTC-001")
        agent._last_post_ts["Crypto"] = time.time()  # force throttle
        with patch("agents.telegram_agent.get_telegram_agent", return_value=telegram), \
             patch("agents.twitter_agent.get_twitter_agent", return_value=twitter):
            await agent.handle_insight(insight)
        telegram.send_message.assert_not_called()
        twitter.post_tweet.assert_not_called()
        assert agent._stats["skipped_cooldown"] == 1

    @pytest.mark.asyncio
    async def test_recent_posts_recorded(self):
        telegram = MagicMock()
        telegram.send_message = AsyncMock(return_value=MagicMock(message_id=1))
        twitter = MagicMock()
        tweet_result = MagicMock()
        tweet_result.tweet_id = "tweet-123"
        twitter.post_tweet = MagicMock(return_value=tweet_result)
        twitter.enabled = True
        agent = make_agent()
        insight = make_insight(ticker="KXBTC-001")
        with patch("agents.telegram_agent.get_telegram_agent", return_value=telegram), \
             patch("agents.twitter_agent.get_twitter_agent", return_value=twitter):
            await agent.handle_insight(insight)
        assert len(agent._post_history) == 1
        assert agent._post_history[0].ticker == "KXBTC-001"
        assert agent._post_history[0].x_tweet_id == "tweet-123"

    @pytest.mark.asyncio
    async def test_thread_id_used_for_repeat_ticker(self):
        telegram = MagicMock()
        telegram.send_message = AsyncMock(return_value=MagicMock(message_id=1))
        twitter = MagicMock()
        reply_result = MagicMock()
        reply_result.tweet_id = "tweet-456"
        twitter.post_tweet_reply = MagicMock(return_value=reply_result)
        twitter.enabled = True
        agent = make_agent()
        agent._thread_ids["KXBTC-001"] = "tweet-111"
        insight = make_insight(ticker="KXBTC-001")
        with patch("agents.telegram_agent.get_telegram_agent", return_value=telegram), \
             patch("agents.twitter_agent.get_twitter_agent", return_value=twitter):
            await agent.handle_insight(insight)
        twitter.post_tweet_reply.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_increments_error_count(self):
        telegram = MagicMock()
        telegram.send_message = AsyncMock(side_effect=Exception("Telegram down"))
        twitter = MagicMock()
        tweet_result = MagicMock()
        tweet_result.tweet_id = None
        twitter.post_tweet = MagicMock(return_value=tweet_result)
        twitter.enabled = True
        agent = make_agent()
        insight = make_insight()
        with patch("agents.telegram_agent.get_telegram_agent", return_value=telegram), \
             patch("agents.twitter_agent.get_twitter_agent", return_value=twitter):
            await agent.handle_insight(insight)
        assert agent._stats["errors"] >= 1


# ── Status dict ───────────────────────────────────────────────────────────────

class TestNewsAgentStatus:
    def test_status_includes_totals(self):
        agent = make_agent()
        agent._stats["total_processed"] = 10
        agent._stats["total_telegram"] = 8
        agent._stats["total_x"] = 6
        agent._stats["skipped_cooldown"] = 2
        status = agent.summary()
        assert status["total_processed"] == 10
        assert status["total_telegram"] == 8
        assert status["total_x"] == 6
        assert status["skipped_cooldown"] == 2

    def test_status_includes_recent_posts(self):
        from merid.publishing.kalshi_news_agent import PostRecord
        agent = make_agent()
        agent._post_history = [PostRecord(
            ticker="KXBTC-001", category="Crypto", action="swing",
            telegram_sent=True, x_tweet_id="123", text_preview="test"
        )]
        status = agent.summary()
        assert len(status["recent_posts"]) == 1

    def test_status_includes_category_cooldowns(self):
        agent = make_agent()
        agent._last_post_ts["Crypto"] = time.time()
        status = agent.summary()
        assert "Crypto" in status["category_cooldowns"]
        assert status["category_cooldowns"]["Crypto"] > 0


# ── Cooldown constants ────────────────────────────────────────────────────────

class TestCooldownConstants:
    def test_all_categories_have_cooldown(self):
        expected = {"Trending", "Politics", "Sports", "Culture", "Crypto",
                    "Climate", "Economics", "Mentions", "Companies",
                    "Financials", "Tech & Science"}
        assert expected.issubset(set(CATEGORY_COOLDOWNS.keys()))

    def test_trending_has_shortest_cooldown(self):
        assert CATEGORY_COOLDOWNS["Trending"] <= min(
            v for k, v in CATEGORY_COOLDOWNS.items() if k != "Trending"
        )

    def test_climate_has_long_cooldown(self):
        assert CATEGORY_COOLDOWNS["Climate"] >= 1200  # at least 20 min
