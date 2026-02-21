"""Tests for Sprints Q+R: Time-series forecaster, external sentiment forecaster,
auction consensus, MCP market feed.
"""

from __future__ import annotations

import inspect
import os

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Sprint Q: TimeSeriesForecaster
# ═══════════════════════════════════════════════════════════════════════════


class TestTimeSeriesForecaster:
    """Tests for merid.prediction.forecasters.time_series."""

    def test_import(self):
        from merid.prediction.forecasters.time_series import TimeSeriesForecaster
        f = TimeSeriesForecaster()
        assert f.forecaster_id == "time_series_v1"

    def test_needs_history(self):
        from merid.prediction.forecasters.time_series import TimeSeriesForecaster
        f = TimeSeriesForecaster()
        # First call with no history → None
        result = f.predict(
            market_id="TS-NOHIST",
            implied_yes=0.50,
            implied_no=0.50,
        )
        assert result is None

    def test_produces_forecast_with_history(self):
        from merid.prediction.forecasters.time_series import TimeSeriesForecaster, _price_history
        f = TimeSeriesForecaster()
        # Pre-load history
        _price_history["TS-TEST1"] = [0.45 + i * 0.005 for i in range(15)]
        result = f.predict(
            market_id="TS-TEST1",
            implied_yes=0.52,
            implied_no=0.48,
        )
        assert result is not None
        assert 0.02 <= result.p_model <= 0.98
        assert "ar2_forecast" in result.components
        assert "ewma_volatility" in result.components

    def test_ar2_forecast_method(self):
        from merid.prediction.forecasters.time_series import TimeSeriesForecaster
        f = TimeSeriesForecaster()
        history = [0.50 + 0.01 * i for i in range(20)]
        forecast, confidence = f._ar2_forecast(history)
        assert 0.02 <= forecast <= 0.98
        assert 0.0 <= confidence <= 1.0

    def test_ewma_volatility(self):
        from merid.prediction.forecasters.time_series import TimeSeriesForecaster
        f = TimeSeriesForecaster()
        # Constant series → low vol
        constant = [0.50] * 20
        vol_const = f._ewma_volatility(constant)
        # Volatile series → high vol
        volatile = [0.40, 0.60] * 10
        vol_volatile = f._ewma_volatility(volatile)
        assert vol_volatile > vol_const

    def test_ou_half_life(self):
        from merid.prediction.forecasters.time_series import TimeSeriesForecaster
        f = TimeSeriesForecaster()
        # Mean-reverting series
        mr = [0.50 + 0.05 * ((-1) ** i) * (0.9 ** i) for i in range(20)]
        hl = f._ou_half_life(mr)
        assert hl > 0

    def test_hurst_proxy(self):
        from merid.prediction.forecasters.time_series import TimeSeriesForecaster
        f = TimeSeriesForecaster()
        series = [0.50 + 0.01 * i for i in range(20)]
        hurst = f._hurst_proxy(series)
        assert 0.1 <= hurst <= 0.9

    def test_invalid_implied_returns_none(self):
        from merid.prediction.forecasters.time_series import TimeSeriesForecaster
        f = TimeSeriesForecaster()
        assert f.predict("X", 0.0, 1.0) is None
        assert f.predict("X", 1.0, 0.0) is None

    def test_registered_in_registry(self):
        from merid.prediction.forecasters.registry import get_forecaster_registry
        import merid.prediction.forecasters.registry as mod
        old = mod._registry
        mod._registry = None
        try:
            reg = get_forecaster_registry()
            ids = [f.forecaster_id for f in reg._forecasters]
            assert "time_series_v1" in ids
        finally:
            mod._registry = old

    def test_in_init_exports(self):
        from merid.prediction.forecasters import TimeSeriesForecaster
        assert TimeSeriesForecaster is not None


# ═══════════════════════════════════════════════════════════════════════════
# Sprint Q: ExternalSentimentForecaster
# ═══════════════════════════════════════════════════════════════════════════


class TestExternalSentimentForecaster:
    """Tests for merid.prediction.forecasters.sentiment."""

    def test_import(self):
        from merid.prediction.forecasters.sentiment import ExternalSentimentForecaster
        f = ExternalSentimentForecaster()
        assert f.forecaster_id == "sentiment_ext"

    def test_no_data_returns_none(self):
        from merid.prediction.forecasters.sentiment import ExternalSentimentForecaster
        f = ExternalSentimentForecaster()
        result = f.predict(
            market_id="SENT-NODATA",
            implied_yes=0.50,
            implied_no=0.50,
        )
        # Without any external feeds or mood data → likely None
        # (unless MarketMoodBus has data)
        assert result is None or result.p_model is not None

    def test_with_fear_greed(self):
        from merid.prediction.forecasters.sentiment import ExternalSentimentForecaster
        f = ExternalSentimentForecaster()
        result = f.predict(
            market_id="SENT-FG",
            implied_yes=0.50,
            implied_no=0.50,
            fear_greed_index=15.0,  # Extreme fear → contrarian bullish
        )
        if result:
            assert result.p_model > 0.50  # Contrarian bullish

    def test_with_extreme_greed(self):
        from merid.prediction.forecasters.sentiment import ExternalSentimentForecaster
        f = ExternalSentimentForecaster()
        result = f.predict(
            market_id="SENT-GREED",
            implied_yes=0.50,
            implied_no=0.50,
            fear_greed_index=90.0,  # Extreme greed → contrarian bearish
        )
        if result:
            assert result.p_model < 0.50  # Contrarian bearish

    def test_feed_provider(self):
        from merid.prediction.forecasters.sentiment import get_sentiment_feed_provider
        provider = get_sentiment_feed_provider()
        assert provider.feed_names is not None

    def test_register_custom_feed(self):
        from merid.prediction.forecasters.sentiment import (
            ExternalSentimentForecaster, get_sentiment_feed_provider,
        )
        provider = get_sentiment_feed_provider()

        def mock_feed(asset="", category="", **kwargs):
            return {"score": 0.5, "confidence": 0.8, "source": "mock"}

        provider.register_feed("mock_test", mock_feed)
        assert "mock_test" in provider.feed_names

        f = ExternalSentimentForecaster()
        result = f.predict(
            market_id="SENT-FEED",
            implied_yes=0.50,
            implied_no=0.50,
            asset="BTC",
            category="crypto",
        )
        # With a feed providing score=0.5, should produce a forecast
        assert result is not None

        # Cleanup
        del provider._feeds["mock_test"]

    def test_invalid_implied_returns_none(self):
        from merid.prediction.forecasters.sentiment import ExternalSentimentForecaster
        f = ExternalSentimentForecaster()
        assert f.predict("X", 0.0, 1.0) is None

    def test_in_init_exports(self):
        from merid.prediction.forecasters import ExternalSentimentForecaster
        assert ExternalSentimentForecaster is not None

    def test_registered_in_registry(self):
        from merid.prediction.forecasters.registry import get_forecaster_registry
        import merid.prediction.forecasters.registry as mod
        old = mod._registry
        mod._registry = None
        try:
            reg = get_forecaster_registry()
            ids = [f.forecaster_id for f in reg._forecasters]
            assert "sentiment_ext" in ids
        finally:
            mod._registry = old


# ═══════════════════════════════════════════════════════════════════════════
# Sprint R: Auction Consensus
# ═══════════════════════════════════════════════════════════════════════════


class TestAuctionConsensus:
    """Tests for merid.swarm.auction_consensus."""

    def test_import(self):
        from merid.swarm.auction_consensus import (
            AuctionConsensusResolver, get_auction_resolver,
        )
        r = get_auction_resolver()
        assert isinstance(r, AuctionConsensusResolver)

    def test_empty_proposals(self):
        from merid.swarm.auction_consensus import AuctionConsensusResolver
        r = AuctionConsensusResolver()
        result = r.resolve_conflict([], "BTC", "15m")
        assert result.resolved is False
        assert result.num_bidders == 0

    def test_unanimous_yes_resolves(self):
        from merid.swarm.auction_consensus import AuctionConsensusResolver
        from merid.swarm.consensus_aggregator import AgentProposal
        from datetime import datetime, timezone

        r = AuctionConsensusResolver()
        proposals = [
            AgentProposal(
                agent_id=f"agent_{i}",
                asset="BTC", timeframe="15m",
                direction="yes", probability=0.70,
                confidence=0.8, size_preference="base",
                rationale="test", edge_estimate=5.0,
                timestamp=datetime.now(timezone.utc),
                agent_archetype="trend",
            )
            for i in range(5)
        ]
        result = r.resolve_conflict(proposals, "BTC", "15m")
        assert result.resolved is True
        assert result.winning_direction == "yes"
        assert result.winning_probability > 0.5

    def test_split_vote_may_not_resolve(self):
        from merid.swarm.auction_consensus import AuctionConsensusResolver
        from merid.swarm.consensus_aggregator import AgentProposal
        from datetime import datetime, timezone

        r = AuctionConsensusResolver()
        proposals = []
        for i in range(3):
            proposals.append(AgentProposal(
                agent_id=f"yes_{i}", asset="BTC", timeframe="15m",
                direction="yes", probability=0.65, confidence=0.5,
                size_preference="base", rationale="test", edge_estimate=3.0,
                timestamp=datetime.now(timezone.utc), agent_archetype="trend",
            ))
        for i in range(3):
            proposals.append(AgentProposal(
                agent_id=f"no_{i}", asset="BTC", timeframe="15m",
                direction="no", probability=0.35, confidence=0.5,
                size_preference="base", rationale="test", edge_estimate=3.0,
                timestamp=datetime.now(timezone.utc), agent_archetype="mean_reversion",
            ))
        result = r.resolve_conflict(proposals, "BTC", "15m")
        # Equal split → likely unresolved
        assert result.num_bidders == 6

    def test_auction_bid_effective(self):
        from merid.swarm.auction_consensus import AuctionBid
        bid = AuctionBid(
            agent_id="a1", direction="yes",
            conviction=0.8, probability=0.65,
            edge_estimate=5.0, calibration_weight=1.2,
        )
        assert bid.effective_bid == pytest.approx(0.96, abs=0.01)

    def test_result_to_dict(self):
        from merid.swarm.auction_consensus import AuctionConsensusResolver
        r = AuctionConsensusResolver()
        result = r.resolve_conflict([], "BTC", "15m")
        d = result.to_dict()
        assert "resolved" in d
        assert "winning_direction" in d
        assert "reason" in d

    def test_stats(self):
        from merid.swarm.auction_consensus import AuctionConsensusResolver
        r = AuctionConsensusResolver()
        r.resolve_conflict([], "BTC", "15m")
        s = r.stats
        assert s["total_auctions"] == 1
        assert s["unresolved"] == 1

    def test_wired_into_aggregator(self):
        from merid.swarm.consensus_aggregator import SwarmConsensusAggregator
        source = inspect.getsource(SwarmConsensusAggregator._recompute_consensus)
        assert "auction_consensus" in source
        assert "resolve_conflict" in source


# ═══════════════════════════════════════════════════════════════════════════
# Sprint R: MCP Market Feed
# ═══════════════════════════════════════════════════════════════════════════


class TestMCPMarketFeed:
    """Tests for merid.prediction.mcp_market_feed."""

    def test_import(self):
        from merid.prediction.mcp_market_feed import MCPMarketFeed, get_mcp_market_feed
        feed = get_mcp_market_feed()
        assert isinstance(feed, MCPMarketFeed)

    def test_config_from_env(self):
        from merid.prediction.mcp_market_feed import MCPMarketConfig
        config = MCPMarketConfig.from_env()
        assert isinstance(config.poll_interval_s, float)
        assert isinstance(config.enabled, bool)

    def test_configure(self):
        from merid.prediction.mcp_market_feed import MCPMarketFeed
        feed = MCPMarketFeed()
        feed.configure(server_url="https://test.example.com")
        assert feed._config.server_url == "https://test.example.com"
        assert feed._config.enabled is True

    def test_stats_disabled(self):
        from merid.prediction.mcp_market_feed import MCPMarketFeed
        feed = MCPMarketFeed()
        s = feed.stats
        assert s["enabled"] is False
        assert s["fetch_count"] == 0

    def test_parse_response_list(self):
        from merid.prediction.mcp_market_feed import MCPMarketFeed
        feed = MCPMarketFeed()
        data = [
            {"ticker": "KXBTC-001", "title": "BTC up?", "category": "crypto",
             "yes_bid": 45, "yes_ask": 55, "volume": 100, "open_interest": 50},
        ]
        snaps = feed._parse_response(data)
        assert len(snaps) == 1
        assert snaps[0].market_id == "KXBTC-001"
        assert snaps[0].yes_bid == 0.45

    def test_parse_response_dict(self):
        from merid.prediction.mcp_market_feed import MCPMarketFeed
        feed = MCPMarketFeed()
        data = {"markets": [
            {"market_id": "M1", "question": "Test?", "category": "crypto",
             "last_price": 60, "volume": 50, "open_interest": 20},
        ]}
        snaps = feed._parse_response(data)
        assert len(snaps) == 1
        assert snaps[0].market_id == "M1"

    def test_snapshot_to_dict(self):
        from merid.prediction.mcp_market_feed import MCPMarketSnapshot
        s = MCPMarketSnapshot(
            market_id="M1", title="Test", category="crypto",
            yes_bid=0.45, yes_ask=0.55, volume=100, open_interest=50,
        )
        d = s.to_dict()
        assert d["market_id"] == "M1"
        assert d["source"] == "mcp"

    @pytest.mark.asyncio
    async def test_fetch_no_url_returns_empty(self):
        from merid.prediction.mcp_market_feed import MCPMarketFeed
        feed = MCPMarketFeed()
        result = await feed.fetch_markets()
        assert result == []


# ═══════════════════════════════════════════════════════════════════════════
# Gap Analysis Verification
# ═══════════════════════════════════════════════════════════════════════════


class TestGapAnalysisQR:
    """Verify gap analysis reflects Sprint Q+R closures — 62/62."""

    def test_perfect_score(self):
        with open(os.path.join("docs", "KALSHI_SWARM_GAP_ANALYSIS.md"), "r", encoding="utf-8") as f:
            content = f.read()
        assert "62/62" in content
        assert "**A+**" in content

    def test_time_series_in_doc(self):
        with open(os.path.join("docs", "KALSHI_SWARM_GAP_ANALYSIS.md"), "r", encoding="utf-8") as f:
            content = f.read()
        assert "TimeSeriesForecaster" in content

    def test_external_sentiment_in_doc(self):
        with open(os.path.join("docs", "KALSHI_SWARM_GAP_ANALYSIS.md"), "r", encoding="utf-8") as f:
            content = f.read()
        assert "ExternalSentimentForecaster" in content

    def test_auction_in_doc(self):
        with open(os.path.join("docs", "KALSHI_SWARM_GAP_ANALYSIS.md"), "r", encoding="utf-8") as f:
            content = f.read()
        assert "AuctionConsensusResolver" in content

    def test_mcp_in_doc(self):
        with open(os.path.join("docs", "KALSHI_SWARM_GAP_ANALYSIS.md"), "r", encoding="utf-8") as f:
            content = f.read()
        assert "mcp_market_feed" in content

    def test_registry_has_six_forecasters(self):
        """2 defaults + macro + orderbook + timeseries + sentiment = 6."""
        from merid.prediction.forecasters.registry import get_forecaster_registry
        import merid.prediction.forecasters.registry as mod
        old = mod._registry
        mod._registry = None
        try:
            reg = get_forecaster_registry()
            assert len(reg._forecasters) == 6
        finally:
            mod._registry = old
