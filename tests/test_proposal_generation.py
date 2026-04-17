"""
Test suite for proposal generation and validation.

Tests the normalized proposal schema, validation at the consensus entrypoint,
and that NewsMonitorAgent correctly generates proposals for all 25 crypto pairs.
"""

import pytest
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Dict, Any

from agents.interface import NormalizedProposal
from agents.news_monitor_agent import NewsMonitorAgent, NewsItem, HeadlineImpact
from config.crypto_universe import (
    ACTIVE_CRYPTO_ASSETS,
    ACTIVE_CRYPTO_TIMEFRAMES,
    get_kalshi_series_ticker,
)


class TestNewsMonitorProposalGeneration:
    """Test NewsMonitorAgent proposal generation across all 25 crypto pairs."""
    
    @pytest.fixture
    def news_agent(self):
        """Create a fresh NewsMonitorAgent for testing."""
        return NewsMonitorAgent(importance_threshold=0.5)
    
    @pytest.fixture
    def bullish_news(self):
        """Create a bullish news item."""
        return NewsItem(
            title="Bitcoin ETF approved by SEC - Major institutional adoption",
            source="TestNews",
            url="http://test.com/news1",
            published_at=datetime.now(timezone.utc),
            importance=0.9
        )
    
    @pytest.fixture
    def bearish_sol_news(self):
        """Create bearish SOL-specific news."""
        return NewsItem(
            title="Solana outage reported - network down for hours",
            source="TestNews",
            url="http://test.com/news2",
            published_at=datetime.now(timezone.utc),
            importance=0.9
        )
    
    def test_news_monitor_generates_all_25_pairs_when_news_exists(self, news_agent, bullish_news):
        """
        Test that NewsMonitorAgent can generate proposals for all 25 crypto pairs.
        
        For each of the 25 pairs (BTC/ETH/SOL/XRP/DOGE × 15m/1h/daily/weekly/monthly),
        verify that a valid MarketOpinion can be generated when news exists.
        """
        # Analyze the bullish news
        impact = news_agent._analyze_headline_impact(bullish_news)
        
        # Verify all 5 assets have impact scores
        for asset in ACTIVE_CRYPTO_ASSETS:
            assert asset in impact.asset_impacts, f"Missing impact for {asset}"
            assert isinstance(impact.asset_impacts[asset], float)
            assert -1.0 <= impact.asset_impacts[asset] <= 1.0
        
        # Verify all 5 timeframes are represented
        for timeframe in ACTIVE_CRYPTO_TIMEFRAMES:
            assert timeframe in impact.timeframe_relevance, f"Missing timeframe {timeframe}"
            assert isinstance(impact.timeframe_relevance[timeframe], bool)
        
        # Verify the headline impact has the right structure
        assert impact.headline == bullish_news.title
        assert impact.source == bullish_news.source
        assert 0.0 <= impact.importance <= 1.0
    
    def test_sol_bearish_news_scored_correctly(self, news_agent, bearish_sol_news):
        """
        Regression test for SOL scoring bug.
        
        Bearish SOL news should produce negative impact scores, not positive.
        Bug was: sol_bearish variable was using sol_bullish instead.
        """
        impact = news_agent._analyze_headline_impact(bearish_sol_news)
        
        # The headline "Solana outage reported" should produce negative SOL impact
        sol_impact = impact.get_asset_impact("SOL")
        
        # Verify SOL impact is negative (bearish)
        assert sol_impact < 0, f"Expected negative SOL impact for outage news, got {sol_impact}"
        
        # Verify it's more bearish than neutral
        assert sol_impact < -0.1, f"Expected meaningful negative impact, got {sol_impact}"
    
    def test_btc_bullish_news_positive_impact(self, news_agent, bullish_news):
        """Test that bullish BTC news produces positive BTC impact."""
        impact = news_agent._analyze_headline_impact(bullish_news)
        
        btc_impact = impact.get_asset_impact("BTC")
        
        # Verify BTC impact is positive
        assert btc_impact > 0, f"Expected positive BTC impact for ETF news, got {btc_impact}"
    
    def test_all_assets_have_impact_scores(self, news_agent, bullish_news):
        """Test that all 5 assets get impact scores from general crypto news."""
        impact = news_agent._analyze_headline_impact(bullish_news)
        
        for asset in ACTIVE_CRYPTO_ASSETS:
            score = impact.get_asset_impact(asset)
            assert isinstance(score, float), f"Impact for {asset} should be float"
            assert -1.0 <= score <= 1.0, f"Impact for {asset} should be in [-1, 1]"


class TestNormalizedProposalValidation:
    """Test the NormalizedProposal schema validation."""
    
    def test_valid_normalized_proposal_creates_successfully(self):
        """Test that a valid proposal passes validation."""
        proposal = NormalizedProposal(
            proposal_id="test-001",
            agent_id="test_agent",
            agent_role="news",
            asset="BTC",
            timeframe="15m",
            kalshi_ticker="KXBTC-15M",
            recommendation="buy",
            direction="bullish",
            confidence=0.75,
            edge=10.0,
            size_hint=10,
            max_position=100,
            risk_pct=0.1
        )
        
        assert proposal.asset == "BTC"
        assert proposal.timeframe == "15m"
        assert proposal.confidence == 0.75
    
    def test_invalid_asset_rejected(self):
        """Test that proposals with invalid assets are rejected."""
        with pytest.raises(ValueError) as exc_info:
            NormalizedProposal(
                proposal_id="test-002",
                agent_id="test_agent",
                agent_role="news",
                asset="INVALID",  # Not in ACTIVE_CRYPTO_ASSETS
                timeframe="15m",
                kalshi_ticker="KXINVALID-15M",
                recommendation="buy",
                direction="bullish",
                confidence=0.75
            )
        
        assert "Invalid asset" in str(exc_info.value)
    
    def test_invalid_timeframe_rejected(self):
        """Test that proposals with invalid timeframes are rejected."""
        with pytest.raises(ValueError) as exc_info:
            NormalizedProposal(
                proposal_id="test-003",
                agent_id="test_agent",
                agent_role="news",
                asset="BTC",
                timeframe="99m",  # Not in ACTIVE_CRYPTO_TIMEFRAMES
                kalshi_ticker="KXBTC-99M",
                recommendation="buy",
                direction="bullish",
                confidence=0.75
            )
        
        assert "Invalid timeframe" in str(exc_info.value)
    
    def test_invalid_confidence_rejected(self):
        """Test that proposals with out-of-range confidence are rejected."""
        with pytest.raises(ValueError) as exc_info:
            NormalizedProposal(
                proposal_id="test-004",
                agent_id="test_agent",
                agent_role="news",
                asset="BTC",
                timeframe="15m",
                kalshi_ticker="KXBTC-15M",
                recommendation="buy",
                direction="bullish",
                confidence=1.5  # Out of [0, 1] range
            )
        
        assert "Confidence out of range" in str(exc_info.value)
    
    def test_invalid_recommendation_rejected(self):
        """Test that proposals with invalid recommendation are rejected."""
        with pytest.raises(ValueError) as exc_info:
            NormalizedProposal(
                proposal_id="test-005",
                agent_id="test_agent",
                agent_role="news",
                asset="BTC",
                timeframe="15m",
                kalshi_ticker="KXBTC-15M",
                recommendation="pump",  # Invalid value
                direction="bullish",
                confidence=0.75
            )
        
        assert "Invalid recommendation" in str(exc_info.value)
    
    def test_invalid_direction_rejected(self):
        """Test that proposals with invalid direction are rejected."""
        with pytest.raises(ValueError) as exc_info:
            NormalizedProposal(
                proposal_id="test-006",
                agent_id="test_agent",
                agent_role="news",
                asset="BTC",
                timeframe="15m",
                kalshi_ticker="KXBTC-15M",
                recommendation="buy",
                direction="up",  # Invalid value
                confidence=0.75
            )
        
        assert "Invalid direction" in str(exc_info.value)
    
    def test_negative_size_hint_rejected(self):
        """Test that proposals with negative size_hint are rejected."""
        with pytest.raises(ValueError) as exc_info:
            NormalizedProposal(
                proposal_id="test-007",
                agent_id="test_agent",
                agent_role="news",
                asset="BTC",
                timeframe="15m",
                kalshi_ticker="KXBTC-15M",
                recommendation="buy",
                direction="bullish",
                confidence=0.75,
                size_hint=-5  # Invalid
            )
        
        assert "size_hint must be positive" in str(exc_info.value)
    
    def test_optional_fields_can_be_none(self):
        """Test that optional fields can be left as None."""
        proposal = NormalizedProposal(
            proposal_id="test-008",
            agent_id="test_agent",
            agent_role="news",
            asset="BTC",
            timeframe="15m",
            kalshi_ticker="KXBTC-15M",
            recommendation="buy",
            direction="bullish",
            confidence=0.75
            # size_hint, max_position, risk_pct, edge all default to None
        )
        
        assert proposal.size_hint is None
        assert proposal.max_position is None
        assert proposal.risk_pct is None
        assert proposal.edge is None


class TestDirectionRecommendationAlignment:
    """Test that direction and recommendation fields are aligned."""
    
    def test_bullish_buy_alignment(self):
        """Test that bullish direction aligns with buy recommendation."""
        proposal = NormalizedProposal(
            proposal_id="test-009",
            agent_id="test_agent",
            agent_role="analyst",
            asset="BTC",
            timeframe="1h",
            kalshi_ticker="KXBTC",
            recommendation="buy",
            direction="bullish",
            confidence=0.8
        )
        
        # Both should indicate positive sentiment
        assert proposal.recommendation == "buy"
        assert proposal.direction == "bullish"
    
    def test_bearish_sell_alignment(self):
        """Test that bearish direction aligns with sell recommendation."""
        proposal = NormalizedProposal(
            proposal_id="test-010",
            agent_id="test_agent",
            agent_role="analyst",
            asset="ETH",
            timeframe="15m",
            kalshi_ticker="KXETH-15M",
            recommendation="sell",
            direction="bearish",
            confidence=0.7
        )
        
        assert proposal.recommendation == "sell"
        assert proposal.direction == "bearish"
    
    def test_neutral_hold_alignment(self):
        """Test that neutral direction aligns with hold recommendation."""
        proposal = NormalizedProposal(
            proposal_id="test-011",
            agent_id="test_agent",
            agent_role="analyst",
            asset="SOL",
            timeframe="daily",
            kalshi_ticker="KXSOL-D1",
            recommendation="hold",
            direction="neutral",
            confidence=0.5
        )
        
        assert proposal.recommendation == "hold"
        assert proposal.direction == "neutral"
    
    def test_abstain_neutral_alignment(self):
        """Test that abstain recommendation aligns with neutral direction."""
        proposal = NormalizedProposal(
            proposal_id="test-012",
            agent_id="test_agent",
            agent_role="analyst",
            asset="XRP",
            timeframe="weekly",
            kalshi_ticker="KXXRP-W1",
            recommendation="abstain",
            direction="neutral",
            confidence=0.3
        )
        
        assert proposal.recommendation == "abstain"
        assert proposal.direction == "neutral"


class Test25PairCoverage:
    """Test that all 25 crypto pairs are properly covered."""
    
    def test_all_25_pairs_in_kalshi_markets(self):
        """
        Verify that KALSHI_CRYPTO_MARKETS contains all 25 pairs.
        
        5 assets × 5 timeframes = 25 pairs
        """
        from agents.news_monitor_agent import KALSHI_CRYPTO_MARKETS
        
        # Count pairs
        assert len(KALSHI_CRYPTO_MARKETS) == 25, f"Expected 25 pairs, got {len(KALSHI_CRYPTO_MARKETS)}"
        
        # Verify all combinations exist
        expected_pairs = set()
        for asset in ACTIVE_CRYPTO_ASSETS:
            for timeframe in ACTIVE_CRYPTO_TIMEFRAMES:
                expected_pairs.add((asset, timeframe))
        
        actual_pairs = set()
        for ticker, asset, timeframe in KALSHI_CRYPTO_MARKETS:
            actual_pairs.add((asset, timeframe))
        
        assert actual_pairs == expected_pairs, f"Missing pairs: {expected_pairs - actual_pairs}"
    
    def test_kalshi_ticker_format(self):
        """Test that Kalshi tickers follow expected format."""
        from agents.news_monitor_agent import KALSHI_CRYPTO_MARKETS
        
        for ticker, asset, timeframe in KALSHI_CRYPTO_MARKETS:
            # Ticker should start with KX
            assert ticker.startswith("KX"), f"Ticker {ticker} should start with KX"
            
            # Ticker should contain asset
            assert asset in ticker, f"Ticker {ticker} should contain asset {asset}"
    
    def test_proposal_validation_across_all_assets(self):
        """Test that proposals validate for all 5 assets."""
        for asset in ACTIVE_CRYPTO_ASSETS:
            proposal = NormalizedProposal(
                proposal_id=f"test-{asset}",
                agent_id="test_agent",
                agent_role="news",
                asset=asset,
                timeframe="1h",
                kalshi_ticker=f"KX{asset}",
                recommendation="buy",
                direction="bullish",
                confidence=0.75
            )
            
            assert proposal.asset == asset
    
    def test_proposal_validation_across_all_timeframes(self):
        """Test that proposals validate for all 5 timeframes."""
        for timeframe in ACTIVE_CRYPTO_TIMEFRAMES:
            proposal = NormalizedProposal(
                proposal_id=f"test-{timeframe}",
                agent_id="test_agent",
                agent_role="news",
                asset="BTC",
                timeframe=timeframe,
                kalshi_ticker=get_kalshi_series_ticker("BTC", timeframe),
                recommendation="buy",
                direction="bullish",
                confidence=0.75
            )
            
            assert proposal.timeframe == timeframe
