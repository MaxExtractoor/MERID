"""test_sentiment_config.py — Unit tests for sentiment configuration.

NOTE: This test is marked as sentiment_research and should be excluded from
kalshi_crypto_15m_v2 production test runs. Sentiment is research-only and
must not influence live 15m Kalshi trading decisions.
"""
import hashlib
from collections import deque
from datetime import datetime, timezone

import pytest

# ── Imports under test ────────────────────────────────────────────────────

import importlib
import sys

# Import directly from submodules to avoid __init__.py eager import chain
_news_config = importlib.import_module("merid.sentiment.news_config")
NEWS_TOPICS = _news_config.NEWS_TOPICS
CRYPTO_ASSETS = _news_config.CRYPTO_ASSETS

_nia = importlib.import_module("merid.sentiment.news_ingestion_agent")
_label_from_score = _nia._label_from_score
_dedupe_key = _nia._dedupe_key

_ha = importlib.import_module("merid.sentiment.hashtag_agent")
_TagHistory = _ha._TagHistory
HashtagSentiment = _ha.HashtagSentiment
HashtagSignal = _ha.HashtagSignal

_sbv2 = importlib.import_module("merid.sentiment.sentiment_bus_v2")
_ScoreWindow = _sbv2._ScoreWindow


# ═══════════════════════════════════════════════════════════════════════════
# §1  NEWS_TOPICS config completeness
# ═══════════════════════════════════════════════════════════════════════════

class TestNewsTopicsConfig:

    def test_news_topics_is_dict(self):
        assert isinstance(NEWS_TOPICS, dict)

    def test_news_topics_not_empty(self):
        assert len(NEWS_TOPICS) >= 3

    def test_each_topic_has_required_fields(self):
        required = {"keywords", "hashtags", "name", "newsapi_keywords"}
        for topic_name, cfg in NEWS_TOPICS.items():
            for field in required:
                assert hasattr(cfg, field), \
                    f"Topic '{topic_name}' missing field '{field}'"

    def test_each_topic_keywords_nonempty(self):
        for name, cfg in NEWS_TOPICS.items():
            kws = cfg.keywords
            assert len(kws) >= 1, f"Topic '{name}' has no keywords"

    def test_each_topic_hashtags_nonempty(self):
        for name, cfg in NEWS_TOPICS.items():
            tags = cfg.hashtags
            assert len(tags) >= 1, f"Topic '{name}' has no hashtags"

    def test_category_name_is_string(self):
        for name, cfg in NEWS_TOPICS.items():
            cat = cfg.name
            assert isinstance(cat, str) and cat, f"Topic '{name}' name is blank"


# ═══════════════════════════════════════════════════════════════════════════
# §2  CRYPTO_ASSETS config completeness
# ═══════════════════════════════════════════════════════════════════════════

class TestCryptoAssetsConfig:

    def test_crypto_assets_is_dict(self):
        assert isinstance(CRYPTO_ASSETS, dict)

    def test_btc_present(self):
        assert "BTC" in CRYPTO_ASSETS

    def test_eth_present(self):
        assert "ETH" in CRYPTO_ASSETS

    def test_each_asset_has_hashtags(self):
        for symbol, cfg in CRYPTO_ASSETS.items():
            tags = cfg.hashtags
            assert len(tags) >= 1, f"Asset '{symbol}' has no hashtags"

    def test_each_asset_has_keywords(self):
        for symbol, cfg in CRYPTO_ASSETS.items():
            kws = cfg.newsapi_keywords
            assert len(kws) >= 1, f"Asset '{symbol}' has no newsapi_keywords"

    def test_no_duplicate_symbols(self):
        keys = list(CRYPTO_ASSETS.keys())
        assert len(keys) == len(set(keys))


# ═══════════════════════════════════════════════════════════════════════════
# §3  _label_from_score — pure function, no mocks
# ═══════════════════════════════════════════════════════════════════════════

class TestLabelFromScore:

    def test_positive_above_threshold(self):
        assert _label_from_score(0.06) == "positive"

    def test_positive_at_boundary(self):
        assert _label_from_score(0.051) == "positive"

    def test_negative_below_threshold(self):
        assert _label_from_score(-0.06) == "negative"

    def test_negative_at_boundary(self):
        assert _label_from_score(-0.051) == "negative"

    def test_neutral_zero(self):
        assert _label_from_score(0.0) == "neutral"

    def test_neutral_just_inside_positive(self):
        assert _label_from_score(0.05) == "neutral"

    def test_neutral_just_inside_negative(self):
        assert _label_from_score(-0.05) == "neutral"

    def test_extreme_positive(self):
        assert _label_from_score(1.0) == "positive"

    def test_extreme_negative(self):
        assert _label_from_score(-1.0) == "negative"


# ═══════════════════════════════════════════════════════════════════════════
# §4  _dedupe_key — determinism and collision resistance
# ═══════════════════════════════════════════════════════════════════════════

class TestDedupeKey:

    def test_deterministic(self):
        k1 = _dedupe_key("Bitcoin surges", "https://example.com/1")
        k2 = _dedupe_key("Bitcoin surges", "https://example.com/1")
        assert k1 == k2

    def test_length_12(self):
        k = _dedupe_key("headline", "url")
        assert len(k) == 12

    def test_different_headline_different_key(self):
        k1 = _dedupe_key("Bitcoin up", "https://example.com/1")
        k2 = _dedupe_key("Bitcoin down", "https://example.com/1")
        assert k1 != k2

    def test_different_url_different_key(self):
        k1 = _dedupe_key("Bitcoin up", "https://a.com/1")
        k2 = _dedupe_key("Bitcoin up", "https://b.com/2")
        assert k1 != k2

    def test_matches_manual_md5(self):
        headline, url = "Test headline", "https://test.com"
        expected = hashlib.md5(f"{headline}{url}".encode()).hexdigest()[:12]
        assert _dedupe_key(headline, url) == expected

    def test_empty_strings(self):
        k = _dedupe_key("", "")
        assert len(k) == 12


# ═══════════════════════════════════════════════════════════════════════════
# §5  _TagHistory — rolling window, avg_score, avg_volume, maxlen
# ═══════════════════════════════════════════════════════════════════════════

class TestTagHistory:

    def test_empty_avg_score_is_zero(self):
        h = _TagHistory()
        assert h.avg_score == 0.0

    def test_empty_avg_volume_is_zero(self):
        h = _TagHistory()
        assert h.avg_volume == 0.0

    def test_single_push(self):
        h = _TagHistory()
        h.push(0.5, 100)
        assert h.avg_score == pytest.approx(0.5)
        assert h.avg_volume == pytest.approx(100.0)

    def test_avg_score_multiple(self):
        h = _TagHistory()
        h.push(0.4, 10)
        h.push(0.6, 10)
        assert h.avg_score == pytest.approx(0.5)

    def test_avg_volume_multiple(self):
        h = _TagHistory()
        h.push(0.0, 100)
        h.push(0.0, 200)
        assert h.avg_volume == pytest.approx(150.0)

    def test_maxlen_20_evicts_oldest(self):
        h = _TagHistory()
        for i in range(25):
            h.push(float(i), i)
        assert len(h.scores) == 20
        assert len(h.volumes) == 20

    def test_maxlen_evicts_correct_value(self):
        h = _TagHistory()
        for i in range(21):
            h.push(float(i), i)
        # oldest (0) should be gone; newest (20) should be present
        assert 0.0 not in h.scores
        assert 20.0 in h.scores

    def test_push_updates_timestamps(self):
        h = _TagHistory()
        h.push(0.1, 5)
        assert len(h.timestamps) == 1

    def test_negative_scores(self):
        h = _TagHistory()
        h.push(-0.8, 50)
        h.push(-0.4, 50)
        assert h.avg_score == pytest.approx(-0.6)


# ═══════════════════════════════════════════════════════════════════════════
# §6  _ScoreWindow — volume_weighted_avg, simple_avg, kalman_smooth, count
# ═══════════════════════════════════════════════════════════════════════════

class TestScoreWindow:

    def test_empty_volume_weighted_avg(self):
        w = _ScoreWindow()
        assert w.volume_weighted_avg() == 0.0

    def test_empty_simple_avg(self):
        w = _ScoreWindow()
        assert w.simple_avg() == 0.0

    def test_empty_kalman_smooth(self):
        w = _ScoreWindow()
        assert w.kalman_smooth() == 0.0

    def test_empty_count(self):
        w = _ScoreWindow()
        assert w.count == 0

    def test_single_push_count(self):
        w = _ScoreWindow()
        w.push(0.5, 10)
        assert w.count == 1

    def test_volume_weighted_avg_equal_volumes(self):
        w = _ScoreWindow()
        w.push(0.2, 10)
        w.push(0.8, 10)
        assert w.volume_weighted_avg() == pytest.approx(0.5)

    def test_volume_weighted_avg_unequal_volumes(self):
        w = _ScoreWindow()
        w.push(0.0, 1)   # low weight
        w.push(1.0, 9)   # high weight
        # expected: (0*1 + 1*9) / 10 = 0.9
        assert w.volume_weighted_avg() == pytest.approx(0.9)

    def test_simple_avg(self):
        w = _ScoreWindow()
        w.push(0.3, 1)
        w.push(0.7, 1)
        assert w.simple_avg() == pytest.approx(0.5)

    def test_kalman_smooth_single(self):
        w = _ScoreWindow()
        w.push(0.6, 1)
        assert w.kalman_smooth() == pytest.approx(0.6)

    def test_kalman_smooth_converges_toward_last(self):
        """With alpha=0.3, smoothed should be between first and last value."""
        w = _ScoreWindow()
        w.push(0.0, 1)
        w.push(1.0, 1)
        result = w.kalman_smooth()
        assert 0.0 < result < 1.0

    def test_kalman_smooth_alpha_0_3(self):
        """Verify exact alpha=0.3 formula: smoothed = 0.3*s + 0.7*prev."""
        w = _ScoreWindow()
        w.push(0.0, 1)
        w.push(1.0, 1)
        # smoothed starts at 0.0, then: 0.3*1.0 + 0.7*0.0 = 0.3
        assert w.kalman_smooth() == pytest.approx(0.3)

    def test_maxlen_respected(self):
        w = _ScoreWindow(maxlen=5)
        for i in range(10):
            w.push(float(i), 1)
        assert w.count == 5

    def test_volume_zero_falls_back_to_simple_avg(self):
        """push(score, 0) should still produce a valid avg (volume clamped to 1)."""
        w = _ScoreWindow()
        w.push(0.4, 0)
        w.push(0.6, 0)
        # volumes clamped to 1 each → equal weight → avg = 0.5
        assert w.volume_weighted_avg() == pytest.approx(0.5)

    def test_negative_scores_volume_weighted(self):
        w = _ScoreWindow()
        w.push(-0.6, 3)
        w.push(-0.3, 1)
        # (-0.6*3 + -0.3*1) / 4 = (-1.8 - 0.3) / 4 = -2.1/4 = -0.525
        assert w.volume_weighted_avg() == pytest.approx(-0.525)
