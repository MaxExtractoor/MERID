"""
Tests for KalshiInsightPipeline — market normalization, event detection, dispatch.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from merid.publishing.kalshi_insight_pipeline import (
    KalshiInsightPipeline,
    KalshiMarket,
    InsightObject,
    CATEGORY_CADENCE,
    PROB_CROSS_THRESHOLD,
    SWING_1H_THRESHOLD,
    MIN_VOLUME,
    CONFIDENCE_FLOOR,
)
from merid.event_venues.kalshi.market_filter import MarketFilter


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_raw_market(**kwargs) -> dict:
    base = {
        "ticker": "KXBTC-1H-T95000",
        "title": "Will BTC exceed $95k in the next hour?",
        "category": "crypto",
        "yes_bid": 55.0,
        "last_price": 56.0,
        "volume": 1200,
        "open_interest": 800,
        "close_time": "2026-02-20T00:00:00Z",
        "status": "open",
        "result": None,
    }
    base.update(kwargs)
    return base


def make_market(**kwargs) -> KalshiMarket:
    """Build a KalshiMarket with correct field names."""
    defaults = dict(
        ticker="KXBTC-001",
        question="Will BTC exceed $95k?",
        category="Crypto",
        yes_price=55.0,
        no_price=45.0,
        volume=1000,
        open_interest=500,
        end_date="2026-02-20T00:00:00Z",
        status="open",
        result=None,
    )
    defaults.update(kwargs)
    return KalshiMarket(**defaults)


def make_pipeline(**kwargs) -> KalshiInsightPipeline:
    p = KalshiInsightPipeline.__new__(KalshiInsightPipeline)
    p._running = False
    p._tasks = []
    p._consumers = []
    p._market_filter = MarketFilter()
    p._last_prob = {}
    p._last_post_ts = {}
    p._seen_tickers = set()
    p._recent_insights = []
    p._stats = {
        "total_emitted": 0,
        "by_category": {},
        "by_action": {},
        "errors": 0,
        "started_at": None,
        "filter_stats": {
            "total_filtered": 0,
            "total_passed": 0,
            "rejection_breakdown": {},
        },
    }
    for k, v in kwargs.items():
        setattr(p, k, v)
    return p


# ── normalize_market ──────────────────────────────────────────────────────────

class TestNormalizeMarket:
    def test_returns_kalshi_market(self):
        p = make_pipeline()
        raw = make_raw_market()
        m = p._normalize_market(raw)
        assert isinstance(m, KalshiMarket)

    def test_ticker_set(self):
        p = make_pipeline()
        m = p._normalize_market(make_raw_market(ticker="KXETH-15M-T3000"))
        assert m.ticker == "KXETH-15M-T3000"

    def test_probability_midpoint(self):
        p = make_pipeline()
        # yes_bid=55 → yes_price=55 → prob = 55/100 = 0.55
        m = p._normalize_market(make_raw_market(yes_bid=55.0))
        assert abs(m.prob - 0.55) < 0.001

    def test_probability_falls_back_to_last_price(self):
        p = make_pipeline()
        m = p._normalize_market(make_raw_market(yes_bid=None, last_price=42.0))
        assert abs(m.prob - 0.42) < 0.001

    def test_volume_set(self):
        p = make_pipeline()
        m = p._normalize_market(make_raw_market(volume=2500))
        assert m.volume == 2500

    def test_category_set(self):
        p = make_pipeline()
        m = p._normalize_market(make_raw_market(category="politics"))
        assert m.category == "Politics"

    def test_resolved_market_has_result(self):
        p = make_pipeline()
        m = p._normalize_market(make_raw_market(status="finalized", result="yes"))
        assert m.result == "yes"


# ── Event detection (via _process_market) ────────────────────────────────────

class TestEventDetection:
    @pytest.mark.asyncio
    async def test_new_market_detected(self):
        p = make_pipeline()
        received = []
        p._consumers = [received.append]
        market = make_market(ticker="KXNEW-001", category="Trending", volume=600)
        with patch.object(p, "_get_swarm_consensus", return_value=(0.50, 0.65)):
            await p._process_market(market)
        assert len(received) == 1
        assert received[0].action == "new_market"

    @pytest.mark.asyncio
    async def test_stable_seen_market_not_emitted(self):
        """Already-seen ticker with no prob delta and recent post → no emission."""
        p = make_pipeline()
        received = []
        p._consumers = [received.append]
        market = make_market(ticker="KXLOW-001", volume=MIN_VOLUME - 1)
        p._seen_tickers.add("KXLOW-001")
        p._last_prob["KXLOW-001"] = market.prob          # no delta
        p._last_post_ts["KXLOW-001"] = time.time()       # just posted → no periodic update
        with patch.object(p, "_get_swarm_consensus", return_value=(0.50, 0.65)):
            await p._process_market(market)
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_prob_cross_detected(self):
        p = make_pipeline()
        received = []
        p._consumers = [received.append]
        ticker = "KXBTC-001"
        prev_prob = 0.45
        # yes_price that gives prob = prev_prob + PROB_CROSS_THRESHOLD + 0.01
        new_prob = prev_prob + PROB_CROSS_THRESHOLD + 0.01
        p._seen_tickers.add(ticker)
        p._last_prob[ticker] = prev_prob
        market = make_market(ticker=ticker, yes_price=new_prob * 100)
        with patch.object(p, "_get_swarm_consensus", return_value=(new_prob, 0.70)):
            await p._process_market(market)
        assert len(received) == 1
        assert received[0].action == "prob_cross"

    @pytest.mark.asyncio
    async def test_swing_detected(self):
        p = make_pipeline()
        received = []
        p._consumers = [received.append]
        ticker = "KXBTC-002"
        prev_prob = 0.50
        new_prob = prev_prob + SWING_1H_THRESHOLD + 0.01
        p._seen_tickers.add(ticker)
        p._last_prob[ticker] = prev_prob
        p._last_post_ts[ticker] = time.time() - 100  # recent post → swing window active
        market = make_market(ticker=ticker, yes_price=new_prob * 100)
        with patch.object(p, "_get_swarm_consensus", return_value=(new_prob, 0.70)):
            await p._process_market(market)
        assert len(received) == 1
        assert received[0].action in ("swing", "prob_cross")

    @pytest.mark.asyncio
    async def test_resolution_detected(self):
        p = make_pipeline()
        received = []
        p._consumers = [received.append]
        ticker = "KXBTC-003"
        p._seen_tickers.add(ticker)
        p._last_prob[ticker] = 0.80
        market = make_market(ticker=ticker, yes_price=80.0, status="settled", result="yes")
        with patch.object(p, "_get_swarm_consensus", return_value=(0.80, 0.70)):
            await p._process_market(market)
        assert len(received) == 1
        assert received[0].action == "resolution"

    @pytest.mark.asyncio
    async def test_no_event_when_stable(self):
        p = make_pipeline()
        received = []
        p._consumers = [received.append]
        ticker = "KXBTC-004"
        p._seen_tickers.add(ticker)
        p._last_prob[ticker] = 0.50
        p._last_post_ts[ticker] = time.time()  # just posted → no periodic update
        market = make_market(ticker=ticker, yes_price=51.0)  # tiny 1pt move
        with patch.object(p, "_get_swarm_consensus", return_value=(0.51, 0.65)):
            await p._process_market(market)
        assert len(received) == 0


# ── InsightObject emission ────────────────────────────────────────────────────

def make_insight_obj(**kwargs) -> InsightObject:
    defaults = dict(
        source="kalshi", category="Crypto", ticker="KXBTC-001",
        question="BTC test", kalshi_prob=0.72, swarm_prob=0.70,
        swarm_confidence=0.65, change_24h=0.05,
        timestamp="2026-02-20T00:00:00Z",
        narrative="BTC rising",
        action="swing", market_url="https://kalshi.com/markets/KXBTC-001",
        volume=1500, open_interest=900, tags=["crypto", "btc"],
    )
    defaults.update(kwargs)
    return InsightObject(**defaults)


class TestInsightEmission:
    def test_emit_calls_sync_consumer(self):
        p = make_pipeline()
        received = []
        p._consumers = [received.append]
        insight = make_insight_obj()
        asyncio.get_event_loop().run_until_complete(p._dispatch(insight))
        assert len(received) == 1
        assert received[0].ticker == "KXBTC-001"

    @pytest.mark.asyncio
    async def test_emit_calls_async_consumer(self):
        p = make_pipeline()
        received = []

        async def async_consumer(obj):
            received.append(obj)

        p._consumers = [async_consumer]
        insight = make_insight_obj(ticker="KXBTC-002", action="update")
        await p._dispatch(insight)
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_emitted_count_increments(self):
        p = make_pipeline()
        market = make_market(ticker="KXTEST-001", category="Trending", volume=600)
        with patch.object(p, "_get_swarm_consensus", return_value=(0.50, 0.65)):
            await p._process_market(market)
        assert p._stats["total_emitted"] == 1


# ── Consumer registration ─────────────────────────────────────────────────────

class TestConsumerRegistration:
    def test_add_consumer(self):
        p = make_pipeline()
        cb = lambda x: x  # noqa: E731
        p.add_consumer(cb)
        assert cb in p._consumers


# ── Status dict ───────────────────────────────────────────────────────────────

class TestStatusDict:
    def test_status_includes_running(self):
        p = make_pipeline()
        p._running = True
        status = p.summary()
        assert status["running"] is True

    def test_status_includes_emitted_count(self):
        p = make_pipeline()
        p._stats["total_emitted"] = 7
        status = p.summary()
        assert status["total_emitted"] == 7

    def test_status_includes_error_count(self):
        p = make_pipeline()
        p._stats["errors"] = 2
        status = p.summary()
        assert status["errors"] == 2

    def test_status_includes_by_category(self):
        p = make_pipeline()
        p._stats["by_category"] = {"Crypto": 5, "Politics": 3}
        status = p.summary()
        assert status["by_category"]["Crypto"] == 5

    def test_status_includes_filter_stats(self):
        p = make_pipeline()
        p._stats["filter_stats"]["total_filtered"] = 100
        p._stats["filter_stats"]["total_passed"] = 25
        status = p.summary()
        assert status["filter_stats"]["total_filtered"] == 100
        assert status["filter_stats"]["total_passed"] == 25


# ── Market filtering ──────────────────────────────────────────────────────────

class TestMarketFiltering:
    def test_to_market_candidates_converts_markets(self):
        p = make_pipeline()
        markets = [
            make_market(ticker="KXBTC-1H-T95000", volume=1000, open_interest=500),
            make_market(ticker="KXETH-15M-T3000", volume=800, open_interest=300),
        ]
        candidates = p._to_market_candidates(markets)
        assert len(candidates) == 2
        assert candidates[0].ticker == "KXBTC-1H-T95000"
        assert candidates[0].underlying == "BTC"
        assert candidates[0].timeframe == "1h"
        assert candidates[1].underlying == "ETH"
        assert candidates[1].timeframe == "15m"

    def test_to_market_candidates_parses_timeframe_from_ticker(self):
        p = make_pipeline()
        test_cases = [
            ("KXBTC-15M-T95000", "15m"),
            ("KXBTC-1H-T95000", "1h"),
            ("KXBTC-D-T95000", "daily"),
            ("KXBTC-DAILY-T95000", "daily"),
            ("KXBTC-W-T95000", "weekly"),
            ("KXBTC-WEEKLY-T95000", "weekly"),
            ("KXBTC-M-T95000", "monthly"),
            ("KXBTC-MONTHLY-T95000", "monthly"),
            ("KXBTC-HOURLY-T95000", "1h"),
        ]
        for ticker, expected_timeframe in test_cases:
            market = make_market(ticker=ticker)
            candidates = p._to_market_candidates([market])
            assert candidates[0].timeframe == expected_timeframe, \
                f"Failed for ticker {ticker}: expected {expected_timeframe}, got {candidates[0].timeframe}"

    def test_to_market_candidates_parses_underlying_from_ticker(self):
        p = make_pipeline()
        test_cases = [
            ("KXBTC-1H-T95000", "BTC"),
            ("KXETH-1H-T3000", "ETH"),
            ("KXSOL-1H-T200", "SOL"),
            ("KXXRP-1H-T1", "XRP"),
            ("KXDOG-1H-T0", "DOGE"),  # DOG -> DOGE mapping
        ]
        for ticker, expected_underlying in test_cases:
            market = make_market(ticker=ticker)
            candidates = p._to_market_candidates([market])
            assert candidates[0].underlying == expected_underlying, \
                f"Failed for ticker {ticker}: expected {expected_underlying}, got {candidates[0].underlying}"

    def test_from_market_candidates_filters_markets(self):
        p = make_pipeline()
        markets = [
            make_market(ticker="KEEP-1", volume=1000),
            make_market(ticker="DROP-1", volume=500),
            make_market(ticker="KEEP-2", volume=800),
        ]
        from merid.event_venues.kalshi.market_filter import MarketCandidate
        # Only keep markets with "KEEP" in ticker
        kept_candidates = [
            MarketCandidate(
                ticker="KEEP-1", underlying="BTC", timeframe="1h",
                expiry_ts=0.0, volume=1000, open_interest=500,
                best_bid_cents=50, best_ask_cents=60, spread_cents=10,
                mid_price_cents=55, category="Crypto"
            ),
            MarketCandidate(
                ticker="KEEP-2", underlying="BTC", timeframe="1h",
                expiry_ts=0.0, volume=800, open_interest=400,
                best_bid_cents=50, best_ask_cents=60, spread_cents=10,
                mid_price_cents=55, category="Crypto"
            ),
        ]
        filtered = p._from_market_candidates(kept_candidates, markets)
        assert len(filtered) == 2
        assert all(m.ticker.startswith("KEEP") for m in filtered)


# ── Category cadence constants ────────────────────────────────────────────────

class TestCategoryConstants:
    def test_trending_has_shortest_cadence(self):
        assert CATEGORY_CADENCE["Trending"] <= min(
            v for k, v in CATEGORY_CADENCE.items() if k != "Trending"
        )

    def test_all_categories_have_cadence(self):
        expected = {"Trending", "Politics", "Sports", "Culture", "Crypto",
                    "Climate", "Economics", "Mentions", "Companies",
                    "Financials", "Tech & Science"}
        assert expected.issubset(set(CATEGORY_CADENCE.keys()))

    def test_confidence_floor_is_reasonable(self):
        assert 0.4 <= CONFIDENCE_FLOOR <= 0.8

    def test_prob_cross_threshold_is_reasonable(self):
        assert 0.05 <= PROB_CROSS_THRESHOLD <= 0.20
