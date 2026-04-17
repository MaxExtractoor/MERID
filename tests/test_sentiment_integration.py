"""test_sentiment_integration.py — Integration tests for HashtagMonitor lifecycle,
SentimentBundle overlay, combine_sentiment blend, API endpoints, and smoke tests
across Politics / Crypto / Culture categories.

Strategy:
- HashtagMonitor: test stats tracking, force-cycle, Telegram gate, get_stats shape.
- SentimentBundle: test pure dataclass helpers (no network).
- combine_sentiment: patch all external calls, verify blend math.
- API endpoints: import-level smoke tests + response shape checks.
- Smoke tests: end-to-end data flow through bus → context → bundle.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.sentiment.hashtag_monitor import HashtagMonitor, MonitorStats, get_hashtag_monitor
from merid.sentiment.sentiment_bundle import SentimentBundle
from merid.sentiment.sentiment_bus_v2 import SentimentBusV2
from merid.sentiment.hashtag_agent import HashtagSentiment, HashtagSignal
from merid.sentiment.news_ingestion_agent import AggregatedNewsSentiment


# ── Helpers ───────────────────────────────────────────────────────────────

def _reset_bus() -> SentimentBusV2:
    SentimentBusV2._instance = None
    return SentimentBusV2()


def _make_signal(
    asset_or_event: str = "BTC",
    direction: str = "bullish",
    strength: float = 0.7,
    reason: str = "hashtags_bullish",
    score: float = 0.5,
    volume: int = 100,
    category: str = "crypto",
) -> HashtagSignal:
    return HashtagSignal(
        asset_or_event=asset_or_event,
        direction=direction,
        strength=strength,
        reason=reason,
        score=score,
        volume=volume,
        tags=["#BTC"],
        category=category,
        timestamp=datetime.now(timezone.utc),
    )


def _make_bundle(
    asset: str = "BTC",
    twitter: float = 0.3,
    reddit: float = 0.2,
    fg_index: int = 50,
    combined: float = 0.25,
    confidence: float = 0.7,
    vader_signal: str = "bullish",
    kalshi_adjustment: float = 0.01,
) -> SentimentBundle:
    return SentimentBundle(
        asset=asset,
        twitter=twitter,
        reddit=reddit,
        fg_index=fg_index,
        combined=combined,
        fg_norm=fg_index / 100.0,
        confidence=confidence,
        timestamp=datetime.now(timezone.utc),
        vader_signal=vader_signal,
        kalshi_adjustment=kalshi_adjustment,
    )


# ═══════════════════════════════════════════════════════════════════════════
# §1  MonitorStats dataclass
# ═══════════════════════════════════════════════════════════════════════════

class TestMonitorStats:

    def test_defaults_zero(self):
        s = MonitorStats()
        assert s.hashtag_cycles == 0
        assert s.news_cycles == 0
        assert s.asset_cycles == 0
        assert s.signals_generated == 0
        assert s.errors == 0
        assert s.last_hashtag_cycle_ts is None
        assert s.last_news_cycle_ts is None

    def test_increment(self):
        s = MonitorStats()
        s.hashtag_cycles += 1
        s.signals_generated += 3
        assert s.hashtag_cycles == 1
        assert s.signals_generated == 3


# ═══════════════════════════════════════════════════════════════════════════
# §2  HashtagMonitor — lifecycle and stats
# ═══════════════════════════════════════════════════════════════════════════

class TestHashtagMonitorLifecycle:

    def _fresh_monitor(self) -> HashtagMonitor:
        return HashtagMonitor(hashtag_interval=9999, news_interval=9999,
                              asset_cycle_interval=9999)

    def test_initial_not_running(self):
        m = self._fresh_monitor()
        assert m._running is False

    def test_initial_stats_zero(self):
        m = self._fresh_monitor()
        assert m.stats.hashtag_cycles == 0
        assert m.stats.signals_generated == 0

    def test_get_stats_shape(self):
        m = self._fresh_monitor()
        s = m.get_stats()
        for key in ("hashtag_cycles", "news_cycles", "asset_cycles",
                    "signals_generated", "errors", "running"):
            assert key in s, f"Missing key: {key}"

    def test_get_stats_running_false_initially(self):
        m = self._fresh_monitor()
        assert m.get_stats()["running"] is False

    def test_get_latest_signals_empty_initially(self):
        m = self._fresh_monitor()
        assert m.get_latest_signals() == []

    def test_get_latest_signals_returns_copy(self):
        m = self._fresh_monitor()
        m._last_signals = [_make_signal()]
        result = m.get_latest_signals()
        result.clear()
        assert len(m._last_signals) == 1  # original unchanged

    def test_start_sets_running(self):
        m = self._fresh_monitor()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(m.start())
            assert m._running is True
            assert len(m._tasks) == 3
        finally:
            loop.run_until_complete(m.stop())
            loop.close()

    def test_stop_clears_tasks(self):
        m = self._fresh_monitor()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(m.start())
            loop.run_until_complete(m.stop())
            assert m._running is False
            assert m._tasks == []
        finally:
            loop.close()

    def test_double_start_is_idempotent(self):
        m = self._fresh_monitor()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(m.start())
            loop.run_until_complete(m.start())  # second call is no-op
            assert len(m._tasks) == 3
        finally:
            loop.run_until_complete(m.stop())
            loop.close()


# ═══════════════════════════════════════════════════════════════════════════
# §3  HashtagMonitor — force-cycle and Telegram gate
# ═══════════════════════════════════════════════════════════════════════════

class TestHashtagMonitorForceCycle:

    def _fresh_monitor(self) -> HashtagMonitor:
        return HashtagMonitor(hashtag_interval=9999, news_interval=9999,
                              asset_cycle_interval=9999)

    def test_force_hashtag_cycle_increments_counter(self):
        m = self._fresh_monitor()
        mock_agent = MagicMock()
        mock_agent.run_cycle = AsyncMock(return_value=[])
        mock_agent.generate_signals = MagicMock(return_value=[])
        mock_bus = MagicMock()
        with patch.object(m, "_get_hashtag_agent", return_value=mock_agent), \
             patch.object(m, "_get_bus", return_value=mock_bus), \
             patch.object(m, "_get_fg", return_value=50):
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(m.force_hashtag_cycle())
            finally:
                loop.close()
        assert m.stats.hashtag_cycles == 1

    def test_force_hashtag_cycle_returns_signals(self):
        m = self._fresh_monitor()
        sig = _make_signal()
        mock_agent = MagicMock()
        mock_agent.run_cycle = AsyncMock(return_value=[])
        mock_agent.generate_signals = MagicMock(return_value=[sig])
        mock_bus = MagicMock()
        with patch.object(m, "_get_hashtag_agent", return_value=mock_agent), \
             patch.object(m, "_get_bus", return_value=mock_bus), \
             patch.object(m, "_get_fg", return_value=50):
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(m.force_hashtag_cycle())
            finally:
                loop.close()
        assert result == [sig]

    def test_force_news_cycle_increments_counter(self):
        m = self._fresh_monitor()
        mock_agent = MagicMock()
        mock_agent.run_cycle = AsyncMock(return_value=None)
        with patch.object(m, "_get_news_agent", return_value=mock_agent):
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(m.force_news_cycle())
            finally:
                loop.close()
        assert m.stats.news_cycles == 1

    def test_telegram_gate_skips_weak_signals(self):
        m = self._fresh_monitor()
        weak = _make_signal(strength=0.3)
        with patch("merid.sentiment.hashtag_monitor.TELEGRAM_ALERTS_ENABLED", True):
            with patch("core.alerts.get_alert_manager") as mock_mgr:
                m._publish_signal_telegram([weak])
                mock_mgr.assert_not_called()

    def test_telegram_gate_disabled_skips_all(self):
        m = self._fresh_monitor()
        strong = _make_signal(strength=0.9)
        with patch("merid.sentiment.hashtag_monitor.TELEGRAM_ALERTS_ENABLED", False):
            with patch("core.alerts.get_alert_manager") as mock_mgr:
                m._publish_signal_telegram([strong])
                mock_mgr.assert_not_called()

    def test_cycle_error_increments_error_counter(self):
        m = self._fresh_monitor()
        mock_agent = MagicMock()
        mock_agent.run_cycle = AsyncMock(side_effect=RuntimeError("network down"))
        with patch.object(m, "_get_hashtag_agent", return_value=mock_agent):
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(m._run_hashtag_cycle())
            finally:
                loop.close()
        assert m.stats.errors == 1
        assert m.stats.hashtag_cycles == 0


# ═══════════════════════════════════════════════════════════════════════════
# §4  SentimentBundle — pure dataclass helpers
# ═══════════════════════════════════════════════════════════════════════════

class TestSentimentBundle:

    def test_is_bullish_above_threshold(self):
        b = _make_bundle(combined=0.3)
        assert b.is_bullish(threshold=0.2) is True

    def test_is_bullish_below_threshold(self):
        b = _make_bundle(combined=0.1)
        assert b.is_bullish(threshold=0.2) is False

    def test_is_bearish_below_threshold(self):
        b = _make_bundle(combined=-0.3)
        assert b.is_bearish(threshold=-0.2) is True

    def test_is_bearish_above_threshold(self):
        b = _make_bundle(combined=-0.1)
        assert b.is_bearish(threshold=-0.2) is False

    def test_contrarian_extreme_fear_positive(self):
        b = _make_bundle(fg_index=15, combined=0.3)
        assert b.is_contrarian_setup() is True

    def test_contrarian_extreme_greed_negative(self):
        b = _make_bundle(fg_index=85, combined=-0.3)
        assert b.is_contrarian_setup() is True

    def test_not_contrarian_neutral_fg(self):
        b = _make_bundle(fg_index=50, combined=0.3)
        assert b.is_contrarian_setup() is False

    def test_position_size_multiplier_extreme_fg(self):
        b = _make_bundle(fg_index=10)
        assert b.get_position_size_multiplier() < 1.0

    def test_position_size_multiplier_neutral_fg(self):
        b = _make_bundle(fg_index=50, confidence=0.8)
        assert b.get_position_size_multiplier() == pytest.approx(1.0)

    def test_position_size_multiplier_low_confidence(self):
        b = _make_bundle(fg_index=50, confidence=0.3)
        assert b.get_position_size_multiplier() < 1.0

    def test_to_dict_has_required_keys(self):
        b = _make_bundle()
        d = b.to_dict()
        for key in ("asset", "twitter", "reddit", "fg_index", "fg_norm",
                    "combined", "confidence", "vader_signal",
                    "kalshi_adjustment", "timestamp"):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_timestamp_is_string(self):
        b = _make_bundle()
        assert isinstance(b.to_dict()["timestamp"], str)

    def test_fg_norm_range(self):
        for fg in (0, 25, 50, 75, 100):
            b = _make_bundle(fg_index=fg, combined=0.0)
            assert 0.0 <= b.fg_norm <= 1.0


# ═══════════════════════════════════════════════════════════════════════════
# §5  combine_sentiment — blend math with patched external calls
# ═══════════════════════════════════════════════════════════════════════════

class TestCombineSentiment:

    def _get_global_bus(self):
        """Return the global singleton bus (what combine_sentiment reads from)."""
        from merid.sentiment.sentiment_bus_v2 import get_sentiment_bus_v2
        return get_sentiment_bus_v2()

    def _call(self, tw: float = 0.4, rd: float = 0.2, fg: int = 50,
              hashtag: float = 0.0, news: float = 0.0) -> "SentimentBundle":
        from merid.sentiment.sentiment_bundle import combine_sentiment
        from merid.sentiment.hashtag_agent import HashtagSentiment

        # combine_sentiment reads from the global singleton
        bus = self._get_global_bus()
        # Inject hashtag + news into global bus so combine_sentiment picks them up
        if hashtag != 0.0:
            s = HashtagSentiment(
                tag="#BTC", score=hashtag, volume=100, category="crypto",
                asset="BTC", event_id=None, provider="twitter",
                timestamp=datetime.now(timezone.utc), confidence=0.7,
            )
            bus.update_hashtags([s])
        if news != 0.0:
            agg = AggregatedNewsSentiment(
                key="crypto:BTC", category="crypto", asset="BTC",
                event_id=None, score=news, confidence=0.6,
                headline_count=5, provider_scores={"newsapi": news},
                label="positive" if news > 0 else "negative",
                timestamp=datetime.now(timezone.utc),
            )
            bus.update_news([agg])

        with patch("merid.sentiment.twitter_fetcher.quick_twitter_sentiment",
                   return_value=tw), \
             patch("merid.sentiment.reddit_scraper.quick_reddit_sentiment",
                   return_value=rd), \
             patch("merid.sentiment.cfgi_client.quick_fg", return_value=fg):
            return combine_sentiment("BTC")

    def test_returns_sentiment_bundle(self):
        from merid.sentiment.sentiment_bundle import SentimentBundle
        result = self._call()
        assert isinstance(result, SentimentBundle)
        assert result.asset == "BTC"

    def test_twitter_stored(self):
        result = self._call(tw=0.6)
        assert result.twitter == pytest.approx(0.6)

    def test_reddit_stored(self):
        result = self._call(rd=0.4)
        assert result.reddit == pytest.approx(0.4)

    def test_fg_index_stored(self):
        result = self._call(fg=30)
        assert result.fg_index == 30

    def test_fg_norm_range(self):
        result = self._call(fg=75)
        assert result.fg_norm == pytest.approx(0.75)

    def test_combined_in_range(self):
        result = self._call(tw=0.5, rd=0.3, fg=50)
        assert -1.0 <= result.combined <= 1.0

    def test_confidence_in_range(self):
        result = self._call()
        assert 0.0 <= result.confidence <= 1.0

    def test_hashtag_overlay_shifts_combined(self):
        """Positive hashtag score should push combined higher."""
        base = self._call(tw=0.0, rd=0.0, fg=50, hashtag=0.0)
        with_htag = self._call(tw=0.0, rd=0.0, fg=50, hashtag=0.9)
        assert with_htag.combined > base.combined

    def test_news_overlay_shifts_combined(self):
        """Positive news score should push combined higher."""
        base = self._call(tw=0.0, rd=0.0, fg=50, news=0.0)
        with_news = self._call(tw=0.0, rd=0.0, fg=50, news=0.9)
        assert with_news.combined > base.combined

    def test_kalshi_adjustment_range(self):
        result = self._call()
        assert -0.1 <= result.kalshi_adjustment <= 0.1


# ═══════════════════════════════════════════════════════════════════════════
# §6  get_risk_overlay — keys and value ranges
# ═══════════════════════════════════════════════════════════════════════════

class TestGetRiskOverlay:

    def setup_method(self):
        self.bus = _reset_bus()

    def _overlay(self, asset: str = "BTC") -> dict:
        with patch.object(self.bus, "_get_fg", return_value=50), \
             patch.object(self.bus, "_get_social_score", return_value=(0.0, 0.5)):
            return self.bus.get_risk_overlay(asset)

    def test_returns_dict(self):
        overlay = self._overlay()
        assert isinstance(overlay, dict)

    def test_has_required_keys(self):
        overlay = self._overlay()
        for key in ("asset", "fg_index", "fg_regime", "combined_score",
                    "should_reduce_size", "is_contrarian", "kalshi_prob_adjustment",
                    "confidence"):
            assert key in overlay, f"Missing key: {key}"

    def test_asset_key_correct(self):
        overlay = self._overlay("ETH")
        assert overlay["asset"] == "ETH"

    def test_fg_regime_present(self):
        overlay = self._overlay()
        assert overlay["fg_regime"] in ("extreme_fear", "fear", "neutral",
                                         "greed", "extreme_greed")

    def test_counts_after_ingestion(self):
        from merid.sentiment.hashtag_agent import HashtagSentiment
        s = HashtagSentiment(
            tag="#BTC", score=0.4, volume=100, category="crypto",
            asset="BTC", event_id=None, provider="twitter",
            timestamp=datetime.now(timezone.utc), confidence=0.7,
        )
        self.bus.update_hashtags([s])
        overlay = self._overlay("BTC")
        assert overlay["asset"] == "BTC"


# ═══════════════════════════════════════════════════════════════════════════
# §7  Smoke tests — Politics / Crypto / Culture end-to-end
# ═══════════════════════════════════════════════════════════════════════════

class TestSmokeEndToEnd:
    """Verify data flows from ingestion → bus → context without errors."""

    def setup_method(self):
        self.bus = _reset_bus()

    def _ingest_hashtag(self, asset: Optional[str], event_id: Optional[str],
                        category: str, score: float, volume: int) -> None:
        from merid.sentiment.hashtag_agent import HashtagSentiment
        s = HashtagSentiment(
            tag=f"#{asset or event_id}", score=score, volume=volume,
            category=category, asset=asset, event_id=event_id,
            provider="twitter", timestamp=datetime.now(timezone.utc),
            confidence=0.6,
        )
        self.bus.update_hashtags([s])

    def _ingest_news(self, key: str, category: str, asset: Optional[str],
                     event_id: Optional[str], score: float) -> None:
        agg = AggregatedNewsSentiment(
            key=key, category=category, asset=asset, event_id=event_id,
            score=score, confidence=0.6, headline_count=3,
            provider_scores={"newsapi": score},
            label="positive" if score > 0 else "negative",
            timestamp=datetime.now(timezone.utc),
        )
        self.bus.update_news([agg])

    # ── Crypto ────────────────────────────────────────────────────────

    def test_crypto_btc_asset_context(self):
        self._ingest_hashtag("BTC", None, "crypto", 0.5, 200)
        self._ingest_news("crypto:BTC", "crypto", "BTC", None, 0.4)
        with patch.object(self.bus, "_get_fg", return_value=55), \
             patch.object(self.bus, "_get_social_score", return_value=(0.3, 0.7)):
            ctx = self.bus.get_asset_context("BTC")
        assert ctx.asset == "BTC"
        assert ctx.hashtag_score == pytest.approx(0.5, abs=0.01)
        assert ctx.news_score == pytest.approx(0.4, abs=0.01)
        assert ctx.fg_regime == "neutral"

    def test_crypto_eth_asset_context(self):
        self._ingest_hashtag("ETH", None, "crypto", -0.3, 150)
        with patch.object(self.bus, "_get_fg", return_value=25), \
             patch.object(self.bus, "_get_social_score", return_value=(-0.2, 0.6)):
            ctx = self.bus.get_asset_context("ETH")
        assert ctx.fg_regime == "fear"
        assert ctx.hashtag_score < 0

    # ── Politics ──────────────────────────────────────────────────────

    def test_politics_event_context(self):
        self._ingest_news("politics:EVT-POL-001", "politics", None,
                          "EVT-POL-001", 0.3)
        self._ingest_hashtag(None, "EVT-POL-001", "politics", 0.2, 80)
        ctx = self.bus.get_event_context("EVT-POL-001", category="politics")
        assert ctx.event_id == "EVT-POL-001"
        assert ctx.category == "politics"
        # 0.5*0.3 + 0.5*0.2 = 0.25
        assert ctx.combined_score == pytest.approx(0.25, abs=0.01)
        assert ctx.label == "positive"

    def test_politics_negative_event(self):
        self._ingest_news("politics:EVT-POL-002", "politics", None,
                          "EVT-POL-002", -0.4)
        ctx = self.bus.get_event_context("EVT-POL-002", category="politics")
        assert ctx.label == "negative"

    # ── Culture ───────────────────────────────────────────────────────

    def test_culture_event_context(self):
        self._ingest_news("culture:EVT-CULT-001", "culture", None,
                          "EVT-CULT-001", 0.3)
        ctx = self.bus.get_event_context("EVT-CULT-001", category="culture")
        assert ctx.event_id == "EVT-CULT-001"
        assert ctx.category == "culture"
        assert ctx.label == "positive"

    def test_culture_neutral_event(self):
        ctx = self.bus.get_event_context("EVT-CULT-EMPTY", category="culture")
        assert ctx.label == "neutral"
        assert ctx.combined_score == pytest.approx(0.0)

    # ── Market context ────────────────────────────────────────────────

    def test_get_market_context_no_asset_no_event(self):
        from merid.sentiment.sentiment_bus_v2 import MarketSentimentContext
        ctx = self.bus.get_market_context("MKT-001", category="politics")
        assert isinstance(ctx, MarketSentimentContext)
        assert ctx.market_id == "MKT-001"

    def test_get_market_context_with_asset(self):
        self._ingest_hashtag("BTC", None, "crypto", 0.4, 100)
        with patch.object(self.bus, "_get_fg", return_value=50), \
             patch.object(self.bus, "_get_social_score", return_value=(0.3, 0.6)):
            ctx = self.bus.get_market_context("MKT-BTC", asset="BTC",
                                              category="crypto")
        assert ctx.asset_context is not None
        assert ctx.asset_context.asset == "BTC"

    def test_get_market_context_to_dict(self):
        ctx = self.bus.get_market_context("MKT-DICT", category="politics")
        d = ctx.to_dict()
        for key in ("market_id", "category", "combined_score", "confidence",
                    "signals", "timestamp"):
            assert key in d, f"Missing key: {key}"


# ═══════════════════════════════════════════════════════════════════════════
# §8  API endpoint smoke tests — import + route registration
# ═══════════════════════════════════════════════════════════════════════════

class TestSentimentApiEndpoints:

    def test_sentiment_api_importable(self):
        import web.api.sentiment_api as api
        assert api is not None

    def test_sentiment_router_exists(self):
        from web.api.sentiment_api import router
        assert router is not None

    def test_asset_sentiment_route_registered(self):
        from web.api.sentiment_api import router
        paths = [r.path for r in router.routes]
        assert any("asset" in p for p in paths), \
            f"No asset route found. Routes: {paths}"

    def test_all_asset_sentiments_route_registered(self):
        from web.api.sentiment_api import router
        paths = [r.path for r in router.routes]
        assert any("assets" in p or "all" in p for p in paths), \
            f"No all-assets route found. Routes: {paths}"


# ═══════════════════════════════════════════════════════════════════════════
# §9  get_hashtag_monitor singleton
# ═══════════════════════════════════════════════════════════════════════════

class TestGetHashtagMonitor:

    def test_returns_hashtag_monitor(self):
        m = get_hashtag_monitor()
        assert isinstance(m, HashtagMonitor)

    def test_singleton_same_instance(self):
        import merid.sentiment.hashtag_monitor as mod
        mod._monitor = None
        m1 = get_hashtag_monitor()
        m2 = get_hashtag_monitor()
        assert m1 is m2
