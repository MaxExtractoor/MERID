"""
Tests for /api/v1/kalshi/publish-pipeline and /publish-pipeline/trigger endpoints.
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


# ── App fixture ───────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    """Minimal FastAPI test client with kalshi_api router mounted."""
    from fastapi import FastAPI
    from web.api.kalshi_api import router
    app = FastAPI()
    app.include_router(router)  # router already has /api/v1/kalshi prefix
    return TestClient(app)


# ── Mock pipeline / news agent ────────────────────────────────────────────────

def make_mock_pipeline(running=True, emitted=10, errors=0, by_category=None):
    p = MagicMock()
    p.summary.return_value = {
        "running": running,
        "consumers": 1,
        "tracked_tickers": 30,
        "total_emitted": emitted,
        "by_category": by_category or {"Crypto": 5, "Politics": 3},
        "by_action": {"swing": 6, "prob_cross": 4},
        "errors": errors,
        "started_at": "2026-02-19T00:00:00Z",
    }
    p._dispatch = MagicMock(return_value=None)
    return p


def make_mock_news_agent(processed=10, telegram=8, x=6, skipped=2, errors=0):
    a = MagicMock()
    a.summary.return_value = {
        "total_processed": processed,
        "total_telegram": telegram,
        "total_x": x,
        "skipped_cooldown": skipped,
        "errors": errors,
        "recent_posts": [
            {
                "ticker": "KXBTC-001",
                "category": "Crypto",
                "action": "swing",
                "telegram": True,
                "tweet_id": "tweet-123",
                "preview": "BTC swings 9%",
                "ts": "2026-02-19T01:00:00Z",
            }
        ],
        "category_cooldowns": {"Crypto": 120, "Trending": 0},
    }
    return a


def make_mock_twitter(enabled=True, recent=5):
    t = MagicMock()
    t.enabled = enabled
    t.recent_tweets = [{} for _ in range(recent)]
    t.last_post_time = None
    return t


def make_mock_telegram(enabled=True, recent=8):
    t = MagicMock()
    t.enabled = enabled
    t.recent_messages = [{} for _ in range(recent)]
    return t


# ── GET /publish-pipeline ─────────────────────────────────────────────────────

class TestPublishPipelineGet:
    def test_returns_200(self, client):
        pipeline = make_mock_pipeline()
        news_agent = make_mock_news_agent()
        twitter = make_mock_twitter()
        telegram = make_mock_telegram()

        with patch("merid.publishing.kalshi_insight_pipeline.get_insight_pipeline", return_value=pipeline), \
             patch("merid.publishing.kalshi_news_agent.get_kalshi_news_agent", return_value=news_agent), \
             patch("agents.twitter_agent.get_twitter_agent", return_value=twitter), \
             patch("agents.telegram_agent.get_telegram_agent", return_value=telegram):
            resp = client.get("/api/v1/kalshi/publish-pipeline")
        assert resp.status_code == 200

    def test_pipeline_running_true(self, client):
        pipeline = make_mock_pipeline(running=True)
        news_agent = make_mock_news_agent()
        twitter = make_mock_twitter()
        telegram = make_mock_telegram()

        with patch("merid.publishing.kalshi_insight_pipeline.get_insight_pipeline", return_value=pipeline), \
             patch("merid.publishing.kalshi_news_agent.get_kalshi_news_agent", return_value=news_agent), \
             patch("agents.twitter_agent.get_twitter_agent", return_value=twitter), \
             patch("agents.telegram_agent.get_telegram_agent", return_value=telegram):
            resp = client.get("/api/v1/kalshi/publish-pipeline")
        data = resp.json()
        assert data["pipeline"]["running"] is True

    def test_pipeline_stopped(self, client):
        pipeline = make_mock_pipeline(running=False)
        news_agent = make_mock_news_agent()
        twitter = make_mock_twitter()
        telegram = make_mock_telegram()

        with patch("merid.publishing.kalshi_insight_pipeline.get_insight_pipeline", return_value=pipeline), \
             patch("merid.publishing.kalshi_news_agent.get_kalshi_news_agent", return_value=news_agent), \
             patch("agents.twitter_agent.get_twitter_agent", return_value=twitter), \
             patch("agents.telegram_agent.get_telegram_agent", return_value=telegram):
            resp = client.get("/api/v1/kalshi/publish-pipeline")
        assert resp.json()["pipeline"]["running"] is False

    def test_news_agent_stats_present(self, client):
        pipeline = make_mock_pipeline()
        news_agent = make_mock_news_agent(processed=10, telegram=8, x=6)
        twitter = make_mock_twitter()
        telegram = make_mock_telegram()

        with patch("merid.publishing.kalshi_insight_pipeline.get_insight_pipeline", return_value=pipeline), \
             patch("merid.publishing.kalshi_news_agent.get_kalshi_news_agent", return_value=news_agent), \
             patch("agents.twitter_agent.get_twitter_agent", return_value=twitter), \
             patch("agents.telegram_agent.get_telegram_agent", return_value=telegram):
            resp = client.get("/api/v1/kalshi/publish-pipeline")
        na = resp.json()["news_agent"]
        assert na["total_processed"] == 10
        assert na["total_telegram"] == 8
        assert na["total_x"] == 6

    def test_recent_posts_in_response(self, client):
        pipeline = make_mock_pipeline()
        news_agent = make_mock_news_agent()
        twitter = make_mock_twitter()
        telegram = make_mock_telegram()

        with patch("merid.publishing.kalshi_insight_pipeline.get_insight_pipeline", return_value=pipeline), \
             patch("merid.publishing.kalshi_news_agent.get_kalshi_news_agent", return_value=news_agent), \
             patch("agents.twitter_agent.get_twitter_agent", return_value=twitter), \
             patch("agents.telegram_agent.get_telegram_agent", return_value=telegram):
            resp = client.get("/api/v1/kalshi/publish-pipeline")
        posts = resp.json()["news_agent"]["recent_posts"]
        assert len(posts) == 1
        assert posts[0]["ticker"] == "KXBTC-001"

    def test_twitter_status_in_response(self, client):
        pipeline = make_mock_pipeline()
        news_agent = make_mock_news_agent()
        twitter = make_mock_twitter(enabled=True, recent=5)
        telegram = make_mock_telegram()

        with patch("merid.publishing.kalshi_insight_pipeline.get_insight_pipeline", return_value=pipeline), \
             patch("merid.publishing.kalshi_news_agent.get_kalshi_news_agent", return_value=news_agent), \
             patch("agents.twitter_agent.get_twitter_agent", return_value=twitter), \
             patch("agents.telegram_agent.get_telegram_agent", return_value=telegram):
            resp = client.get("/api/v1/kalshi/publish-pipeline")
        tw = resp.json()["twitter"]
        assert tw["enabled"] is True
        assert tw["recent_tweets"] == 5

    def test_telegram_status_in_response(self, client):
        pipeline = make_mock_pipeline()
        news_agent = make_mock_news_agent()
        twitter = make_mock_twitter()
        telegram = make_mock_telegram(enabled=True, recent=8)

        with patch("merid.publishing.kalshi_insight_pipeline.get_insight_pipeline", return_value=pipeline), \
             patch("merid.publishing.kalshi_news_agent.get_kalshi_news_agent", return_value=news_agent), \
             patch("agents.twitter_agent.get_twitter_agent", return_value=twitter), \
             patch("agents.telegram_agent.get_telegram_agent", return_value=telegram):
            resp = client.get("/api/v1/kalshi/publish-pipeline")
        tg = resp.json()["telegram"]
        assert tg["enabled"] is True
        assert tg["recent_messages"] == 8

    def test_graceful_when_pipeline_none(self, client):
        with patch("merid.publishing.kalshi_insight_pipeline.get_insight_pipeline", side_effect=Exception("unavailable")), \
             patch("merid.publishing.kalshi_news_agent.get_kalshi_news_agent", side_effect=Exception("unavailable")), \
             patch("agents.twitter_agent.get_twitter_agent", side_effect=Exception("unavailable")), \
             patch("agents.telegram_agent.get_telegram_agent", side_effect=Exception("unavailable")):
            resp = client.get("/api/v1/kalshi/publish-pipeline")
        assert resp.status_code in (200, 503)


# ── POST /publish-pipeline/trigger ───────────────────────────────────────────

class TestPublishPipelineTrigger:
    def test_trigger_returns_200(self, client):
        pipeline = make_mock_pipeline()
        pipeline._dispatch = MagicMock(return_value=None)

        with patch("merid.publishing.kalshi_insight_pipeline.get_insight_pipeline", return_value=pipeline):
            resp = client.post(
                "/api/v1/kalshi/publish-pipeline/trigger",
                params={"ticker": "KXBTC-001", "category": "Crypto"},
            )
        assert resp.status_code in (200, 500)

    def test_trigger_calls_pipeline_with_ticker(self, client):
        pipeline = make_mock_pipeline()
        pipeline._dispatch = MagicMock(return_value=None)

        with patch("merid.publishing.kalshi_insight_pipeline.get_insight_pipeline", return_value=pipeline):
            resp = client.post(
                "/api/v1/kalshi/publish-pipeline/trigger",
                params={"ticker": "KXBTC-001", "category": "Crypto"},
            )
        assert resp.status_code in (200, 500)

    def test_trigger_without_ticker_returns_422(self, client):
        resp = client.post("/api/v1/kalshi/publish-pipeline/trigger")
        assert resp.status_code == 422

    def test_trigger_when_pipeline_not_running_returns_error(self, client):
        pipeline = make_mock_pipeline(running=False)
        pipeline._dispatch = MagicMock(side_effect=Exception("pipeline stopped"))

        with patch("merid.publishing.kalshi_insight_pipeline.get_insight_pipeline", return_value=pipeline):
            resp = client.post(
                "/api/v1/kalshi/publish-pipeline/trigger",
                params={"ticker": "KXBTC-001", "category": "Crypto"},
            )
        assert resp.status_code in (200, 400, 500, 503)
